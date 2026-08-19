from pathlib import Path

import pytest

from aidn_hypervisor.config import OperatorConfigError, load_operator_config


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
