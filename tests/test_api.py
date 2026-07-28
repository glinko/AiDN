import base64
import io
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

import dashboard_seed_preview
from aidn_hypervisor.accounting.models import (
    UsageAcknowledgement,
    UsageReport,
    usage_acknowledgement_hash,
    usage_report_hash,
)
from aidn_hypervisor.bundle_registry import FileBundleRegistry
from aidn_hypervisor.dashboard import build_market_payload
from aidn_hypervisor.domain.models import (
    AllocationRequest,
    BundleConfig,
    NodeCapacity,
    ResourceProfile,
    TaskRequest,
)
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.models import CreateEndpointCommand, UpdateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.main import build_app
from aidn_hypervisor.model_store import FileModelStore
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager, RuntimeHandle
from aidn_hypervisor.providers.executor import (
    ControlledFilesystemProviderInstallationExecutor,
)
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.registry_models import RegistryDiscoveryQuery, RegistryNodeAdvertisement
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.remote_endpoints.service import RemoteEndpointService
from aidn_hypervisor.remote_endpoints.store import RemoteEndpointStore
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.sessions.models import ProxySessionBinding
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore
from aidn_hypervisor.validation.custody_store import ValidationReportCustodyStore
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore
from aidn_hypervisor.wallet_identity import (
    wallet_identity_quorum_approval_payload,
    wallet_identity_quorum_proposal_payload,
    wallet_identity_registration_payload,
)


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        for relative_path, content in entries.items():
            archive.writestr(relative_path, content)
    return buffer.getvalue()


def _bundle(
    bundle_id: str,
    workload_type: str,
    *,
    resource_profile: ResourceProfile | None = None,
    priority_class: int = 50,
    enabled: bool = True,
    endpoint: str | None = None,
) -> BundleConfig:
    return BundleConfig(
        bundle_id=bundle_id,
        plugin_id="fake-managed",
        provider_type="fake",
        workload_type=workload_type,
        model_id=f"{bundle_id}-model",
        launch_mode="managed_process",
        endpoint=endpoint,
        device_affinity="cpu",
        resource_profile=resource_profile or ResourceProfile(),
        warm_policy="auto",
        priority_class=priority_class,
        enabled=enabled,
    )


def _service(
    *,
    with_runtime: bool = True,
    use_process_manager: bool = False,
    capacity: NodeCapacity | None = None,
    reserve_runtime: bool = True,
    whisper_profile: ResourceProfile | None = None,
    bundle_registry=None,
    whisper_endpoint: str | None = None,
    model_store=None,
) -> HypervisorService:
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())

    resources = ResourceOrchestrator(
        capacity
        or NodeCapacity(
            cpu_cores=8.0,
            ram_mb=16384,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 8192},
        )
    )
    if reserve_runtime:
        resources.reserve("runtime-whisper-a", cpu=1.5, ram_mb=2048, vram_mb=1024)

    runtimes = (
        ProviderProcessManager()
        if use_process_manager
        else [
            RuntimeHandle(
                runtime_id="rt-1",
                bundle_id="whisper-a",
                command=["python", "-m", "http.server", "0"],
                status="running",
                health_status="healthy",
            )
        ]
        if with_runtime
        else []
    )

    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=resources,
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=whisper_profile,
                priority_class=80,
                endpoint=whisper_endpoint,
            ),
            _bundle("text-a", "llm_text", priority_class=60),
            _bundle("disabled-text", "llm_text", enabled=False),
        ],
        plugins=plugins,
        runtimes=runtimes,
        bundle_registry=bundle_registry,
        model_store=model_store,
    )


def _operator_registry_identity(node_id: str) -> dict:
    private_key = Ed25519PrivateKey.generate()
    public_key = f"ed25519:{private_key.public_key().public_bytes_raw().hex()}"
    wallet_id = f"{node_id}-operator"
    owner_wallet_id = f"wallet-owner-{node_id}"
    return {
        "node_id": node_id,
        "wallet_id": wallet_id,
        "owner_wallet_id": owner_wallet_id,
        "private_key": private_key,
        "public_key": public_key,
        "object": {
            "object_id": f"sha256:wallet:{wallet_id}:{public_key[-8:]}",
            "object_type": "wallet_identity",
            "object_version": "wallet-identity.v1",
            "namespace": "identity",
            "payload_hash": f"sha256:payload:{wallet_id}:{public_key[-8:]}",
            "payload_encoding": "canonical_json",
            "source_reference": wallet_id,
            "payload": {
                "wallet_id": wallet_id,
                "public_key": public_key,
                "registration_nonce": f"{wallet_id}-nonce",
            },
        },
        "owner_wallet_object": {
            "object_id": f"sha256:wallet:{owner_wallet_id}:{public_key[-8:]}",
            "object_type": "wallet_identity",
            "object_version": "wallet-identity.v1",
            "namespace": "identity",
            "payload_hash": f"sha256:payload:{owner_wallet_id}:{public_key[-8:]}",
            "payload_encoding": "canonical_json",
            "source_reference": owner_wallet_id,
            "payload": {
                "wallet_id": owner_wallet_id,
                "public_key": public_key,
                "registration_nonce": f"{owner_wallet_id}-nonce",
            },
        },
    }


def _registry_node_payload(
    node_id: str,
    *,
    owner_wallet_id: str | None = None,
    heartbeat_at: str = "2026-06-19T18:30:00+00:00",
    heartbeat_ttl_seconds: int = 30,
) -> dict:
    return {
        "node_id": node_id,
        "operator_id": f"{node_id}-operator",
        "owner_wallet_id": owner_wallet_id,
        "registry_version": "m2.v1",
        "base_url": f"https://{node_id}.example",
        "heartbeat_at": heartbeat_at,
        "heartbeat_ttl_seconds": heartbeat_ttl_seconds,
        "status": "ready",
        "resources": {
            "total": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 8192},
            "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
            "free": {"cpu": 6.0, "ram_mb": 12000, "vram_mb": 6144},
        },
        "providers": ["llama.cpp"],
        "can_host_custom_model": True,
        "pricing": {
            "unit": "q_per_1kk_tokens",
            "input": 12,
            "output": 18,
            "fixed_request": None,
        },
        "rating": {
            "score": 0.91,
            "tier": "A",
            "updated_at": "2026-06-19T18:25:00+00:00",
        },
        "bundles": [
            {
                "bundle_id": "phi4-local",
                "plugin_id": "llama.cpp",
                "workload_type": "llm_text",
                "provider_type": "llama.cpp",
                "model_id": "phi-4-mini.gguf",
                "endpoint": f"https://{node_id}.example/runtimes/phi4-local",
                "enabled": True,
                "status": "ready",
                "launch_mode": "managed_process",
                "device_affinity": "cpu",
                "max_parallel_requests": 1,
                "supports_allocation": True,
                "supports_queue": True,
            }
        ],
        "canonical_services": [],
        "canonical_capability_runtimes": [],
        "canonical_compute_compatibility": [],
        "canonical_advertisements": [],
    }


def _sign_registry_quorum_proposal(
    identity: dict,
    *,
    wallet_id: str,
    chosen_object_id: str,
    chosen_payload_hash: str,
    eligible_voter_node_ids: list[str],
    quorum_threshold: int,
    operator_note: str | None,
) -> str:
    signature = (
        identity["private_key"]
        .sign(
            wallet_identity_quorum_proposal_payload(
                wallet_id=wallet_id,
                chosen_object_id=chosen_object_id,
                chosen_payload_hash=chosen_payload_hash,
                proposer_node_id=identity["node_id"],
                eligible_voter_node_ids=eligible_voter_node_ids,
                quorum_threshold=quorum_threshold,
                operator_note=operator_note,
            )
        )
        .hex()
    )
    return f"ed25519:{signature}"


def _sign_registry_quorum_approval(
    identity: dict,
    *,
    resolution_id: str,
    approval_note: str | None,
) -> str:
    signature = (
        identity["private_key"]
        .sign(
            wallet_identity_quorum_approval_payload(
                resolution_id=resolution_id,
                approver_node_id=identity["node_id"],
                approval_note=approval_note,
            )
        )
        .hex()
    )
    return f"ed25519:{signature}"


class _StubRemoteSessionCloseTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
        self.calls.append((method, url, payload))
        if method == "POST" and url.endswith("/api/v1/sessions/remote-session-1/close"):
            return {"session": {"session_id": "remote-session-1", "status": "closed"}}
        raise AssertionError(f"unexpected proxy request: {method} {url}")


class CooldownApiPlugin(FakeManagedPlugin):
    plugin_id = "fake-cooldown-api"

    def __init__(self) -> None:
        self.invoke_attempts = 0

    def retry_policy(self) -> dict:
        return {
            "invoke": {
                "max_attempts": 3,
                "backoff_seconds": 0.0,
                "retry_exceptions": (RuntimeError,),
            }
        }

    def circuit_breaker_policy(self) -> dict:
        return {"failure_threshold": 1, "cooldown_seconds": 60.0}

    def invoke(self, task, runtime_handle) -> dict:
        self.invoke_attempts += 1
        raise RuntimeError("connection refused")


class BadInstallationPlanPlugin(FakeManagedPlugin):
    plugin_id = "bad-plan"

    def build_installation_plan(self, configuration: dict) -> dict:
        plan = super().build_installation_plan(configuration)
        plan["plugin_id"] = self.plugin_id
        plan["unsupported_actions"] = ["RUN_SHELL_SCRIPT"]
        return plan


class AttachOnlyInstallationPlanPlugin(FakeManagedPlugin):
    plugin_id = "attach-only"

    def describe(self) -> dict:
        description = super().describe()
        description["plugin_id"] = self.plugin_id
        description["plugin_capability_flags"] = ["CAN_ATTACH_EXISTING"]
        return description


class LocalImportApiPlugin(FakeManagedPlugin):
    plugin_id = "controlled-fs-import-api"

    def describe(self) -> dict:
        description = super().describe()
        description["plugin_id"] = self.plugin_id
        description["required_permissions"] = [
            {
                "permission_id": "network.private",
                "label": "Private network",
                "risk_level": "low",
                "reason": "Connect to a local fake provider endpoint",
            },
            {
                "permission_id": "filesystem.controlled_path",
                "label": "Controlled filesystem path",
                "risk_level": "medium",
                "reason": "Persist managed installation state inside a controlled path",
            },
        ]
        description["sandbox_policy"] = {
            "execution_mode": "SANDBOX_REQUIRED",
            "filesystem_scope": "CONTROLLED_PATHS",
            "network_scope": "DECLARED_EGRESS",
            "secret_scope": "DECLARED_HANDLES_ONLY",
            "notes": "Managed install may write state inside one controlled host path.",
        }
        return description

    def build_installation_plan(self, configuration: dict) -> dict:
        plan = super().build_installation_plan(configuration)
        plan["plugin_id"] = self.plugin_id
        plan["required_permissions"] = self.plugin_manifest()["required_permissions"]
        plan["volumes"] = [
            {
                "name": "provider-cache",
                "mount_path": "/var/lib/provider-cache",
            }
        ]
        plan["model_downloads"] = [
            {
                "model": "fake-model-imported",
                "source": "local-import://models/fake-model.gguf",
                "destination": "provider-cache/fake-model.gguf",
            }
        ]
        return plan


def test_submit_task_endpoint_returns_queued_task_and_selected_bundle() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/tasks",
        json={"task_type": "audio.transcribe", "payload": {"audio_ref": "clip.wav"}},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["task_type"] == "audio.transcribe"
    assert response.json()["priority"] == 50
    assert response.json()["bundle_id"] == "whisper-a"
    assert response.json()["task_id"]


def test_submit_task_endpoint_uses_allocation_bundle_when_allocation_id_is_provided() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, gpu_devices=["gpu0"], vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("preferred-text", "llm_text", priority_class=100),
            _bundle("leased-text", "llm_text", priority_class=10, endpoint="http://127.0.0.1:8080"),
        ],
        plugins=PluginRegistry(),
        runtimes=ProviderProcessManager(),
    )
    service.plugins.register(FakeManagedPlugin())
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="leased-text",
        )
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/tasks",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "hello"},
            "constraints": {"allocation_id": allocation["allocation_id"]},
        },
    )

    assert response.status_code == 202
    assert response.json()["bundle_id"] == "leased-text"


def test_submit_task_endpoint_executes_via_proxy_endpoint_when_endpoint_id_is_provided() -> None:
    class StubRemoteHypervisorTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict | None]] = []

        def request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
            self.calls.append((method, url, payload))
            if method == "POST" and url == "http://remote-hv/tasks":
                return {
                    "task_id": "remote-task-1",
                    "status": "queued",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                }
            if method == "GET" and url == "http://remote-hv/tasks/remote-task-1":
                return {
                    "task_id": "remote-task-1",
                    "status": "completed",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                    "result": {
                        "ok": True,
                        "task_type": "llm_text.generate",
                        "output_text": "hello from remote",
                    },
                }
            raise AssertionError(f"unexpected proxy request: {method} {url}")

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, gpu_devices=["gpu0"], vram_mb={"gpu0": 4096})
        ),
        bundles=[_bundle("text-a", "llm_text", priority_class=100)],
        plugins=PluginRegistry(),
        runtimes=ProviderProcessManager(),
    )
    service.plugins.register(FakeManagedPlugin())
    endpoint_service = EndpointService(EndpointStore())
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-remote",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="http://remote-hv",
        operator_id="operator-remote",
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-06-30T00:00:00+00:00"},
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Proxy Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    service.remote_transport = StubRemoteHypervisorTransport()
    service.proxy_poll_attempts = 1
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.post(
        "/tasks",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "hello"},
            "constraints": {"endpoint_id": created.endpoint.endpoint_id},
        },
    )

    assert response.status_code == 202
    assert response.json()["bundle_id"] == "text-a"
    detail = client.get(response.json()["task_id"] and f"/tasks/{response.json()['task_id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"
    assert detail.json()["result"]["output_text"] == "hello from remote"
    assert detail.json()["result"]["proxy"]["remote_endpoint_id"] == "ep-remote"


def test_submit_task_endpoint_rejects_paid_endpoint_request_without_session() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="whisper-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.post(
        "/tasks",
        json={
            "task_type": "audio.transcribe",
            "payload": {"audio_ref": "clip.wav"},
            "constraints": {"endpoint_id": created.endpoint.endpoint_id},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (f"Active session required for paid endpoint: {created.endpoint.endpoint_id}")


def test_submit_task_endpoint_updates_session_activity_for_paid_endpoint_session() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="whisper-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    session = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=10.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    ).session
    session_service.store.save_session(
        session.model_copy(
            update={
                "last_activity_at": "2026-06-30T00:00:00+00:00",
                "idle_deadline_at": "2026-06-30T00:10:00+00:00",
            }
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.post(
        "/tasks",
        json={
            "task_type": "audio.transcribe",
            "payload": {"audio_ref": "clip.wav"},
            "constraints": {
                "endpoint_id": created.endpoint.endpoint_id,
                "session_id": session.session_id,
            },
        },
    )

    refreshed = session_service.get_session(session.session_id).session

    assert response.status_code == 202
    assert refreshed.last_activity_at != "2026-06-30T00:00:00+00:00"
    assert refreshed.idle_deadline_at != "2026-06-30T00:10:00+00:00"


def test_submit_task_endpoint_rejects_when_remaining_deposit_cannot_cover_maximum_request_charge() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="whisper-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
            pricing={
                "billing_unit": "request",
                "fixed_price": 4.0,
            },
        )
    )
    session = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
        accounting_contract={
            "contract_version": "acct-v1",
            "pricing_version": "pricing-v1",
            "checkpoint_policy": "per_request",
            "maximum_request_charge": 15.0,
            "billable_units": [],
        },
    ).session
    session_service.record_usage_charge(session.session_id, amount_q=12.0)
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.post(
        "/tasks",
        json={
            "task_type": "audio.transcribe",
            "payload": {"audio_ref": "clip.wav"},
            "constraints": {
                "endpoint_id": created.endpoint.endpoint_id,
                "session_id": session.session_id,
            },
        },
    )

    assert response.status_code == 409
    assert "maximum request charge" in response.json()["detail"]


def test_get_task_endpoint_exposes_proxy_trace_for_proxy_execution() -> None:
    class StubRemoteHypervisorTransport:
        def request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
            if method == "POST" and url == "http://remote-hv/tasks":
                return {
                    "task_id": "remote-task-1",
                    "status": "queued",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                }
            if method == "GET" and url == "http://remote-hv/tasks/remote-task-1":
                return {
                    "task_id": "remote-task-1",
                    "status": "completed",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                    "result": {
                        "ok": True,
                        "output_text": "hello from remote",
                    },
                }
            raise AssertionError(f"unexpected proxy request: {method} {url}")

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, gpu_devices=["gpu0"], vram_mb={"gpu0": 4096})
        ),
        bundles=[_bundle("text-a", "llm_text", priority_class=100)],
        plugins=PluginRegistry(),
        runtimes=ProviderProcessManager(),
    )
    service.plugins.register(FakeManagedPlugin())
    endpoint_service = EndpointService(EndpointStore())
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-remote",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="http://remote-hv",
        operator_id="operator-remote",
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-06-30T00:00:00+00:00"},
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Proxy Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    service.remote_transport = StubRemoteHypervisorTransport()
    service.proxy_poll_attempts = 1
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.post(
        "/tasks",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "hello"},
            "constraints": {"endpoint_id": created.endpoint.endpoint_id},
        },
    )

    assert response.status_code == 202
    detail = client.get(f"/tasks/{response.json()['task_id']}")

    assert detail.status_code == 200
    assert detail.json()["proxy_trace"]["strategy"] == "proxy"
    assert detail.json()["proxy_trace"]["status"] == "completed"
    assert detail.json()["proxy_trace"]["remote_task_id"] == "remote-task-1"
    assert detail.json()["proxy_trace"]["remote_endpoint_id"] == "ep-remote"
    assert detail.json()["proxy_trace"]["remote_node_id"] == "node-remote"
    assert detail.json()["proxy_trace"]["source_base_url"] == "http://remote-hv"
    assert detail.json()["proxy_trace"]["dispatched_at"]


def test_get_task_endpoint_exposes_proxy_session_for_proxy_paid_execution() -> None:
    class StubPaidRemoteHypervisorTransport:
        def request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
            if method == "POST" and url == "http://remote-hv/api/v1/endpoints/ep-remote/sessions":
                return {
                    "session": {
                        "session_id": "remote-session-1",
                        "opened_at": "2026-07-02T00:00:00+00:00",
                    }
                }
            if method == "POST" and url == "http://remote-hv/tasks":
                return {
                    "task_id": "remote-task-1",
                    "status": "queued",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                }
            if method == "GET" and url == "http://remote-hv/tasks/remote-task-1":
                return {
                    "task_id": "remote-task-1",
                    "status": "completed",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                    "result": {
                        "ok": True,
                        "output_text": "hello from remote",
                    },
                }
            raise AssertionError(f"unexpected proxy request: {method} {url}")

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, gpu_devices=["gpu0"], vram_mb={"gpu0": 4096})
        ),
        bundles=[_bundle("text-a", "llm_text", priority_class=100)],
        plugins=PluginRegistry(),
        runtimes=ProviderProcessManager(),
    )
    service.plugins.register(FakeManagedPlugin())
    endpoint_service = EndpointService(EndpointStore())
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    session_service = SessionService(SessionStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-remote",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="http://remote-hv",
        operator_id="operator-remote",
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-06-30T00:00:00+00:00"},
        session_policy={"minimum_deposit": 10.0},
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Proxy Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    )
    service.remote_transport = StubPaidRemoteHypervisorTransport()
    service.proxy_poll_attempts = 1
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
            session_service=session_service,
        )
    )

    response = client.post(
        "/tasks",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "hello"},
            "constraints": {
                "endpoint_id": created.endpoint.endpoint_id,
                "session_id": opened.session.session_id,
            },
        },
    )

    assert response.status_code == 202
    detail = client.get(f"/tasks/{response.json()['task_id']}")

    assert detail.status_code == 200
    assert detail.json()["proxy_session"]["remote_session_id"] == "remote-session-1"
    assert detail.json()["proxy_session"]["status"] == "active"


def test_submit_task_endpoint_rejects_released_allocation_id() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, gpu_devices=["gpu0"], vram_mb={"gpu0": 4096})
        ),
        bundles=[_bundle("leased-text", "llm_text", endpoint="http://127.0.0.1:8080")],
        plugins=PluginRegistry(),
        runtimes=ProviderProcessManager(),
    )
    service.plugins.register(FakeManagedPlugin())
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="leased-text",
        )
    )
    service.release_allocation(allocation["allocation_id"])
    client = TestClient(build_app(service=service))

    response = client.post(
        "/tasks",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "hello"},
            "constraints": {"allocation_id": allocation["allocation_id"]},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == f"Allocation is not active: {allocation['allocation_id']}"


def test_queue_endpoint_returns_enqueued_tasks_with_selected_bundles() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=1.0,
            ram_mb=1024,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 512},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=1.0,
            steady_cpu=0.5,
            per_request_cpu=0.5,
        ),
    )
    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))
    client = TestClient(build_app(service=service))

    response = client.get("/queue")

    assert response.status_code == 200
    assert response.json() == [
        {
            "task_id": task.task_id,
            "status": "queued",
            "priority": 50,
            "task_type": "audio.transcribe",
            "bundle_id": "whisper-a",
        }
    ]


def test_task_detail_endpoint_returns_submitted_task_status() -> None:
    service = _service()
    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))
    client = TestClient(build_app(service=service))
    history = [event.model_dump(mode="json") for event in service.task_history(task.task_id)]

    response = client.get(f"/tasks/{task.task_id}")

    assert response.status_code == 200
    assert response.json() == {
        "task_id": task.task_id,
        "status": "completed",
        "priority": 50,
        "task_type": "audio.transcribe",
        "bundle_id": "whisper-a",
        "result": {"ok": True, "task_type": "audio.transcribe"},
        "recovery_reason": None,
        "history": [
            {
                "timestamp": history[0]["timestamp"],
                "event_type": "task.submitted",
                "message": "task accepted into queue",
                "task_id": task.task_id,
                "bundle_id": "whisper-a",
                "runtime_id": None,
                "details": {
                    "task_type": "audio.transcribe",
                    "mode": "auto",
                },
            },
            {
                "timestamp": history[1]["timestamp"],
                "event_type": "admission.selected",
                "message": "task selected for admission attempt",
                "task_id": task.task_id,
                "bundle_id": "whisper-a",
                "runtime_id": None,
                "details": {
                    "base_priority": 50,
                    "aging_bonus": 0,
                    "effective_priority": 50,
                    "fair_share_round": 0,
                    "admission_rank": 1,
                    "selection_reason": "only_remaining_bundle",
                },
            },
            {
                "timestamp": history[2]["timestamp"],
                "event_type": "task.completed",
                "message": "task completed successfully",
                "task_id": task.task_id,
                "bundle_id": "whisper-a",
                "runtime_id": "rt-1",
                "details": {},
            },
        ],
    }


def test_cancel_task_endpoint_marks_queued_task_cancelled() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=1.0,
            ram_mb=1024,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 512},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=1.0,
            steady_cpu=0.5,
            per_request_cpu=0.5,
        ),
    )
    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))
    client = TestClient(build_app(service=service))

    response = client.post(f"/tasks/{task.task_id}/cancel")

    assert response.status_code == 200
    assert response.json() == {
        "task_id": task.task_id,
        "status": "cancelled",
        "priority": 50,
        "task_type": "audio.transcribe",
        "bundle_id": "whisper-a",
        "result": None,
    }

    detail_response = client.get(f"/tasks/{task.task_id}")

    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "cancelled"


def test_queue_endpoint_omits_cancelled_tasks() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=1.0,
            ram_mb=1024,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 512},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=1.0,
            steady_cpu=0.5,
            per_request_cpu=0.5,
        ),
    )
    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))
    client = TestClient(build_app(service=service))

    client.post(f"/tasks/{task.task_id}/cancel")
    response = client.get("/queue")

    assert response.status_code == 200
    assert response.json() == []


def test_cancel_task_endpoint_rejects_non_cancellable_tasks() -> None:
    service = _service()
    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))
    service.queue.transition_status(task.task_id, "running")
    client = TestClient(build_app(service=service))

    response = client.post(f"/tasks/{task.task_id}/cancel")

    assert response.status_code == 409
    assert "not cancellable" in response.json()["detail"]


def test_bundles_endpoint_returns_bundle_definitions_and_status() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/bundles")

    assert response.status_code == 200
    assert response.json() == [
        {
            "bundle_id": "whisper-a",
            "plugin_id": "fake-managed",
            "provider_type": "fake",
            "workload_type": "speech_to_text",
            "model_id": "whisper-a-model",
            "launch_mode": "managed_process",
            "enabled": True,
            "priority_class": 80,
            "status": "running",
        },
        {
            "bundle_id": "text-a",
            "plugin_id": "fake-managed",
            "provider_type": "fake",
            "workload_type": "llm_text",
            "model_id": "text-a-model",
            "launch_mode": "managed_process",
            "enabled": True,
            "priority_class": 60,
            "status": "stopped",
        },
        {
            "bundle_id": "disabled-text",
            "plugin_id": "fake-managed",
            "provider_type": "fake",
            "workload_type": "llm_text",
            "model_id": "disabled-text-model",
            "launch_mode": "managed_process",
            "enabled": False,
            "priority_class": 50,
            "status": "disabled",
        },
    ]


def test_start_bundle_endpoint_launches_runtime_and_updates_bundle_status() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    client = TestClient(build_app(service=service))

    response = client.post("/bundles/whisper-a/start")

    assert response.status_code == 200
    assert response.json() == {
        "runtime_id": "rt-1",
        "bundle_id": "whisper-a",
        "command": ["python", "-m", "http.server", "0"],
        "status": "starting",
    }

    bundles_response = client.get("/bundles")

    assert bundles_response.status_code == 200
    assert bundles_response.json()[0]["status"] == "starting"


def test_start_bundle_endpoint_rejects_disabled_bundles() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    client = TestClient(build_app(service=service))

    response = client.post("/bundles/disabled-text/start")

    assert response.status_code == 409
    assert "disabled" in response.json()["detail"]


def test_stop_bundle_endpoint_removes_active_runtime() -> None:
    service = _service(with_runtime=True)
    client = TestClient(build_app(service=service))

    response = client.post("/bundles/whisper-a/stop")

    assert response.status_code == 200
    assert response.json() == {
        "bundle_id": "whisper-a",
        "status": "stopped",
    }

    runtimes_response = client.get("/runtimes")
    bundles_response = client.get("/bundles")

    assert runtimes_response.status_code == 200
    assert runtimes_response.json() == []
    assert bundles_response.status_code == 200
    assert bundles_response.json()[0]["status"] == "stopped"


def test_runtimes_endpoint_returns_runtime_handles() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/runtimes")

    assert response.status_code == 200
    assert response.json() == [
        {
            "runtime_id": "rt-1",
            "bundle_id": "whisper-a",
            "command": ["python", "-m", "http.server", "0"],
            "status": "running",
            "health_status": "healthy",
            "active_task_count": 0,
            "failure_streak": 0,
            "cooldown_until": None,
            "cooldown_reason": None,
            "drain_mode": False,
            "drain_reason": None,
        }
    ]


def test_runtime_detail_endpoint_returns_runtime_with_history() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    runtime = service.start_bundle("whisper-a")
    client = TestClient(build_app(service=service))

    response = client.get(f"/runtimes/{runtime.runtime_id}")

    assert response.status_code == 200
    assert response.json() == {
        "runtime_id": "rt-1",
        "bundle_id": "whisper-a",
        "command": ["python", "-m", "http.server", "0"],
        "status": "starting",
        "health_status": "unknown",
        "active_task_count": 0,
        "failure_streak": 0,
        "cooldown_until": None,
        "cooldown_reason": None,
        "drain_mode": False,
        "drain_reason": None,
        "history": [
            {
                "timestamp": service.event_journal(limit=1)[0].timestamp,
                "event_type": "runtime.started",
                "message": "runtime started",
                "task_id": None,
                "bundle_id": "whisper-a",
                "runtime_id": "rt-1",
                "details": {},
            }
        ],
    }


def test_runtime_detail_endpoint_returns_404_for_unknown_runtime() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/runtimes/rt-missing")

    assert response.status_code == 404
    assert "Unknown runtime" in response.json()["detail"]


def test_resources_endpoint_returns_total_reserved_and_free_capacity() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/resources")

    assert response.status_code == 200
    assert response.json() == {
        "total": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 8192},
        "reserved": {"cpu": 1.5, "ram_mb": 2048, "vram_mb": 1024},
        "free": {"cpu": 6.5, "ram_mb": 14336, "vram_mb": 7168},
    }


def test_plugins_endpoint_returns_installed_plugin_descriptions() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/plugins")

    assert response.status_code == 200
    plugins = response.json()
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin["plugin_id"] == "fake-managed"
    assert plugin["plugin_version"] == "0.1.0"
    assert plugin["display_name"] == "Fake Managed Provider"
    assert plugin["publisher"] == "AiDN Test"
    assert plugin["package_digest"] == "sha256:2e348ef1dca5559c3e648df90ce6774de4fdf400887945645f6f32d4ecc1fa8b"
    assert plugin["provider_type"] == "fake"
    assert plugin["provider_families"] == ["fake"]
    assert plugin["plugin_capability_flags"] == [
        "CAN_ATTACH_EXISTING",
        "CAN_INSTALL_PROVIDER",
        "CAN_DISCOVER_MODELS",
    ]
    assert plugin["required_permissions"][0]["permission_id"] == "network.private"
    assert plugin["secret_requirements"][0]["secret_type"] == "API_KEY"
    assert plugin["trust_status"] == "CONFORMANCE_TESTED"
    assert plugin["sandbox_policy"]["execution_mode"] == "RECORDED_ONLY"
    assert plugin["installation_recipes"][0]["recipe_id"] == "fake-managed-local"
    assert plugin["supported_aidn_capabilities"] == ["llm.chat"]
    assert plugin["workload_types"] == ["llm_text", "speech_to_text"]
    assert plugin["usage_contract"] == {
        "supports_exact": False,
        "supports_estimated": False,
        "default_measurement_source": None,
        "fallback_measurement_source": None,
        "fallback_policy": "none",
        "missing_usage_behavior": "skip",
    }


def test_queue_diagnostics_endpoint_reports_blocked_reason() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=1.0,
            ram_mb=1024,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 512},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=1.0,
            steady_cpu=0.5,
            per_request_cpu=0.5,
        ),
    )
    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))
    client = TestClient(build_app(service=service))

    response = client.get("/diagnostics/queue")

    assert response.status_code == 200
    assert response.json() == {
        "summary": {"queued": 1, "active": 0, "completed": 0, "failed": 0},
        "items": [
            {
                "task_id": task.task_id,
                "bundle_id": "whisper-a",
                "reason": "insufficient_resources",
            }
        ],
    }


def test_create_allocation_endpoint_returns_agent_lease() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        whisper_endpoint="http://127.0.0.1:9000",
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/allocations",
        json={"workload_type": "speech_to_text", "owner_id": "agent-a"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "allocation_id": response.json()["allocation_id"],
        "owner_id": "agent-a",
        "workload_type": "speech_to_text",
        "bundle_id": "whisper-a",
        "runtime_id": "rt-1",
        "endpoint": "http://127.0.0.1:9000",
        "status": "active",
    }


