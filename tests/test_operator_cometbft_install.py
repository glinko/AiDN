from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.operator_access import DashboardAccessService
from aidn_hypervisor.operator_access_api import build_operator_access_router
from aidn_hypervisor.operator_cometbft_install import (
    apply_pending_cometbft_configuration,
    build_cometbft_install_argv,
    build_operator_cometbft_install_payload,
    install_cometbft_from_dashboard,
)
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.secrets import FileSecretManager

_BROWSER_HEADERS = {"X-AiDN-Browser-Key": "browser-key-for-cometbft-install-tests-000000000000000000000000"}


def _service(tmp_path, *, executor=None):
    service = SimpleNamespace(
        state_store=FileStateStore(tmp_path / "hypervisor-state.json"),
        operator_id="gpu-3090",
        node_id="gpu-3090",
        consensus_service=None,
    )
    if executor is not None:
        service.consensus_installation_executor = executor
    return service


def test_install_payload_is_manual_without_bootstrapped_broker(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(tmp_path / "hypervisor-state.json"))

    payload = build_operator_cometbft_install_payload(_service(tmp_path))

    assert payload["available"] is False
    assert payload["broker"]["configured"] is False
    assert payload["defaults"]["version"] == "v0.38.19"


def test_install_argv_derives_paths_and_keeps_rpc_loopback(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(tmp_path / "hypervisor-state.json"))
    service = _service(tmp_path)

    plan, argv = build_cometbft_install_argv(
        service,
        {
            "mode": "non_validator",
            "chain_id": "aidn-testnet-1",
            "moniker": "node-a",
            "p2p_host": "0.0.0.0",
        },
    )

    assert argv[:3] == [
        "/usr/libexec/aidn-provider-runtime/aidn-provider-runtime-ubuntu.sh",
        "consensus",
        "install",
    ]
    assert "--no-abci" in argv
    assert plan.rpc_host == "127.0.0.1"
    assert plan.home.endswith("consensus\\cometbft") or plan.home.endswith("consensus/cometbft")
    assert "--external-address" not in argv
    assert "--seeds" not in argv
    assert "--persistent-peers" not in argv
    with pytest.raises(ValueError, match="loopback"):
        build_cometbft_install_argv(service, {"rpc_host": "0.0.0.0"})


def test_install_argv_configures_peer_discovery_sources(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(tmp_path / "hypervisor-state.json"))
    service = _service(tmp_path)

    plan, argv = build_cometbft_install_argv(
        service,
        {
            "p2p_host": "0.0.0.0",
            "external_address": "node-a.example:26656",
            "seeds": "seed-a.example:26656,seed-b.example:26656",
            "persistent_peers": "peer-a@10.0.0.2:26656",
        },
    )

    assert plan.external_address == "node-a.example:26656"
    assert plan.seeds == "seed-a.example:26656,seed-b.example:26656"
    assert plan.persistent_peers == "peer-a@10.0.0.2:26656"
    assert "--external-address" in argv
    assert argv[argv.index("--seeds") + 1] == "seed-a.example:26656,seed-b.example:26656"
    assert argv[argv.index("--persistent-peers") + 1] == "peer-a@10.0.0.2:26656"

    with pytest.raises(ValueError, match="host:port"):
        build_cometbft_install_argv(service, {"external_address": "not-an-endpoint"})
    with pytest.raises(ValueError, match="peer ID"):
        build_cometbft_install_argv(service, {"persistent_peers": "bad$id@10.0.0.2:26656"})


def test_install_stages_pending_and_apply_activates_atomically(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(tmp_path / "hypervisor-state.json"))
    monkeypatch.setenv("AIDN_HYPERVISOR_RESTART_ON_BIND_CHANGE", "false")

    calls = []

    class Executor:
        def invoke(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(returncode=0, stdout='{"status":"ok"}', stderr="")

    service = _service(tmp_path, executor=Executor())
    installed = install_cometbft_from_dashboard(
        service,
        {"mode": "validator", "chain_id": "aidn-testnet-1", "moniker": "node-a"},
    )

    assert installed["status"] == "installed_pending_apply"
    assert calls[0]["argv"][1:3] == ["consensus", "install"]
    pending_path = tmp_path / "consensus-config.pending.json"
    assert pending_path.exists()

    applied = apply_pending_cometbft_configuration(service)

    assert applied["status"] == "applied"
    assert applied["restart_scheduled"] is False
    assert (tmp_path / "consensus-config.json").exists()
    assert not pending_path.exists()


def test_install_rejects_colliding_ports(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(tmp_path / "hypervisor-state.json"))
    with pytest.raises(ValueError, match="distinct"):
        build_cometbft_install_argv(_service(tmp_path), {"rpc_port": 26656})


def test_install_route_is_paired_and_accepts_only_reviewed_payload(tmp_path, monkeypatch) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=b"m" * 32)
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    service = _service(tmp_path)
    app = FastAPI()
    app.include_router(
        build_operator_access_router(
            access_service=access,
            credential_store=credentials,
            allow_insecure_lan=True,
            hypervisor_service=service,
        )
    )
    monkeypatch.setattr(
        "aidn_hypervisor.operator_access_api.install_cometbft_from_dashboard",
        lambda _service, payload: {"status": "installed_pending_apply", "mode": payload["mode"]},
    )
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)

    assert client.post("/operators/dashboard/access/operations/cometbft/install", json={}).status_code == 401
    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 204
    response = client.post(
        "/operators/dashboard/access/operations/cometbft/install",
        json={"mode": "validator", "chain_id": "aidn-testnet-1"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "installed_pending_apply"
