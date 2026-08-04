from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/run-live-fault-recovery-drills.py"
SPEC = importlib.util.spec_from_file_location("live_fault_recovery_drills", TOOL)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _status(endpoint: str, height: int) -> dict[str, object]:
    return {
        "rpc_url": endpoint,
        "height": height,
        "app_hash": "APP",
        "node_id": "NODE",
        "chain_id": "CHAIN",
        "catching_up": False,
    }


def test_host_reboot_recovery_command_runs_before_convergence(monkeypatch) -> None:
    endpoints = [f"http://validator-{index}" for index in range(4)]
    calls: list[tuple[str, str]] = []
    convergence_count = 0

    def converge(*args, **kwargs):
        nonlocal convergence_count
        convergence_count += 1
        height = 10 if convergence_count == 1 else 11
        calls.append(("converge", str(height)))
        return [_status(endpoint, height) for endpoint in endpoints]

    def run_ssh(command: str, **kwargs):
        calls.append(("ssh", command))
        return {"returncode": 0, "stdout": "", "stderr": ""}

    def observe_unreachable(endpoint: str, **kwargs):
        calls.append(("outage", endpoint))
        return True

    monkeypatch.setattr(MODULE, "_converge", converge)
    monkeypatch.setattr(MODULE, "_run_ssh", run_ssh)
    monkeypatch.setattr(MODULE, "_observe_unreachable", observe_unreachable)

    report = MODULE._run_live_action(
        name="host_reboot",
        command="reboot",
        ssh_target="operator@jump",
        endpoints=endpoints,
        target_endpoint=endpoints[0],
        timeout_seconds=30,
        allow_disconnect=True,
        post_recovery_command="start-validator",
    )

    assert report["status"] == "PASS"
    assert calls == [
        ("converge", "10"),
        ("ssh", "reboot"),
        ("outage", endpoints[0]),
        ("ssh", "start-validator"),
        ("converge", "11"),
    ]
    assert report["recovery_command"] == "start-validator"
    assert report["recovery_result"]["returncode"] == 0


def test_stale_command_accepts_pretty_json_report(monkeypatch) -> None:
    expected = {"status": "PASS", "evidence_reference": "sha256:test"}

    class Completed:
        returncode = 0
        stdout = '{\n  "status": "PASS",\n  "evidence_reference": "sha256:test"\n}\n'
        stderr = ""

    monkeypatch.setattr(MODULE.subprocess, "run", lambda *args, **kwargs: Completed())

    assert MODULE._run_stale_command("stale-command") == expected


def test_restart_action_records_outage_seen_during_command(monkeypatch) -> None:
    endpoints = [f"http://validator-{index}" for index in range(4)]
    convergence_count = 0

    def converge(*args, **kwargs):
        nonlocal convergence_count
        convergence_count += 1
        height = 20 if convergence_count == 1 else 21
        return [_status(endpoint, height) for endpoint in endpoints]

    monkeypatch.setattr(MODULE, "_converge", converge)
    monkeypatch.setattr(
        MODULE,
        "_run_ssh_with_outage_observation",
        lambda *args, **kwargs: (
            {"returncode": 0, "stdout": "", "stderr": ""},
            True,
        ),
    )
    monkeypatch.setattr(MODULE, "_observe_unreachable", lambda *args, **kwargs: False)

    report = MODULE._run_live_action(
        name="abrupt_process_termination",
        command="kill-and-recover",
        ssh_target="operator@jump",
        endpoints=endpoints,
        target_endpoint=endpoints[0],
        timeout_seconds=30,
        allow_disconnect=False,
    )

    assert report["command_outage_observed"] is True
    assert report["outage_observed"] is True


def test_ssh_observer_detects_rpc_failure_before_action_finishes(monkeypatch) -> None:
    class Process:
        returncode = 0

        def __init__(self) -> None:
            self.poll_count = 0

        def poll(self):
            self.poll_count += 1
            return None if self.poll_count == 1 else self.returncode

        def communicate(self):
            return "out", "err"

        def kill(self):
            self.returncode = -9

    process = Process()
    monkeypatch.setattr(MODULE.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        MODULE,
        "_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("RPC down")),
    )
    monkeypatch.setattr(MODULE.time, "sleep", lambda seconds: None)

    result, outage_observed = MODULE._run_ssh_with_outage_observation(
        "kill-and-recover",
        ssh_target="operator@jump",
        target_endpoint="http://validator-0",
        timeout_seconds=30,
        allow_disconnect=False,
    )

    assert result["returncode"] == 0
    assert outage_observed is True
