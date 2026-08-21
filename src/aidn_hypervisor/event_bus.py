"""Canonical, in-process event bus for the RFC-0072 control plane.

The bus is intentionally smaller than the durable Event Store described by
RFC-0072.  It gives every local producer one normalisation boundary today:
events receive stable identity, ordering, correlation, redaction, and a
content hash before the RFC-0072 Hook dispatcher consumes them.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field


class EventSeverity(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    NOTICE = "NOTICE"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventDataClass(StrEnum):
    PUBLIC = "PUBLIC"
    OPERATOR = "OPERATOR"
    SENSITIVE = "SENSITIVE"
    FINANCIAL = "FINANCIAL"
    SECURITY = "SECURITY"
    SECRET = "SECRET"


class CanonicalEventEnvelope(BaseModel):
    """The externally consumable event shape defined by RFC-0072 section 6."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    event_version: int = Field(default=1, ge=1)
    hypervisor_id: str = Field(min_length=1)
    network_id: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    source: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    resource_id: str | None = None
    resource_revision: str | None = None
    severity: EventSeverity
    data_class: EventDataClass
    correlation_id: str | None = None
    causation_id: str | None = None
    requires_attention: bool = False
    requires_action: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)
    event_hash: str = Field(min_length=1)


EventSubscriber = Callable[[CanonicalEventEnvelope], None]


_SECRET_FIELD_NAMES = {
    "access_token",
    "api_key",
    "authorization",
    "credential",
    "credentials",
    "mnemonic",
    "password",
    "private_key",
    "secret",
    "seed",
    "signing_key",
    "token",
}

_CRITICAL_WORDS = {"critical", "apphash_mismatch", "signing_failure"}
_ERROR_WORDS = {"failed", "failure", "error", "crash", "unhealthy", "rejected"}
_WARNING_WORDS = {"denied", "degraded", "expired", "pressure", "stalled", "waiting"}
_ACTION_WORDS = {"required", "failed", "denied", "expired", "waiting", "pressure"}


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _redact(value: Any, *, secret_event: bool = False) -> Any:
    """Return a JSON-safe copy with secret-looking fields removed.

    A SECRET event is still useful inside the bus for policy accounting, but
    its ordinary payload must not carry secret material.  For other classes,
    well-known credential keys are replaced recursively while unrelated
    provider diagnostics remain intact.
    """

    if secret_event:
        return {"redacted": True}
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            result[str(key)] = (
                "[REDACTED]"
                if normalized_key in _SECRET_FIELD_NAMES
                else _redact(item)
            )
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _event_words(event_type: str) -> set[str]:
    return {part for part in event_type.lower().replace("-", "_").split(".") if part}


def _infer_severity(event_type: str) -> EventSeverity:
    words = _event_words(event_type)
    if words & _CRITICAL_WORDS:
        return EventSeverity.CRITICAL
    if words & _ERROR_WORDS:
        return EventSeverity.ERROR
    if words & _WARNING_WORDS:
        return EventSeverity.WARNING
    if words & {"debug"}:
        return EventSeverity.DEBUG
    if words & {"notice"}:
        return EventSeverity.NOTICE
    return EventSeverity.INFO


def _infer_data_class(event_type: str, payload: dict[str, Any]) -> EventDataClass:
    words = _event_words(event_type)
    if words & {"security", "auth", "authentication", "permission"}:
        return EventDataClass.SECURITY
    if words & {"wallet", "budget", "settlement", "payment", "faucet", "economics"}:
        return EventDataClass.FINANCIAL
    if words & {"secret", "credential"} or any(
        str(key).lower().replace("-", "_") in _SECRET_FIELD_NAMES for key in payload
    ):
        return EventDataClass.SECRET
    if words & {"network", "endpoint", "provider", "model", "bundle", "runtime", "node"}:
        return EventDataClass.OPERATOR
    return EventDataClass.OPERATOR


def _infer_resource(
    *,
    event_type: str,
    task_id: str | None,
    bundle_id: str | None,
    runtime_id: str | None,
    payload: dict[str, Any],
) -> tuple[str, str | None]:
    candidates = (
        ("runtime", runtime_id),
        ("bundle", bundle_id),
        ("task", task_id),
        ("provider", payload.get("provider_instance_id")),
        ("model", payload.get("model_id") or payload.get("model_deployment_id")),
        ("endpoint", payload.get("endpoint_id")),
        ("session", payload.get("session_id")),
        ("allocation", payload.get("allocation_id")),
        ("job", payload.get("job_id")),
    )
    for resource_type, resource_id in candidates:
        if resource_id is not None:
            return resource_type, str(resource_id)
    prefix = event_type.split(".", 2)[1] if "." in event_type else event_type
    resource_type = {
        "admission": "resource",
        "budget": "budget",
        "network": "network",
        "provider": "provider",
        "validation": "validation",
        "wallet": "wallet",
    }.get(prefix, prefix or "unknown")
    return resource_type, None


