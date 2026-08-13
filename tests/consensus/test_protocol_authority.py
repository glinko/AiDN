from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.epoch_result_manifest import build_epoch_result_manifest
from aidn_hypervisor.consensus.epoch_result_manifest_commit import (
    build_unsigned_epoch_result_manifest_commit,
    combine_epoch_result_manifest_commit_signatures,
    sign_epoch_result_manifest_commit_signature,
)
from aidn_hypervisor.consensus.epoch_schedule import build_epoch_schedule
from aidn_hypervisor.consensus.epoch_schedule_rebase import build_epoch_schedule_rebase
from aidn_hypervisor.consensus.epoch_schedule_rebase_commit import (
    build_unsigned_epoch_schedule_rebase,
    combine_epoch_schedule_rebase_signatures,
    sign_epoch_schedule_rebase_signature,
)
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy
from aidn_hypervisor.consensus.service import ConsensusMode, ConsensusService, ConsensusServiceConfig
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


def _schedule():
    return build_epoch_schedule(
        genesis_start_time="2030-01-01T00:00:00Z",
        epoch_duration_seconds=60,
        parameter_version="params-v1",
        task_set_version="tasks-v1",
        protocol_version="0.1",
    )


def _schedule_envelope(
    policy: ProtocolAuthorityPolicy,
    schedule,
    *,
    signatures: list[str] | None = None,
    created_at: str | None = None,
) -> LedgerOperationEnvelope:
    return LedgerOperationEnvelope(
        operation_type="EPOCH_SCHEDULE_COMMIT",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="protocol",
        initiator_id="epoch-engine",
        fee_class="protocol_sponsored",
        created_at=created_at or _timestamp(),
        target_epoch="0",
        payload={
            "epoch_schedule": schedule.model_dump(mode="json"),
            "protocol_authority_policy_hash": policy.policy_hash,
        },
        signatures=signatures or [],
    )


def _manifest(policy: ProtocolAuthorityPolicy):
    return build_epoch_result_manifest(
        epoch_number=7,
        start_height=1,
        closing_height=60,
        start_time="2030-01-01T00:00:00Z",
        closing_time="2030-01-01T00:01:00Z",
        closing_block_hash="sha256:closing-block",
        closing_state_root="sha256:closing-state",
        source_app_hash="sha256:closing-app",
        protocol_version="0.1",
        parameter_version="params-v1",
        task_set_version="tasks-v1",
        epoch_schedule_version="aidn.epoch-schedule.v1",
        epoch_schedule_hash="sha256:schedule-v1",
        scheduled_end_time="2030-01-01T00:01:00Z",
        frozen_evidence_root="sha256:frozen-evidence",
        participant_snapshot_root="sha256:participants",
        service_snapshot_root="sha256:services",
        task_result_root="sha256:tasks",
        eligibility_root="sha256:eligibility",
        reputation_root="sha256:reputation",
        penalty_root="sha256:penalty",
        recycle_root="sha256:recycle",
        reward_authorization_root="sha256:reward-authorization",
        reward_result_root="sha256:reward-result",
        faucet_root="sha256:faucet",
        validator_set_update_root="sha256:validator-set",
        reward_calculation_root="sha256:reward-calculation",
        next_protocol_parameters_hash="sha256:params-v2",
        pool_budgets={"GENERAL_DEVELOPMENT": 0},
        pool_budget_references={"GENERAL_DEVELOPMENT": "epoch:7:GENERAL_DEVELOPMENT"},
        next_epoch_reference="epoch:8",
    )


def _manifest_envelope(
    policy: ProtocolAuthorityPolicy,
    *,
    signatures: list[str] | None = None,
) -> LedgerOperationEnvelope:
    envelope = build_unsigned_epoch_result_manifest_commit(
        policy=policy,
        manifest=_manifest(policy),
        created_at=_timestamp(),
        expires_at=_timestamp(hours=24),
    )
    return envelope.model_copy(update={"signatures": signatures or []})


def _rebase(policy: ProtocolAuthorityPolicy, schedule) -> object:
    return build_epoch_schedule_rebase(
        schedule_hash=schedule.schedule_hash,
        effective_epoch_zero_start_time="2030-01-01T00:10:00Z",
    )