def test_release_allocation_endpoint_marks_lease_released() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        whisper_endpoint="http://127.0.0.1:9000",
    )
    allocation = service.create_allocation(AllocationRequest(workload_type="speech_to_text", owner_id="agent-a"))
    client = TestClient(build_app(service=service))

    response = client.delete(f"/allocations/{allocation['allocation_id']}")

    assert response.status_code == 200
    assert response.json() == {
        "allocation_id": allocation["allocation_id"],
        "owner_id": "agent-a",
        "workload_type": "speech_to_text",
        "bundle_id": "whisper-a",
        "runtime_id": "rt-1",
        "endpoint": "http://127.0.0.1:9000",
        "status": "released",
    }


def test_capabilities_endpoint_lists_enabled_bundle_inventory() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    client = TestClient(build_app(service=service))

    response = client.get("/capabilities")

    assert response.status_code == 200
    assert response.json() == [
        {
            "bundle_id": "whisper-a",
            "workload_type": "speech_to_text",
            "enabled": True,
            "status": "running",
            "endpoint": "http://127.0.0.1:9000",
        },
        {
            "bundle_id": "text-a",
            "workload_type": "llm_text",
            "enabled": True,
            "status": "stopped",
            "endpoint": None,
        },
        {
            "bundle_id": "disabled-text",
            "workload_type": "llm_text",
            "enabled": False,
            "status": "disabled",
            "endpoint": None,
        },
    ]


def test_operator_registry_advertisement_endpoint_returns_current_node_payload() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    service.node_id = "node-local"
    service.operator_id = "operator-a"
    service.base_url = "https://node.example"
    service.can_host_custom_model = False
    service.pricing = {
        "unit": "q_per_1kk_tokens",
        "input": 10,
        "output": 14,
        "fixed_request": None,
    }
    service.rating = {
        "score": 0.88,
        "tier": "B",
        "updated_at": "2026-06-19T18:20:00Z",
    }
    client = TestClient(build_app(service=service))

    response = client.get("/operators/registry/advertisement")

    assert response.status_code == 200
    assert response.json()["node_id"] == "node-local"
    assert response.json()["bundles"][0]["bundle_id"] == "whisper-a"


def test_operator_registry_objects_endpoint_returns_local_registry_objects() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    client = TestClient(build_app(service=service))

    response = client.get("/operators/registry/objects")

    assert response.status_code == 200
    object_types = {item["object_type"] for item in response.json()["objects"]}
    assert "capability_definition" in object_types


def test_operator_registry_objects_endpoint_lists_wallet_identity_objects() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    private_key = Ed25519PrivateKey.generate()
    public_key = f"ed25519:{private_key.public_key().public_bytes_raw().hex()}"
    registration_nonce = "wallet-registry-object"
    signature = private_key.sign(
        wallet_identity_registration_payload(
            wallet_id="wallet-consumer",
            public_key=public_key,
            registration_nonce=registration_nonce,
        )
    ).hex()
    service.register_wallet_identity(
        wallet_id="wallet-consumer",
        public_key=public_key,
        registration_nonce=registration_nonce,
        signature=f"ed25519:{signature}",
    )
    client = TestClient(build_app(service=service))

    response = client.get("/operators/registry/objects?include_payload=true")

    assert response.status_code == 200
    wallet_identity = next(item for item in response.json()["objects"] if item["object_type"] == "wallet_identity")
    assert wallet_identity["namespace"] == "identity"
    assert wallet_identity["payload"] == {
        "wallet_id": "wallet-consumer",
        "public_key": public_key,
        "registration_nonce": registration_nonce,
    }


def test_wallet_identity_endpoint_resolves_registry_backed_identity() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    registry = RegistryService()
    private_key = Ed25519PrivateKey.generate()
    public_key = f"ed25519:{private_key.public_key().public_bytes_raw().hex()}"
    registration_nonce = "wallet-registry-view"
    signature = private_key.sign(
        wallet_identity_registration_payload(
            wallet_id="wallet-consumer",
            public_key=public_key,
            registration_nonce=registration_nonce,
        )
    ).hex()
    service.register_wallet_identity(
        wallet_id="wallet-consumer",
        public_key=public_key,
        registration_nonce=registration_nonce,
        signature=f"ed25519:{signature}",
    )
    registry.upsert_node(RegistryNodeAdvertisement(**service.node_advertisement()))
    service._wallet_identities.clear()
    client = TestClient(build_app(service=service, registry_service=registry))

    response = client.get("/wallets/wallet-consumer/identity")

    assert response.status_code == 200
    assert response.json()["wallet_id"] == "wallet-consumer"
    assert response.json()["public_key"] == public_key
    assert response.json()["identity_source"] == "registry_object"


def test_operator_registry_conflicts_endpoint_lists_wallet_identity_conflicts() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    registry = RegistryService()
    client = TestClient(build_app(service=service, registry_service=registry))

    node_a = RegistryNodeAdvertisement(
        node_id="node-a",
        operator_id="operator-a",
        base_url="https://node-a.example",
        heartbeat_at="2026-07-05T14:00:00+00:00",
        heartbeat_ttl_seconds=30,
        resources={
            "total": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 8192},
            "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
            "free": {"cpu": 6.0, "ram_mb": 12000, "vram_mb": 6144},
        },
        providers=["llama.cpp"],
        can_host_custom_model=True,
        pricing={
            "unit": "q_per_1kk_tokens",
            "input": 12,
            "output": 18,
            "fixed_request": None,
        },
        rating={
            "score": 0.91,
            "tier": "A",
            "updated_at": "2026-07-05T13:55:00+00:00",
        },
        bundles=[],
        canonical_registry_objects=[
            {
                "object_id": "sha256:wallet:consumer:a",
                "object_type": "wallet_identity",
                "object_version": "wallet-identity.v1",
                "namespace": "identity",
                "payload_hash": "sha256:wallet-payload:a",
                "payload_encoding": "canonical_json",
                "source_reference": "wallet-consumer",
                "payload": {
                    "wallet_id": "wallet-consumer",
                    "public_key": "ed25519:" + "11" * 32,
                    "registration_nonce": "nonce-a",
                },
            }
        ],
    )
    node_b = node_a.model_copy(
        update={
            "node_id": "node-b",
            "operator_id": "operator-b",
            "base_url": "https://node-b.example",
            "canonical_registry_objects": [
                {
                    "object_id": "sha256:wallet:consumer:b",
                    "object_type": "wallet_identity",
                    "object_version": "wallet-identity.v1",
                    "namespace": "identity",
                    "payload_hash": "sha256:wallet-payload:b",
                    "payload_encoding": "canonical_json",
                    "source_reference": "wallet-consumer",
                    "payload": {
                        "wallet_id": "wallet-consumer",
                        "public_key": "ed25519:" + "22" * 32,
                        "registration_nonce": "nonce-b",
                    },
                }
            ],
        }
    )

    registry.upsert_node(node_a)
    with pytest.raises(ValueError, match="wallet-consumer"):
        registry.upsert_node(node_b)

    response = client.get(
        "/operators/registry/conflicts",
        params={
            "conflict_class": "wallet_identity_binding",
            "logical_key": "wallet-consumer",
        },
    )

    assert response.status_code == 200
    assert len(response.json()["conflicts"]) == 1
    assert response.json()["conflicts"][0]["logical_key"] == "wallet-consumer"


def test_operator_wallet_identity_reconciliation_endpoint_reports_registry_state(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = _service(with_runtime=False, use_process_manager=True)
    registry = RegistryService()
    registry.upsert_wallet_identity_peer(peer_base_url="https://peer-a.example/")
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-a",
            operator_id="operator-a",
            base_url="https://node-a.example",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            heartbeat_ttl_seconds=30,
            resources={
                "total": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 8192},
                "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
                "free": {"cpu": 6.0, "ram_mb": 12000, "vram_mb": 6144},
            },
            providers=["llama.cpp"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 12,
                "output": 18,
                "fixed_request": None,
            },
            rating={
                "score": 0.91,
                "tier": "A",
                "updated_at": "2026-07-05T13:55:00+00:00",
            },
            bundles=[],
            canonical_registry_objects=[
                {
                    "object_id": "sha256:wallet:consumer:a",
                    "object_type": "wallet_identity",
                    "object_version": "wallet-identity.v1",
                    "namespace": "identity",
                    "payload_hash": "sha256:wallet-payload:a",
                    "payload_encoding": "canonical_json",
                    "source_reference": "wallet-consumer",
                    "payload": {
                        "wallet_id": "wallet-consumer",
                        "public_key": "ed25519:" + "11" * 32,
                        "registration_nonce": "nonce-a",
                    },
                }
            ],
        )
    )
    client = TestClient(build_app(service=service, registry_service=registry))

    response = client.get("/operators/registry/wallet-identities/reconciliation")

    assert response.status_code == 200
    assert response.json()["summary"]["wallet_count"] == 1
    assert response.json()["summary"]["enabled_peer_count"] == 1
    assert response.json()["items"][0]["wallet_id"] == "wallet-consumer"
    assert response.json()["items"][0]["status"] == "consistent"


def test_operator_wallet_identity_governance_policy_endpoint_updates_registry_policy() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    registry = RegistryService()
    client = TestClient(build_app(service=service, registry_service=registry))

    initial = client.get("/operators/registry/wallet-identities/governance-policy")
    assert initial.status_code == 200
    assert initial.json()["threshold_mode"] == "majority"
    assert initial.json()["authorized_voter_statuses"] == ["ready", "stale"]

    updated = client.post(
        "/operators/registry/wallet-identities/governance-policy",
        json={
            "authorized_voter_statuses": ["ready"],
            "minimum_eligible_voter_count": 2,
            "minimum_quorum_threshold": 2,
            "quorum_resolution_required": True,
            "ledger_authorization_required": True,
        },
    )

    assert updated.status_code == 200
    assert updated.json()["authorized_voter_statuses"] == ["ready"]
    assert updated.json()["minimum_eligible_voter_count"] == 2
    assert updated.json()["minimum_quorum_threshold"] == 2
    assert updated.json()["quorum_resolution_required"] is True
    assert updated.json()["ledger_authorization_required"] is True
    assert registry.wallet_identity_governance_policy()["authorized_voter_statuses"] == ["ready"]


def test_operator_wallet_identity_resolve_conflict_endpoint_applies_resolution() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    registry = RegistryService()
    first = {
        "object_id": "sha256:wallet:consumer:a",
        "object_type": "wallet_identity",
        "object_version": "wallet-identity.v1",
        "namespace": "identity",
        "payload_hash": "sha256:wallet-payload:a",
        "payload_encoding": "canonical_json",
        "source_reference": "wallet-consumer",
        "payload": {
            "wallet_id": "wallet-consumer",
            "public_key": "ed25519:" + "11" * 32,
            "registration_nonce": "nonce-a",
        },
    }
    second = {
        "object_id": "sha256:wallet:consumer:b",
        "object_type": "wallet_identity",
        "object_version": "wallet-identity.v1",
        "namespace": "identity",
        "payload_hash": "sha256:wallet-payload:b",
        "payload_encoding": "canonical_json",
        "source_reference": "wallet-consumer",
        "payload": {
            "wallet_id": "wallet-consumer",
            "public_key": "ed25519:" + "22" * 32,
            "registration_nonce": "nonce-b",
        },
    }
    registry.upsert_registry_object(first)
    try:
        registry.upsert_registry_object(second)
    except ValueError:
        pass
    client = TestClient(build_app(service=service, registry_service=registry))

    response = client.post(
        "/operators/registry/wallet-identities/resolve-conflict",
        json={
            "wallet_id": "wallet-consumer",
            "chosen_object_id": first["object_id"],
            "operator_note": "prefer original binding",
        },
    )

    assert response.status_code == 200
    assert response.json()["chosen_object_id"] == first["object_id"]
    resolved = registry.resolve_wallet_identity("wallet-consumer")
    assert resolved is not None
    assert resolved["identity_source"] == "registry_resolution"


def test_operator_wallet_identity_quorum_resolution_endpoints_finalize_after_quorum() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    registry = RegistryService()
    operator_a = _operator_registry_identity("node-a")
    operator_b = _operator_registry_identity("node-b")
    consumer_object = {
        "object_id": "sha256:wallet:consumer:a",
        "object_type": "wallet_identity",
        "object_version": "wallet-identity.v1",
        "namespace": "identity",
        "payload_hash": "sha256:wallet-payload:a",
        "payload_encoding": "canonical_json",
        "source_reference": "wallet-consumer",
        "payload": {
            "wallet_id": "wallet-consumer",
            "public_key": "ed25519:" + "11" * 32,
            "registration_nonce": "nonce-a",
        },
    }
    node_a = _registry_node_payload("node-a")
    node_a["owner_wallet_id"] = operator_a["owner_wallet_id"]
    node_a["heartbeat_at"] = "2030-01-01T00:00:00+00:00"
    node_a["canonical_registry_objects"] = [consumer_object]
    node_b = _registry_node_payload("node-b")
    node_b["owner_wallet_id"] = operator_b["owner_wallet_id"]
    node_b["heartbeat_at"] = "2030-01-01T00:00:00+00:00"
    node_b["canonical_registry_objects"] = [consumer_object]
    registry.upsert_node(RegistryNodeAdvertisement(**node_a))
    registry.upsert_node(RegistryNodeAdvertisement(**node_b))
    registry.upsert_registry_object(operator_a["object"])
    registry.upsert_registry_object(operator_b["object"])
    registry.upsert_registry_object(operator_a["owner_wallet_object"])
    registry.upsert_registry_object(operator_b["owner_wallet_object"])
    registry.upsert_registry_object(consumer_object)
    client = TestClient(build_app(service=service, registry_service=registry))

    proposed = client.post(
        "/operators/registry/wallet-identities/quorum-proposals",
        json={
            "wallet_id": "wallet-consumer",
            "chosen_object_id": "sha256:wallet:consumer:a",
            "proposer_node_id": "node-a",
            "proposer_signature": _sign_registry_quorum_proposal(
                operator_a,
                wallet_id="wallet-consumer",
                chosen_object_id="sha256:wallet:consumer:a",
                chosen_payload_hash="sha256:wallet-payload:a",
                eligible_voter_node_ids=["node-a", "node-b"],
                quorum_threshold=2,
                operator_note="network quorum proposal",
            ),
            "eligible_voter_node_ids": ["node-a", "node-b"],
            "quorum_threshold": 2,
            "operator_note": "network quorum proposal",
        },
    )

    assert proposed.status_code == 200
    assert proposed.json()["status"] == "pending"
    assert proposed.json()["eligible_voter_node_ids"] == ["node-a", "node-b"]
    assert proposed.json()["governance_policy_snapshot"]["owner_wallet_link_required"] is True
    resolution_id = proposed.json()["resolution_id"]

    approved = client.post(
        f"/operators/registry/wallet-identities/quorum-proposals/{resolution_id}/approvals",
        json={
            "resolution_id": resolution_id,
            "approver_node_id": "node-b",
            "approval_signature": _sign_registry_quorum_approval(
                operator_b,
                resolution_id=resolution_id,
                approval_note="second vote",
            ),
            "approval_note": "second vote",
        },
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "finalized"
    assert approved.json()["governance_certificate"]["ledger_commitment"]["operation_type"] == (
        "GOVERNANCE_AUTHORIZATION_COMMIT"
    )
    certificates = client.get("/operators/registry/wallet-identities/governance-certificates")
    assert certificates.status_code == 200
    assert certificates.json()["items"][0]["payload"]["certificate_id"] == approved.json()[
        "governance_certificate"
    ]["certificate_id"]
    ledger_proof = client.get(
        "/operators/registry/wallet-identities/governance-certificates/"
        f"{approved.json()['governance_certificate']['certificate_id']}/ledger-proof"
    )
    assert ledger_proof.status_code == 200
    assert ledger_proof.json()["operation_type"] == "GOVERNANCE_AUTHORIZATION_COMMIT"
    assert ledger_proof.json()["consensus_finality"] is False
    peer_report = client.get(
        "/operators/registry/wallet-identities/governance-certificates/"
        f"{approved.json()['governance_certificate']['certificate_id']}/peer-proof-report"
    )
    assert peer_report.status_code == 200
    assert peer_report.json()["enabled_peer_count"] == 0
    assert peer_report.json()["consensus_finality"] is False
    resolved = registry.resolve_wallet_identity("wallet-consumer")
    assert resolved is not None
    assert resolved["identity_source"] == "registry_resolution"


def test_operator_registry_object_endpoint_returns_object_by_id() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    advertisement = service.node_advertisement()
    object_id = advertisement["canonical_registry_objects"][0]["object_id"]
    client = TestClient(build_app(service=service))

    response = client.get(f"/operators/registry/objects/{object_id}")

    assert response.status_code == 200
    assert response.json()["object_id"] == object_id
    assert response.json()["sources"][0]["node_id"] == advertisement["node_id"]
    assert response.json()["sources"][0]["operator_id"] == advertisement["operator_id"]
    assert response.json()["sources"][0]["status"] != "stored"


def test_operator_registry_objects_endpoint_includes_payload_when_requested() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    client = TestClient(build_app(service=service))

    response = client.get("/operators/registry/objects?include_payload=true")

    assert response.status_code == 200
    capability_definition = next(
        item for item in response.json()["objects"] if item["object_type"] == "capability_definition"
    )
    assert capability_definition["payload"]["capability_id"] == "llm.chat"


def test_operator_registry_object_endpoint_includes_payload_when_requested() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    advertisement = service.node_advertisement()
    object_id = advertisement["canonical_registry_objects"][0]["object_id"]
    client = TestClient(build_app(service=service))

    response = client.get(f"/operators/registry/objects/{object_id}?include_payload=true")

    assert response.status_code == 200
    assert response.json()["payload"]["capability_id"] == "llm.chat"


def test_operator_registry_objects_endpoint_uses_local_registry_store_fallback() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    advertisement = service.node_advertisement()
    client = TestClient(build_app(service=service))

    response = client.get("/operators/registry/objects?include_payload=true")

    assert response.status_code == 200
    capability_definition = next(
        item for item in response.json()["objects"] if item["object_type"] == "capability_definition"
    )
    assert capability_definition["payload"]["capability_id"] == "llm.chat"
    assert capability_definition["sources"] == [
        {
            "node_id": advertisement["node_id"],
            "operator_id": advertisement["operator_id"],
            "status": "ready",
        }
    ]


def test_operator_registry_object_endpoint_uses_local_registry_store_fallback() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    advertisement = service.node_advertisement()
    object_id = advertisement["canonical_registry_objects"][0]["object_id"]
    client = TestClient(build_app(service=service))

    response = client.get(f"/operators/registry/objects/{object_id}?include_payload=true")

    assert response.status_code == 200
    assert response.json()["object_id"] == object_id
    assert response.json()["payload"]["capability_id"] == "llm.chat"
    assert response.json()["sources"] == [
        {
            "node_id": advertisement["node_id"],
            "operator_id": advertisement["operator_id"],
            "status": "ready",
        }
    ]


def test_operator_registry_objects_endpoint_lists_session_contract_objects() -> None:
    registry_service = RegistryService()
    session_service = SessionService(SessionStore(), registry_service=registry_service)
    service = _service(with_runtime=False, use_process_manager=True)
    session_service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id=service.node_id,
        deposit_q=10.0,
        session_policy={
            "minimum_deposit": 10.0,
            "recommended_deposit": 25.0,
            "idle_fee_per_minute": 1.0,
            "idle_timeout_seconds": 600,
            "max_concurrent_sessions": 1,
            "maximum_session_duration_seconds": 3600,
            "queue_policy": "busy",
            "minimum_session_fee": 2.0,
        },
        accounting_contract={
            "contract_version": "acct-v1",
            "pricing_version": "pricing-v1",
        },
        advertisement_id="adv-ep-1-v1",
        offer_id="offer-public",
        pricing_policy_hash="sha256:pricing-v1",
    )
    client = TestClient(
        build_app(
            service=service,
            registry_service=registry_service,
            session_service=session_service,
        )
    )

    response = client.get("/operators/registry/objects?include_payload=true")

    assert response.status_code == 200
    session_contract = next(item for item in response.json()["objects"] if item["object_type"] == "session_contract")
    assert session_contract["namespace"] == "session"
    assert session_contract["payload"]["advertisement_id"] == "adv-ep-1-v1"


def test_operator_registry_objects_endpoint_preserves_publication_objects_with_shared_registry() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )
    validation_service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-02T00:00:00+00:00",
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
            validation_service=validation_service,
        )
    )

    publish_response = client.post(f"/api/v1/endpoints/{created.endpoint.endpoint_id}/publish-configuration")
    assert publish_response.status_code == 200

    response = client.get("/operators/registry/objects?include_payload=true")

    assert response.status_code == 200
    object_types = {item["object_type"] for item in response.json()["objects"]}
    assert "accounting_contract" in object_types
    assert "endpoint_feature_profile" in object_types
    assert "endpoint_limit_profile" in object_types
    assert "endpoint_implementation_profile" in object_types


def test_operator_dashboard_fleet_endpoint_returns_aggregated_payload(tmp_path) -> None:
    service = _service(model_store=FileModelStore(tmp_path))
    client = TestClient(build_app(service=service))

    response = client.get("/operators/dashboard/fleet")

    assert response.status_code == 200
    assert response.json()["node"]["node_id"] == service.node_id
    assert response.json()["bundles"][0]["bundle_id"] == "whisper-a"
    assert response.json()["owner_wallet"]["configured"] is False
    assert response.json()["node_identity"]["node_id"] == service.node_id


def test_operator_dashboard_market_endpoint_marks_own_and_external_candidates() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at=datetime.now(UTC).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 9,
                "output": 15,
                "fixed_request": 1,
            },
            rating={
                "score": 0.97,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[
                {
                    "bundle_id": "remote-text",
                    "plugin_id": "fake-managed",
                    "workload_type": "llm_text",
                    "provider_type": "fake",
                    "model_id": "remote-text-model",
                    "endpoint": "https://remote.example/runtimes/remote-text",
                    "enabled": True,
                    "status": "ready",
                    "launch_mode": "attached_service",
                    "device_affinity": "cpu",
                    "max_parallel_requests": 2,
                    "supports_allocation": True,
                    "supports_queue": True,
                }
            ],
        )
    )
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    response = client.get("/operators/dashboard/market")

    assert response.status_code == 200
    assert {item["origin"] for item in response.json()["candidates"]} == {
        "own",
        "external",
    }
    assert any(
        item["node_id"] == hypervisor.node_id and item["origin"] == "own" for item in response.json()["candidates"]
    )


def test_operator_dashboard_market_endpoint_includes_published_endpoint_counts() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
        node_id=hypervisor.node_id,
        wallet_private_key=hypervisor.owner_wallet_private_key(),
    )
    hypervisor.endpoint_publication_service = publication_service
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at=datetime.now(UTC).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 9,
                "output": 15,
                "fixed_request": 1,
            },
            rating={
                "score": 0.97,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[
                {
                    "bundle_id": "remote-text",
                    "plugin_id": "fake-managed",
                    "workload_type": "llm_text",
                    "provider_type": "fake",
                    "model_id": "remote-text-model",
                    "endpoint": "https://remote.example/runtimes/remote-text",
                    "enabled": True,
                    "status": "ready",
                    "launch_mode": "attached_service",
                    "device_affinity": "cpu",
                    "max_parallel_requests": 2,
                    "supports_allocation": True,
                    "supports_queue": True,
                }
            ],
            published_endpoints=[
                {
                    "endpoint_id": "ep-remote",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-external",
                    "current_publication_id": "pub-remote",
                    "current_configuration_hash": "cfg-remote",
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                }
            ],
        )
    )
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    response = client.get("/operators/dashboard/market")

    assert response.status_code == 200
    own = next(item for item in response.json()["candidates"] if item["node_id"] == hypervisor.node_id)
    external = next(item for item in response.json()["candidates"] if item["node_id"] == "node-external")
    assert own["published_endpoint_count"] == 1
    assert external["published_endpoint_count"] == 1


def test_operator_dashboard_market_endpoint_includes_canonical_candidates() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-canonical",
            operator_id="operator-c",
            base_url="https://canonical.example",
            heartbeat_at=datetime.now(UTC).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 7,
                "output": 11,
                "fixed_request": 1,
            },
            rating={
                "score": 0.98,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[],
            canonical_services=[
                {
                    "service_id": "compute",
                    "kind": "compute",
                    "enabled": True,
                    "derived_roles": ["compute_provider"],
                    "responsibilities": ["endpoint_hosting"],
                }
            ],
            canonical_capability_runtimes=[
                {
                    "runtime_id": "runtime-canonical-text",
                    "capability_id": "llm.chat",
                    "runtime_version": "runtime.v2",
                    "protocol_version": "runtime.v1",
                    "location_kind": "local_process",
                    "health_status": "healthy",
                    "supported_features": ["native_canonical_runtime"],
                }
            ],
            canonical_compute_compatibility=[],
            canonical_advertisements=[
                {
                    "advertisement_id": "adv-canonical-text",
                    "resource_type": "endpoint",
                    "owner_wallet": "wallet-canonical",
                    "hypervisor_id": "node-canonical",
                    "capability_id": "llm.chat",
                    "visibility": "public",
                    "signature_scope": "configuration_publication",
                }
            ],
        )
    )
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    response = client.get("/operators/dashboard/market")

    assert response.status_code == 200
    body = response.json()
    assert "canonical_candidates" in body
    assert "canonical_summary" in body
    assert body["canonical_candidates"][0]["capability_id"] == "llm.chat"
    assert body["canonical_candidates"][0]["origin"] == "external"


def test_operator_dashboard_market_endpoint_includes_local_canonical_publication_identity() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Public STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "public",
                "discoverable": True,
                "accepts_external_requests": True,
            },
        )
    )
    publication = publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
        node_id=hypervisor.node_id,
        wallet_private_key=hypervisor.owner_wallet_private_key(),
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.get("/operators/dashboard/market")

    assert response.status_code == 200
    body = response.json()
    candidate = next(
        item for item in body["canonical_candidates"] if item["advertisement_id"] == f"adv-{publication.publication_id}"
    )
    assert candidate["origin"] == "own"
    assert candidate["node_id"] == hypervisor.node_id
    assert candidate["owner_wallet"] == publication.owner_wallet
    assert candidate["visibility"] == "public"
    assert candidate["capability_id"] == "speech.stt"
    assert candidate["published_endpoint_count"] == 1
    assert body["canonical_summary"]["endpoint_advertisement_count"] == 1


def test_operator_dashboard_market_payload_builds_canonical_summary() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")

    payload = build_market_payload(service=hypervisor, registry_service=None)

    assert payload["canonical_summary"]["service_kinds"] == ["compute"]
    assert "speech.stt" in payload["canonical_summary"]["capability_ids"]
    assert payload["canonical_summary"]["runtime_count"] >= 1


def test_operator_dashboard_market_payload_includes_reputation_block() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.rating = {
        "score": 0.31,
        "tier": "D",
        "updated_at": "2026-07-06T11:55:00+00:00",
    }
    completed = hypervisor.queue.enqueue(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "ok.wav"}))
    hypervisor.queue.transition_status(completed.task_id, "completed")
    failed = hypervisor.queue.enqueue(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "fail.wav"}))
    hypervisor.queue.transition_status(failed.task_id, "failed")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Trusty STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication = publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
        node_id=hypervisor.node_id,
        wallet_private_key=hypervisor.owner_wallet_private_key(),
    )
    hypervisor.endpoint_publication_service = publication_service

    payload = build_market_payload(service=hypervisor, registry_service=None)

    candidate = payload["candidates"][0]
    canonical_candidate = next(
        item
        for item in payload["canonical_candidates"]
        if item["advertisement_id"] == f"adv-{publication.publication_id}"
    )
    assert candidate["rating"]["score"] == 0.31
    assert candidate["reputation"]["score"] > candidate["rating"]["score"]
    assert candidate["reputation"]["components"]["operational_reliability"] == 0.5
    assert canonical_candidate["reputation"] == candidate["reputation"]


def test_operator_dashboard_market_payload_uses_field_level_reputation_fallback_for_sorting() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    heartbeat_at = datetime.now(UTC).isoformat()
    common_bundle = [
        {
            "bundle_id": "remote-text",
            "plugin_id": "fake-managed",
            "workload_type": "llm_text",
            "provider_type": "fake",
            "model_id": "remote-text-model",
            "endpoint": "https://remote.example/runtimes/remote-text",
            "enabled": True,
            "status": "ready",
            "launch_mode": "attached_service",
            "device_affinity": "cpu",
            "max_parallel_requests": 2,
            "supports_allocation": True,
            "supports_queue": True,
        }
    ]
    common_resources = {
        "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
        "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
    }
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-partial-reputation",
            operator_id="operator-a",
            base_url="https://node-partial-reputation.example",
            heartbeat_at=heartbeat_at,
            resources=common_resources,
            providers=["fake"],
            can_host_custom_model=True,
            pricing={"unit": "q_per_1kk_tokens", "input": 7, "output": 10},
            rating={"score": 0.94, "tier": "A", "updated_at": "2026-07-06T11:55:00+00:00"},
            reputation={
                "score": 0.73,
                "tier": "B",
                "updated_at": "2026-07-06T11:55:00+00:00",
                "components": {"freshness": 0.82},
                "evidence": {"node_status": "ready"},
            },
            bundles=common_bundle,
        )
    )
    registry._nodes["node-partial-reputation"]["reputation"].pop("score")
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-lower-score",
            operator_id="operator-b",
            base_url="https://node-lower-score.example",
            heartbeat_at=heartbeat_at,
            resources=common_resources,
            providers=["fake"],
            can_host_custom_model=True,
            pricing={"unit": "q_per_1kk_tokens", "input": 6, "output": 9},
            rating={"score": 0.45, "tier": "C", "updated_at": "2026-07-06T11:55:00+00:00"},
            reputation={
                "score": 0.61,
                "tier": "C",
                "updated_at": "2026-07-06T11:55:00+00:00",
                "components": {"freshness": 0.61},
                "evidence": {"node_status": "ready"},
            },
            bundles=common_bundle,
        )
    )

    payload = build_market_payload(service=hypervisor, registry_service=registry)

    assert [candidate["node_id"] for candidate in payload["candidates"][:2]] == [
        "node-partial-reputation",
        "node-lower-score",
    ]
    candidate = payload["candidates"][0]
    assert candidate["reputation"]["score"] == 0.94
    assert candidate["reputation"]["tier"] == "B"
    assert candidate["reputation"]["components"]["freshness"] == 0.82
    assert candidate["rating"]["score"] == 0.94


def test_operator_dashboard_market_payload_registry_backed_summary_ignores_unpublished_canonical_overlay() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))

    payload = build_market_payload(service=hypervisor, registry_service=registry)

    assert payload["canonical_candidates"] == []
    assert payload["canonical_summary"] == {
        "service_kinds": [],
        "capability_ids": [],
        "runtime_count": 0,
        "endpoint_advertisement_count": 0,
    }