class CanonicalEventNormalizer:
    """Convert legacy journal arguments into an RFC-0072 envelope."""

    def __init__(self, *, hypervisor_id: str, network_id: str) -> None:
        self.hypervisor_id = str(hypervisor_id or "node-local")
        self.network_id = str(network_id or "local")

    def normalize(
        self,
        *,
        sequence: int,
        event_type: str,
        message: str,
        task_id: str | None = None,
        bundle_id: str | None = None,
        runtime_id: str | None = None,
        details: dict[str, Any] | None = None,
        source: str | None = None,
        severity: EventSeverity | str | None = None,
        data_class: EventDataClass | str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        resource_revision: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        requires_attention: bool | None = None,
        requires_action: bool | None = None,
    ) -> CanonicalEventEnvelope:
        raw_payload: dict[str, Any] = {"message": str(message)}
        raw_payload.update(dict(details or {}))
        resolved_severity = (
            EventSeverity(str(severity).upper())
            if severity is not None
            else _infer_severity(event_type)
        )
        resolved_data_class = (
            EventDataClass(str(data_class).upper())
            if data_class is not None
            else _infer_data_class(event_type, raw_payload)
        )
        sanitized_payload = _redact(raw_payload, secret_event=resolved_data_class is EventDataClass.SECRET)
        resolved_resource_type, inferred_resource_id = _infer_resource(
            event_type=event_type,
            task_id=task_id,
            bundle_id=bundle_id,
            runtime_id=runtime_id,
            payload=raw_payload,
        )
        resolved_resource_id = resource_id or inferred_resource_id
        timestamp = datetime.now(UTC).isoformat()
        words = _event_words(event_type)
        attention = (
            bool(requires_attention)
            if requires_attention is not None
            else resolved_severity in {EventSeverity.WARNING, EventSeverity.ERROR, EventSeverity.CRITICAL}
        )
        action = (
            bool(requires_action)
            if requires_action is not None
            else bool(words & _ACTION_WORDS)
        )
        identity_material = f"{self.hypervisor_id}:{sequence}:{event_type}:{timestamp}"
        event_id = f"evt_{hashlib.sha256(identity_material.encode('utf-8')).hexdigest()}"
        raw_revision = (
            resource_revision
            or raw_payload.get("resource_revision")
            or raw_payload.get("revision")
        )
        unsigned = {
            "event_id": event_id,
            "event_type": event_type,
            "event_version": 1,
            "hypervisor_id": self.hypervisor_id,
            "network_id": self.network_id,
            "timestamp": timestamp,
            "sequence": sequence,
            "source": str(source or event_type.split(".", 1)[0] or "hypervisor"),
            "resource_type": str(resource_type or resolved_resource_type),
            "resource_id": resolved_resource_id,
            "resource_revision": str(raw_revision) if raw_revision is not None else None,
            "severity": resolved_severity.value,
            "data_class": resolved_data_class.value,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "requires_attention": attention,
            "requires_action": action,
            "payload": sanitized_payload,
        }
        return CanonicalEventEnvelope(**unsigned, event_hash=f"sha256:{_hash(unsigned)}")


class InternalEventBus:
    """Thread-safe local bus with ordered, normalised event publication."""

    def __init__(
        self,
        *,
        hypervisor_id: str,
        network_id: str = "local",
        initial_sequence: int = 0,
    ) -> None:
        self._normalizer = CanonicalEventNormalizer(
            hypervisor_id=hypervisor_id,
            network_id=network_id,
        )
        self._sequence = max(0, int(initial_sequence))
        self._events: list[CanonicalEventEnvelope] = []
        self._subscribers: dict[str, EventSubscriber] = {}
        self._lock = RLock()

    @property
    def last_sequence(self) -> int:
        with self._lock:
            return self._sequence

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def subscribe(self, subscriber: EventSubscriber, *, subscription_id: str | None = None) -> str:
        with self._lock:
            key = subscription_id
            if key is None:
                # Allocate the generated id while holding the same lock as
                # publication and removal.  Otherwise two concurrent
                # producers could receive the same default subscription id.
                ordinal = len(self._subscribers) + 1
                key = f"sub_{ordinal}"
                while key in self._subscribers:
                    ordinal += 1
                    key = f"sub_{ordinal}"
            self._subscribers[key] = subscriber
        return key

    def unsubscribe(self, subscription_id: str) -> bool:
        with self._lock:
            return self._subscribers.pop(subscription_id, None) is not None

    def restore_sequence(self, sequence: int) -> None:
        with self._lock:
            self._sequence = max(self._sequence, int(sequence))

    def publish(self, **kwargs: Any) -> CanonicalEventEnvelope:
        with self._lock:
            self._sequence += 1
            event = self._normalizer.normalize(sequence=self._sequence, **kwargs)
            self._events.append(event)
            subscribers = list(self._subscribers.values())
        for subscriber in subscribers:
            try:
                subscriber(event)
            except Exception:
                # A Hook delivery failure is recorded by the dispatcher; a
                # local observer must never break the authoritative producer.
                continue
        return event

    def events(self, *, limit: int | None = None) -> list[CanonicalEventEnvelope]:
        with self._lock:
            events = list(self._events)
        if limit is None or limit >= len(events):
            return events
        normalized_limit = int(limit)
        if normalized_limit <= 0:
            return []
        return events[-normalized_limit:]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def prune(self, *, max_events: int) -> None:
        """Retain only the newest bounded window without changing sequence."""

        bounded_limit = max(1, int(max_events))
        with self._lock:
            if len(self._events) > bounded_limit:
                del self._events[:-bounded_limit]

    def restore_events(
        self,
        events: list[CanonicalEventEnvelope],
        *,
        sequence: int = 0,
    ) -> None:
        """Restore retained events and a sequence lower bound atomically."""

        with self._lock:
            self._events = [event.model_copy(deep=True) for event in events]
            latest = max((event.sequence for event in self._events), default=0)
            self._sequence = max(self._sequence, int(sequence), latest)
