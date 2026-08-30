from __future__ import annotations

import base64
import os
import subprocess
import sys
import threading
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
    browser_key = "browser-key-for-test-0000000000000000000000000000000000000000"
    pairing = access.create_pairing(ttl_seconds=600)

    session = access.exchange_pairing_code(
        pairing.code,
        browser_key=browser_key,
        duration="ten_minutes",
    )

    assert session is not None
    assert access.authorize(
        session.session_id,
        browser_key=browser_key,
    ) is True
    assert access.authorize(
        session.session_id,
        browser_key="other-browser-key-0000000000000000000000000000000000000000",
    ) is False
    assert access.exchange_pairing_code(pairing.code, browser_key=browser_key) is None
    clock.advance(seconds=601)
    assert access.authorize(session.session_id, browser_key=browser_key) is False


def test_pairing_exchange_is_atomic_and_authorization_does_not_rewrite_secret_file(tmp_path) -> None:
    store = McpCredentialStore(secret_manager=_manager(tmp_path))
    access = DashboardAccessService(store=store)
    browser_key = "atomic-browser-key-000000000000000000000000000000000000000000"
    pairing = access.create_pairing(ttl_seconds=600)

    session = access.exchange_pairing_code(pairing.code, browser_key=browser_key)

    assert session is not None
    secret_path = tmp_path / "secrets.json"
    before = secret_path.read_bytes()
    assert access.authorize(session.session_id, browser_key=browser_key) is True
    assert secret_path.read_bytes() == before
    assert access.exchange_pairing_code(pairing.code, browser_key=browser_key) is None


def test_file_secret_manager_serializes_independent_process_style_mutations(tmp_path) -> None:
    """Two manager instances must not lose each other's fresh writes."""
    key = os.urandom(32)
    path = tmp_path / "secrets.json"
    first = FileSecretManager(path=path, master_key=key)
    second = FileSecretManager(path=path, master_key=key)
    first_entered = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()

    def mutate_first(values: dict[str, bytes]) -> None:
        values["secret://first"] = b"one"
        first_entered.set()
        assert release_first.wait(timeout=2)

    def mutate_second(values: dict[str, bytes]) -> None:
        second_entered.set()
        values["secret://second"] = b"two"

    first_thread = threading.Thread(target=lambda: first.mutate(mutate_first))
    second_thread = threading.Thread(target=lambda: second.mutate(mutate_second))
    first_thread.start()
    assert first_entered.wait(timeout=2)
    second_thread.start()
    assert not second_entered.wait(timeout=0.1)
    release_first.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    restored = FileSecretManager(path=path, master_key=key)
    assert restored.get("secret://first") == b"one"
    assert restored.get("secret://second") == b"two"


def test_access_session_can_be_persistent_and_survives_service_restart(tmp_path) -> None:
    clock = _Clock()
    store = McpCredentialStore(secret_manager=_manager(tmp_path), now=clock)
    browser_key = "persistent-browser-key-000000000000000000000000000000000000000"
    pairing = DashboardAccessService(store=store, now=clock).create_pairing(ttl_seconds=600)
    session = DashboardAccessService(store=store, now=clock).exchange_pairing_code(
        pairing.code,
        browser_key=browser_key,
        duration="forever",
    )

    assert session is not None
    restored = DashboardAccessService(store=store, now=clock)
    assert restored.authorize(session.session_id, browser_key=browser_key) is True
    assert restored.session_expiry(session.session_id, browser_key=browser_key) is None


def test_first_browser_claim_requires_explicit_action_and_is_single_use(tmp_path) -> None:
    clock = _Clock()
    store = McpCredentialStore(secret_manager=_manager(tmp_path), now=clock)
    access = DashboardAccessService(store=store, now=clock)
    browser_key = "first-browser-key-000000000000000000000000000000000000000000"

    window = access.open_first_browser_claim(ttl_seconds=3600)

    assert access.first_browser_claim_expiry() == window.expires_at
    session = access.claim_first_browser(browser_key=browser_key, duration="one_day")
    assert session is not None
    assert access.authorize(session.session_id, browser_key=browser_key) is True
    assert access.first_browser_claim_expiry() is None
    assert access.claim_first_browser(browser_key=browser_key, duration="one_day") is None


def test_first_browser_claim_expires_without_trusting_a_browser(tmp_path) -> None:
    clock = _Clock()
    store = McpCredentialStore(secret_manager=_manager(tmp_path), now=clock)
    access = DashboardAccessService(store=store, now=clock)
    browser_key = "expiring-browser-key-000000000000000000000000000000000000000000"

    access.open_first_browser_claim(ttl_seconds=60)
    clock.advance(seconds=61)

    assert access.first_browser_claim_expiry() is None
    assert access.claim_first_browser(browser_key=browser_key) is None


def test_dashboard_enrollment_methods_replace_each_other(tmp_path) -> None:
    store = McpCredentialStore(secret_manager=_manager(tmp_path))

    store.open_first_dashboard_browser_claim(ttl_seconds=3600)
    pairing = store.create_pairing_code(ttl_seconds=600)

    assert store.first_dashboard_browser_claim_expiry() is None
    assert store.consume_pairing_code(pairing.code) is True


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


def test_operator_pair_first_browser_mode_opens_explicit_claim_window(tmp_path, capsys) -> None:
    key = os.urandom(32)
    secret_path = tmp_path / "secrets.json"
    key_path = tmp_path / "master-key.b64"
    key_path.write_text(base64.b64encode(key).decode("ascii"), encoding="utf-8")

    result = operator_cli_main(
        [
            "pair",
            "--mode",
            "first-browser",
            "--secret-manager-path",
            str(secret_path),
            "--master-key-file",
            str(key_path),
            "--dashboard-url",
            "http://127.0.0.1:8766/operators/dashboard/react#settings",
        ]
    )

    output = capsys.readouterr().out
    store = McpCredentialStore(secret_manager=FileSecretManager(path=secret_path, master_key=key))
    assert result == 0
    assert "first-browser claim window opened" in output
    assert "Code:" not in output
    assert store.first_dashboard_browser_claim_expiry() is not None


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
