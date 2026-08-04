"""Durable local state for the AiDN MCP control plane.

MCP authority state is deliberately stored beside, but not inside, the
Hypervisor snapshot. It is operator-local control-plane state and must not
become consensus or Ledger input.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

MCP_STATE_SCHEMA_VERSION = 1


class McpPersistenceError(RuntimeError):
    """Raised when durable MCP state cannot be trusted or written."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": MCP_STATE_SCHEMA_VERSION,
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


class McpPersistentStateStore:
    """Atomic JSON store for one node's MCP control-plane state."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @classmethod
    def from_hypervisor_state_store(cls, state_store) -> McpPersistentStateStore | None:
        state_path = getattr(state_store, "path", None)
        if state_path is None:
            return None
        return cls(Path(state_path).parent / "mcp-control-state.json")

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_state()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise McpPersistenceError(
                "MCP_INTERNAL_ERROR",
                "Persistent MCP state cannot be read safely",
            ) from error
        if not isinstance(payload, dict):
            raise McpPersistenceError(
                "MCP_INTERNAL_ERROR",
                "Persistent MCP state must be a JSON object",
            )
        version = payload.get("schema_version")
        if version != MCP_STATE_SCHEMA_VERSION:
            raise McpPersistenceError(
                "MCP_INTERNAL_ERROR",
                f"Unsupported MCP state schema version: {version}",
            )
        normalized = _empty_state()
        for key in normalized:
            if key in payload:
                normalized[key] = payload[key]
        if not isinstance(normalized["sessions"], dict):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "MCP sessions state is invalid")
        if not isinstance(normalized["audit_events"], list):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "MCP audit state is invalid")
        if not isinstance(normalized["plans"], dict):
            raise McpPersistenceError("MCP plan state is invalid")
        if not isinstance(normalized["idempotency"], dict):
            raise McpPersistenceError("MCP idempotency state is invalid")
        if not isinstance(normalized["emergency_stop"], dict):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "MCP emergency-stop state is invalid")
        return normalized

    def save(self, state: dict[str, Any]) -> None:
        if not isinstance(state, dict):
            raise McpPersistenceError("MCP_INTERNAL_ERROR", "MCP state must be a JSON object")
        payload = dict(state)
        payload["schema_version"] = MCP_STATE_SCHEMA_VERSION
        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_name(
                f".{self.path.name}.{os.getpid()}.tmp"
            )
            with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
            if os.name != "nt":
                self.path.chmod(0o600)
        except (OSError, TypeError, ValueError) as error:
            raise McpPersistenceError(
                "MCP_INTERNAL_ERROR",
                "Persistent MCP state cannot be written safely",
            ) from error