def _rebase_envelope(
    policy: ProtocolAuthorityPolicy,
    schedule,
    *,
    signatures: list[str] | None = None,
    created_at: str | None = None,
) -> LedgerOperationEnvelope:
    envelope = build_unsigned_epoch_schedule_rebase(
        policy=policy,
        rebase=_rebase(policy, schedule),
        created_at=created_at or _timestamp(),
        expires_at=_timestamp(hours=24),
    )
    return envelope.model_copy(update={"signatures": signatures or []})


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


def _signed_schedule(
    policy: ProtocolAuthorityPolicy,
    schedule,
    *key_indexes: int,
    created_at: str | None = None,
) -> LedgerOperationEnvelope:
    unsigned = _schedule_envelope(policy, schedule, created_at=created_at)
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


def test_epoch_schedule_commit_requires_authority_quorum_and_is_projected() -> None:
    policy = _policy()
    schedule = _schedule()
    app, ledger = _app(policy)
    unsigned = _schedule_envelope(policy, schedule)

    check = app.check_transaction(unsigned.consensus_bytes())
    assert check.code == "rejected"
    assert check.log == "EPOCH_SCHEDULE_COMMIT_AUTHORITY_SIGNATURE_REQUIRED"

    signed = _signed_schedule(policy, schedule, 0, 1)
    result, results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"S" * 32,
        txs=[signed.consensus_bytes()],
        time="2029-12-31T23:59:00Z",
    )

    assert result.code == "ok"
    assert results[0].code == "ok"
    projection = ledger.epoch_schedule_projection()
    assert projection is not None
    assert projection["operation_id"] == signed.operation_id
    assert projection["epoch_schedule"]["schedule_hash"] == schedule.schedule_hash
    query = json.loads(app.query(path="epoch/schedule").value)
    assert query == projection


def test_late_initial_schedule_requires_one_authorized_rebase_before_epoch_activity() -> None:
    policy = _policy()
    schedule = _schedule()
    app, ledger = _app(policy)
    schedule_tx = _signed_schedule(policy, schedule, 0, 1)
    result, results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"S" * 32,
        txs=[schedule_tx.consensus_bytes()],
        time="2029-12-31T23:59:00Z",
    )
    assert result.code == "ok"
    assert results[0].code == "ok"

    unsigned = _rebase_envelope(policy, schedule)
    check = app.check_transaction(unsigned.consensus_bytes())
    assert check.code == "rejected"
    assert check.log == "EPOCH_SCHEDULE_REBASE_AUTHORITY_SIGNATURE_REQUIRED"

    first = sign_consensus_bytes(private_key=PRIVATE_KEYS[0], payload=unsigned.signing_bytes())
    second = sign_consensus_bytes(private_key=PRIVATE_KEYS[1], payload=unsigned.signing_bytes())
    signed = _rebase_envelope(policy, schedule, signatures=[first, second])
    result, results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"R" * 32,
        txs=[signed.consensus_bytes()],
        time="2030-01-01T00:11:00Z",
    )
    assert result.code == "ok"
    assert results[0].code == "ok"
    assert ledger.effective_epoch_zero_start_time() == "2030-01-01T00:10:00Z"
    assert app._active_epoch_context() == (0, "2030-01-01T00:10:00Z", None)

    duplicate_unsigned = _rebase_envelope(
        policy,
        schedule,
        created_at="2030-01-01T00:01:00Z",
    )
    duplicate_first = sign_consensus_bytes(private_key=PRIVATE_KEYS[0], payload=duplicate_unsigned.signing_bytes())
    duplicate_second = sign_consensus_bytes(private_key=PRIVATE_KEYS[1], payload=duplicate_unsigned.signing_bytes())
    duplicate = duplicate_unsigned.model_copy(update={"signatures": [duplicate_first, duplicate_second]})
    _, duplicate_results = app.finalize_block_with_results(
        block_height=3,
        block_hash=b"D" * 32,
        txs=[duplicate.consensus_bytes()],
        time="2030-01-01T00:12:00Z",
    )
    assert duplicate_results[0].code == "rejected"
    assert duplicate_results[0].log == "epoch schedule rebase is already committed"


