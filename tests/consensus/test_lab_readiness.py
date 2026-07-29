from __future__ import annotations

import pytest

from aidn_hypervisor.consensus.lab_readiness import (
    CometBftLabObservation,
    CometBftLanTestnetConfig,
    validate_cometbft_lab_quorum,
)

ENDPOINTS = [f"http://192.168.88.{host}:26657" for host in range(127, 131)]


def _config(**overrides: object) -> CometBftLanTestnetConfig:
    return CometBftLanTestnetConfig.model_validate(
        {
            "rpc_endpoints": ENDPOINTS,
            "allow_insecure_private_http": True,
        }
        | overrides
    )


def _observations(**overrides: object) -> list[CometBftLabObservation]:
    values = [
        CometBftLabObservation(
            endpoint=endpoint,
            node_id=f"node-{index}",
            chain_id="aidn-lan-testnet",
            height=42,
            app_hash="A" * 64,
            catching_up=False,
            peer_count=3,
        )
        for index, endpoint in enumerate(ENDPOINTS)
    ]
    for index, value in enumerate(values):
        values[index] = value.model_copy(update=overrides)
    return values


def test_lab_readiness_accepts_a_healthy_four_node_private_lab() -> None:
    result = validate_cometbft_lab_quorum(config=_config(), observations=_observations())

    assert result["status"] == "ok"
    assert result["transport_security"] == "PRIVATE_LAN_HTTP"
    assert result["ownership_evidence"]["status"] == "NOT_PROVEN_BY_PROTOCOL"


def test_lab_readiness_rejects_insecure_http_without_explicit_opt_in() -> None:
    with pytest.raises(ValueError, match="explicit"):
        _config(allow_insecure_private_http=False)


def test_lab_readiness_rejects_a_missing_peer_quorum() -> None:
    observations = _observations()
    observations[0] = observations[0].model_copy(update={"peer_count": 2})

    with pytest.raises(ValueError, match="peer quorum"):
        validate_cometbft_lab_quorum(config=_config(), observations=observations)


def test_lab_readiness_rejects_conflicting_application_hashes() -> None:
    observations = _observations()
    observations[-1] = observations[-1].model_copy(update={"app_hash": "B" * 64})

    with pytest.raises(ValueError, match="application hash"):
        validate_cometbft_lab_quorum(config=_config(), observations=observations)