def test_operator_dashboard_market_payload_excludes_non_market_nodes_from_canonical_summary() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-stale-canonical",
            operator_id="operator-stale",
            base_url="https://stale.example",
            heartbeat_at="2026-06-01T00:00:00+00:00",
            heartbeat_ttl_seconds=30,
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 7,
                "output": 11,
                "fixed_request": 1,
            },
            rating={
                "score": 0.98,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[],
            canonical_services=[
                {
                    "service_id": "validation",
                    "kind": "validation",
                    "enabled": True,
                    "derived_roles": ["validator"],
                    "responsibilities": ["endpoint_validation"],
                }
            ],
            canonical_capability_runtimes=[
                {
                    "runtime_id": "runtime-stale",
                    "capability_id": "vision.generate",
                    "runtime_version": "runtime.v2",
                    "protocol_version": "runtime.v1",
                    "location_kind": "local_process",
                    "health_status": "healthy",
                    "supported_features": ["native_canonical_runtime"],
                }
            ],
            canonical_compute_compatibility=[],
            canonical_advertisements=[
                {
                    "advertisement_id": "adv-stale",
                    "resource_type": "endpoint",
                    "owner_wallet": "wallet-stale",
                    "hypervisor_id": "node-stale-canonical",
                    "capability_id": "vision.generate",
                    "visibility": "public",
                    "signature_scope": "configuration_publication",
                }
            ],
        )
    )

    payload = build_market_payload(service=hypervisor, registry_service=registry)

    assert payload["canonical_summary"] == {
        "service_kinds": [],
        "capability_ids": [],
        "runtime_count": 0,
        "endpoint_advertisement_count": 0,
    }


def test_operator_dashboard_remote_endpoints_route_returns_discovered_and_attached_items() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at=datetime.now(UTC).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 9,
                "output": 15,
                "fixed_request": 1,
            },
            rating={
                "score": 0.97,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[],
            published_endpoints=[
                {
                    "endpoint_id": "ep-remote",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-external",
                    "current_publication_id": "pub-remote",
                    "current_configuration_hash": "cfg-remote",
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                }
            ],
        )
    )
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-external",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-b",
        pricing={"unit": "q_per_1kk_tokens", "input": 9, "output": 15, "fixed_request": 1},
        rating={"score": 0.97, "tier": "A", "updated_at": "2026-06-20T11:55:00Z"},
        alias="Preferred Remote",
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            registry_service=registry,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.get("/operators/dashboard/remote-endpoints")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["attached"] == 1
    assert body["summary"]["discovered"] == 1
    assert body["attached"][0]["source_endpoint_id"] == "ep-remote"
    assert body["discovered"][0]["endpoint_id"] == "ep-remote"
    assert body["discovered"][0]["already_attached"] is True


def test_attach_remote_endpoint_route_persists_preferred_catalogue_entry() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at=datetime.now(UTC).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 9,
                "output": 15,
                "fixed_request": 1,
            },
            rating={
                "score": 0.97,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[],
            published_endpoints=[
                {
                    "endpoint_id": "ep-remote",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-external",
                    "current_publication_id": "pub-remote",
                    "current_configuration_hash": "cfg-remote",
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                }
            ],
        )
    )
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    client = TestClient(
        build_app(
            service=hypervisor,
            registry_service=registry,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.post(
        "/operators/remote-endpoints/attach",
        json={"node_id": "node-external", "endpoint_id": "ep-remote", "alias": "Primary Remote"},
    )

    assert response.status_code == 201
    body = response.json()["data"]["remote_endpoint"]
    assert body["source_node_id"] == "node-external"
    assert body["source_endpoint_id"] == "ep-remote"
    assert body["alias"] == "Primary Remote"
    assert remote_endpoint_service.list_remote_endpoints()[0].source_endpoint_id == "ep-remote"


def test_detach_remote_endpoint_route_removes_preferred_catalogue_entry() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-external",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-b",
        pricing={"unit": "q_per_1kk_tokens", "input": 9, "output": 15, "fixed_request": 1},
        rating={"score": 0.97, "tier": "A", "updated_at": "2026-06-20T11:55:00Z"},
        alias="Primary Remote",
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.delete(f"/operators/remote-endpoints/{attached.remote_endpoint_id}")

    assert response.status_code == 200
    body = response.json()["data"]["remote_endpoint"]
    assert body["remote_endpoint_id"] == attached.remote_endpoint_id
    assert remote_endpoint_service.list_remote_endpoints() == []


def test_detach_remote_endpoint_route_rejects_proxy_dependencies() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Proxy Worker",
            model_class="llm_text",
            capabilities=["chat"],
        )
    )
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-external",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-b",
        pricing={"unit": "q_per_1kk_tokens", "input": 9, "output": 15, "fixed_request": 1},
        rating={"score": 0.97, "tier": "A", "updated_at": "2026-06-20T11:55:00Z"},
    )
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.delete(f"/operators/remote-endpoints/{attached.remote_endpoint_id}")

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "remote_endpoint_in_use"
    assert body["error"]["details"]["dependent_endpoint_ids"] == [created.endpoint.endpoint_id]


def test_attach_proxy_target_route_updates_endpoint_to_proxy_strategy() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    registry = RegistryService()
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at=datetime.now(UTC).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 9,
                "output": 15,
                "fixed_request": 1,
            },
            rating={
                "score": 0.97,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[],
            published_endpoints=[
                {
                    "endpoint_id": "ep-remote",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-external",
                    "current_publication_id": "pub-remote",
                    "current_configuration_hash": "cfg-remote",
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                }
            ],
        )
    )
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-external",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-b",
        pricing={"unit": "q_per_1kk_tokens", "input": 9, "output": 15, "fixed_request": 1},
        rating={"score": 0.97, "tier": "A", "updated_at": "2026-06-20T11:55:00Z"},
        alias="Primary Remote",
    )
    client = TestClient(
        build_app(
            service=service,
            registry_service=registry,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.post(
        f"/api/v1/endpoints/{created.endpoint.endpoint_id}/proxy-target",
        json={"remote_endpoint_id": attached.remote_endpoint_id},
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["endpoint"]["execution_strategy"] == "proxy"
    assert body["endpoint"]["proxy_target"]["remote_endpoint_id"] == attached.remote_endpoint_id
    assert body["snapshot"]["proxy_target"]["remote_endpoint_id"] == attached.remote_endpoint_id


def test_detach_proxy_target_route_reverts_endpoint_to_local_strategy() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-external",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-b",
        pricing={"unit": "q_per_1kk_tokens", "input": 9, "output": 15, "fixed_request": 1},
        rating={"score": 0.97, "tier": "A", "updated_at": "2026-06-20T11:55:00Z"},
        alias="Primary Remote",
    )
    proxied = endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.delete(f"/api/v1/endpoints/{created.endpoint.endpoint_id}/proxy-target")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["endpoint"]["configuration_hash"] != proxied.endpoint.configuration_hash
    assert body["endpoint"]["execution_strategy"] == "local"
    assert body["endpoint"]["proxy_target"] is None
    assert body["snapshot"]["proxy_target"] is None


def test_operator_dashboard_shell_route_returns_terminal_layout_markup() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "AiDN Operator Dashboard" in response.text
    assert 'data-screen="home"' in response.text
    assert 'data-screen="fleet"' in response.text
    assert 'data-screen="sessions"' in response.text
    assert 'data-screen="market"' in response.text
    assert 'data-role="command-rail"' in response.text
    assert 'data-role="metrics-strip"' in response.text
    assert 'data-role="workspace"' in response.text
    assert 'data-role="inspector"' in response.text
    assert 'data-role="operations-band"' in response.text


def test_operator_services_route_returns_canonical_service_inventory() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/services")

    assert response.status_code == 200
    body = response.json()
    assert body["services"][0]["kind"] == "compute"
    assert "capabilities" in body
    assert "runtimes" in body


def test_operator_dashboard_shell_mentions_compute_service_overlay() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Compute Service" in response.text
    assert "Capability Runtimes" in response.text
    assert "Bundles remain a transitional local supply layer." in response.text


def test_operator_dashboard_shell_route_exposes_market_terminal_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Execution Market" in response.text
    assert "Selected Offer" in response.text
    assert "Request Queue" in response.text
    assert "Policy Controls" in response.text
    assert "Published Endpoints" in response.text
    assert "Trust Posture" in response.text
    assert "Recommended Next Action" in response.text
    assert "Open Endpoints and publish local supply before relying on remote market capacity." in response.text
    assert "Compare the selected offer against local capacity before routing work outward." in response.text
    assert "function marketRecommendedAction" in response.text


def test_operator_dashboard_shell_renders_reputation_breakdown() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "function candidateReputation(candidate)" in response.text
    assert "Freshness" in response.text
    assert "Publication Integrity" in response.text
    assert "Validation Posture" in response.text
    assert "Operational Reliability" in response.text


def test_operator_dashboard_shell_reputation_breakdown_uses_placeholder_for_missing_components() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "function renderReputationBreakdown(candidate)" in response.text
    assert 'value == null ? "-" : formatRating(value)' in response.text
    assert "formatRating(Number(value ?? 0))" not in response.text


def test_operator_dashboard_shell_route_keeps_home_market_preview_in_sync() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'loadScreen("market"),' in response.text
    assert "function marketCandidateCount()" in response.text
    assert "Math.max(" in response.text
    assert "Number(home.market_preview?.candidate_count || 0)" in response.text
    assert "marketCandidateCount()" in response.text


def test_operator_dashboard_shell_route_exposes_market_offer_configuration_handoff() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Select Offer And Configure" in response.text
    assert 'data-market-action="configure-offer"' in response.text
    assert 'data-screen-jump="remote"' in response.text
    assert 'button.dataset.marketAction === "configure-offer"' in response.text
    assert 'state.screen = "remote"' in response.text
    assert "remoteSelectionKeyForDiscovered" in response.text


def test_operator_dashboard_shell_route_exposes_market_shortcut_for_attached_proxy_staging() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "prepareEndpointProxyHandoff" in response.text
    assert "discovered?.already_attached" in response.text


def test_operator_dashboard_shell_route_prefers_payload_recommendations_for_market_and_remote() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "marketPayload().recommended_action" in response.text
    assert "remotePayload().recommended_action" in response.text


def test_operator_dashboard_shell_route_exposes_fleet_guided_handoff_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-screen="fleet"' in response.text
    assert "Node Inventory" in response.text
    assert "Recommended Next Action" in response.text
    assert "Open Providers to attach execution backends before local capacity can serve bundles." in response.text
    assert "Open Bundles to turn local capacity into endpoint-ready inventory." in response.text
    assert "function fleetRecommendedAction" in response.text


def test_operator_dashboard_shell_route_exposes_remote_endpoint_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-screen="remote"' in response.text
    assert "/operators/dashboard/remote-endpoints" in response.text
    assert "Remote Endpoints" in response.text
    assert "Preferred Catalogue" in response.text
    assert "Attach Remote Endpoint" in response.text


def test_operator_dashboard_shell_route_exposes_remote_proxy_handoff_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Open Endpoints And Stage Proxy" in response.text
    assert 'data-remote-action="stage-proxy"' in response.text
    assert 'button.dataset.remoteAction === "stage-proxy"' in response.text
    assert 'state.screen = "endpoints"' in response.text
    assert "state.endpointProxyDraft = {" in response.text


def test_operator_dashboard_shell_route_exposes_detach_remote_endpoint_action() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-remote-action="detach"' in response.text
    assert "Detach Remote Endpoint" in response.text
    assert '"/operators/remote-endpoints/' in response.text
    assert "function clearDetachedRemoteProxyState(remoteEndpointId)" in response.text
    assert "state.endpointProxyDraft.remoteEndpointId === remoteEndpointId" in response.text
    assert "state.endpointProxyDraft = {" in response.text
    assert "state.proxyGuidedFlow?.remoteEndpointId === remoteEndpointId" in response.text
    assert "clearGuidedProxyFlow();" in response.text
    assert "clearDetachedRemoteProxyState(remote.remote_endpoint_id);" in response.text


def test_operator_dashboard_shell_route_exposes_attach_to_endpoint_proxy_handoff() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "prepareEndpointProxyHandoff(result.data.remote_endpoint" in response.text
    assert "Proxy draft preserved for the next local endpoint." in response.text


def test_operator_dashboard_shell_route_exposes_wallet_drawer_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-wallet-open="rail"' in response.text
    assert 'data-wallet-open="ops"' in response.text
    assert 'data-wallet-close="true"' in response.text
    assert 'id="wallet-drawer"' in response.text
    assert "/operators/dashboard/wallet" in response.text
    assert "/operators/wallet/usage" in response.text
    assert "/operators/wallet/allocations" in response.text
    assert "/operators/wallet/allocations/disputes" in response.text
    assert "/operators/wallet/quote" in response.text


def test_operator_dashboard_shell_route_exposes_requests_workspace_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-screen="requests"' in response.text
    assert "/operators/dashboard/requests" in response.text
    assert 'data-requests-policy="strategy"' in response.text
    assert "Spillover Preview" in response.text


def test_operator_dashboard_shell_route_exposes_sessions_workspace_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-screen="sessions"' in response.text
    assert "/operators/dashboard/sessions" in response.text
    assert "/operators/dashboard/sessions/actions/close" in response.text
    assert "/operators/dashboard/sessions/actions/sweep-idle" in response.text
    assert "/operators/wallet/economics" in response.text
    assert "/operators/wallet/economics/export" in response.text
    assert "/operators/wallet/economics/faucet" in response.text
    assert "/operators/wallet/economics/faucet/claim" in response.text
    assert 'data-wallet-tab="economics"' in response.text
    assert "Faucet Pool" in response.text
    assert "Faucet Claim" in response.text
    assert "Claim Faucet Share" in response.text
    assert "Faucet Mechanics" in response.text
    assert "Reward Pools" in response.text
    assert "Economics History" in response.text
    assert "Recycle Backlog" in response.text
    assert "Reserve Paid Session" in response.text
    assert "Deposit Confirmation" in response.text
    assert "Confirm Deposit &amp; Open Session" in response.text
    assert "Session Forced Settlement" in response.text
    assert "Force Refund Timeout" in response.text
    assert 'data-session-action="force-unavailable-refund"' in response.text
    assert 'data-session-force-field="forceAfter"' in response.text
    assert "/mvp-sessions/${selected.session.session_id}/force-finalize" in response.text
    assert 'data-session-open-field="endpointId"' in response.text
    assert 'data-session-open-field="clientWallet"' in response.text
    assert 'data-session-open-field="depositQ"' in response.text
    assert 'data-session-open-field="confirm"' in response.text
    assert "Launch Session Request" in response.text
    assert 'data-session-request-field="taskType"' in response.text
    assert 'data-session-request-field="inputValue"' in response.text
    assert 'data-session-request-action="submit"' in response.text
    assert "Submit Session Task" in response.text
    assert "Session Activity" in response.text
    assert "Usage Timeline" in response.text
    assert "Settlement Preview" in response.text
    assert "Idle Exposure" in response.text
    assert "Session Console" in response.text
    assert "Idle Timeout Watch" in response.text
    assert "Sweep Idle Sessions" in response.text
    assert "Close Session" in response.text


def test_operator_dashboard_shell_route_exposes_install_registration_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-screen="installs"' in response.text
    assert "/operators/dashboard/installs" in response.text
    assert "/operators/models/" in response.text
    assert "/register-bundle" in response.text
    assert "Bundle Registration" in response.text
    assert 'data-install-field="bundleId"' in response.text
    assert 'data-install-field="workloadType"' in response.text
    assert 'data-install-field="endpoint"' in response.text
    assert 'data-install-action="register-bundle"' in response.text
    assert "Register Bundle" in response.text
    assert "Recommended Next Action" in response.text
    assert (
        "Queue or process a model install first so completed artifacts can be registered as bundles." in response.text
    )
    assert "Select a completed install, then register it as a bundle so it can become an endpoint." in response.text
    assert "function installRecommendedAction" in response.text


def test_operator_dashboard_shell_route_exposes_bundle_endpoint_creation_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-screen="bundles"' in response.text
    assert "/operators/dashboard/bundles" in response.text
    assert "/api/v1/endpoints" in response.text
    assert "Bundle To Endpoint" in response.text
    assert 'data-bundle-endpoint-field="displayName"' in response.text
    assert 'data-bundle-endpoint-field="visibility"' in response.text
    assert 'data-bundle-endpoint-field="sharedWallets"' in response.text
    assert 'data-bundle-endpoint-action="create-endpoint"' in response.text
    assert "Create Endpoint From Bundle" in response.text
    assert "Recommended Next Action" in response.text
    expected_action = (
        "Select a first-endpoint candidate, then create an endpoint from local "
        "inventory without leaving this workspace."
    )
    assert expected_action in response.text
    assert "function bundleRecommendedAction" in response.text
    assert "action-focus" in response.text


def test_operator_dashboard_shell_route_exposes_endpoint_pipeline_copy() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Endpoint Pipeline" in response.text
    assert "Endpoints are the primary operator workspace." in response.text
    assert "Providers prepare execution supply. Bundles prepare endpoint candidates." in response.text
    assert 'data-screen-jump="endpoints"' in response.text


def test_operator_dashboard_shell_route_exposes_provider_attach_and_reload_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-screen="providers"' in response.text
    assert "/operators/dashboard/providers" in response.text
    assert "/operators/models/install" in response.text
    assert "/operators/bundles/config" in response.text
    assert "/operators/bundles/reload" in response.text
    assert "Provider instances" in response.text
    assert "Model deployments" in response.text
    assert "Runtime bindings" in response.text
    assert "Plugin Host connections" in response.text
    assert "Plugin Host Status" in response.text
    assert "Local Plugin Host control-plane observability." in response.text
    assert "Plugin directory" in response.text
    assert "Trust" in response.text
    assert "Install plan preview" in response.text
    assert "Preview only /" in response.text
    assert "Declarative preview available" not in response.text
    assert 'data-provider-row="${escapeHtml(provider.plugin_id)}"' in response.text
    assert "${escapeHtml(provider.display_name || provider.plugin_id)}" in response.text
    assert '${escapeHtml(provider.trust_status || "UNREVIEWED")}' in response.text
    assert "escapeHtml(permission.label || permission.permission_id)" in response.text
    assert "No providers installed" in response.text
    assert "Manual Provider Attach" in response.text
    assert "Reload Saved Bundle Config" in response.text
    assert 'data-provider-bundle-field="bundleId"' in response.text
    assert 'data-provider-bundle-field="modelId"' in response.text
    assert 'data-provider-bundle-field="workloadType"' in response.text
    assert 'data-provider-bundle-field="endpoint"' in response.text
    assert 'data-provider-action="attach-bundle"' in response.text
    assert 'data-provider-action="reload-bundles"' in response.text
    assert "Recommended Next Action" in response.text
    assert "Attach a provider or import its manifest before bundle wiring or installs can begin." in response.text
    assert "Queue a model install so the artifact can be handed off into Installs for registration." in response.text
    assert "function providerRecommendedAction" in response.text


def test_operator_dashboard_shell_route_uses_payload_driven_provider_and_bundle_handoff_copy() -> None:
    response = TestClient(build_app(service=_service())).get("/operators/dashboard")

    assert response.status_code == 200
    assert "selectedProvider()?.endpoint_readiness" in response.text
    assert "selectedFleetBundle()?.endpoint_relationship" in response.text
    assert "This screen prepares execution supply through provider plugins" in response.text
    assert "This screen tracks bundle-to-endpoint relationship state." in response.text


def test_operator_dashboard_shell_route_exposes_provider_install_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-screen="providers"' in response.text
    assert "/operators/models/install" in response.text
    assert "Install Model Artifact" in response.text
    assert 'data-provider-install-field="modelId"' in response.text
    assert 'data-provider-install-field="sourceUrl"' in response.text
    assert 'data-provider-install-field="requestedBy"' in response.text
    assert 'data-provider-action="queue-install"' in response.text
    assert "/operators/provider-installation-approvals" in response.text
    assert "/operators/provider-installation-jobs" in response.text
    assert "/operators/provider-installation-artifacts" in response.text
    assert "Apply approved plan" in response.text
    assert "controlled executor" in response.text
    assert "Approve Install Plan" in response.text
    assert "Run Dry-Run Diagnostics" in response.text
    assert "Apply Latest Approval" in response.text
    assert "Install UI schema:" in response.text
    assert "Sandbox Policy" in response.text
    assert "Installation Recipe" in response.text
    assert "Custom configuration" in response.text
    assert "data-provider-apply-recipe" in response.text
    assert 'data-provider-apply-field="${escapeHtml(fieldId)}"' in response.text
    assert "data-provider-apply-note" in response.text
    assert 'data-provider-action="approve-installation"' in response.text
    assert 'data-provider-action="run-installation-diagnostics"' in response.text
    assert 'data-provider-action="apply-installation"' in response.text
    assert "/operators/provider-plugins/" in response.text
    assert "/installation-diagnostics" in response.text
    assert "Provider Installation Apply Jobs" in response.text
    assert "/operators/provider-instances/" in response.text
    assert "/discover-models" in response.text
    assert "Discover Models" in response.text
    assert "data-provider-discover-models" in response.text
    assert "/operators/model-deployments/" in response.text
    assert "/runtime-bindings" in response.text
    assert "Create Runtime Binding" in response.text
    assert "Materialize Artifacts First" in response.text
    assert "materialize first" in response.text
    assert "artifacts ready" in response.text
    assert "Fix Endpoint Readiness" in response.text
    assert "review pricing" in response.text
    assert "endpoint ready" in response.text
    assert "data-model-runtime-binding" in response.text
    assert "runtime_binding_id" in response.text
    assert "data-runtime-binding-endpoint" in response.text
    assert "Stage Local Artifact" in response.text
    assert "Extract Staged Archive" in response.text
    assert "Controlled Imports Root" in response.text
    assert "data-provider-artifact-relative-path" in response.text
    assert "data-provider-artifact-file" in response.text
    assert "data-provider-artifact-archive-path" in response.text
    assert "data-provider-artifact-destination-directory" in response.text
    assert "Guided Provider Setup" in response.text
    assert "data-provider-setup-step" in response.text
    assert "Suggested Provider Step" in response.text


def test_operator_dashboard_shell_route_exposes_provider_install_processing_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-screen="providers"' in response.text
    assert "/operators/models/install/process" in response.text
    assert "Process Queued Installs" in response.text
    assert 'data-provider-action="process-installs"' in response.text


def test_operator_dashboard_shell_route_exposes_provider_to_installs_handoff_logic() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'state.screen = "installs";' in response.text
    assert "Ready to review install" in response.text


def test_operator_dashboard_shell_route_exposes_install_registration_cta() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Register Bundle Now" in response.text
    assert "Registration path stays local until you decide to create an endpoint." in response.text


def test_operator_dashboard_shell_route_exposes_install_to_bundles_handoff_logic() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'state.screen = "bundles";' in response.text
    assert "Ready to review bundle" in response.text


def test_operator_dashboard_shell_route_exposes_bundles_to_endpoints_handoff_logic() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'state.screen = "endpoints";' in response.text
    assert "Ready to review endpoint" in response.text


def test_operator_dashboard_shell_route_exposes_endpoints_workspace_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-screen="endpoints"' in response.text
    assert "/operators/dashboard/endpoints" in response.text
    assert "/api/v1/endpoints" in response.text
    assert "Endpoint Control Plane" in response.text
    assert "Visibility & Access" in response.text
    assert "Validation Requested" in response.text
    assert "Configured Endpoints" in response.text
    assert "Selected Endpoint Actions" in response.text
    assert "MVP Paid Smoke" in response.text
    assert "MVP Smoke Settlement Controls" in response.text
    assert "/mvp-paid-smoke" in response.text
    assert "/mvp-sessions/${ids.sessionId}/finalize" in response.text
    assert "/mvp-sessions/${ids.sessionId}/force-finalize" in response.text
    assert "Endpoint Policy Editor" in response.text
    assert "Endpoint Runtime Editor" in response.text
    assert "Configuration History" in response.text
    assert 'data-endpoint-action="publish"' in response.text
    assert 'data-endpoint-action="request-validation"' in response.text
    assert 'data-endpoint-action="run-mvp-smoke"' in response.text
    assert 'data-endpoint-action="finalize-mvp-smoke"' in response.text
    assert 'data-endpoint-action="force-finalize-mvp-smoke"' in response.text
    assert 'data-mvp-smoke-settlement-field="consumerSignature"' in response.text
    assert 'data-mvp-smoke-settlement-field="forceAfter"' in response.text
    assert 'data-endpoint-action="save-policy"' in response.text
    assert 'data-endpoint-action="save-config"' in response.text
    assert 'data-endpoint-field="visibility"' in response.text
    assert 'data-endpoint-field="sharedWallets"' in response.text
    assert 'data-endpoint-field="validationEnabled"' in response.text
    assert 'data-endpoint-config-field="displayName"' in response.text
    assert 'data-endpoint-config-field="profileSummary"' in response.text
    assert 'data-endpoint-config-field="contextLength"' in response.text
    assert 'data-endpoint-config-field="temperature"' in response.text


def test_operator_dashboard_shell_route_exposes_endpoint_next_step_guidance() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Endpoint Next Step" in response.text
    assert "Current Step" in response.text
    assert "Configuration Snapshot" in response.text
    assert "Endpoint Availability" in response.text
    assert "Recommended Action" in response.text
    assert "The highlighted control matches the current step above." in response.text
    assert "Save policy and runtime changes before publishing a new configuration snapshot." in response.text
    assert "Publish this endpoint when routing, visibility, and pricing are ready for remote use." in response.text
    assert (
        "Validation remains optional and can be requested after publication when you want network trust."
        in response.text
    )
    assert (
        "Create or select an endpoint to save policy, publish configuration, and request validation later."
        in response.text
    )
    assert 'key: "snapshot"' in response.text
    assert 'key: "publish"' in response.text
    assert 'key: "validation"' in response.text
    assert "function endpointRecommendedAction" in response.text
    assert "action-focus" in response.text
    assert 'data-endpoint-config-field="maxTokens"' in response.text
    assert 'data-endpoint-config-field="timeout"' in response.text
    assert 'data-endpoint-config-field="streaming"' in response.text


def test_operator_dashboard_shell_route_exposes_proxy_attach_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Proxy Route Attachment" in response.text
    assert "Proxy Runtime Trace" in response.text
    assert "Proxy Route Summary" in response.text
    assert 'data-endpoint-proxy-field="remoteEndpointId"' in response.text
    assert 'data-endpoint-action="attach-proxy-target"' in response.text


def test_operator_dashboard_shell_route_exposes_guided_proxy_publish_flow() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Proxy Route Binding" in response.text
    assert (
        "Attach the staged remote endpoint as the proxy target before publishing the new configuration."
        in response.text
    )
    assert 'return "attach-proxy-target";' in response.text
    assert 'case "attach-proxy-target":' in response.text
    assert "proxyGuidedFlow" in response.text


def test_operator_dashboard_shell_exposes_detach_proxy_route_action() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-endpoint-action="detach-proxy-target"' in response.text
    assert 'case "detach-proxy-target":' in response.text
    assert "Detach Proxy Route" in response.text


def test_operator_dashboard_shell_route_exposes_one_click_guided_proxy_publish_action() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "function renderGuidedProxyPanel(" in response.text
    assert (
        'action: "complete-guided-proxy-publish",' in response.text
        and 'label: "Publish Configuration",' in response.text
        and 'kind: "endpoint-action",' in response.text
    )
    assert 'case "complete-guided-proxy-publish":' in response.text
    assert 'state.endpointInspectorView = "signed-publication";' in response.text


def test_operator_dashboard_shell_route_exposes_guided_proxy_step_rail() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Guided Route Flow" in response.text
    assert "Request Validation (Optional)" in response.text
    assert "Create Endpoint" in response.text
    assert "Attach Proxy Route" in response.text
    assert "Publish Configuration" in response.text
    assert 'case "create-endpoint":' in response.text


def test_operator_dashboard_shell_route_guided_bootstrap_cta_uses_shell_readiness() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "const recommendation = homeRecommendedAction(state.payloads.home?.bootstrap || {});" in response.text
    assert 'return { kind: "screen-jump", action: "home", label: "Open Wallet Setup" };' in response.text
    assert "action: recommendation.action," in response.text
    assert 'data-screen-jump="${proxyGuidedPrimaryAction.action}"' in response.text
    assert 'return { kind: "endpoint-action", action: "create-endpoint", label: "Create Endpoint" };' in response.text


def test_operator_dashboard_shell_route_exposes_guided_proxy_finish_action() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Finish Guided Flow" in response.text
    assert 'data-endpoint-action="finish-guided-flow"' in response.text
    assert 'case "finish-guided-flow":' in response.text


def test_operator_dashboard_shell_route_exposes_guided_proxy_phase_transitions() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'phase: "attach"' in response.text
    assert 'phase: "publish"' in response.text
    assert 'phase: "validate_optional"' in response.text
    assert "clearGuidedProxyFlow" in response.text
    assert 'state.screen = proxyGuidedFlow?.phase === "publish" ? "endpoints" : "home";' in response.text
    assert "Open the validation controls when you are ready to request it." not in response.text
    assert "`${endpointApiBase}/${draft.endpoint_id}/request-validation`" in response.text


def test_operator_dashboard_shell_route_exposes_wallet_and_endpoint_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Wallet Ownership" in response.text
    assert "Node Identity" in response.text
    assert "First Endpoint" in response.text
    assert "/operators/wallet/bootstrap/create" in response.text
    assert "/operators/wallet/bootstrap/import" in response.text
    assert "/api/v1/endpoints" in response.text
    assert 'data-bootstrap-action="create-wallet"' in response.text
    assert 'data-bootstrap-action="import-wallet"' in response.text
    assert 'data-endpoint-action="create"' in response.text
    assert 'data-endpoint-action="publish"' in response.text
    assert 'data-endpoint-action="request-validation"' in response.text
    assert 'data-bootstrap-field="walletLabel"' in response.text
    assert 'data-bootstrap-field="endpointVisibility"' in response.text
    assert 'data-bootstrap-field="sharedWallets"' in response.text
    assert "Recommended Next Action" in response.text
    assert "Create or import a wallet before any publish or market-facing step." in response.text
    assert (
        "Attach a provider or finish a model install so bootstrap can surface a first endpoint candidate."
        in response.text
    )
    assert "function homeRecommendedAction" in response.text
    assert 'data-screen-jump="providers"' in response.text
    assert "/operators/endpoints/bootstrap" not in response.text


def test_operator_dashboard_shell_route_exposes_guided_onboarding_sections() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Onboarding Progress" in response.text
    assert "Current Guided Step" in response.text
    assert "Onboarding completes when the first local endpoint is published." in response.text
    assert "Validation stays optional and does not block completion." in response.text
    assert 'data-screen-jump="providers"' in response.text
    assert 'data-screen-jump="bundles"' in response.text
    assert 'data-screen-jump="endpoints"' in response.text
    assert 'state.screen = proxyGuidedFlow?.phase === "publish" ? "endpoints" : "home";' in response.text


def test_operator_dashboard_home_market_preview_matches_market_candidates() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    home = client.get("/operators/dashboard/home")
    market = client.get("/operators/dashboard/market")

    assert home.status_code == 200
    assert market.status_code == 200
    assert home.json()["bootstrap"]["wallet_ready"] is False
    assert home.json()["bootstrap"]["node_identity"]["node_id"] == hypervisor.node_id
    assert home.json()["market_preview"]["candidate_count"] == len(market.json()["candidates"])


def test_dashboard_seed_preview_refreshes_registry_visibility_after_heartbeat_ttl(
    monkeypatch,
) -> None:
    preview_app = dashboard_seed_preview.create_app()
    client = TestClient(preview_app)

    initial_market = client.get("/operators/dashboard/market")

    assert initial_market.status_code == 200
    assert len(initial_market.json()["candidates"]) > 0

    future_now = datetime.now(UTC) + timedelta(seconds=120)

    class _FutureDateTime:
        @staticmethod
        def now(tz=None):
            if tz is None:
                return future_now.replace(tzinfo=None)
            return future_now.astimezone(tz)

    monkeypatch.setattr(
        "aidn_hypervisor.registry_service.time.time",
        lambda: future_now.timestamp(),
    )
    monkeypatch.setattr(dashboard_seed_preview, "datetime", _FutureDateTime)

    refreshed_market = client.get("/operators/dashboard/market")

    assert refreshed_market.status_code == 200
    assert len(refreshed_market.json()["candidates"]) > 0


def test_operator_dashboard_home_bootstrap_prefers_endpoint_service_state() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    client = TestClient(build_app(service=hypervisor, endpoint_service=endpoint_service))

    home = client.get("/operators/dashboard/home")

    assert home.status_code == 200
    assert home.json()["bootstrap"]["wallet_ready"] is True
    assert home.json()["bootstrap"]["endpoint_count"] == 1
    assert home.json()["bootstrap"]["items"][0]["endpoint_id"] == created.endpoint.endpoint_id
    assert home.json()["bootstrap"]["next_step"] == "Review your configured endpoint and publish it"


def test_operator_dashboard_home_exposes_endpoint_pipeline_create_action() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    client = TestClient(build_app(service=hypervisor))

    home = client.get("/operators/dashboard/home")

    assert home.status_code == 200
    payload = home.json()
    assert payload["endpoint_pipeline"]["state"] == "no_endpoint"
    assert payload["endpoint_pipeline"]["primary_endpoint_id"] is None
    assert payload["endpoint_pipeline"]["recommended_action"]["action"] == "create"
    assert payload["onboarding"]["recommended_action"]["action"] == "create"


def test_operator_dashboard_home_endpoint_pipeline_uses_endpoints_for_draft_follow_up() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Draft STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    client = TestClient(build_app(service=hypervisor, endpoint_service=endpoint_service))

    payload = client.get("/operators/dashboard/home").json()

    assert payload["endpoint_pipeline"]["state"] == "draft_exists"
    assert payload["endpoint_pipeline"]["recommended_action"]["workspace"] == "endpoints"
    assert payload["onboarding"]["recommended_action"]["action"] == "endpoints"


def test_operator_dashboard_home_endpoint_pipeline_uses_endpoints_for_in_sync_management() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Published STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
        node_id=hypervisor.node_id,
        wallet_private_key=hypervisor.owner_wallet_private_key(),
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    payload = client.get("/operators/dashboard/home").json()

    assert payload["endpoint_pipeline"]["state"] == "published_in_sync"
    assert payload["endpoint_pipeline"]["recommended_action"]["action"] == "endpoints"
    assert payload["endpoint_pipeline"]["recommended_action"]["workspace"] == "endpoints"


def test_operator_dashboard_home_preserves_completion_history_while_recommending_create() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    hypervisor.sync_operator_onboarding_state(endpoint_items=[{"publication_status": "published"}])
    client = TestClient(build_app(service=hypervisor))

    home = client.get("/operators/dashboard/home")

    assert home.status_code == 200
    payload = home.json()
    assert payload["onboarding"]["completed"] is True
    assert payload["onboarding"]["completed_at"] is not None
    assert payload["onboarding"]["completed_via"] == "first_local_endpoint_published"
    assert payload["endpoint_pipeline"]["state"] == "no_endpoint"
    assert payload["endpoint_pipeline"]["recommended_action"]["action"] == "create"
    assert payload["onboarding"]["recommended_action"]["action"] == "create"


def test_operator_dashboard_home_shell_highlights_publish_configuration_recommendation() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'recommendation.action === "create" ? "action-focus" : ""' in response.text
    assert 'recommendation.action === "publish-configuration" ? "action-focus" : ""' in response.text


def test_operator_dashboard_home_targets_drifted_endpoint_over_older_in_sync_endpoint() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    older_in_sync = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Older In Sync",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=older_in_sync.endpoint.endpoint_id,
        owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
        node_id=hypervisor.node_id,
        wallet_private_key=hypervisor.owner_wallet_private_key(),
    )
    newer_drifted = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Newer Drifted",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=newer_drifted.endpoint.endpoint_id,
        owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
        node_id=hypervisor.node_id,
        wallet_private_key=hypervisor.owner_wallet_private_key(),
    )
    endpoint_service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=newer_drifted.endpoint.endpoint_id,
            runtime={"streaming": True},
        )
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    home = client.get("/operators/dashboard/home")

    assert home.status_code == 200
    payload = home.json()
    assert payload["endpoint_pipeline"]["state"] == "published_drifted"
    assert payload["endpoint_pipeline"]["primary_endpoint_id"] == newer_drifted.endpoint.endpoint_id
    assert payload["endpoint_pipeline"]["primary_endpoint_id"] != older_in_sync.endpoint.endpoint_id


