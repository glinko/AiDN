from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aidn_hypervisor.main import _is_validator_consensus_write_path
from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.operator_access import DashboardAccessService
from aidn_hypervisor.operator_access_api import build_operator_access_router
from aidn_hypervisor.operator_cometbft import (
    build_operator_cometbft_payload,
    control_managed_cometbft,
)
from aidn_hypervisor.secrets import FileSecretManager

_BROWSER_HEADERS = {"X-AiDN-Browser-Key": "browser-key-for-cometbft-tests-000000000000000000000000"}


class _Consensus:
    is_enabled = True

    def __init__(self, *, service_name: str | None = "aidn-cometbft.service") -> None:
        self.config = SimpleNamespace(
            managed_service_name=service_name,
            cometbft_endpoint="tcp://127.0.0.1:26657?secret=removed",
            node_id="node-local",
            chain_id="aidn-localnet-1",
            mode=SimpleNamespace(value="validator"),
        )

    def status(self) -> dict:
        return {
            "enabled": True,
            "mode": "validator",
            "node_id": "node-local",
            "chain_id": "aidn-localnet-1",
            "rpc": {
                "available": True,
                "latest_block_height": 42,
                "peer_count": 3,
            },
            "management": {"managed": True, "service": "ignored-by-read-model"},
            "metrics": {"total_submitted": 2},
            "protocol_authority": {"configured": False},
        }


def test_operator_cometbft_payload_is_bounded_and_sanitized() -> None:
    payload = build_operator_cometbft_payload(SimpleNamespace(consensus_service=_Consensus()))

    assert payload["profile"] == "operator-cometbft-v1"
    assert payload["rpc_endpoint"] == "tcp://127.0.0.1:26657"
    assert payload["management"] == {
        "managed": True,
        "service": "aidn-cometbft.service",
        "control_supported": True,
    }
    assert payload["rpc"]["latest_block_height"] == 42
    assert payload["protocol_authority"] == {"configured": False}


def test_operator_cometbft_payload_reports_disabled_service() -> None:
    payload = build_operator_cometbft_payload(SimpleNamespace(consensus_service=None))

    assert payload["enabled"] is False
    assert payload["rpc"]["reason"] == "consensus_service_unavailable"
    assert payload["management"]["control_supported"] is False


def test_operator_cometbft_control_invokes_only_configured_user_unit() -> None:
    calls: list[tuple[list[str], dict]] = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr="")

    result = control_managed_cometbft(
        SimpleNamespace(consensus_service=_Consensus()),
        "restart",
        runner=runner,
    )

    assert result == {
        "status": "ok",
        "action": "restart",
        "service": "aidn-cometbft.service",
    }
    assert calls[0][0] == ["systemctl", "--user", "restart", "aidn-cometbft.service"]
    assert calls[0][1]["check"] is False


def test_operator_cometbft_control_rejects_unconfigured_unit_and_action() -> None:
    with pytest.raises(ValueError, match="not managed"):
        control_managed_cometbft(
            SimpleNamespace(consensus_service=_Consensus(service_name=None)),
            "start",
            runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr=""),
        )
    with pytest.raises(ValueError, match="must be start"):
        control_managed_cometbft(
            SimpleNamespace(consensus_service=_Consensus()),
            "status",
            runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr=""),
        )


def test_validator_boundary_allows_only_allowlisted_cometbft_actions() -> None:
    for action in ("start", "stop", "restart"):
        assert _is_validator_consensus_write_path(
            f"/operators/dashboard/access/operations/cometbft/{action}",
            "POST",
        ) is True
    assert _is_validator_consensus_write_path(
        "/operators/dashboard/access/operations/cometbft/status",
        "POST",
    ) is False
    assert _is_validator_consensus_write_path(
        "/operators/dashboard/access/operations/cometbft/start",
        "GET",
    ) is False


def test_cometbft_control_route_requires_paired_dashboard(monkeypatch, tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=b"m" * 32)
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    app = FastAPI()
    app.include_router(build_operator_access_router(
        access_service=access,
        credential_store=credentials,
        allow_insecure_lan=True,
        hypervisor_service=SimpleNamespace(consensus_service=_Consensus()),
    ))
    monkeypatch.setattr(
        "aidn_hypervisor.operator_access_api.control_managed_cometbft",
        lambda _service, action: {"status": "ok", "action": action, "service": "aidn-cometbft.service"},
    )
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)

    assert client.post("/operators/dashboard/access/operations/cometbft/start").status_code == 401
    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 200
    response = client.post("/operators/dashboard/access/operations/cometbft/restart")

    assert response.status_code == 202
    assert response.json()["action"] == "restart"
