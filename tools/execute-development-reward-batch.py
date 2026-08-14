#!/usr/bin/env python3
"""Execute one hash-bound ECO-0007 batch through canonical consensus.

The command is deliberately an orchestration surface. It does not create
keys, sign envelopes, apply local Q, or treat CheckTx as payment finality.
Before every retry it re-reads the epoch/pool preflight from the configured
validator quorum and stops if the batch no longer matches the canonical pool.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from aidn_hypervisor.consensus.cometbft_finality import build_cometbft_multi_rpc_finality_source
from aidn_hypervisor.consensus.deployment import load_cometbft_finality_deployment_config
from aidn_hypervisor.consensus.service import (
    ConsensusMode,
    ConsensusService,
    ConsensusServiceConfig,
    SubmissionRecord,
)
from aidn_hypervisor.reward.development_execution import (
    DevelopmentRewardBatchExecution,
    DevelopmentRewardBatchExecutor,
)
from aidn_hypervisor.reward.development_preflight_quorum import (
    DevelopmentRewardPreflightQuorum,
    build_development_reward_preflight_quorum,
    collect_development_reward_preflight,
)
from aidn_hypervisor.reward.development_production import (
    DevelopmentRewardProductionBatch,
    DevelopmentRewardProductionProfile,
)


class JsonPendingEnvelopeStore:
    """Durable pending-envelope and submission-recovery stores.

    The pending file contains only envelopes that still need reconciliation.
    The sibling submission journal survives pending cleanup and retains the
    exact transport identity observed for every operation.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.submission_journal_path = path.with_name(f"{path.stem}.submissions.json")

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("pending envelope state is not valid JSON") from error
        if not isinstance(value, dict):
            raise ValueError("pending envelope state must be a JSON object")
        return value

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def _read_submission_journal(self) -> dict[str, Any]:
        if not self.submission_journal_path.exists():
            return {}
        try:
            value = json.loads(self.submission_journal_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("submission journal state is not valid JSON") from error
        if not isinstance(value, dict):
            raise ValueError("submission journal state must be a JSON object")
        return value

    def _write_submission_journal(self, value: dict[str, Any]) -> None:
        self.submission_journal_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.submission_journal_path.with_name(
            f".{self.submission_journal_path.name}.{os.getpid()}.tmp"
        )
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.submission_journal_path)

    def stage_pending_consensus_envelope(self, envelope: Any) -> None:
        pending = self._read()
        pending[envelope.operation_id] = envelope.model_dump(mode="json")
        self._write(pending)

    def discard_pending_consensus_envelopes(self, *operation_ids: str) -> None:
        pending = self._read()
        changed = False
        for operation_id in operation_ids:
            changed = pending.pop(operation_id, None) is not None or changed
        if changed:
            if pending:
                self._write(pending)
            else:
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass

    def record_submission(self, record: SubmissionRecord) -> None:
        """Persist non-secret submission metadata for restart reconciliation."""
        operation_id = record.operation_id
        status = record.status.value if hasattr(record.status, "value") else str(record.status)
        journal = self._read_submission_journal()
        journal[operation_id] = {
            "operation_id": operation_id,
            "status": status,
            "transaction_hash": record.transaction_hash,
            "block_height": record.block_height,
            "error": record.error,
        }
        self._write_submission_journal(journal)

    def transaction_hash_for_operation(self, operation_id: str) -> str | None:
        """Return a previously observed tx hash without exposing envelope data."""
        entry = self._read_submission_journal().get(operation_id)
        if not isinstance(entry, dict):
            return None
        transaction_hash = entry.get("transaction_hash")
        return transaction_hash if isinstance(transaction_hash, str) else None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path)
    parser.add_argument("--production-profile", required=True, type=Path)
    parser.add_argument("--finality-config", required=True, type=Path)
    parser.add_argument("--execution-output", required=True, type=Path)
    parser.add_argument("--pending-state", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    return parser


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_current_preflight(
    *,
    rpc_endpoints: list[str],
    pool_id: str,
    quorum: int,
) -> DevelopmentRewardPreflightQuorum:
    report = collect_development_reward_preflight(
        rpc_urls=rpc_endpoints,
        pool_id=pool_id,
        quorum=quorum,
    )
    return build_development_reward_preflight_quorum(report)


def _assert_current_preflight(
    *,
    batch: DevelopmentRewardProductionBatch,
    current: DevelopmentRewardPreflightQuorum,
) -> None:
    expected = batch.preflight_quorum
    if current.chain_id != batch.chain_id or current.pool_id != batch.pool_id:
        raise ValueError("DEVELOPMENT_REWARD_EXECUTION_PREFLIGHT_NETWORK_MISMATCH")
    if current.preflight.preflight_hash != expected.preflight.preflight_hash:
        raise ValueError("DEVELOPMENT_REWARD_EXECUTION_PREFLIGHT_CHANGED")
    if current.preflight.epoch != batch.epoch:
        raise ValueError("DEVELOPMENT_REWARD_EXECUTION_PREFLIGHT_EPOCH_MISMATCH")
    if (
        current.preflight.source_epoch_transition_operation_id
        != batch.source_epoch_transition_operation_id
    ):
        raise ValueError("DEVELOPMENT_REWARD_EXECUTION_PREFLIGHT_SOURCE_MISMATCH")
    if current.preflight.pool_budget_reference != batch.pool_budget_reference:
        raise ValueError("DEVELOPMENT_REWARD_EXECUTION_PREFLIGHT_REFERENCE_MISMATCH")
    if current.preflight.pool_budget_q_atoms != expected.preflight.pool_budget_q_atoms:
        raise ValueError("DEVELOPMENT_REWARD_EXECUTION_PREFLIGHT_BUDGET_MISMATCH")


def _execution_result(path: Path, result: DevelopmentRewardBatchExecution) -> None:
    _write_json(path, result.model_dump(mode="json"))


def main() -> int:
    args = _parser().parse_args()
    if args.timeout_seconds <= 0 or args.poll_seconds <= 0:
        raise SystemExit("--timeout-seconds and --poll-seconds must be positive")

    batch = DevelopmentRewardProductionBatch.model_validate_json(
        args.batch.read_text(encoding="utf-8")
    )
    profile = DevelopmentRewardProductionProfile.model_validate_json(
        args.production_profile.read_text(encoding="utf-8")
    )
    deployment = load_cometbft_finality_deployment_config(args.finality_config)
    if deployment.chain_id != batch.chain_id:
        raise ValueError("DEVELOPMENT_REWARD_EXECUTION_FINALITY_CHAIN_MISMATCH")

    consensus = ConsensusService(
        ConsensusServiceConfig(
            node_id=f"development-reward-executor:{batch.batch_id[:16]}",
            mode=ConsensusMode.NON_VALIDATOR,
            cometbft_endpoint=deployment.rpc_endpoints[0],
            chain_id=batch.chain_id,
            submission_timeout_seconds=float(deployment.timeout_seconds),
            retry_interval_seconds=float(deployment.timeout_seconds),
            max_retries=1,
        )
    )
    pending_state = args.pending_state or args.execution_output.with_suffix(".pending.json")
    pending_store = JsonPendingEnvelopeStore(pending_state)

    def transaction_hash_for_operation(operation_id: str) -> str | None:
        return (
            pending_store.transaction_hash_for_operation(operation_id)
            or consensus.transaction_hash_for_operation(operation_id)
        )

    finality_source = build_cometbft_multi_rpc_finality_source(
        config=deployment.runtime_config(),
        transaction_hash_for_operation=transaction_hash_for_operation,
    )
    executor = DevelopmentRewardBatchExecutor(
        consensus,
        finality_source=finality_source,
        pending_envelope_store=pending_store,
    )

    deadline = time.monotonic() + args.timeout_seconds
    result: DevelopmentRewardBatchExecution | None = None
    while True:
        current_preflight = _load_current_preflight(
            rpc_endpoints=list(deployment.rpc_endpoints),
            pool_id=batch.pool_id,
            quorum=deployment.minimum_agreement,
        )
        _assert_current_preflight(batch=batch, current=current_preflight)
        result = executor.execute(batch, profile=profile)
        _execution_result(args.execution_output, result)
        print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
        if result.status != "AWAITING_VERIFIED_FINALITY":
            return 0 if result.status == "FINALIZED" else 2
        if time.monotonic() >= deadline:
            return 2
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        raise SystemExit(2) from error
