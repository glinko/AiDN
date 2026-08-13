#!/usr/bin/env python3
"""Build a live, quorum-bound Epoch Result Manifest.

The command is read-only with respect to the network.  It collects the
current Epoch Engine report from a validator quorum, derives the controlled
localnet no-work evidence bundle from the finalized schedule boundary, and
writes both the evidence bundle and the manifest.  It never signs or submits
an operation.

The no-work profile is intentionally limited to a zero-budget calibration
epoch.  Production epochs must use a finalized evidence bundle produced by
the relevant task, eligibility and reward services instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.consensus.epoch_result_evidence import (  # noqa: E402
    build_controlled_localnet_no_work_evidence,
    build_manifest_from_evidence,
)
from aidn_hypervisor.consensus.epoch_transition_inputs import EpochTransitionInputReport  # noqa: E402
from aidn_hypervisor.consensus.epoch_transition_quorum import collect_epoch_transition_quorum  # noqa: E402


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _rebase_anchor(path: Path | None) -> tuple[int | None, str | None]:
    if path is None:
        return None, None
    value = _object(path)
    evidence = value.get("finality_evidence")
    if not isinstance(evidence, dict):
        raise ValueError("rebase finality receipt is missing finality_evidence")
    height = evidence.get("block_height")
    start_time = value.get("effective_epoch_zero_start_time")
    if isinstance(height, bool) or not isinstance(height, int) or height < 1:
        raise ValueError("rebase finality receipt block_height is invalid")
    if not isinstance(start_time, str) or not start_time.strip():
        raise ValueError("rebase finality receipt start time is invalid")
    return height, start_time


def _schedule_from_quorum(quorum: dict[str, Any]) -> dict[str, Any]:
    observations = quorum.get("observations")
    if not isinstance(observations, list):
        raise ValueError("quorum report observations are missing")
    for observation in observations:
        if not isinstance(observation, dict) or observation.get("status") != "PASS":
            continue
        projection = observation.get("schedule_projection")
        if not isinstance(projection, dict):
            continue
        schedule = projection.get("epoch_schedule")
        if isinstance(schedule, dict):
            return schedule
    raise ValueError("quorum report has no finalized schedule projection")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", action="append", required=True, help="Validator RPC URL; repeat per validator")
    parser.add_argument("--network-id", required=True)
    parser.add_argument("--rebase-finality-receipt", type=Path)
    parser.add_argument("--start-height", type=int)
    parser.add_argument("--start-time")
    parser.add_argument("--evidence-reference", action="append", default=[])
    parser.add_argument("--evidence-output", required=True, type=Path)
    parser.add_argument("--manifest-output", required=True, type=Path)
    args = parser.parse_args()

    quorum = collect_epoch_transition_quorum(rpc_urls=args.rpc_url)
    if quorum.get("chain_id") is None:
        raise ValueError("quorum report has no chain identity")
    raw_report = quorum.get("report")
    if not isinstance(raw_report, dict):
        raise ValueError("quorum report has no canonical transition report")
    report = EpochTransitionInputReport.model_validate(raw_report)
    if report.status != "BLOCKED":
        raise ValueError("live Epoch report is not BLOCKED; refusing to build a duplicate manifest")

    receipt_height, receipt_start = _rebase_anchor(args.rebase_finality_receipt)
    start_height = args.start_height if args.start_height is not None else receipt_height
    start_time = args.start_time or receipt_start
    if start_height is None or start_time is None:
        raise ValueError("provide --start-height and --start-time, or --rebase-finality-receipt")
    if receipt_height is not None and args.start_height is not None and receipt_height != args.start_height:
        raise ValueError("start height conflicts with rebase finality receipt")
    if receipt_start is not None and args.start_time is not None and receipt_start != args.start_time:
        raise ValueError("start time conflicts with rebase finality receipt")

    schedule = _schedule_from_quorum(quorum)
    bundle = build_controlled_localnet_no_work_evidence(
        report=report,
        network_id=args.network_id,
        chain_id=str(quorum["chain_id"]),
        start_height=start_height,
        start_time=start_time,
        epoch_schedule=schedule,
        source_references=args.evidence_reference or [
            "controlled-localnet:no-work",
            f"epoch-schedule:{report.epoch_schedule_hash}",
        ],
    )
    manifest = build_manifest_from_evidence(bundle, report)
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.write_text(
        json.dumps(bundle.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.manifest_output.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "CREATED",
                "source_kind": bundle.source_kind,
                "chain_id": bundle.chain_id,
                "epoch_number": manifest.epoch_number,
                "closing_height": manifest.closing_height,
                "evidence_bundle_hash": bundle.bundle_hash,
                "manifest_hash": manifest.manifest_hash,
                "pool_budgets": manifest.pool_budgets,
                "evidence_output": str(args.evidence_output),
                "manifest_output": str(args.manifest_output),
                "signed": False,
                "broadcast": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        raise SystemExit(2) from error
