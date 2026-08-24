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


def test_validator_write_boundary_allows_local_resident_inference_lifecycle() -> None:
    allowed_paths = (
        "/operators/dashboard/steward/enabled",
        "/operators/dashboard/steward/action-policy",
        "/operators/dashboard/steward/action-execute",
        "/operators/dashboard/steward/inference/prepare",
        "/operators/dashboard/steward/inference/start",
        "/operators/dashboard/steward/inference/stop",
        "/operators/dashboard/steward/inference/model/prepare",
        "/operators/dashboard/steward/inference/model/verify",
        "/operators/dashboard/steward/inference/invoke",
        "/operators/dashboard/steward/chat",
    )
    for path in allowed_paths:
        assert _is_validator_consensus_write_path(path, "POST") is True

    assert _is_validator_consensus_write_path(
        "/operators/dashboard/steward/inference/restart", "POST"
    ) is False
    assert _is_validator_consensus_write_path(allowed_paths[0], "GET") is False


def test_validator_write_boundary_allows_bounded_local_provider_installation() -> None:
    assert _is_validator_consensus_write_path(
        "/operators/dashboard/access/operations/cometbft/reconnect",
        "POST",
    ) is True
    assert (
        _is_validator_consensus_write_path(
            "/operators/provider-plugins/whisper/installation-plan"
        )
        is True
    )
    assert (
        _is_validator_consensus_write_path(
            "/operators/provider-plugins/whisper/installation-diagnostics"
        )
        is True
    )
    assert (
        _is_validator_consensus_write_path(
            "/operators/provider-plugins/whisper/installation-approvals"
        )
        is True
    )
    assert (
        _is_validator_consensus_write_path(
            "/operators/provider-installation-approvals/pia-1/apply"
        )
        is True
    )
    assert (
        _is_validator_consensus_write_path(
            "/operators/provider-installation-jobs/pij-1/rollback"
        )
        is True
    )
    assert (
        _is_validator_consensus_write_path(
            "/operators/provider-instances/pi-1/discover-models"
        )
        is True
    )
    assert (
        _is_validator_consensus_write_path(
            "/operators/provider-instances/pi-1/health"
        )
        is True
    )
    assert (
        _is_validator_consensus_write_path(
            "/operators/model-deployments/md-1/runtime-bindings"
        )
        is True
    )
    assert _is_validator_consensus_write_path("/operators/providers/arbitrary-write") is False


def test_validator_write_boundary_allows_local_endpoint_draft_creation() -> None:
    assert _is_validator_consensus_write_path("/api/v1/endpoints") is True
    assert _is_validator_consensus_write_path("/api/v1/endpoints/ep-1", "PATCH") is True
    assert _is_validator_consensus_write_path("/api/v1/endpoints/ep-1", "DELETE") is False
    assert _is_validator_consensus_write_path(
        "/api/v1/endpoints/ep-1/publish-configuration", "POST"
    ) is True
    assert _is_validator_consensus_write_path(
        "/api/v1/endpoints/ep-1/publish-configuration", "GET"
    ) is False


def test_validator_write_boundary_allows_local_runtime_task_submission() -> None:
    assert _is_validator_consensus_write_path("/tasks") is True
    assert _is_validator_consensus_write_path("/tasks/task-1") is False


def test_validator_write_boundary_allows_consensus_bound_mvp_settlement_paths() -> None:
    for action in ("settlement-preview", "finalize", "force-finalize"):
        assert (
            _is_validator_consensus_write_path(
                f"/api/v1/endpoints/ep-1/mvp-sessions/sess-1/{action}"
            )
            is True
        )


def test_validator_write_boundary_rejects_unknown_mvp_session_actions() -> None:
    assert (
        _is_validator_consensus_write_path(
            "/api/v1/endpoints/ep-1/mvp-sessions/sess-1/arbitrary-action"
        )
        is False
    )
