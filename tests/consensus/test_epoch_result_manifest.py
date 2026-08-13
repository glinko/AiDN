from __future__ import annotations

import hashlib
import json

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.epoch_result_manifest import (
    EPOCH_RESULT_MANIFEST_LEGACY_VERSION,
    build_epoch_result_manifest,
)
from aidn_hypervisor.consensus.epoch_schedule import build_epoch_schedule
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService


def _manifest(*, epoch_number: int = 0, closing_height: int = 60):
    return build_epoch_result_manifest(
        manifest_state="FINALIZED",
        epoch_number=epoch_number,
        start_height=1,
        closing_height=closing_height,
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
        penalty_root="sha256:penalties",
        recycle_root="sha256:recycle",
        reward_authorization_root="sha256:reward-authorization",
        reward_result_root="sha256:reward-result",
        faucet_root="sha256:faucet",
        validator_set_update_root="sha256:validator-set",
        reward_calculation_root="sha256:reward-calculation",
        next_protocol_parameters_hash="sha256:params-v2",
        pool_budgets={"GENERAL_DEVELOPMENT": 250_000},
        pool_budget_references={"GENERAL_DEVELOPMENT": "epoch:0:GENERAL_DEVELOPMENT"},
        next_epoch_reference="epoch:1",
    )


def _envelope(manifest: dict) -> bytes:
    envelope = LedgerOperationEnvelope(
        operation_type="EPOCH_RESULT_MANIFEST_COMMIT",
        origin_type="protocol",
        initiator_id="epoch-engine",
        fee_class="protocol_sponsored",
        target_epoch="0",
        created_at="2030-01-01T00:01:00Z",
        payload={"manifest": manifest},
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def test_legacy_manifest_hash_and_replay_shape_remain_compatible() -> None:
    manifest = build_epoch_result_manifest(
        manifest_version=EPOCH_RESULT_MANIFEST_LEGACY_VERSION,
        manifest_state="FINALIZED",
        epoch_number=0,
        start_height=1,
        closing_height=60,
        start_time="2030-01-01T00:00:00Z",
        closing_time="2030-01-01T00:01:00Z",
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
        penalty_root="sha256:penalties",
        recycle_root="sha256:recycle",
        reward_authorization_root="sha256:reward-authorization",
        reward_result_root="sha256:reward-result",
        faucet_root="sha256:faucet",
        validator_set_update_root="sha256:validator-set",
        reward_calculation_root="sha256:reward-calculation",
        next_protocol_parameters_hash="sha256:params-v2",
        pool_budgets={"GENERAL_DEVELOPMENT": 250_000},
        pool_budget_references={"GENERAL_DEVELOPMENT": "epoch:0:GENERAL_DEVELOPMENT"},
        next_epoch_reference="epoch:1",
    )

    assert manifest.manifest_version == EPOCH_RESULT_MANIFEST_LEGACY_VERSION
    assert manifest.closing_block_hash is None
    assert manifest.closing_state_root is None
    assert manifest.source_app_hash is None
    assert "closing_block_hash" not in manifest.unsigned_payload()
    assert "closing_state_root" not in manifest.unsigned_payload()
    assert "source_app_hash" not in manifest.unsigned_payload()
    encoded = json.dumps(
        manifest.unsigned_payload(),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    expected_hash = "sha256:" + hashlib.sha256(
        (EPOCH_RESULT_MANIFEST_LEGACY_VERSION + ":" + encoded).encode("utf-8")
    ).hexdigest()
    assert manifest.manifest_hash == expected_hash


def test_manifest_is_committed_without_wallet_or_economic_effect() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(ledger_service=ledger)
    manifest = _manifest()

    result, tx_results = app.finalize_block_with_results(
        block_height=60,
        block_hash=b"m" * 32,
        txs=[_envelope(manifest.model_dump(mode="json"))],
        time="2030-01-01T00:01:00Z",
    )

    assert result.code == "ok"
    assert tx_results[0].code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:epoch-engine") == 0
    committed = ledger.epoch_result_manifest_commitment(0)
    assert committed is not None
    assert committed["payload"]["manifest"]["manifest_hash"] == manifest.manifest_hash


def test_manifest_for_an_epoch_is_immutable() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(ledger_service=ledger)
    first = _envelope(_manifest().model_dump(mode="json"))
    replacement = build_epoch_result_manifest(
        **{
            **_manifest().unsigned_payload(),
            "task_result_root": "sha256:replacement-tasks",
        }
    )
    second = _envelope(replacement.model_dump(mode="json"))

    first_result = app.finalize_block(block_height=1, block_hash=b"a" * 32, txs=[first])
    second_result, tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"b" * 32,
        txs=[second],
    )

    assert first_result.code == "ok"
    assert second_result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "already committed" in tx_results[0].log
    assert len(ledger.snapshot_operations()) == 1


def test_manifest_populates_ready_epoch_transition_preflight() -> None:
    schedule = build_epoch_schedule(
        genesis_start_time="2030-01-01T00:00:00Z",
        epoch_duration_seconds=60,
        parameter_version="params-v1",
        task_set_version="tasks-v1",
        protocol_version="0.1",
    )
    manifest = build_epoch_result_manifest(
        **{
            **_manifest().model_dump(mode="json"),
            "epoch_schedule_hash": schedule.schedule_hash,
        }
    )
    app = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        epoch_schedule=schedule,
    )
    result = app.finalize_block(
        block_height=60,
        block_hash=b"c" * 32,
        txs=[_envelope(manifest.model_dump(mode="json"))],
        time="2030-01-01T00:01:00Z",
    )

    assert result.code == "ok"
    report = app.epoch_transition_input_report()
    assert report["status"] == "READY"
    assert report["epoch_task_result_root"] == manifest.task_result_root
    assert report["eligibility_snapshot_root"] == manifest.eligibility_root
    assert report["reward_calculation_root"] == manifest.reward_calculation_root
    assert report["epoch_result_manifest_hash"] == manifest.manifest_hash
    assert report["epoch_result_manifest_operation_id"]
    assert report["closing_height"] == manifest.closing_height
    assert report["closing_block_hash"] == manifest.closing_block_hash
    assert report["source_app_hash"] == manifest.source_app_hash
    payload = json.loads(app.query(path="epoch/transition-inputs").value.decode("utf-8"))
    assert payload["status"] == "READY"
    projection = json.loads(
        app.query(path="epoch/result-manifest/0").value.decode("utf-8")
    )
    assert projection["operation_id"] == report["epoch_result_manifest_operation_id"]
    assert projection["manifest_hash"] == manifest.manifest_hash
    assert projection["closing_height"] == manifest.closing_height
    assert projection["closing_state_root"] == manifest.closing_state_root
    assert projection["source_app_hash"] == manifest.source_app_hash
    assert projection["epoch_schedule_hash"] == schedule.schedule_hash


