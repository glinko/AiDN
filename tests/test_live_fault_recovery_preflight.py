from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/preflight-live-fault-recovery.py"
SPEC = importlib.util.spec_from_file_location("live_fault_recovery_preflight", TOOL)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _config(tmp_path: Path) -> Path:
    commands = {
        name: {
            "command": f"execute-{name}",
            "preflight": {"transport": "ssh", "command": f"test -x /opt/aidn/{name}"},
        }
        for name in MODULE.REQUIRED_DRILLS
    }
    commands["stale_predecessor_rejected"]["preflight"] = {
        "transport": "local",
        "command": "test -f tools/run-cometbft-stale-predecessor-drill.py",
    }
    commands["host_reboot"].update(
        {
            "recovery_command": "recover-host",
            "recovery_preflight": {"transport": "ssh", "command": "test -x /opt/aidn/recover"},
        }
    )
    path = tmp_path / "preflight.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scope": "CONTROLLED_LAN_TESTNET",
                "ssh_target": "operator@jump",
                "validator_rpc_urls": [f"http://validator-{index}:26657" for index in range(4)],
                "target_rpc_url": "http://validator-0:26657",
                "commands": commands,
            }
        ),
        encoding="utf-8",
    )
    return path


def _rpc_status(endpoint: str) -> dict[str, object]:
    index = endpoint.split("validator-")[1].split(":")[0]
    return {
        "status": "PASS",
        "rpc_url": endpoint,
        "height": 10,
        "app_hash": "A" * 64,
        "node_id": f"node-{index}",
        "chain_id": "chain-test",
        "catching_up": False,
    }


def test_preflight_runs_only_read_only_checks(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def probe(command: str, *, transport: str, ssh_target: str, timeout_seconds: int):
        calls.append((transport, command))
        return {"status": "PASS", "returncode": 0}

    monkeypatch.setattr(MODULE, "_rpc_status", _rpc_status)
    monkeypatch.setattr(MODULE, "_run_probe", probe)

    report = MODULE.run_preflight(config_path=_config(tmp_path))

    assert report["status"] == "PASS"
    assert report["read_only"] is True
    assert ("ssh", "printf '%s' aidn-g5-preflight") in calls
    assert all(not command.startswith("execute-") for _, command in calls)
    assert all(command != "recover-host" for _, command in calls)


def test_preflight_fails_when_operator_check_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(MODULE, "_rpc_status", _rpc_status)

    def probe(command: str, *, transport: str, ssh_target: str, timeout_seconds: int):
        return {"status": "FAIL" if "abrupt_process_termination" in command else "PASS", "returncode": 1}

    monkeypatch.setattr(MODULE, "_run_probe", probe)

    report = MODULE.run_preflight(config_path=_config(tmp_path))

    assert report["status"] == "FAIL"
    assert report["commands"]["abrupt_process_termination"]["status"] == "FAIL"


def test_preflight_requires_recovery_check(tmp_path: Path) -> None:
    path = _config(tmp_path)
    config = json.loads(path.read_text(encoding="utf-8"))
    del config["commands"]["host_reboot"]["recovery_preflight"]
    path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="recovery_preflight"):
        MODULE.run_preflight(config_path=path)
