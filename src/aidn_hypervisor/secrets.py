"""Small encrypted-at-rest secret manager for local operator deployment."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretManagerError(ValueError):
    """A secret is missing, invalid, or cannot be safely persisted."""


class FileSecretManager:
    """Persist opaque secrets encrypted by an externally supplied 256-bit key.

    The encryption key is intentionally not persisted beside this file. An
    operator may supply it from an OS credential store, KMS agent, or a mounted
    deployment secret. The file is only a local encrypted secret backend.
    """

    _FORMAT_VERSION = 1

    def __init__(self, *, path: Path, master_key: bytes) -> None:
        if len(master_key) != 32:
            raise SecretManagerError("secret manager master key must be 32 bytes")
        self._path = path
        self._aesgcm = AESGCM(master_key)
        self._secrets = self._load()

    def put(self, *, handle: str, value: bytes) -> None:
        self._validate_handle(handle)
        if not value:
            raise SecretManagerError("secret value must not be empty")
        self._secrets[handle] = bytes(value)
        self._persist()

    def get(self, handle: str) -> bytes:
        self._validate_handle(handle)
        try:
            return self._secrets[handle]
        except KeyError as exc:
            raise SecretManagerError(f"secret handle is not available: {handle}") from exc

    def remove(self, *, handle: str) -> None:
        self._validate_handle(handle)
        if handle in self._secrets:
            del self._secrets[handle]
            self._persist()

    def has(self, handle: str) -> bool:
        self._validate_handle(handle)
        return handle in self._secrets

    def _load(self) -> dict[str, bytes]:
        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if payload.get("format_version") != self._FORMAT_VERSION:
                raise SecretManagerError("secret manager format version is unsupported")
            encrypted = base64.b64decode(payload["ciphertext"], validate=True)
            nonce = base64.b64decode(payload["nonce"], validate=True)
            plaintext = self._aesgcm.decrypt(nonce, encrypted, b"aidn.secret-manager.v1")
            decoded = json.loads(plaintext.decode("utf-8"))
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise SecretManagerError("secret manager state is invalid") from exc
        except Exception as exc:
            raise SecretManagerError("secret manager state cannot be decrypted") from exc
        if not isinstance(decoded, dict):
            raise SecretManagerError("secret manager plaintext is invalid")
        secrets: dict[str, bytes] = {}
        for handle, encoded in decoded.items():
            self._validate_handle(handle)
            if not isinstance(encoded, str):
                raise SecretManagerError("secret manager value is invalid")
            try:
                secrets[handle] = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise SecretManagerError("secret manager value is invalid") from exc
        return secrets

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(
            {
                handle: base64.b64encode(value).decode("ascii")
                for handle, value in sorted(self._secrets.items())
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        nonce = os.urandom(12)
        encrypted = self._aesgcm.encrypt(nonce, plaintext, b"aidn.secret-manager.v1")
        payload = json.dumps(
            {
                "format_version": self._FORMAT_VERSION,
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(encrypted).decode("ascii"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        descriptor, temporary_path = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self._path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    @staticmethod
    def _validate_handle(handle: str) -> None:
        if not isinstance(handle, str) or not handle.startswith("secret://") or len(handle) > 512:
            raise SecretManagerError("secret handle must use the secret:// namespace")
