"""Read-only quorum evidence for an epoch transition preflight."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections import Counter
from collections.abc import Callable
from typing import Any, Literal
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aidn_hypervisor.consensus.epoch_transition_inputs import (
    EpochTransitionInputReport,
)

EPOCH_TRANSITION_QUORUM_VERSION = "aidn.epoch-transition-quorum.v1"
EPOCH_RESULT_MANIFEST_OPERATION = "EPOCH_RESULT_MANIFEST_COMMIT"
EPOCH_SCHEDULE_COMMIT_OPERATION = "EPOCH_SCHEDULE_COMMIT"

Fetcher = Callable[[str, str, dict[str, str]], dict[str, Any]]


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(
        (EPOCH_TRANSITION_QUORUM_VERSION + ":").encode("utf-8") + encoded
    ).hexdigest()


class EpochTransitionQuorumReport(BaseModel, frozen=True):
    """Hash-bound multi-validator evidence for a transition gate."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = EPOCH_TRANSITION_QUORUM_VERSION
    status: Literal["READY", "BLOCKED"]
    chain_id: str | None = None
    required_quorum: int = Field(ge=2)
    agreement_count: int = Field(ge=0)
    chain_agreement_count: int = Field(ge=0)
    manifest_finality_count: int = Field(ge=0)
    report: EpochTransitionInputReport | None = None
    manifest_hash: str | None = None
    manifest_operation_id: str | None = None
    manifest_sequence_id: int | None = Field(default=None, ge=1)
    manifest_record_digest: str | None = None
    schedule_finality_count: int = Field(default=0, ge=0)
    schedule_operation_id: str | None = None
    schedule_sequence_id: int | None = Field(default=None, ge=1)
    schedule_record_digest: str | None = None
    observations_hash: str
    observations: list[dict[str, Any]] = Field(default_factory=list)
    reason_code: str | None = None
    quorum_hash: str

    @model_validator(mode="after")
    def validate_report(self) -> EpochTransitionQuorumReport:
        if self.schema_version != EPOCH_TRANSITION_QUORUM_VERSION:
            raise ValueError("EPOCH_TRANSITION_QUORUM_VERSION_INVALID")
        if self.observations_hash != _canonical_hash(self.observations):
            raise ValueError("EPOCH_TRANSITION_QUORUM_OBSERVATIONS_HASH_INVALID")
        if self.report is not None:
            if self.report.status == "READY" and self.status != "READY":
                if self.reason_code not in {
                    "EPOCH_RESULT_MANIFEST_FINALITY_QUORUM_UNAVAILABLE",
                    "EPOCH_SCHEDULE_FINALITY_QUORUM_UNAVAILABLE",
                }:
                    raise ValueError("EPOCH_TRANSITION_QUORUM_READY_REPORT_BLOCKED")
            if self.report.epoch_result_manifest_hash != self.manifest_hash:
                raise ValueError("EPOCH_TRANSITION_QUORUM_MANIFEST_HASH_MISMATCH")
            if self.report.epoch_result_manifest_operation_id != self.manifest_operation_id:
                raise ValueError("EPOCH_TRANSITION_QUORUM_MANIFEST_OPERATION_MISMATCH")
            if self.report.epoch_schedule_commit_operation_id != self.schedule_operation_id:
                raise ValueError("EPOCH_TRANSITION_QUORUM_SCHEDULE_OPERATION_MISMATCH")
            if (
                self.schedule_sequence_id is not None
                and self.report.epoch_schedule_commit_sequence_id != self.schedule_sequence_id
            ):
                raise ValueError("EPOCH_TRANSITION_QUORUM_SCHEDULE_SEQUENCE_MISMATCH")
            if (
                self.schedule_record_digest is not None
                and self.report.epoch_schedule_commit_record_digest != self.schedule_record_digest
            ):
                raise ValueError("EPOCH_TRANSITION_QUORUM_SCHEDULE_DIGEST_MISMATCH")
        if self.status == "READY":
            if self.chain_id is None or self.report is None or self.report.status != "READY":
                raise ValueError("EPOCH_TRANSITION_QUORUM_READY_REPORT_MISSING")
            if self.agreement_count < self.required_quorum:
                raise ValueError("EPOCH_TRANSITION_QUORUM_INSUFFICIENT_AGREEMENT")
            if self.chain_agreement_count < self.required_quorum:
                raise ValueError("EPOCH_TRANSITION_QUORUM_INSUFFICIENT_CHAIN_AGREEMENT")
            if self.manifest_finality_count < self.required_quorum:
                raise ValueError("EPOCH_TRANSITION_QUORUM_INSUFFICIENT_MANIFEST_FINALITY")
            if not self.manifest_hash or not self.manifest_operation_id:
                raise ValueError("EPOCH_TRANSITION_QUORUM_MANIFEST_MISSING")
            if self.manifest_sequence_id is None or not self.manifest_record_digest:
                raise ValueError("EPOCH_TRANSITION_QUORUM_FINALITY_REFERENCE_MISSING")
            if self.report.epoch_schedule_commit_operation_id:
                if self.schedule_finality_count < self.required_quorum:
                    raise ValueError("EPOCH_TRANSITION_QUORUM_INSUFFICIENT_SCHEDULE_FINALITY")
                if self.schedule_sequence_id is None or not self.schedule_record_digest:
                    raise ValueError("EPOCH_TRANSITION_QUORUM_SCHEDULE_FINALITY_REFERENCE_MISSING")
            if self.reason_code is not None:
                raise ValueError("EPOCH_TRANSITION_QUORUM_READY_HAS_REASON")
        elif not self.reason_code:
            raise ValueError("EPOCH_TRANSITION_QUORUM_BLOCKED_REASON_MISSING")
        if self.quorum_hash != epoch_transition_quorum_hash(self):
            raise ValueError("EPOCH_TRANSITION_QUORUM_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"quorum_hash"})

    def verify_integrity(self) -> bool:
        return self.quorum_hash == epoch_transition_quorum_hash(self)


def epoch_transition_quorum_hash(report: EpochTransitionQuorumReport) -> str:
    """Return the deterministic hash of the quorum report."""

    return _canonical_hash(report.unsigned_payload())


def _rpc_result(payload: dict[str, Any], path: str) -> dict[str, Any]:
    if payload.get("error") not in {None, ""}:
        raise ValueError(f"CometBFT RPC returned an error for {path}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError(f"CometBFT RPC result is invalid for {path}")
    return result


def _fetch_json(endpoint: str, path: str, params: dict[str, str]) -> dict[str, Any]:
    query = urllib_parse.urlencode(params)
    request = urllib_request.Request(
        f"{endpoint.rstrip('/')}{path}?{query}",
        method="GET",
        headers={"Accept": "application/json"},
    )
    with urllib_request.urlopen(request, timeout=10) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("CometBFT RPC response is invalid")
    return value


def _query_value(
    fetcher: Fetcher,
    endpoint: str,
    path: str,
) -> tuple[dict[str, Any], int]:
    response = _rpc_result(
        fetcher(
            endpoint,
            "/abci_query",
            {"path": json.dumps(path, separators=(",", ":")), "prove": "false"},
        ),
        "/abci_query",
    )
    query = response.get("response")
    if not isinstance(query, dict) or int(query.get("code", -1)) != 0:
        raise ValueError(f"ABCI query failed for {path}")
    try:
        height = int(query.get("height"))
    except (TypeError, ValueError) as error:
        raise ValueError(f"ABCI query height is invalid for {path}") from error
    if height < 1:
        raise ValueError(f"ABCI query height is invalid for {path}")
    encoded = query.get("value")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError(f"ABCI query value is unavailable for {path}")
    try:
        value = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
    except (
        ValueError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as error:
        raise ValueError(f"ABCI query value is not valid JSON for {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"ABCI query value is not an object for {path}")
    return value, height


def _status(fetcher: Fetcher, endpoint: str) -> tuple[str, str, int, bool]:
    result = _rpc_result(fetcher(endpoint, "/status", {}), "/status")
    node_info = result.get("node_info")
    sync_info = result.get("sync_info")
    if not isinstance(node_info, dict) or not isinstance(sync_info, dict):
        raise ValueError("CometBFT status is incomplete")
    chain_id = node_info.get("network")
    node_id = node_info.get("id")
    try:
        height = int(sync_info.get("latest_block_height"))
    except (TypeError, ValueError) as error:
        raise ValueError("CometBFT status height is invalid") from error
    if (
        not isinstance(chain_id, str)
        or not chain_id.strip()
        or not isinstance(node_id, str)
        or not node_id.strip()
        or height < 1
    ):
        raise ValueError("CometBFT status identity is incomplete")
    return chain_id, node_id, height, bool(sync_info.get("catching_up"))


def _manifest_reference(
    fetcher: Fetcher,
    endpoint: str,
    operation_id: str,
    *,
    minimum_height: int,
) -> tuple[dict[str, Any], int]:
    reference, query_height = _query_value(
        fetcher,
        endpoint,
        f"operation/finalized/{operation_id}",
    )
    if query_height < minimum_height:
        raise ValueError("finalized manifest query is behind transition report")
    if reference.get("operation_id") != operation_id:
        raise ValueError("finalized manifest operation ID does not match report")
    if reference.get("operation_type") != EPOCH_RESULT_MANIFEST_OPERATION:
        raise ValueError("finalized manifest operation type is invalid")
    if isinstance(reference.get("sequence_id"), bool) or not isinstance(
        reference.get("sequence_id"), int
    ) or reference["sequence_id"] < 1:
        raise ValueError("finalized manifest sequence is invalid")
    if not isinstance(reference.get("record_digest"), str) or not reference["record_digest"].strip():
        raise ValueError("finalized manifest record digest is invalid")
    return {
        "operation_id": reference["operation_id"],
        "operation_type": reference["operation_type"],
        "sequence_id": reference["sequence_id"],
        "record_digest": reference["record_digest"],
    }, query_height


def _manifest_projection(
    fetcher: Fetcher,
    endpoint: str,
    epoch_number: int,
    *,
    minimum_height: int,
) -> tuple[dict[str, Any], int]:
    projection, query_height = _query_value(
        fetcher,
        endpoint,
        f"epoch/result-manifest/{epoch_number}",
    )
    if query_height < minimum_height:
        raise ValueError("manifest projection query is behind transition report")
    if projection.get("epoch_number") != epoch_number:
        raise ValueError("manifest projection epoch does not match report")
    if projection.get("operation_type") != EPOCH_RESULT_MANIFEST_OPERATION:
        raise ValueError("manifest projection operation type is invalid")
    return projection, query_height


def _schedule_reference(
    fetcher: Fetcher,
    endpoint: str,
    operation_id: str,
    *,
    minimum_height: int,
) -> tuple[dict[str, Any], int]:
    reference, query_height = _query_value(
        fetcher,
        endpoint,
        f"operation/finalized/{operation_id}",
    )
    if query_height < minimum_height:
        raise ValueError("finalized schedule query is behind transition report")
    if reference.get("operation_id") != operation_id:
        raise ValueError("finalized schedule operation ID does not match report")
    if reference.get("operation_type") != EPOCH_SCHEDULE_COMMIT_OPERATION:
        raise ValueError("finalized schedule operation type is invalid")
    if isinstance(reference.get("sequence_id"), bool) or not isinstance(
        reference.get("sequence_id"), int
    ) or reference["sequence_id"] < 1:
        raise ValueError("finalized schedule sequence is invalid")
    if not isinstance(reference.get("record_digest"), str) or not reference["record_digest"].strip():
        raise ValueError("finalized schedule record digest is invalid")
    return {
        "operation_id": reference["operation_id"],
        "operation_type": reference["operation_type"],
        "sequence_id": reference["sequence_id"],
        "record_digest": reference["record_digest"],
    }, query_height


def _schedule_projection(
    fetcher: Fetcher,
    endpoint: str,
    *,
    minimum_height: int,
) -> tuple[dict[str, Any], int]:
    projection, query_height = _query_value(
        fetcher,
        endpoint,
        "epoch/schedule",
    )
    if query_height < minimum_height:
        raise ValueError("schedule projection query is behind transition report")
    if projection.get("operation_type") != EPOCH_SCHEDULE_COMMIT_OPERATION:
        raise ValueError("schedule projection operation type is invalid")
    schedule = projection.get("epoch_schedule")
    if not isinstance(schedule, dict):
        raise ValueError("schedule projection is missing epoch schedule")
    return projection, query_height


def collect_epoch_transition_quorum(
    *,
    rpc_urls: list[str],
    quorum: int | None = None,
    fetcher: Fetcher = _fetch_json,
) -> dict[str, Any]:
    """Collect a fail-closed, read-only epoch transition quorum report."""

    if len(rpc_urls) < 2 or len(set(rpc_urls)) != len(rpc_urls):
        raise ValueError("at least two unique RPC endpoints are required")
    required_quorum = (len(rpc_urls) // 2) + 1 if quorum is None else quorum
    if not 2 <= required_quorum <= len(rpc_urls):
        raise ValueError("epoch transition quorum is outside RPC count")

    observations: list[dict[str, Any]] = []
    for rpc_url in rpc_urls:
        observation: dict[str, Any] = {"rpc_url": rpc_url, "status": "FAIL"}
        try:
            chain_id, node_id, status_height, catching_up = _status(fetcher, rpc_url)
            report_value, report_query_height = _query_value(
                fetcher,
                rpc_url,
                "epoch/transition-inputs",
            )
            report = EpochTransitionInputReport.model_validate(report_value)
            if report_query_height > status_height:
                raise ValueError("epoch transition report is ahead of node status")
            if report.status == "READY" and report.closing_height is not None:
                if report_query_height < report.closing_height:
                    raise ValueError("epoch transition report is ahead of queried state")

            observation.update(
                {
                    "status": "PASS",
                    "node_id": node_id,
                    "chain_id": chain_id,
                    "status_height": status_height,
                    "report_query_height": report_query_height,
                    "catching_up": catching_up,
                    "report": report.model_dump(mode="json"),
                }
            )
            schedule_operation_id = report.epoch_schedule_commit_operation_id
            if schedule_operation_id:
                schedule_reference, schedule_reference_query_height = _schedule_reference(
                    fetcher,
                    rpc_url,
                    schedule_operation_id,
                    minimum_height=report_query_height,
                )
                schedule_projection, schedule_projection_query_height = _schedule_projection(
                    fetcher,
                    rpc_url,
                    minimum_height=report_query_height,
                )
                if schedule_projection.get("operation_id") != schedule_operation_id:
                    raise ValueError("schedule projection operation ID does not match report")
                for field in (
                    "operation_id",
                    "operation_type",
                    "sequence_id",
                    "record_digest",
                ):
                    if schedule_projection.get(field) != schedule_reference.get(field):
                        raise ValueError(
                            "schedule projection conflicts with finalized operation reference"
                        )
                schedule_value = schedule_projection["epoch_schedule"]
                expected_schedule = {
                    "schema_version": report.epoch_schedule_version,
                    "schedule_hash": report.epoch_schedule_hash,
                }
                for field, expected in expected_schedule.items():
                    if schedule_value.get(field) != expected:
                        raise ValueError(f"schedule projection field {field} does not match report")
                observation["schedule_reference_query_height"] = schedule_reference_query_height
                observation["schedule_projection_query_height"] = schedule_projection_query_height
                observation["schedule_reference"] = schedule_reference
                observation["schedule_projection"] = schedule_projection
                observation["schedule_finalized"] = True
            else:
                observation["schedule_finalized"] = report.status != "BLOCKED"
            if report.status == "READY":
                operation_id = report.epoch_result_manifest_operation_id
                if not operation_id or not report.epoch_result_manifest_hash:
                    raise ValueError("READY report has no finalized manifest identity")
                reference, reference_query_height = _manifest_reference(
                    fetcher,
                    rpc_url,
                    operation_id,
                    minimum_height=report_query_height,
                )
                projection, projection_query_height = _manifest_projection(
                    fetcher,
                    rpc_url,
                    report.closing_epoch or 0,
                    minimum_height=report_query_height,
                )
                if projection.get("operation_id") != operation_id:
                    raise ValueError("manifest projection operation ID does not match report")
                if projection.get("manifest_hash") != report.epoch_result_manifest_hash:
                    raise ValueError("manifest projection hash does not match report")
                for field in (
                    "operation_id",
                    "operation_type",
                    "sequence_id",
                    "record_digest",
                ):
                    if projection.get(field) != reference.get(field):
                        raise ValueError(
                            "manifest projection conflicts with finalized operation reference"
                        )
                expected_projection = {
                    "manifest_hash": report.epoch_result_manifest_hash,
                    "epoch_number": report.closing_epoch,
                    "closing_height": report.closing_height,
                    "closing_time": report.canonical_block_time,
                    "closing_block_hash": report.closing_block_hash,
                    "closing_state_root": report.closing_state_root,
                    "source_app_hash": report.source_app_hash,
                    "epoch_schedule_version": report.epoch_schedule_version,
                    "epoch_schedule_hash": report.epoch_schedule_hash,
                    "scheduled_end_time": report.scheduled_end_time,
                }
                for field, expected in expected_projection.items():
                    if projection.get(field) != expected:
                        raise ValueError(
                            f"manifest projection field {field} does not match report"
                        )
                observation["manifest_reference_query_height"] = reference_query_height
                observation["manifest_projection_query_height"] = projection_query_height
                observation["manifest_reference"] = reference
                observation["manifest_projection"] = projection
                observation["manifest_finalized"] = True
            else:
                observation["manifest_finalized"] = False
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            binascii.Error,
        ) as error:
            observation["error"] = str(error)
        observations.append(observation)

    passed = [item for item in observations if item.get("status") == "PASS"]
    chain_counts = Counter(str(item["chain_id"]) for item in passed)
    chain_id, chain_count = chain_counts.most_common(1)[0] if chain_counts else (None, 0)
    eligible = [
        item
        for item in passed
        if item.get("chain_id") == chain_id and item.get("catching_up") is False
    ]

    def report_key(item: dict[str, Any]) -> str:
        return json.dumps(item["report"], sort_keys=True, separators=(",", ":"))

    ready_eligible = [
        item
        for item in eligible
        if item.get("report", {}).get("status") == "READY"
        and item.get("manifest_finalized") is True
        and item.get("schedule_finalized") is True
    ]
    identity_counts = Counter(
        json.dumps(
            {
                "report": item["report"],
                "manifest_reference": item["manifest_reference"],
                "schedule_reference": item.get("schedule_reference"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        for item in ready_eligible
    )
    winning_identity, winning_count = (
        identity_counts.most_common(1)[0] if identity_counts else (None, 0)
    )
    if winning_identity is not None:
        winning_payload = json.loads(winning_identity)
        winning_report = winning_payload["report"]
        winning_reference = winning_payload["manifest_reference"]
        winning_schedule_reference = winning_payload.get("schedule_reference")
        manifest_finality_count = winning_count
        schedule_finality_count = winning_count if winning_schedule_reference is not None else 0
    else:
        report_counts = Counter(report_key(item) for item in eligible)
        winning_report_key, winning_count = (
            report_counts.most_common(1)[0] if report_counts else (None, 0)
        )
        winning_report = json.loads(winning_report_key) if winning_report_key else None
        winning_reference = None
        matching_items = [
            item for item in eligible if report_key(item) == winning_report_key
        ]
        winning_schedule_reference = (
            matching_items[0].get("schedule_reference") if matching_items else None
        )
        manifest_finality_count = 0
        schedule_finality_count = sum(
            item.get("schedule_finalized") is True
            and item.get("schedule_reference") == winning_schedule_reference
            for item in matching_items
        )

    typed_report = (
        EpochTransitionInputReport.model_validate(winning_report)
        if winning_report is not None
        else None
    )
    ready = (
        typed_report is not None
        and typed_report.status == "READY"
        and winning_identity is not None
        and winning_count >= required_quorum
        and chain_count >= required_quorum
        and manifest_finality_count >= required_quorum
        and (
            not typed_report.epoch_schedule_commit_operation_id
            or schedule_finality_count >= required_quorum
        )
    )
    if ready:
        reason_code = None
    elif typed_report is not None and typed_report.status == "BLOCKED":
        reason_code = typed_report.reason_code or "EPOCH_TRANSITION_INPUTS_NOT_READY"
    elif typed_report is not None and typed_report.status == "READY":
        reason_code = (
            "EPOCH_SCHEDULE_FINALITY_QUORUM_UNAVAILABLE"
            if typed_report.epoch_schedule_commit_operation_id
            and schedule_finality_count < required_quorum
            else "EPOCH_RESULT_MANIFEST_FINALITY_QUORUM_UNAVAILABLE"
        )
    else:
        reason_code = "EPOCH_TRANSITION_QUORUM_UNAVAILABLE"

    manifest_hash = typed_report.epoch_result_manifest_hash if typed_report else None
    manifest_operation_id = (
        typed_report.epoch_result_manifest_operation_id if typed_report else None
    )
    report_payload = {
        "schema_version": EPOCH_TRANSITION_QUORUM_VERSION,
        "status": "READY" if ready else "BLOCKED",
        "chain_id": chain_id,
        "required_quorum": required_quorum,
        "agreement_count": winning_count,
        "chain_agreement_count": chain_count,
        "manifest_finality_count": manifest_finality_count,
        "report": winning_report,
        "manifest_hash": manifest_hash,
        "manifest_operation_id": manifest_operation_id,
        "manifest_sequence_id": (
            winning_reference.get("sequence_id") if winning_reference is not None else None
        ),
        "manifest_record_digest": (
            winning_reference.get("record_digest") if winning_reference is not None else None
        ),
        "schedule_finality_count": schedule_finality_count,
        "schedule_operation_id": (
            winning_schedule_reference.get("operation_id")
            if winning_schedule_reference is not None
            else (typed_report.epoch_schedule_commit_operation_id if typed_report else None)
        ),
        "schedule_sequence_id": (
            winning_schedule_reference.get("sequence_id")
            if winning_schedule_reference is not None
            else (typed_report.epoch_schedule_commit_sequence_id if typed_report else None)
        ),
        "schedule_record_digest": (
            winning_schedule_reference.get("record_digest")
            if winning_schedule_reference is not None
            else (typed_report.epoch_schedule_commit_record_digest if typed_report else None)
        ),
        "observations_hash": _canonical_hash(observations),
        "observations": observations,
        "reason_code": reason_code,
    }
    return EpochTransitionQuorumReport(
        **report_payload,
        quorum_hash=_canonical_hash(report_payload),
    ).model_dump(mode="json")


__all__ = [
    "EPOCH_SCHEDULE_COMMIT_OPERATION",
    "EPOCH_RESULT_MANIFEST_OPERATION",
    "EPOCH_TRANSITION_QUORUM_VERSION",
    "EpochTransitionQuorumReport",
    "collect_epoch_transition_quorum",
    "epoch_transition_quorum_hash",
]
