from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy
from aidn_hypervisor.endpoint_publications.signing import (
    public_key_for_private_key,
    sign_consensus_bytes,
)
from aidn_hypervisor.ledger.service import LedgerOperationService

NOW = datetime(2030, 1, 1, tzinfo=UTC)
PRIVATE_KEYS = (
    "ed25519:" + "11" * 32,
    "ed25519:" + "22" * 32,
    "ed25519:" + "33" * 32,
)


def _timestamp(*, hours: int = 0) -> str:
    return (NOW + timedelta(hours=hours)).isoformat()


def _policy(*, threshold: int = 2) -> ProtocolAuthorityPolicy:
    return ProtocolAuthorityPolicy(
        threshold=threshold,
        authorities=tuple(
            (f"authority-{index}", public_key_for_private_key(private_key))
            for index, private_key in enumerate(PRIVATE_KEYS, start=1)
        ),
    )


def _payload(policy: ProtocolAuthorityPolicy) -> dict[str, object]:
    return {
        "closing_epoch": 7,
        "opening_epoch": 8,
        "closing_state_root": "sha256:closing-state",
        "epoch_task_result_root": "sha256:epoch-tasks",
        "eligibility_snapshot_root": "sha256:eligibility",
        "reward_calculation_root": "sha256:calculation",
        "next_protocol_parameters_hash": "sha256:next-parameters",
        "pool_budgets": {"general_development": 250_000},
        "pool_budget_references": {"general_development": "epoch:7:general-development"},
        "protocol_authority_policy_hash": policy.policy_hash,
    }


def _envelope(
    policy: ProtocolAuthorityPolicy,
    *,
    signatures: list[str] | None = None,
    payload: dict[str, object] | None = None,
) -> LedgerOperationEnvelope:
    return LedgerOperationEnvelope(
        operation_type="EPOCH_TRANSITION",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="protocol",
        initiator_id="epoch-engine",
        sender_wallet=None,
        sender_sequence=None,
        fee_payer=None,
        fee_class="protocol_sponsored",
        created_at=_timestamp(),
        expires_at=_timestamp(hours=24),
        target_epoch="7",
        payload=payload or _payload(policy),
        signatures=signatures or [],
    )


def _signed(
    policy: ProtocolAuthorityPolicy,
    *key_indexes: int,
    payload: dict[str, object] | None = None,
) -> LedgerOperationEnvelope:
    unsigned = _envelope(policy, payload=payload)
    signatures = [
        sign_consensus_bytes(
            private_key=PRIVATE_KEYS[index],
            payload=unsigned.signing_bytes(),
        )
        for index in key_indexes
    ]
    return unsigned.model_copy(update={"signatures": signatures})


def _app(policy: ProtocolAuthorityPolicy) -> tuple[AIDNABCIApplication, LedgerOperationService]:
    ledger = LedgerOperationService()
    return (
        AIDNABCIApplication(
            ledger_service=ledger,
            admission_validator=AdmissionValidator(current_time=_timestamp()),
            strict_operation_coverage=True,
            protocol_authority_policy=policy,
        ),
        ledger,
    )


def test_unsigned_epoch_transition_is_rejected_at_check_and_block_execution() -> None:
    policy = _policy()
    app, ledger = _app(policy)
    tx = _envelope(policy)
    raw = tx.consensus_bytes()

    check = app.check_transaction(raw)
    assert check.code == "rejected"
    assert check.log == "EPOCH_TRANSITION_AUTHORITY_SIGNATURE_REQUIRED"
    recheck = app.check_transaction(raw, recheck=True)
    assert recheck.code == "rejected"
    assert recheck.log == "EPOCH_TRANSITION_AUTHORITY_SIGNATURE_REQUIRED"

    _, results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[raw],
    )
    assert results[0].code == "rejected"
    assert results[0].log == "EPOCH_TRANSITION_AUTHORITY_SIGNATURE_REQUIRED"
    assert ledger.snapshot_operations() == []


def test_epoch_transition_requires_distinct_authority_quorum() -> None:
    policy = _policy()
    app, ledger = _app(policy)
    tx = _signed(policy, 0)

    _, results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"B" * 32,
        txs=[tx.consensus_bytes()],
    )
    assert results[0].code == "rejected"
    assert results[0].log == "EPOCH_TRANSITION_AUTHORITY_SIGNATURE_REQUIRED"
    assert ledger.snapshot_operations() == []

    duplicate = _envelope(policy, signatures=[tx.signatures[0], tx.signatures[0]])
    _, duplicate_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"C" * 32,
        txs=[duplicate.consensus_bytes()],
    )
    assert duplicate_results[0].code == "rejected"
    assert duplicate_results[0].log == "EPOCH_TRANSITION_AUTHORITY_QUORUM_NOT_MET"


def test_epoch_transition_rejects_tampered_payload_and_accepts_valid_quorum() -> None:
    policy = _policy()
    app, ledger = _app(policy)
    signed = _signed(policy, 0, 1)
    tampered_payload = {**signed.payload, "reward_calculation_root": "sha256:tampered"}
    tampered = _envelope(policy, signatures=list(signed.signatures), payload=tampered_payload)

    _, tampered_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"D" * 32,
        txs=[tampered.consensus_bytes()],
    )
    assert tampered_results[0].code == "rejected"
    assert tampered_results[0].log == "EPOCH_TRANSITION_AUTHORITY_QUORUM_NOT_MET"
    assert ledger.snapshot_operations() == []

    _, valid_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"E" * 32,
        txs=[signed.consensus_bytes()],
    )
    assert valid_results[0].code == "ok"
    assert [item["operation_type"] for item in ledger.snapshot_operations()] == [
        "EPOCH_TRANSITION"
    ]


def test_policy_mapping_binds_declared_policy_hash() -> None:
    policy = _policy()
    loaded = ProtocolAuthorityPolicy.from_mapping(policy.as_dict())
    assert loaded.policy_hash == policy.policy_hash

    invalid = {**policy.as_dict(), "policy_hash": "sha256:not-the-policy"}
    try:
        ProtocolAuthorityPolicy.from_mapping(invalid)
    except ValueError as error:
        assert str(error) == "protocol authority policy hash is invalid"
    else:
        raise AssertionError("invalid policy hash was accepted")


def test_policy_rejects_duplicate_public_keys_under_different_authority_ids() -> None:
    public_key = public_key_for_private_key(PRIVATE_KEYS[0])
    try:
        ProtocolAuthorityPolicy(
            threshold=2,
            authorities=(("authority-1", public_key), ("authority-2", public_key)),
        )
    except ValueError as error:
        assert str(error) == "protocol authority public keys must be unique"
    else:
        raise AssertionError("duplicate authority public key was accepted")


def test_deterministic_execution_engine_uses_the_same_authority_boundary() -> None:
    policy = _policy()
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=_timestamp()),
        strict_operation_coverage=True,
        protocol_authority_policy=policy,
    )
    unsigned = _envelope(policy)

    rejected = engine.execute_block(
        block_height=1,
        block_hash=b"F" * 32,
        txs=[unsigned.consensus_bytes()],
    )
    assert rejected.operations_rejected == 1
    assert rejected.execution_events[0].error == "EPOCH_TRANSITION_AUTHORITY_SIGNATURE_REQUIRED"

    signed = _signed(policy, 0, 1)
    accepted = engine.execute_block(
        block_height=1,
        block_hash=b"G" * 32,
        txs=[signed.consensus_bytes()],
    )
    assert accepted.operations_executed == 1