def test_operator_dashboard_home_shell_uses_endpoint_pipeline_primary_endpoint_id_for_home_actions() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "state.payloads.home?.endpoint_pipeline?.primary_endpoint_id" in response.text
    assert "function homeActionEndpointDraft()" in response.text


def test_create_endpoint_api_refreshes_onboarding_state() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    client = TestClient(build_app(service=hypervisor, endpoint_service=endpoint_service))

    response = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": hypervisor.owner_wallet_state()["wallet_id"],
            "bundle_id": "whisper-a",
            "bundle_hash": "whisper-a",
            "display_name": "Operator STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
        },
    )

    assert response.status_code == 201
    assert response.json()["data"]["onboarding"]["current_step"] == "publish_endpoint"
    assert hypervisor.operator_onboarding_state()["current_step"] == "publish_endpoint"


def test_operator_dashboard_home_route_uses_operator_view_payload(
    monkeypatch,
) -> None:
    hypervisor = _service()
    expected_payload = {
        "bootstrap": {
            "wallet_ready": False,
            "node_identity": {"node_id": "node-from-operator-view"},
        },
        "market_preview": {"candidate_count": 2},
    }
    captured: dict[str, object] = {}

    def fake_build_market_payload(*, service, registry_service) -> dict:
        captured["market_args"] = {
            "service": service,
            "registry_service": registry_service,
        }
        return {"candidates": [{"bundle_id": "whisper-a"}, {"bundle_id": "text-a"}]}

    def fake_build_operator_home_payload(**kwargs) -> dict:
        captured["view_args"] = kwargs
        return expected_payload

    monkeypatch.setattr("aidn_hypervisor.api.build_market_payload", fake_build_market_payload)
    monkeypatch.setattr(
        "aidn_hypervisor.api.build_operator_home_payload",
        fake_build_operator_home_payload,
    )
    client = TestClient(build_app(service=hypervisor))

    response = client.get("/operators/dashboard/home")

    assert response.status_code == 200
    assert response.json() == expected_payload
    assert captured["market_args"] == {
        "service": hypervisor,
        "registry_service": None,
    }
    assert captured["view_args"]["service"] is hypervisor
    assert captured["view_args"]["market_candidates"] == [
        {"bundle_id": "whisper-a"},
        {"bundle_id": "text-a"},
    ]
    assert "endpoint_service" in captured["view_args"]
    assert "endpoint_publication_service" in captured["view_args"]
    assert "validation_service" in captured["view_args"]


def test_operator_dashboard_endpoints_route_uses_endpoint_first_payload(
    monkeypatch,
) -> None:
    hypervisor = _service()
    endpoint_service = EndpointService(EndpointStore())
    expected_payload = {
        "owner_wallet": {"configured": False},
        "summary": {"total": 0},
        "items": [],
    }
    captured: dict[str, object] = {}

    def fake_build_operator_endpoints_payload(**kwargs) -> dict:
        captured["view_args"] = kwargs
        return expected_payload

    monkeypatch.setattr(
        "aidn_hypervisor.api.build_operator_endpoints_payload",
        fake_build_operator_endpoints_payload,
    )
    client = TestClient(build_app(service=hypervisor, endpoint_service=endpoint_service))

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    assert response.json() == expected_payload
    assert captured["view_args"]["service"] is hypervisor
    assert captured["view_args"]["endpoint_service"] is endpoint_service
    assert "endpoint_publication_service" in captured["view_args"]
    assert "validation_service" in captured["view_args"]


def test_operator_dashboard_providers_route_returns_workspace_payload(
    monkeypatch,
) -> None:
    hypervisor = _service()
    endpoint_service = EndpointService(EndpointStore())
    expected_payload = {
        "summary": {"total": 1},
        "items": [{"plugin_id": "fake-managed"}],
    }
    captured: dict[str, object] = {}

    def fake_build_operator_providers_payload(**kwargs) -> dict:
        captured["view_args"] = kwargs
        return expected_payload

    monkeypatch.setattr(
        "aidn_hypervisor.api.build_operator_providers_payload",
        fake_build_operator_providers_payload,
    )
    client = TestClient(build_app(service=hypervisor, endpoint_service=endpoint_service))

    response = client.get("/operators/dashboard/providers")

    assert response.status_code == 200
    assert response.json() == expected_payload
    assert captured["view_args"]["service"] is hypervisor
    assert captured["view_args"]["endpoint_service"] is endpoint_service
    assert "endpoint_publication_service" in captured["view_args"]
    assert "validation_service" in captured["view_args"]


def test_operator_dashboard_providers_route_returns_plugin_first_inventory_payload() -> None:
    service = _service()
    attached = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    models = service.discover_provider_models(attached["provider_instance_id"])
    binding = service.create_runtime_binding(
        model_deployment_id=models[0]["model_deployment_id"],
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )
    client = TestClient(build_app(service=service))

    payload = client.get("/operators/dashboard/providers").json()

    assert payload["plugin_directory"][0]["plugin_id"] == "fake-managed"
    assert payload["plugin_directory"][0]["package_verification"]["status"] == "VERIFIED"
    assert payload["installation_executor"]["executor_id"] == "sandbox-enforced-declarative-v1"
    assert payload["installation_executor"]["sandbox_capabilities"]["supported_execution_modes"] == [
        "RECORDED_ONLY",
        "SANDBOX_REQUIRED",
    ]
    assert payload["provider_instances"][0]["provider_instance_id"] == attached["provider_instance_id"]
    assert payload["provider_instances"][0]["model_count"] == 1
    assert payload["provider_instances"][0]["runtime_binding_ready_count"] == 1
    assert payload["model_deployments"][0]["model_deployment_id"] == models[0]["model_deployment_id"]
    assert payload["runtime_bindings"][0]["runtime_binding_id"] == binding["runtime_binding_id"]


def test_operator_dashboard_providers_payload_prefers_endpoint_handoff_when_supply_is_ready() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    client = TestClient(build_app(service=hypervisor))

    payload = client.get("/operators/dashboard/providers").json()

    assert payload["summary"]["recommended_action"]["workspace"] == "endpoints"
    assert payload["summary"]["recommended_action"]["action"] in {
        "create_endpoint",
        "open_endpoint",
    }
    assert payload["items"][0]["endpoint_readiness"]["state"] in {
        "ready_for_endpoint_creation",
        "already_backing_endpoint_supply",
    }


def test_operator_dashboard_providers_payload_marks_provider_as_backing_existing_endpoint() -> None:
    hypervisor = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(
                cpu_cores=8.0,
                ram_mb=16384,
                gpu_devices=["gpu0"],
                vram_mb={"gpu0": 8192},
            )
        ),
        bundles=[_bundle("whisper-a", "speech_to_text", endpoint="http://127.0.0.1:9000")],
        plugins=PluginRegistry(),
        runtimes=[],
    )
    hypervisor.plugins.register(FakeManagedPlugin())
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Endpoint-backed STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    client = TestClient(build_app(service=hypervisor, endpoint_service=endpoint_service))

    payload = client.get("/operators/dashboard/providers").json()
    first = payload["items"][0]

    assert first["endpoint_readiness"]["state"] == "already_backing_endpoint_supply"
    assert first["endpoint_readiness"]["recommended_action"]["action"] == "open_endpoint"
    assert first["endpoint_readiness"]["recommended_action"]["endpoint_id"] == created.endpoint.endpoint_id


def test_operator_dashboard_providers_payload_counts_endpoint_ready_bundles() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(
                cpu_cores=8.0,
                ram_mb=16384,
                gpu_devices=["gpu0"],
                vram_mb={"gpu0": 8192},
            )
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text"),
            _bundle("text-a", "llm_text"),
            _bundle("text-b", "llm_text"),
        ],
        plugins=PluginRegistry(),
        runtimes=[],
    )
    service.plugins.register(FakeManagedPlugin())
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Published STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    client = TestClient(build_app(service=service, endpoint_service=endpoint_service))

    payload = client.get("/operators/dashboard/providers").json()

    assert payload["summary"]["bundles"] == 3
    assert payload["summary"]["endpoint_ready_bundles"] == 2


def test_operator_dashboard_providers_payload_prefers_create_when_provider_has_mixed_endpoint_supply() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Claimed STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    client = TestClient(build_app(service=hypervisor, endpoint_service=endpoint_service))

    payload = client.get("/operators/dashboard/providers").json()
    first = payload["items"][0]

    assert first["endpoint_readiness"]["state"] == "mixed_endpoint_supply"
    assert first["endpoint_readiness"]["recommended_action"]["action"] == "create_endpoint"
    assert first["endpoint_readiness"]["recommended_action"]["workspace"] == "endpoints"
    assert payload["summary"]["recommended_action"]["action"] == "create_endpoint"
    assert payload["summary"]["endpoint_ready_bundles"] == 2
    assert created.endpoint.endpoint_id is not None


def test_provider_inventory_operator_routes_attach_discover_and_bind() -> None:
    service = _service()
    client = TestClient(build_app(service=service))

    plugins_response = client.get("/operators/provider-plugins")
    assert plugins_response.status_code == 200
    assert plugins_response.json()["items"][0]["plugin_id"] == "fake-managed"
    assert plugins_response.json()["items"][0]["package_verification"]["status"] == "VERIFIED"

    attach_response = client.post(
        "/operators/provider-instances/attach",
        json={
            "plugin_id": "fake-managed",
            "display_name": "Local Fake",
            "configuration": {"base_url": "http://127.0.0.1:9999"},
        },
    )
    assert attach_response.status_code == 200
    attached = attach_response.json()
    assert attached["plugin_id"] == "fake-managed"

    discover_response = client.post(f"/operators/provider-instances/{attached['provider_instance_id']}/discover-models")
    assert discover_response.status_code == 200
    models = discover_response.json()["items"]
    assert models[0]["provider_instance_id"] == attached["provider_instance_id"]

    binding_response = client.post(
        f"/operators/model-deployments/{models[0]['model_deployment_id']}/runtime-bindings",
        json={
            "capability_id": "llm.chat",
            "capability_version": "1.0.0",
            "capability_definition_hash": "cap-hash",
        },
    )
    assert binding_response.status_code == 200
    binding = binding_response.json()

    compatibility_bundle = next(
        bundle for bundle in service.bundles if bundle.bundle_id == binding["compatibility_bundle_id"]
    )
    assert compatibility_bundle.workload_type == "llm.chat"
    assert compatibility_bundle.endpoint == "http://127.0.0.1:9999"


def test_provider_inventory_runtime_binding_route_requires_materialized_artifacts(
    tmp_path,
) -> None:
    service = _service()
    service.provider_inventory = ProviderInventoryService(
        plugins=service.plugins,
        store=InMemoryProviderInventoryStore(),
        installation_executor=ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root"),
    )
    client = TestClient(build_app(service=service))

    upload_response = client.post(
        "/operators/provider-installation-artifacts",
        json={
            "relative_path": "models/fake-model.gguf",
            "content_base64": base64.b64encode(b"model-bytes").decode("ascii"),
        },
    )
    assert upload_response.status_code == 200
    artifact_response = client.post(
        "/operators/model-artifacts/promote",
        json={"relative_path": "models/fake-model.gguf"},
    )
    assert artifact_response.status_code == 200
    artifact_set_response = client.post(
        "/operators/model-artifact-sets",
        json={
            "display_name": "Fake model package",
            "files": [
                {
                    "relative_path": "weights/fake-model.gguf",
                    "artifact_id": artifact_response.json()["artifact_id"],
                    "role": "WEIGHTS",
                }
            ],
        },
    )
    assert artifact_set_response.status_code == 200

    attach_response = client.post(
        "/operators/provider-instances/attach",
        json={
            "plugin_id": "fake-managed",
            "display_name": "Local Fake",
            "configuration": {"base_url": "http://127.0.0.1:9999"},
        },
    )
    assert attach_response.status_code == 200
    provider_instance_id = attach_response.json()["provider_instance_id"]
    models_response = client.post(f"/operators/provider-instances/{provider_instance_id}/discover-models")
    assert models_response.status_code == 200
    model_deployment_id = models_response.json()["items"][0]["model_deployment_id"]

    bind_response = client.post(
        f"/operators/model-deployments/{model_deployment_id}/artifact-set",
        json={"artifact_set_id": artifact_set_response.json()["artifact_set_id"]},
    )
    assert bind_response.status_code == 200

    binding_response = client.post(
        f"/operators/model-deployments/{model_deployment_id}/runtime-bindings",
        json={
            "capability_id": "llm.chat",
            "capability_version": "1.0.0",
            "capability_definition_hash": "cap-hash",
        },
    )

    assert binding_response.status_code == 409
    assert "artifact set must be materialized" in binding_response.json()["detail"]


def test_provider_plugin_release_routes_record_local_installation_without_execution() -> None:
    service = _service()
    client = TestClient(build_app(service=service))
    manifest = service.plugins.get("fake-managed").plugin_manifest()

    register_response = client.post(
        "/operators/provider-plugin-releases",
        json={
            "manifest": manifest,
            "source_reference": "registry://plugins/fake-managed",
        },
    )

    assert register_response.status_code == 200
    release = register_response.json()
    assert release["release_status"] == "AVAILABLE"
    assert client.get("/operators/provider-plugin-releases").json()["items"] == [release]

    install_response = client.post(
        f"/operators/provider-plugin-releases/{release['release_id']}/install",
        json={"granted_permissions": release["declared_permissions"]},
    )

    assert install_response.status_code == 200
    installed_plugin = install_response.json()
    assert installed_plugin["release_id"] == release["release_id"]
    assert installed_plugin["state"] == "INSTALLED"
    assert client.get("/operators/installed-provider-plugins").json()["items"] == [installed_plugin]


def test_plugin_host_status_route_returns_sanitized_observability() -> None:
    service = _service()
    client = TestClient(build_app(service=service))

    response = client.get("/operators/plugin-host/status")

    assert response.status_code == 200
    assert response.json() == {
        "active_connection_count": 0,
        "connections": [],
        "listener_count": 0,
        "listener_transports": [],
    }


def test_provider_inventory_operator_routes_reject_malformed_payloads() -> None:
    client = TestClient(build_app(service=_service()))

    attach_response = client.post(
        "/operators/provider-instances/attach",
        json={
            "plugin_id": "fake-managed",
            "display_name": "Local Fake",
        },
    )
    assert attach_response.status_code == 422

    binding_response = client.post(
        "/operators/model-deployments/md-missing/runtime-bindings",
        json={
            "capability_id": "llm.chat",
        },
    )
    assert binding_response.status_code == 422

    extra_field_response = client.post(
        "/operators/provider-instances/attach",
        json={
            "plugin_id": "fake-managed",
            "display_name": "Local Fake",
            "configuration": {"base_url": "http://127.0.0.1:9999"},
            "unexpected": True,
        },
    )
    assert extra_field_response.status_code == 422

    plan_extra_field_response = client.post(
        "/operators/provider-plugins/fake-managed/installation-plan",
        json={
            "configuration": {"base_url": "http://127.0.0.1:9999"},
            "unexpected": True,
        },
    )
    assert plan_extra_field_response.status_code == 422

    approval_extra_field_response = client.post(
        "/operators/provider-plugins/fake-managed/installation-approvals",
        json={
            "configuration": {"base_url": "http://127.0.0.1:9999"},
            "approved_permissions": ["network.private"],
            "operator_note": "approve",
            "unexpected": True,
        },
    )
    assert approval_extra_field_response.status_code == 422

    approval_response = client.post(
        "/operators/provider-plugins/fake-managed/installation-approvals",
        json={
            "configuration": {"base_url": "http://127.0.0.1:9999"},
            "approved_permissions": ["network.private"],
            "operator_note": "approve",
        },
    )
    assert approval_response.status_code == 200

    apply_note_response = client.post(
        f"/operators/provider-installation-approvals/{approval_response.json()['approval_id']}/apply",
        json={"operator_note": "apply"},
    )
    assert apply_note_response.status_code == 422


def test_provider_plugin_installation_plan_preview_route() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/provider-plugins/fake-managed/installation-plan",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plugin_id"] == "fake-managed"
    assert body["unsupported_actions"] == []
    assert body["health_checks"][0]["type"] == "http"


def test_provider_installation_approval_and_apply_routes() -> None:
    service = _service()
    client = TestClient(build_app(service=service))

    approval_response = client.post(
        "/operators/provider-plugins/fake-managed/installation-approvals",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
            "approved_permissions": ["network.private"],
            "selected_secret_handles": [
                {
                    "requirement_key": "API_KEY:Optional provider API key handle",
                    "secret_handle": "secret://providers/fake-managed/api-key",
                }
            ],
            "operator_note": "approved from api",
        },
    )

    assert approval_response.status_code == 200
    approval = approval_response.json()
    assert approval["plugin_id"] == "fake-managed"
    assert approval["operator_note"] == "approved from api"
    assert approval["upgrade_review"]["status"] == "INITIAL_APPROVAL"
    assert approval["upgrade_acknowledged"] is False
    assert approval["acknowledged_sandbox_policy"]["execution_mode"] == "RECORDED_ONLY"
    assert approval["selected_secret_handles"][0]["secret_handle"] == "secret://providers/fake-managed/api-key"

    apply_response = client.post(
        f"/operators/provider-installation-approvals/{approval['approval_id']}/apply",
        json={},
    )

    assert apply_response.status_code == 200
    job = apply_response.json()
    assert job["approval_id"] == approval["approval_id"]
    assert job["status"] == "SUCCEEDED"
    assert job["executor_id"] == "sandbox-enforced-declarative-v1"
    assert job["provider_instance_id"].startswith("pi-")
    assert job["rollback_status"] == "NOT_REQUIRED"
    assert "rollback is not required" in (job["rollback_summary"] or "")

    jobs_response = client.get("/operators/provider-installation-jobs")
    assert jobs_response.status_code == 200
    listed_job = jobs_response.json()["items"][0]
    assert listed_job["job_id"] == job["job_id"]
    assert listed_job["provider_instance_id"] == job["provider_instance_id"]

    approvals_response = client.get("/operators/provider-installation-approvals")
    assert approvals_response.status_code == 200
    assert approvals_response.json()["items"][0]["approval_id"] == approval["approval_id"]


def test_provider_installation_job_rollback_route() -> None:
    service = _service()
    client = TestClient(build_app(service=service))

    approval_response = client.post(
        "/operators/provider-plugins/fake-managed/installation-approvals",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
            "approved_permissions": ["network.private"],
        },
    )
    approval = approval_response.json()
    apply_response = client.post(
        f"/operators/provider-installation-approvals/{approval['approval_id']}/apply",
        json={},
    )
    job = apply_response.json()

    rollback_response = client.post(
        f"/operators/provider-installation-jobs/{job['job_id']}/rollback",
        json={},
    )

    assert rollback_response.status_code == 200
    rolled_back = rollback_response.json()
    assert rolled_back["job_id"] == job["job_id"]
    assert rolled_back["rollback_status"] == "COMPLETED"
    assert rolled_back["rollback_step_results"][-1]["step_id"] == ("rollback-delete-local-provider-instance")


def test_provider_installation_job_rollback_route_rejects_unknown_job() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/provider-installation-jobs/job-missing/rollback",
        json={},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown installation job: job-missing"


def test_provider_installation_apply_route_rejects_unknown_approval() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/provider-installation-approvals/approval-missing/apply",
        json={},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown approval: approval-missing"


def test_provider_installation_approval_route_rejects_incomplete_permission_acknowledgement() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/provider-plugins/fake-managed/installation-approvals",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
            "approved_permissions": [],
            "operator_note": "approve",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "approved permissions must match requested permissions exactly"


def test_provider_installation_routes_require_upgrade_acknowledgement_for_changed_contract() -> None:
    class MutablePermissionPlugin(FakeManagedPlugin):
        plugin_id = "mutable-permissions"

        def __init__(self) -> None:
            self.required_permissions = [
                {
                    "permission_id": "network.private",
                    "label": "Private network",
                    "risk_level": "low",
                    "reason": "Connect to a local fake provider endpoint",
                }
            ]

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["required_permissions"] = list(self.required_permissions)
            return description

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            plan["required_permissions"] = list(self.required_permissions)
            return plan

    service = _service()
    plugin = MutablePermissionPlugin()
    service.plugins.register(plugin)
    client = TestClient(build_app(service=service))

    first_approval = client.post(
        "/operators/provider-plugins/mutable-permissions/installation-approvals",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
            "approved_permissions": ["network.private"],
        },
    )
    assert first_approval.status_code == 200

    plugin.required_permissions = [
        *plugin.required_permissions,
        {
            "permission_id": "filesystem.write",
            "label": "Filesystem write",
            "risk_level": "medium",
            "reason": "Write provider files into a controlled location",
        },
    ]

    diagnostics_response = client.post(
        "/operators/provider-plugins/mutable-permissions/installation-diagnostics",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
            "approved_permissions": ["network.private", "filesystem.write"],
        },
    )
    assert diagnostics_response.status_code == 200
    diagnostics = diagnostics_response.json()
    assert diagnostics["readiness_status"] == "BLOCKED"
    upgrade_check = next(check for check in diagnostics["checks"] if check["check_id"] == "upgrade_review")
    assert upgrade_check["status"] == "FAIL"
    assert upgrade_check["details"]["status"] == "CHANGED"
    assert upgrade_check["details"]["added_permissions"] == ["filesystem.write"]

    approval_response = client.post(
        "/operators/provider-plugins/mutable-permissions/installation-approvals",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
            "approved_permissions": ["network.private", "filesystem.write"],
        },
    )
    assert approval_response.status_code == 409
    assert "requires explicit upgrade acknowledgement" in approval_response.json()["detail"]

    acknowledged_response = client.post(
        "/operators/provider-plugins/mutable-permissions/installation-approvals",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
            "approved_permissions": ["network.private", "filesystem.write"],
            "upgrade_acknowledged": True,
        },
    )
    assert acknowledged_response.status_code == 200
    assert acknowledged_response.json()["upgrade_review"]["status"] == "CHANGED"
    assert acknowledged_response.json()["upgrade_acknowledged"] is True


def test_provider_installation_diagnostics_route_returns_readiness_and_rollback_preview() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/provider-plugins/fake-managed/installation-diagnostics",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
            "approved_permissions": ["network.private"],
            "selected_secret_handles": [
                {
                    "requirement_key": "API_KEY:Optional provider API key handle",
                    "secret_handle": "secret://providers/fake-managed/api-key",
                }
            ],
        },
    )

    assert response.status_code == 200
    diagnostics = response.json()
    assert diagnostics["plugin_id"] == "fake-managed"
    assert diagnostics["readiness_status"] == "READY"
    assert diagnostics["executor_id"] == "sandbox-enforced-declarative-v1"
    assert diagnostics["rollback_result"]["status"] == "NOT_REQUIRED"
    package_check = next(check for check in diagnostics["checks"] if check["check_id"] == "package_verification")
    assert package_check["status"] == "PASS"
    assert any(check["check_id"] == "rollback_preview" for check in diagnostics["checks"])


def test_provider_installation_diagnostics_route_surfaces_blocked_state_without_failing_request() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/provider-plugins/fake-managed/installation-diagnostics",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
            "approved_permissions": [],
        },
    )

    assert response.status_code == 200
    diagnostics = response.json()
    assert diagnostics["readiness_status"] == "BLOCKED"
    permission_check = next(check for check in diagnostics["checks"] if check["check_id"] == "permissions_acknowledged")
    assert permission_check["status"] == "FAIL"


def test_provider_installation_diagnostics_route_surfaces_missing_local_import_artifacts(
    tmp_path,
) -> None:
    service = _service()
    service.plugins.register(LocalImportApiPlugin())
    service.provider_inventory = ProviderInventoryService(
        plugins=service.plugins,
        store=InMemoryProviderInventoryStore(),
        installation_executor=ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root"),
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/operators/provider-plugins/controlled-fs-import-api/installation-diagnostics",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
            "approved_permissions": ["network.private", "filesystem.controlled_path"],
            "selected_secret_handles": [
                {
                    "requirement_key": "API_KEY:Optional provider API key handle",
                    "secret_handle": "secret://providers/controlled-fs-import-api/api-key",
                }
            ],
        },
    )

    assert response.status_code == 200
    diagnostics = response.json()
    assert diagnostics["readiness_status"] == "BLOCKED"
    import_check = next(check for check in diagnostics["checks"] if check["check_id"] == "local_import_artifacts")
    assert import_check["status"] == "FAIL"
    assert import_check["details"]["missing_local_import_count"] == 1


def test_provider_installation_diagnostics_route_surfaces_ready_local_import_artifacts(
    tmp_path,
) -> None:
    service = _service()
    service.plugins.register(LocalImportApiPlugin())
    imports_root = tmp_path / "executor-root" / "imports" / "models"
    imports_root.mkdir(parents=True, exist_ok=True)
    (imports_root / "fake-model.gguf").write_text("fake-model-bytes", encoding="utf-8")
    service.provider_inventory = ProviderInventoryService(
        plugins=service.plugins,
        store=InMemoryProviderInventoryStore(),
        installation_executor=ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root"),
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/operators/provider-plugins/controlled-fs-import-api/installation-diagnostics",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
            "approved_permissions": ["network.private", "filesystem.controlled_path"],
            "selected_secret_handles": [
                {
                    "requirement_key": "API_KEY:Optional provider API key handle",
                    "secret_handle": "secret://providers/controlled-fs-import-api/api-key",
                }
            ],
        },
    )

    assert response.status_code == 200
    diagnostics = response.json()
    assert diagnostics["readiness_status"] == "READY"
    import_check = next(check for check in diagnostics["checks"] if check["check_id"] == "local_import_artifacts")
    assert import_check["status"] == "PASS"
    assert import_check["details"]["ready_local_import_count"] == 1


