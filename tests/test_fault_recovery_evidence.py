from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from aidn_hypervisor.consensus.snapshot_acceptance import run_snapshot_acceptance

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/verify-fault-recovery-evidence.py"
SPEC = importlib.util.spec_from_file_location("fault_recovery_evidence", TOOL)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_g2_report(path: Path) -> None:
    path.write_text(json.dumps(run_snapshot_acceptance()), encoding="utf-8")


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
    live_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "drills": {
                    name: {"status": "PASS", "evidence_reference": f"{name}.json"}
                    for name in MODULE.REQUIRED_LIVE_DRILLS
                },
            }
        ),
        encoding="utf-8",
    )

    report = MODULE.verify_fault_recovery_evidence(
        g2_report_path=g2_path,
        live_report_path=live_path,
    )

    assert report["status"] == "PASS"
    assert set(report["drills"]) == set(MODULE.REQUIRED_G2_DRILLS) | set(MODULE.REQUIRED_LIVE_DRILLS)
