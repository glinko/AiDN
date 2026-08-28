"""Safe Dashboard projection for Testnet participation operations.

The settlement monitor and payout store contain operational details which are
not Dashboard data: Treasury identity, signed transfer envelopes and protected
secret references must stay out of this projection.  This module deliberately
returns only programme and accounting facts an operator needs to understand
whether participation rewards are observing, calculating or settling.
"""

from __future__ import annotations

import re
from typing import Any

from aidn_hypervisor.testnet_participation_monitor import (
    TestnetParticipationSettlementMonitor,
)

_SAFE_ERROR_CODE = re.compile(r"\b(PARTICIPATION_[A-Z0-9_]+)\b")


def _safe_error_code(value: str | None) -> str | None:
    """Keep a machine-actionable reason without leaking a secret handle."""

    if not value:
        return None
    matched = _SAFE_ERROR_CODE.search(value)
    return matched.group(1) if matched is not None else "PARTICIPATION_MONITOR_ERROR"


def build_testnet_participation_status_payload(
    monitor: TestnetParticipationSettlementMonitor | None,
) -> dict[str, Any]:
    """Return a bounded, non-secret participation status document."""

    if monitor is None:
        return {
            "available": False,
            "runtime": {"enabled": False, "mode": "disabled"},
            "program": None,
            "monitor": {"scan_count": 0, "transition_count": 0, "processed_count": 0},
            "last_settlement": None,
            "last_error_code": None,
        }

    runtime = monitor.dispatcher.runtime
    program = runtime.program
    monitor_status = monitor.status()
    result = monitor_status.last_result
    runtime_result = result.runtime if result is not None else None
    settlement = runtime_result.settlement if runtime_result is not None else None
    batch = runtime_result.batch if runtime_result is not None else None

    last_settlement = None
    if result is not None:
        last_settlement = {
            "state": result.status,
            "source_epoch_transition_operation_id": result.source_epoch_transition_operation_id,
            "closing_epoch": result.closing_epoch,
            "period_start": result.period_start,
            "detail": result.detail,
            "accounting": (
                None
                if settlement is None
                else {
                    "settlement_id": settlement.settlement_id,
                    "settlement_hash": settlement.settlement_hash,
                    "program_policy_hash": settlement.program_policy_hash,
                    "period_end": settlement.period_end,
                    "eligible_node_count": sum(
                        1 for accrual in settlement.accruals if accrual.reward_q_atoms > 0
                    ),
                    "eligible_window_count": sum(
                        len(accrual.eligible_window_indices)
                        for accrual in settlement.accruals
                    ),
                    "total_reward_q_atoms": settlement.total_reward_q_atoms,
                }
            ),
            "payout": (
                None
                if runtime_result is None
                else {
                    "mode": runtime_result.mode,
                    "batch_status": runtime_result.batch_status,
                    "transfer_count": len(batch.transfers) if batch is not None else 0,
                    "submitted_operation_id": runtime_result.processed_operation_id,
                }
            ),
        }

    return {
        "available": True,
        "runtime": {
            "enabled": runtime.config.enabled,
            "mode": runtime.config.mode,
        },
        "program": (
            None
            if program is None
            else {
                "program_id": program.program_id,
                "network_id": program.network_id,
                "chain_id": program.chain_id,
                "policy_hash": program.policy_hash,
                "participation_window_seconds": program.participation_window_seconds,
                "settlement_period_seconds": program.settlement_period_seconds,
                "reward_per_eligible_window_q_atoms": (
                    program.reward_per_eligible_window_q_atoms
                ),
            }
        ),
        "monitor": {
            "scan_count": monitor_status.scan_count,
            "transition_count": monitor_status.transition_count,
            "processed_count": monitor_status.processed_count,
        },
        "last_settlement": last_settlement,
        "last_error_code": _safe_error_code(monitor_status.last_error),
    }


__all__ = ["build_testnet_participation_status_payload"]
