from __future__ import annotations

import base64
import json
from typing import Any

from aidn_hypervisor.consensus.epoch_transition_inputs import (
    build_epoch_transition_input_report,
)
from aidn_hypervisor.consensus.epoch_transition_quorum import (
    EpochTransitionQuorumReport,
    collect_epoch_transition_quorum,
)

RPC_URLS = [
    "http://127.0.0.1:26657",
    "http://127.0.0.1:26658",
    "http://127.0.0.1:26659",
]
MANIFEST_OPERATION_ID = "manifest-operation-1"
MANIFEST_HASH = "sha256:manifest"
SCHEDULE_OPERATION_ID = "schedule-operation-1"


def _report(
    *,
    reward_root: str = "sha256:rewards",
    schedule_reference: bool = False,
) -> dict[str, Any]:
    return build_epoch_transition_input_report(
        closing_epoch=0,
        opening_epoch=1,
        closing_height=100,
        closing_block_hash="sha256:block",
        closing_state_root="sha256:state",
        epoch_task_result_root="sha256:tasks",
        eligibility_snapshot_root="sha256:eligibility",
        reward_calculation_root=reward_root,
        next_protocol_parameters_hash="sha256:params",
        pool_budgets={"GENERAL_DEVELOPMENT": 250_000},
        pool_budget_references={"GENERAL_DEVELOPMENT": "epoch:0:GENERAL_DEVELOPMENT"},
        source_app_hash="sha256:app",
        epoch_schedule_version="aidn.epoch-schedule.v1",
        epoch_schedule_hash="sha256:schedule",
        canonical_block_time="2030-01-01T00:01:00Z",
        scheduled_end_time="2030-01-01T00:01:00Z",
        epoch_boundary_reached=True,
        epoch_result_manifest_hash=MANIFEST_HASH,
        epoch_result_manifest_operation_id=MANIFEST_OPERATION_ID,
        epoch_schedule_commit_operation_id=(SCHEDULE_OPERATION_ID if schedule_reference else None),
        epoch_schedule_commit_sequence_id=(3 if schedule_reference else None),
        epoch_schedule_commit_record_digest=("sha256:schedule-record" if schedule_reference else None),
    ).model_dump(mode="json")


