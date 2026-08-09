from __future__ import annotations

import os

from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.secrets import FileSecretManager


def _manager(tmp_path) -> FileSecretManager:
    return FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))


def test_store_resolves_active_token_but_lists_only_redacted_metadata(tmp_path) -> None:
    store = McpCredentialStore(secret_manager=_manager(tmp_path))

    issued = store.create_credential(
        label="node127-agent",
        scopes=("NODE:READ",),
    )

    assert issued.token
    resolved = store.resolve(issued.token)
    assert resolved is not None
    assert resolved.credential_id == issued.credential_id
    assert resolved.token is None

    listed = store.list_credentials()
    assert len(listed) == 1
    assert listed[0].credential_id == issued.credential_id
    assert listed[0].token is None
    assert listed[0].fingerprint == issued.fingerprint


def test_rotation_and_revoke_make_predecessor_unusable(tmp_path) -> None:
    store = McpCredentialStore(secret_manager=_manager(tmp_path))
    initial = store.create_credential(label="agent", scopes=("NODE:READ",))

    replacement = store.rotate_credential(initial.credential_id)

    assert store.resolve(initial.token) is None
    assert store.resolve(replacement.token) is not None
    assert store.revoke_credential(replacement.credential_id) is True
    assert store.resolve(replacement.token) is None


def test_pairing_code_is_single_use_without_persisting_raw_value(tmp_path) -> None:
    manager = _manager(tmp_path)
    store = McpCredentialStore(secret_manager=manager)

    pairing = store.create_pairing_code(ttl_seconds=600)

    assert pairing.code
    assert pairing.code.encode("utf-8") not in (tmp_path / "secrets.json").read_bytes()
    assert store.consume_pairing_code(pairing.code) is True
    assert store.consume_pairing_code(pairing.code) is False


def test_invalid_pairing_attempt_does_not_consume_valid_code(tmp_path) -> None:
    store = McpCredentialStore(secret_manager=_manager(tmp_path))
    pairing = store.create_pairing_code(ttl_seconds=600)

    assert store.consume_pairing_code("wrong-code") is False
    assert store.consume_pairing_code(pairing.code) is True
