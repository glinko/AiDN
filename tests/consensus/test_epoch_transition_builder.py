from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.epoch_transition import (
    build_signed_epoch_transition,
    load_protocol_authority_private_key,
)
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy
from aidn_hypervisor.endpoint_publications.signing import public_key_for_private_key

PRIVATE_KEYS = tuple("ed25519:" + value * 32 for value in ("11", "22", "33"))


def _policy() -> ProtocolAuthorityPolicy:
    return ProtocolAuthorityPolicy(
        threshold=2,
        authorities=tuple(
            (f"authority-{index}", public_key_for_private_key(key))
            for index, key in enumerate(PRIVATE_KEYS, start=1)
        ),
    )


def _payload() -> dict[str, object]:
    return {
        "closing_epoch": 20,
        "opening_epoch": 21,
        "closing_state_root": "sha256:closing-state",
        "epoch_task_result_root": "sha256:epoch-tasks",
        "eligibility_snapshot_root": "sha256:eligibility",
        "reward_calculation_root": "sha256:reward-calculation",
        "next_protocol_parameters_hash": "sha256:next-parameters",
        "pool_budgets": {"GENERAL_DEVELOPMENT": 250_000},
        "pool_budget_references": {
            "GENERAL_DEVELOPMENT": "epoch:20:GENERAL_DEVELOPMENT"
        },
    }


def _keys(*indexes: int) -> dict[str, Ed25519PrivateKey]:
    return {
        f"authority-{index + 1}": Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(PRIVATE_KEYS[index].removeprefix("ed25519:"))
        )
        for index in indexes
    }


def test_builder_adds_policy_hash_and_validates_quorum() -> None:
    policy = _policy()
    envelope = build_signed_epoch_transition(
        policy=policy,
        payload=_payload(),
        signers=_keys(0, 1),
        created_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-02T00:00:00Z",
    )

    assert envelope.payload["protocol_authority_policy_hash"] == policy.policy_hash
    assert len(envelope.signatures) == 2
    policy.verify_epoch_transition(envelope)


def test_builder_rejects_insufficient_quorum() -> None:
    with pytest.raises(ValueError, match="signer quorum is not met"):
        build_signed_epoch_transition(
            policy=_policy(),
            payload=_payload(),
            signers=_keys(0),
            created_at="2030-01-01T00:00:00Z",
        )


def test_builder_rejects_key_not_bound_to_declared_authority() -> None:
    policy = _policy()
    wrong_key = {"authority-1": _keys(1)["authority-2"]}
    wrong_key["authority-2"] = _keys(0)["authority-1"]

    with pytest.raises(ValueError, match="private key does not match"):
        build_signed_epoch_transition(
            policy=policy,
            payload=_payload(),
            signers=wrong_key,
            created_at="2030-01-01T00:00:00Z",
        )


def test_builder_rejects_invalid_ledger_payload() -> None:
    payload = _payload()
    payload["opening_epoch"] = 23
    with pytest.raises(ValueError, match="opening epoch must immediately follow"):
        build_signed_epoch_transition(
            policy=_policy(),
            payload=payload,
            signers=_keys(0, 1),
            created_at="2030-01-01T00:00:00Z",
        )


def test_private_key_loader_accepts_seed_file_without_exporting_key(tmp_path: Path) -> None:
    path = tmp_path / "authority-1.seed"
    path.write_text(PRIVATE_KEYS[0].removeprefix("ed25519:"), encoding="ascii")
    key = load_protocol_authority_private_key(path)
    assert public_key_for_private_key(PRIVATE_KEYS[0]) == (
        "ed25519:" + key.public_key().public_bytes_raw().hex()
    )


def test_output_shape_is_json_serializable() -> None:
    envelope = build_signed_epoch_transition(
        policy=_policy(),
        payload=_payload(),
        signers=_keys(0, 1),
        created_at="2030-01-01T00:00:00Z",
    )
    assert json.loads(json.dumps(envelope.model_dump(mode="json")))['operation_type'] == (
        "EPOCH_TRANSITION"
    )
