from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from aidn_hypervisor.config import load_operator_config
from aidn_hypervisor.network_profile import (
    NetworkProfileError,
    activate_network_profile,
    apply_network_profile_environment,
    load_network_profile,
    verify_network_profile,
)
from aidn_hypervisor.operator_cli import main as operator_cli_main


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _profile(tmp_path: Path, *, name: str = "development") -> Path:
    genesis = tmp_path / "genesis.json"
    genesis.write_text('{"chain_id":"aidn-dev-1"}\n', encoding="utf-8")
    path = tmp_path / f"{name}.toml"
    path.write_text(
        f'''schema_version = "aidn.network-profile.v1"

[network]
name = "{name}"
network_id = "aidn-development"
chain_id = "aidn-dev-1"
environment = "development"
protocol_version = "1"
genesis_file = "genesis.json"
genesis_sha256 = "{_digest(genesis)}"

[network.cometbft]
p2p_host = "0.0.0.0"
p2p_port = 26656
rpc_host = "127.0.0.1"
rpc_port = 26657
persistent_peers = []
seeds = []
max_num_inbound_peers = 40
max_num_outbound_peers = 10
pex = true
addr_book_strict = true

[network.consensus]
timeout_propose = "3s"
timeout_prevote = "1s"
timeout_precommit = "1s"
timeout_commit = "3s"

[network.state_sync]
enabled = false
rpc_servers = []
trust_height = 0
trust_hash = ""

[network.discovery]
enabled = true
bootstrap = []
''',
        encoding="utf-8",
    )
    return path


def test_network_profile_verifies_genesis_and_projects_environment(tmp_path: Path) -> None:
    path = _profile(tmp_path)
    verification = verify_network_profile(path)
    assert verification.valid is True

    profile = load_network_profile(path)
    environment: dict[str, str] = {}
    applied = apply_network_profile_environment(profile, environ=environment)
    assert "AIDN_COMETBFT_CHAIN_ID" in applied
    assert environment["AIDN_NETWORK_ID"] == "aidn-development"
    assert environment["AIDN_COMETBFT_ENDPOINT"] == "tcp://127.0.0.1:26657"


def test_consensus_bound_environment_override_fails_closed(tmp_path: Path) -> None:
    profile = load_network_profile(_profile(tmp_path))
    with pytest.raises(NetworkProfileError, match="CONSENSUS_OVERRIDE"):
        apply_network_profile_environment(
            profile,
            environ={"AIDN_COMETBFT_CHAIN_ID": "other-chain"},
        )


def test_public_network_requires_signed_profile_binding(tmp_path: Path) -> None:
    path = _profile(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        'environment = "development"', 'environment = "testnet"'
    )
    path.write_text(text, encoding="utf-8")
    with pytest.raises(NetworkProfileError, match="PUBLIC_BINDING_REQUIRED"):
        load_network_profile(path)


def test_activation_is_atomic_and_cli_can_show_and_verify(tmp_path: Path, capsys) -> None:
    source = _profile(tmp_path, name="source")
    destination = tmp_path / "active.toml"
    result = activate_network_profile(source, destination)
    assert result.valid is True

    assert operator_cli_main(["network", "--profile-path", str(destination), "verify"]) == 0
    assert '"valid":true' in capsys.readouterr().out
    assert operator_cli_main(["network", "--profile-path", str(destination), "show"]) == 0
    assert '"consensus_binding_hash":"sha256:' in capsys.readouterr().out


def test_operator_config_loads_and_applies_selected_network_profile(tmp_path: Path) -> None:
    profile_path = _profile(tmp_path)
    operator_path = tmp_path / "operator-config.toml"
    operator_path.write_text(
        f'[env]\nAIDN_NETWORK_PROFILE_PATH = "{profile_path.as_posix()}"\n',
        encoding="utf-8",
    )
    environment = {"AIDN_CONFIG_FILE": str(operator_path)}

    result = load_operator_config(environ=environment)

    assert "AIDN_NETWORK_PROFILE_PATH" in result.applied
    assert "AIDN_COMETBFT_CHAIN_ID" in result.applied
    assert environment["AIDN_NETWORK_ID"] == "aidn-development"


def test_network_profile_environment_works_without_operator_config(tmp_path: Path) -> None:
    profile_path = _profile(tmp_path)
    environment = {"AIDN_NETWORK_PROFILE_PATH": str(profile_path)}

    result = load_operator_config(environ=environment)

    assert result.path is None
    assert "AIDN_COMETBFT_CHAIN_ID" in result.applied
    assert environment["AIDN_COMETBFT_CHAIN_ID"] == "aidn-dev-1"


def test_activation_refuses_profile_whose_relative_assets_do_not_exist_at_destination(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = _profile(source_dir)
    destination = tmp_path / "active" / "network.toml"
    with pytest.raises(NetworkProfileError, match="cannot be activated"):
        activate_network_profile(source, destination)
    assert not destination.exists()
