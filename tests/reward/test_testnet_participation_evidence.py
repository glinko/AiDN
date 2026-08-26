from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.testnet_participation import (
    TestnetParticipantEnrollment as ParticipantEnrollment,
)
from aidn_hypervisor.testnet_participation import (
    TestnetParticipationProgram as ParticipationProgram,
)
from aidn_hypervisor.testnet_participation import (
    build_testnet_heartbeat_evidence,
)
from aidn_hypervisor.testnet_participation_evidence import (
    TestnetParticipationEvidenceStore as EvidenceStore,
)

START = datetime(2026, 9, 1, tzinfo=UTC)


def _public_key(private_key: Ed25519PrivateKey) -> str:
    return "ed25519:" + private_key.public_key().public_bytes_raw().hex()


def _enrollment() -> ParticipantEnrollment:
    return ParticipantEnrollment(
        node_id="node-1",
        owner_wallet="wallet-owner",
        reward_wallet="wallet-reward",
        registered_at=(START - timedelta(minutes=30)).isoformat(),
        registered_epoch=9,
    )


def _heartbeat(private_key: Ed25519PrivateKey, *, observed_at: str | None = None):
    unsigned = build_testnet_heartbeat_evidence(
        evidence_id="heartbeat-1",
        node_id="node-1",
        network_id="aidn-testnet",
        chain_id="aidn-testnet-1",
        observed_at=observed_at or START.isoformat(),
        protocol_version="0.1",
        identity_signature_verified=False,
    )
    return unsigned.model_copy(
        update={
            "identity_signature": "ed25519:"
            + private_key.sign(unsigned.signing_bytes()).hex()
        }
    )


def test_store_accepts_only_finalized_heartbeat_signed_by_enrolled_node(tmp_path) -> None:
    key = Ed25519PrivateKey.generate()
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    store.register_enrollment(
        _enrollment(),
        public_key=_public_key(key),
        binding_operation_id="operator-wallet-bind:node-1",
    )

    stored = store.record_finalized_heartbeat(_heartbeat(key))

    assert stored.identity_signature_verified is True
    assert list(store.snapshot_enrollments())[0].node_id == "node-1"


def test_store_rejects_missing_or_wrong_node_signature(tmp_path) -> None:
    key = Ed25519PrivateKey.generate()
    other_key = Ed25519PrivateKey.generate()
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    store.register_enrollment(
        _enrollment(),
        public_key=_public_key(key),
        binding_operation_id="operator-wallet-bind:node-1",
    )
    unsigned = build_testnet_heartbeat_evidence(
        evidence_id="heartbeat-bad",
        node_id="node-1",
        network_id="aidn-testnet",
        chain_id="aidn-testnet-1",
        observed_at=START.isoformat(),
        protocol_version="0.1",
        identity_signature_verified=False,
    )
    invalid = unsigned.model_copy(
        update={
            "identity_signature": "ed25519:"
            + other_key.sign(unsigned.signing_bytes()).hex()
        }
    )

    with pytest.raises(ValueError, match="SIGNATURE_INVALID"):
        store.record_finalized_heartbeat(invalid)


def test_settlement_inputs_are_period_bounded_and_only_include_finalized_evidence(tmp_path) -> None:
    key = Ed25519PrivateKey.generate()
    store = EvidenceStore(tmp_path / "evidence.sqlite")
    store.register_enrollment(
        _enrollment(),
        public_key=_public_key(key),
        binding_operation_id="operator-wallet-bind:node-1",
    )
    store.record_finalized_heartbeat(_heartbeat(key))
    next_day_unsigned = build_testnet_heartbeat_evidence(
        evidence_id="heartbeat-next-day",
        node_id="node-1",
        network_id="aidn-testnet",
        chain_id="aidn-testnet-1",
        observed_at=(START + timedelta(days=1)).isoformat(),
        protocol_version="0.1",
        identity_signature_verified=False,
    )
    store.record_finalized_heartbeat(
        next_day_unsigned.model_copy(
            update={
                "identity_signature": "ed25519:"
                + key.sign(next_day_unsigned.signing_bytes()).hex()
            }
        )
    )
    program = ParticipationProgram(
        program_id="testnet-alpha-participation-1",
        network_id="aidn-testnet",
        chain_id="aidn-testnet-1",
        active_from_epoch=10,
        compatible_protocol_versions=["0.1"],
    )

    enrollments, heartbeats = store.settlement_inputs(
        program, period_start=START.isoformat()
    )

    assert len(enrollments) == 1
    assert [item.evidence_id for item in heartbeats] == ["heartbeat-1"]
