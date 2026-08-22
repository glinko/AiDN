from __future__ import annotations

import time

from aidn_hypervisor.resident_worker import ResidentWorker


class _Agent:
    def __init__(self) -> None:
        self.heartbeats = 0

    def heartbeat(self, **_kwargs):
        self.heartbeats += 1
        return {"enabled": True}


class _Service:
    node_id = "node-test"

    def __init__(self) -> None:
        self.resident_agent = _Agent()
        self.refreshes = 0

    def resident_inference_status(self):
        self.refreshes += 1
        return {"state": "RUNNING"}


def test_worker_tick_refreshes_and_reports_health() -> None:
    service = _Service()
    worker = ResidentWorker(service, enabled=True, interval_seconds=1)

    result = worker.run_once()

    assert result["ok"] is True
    assert service.resident_agent.heartbeats == 1
    assert service.refreshes == 1
    assert worker.status()["inference_state"] == "RUNNING"


def test_worker_start_stop_is_idempotent() -> None:
    worker = ResidentWorker(_Service(), enabled=True, interval_seconds=1)

    worker.start()
    time.sleep(0.02)
    assert worker.status()["running"] is True
    worker.start()
    worker.stop()
    worker.stop()

    assert worker.status()["running"] is False
    assert worker.status()["ticks"] >= 1


def test_disabled_worker_does_not_start() -> None:
    worker = ResidentWorker(_Service(), enabled=False)

    result = worker.start()

    assert result["running"] is False
    assert result["enabled"] is False


def test_worker_failure_is_observable_without_raising() -> None:
    class Broken(_Service):
        def resident_inference_status(self):
            raise RuntimeError("adapter unavailable")

    worker = ResidentWorker(Broken(), enabled=True)

    result = worker.run_once()

    assert result["ok"] is False
    assert "adapter unavailable" in result["error"]
    assert worker.status()["consecutive_failures"] == 1

