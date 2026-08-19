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
from pathlib import Path
from typing import Any, TextIO

from aidn_hypervisor.mcp.persistence import (
    McpPersistenceError,
    McpPersistentStateStore,
)
from aidn_hypervisor.operator_views import (
    build_operator_bundles_payload,
    build_operator_endpoints_payload,
    build_operator_providers_payload,
)

MCP_PROTOCOL_VERSION = "2025-06-18"
# Hermes Agent 0.20.x sends the 2025-11-25 handshake even when its
# mcp_servers config contains an older protocol_version hint. The AiDN
# control plane does not use any 2025-11-25-only features yet, so accepting
# that negotiated version keeps the JSON-RPC boundary interoperable while
# preserving the older client versions already in the field.
SUPPORTED_MCP_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
MCP_SERVER_VERSION = "0.1.0"
DEFAULT_CONTROL_SESSION_TTL_SECONDS = 3600
MIN_CONTROL_SESSION_TTL_SECONDS = 60

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
            "deferred_tool_families": [
                "aidn.host.prepare",
                "aidn.node.install",
                "aidn.node.join_network",
                "aidn.plugin.install",
                "aidn.model.deploy",
                "aidn.bundle.publish",
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
            domain_error = McpDomainError(
                self._map_domain_error(name, error),
                str(error),
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

    def _build_tools(self) -> dict[str, McpTool]:
        read_schema = {"type": "object", "additionalProperties": False}
        return {
            "aidn.capabilities.get": McpTool(
                "aidn.capabilities.get",
                "Return the negotiated MCP control-plane capabilities and policy boundary.",
                read_schema,
                (),
                "READ_ONLY",
                lambda _args: self.capabilities(),
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
            "aidn.resources.status": McpTool(
                "aidn.resources.status",
                "Return current CPU, RAM, and VRAM reservation state.",
                read_schema,
                ("RESOURCES:READ",),
                "READ_ONLY",
                lambda _args: self._resource_status(),
            ),
            "aidn.scheduler.get_policy": McpTool(
                "aidn.scheduler.get_policy",
                "Return local request routing policy.",
                read_schema,
                ("SCHEDULER:READ",),
                "READ_ONLY",
                lambda _args: self.service.operator_requests_policy(),
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
            "aidn://scheduler/policy": McpResource(
                "aidn://scheduler/policy",
                "Scheduler policy",
                "Local scheduler policy.",
                "SCHEDULER:READ",
                lambda _uri: self.service.operator_requests_policy(),
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
            target=arguments.get("bundle_id"),
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
        current_revision = self._bundle_revision(arguments.get("bundle_id")) if arguments.get("bundle_id") else None
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
            "target": arguments.get("bundle_id"),
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
        return [tool_name]

    @staticmethod
    def _planned_risks(tool_name: str) -> list[str]:
        if tool_name == "aidn.bundle.retire":
            return ["active requests may be interrupted after the runtime stop"]
        if tool_name == "aidn.provider.attach":
            return ["the configured endpoint becomes available to local Runtime flows"]
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
            if item.get("runtime_status") not in {"running", "healthy", "starting", "stopped"}
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
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                },
                "serverInfo": {"name": "aidn-node-control", "version": MCP_SERVER_VERSION},
                "instructions": "Use aidn.capabilities.get before mutating operations; plan before apply.",
            }
        if method == "ping":
            return {}
        if not self.initialized:
            raise McpDomainError("MCP_NOT_INITIALIZED", "The MCP session is not initialized")
        if method == "tools/list":
            return {"tools": self.control.tool_definitions()}
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
                "CAPABILITIES:READ,HOST:READ,NODE:READ,NETWORK:READ,PROVIDER:READ,MODEL:READ,BUNDLE:READ,ENDPOINT:READ,RESOURCES:READ,SCHEDULER:READ,WALLET:READ,BUDGET:READ,AUDIT:READ",
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