def test_provider_installation_artifact_routes_stage_list_and_remove_artifacts(
    tmp_path,
) -> None:
    service = _service()
    service.provider_inventory = ProviderInventoryService(
        plugins=service.plugins,
        store=InMemoryProviderInventoryStore(),
        installation_executor=ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root"),
    )
    client = TestClient(build_app(service=service))

    create_response = client.post(
        "/operators/provider-installation-artifacts",
        json={
            "relative_path": "models/fake-model.gguf",
            "content_base64": base64.b64encode(b"fake-model-bytes").decode("ascii"),
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["relative_path"] == "models/fake-model.gguf"
    assert created["size_bytes"] == len(b"fake-model-bytes")

    list_response = client.get("/operators/provider-installation-artifacts")
    assert list_response.status_code == 200
    inventory = list_response.json()
    assert inventory["supported"] is True
    assert inventory["items"][0]["relative_path"] == "models/fake-model.gguf"

    delete_response = client.post(
        "/operators/provider-installation-artifacts/remove",
        json={"relative_path": "models/fake-model.gguf"},
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {
        "relative_path": "models/fake-model.gguf",
        "deleted": True,
    }

    final_inventory = client.get("/operators/provider-installation-artifacts").json()
    assert final_inventory["items"] == []


def test_provider_installation_artifact_extract_route_unpacks_staged_archive(
    tmp_path,
) -> None:
    service = _service()
    service.provider_inventory = ProviderInventoryService(
        plugins=service.plugins,
        store=InMemoryProviderInventoryStore(),
        installation_executor=ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root"),
    )
    client = TestClient(build_app(service=service))

    create_response = client.post(
        "/operators/provider-installation-artifacts",
        json={
            "relative_path": "archives/fake-model.zip",
            "content_base64": base64.b64encode(
                _zip_bytes(
                    {
                        "weights/model.gguf": b"fake-model-bytes",
                        "metadata/config.json": b'{"name":"fake"}',
                    }
                )
            ).decode("ascii"),
        },
    )

    assert create_response.status_code == 200

    extract_response = client.post(
        "/operators/provider-installation-artifacts/extract",
        json={
            "archive_relative_path": "archives/fake-model.zip",
            "destination_directory": "models/fake-model",
        },
    )

    assert extract_response.status_code == 200
    extracted = extract_response.json()
    assert extracted["archive_relative_path"] == "archives/fake-model.zip"
    assert extracted["destination_directory"] == "models/fake-model"
    assert extracted["extracted_file_count"] == 2
    assert "models/fake-model/weights/model.gguf" in extracted["extracted_relative_paths"]

    inventory = client.get("/operators/provider-installation-artifacts").json()
    paths = {item["relative_path"] for item in inventory["items"]}
    assert "archives/fake-model.zip" in paths
    assert "models/fake-model/weights/model.gguf" in paths
    assert "models/fake-model/metadata/config.json" in paths


def test_model_artifact_routes_promote_deduplicate_and_remove_staged_artifacts(
    tmp_path,
) -> None:
    service = _service()
    service.provider_inventory = ProviderInventoryService(
        plugins=service.plugins,
        store=InMemoryProviderInventoryStore(),
        installation_executor=ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root"),
    )
    client = TestClient(build_app(service=service))
    content_base64 = base64.b64encode(b"shared-model-bytes").decode("ascii")

    for relative_path in ["models/first.gguf", "models/second.gguf"]:
        response = client.post(
            "/operators/provider-installation-artifacts",
            json={"relative_path": relative_path, "content_base64": content_base64},
        )
        assert response.status_code == 200

    first = client.post(
        "/operators/model-artifacts/promote",
        json={"relative_path": "models/first.gguf"},
    )
    second = client.post(
        "/operators/model-artifacts/promote",
        json={"relative_path": "models/second.gguf"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["artifact_id"] == second.json()["artifact_id"]

    inventory = client.get("/operators/model-artifacts")
    assert inventory.status_code == 200
    assert inventory.json()["supported"] is True
    assert len(inventory.json()["items"]) == 1

    artifact_id = first.json()["artifact_id"]
    remove = client.post(
        "/operators/model-artifacts/remove",
        json={"artifact_id": artifact_id},
    )
    assert remove.status_code == 200
    assert remove.json() == {"artifact_id": artifact_id, "deleted": True}
    assert client.get("/operators/model-artifacts").json()["items"] == []


def test_model_artifact_set_routes_create_and_list_sets(tmp_path) -> None:
    service = _service()
    service.provider_inventory = ProviderInventoryService(
        plugins=service.plugins,
        store=InMemoryProviderInventoryStore(),
        installation_executor=ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root"),
    )
    client = TestClient(build_app(service=service))
    client.post(
        "/operators/provider-installation-artifacts",
        json={
            "relative_path": "models/fake-model.gguf",
            "content_base64": base64.b64encode(b"model-bytes").decode("ascii"),
        },
    )
    artifact = client.post(
        "/operators/model-artifacts/promote",
        json={"relative_path": "models/fake-model.gguf"},
    ).json()

    created = client.post(
        "/operators/model-artifact-sets",
        json={
            "display_name": "Fake model package",
            "files": [
                {
                    "relative_path": "weights/fake-model.gguf",
                    "artifact_id": artifact["artifact_id"],
                    "role": "WEIGHTS",
                }
            ],
        },
    )

    assert created.status_code == 200
    listed = client.get("/operators/model-artifact-sets")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["artifact_set_id"] == created.json()["artifact_set_id"]


def test_model_artifact_collect_route_starts_grace_tracking(tmp_path) -> None:
    service = _service()
    service.provider_inventory = ProviderInventoryService(
        plugins=service.plugins,
        store=InMemoryProviderInventoryStore(),
        installation_executor=ControlledFilesystemProviderInstallationExecutor(
            tmp_path / "executor-root",
            model_artifact_gc_grace_seconds=0,
        ),
    )
    client = TestClient(build_app(service=service))
    client.post(
        "/operators/provider-installation-artifacts",
        json={
            "relative_path": "models/fake-model.gguf",
            "content_base64": base64.b64encode(b"model-bytes").decode("ascii"),
        },
    )
    client.post(
        "/operators/model-artifacts/promote",
        json={"relative_path": "models/fake-model.gguf"},
    )

    first = client.post("/operators/model-artifacts/collect")
    second = client.post("/operators/model-artifacts/collect")

    assert first.status_code == 200
    assert len(first.json()["pending_artifact_ids"]) == 1
    assert second.status_code == 200
    assert len(second.json()["collected_artifact_ids"]) == 1


def test_provider_installation_artifact_route_rejects_invalid_base64() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/provider-installation-artifacts",
        json={
            "relative_path": "models/fake-model.gguf",
            "content_base64": "%%%not-base64%%%",
        },
    )

    assert response.status_code == 422
    assert "Invalid base64 artifact content" in response.json()["detail"]


def test_provider_plugin_installation_plan_preview_route_rejects_invalid_plugin_plan() -> None:
    service = _service()
    service.plugins.register(BadInstallationPlanPlugin())
    client = TestClient(build_app(service=service))

    response = client.post(
        "/operators/provider-plugins/bad-plan/installation-plan",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            }
        },
    )

    assert response.status_code == 409
    assert "declarative-only" in response.json()["detail"]


def test_provider_plugin_installation_plan_preview_route_rejects_attach_only_plugin() -> None:
    service = _service()
    service.plugins.register(AttachOnlyInstallationPlanPlugin())
    client = TestClient(build_app(service=service))

    response = client.post(
        "/operators/provider-plugins/attach-only/installation-plan",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            }
        },
    )

    assert response.status_code == 409
    assert "does not support managed installation" in response.json()["detail"]


def test_operator_dashboard_bundles_route_returns_workspace_payload(
    monkeypatch,
) -> None:
    hypervisor = _service()
    endpoint_service = EndpointService(EndpointStore())
    expected_payload = {
        "summary": {"total": 2},
        "items": [{"bundle_id": "whisper-a"}],
    }
    captured: dict[str, object] = {}

    def fake_build_operator_bundles_payload(**kwargs) -> dict:
        captured["view_args"] = kwargs
        return expected_payload

    monkeypatch.setattr(
        "aidn_hypervisor.api.build_operator_bundles_payload",
        fake_build_operator_bundles_payload,
    )
    client = TestClient(build_app(service=hypervisor, endpoint_service=endpoint_service))

    response = client.get("/operators/dashboard/bundles")

    assert response.status_code == 200
    assert response.json() == expected_payload
    assert captured["view_args"]["service"] is hypervisor
    assert captured["view_args"]["endpoint_service"] is endpoint_service
    assert "endpoint_publication_service" in captured["view_args"]
    assert "validation_service" in captured["view_args"]


def test_operator_dashboard_bundles_payload_exposes_endpoint_relationship_contract() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    client = TestClient(build_app(service=hypervisor))

    payload = client.get("/operators/dashboard/bundles").json()
    first = payload["items"][0]

    assert first["endpoint_relationship"]["state"] == "no_endpoint"
    assert first["endpoint_relationship"]["recommended_action"]["workspace"] == "endpoints"
    assert first["endpoint_relationship"]["recommended_action"]["action"] == "create_endpoint"


def test_operator_dashboard_bundles_payload_marks_published_endpoint_relationship_in_sync() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Published STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
        node_id=hypervisor.node_id,
        wallet_private_key=hypervisor.owner_wallet_private_key(),
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    payload = client.get("/operators/dashboard/bundles").json()
    first = next(item for item in payload["items"] if item["bundle_id"] == "whisper-a")

    assert first["endpoint_relationship"]["state"] == "published_endpoint"
    assert first["endpoint_relationship"]["recommended_action"]["action"] == "open_endpoint"
    assert first["endpoint_relationship"]["recommended_action"]["endpoint_id"] == created.endpoint.endpoint_id


def test_operator_dashboard_bundles_payload_marks_published_endpoint_relationship_drifted() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Drifted STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
        node_id=hypervisor.node_id,
        wallet_private_key=hypervisor.owner_wallet_private_key(),
    )
    endpoint_service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            runtime={"streaming": True},
        )
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    payload = client.get("/operators/dashboard/bundles").json()
    first = next(item for item in payload["items"] if item["bundle_id"] == "whisper-a")

    assert first["endpoint_relationship"]["state"] == "published_drifted"
    assert first["endpoint_relationship"]["recommended_action"]["action"] == "open_endpoint"
    assert first["endpoint_relationship"]["recommended_action"]["label"] == "Republish In Endpoints"


def test_operator_dashboard_bundles_payload_marks_draft_endpoint_relationship() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Draft STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    client = TestClient(build_app(service=hypervisor, endpoint_service=endpoint_service))

    payload = client.get("/operators/dashboard/bundles").json()
    first = next(item for item in payload["items"] if item["bundle_id"] == "whisper-a")

    assert first["endpoint_relationship"]["state"] == "draft_endpoint"
    assert first["endpoint_relationship"]["recommended_action"]["action"] == "open_endpoint"
    assert first["endpoint_relationship"]["recommended_action"]["endpoint_id"] == created.endpoint.endpoint_id


def test_operator_dashboard_market_route_uses_operator_view_payload(
    monkeypatch,
) -> None:
    hypervisor = _service()
    registry = RegistryService()
    expected_payload = {
        "nodes": [],
        "candidates": [],
        "canonical_candidates": [],
        "canonical_summary": {},
    }
    captured: dict[str, object] = {}

    def fake_build_operator_market_payload(**kwargs) -> dict:
        captured["view_args"] = kwargs
        return expected_payload

    monkeypatch.setattr(
        "aidn_hypervisor.api.build_operator_market_payload",
        fake_build_operator_market_payload,
    )
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    response = client.get("/operators/dashboard/market")

    assert response.status_code == 200
    assert response.json() == expected_payload
    assert captured["view_args"]["service"] is hypervisor
    assert captured["view_args"]["registry_service"] is registry


def test_operator_dashboard_remote_endpoints_route_uses_operator_view_payload(
    monkeypatch,
) -> None:
    hypervisor = _service()
    registry = RegistryService()
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    expected_payload = {
        "summary": {"attached": 0, "discovered": 0},
        "attached": [],
        "discovered": [],
    }
    captured: dict[str, object] = {}

    def fake_build_operator_remote_endpoints_payload(**kwargs) -> dict:
        captured["view_args"] = kwargs
        return expected_payload

    monkeypatch.setattr(
        "aidn_hypervisor.api.build_operator_remote_endpoints_payload",
        fake_build_operator_remote_endpoints_payload,
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            registry_service=registry,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.get("/operators/dashboard/remote-endpoints")

    assert response.status_code == 200
    assert response.json() == expected_payload
    assert captured["view_args"]["service"] is hypervisor
    assert captured["view_args"]["registry_service"] is registry
    assert captured["view_args"]["remote_endpoint_service"] is remote_endpoint_service


def test_operator_dashboard_market_payload_includes_endpoint_first_recommended_action() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")

    payload = build_market_payload(service=hypervisor, registry_service=None)

    assert payload["recommended_action"]["action"] == "publish_local_endpoint"
    assert payload["recommended_action"]["workspace"] == "endpoints"


def test_operator_dashboard_remote_endpoints_route_includes_recommended_action() -> None:
    service = _service()
    registry = RegistryService()
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-remote",
            operator_id="operator-remote",
            base_url="https://remote.example",
            heartbeat_at="2026-07-06T12:00:00+00:00",
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
                "free": {"cpu": 10.0, "ram_mb": 28672, "vram_mb": 12288},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={"unit": "q_per_1kk_tokens", "input": 7, "output": 11, "fixed_request": 1},
            rating={"score": 0.98, "tier": "A", "updated_at": "2026-07-06T11:55:00+00:00"},
            bundles=[],
            published_endpoints=[
                {
                    "endpoint_id": "endpoint-remote",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-remote",
                    "current_publication_id": "pub-remote",
                    "current_configuration_hash": "cfg-remote",
                    "published_at": "2026-07-06T11:50:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                }
            ],
        )
    )
    client = TestClient(build_app(service=service, registry_service=registry))

    response = client.get("/operators/dashboard/remote-endpoints")

    assert response.status_code == 200
    assert response.json()["recommended_action"]["action"] == "attach_remote_endpoint"
    assert response.json()["recommended_action"]["workspace"] == "remote"


def test_operator_dashboard_installs_route_returns_actionable_install_state(
    monkeypatch,
) -> None:
    hypervisor = _service()
    expected_payload = {
        "summary": {"total": 1, "ready_to_register": 1},
        "items": [{"install_id": "install-1", "next_action": "register_bundle"}],
    }
    captured: dict[str, object] = {}

    def fake_build_operator_installs_payload(**kwargs) -> dict:
        captured["view_args"] = kwargs
        return expected_payload

    monkeypatch.setattr(
        "aidn_hypervisor.api.build_operator_installs_payload",
        fake_build_operator_installs_payload,
    )
    client = TestClient(build_app(service=hypervisor))

    response = client.get("/operators/dashboard/installs")

    assert response.status_code == 200
    assert response.json() == expected_payload
    assert captured["view_args"]["service"] is hypervisor


def test_owner_wallet_bootstrap_create_endpoint_returns_owner_state() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/wallet/bootstrap/create",
        json={"label": "Primary Wallet"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["wallet"]["configured"] is True
    assert body["wallet"]["label"] == "Primary Wallet"
    assert body["wallet"]["wallet_id"].startswith("wallet-")
    assert body["private_key"].startswith("ed25519:")
    assert body["wallet"]["public_key"].startswith("ed25519:")


def test_operator_dashboard_requests_endpoint_returns_grouped_payload() -> None:
    service = _service(with_runtime=False, use_process_manager=True, reserve_runtime=False)
    service.queue.enqueue(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "queued.wav"}))
    client = TestClient(build_app(service=service))

    response = client.get("/operators/dashboard/requests")

    assert response.status_code == 200
    assert "summary" in response.json()
    assert "queue" in response.json()
    assert "policy" in response.json()
    assert "market_spillover_preview" in response.json()


def test_operator_dashboard_requests_endpoint_includes_proxy_trace_on_task_rows() -> None:
    class StubRemoteHypervisorTransport:
        def request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
            if method == "POST" and url == "http://remote-hv/tasks":
                return {
                    "task_id": "remote-task-1",
                    "status": "queued",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                }
            if method == "GET" and url == "http://remote-hv/tasks/remote-task-1":
                return {
                    "task_id": "remote-task-1",
                    "status": "completed",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                    "result": {
                        "ok": True,
                        "output_text": "hello from remote",
                    },
                }
            raise AssertionError(f"unexpected proxy request: {method} {url}")

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, gpu_devices=["gpu0"], vram_mb={"gpu0": 4096})
        ),
        bundles=[_bundle("text-a", "llm_text", priority_class=100)],
        plugins=PluginRegistry(),
        runtimes=ProviderProcessManager(),
    )
    service.plugins.register(FakeManagedPlugin())
    endpoint_service = EndpointService(EndpointStore())
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-remote",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="http://remote-hv",
        operator_id="operator-remote",
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-06-30T00:00:00+00:00"},
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Proxy Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    service.endpoint_service = endpoint_service
    service.remote_endpoint_service = remote_endpoint_service
    service.remote_transport = StubRemoteHypervisorTransport()
    service.proxy_poll_attempts = 1
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"endpoint_id": created.endpoint.endpoint_id},
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.get("/operators/dashboard/requests")

    assert response.status_code == 200
    assert response.json()["recent"][0]["proxy_trace"]["remote_endpoint_id"] == "ep-remote"
    assert response.json()["recent"][0]["proxy_trace"]["remote_node_id"] == "node-remote"


def test_operator_dashboard_endpoints_endpoint_returns_endpoint_control_payload() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "shared",
                "discoverable": True,
                "accepts_external_requests": True,
                "shared_with_wallet_ids": ["wallet-a"],
            },
        )
    )
    endpoint_service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            validation={
                "enabled": True,
                "model_class_supported": True,
                "verification_status": "pending",
            },
        )
    )
    client = TestClient(build_app(service=service, endpoint_service=endpoint_service))

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 1
    assert response.json()["summary"]["validation_requested"] == 1
    assert response.json()["items"][0]["visibility"] == "shared"
    assert response.json()["items"][0]["shared_with_wallet_ids"] == ["wallet-a"]
    assert response.json()["items"][0]["mvp_paid_smoke"]["profile"] == "MVP-0001"
    assert response.json()["items"][0]["mvp_paid_smoke"]["route"].endswith("/mvp-paid-smoke")
    assert response.json()["items"][0]["mvp_paid_smoke"]["default_task_type"] == "audio.transcribe"
    assert response.json()["items"][0]["mvp_paid_smoke"]["accounting_mode"] == "FIXED_PRICE"
    assert response.json()["policy"]["publish_requires_validation"] is False


def test_operator_dashboard_endpoints_payload_exposes_session_policy() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Paid STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 2,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    client = TestClient(build_app(service=service, endpoint_service=endpoint_service))

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    assert response.json()["items"][0]["session"]["minimum_deposit"] == 10.0
    assert response.json()["items"][0]["session"]["max_concurrent_sessions"] == 2


def test_operator_dashboard_sessions_endpoint_returns_operator_session_summary() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Paid STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "queue",
                "minimum_session_fee": 2.0,
            },
        )
    )
    first = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-a",
        provider_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        deposit_q=10.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    )
    session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-b",
        provider_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        deposit_q=10.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    )
    session_service.close_session(first.session.session_id)
    session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-c",
        provider_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        deposit_q=10.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.get("/operators/dashboard/sessions")

    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 3
    assert response.json()["summary"]["active"] == 1
    assert response.json()["summary"]["queued"] == 1
    assert response.json()["summary"]["closed"] == 1
    assert response.json()["items"][0]["display_name"] == "Paid STT"
    assert response.json()["items"][0]["deposit"]["locked_q"] == 10.0
    assert response.json()["items"][0]["session"]["endpoint_id"] == created.endpoint.endpoint_id


def test_operator_dashboard_sessions_endpoint_exposes_mvp_force_refund_eligibility_fields() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    service.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=1_000)
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Paid STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    opened, _, funding = service.open_mvp_fixed_price_session(
        session_service=session_service,
        endpoint=created.endpoint,
        client_wallet="wallet-consumer",
        deposit_q_atoms=1_000,
        fixed_price_q_atoms=900,
        network_fee_reserve_q_atoms=100,
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.get("/operators/dashboard/sessions")
    item = response.json()["items"][0]

    assert response.status_code == 200
    assert item["session"]["session_id"] == opened.session_id
    assert item["session"]["economic_profile"] == "MVP-0001"
    assert item["session"]["request_count"] == 0
    assert item["session"]["canonical_funding_state_hash"] == funding.funding_state_hash


def test_operator_dashboard_sessions_endpoint_includes_related_task_telemetry() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="whisper-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    session = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=10.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    ).session
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )
    submitted = client.post(
        "/tasks",
        json={
            "task_type": "audio.transcribe",
            "payload": {"audio_ref": "clip.wav"},
            "constraints": {
                "endpoint_id": created.endpoint.endpoint_id,
                "session_id": session.session_id,
            },
        },
    ).json()

    response = client.get("/operators/dashboard/sessions")

    body = response.json()

    assert response.status_code == 200
    assert body["items"][0]["related_tasks"][0]["task_id"] == submitted["task_id"]
    assert body["items"][0]["related_tasks"][0]["session_id"] == session.session_id
    assert body["items"][0]["activity"][0]["event_type"]
    assert (
        body["items"][0]["activity"][0]["task_id"] == submitted["task_id"]
        or body["items"][0]["activity"][0]["details"].get("session_id") == session.session_id
    )


def test_operator_dashboard_sessions_endpoint_exposes_proxy_session_binding() -> None:
    class StubPaidRemoteHypervisorTransport:
        def request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
            if method == "POST" and url == "http://remote-hv/api/v1/endpoints/ep-remote/sessions":
                return {
                    "session": {
                        "session_id": "remote-session-1",
                        "opened_at": "2026-07-02T00:00:00+00:00",
                    }
                }
            if method == "POST" and url == "http://remote-hv/tasks":
                return {
                    "task_id": "remote-task-1",
                    "status": "queued",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                }
            if method == "GET" and url == "http://remote-hv/tasks/remote-task-1":
                return {
                    "task_id": "remote-task-1",
                    "status": "completed",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                    "result": {
                        "ok": True,
                        "task_type": "llm_text.generate",
                        "output_text": "hello from remote",
                    },
                }
            raise AssertionError(f"unexpected proxy request: {method} {url}")

    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-remote",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="http://remote-hv",
        operator_id="operator-remote",
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-06-30T00:00:00+00:00"},
        session_policy={"minimum_deposit": 10.0},
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Proxy Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    )
    service.remote_transport = StubPaidRemoteHypervisorTransport()
    service.proxy_poll_attempts = 1
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )
    client.post(
        "/tasks",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "hello"},
            "constraints": {
                "endpoint_id": created.endpoint.endpoint_id,
                "session_id": opened.session.session_id,
            },
        },
    )

    response = client.get("/operators/dashboard/sessions")

    assert response.status_code == 200
    assert response.json()["items"][0]["proxy_session"]["remote_session_id"] == "remote-session-1"
    assert response.json()["items"][0]["proxy_session"]["status"] == "active"


def test_operator_dashboard_sessions_endpoint_includes_settlement_preview() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="whisper-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=10.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    )
    session_service.record_usage_charge(opened.session.session_id, amount_q=3.0)
    session_service.store.save_session(
        session_service.get_session(opened.session.session_id).session.model_copy(
            update={
                "last_activity_at": (datetime.now(UTC) - timedelta(minutes=4)).isoformat(),
                "idle_deadline_at": (datetime.now(UTC) + timedelta(minutes=6)).isoformat(),
            }
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.get("/operators/dashboard/sessions")

    body = response.json()
    preview = body["items"][0]["settlement_preview"]

    assert response.status_code == 200
    assert preview["usage_charged_q"] == 3.0
    assert preview["network_fee_q"] == 0.01
    assert preview["idle_exposure_q"] > 0.0
    assert preview["projected_charged_q"] >= 3.01
    assert preview["projected_refundable_q"] < 7.0
    assert preview["seconds_until_idle_timeout"] > 0


def test_operator_dashboard_session_close_action_closes_selected_session() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    session_store = SessionStore()
    session_service = SessionService(session_store)
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Paid STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-a",
        provider_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        deposit_q=10.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.post(
        "/operators/dashboard/sessions/actions/close",
        json={"session_id": opened.session.session_id},
    )

    body = response.json()

    assert response.status_code == 200
    assert body["data"]["session"]["session_id"] == opened.session.session_id
    assert body["data"]["session"]["status"] == "closed"
    assert body["data"]["deposit"]["status"] == "released"
    assert body["data"]["settlement"]["charged_q"] == 2.01
    assert body["data"]["settlement"]["network_fee_q"] == 0.01


def test_operator_dashboard_session_close_action_propagates_proxy_session_close() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    session_store = SessionStore()
    session_service = SessionService(session_store)
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Proxy Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-a",
        provider_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    )
    session_service.save_proxy_session_binding(
        ProxySessionBinding(
            local_session_id=opened.session.session_id,
            remote_endpoint_id="ep-remote",
            remote_session_id="remote-session-1",
            remote_node_id="node-remote",
            source_base_url="http://remote-hv",
            status="active",
            opened_at="2026-07-02T00:00:00+00:00",
        )
    )
    service.session_service = session_service
    service.remote_transport = _StubRemoteSessionCloseTransport()
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.post(
        "/operators/dashboard/sessions/actions/close",
        json={"session_id": opened.session.session_id},
    )

    assert response.status_code == 200
    assert (
        "POST",
        "http://remote-hv/api/v1/sessions/remote-session-1/close",
        None,
    ) in service.remote_transport.calls
    assert session_service.get_proxy_session_binding(opened.session.session_id).close_status == "closed"


def test_public_session_close_endpoint_propagates_proxy_session_close() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    session_store = SessionStore()
    session_service = SessionService(session_store)
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Proxy Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-a",
        provider_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    )
    session_service.save_proxy_session_binding(
        ProxySessionBinding(
            local_session_id=opened.session.session_id,
            remote_endpoint_id="ep-remote",
            remote_session_id="remote-session-1",
            remote_node_id="node-remote",
            source_base_url="http://remote-hv",
            status="active",
            opened_at="2026-07-02T00:00:00+00:00",
        )
    )
    service.session_service = session_service
    service.remote_transport = _StubRemoteSessionCloseTransport()
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.post(f"/api/v1/sessions/{opened.session.session_id}/close")

    assert response.status_code == 200
    assert (
        "POST",
        "http://remote-hv/api/v1/sessions/remote-session-1/close",
        None,
    ) in service.remote_transport.calls
    assert session_service.get_proxy_session_binding(opened.session.session_id).close_status == "closed"


