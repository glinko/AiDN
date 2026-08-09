from __future__ import annotations

import base64
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.operator_access import DashboardAccessService
from aidn_hypervisor.operator_cli import main as operator_cli_main
from aidn_hypervisor.secrets import FileSecretManager


def _manager(tmp_path) -> FileSecretManager:
    return FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 9, 17, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, *, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


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
    initial = store.create_credential(
        label="agent",
        scopes=("NODE:READ", "BUNDLE:ACTIVATE"),
        auto_approved_scopes=("BUNDLE:ACTIVATE",),
    )

    replacement = store.rotate_credential(initial.credential_id)

    assert store.resolve(initial.token) is None
    assert store.resolve(replacement.token) is not None
    assert replacement.auto_approved_scopes == ("BUNDLE:ACTIVATE",)
    assert store.revoke_credential(replacement.credential_id) is True
    assert store.resolve(replacement.token) is None


def test_legacy_token_import_happens_once_and_never_restores_a_revoked_credential(tmp_path) -> None:
    manager = _manager(tmp_path)
    store = McpCredentialStore(secret_manager=manager)

    imported = store.import_legacy_token(
        token="legacy-agent-token",
        label="Legacy agent token",
        scopes=("NODE:READ",),
    )

    assert imported is not None
    assert store.resolve("legacy-agent-token") is not None
    assert store.revoke_credential(imported.credential_id) is True

    restored = McpCredentialStore(secret_manager=manager)
    assert restored.import_legacy_token(
        token="legacy-agent-token",
        label="Legacy agent token",
        scopes=("NODE:READ",),
    ) is None
    assert restored.resolve("legacy-agent-token") is None


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


def test_long_running_store_observes_pairing_code_created_by_another_process(tmp_path) -> None:
    key = os.urandom(32)
    secret_path = tmp_path / "secrets.json"
    running_store = McpCredentialStore(
        secret_manager=FileSecretManager(path=secret_path, master_key=key)
    )
    cli_store = McpCredentialStore(
        secret_manager=FileSecretManager(path=secret_path, master_key=key)
    )

    pairing = cli_store.create_pairing_code(ttl_seconds=600)

    assert running_store.consume_pairing_code(pairing.code) is True


def test_access_session_requires_one_pairing_exchange_and_expires(tmp_path) -> None:
    clock = _Clock()
    store = McpCredentialStore(secret_manager=_manager(tmp_path), now=clock)
    access = DashboardAccessService(store=store, now=clock)
    pairing = access.create_pairing(ttl_seconds=600)

    session = access.exchange_pairing_code(pairing.code)

    assert session is not None
    assert access.authorize(session.session_id) is True
    assert access.exchange_pairing_code(pairing.code) is None
    clock.advance(seconds=901)
    assert access.authorize(session.session_id) is False


def test_operator_pair_command_prints_one_time_code_only_to_stdout(tmp_path, capsys) -> None:
    key = os.urandom(32)
    secret_path = tmp_path / "secrets.json"
    key_path = tmp_path / "master-key.b64"
    key_path.write_text(base64.b64encode(key).decode("ascii"), encoding="utf-8")

    result = operator_cli_main(
        [
            "pair",
            "--secret-manager-path",
            str(secret_path),
            "--master-key-file",
            str(key_path),
            "--dashboard-url",
            "http://127.0.0.1:8766/operators/dashboard/react#settings",
        ]
    )

    output = capsys.readouterr().out
    code = output.split("Code: ", maxsplit=1)[1].strip()
    store = McpCredentialStore(
        secret_manager=FileSecretManager(path=secret_path, master_key=key)
    )
    assert result == 0
    assert store.consume_pairing_code(code) is True
    assert code.encode("utf-8") not in secret_path.read_bytes()


def test_operator_pair_module_entrypoint_runs_main(tmp_path) -> None:
    key = os.urandom(32)
    secret_path = tmp_path / "secrets.json"
    key_path = tmp_path / "master-key.b64"
    key_path.write_text(base64.b64encode(key).decode("ascii"), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "aidn_hypervisor.operator_cli",
            "pair",
            "--secret-manager-path",
            str(secret_path),
            "--master-key-file",
            str(key_path),
            "--dashboard-url",
            "http://127.0.0.1:8766/operators/dashboard/react#settings",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Code: " in result.stdout