def test_late_schedule_cannot_start_epoch_activity_without_authorized_rebase() -> None:
    policy = _policy()
    schedule = _schedule()
    app, _ = _app(policy)
    schedule_tx = _signed_schedule(policy, schedule, 0, 1)
    app.finalize_block(
        block_height=1,
        block_hash=b"L" * 32,
        txs=[schedule_tx.consensus_bytes()],
        time="2030-01-01T00:02:00Z",
    )
    manifest = _manifest_envelope(policy)
    first = sign_consensus_bytes(private_key=PRIVATE_KEYS[0], payload=manifest.signing_bytes())
    second = sign_consensus_bytes(private_key=PRIVATE_KEYS[1], payload=manifest.signing_bytes())
    signed = manifest.model_copy(update={"signatures": [first, second]})
    check = app.check_transaction(signed.consensus_bytes())
    assert check.code == "rejected"
    assert check.log == "epoch schedule activation is required before epoch activity"
    _, finalized = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"Z" * 32,
        txs=[signed.consensus_bytes()],
        time="2030-01-01T00:02:01Z",
    )
    assert finalized[0].code == "rejected"
    assert finalized[0].log == "epoch schedule activation is required before epoch activity"


def test_rebased_epoch_zero_manifest_requires_exact_rebase_evidence() -> None:
    policy = _policy()
    schedule = _schedule()
    app, _ = _app(policy)
    schedule_tx = _signed_schedule(policy, schedule, 0, 1)
    app.finalize_block(
        block_height=1,
        block_hash=b"B" * 32,
        txs=[schedule_tx.consensus_bytes()],
        time="2029-12-31T23:59:00Z",
    )
    unsigned_rebase = _rebase_envelope(policy, schedule)
    rebase = unsigned_rebase.model_copy(
        update={
            "signatures": [
                sign_consensus_bytes(private_key=PRIVATE_KEYS[0], payload=unsigned_rebase.signing_bytes()),
                sign_consensus_bytes(private_key=PRIVATE_KEYS[1], payload=unsigned_rebase.signing_bytes()),
            ]
        }
    )
    app.finalize_block(
        block_height=2,
        block_hash=b"C" * 32,
        txs=[rebase.consensus_bytes()],
        time="2030-01-01T00:11:00Z",
    )
    manifest = build_epoch_result_manifest(
        epoch_number=0,
        start_height=2,
        closing_height=3,
        start_time="2030-01-01T00:10:00Z",
        closing_time="2030-01-01T00:11:00Z",
        closing_block_hash="sha256:closing-block",
        closing_state_root="sha256:closing-state",
        source_app_hash="sha256:closing-app",
        protocol_version="0.1",
        parameter_version="params-v1",
        task_set_version="tasks-v1",
        epoch_schedule_version=schedule.schema_version,
        epoch_schedule_hash=schedule.schedule_hash,
        scheduled_end_time="2030-01-01T00:11:00Z",
        frozen_evidence_root="sha256:frozen-evidence",
        participant_snapshot_root="sha256:participants",
        service_snapshot_root="sha256:services",
        task_result_root="sha256:tasks",
        eligibility_root="sha256:eligibility",
        reputation_root="sha256:reputation",
        penalty_root="sha256:penalty",
        recycle_root="sha256:recycle",
        reward_authorization_root="sha256:reward-authorization",
        reward_result_root="sha256:reward-result",
        faucet_root="sha256:faucet",
        validator_set_update_root="sha256:validator-set",
        reward_calculation_root="sha256:reward-calculation",
        next_protocol_parameters_hash="sha256:params-v2",
        pool_budgets={"GENERAL_DEVELOPMENT": 0},
        pool_budget_references={"GENERAL_DEVELOPMENT": "epoch:0:GENERAL_DEVELOPMENT"},
        next_epoch_reference="epoch:1",
    )
    unsigned_manifest = build_unsigned_epoch_result_manifest_commit(
        policy=policy,
        manifest=manifest,
        created_at=_timestamp(),
    )
    signed_manifest = unsigned_manifest.model_copy(
        update={
            "signatures": [
                sign_consensus_bytes(private_key=PRIVATE_KEYS[0], payload=unsigned_manifest.signing_bytes()),
                sign_consensus_bytes(private_key=PRIVATE_KEYS[1], payload=unsigned_manifest.signing_bytes()),
            ]
        }
    )
    check = app.check_transaction(signed_manifest.consensus_bytes())
    assert check.code == "rejected"
    assert check.log == "epoch result manifest rebase evidence references are incomplete"


