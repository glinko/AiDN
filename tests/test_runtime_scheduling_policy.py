from datetime import UTC, datetime, timedelta

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.domain.models import NodeCapacity
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.runtime_instance_manager import (
    derive_runtime_state,
    evaluate_runtime_eviction,
    mark_runtime_residency_started,
    minimum_residency_seconds,
)
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService


def _bundle(**overrides) -> BundleConfig:
    values = {
        "bundle_id": "bundle-policy",
        "plugin_id": "fake-managed",
        "provider_type": "fake",
        "workload_type": "llm_text",
        "model_id": "policy-model",
        "launch_mode": "managed_process",
        "device_affinity": "cpu",
        "resource_profile": ResourceProfile(steady_cpu=1.0),
        "warm_policy": "auto",
    }
    values.update(overrides)
    return BundleConfig(**values)


def _runtime(*, metadata: dict[str, str] | None = None) -> RuntimeHandle:
    return RuntimeHandle(
        runtime_id="rt-policy",
        command=["python", "-m", "http.server", "0"],
        status="running",
        bundle_id="bundle-policy",
        lifecycle_state="WARM_IDLE",
        metadata=dict(metadata or {}),
    )


def test_non_preemptible_runtime_requires_local_owner_reclamation() -> None:
    runtime = _runtime()
    bundle = _bundle(preemption_class="NON_PREEMPTIBLE")
    remote = TaskRequest(task_type="llm_text.generate", payload={}, priority=200)

    decision = evaluate_runtime_eviction(runtime, bundle, remote)

    assert decision["eligible"] is False
    assert decision["reason"] == "non_preemptible"
    assert decision["preemption_class"] == "NON_PREEMPTIBLE"

    local = remote.model_copy(update={"constraints": {"owner_scope": "local"}})
    local_decision = evaluate_runtime_eviction(runtime, bundle, local)

    assert local_decision["eligible"] is True
    assert local_decision["reason"] == "local_owner_reclamation"
    assert local_decision["local_owner"] is True


def test_minimum_residency_protects_new_runtime_then_expires() -> None:
    started = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    runtime = _runtime()
    mark_runtime_residency_started(runtime, at=started)
    bundle = _bundle(minimum_residency_seconds=60)
    waiting = TaskRequest(task_type="llm_text.generate", payload={})

    protected = evaluate_runtime_eviction(
        runtime,
        bundle,
        waiting,
        now=started + timedelta(seconds=30),
    )
    assert protected["eligible"] is False
    assert protected["reason"] == "minimum_residency"
    assert protected["residency_age_seconds"] == 30.0

    expired = evaluate_runtime_eviction(
        runtime,
        bundle,
        waiting,
        now=started + timedelta(seconds=61),
    )
    assert expired["eligible"] is True
    assert expired["reason"] == "policy_allows_eviction"


def test_bundle_warm_retention_overrides_global_projection() -> None:
    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    runtime = _runtime(
        metadata={"residency_started_at": "2026-08-22T11:59:00Z"},
    )
    runtime.last_activity_at = "2026-08-22T11:59:00Z"
    bundle = _bundle(warm_retention_seconds=30)

    assert (
        derive_runtime_state(
            runtime,
            now=now,
            warm_retention_seconds_value=bundle.warm_retention_seconds,
        )
        == "WARM_IDLE"
    )


def test_invalid_global_minimum_residency_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("AIDN_RUNTIME_MINIMUM_RESIDENCY_SECONDS", "not-a-number")

    assert minimum_residency_seconds() == 0


def test_started_runtime_persists_bundle_eviction_policy_metadata() -> None:
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=4096)),
        bundles=[
            _bundle(
                preemption_class="CHECKPOINTABLE",
                warm_retention_seconds=45,
                minimum_residency_seconds=12,
            )
        ],
        plugins=plugins,
    )

    task = service.submit(TaskRequest(task_type="llm_text.generate", payload={"prompt": "hi"}))

    assert service.get_task(task.task_id).status == "completed"
    runtime = service.list_runtimes()[0]
    assert runtime.metadata["preemption_class"] == "CHECKPOINTABLE"
    assert runtime.metadata["warm_retention_seconds"] == "45"
    assert runtime.metadata["minimum_residency_seconds"] == "12"
    assert runtime.metadata["residency_started_at"]
