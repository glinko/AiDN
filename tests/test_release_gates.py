from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_TOOL = ROOT / "tools/verify-release-gates.py"


def _run_gate(*extra: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [
            sys.executable,
            str(GATE_TOOL),
            "--profile",
            str(ROOT / "profiles/aidn-mainnet-candidate-1.json"),
            "--fixture-manifest",
            str(ROOT / "fixtures/manifest.json"),
            *extra,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_release_gate_reports_active_g1_as_pass_and_operational_gates_missing() -> None:
    result = _run_gate("--allow-incomplete")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["status"] == "INCOMPLETE"
    assert payload["gates"]["G0"]["status"] == "PASS"
    assert payload["gates"]["G1"]["status"] == "PASS"
    assert payload["gates"]["G1"]["details"]["strict_operation_coverage"]["legacy_excluded"] == 11
    assert payload["gates"]["G2"]["status"] == "NOT_RUN"


def test_release_gate_fails_closed_without_allow_incomplete() -> None:
    result = _run_gate()
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["status"] == "INCOMPLETE"
    assert payload["gates"]["G1"]["status"] == "PASS"
