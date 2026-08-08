from fastapi.testclient import TestClient

from aidn_hypervisor.domain.models import NodeCapacity
from aidn_hypervisor.main import _is_validator_consensus_write_path, build_app
from aidn_hypervisor.resource_probe import ResourceProbeReport


def test_operator_can_refresh_bounded_host_capacity(monkeypatch) -> None:
    report = ResourceProbeReport(
        capacity=NodeCapacity(cpu_cores=4, ram_mb=8192),
        source="operator-refresh",
        observed_at="2026-08-08T00:00:00+00:00",
    )
    monkeypatch.setattr(
        "aidn_hypervisor.api.refresh_resource_probe_from_environment",
        lambda: report,
    )
    client = TestClient(build_app())

    response = client.post("/operators/resources/probe", json={})

    assert response.status_code == 200
    assert response.json()["resources"]["total"] == {
        "cpu": 4.0,
        "ram_mb": 8192,
        "vram_mb": 0,
    }
    readiness = client.get("/operators/dashboard/readiness").json()
    capacity = next(step for step in readiness["steps"] if step["key"] == "resources")
    assert capacity["status"] == "ready"
    assert capacity["evidence"]["probe"]["source"] == "operator-refresh"


def test_dashboard_exposes_automatic_resource_probe_recovery() -> None:
    response = TestClient(build_app()).get("/operators/dashboard")

    assert response.status_code == 200
    assert "/operators/resources/probe" in response.text
    assert "Run automatic probe" not in response.text
    assert "resource-probe" in response.text
    assert "measures host capacity automatically" in response.text


def test_validator_write_boundary_allows_only_bounded_resource_measurement() -> None:
    assert _is_validator_consensus_write_path("/operators/resources/probe") is True
    assert _is_validator_consensus_write_path("/operators/resources/configure") is False
