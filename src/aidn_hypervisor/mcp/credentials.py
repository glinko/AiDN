"""Encrypted local credential records for the MCP remote boundary."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from aidn_hypervisor.mcp.permissions import DEFAULT_AGENT_READ_SCOPES, normalize_auto_approved_scopes
from aidn_hypervisor.secrets import FileSecretManager, SecretManagerError

MCP_ACCESS_STATE_HANDLE = "secret://mcp/access-state"
_STATE_VERSION = 1


@dataclass(frozen=True)
class McpCredential:
    """A credential read model; only newly issued values include ``token``."""

    credential_id: str
    label: str
    scopes: tuple[str, ...]
    auto_approved_scopes: tuple[str, ...]
    fingerprint: str
    state: str
    created_at: str
    last_used_at: str | None
    token: str | None = None


@dataclass(frozen=True)
class McpPairingCode:
    """A newly created pairing code; the value is never persisted."""

    code: str
    expires_at: str


class McpCredentialStore:
    """Store MCP credential digests in the configured encrypted secret backend."""

    def __init__(
        self,
        *,
        secret_manager: FileSecretManager,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._secret_manager = secret_manager
        self._now = now or (lambda: datetime.now(UTC))

    def create_credential(
        self, *, label: str, scopes: tuple[str, ...], auto_approved_scopes: tuple[str, ...] = ()
    ) -> McpCredential:
        normalized_label = self._normalize_label(label)
        normalized_scopes = self._normalize_scopes(scopes)
        normalized_auto_approved_scopes = normalize_auto_approved_scopes(auto_approved_scopes)
        if not set(normalized_auto_approved_scopes).issubset(normalized_scopes):
            raise ValueError("MCP auto approval requires the corresponding credential scope")
        token = secrets.token_urlsafe(32)
        created_at = self._timestamp()
        record = {
            "credential_id": "mcpcred-" + secrets.token_urlsafe(12),
            "label": normalized_label,
            "scopes": list(normalized_scopes),
            "auto_approved_scopes": list(normalized_auto_approved_scopes),
            "token_digest": self._digest(token),
            "fingerprint": self._fingerprint(token),
            "state": "active",
            "created_at": created_at,
            "last_used_at": None,
        }
        state = self._load_state()
        state["credentials"].append(record)
        self._save_state(state)
        return self._credential(record, token=token)

    def import_legacy_token(
        self,
        *,
        token: str,
        label: str,
        scopes: tuple[str, ...],
    ) -> McpCredential | None:
        """Import one environment-provided token without making it permanent authority.

        Deployments prior to dashboard credential management used a single
        environment token. Import it exactly once so the operator can rotate
        or revoke it from the new control surface. A revoked import must never
        reappear merely because the old environment variable still exists.
        """
        normalized_label = self._normalize_label(label)
        normalized_scopes = self._normalize_scopes(scopes)
        if not isinstance(token, str) or not token.strip():
            raise ValueError("MCP legacy token must be a non-empty string")
        state = self._load_state()
        if state["legacy_imported"]:
            return None
        record = {
            "credential_id": "mcpcred-" + secrets.token_urlsafe(12),
            "label": normalized_label,
            "scopes": list(normalized_scopes),
            "auto_approved_scopes": [],
            "token_digest": self._digest(token.strip()),
            "fingerprint": self._fingerprint(token.strip()),
            "state": "active",
            "created_at": self._timestamp(),
            "last_used_at": None,
        }
        state["credentials"].append(record)
        state["legacy_imported"] = True
        self._save_state(state)
        return self._credential(record)

    def list_credentials(self) -> list[McpCredential]:
        state = self._load_state()
        self._migrate_legacy_control_session_scope(state)
        return [self._credential(record) for record in state["credentials"]]

    def resolve(self, token: str | None) -> McpCredential | None:
        if not isinstance(token, str) or not token.strip():
            return None
        token_digest = self._digest(token.strip())
        state = self._load_state()
        self._migrate_legacy_control_session_scope(state)
        for record in state["credentials"]:
            if record["state"] != "active":
                continue
            if hmac.compare_digest(record["token_digest"], token_digest):
                return self._credential(record)
        return None

    def record_use(self, credential_id: str) -> None:
        state = self._load_state()
        for record in state["credentials"]:
            if record["credential_id"] == credential_id and record["state"] == "active":
                record["last_used_at"] = self._timestamp()
                self._save_state(state)
                return

    def rotate_credential(self, credential_id: str) -> McpCredential:
        state = self._load_state()
        predecessor = self._find_active_record(state, credential_id)
        token = secrets.token_urlsafe(32)
        created_at = self._timestamp()
        replacement = {
            "credential_id": "mcpcred-" + secrets.token_urlsafe(12),
            "label": predecessor["label"],
            "scopes": predecessor["scopes"],
            "auto_approved_scopes": predecessor.get("auto_approved_scopes", []),
            "token_digest": self._digest(token),
            "fingerprint": self._fingerprint(token),
            "state": "active",
            "created_at": created_at,
            "last_used_at": None,
        }
        predecessor["state"] = "revoked"
        state["credentials"].append(replacement)
        self._save_state(state)
        return self._credential(replacement, token=token)

    def update_scopes(
        self,
        credential_id: str,
        *,
        scopes: tuple[str, ...],
        auto_approved_scopes: tuple[str, ...] = (),
    ) -> McpCredential:
        """Replace an active credential's permissions without revealing its token."""
        normalized_scopes = self._normalize_scopes(scopes)
        normalized_auto_approved_scopes = normalize_auto_approved_scopes(auto_approved_scopes)
        if not set(normalized_auto_approved_scopes).issubset(normalized_scopes):
            raise ValueError("MCP auto approval requires the corresponding credential scope")
        state = self._load_state()
        record = self._find_active_record(state, credential_id)
        record["scopes"] = list(normalized_scopes)
        record["auto_approved_scopes"] = list(normalized_auto_approved_scopes)
        self._save_state(state)
        return self._credential(record)

    def revoke_credential(self, credential_id: str) -> bool:
        state = self._load_state()
        for record in state["credentials"]:
            if record["credential_id"] != credential_id or record["state"] != "active":
                continue
            record["state"] = "revoked"
            self._save_state(state)
            return True
        return False

    def create_pairing_code(self, *, ttl_seconds: int) -> McpPairingCode:
        if ttl_seconds <= 0:
            raise ValueError("MCP pairing TTL must be positive")
        code = secrets.token_urlsafe(24)
        created_at = self._current_time()
        expires_at = created_at + timedelta(seconds=ttl_seconds)
        state = self._load_state()
        state["pairing"] = {
            "code_digest": self._digest(code),
            "created_at": self._format_timestamp(created_at),
            "expires_at": self._format_timestamp(expires_at),
        }
        self._save_state(state)
        return McpPairingCode(code=code, expires_at=self._format_timestamp(expires_at))

    def consume_pairing_code(self, code: str | None) -> bool:
        if not isinstance(code, str) or not code.strip():
            return False
        state = self._load_state()
        pairing = state.get("pairing")
        if not isinstance(pairing, dict):
            return False
        expires_at = self._parse_timestamp(pairing.get("expires_at"))
        digest = pairing.get("code_digest")
        valid = bool(
            expires_at is not None
            and expires_at > self._current_time()
            and isinstance(digest, str)
            and hmac.compare_digest(digest, self._digest(code.strip()))
        )
        if valid or expires_at is None or expires_at <= self._current_time():
            state["pairing"] = None
            self._save_state(state)
        return valid

    def create_dashboard_browser_session(
        self,
        *,
        session_id: str,
        browser_key: str,
        expires_at: str | None,
        max_sessions: int,
    ) -> bool:
        """Persist a browser-bound dashboard session without storing either secret."""
        if not session_id or not self._valid_browser_key(browser_key) or max_sessions < 1:
            return False
        state = self._load_state()
        self._prune_dashboard_sessions(state)
        if len(state["dashboard_sessions"]) >= max_sessions:
            self._save_state(state)
            return False
        state["dashboard_sessions"].append(
            {
                "session_digest": self._digest(session_id),
                "browser_key_digest": self._digest(browser_key),
                "expires_at": expires_at,
            }
        )
        self._save_state(state)
        return True

    def authorize_dashboard_browser_session(self, *, session_id: str | None, browser_key: str | None) -> bool:
        if not isinstance(session_id, str) or not self._valid_browser_key(browser_key):
            return False
        state = self._load_state()
        self._prune_dashboard_sessions(state)
        session_digest = self._digest(session_id)
        browser_key_digest = self._digest(browser_key)
        valid = any(
            hmac.compare_digest(record.get("session_digest", ""), session_digest)
            and hmac.compare_digest(record.get("browser_key_digest", ""), browser_key_digest)
            for record in state["dashboard_sessions"]
        )
        self._save_state(state)
        return valid

    def dashboard_browser_session_expiry(self, *, session_id: str | None, browser_key: str | None) -> str | None:
        if not isinstance(session_id, str) or not self._valid_browser_key(browser_key):
            return None
        state = self._load_state()
        self._prune_dashboard_sessions(state)
        session_digest = self._digest(session_id)
        browser_key_digest = self._digest(browser_key)
        for record in state["dashboard_sessions"]:
            if hmac.compare_digest(record.get("session_digest", ""), session_digest) and hmac.compare_digest(
                record.get("browser_key_digest", ""), browser_key_digest
            ):
                self._save_state(state)
                return record.get("expires_at")
        self._save_state(state)
        return None

    def revoke_dashboard_browser_session(self, *, session_id: str | None, browser_key: str | None) -> bool:
        if not isinstance(session_id, str) or not self._valid_browser_key(browser_key):
            return False
        state = self._load_state()
        session_digest = self._digest(session_id)
        browser_key_digest = self._digest(browser_key)
        before = len(state["dashboard_sessions"])
        state["dashboard_sessions"] = [
            record
            for record in state["dashboard_sessions"]
            if not (
                hmac.compare_digest(record.get("session_digest", ""), session_digest)
                and hmac.compare_digest(record.get("browser_key_digest", ""), browser_key_digest)
            )
        ]
        self._save_state(state)
        return len(state["dashboard_sessions"]) != before

    def _load_state(self) -> dict:
        # Pairing codes are intentionally minted by a separate host-local CLI
        # process. Refresh the encrypted backend before every operation so the
        # long-running Hypervisor observes that external, authenticated write.
        self._secret_manager.reload()
        if not self._secret_manager.has(MCP_ACCESS_STATE_HANDLE):
            return {
                "version": _STATE_VERSION,
                "credentials": [],
                "pairing": None,
                "legacy_imported": False,
                "dashboard_sessions": [],
            }
        try:
            raw = self._secret_manager.get(MCP_ACCESS_STATE_HANDLE)
            import json

            state = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, SecretManagerError) as exc:
            raise SecretManagerError("MCP credential state is invalid") from exc
        if not isinstance(state, dict) or state.get("version") != _STATE_VERSION:
            raise SecretManagerError("MCP credential state version is unsupported")
        credentials = state.get("credentials")
        if not isinstance(credentials, list) or any(not isinstance(item, dict) for item in credentials):
            raise SecretManagerError("MCP credential state is invalid")
        if "pairing" not in state:
            state["pairing"] = None
        if "legacy_imported" not in state:
            state["legacy_imported"] = False
        if "dashboard_sessions" not in state:
            state["dashboard_sessions"] = []
        for record in credentials:
            if "auto_approved_scopes" not in record:
                record["auto_approved_scopes"] = []
        if state["pairing"] is not None and not isinstance(state["pairing"], dict):
            raise SecretManagerError("MCP credential pairing state is invalid")
        if not isinstance(state["legacy_imported"], bool):
            raise SecretManagerError("MCP credential legacy import state is invalid")
        if not isinstance(state["dashboard_sessions"], list) or any(
            not isinstance(item, dict) for item in state["dashboard_sessions"]
        ):
            raise SecretManagerError("MCP dashboard browser session state is invalid")
        return state

    def _prune_dashboard_sessions(self, state: dict) -> None:
        now = self._current_time()
        state["dashboard_sessions"] = [
            record
            for record in state["dashboard_sessions"]
            if (expires_at := self._parse_timestamp(record.get("expires_at"))) is None or expires_at > now
        ]

    def _save_state(self, state: dict) -> None:
        import json

        self._secret_manager.put(
            handle=MCP_ACCESS_STATE_HANDLE,
            value=json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )

    def _migrate_legacy_control_session_scope(self, state: dict) -> None:
        """Replace the former metadata-only enrollment scope with safe reads.

        Releases before credential-scoped transport enforcement issued
        ``CONTROL_SESSION``. It did not map to an MCP tool and therefore
        cannot be preserved as an operator-selected permission.  Upgrade only
        that exact legacy value, never a broader historical scope set.
        """
        changed = False
        for record in state["credentials"]:
            if record.get("scopes") == ["CONTROL_SESSION"]:
                record["scopes"] = list(DEFAULT_AGENT_READ_SCOPES)
                changed = True
        if changed:
            self._save_state(state)

    @staticmethod
    def _find_active_record(state: dict, credential_id: str) -> dict:
        for record in state["credentials"]:
            if record["credential_id"] == credential_id and record["state"] == "active":
                return record
        raise ValueError("MCP credential is not active")

    @staticmethod
    def _normalize_label(label: str) -> str:
        if not isinstance(label, str) or not (1 <= len(label.strip()) <= 96):
            raise ValueError("MCP credential label must contain 1..96 characters")
        return label.strip()

    @staticmethod
    def _normalize_scopes(scopes: tuple[str, ...], *, allow_empty: bool = False) -> tuple[str, ...]:
        if (not allow_empty and not scopes) or any(not isinstance(scope, str) or not scope.strip() for scope in scopes):
            raise ValueError("MCP credential scopes must be non-empty strings")
        return tuple(sorted({scope.strip() for scope in scopes}))

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _fingerprint(token: str) -> str:
        return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]

    def _timestamp(self) -> str:
        return self._format_timestamp(self._current_time())

    def _current_time(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("MCP credential clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _format_timestamp(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _parse_timestamp(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None

    @staticmethod
    def _valid_browser_key(value: object) -> bool:
        return isinstance(value, str) and 32 <= len(value) <= 128

    @staticmethod
    def _credential(record: dict, *, token: str | None = None) -> McpCredential:
        return McpCredential(
            credential_id=record["credential_id"],
            label=record["label"],
            scopes=tuple(record["scopes"]),
            auto_approved_scopes=tuple(record.get("auto_approved_scopes", [])),
            fingerprint=record["fingerprint"],
            state=record["state"],
            created_at=record["created_at"],
            last_used_at=record["last_used_at"],
            token=token,
        )