def test_post_session_usage_reports_returns_ack_pending_checkpoint_view() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    service.endpoint_service = endpoint_service
    service.session_service = session_service
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            pricing={"billing_unit": "token", "input_price": 12.0},
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
        accounting_contract=service.accounting_contract_for_endpoint(created.endpoint),
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )
    usage_report = {
        "report_id": "report-1",
        "report_version": "0.1",
        "session_id": opened.session.session_id,
        "endpoint_id": created.endpoint.endpoint_id,
        "capability_id": "llm_text.generate",
        "pricing_version": "pricing-v1",
        "accounting_contract_version": "acct-v1",
        "accounting_modes": {"input_tokens": "provider_metered"},
        "sequence": 1,
        "cumulative_usage": {"input_tokens": 250_000},
        "measurement_sources": {"input_tokens": "provider_api"},
        "created_at": "2026-07-12T12:00:00+00:00",
        "signature": "local:report-1",
    }
    expected_report_head = UsageReport.model_validate(usage_report).model_dump(mode="json")

    response = client.post(
        f"/api/v1/sessions/{opened.session.session_id}/usage-reports",
        json={
            "usage_report": usage_report,
            "acknowledgement_timeout_seconds": 30,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["session_accounting"] == {
        "session_id": opened.session.session_id,
        "status": "ack_pending",
        "checkpoint": {
            "last_report_id": "report-1",
            "last_report_sequence": 1,
            "last_report_hash": usage_report_hash(UsageReport.model_validate(usage_report)),
            "last_ack_sequence": None,
            "last_ack_hash": None,
            "last_accepted_report_sequence": None,
            "last_accepted_report_id": None,
            "last_accepted_report_hash": None,
            "accounting_contract_hash": opened.session.accounting_contract_hash,
            "last_accepted_usage_charged_q": 0.0,
            "mismatch_open": False,
            "ack_deadline_at": "2026-07-12T12:00:30+00:00",
        },
        "report_head": expected_report_head,
        "acknowledgement_head": {},
    }


def test_post_session_usage_acknowledgements_advances_accepted_checkpoint() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    service.endpoint_service = endpoint_service
    service.session_service = session_service
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            pricing={"billing_unit": "token", "input_price": 12.0},
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
        accounting_contract=service.accounting_contract_for_endpoint(created.endpoint),
    )
    usage_report = {
        "report_id": "report-1",
        "report_version": "0.1",
        "session_id": opened.session.session_id,
        "endpoint_id": created.endpoint.endpoint_id,
        "capability_id": "llm_text.generate",
        "pricing_version": "pricing-v1",
        "accounting_contract_version": "acct-v1",
        "accounting_modes": {"input_tokens": "provider_metered"},
        "sequence": 1,
        "cumulative_usage": {"input_tokens": 250_000},
        "measurement_sources": {"input_tokens": "provider_api"},
        "created_at": "2026-07-12T12:00:00+00:00",
        "signature": "local:report-1",
    }
    expected_report_head = UsageReport.model_validate(usage_report).model_dump(mode="json")
    session_service.record_usage_report(
        opened.session.session_id,
        usage_report=usage_report,
        acknowledgement_timeout_seconds=30,
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )
    usage_acknowledgement = {
        "session_id": opened.session.session_id,
        "sequence": 1,
        "provider_report_hash": usage_report_hash(UsageReport.model_validate(usage_report)),
        "verification_status": "accepted_unverified",
        "signature": "local-ack:report-1",
    }
    expected_acknowledgement_head = UsageAcknowledgement.model_validate(usage_acknowledgement).model_dump(mode="json")

    response = client.post(
        f"/api/v1/sessions/{opened.session.session_id}/usage-acknowledgements",
        json={
            "usage_acknowledgement": usage_acknowledgement,
            "accepted_charge_q": 3.5,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["session_accounting"] == {
        "session_id": opened.session.session_id,
        "status": "open",
        "checkpoint": {
            "last_report_id": "report-1",
            "last_report_sequence": 1,
            "last_report_hash": usage_report_hash(UsageReport.model_validate(usage_report)),
            "last_ack_sequence": 1,
            "last_ack_hash": usage_acknowledgement_hash(UsageAcknowledgement.model_validate(usage_acknowledgement)),
            "last_accepted_report_sequence": 1,
            "last_accepted_report_id": "report-1",
            "last_accepted_report_hash": usage_report_hash(UsageReport.model_validate(usage_report)),
            "accounting_contract_hash": opened.session.accounting_contract_hash,
            "last_accepted_usage_charged_q": 3.5,
            "mismatch_open": False,
            "ack_deadline_at": None,
        },
        "report_head": expected_report_head,
        "acknowledgement_head": expected_acknowledgement_head,
    }


def test_post_session_usage_acknowledgements_replay_is_idempotent() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    service.endpoint_service = endpoint_service
    service.session_service = session_service
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            pricing={"billing_unit": "token", "input_price": 12.0},
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
        accounting_contract=service.accounting_contract_for_endpoint(created.endpoint),
    )
    usage_report = {
        "report_id": "report-1",
        "report_version": "0.1",
        "session_id": opened.session.session_id,
        "endpoint_id": created.endpoint.endpoint_id,
        "capability_id": "llm_text.generate",
        "pricing_version": "pricing-v1",
        "accounting_contract_version": "acct-v1",
        "accounting_modes": {"input_tokens": "provider_metered"},
        "sequence": 1,
        "cumulative_usage": {"input_tokens": 250_000},
        "measurement_sources": {"input_tokens": "provider_api"},
        "created_at": "2026-07-12T12:00:00+00:00",
        "signature": "local:report-1",
    }
    expected_report_head = UsageReport.model_validate(usage_report).model_dump(mode="json")
    session_service.record_usage_report(
        opened.session.session_id,
        usage_report=usage_report,
        acknowledgement_timeout_seconds=30,
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )
    usage_acknowledgement = {
        "session_id": opened.session.session_id,
        "sequence": 1,
        "provider_report_hash": usage_report_hash(UsageReport.model_validate(usage_report)),
        "verification_status": "accepted_unverified",
        "signature": "local-ack:report-1",
    }
    expected_acknowledgement_head = UsageAcknowledgement.model_validate(usage_acknowledgement).model_dump(mode="json")
    expected_accounting = {
        "session_id": opened.session.session_id,
        "status": "open",
        "checkpoint": {
            "last_report_id": "report-1",
            "last_report_sequence": 1,
            "last_report_hash": usage_report_hash(UsageReport.model_validate(usage_report)),
            "last_ack_sequence": 1,
            "last_ack_hash": usage_acknowledgement_hash(UsageAcknowledgement.model_validate(usage_acknowledgement)),
            "last_accepted_report_sequence": 1,
            "last_accepted_report_id": "report-1",
            "last_accepted_report_hash": usage_report_hash(UsageReport.model_validate(usage_report)),
            "accounting_contract_hash": opened.session.accounting_contract_hash,
            "last_accepted_usage_charged_q": 3.5,
            "mismatch_open": False,
            "ack_deadline_at": None,
        },
        "report_head": expected_report_head,
        "acknowledgement_head": expected_acknowledgement_head,
    }

    first_response = client.post(
        f"/api/v1/sessions/{opened.session.session_id}/usage-acknowledgements",
        json={
            "usage_acknowledgement": usage_acknowledgement,
            "accepted_charge_q": 3.5,
        },
    )
    replay_response = client.post(
        f"/api/v1/sessions/{opened.session.session_id}/usage-acknowledgements",
        json={
            "usage_acknowledgement": usage_acknowledgement,
            "accepted_charge_q": 3.5,
        },
    )
    accounting_response = client.get(f"/api/v1/sessions/{opened.session.session_id}/accounting")

    assert first_response.status_code == 200
    assert replay_response.status_code == 200
    assert replay_response.json()["data"]["session_accounting"] == expected_accounting
    assert accounting_response.status_code == 200
    assert accounting_response.json()["data"]["session_accounting"] == expected_accounting


def test_post_session_usage_acknowledgements_replay_conflicts_on_different_accepted_charge() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    service.endpoint_service = endpoint_service
    service.session_service = session_service
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            pricing={"billing_unit": "token", "input_price": 12.0},
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
        accounting_contract=service.accounting_contract_for_endpoint(created.endpoint),
    )
    usage_report = {
        "report_id": "report-1",
        "report_version": "0.1",
        "session_id": opened.session.session_id,
        "endpoint_id": created.endpoint.endpoint_id,
        "capability_id": "llm_text.generate",
        "pricing_version": "pricing-v1",
        "accounting_contract_version": "acct-v1",
        "accounting_modes": {"input_tokens": "provider_metered"},
        "sequence": 1,
        "cumulative_usage": {"input_tokens": 250_000},
        "measurement_sources": {"input_tokens": "provider_api"},
        "created_at": "2026-07-12T12:00:00+00:00",
        "signature": "local:report-1",
    }
    expected_report_head = UsageReport.model_validate(usage_report).model_dump(mode="json")
    session_service.record_usage_report(
        opened.session.session_id,
        usage_report=usage_report,
        acknowledgement_timeout_seconds=30,
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )
    usage_acknowledgement = {
        "session_id": opened.session.session_id,
        "sequence": 1,
        "provider_report_hash": usage_report_hash(UsageReport.model_validate(usage_report)),
        "verification_status": "accepted_unverified",
        "signature": "local-ack:report-1",
    }
    expected_acknowledgement_head = UsageAcknowledgement.model_validate(usage_acknowledgement).model_dump(mode="json")
    expected_accounting = {
        "session_id": opened.session.session_id,
        "status": "open",
        "checkpoint": {
            "last_report_id": "report-1",
            "last_report_sequence": 1,
            "last_report_hash": usage_report_hash(UsageReport.model_validate(usage_report)),
            "last_ack_sequence": 1,
            "last_ack_hash": usage_acknowledgement_hash(UsageAcknowledgement.model_validate(usage_acknowledgement)),
            "last_accepted_report_sequence": 1,
            "last_accepted_report_id": "report-1",
            "last_accepted_report_hash": usage_report_hash(UsageReport.model_validate(usage_report)),
            "accounting_contract_hash": opened.session.accounting_contract_hash,
            "last_accepted_usage_charged_q": 3.5,
            "mismatch_open": False,
            "ack_deadline_at": None,
        },
        "report_head": expected_report_head,
        "acknowledgement_head": expected_acknowledgement_head,
    }

    first_response = client.post(
        f"/api/v1/sessions/{opened.session.session_id}/usage-acknowledgements",
        json={
            "usage_acknowledgement": usage_acknowledgement,
            "accepted_charge_q": 3.5,
        },
    )
    conflicting_replay_response = client.post(
        f"/api/v1/sessions/{opened.session.session_id}/usage-acknowledgements",
        json={
            "usage_acknowledgement": usage_acknowledgement,
            "accepted_charge_q": 9.5,
        },
    )
    accounting_response = client.get(f"/api/v1/sessions/{opened.session.session_id}/accounting")

    assert first_response.status_code == 200
    assert conflicting_replay_response.status_code == 409
    assert conflicting_replay_response.json()["error"]["code"] == "session_accounting_conflict"
    assert accounting_response.status_code == 200
    assert accounting_response.json()["data"]["session_accounting"] == expected_accounting


def test_post_session_usage_reports_returns_422_for_invalid_nested_payload() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    service.endpoint_service = endpoint_service
    service.session_service = session_service
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            pricing={"billing_unit": "token", "input_price": 12.0},
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
        accounting_contract=service.accounting_contract_for_endpoint(created.endpoint),
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.post(
        f"/api/v1/sessions/{opened.session.session_id}/usage-reports",
        json={
            "usage_report": {
                "report_version": "0.1",
                "session_id": opened.session.session_id,
                "endpoint_id": created.endpoint.endpoint_id,
                "sequence": "bad-sequence",
                "created_at": "2026-07-12T12:00:00+00:00",
                "signature": "local:report-1",
            },
            "acknowledgement_timeout_seconds": 30,
        },
    )

    assert response.status_code == 422


def test_post_session_usage_acknowledgements_returns_422_for_invalid_nested_payload() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    service.endpoint_service = endpoint_service
    service.session_service = session_service
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            pricing={"billing_unit": "token", "input_price": 12.0},
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
        accounting_contract=service.accounting_contract_for_endpoint(created.endpoint),
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.post(
        f"/api/v1/sessions/{opened.session.session_id}/usage-acknowledgements",
        json={
            "usage_acknowledgement": {
                "session_id": opened.session.session_id,
                "sequence": "bad-sequence",
                "verification_status": "accepted_unverified",
                "signature": "local-ack:report-1",
            },
            "accepted_charge_q": 3.5,
        },
    )

    assert response.status_code == 422


def test_post_session_usage_reports_returns_409_for_broken_chain_continuity() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    service.endpoint_service = endpoint_service
    service.session_service = session_service
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            pricing={"billing_unit": "token", "input_price": 12.0},
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
        accounting_contract=service.accounting_contract_for_endpoint(created.endpoint),
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )
    first_report = {
        "report_id": "report-1",
        "report_version": "0.1",
        "session_id": opened.session.session_id,
        "endpoint_id": created.endpoint.endpoint_id,
        "capability_id": "llm_text.generate",
        "pricing_version": "pricing-v1",
        "accounting_contract_version": "acct-v1",
        "accounting_modes": {"input_tokens": "provider_metered"},
        "sequence": 1,
        "cumulative_usage": {"input_tokens": 250_000},
        "measurement_sources": {"input_tokens": "provider_api"},
        "created_at": "2026-07-12T12:00:00+00:00",
        "signature": "local:report-1",
    }
    broken_report = {
        "report_id": "report-2",
        "report_version": "0.1",
        "session_id": opened.session.session_id,
        "endpoint_id": created.endpoint.endpoint_id,
        "capability_id": "llm_text.generate",
        "pricing_version": "pricing-v1",
        "accounting_contract_version": "acct-v1",
        "accounting_modes": {"input_tokens": "provider_metered"},
        "sequence": 3,
        "cumulative_usage": {"input_tokens": 350_000},
        "measurement_sources": {"input_tokens": "provider_api"},
        "created_at": "2026-07-12T12:01:00+00:00",
        "signature": "local:report-2",
    }
    expected_broken_report_head = UsageReport.model_validate(broken_report).model_dump(mode="json")
    first_response = client.post(
        f"/api/v1/sessions/{opened.session.session_id}/usage-reports",
        json={
            "usage_report": first_report,
            "acknowledgement_timeout_seconds": 30,
        },
    )
    assert first_response.status_code == 200

    response = client.post(
        f"/api/v1/sessions/{opened.session.session_id}/usage-reports",
        json={
            "usage_report": broken_report,
            "acknowledgement_timeout_seconds": 30,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_accounting_conflict"
    assert response.json()["error"]["details"]["session_accounting"] == {
        "session_id": opened.session.session_id,
        "status": "mismatch",
        "checkpoint": {
            "last_report_id": "report-1",
            "last_report_sequence": 1,
            "last_report_hash": usage_report_hash(UsageReport.model_validate(first_report)),
            "last_ack_sequence": None,
            "last_ack_hash": None,
            "last_accepted_report_sequence": None,
            "last_accepted_report_id": None,
            "last_accepted_report_hash": None,
            "accounting_contract_hash": opened.session.accounting_contract_hash,
            "last_accepted_usage_charged_q": 0.0,
            "mismatch_open": True,
            "ack_deadline_at": "2026-07-12T12:00:30+00:00",
        },
        "report_head": expected_broken_report_head,
        "acknowledgement_head": {},
    }


def test_post_session_usage_acknowledgements_returns_409_for_report_hash_mismatch() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    service.endpoint_service = endpoint_service
    service.session_service = session_service
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            pricing={"billing_unit": "token", "input_price": 12.0},
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
        accounting_contract=service.accounting_contract_for_endpoint(created.endpoint),
    )
    usage_report = {
        "report_id": "report-1",
        "report_version": "0.1",
        "session_id": opened.session.session_id,
        "endpoint_id": created.endpoint.endpoint_id,
        "capability_id": "llm_text.generate",
        "pricing_version": "pricing-v1",
        "accounting_contract_version": "acct-v1",
        "accounting_modes": {"input_tokens": "provider_metered"},
        "sequence": 1,
        "cumulative_usage": {"input_tokens": 250_000},
        "measurement_sources": {"input_tokens": "provider_api"},
        "created_at": "2026-07-12T12:00:00+00:00",
        "signature": "local:report-1",
    }
    expected_report_head = UsageReport.model_validate(usage_report).model_dump(mode="json")
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )
    session_service.record_usage_report(
        opened.session.session_id,
        usage_report=usage_report,
        acknowledgement_timeout_seconds=30,
    )
    mismatched_acknowledgement = {
        "session_id": opened.session.session_id,
        "sequence": 1,
        "provider_report_hash": "sha256:not-the-current-head",
        "verification_status": "accepted_unverified",
        "signature": "local-ack:report-1",
    }
    expected_acknowledgement_head = UsageAcknowledgement.model_validate(mismatched_acknowledgement).model_dump(
        mode="json"
    )

    response = client.post(
        f"/api/v1/sessions/{opened.session.session_id}/usage-acknowledgements",
        json={
            "usage_acknowledgement": mismatched_acknowledgement,
            "accepted_charge_q": 3.5,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_accounting_conflict"
    assert response.json()["error"]["details"]["session_accounting"] == {
        "session_id": opened.session.session_id,
        "status": "mismatch",
        "checkpoint": {
            "last_report_id": "report-1",
            "last_report_sequence": 1,
            "last_report_hash": usage_report_hash(UsageReport.model_validate(usage_report)),
            "last_ack_sequence": 1,
            "last_ack_hash": usage_acknowledgement_hash(
                UsageAcknowledgement.model_validate(mismatched_acknowledgement)
            ),
            "last_accepted_report_sequence": None,
            "last_accepted_report_id": None,
            "last_accepted_report_hash": None,
            "accounting_contract_hash": opened.session.accounting_contract_hash,
            "last_accepted_usage_charged_q": 0.0,
            "mismatch_open": True,
            "ack_deadline_at": "2026-07-12T12:00:30+00:00",
        },
        "report_head": expected_report_head,
        "acknowledgement_head": expected_acknowledgement_head,
    }


def test_get_session_accounting_returns_canonical_read_model() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    service.endpoint_service = endpoint_service
    service.session_service = session_service
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            pricing={"billing_unit": "token", "input_price": 12.0},
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
        accounting_contract=service.accounting_contract_for_endpoint(created.endpoint),
    )
    usage_report = {
        "report_id": "report-1",
        "report_version": "0.1",
        "session_id": opened.session.session_id,
        "endpoint_id": created.endpoint.endpoint_id,
        "capability_id": "llm_text.generate",
        "pricing_version": "pricing-v1",
        "accounting_contract_version": "acct-v1",
        "accounting_modes": {"input_tokens": "provider_metered"},
        "sequence": 1,
        "cumulative_usage": {"input_tokens": 250_000},
        "measurement_sources": {"input_tokens": "provider_api"},
        "created_at": "2026-07-12T12:00:00+00:00",
        "signature": "local:report-1",
    }
    expected_report_head = UsageReport.model_validate(usage_report).model_dump(mode="json")
    usage_acknowledgement = {
        "session_id": opened.session.session_id,
        "sequence": 1,
        "provider_report_hash": usage_report_hash(UsageReport.model_validate(usage_report)),
        "verification_status": "accepted_unverified",
        "signature": "local-ack:report-1",
    }
    expected_acknowledgement_head = UsageAcknowledgement.model_validate(usage_acknowledgement).model_dump(mode="json")
    session_service.record_usage_report(
        opened.session.session_id,
        usage_report=usage_report,
        acknowledgement_timeout_seconds=30,
    )
    session_service.record_usage_acknowledgement(
        opened.session.session_id,
        usage_acknowledgement=usage_acknowledgement,
        accepted_charge_q=3.5,
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.get(f"/api/v1/sessions/{opened.session.session_id}/accounting")

    assert response.status_code == 200
    assert response.json()["data"]["session_accounting"] == {
        "session_id": opened.session.session_id,
        "status": "open",
        "checkpoint": {
            "last_report_id": "report-1",
            "last_report_sequence": 1,
            "last_report_hash": usage_report_hash(UsageReport.model_validate(usage_report)),
            "last_ack_sequence": 1,
            "last_ack_hash": usage_acknowledgement_hash(UsageAcknowledgement.model_validate(usage_acknowledgement)),
            "last_accepted_report_sequence": 1,
            "last_accepted_report_id": "report-1",
            "last_accepted_report_hash": usage_report_hash(UsageReport.model_validate(usage_report)),
            "accounting_contract_hash": opened.session.accounting_contract_hash,
            "last_accepted_usage_charged_q": 3.5,
            "mismatch_open": False,
            "ack_deadline_at": None,
        },
        "report_head": expected_report_head,
        "acknowledgement_head": expected_acknowledgement_head,
    }


def test_session_endpoints_do_not_expose_internal_accounting_replay_metadata() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    service.endpoint_service = endpoint_service
    service.session_service = session_service
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            pricing={"billing_unit": "token", "input_price": 12.0},
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
        accounting_contract=service.accounting_contract_for_endpoint(created.endpoint),
    )
    usage_report = {
        "report_id": "report-1",
        "report_version": "0.1",
        "session_id": opened.session.session_id,
        "endpoint_id": created.endpoint.endpoint_id,
        "capability_id": "llm_text.generate",
        "pricing_version": "pricing-v1",
        "accounting_contract_version": "acct-v1",
        "accounting_modes": {"input_tokens": "provider_metered"},
        "sequence": 1,
        "cumulative_usage": {"input_tokens": 250_000},
        "measurement_sources": {"input_tokens": "provider_api"},
        "created_at": "2026-07-12T12:00:00+00:00",
        "signature": "local:report-1",
    }
    session_service.record_usage_report(
        opened.session.session_id,
        usage_report=usage_report,
        acknowledgement_timeout_seconds=30,
    )
    session_service.record_usage_acknowledgement(
        opened.session.session_id,
        usage_acknowledgement={
            "session_id": opened.session.session_id,
            "sequence": 1,
            "provider_report_hash": "sha256:wrong",
            "verification_status": "mismatch",
            "signature": "local-ack:report-1",
        },
        accepted_charge_q=3.5,
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    detail_response = client.get(f"/api/v1/sessions/{opened.session.session_id}")
    list_response = client.get("/api/v1/sessions")

    assert detail_response.status_code == 200
    assert list_response.status_code == 200
    detail_session = detail_response.json()["data"]["session"]
    listed_session = list_response.json()["data"]["items"][0]
    assert "_accepted_charge_q" not in detail_session["last_usage_acknowledgement_snapshot"]
    assert "_accepted_charge_q" not in listed_session["last_usage_acknowledgement_snapshot"]
    assert "_accepted_charge_q" not in detail_session["usage_acknowledgement_chain"][0]
    assert "_accepted_charge_q" not in listed_session["usage_acknowledgement_chain"][0]


def test_session_detail_exposes_session_contract_object_references() -> None:
    registry_service = RegistryService()
    session_service = SessionService(SessionStore(), registry_service=registry_service)
    service = _service(with_runtime=False, use_process_manager=True)
    client = TestClient(
        build_app(
            service=service,
            registry_service=registry_service,
            session_service=session_service,
        )
    )

    opened = session_service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id=service.node_id,
        deposit_q=10.0,
        session_policy={
            "minimum_deposit": 10.0,
            "recommended_deposit": 25.0,
            "idle_fee_per_minute": 1.0,
            "idle_timeout_seconds": 600,
            "max_concurrent_sessions": 1,
            "maximum_session_duration_seconds": 3600,
            "queue_policy": "busy",
            "minimum_session_fee": 2.0,
        },
        accounting_contract={
            "contract_version": "acct-v1",
            "pricing_version": "pricing-v1",
        },
        advertisement_id="adv-ep-1-v1",
        offer_id="offer-public",
        pricing_policy_hash="sha256:pricing-v1",
    )

    response = client.get(f"/api/v1/sessions/{opened.session.session_id}")

    assert response.status_code == 200
    session_payload = response.json()["data"]["session"]
    assert session_payload["session_contract_object_id"] == opened.session.session_contract_object_id
    assert session_payload["session_contract_object_version"] == "session-contract.v2"
    assert session_payload["endpoint_payment_beneficiary"] == "wallet-provider"
    assert session_payload["consumer_refund_beneficiary"] == "wallet-client"
    assert session_payload["session_contract_namespace"] == "session"


def test_operator_dashboard_session_sweep_action_closes_idle_sessions() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    session_store = SessionStore()
    session_service = SessionService(session_store)
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Paid STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-a",
        provider_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        deposit_q=10.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    )
    session_store.save_session(opened.session.model_copy(update={"idle_deadline_at": "2020-01-01T00:00:00+00:00"}))
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.post("/operators/dashboard/sessions/actions/sweep-idle", json={})

    body = response.json()

    assert response.status_code == 200
    assert body["data"]["closed_count"] == 1
    assert body["data"]["items"][0]["session"]["session_id"] == opened.session.session_id
    assert body["data"]["items"][0]["session"]["status"] == "closed"
    assert body["data"]["items"][0]["session"]["close_reason"] == "idle_timeout"


def test_operator_dashboard_session_sweep_action_propagates_proxy_session_close() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    session_store = SessionStore()
    session_service = SessionService(session_store)
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Proxy Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    opened = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-a",
        provider_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    )
    session_service.save_proxy_session_binding(
        ProxySessionBinding(
            local_session_id=opened.session.session_id,
            remote_endpoint_id="ep-remote",
            remote_session_id="remote-session-1",
            remote_node_id="node-remote",
            source_base_url="http://remote-hv",
            status="active",
            opened_at="2026-07-02T00:00:00+00:00",
        )
    )
    session_store.save_session(opened.session.model_copy(update={"idle_deadline_at": "2020-01-01T00:00:00+00:00"}))
    service.session_service = session_service
    service.remote_transport = _StubRemoteSessionCloseTransport()
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.post("/operators/dashboard/sessions/actions/sweep-idle", json={})

    assert response.status_code == 200
    assert (
        "POST",
        "http://remote-hv/api/v1/sessions/remote-session-1/close",
        None,
    ) in service.remote_transport.calls
    assert session_service.get_proxy_session_binding(opened.session.session_id).close_status == "closed"


def test_operator_dashboard_endpoints_endpoint_prefers_endpoint_service_payload_for_configured_endpoint() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            profile={"summary": "Speech endpoint tuned for transcription"},
            runtime={
                "context_length": 8192,
                "temperature": 0.2,
                "max_tokens": 1024,
                "timeout": 45,
                "streaming": True,
            },
            publication={
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a"],
                "discoverable": True,
            },
        )
    )
    endpoint_service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            runtime={
                "context_length": 16384,
                "temperature": 0.1,
                "max_tokens": 2048,
                "timeout": 60,
                "streaming": True,
            },
            validation={
                "enabled": True,
                "model_class_supported": True,
                "verification_status": "pending",
            },
        )
    )
    client = TestClient(build_app(service=service, endpoint_service=endpoint_service))

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 1
    assert response.json()["summary"]["configured"] == 1
    assert response.json()["summary"]["published"] == 0
    assert response.json()["summary"]["shared"] == 1
    assert response.json()["summary"]["validation_requested"] == 1
    assert response.json()["items"][0]["endpoint_id"] == created.endpoint.endpoint_id
    assert response.json()["items"][0]["visibility"] == "shared"
    assert response.json()["items"][0]["shared_with_wallet_ids"] == ["wallet-a"]
    assert response.json()["items"][0]["profile"]["summary"] == "Speech endpoint tuned for transcription"
    assert response.json()["items"][0]["runtime"]["context_length"] == 16384
    assert response.json()["items"][0]["runtime"]["temperature"] == 0.1
    assert response.json()["items"][0]["runtime"]["max_tokens"] == 2048
    assert response.json()["items"][0]["runtime"]["timeout"] == 60
    assert response.json()["items"][0]["runtime"]["streaming"] is True
    assert len(response.json()["items"][0]["configuration_snapshots"]) == 2
    assert (
        response.json()["items"][0]["configuration_snapshots"][0]["configuration_hash"]
        == created.endpoint.configuration_hash
    )
    assert response.json()["items"][0]["configuration_snapshots"][1]["runtime"]["context_length"] == 16384
    assert response.json()["items"][0]["configuration_snapshots"][1]["runtime"]["timeout"] == 60
    assert response.json()["items"][0]["publication_status"] == "configured"
    assert response.json()["items"][0]["current_publication"] is None


def test_operator_dashboard_endpoints_payload_exposes_proxy_strategy() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-external",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-b",
        pricing={"unit": "q_per_1kk_tokens", "input": 9, "output": 15},
        rating={"score": 0.97, "tier": "A", "updated_at": "2026-06-20T11:55:00Z"},
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["execution_strategy"] == "proxy"
    assert item["proxy_target"]["remote_endpoint_id"] == attached.remote_endpoint_id


def test_publish_configuration_endpoint_returns_signed_record() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )
    validation_service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-02T00:00:00+00:00",
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
            validation_service=validation_service,
        )
    )

    response = client.post(f"/api/v1/endpoints/{created.endpoint.endpoint_id}/publish-configuration")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["publication"]["endpoint_id"] == created.endpoint.endpoint_id
    assert body["data"]["publication"]["owner_wallet"] == service.owner_wallet_state()["wallet_id"]
    assert body["data"]["publication"]["wallet_signature"]
    assert body["data"]["validation_summary"]["validation_status"] == "validated"
    assert body["data"]["validation_summary"]["configuration_hash"] == created.endpoint.configuration_hash


def test_publish_configuration_returns_readiness_blockers() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Private External STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "private",
                "accepts_external_requests": True,
            },
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.post(f"/api/v1/endpoints/{created.endpoint.endpoint_id}/publish-configuration")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "endpoint_publication_blocked"
    assert error["details"]["ready"] is False
    assert error["details"]["blockers"][0]["code"] == "ENDPOINT_PUBLICATION_POLICY_CONFLICT"


def test_publish_configuration_endpoint_refreshes_onboarding_completion() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.post(f"/api/v1/endpoints/{created.endpoint.endpoint_id}/publish-configuration")

    assert response.status_code == 200
    assert response.json()["data"]["onboarding"]["completed"] is True
    assert response.json()["data"]["onboarding"]["current_step"] == "operate"
    home = client.get("/operators/dashboard/home")
    assert home.json()["onboarding"]["completed"] is True
    assert home.json()["onboarding"]["current_step"] == "operate"


def test_endpoint_proof_returns_live_configuration_hash() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a"],
                "discoverable": True,
            },
        )
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )
    validation_service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-02T00:00:00+00:00",
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    updated = endpoint_service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            runtime={"streaming": True, "timeout": 45},
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
            validation_service=validation_service,
        )
    )

    response = client.get(f"/api/v1/endpoints/{created.endpoint.endpoint_id}/proof")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["proof"]["endpoint_id"] == created.endpoint.endpoint_id
    assert body["data"]["proof"]["node_id"] == service.node_id
    assert body["data"]["proof"]["configuration_hash"] == updated.endpoint.configuration_hash
    assert body["data"]["proof"]["publication"]["visibility"] == "shared"
    assert body["data"]["proof"]["validation_summary"]["configuration_hash"] == updated.endpoint.configuration_hash
    assert body["data"]["proof"]["validation_summary"]["validation_status"] == "unvalidated"
    assert (
        body["data"]["proof"]["local_publication_configuration_hash"]
        != body["data"]["proof"]["current_publication"]["configuration_hash"]
    )
    assert body["data"]["proof"]["publication_sync_status"] == "local_changes_not_published"
    assert (
        body["data"]["proof"]["published_validation_summary"]["configuration_hash"]
        == created.endpoint.configuration_hash
    )
    assert body["data"]["proof"]["published_validation_summary"]["validation_status"] == "validated"


def test_patch_endpoint_rotation_supersedes_previous_validation_snapshot() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Validated Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={"minimum_deposit": 25.0},
        )
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )
    validation_service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-02T00:00:00+00:00",
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            validation_service=validation_service,
        )
    )

    response = client.patch(
        f"/api/v1/endpoints/{created.endpoint.endpoint_id}",
        json={"runtime": {"streaming": True, "timeout": 45}},
    )

    assert response.status_code == 200
    rotated_hash = response.json()["data"]["endpoint"]["configuration_hash"]
    old_summary = validation_service.validation_summary(
        created.endpoint.endpoint_id,
        configuration_hash=created.endpoint.configuration_hash,
    )
    new_summary = validation_service.validation_summary(
        created.endpoint.endpoint_id,
        configuration_hash=rotated_hash,
    )

    assert old_summary["validation_status"] == "superseded"
    assert old_summary["latest_request_id"] == requested.request.request_id
    assert new_summary["validation_status"] == "unvalidated"


def test_request_validation_endpoint_returns_bond_and_snapshot_summary() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Validated Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={"minimum_deposit": 25.0},
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            validation_service=validation_service,
        )
    )

    response = client.post(f"/api/v1/endpoints/{created.endpoint.endpoint_id}/request-validation")

    assert response.status_code == 200
    assert response.json()["data"]["request"]["status"] == "queued"
    assert response.json()["data"]["bond"]["amount_q"] == 500.0
    assert response.json()["data"]["snapshot"]["status"] == "pending_initial"


def test_endpoint_validation_history_endpoint_returns_reports_and_assignments() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Validated Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={"minimum_deposit": 25.0},
        )
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )
    validation_service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-1",
                "validator_label": "validator-a",
                "shares": 1,
                "capability_profiles": ["llm_text"],
                "contribution_q": 500.0,
            }
        ],
        seed="seed-1",
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            validation_service=validation_service,
        )
    )

    response = client.get(f"/api/v1/endpoints/{created.endpoint.endpoint_id}/validation/history")

    assert response.status_code == 200
    assert len(response.json()["data"]["requests"]) == 1
    assert response.json()["data"]["requests"][0]["request_id"] == requested.request.request_id
    assert len(response.json()["data"]["assignments"]) == 1
    assert len(response.json()["data"]["authorizations"]) == 1


def test_operator_validation_custody_routes_return_metadata_and_integrity_state(tmp_path) -> None:
    validation_service = ValidationService(
        ValidationStore(),
        custody_store=ValidationReportCustodyStore(tmp_path / "custody"),
    )
    requested = validation_service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    validation_service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-1",
                "validator_label": "validator-a",
                "shares": 1,
                "capability_profiles": ["llm_text"],
                "contribution_q": 500.0,
            }
        ],
        seed="seed-1",
    )
    outcome = validation_service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )
    client = TestClient(build_app(service=_service(), validation_service=validation_service))

    metadata = client.get(
        f"/operators/validation/reports/{outcome.report.report_id}/custody"
    )
    checked = client.post(
        f"/operators/validation/reports/{outcome.report.report_id}/custody/check"
    )

    assert metadata.status_code == 200
    assert metadata.json()["data"]["commitment"]["report_hash"] == outcome.commitment.report_hash
    assert "report" not in metadata.json()["data"]
    assert checked.status_code == 200
    assert checked.json()["data"]["custody_state"]["status"] == "available"


