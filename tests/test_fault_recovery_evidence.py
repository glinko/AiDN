from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from aidn_hypervisor.consensus.snapshot_acceptance import run_snapshot_acceptance

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/verify-fault-recovery-evidence.py"
SPEC = importlib.util.spec_from_file_location("fault_recovery_evidence", TOOL)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_g2_report(path: Path) -> None:
    path.write_text(json.dumps(run_snapshot_acceptance()), encoding="utf-8")


def _live_report() -> dict:
    endpoints = [f"http://validator-{index}" for index in range(4)]
    before = [
        {
            "rpc_url": endpoint,
            "height": 10,
            "app_hash": "A" * 64,
            "node_id": f"node-{index}",
            "chain_id": "chain-test",
            "catching_up": False,
        }
        for index, endpoint in enumerate(endpoints)
    ]
    after = [
        {
            **snapshot,
            "height": 11,
        }
        for snapshot in before
    ]
    checks = {
        "all_validators_reconverged": True,
        "target_identity_preserved": True,
        "target_chain_preserved": True,
    }
    action = {
        "status": "PASS",
        "evidence_reference": "sha256:" + "1" * 64,
        "command": "restart-validator",
        "command_result": {"returncode": 0},
        "command_outage_observed": True,
        "outage_observed": True,
        "before": before,
        "after": after,
        "checks": checks,
    }
    stale = {
        "schema_version": 1,
        "status": "PASS",
        "scope": "CONTROLLED_LAN_TESTNET",
        "drill": "STALE_PREDECESSOR_REJECTED",
        "rpc_url": endpoints[0],
        "source_transaction_hash": "2" * 64,
        "before": before[0],
        "after": after[0],
        "rejection": {
            "transaction_hash": "3" * 64,
            "code": 1,
            "log": "funding predecessor is not finalized",
        },
        "checks": {
            "transaction_rejected": True,
            "funding_predecessor_error": True,
            "validator_identity_preserved": True,
        },
        "evidence_reference": "sha256:" + "4" * 64,
    }
    report = {
        "schema_version": 1,
        "status": "PASS",
        "scope": "CONTROLLED_LAN_TESTNET",
        "validator_rpc_urls": endpoints,
        "target_rpc_url": endpoints[0],
        "drills": {
            "graceful_restart": action,
            "abrupt_process_termination": action,
            "host_reboot": {
                **action,
                "recovery_command": "start-validator",
                "recovery_result": {"returncode": 0},
            },
            "stale_predecessor_rejected": stale,
        },
    }
    report["report_hash"] = MODULE._report_hash(report)
    return report


def test_fault_recovery_report_does_not_promote_missing_live_drills(tmp_path: Path) -> None:
    g2_path = tmp_path / "g2.json"
    _write_g2_report(g2_path)

    report = MODULE.verify_fault_recovery_evidence(
        g2_report_path=g2_path,
        live_report_path=None,
    )

    assert report["status"] == "INCOMPLETE"
    assert set(report["missing_live_drills"]) == set(MODULE.REQUIRED_LIVE_DRILLS)


def test_fault_recovery_report_combines_g2_and_live_drills(tmp_path: Path) -> None:
    g2_path = tmp_path / "g2.json"
    live_path = tmp_path / "live.json"
    _write_g2_report(g2_path)
    live_path.write_text(json.dumps(_live_report()), encoding="utf-8")

    report = MODULE.verify_fault_recovery_evidence(
        g2_report_path=g2_path,
        live_report_path=live_path,
    )

    assert report["status"] == "PASS"
    assert set(report["drills"]) == set(MODULE.REQUIRED_G2_DRILLS) | set(MODULE.REQUIRED_LIVE_DRILLS)


def test_fault_recovery_report_rejects_tampered_live_report(tmp_path: Path) -> None:
    g2_path = tmp_path / "g2.json"
    live_path = tmp_path / "live.json"
    _write_g2_report(g2_path)
    live = _live_report()
    live["drills"]["host_reboot"]["recovery_result"]["returncode"] = 1
    live_path.write_text(json.dumps(live), encoding="utf-8")

    with pytest.raises(ValueError, match="live fault report hash is invalid"):
        MODULE.verify_fault_recovery_evidence(
            g2_report_path=g2_path,
            live_report_path=live_path,
        )


def test_fault_recovery_report_requires_successful_action_returncode(tmp_path: Path) -> None:
    g2_path = tmp_path / "g2.json"
    live_path = tmp_path / "live.json"
    _write_g2_report(g2_path)
    live = _live_report()
    live["drills"]["graceful_restart"]["command_result"].pop("returncode")
    live["report_hash"] = MODULE._report_hash({key: value for key, value in live.items() if key != "report_hash"})
    live_path.write_text(json.dumps(live), encoding="utf-8")

    with pytest.raises(ValueError, match="live fault drill command failed: graceful_restart"):
        MODULE.verify_fault_recovery_evidence(
            g2_report_path=g2_path,
            live_report_path=live_path,
        )
