from __future__ import annotations

import os

import pytest

from aidn_hypervisor.secrets import FileSecretManager, SecretManagerError


def test_file_secret_manager_persists_ciphertext_without_plaintext(tmp_path) -> None:
    path = tmp_path / "secrets.json"
    key = os.urandom(32)
    manager = FileSecretManager(path=path, master_key=key)

    manager.put(handle="secret://registry/signing-key", value=b"private-key-material")

    assert b"private-key-material" not in path.read_bytes()
    restored = FileSecretManager(path=path, master_key=key)
    assert restored.get("secret://registry/signing-key") == b"private-key-material"


def test_file_secret_manager_rejects_wrong_key_and_invalid_handle(tmp_path) -> None:
    path = tmp_path / "secrets.json"
    manager = FileSecretManager(path=path, master_key=os.urandom(32))
    manager.put(handle="secret://registry/signing-key", value=b"private-key-material")

    with pytest.raises(SecretManagerError, match="cannot be decrypted"):
        FileSecretManager(path=path, master_key=os.urandom(32))
    with pytest.raises(SecretManagerError, match="secret://"):
        manager.get("registry/signing-key")


def test_file_secret_manager_refreshes_and_atomically_updates_many_handles(tmp_path) -> None:
    path = tmp_path / "secrets.json"
    key = os.urandom(32)
    manager = FileSecretManager(path=path, master_key=key)
    manager.put_many(
        {
            "secret://mcp/certificate": b"certificate-v1",
            "secret://mcp/private-key": b"private-key-v1",
        }
    )
    restored = FileSecretManager(path=path, master_key=key)
    old_fingerprint = restored.fingerprint(
        ("secret://mcp/certificate", "secret://mcp/private-key")
    )

    manager.put_many(
        {
            "secret://mcp/certificate": b"certificate-v2",
            "secret://mcp/private-key": b"private-key-v2",
        }
    )

    assert restored.reload() is True
    assert restored.get("secret://mcp/certificate") == b"certificate-v2"
    assert restored.fingerprint(
        ("secret://mcp/certificate", "secret://mcp/private-key")
    ) != old_fingerprint