def test_create_validation_epoch_endpoint_returns_assignments_and_authorizations() -> None:
    validation_service = ValidationService(ValidationStore())
    requested = validation_service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    client = TestClient(build_app(service=_service(), validation_service=validation_service))

    response = client.post(
        "/api/v1/validation/epochs",
        json={
            "epoch_id": "epoch-1",
            "seed": "seed-1",
            "validator_entries": [
                {
                    "validator_id": "val-1",
                    "validator_label": "validator-a",
                    "shares": 1,
                    "capability_profiles": ["llm_text"],
                    "contribution_q": 500.0,
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["epoch"]["epoch_id"] == "epoch-1"
    assert len(response.json()["data"]["assignments"]) == 1
    assert len(response.json()["data"]["authorizations"]) == 1
    assert response.json()["data"]["assignments"][0]["request_id"] == requested.request.request_id


def test_validation_summary_endpoint_returns_certification_status_and_compatibility_fields() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Validated Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={"minimum_deposit": 25.0},
        )
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )
    validation_service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-1",
                "validator_label": "validator-a",
                "shares": 1,
                "capability_profiles": ["llm_text"],
                "contribution_q": 500.0,
            }
        ],
        seed="seed-1",
    )
    validation_service.submit_validation_report(
        request_id=requested.request.request_id,
        recommendation="certify",
        validator_label="validator-a",
        evidence_summary="validated",
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            validation_service=validation_service,
        )
    )

    response = client.get(f"/api/v1/endpoints/{created.endpoint.endpoint_id}/validation")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["endpoint_id"] == created.endpoint.endpoint_id
    assert payload["configuration_hash"] == created.endpoint.configuration_hash
    assert payload["certification_status"] == "certified"
    assert payload["validation_status"] == "validated"
    assert payload["latest_request_id"] == requested.request.request_id
    assert payload["latest_report_id"] is not None
    assert payload["latest_recommendation"] == "certify"
    assert payload["critical_issue_count"] == 0
    assert payload["bond_state"]["bond_id"] == requested.bond.bond_id
    assert payload["validated_at"] is not None
    assert payload["superseded_at"] is None


def test_validation_summary_endpoint_expands_legacy_service_payload() -> None:
    class LegacyValidationService:
        def validation_summary(
            self,
            endpoint_id: str,
            *,
            configuration_hash: str | None = None,
        ) -> dict:
            return {
                "endpoint_id": endpoint_id,
                "configuration_hash": configuration_hash,
                "validation_status": "validated",
                "latest_request_id": "request-1",
                "latest_report_id": "report-1",
                "bond_state": None,
                "validated_at": "2026-07-10T00:00:00+00:00",
                "superseded_at": None,
            }

    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Validated Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={"minimum_deposit": 25.0},
        )
    )
    client = TestClient(
        build_app(
            service=_service(),
            endpoint_service=endpoint_service,
            validation_service=LegacyValidationService(),
        )
    )

    response = client.get(f"/api/v1/endpoints/{created.endpoint.endpoint_id}/validation")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["endpoint_id"] == created.endpoint.endpoint_id
    assert payload["certification_status"] == "certified"
    assert payload["validation_status"] == "validated"
    assert payload["latest_recommendation"] is None
    assert payload["critical_issue_count"] == 0
    assert payload["warning_issue_count"] == 0
    assert payload["maintenance_report_count"] == 0


def test_submit_validation_report_endpoint_accepts_recommendation_payload() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Validated Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={"minimum_deposit": 25.0},
        )
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )
    validation_service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-1",
                "validator_label": "validator-a",
                "shares": 1,
                "capability_profiles": ["llm_text"],
                "contribution_q": 500.0,
            }
        ],
        seed="seed-1",
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            validation_service=validation_service,
        )
    )

    response = client.post(
        f"/api/v1/validation/requests/{requested.request.request_id}/reports",
        json={
            "recommendation": "certify_with_issues",
            "validator_label": "validator-a",
            "evidence_summary": "operational with warnings",
            "detected_issues": [{"severity": "warning", "code": "latency_spike"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["request"]["status"] == "passed"
    assert response.json()["data"]["snapshot"]["certification_status"] == "certified_with_issues"
    assert response.json()["data"]["snapshot"]["status"] == "validated"


def test_submit_validation_report_endpoint_accepts_valid_legacy_outcome_payload() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Validated Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={"minimum_deposit": 25.0},
        )
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )
    validation_service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-1",
                "validator_label": "validator-a",
                "shares": 1,
                "capability_profiles": ["llm_text"],
                "contribution_q": 500.0,
            }
        ],
        seed="seed-1",
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            validation_service=validation_service,
        )
    )

    response = client.post(
        f"/api/v1/validation/requests/{requested.request.request_id}/reports",
        json={
            "outcome": "pass",
            "validator_label": "validator-a",
            "evidence_summary": "operational",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["snapshot"]["certification_status"] == "certified"


def test_submit_validation_report_endpoint_rejects_unimplemented_structured_evidence_fields() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Validated Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={"minimum_deposit": 25.0},
        )
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )
    validation_service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-1",
                "validator_label": "validator-a",
                "shares": 1,
                "capability_profiles": ["llm_text"],
                "contribution_q": 500.0,
            }
        ],
        seed="seed-1",
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            validation_service=validation_service,
        )
    )

    response = client.post(
        f"/api/v1/validation/requests/{requested.request.request_id}/reports",
        json={
            "recommendation": "certify",
            "validator_label": "validator-a",
            "evidence_summary": "operational",
            "observations": ["not yet supported"],
        },
    )

    assert response.status_code == 422


def test_submit_validation_report_endpoint_rejects_invalid_legacy_outcome() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Validated Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={"minimum_deposit": 25.0},
        )
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )
    validation_service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-1",
                "validator_label": "validator-a",
                "shares": 1,
                "capability_profiles": ["llm_text"],
                "contribution_q": 500.0,
            }
        ],
        seed="seed-1",
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            validation_service=validation_service,
        )
    )

    response = client.post(
        f"/api/v1/validation/requests/{requested.request.request_id}/reports",
        json={
            "outcome": "garbage",
            "validator_label": "validator-a",
            "evidence_summary": "operational",
        },
    )

    assert response.status_code == 422


def test_operator_dashboard_endpoints_payload_includes_validation_summary() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Validated Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={"minimum_deposit": 25.0},
        )
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            validation_service=validation_service,
        )
    )

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["validation_summary"]["validation_status"] == "pending_initial"
    assert item["validation_summary"]["bond_state"]["bond_id"] == requested.bond.bond_id


def test_operator_dashboard_endpoints_payload_includes_dual_layer_trust() -> None:
    service = _service()
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Dual Trust Endpoint",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={"minimum_deposit": 25.0},
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )
    validation_service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-validated",
        validated_at="2026-07-03T00:00:00+00:00",
    )
    endpoint_service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            runtime={"streaming": True, "timeout": 45},
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
            validation_service=validation_service,
        )
    )

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["validation_summary"]["validation_status"] == "unvalidated"
    assert item["published_validation_summary"]["validation_status"] == "validated"
    assert item["publication_sync_status"] == "local_changes_not_published"


def test_maintenance_route_forfeits_remaining_bond_on_fail() -> None:
    validation_service = ValidationService(ValidationStore())
    requested = validation_service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    validation_service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-02T00:00:00+00:00",
    )
    client = TestClient(build_app(service=_service(), validation_service=validation_service))

    response = client.post(
        f"/api/v1/validation/requests/{requested.request.request_id}/maintenance",
        json={
            "outcome": "fail",
            "validator_label": "validator-a",
            "evidence_summary": "timeout",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["bond"]["forfeited_q"] == 500.0
    assert response.json()["data"]["snapshot"]["status"] == "validation_failed"


def test_revoke_publication_endpoint_returns_revoked_record() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.post(f"/api/v1/endpoints/{created.endpoint.endpoint_id}/revoke-publication")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["publication"]["endpoint_id"] == created.endpoint.endpoint_id
    assert body["data"]["publication"]["status"] == "revoked"


def test_wallet_endpoint_publications_export_returns_publication_journal() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.get("/operators/wallet/endpoints/publications/export")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["endpoint_id"] == created.endpoint.endpoint_id
    assert body["items"][0]["wallet_signature"]


def test_registry_advertisement_includes_current_published_configuration_hash() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a"],
                "discoverable": True,
                "accepts_external_requests": True,
            },
        )
    )
    publication = publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
        node_id=hypervisor.node_id,
        wallet_private_key=hypervisor.owner_wallet_private_key(),
    )
    hypervisor.endpoint_publication_service = publication_service
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.get("/operators/registry/advertisement")

    assert response.status_code == 200
    body = response.json()
    assert body["published_endpoints"][0]["endpoint_id"] == created.endpoint.endpoint_id
    assert body["published_endpoints"][0]["current_configuration_hash"] == publication.configuration_hash
    assert body["published_endpoints"][0]["current_publication_id"] == publication.publication_id


def test_registry_advertisement_includes_dual_layer_trust_fields() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Trusty STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            session={"minimum_deposit": 25.0},
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
        node_id=hypervisor.node_id,
        wallet_private_key=hypervisor.owner_wallet_private_key(),
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )
    validation_service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-03T00:00:00+00:00",
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
            validation_service=validation_service,
        )
    )

    response = client.get("/operators/registry/advertisement")

    assert response.status_code == 200
    item = response.json()["published_endpoints"][0]
    assert item["publication_sync_status"] == "in_sync"
    assert item["published_validation_summary"]["validation_status"] == "validated"
    assert item["live_validation_summary"]["validation_status"] == "validated"


def test_node_advertisement_includes_computed_reputation() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.rating = {
        "score": 0.31,
        "tier": "D",
        "updated_at": "2026-07-06T11:55:00+00:00",
    }
    completed = hypervisor.queue.enqueue(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "ok.wav"}))
    hypervisor.queue.transition_status(completed.task_id, "completed")
    failed = hypervisor.queue.enqueue(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "fail.wav"}))
    hypervisor.queue.transition_status(failed.task_id, "failed")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Trusty STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
        node_id=hypervisor.node_id,
        wallet_private_key=hypervisor.owner_wallet_private_key(),
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=0.0,
    )
    validation_service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-03T00:00:00+00:00",
    )
    hypervisor.endpoint_publication_service = publication_service
    hypervisor.bind_validation_service(validation_service)

    advertisement = hypervisor.node_advertisement()

    assert advertisement["rating"]["score"] == 0.31
    assert advertisement["reputation"]["score"] > advertisement["rating"]["score"]
    assert advertisement["reputation"]["tier"] == "B"
    assert advertisement["reputation"]["evidence"]["published_endpoint_count"] == 1
    assert advertisement["reputation"]["evidence"]["successful_tasks"] == 1
    assert advertisement["reputation"]["evidence"]["failed_tasks"] == 1
    assert advertisement["reputation"]["components"]["operational_reliability"] == 0.5


def test_node_advertisement_uses_stale_heartbeat_for_reputation_freshness() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")

    advertisement = hypervisor.node_advertisement(heartbeat_at=(datetime.now(UTC) - timedelta(seconds=35)).isoformat())

    assert advertisement["status"] == "stale"
    assert advertisement["reputation"]["evidence"]["node_status"] == "stale"
    assert advertisement["reputation"]["components"]["freshness"] == 0.55


def test_operator_dashboard_endpoints_payload_reports_publication_sync_state() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a"],
                "discoverable": True,
            },
        )
    )
    publication = publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["local_configuration_hash"] == publication.configuration_hash
    assert item["published_configuration_hash"] == publication.configuration_hash
    assert item["publication_sync_status"] == "in_sync"


def test_operator_dashboard_endpoints_payload_requires_signed_publication_for_published_status() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a"],
                "discoverable": True,
                "accepts_external_requests": True,
            },
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=EndpointPublicationService(
                store=EndpointPublicationStore(),
                endpoint_service=endpoint_service,
            ),
        )
    )

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["endpoint_id"] == created.endpoint.endpoint_id
    assert item["publication_status"] == "configured"
    assert item["published_configuration_hash"] is None
    assert item["publication_sync_status"] == "never_published"


def test_operator_dashboard_market_payload_includes_trust_summary() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at=datetime.now(UTC).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 9,
                "output": 15,
                "fixed_request": 1,
            },
            rating={
                "score": 0.97,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[
                {
                    "bundle_id": "remote-text",
                    "plugin_id": "fake-managed",
                    "workload_type": "llm_text",
                    "provider_type": "fake",
                    "model_id": "remote-text-model",
                    "endpoint": "https://remote.example/runtimes/remote-text",
                    "enabled": True,
                    "status": "ready",
                    "launch_mode": "attached_service",
                    "device_affinity": "cpu",
                    "max_parallel_requests": 2,
                    "supports_allocation": True,
                    "supports_queue": True,
                }
            ],
            published_endpoints=[
                {
                    "endpoint_id": "ep-remote-a",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-external",
                    "current_publication_id": "pub-remote-a",
                    "current_configuration_hash": "cfg-remote-a",
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                    "publication_sync_status": "in_sync",
                    "published_validation_summary": {
                        "validation_status": "validated",
                        "configuration_hash": "cfg-remote-a",
                    },
                    "published_custody_summary": {
                        "custody_status": "available",
                        "report_count": 1,
                        "checked_report_count": 1,
                        "available_report_count": 1,
                        "attention_report_count": 0,
                        "latest_checked_at": "2026-06-30T00:00:00+00:00",
                    },
                },
                {
                    "endpoint_id": "ep-remote-b",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-external",
                    "current_publication_id": "pub-remote-b",
                    "current_configuration_hash": "cfg-remote-b",
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                    "publication_sync_status": "published_configuration_not_served",
                    "published_validation_summary": {
                        "validation_status": "superseded",
                        "configuration_hash": "cfg-remote-b",
                    },
                    "published_custody_summary": {
                        "custody_status": "attention_required",
                        "report_count": 1,
                        "checked_report_count": 1,
                        "available_report_count": 0,
                        "attention_report_count": 1,
                        "latest_checked_at": "2026-06-30T00:00:00+00:00",
                    },
                },
            ],
        )
    )
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    response = client.get("/operators/dashboard/market")

    assert response.status_code == 200
    item = next(candidate for candidate in response.json()["candidates"] if candidate["node_id"] == "node-external")
    assert item["trust_summary"]["total_endpoints"] == 2
    assert item["trust_summary"]["validated_count"] == 1
    assert item["trust_summary"]["attention_count"] == 1
    assert item["trust_summary"]["in_sync_count"] == 1
    assert item["trust_summary"]["drift_count"] == 1
    assert item["trust_summary"]["custody_available_count"] == 1
    assert item["trust_summary"]["custody_attention_count"] == 1
    assert item["trust_summary"]["custody_unverified_count"] == 0


def test_operator_dashboard_market_payload_includes_certification_counts() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at=datetime.now(UTC).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 9,
                "output": 15,
                "fixed_request": 1,
            },
            rating={
                "score": 0.97,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[
                {
                    "bundle_id": "remote-text",
                    "plugin_id": "fake-managed",
                    "workload_type": "llm_text",
                    "provider_type": "fake",
                    "model_id": "remote-text-model",
                    "endpoint": "https://remote.example/runtimes/remote-text",
                    "enabled": True,
                    "status": "ready",
                    "launch_mode": "attached_service",
                    "device_affinity": "cpu",
                    "max_parallel_requests": 2,
                    "supports_allocation": True,
                    "supports_queue": True,
                }
            ],
            published_endpoints=[
                {
                    "endpoint_id": "ep-remote-a",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-external",
                    "current_publication_id": "pub-remote-a",
                    "current_configuration_hash": "cfg-remote-a",
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                    "publication_sync_status": "in_sync",
                    "published_validation_summary": {
                        "certification_status": "certified",
                        "validation_status": "validated",
                        "configuration_hash": "cfg-remote-a",
                    },
                },
                {
                    "endpoint_id": "ep-remote-b",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-external",
                    "current_publication_id": "pub-remote-b",
                    "current_configuration_hash": "cfg-remote-b",
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                    "publication_sync_status": "published_configuration_not_served",
                    "published_validation_summary": {
                        "certification_status": "certified_with_issues",
                        "validation_status": "validated",
                        "configuration_hash": "cfg-remote-b",
                    },
                },
            ],
        )
    )
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    response = client.get("/operators/dashboard/market")

    assert response.status_code == 200
    item = next(candidate for candidate in response.json()["candidates"] if candidate["node_id"] == "node-external")
    assert item["trust_summary"]["certified_count"] == 1
    assert item["trust_summary"]["certified_with_issues_count"] == 1
    assert item["trust_summary"]["validated_count"] == 2
    assert item["trust_summary"]["validation_by_status"]["validated"] == 2


def test_operator_dashboard_remote_endpoints_payload_includes_trust_fields() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at=datetime.now(UTC).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 9,
                "output": 15,
                "fixed_request": 1,
            },
            rating={
                "score": 0.97,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[],
            published_endpoints=[
                {
                    "endpoint_id": "ep-remote",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-external",
                    "current_publication_id": "pub-remote",
                    "current_configuration_hash": "cfg-remote",
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                    "publication_sync_status": "published_configuration_not_served",
                    "published_validation_summary": {
                        "validation_status": "validated",
                        "configuration_hash": "cfg-remote",
                    },
                }
            ],
        )
    )
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    response = client.get("/operators/dashboard/remote-endpoints")

    assert response.status_code == 200
    item = response.json()["discovered"][0]
    assert item["publication_sync_status"] == "published_configuration_not_served"
    assert item["published_validation_summary"]["validation_status"] == "validated"


def test_operator_dashboard_remote_endpoints_payload_surfaces_certification_status() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at=datetime.now(UTC).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 9,
                "output": 15,
                "fixed_request": 1,
            },
            rating={
                "score": 0.97,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[],
            published_endpoints=[
                {
                    "endpoint_id": "ep-remote",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-external",
                    "current_publication_id": "pub-remote",
                    "current_configuration_hash": "cfg-remote",
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                    "publication_sync_status": "published_configuration_not_served",
                    "published_validation_summary": {
                        "certification_status": "certified_with_issues",
                        "validation_status": "validated",
                        "configuration_hash": "cfg-remote",
                    },
                }
            ],
        )
    )
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    response = client.get("/operators/dashboard/remote-endpoints")

    assert response.status_code == 200
    item = response.json()["discovered"][0]
    assert item["published_validation_summary"]["certification_status"] == "certified_with_issues"
    assert item["published_validation_summary"]["validation_status"] == "validated"


def test_operator_dashboard_shell_preserves_legacy_validation_labels_for_published_trust() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "function publishedTrustStatusLabel(summary)" in response.text
    assert "return trustStatusLabel(summary.certification_status);" in response.text
    assert "return trustStatusLabel(validationStatus(summary), { legacyValidation: true });" in response.text
    assert 'return legacyValidation ? "Revoked" : "Attention Required";' in response.text


def test_operator_dashboard_shell_exposes_publication_sync_copy() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Published Configuration" in response.text
    assert "Sync Status" in response.text
    assert "Validation Trust" in response.text
    assert "Publication Trust" in response.text
    assert 'data-endpoint-action="publish-configuration"' in response.text
    assert "/publish-configuration" in response.text
    assert 'data-endpoint-action="revoke-publication"' in response.text
    assert 'data-endpoint-action="view-signed-publication"' in response.text
    assert "Revoke Publication" in response.text
    assert "View Signed Publication" in response.text
    assert "Signed Publication" in response.text
    assert "Wallet Signature" in response.text
    assert "Publication Payload" in response.text


def test_operator_dashboard_shell_exposes_signed_publication_operator_summary() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Trust Artifact Summary" in response.text
    assert "Execution Route" in response.text
    assert "Proxy Target" in response.text
    assert "Open Execution Market" in response.text
    assert "Back To Endpoint Summary" in response.text


def test_operator_dashboard_wallet_endpoint_returns_aggregated_payload() -> None:
    service = _service()
    client = TestClient(build_app(service=service))

    response = client.get("/operators/dashboard/wallet")

    assert response.status_code == 200
    payload = response.json()
    assert "owner_wallet" in payload
    assert "node_identity" in payload
    assert isinstance(payload["usage_events"], list)
    assert isinstance(payload["allocation_events"], list)
    assert isinstance(payload["dispute_events"], list)
    assert "economics_summary" in payload
    assert isinstance(payload["economics_history"], list)
    assert "economics_history_cursor" in payload
    assert "faucet_preview" in payload


def test_operator_dashboard_endpoints_payload_includes_publication_history() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    publication_service.revoke_publication(created.endpoint.endpoint_id)
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert len(item["publication_history"]) == 1
    assert item["publication_history"][0]["status"] == "revoked"


def test_operator_dashboard_endpoints_payload_includes_current_publication_payload() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication = publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["current_publication"]["publication_id"] == publication.publication_id
    assert item["current_publication"]["wallet_signature"] == publication.wallet_signature


def test_operator_dashboard_requests_policy_endpoint_updates_service_state() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/dashboard/requests/policy",
        json={
            "allow_spillover": True,
            "dispatch_strategy": "balanced",
            "ready_endpoint_only": False,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "allow_spillover": True,
        "dispatch_strategy": "balanced",
        "ready_endpoint_only": False,
    }


def test_hypervisor_advertisement_can_be_registered_and_discovered() -> None:
    hypervisor = _service(
        with_runtime=False,
        use_process_manager=True,
        whisper_endpoint="http://127.0.0.1:9000",
    )
    hypervisor.node_id = "node-a"
    hypervisor.operator_id = "operator-a"
    hypervisor.base_url = "https://node-a.example"
    hypervisor.can_host_custom_model = True
    hypervisor.pricing = {
        "unit": "q_per_1kk_tokens",
        "input": 12,
        "output": 18,
        "fixed_request": None,
    }
    hypervisor.rating = {
        "score": 0.91,
        "tier": "A",
        "updated_at": "2026-06-19T18:25:00Z",
    }
    registry = RegistryService()

    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    result = registry.discover(
        RegistryDiscoveryQuery(
            workload_type="speech_to_text",
            can_host_custom_model=True,
        )
    )

    assert result["nodes"][0]["node_id"] == "node-a"
    assert result["nodes"][0]["bundles"][0]["bundle_id"] == "whisper-a"


def test_registry_discovery_orders_ready_nodes_by_reputation_then_price() -> None:
    registry = RegistryService()
    heartbeat_at = datetime.now(UTC).isoformat()
    common_bundle = [
        {
            "bundle_id": "remote-text",
            "plugin_id": "fake-managed",
            "workload_type": "llm_text",
            "provider_type": "fake",
            "model_id": "remote-text-model",
            "endpoint": "https://remote.example/runtimes/remote-text",
            "enabled": True,
            "status": "ready",
            "launch_mode": "attached_service",
            "device_affinity": "cpu",
            "max_parallel_requests": 2,
            "supports_allocation": True,
            "supports_queue": True,
        }
    ]
    common_resources = {
        "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
        "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
    }
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-low-price",
            operator_id="operator-a",
            base_url="https://node-low-price.example",
            heartbeat_at=heartbeat_at,
            resources=common_resources,
            providers=["fake"],
            can_host_custom_model=True,
            pricing={"unit": "q_per_1kk_tokens", "input": 5, "output": 9},
            rating={"score": 0.99, "tier": "A", "updated_at": "2026-07-06T11:55:00+00:00"},
            reputation={
                "score": 0.64,
                "tier": "C",
                "updated_at": "2026-07-06T11:55:00+00:00",
                "components": {},
                "evidence": {},
            },
            bundles=common_bundle,
        )
    )
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-high-reputation-cheaper",
            operator_id="operator-b",
            base_url="https://node-high-reputation-cheaper.example",
            heartbeat_at=heartbeat_at,
            resources=common_resources,
            providers=["fake"],
            can_host_custom_model=True,
            pricing={"unit": "q_per_1kk_tokens", "input": 7, "output": 10},
            rating={"score": 0.40, "tier": "D", "updated_at": "2026-07-06T11:55:00+00:00"},
            reputation={
                "score": 0.93,
                "tier": "A",
                "updated_at": "2026-07-06T11:55:00+00:00",
                "components": {},
                "evidence": {},
            },
            bundles=common_bundle,
        )
    )
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-high-reputation-pricier",
            operator_id="operator-c",
            base_url="https://node-high-reputation-pricier.example",
            heartbeat_at=heartbeat_at,
            resources=common_resources,
            providers=["fake"],
            can_host_custom_model=True,
            pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 11},
            rating={"score": 0.10, "tier": "D", "updated_at": "2026-07-06T11:55:00+00:00"},
            reputation={
                "score": 0.93,
                "tier": "A",
                "updated_at": "2026-07-06T11:55:00+00:00",
                "components": {},
                "evidence": {},
            },
            bundles=common_bundle,
        )
    )

    result = registry.discover(RegistryDiscoveryQuery(workload_type="llm_text", min_rating=0.9))

    assert [node["node_id"] for node in result["nodes"]] == [
        "node-high-reputation-cheaper",
        "node-high-reputation-pricier",
    ]
    assert [candidate["node_id"] for candidate in result["candidates"]] == [
        "node-high-reputation-cheaper",
        "node-high-reputation-pricier",
    ]


def test_registry_discovery_falls_back_to_legacy_rating_when_reputation_absent() -> None:
    registry = RegistryService()
    heartbeat_at = datetime.now(UTC).isoformat()
    common_bundle = [
        {
            "bundle_id": "remote-text",
            "plugin_id": "fake-managed",
            "workload_type": "llm_text",
            "provider_type": "fake",
            "model_id": "remote-text-model",
            "endpoint": "https://remote.example/runtimes/remote-text",
            "enabled": True,
            "status": "ready",
            "launch_mode": "attached_service",
            "device_affinity": "cpu",
            "max_parallel_requests": 2,
            "supports_allocation": True,
            "supports_queue": True,
        }
    ]
    common_resources = {
        "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
        "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
    }
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-high-rating",
            operator_id="operator-a",
            base_url="https://node-high-rating.example",
            heartbeat_at=heartbeat_at,
            resources=common_resources,
            providers=["fake"],
            can_host_custom_model=True,
            pricing={"unit": "q_per_1kk_tokens", "input": 9, "output": 12},
            rating={"score": 0.94, "tier": "A", "updated_at": "2026-07-06T11:55:00+00:00"},
            bundles=common_bundle,
        )
    )
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-low-rating",
            operator_id="operator-b",
            base_url="https://node-low-rating.example",
            heartbeat_at=heartbeat_at,
            resources=common_resources,
            providers=["fake"],
            can_host_custom_model=True,
            pricing={"unit": "q_per_1kk_tokens", "input": 5, "output": 8},
            rating={"score": 0.72, "tier": "B", "updated_at": "2026-07-06T11:55:00+00:00"},
            bundles=common_bundle,
        )
    )

    result = registry.discover(RegistryDiscoveryQuery(workload_type="llm_text", min_rating=0.9))

    assert [node["node_id"] for node in result["nodes"]] == ["node-high-rating"]
    assert [candidate["node_id"] for candidate in result["candidates"]] == ["node-high-rating"]


def test_agent_capabilities_endpoint_reports_ready_bundle_catalog() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        whisper_endpoint="http://127.0.0.1:9000",
    )
    service.node_id = "node-a"
    service.operator_id = "operator-a"
    service.can_host_custom_model = True
    service.pricing = {
        "unit": "q_per_1kk_tokens",
                    "input": 12,
                    "output": 18,
                    "fixed_request": 4,
                    "audio_input_second": 0.0,
    }
    client = TestClient(build_app(service=service))

    response = client.get(
        "/agent/capabilities",
        params={"owner_id": "agent-a", "workload_type": "speech_to_text"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "node": {
            "node_id": "node-a",
            "operator_id": "operator-a",
            "can_host_custom_model": True,
            "pricing": {
                "unit": "q_per_1kk_tokens",
                "input": 12,
                "output": 18,
                "fixed_request": 4,
                "audio_input_second": 0.0,
            },
        },
        "resources": {
            "total": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 8192},
            "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
            "free": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 8192},
        },
        "bundles": [
            {
                "bundle_id": "whisper-a",
                "plugin_id": "fake-managed",
                "provider_type": "fake",
                "model_id": "whisper-a-model",
                "workload_type": "speech_to_text",
                "enabled": True,
                "status": "stopped",
                "endpoint": "http://127.0.0.1:9000",
                "can_allocate_now": True,
                "can_queue": False,
                "allocation_mode": "active",
                "reason": None,
                "required": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
                "requires_runtime_start": True,
                "fit": {
                    "fits": True,
                    "cpu_shortfall": 0.0,
                    "ram_mb_shortfall": 0,
                    "vram_mb_shortfall": 0,
                },
            }
        ],
    }


def test_agent_capabilities_endpoint_reports_waiting_bundle_catalog() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=2.0,
            ram_mb=2048,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 1024},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=0.5,
            cold_start_ram_mb=512,
            steady_cpu=1.5,
            steady_ram_mb=1536,
        ),
        whisper_endpoint="http://127.0.0.1:9000",
    )
    service.resources.reserve("busy", cpu=2.0, ram_mb=2048, vram_mb=0)
    service.node_id = "node-a"
    service.operator_id = "operator-a"
    service.can_host_custom_model = True
    service.pricing = {
        "unit": "q_per_1kk_tokens",
                    "input": 12,
                    "output": 18,
                    "fixed_request": 4,
                    "audio_input_second": 0.0,
    }
    client = TestClient(build_app(service=service))

    response = client.get(
        "/agent/capabilities",
        params={"owner_id": "agent-a", "workload_type": "speech_to_text"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "node": {
            "node_id": "node-a",
            "operator_id": "operator-a",
            "can_host_custom_model": True,
            "pricing": {
                "unit": "q_per_1kk_tokens",
                "input": 12,
                "output": 18,
                "fixed_request": 4,
                "audio_input_second": 0.0,
            },
        },
        "resources": {
            "total": {"cpu": 2.0, "ram_mb": 2048, "vram_mb": 1024},
            "reserved": {"cpu": 2.0, "ram_mb": 2048, "vram_mb": 0},
            "free": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 1024},
        },
        "bundles": [
            {
                "bundle_id": "whisper-a",
                "plugin_id": "fake-managed",
                "provider_type": "fake",
                "model_id": "whisper-a-model",
                "workload_type": "speech_to_text",
                "enabled": True,
                "status": "stopped",
                "endpoint": "http://127.0.0.1:9000",
                "can_allocate_now": False,
                "can_queue": True,
                "allocation_mode": "wait",
                "reason": "insufficient_resources",
                "required": {"cpu": 2.0, "ram_mb": 2048, "vram_mb": 0},
                "requires_runtime_start": True,
                "fit": {
                    "fits": False,
                    "cpu_shortfall": 2.0,
                    "ram_mb_shortfall": 2048,
                    "vram_mb_shortfall": 0,
                },
            }
        ],
    }


