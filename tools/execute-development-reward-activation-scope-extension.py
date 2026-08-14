#!/usr/bin/env python3
"""Submit one ECO-0007 scope extension and wait for verified finality.

The command never changes approvals or local balances. It persists the exact
envelope before submission, retries only that same operation identity, and
removes the pending file only after the configured validator quorum proves
operation-bound finality.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from aidn_hypervisor.consensus.cometbft_finality import build_cometbft_multi_rpc_finality_source
from aidn_hypervisor.consensus.deployment import load_cometbft_finality_deployment_config
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.service import (
    ConsensusMode,
    ConsensusService,
    ConsensusServiceConfig,
    SubmissionStatus,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--envelope", required=True, type=Path)
    parser.add_argument("--finality-config", required=True, type=Path)
    parser.add_argument("--execution-output", required=True, type=Path)
    parser.add_argument("--pending-state", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    return parser


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_or_stage_envelope(source: Path, pending: Path) -> LedgerOperationEnvelope:
    envelope = LedgerOperationEnvelope.model_validate_json(source.read_text(encoding="utf-8"))
    if envelope.operation_type != "DEVELOPMENT_REWARD_ACTIVATION_SCOPE_EXTEND":
        raise ValueError("DEVELOPMENT_REWARD_SCOPE_EXTENSION_OPERATION_REQUIRED")
    if pending.exists():
        existing = LedgerOperationEnvelope.model_validate_json(pending.read_text(encoding="utf-8"))
        if existing.model_dump(mode="json") != envelope.model_dump(mode="json"):
            raise ValueError("DEVELOPMENT_REWARD_SCOPE_EXTENSION_PENDING_CONFLICT")
    else:
        _write_json(pending, envelope.model_dump(mode="json"))
    return envelope


def main() -> int:
    args = _parser().parse_args()
    if args.timeout_seconds <= 0 or args.poll_seconds <= 0:
        raise SystemExit("--timeout-seconds and --poll-seconds must be positive")
    deployment = load_cometbft_finality_deployment_config(args.finality_config)
    pending = args.pending_state or args.execution_output.with_suffix(".pending.json")
    envelope = _load_or_stage_envelope(args.envelope, pending)
    consensus = ConsensusService(
        ConsensusServiceConfig(
            node_id=f"development-reward-scope-extension:{envelope.operation_id[:16]}",
            mode=ConsensusMode.NON_VALIDATOR,
            cometbft_endpoint=deployment.rpc_endpoints[0],
            chain_id=deployment.chain_id,
            submission_timeout_seconds=float(deployment.timeout_seconds),
            retry_interval_seconds=float(deployment.timeout_seconds),
            max_retries=1,
        )
    )
    finality_source = build_cometbft_multi_rpc_finality_source(
        config=deployment.runtime_config(),
        transaction_hash_for_operation=consensus.transaction_hash_for_operation,
    )
    deadline = time.monotonic() + args.timeout_seconds
    while True:
        record = consensus.submit_operation(envelope, retry_existing=True)
        if record.status == SubmissionStatus.FAILED:
            result = {
                "status": "REJECTED",
                "operation_id": envelope.operation_id,
                "error": record.error,
                "pending_state": str(pending),
            }
            _write_json(args.execution_output, result)
            print(json.dumps(result, sort_keys=True))
            return 2
        finalized = consensus.reconcile_finality(
            envelope.operation_id,
            finality_source=finality_source,
        )
        if finalized is not None and finalized.status == SubmissionStatus.FINALIZED:
            result = {
                "status": "FINALIZED",
                "operation_id": envelope.operation_id,
                "extension_id": envelope.payload.get("extension_id"),
                "extension_hash": envelope.payload.get("extension_hash"),
                "transaction_hash": finalized.transaction_hash,
                "block_height": finalized.block_height,
                "validator_quorum": deployment.minimum_agreement,
            }
            _write_json(args.execution_output, result)
            try:
                pending.unlink()
            except FileNotFoundError:
                pass
            print(json.dumps(result, sort_keys=True))
            return 0
        if time.monotonic() >= deadline:
            result = {
                "status": "AWAITING_VERIFIED_FINALITY",
                "operation_id": envelope.operation_id,
                "transaction_hash": record.transaction_hash,
                "submission_status": record.status.value,
                "pending_state": str(pending),
            }
            _write_json(args.execution_output, result)
            print(json.dumps(result, sort_keys=True))
            return 2
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, StopIteration) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        raise SystemExit(2) from error
