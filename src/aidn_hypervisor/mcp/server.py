"""MCP control plane for an AiDN Hypervisor.

The first implementation deliberately uses only the MCP JSON-RPC data layer
and the stdio transport.  It is a local operator sidecar boundary: the
Hypervisor remains the source of truth and this module never receives wallet
private keys or executes arbitrary shell commands.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, TextIO

from aidn_hypervisor.bundle_hash import bundle_config_hash
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationReadinessError
from aidn_hypervisor.endpoints.endpoint_application_service import EndpointApplicationService
from aidn_hypervisor.mcp.persistence import (
    McpPersistenceError,
    McpPersistentStateStore,
)
from aidn_hypervisor.operator_views import (
    build_operator_bundles_payload,
    build_operator_endpoints_payload,
    build_operator_providers_payload,
)
from aidn_hypervisor.runtime_operations_read_models import (
    build_runtime_operations_payload,
)

MCP_PROTOCOL_VERSION = "2025-06-18"
# Hermes Agent 0.20.x sends the 2025-11-25 handshake even when its
# mcp_servers config contains an older protocol_version hint. The AiDN
# control plane does not use any 2025-11-25-only features yet, so accepting
# that negotiated version keeps the JSON-RPC boundary interoperable while
# preserving the older client versions already in the field.
SUPPORTED_MCP_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
MCP_SERVER_VERSION = "0.2.0"
DEFAULT_CONTROL_SESSION_TTL_SECONDS = 3600
MIN_CONTROL_SESSION_TTL_SECONDS = 60


def load_operator_config() -> None:
    """Load optional operator config when this checkout provides the module."""

    try:
        module = import_module("aidn_hypervisor.config")
    except ImportError:  # pragma: no cover - compatibility with older node checkouts
        return
    loader = getattr(module, "load_operator_config", None)
    if callable(loader):
        loader()

JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _hash_payload(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _tool_catalog_revision(definitions: list[dict[str, Any]]) -> str:
    """Return a stable revision for the effective, scope-filtered tool list."""

    return _hash_payload(definitions)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise McpPersistenceError("MCP_INTERNAL_ERROR", f"Persisted {field_name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise McpPersistenceError("MCP_INTERNAL_ERROR", f"Persisted {field_name} is invalid") from error
    if parsed.tzinfo is None:
        raise McpPersistenceError("MCP_INTERNAL_ERROR", f"Persisted {field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _is_additive_read_scope(scope: str) -> bool:
    """Return whether a newly introduced scope is safe to migrate automatically.

    Read-only catalog additions do not grant mutation authority, so an older
    persisted control session can adopt them during a normal process restart.
    Write scopes remain an explicit re-pair/re-authorization boundary.
    """

    return scope.count(":") == 1 and scope.endswith(":READ")


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _json_safe(value: Any) -> Any:
    """Convert project models and runtime handles to MCP JSON values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump(mode="json"))
    if hasattr(value, "__dict__"):
        return _json_safe(vars(value))
    return str(value)