def test_offline_rebase_combiner_requires_distinct_authorities() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    policy = _policy()
    unsigned = _rebase_envelope(policy, _schedule())
    signature = sign_epoch_schedule_rebase_signature(
        unsigned,
        policy=policy,
        authority_id="authority-1",
        private_key=Ed25519PrivateKey.from_private_bytes(bytes.fromhex("11" * 32)),
    )
    with pytest.raises(ValueError, match="EPOCH_SCHEDULE_REBASE_AUTHORITY_SIGNATURE_REQUIRED"):
        combine_epoch_schedule_rebase_signatures(
            unsigned,
            policy=policy,
            signatures={"authority-1": signature},
        )


def test_epoch_result_manifest_requires_authority_quorum_before_it_is_immutable() -> None:
    policy = _policy()
    app, ledger = _app(policy)
    unsigned = _manifest_envelope(policy)

    check = app.check_transaction(unsigned.consensus_bytes())
    assert check.code == "rejected"
    assert check.log == "EPOCH_RESULT_MANIFEST_COMMIT_AUTHORITY_SIGNATURE_REQUIRED"

    # The fixture signer follows the exact same detached signing bytes as the CLI.
    first_signature = sign_consensus_bytes(private_key=PRIVATE_KEYS[0], payload=unsigned.signing_bytes())
    second_signature = sign_consensus_bytes(private_key=PRIVATE_KEYS[1], payload=unsigned.signing_bytes())
    signed = _manifest_envelope(policy, signatures=[first_signature, second_signature])
    result, tx_results = app.finalize_block_with_results(
        block_height=60,
        block_hash=b"M" * 32,
        txs=[signed.consensus_bytes()],
        time="2030-01-01T00:01:00Z",
    )

    assert result.code == "ok"
    assert tx_results[0].code == "ok"
    assert ledger.epoch_result_manifest_commitment(7) is not None


def test_epoch_result_manifest_offline_combiner_requires_distinct_authorities() -> None:
    policy = _policy()
    unsigned = _manifest_envelope(policy)
    # Constructing key objects here keeps the assertion on the public offline
    # API rather than duplicating the signature combiner implementation.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    signature = sign_epoch_result_manifest_commit_signature(
        unsigned,
        policy=policy,
        authority_id="authority-1",
        private_key=Ed25519PrivateKey.from_private_bytes(bytes.fromhex("11" * 32)),
    )
    try:
        combine_epoch_result_manifest_commit_signatures(
            unsigned,
            policy=policy,
            signatures={"authority-1": signature},
        )
    except ValueError as error:
        assert str(error) == "EPOCH_RESULT_MANIFEST_COMMIT_AUTHORITY_SIGNATURE_REQUIRED"
    else:
        raise AssertionError("single authority manifest commitment was accepted")


def test_epoch_schedule_commit_is_immutable_and_restores_from_canonical_ledger() -> None:
    policy = _policy()
    schedule = _schedule()
    app, ledger = _app(policy)
    signed = _signed_schedule(policy, schedule, 0, 1)
    app.finalize_block(
        block_height=1,
        block_hash=b"T" * 32,
        txs=[signed.consensus_bytes()],
        time="2030-01-01T00:00:01Z",
    )

    replacement = _signed_schedule(
        policy,
        schedule,
        0,
        1,
        created_at="2030-01-01T00:00:02Z",
    )
    _, duplicate_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"U" * 32,
        txs=[replacement.consensus_bytes()],
        time="2030-01-01T00:00:02Z",
    )
    assert duplicate_results[0].code == "rejected"
    assert duplicate_results[0].log == "epoch schedule is already committed"
    assert len(ledger.snapshot_operations()) == 1

    snapshot = app.prepare_snapshot()
    snapshot.pop("epoch_schedule")
    restored = AIDNABCIApplication(ledger_service=LedgerOperationService())
    restore_result = restored.apply_snapshot(snapshot)
    assert restore_result.code == "ok"
    restored_projection = restored.ledger.epoch_schedule_projection()
    assert restored_projection == ledger.epoch_schedule_projection()


def test_deterministic_execution_engine_accepts_signed_epoch_schedule_commit() -> None:
    policy = _policy()
    schedule = _schedule()
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=_timestamp()),
        strict_operation_coverage=True,
        protocol_authority_policy=policy,
    )
    signed = _signed_schedule(policy, schedule, 0, 1)

    result = engine.execute_block(
        block_height=1,
        block_hash=b"V" * 32,
        txs=[signed.consensus_bytes()],
    )

    assert result.operations_executed == 1
    assert result.operations_rejected == 0
    projection = ledger.epoch_schedule_projection()
    assert projection is not None
    assert projection["epoch_schedule"]["schedule_hash"] == schedule.schedule_hash


