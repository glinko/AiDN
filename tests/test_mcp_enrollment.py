from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.mcp.enrollment import McpEnrollmentService
from aidn_hypervisor.secrets import FileSecretManager


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def test_approved_enrollment_seals_agent_token_to_request_public_key(tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    service = McpEnrollmentService(secret_manager=manager, credential_store=credentials)
    private_key = X25519PrivateKey.generate()
    public_key = _b64(private_key.public_key().public_bytes_raw())

    created = service.create_request(label="remote-agent", encryption_public_key=public_key)
    approved = service.approve(created.request_id)
    retrieved = service.retrieve(
        request_id=created.request_id,
        retrieval_secret=created.retrieval_secret,
    )

    assert approved.state == "approved"
    assert retrieved is not None
    assert "token" not in str(service.list_requests())
    envelope = retrieved["credential"]
    ephemeral = X25519PublicKey.from_public_bytes(
        base64.urlsafe_b64decode(envelope["ephemeral_public_key"] + "==")
    )
    shared = private_key.exchange(ephemeral)
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=("aidn.mcp.enrollment.v1:" + created.request_id).encode(),
    ).derive(shared)
    token = AESGCM(key).decrypt(
        base64.urlsafe_b64decode(envelope["nonce"] + "=="),
        base64.urlsafe_b64decode(envelope["ciphertext"] + "=="),
        created.request_id.encode(),
    ).decode()

    assert credentials.resolve(token) is not None
    assert service.retrieve(request_id=created.request_id, retrieval_secret="wrong") is None


def test_legacy_control_session_scope_migrates_to_safe_read_permissions(tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    credentials.create_credential(label="legacy agent", scopes=("CONTROL_SESSION",))

    migrated = credentials.list_credentials()[0]

    assert "CONTROL_SESSION" not in migrated.scopes
    assert "NODE:READ" in migrated.scopes
    assert "BUNDLE:ACTIVATE" not in migrated.scopes
