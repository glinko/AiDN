from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from aidn_faucet.api import build_app
from aidn_faucet.cli import _serve, build_parser
from aidn_faucet.policy import FixedDailyPolicy
from aidn_faucet.service import FaucetService, TreasurySigner
from aidn_faucet.store import FaucetStore
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from aidn_hypervisor.faucet_treasury import FaucetTreasuryManifest


class Submitter:
    def __init__(self) -> None:
        self.balance = 100_000_000

    def next_sender_sequence(self, wallet_id: str) -> int:
        del wallet_id
        return 1

    def treasury_balance_q_atoms(self, wallet_id: str) -> int:
        del wallet_id
        return self.balance

    def submit_transfer(self, envelope):
        del envelope
        raise AssertionError("paused Faucet must not submit")

    def reconcile_transfer(self, envelope):
        del envelope
        raise AssertionError("paused Faucet must not reconcile")


def _public_key(key: Ed25519PrivateKey) -> str:
    return "ed25519:" + key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()


def _service(tmp_path):
    treasury_key = Ed25519PrivateKey.generate()
    public_key = _public_key(treasury_key)
    manifest = FaucetTreasuryManifest(
        treasury_id="faucet-treasury-controls-v1",
        network_id="aidn-localnet-1",
        chain_id="aidn-testnet-1",
        wallet_id="wallet-" + hashlib.sha256(public_key.encode()).hexdigest()[:12],
        wallet_public_key=public_key,
        creator_recovery_wallet="wallet-creator-recovery",
        genesis_allocation_q_atoms=10_000_000_000_000,
        policy_registry_hash="sha256:" + ("ab" * 32),
    )
    submitter = Submitter()
    service = FaucetService(
        manifest=manifest,
        signer=TreasurySigner(treasury_key, expected_public_key=public_key),
        policy=FixedDailyPolicy(amount_q=50),
        store=FaucetStore(tmp_path / "faucet.sqlite"),
        submitter=submitter,
        agent_token="agent-secret",
        creator_token="creator-secret",
        require_treasury_activation=False,
        now=lambda: datetime(2030, 1, 1, tzinfo=UTC),
    )
    return service, submitter


def test_creator_pause_and_resume_are_durable(tmp_path) -> None:
    service, _ = _service(tmp_path)

    with pytest.raises(PermissionError, match="UNAUTHORIZED"):
        service.authorize_creator("wrong")
    service.authorize_creator("creator-secret")

    paused = service.pause(reason="maintenance")
    assert paused["paused"] is True
    assert service.status().paused is True
    with pytest.raises(ValueError, match="FAUCET_PAUSED"):
        service._ensure_claims_enabled()

    service.resume()
    assert service.status().paused is False


def test_low_balance_watermark_blocks_without_mutating_policy(tmp_path) -> None:
    service, submitter = _service(tmp_path)
    service.set_low_balance_watermark(watermark_q_atoms=200_000_000)

    assert service.status().low_balance_blocked is True
    with pytest.raises(ValueError, match="LOW_BALANCE_PAUSED"):
        service._ensure_claims_enabled()

    submitter.balance = 300_000_000
    assert service.status().low_balance_blocked is False


def test_creator_http_surface_is_separate_from_agent_auth(tmp_path) -> None:
    service, _ = _service(tmp_path)
    client = TestClient(build_app(service))

    assert client.get("/v1/admin/status").status_code == 401
    assert client.post(
        "/v1/admin/pause",
        headers={"Authorization": "Bearer creator-secret"},
        json={"reason": "planned maintenance"},
    ).status_code == 200
    assert client.get(
        "/v1/admin/status",
        headers={"Authorization": "Bearer creator-secret"},
    ).json()["paused"] is True


def _mcp_call(client, payload, *, token, session_id=None):
    headers = {"Authorization": f"Bearer {token}"}
    if session_id is not None:
        headers["Mcp-Session-Id"] = session_id
    return client.post("/mcp", headers=headers, json=payload)


def test_faucet_mcp_separates_agent_and_creator_tools(tmp_path) -> None:
    service, _ = _service(tmp_path)
    client = TestClient(build_app(service))

    initialized = _mcp_call(
        client,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        },
        token="agent-secret",
    )
    assert initialized.status_code == 200
    session_id = initialized.headers["Mcp-Session-Id"]

    tools = _mcp_call(
        client,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        token="agent-secret",
        session_id=session_id,
    ).json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert "aidn.faucet.status" in names
    assert "aidn.faucet.admin.pause" not in names

    denied = _mcp_call(
        client,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "aidn.faucet.admin.pause", "arguments": {"reason": "no"}},
        },
        token="agent-secret",
        session_id=session_id,
    ).json()
    assert denied["result"]["isError"] is True
    assert denied["result"]["structuredContent"]["error"]["code"] == "MCP_PERMISSION_DENIED"

    creator_initialized = _mcp_call(
        client,
        {"jsonrpc": "2.0", "id": 4, "method": "initialize", "params": {}},
        token="creator-secret",
    )
    creator_session = creator_initialized.headers["Mcp-Session-Id"]
    creator_tools = _mcp_call(
        client,
        {"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}},
        token="creator-secret",
        session_id=creator_session,
    ).json()["result"]["tools"]
    creator_names = {tool["name"] for tool in creator_tools}
    assert "aidn.faucet.admin.pause" in creator_names
    assert "aidn.faucet.claim" not in creator_names


def test_faucet_admin_ui_is_available_without_leaking_creator_state(tmp_path) -> None:
    service, _ = _service(tmp_path)
    client = TestClient(build_app(service))

    page = client.get("/")
    assert page.status_code == 200
    assert "Faucet control room" in page.text
    assert "creator-secret" not in page.text
    assert client.get("/v1/admin/status").status_code == 401


def test_cli_exposes_explicit_lan_mode() -> None:
    args = build_parser().parse_args(
        [
            "serve",
            "--manifest",
            "manifest.json",
            "--private-key",
            "treasury.key",
            "--state",
            "faucet.sqlite",
            "--lan",
        ]
    )

    assert args.lan is True
    assert args.host == "127.0.0.1"


def test_cli_rejects_unauthenticated_non_loopback_bind() -> None:
    args = build_parser().parse_args(
        [
            "serve",
            "--manifest",
            "manifest.json",
            "--private-key",
            "treasury.key",
            "--state",
            "faucet.sqlite",
            "--host",
            "192.168.88.127",
        ]
    )

    with pytest.raises(ValueError, match="requires bearer authentication"):
        _serve(args)