def test_epoch_schedule_commit_cannot_share_block_with_epoch_transition() -> None:
    policy = _policy()
    schedule = _schedule()
    signed_schedule = _signed_schedule(policy, schedule, 0, 1)
    signed_transition = _signed(policy, 0, 1)
    expected_error = "epoch transition cannot depend on same-block epoch schedule commit"

    for ordered_txs in (
        (signed_transition, signed_schedule),
        (signed_schedule, signed_transition),
    ):
        app, ledger = _app(policy)
        raw_txs = [tx.consensus_bytes() for tx in ordered_txs]
        proposal = app.process_proposal(raw_txs)
        assert proposal.code == "rejected"
        assert proposal.log == expected_error
        prepared = app.prepare_proposal(raw_txs, maximum_bytes=1_000_000)
        assert [app._parse_envelope(tx).operation_type for tx in prepared] == ["EPOCH_SCHEDULE_COMMIT"]
        result, results = app.finalize_block_with_results(
            block_height=1,
            block_hash=b"W" * 32,
            txs=raw_txs,
        )

        assert result.code == "ok"
        transition_index = next(
            index for index, tx in enumerate(ordered_txs) if tx.operation_type == "EPOCH_TRANSITION"
        )
        schedule_index = next(
            index for index, tx in enumerate(ordered_txs) if tx.operation_type == "EPOCH_SCHEDULE_COMMIT"
        )
        assert results[transition_index].code == "rejected"
        assert results[transition_index].log == expected_error
        assert results[schedule_index].code == "ok"
        assert len(ledger.snapshot_operations()) == 1

    for ordered_txs in (
        (signed_transition, signed_schedule),
        (signed_schedule, signed_transition),
    ):
        ledger = LedgerOperationService()
        engine = ExecutionEngine(
            ledger_service=ledger,
            admission_validator=AdmissionValidator(current_time=_timestamp()),
            strict_operation_coverage=True,
            protocol_authority_policy=policy,
        )
        result = engine.execute_block(
            block_height=1,
            block_hash=b"X" * 32,
            txs=[tx.consensus_bytes() for tx in ordered_txs],
        )

        assert result.operations_executed == 1
        assert result.operations_rejected == 1
        transition_event = next(
            event for event in result.execution_events if event.operation_type == "EPOCH_TRANSITION"
        )
        assert transition_event.error == expected_error
        assert ledger.epoch_schedule_projection() is not None


def test_epoch_transition_schedule_reference_requires_finalized_commitment() -> None:
    policy = _policy()
    app, ledger = _app(policy)
    payload = {
        **_payload(policy),
        "epoch_schedule_commit_operation_id": "not-finalized",
    }
    transition = _signed(policy, 0, 1, payload=payload)

    check = app.check_transaction(transition.consensus_bytes())
    assert check.code == "rejected"
    assert check.log == "epoch transition epoch schedule is not finalized"
    assert ledger.snapshot_operations() == []


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
    assert [item["operation_type"] for item in ledger.snapshot_operations()] == ["EPOCH_TRANSITION"]


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


def test_abci_query_exposes_only_sanitized_authority_policy_state() -> None:
    policy = _policy()
    app, _ = _app(policy)

    response = app.query(path="protocol/authority-policy")
    value = json.loads(response.value)

    assert value == {
        "authority_count": 3,
        "configured": True,
        "epoch_transition_mode": "THRESHOLD_AUTHORIZED",
        "policy_hash": policy.policy_hash,
        "threshold": 2,
        "version": "aidn.protocol-authority.v1",
    }
    assert "authorities" not in value
    assert "public_key" not in response.value.decode("utf-8")


def test_consensus_status_reports_fail_closed_authority_state() -> None:
    service = ConsensusService(
        ConsensusServiceConfig(
            mode=ConsensusMode.VALIDATOR,
            protocol_authority_policy=ProtocolAuthorityPolicy.empty(),
        )
    )

    assert service.status()["protocol_authority"] == {
        "configured": False,
        "policy_hash": None,
        "threshold": None,
        "authority_count": 0,
        "epoch_transition_mode": "FAIL_CLOSED",
    }
