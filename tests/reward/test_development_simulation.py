import json
import subprocess
import sys
from pathlib import Path


def test_development_reward_cli_is_non_emitting():
    repository_root = Path(__file__).parents[2]
    result = subprocess.run(
        [
            sys.executable,
            str(repository_root / "tools" / "simulate-development-rewards.py"),
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["simulation_only"] is True
    assert payload["emits_q"] is False
    assert payload["ledger_writes"] is False
    calculation = payload["calculation"]
    assert calculation["pool"]["pool_in_q_atoms"] == 3_000_000_000
    assert calculation["calculation_root"].startswith("sha256:")
