import sys
import time
from pathlib import Path

from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, ResourceProfile
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService


def _service(
    tmp_path: Path,
    *,
    runtimes: ProviderProcessManager | None = None,
) -> HypervisorService:
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())
    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8, ram_mb=16_384, vram_mb={"gpu0": 8_192})
        ),
        bundles=[
            BundleConfig(
                bundle_id="bundle-a",
                plugin_id="fake-managed",
                provider_type="fake",
                workload_type="llm_text",
                model_id="model-a",
                launch_mode="managed_process",
                endpoint="http://127.0.0.1:9999",
                device_affinity="cpu",
                resource_profile=ResourceProfile(),
                warm_policy="auto",
            )
        ],
        plugins=plugins,
        runtimes=runtimes or ProviderProcessManager(),
        state_store=FileStateStore(tmp_path / "hypervisor-state.json"),
    )


def test_read_reconciler_promotes_starting_runtime_and_persists_live_health(tmp_path) -> None:
    service = _service(tmp_path)

    runtime = service.start_bundle("bundle-a")
    assert runtime.status == "starting"
    assert runtime.health_status == "unknown"
    assert service.operator_dashboard_fleet()["bundles"][0]["runtime_status"] == "running"

    persisted = service.state_store.load().runtimes[0]
    assert persisted.status == "running"
    assert persisted.health_status == "healthy"


def test_stopped_process_is_not_selected_as_an_active_bundle_runtime(tmp_path) -> None:
    service = _service(tmp_path)
    runtime = service.start_bundle("bundle-a")
    runtime.status = "stopped"

    assert service._runtime_for_bundle("bundle-a") is None
    assert service._bundle_inventory_status(service._get_bundle("bundle-a")) == "stopped"


def test_process_exit_persists_without_a_follow_up_read(tmp_path) -> None:
    manager = ProviderProcessManager(enable_subprocesses=True)
    service = _service(tmp_path, runtimes=manager)

    manager.start_runtime(
        {
            "command": [sys.executable, "-c", "import time; time.sleep(0.25); raise SystemExit(7)"],
            "launch_mode": "managed_process",
            "bundle_id": "bundle-a",
        }
    )
    service._persist_state()

    deadline = time.monotonic() + 2
    while (
        service.state_store.load().runtimes[0].status != "stopped"
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)

    persisted = service.state_store.load().runtimes[0]
    assert persisted.status == "stopped"
    assert persisted.health_status == "unhealthy"
    assert persisted.last_error == "managed runtime exited with code 7"
