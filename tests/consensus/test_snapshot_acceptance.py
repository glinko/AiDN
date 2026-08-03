from __future__ import annotations

import copy

import pytest

from aidn_hypervisor.consensus.snapshot_acceptance import (
    SnapshotAcceptanceError,
    run_snapshot_acceptance,
    verify_snapshot_acceptance_report,
)


def test_snapshot_acceptance_proves_restore_state_sync_and_continuity() -> None:
    report = run_snapshot_acceptance()

    assert report["status"] == "PASS"
    assert all(report["checks"].values())
    assert report["height_one"]["source_app_hash"] == report["height_one"]["restored_app_hash"]
    assert report["height_one"]["source_app_hash"] == report["height_one"]["state_synced_app_hash"]
    assert report["height_two"]["source_app_hash"] == report["height_two"]["restored_app_hash"]
    assert report["height_two"]["source_app_hash"] == report["height_two"]["state_synced_app_hash"]
    assert report["snapshot"]["corrupt_state_sync_statuses"][-1] != "accept"


def test_snapshot_acceptance_report_is_reproducible_and_tamper_evident() -> None:
    report = run_snapshot_acceptance()
    assert verify_snapshot_acceptance_report(report) == report

    tampered = copy.deepcopy(report)
    tampered["height_two"]["source_app_hash"] = "0" * 64
    with pytest.raises(SnapshotAcceptanceError, match="hash mismatch"):
        verify_snapshot_acceptance_report(tampered)