def test_manifest_keeps_historical_closing_state_after_later_blocks() -> None:
    schedule = build_epoch_schedule(
        genesis_start_time="2030-01-01T00:00:00Z",
        epoch_duration_seconds=60,
        parameter_version="params-v1",
        task_set_version="tasks-v1",
        protocol_version="0.1",
    )
    manifest = build_epoch_result_manifest(
        **{
            **_manifest().model_dump(mode="json"),
            "epoch_schedule_hash": schedule.schedule_hash,
        }
    )
    app = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        epoch_schedule=schedule,
    )
    app.finalize_block(
        block_height=60,
        block_hash=b"c" * 32,
        txs=[_envelope(manifest.model_dump(mode="json"))],
        time="2030-01-01T00:01:00Z",
    )
    app.finalize_block(
        block_height=61,
        block_hash=b"d" * 32,
        txs=[],
        time="2030-01-01T00:01:02Z",
    )

    report = app.epoch_transition_input_report()
    assert report["status"] == "READY"
    assert report["closing_height"] == manifest.closing_height
    assert report["closing_block_hash"] == manifest.closing_block_hash
    assert report["canonical_block_time"] == manifest.closing_time


def test_transition_cannot_consume_manifest_from_the_same_block() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(ledger_service=ledger)
    manifest = _manifest()
    manifest_tx = _envelope(manifest.model_dump(mode="json"))
    manifest_id = LedgerOperationEnvelope.model_validate(json.loads(manifest_tx)).operation_id
    transition_tx = json.dumps(
        LedgerOperationEnvelope(
            operation_type="EPOCH_TRANSITION",
            origin_type="protocol",
            initiator_id="epoch-engine",
            fee_class="protocol_sponsored",
            target_epoch="0",
            created_at="2030-01-01T00:01:00Z",
            payload={
                "closing_epoch": 0,
                "opening_epoch": 1,
                "closing_state_root": "sha256:closing-state",
                "epoch_task_result_root": manifest.task_result_root,
                "eligibility_snapshot_root": manifest.eligibility_root,
                "reward_calculation_root": manifest.reward_calculation_root,
                "next_protocol_parameters_hash": manifest.next_protocol_parameters_hash,
                "pool_budgets": manifest.pool_budgets,
                "pool_budget_references": manifest.pool_budget_references,
                "epoch_schedule_version": manifest.epoch_schedule_version,
                "epoch_schedule_hash": manifest.epoch_schedule_hash,
                "canonical_block_time": manifest.closing_time,
                "scheduled_end_time": manifest.scheduled_end_time,
                "epoch_result_manifest_hash": manifest.manifest_hash,
                "epoch_result_manifest_operation_id": manifest_id,
            },
        ).model_dump(mode="json")
    ).encode("utf-8")

    result, tx_results = app.finalize_block_with_results(
        block_height=60,
        block_hash=b"d" * 32,
        txs=[manifest_tx, transition_tx],
        time="2030-01-01T00:01:00Z",
    )

    assert result.code == "ok"
    assert tx_results[0].code == "ok"
    assert tx_results[1].code == "rejected"
    assert "not finalized" in tx_results[1].log
    assert len(ledger.snapshot_operations()) == 1

    engine_ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=engine_ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:02:00Z"),
    )
    execution = engine.execute_block(
        block_height=60,
        block_hash=b"e" * 32,
        txs=[manifest_tx, transition_tx],
    )

    assert execution.operations_executed == 1
    assert execution.operations_rejected == 1
    assert "not finalized" in (execution.execution_events[1].error or "")
    assert len(engine_ledger.snapshot_operations()) == 1