def test_operator_model_install_endpoint_queues_install_job(tmp_path) -> None:
    service = _service(model_store=FileModelStore(tmp_path))
    client = TestClient(build_app(service=service))

    response = client.post(
        "/operators/models/install",
        json={
            "provider_type": "llama.cpp",
            "model_id": "phi-4-mini.gguf",
            "source_url": "https://example.invalid/models/phi-4-mini.gguf",
            "requested_by": "operator-a",
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["provider_type"] == "llama.cpp"
    assert response.json()["target_path"].endswith("llama.cpp\\phi-4-mini.gguf")


def test_operator_model_install_list_endpoint_returns_queued_jobs(tmp_path) -> None:
    service = _service(model_store=FileModelStore(tmp_path))
    service.request_model_install(
        provider_type="llama.cpp",
        model_id="phi-4-mini.gguf",
        source_url="https://example.invalid/models/phi-4-mini.gguf",
        requested_by="operator-a",
    )
    client = TestClient(build_app(service=service))

    response = client.get("/operators/models/install")

    assert response.status_code == 200
    assert response.json()[0]["status"] == "queued"
    assert response.json()[0]["model_id"] == "phi-4-mini.gguf"


def test_operator_model_install_process_endpoint_executes_queued_jobs(tmp_path) -> None:
    source_artifact = tmp_path / "phi-4-mini.gguf"
    source_artifact.write_text("model-bytes", encoding="utf-8")
    service = _service(model_store=FileModelStore(tmp_path / "models"))
    install = service.request_model_install(
        provider_type="fake-managed",
        model_id="phi-4-mini.gguf",
        source_url=source_artifact.as_uri(),
        requested_by="operator-a",
    )
    client = TestClient(build_app(service=service))

    response = client.post("/operators/models/install/process")

    assert response.status_code == 200
    assert response.json() == [
        {
            "install_id": install["install_id"],
            "provider_type": "fake-managed",
            "model_id": "phi-4-mini.gguf",
            "source_url": source_artifact.as_uri(),
            "target_path": install["target_path"],
            "requested_by": "operator-a",
            "status": "completed",
            "bundle_id": None,
            "last_error": None,
        }
    ]


def test_operator_register_bundle_from_install_endpoint_creates_bundle(tmp_path) -> None:
    service = _service(model_store=FileModelStore(tmp_path))
    install = service.request_model_install(
        provider_type="fake-managed",
        model_id="phi-4-mini.gguf",
        source_url="https://example.invalid/models/phi-4-mini.gguf",
        requested_by="operator-a",
    )
    service.mark_model_install_completed(install["install_id"])
    client = TestClient(build_app(service=service))

    response = client.post(
        f"/operators/models/{install['install_id']}/register-bundle",
        json={
            "bundle_id": "phi4-local",
            "workload_type": "llm_text",
            "endpoint": "http://127.0.0.1:8080",
        },
    )

    assert response.status_code == 200
    assert response.json()["bundle_id"] == "phi4-local"
    assert response.json()["plugin_id"] == "fake-managed"
    assert service.bundles[-1].model_id == install["target_path"]


def test_operator_can_install_register_and_expose_new_model_via_api(tmp_path) -> None:
    service = _service(model_store=FileModelStore(tmp_path))
    service.node_id = "node-a"
    service.operator_id = "operator-a"
    service.can_host_custom_model = True
    service.pricing = {
        "unit": "q_per_1kk_tokens",
        "input": 12,
        "output": 18,
        "fixed_request": 4,
    }
    source_artifact = tmp_path / "phi-4-mini.gguf"
    source_artifact.write_text("model-bytes", encoding="utf-8")
    client = TestClient(build_app(service=service))

    install_response = client.post(
        "/operators/models/install",
        json={
            "provider_type": "fake-managed",
            "model_id": "phi-4-mini.gguf",
            "source_url": source_artifact.as_uri(),
            "requested_by": "operator-a",
        },
    )
    install_id = install_response.json()["install_id"]

    complete_response = client.post("/operators/models/install/process")
    register_response = client.post(
        f"/operators/models/{install_id}/register-bundle",
        json={
            "bundle_id": "phi4-local",
            "workload_type": "llm_text",
            "endpoint": "http://127.0.0.1:8080",
        },
    )
    catalog_response = client.get(
        "/agent/capabilities",
        params={
            "owner_id": "agent-a",
            "workload_type": "llm_text",
            "bundle_id": "phi4-local",
        },
    )

    assert install_response.status_code == 202
    assert complete_response.status_code == 200
    assert register_response.status_code == 200
    assert catalog_response.status_code == 200
    assert complete_response.json()[0]["status"] == "completed"
    assert register_response.json()["bundle_id"] == "phi4-local"
    assert catalog_response.json()["node"]["can_host_custom_model"] is True
    assert catalog_response.json()["bundles"][0]["bundle_id"] == "phi4-local"
    assert catalog_response.json()["bundles"][0]["model_id"].endswith("phi-4-mini.gguf")


def test_create_allocation_endpoint_returns_409_when_resources_do_not_fit() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=1.0,
            ram_mb=1024,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 256},
        ),
        whisper_profile=ResourceProfile(
            steady_cpu=2.0,
            steady_ram_mb=2048,
            steady_vram_mb=512,
        ),
        whisper_endpoint="http://127.0.0.1:9000",
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/allocations",
        json={"workload_type": "speech_to_text", "owner_id": "agent-a"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "reason": "insufficient_resources",
        "retryable": True,
        "bundle_id": "whisper-a",
        "message": "insufficient resources for allocation runtime residency: whisper-a",
        "retry_after_seconds": 5,
        "next_attempt_at": response.json()["detail"]["next_attempt_at"],
    }


def test_create_allocation_endpoint_returns_pending_lease_for_wait_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=2.0,
            ram_mb=2048,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 1024},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=0.5,
            cold_start_ram_mb=512,
            steady_cpu=1.5,
            steady_ram_mb=1536,
        ),
        whisper_endpoint="http://127.0.0.1:9000",
    )
    service.resources.reserve("busy", cpu=2.0, ram_mb=2048, vram_mb=0)
    client = TestClient(build_app(service=service))

    response = client.post(
        "/allocations",
        json={
            "workload_type": "speech_to_text",
            "owner_id": "agent-a",
            "policy": "wait",
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "allocation_id": response.json()["allocation_id"],
        "owner_id": "agent-a",
        "workload_type": "speech_to_text",
        "bundle_id": "whisper-a",
        "runtime_id": None,
        "endpoint": None,
        "status": "pending",
        "reason": "insufficient_resources",
        "retry_after_seconds": 5,
        "next_attempt_at": datetime.fromtimestamp(
            current_time[0] + 5,
            UTC,
        ).isoformat(),
    }


def test_reconcile_allocation_endpoint_activates_pending_wait_lease() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=2.0,
            ram_mb=2048,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 1024},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=0.5,
            cold_start_ram_mb=512,
            steady_cpu=1.0,
            steady_ram_mb=1024,
        ),
        whisper_endpoint="http://127.0.0.1:9000",
    )
    service.resources.reserve("busy", cpu=2.0, ram_mb=2048, vram_mb=0)
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="speech_to_text",
            owner_id="agent-a",
            policy="wait",
        )
    )
    client = TestClient(build_app(service=service))

    service.resources.release("busy")
    response = client.post(f"/allocations/{allocation['allocation_id']}/reconcile")

    assert response.status_code == 200
    assert response.json() == {
        "allocation_id": allocation["allocation_id"],
        "owner_id": "agent-a",
        "workload_type": "speech_to_text",
        "bundle_id": "whisper-a",
        "runtime_id": "rt-1",
        "endpoint": "http://127.0.0.1:9000",
        "status": "active",
    }


def test_create_allocation_endpoint_returns_409_when_owner_active_quota_is_exceeded() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        whisper_endpoint="http://127.0.0.1:9000",
    )
    service.max_active_allocations_per_owner = 1
    service.create_allocation(AllocationRequest(workload_type="speech_to_text", owner_id="agent-a"))
    client = TestClient(build_app(service=service))

    response = client.post(
        "/allocations",
        json={"workload_type": "speech_to_text", "owner_id": "agent-a"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "owner_quota_exceeded"


def test_admission_diagnostics_endpoint_reports_selection_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: 1_781_827_800.0)
    service = _service(with_runtime=False, use_process_manager=True)
    older_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "older.wav"},
            priority=10,
            mode="manual",
            bundle_override="whisper-a",
        )
    )
    service._selected_bundles[older_task.task_id] = "whisper-a"
    newer_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "newer.wav"},
            priority=40,
            mode="manual",
            bundle_override="whisper-a",
        )
    )
    service._selected_bundles[newer_task.task_id] = "whisper-a"
    peer_task = service.queue.enqueue(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "peer"},
            priority=30,
            mode="manual",
            bundle_override="text-a",
        )
    )
    service._selected_bundles[peer_task.task_id] = "text-a"
    service.queue.restore(
        [
            replace(service.get_task(older_task.task_id), created_at="2026-06-19T00:00:00+00:00"),
            replace(service.get_task(newer_task.task_id), created_at="2026-06-19T00:09:00+00:00"),
            replace(service.get_task(peer_task.task_id), created_at="2026-06-19T00:09:00+00:00"),
        ]
    )
    client = TestClient(build_app(service=service))

    response = client.get("/diagnostics/admission")

    assert response.status_code == 200
    assert response.json() == {
        "summary": {"queued": 3, "active": 0, "completed": 0, "failed": 0},
        "items": [
            {
                "task_id": older_task.task_id,
                "bundle_id": "whisper-a",
                "base_priority": 10,
                "aging_bonus": 100,
                "effective_priority": 110,
                "fair_share_round": 0,
                "admission_rank": 1,
                "selection_reason": "highest_effective_priority",
            },
            {
                "task_id": peer_task.task_id,
                "bundle_id": "text-a",
                "base_priority": 30,
                "aging_bonus": 10,
                "effective_priority": 40,
                "fair_share_round": 0,
                "admission_rank": 2,
                "selection_reason": "lowest_dispatch_count",
            },
            {
                "task_id": newer_task.task_id,
                "bundle_id": "whisper-a",
                "base_priority": 40,
                "aging_bonus": 10,
                "effective_priority": 50,
                "fair_share_round": 1,
                "admission_rank": 3,
                "selection_reason": "only_remaining_bundle",
            },
        ],
    }


def test_process_pending_endpoint_returns_processing_summary() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=1.0,
            ram_mb=1024,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 512},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=1.0,
            steady_cpu=0.5,
            per_request_cpu=0.5,
        ),
    )
    service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))
    client = TestClient(build_app(service=service))

    response = client.post("/operators/process-pending")

    assert response.status_code == 200
    assert response.json() == {
        "queued": 1,
        "active": 0,
        "completed": 0,
        "failed": 0,
    }


def test_operator_state_endpoint_returns_snapshot() -> None:
    service = _service()
    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))
    client = TestClient(build_app(service=service))

    response = client.get("/operators/state")

    assert response.status_code == 200
    assert response.json()["tasks"] == [
        {
            "task_id": task.task_id,
            "priority": 50,
            "enqueue_index": 0,
            "created_at": service.get_task(task.task_id).created_at,
            "status": "completed",
            "request": {
                "task_type": "audio.transcribe",
                "payload": {"audio_ref": "clip.wav"},
                "mode": "auto",
                "bundle_override": None,
                "priority": 50,
                "constraints": {},
            },
            "bundle_id": "whisper-a",
            "result": {"ok": True, "task_type": "audio.transcribe"},
            "recovery_reason": None,
        }
    ]


def test_operator_restore_state_endpoint_replaces_runtime_and_queue_state() -> None:
    service = _service(with_runtime=False, use_process_manager=True, reserve_runtime=False)
    client = TestClient(build_app(service=service))

    response = client.post(
        "/operators/state/restore",
        json={
            "tasks": [
                {
                    "task_id": "task-1",
                    "priority": 50,
                    "enqueue_index": 0,
                    "created_at": "2026-06-19T00:00:00+00:00",
                    "status": "queued",
                    "request": {
                        "task_type": "audio.transcribe",
                        "payload": {"audio_ref": "clip.wav"},
                        "mode": "auto",
                        "bundle_override": None,
                        "priority": 50,
                        "constraints": {},
                    },
                    "bundle_id": "whisper-a",
                    "result": None,
                }
            ],
            "runtimes": [
                {
                    "runtime_id": "rt-1",
                    "bundle_id": "whisper-a",
                    "command": ["python", "-m", "http.server", "0"],
                    "status": "running",
                    "health_status": "unknown",
                    "last_error": None,
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"queued": 1, "active": 0, "completed": 0, "failed": 0}
    assert service.get_task("task-1").status == "queued"
    assert service.list_runtimes()[0].runtime_id == "rt-1"


def test_operator_events_endpoint_returns_recent_journal_entries() -> None:
    service = _service()
    service.record_event(
        event_type="operator.note",
        message="first",
        details={"index": 1},
    )
    service.record_event(
        event_type="operator.note",
        message="second",
        details={"index": 2},
    )
    client = TestClient(build_app(service=service))

    response = client.get("/operators/events?limit=1")

    assert response.status_code == 200
    assert response.json() == [
        {
            "timestamp": service.event_journal(limit=1)[0].timestamp,
            "event_type": "operator.note",
            "message": "second",
            "task_id": None,
            "bundle_id": None,
            "runtime_id": None,
            "details": {"index": 2},
        }
    ]


def test_operator_events_endpoint_includes_admission_decision_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: 1_781_827_800.0)
    service = _service(with_runtime=False, use_process_manager=True)
    older_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "older.wav"},
            priority=10,
            mode="manual",
            bundle_override="whisper-a",
        )
    )
    service._selected_bundles[older_task.task_id] = "whisper-a"
    newer_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "newer.wav"},
            priority=40,
            mode="manual",
            bundle_override="whisper-a",
        )
    )
    service._selected_bundles[newer_task.task_id] = "whisper-a"
    peer_task = service.queue.enqueue(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "peer"},
            priority=30,
            mode="manual",
            bundle_override="text-a",
        )
    )
    service._selected_bundles[peer_task.task_id] = "text-a"
    service.queue.restore(
        [
            replace(service.get_task(older_task.task_id), created_at="2026-06-19T00:00:00+00:00"),
            replace(service.get_task(newer_task.task_id), created_at="2026-06-19T00:09:00+00:00"),
            replace(service.get_task(peer_task.task_id), created_at="2026-06-19T00:09:00+00:00"),
        ]
    )
    service.process_pending()
    client = TestClient(build_app(service=service))

    response = client.get("/operators/events")

    assert response.status_code == 200
    admission_events = [event for event in response.json() if event["event_type"] == "admission.selected"]
    assert admission_events == [
        {
            "timestamp": admission_events[0]["timestamp"],
            "event_type": "admission.selected",
            "message": "task selected for admission attempt",
            "task_id": older_task.task_id,
            "bundle_id": "whisper-a",
            "runtime_id": None,
            "details": {
                "base_priority": 10,
                "aging_bonus": 100,
                "effective_priority": 110,
                "fair_share_round": 0,
                "admission_rank": 1,
                "selection_reason": "highest_effective_priority",
            },
        },
        {
            "timestamp": admission_events[1]["timestamp"],
            "event_type": "admission.selected",
            "message": "task selected for admission attempt",
            "task_id": peer_task.task_id,
            "bundle_id": "text-a",
            "runtime_id": None,
            "details": {
                "base_priority": 30,
                "aging_bonus": 10,
                "effective_priority": 40,
                "fair_share_round": 0,
                "admission_rank": 2,
                "selection_reason": "lowest_dispatch_count",
            },
        },
        {
            "timestamp": admission_events[2]["timestamp"],
            "event_type": "admission.selected",
            "message": "task selected for admission attempt",
            "task_id": newer_task.task_id,
            "bundle_id": "whisper-a",
            "runtime_id": None,
            "details": {
                "base_priority": 40,
                "aging_bonus": 10,
                "effective_priority": 50,
                "fair_share_round": 1,
                "admission_rank": 3,
                "selection_reason": "only_remaining_bundle",
            },
        },
    ]


def test_operator_bundle_config_endpoint_returns_persisted_bundle_definitions(
    tmp_path,
) -> None:
    path = tmp_path / "bundles.json"
    registry = FileBundleRegistry(path)
    service = _service(bundle_registry=registry)
    registry.save(service.bundles)
    client = TestClient(build_app(service=service))

    response = client.get("/operators/bundles/config")

    assert response.status_code == 200
    assert response.json()[0]["bundle_id"] == "whisper-a"
    assert response.json()[0]["plugin_id"] == "fake-managed"


def test_operator_replace_bundle_config_endpoint_persists_and_reloads_bundles(
    tmp_path,
) -> None:
    path = tmp_path / "bundles.json"
    registry = FileBundleRegistry(path)
    service = _service(bundle_registry=registry)
    client = TestClient(build_app(service=service))

    response = client.put(
        "/operators/bundles/config",
        json=[
            {
                "bundle_id": "whisper-local",
                "plugin_id": "fake-managed",
                "provider_type": "fake",
                "workload_type": "speech_to_text",
                "model_id": "whisper-large",
                "launch_mode": "attached_service",
                "endpoint": "http://127.0.0.1:9000",
                "device_affinity": "cpu",
                "resource_profile": {
                    "cold_start_cpu": 0.0,
                    "cold_start_ram_mb": 0,
                    "cold_start_vram_mb": 0,
                    "steady_cpu": 1.0,
                    "steady_ram_mb": 1024,
                    "steady_vram_mb": 0,
                    "per_request_cpu": 0.5,
                    "per_request_ram_mb": 256,
                    "per_request_vram_mb": 0,
                },
                "warm_policy": "auto",
                "priority_class": 70,
                "max_parallel_requests": 1,
                "enabled": True,
            }
        ],
    )

    assert response.status_code == 200
    assert response.json() == {"bundle_count": 1, "status": "reloaded"}
    assert [bundle.bundle_id for bundle in service.bundles] == ["whisper-local"]
    assert registry.load(service.plugins)[0].bundle_id == "whisper-local"


def test_operator_reload_bundle_config_endpoint_refreshes_bundles_from_disk(
    tmp_path,
) -> None:
    path = tmp_path / "bundles.json"
    registry = FileBundleRegistry(path)
    service = _service(bundle_registry=registry)
    registry.save(
        [
            BundleConfig(
                bundle_id="phi4-ollama",
                plugin_id="fake-managed",
                provider_type="fake",
                workload_type="llm_text",
                model_id="phi4",
                launch_mode="attached_service",
                endpoint="http://127.0.0.1:11434",
                device_affinity="cpu",
                resource_profile=ResourceProfile(),
                warm_policy="auto",
            )
        ]
    )
    client = TestClient(build_app(service=service))

    response = client.post("/operators/bundles/reload")

    assert response.status_code == 200
    assert response.json() == {"bundle_count": 1, "status": "reloaded"}
    assert [bundle.bundle_id for bundle in service.bundles] == ["phi4-ollama"]


def test_api_surfaces_bundle_cooldown_status_and_runtime_metadata(
    monkeypatch,
) -> None:
    current_time = [1000.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    monkeypatch.setattr("aidn_hypervisor.service.time.sleep", lambda _: None)
    plugins = PluginRegistry()
    plugin = CooldownApiPlugin()
    plugins.register(plugin)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[_bundle("whisper-a", "speech_to_text").model_copy(update={"plugin_id": "fake-cooldown-api"})],
        plugins=plugins,
        runtimes=ProviderProcessManager(),
    )
    service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"}))
    queued_task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"}))
    client = TestClient(build_app(service=service))

    bundles_response = client.get("/bundles")
    runtimes_response = client.get("/runtimes")
    diagnostics_response = client.get("/diagnostics/queue")
    state_response = client.get("/operators/state")

    assert bundles_response.status_code == 200
    assert bundles_response.json() == [
        {
            "bundle_id": "whisper-a",
            "plugin_id": "fake-cooldown-api",
            "provider_type": "fake",
            "workload_type": "speech_to_text",
            "model_id": "whisper-a-model",
            "launch_mode": "managed_process",
            "enabled": True,
            "priority_class": 50,
            "status": "cooldown",
        }
    ]
    assert runtimes_response.status_code == 200
    assert runtimes_response.json() == [
        {
            "runtime_id": "rt-1",
            "bundle_id": "whisper-a",
            "command": ["python", "-m", "http.server", "0"],
            "status": "running",
            "health_status": "cooldown",
            "active_task_count": 0,
            "failure_streak": 1,
            "cooldown_until": 1060.0,
            "cooldown_reason": "connection refused",
            "drain_mode": False,
            "drain_reason": None,
        }
    ]
    assert diagnostics_response.status_code == 200
    assert diagnostics_response.json() == {
        "summary": {"queued": 1, "active": 0, "completed": 0, "failed": 1},
        "items": [
            {
                "task_id": queued_task.task_id,
                "bundle_id": "whisper-a",
                "reason": "provider_cooldown",
            }
        ],
    }
    assert state_response.status_code == 200
    assert state_response.json()["bundle_states"] == [
        {
            "bundle_id": "whisper-a",
            "failure_streak": 1,
            "cooldown_until": 1060.0,
            "cooldown_reason": "connection refused",
            "drain_mode": False,
            "drain_reason": None,
        }
    ]


def test_operator_reset_cooldown_endpoint_clears_bundle_cooldown(monkeypatch) -> None:
    current_time = [1000.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    monkeypatch.setattr("aidn_hypervisor.service.time.sleep", lambda _: None)
    plugins = PluginRegistry()
    plugin = CooldownApiPlugin()
    plugins.register(plugin)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[_bundle("whisper-a", "speech_to_text").model_copy(update={"plugin_id": "fake-cooldown-api"})],
        plugins=plugins,
        runtimes=ProviderProcessManager(),
    )
    service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"}))
    client = TestClient(build_app(service=service))

    response = client.post("/operators/bundles/whisper-a/cooldown/reset")

    assert response.status_code == 200
    assert response.json() == {
        "bundle_id": "whisper-a",
        "status": "ready",
        "cooldown_until": None,
        "cooldown_reason": None,
        "failure_streak": 0,
    }
    assert service.bundle_state("whisper-a") == {
        "bundle_id": "whisper-a",
        "failure_streak": 0,
        "cooldown_until": None,
        "cooldown_reason": None,
        "drain_mode": False,
        "drain_reason": None,
    }


def test_operator_retry_bundle_endpoint_reprocesses_waiting_task(monkeypatch) -> None:
    current_time = [1000.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    monkeypatch.setattr("aidn_hypervisor.service.time.sleep", lambda _: None)
    plugins = PluginRegistry()
    plugin = CooldownApiPlugin()
    plugin.invoke = lambda task, runtime_handle: (_ for _ in ()).throw(RuntimeError("connection refused"))
    plugins.register(plugin)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[_bundle("whisper-a", "speech_to_text").model_copy(update={"plugin_id": "fake-cooldown-api"})],
        plugins=plugins,
        runtimes=ProviderProcessManager(),
    )
    service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"}))
    queued_task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"}))
    plugin.invoke = lambda task, runtime_handle: {
        "ok": True,
        "task_type": task.task_type,
    }
    client = TestClient(build_app(service=service))

    response = client.post("/operators/bundles/whisper-a/retry")

    assert response.status_code == 200
    assert response.json() == {
        "bundle_id": "whisper-a",
        "status": "retried",
        "summary": {"queued": 0, "active": 0, "completed": 1, "failed": 1},
    }
    assert service.get_task(queued_task.task_id).status == "completed"


def test_operator_disable_and_enable_bundle_endpoints_toggle_status() -> None:
    service = _service(with_runtime=True)
    client = TestClient(build_app(service=service))

    disable_response = client.post("/operators/bundles/whisper-a/disable")
    bundles_response = client.get("/bundles")
    enable_response = client.post("/operators/bundles/whisper-a/enable")
    bundles_enabled_response = client.get("/bundles")

    assert disable_response.status_code == 200
    assert disable_response.json() == {
        "bundle_id": "whisper-a",
        "enabled": False,
        "status": "disabled",
    }
    assert bundles_response.status_code == 200
    assert bundles_response.json()[0]["status"] == "disabled"
    assert enable_response.status_code == 200
    assert enable_response.json() == {
        "bundle_id": "whisper-a",
        "enabled": True,
        "status": "enabled",
    }
    assert bundles_enabled_response.status_code == 200
    assert bundles_enabled_response.json()[0]["status"] == "running"


def test_operator_drain_runtime_endpoint_marks_runtime_and_bundle_draining() -> None:
    service = _service(with_runtime=True)
    client = TestClient(build_app(service=service))

    response = client.post("/operators/runtimes/rt-1/drain")
    bundles_response = client.get("/bundles")
    runtimes_response = client.get("/runtimes")

    assert response.status_code == 200
    assert response.json() == {
        "runtime_id": "rt-1",
        "bundle_id": "whisper-a",
        "drain_mode": True,
        "status": "draining",
    }
    assert bundles_response.status_code == 200
    assert bundles_response.json()[0]["status"] == "draining"
    assert runtimes_response.status_code == 200
    assert runtimes_response.json()[0]["drain_mode"] is True
    assert runtimes_response.json()[0]["drain_reason"] == "operator_requested"


def test_operator_force_stop_runtime_endpoint_removes_runtime() -> None:
    service = _service(with_runtime=True)
    client = TestClient(build_app(service=service))

    response = client.post("/operators/runtimes/rt-1/force-stop")
    runtimes_response = client.get("/runtimes")

    assert response.status_code == 200
    assert response.json() == {
        "runtime_id": "rt-1",
        "bundle_id": "whisper-a",
        "status": "force_stopped",
    }
    assert runtimes_response.status_code == 200
    assert runtimes_response.json() == []


def test_operator_restart_runtime_endpoint_clears_drain_and_processes_queue() -> None:
    service = _service(with_runtime=True, use_process_manager=False)
    task = service.queue.enqueue(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))
    service._selected_bundles[task.task_id] = "whisper-a"
    service.drain_runtime("rt-1")
    service.process_pending()
    client = TestClient(build_app(service=service))

    response = client.post("/operators/runtimes/rt-1/restart")
    bundles_response = client.get("/bundles")

    assert response.status_code == 200
    assert response.json()["bundle_id"] == "whisper-a"
    assert response.json()["status"] == "restarted"
    assert service.get_task(task.task_id).status == "completed"
    assert bundles_response.status_code == 200
    assert bundles_response.json()[0]["status"] == "running"


# ---------------------------------------------------------------------------
# Wallet settlement hold / release / correction API endpoints
# ---------------------------------------------------------------------------


class _UsageMeteringPlugin(FakeManagedPlugin):
    """Fake plugin that returns usage data for wallet allocation events."""

    plugin_id = "fake-usage-metering"

    def invoke(self, task, runtime_handle) -> dict:
        return {
            "ok": True,
            "task_type": task.task_type,
            "usage": {
                "input_tokens": 250_000,
                "output_tokens": 500_000,
                "fixed_request_count": 1,
                "measurement_kind": "exact",
                "measurement_source": "provider_api",
            },
        }


def _wallet_service() -> HypervisorService:
    """Build a service with usage-metering plugin for wallet settlement tests."""
    plugins = PluginRegistry()
    plugins.register(_UsageMeteringPlugin())
    bundle = _bundle("phi4-local", "llm_text").model_copy(
        update={"plugin_id": "fake-usage-metering", "endpoint": "http://127.0.0.1:8080"}
    )
    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[bundle],
        plugins=plugins,
        runtimes=ProviderProcessManager(),
        bundle_registry=FileBundleRegistry("bundles.json"),
        node_id="node-a",
        operator_id="operator-a",
        pricing={
            "unit": "q_per_1kk_tokens",
            "input": 12,
            "output": 18,
            "fixed_request": 4,
        },
        wallet_allocation_grace_period_seconds=30,
    )


def _make_wallet_allocation_event(service: HypervisorService) -> dict:
    """Create an allocation, submit a task, release it, and return the event."""
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )
    service.release_allocation(allocation["allocation_id"])
    return service.list_wallet_allocation_events()[0]


def test_operator_wallet_hold_endpoint_success() -> None:
    service = _wallet_service()
    event = _make_wallet_allocation_event(service)
    client = TestClient(build_app(service=service))

    response = client.post(
        f"/operators/wallet/allocations/{event['event_id']}/hold",
        json={"reason": "manual review"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == event["event_id"]
    assert body["settlement_status"] == "hold"
    assert body["hold_reason"] == "manual review"
    assert body["hold_started_at"] is not None


def test_operator_wallet_hold_endpoint_returns_404() -> None:
    service = _wallet_service()
    client = TestClient(build_app(service=service))

    response = client.post(
        "/operators/wallet/allocations/nonexistent-event-id/hold",
        json={"reason": "manual review"},
    )

    assert response.status_code == 404


def test_operator_wallet_hold_endpoint_returns_409_when_already_held() -> None:
    service = _wallet_service()
    event = _make_wallet_allocation_event(service)
    client = TestClient(build_app(service=service))

    client.post(
        f"/operators/wallet/allocations/{event['event_id']}/hold",
        json={"reason": "first hold"},
    )

    response = client.post(
        f"/operators/wallet/allocations/{event['event_id']}/hold",
        json={"reason": "second hold"},
    )

    assert response.status_code == 409


def test_operator_wallet_release_endpoint_success() -> None:
    service = _wallet_service()
    event = _make_wallet_allocation_event(service)
    client = TestClient(build_app(service=service))

    client.post(
        f"/operators/wallet/allocations/{event['event_id']}/hold",
        json={"reason": "manual review"},
    )

    response = client.post(
        f"/operators/wallet/allocations/{event['event_id']}/release",
        json={"reason": "review complete", "target_status": "closed"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["settlement_status"] == "closed"
    assert body["hold_released_at"] is not None
    assert body["closed_at"] is not None


def test_operator_wallet_release_endpoint_returns_409_when_not_held() -> None:
    service = _wallet_service()
    event = _make_wallet_allocation_event(service)
    client = TestClient(build_app(service=service))

    response = client.post(
        f"/operators/wallet/allocations/{event['event_id']}/release",
        json={"reason": "release", "target_status": "closed"},
    )

    assert response.status_code == 409


def test_operator_wallet_correction_endpoint_success() -> None:
    service = _wallet_service()
    event = _make_wallet_allocation_event(service)
    client = TestClient(build_app(service=service))

    client.post(
        f"/operators/wallet/allocations/{event['event_id']}/hold",
        json={"reason": "manual review"},
    )

    response = client.post(
        f"/operators/wallet/allocations/{event['event_id']}/corrections",
        json={
            "reason": "remove duplicate charge",
            "effective_usage_total_q": 0.0,
            "annotations": {"reviewer": "ops"},
            "release_after_apply": False,
            "release_target_status": None,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["effective_usage_total_q"] == 0.0
    assert body["base_usage_total_q"] > 0.0
    assert body["correction_count"] == 1


def test_operator_wallet_corrections_export_with_cursor() -> None:
    service = _wallet_service()
    event = _make_wallet_allocation_event(service)
    client = TestClient(build_app(service=service))

    # Hold the event
    client.post(
        f"/operators/wallet/allocations/{event['event_id']}/hold",
        json={"reason": "manual review"},
    )

    # Apply a correction
    client.post(
        f"/operators/wallet/allocations/{event['event_id']}/corrections",
        json={
            "reason": "ops correction",
            "effective_usage_total_q": 0.0,
            "annotations": {"reviewer": "ops"},
        },
    )

    # Export corrections
    response = client.get(
        "/operators/wallet/allocations/corrections/export",
        params={"after_sequence": 0, "limit": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert len(body["items"]) == 1
    assert body["items"][0]["reason"] == "ops correction"
    assert "next_after_sequence" in body
    assert "cursor_status" in body


def test_operator_wallet_corrections_export_empty() -> None:
    service = _wallet_service()
    client = TestClient(build_app(service=service))

    response = client.get(
        "/operators/wallet/allocations/corrections/export",
        params={"limit": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert len(body["items"]) == 0
    assert "next_after_sequence" in body
    assert "cursor_status" in body