def _encoded(value: dict[str, Any]) -> str:
    return base64.b64encode(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def _fetcher(
    reports: dict[str, dict[str, Any]],
    *,
    missing_finality: set[str] | None = None,
    conflicting_reference: set[str] | None = None,
    conflicting_projection: set[str] | None = None,
    missing_schedule_finality: set[str] | None = None,
    conflicting_schedule_reference: set[str] | None = None,
    conflicting_schedule_projection: set[str] | None = None,
):
    missing_finality = missing_finality or set()
    conflicting_reference = conflicting_reference or set()
    conflicting_projection = conflicting_projection or set()
    missing_schedule_finality = missing_schedule_finality or set()
    conflicting_schedule_reference = conflicting_schedule_reference or set()
    conflicting_schedule_projection = conflicting_schedule_projection or set()

    def fetcher(url: str, path: str, params: dict[str, str]) -> dict[str, Any]:
        if path == "/status":
            index = RPC_URLS.index(url)
            return {
                "result": {
                    "node_info": {"id": f"validator-{index}", "network": "chain-1"},
                    "sync_info": {"latest_block_height": "120", "catching_up": False},
                }
            }
        query_path = json.loads(params["path"])
        if query_path == "epoch/transition-inputs":
            return {
                "result": {
                    "response": {
                        "code": 0,
                        "height": "120",
                        "value": _encoded(reports[url]),
                    }
                }
            }
        if query_path == f"operation/finalized/{MANIFEST_OPERATION_ID}":
            if url in missing_finality:
                return {
                    "result": {
                        "response": {"code": 0, "height": "120", "value": ""}
                    }
                }
            operation_id = (
                "different-operation" if url in conflicting_reference else MANIFEST_OPERATION_ID
            )
            return {
                "result": {
                    "response": {
                        "code": 0,
                        "height": "120",
                        "value": _encoded(
                            {
                                "operation_id": operation_id,
                                "operation_type": "EPOCH_RESULT_MANIFEST_COMMIT",
                                "sequence_id": 7,
                                "record_digest": "sha256:record",
                            }
                        ),
                    }
                }
            }
        if query_path == f"operation/finalized/{SCHEDULE_OPERATION_ID}":
            if url in missing_schedule_finality:
                return {
                    "result": {
                        "response": {"code": 0, "height": "120", "value": ""}
                    }
                }
            operation_id = (
                "different-schedule-operation"
                if url in conflicting_schedule_reference
                else SCHEDULE_OPERATION_ID
            )
            return {
                "result": {
                    "response": {
                        "code": 0,
                        "height": "120",
                        "value": _encoded(
                            {
                                "operation_id": operation_id,
                                "operation_type": "EPOCH_SCHEDULE_COMMIT",
                                "sequence_id": 3,
                                "record_digest": "sha256:schedule-record",
                            }
                        ),
                    }
                }
            }
        if query_path == "epoch/result-manifest/0":
            if url in missing_finality:
                return {
                    "result": {
                        "response": {"code": 0, "height": "120", "value": ""}
                    }
                }
            return {
                "result": {
                    "response": {
                        "code": 0,
                        "height": "120",
                        "value": _encoded(
                            {
                                "operation_id": MANIFEST_OPERATION_ID,
                                "operation_type": "EPOCH_RESULT_MANIFEST_COMMIT",
                                "sequence_id": 7,
                                "record_digest": "sha256:record",
                                "manifest_hash": MANIFEST_HASH,
                                "epoch_number": 0,
                                "closing_height": 100,
                                "closing_time": "2030-01-01T00:01:00Z",
                                "closing_block_hash": "sha256:block",
                                "closing_state_root": (
                                    "sha256:other-state"
                                    if url in conflicting_projection
                                    else "sha256:state"
                                ),
                                "source_app_hash": "sha256:app",
                                "epoch_schedule_version": "aidn.epoch-schedule.v1",
                                "epoch_schedule_hash": "sha256:schedule",
                                "scheduled_end_time": "2030-01-01T00:01:00Z",
                            }
                        ),
                    }
                }
            }
        if query_path == "epoch/schedule":
            return {
                "result": {
                    "response": {
                        "code": 0,
                        "height": "120",
                        "value": _encoded(
                            {
                                "operation_id": (
                                    "different-schedule-operation"
                                    if url in conflicting_schedule_projection
                                    else SCHEDULE_OPERATION_ID
                                ),
                                "operation_type": "EPOCH_SCHEDULE_COMMIT",
                                "sequence_id": 3,
                                "record_digest": "sha256:schedule-record",
                                "epoch_schedule": {
                                    "schema_version": "aidn.epoch-schedule.v1",
                                    "schedule_hash": "sha256:schedule",
                                },
                            }
                        ),
                    }
                }
            }
        raise AssertionError(f"unexpected query path: {query_path}")

    return fetcher


def test_quorum_requires_finalized_manifest_reference() -> None:
    reports = {url: _report() for url in RPC_URLS}
    result = collect_epoch_transition_quorum(
        rpc_urls=RPC_URLS,
        quorum=2,
        fetcher=_fetcher(reports, missing_finality={RPC_URLS[2]}),
    )

    assert result["status"] == "READY"
    assert result["agreement_count"] == 2
    assert result["chain_agreement_count"] == 3
    assert result["manifest_finality_count"] == 2
    assert result["manifest_operation_id"] == MANIFEST_OPERATION_ID
    assert EpochTransitionQuorumReport.model_validate(result).verify_integrity()


def test_quorum_blocks_when_manifest_finality_is_below_threshold() -> None:
    reports = {url: _report() for url in RPC_URLS}
    result = collect_epoch_transition_quorum(
        rpc_urls=RPC_URLS,
        quorum=2,
        fetcher=_fetcher(reports, missing_finality={RPC_URLS[1], RPC_URLS[2]}),
    )

    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "EPOCH_RESULT_MANIFEST_FINALITY_QUORUM_UNAVAILABLE"
    assert result["manifest_finality_count"] == 1


def test_quorum_does_not_merge_conflicting_ready_reports() -> None:
    reports = {
        RPC_URLS[0]: _report(),
        RPC_URLS[1]: _report(),
        RPC_URLS[2]: _report(reward_root="sha256:other-rewards"),
    }
    result = collect_epoch_transition_quorum(
        rpc_urls=RPC_URLS,
        quorum=3,
        fetcher=_fetcher(reports, conflicting_reference={RPC_URLS[2]}),
    )

    assert result["status"] == "BLOCKED"
    assert result["agreement_count"] == 2
    assert result["manifest_finality_count"] == 2
    assert result["reason_code"] == "EPOCH_RESULT_MANIFEST_FINALITY_QUORUM_UNAVAILABLE"


def test_quorum_rejects_conflicting_manifest_projection_fields() -> None:
    reports = {url: _report() for url in RPC_URLS}
    result = collect_epoch_transition_quorum(
        rpc_urls=RPC_URLS,
        quorum=3,
        fetcher=_fetcher(reports, conflicting_projection={RPC_URLS[2]}),
    )

    assert result["status"] == "BLOCKED"
    assert result["agreement_count"] == 2
    assert result["manifest_finality_count"] == 2
    assert result["reason_code"] == "EPOCH_RESULT_MANIFEST_FINALITY_QUORUM_UNAVAILABLE"


def test_quorum_requires_finalized_schedule_reference_when_report_binds_one() -> None:
    reports = {url: _report(schedule_reference=True) for url in RPC_URLS}
    result = collect_epoch_transition_quorum(
        rpc_urls=RPC_URLS,
        quorum=2,
        fetcher=_fetcher(reports, missing_schedule_finality={RPC_URLS[2]}),
    )

    assert result["status"] == "READY"
    assert result["schedule_finality_count"] == 2
    assert result["schedule_operation_id"] == SCHEDULE_OPERATION_ID
    assert result["schedule_sequence_id"] == 3
    assert result["schedule_record_digest"] == "sha256:schedule-record"
    assert EpochTransitionQuorumReport.model_validate(result).verify_integrity()


def test_quorum_blocks_when_schedule_finality_is_below_threshold() -> None:
    reports = {url: _report(schedule_reference=True) for url in RPC_URLS}
    result = collect_epoch_transition_quorum(
        rpc_urls=RPC_URLS,
        quorum=2,
        fetcher=_fetcher(
            reports,
            missing_schedule_finality={RPC_URLS[1], RPC_URLS[2]},
        ),
    )

    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "EPOCH_SCHEDULE_FINALITY_QUORUM_UNAVAILABLE"
    assert result["schedule_operation_id"] == SCHEDULE_OPERATION_ID
    assert EpochTransitionQuorumReport.model_validate(result).verify_integrity()


def test_quorum_rejects_conflicting_schedule_evidence() -> None:
    reports = {url: _report(schedule_reference=True) for url in RPC_URLS}
    result = collect_epoch_transition_quorum(
        rpc_urls=RPC_URLS,
        quorum=3,
        fetcher=_fetcher(
            reports,
            conflicting_schedule_reference={RPC_URLS[2]},
        ),
    )

    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "EPOCH_SCHEDULE_FINALITY_QUORUM_UNAVAILABLE"
    assert result["schedule_finality_count"] == 2
