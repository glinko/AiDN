from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.mcp.enrollment import McpEnrollmentService
from aidn_hypervisor.operator_cli import main as operator_cli_main
from aidn_hypervisor.secrets import FileSecretManager


def _cli_args(tmp_path: Path) -> list[str]:
    master_key = os.urandom(32)
    key_path = tmp_path / "master-key.b64"
    key_path.write_text(base64.b64encode(master_key).decode("ascii"), encoding="utf-8")
    return [
        "--secret-manager-path",
        str(tmp_path / "secrets.json"),
        "--master-key-file",
        str(key_path),
        "--state-path",
        str(tmp_path / "hypervisor-state.json"),
        "--bundles-path",
        str(tmp_path / "bundles.json"),
        "--consensus-mode",
        "disabled",
    ]


def test_wallet_create_is_one_time_and_status_never_returns_private_key(tmp_path, capsys) -> None:
    result = operator_cli_main(["wallet", "create", *_cli_args(tmp_path), "--label", "CLI owner"])
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert result == 0
    assert payload["wallet"]["configured"] is True
    assert payload["private_key"].startswith("ed25519:")

    operator_cli_main(["wallet", "create", *_cli_args(tmp_path)])
    second = json.loads(capsys.readouterr().out)
    assert second["status"] == "ALREADY_CONFIGURED"
    assert second.get("private_key") is None

    operator_cli_main(["wallet", "status", *_cli_args(tmp_path)])
    status = json.loads(capsys.readouterr().out)
    assert status["configured"] is True
    assert "private_key" not in status


def test_wallet_import_reads_hidden_input_and_never_echoes_it(tmp_path, monkeypatch, capsys) -> None:
    private_key = "ed25519:" + os.urandom(32).hex()
    monkeypatch.setattr("aidn_hypervisor.operator_cli.getpass.getpass", lambda _prompt: private_key)

    result = operator_cli_main(["wallet", "import", *_cli_args(tmp_path), "--label", "Imported"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert result == 0
    assert payload["wallet"]["imported"] is True
    assert payload.get("private_key") is None
    assert private_key not in captured.out
    assert private_key not in captured.err


def test_enrollment_cli_uses_existing_encrypted_mcp_state(tmp_path, capsys) -> None:
    args = _cli_args(tmp_path)
    secret_path = Path(args[args.index("--secret-manager-path") + 1])
    key_path = Path(args[args.index("--master-key-file") + 1])
    master_key = base64.b64decode(key_path.read_text(encoding="utf-8"), validate=True)
    manager = FileSecretManager(path=secret_path, master_key=master_key)
    enrollment = McpEnrollmentService(
        secret_manager=manager,
        credential_store=McpCredentialStore(secret_manager=manager),
    )
    agent_key = X25519PrivateKey.generate()
    created = enrollment.create_request(
        label="my-agent",
        encryption_public_key=base64.urlsafe_b64encode(
            agent_key.public_key().public_bytes_raw()
        ).rstrip(b"=").decode("ascii"),
    )

    assert operator_cli_main(["enrollment", "list", *args]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["items"][0]["request_id"] == created.request_id
    assert "retrieval_secret" not in listed["items"][0]

    assert (
        operator_cli_main(
            ["enrollment", "approve", *args, "--request-id", created.request_id]
        )
        == 0
    )
    approved = json.loads(capsys.readouterr().out)
    assert approved["state"] == "approved"
    assert "sealed_credential" not in approved
