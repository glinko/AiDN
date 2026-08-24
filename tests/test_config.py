import os
from pathlib import Path

import pytest

from aidn_hypervisor.config import (
    OperatorConfigError,
    config_sha256,
    load_operator_config,
    write_operator_config,
    write_operator_config_from_environment,
)
from aidn_hypervisor.operator_config_service import OperatorConfigConflict, OperatorConfigService


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_config_file_applies_missing_values_and_preserves_environment(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "aidn.toml",
        """
[env]
AIDN_NODE_ID = "from-file"
AIDN_INFERENCE_MAX_MESSAGES = 256
AIDN_MCP_CONTROL_SESSION_STATELESS = true
AIDN_MCP_SCOPES = ["NODE:READ", "NETWORK:READ"]
""",
    )
    environment = {
        "AIDN_CONFIG_FILE": str(config_path),
        "AIDN_NODE_ID": "from-environment",
    }

    result = load_operator_config(environ=environment)

    assert environment["AIDN_NODE_ID"] == "from-environment"
    assert environment["AIDN_INFERENCE_MAX_MESSAGES"] == "256"
    assert environment["AIDN_MCP_CONTROL_SESSION_STATELESS"] == "true"
    assert environment["AIDN_MCP_SCOPES"] == "NODE:READ,NETWORK:READ"
    assert result.path == config_path
    assert result.applied == (
        "AIDN_INFERENCE_MAX_MESSAGES",
        "AIDN_MCP_CONTROL_SESSION_STATELESS",
        "AIDN_MCP_SCOPES",
    )
    assert result.preserved == ("AIDN_NODE_ID",)


def test_config_file_requires_explicit_env_table(tmp_path: Path) -> None:
    config_path = _write(tmp_path / "aidn.toml", "AIDN_NODE_ID = 'invalid'\n")

    with pytest.raises(OperatorConfigError, match=r"\[env\] table"):
        load_operator_config(path=config_path, environ={})


def test_config_file_rejects_unknown_keys(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "aidn.toml",
        """
[env]
NODE_ID = "invalid"
""",
    )

    with pytest.raises(OperatorConfigError, match="unsupported configuration key"):
        load_operator_config(path=config_path, environ={})


def test_missing_optional_config_is_a_noop() -> None:
    environment: dict[str, str] = {}
    result = load_operator_config(environ=environment)
    assert result.path is None
    assert environment == {}


def test_selected_config_must_exist(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"

    with pytest.raises(OperatorConfigError, match="does not exist"):
        load_operator_config(path=missing, environ={})


def test_operator_profile_is_secret_free_atomic_and_redacted(tmp_path: Path) -> None:
    path = tmp_path / "operator-config.toml"
    write_operator_config_from_environment(
        path,
        {
            "AIDN_HYPERVISOR_API_PORT": "8766",
            "AIDN_SECRET_MANAGER_MASTER_KEY": "do-not-write",
            "AIDN_PROVIDER_URL": "https://provider.example.test/v1",
        },
    )
    text = path.read_text(encoding="utf-8")
    assert "do-not-write" not in text
    assert "AIDN_HYPERVISOR_API_PORT" in text
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0
    assert config_sha256(path)


def test_operator_profile_validation_preserves_protected_values_and_rejects_secrets(tmp_path: Path) -> None:
    path = tmp_path / "operator-config.toml"
    write_operator_config(
        path,
        {
            "AIDN_HYPERVISOR_STATE_PATH": str(tmp_path / "state.json"),
            "AIDN_HYPERVISOR_API_PORT": "8766",
            "AIDN_SECRET_MANAGER_MASTER_KEY": "hidden",
        },
    )
    service = OperatorConfigService(path=path, environ={})
    payload = service.read_payload()
    assert "hidden" not in payload["text"]
    assert "AIDN_SECRET_MANAGER_MASTER_KEY" in payload["hidden_keys"]

    changed = service.validate(
        '[env]\nAIDN_HYPERVISOR_STATE_PATH = "/tmp/other.json"\nAIDN_HYPERVISOR_API_PORT = "9000"\n'
    )
    assert changed["valid"] is False
    assert "protected" in changed["errors"][0]

    secret = service.validate(
        '[env]\nAIDN_SECRET_MANAGER_MASTER_KEY = "new-secret"\n'
    )
    assert secret["valid"] is False
    assert "Secret Manager" in secret["errors"][0]


def test_operator_profile_save_uses_optimistic_concurrency_and_schedules_apply(tmp_path: Path) -> None:
    path = tmp_path / "operator-config.toml"
    write_operator_config(path, {"AIDN_HYPERVISOR_API_PORT": "8766"})
    restarts: list[bool] = []
    service = OperatorConfigService(
        path=path,
        environ={},
        restart_callback=lambda: restarts.append(True) or True,
        restart_supported=True,
    )
    initial = service.read_payload()
    edited = '[env]\nAIDN_HYPERVISOR_API_PORT = "9000"\n'
    result = service.save(edited, expected_sha256=initial["sha256"], apply=True)
    assert result["status"] == "accepted"
    assert result["restart_scheduled"] is True
    assert restarts == [True]
    with pytest.raises(OperatorConfigConflict):
        service.save(edited, expected_sha256=initial["sha256"])
