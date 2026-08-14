"""Short-lived agent enrollment requests for dashboard approval."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.mcp.permissions import DEFAULT_AGENT_READ_SCOPES
from aidn_hypervisor.secrets import FileSecretManager, SecretManagerError

MCP_ENROLLMENT_STATE_HANDLE = "secret://mcp/enrollment-state"
DEFAULT_ENROLLMENT_TTL_SECONDS = 600


@dataclass(frozen=True)
class McpEnrollmentRequest:
    request_id: str
    label: str
    key_fingerprint: str
    state: str
    created_at: str
    expires_at: str


@dataclass(frozen=True)
class McpEnrollmentCreated(McpEnrollmentRequest):
    retrieval_secret: str


class McpEnrollmentService:
    """Collect agent requests and seal approved credentials to agent-owned keys."""

    def __init__(
        self,
        *,
        secret_manager: FileSecretManager,
        credential_store: McpCredentialStore,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._secret_manager = secret_manager
        self._credential_store = credential_store
        self._now = now or (lambda: datetime.now(UTC))

    def create_request(self, *, label: str, encryption_public_key: str) -> McpEnrollmentCreated:
        label = self._label(label)
        public_key = self._public_key(encryption_public_key)
        now = self._current_time()
        retrieval_secret = secrets.token_urlsafe(32)
        record = {
            "request_id": "mcpreq-" + secrets.token_urlsafe(12),
            "label": label,
            "encryption_public_key": encryption_public_key,
            "key_fingerprint": self._fingerprint(public_key),
            "retrieval_digest": self._digest(retrieval_secret),
            "state": "pending",
            "created_at": self._format(now),
            "expires_at": self._format(now + timedelta(seconds=DEFAULT_ENROLLMENT_TTL_SECONDS)),
            "credential_id": None,
            "sealed_credential": None,
        }
        state = self._load()
        self._expire(state, now)
        if sum(item["state"] == "pending" for item in state["requests"]) >= 32:
            raise ValueError("too many pending MCP enrollment requests")
        state["requests"].append(record)
        self._save(state)
        return McpEnrollmentCreated(**self._public(record), retrieval_secret=retrieval_secret)

    def list_requests(self) -> list[McpEnrollmentRequest]:
        state = self._load()
        changed = self._expire(state, self._current_time())
        if changed:
            self._save(state)
        return [McpEnrollmentRequest(**self._public(item)) for item in state["requests"]]

    def approve(self, request_id: str) -> McpEnrollmentRequest:
        state = self._load()
        self._expire(state, self._current_time())
        record = self._pending(state, request_id)
        issued = self._credential_store.create_credential(
            label=f"enrolled:{record['label']}",
            scopes=DEFAULT_AGENT_READ_SCOPES,
        )
        assert issued.token is not None
        try:
            record["credential_id"] = issued.credential_id
            record["sealed_credential"] = self._seal(
                public_key=self._public_key(record["encryption_public_key"]),
                token=issued.token,
                request_id=record["request_id"],
            )
            record["state"] = "approved"
            self._save(state)
        except Exception:
            self._credential_store.revoke_credential(issued.credential_id)
            raise
        return McpEnrollmentRequest(**self._public(record))

    def reject(self, request_id: str) -> McpEnrollmentRequest:
        state = self._load()
        self._expire(state, self._current_time())
        record = self._pending(state, request_id)
        record["state"] = "rejected"
        self._save(state)
        return McpEnrollmentRequest(**self._public(record))

    def retrieve(self, *, request_id: str, retrieval_secret: str) -> dict | None:
        state = self._load()
        changed = self._expire(state, self._current_time())
        record = next((item for item in state["requests"] if item["request_id"] == request_id), None)
        if changed:
            self._save(state)
        if record is None or not isinstance(retrieval_secret, str):
            return None
        if not hmac.compare_digest(record["retrieval_digest"], self._digest(retrieval_secret)):
            return None
        result = {"request_id": request_id, "state": record["state"], "expires_at": record["expires_at"]}
        if record["state"] == "approved":
            result["credential"] = record["sealed_credential"]
        return result

    def _load(self) -> dict:
        self._secret_manager.reload()
        if not self._secret_manager.has(MCP_ENROLLMENT_STATE_HANDLE):
            return {"version": 1, "requests": []}
        try:
            state = json.loads(self._secret_manager.get(MCP_ENROLLMENT_STATE_HANDLE).decode("utf-8"))
        except (UnicodeDecodeError, ValueError, SecretManagerError) as exc:
            raise SecretManagerError("MCP enrollment state is invalid") from exc
        if not isinstance(state, dict) or state.get("version") != 1 or not isinstance(state.get("requests"), list):
            raise SecretManagerError("MCP enrollment state is invalid")
        return state

    def _save(self, state: dict) -> None:
        encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        self._secret_manager.put(
            handle=MCP_ENROLLMENT_STATE_HANDLE,
            value=encoded,
        )

    def _pending(self, state: dict, request_id: str) -> dict:
        record = next((item for item in state["requests"] if item["request_id"] == request_id), None)
        if record is None or record["state"] != "pending":
            raise ValueError("MCP enrollment request is not pending")
        return record

    @staticmethod
    def _label(value: str) -> str:
        if not isinstance(value, str) or not (1 <= len(value.strip()) <= 96):
            raise ValueError("MCP enrollment label must contain 1..96 characters")
        return value.strip()

    @staticmethod
    def _public_key(value: str) -> bytes:
        try:
            raw = base64.urlsafe_b64decode(value.encode("ascii") + b"=" * (-len(value) % 4))
            X25519PublicKey.from_public_bytes(raw)
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("MCP enrollment public key must be a base64url X25519 key") from exc
        return raw

    def _expire(self, state: dict, now: datetime) -> bool:
        changed = False
        for record in state["requests"]:
            if record["state"] == "pending" and self._parse(record["expires_at"]) <= now:
                record["state"] = "expired"
                changed = True
        return changed

    @staticmethod
    def _seal(*, public_key: bytes, token: str, request_id: str) -> dict:
        recipient = X25519PublicKey.from_public_bytes(public_key)
        ephemeral = X25519PrivateKey.generate()
        shared = ephemeral.exchange(recipient)
        key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=("aidn.mcp.enrollment.v1:" + request_id).encode(),
        ).derive(shared)
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(key).encrypt(nonce, token.encode("utf-8"), request_id.encode("utf-8"))
        return {
            "version": 1,
            "ephemeral_public_key": McpEnrollmentService._b64(ephemeral.public_key().public_bytes_raw()),
            "nonce": McpEnrollmentService._b64(nonce),
            "ciphertext": McpEnrollmentService._b64(ciphertext),
        }

    @staticmethod
    def _public(record: dict) -> dict:
        public_fields = (
            "request_id",
            "label",
            "key_fingerprint",
            "state",
            "created_at",
            "expires_at",
        )
        return {key: record[key] for key in public_fields}

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _fingerprint(value: bytes) -> str:
        return "sha256:" + hashlib.sha256(value).hexdigest()[:16]

    def _current_time(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("MCP enrollment clock must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _format(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