class McpDomainError(Exception):
    """A stable MCP domain error returned inside a tool result."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}

    def as_dict(self, *, audit_event_id: str | None = None) -> dict[str, Any]:
        payload = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": _json_safe(self.details),
        }
        if audit_event_id is not None:
            payload["audit_event_id"] = audit_event_id
        return payload


@dataclass
class DelegatedBudget:
    """A bounded budget view; Q spending is not implemented by this slice."""

    budget_id: str
    max_total_atoms: int
    max_per_operation_atoms: int
    remaining_atoms: int
    reserved_atoms: int = 0
    spent_atoms: int = 0
    allowed_purposes: tuple[str, ...] = ()
    allowed_endpoint_selectors: tuple[str, ...] = ()
    expires_at: datetime | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "budget_id": self.budget_id,
            "max_total_atoms": self.max_total_atoms,
            "max_per_operation_atoms": self.max_per_operation_atoms,
            "remaining_atoms": self.remaining_atoms,
            "reserved_atoms": self.reserved_atoms,
            "spent_atoms": self.spent_atoms,
            "allowed_purposes": list(self.allowed_purposes),
            "allowed_endpoint_selectors": list(self.allowed_endpoint_selectors),
            "expires_at": _iso(self.expires_at) if self.expires_at else None,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> DelegatedBudget:
        if not isinstance(record, Mapping):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP budget is invalid")

        def integer(name: str) -> int:
            value = record.get(name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise McpPersistenceError("MCP_INTERNAL_ERROR", f"Persisted MCP budget field is invalid: {name}")
            return value

        def strings(name: str) -> tuple[str, ...]:
            value = record.get(name, [])
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise McpPersistenceError("MCP_INTERNAL_ERROR", f"Persisted MCP budget field is invalid: {name}")
            return tuple(value)

        expires_at = record.get("expires_at")
        return cls(
            budget_id=str(record.get("budget_id", "")),
            max_total_atoms=integer("max_total_atoms"),
            max_per_operation_atoms=integer("max_per_operation_atoms"),
            remaining_atoms=integer("remaining_atoms"),
            reserved_atoms=integer("reserved_atoms"),
            spent_atoms=integer("spent_atoms"),
            allowed_purposes=strings("allowed_purposes"),
            allowed_endpoint_selectors=strings("allowed_endpoint_selectors"),
            expires_at=_parse_datetime(expires_at, "budget.expires_at") if expires_at is not None else None,
        )

    def public(self) -> dict[str, Any]:
        return self.to_record()


@dataclass
class ControlSession:
    """Authority context attached to one MCP connection."""

    control_session_id: str
    agent_identity: str
    operator_identity: str
    scopes: frozenset[str]
    # ``None`` is the explicit stateless mode.  The remote gateway still
    # authenticates every request with a revocable bearer credential; this
    # field only controls the optional server-side lease.
    expires_at: datetime | None
    created_at: datetime = field(default_factory=_now)
    budget: DelegatedBudget | None = None
    approval_policy: dict[str, str] = field(default_factory=dict)
    approved_plan_hashes: frozenset[str] = frozenset()

    def to_record(self) -> dict[str, Any]:
        return {
            "control_session_id": self.control_session_id,
            "agent_identity": self.agent_identity,
            "operator_identity": self.operator_identity,
            "scopes": sorted(self.scopes),
            "created_at": _iso(self.created_at),
            "expires_at": _iso(self.expires_at) if self.expires_at else None,
            "budget": self.budget.to_record() if self.budget else None,
            "approval_policy": dict(self.approval_policy),
            "approved_plan_hashes": sorted(self.approved_plan_hashes),
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> ControlSession:
        if not isinstance(record, Mapping):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP Control Session is invalid")

        def required_string(name: str) -> str:
            value = record.get(name)
            if not isinstance(value, str) or not value:
                raise McpPersistenceError("MCP_INTERNAL_ERROR", f"Persisted MCP session field is invalid: {name}")
            return value

        scopes = record.get("scopes", [])
        if not isinstance(scopes, list) or not all(isinstance(item, str) for item in scopes):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP session scopes are invalid")
        approved_plan_hashes = record.get("approved_plan_hashes", [])
        if not isinstance(approved_plan_hashes, list) or not all(
            isinstance(item, str) for item in approved_plan_hashes
        ):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP approvals are invalid")
        approval_policy = record.get("approval_policy", {})
        if not isinstance(approval_policy, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in approval_policy.items()
        ):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP approval policy is invalid")
        budget_record = record.get("budget")
        budget = DelegatedBudget.from_record(budget_record) if budget_record is not None else None
        expires_at_value = record.get("expires_at")
        expires_at = (
            None
            if expires_at_value is None
            else _parse_datetime(expires_at_value, "session.expires_at")
        )
        return cls(
            control_session_id=required_string("control_session_id"),
            agent_identity=required_string("agent_identity"),
            operator_identity=required_string("operator_identity"),
            scopes=frozenset(scopes),
            created_at=_parse_datetime(record.get("created_at"), "session.created_at"),
            expires_at=expires_at,
            budget=budget,
            approval_policy=dict(approval_policy),
            approved_plan_hashes=frozenset(approved_plan_hashes),
        )

    def require_active(self) -> None:
        if self.expires_at is not None and _now() >= self.expires_at:
            raise McpDomainError(
                "MCP_CONTROL_SESSION_EXPIRED",
                "The Agent Control Session has expired",
            )

    @staticmethod
    def _scope_matches(granted: str, required: str) -> bool:
        if granted in {"*", required}:
            return True
        if granted.endswith(":*") and required.startswith(granted[:-1]):
            return True
        # A resource-specific permission can be satisfied by the domain action
        # permission, e.g. BUNDLE:READ permits BUNDLE:READ:bundle-1.
        return required.startswith(granted + ":")

    def allows(self, required: str) -> bool:
        return any(self._scope_matches(granted, required) for granted in self.scopes)

    def require(self, *required_scopes: str) -> None:
        self.require_active()
        missing = [scope for scope in required_scopes if not self.allows(scope)]
        if missing:
            raise McpDomainError(
                "MCP_PERMISSION_DENIED",
                "The active Agent Control Session does not grant the requested scope",
                details={"missing_scopes": missing},
            )

    def public(self) -> dict[str, Any]:
        self.require_active()
        return {
            "control_session_id": self.control_session_id,
            "agent_identity": self.agent_identity,
            "operator_identity": self.operator_identity,
            "scope": sorted(self.scopes),
            "budget": self.budget.public() if self.budget else None,
            "approval_policy": dict(self.approval_policy),
            "created_at": _iso(self.created_at),
            "expires_at": _iso(self.expires_at) if self.expires_at else None,
        }


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    required_scopes: tuple[str, ...]
    action_class: str
    handler: Callable[[dict[str, Any]], Any]
    mutating: bool = False
    approval_key: str | None = None

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass(frozen=True)
class McpResource:
    uri: str
    name: str
    description: str
    required_scope: str
    handler: Callable[[str], Any]
    mime_type: str = "application/json"

    def definition(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }


class McpAuditLog:
    """Small hash-linked audit stream for MCP actions."""

    def __init__(
        self,
        events: list[dict[str, Any]] | None = None,
        *,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._events: list[dict[str, Any]] = []
        self._on_change = on_change
        for event in events or []:
            self._append_loaded(event)

    def _append_loaded(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP audit event is invalid")
        sequence = len(self._events) + 1
        if event.get("sequence") != sequence:
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP audit sequence is invalid")
        previous_hash = self._events[-1]["event_hash"] if self._events else None
        if event.get("previous_event_hash") != previous_hash:
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP audit chain is invalid")
        event_hash = event.get("event_hash")
        unsigned_event = {key: value for key, value in event.items() if key != "event_hash"}
        if not isinstance(event_hash, str) or _hash_payload(unsigned_event) != event_hash:
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP audit hash is invalid")
        self._events.append(dict(event))

    def events(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self._events]

    def append(self, **event: Any) -> dict[str, Any]:
        sequence = len(self._events) + 1
        payload = {
            "audit_event_id": f"mcp-audit-{sequence}",
            "sequence": sequence,
            "created_at": _iso(_now()),
            "previous_event_hash": self._events[-1]["event_hash"] if self._events else None,
            **_json_safe(event),
        }
        payload["event_hash"] = _hash_payload(payload)
        self._events.append(payload)
        try:
            if self._on_change is not None:
                self._on_change()
        except Exception:
            self._events.pop()
            raise
        return dict(payload)

    def query(self, *, limit: int = 100, after_sequence: int = 0) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 500))
        items = [dict(event) for event in self._events if int(event["sequence"]) > int(after_sequence)][:bounded_limit]
        next_after = items[-1]["sequence"] if items else after_sequence
        return {
            "items": items,
            "next_after_sequence": next_after,
            "head_hash": self._events[-1]["event_hash"] if self._events else None,
        }


class McpControlPlane:
    """Maps MCP intent to existing Hypervisor read models and safe mutations."""

    def __init__(
        self,
        service,
        *,
        endpoint_service=None,
        endpoint_publication_service=None,
        validation_service=None,
        registry_service=None,
        session: ControlSession,
        mcp_state_store: McpPersistentStateStore | None = None,
        control_session_auto_renew: bool = False,
        control_session_ttl_seconds: int = DEFAULT_CONTROL_SESSION_TTL_SECONDS,
        control_session_stateless: bool = False,
    ) -> None:
        if control_session_ttl_seconds < MIN_CONTROL_SESSION_TTL_SECONDS:
            raise ValueError(
                "control_session_ttl_seconds must be at least "
                f"{MIN_CONTROL_SESSION_TTL_SECONDS}"
            )
        self.service = service
        self.endpoint_service = endpoint_service
        self.endpoint_publication_service = endpoint_publication_service
        self.endpoint_application_service = (
            EndpointApplicationService(
                endpoint_service=endpoint_service,
                hypervisor_service=service,
                endpoint_publication_service=endpoint_publication_service,
                validation_service=validation_service,
            )
            if endpoint_service is not None
            else None
        )
        self.validation_service = validation_service
        self.registry_service = registry_service
        self.mcp_state_store = mcp_state_store
        self.control_session_auto_renew = control_session_auto_renew
        self.control_session_ttl_seconds = control_session_ttl_seconds
        self.control_session_stateless = control_session_stateless
        persisted_state = mcp_state_store.load() if mcp_state_store is not None else {
            "sessions": {},
            "audit_events": [],
            "plans": {},
            "idempotency": {},
            "emergency_stop": {
                "active": False,
                "reason": None,
                "operator_identity": None,
                "reference": None,
                "updated_at": None,
            },
        }
        self.session = self._restore_session(session, persisted_state)
        if self.control_session_stateless:
            # A stateless Control Session is still scoped and audited, but its
            # lease is not an additional expiry boundary.  The bearer
            # credential resolver remains the revocation boundary for remote
            # requests.
            self.session.expires_at = None
        elif self.session.expires_at is None:
            # Switching stateless mode off must restore a finite lease rather
            # than inheriting the previous ``None`` value from persistence.
            self.session.expires_at = _now() + timedelta(seconds=self.control_session_ttl_seconds)
        self._persist_session = True
        self._plans = self._restore_plans(persisted_state)
        self._idempotency = self._restore_idempotency(persisted_state)
        self._emergency_stop = self._restore_emergency_stop(persisted_state)
        self.audit = McpAuditLog(
            persisted_state.get("audit_events", []),
            on_change=self._persist_state if mcp_state_store is not None else None,
        )
        self._tools = self._build_tools()
        self._resources = self._build_resources()
        self._persist_state()

    def _restore_session(
        self,
        requested: ControlSession,
        persisted_state: dict[str, Any],
    ) -> ControlSession:
        sessions = persisted_state.get("sessions", {})
        if not isinstance(sessions, dict):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP sessions are invalid")
        persisted = sessions.get(requested.control_session_id)
        if persisted is None:
            return requested
        restored = ControlSession.from_record(persisted)
        requested_identity = (
            requested.agent_identity,
            requested.operator_identity,
            sorted(requested.scopes),
            requested.approval_policy,
            requested.budget.to_record() if requested.budget else None,
        )
        persisted_policy = dict(restored.approval_policy)
        requested_policy = dict(requested.approval_policy)
        if persisted_policy != requested_policy:
            # A release may add a new mutating tool after an older control
            # session was persisted.  Allow only additive, restrictive
            # defaults; changing an existing rule or adding AUTO would weaken
            # the operator's previously persisted authority.
            persisted_keys = set(persisted_policy)
            existing_policy_unchanged = all(
                requested_policy.get(key) == value
                for key, value in persisted_policy.items()
            )
            additive_policy = {
                key: value
                for key, value in requested_policy.items()
                if key not in persisted_keys
            }
            if (
                existing_policy_unchanged
                and additive_policy
                and all(value != "AUTO" for value in additive_policy.values())
                and set(requested_policy) == persisted_keys | set(additive_policy)
            ):
                restored.approval_policy.update(additive_policy)
            else:
                raise McpPersistenceError(
                    "MCP_INTERNAL_ERROR",
                    "Control Session identity or delegation does not match persisted state",
                )
        persisted_scopes = set(restored.scopes)
        requested_scopes = set(requested.scopes)
        if persisted_scopes != requested_scopes:
            added_scopes = requested_scopes - persisted_scopes
            removed_scopes = persisted_scopes - requested_scopes
            if not removed_scopes and all(
                _is_additive_read_scope(scope) for scope in added_scopes
            ):
                # A release may add a read-only tool family. Persist the
                # expanded view without silently granting a mutating scope.
                restored.scopes = frozenset(requested_scopes)
            else:
                raise McpPersistenceError(
                    "MCP_INTERNAL_ERROR",
                    "Control Session identity or delegation does not match persisted state",
                )
        persisted_identity = (
            restored.agent_identity,
            restored.operator_identity,
            sorted(restored.scopes),
            restored.approval_policy,
            restored.budget.to_record() if restored.budget else None,
        )
        if requested_identity != persisted_identity:
            raise McpPersistenceError(
                "MCP_INTERNAL_ERROR",
                "Control Session identity or delegation does not match persisted state",
            )
        return restored

    @staticmethod
    def _restore_plans(persisted_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
        plans = persisted_state.get("plans", {})
        if not isinstance(plans, dict) or not all(
            isinstance(key, str) and isinstance(value, dict) for key, value in plans.items()
        ):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP plans are invalid")
        return {key: dict(value) for key, value in plans.items()}

    @staticmethod
    def _restore_idempotency(
        persisted_state: dict[str, Any],
    ) -> dict[str, tuple[str, dict[str, Any]]]:
        entries = persisted_state.get("idempotency", {})
        if not isinstance(entries, dict):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP idempotency is invalid")
        restored: dict[str, tuple[str, dict[str, Any]]] = {}
        for key, entry in entries.items():
            if (
                not isinstance(key, str)
                or not isinstance(entry, dict)
                or not isinstance(entry.get("fingerprint"), str)
                or not isinstance(entry.get("result"), dict)
            ):
                raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP idempotency entry is invalid")
            restored[key] = (entry["fingerprint"], dict(entry["result"]))
        return restored

    @staticmethod
    def _restore_emergency_stop(persisted_state: dict[str, Any]) -> dict[str, Any]:
        state = persisted_state.get("emergency_stop", {})
        if not isinstance(state, dict):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP emergency-stop state is invalid")
        active = state.get("active", False)
        if not isinstance(active, bool):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "Persisted MCP emergency-stop flag is invalid")
        values: dict[str, Any] = {"active": active}
        for field_name in ("reason", "operator_identity", "reference"):
            value = state.get(field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise McpPersistenceError(
                    "MCP_INTERNAL_ERROR",
                    f"Persisted MCP emergency-stop field is invalid: {field_name}",
                )
            values[field_name] = value
        updated_at = state.get("updated_at")
        if updated_at is not None:
            _parse_datetime(updated_at, "emergency_stop.updated_at")
        values["updated_at"] = updated_at
        if active and not all(values[field] for field in ("reason", "operator_identity", "reference", "updated_at")):
            raise McpPersistenceError(
                "MCP_INTERNAL_ERROR",
                "Persisted active emergency-stop state is incomplete",
            )
        return values

    def _persist_state(self) -> None:
        if self.mcp_state_store is None:
            return
        state = self.mcp_state_store.load()
        sessions = state.setdefault("sessions", {})
        if self._persist_session:
            sessions[self.session.control_session_id] = self.session.to_record()
        plans = state.setdefault("plans", {})
        plans.update(_json_safe(self._plans))
        state["audit_events"] = self.audit.events() if hasattr(self, "audit") else []
        state["idempotency"] = {
            key: {"fingerprint": fingerprint, "result": _json_safe(result)}
            for key, (fingerprint, result) in self._idempotency.items()
        }
        state["emergency_stop"] = _json_safe(self._emergency_stop)
        self.mcp_state_store.save(state)

    def renew_control_session(self, *, source: str) -> dict[str, Any]:
        """Renew an authenticated session lease without changing authority.

        Renewal is deliberately outside ``ControlSession.require_active`` so a
        valid bearer credential can recover a persisted session after an idle
        period. It never changes identity, scopes, budget or approvals.
        """

        if self.control_session_stateless:
            return {
                "renewed": False,
                "stateless": True,
                "control_session_id": self.session.control_session_id,
                "expires_at": None,
            }

        now = _now()
        if not self.control_session_auto_renew:
            return {
                "renewed": False,
                "control_session_id": self.session.control_session_id,
                "expires_at": _iso(self.session.expires_at),
            }
        renewal_window = timedelta(seconds=max(1, self.control_session_ttl_seconds // 2))
        if self.session.expires_at > now + renewal_window:
            return {
                "renewed": False,
                "control_session_id": self.session.control_session_id,
                "expires_at": _iso(self.session.expires_at),
            }

        previous_expires_at = self.session.expires_at
        self.session.expires_at = now + timedelta(seconds=self.control_session_ttl_seconds)
        self.audit.append(
            event_type="MCP_CONTROL_SESSION_RENEWED",
            agent_identity=self.session.agent_identity,
            operator_identity=self.session.operator_identity,
            source=source,
            control_session_id=self.session.control_session_id,
            previous_expires_at=_iso(previous_expires_at),
            expires_at=_iso(self.session.expires_at),
            result="RENEWED",
        )
        return {
            "renewed": True,
            "control_session_id": self.session.control_session_id,
            "previous_expires_at": _iso(previous_expires_at),
            "expires_at": _iso(self.session.expires_at),
        }

    def approve_plan(
        self,
        plan_hash: str,
        *,
        approval_reference: str,
        approver_identity: str,
    ) -> dict[str, Any]:
        """Approve a plan through a trusted operator embedding boundary.

        This method is intentionally not exposed as an Agent tool. A future
        remote approval channel must call this boundary after authenticating
        the operator rather than allowing an Agent to approve its own plan.
        """

        self.session.require_active()
        if self.emergency_stop_active:
            raise McpDomainError(
                "MCP_PERMISSION_DENIED",
                "Emergency stop is active; new plan approvals are frozen",
                details={"emergency_stop": self.emergency_stop_status()},
            )
        if not plan_hash or not approval_reference or not approver_identity:
            raise McpDomainError("MCP_INVALID_ARGUMENTS", "Plan approval fields are required")
        if approver_identity != self.session.operator_identity:
            raise McpDomainError(
                "MCP_PERMISSION_DENIED",
                "Only the bound operator may approve this Control Session plan",
            )
        plan = self._plans.get(plan_hash)
        if plan is None:
            raise McpDomainError("MCP_APPROVAL_HASH_MISMATCH", "The plan hash is not known to this server")
        self.session.approved_plan_hashes = frozenset(
            {*self.session.approved_plan_hashes, plan_hash}
        )
        audit_event = self.audit.append(
            event_type="MCP_PLAN_APPROVED",
            agent_identity=self.session.agent_identity,
            operator_identity=self.session.operator_identity,
            approver_identity=approver_identity,
            approval_reference=approval_reference,
            plan_id=plan["plan_id"],
            plan_hash=plan_hash,
            result="APPROVED",
        )
        return {
            "plan_id": plan["plan_id"],
            "plan_hash": plan_hash,
            "approval_reference": approval_reference,
            "approved": True,
            "audit_event_id": audit_event["audit_event_id"],
        }

    @property
    def emergency_stop_active(self) -> bool:
        return bool(self._emergency_stop.get("active"))

    def emergency_stop_status(self) -> dict[str, Any]:
        return dict(self._emergency_stop)

    def set_emergency_stop(
        self,
        *,
        active: bool,
        reason: str,
        reference: str,
        operator_identity: str,
    ) -> dict[str, Any]:
        """Set the operator-controlled mutation freeze outside the Agent tool set."""

        self.session.require_active()
        if not isinstance(active, bool) or not all(
            isinstance(value, str) and value.strip()
            for value in (reason, reference, operator_identity)
        ):
            raise McpDomainError(
                "MCP_INVALID_ARGUMENTS",
                "Emergency-stop state requires reason, reference, and operator identity",
            )
        if operator_identity != self.session.operator_identity:
            raise McpDomainError(
                "MCP_PERMISSION_DENIED",
                "Only the bound operator may change the emergency-stop state",
            )
        previous = dict(self._emergency_stop)
        self._emergency_stop = {
            "active": active,
            "reason": reason,
            "operator_identity": operator_identity,
            "reference": reference,
            "updated_at": _iso(_now()),
        }
        try:
            audit_event = self.audit.append(
                event_type=(
                    "MCP_EMERGENCY_STOP_ACTIVATED"
                    if active
                    else "MCP_EMERGENCY_STOP_CLEARED"
                ),
                agent_identity=self.session.agent_identity,
                operator_identity=self.session.operator_identity,
                reference=reference,
                reason=reason,
                result="ACTIVE" if active else "CLEARED",
            )
        except Exception:
            self._emergency_stop = previous
            raise
        return {**self.emergency_stop_status(), "audit_event_id": audit_event["audit_event_id"]}

    def tool_definitions(self) -> list[dict[str, Any]]:
        return [
            tool.definition()
            for tool in self._tools.values()
            if all(self.session.allows(scope) for scope in tool.required_scopes)
        ]

    def resource_definitions(self) -> list[dict[str, Any]]:
        return [
            resource.definition()
            for resource in self._resources.values()
            if self.session.allows(resource.required_scope)
        ]

    def capabilities(self) -> dict[str, Any]:
        self.session.require_active()
        approval_policy = dict(self.session.approval_policy)
        catalog = self.tool_catalog_metadata()
        return {
            "spec_version": "MCP-0001/0.1",
            "server_version": MCP_SERVER_VERSION,
            "mcp_protocol_version": MCP_PROTOCOL_VERSION,
            "node_identity": _json_safe(self.service.node_identity()),
            "control_session": self.session.public(),
            # Keep the effective, credential-scoped policy at a stable
            # top-level location as well as inside ``control_session``.  A
            # remote agent must never have to infer whether a value came from
            # the operator baseline or its own delegated credential.
            "effective_approval_policy": approval_policy,
            "implemented_tools": sorted(self._tools),
            "implemented_resources": sorted(self._resources),
            "tool_catalog_revision": catalog["revision"],
            "tool_catalog": catalog,
            "deferred_tool_families": [
                "aidn.host.prepare",
                "aidn.node.install",
                "aidn.node.join_network",
                "aidn.plugin.install",
                "aidn.model.deploy",
                "aidn.validation.request",
                "aidn.session.open",
                "aidn.wallet.transfer",
                "aidn.host.exec",
            ],
            "security_boundary": {
                "private_key_export": "DENY",
                "arbitrary_shell": "DENY",
                "consensus_bypass": "DENY",
                "plan_before_apply": "REQUIRED_FOR_MUTATIONS",
                "emergency_stop": self.emergency_stop_status(),
            },
        }

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        self.session.require_active()
        tool = self._tools.get(name)
        if tool is None:
            raise McpDomainError(
                "MCP_UNSUPPORTED_TOOL",
                f"Unsupported MCP tool: {name}",
                details={
                    "refresh_tools": True,
                    "tool_catalog_changed": True,
                    "next_action": "Call tools/list and replace the cached tool catalog before retrying.",
                },
            )
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise McpDomainError(
                "MCP_INVALID_ARGUMENTS",
                "Tool arguments must be a JSON object",
            )
        try:
            self.session.require(*tool.required_scopes)
            if tool.mutating and self.emergency_stop_active:
                raise McpDomainError(
                    "MCP_PERMISSION_DENIED",
                    "Emergency stop is active; Agent mutations are frozen",
                    details={"emergency_stop": self.emergency_stop_status()},
                )
            if tool.mutating:
                payload = self._call_mutating(tool, arguments)
            else:
                payload = tool.handler(arguments)
            return self.success(payload)
        except McpDomainError as error:
            audit_event = self.audit.append(
                event_type="MCP_TOOL_REJECTED",
                agent_identity=self.session.agent_identity,
                operator_identity=self.session.operator_identity,
                tool=name,
                request_id=arguments.get("request_id"),
                action_class=tool.action_class,
                result=error.code,
            )
            return self.failure(error, audit_event_id=audit_event["audit_event_id"])
        except (KeyError, ValueError) as error:
            error_details = getattr(error, "details", None)
            domain_error = McpDomainError(
                self._map_domain_error(name, error),
                str(error),
                details=error_details if isinstance(error_details, dict) else None,
            )
            audit_event = self.audit.append(
                event_type="MCP_TOOL_FAILED",
                agent_identity=self.session.agent_identity,
                operator_identity=self.session.operator_identity,
                tool=name,
                request_id=arguments.get("request_id"),
                action_class=tool.action_class,
                result=domain_error.code,
            )
            return self.failure(domain_error, audit_event_id=audit_event["audit_event_id"])
        except FileNotFoundError as error:
            missing_path = getattr(error, "filename", None)
            if not isinstance(missing_path, str) or not missing_path:
                missing_path = "the configured runtime executable or working directory"
            domain_error = McpDomainError(
                "MCP_RUNTIME_ARTIFACT_NOT_FOUND",
                "The configured runtime executable or working directory was not found",
                details={"missing_path": missing_path},
            )
            audit_event = self.audit.append(
                event_type="MCP_TOOL_FAILED",
                agent_identity=self.session.agent_identity,
                operator_identity=self.session.operator_identity,
                tool=name,
                request_id=arguments.get("request_id"),
                action_class=tool.action_class,
                result=domain_error.code,
            )
            return self.failure(domain_error, audit_event_id=audit_event["audit_event_id"])
        except Exception as error:  # pragma: no cover - defensive adapter boundary
            domain_error = McpDomainError(
                "MCP_INTERNAL_ERROR",
                "The Hypervisor operation failed without a stable domain result",
                details={"exception_type": type(error).__name__},
            )
            audit_event = self.audit.append(
                event_type="MCP_TOOL_FAILED",
                agent_identity=self.session.agent_identity,
                operator_identity=self.session.operator_identity,
                tool=name,
                request_id=arguments.get("request_id"),
                action_class=tool.action_class,
                result=domain_error.code,
            )
            return self.failure(domain_error, audit_event_id=audit_event["audit_event_id"])

    def read_resource(self, uri: str) -> dict[str, Any]:
        self.session.require_active()
        resource = self._resolve_resource(uri)
        self.session.require(resource.required_scope)
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": resource.mime_type,
                    "text": _canonical_json(resource.handler(uri)),
                }
            ]
        }

    def success(self, payload: Any) -> dict[str, Any]:
        safe_payload = _json_safe(payload)
        return {
            "content": [
                {
                    "type": "text",
                    "text": _canonical_json(safe_payload),
                }
            ],
            "structuredContent": safe_payload,
            "isError": False,
        }

    def failure(
        self,
        error: McpDomainError,
        *,
        audit_event_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {"error": error.as_dict(audit_event_id=audit_event_id)}
        return {
            "content": [
                {
                    "type": "text",
                    "text": _canonical_json(payload),
                }
            ],
            "structuredContent": payload,
            "isError": True,
        }

    def tool_catalog_metadata(self) -> dict[str, Any]:
        """Describe the currently effective tool catalog without exposing secrets."""

        definitions = self.tool_definitions()
        return {
            "revision": _tool_catalog_revision(definitions),
            "count": len(definitions),
            "refresh_required": False,
            "transport_reconnect_required": False,
            "next_action": "Call tools/list when the catalog revision changes.",
        }

    def mcp_session_status(self) -> dict[str, Any]:
        """Give an Agent an explicit, non-destructive MCP refresh checkpoint."""

        return {
            "server_version": MCP_SERVER_VERSION,
            "protocol_version": MCP_PROTOCOL_VERSION,
            "control_session": self.session.public(),
            "tool_catalog": self.tool_catalog_metadata(),
            "refresh": {
                "scope_changes_apply_to_active_session": True,
                "gateway_restart_required": False,
                "after_scope_change": [
                    "Call aidn.capabilities.get",
                    "Call tools/list if tool_catalog_revision changed",
                ],
            },
        }

    def _build_tools(self) -> dict[str, McpTool]:
        read_schema = {"type": "object", "additionalProperties": False}
        forecast_schema = {
            "type": "object",
            "properties": {
                "cpu": {"type": "number", "minimum": 0},
                "ram_mb": {"type": "integer", "minimum": 0},
                "vram_mb": {"type": "integer", "minimum": 0},
            },
            "additionalProperties": False,
        }
        hook_filter_schema = {
            "type": "object",
            "properties": {
                "event_types": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "maxItems": 128,
                },
                "resource_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "maxItems": 128,
                },
                "severity_minimum": {
                    "enum": ["DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL"],
                },
            },
            "additionalProperties": False,
        }
        hook_mutation_fields = {
            "mode": {"enum": ["plan", "apply"]},
            "request_id": {"type": "string", "minLength": 1},
            "idempotency_key": {"type": "string", "minLength": 1},
            "plan_hash": {"type": "string", "minLength": 1},
            "expected_revision": {"type": "string", "minLength": 1},
            "approval_reference": {"type": "string", "minLength": 1},
        }
        runtime_mutation_schema = {
            "type": "object",
            "properties": {
                "runtime_id": {"type": "string", "minLength": 1},
                "mode": {"enum": ["plan", "apply"]},
                "request_id": {"type": "string", "minLength": 1},
                "idempotency_key": {"type": "string", "minLength": 1},
                "plan_hash": {"type": "string", "minLength": 1},
                "expected_revision": {"type": "string", "minLength": 1},
                "approval_reference": {"type": "string", "minLength": 1},
            },
            "required": ["runtime_id", "mode", "request_id", "idempotency_key"],
            "additionalProperties": False,
        }
        return {
            "aidn.capabilities.get": McpTool(
                "aidn.capabilities.get",
                "Return the negotiated MCP control-plane capabilities and policy boundary.",
                read_schema,
                (),
                "READ_ONLY",
                lambda _args: self.capabilities(),
            ),
            "aidn.mcp.session_status": McpTool(
                "aidn.mcp.session_status",
                "Report MCP session, permission refresh, and effective tool-catalog status.",
                read_schema,
                (),
                "READ_ONLY",
                lambda _args: self.mcp_session_status(),
            ),
            "aidn.policy.get": McpTool(
                "aidn.policy.get",
                "Return the effective scheduler and approval policy visible to this agent.",
                read_schema,
                ("SCHEDULER:READ",),
                "READ_ONLY",
                lambda _args: {
                    "scheduler": self.service.operator_requests_policy(),
                    "approval_policy": dict(self.session.approval_policy),
                    "effective_approval_policy": dict(self.session.approval_policy),
                },
            ),
            "aidn.host.inspect": McpTool(
                "aidn.host.inspect",
                "Inspect non-secret host capabilities without executing shell commands.",
                read_schema,
                ("HOST:READ",),
                "READ_ONLY",
                lambda args: self._host_inspect(args),
            ),
            "aidn.node.status": McpTool(
                "aidn.node.status",
                "Return the local node identity and operational summary.",
                read_schema,
                ("NODE:READ",),
                "READ_ONLY",
                lambda _args: self._node_status(),
            ),
            "aidn.node.health": McpTool(
                "aidn.node.health",
                "Return a sanitized node health report.",
                read_schema,
                ("NODE:READ",),
                "READ_ONLY",
                lambda _args: self._node_health(),
            ),
            "aidn.network.status": McpTool(
                "aidn.network.status",
                "Return network identity and synchronization status.",
                read_schema,
                ("NETWORK:READ",),
                "READ_ONLY",
                lambda _args: self._network_status(),
            ),
            "aidn.network.peers": McpTool(
                "aidn.network.peers",
                "Return known network peers when the local registry exposes them.",
                read_schema,
                ("NETWORK:READ",),
                "READ_ONLY",
                lambda _args: self._network_peers(),
            ),
            "aidn.provider.list": McpTool(
                "aidn.provider.list",
                "List provider plugins, instances, model deployments, and runtime bindings.",
                read_schema,
                ("PROVIDER:READ",),
                "READ_ONLY",
                lambda _args: build_operator_providers_payload(
                    service=self.service,
                    endpoint_service=self.endpoint_service,
                    endpoint_publication_service=self.endpoint_publication_service,
                    validation_service=self.validation_service,
                ),
            ),
            "aidn.runtime.operations": McpTool(
                "aidn.runtime.operations",
                "Return freshly reconciled runtime readiness and Provider Broker installation progress.",
                read_schema,
                ("PROVIDER:READ",),
                "READ_ONLY",
                lambda _args: build_runtime_operations_payload(service=self.service),
            ),
            "aidn.runtime.instances": McpTool(
                "aidn.runtime.instances",
                "Return freshly reconciled Runtime Instance state and warm-retention controls.",
                read_schema,
                ("RUNTIME:READ",),
                "READ_ONLY",
                lambda _args: self._runtime_instances(),
            ),
            "aidn.runtime.drain": McpTool(
                "aidn.runtime.drain",
                "Plan or drain a Runtime Instance so it finishes current work and accepts no new work.",
                runtime_mutation_schema,
                ("RUNTIME:WRITE",),
                "RUNTIME_MUTATION",
                lambda args: self._drain_runtime(args),
                mutating=True,
                approval_key="runtime_control",
            ),
            "aidn.runtime.stop": McpTool(
                "aidn.runtime.stop",
                "Plan or force-stop a Runtime Instance and release its Resource Broker lease.",
                runtime_mutation_schema,
                ("RUNTIME:WRITE",),
                "DISRUPTIVE_MUTATION",
                lambda args: self._stop_runtime(args),
                mutating=True,
                approval_key="runtime_control",
            ),
            "aidn.runtime.pin": McpTool(
                "aidn.runtime.pin",
                "Plan or pin a live Runtime Instance warm so idle eviction will not reclaim it.",
                runtime_mutation_schema,
                ("RUNTIME:WRITE",),
                "RUNTIME_MUTATION",
                lambda args: self._pin_runtime(args),
                mutating=True,
                approval_key="runtime_control",
            ),
            "aidn.runtime.unpin": McpTool(
                "aidn.runtime.unpin",
                "Plan or release a Runtime Instance warm pin so normal eviction policy applies.",
                runtime_mutation_schema,
                ("RUNTIME:WRITE",),
                "RUNTIME_MUTATION",
                lambda args: self._unpin_runtime(args),
                mutating=True,
                approval_key="runtime_control",
            ),
            "aidn.model.list": McpTool(
                "aidn.model.list",
                "List model deployments and model installation jobs.",
                read_schema,
                ("MODEL:READ",),
                "READ_ONLY",
                lambda _args: {
                    "deployments": self.service.list_model_deployments(),
                    "installs": self.service.list_model_installs(),
                },
            ),
            "aidn.bundle.list": McpTool(
                "aidn.bundle.list",
                "List immutable Bundle revisions and their local runtime state.",
                read_schema,
                ("BUNDLE:READ",),
                "READ_ONLY",
                lambda _args: build_operator_bundles_payload(
                    service=self.service,
                    endpoint_service=self.endpoint_service,
                    endpoint_publication_service=self.endpoint_publication_service,
                    validation_service=self.validation_service,
                ),
            ),
            "aidn.bundle.get": McpTool(
                "aidn.bundle.get",
                "Return one Bundle configuration and runtime state.",
                {
                    "type": "object",
                    "properties": {"bundle_id": {"type": "string", "minLength": 1}},
                    "required": ["bundle_id"],
                    "additionalProperties": False,
                },
                ("BUNDLE:READ",),
                "READ_ONLY",
                lambda args: self._bundle_get(args),
            ),
            "aidn.endpoint.list": McpTool(
                "aidn.endpoint.list",
                "List local Endpoint configurations without exposing private secrets.",
                read_schema,
                ("ENDPOINT:READ",),
                "READ_ONLY",
                lambda _args: build_operator_endpoints_payload(
                    service=self.service,
                    endpoint_service=self.endpoint_service,
                    endpoint_publication_service=self.endpoint_publication_service,
                    validation_service=self.validation_service,
                ),
            ),
            "aidn.endpoint.create": McpTool(
                "aidn.endpoint.create",
                "Plan or create an Endpoint draft from an existing Runtime Binding and immutable Bundle revision.",
                {
                    "type": "object",
                    "properties": {
                        "runtime_binding_id": {"type": "string", "minLength": 1},
                        "bundle_id": {"type": "string", "minLength": 1},
                        "display_name": {"type": "string", "minLength": 1},
                        "model_class": {"type": "string", "minLength": 1},
                        "capabilities": {"type": "array", "items": {"type": "string"}},
                        "runtime_parameter_policy": {"type": "object"},
                        "profile": {"type": "object"},
                        "runtime": {"type": "object"},
                        "publication": {"type": "object"},
                        "pricing": {"type": "object"},
                        "session": {"type": "object"},
                        "validation": {"type": "object"},
                        "local_agent_use": {"type": "boolean"},
                        "mode": {"enum": ["plan", "apply"]},
                        "request_id": {"type": "string", "minLength": 1},
                        "idempotency_key": {"type": "string", "minLength": 1},
                        "plan_hash": {"type": "string"},
                        "expected_revision": {"type": "string"},
                        "approval_reference": {"type": "string"},
                    },
                    "required": [
                        "runtime_binding_id",
                        "bundle_id",
                        "display_name",
                        "mode",
                        "request_id",
                        "idempotency_key",
                    ],
                    "additionalProperties": False,
                },
                ("ENDPOINT:WRITE",),
                "ENDPOINT_MUTATION",
                lambda args: self._create_endpoint(args),
                mutating=True,
                approval_key="endpoint_write",
            ),
            "aidn.endpoint.publish": McpTool(
                "aidn.endpoint.publish",
                "Plan or publish an Endpoint draft through the canonical wallet and CometBFT publication path.",
                {
                    "type": "object",
                    "properties": {
                        "endpoint_id": {"type": "string", "minLength": 1},
                        "mode": {"enum": ["plan", "apply"]},
                        "request_id": {"type": "string", "minLength": 1},
                        "idempotency_key": {"type": "string", "minLength": 1},
                        "plan_hash": {"type": "string"},
                        "expected_revision": {"type": "string"},
                        "approval_reference": {"type": "string"},
                    },
                    "required": [
                        "endpoint_id",
                        "mode",
                        "request_id",
                        "idempotency_key",
                    ],
                    "additionalProperties": False,
                },
                ("ENDPOINT:WRITE",),
                "ENDPOINT_PUBLICATION",
                lambda args: self._publish_endpoint(args),
                mutating=True,
                approval_key="endpoint_write",
            ),
            "aidn.resources.status": McpTool(
                "aidn.resources.status",
                "Return current CPU, RAM, and VRAM reservation state.",
                read_schema,
                ("RESOURCES:READ",),
                "READ_ONLY",
                lambda _args: self._resource_status(),
            ),
            "aidn.resources.forecast": McpTool(
                "aidn.resources.forecast",
                "Explain whether a new CPU, RAM, and VRAM lease fits without reserving it.",
                {
                    "type": "object",
                    "properties": {
                        "cpu": {"type": "number", "minimum": 0},
                        "ram_mb": {"type": "integer", "minimum": 0},
                        "vram_mb": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
                ("RESOURCES:READ",),
                "READ_ONLY",
                lambda args: self._resource_forecast(args),
            ),
            "aidn.resources.leases": McpTool(
                "aidn.resources.leases",
                "List active Resource Broker leases and their reserved capacity.",
                read_schema,
                ("RESOURCES:READ",),
                "READ_ONLY",
                lambda _args: self._resource_leases(),
            ),
            # RFC-0073 names the same read surface Resource Broker.  Keep the
            # shorter resources.* names for existing clients and expose these
            # canonical aliases so agents can follow the RFC verbatim.
            "aidn.resource_broker.status": McpTool(
                "aidn.resource_broker.status",
                "Return current Resource Broker capacity and reservation state.",
                read_schema,
                ("RESOURCES:READ",),
                "READ_ONLY",
                lambda _args: self._resource_status(),
            ),
            "aidn.resource_broker.devices": McpTool(
                "aidn.resource_broker.devices",
                "Return Hardware Monitor state for CPU, RAM, per-GPU VRAM, storage, and reconciliation confidence.",
                read_schema,
                ("RESOURCES:READ",),
                "READ_ONLY",
                lambda _args: self._resource_devices(),
            ),
            "aidn.resource_broker.forecast": McpTool(
                "aidn.resource_broker.forecast",
                "Forecast whether a new Resource Broker lease fits without reserving it.",
                forecast_schema,
                ("RESOURCES:READ",),
                "READ_ONLY",
                lambda args: self._resource_forecast(args),
            ),
            "aidn.resource_broker.leases": McpTool(
                "aidn.resource_broker.leases",
                "List active Resource Broker leases.",
                read_schema,
                ("RESOURCES:READ",),
                "READ_ONLY",
                lambda _args: self._resource_leases(),
            ),
            "aidn.resource_broker.explain_denial": McpTool(
                "aidn.resource_broker.explain_denial",
                "Explain a Resource Broker admission denial using required/free/shortfall values.",
                forecast_schema,
                ("RESOURCES:READ",),
                "READ_ONLY",
                lambda args: self._resource_forecast(args),
            ),
            "aidn.scheduler.get_policy": McpTool(
                "aidn.scheduler.get_policy",
                "Return local request routing policy.",
                read_schema,
                ("SCHEDULER:READ",),
                "READ_ONLY",
                lambda _args: self.service.operator_requests_policy(),
            ),
            "aidn.scheduler.status": McpTool(
                "aidn.scheduler.status",
                "Return queue, Resource Broker, and fit-aware scheduler status.",
                read_schema,
                ("SCHEDULER:READ",),
                "READ_ONLY",
                lambda _args: self._scheduler_status(),
            ),
            "aidn.scheduler.queues": McpTool(
                "aidn.scheduler.queues",
                "List independent scheduler queues and their current head candidates.",
                read_schema,
                ("SCHEDULER:READ",),
                "READ_ONLY",
                lambda _args: self._scheduler_queues(),
            ),
            "aidn.scheduler.candidates": McpTool(
                "aidn.scheduler.candidates",
                "List the current head candidate from every independent queue with admission reasons.",
                {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    },
                    "additionalProperties": False,
                },
                ("SCHEDULER:READ",),
                "READ_ONLY",
                lambda args: self._scheduler_candidates(args),
            ),
            "aidn.scheduler.explain_decision": McpTool(
                "aidn.scheduler.explain_decision",
                (
                    "Explain why one queued task is runnable, waiting for resources, "
                    "blocked by policy, or behind another Endpoint queue head."
                ),
                {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "minLength": 1},
                    },
                    "required": ["task_id"],
                    "additionalProperties": False,
                },
                ("SCHEDULER:READ",),
                "READ_ONLY",
                lambda args: self._scheduler_explain_decision(args),
            ),
            "aidn.scheduler.reconcile": McpTool(
                "aidn.scheduler.reconcile",
                (
                    "Plan or request a global scheduler reconciliation. "
                    "Admission, leases, and eviction policy remain authoritative."
                ),
                {
                    "type": "object",
                    "properties": {
                        "trigger": {"type": "string", "minLength": 1, "maxLength": 96},
                        "max_cycles": {"type": "integer", "minimum": 1, "maximum": 1024},
                        "mode": {"enum": ["plan", "apply"]},
                        "request_id": {"type": "string", "minLength": 1},
                        "idempotency_key": {"type": "string", "minLength": 1},
                        "plan_hash": {"type": "string"},
                    },
                    "required": ["mode", "request_id", "idempotency_key"],
                    "additionalProperties": False,
                },
                ("SCHEDULER:WRITE",),
                "SAFE_MUTATION",
                lambda args: self._reconcile_scheduler(args),
                mutating=True,
            ),
            "aidn.wallet.summary": McpTool(
                "aidn.wallet.summary",
                "Return public owner-wallet and local accounting summary, never private keys.",
                read_schema,
                ("WALLET:READ",),
                "READ_ONLY",
                lambda _args: self._wallet_summary(),
            ),
            "aidn.budget.list": McpTool(
                "aidn.budget.list",
                "List delegated budgets visible to this control session.",
                read_schema,
                ("BUDGET:READ",),
                "READ_ONLY",
                lambda _args: self._budget_list(),
            ),
            "aidn.budget.status": McpTool(
                "aidn.budget.status",
                "Return the current delegated budget state.",
                read_schema,
                ("BUDGET:READ",),
                "READ_ONLY",
                lambda _args: self._budget_status(),
            ),
            "aidn.audit.query": McpTool(
                "aidn.audit.query",
                "Query the hash-linked MCP audit stream.",
                {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                        "after_sequence": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
                ("AUDIT:READ",),
                "READ_ONLY",
                lambda args: self.audit.query(
                    limit=int(args.get("limit", 100)),
                    after_sequence=int(args.get("after_sequence", 0)),
                ),
            ),
            "aidn.event.query": McpTool(
                "aidn.event.query",
                "Query retained canonical Hypervisor events with a restart-safe cursor.",
                {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                        "after_sequence": {"type": "integer", "minimum": 0},
                        "event_type": {"type": "array", "items": {"type": "string"}},
                        "resource_id": {"type": "string", "minLength": 1},
                    },
                    "additionalProperties": False,
                },
                ("AUDIT:READ",),
                "READ_ONLY",
                lambda args: self.service.canonical_event_query(
                    after_sequence=int(args.get("after_sequence", 0)),
                    limit=int(args.get("limit", 100)),
                    event_types=set(args["event_type"]) if args.get("event_type") else None,
                    resource_id=args.get("resource_id"),
                ),
            ),
            "aidn.event.inbox": McpTool(
                "aidn.event.inbox",
                "Read this agent's durable canonical event Inbox without acknowledging events.",
                {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                        "after_sequence": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
                ("AUDIT:READ",),
                "READ_ONLY",
                lambda args: self.service.event_inbox(
                    self.session.agent_identity,
                    after_sequence=(
                        int(args["after_sequence"])
                        if args.get("after_sequence") is not None
                        else None
                    ),
                    limit=int(args.get("limit", 100)),
                ),
            ),
            "aidn.event.ack": McpTool(
                "aidn.event.ack",
                "Acknowledge retained canonical events for this agent's Inbox.",
                {
                    "type": "object",
                    "properties": {
                        "event_ids": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 500,
                            "items": {"type": "string", "minLength": 1},
                        }
                    },
                    "required": ["event_ids"],
                    "additionalProperties": False,
                },
                ("AUDIT:READ",),
                "INBOX_ACK",
                lambda args: self.service.acknowledge_event_inbox(
                    self.session.agent_identity,
                    list(args.get("event_ids", [])),
                ),
            ),
            "aidn.operator.chat.status": McpTool(
                "aidn.operator.chat.status",
                "Read the external operator-to-agent conversation channel and recent message history.",
                read_schema,
                ("AUDIT:READ",),
                "READ_ONLY",
                lambda _args: self.service.agent_conversation_status(),
            ),
            "aidn.operator.chat.reply": McpTool(
                "aidn.operator.chat.reply",
                "Append a text reply to the bound operator conversation. The session Agent identity must match the channel binding.",
                {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "minLength": 1, "maxLength": 16384},
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
                ("CHAT:WRITE",),
                "OPERATOR_CHAT_REPLY",
                lambda args: self.service.receive_agent_conversation_reply(
                    agent_id=self.session.agent_identity,
                    text=str(args["text"]),
                ),
            ),
            "aidn.hook.list": McpTool(
                "aidn.hook.list",
                "List operator-owned RFC-0072 Hook subscriptions.",
                {
                    "type": "object",
                    "properties": {
                        "owner_operator_id": {"type": "string", "minLength": 1},
                    },
                    "additionalProperties": False,
                },
                ("HOOK:READ",),
                "READ_ONLY",
                lambda args: {
                    "items": [
                        item.model_dump(mode="json")
                        for item in self._visible_hooks(
                            owner_operator_id=args.get("owner_operator_id")
                        )
                    ]
                },
            ),
            "aidn.hook.deliveries": McpTool(
                "aidn.hook.deliveries",
                "Inspect bounded Hook delivery attempts and retry state.",
                {
                    "type": "object",
                    "properties": {
                        "hook_id": {"type": "string", "minLength": 1},
                        "status": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    },
                    "additionalProperties": False,
                },
                ("HOOK:READ",),
                "READ_ONLY",
                lambda args: {
                        "items": [
                            item.model_dump(mode="json")
                            for item in self.service.hook_deliveries(
                                hook_id=args.get("hook_id"),
                                status=args.get("status"),
                                limit=int(args.get("limit", 100)),
                            )
                            if self._is_visible_delivery(item)
                        ]
                    },
            ),
            "aidn.hook.dead_letters": McpTool(
                "aidn.hook.dead_letters",
                "Inspect Hook deliveries that exhausted their bounded retry policy.",
                {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    },
                    "additionalProperties": False,
                },
                ("HOOK:READ",),
                "READ_ONLY",
                lambda args: {
                        "items": [
                            item.model_dump(mode="json")
                            for item in self.service.hook_dead_letters(
                                limit=int(args.get("limit", 100))
                            )
                            if self._is_visible_delivery(item)
                        ]
                    },
            ),
            "aidn.hook.metrics": McpTool(
                "aidn.hook.metrics",
                "Return Hook delivery, retry, dead-letter, and queue metrics.",
                {"type": "object", "properties": {}, "additionalProperties": False},
                ("HOOK:READ",),
                "READ_ONLY",
                lambda _args: self.service.hook_dispatch_metrics(),
            ),
            "aidn.hook.get": McpTool(
                "aidn.hook.get",
                "Return one operator-owned Hook definition and its delivery status.",
                {
                    "type": "object",
                    "properties": {"hook_id": {"type": "string", "minLength": 1}},
                    "required": ["hook_id"],
                    "additionalProperties": False,
                },
                ("HOOK:READ",),
                "READ_ONLY",
                lambda args: self._hook_get(args),
            ),
            "aidn.hook.create": McpTool(
                "aidn.hook.create",
                "Plan or create an operator-owned Hook subscription for the current Agent.",
                {
                    "type": "object",
                    "properties": {
                        "hook_id": {"type": "string", "minLength": 1, "maxLength": 128},
                        "target_agent_id": {"type": "string", "minLength": 1, "maxLength": 256},
                        "event_filter": hook_filter_schema,
                        "delivery_mode": {"enum": ["DURABLE_INBOX", "MCP_LIVE"]},
                        "max_attempts": {"type": "integer", "minimum": 1, "maximum": 10},
                        "retry_backoff_seconds": {"type": "number", "minimum": 0, "maximum": 3600},
                        "expires_at": {"type": ["string", "null"]},
                        **hook_mutation_fields,
                    },
                    "required": ["hook_id", "event_filter", "mode", "request_id", "idempotency_key"],
                    "additionalProperties": False,
                },
                ("HOOK:MANAGE",),
                "HOOK_MUTATION",
                lambda args: self._hook_create(args),
                mutating=True,
                approval_key="hook_manage",
            ),
            "aidn.hook.update": McpTool(
                "aidn.hook.update",
                "Plan or update an operator-owned Hook without changing its immutable event history.",
                {
                    "type": "object",
                    "properties": {
                        "hook_id": {"type": "string", "minLength": 1},
                        "enabled": {"type": "boolean"},
                        "target_agent_id": {"type": "string", "minLength": 1, "maxLength": 256},
                        "event_filter": hook_filter_schema,
                        "delivery_mode": {"enum": ["DURABLE_INBOX", "MCP_LIVE"]},
                        "max_attempts": {"type": "integer", "minimum": 1, "maximum": 10},
                        "retry_backoff_seconds": {"type": "number", "minimum": 0, "maximum": 3600},
                        "expires_at": {"type": ["string", "null"]},
                        **hook_mutation_fields,
                    },
                    "required": ["hook_id", "mode", "request_id", "idempotency_key"],
                    "additionalProperties": False,
                },
                ("HOOK:MANAGE",),
                "HOOK_MUTATION",
                lambda args: self._hook_update(args),
                mutating=True,
                approval_key="hook_manage",
            ),
            "aidn.hook.pause": McpTool(
                "aidn.hook.pause",
                "Plan or pause an operator-owned Hook; queued deliveries expire safely.",
                {
                    "type": "object",
                    "properties": {"hook_id": {"type": "string", "minLength": 1}, **hook_mutation_fields},
                    "required": ["hook_id", "mode", "request_id", "idempotency_key"],
                    "additionalProperties": False,
                },
                ("HOOK:MANAGE",),
                "HOOK_MUTATION",
                lambda args: self._hook_update({**args, "enabled": False}),
                mutating=True,
                approval_key="hook_manage",
            ),
            "aidn.hook.resume": McpTool(
                "aidn.hook.resume",
                "Plan or resume an operator-owned Hook subscription.",
                {
                    "type": "object",
                    "properties": {"hook_id": {"type": "string", "minLength": 1}, **hook_mutation_fields},
                    "required": ["hook_id", "mode", "request_id", "idempotency_key"],
                    "additionalProperties": False,
                },
                ("HOOK:MANAGE",),
                "HOOK_MUTATION",
                lambda args: self._hook_update({**args, "enabled": True}),
                mutating=True,
                approval_key="hook_manage",
            ),
            "aidn.hook.delete": McpTool(
                "aidn.hook.delete",
                "Plan or delete an operator-owned Hook subscription.",
                {
                    "type": "object",
                    "properties": {"hook_id": {"type": "string", "minLength": 1}, **hook_mutation_fields},
                    "required": ["hook_id", "mode", "request_id", "idempotency_key"],
                    "additionalProperties": False,
                },
                ("HOOK:MANAGE",),
                "HOOK_MUTATION",
                lambda args: self._hook_delete(args),
                mutating=True,
                approval_key="hook_manage",
            ),
            "aidn.hook.test": McpTool(
                "aidn.hook.test",
                "Run a synthetic Hook delivery readiness check without creating an event or inbox entry.",
                {
                    "type": "object",
                    "properties": {"hook_id": {"type": "string", "minLength": 1}},
                    "required": ["hook_id"],
                    "additionalProperties": False,
                },
                ("HOOK:MANAGE",),
                "HOOK_TEST",
                lambda args: self._hook_test(args),
            ),
            "aidn.hook.ack": McpTool(
                "aidn.hook.ack",
                "Acknowledge delivered Hook events in the current Agent Inbox.",
                {
                    "type": "object",
                    "properties": {
                        "hook_id": {"type": "string", "minLength": 1},
                        "event_ids": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 500,
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                    "required": ["hook_id", "event_ids"],
                    "additionalProperties": False,
                },
                ("HOOK:MANAGE",),
                "INBOX_ACK",
                lambda args: self._hook_ack(args),
            ),
            "aidn.hook.replay": McpTool(
                "aidn.hook.replay",
                "Plan or replay a retained event to all matching operator-owned Hooks.",
                {
                    "type": "object",
                    "properties": {"event_id": {"type": "string", "minLength": 1}, **hook_mutation_fields},
                    "required": ["event_id", "mode", "request_id", "idempotency_key"],
                    "additionalProperties": False,
                },
                ("HOOK:MANAGE",),
                "HOOK_MUTATION",
                lambda args: self._hook_replay(args),
                mutating=True,
                approval_key="hook_manage",
            ),
            "aidn.hook.dead_letter_retry": McpTool(
                "aidn.hook.dead_letter_retry",
                "Plan or retry one retained Hook dead-letter delivery.",
                {
                    "type": "object",
                    "properties": {"delivery_id": {"type": "string", "minLength": 1}, **hook_mutation_fields},
                    "required": ["delivery_id", "mode", "request_id", "idempotency_key"],
                    "additionalProperties": False,
                },
                ("HOOK:MANAGE",),
                "HOOK_MUTATION",
                lambda args: self._hook_dead_letter_retry(args),
                mutating=True,
                approval_key="hook_manage",
            ),
            "aidn.provider.attach": McpTool(
                "aidn.provider.attach",
                "Plan or attach one already reachable Provider endpoint through a validated built-in Plugin.",
                {
                    "type": "object",
                    "properties": {
                        "plugin_id": {"type": "string", "minLength": 1},
                        "display_name": {"type": "string", "minLength": 1},
                        "configuration": {"type": "object"},
                        "mode": {"enum": ["plan", "apply"]},
                        "request_id": {"type": "string", "minLength": 1},
                        "idempotency_key": {"type": "string", "minLength": 1},
                        "plan_hash": {"type": "string"},
                        "approval_reference": {"type": "string"},
                    },
                    "required": [
                        "plugin_id",
                        "display_name",
                        "configuration",
                        "mode",
                        "request_id",
                        "idempotency_key",
                    ],
                    "additionalProperties": False,
                },
                ("PROVIDER:WRITE",),
                "PROVIDER_MUTATION",
                lambda args: self._attach_provider(args),
                mutating=True,
                approval_key="provider_attach",
            ),
            "aidn.bundle.activate": McpTool(
                "aidn.bundle.activate",
                "Plan or activate one existing Bundle without editing its immutable revision.",
                {
                    "type": "object",
                    "properties": {
                        "bundle_id": {"type": "string", "minLength": 1},
                        "mode": {"enum": ["plan", "apply"]},
                        "request_id": {"type": "string", "minLength": 1},
                        "idempotency_key": {"type": "string", "minLength": 1},
                        "plan_hash": {"type": "string"},
                        "expected_revision": {"type": "string"},
                    },
                    "required": ["bundle_id", "mode", "request_id", "idempotency_key"],
                    "additionalProperties": False,
                },
                ("BUNDLE:ACTIVATE",),
                "SAFE_MUTATION",
                lambda args: self._activate_bundle(args),
                mutating=True,
                approval_key="bundle_activate",
            ),
            "aidn.bundle.retire": McpTool(
                "aidn.bundle.retire",
                "Plan or retire one Bundle; apply requires an explicit pre-authorized plan hash.",
                {
                    "type": "object",
                    "properties": {
                        "bundle_id": {"type": "string", "minLength": 1},
                        "mode": {"enum": ["plan", "apply"]},
                        "request_id": {"type": "string", "minLength": 1},
                        "idempotency_key": {"type": "string", "minLength": 1},
                        "plan_hash": {"type": "string"},
                        "expected_revision": {"type": "string"},
                        "approval_reference": {"type": "string"},
                    },
                    "required": ["bundle_id", "mode", "request_id", "idempotency_key"],
                    "additionalProperties": False,
                },
                ("BUNDLE:RETIRE",),
                "DISRUPTIVE_MUTATION",
                lambda args: self._retire_bundle(args),
                mutating=True,
                approval_key="bundle_retire",
            ),
        }

    def _build_resources(self) -> dict[str, McpResource]:
        return {
            "aidn://node/status": McpResource(
                "aidn://node/status",
                "Node status",
                "Local node operational summary.",
                "NODE:READ",
                lambda _uri: self._node_status(),
            ),
            "aidn://node/health": McpResource(
                "aidn://node/health",
                "Node health",
                "Sanitized node health report.",
                "NODE:READ",
                lambda _uri: self._node_health(),
            ),
            "aidn://node/profile": McpResource(
                "aidn://node/profile",
                "Node profile",
                "Node identity and advertised capabilities.",
                "NODE:READ",
                lambda _uri: self.service.node_identity(),
            ),
            "aidn://host/inventory": McpResource(
                "aidn://host/inventory",
                "Host inventory",
                "Non-secret host inventory.",
                "HOST:READ",
                lambda uri: self._host_inspect({}),
            ),
            "aidn://network/status": McpResource(
                "aidn://network/status",
                "Network status",
                "Network identity and synchronization state.",
                "NETWORK:READ",
                lambda _uri: self._network_status(),
            ),
            "aidn://network/peers": McpResource(
                "aidn://network/peers",
                "Network peers",
                "Known network peers.",
                "NETWORK:READ",
                lambda _uri: self._network_peers(),
            ),
            "aidn://providers": McpResource(
                "aidn://providers",
                "Providers",
                "Provider and runtime inventory.",
                "PROVIDER:READ",
                lambda _uri: build_operator_providers_payload(
                    service=self.service,
                    endpoint_service=self.endpoint_service,
                    endpoint_publication_service=self.endpoint_publication_service,
                    validation_service=self.validation_service,
                ),
            ),
            "aidn://runtime/operations": McpResource(
                "aidn://runtime/operations",
                "Runtime operations",
                "Live runtime readiness and Provider Broker installation progress.",
                "PROVIDER:READ",
                lambda _uri: build_runtime_operations_payload(service=self.service),
            ),
            "aidn://runtime/instances": McpResource(
                "aidn://runtime/instances",
                "Runtime instances",
                "Live Runtime Instance state and warm-retention controls.",
                "RUNTIME:READ",
                lambda _uri: self._runtime_instances(),
            ),
            "aidn://models": McpResource(
                "aidn://models",
                "Models",
                "Model deployments and install jobs.",
                "MODEL:READ",
                lambda _uri: {
                    "deployments": self.service.list_model_deployments(),
                    "installs": self.service.list_model_installs(),
                },
            ),
            "aidn://bundles": McpResource(
                "aidn://bundles",
                "Bundles",
                "Bundle revisions and runtime state.",
                "BUNDLE:READ",
                lambda _uri: build_operator_bundles_payload(
                    service=self.service,
                    endpoint_service=self.endpoint_service,
                    endpoint_publication_service=self.endpoint_publication_service,
                    validation_service=self.validation_service,
                ),
            ),
            "aidn://endpoints": McpResource(
                "aidn://endpoints",
                "Endpoints",
                "Endpoint configuration and publication state.",
                "ENDPOINT:READ",
                lambda _uri: build_operator_endpoints_payload(
                    service=self.service,
                    endpoint_service=self.endpoint_service,
                    endpoint_publication_service=self.endpoint_publication_service,
                    validation_service=self.validation_service,
                ),
            ),
            "aidn://resources/current": McpResource(
                "aidn://resources/current",
                "Current resources",
                "Current host resource reservations.",
                "RESOURCES:READ",
                lambda _uri: self._resource_status(),
            ),
            "aidn://resources/leases": McpResource(
                "aidn://resources/leases",
                "Resource leases",
                "Active Resource Broker leases.",
                "RESOURCES:READ",
                lambda _uri: self._resource_leases(),
            ),
            "aidn://resource-broker/status": McpResource(
                "aidn://resource-broker/status",
                "Resource Broker status",
                "Current Resource Broker capacity and reservations.",
                "RESOURCES:READ",
                lambda _uri: self._resource_status(),
            ),
            "aidn://resource-broker/devices": McpResource(
                "aidn://resource-broker/devices",
                "Resource Broker devices",
                "Hardware Monitor state for local devices and allocatable capacity.",
                "RESOURCES:READ",
                lambda _uri: self._resource_devices(),
            ),
            "aidn://resource-broker/leases": McpResource(
                "aidn://resource-broker/leases",
                "Resource Broker leases",
                "Active Resource Broker leases.",
                "RESOURCES:READ",
                lambda _uri: self._resource_leases(),
            ),
            "aidn://scheduler/policy": McpResource(
                "aidn://scheduler/policy",
                "Scheduler policy",
                "Local scheduler policy.",
                "SCHEDULER:READ",
                lambda _uri: self.service.operator_requests_policy(),
            ),
            "aidn://scheduler/status": McpResource(
                "aidn://scheduler/status",
                "Scheduler status",
                "Queue, Resource Broker, and fit-aware scheduler status.",
                "SCHEDULER:READ",
                lambda _uri: self._scheduler_status(),
            ),
            "aidn://scheduler/candidates": McpResource(
                "aidn://scheduler/candidates",
                "Scheduler candidates",
                "Current head candidate from every independent queue.",
                "SCHEDULER:READ",
                lambda _uri: {"items": self.service.scheduler_candidates()},
            ),
            "aidn://scheduler/queues": McpResource(
                "aidn://scheduler/queues",
                "Scheduler queues",
                "Independent scheduler queues and their current heads.",
                "SCHEDULER:READ",
                lambda _uri: self._scheduler_queues(),
            ),
            "aidn://wallet/summary": McpResource(
                "aidn://wallet/summary",
                "Wallet summary",
                "Public wallet and accounting summary.",
                "WALLET:READ",
                lambda _uri: self._wallet_summary(),
            ),
            "aidn://budgets": McpResource(
                "aidn://budgets",
                "Delegated budgets",
                "Budgets granted to this control session.",
                "BUDGET:READ",
                lambda _uri: self._budget_list(),
            ),
            "aidn://audit/recent": McpResource(
                "aidn://audit/recent",
                "Recent audit",
                "Recent hash-linked MCP audit events.",
                "AUDIT:READ",
                lambda _uri: self.audit.query(limit=100),
            ),
            "aidn://events/recent": McpResource(
                "aidn://events/recent",
                "Canonical events",
                "Recent retained canonical Hypervisor events.",
                "AUDIT:READ",
                lambda _uri: self.service.canonical_event_query(limit=100),
            ),
            "aidn://events/inbox": McpResource(
                "aidn://events/inbox",
                "Agent event Inbox",
                "Durable at-least-once event Inbox for this MCP agent.",
                "AUDIT:READ",
                lambda _uri: self.service.event_inbox(self.session.agent_identity),
            ),
            "aidn://hooks": McpResource(
                "aidn://hooks",
                "Hook subscriptions",
                "Operator-owned RFC-0072 Hook definitions and delivery modes.",
                "HOOK:READ",
                lambda _uri: {
                    "items": [
                        item.model_dump(mode="json")
                        for item in self._visible_hooks()
                    ]
                },
            ),
            "aidn://hooks/dead-letters": McpResource(
                "aidn://hooks/dead-letters",
                "Hook dead letters",
                "Retained Hook deliveries that exhausted bounded retries.",
                "HOOK:READ",
                lambda _uri: {
                    "items": [
                        item.model_dump(mode="json")
                        for item in self.service.hook_dead_letters()
                        if self._is_visible_delivery(item)
                    ],
                    "metrics": self.service.hook_dispatch_metrics(),
                },
            ),
            "aidn://capabilities": McpResource(
                "aidn://capabilities",
                "MCP capabilities",
                "Tools, resources, scopes, and security boundary.",
                "CAPABILITIES:READ",
                lambda _uri: self.capabilities(),
            ),
        }

    def _call_mutating(self, tool: McpTool, arguments: dict[str, Any]) -> Any:
        mode = arguments.get("mode")
        if mode not in {"plan", "apply"}:
            raise McpDomainError(
                "MCP_INVALID_MODE",
                "Mutating tools require mode=plan or mode=apply",
            )
        request_id = arguments.get("request_id")
        idempotency_key = arguments.get("idempotency_key")
        if not isinstance(request_id, str) or not request_id:
            raise McpDomainError("MCP_REQUEST_ID_REQUIRED", "request_id is required")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise McpDomainError("MCP_IDEMPOTENCY_KEY_REQUIRED", "idempotency_key is required")

        fingerprint = _hash_payload({"tool": tool.name, "arguments": self._plan_arguments(arguments)})
        cache_key = f"{self.session.control_session_id}:{idempotency_key}"
        cached = self._idempotency.get(cache_key)
        if cached is not None:
            cached_fingerprint, cached_result = cached
            if cached_fingerprint != fingerprint:
                raise McpDomainError(
                    "MCP_IDEMPOTENCY_CONFLICT",
                    "The idempotency key was already used with different arguments",
                )
            return cached_result

        plan = self._build_plan(tool, arguments)
        if mode == "plan":
            self.audit.append(
                event_type="MCP_PLAN_CREATED",
                agent_identity=self.session.agent_identity,
                operator_identity=self.session.operator_identity,
                tool=tool.name,
                request_id=request_id,
                action_class=tool.action_class,
                plan_hash=plan["plan_hash"],
                result="PLAN_CREATED",
            )
            return plan

        supplied_plan_hash = arguments.get("plan_hash")
        if supplied_plan_hash != plan["plan_hash"]:
            raise McpDomainError(
                "MCP_APPROVAL_HASH_MISMATCH",
                "apply must reference the current plan_hash",
                details={"expected_plan_hash": plan["plan_hash"]},
            )
        approval_mode = self.session.approval_policy.get(tool.approval_key or "", "AUTO")
        if approval_mode != "AUTO" and supplied_plan_hash not in self.session.approved_plan_hashes:
            raise McpDomainError(
                "MCP_APPROVAL_REQUIRED",
                "The plan requires an explicit operator approval before apply",
                details={
                    "plan_id": plan["plan_id"],
                    "plan_hash": plan["plan_hash"],
                    "approval_mode": approval_mode,
                },
            )

        result = tool.handler(arguments)
        audit_event = self.audit.append(
            event_type="MCP_TOOL_APPLIED",
            agent_identity=self.session.agent_identity,
            operator_identity=self.session.operator_identity,
            tool=tool.name,
            request_id=request_id,
            idempotency_key=idempotency_key,
            action_class=tool.action_class,
            target=(
                arguments.get("bundle_id")
                or arguments.get("endpoint_id")
                or arguments.get("runtime_id")
            ),
            plan_hash=plan["plan_hash"],
            approval_reference=arguments.get("approval_reference"),
            result="SUCCEEDED",
        )
        result = {
            **(_json_safe(result) if isinstance(result, dict) else {"result": _json_safe(result)}),
            "plan": plan,
            "audit_event_id": audit_event["audit_event_id"],
        }
        self._idempotency[cache_key] = (fingerprint, result)
        self._persist_state()
        return result

    def _build_plan(self, tool: McpTool, arguments: dict[str, Any]) -> dict[str, Any]:
        plan_arguments = self._plan_arguments(arguments)
        current_revision = self._target_revision(arguments, tool_name=tool.name)
        expected_revision = arguments.get("expected_revision")
        if expected_revision is not None and current_revision != expected_revision:
            raise McpDomainError(
                "MCP_CONFLICT_STALE_PLAN",
                "The target resource revision changed",
                details={"expected_revision": expected_revision, "current_revision": current_revision},
            )
        plan_body = {
            "tool": tool.name,
            "request_id": arguments.get("request_id"),
            "target": (
                arguments.get("bundle_id")
                or arguments.get("endpoint_id")
                or arguments.get("runtime_id")
            ),
            "arguments": plan_arguments,
            "expected_revision": expected_revision,
            "current_revision": current_revision,
            "changes": self._planned_changes(tool.name, arguments),
            "risks": self._planned_risks(tool.name),
            "requires_approval": self.session.approval_policy.get(tool.approval_key or "", "AUTO") != "AUTO",
            "estimated_downtime_seconds": 0 if tool.name.endswith("activate") else 30,
            "estimated_q_atoms": 0,
            "validation_impact": "UNCHANGED",
        }
        plan_hash = _hash_payload(plan_body)
        plan = {
            "plan_id": "plan_" + plan_hash.removeprefix("sha256:")[:24],
            "plan_hash": plan_hash,
            **plan_body,
        }
        self._plans[plan_hash] = plan
        return plan

    @staticmethod
    def _plan_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in arguments.items()
            if key not in {"mode", "plan_hash", "approval_reference", "idempotency_key"}
        }

    @staticmethod
    def _planned_changes(tool_name: str, arguments: dict[str, Any]) -> list[str]:
        bundle_id = arguments.get("bundle_id", "bundle")
        if tool_name == "aidn.bundle.activate":
            return [f"start runtime for Bundle {bundle_id}"]
        if tool_name == "aidn.bundle.retire":
            return [f"stop runtime and disable Bundle {bundle_id}"]
        if tool_name == "aidn.provider.attach":
            return [
                "attach one existing Provider endpoint",
                f"bind it to Plugin {arguments.get('plugin_id', 'unknown')}",
            ]
        if tool_name == "aidn.endpoint.create":
            return [
                "create a local Endpoint draft",
                f"pin it to Bundle {bundle_id} and Runtime Binding {arguments.get('runtime_binding_id', 'unknown')}",
            ]
        if tool_name == "aidn.endpoint.publish":
            return [
                f"publish Endpoint {arguments.get('endpoint_id', 'unknown')} through the canonical wallet path",
            ]
        if tool_name == "aidn.runtime.drain":
            return [
                f"drain Runtime Instance {arguments.get('runtime_id', 'unknown')} and reject new work",
            ]
        if tool_name == "aidn.runtime.stop":
            return [
                f"force-stop Runtime Instance {arguments.get('runtime_id', 'unknown')} and release its Resource Lease",
            ]
        if tool_name == "aidn.runtime.pin":
            return [
                f"pin Runtime Instance {arguments.get('runtime_id', 'unknown')} warm against idle eviction",
            ]
        if tool_name == "aidn.runtime.unpin":
            return [
                f"release the warm pin for Runtime Instance {arguments.get('runtime_id', 'unknown')}",
            ]
        if tool_name == "aidn.hook.create":
            return [
                f"create a {arguments.get('delivery_mode', 'DURABLE_INBOX')} Hook for Agent {arguments.get('target_agent_id', 'current-agent')}",
                "route matching canonical events through the configured retry policy",
            ]
        if tool_name in {"aidn.hook.update", "aidn.hook.pause", "aidn.hook.resume"}:
            action = "update" if tool_name == "aidn.hook.update" else tool_name.rsplit(".", 1)[-1]
            return [f"{action} Hook {arguments.get('hook_id', 'unknown')} without changing retained events"]
        if tool_name == "aidn.hook.delete":
            return [f"delete Hook {arguments.get('hook_id', 'unknown')} and stop future matching deliveries"]
        if tool_name == "aidn.hook.replay":
            return [f"replay retained event {arguments.get('event_id', 'unknown')} to matching Hooks"]
        if tool_name == "aidn.hook.dead_letter_retry":
            return [f"retry retained Hook dead letter {arguments.get('delivery_id', 'unknown')}"]
        return [tool_name]

    @staticmethod
    def _planned_risks(tool_name: str) -> list[str]:
        if tool_name == "aidn.bundle.retire":
            return ["active requests may be interrupted after the runtime stop"]
        if tool_name == "aidn.provider.attach":
            return ["the configured endpoint becomes available to local Runtime flows"]
        if tool_name == "aidn.endpoint.publish":
            return [
                "the Endpoint publication becomes visible to network discovery according to its publication policy",
            ]
        if tool_name == "aidn.runtime.stop":
            return ["active requests on the Runtime Instance may be interrupted"]
        if tool_name == "aidn.runtime.drain":
            return ["new work is rejected while existing requests drain"]
        if tool_name == "aidn.runtime.unpin":
            return ["normal warm-runtime eviction policy may reclaim the instance"]
        if tool_name == "aidn.hook.delete":
            return ["future events will no longer be delivered to this Hook"]
        if tool_name in {"aidn.hook.replay", "aidn.hook.dead_letter_retry"}:
            return ["an existing event may be delivered again; Agents must deduplicate by event_id"]
        return []

    def _attach_provider(self, arguments: dict[str, Any]) -> dict[str, Any]:
        plugin_id = self._required_string(arguments, "plugin_id")
        display_name = self._required_string(arguments, "display_name")
        configuration = arguments.get("configuration")
        if not isinstance(configuration, dict):
            raise McpDomainError(
                "MCP_INVALID_ARGUMENTS",
                "configuration must be a JSON object",
            )
        if arguments.get("mode") == "plan":
            return self._build_plan(self._tools["aidn.provider.attach"], arguments)
        instance = self.service.attach_provider_instance(
            plugin_id=plugin_id,
            display_name=display_name,
            configuration=configuration,
        )
        return {
            "provider_instance": _json_safe(instance),
            "status": "attached",
        }

    def _activate_bundle(self, arguments: dict[str, Any]) -> dict[str, Any]:
        bundle_id = self._required_string(arguments, "bundle_id")
        if arguments.get("mode") == "plan":
            return self._build_plan(self._tools["aidn.bundle.activate"], arguments)
        existing_runtime = self.service._runtime_for_bundle(bundle_id)
        if existing_runtime is not None:
            return {
                "bundle_id": bundle_id,
                "runtime": _json_safe(existing_runtime),
                "status": "already_activated",
            }
        runtime = self.service.start_bundle(bundle_id)
        return {"bundle_id": bundle_id, "runtime": _json_safe(runtime), "status": "activated"}

    def _retire_bundle(self, arguments: dict[str, Any]) -> dict[str, Any]:
        bundle_id = self._required_string(arguments, "bundle_id")
        if arguments.get("mode") == "plan":
            return self._build_plan(self._tools["aidn.bundle.retire"], arguments)
        # Retirement is deliberately idempotent.  A stopped Bundle is still a
        # valid retirement target; ``stop_bundle`` historically raised a
        # KeyError when no runtime existed, which leaked as MCP_INTERNAL_ERROR
        # and made a safe retry impossible.
        runtime = self.service._runtime_for_bundle(bundle_id)
        if runtime is None:
            stopped = {"bundle_id": bundle_id, "status": "already_stopped"}
        else:
            try:
                stopped = self.service.stop_bundle(bundle_id)
            except KeyError:
                # A runtime may disappear between the read and the stop call.
                # Treat that race as the same idempotent state, but preserve a
                # genuine KeyError from an inconsistent runtime registry.
                if self.service._runtime_for_bundle(bundle_id) is not None:
                    raise
                stopped = {"bundle_id": bundle_id, "status": "already_stopped"}
        disabled = self.service.set_bundle_enabled(bundle_id, False)
        return {"bundle_id": bundle_id, "runtime": stopped, "bundle": disabled, "status": "retired"}

    def _create_endpoint(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.endpoint_application_service is None:
            raise McpDomainError(
                "MCP_ENDPOINTS_UNAVAILABLE",
                "Endpoint application service is not configured",
            )
        runtime_binding_id = self._required_string(arguments, "runtime_binding_id")
        bundle_id = self._required_string(arguments, "bundle_id")
        display_name = self._required_string(arguments, "display_name")
        wallet = self.service.owner_wallet_state()
        if not wallet.get("configured") or not wallet.get("wallet_id"):
            raise McpDomainError(
                "MCP_ENDPOINT_OWNER_WALLET_REQUIRED",
                "Owner wallet must be configured before creating an Endpoint draft",
            )

        bundle = next(
            (item for item in self.service.bundle_config() if item.bundle_id == bundle_id),
            None,
        )
        if bundle is None:
            raise McpDomainError("MCP_BUNDLE_NOT_FOUND", f"Bundle not found: {bundle_id}")
        bindings = self.service.list_runtime_bindings()
        binding = next(
            (
                item
                for item in bindings
                if isinstance(item, dict)
                and item.get("runtime_binding_id") == runtime_binding_id
            ),
            None,
        )
        if binding is None:
            raise McpDomainError(
                "MCP_RUNTIME_BINDING_NOT_FOUND",
                f"Runtime Binding not found: {runtime_binding_id}",
            )
        model_class = arguments.get("model_class") or binding.get("capability_id")
        if not isinstance(model_class, str) or not model_class:
            raise McpDomainError(
                "MCP_INVALID_ARGUMENTS",
                "model_class is required when the Runtime Binding has no capability_id",
            )
        capabilities = arguments.get("capabilities")
        if capabilities is None:
            capabilities = [model_class]
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) and item for item in capabilities
        ):
            raise McpDomainError(
                "MCP_INVALID_ARGUMENTS",
                "capabilities must be a list of non-empty strings",
            )

        payload: dict[str, Any] = {
            "owner_wallet": str(wallet["wallet_id"]),
            "runtime_binding_id": runtime_binding_id,
            "bundle_id": bundle_id,
            "bundle_hash": str(bundle.bundle_hash or bundle_config_hash(bundle)),
            "display_name": display_name,
            "model_class": model_class,
            "capabilities": capabilities,
        }
        for field_name in (
            "runtime_parameter_policy",
            "profile",
            "runtime",
            "publication",
            "pricing",
            "session",
            "validation",
        ):
            value = arguments.get(field_name)
            if value is not None:
                if not isinstance(value, dict):
                    raise McpDomainError(
                        "MCP_INVALID_ARGUMENTS",
                        f"{field_name} must be a JSON object",
                    )
                payload[field_name] = value

        # Validate admission before mutating state so an Agent receives a
        # useful readiness report instead of a generic Pydantic error.
        admission = self.service.runtime_binding_endpoint_admission(
            runtime_binding_id,
            endpoint_payload=payload,
        )
        if not admission.get("ready"):
            raise McpDomainError(
                "MCP_ENDPOINT_ADMISSION_BLOCKED",
                "Runtime Binding is not ready for Endpoint creation",
                details=admission,
            )
        result = self.endpoint_application_service.create_endpoint(payload)
        endpoint = result["created"].endpoint
        if arguments.get("local_agent_use") is True:
            endpoint = self.endpoint_service.set_local_agent_use(
                endpoint.endpoint_id,
                enabled=True,
            ).endpoint
        return {
            "status": "created",
            "endpoint": _json_safe(endpoint),
            "snapshot": _json_safe(result["created"].snapshot),
            "onboarding": _json_safe(result.get("onboarding")),
        }

    def _publish_endpoint(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.endpoint_application_service is None:
            raise McpDomainError(
                "MCP_ENDPOINTS_UNAVAILABLE",
                "Endpoint application service is not configured",
            )
        endpoint_id = self._required_string(arguments, "endpoint_id")
        try:
            return self.endpoint_application_service.publish_endpoint(endpoint_id)
        except EndpointPublicationReadinessError as error:
            raise McpDomainError(
                "MCP_ENDPOINT_PUBLICATION_BLOCKED",
                str(error),
                details=error.readiness,
            ) from error

    def _visible_hooks(self, *, owner_operator_id: str | None = None) -> list[Any]:
        """Return only Hooks visible to this Agent Control Session."""

        requested_owner = owner_operator_id or self.session.operator_identity
        if requested_owner != self.session.operator_identity:
            raise McpDomainError(
                "MCP_PERMISSION_DENIED",
                "An Agent may only inspect Hooks owned by its bound operator",
            )
        return [
            hook
            for hook in self.service.list_hooks(owner_operator_id=requested_owner)
            if hook.target_agent_id == self.session.agent_identity
        ]

    def _owned_hook(self, arguments: dict[str, Any]) -> Any:
        hook_id = self._required_string(arguments, "hook_id")
        try:
            hook = self.service.get_hook(hook_id)
        except ValueError as error:
            raise McpDomainError("MCP_HOOK_NOT_FOUND", str(error)) from error
        if hook.owner_operator_id != self.session.operator_identity or hook.target_agent_id != self.session.agent_identity:
            raise McpDomainError(
                "MCP_PERMISSION_DENIED",
                "The current Agent is not authorized for this Hook",
            )
        return hook

    def _is_visible_delivery(self, delivery: Any) -> bool:
        try:
            hook = self.service.get_hook(delivery.hook_id)
        except ValueError:
            return False
        return (
            hook.owner_operator_id == self.session.operator_identity
            and hook.target_agent_id == self.session.agent_identity
        )

    def _hook_get(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hook = self._owned_hook(arguments)
        deliveries = self.service.hook_deliveries(hook_id=hook.hook_id, limit=25)
        return {
            "hook": _json_safe(hook),
            "deliveries": [item.model_dump(mode="json") for item in deliveries],
        }

    def _hook_create(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hook_id = self._required_string(arguments, "hook_id")
        target_agent_id = arguments.get("target_agent_id", self.session.agent_identity)
        if target_agent_id != self.session.agent_identity:
            raise McpDomainError(
                "MCP_PERMISSION_DENIED",
                "A remote Agent may only create a Hook for its own Agent identity",
            )
        event_filter = arguments.get("event_filter")
        if not isinstance(event_filter, dict):
            raise McpDomainError("MCP_INVALID_ARGUMENTS", "event_filter must be a JSON object")
        if arguments.get("mode") == "plan":
            return self._build_plan(self._tools["aidn.hook.create"], arguments)
        payload = {
            "hook_id": hook_id,
            "owner_operator_id": self.session.operator_identity,
            "target_agent_id": target_agent_id,
            "event_filter": event_filter,
            "delivery_mode": arguments.get("delivery_mode", "DURABLE_INBOX"),
            "max_attempts": arguments.get("max_attempts", 3),
            "retry_backoff_seconds": arguments.get("retry_backoff_seconds", 1.0),
            "expires_at": arguments.get("expires_at"),
        }
        hook = self.service.create_hook(**payload)
        return {"status": "created", "hook": _json_safe(hook)}

    def _hook_update(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hook = self._owned_hook(arguments)
        if arguments.get("mode") == "plan":
            return self._build_plan(self._tools["aidn.hook.update"], arguments)
        updates = {
            key: arguments[key]
            for key in (
                "enabled",
                "event_filter",
                "delivery_mode",
                "max_attempts",
                "retry_backoff_seconds",
                "expires_at",
            )
            if key in arguments
        }
        if "target_agent_id" in arguments:
            if arguments["target_agent_id"] != self.session.agent_identity:
                raise McpDomainError(
                    "MCP_PERMISSION_DENIED",
                    "A remote Agent may only keep a Hook bound to its own identity",
                )
            updates["target_agent_id"] = arguments["target_agent_id"]
        updated = self.service.update_hook(hook.hook_id, **updates)
        return {"status": "updated", "hook": _json_safe(updated)}

    def _hook_delete(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hook = self._owned_hook(arguments)
        if arguments.get("mode") == "plan":
            return self._build_plan(self._tools["aidn.hook.delete"], arguments)
        self.service.delete_hook(hook.hook_id)
        return {"status": "deleted", "hook_id": hook.hook_id}

    def _hook_test(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hook = self._owned_hook(arguments)
        return self.service.test_hook(hook.hook_id)

    def _hook_ack(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hook = self._owned_hook(arguments)
        event_ids = arguments.get("event_ids")
        if not isinstance(event_ids, list) or not event_ids or not all(
            isinstance(item, str) and item for item in event_ids
        ):
            raise McpDomainError("MCP_INVALID_ARGUMENTS", "event_ids must be a non-empty string list")
        return self.service.acknowledge_event_inbox(hook.target_agent_id, event_ids)

    def _hook_replay(self, arguments: dict[str, Any]) -> dict[str, Any]:
        event_id = self._required_string(arguments, "event_id")
        if arguments.get("mode") == "plan":
            return self._build_plan(self._tools["aidn.hook.replay"], arguments)
        deliveries = self.service.replay_hook_event(
            event_id,
            owner_operator_id=self.session.operator_identity,
            target_agent_id=self.session.agent_identity,
        )
        return {
            "status": "replayed",
            "event_id": event_id,
            "deliveries": [item.model_dump(mode="json") for item in deliveries],
        }

    def _hook_dead_letter_retry(self, arguments: dict[str, Any]) -> dict[str, Any]:
        delivery_id = self._required_string(arguments, "delivery_id")
        delivery = next(
            (item for item in self.service.hook_dead_letters(limit=500) if item.delivery_id == delivery_id),
            None,
        )
        if delivery is None or not self._is_visible_delivery(delivery):
            raise McpDomainError("MCP_HOOK_REPLAY_UNAVAILABLE", f"Unknown dead letter: {delivery_id}")
        if arguments.get("mode") == "plan":
            return self._build_plan(self._tools["aidn.hook.dead_letter_retry"], arguments)
        retried = self.service.retry_hook_dead_letter(delivery_id)
        return {"status": "retrying", "delivery": _json_safe(retried)}

    def _target_revision(self, arguments: dict[str, Any], *, tool_name: str | None = None) -> str | None:
        bundle_id = arguments.get("bundle_id")
        if bundle_id:
            return self._bundle_revision(bundle_id)
        endpoint_id = arguments.get("endpoint_id")
        hook_id = arguments.get("hook_id")
        if hook_id:
            if tool_name == "aidn.hook.create":
                return None
            hook = self._owned_hook(arguments)
            return _hash_payload(_json_safe(hook))
        runtime_id = arguments.get("runtime_id")
        if runtime_id:
            return self._runtime_revision(runtime_id)
        if not endpoint_id:
            return None
        if self.endpoint_service is None:
            raise McpDomainError(
                "MCP_ENDPOINTS_UNAVAILABLE",
                "Endpoint service is not configured",
            )
        try:
            endpoint = self.endpoint_service.get_endpoint(endpoint_id).endpoint
        except KeyError as error:
            raise McpDomainError(
                "MCP_ENDPOINT_NOT_FOUND",
                f"Endpoint not found: {endpoint_id}",
            ) from error
        return endpoint.configuration_hash

    def _runtime_revision(self, runtime_id: str) -> str:
        try:
            runtime = next(
                item
                for item in self.service.list_runtimes()
                if item.runtime_id == runtime_id
            )
        except StopIteration as error:
            raise McpDomainError(
                "MCP_RUNTIME_NOT_FOUND",
                f"Runtime Instance not found: {runtime_id}",
            ) from error
        return _hash_payload(_json_safe(runtime))

    def _bundle_revision(self, bundle_id: str | None) -> str | None:
        if not bundle_id:
            return None
        bundle = next((item for item in self.service.bundles if item.bundle_id == bundle_id), None)
        if bundle is None:
            raise McpDomainError("MCP_BUNDLE_NOT_FOUND", f"Bundle not found: {bundle_id}")
        return _hash_payload(_json_safe(bundle))

    def _bundle_get(self, arguments: dict[str, Any]) -> dict[str, Any]:
        bundle_id = self._required_string(arguments, "bundle_id")
        bundle = next((item for item in self.service.bundles if item.bundle_id == bundle_id), None)
        if bundle is None:
            raise McpDomainError("MCP_BUNDLE_NOT_FOUND", f"Bundle not found: {bundle_id}")
        # ``bundle.get`` is a read-only tool, but runtime readiness is an
        # external fact.  Reconcile it before serializing the object so MCP
        # clients do not poll a permanently stale ``starting/unknown`` value.
        self.service.refresh_runtime_health(bundle_id)
        runtime = self.service._runtime_for_bundle(bundle_id)
        return {
            "bundle": _json_safe(bundle),
            "revision": self._bundle_revision(bundle_id),
            "runtime": _json_safe(runtime),
            "state": self.service.bundle_state(bundle_id),
        }

    def _node_status(self) -> dict[str, Any]:
        # Keep the MCP node summary on the same canonical operator read model
        # as ``aidn.bundle.list``.  The legacy fleet payload contains useful
        # runtime facts, but its persisted onboarding field can lag behind the
        # endpoint publication projection (for example after a consensus
        # finality update).  Reusing the bundle projection makes status reads
        # reflect the endpoint state that operators and the dashboard see.
        bundle_payload = build_operator_bundles_payload(
            service=self.service,
            endpoint_service=self.endpoint_service,
            endpoint_publication_service=self.endpoint_publication_service,
            validation_service=self.validation_service,
        )
        return {
            "node": self.service.node_identity(),
            "queue": self.service.queue_summary(),
            "resources": self._resource_status(),
            "bundles": bundle_payload.get("items", []),
            "onboarding": bundle_payload.get(
                "onboarding", self.service.operator_onboarding_state()
            ),
        }

    def _node_health(self) -> dict[str, Any]:
        status = self._node_status()
        runtimes = status["bundles"]
        unhealthy = [
            item["bundle_id"]
            for item in runtimes
            if (
                item.get("runtime_status") not in {"running", "healthy", "starting", "stopped"}
                or item.get("runtime_health_status") in {"unhealthy", "cooldown"}
            )
        ]
        return {
            "status": "degraded" if unhealthy else "healthy",
            "node_id": self.service.node_id,
            "unhealthy_bundles": unhealthy,
            "queue": status["queue"],
            "resources": status["resources"],
        }

    def _network_status(self) -> dict[str, Any]:
        advertisement = self.service.node_advertisement()
        consensus = self.service.consensus_service
        consensus_status = (
            consensus.status() if callable(getattr(consensus, "status", None)) else None
        )
        return {
            "node_id": self.service.node_id,
            "network": _json_safe(advertisement),
            "registry_enabled": self.service.registry_enabled(),
            "consensus": _json_safe(consensus_status),
        }

    def _network_peers(self) -> dict[str, Any]:
        if self.registry_service is None:
            return {"items": [], "available": False}
        list_peers = getattr(self.registry_service, "list_peers", None)
        if callable(list_peers):
            return {"items": _json_safe(list_peers()), "available": True}
        return {"items": [], "available": False}

    def _host_inspect(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root = Path(str(arguments.get("path") or os.environ.get("AIDN_MCP_HOST_ROOT") or Path.cwd()))
        root = root.expanduser().resolve()
        usage = shutil.disk_usage(root) if root.exists() else None
        return {
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            },
            "cpu_count": os.cpu_count(),
            "root": str(root),
            "disk": {
                "total_bytes": usage.total,
                "free_bytes": usage.free,
                "used_bytes": usage.used,
            }
            if usage is not None
            else None,
            "gpu": {"status": "not_probed_by_mcp"},
            "shell": {"available": False, "reason": "EXPERT_SHELL is not exposed by this server"},
        }

    def _resource_status(self) -> dict[str, Any]:
        resources = self.service.resources
        return resources.summary() if resources is not None else {"available": False}

    def _resource_devices(self) -> dict[str, Any]:
        resources = self.service.resources
        return resources.hardware_status() if resources is not None else {"available": False}

    def _resource_forecast(self, arguments: dict[str, Any]) -> dict[str, Any]:
        resources = self.service.resources
        if resources is None:
            return {"available": False}
        cpu = arguments.get("cpu", 0.0)
        ram_mb = arguments.get("ram_mb", 0)
        vram_mb = arguments.get("vram_mb", 0)
        if isinstance(cpu, bool) or not isinstance(cpu, (int, float)):
            raise McpDomainError("MCP_INVALID_ARGUMENTS", "cpu must be a non-negative number")
        if isinstance(ram_mb, bool) or not isinstance(ram_mb, int) or ram_mb < 0:
            raise McpDomainError("MCP_INVALID_ARGUMENTS", "ram_mb must be a non-negative integer")
        if isinstance(vram_mb, bool) or not isinstance(vram_mb, int) or vram_mb < 0:
            raise McpDomainError("MCP_INVALID_ARGUMENTS", "vram_mb must be a non-negative integer")
        if cpu < 0:
            raise McpDomainError("MCP_INVALID_ARGUMENTS", "cpu must be a non-negative number")
        return resources.forecast(cpu=float(cpu), ram_mb=ram_mb, vram_mb=vram_mb)

    def _resource_leases(self) -> dict[str, Any]:
        resources = self.service.resources
        return {
            "items": resources.lease_snapshot() if resources is not None else [],
            "details": resources.lease_details() if resources is not None else [],
            "available": resources is not None,
        }

    def _scheduler_status(self) -> dict[str, Any]:
        return self.service.scheduler_status()

    def _scheduler_candidates(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = arguments.get("limit", 200)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise McpDomainError(
                "MCP_INVALID_ARGUMENTS",
                "limit must be an integer between 1 and 500",
            )
        return {"items": self.service.scheduler_candidates(limit=limit), "limit": limit}

    def _scheduler_explain_decision(self, arguments: dict[str, Any]) -> dict[str, Any]:
        task_id = arguments.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise McpDomainError(
                "MCP_INVALID_ARGUMENTS",
                "task_id must be a non-empty string",
            )
        try:
            return self.service.scheduler_explain_decision(task_id)
        except KeyError as error:
            raise McpDomainError(
                "MCP_TASK_NOT_FOUND",
                f"Task not found: {task_id}",
            ) from error

    def _scheduler_queues(self) -> dict[str, Any]:
        items = []
        for candidate in self.service.scheduler_candidates():
            items.append(
                {
                    "queue_key": candidate["queue_key"],
                    "endpoint_id": candidate.get("endpoint_id"),
                    "bundle_id": candidate.get("bundle_id"),
                    "depth": candidate["queue_depth"],
                    "head_task_id": candidate["task_id"],
                    "head_status": candidate["status"],
                }
            )
        return {"items": items}

    def _runtime_instances(self) -> dict[str, Any]:
        """Return the live Runtime Instance projection without install-job noise."""

        payload = build_runtime_operations_payload(service=self.service)
        return {
            "generated_at": payload.get("generated_at"),
            "freshness": payload.get("freshness", {}),
            "summary": payload.get("summary", {}),
            "instances": payload.get("runtimes", []),
        }

    def _drain_runtime(self, arguments: dict[str, Any]) -> dict[str, Any]:
        runtime_id = self._required_string(arguments, "runtime_id")
        if arguments.get("mode") == "plan":
            return self._build_plan(self._tools["aidn.runtime.drain"], arguments)
        return _json_safe(self.service.drain_runtime(runtime_id))

    def _stop_runtime(self, arguments: dict[str, Any]) -> dict[str, Any]:
        runtime_id = self._required_string(arguments, "runtime_id")
        if arguments.get("mode") == "plan":
            return self._build_plan(self._tools["aidn.runtime.stop"], arguments)
        return _json_safe(self.service.force_stop_runtime(runtime_id))

    def _pin_runtime(self, arguments: dict[str, Any]) -> dict[str, Any]:
        runtime_id = self._required_string(arguments, "runtime_id")
        if arguments.get("mode") == "plan":
            return self._build_plan(self._tools["aidn.runtime.pin"], arguments)
        return _json_safe(self.service.set_runtime_pinned_warm(runtime_id, True))

    def _unpin_runtime(self, arguments: dict[str, Any]) -> dict[str, Any]:
        runtime_id = self._required_string(arguments, "runtime_id")
        if arguments.get("mode") == "plan":
            return self._build_plan(self._tools["aidn.runtime.unpin"], arguments)
        return _json_safe(self.service.set_runtime_pinned_warm(runtime_id, False))

    def _reconcile_scheduler(self, arguments: dict[str, Any]) -> dict[str, Any]:
        trigger = arguments.get("trigger", "mcp")
        if not isinstance(trigger, str) or not trigger.strip():
            raise McpDomainError(
                "MCP_INVALID_ARGUMENTS",
                "trigger must be a non-empty string",
            )
        max_cycles = arguments.get("max_cycles", 128)
        if (
            isinstance(max_cycles, bool)
            or not isinstance(max_cycles, int)
            or not 1 <= max_cycles <= 1024
        ):
            raise McpDomainError(
                "MCP_INVALID_ARGUMENTS",
                "max_cycles must be an integer between 1 and 1024",
            )
        return self.service.reconcile_scheduler(
            trigger=trigger,
            max_cycles=max_cycles,
        )

    def _wallet_summary(self) -> dict[str, Any]:
        return {
            "owner_wallet": self.service.owner_wallet_state(),
            "node_identity": self.service.node_identity(),
            "economics": self.service.get_wallet_economics_summary(recent_limit=10),
        }

    def _budget_list(self) -> dict[str, Any]:
        return {"items": [self.session.budget.public()] if self.session.budget else []}

    def _budget_status(self) -> dict[str, Any]:
        return self.session.budget.public() if self.session.budget else {"configured": False}

    @staticmethod
    def _required_string(arguments: dict[str, Any], key: str) -> str:
        value = arguments.get(key)
        if not isinstance(value, str) or not value:
            raise McpDomainError("MCP_INVALID_ARGUMENTS", f"{key} is required")
        return value

    def _resolve_resource(self, uri: str) -> McpResource:
        direct = self._resources.get(uri)
        if direct is not None:
            return direct
        if uri.startswith("aidn://bundle/"):
            bundle_id = uri.removeprefix("aidn://bundle/")
            return McpResource(
                uri,
                "Bundle",
                "Parameterized Bundle resource.",
                "BUNDLE:READ",
                lambda _uri: self._bundle_get({"bundle_id": bundle_id}),
            )
        raise McpDomainError("MCP_RESOURCE_NOT_FOUND", f"Resource not found: {uri}")

    @staticmethod
    def _map_domain_error(tool_name: str, error: Exception) -> str:
        message = str(error).lower()
        if "runtime" in message and "not active" in message:
            return "MCP_RUNTIME_NOT_ACTIVE"
        if "runtime" in message and "not found" in message:
            return "MCP_RUNTIME_NOT_FOUND"
        if "bundle" in message and "not" in message:
            return "MCP_BUNDLE_NOT_FOUND"
        if "insufficient" in message or "resource" in message:
            return "MCP_BUNDLE_RESOURCE_UNSATISFIED"
        return "MCP_INTERNAL_ERROR"


class McpJsonRpcServer:
    """JSON-RPC MCP lifecycle and stdio transport."""

    def __init__(self, control: McpControlPlane) -> None:
        self.control = control
        self.initialized = False
        self.client_protocol_version: str | None = None

    def handle_message(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return self._error(None, JSONRPC_INVALID_REQUEST, "Invalid JSON-RPC request")
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if not isinstance(method, str) or not isinstance(params, dict):
            return self._error(request_id, JSONRPC_INVALID_REQUEST, "Invalid JSON-RPC request")
        if method.startswith("notifications/"):
            if method == "notifications/initialized":
                self.initialized = True
            return None
        try:
            result = self._dispatch(method, params)
        except McpDomainError as error:
            return self._error(request_id, JSONRPC_INVALID_PARAMS, error.message, error.as_dict())
        except Exception as error:  # pragma: no cover - defensive transport boundary
            return self._error(
                request_id, JSONRPC_INTERNAL_ERROR, "Internal MCP server error", {"type": type(error).__name__}
            )
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            requested = params.get("protocolVersion")
            if requested in SUPPORTED_MCP_PROTOCOL_VERSIONS:
                self.client_protocol_version = requested
            elif requested is None:
                self.client_protocol_version = MCP_PROTOCOL_VERSION
            else:
                raise McpDomainError(
                    "MCP_UNSUPPORTED_VERSION",
                    f"Unsupported MCP protocol version: {requested}",
                )
            return {
                "protocolVersion": self.client_protocol_version,
                "capabilities": {
                    "tools": {"listChanged": True},
                    "resources": {"subscribe": False, "listChanged": False},
                },
                "serverInfo": {"name": "aidn-node-control", "version": MCP_SERVER_VERSION},
                "instructions": (
                    "Permission changes are applied to the active MCP transport session. "
                    "Call aidn.capabilities.get or aidn.mcp.session_status after a scope change; "
                    "call tools/list when tool_catalog_revision changes. "
                    "If MCP_REMOTE_SESSION_NOT_FOUND is returned, "
                    "discard Mcp-Session-Id, initialize again, send notifications/initialized, "
                    "then call tools/list. Do not restart the gateway. "
                    "Use plan before apply for mutations."
                ),
            }
        if method == "ping":
            # Keep the standard liveness response backwards-compatible while
            # exposing a read-only catalog marker. Long-lived clients can
            # compare this revision with their last tools/list snapshot and
            # refresh after a node upgrade or live scope change.
            return {
                "_meta": {
                    "tool_catalog_revision": self.control.tool_catalog_metadata()["revision"],
                },
            }
        if not self.initialized:
            raise McpDomainError("MCP_NOT_INITIALIZED", "The MCP session is not initialized")
        if method == "tools/list":
            return {
                "tools": self.control.tool_definitions(),
                "_meta": {"tool_catalog": self.control.tool_catalog_metadata()},
            }
        if method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str):
                raise McpDomainError("MCP_INVALID_ARGUMENTS", "tools/call requires a tool name")
            return self.control.call_tool(name, params.get("arguments"))
        if method == "resources/list":
            return {"resources": self.control.resource_definitions()}
        if method == "resources/read":
            uri = params.get("uri")
            if not isinstance(uri, str):
                raise McpDomainError("MCP_INVALID_ARGUMENTS", "resources/read requires a URI")
            return self.control.read_resource(uri)
        raise McpDomainError("MCP_METHOD_NOT_FOUND", f"Unsupported MCP method: {method}")

    @staticmethod
    def _error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = _json_safe(data)
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    def run_stdio(self, *, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
        input_stream = stdin or sys.stdin
        output_stream = stdout or sys.stdout
        for line in input_stream:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                response = self._error(None, JSONRPC_INVALID_REQUEST, "Invalid JSON")
            else:
                response = self.handle_message(message)
            if response is not None:
                output_stream.write(_canonical_json(response) + "\n")
                output_stream.flush()


from aidn_hypervisor.mcp.steward_tools import install_steward_extensions  # noqa: E402

install_steward_extensions(McpControlPlane, McpTool, McpResource)


def build_mcp_server(
    service,
    *,
    endpoint_service=None,
    endpoint_publication_service=None,
    validation_service=None,
    registry_service=None,
    session: ControlSession | None = None,
    mcp_state_store: McpPersistentStateStore | None = None,
    control_session_auto_renew: bool | None = None,
    control_session_ttl_seconds: int | None = None,
    control_session_stateless: bool | None = None,
) -> McpJsonRpcServer:
    """Build an MCP server around an already constructed Hypervisor service."""

    resolved_auto_renew = (
        _env_bool("AIDN_MCP_CONTROL_SESSION_AUTO_RENEW", default=False)
        if control_session_auto_renew is None
        else control_session_auto_renew
    )
    resolved_ttl_seconds = (
        int(os.environ.get("AIDN_MCP_CONTROL_SESSION_TTL_SECONDS", DEFAULT_CONTROL_SESSION_TTL_SECONDS))
        if control_session_ttl_seconds is None
        else control_session_ttl_seconds
    )
    resolved_stateless = (
        _env_bool("AIDN_MCP_CONTROL_SESSION_STATELESS", default=False)
        if control_session_stateless is None
        else control_session_stateless
    )
    resolved_session = session or ControlSession(
        control_session_id=os.environ.get("AIDN_MCP_CONTROL_SESSION_ID", "acs-local-default"),
        agent_identity=os.environ.get("AIDN_MCP_AGENT_IDENTITY", "agent:local"),
        operator_identity=os.environ.get("AIDN_MCP_OPERATOR_IDENTITY", service.operator_id),
        scopes=frozenset(
            item.strip()
            for item in os.environ.get(
                "AIDN_MCP_SCOPES",
                "CAPABILITIES:READ,HOST:READ,NODE:READ,NETWORK:READ,PROVIDER:READ,RUNTIME:READ,MODEL:READ,BUNDLE:READ,ENDPOINT:READ,RESOURCES:READ,SCHEDULER:READ,WALLET:READ,BUDGET:READ,AUDIT:READ",
            ).split(",")
            if item.strip()
        ),
        expires_at=(
            None
            if resolved_stateless
            else _now() + timedelta(seconds=resolved_ttl_seconds)
        ),
        approval_policy={
            "bundle_activate": "AUTO",
            "bundle_retire": "OPERATOR_CONFIRMATION",
            "provider_attach": "OPERATOR_CONFIRMATION",
            "endpoint_write": "OPERATOR_CONFIRMATION",
            "runtime_control": "OPERATOR_CONFIRMATION",
        },
    )
    control = McpControlPlane(
        service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
        registry_service=registry_service,
        session=resolved_session,
        mcp_state_store=mcp_state_store,
        control_session_auto_renew=resolved_auto_renew,
        control_session_ttl_seconds=resolved_ttl_seconds,
        control_session_stateless=resolved_stateless,
    )
    return McpJsonRpcServer(control)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AiDN node-control MCP server over stdio")
    parser.add_argument("--agent-identity", default=os.environ.get("AIDN_MCP_AGENT_IDENTITY", "agent:local"))
    parser.add_argument("--operator-identity", default=os.environ.get("AIDN_MCP_OPERATOR_IDENTITY"))
    parser.add_argument("--control-session-id", default=os.environ.get("AIDN_MCP_CONTROL_SESSION_ID"))
    parser.add_argument("--scope", action="append", dest="scopes", default=None)
    parser.add_argument("--expires-in-seconds", type=int, default=3600)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    load_operator_config()
    args = _parse_args(argv)
    from aidn_hypervisor.main import build_app

    app = build_app()
    service = app.state.hypervisor_service
    default_scopes = {
        "CAPABILITIES:READ",
        "HOST:READ",
        "NODE:READ",
        "NETWORK:READ",
        "PROVIDER:READ",
        "RUNTIME:READ",
        "MODEL:READ",
        "BUNDLE:READ",
        "ENDPOINT:READ",
        "RESOURCES:READ",
        "SCHEDULER:READ",
        "WALLET:READ",
        "BUDGET:READ",
        "AUDIT:READ",
    }
    session = ControlSession(
        control_session_id=args.control_session_id
        or "acs-cli-"
        + hashlib.sha256(
            f"{args.agent_identity}\n{args.operator_identity or service.operator_id}".encode()
        ).hexdigest()[:16],
        agent_identity=args.agent_identity,
        operator_identity=args.operator_identity or service.operator_id,
        scopes=frozenset(args.scopes or default_scopes),
        expires_at=_now() + timedelta(seconds=max(1, args.expires_in_seconds)),
        approval_policy={
            "bundle_activate": "AUTO",
            "bundle_retire": "OPERATOR_CONFIRMATION",
            "provider_attach": "OPERATOR_CONFIRMATION",
            "endpoint_write": "OPERATOR_CONFIRMATION",
            "runtime_control": "OPERATOR_CONFIRMATION",
        },
    )
    server = build_mcp_server(
        service,
        endpoint_service=getattr(app.state, "endpoint_service", None),
        endpoint_publication_service=getattr(app.state, "endpoint_publication_service", None),
        validation_service=getattr(app.state, "validation_service", None),
        registry_service=getattr(app.state, "registry_service", None),
        session=session,
        mcp_state_store=getattr(app.state, "mcp_state_store", None),
    )
    server.run_stdio()


if __name__ == "__main__":  # pragma: no cover
    main()
