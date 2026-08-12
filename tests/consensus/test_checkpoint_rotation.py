from __future__ import annotations

from aidn_hypervisor.consensus.checkpoint_rotation import (
    CometBftCheckpointCandidate,
    rotate_checkpoint,
)
from aidn_hypervisor.consensus.deployment import (
    CometBftDeploymentCheckpoint,
    CometBftDeploymentValidator,
    CometBftFinalityDeploymentConfig,
)
from aidn_hypervisor.consensus.light_client import CometBftValidator, CometBftValidatorSet


def _config() -> CometBftFinalityDeploymentConfig:
    validator = CometBftDeploymentValidator(
        address="A" * 40,
        public_key="ed25519:" + "A" * 44,
        voting_power=1,
    )
    return CometBftFinalityDeploymentConfig(
        rpc_endpoints=[
            "http://validator-a.example",
            "http://validator-b.example",
            "http://validator-c.example",
        ],
        minimum_agreement=2,
        chain_id="aidn-testnet-1",
        verifier_id="test-rotation",
        trusted_checkpoint=CometBftDeploymentCheckpoint(
            height=10,
            block_id="A" * 64,
            app_hash="B" * 64,
            header_time="2030-01-01T00:00:00Z",
            validator_set_hash="C" * 64,
            next_validator_set_hash="D" * 64,
            validators=[validator],
        ),
        trust_period_seconds=86_400,
    )


def _candidate(height: int = 11) -> CometBftCheckpointCandidate:
    deployment_validator = CometBftDeploymentValidator(
        address="E" * 40,
        public_key="ed25519:" + "E" * 44,
        voting_power=1,
    )
    return CometBftCheckpointCandidate(
        endpoint="test",
        checkpoint=CometBftDeploymentCheckpoint(
            height=height,
            block_id="F" * 64,
            app_hash="1" * 64,
            header_time="2030-01-01T00:00:01Z",
            validator_set_hash="2" * 64,
            next_validator_set_hash="3" * 64,
            validators=[deployment_validator],
        ),
        next_validator_set=CometBftValidatorSet(
            (
                CometBftValidator(
                    address="G" * 40,
                    public_key="ed25519:" + "G" * 44,
                    voting_power=1,
                ),
            )
        ),
    )


def test_rotation_accepts_unique_quorum_with_one_failed_rpc(monkeypatch):
    candidate = _candidate()

    def collect(*, endpoint, transport, config, height):
        if endpoint.endswith("c.example"):
            raise ValueError("offline")
        return candidate

    monkeypatch.setattr(
        "aidn_hypervisor.consensus.checkpoint_rotation.collect_checkpoint_candidate",
        collect,
    )
    checkpoint, agreement, failures = rotate_checkpoint(
        config=_config(),
        height=11,
        transports=[object(), object(), object()],
    )

    assert checkpoint.height == 11
    assert agreement == 2
    assert failures == [{"endpoint": "http://validator-c.example", "error": "offline"}]


def test_rotation_rejects_conflicting_quorum_groups(monkeypatch):
    candidates = [_candidate(), _candidate(), _candidate(), _candidate()]
    candidates[2] = candidates[2].__class__(
        endpoint="test-b",
        checkpoint=candidates[2].checkpoint.model_copy(update={"block_id": "0" * 64}),
        next_validator_set=candidates[2].next_validator_set,
    )
    candidates[3] = candidates[3].__class__(
        endpoint="test-c",
        checkpoint=candidates[3].checkpoint.model_copy(update={"block_id": "0" * 64}),
        next_validator_set=candidates[3].next_validator_set,
    )

    def collect(*, endpoint, transport, config, height):
        index_by_endpoint = {
            "http://validator-a.example": 0,
            "http://validator-b.example": 1,
            "http://validator-c.example": 2,
            "http://validator-d.example": 3,
        }
        return candidates[index_by_endpoint[endpoint]]

    monkeypatch.setattr(
        "aidn_hypervisor.consensus.checkpoint_rotation.collect_checkpoint_candidate",
        collect,
    )
    try:
        rotate_checkpoint(
            config=_config().model_copy(
                update={
                    "rpc_endpoints": [
                        "http://validator-a.example",
                        "http://validator-b.example",
                        "http://validator-c.example",
                        "http://validator-d.example",
                    ]
                }
            ),
            height=11,
            transports=[object(), object(), object(), object()],
        )
    except ValueError as error:
        assert "CHECKPOINT_ROTATION_QUORUM_NOT_REACHED" in str(error)
    else:
        raise AssertionError("conflicting checkpoint groups must be rejected")
