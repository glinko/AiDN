from __future__ import annotations

import pytest

from aidn_hypervisor.consensus.external_acceptance import (
    ExternalCometBftAcceptanceConfig,
    verify_external_cometbft_acceptance,
)
from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence


def _config() -> ExternalCometBftAcceptanceConfig:
    return ExternalCometBftAcceptanceConfig.model_validate(
        {
            "rpc_endpoints": ["https://one.example", "https://two.example"],
            "chain_id": "aidn-testnet-1",
            "verifier_id": "acceptance",
            "operation_id": "operation-1",
            "transaction_hash": "A" * 64,
            "trust_period_seconds": 3600,
            "trusted_checkpoint": {
                "height": 1,
                "block_id": "B" * 64,
                "app_hash": "C" * 64,
                "header_time": "2030-01-01T00:00:00Z",
                "validator_set_hash": "D" * 64,
                "next_validator_set_hash": "D" * 64,
                "validators": [
                    {"address": "A" * 40, "public_key": "ed25519:AA==", "voting_power": 1}
                ],
            },
        }
    )


def _evidence(
    *,
    block_id: str = "B" * 64,
    commit_hash: str = "D" * 64,
    finalized_at: str = "2030-01-01T00:00:01Z",
) -> ConsensusFinalityEvidence:
    return ConsensusFinalityEvidence(
        operation_id="operation-1",
        chain_id="aidn-testnet-1",
        block_height=2,
        block_id=block_id,
        app_hash="C" * 64,
        commit_hash=commit_hash,
        finalized_at=finalized_at,
        verifier_id="acceptance",
    )


def test_external_acceptance_requires_matching_verified_evidence_from_all_endpoints() -> None:
    result = verify_external_cometbft_acceptance(
        config=_config(), evidence_loader=lambda _: _evidence()
    )

    assert result["status"] == "ok"
    assert result["rpc_endpoints"] == ["https://one.example", "https://two.example"]
    assert result["ownership_evidence"]["status"] == "NOT_PROVEN_BY_PROTOCOL"


def test_external_acceptance_rejects_divergent_rpc_evidence() -> None:
    with pytest.raises(ValueError, match="disagree"):
        verify_external_cometbft_acceptance(
            config=_config(),
            evidence_loader=lambda endpoint: _evidence(
                block_id=("E" if endpoint.endswith("two.example") else "B") * 64
            ),
        )


@pytest.mark.parametrize(
    ("commit_hash", "finalized_at"),
    [("E" * 64, "2030-01-01T00:00:01Z"), ("D" * 64, "2030-01-01T00:00:02Z")],
)
def test_external_acceptance_rejects_divergent_commit_evidence(
    commit_hash: str,
    finalized_at: str,
) -> None:
    with pytest.raises(ValueError, match="disagree"):
        verify_external_cometbft_acceptance(
            config=_config(),
            evidence_loader=lambda endpoint: _evidence(
                commit_hash=commit_hash if endpoint.endswith("two.example") else "D" * 64,
                finalized_at=finalized_at if endpoint.endswith("two.example") else "2030-01-01T00:00:01Z",
            ),
        )


def test_external_acceptance_rejects_non_https_rpc_endpoint() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        ExternalCometBftAcceptanceConfig.model_validate(
            _config().model_dump() | {"rpc_endpoints": ["http://one.example", "https://two.example"]}
        )
