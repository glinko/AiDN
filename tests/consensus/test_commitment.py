"""M7-S6: State commitment — RFC-0047 §24."""

from __future__ import annotations

import pytest

from aidn_hypervisor.consensus.commitment import (
    CommitmentRecord,
    StateCommitment,
    StateCommitmentService,
)


# ── StateCommitment model ───────────────────────────────────────────


def test_state_commitment_creation() -> None:
    c = StateCommitment(
        epoch=0,
        block_height=100,
        state_hash="abc123",
        timestamp="2025-01-01T00:00:00Z",
    )
    assert c.epoch == 0
    assert c.block_height == 100
    assert c.state_hash == "abc123"
    assert c.validator_set_hash is None


def test_state_commitment_frozen() -> None:
    c = StateCommitment(
        epoch=0,
        block_height=100,
        state_hash="abc123",
        timestamp="2025-01-01T00:00:00Z",
    )
    with pytest.raises(Exception):
        c.epoch = 1  # type: ignore


# ── StateCommitmentService ──────────────────────────────────────────


def test_compute_state_hash() -> None:
    svc = StateCommitmentService()
    h = svc.compute_state_hash({"a": 1, "b": 2})
    assert isinstance(h, str)
    assert len(h) == 64  # SHA-256 hex


def test_state_hash_deterministic() -> None:
    svc = StateCommitmentService()
    data = {"x": 10, "y": 20}
    h1 = svc.compute_state_hash(data)
    h2 = svc.compute_state_hash(data)
    assert h1 == h2


def test_state_hash_canonical() -> None:
    svc = StateCommitmentService()
    h1 = svc.compute_state_hash({"b": 2, "a": 1})
    h2 = svc.compute_state_hash({"a": 1, "b": 2})
    assert h1 == h2  # sorted keys → same hash


def test_state_hash_different_data() -> None:
    svc = StateCommitmentService()
    h1 = svc.compute_state_hash({"a": 1})
    h2 = svc.compute_state_hash({"a": 2})
    assert h1 != h2


def test_create_commitment() -> None:
    svc = StateCommitmentService()
    c = svc.create_commitment(
        epoch=0,
        block_height=50,
        state_data={"balance": 100},
        timestamp="2025-06-01T00:00:00Z",
    )
    assert c.epoch == 0
    assert c.block_height == 50
    assert c.state_hash == svc.compute_state_hash({"balance": 100})


def test_verify_commitment_valid() -> None:
    svc = StateCommitmentService()
    state_data = {"wallet": "A", "balance": 500}
    svc.create_commitment(
        epoch=3,
        block_height=300,
        state_data=state_data,
        timestamp="2025-06-01T00:00:00Z",
    )
    assert svc.verify_commitment(3, state_data) is True


def test_verify_commitment_invalid() -> None:
    svc = StateCommitmentService()
    svc.create_commitment(
        epoch=3,
        block_height=300,
        state_data={"wallet": "A", "balance": 500},
        timestamp="2025-06-01T00:00:00Z",
    )
    assert svc.verify_commitment(3, {"wallet": "A", "balance": 999}) is False


def test_verify_commitment_unknown_epoch() -> None:
    svc = StateCommitmentService()
    assert svc.verify_commitment(99, {}) is False


def test_get_latest_commitment() -> None:
    svc = StateCommitmentService()
    svc.create_commitment(
        epoch=0,
        block_height=10,
        state_data={"x": 1},
        timestamp="2025-01-01T00:00:00Z",
    )
    svc.create_commitment(
        epoch=0,
        block_height=20,
        state_data={"x": 2},
        timestamp="2025-01-01T00:01:00Z",
    )
    latest = svc.get_latest_commitment(0)
    assert latest is not None
    assert latest.block_height == 20


def test_get_latest_commitment_none() -> None:
    svc = StateCommitmentService()
    assert svc.get_latest_commitment(5) is None


def test_get_all_commitments() -> None:
    svc = StateCommitmentService()
    svc.create_commitment(
        epoch=0,
        block_height=10,
        state_data={"a": 1},
        timestamp="2025-01-01T00:00:00Z",
    )
    svc.create_commitment(
        epoch=1,
        block_height=110,
        state_data={"b": 2},
        timestamp="2025-01-02T00:00:00Z",
    )
    all_c = svc.get_all_commitments()
    assert len(all_c) == 2


def test_record_commitment() -> None:
    svc = StateCommitmentService()
    c = svc.create_commitment(
        epoch=0,
        block_height=10,
        state_data={"x": 1},
        timestamp="2025-01-01T00:00:00Z",
    )
    rec = svc.record_commitment(
        c,
        signature="sig-abc",
        node_id="node-1",
        verified=True,
    )
    assert rec.commitment.epoch == 0
    assert rec.signature == "sig-abc"
    assert rec.committed_by == "node-1"
    assert rec.verified is True


def test_commitment_record_frozen() -> None:
    svc = StateCommitmentService()
    c = svc.create_commitment(
        epoch=0,
        block_height=10,
        state_data={"x": 1},
        timestamp="2025-01-01T00:00:00Z",
    )
    rec = svc.record_commitment(c, signature="s1", node_id="n1")
    with pytest.raises(Exception):
        rec.verified = True  # type: ignore


def test_multiple_epochs_commitments() -> None:
    svc = StateCommitmentService()
    for ep in range(3):
        svc.create_commitment(
            epoch=ep,
            block_height=ep * 100,
            state_data={"epoch": ep},
            timestamp="2025-01-01T00:00:00Z",
        )
    assert len(svc.get_all_commitments()) == 3
    for ep in range(3):
        assert svc.verify_commitment(ep, {"epoch": ep}) is True


def test_commitment_timestamp() -> None:
    svc = StateCommitmentService()
    ts = "2025-12-25T12:00:00Z"
    c = svc.create_commitment(
        epoch=0,
        block_height=1,
        state_data={},
        timestamp=ts,
    )
    assert c.timestamp == ts
