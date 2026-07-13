import json
import warnings
from datetime import datetime
from pathlib import Path

import pytest

from aidn_hypervisor.registry_models import RegistryDiscoveryQuery, RegistryNodeAdvertisement
from aidn_hypervisor.registry_service import RegistryService


def _bundle(
    bundle_id: str,
    *,
    workload_type: str = "llm_text",
    provider_type: str = "llama.cpp",
    model_id: str = "phi-4-mini.gguf",
    endpoint: str | None = "auto",
    status: str = "ready",
    enabled: bool = True,
    supports_allocation: bool = True,
    supports_queue: bool = True,
) -> dict:
    return {
        "bundle_id": bundle_id,
        "plugin_id": provider_type,
        "workload_type": workload_type,
        "provider_type": provider_type,
        "model_id": model_id,
        "endpoint": (
            f"https://{bundle_id}.example/invoke" if endpoint == "auto" else endpoint
        ),
        "enabled": enabled,
        "status": status,
        "launch_mode": "managed_process",
        "device_affinity": "cpu",
        "max_parallel_requests": 1,
        "supports_allocation": supports_allocation,
        "supports_queue": supports_queue,
    }


def _node(
    node_id: str,
    *,
    bundles: list[dict] | None = None,
    canonical_services: list[dict] | None = None,
    canonical_capability_runtimes: list[dict] | None = None,
    canonical_compute_compatibility: list[dict] | None = None,
    canonical_registry_objects: list[dict] | None = None,
    canonical_advertisements: list[dict] | None = None,
    rating_score: float = 0.91,
    input_price: int = 12,
    output_price: int = 18,
    heartbeat_at: str = "2026-06-19T18:30:00+00:00",
    heartbeat_ttl_seconds: int = 30,
) -> RegistryNodeAdvertisement:
    return RegistryNodeAdvertisement(
        node_id=node_id,
        operator_id=f"{node_id}-operator",
        base_url=f"https://{node_id}.example",
        heartbeat_at=heartbeat_at,
        heartbeat_ttl_seconds=heartbeat_ttl_seconds,
        resources={
            "total": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 8192},
            "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
            "free": {"cpu": 6.0, "ram_mb": 12000, "vram_mb": 6144},
        },
        providers=["llama.cpp", "whisper"],
        can_host_custom_model=True,
        pricing={
            "unit": "q_per_1kk_tokens",
            "input": input_price,
            "output": output_price,
            "fixed_request": None,
        },
        rating={
            "score": rating_score,
            "tier": "A",
            "updated_at": "2026-06-19T18:25:00+00:00",
        },
        bundles=[_bundle("phi4-local")] if bundles is None else bundles,
        canonical_services=[] if canonical_services is None else canonical_services,
        canonical_capability_runtimes=(
            [] if canonical_capability_runtimes is None else canonical_capability_runtimes
        ),
        canonical_compute_compatibility=(
            [] if canonical_compute_compatibility is None else canonical_compute_compatibility
        ),
        canonical_registry_objects=(
            [] if canonical_registry_objects is None else canonical_registry_objects
        ),
        canonical_advertisements=(
            [] if canonical_advertisements is None else canonical_advertisements
        ),
    )


def test_registry_service_upserts_and_returns_node_advertisements() -> None:
    service = RegistryService()
    payload = RegistryNodeAdvertisement(
        node_id="node-a",
        operator_id="operator-a",
        base_url="https://node-a.example",
        heartbeat_at="2026-06-19T18:30:00Z",
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
            "updated_at": "2026-06-19T18:25:00Z",
        },
        bundles=[],
    )

    service.upsert_node(payload)

    assert service.get_node("node-a")["node_id"] == "node-a"
    assert service.list_nodes()[0]["operator_id"] == "operator-a"


def test_registry_node_advertisement_accepts_dual_payload_fields() -> None:
    payload = RegistryNodeAdvertisement(
        node_id="node-a",
        operator_id="operator-a",
        base_url="https://node-a.example",
        heartbeat_at="2026-07-05T14:00:00+00:00",
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
        canonical_services=[
            {
                "service_id": "compute",
                "kind": "compute",
                "enabled": True,
                "derived_roles": ["compute_provider"],
                "responsibilities": ["endpoint_hosting"],
            }
        ],
        canonical_capability_runtimes=[],
        canonical_compute_compatibility=[],
        canonical_advertisements=[],
    )

    assert payload.canonical_services[0].kind == "compute"


def test_registry_service_discovery_preserves_legacy_candidates_for_m2_v2_nodes(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-a",
            operator_id="operator-a",
            registry_version="m2.v2",
            base_url="https://node-a.example",
            heartbeat_at="2026-07-05T14:00:00+00:00",
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
            bundles=[_bundle("phi4-local")],
            canonical_services=[
                {
                    "service_id": "compute",
                    "kind": "compute",
                    "enabled": True,
                    "derived_roles": ["compute_provider"],
                    "responsibilities": ["endpoint_hosting"],
                }
            ],
            canonical_capability_runtimes=[],
            canonical_compute_compatibility=[],
            canonical_advertisements=[],
        )
    )

    result = service.discover(RegistryDiscoveryQuery(workload_type="llm_text"))

    assert result["nodes"][0]["registry_version"] == "m2.v2"
    assert result["candidates"][0]["bundle_id"] == "phi4-local"


def test_registry_service_marks_nodes_stale_and_offline(monkeypatch) -> None:
    current_time = [1000.0]
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: current_time[0])
    service = RegistryService(stale_grace_seconds=30)
    payload = RegistryNodeAdvertisement(
        node_id="node-a",
        operator_id="operator-a",
        base_url="https://node-a.example",
        heartbeat_at="1970-01-01T00:16:40+00:00",
        heartbeat_ttl_seconds=10,
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
            "updated_at": "2026-06-19T18:25:00Z",
        },
        bundles=[],
    )

    service.upsert_node(payload)

    current_time[0] = 1015.0
    assert service.get_node("node-a")["status"] == "stale"
    current_time[0] = 1045.0
    assert service.get_node("node-a")["status"] == "offline"


def test_registry_service_get_registry_object_skips_stale_node_backed_object(
    monkeypatch,
) -> None:
    stale_time = datetime.fromisoformat("2026-07-05T14:00:35+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: stale_time)
    service = RegistryService(stale_grace_seconds=30)
    service.upsert_node(
        _node(
            "node-a",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            heartbeat_ttl_seconds=10,
            canonical_registry_objects=[
                {
                    "object_id": "sha256:stale-only",
                    "object_type": "capability_definition",
                    "object_version": "capdef.v1",
                    "namespace": "protocol",
                    "payload_hash": "sha256:stale-only-payload",
                    "payload_encoding": "canonical_json",
                    "source_reference": "llm.chat",
                }
            ],
        )
    )

    assert service.list_registry_objects() == []
    with pytest.raises(KeyError, match="sha256:stale-only"):
        service.get_registry_object("sha256:stale-only")


def test_registry_service_discovers_matching_bundles_by_workload_and_model(monkeypatch) -> None:
    ready_time = datetime.fromisoformat("2026-06-19T18:30:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-a",
            bundles=[
                _bundle(
                    "phi4-local",
                    workload_type="llm_text",
                    provider_type="llama.cpp",
                    model_id="phi-4-mini.gguf",
                )
            ],
        )
    )
    service.upsert_node(
        _node(
            "node-b",
            bundles=[
                _bundle(
                    "whisper-local",
                    workload_type="speech_to_text",
                    provider_type="whisper",
                    model_id="large-v3",
                )
            ],
        )
    )

    result = service.discover(
        RegistryDiscoveryQuery(workload_type="llm_text", model_id="phi-4-mini")
    )

    assert [node["node_id"] for node in result["nodes"]] == ["node-a"]
    assert result["nodes"][0]["bundles"][0]["bundle_id"] == "phi4-local"
    assert result["nodes"][0]["bundles"][0]["plugin_id"] == "llama.cpp"


def test_registry_service_orders_ready_nodes_by_rating_then_price(monkeypatch) -> None:
    ready_time = datetime.fromisoformat("2026-06-19T18:30:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(_node("node-cheap", rating_score=0.90, input_price=10, output_price=20))
    service.upsert_node(_node("node-better", rating_score=0.95, input_price=12, output_price=22))

    result = service.discover(RegistryDiscoveryQuery(workload_type="llm_text"))

    assert [node["node_id"] for node in result["nodes"]] == ["node-better", "node-cheap"]


def test_registry_service_discovery_returns_flattened_candidates(monkeypatch) -> None:
    ready_time = datetime.fromisoformat("2026-06-19T18:30:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-a",
            bundles=[
                _bundle(
                    "phi4-local",
                    workload_type="llm_text",
                    provider_type="llama.cpp",
                    model_id="phi-4-mini.gguf",
                )
            ],
        )
    )

    result = service.discover(RegistryDiscoveryQuery(workload_type="llm_text"))

    assert result["candidates"] == [
        {
            "node_id": "node-a",
            "operator_id": "node-a-operator",
            "status": "ready",
            "base_url": "https://node-a.example",
            "resources": {
                "total": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 8192},
                "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
                "free": {"cpu": 6.0, "ram_mb": 12000, "vram_mb": 6144},
            },
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
            "bundle_id": "phi4-local",
            "plugin_id": "llama.cpp",
            "provider_type": "llama.cpp",
            "model_id": "phi-4-mini.gguf",
            "workload_type": "llm_text",
            "endpoint": "https://phi4-local.example/invoke",
            "endpoint_ready": True,
            "supports_allocation": True,
            "supports_queue": True,
        }
    ]


def test_registry_service_discovery_returns_canonical_candidates(monkeypatch) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-a",
            bundles=[_bundle("phi4-local")],
            heartbeat_at="2026-07-05T14:00:00+00:00",
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
                    "runtime_id": "runtime-phi4-local",
                    "capability_id": "llm.chat",
                    "runtime_version": "legacy.bundle.v1",
                    "protocol_version": "runtime.v1",
                    "location_kind": "local_process",
                    "health_status": "healthy",
                    "supported_features": ["legacy_bundle_compatibility"],
                }
            ],
            canonical_compute_compatibility=[
                {
                    "compatibility_id": "bundle:phi4-local",
                    "legacy_bundle_id": "phi4-local",
                    "legacy_plugin_id": "llama.cpp",
                    "legacy_provider_type": "llama.cpp",
                    "canonical_capability_id": "llm.chat",
                    "canonical_runtime_id": "runtime-phi4-local",
                }
            ],
            canonical_advertisements=[
                {
                    "advertisement_id": "adv-endpoint-1",
                    "offer_id": "offer-endpoint-1",
                    "resource_type": "endpoint",
                    "owner_wallet": "wallet-a",
                    "hypervisor_id": "node-a",
                    "capability_id": "llm.chat",
                    "capability_version": "2.0.0",
                    "capability_definition_hash": "sha256:capability",
                    "feature_profile_hash": "sha256:feature",
                    "limit_profile_hash": "sha256:limit",
                    "implementation_profile_hash": "sha256:implementation",
                    "visibility": "public",
                    "signature_scope": "configuration_publication",
                }
            ],
        )
    )

    result = service.discover(RegistryDiscoveryQuery(capability_id="llm.chat"))

    assert result["canonical_candidates"][0]["capability_id"] == "llm.chat"
    assert result["canonical_candidates"][0]["capability_version"] == "2.0.0"
    assert result["canonical_candidates"][0]["legacy_bundle_id"] == "phi4-local"
    assert result["canonical_candidates"][0]["offer_id"] == "offer-endpoint-1"
    assert result["canonical_candidates"][0]["capability_definition_hash"] == "sha256:capability"
    assert result["canonical_candidates"][0]["feature_profile_hash"] == "sha256:feature"
    assert result["canonical_candidates"][0]["limit_profile_hash"] == "sha256:limit"
    assert (
        result["canonical_candidates"][0]["implementation_profile_hash"]
        == "sha256:implementation"
    )


def test_registry_service_combined_legacy_and_canonical_filters_require_both(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-legacy-only",
            bundles=[_bundle("phi4-local", workload_type="llm_text")],
            heartbeat_at="2026-07-05T14:00:00+00:00",
        )
    )
    service.upsert_node(
        _node(
            "node-canonical-only",
            bundles=[],
            heartbeat_at="2026-07-05T14:00:00+00:00",
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
                    "runtime_id": "runtime-canonical-only",
                    "capability_id": "llm.chat",
                    "runtime_version": "runtime.v2",
                    "protocol_version": "runtime.v1",
                    "location_kind": "local_process",
                    "health_status": "healthy",
                    "supported_features": ["native_canonical_runtime"],
                }
            ],
            canonical_advertisements=[
                {
                    "advertisement_id": "adv-canonical-only",
                    "resource_type": "endpoint",
                    "owner_wallet": "wallet-canonical-only",
                    "hypervisor_id": "node-canonical-only",
                    "capability_id": "llm.chat",
                    "visibility": "public",
                    "signature_scope": "configuration_publication",
                }
            ],
        )
    )
    service.upsert_node(
        _node(
            "node-both",
            bundles=[_bundle("phi4-both", workload_type="llm_text")],
            heartbeat_at="2026-07-05T14:00:00+00:00",
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
                    "runtime_id": "runtime-both",
                    "capability_id": "llm.chat",
                    "runtime_version": "legacy.bundle.v1",
                    "protocol_version": "runtime.v1",
                    "location_kind": "local_process",
                    "health_status": "healthy",
                    "supported_features": ["legacy_bundle_compatibility"],
                }
            ],
            canonical_compute_compatibility=[
                {
                    "compatibility_id": "bundle:phi4-both",
                    "legacy_bundle_id": "phi4-both",
                    "legacy_plugin_id": "llama.cpp",
                    "legacy_provider_type": "llama.cpp",
                    "canonical_capability_id": "llm.chat",
                    "canonical_runtime_id": "runtime-both",
                }
            ],
            canonical_advertisements=[
                {
                    "advertisement_id": "adv-both",
                    "resource_type": "endpoint",
                    "owner_wallet": "wallet-both",
                    "hypervisor_id": "node-both",
                    "capability_id": "llm.chat",
                    "visibility": "public",
                    "signature_scope": "configuration_publication",
                }
            ],
        )
    )

    result = service.discover(
        RegistryDiscoveryQuery(workload_type="llm_text", capability_id="llm.chat")
    )

    assert [node["node_id"] for node in result["nodes"]] == ["node-both"]
    assert [candidate["node_id"] for candidate in result["candidates"]] == ["node-both"]
    assert [candidate["node_id"] for candidate in result["canonical_candidates"]] == [
        "node-both"
    ]


def test_registry_service_canonical_candidates_keep_runtime_without_legacy_bridge(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-runtime-only",
            bundles=[],
            heartbeat_at="2026-07-05T14:00:00+00:00",
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
                    "runtime_id": "runtime-canonical-direct",
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
                    "advertisement_id": "adv-runtime-direct",
                    "resource_type": "endpoint",
                    "owner_wallet": "wallet-runtime",
                    "hypervisor_id": "node-runtime-only",
                    "capability_id": "llm.chat",
                    "visibility": "public",
                    "signature_scope": "configuration_publication",
                }
            ],
        )
    )

    result = service.discover(RegistryDiscoveryQuery(capability_id="llm.chat"))

    assert result["canonical_candidates"][0]["runtime_id"] == "runtime-canonical-direct"
    assert result["canonical_candidates"][0]["legacy_bundle_id"] is None


def test_registry_service_canonical_candidates_keep_native_runtime_when_capability_is_mixed(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-mixed-runtime",
            bundles=[],
            heartbeat_at="2026-07-05T14:00:00+00:00",
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
                    "runtime_id": "runtime-bridged",
                    "capability_id": "llm.chat",
                    "runtime_version": "legacy.bundle.v1",
                    "protocol_version": "runtime.v1",
                    "location_kind": "local_process",
                    "health_status": "healthy",
                    "supported_features": ["legacy_bundle_compatibility"],
                },
                {
                    "runtime_id": "runtime-native",
                    "capability_id": "llm.chat",
                    "runtime_version": "runtime.v2",
                    "protocol_version": "runtime.v1",
                    "location_kind": "local_process",
                    "health_status": "healthy",
                    "supported_features": ["native_canonical_runtime"],
                },
            ],
            canonical_compute_compatibility=[
                {
                    "compatibility_id": "bundle:phi4-bridged",
                    "legacy_bundle_id": "phi4-bridged",
                    "legacy_plugin_id": "llama.cpp",
                    "legacy_provider_type": "llama.cpp",
                    "canonical_capability_id": "llm.chat",
                    "canonical_runtime_id": "runtime-bridged",
                }
            ],
            canonical_advertisements=[
                {
                    "advertisement_id": "adv-mixed-runtime",
                    "resource_type": "endpoint",
                    "owner_wallet": "wallet-mixed",
                    "hypervisor_id": "node-mixed-runtime",
                    "capability_id": "llm.chat",
                    "visibility": "public",
                    "signature_scope": "configuration_publication",
                }
            ],
        )
    )

    result = service.discover(RegistryDiscoveryQuery(capability_id="llm.chat"))

    assert [candidate["runtime_id"] for candidate in result["canonical_candidates"]] == [
        "runtime-bridged",
        "runtime-native",
    ]
    assert result["canonical_candidates"][0]["legacy_bundle_id"] == "phi4-bridged"
    assert result["canonical_candidates"][1]["legacy_bundle_id"] is None


def test_registry_service_canonical_candidates_preserve_multiple_legacy_bridges_per_runtime(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-multi-bridge",
            bundles=[],
            heartbeat_at="2026-07-05T14:00:00+00:00",
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
                    "runtime_id": "runtime-shared",
                    "capability_id": "llm.chat",
                    "runtime_version": "runtime.v2",
                    "protocol_version": "runtime.v1",
                    "location_kind": "local_process",
                    "health_status": "healthy",
                    "supported_features": ["native_canonical_runtime"],
                }
            ],
            canonical_compute_compatibility=[
                {
                    "compatibility_id": "bundle:phi4-a",
                    "legacy_bundle_id": "phi4-a",
                    "legacy_plugin_id": "llama.cpp",
                    "legacy_provider_type": "llama.cpp",
                    "canonical_capability_id": "llm.chat",
                    "canonical_runtime_id": "runtime-shared",
                },
                {
                    "compatibility_id": "bundle:phi4-b",
                    "legacy_bundle_id": "phi4-b",
                    "legacy_plugin_id": "ollama",
                    "legacy_provider_type": "ollama",
                    "canonical_capability_id": "llm.chat",
                    "canonical_runtime_id": "runtime-shared",
                },
            ],
            canonical_advertisements=[
                {
                    "advertisement_id": "adv-multi-bridge",
                    "resource_type": "endpoint",
                    "owner_wallet": "wallet-multi",
                    "hypervisor_id": "node-multi-bridge",
                    "capability_id": "llm.chat",
                    "visibility": "public",
                    "signature_scope": "configuration_publication",
                }
            ],
        )
    )

    result = service.discover(RegistryDiscoveryQuery(capability_id="llm.chat"))

    assert [candidate["legacy_bundle_id"] for candidate in result["canonical_candidates"]] == [
        "phi4-a",
        "phi4-b",
    ]
    assert [candidate["runtime_id"] for candidate in result["canonical_candidates"]] == [
        "runtime-shared",
        "runtime-shared",
    ]


def test_registry_service_canonical_candidates_map_service_id_from_resource_type(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-registry-service",
            bundles=[],
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_services=[
                {
                    "service_id": "registry",
                    "kind": "registry",
                    "enabled": True,
                    "derived_roles": ["registry_operator"],
                    "responsibilities": ["ledger_storage"],
                }
            ],
            canonical_capability_runtimes=[],
            canonical_compute_compatibility=[],
            canonical_advertisements=[
                {
                    "advertisement_id": "adv-registry-service",
                    "resource_type": "registry_service",
                    "owner_wallet": "wallet-registry",
                    "hypervisor_id": "node-registry-service",
                    "capability_id": None,
                    "visibility": "public",
                    "signature_scope": "configuration_publication",
                }
            ],
        )
    )

    result = service.discover(
        RegistryDiscoveryQuery(advertisement_resource_type="registry_service")
    )

    assert result["canonical_candidates"][0]["service_id"] == "registry"


def test_registry_service_legacy_discovery_does_not_include_canonical_only_nodes(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-canonical",
            bundles=[],
            heartbeat_at="2026-07-05T14:00:00+00:00",
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
                    "runtime_id": "runtime-canonical-only",
                    "capability_id": "llm.chat",
                    "runtime_version": "legacy.bundle.v1",
                    "protocol_version": "runtime.v1",
                    "location_kind": "local_process",
                    "health_status": "healthy",
                    "supported_features": ["legacy_bundle_compatibility"],
                }
            ],
            canonical_compute_compatibility=[],
            canonical_advertisements=[
                {
                    "advertisement_id": "adv-endpoint-canonical-only",
                    "resource_type": "endpoint",
                    "owner_wallet": "wallet-a",
                    "hypervisor_id": "node-canonical",
                    "capability_id": "llm.chat",
                    "visibility": "public",
                    "signature_scope": "configuration_publication",
                }
            ],
        )
    )

    result = service.discover(RegistryDiscoveryQuery())

    assert result["nodes"] == []
    assert result["candidates"] == []


def test_registry_service_filters_and_orders_candidates_by_execution_readiness(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-06-19T18:30:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-a",
            rating_score=0.99,
            bundles=[
                _bundle(
                    "text-no-endpoint",
                    endpoint=None,
                    supports_allocation=True,
                    supports_queue=True,
                )
            ],
        )
    )
    service.upsert_node(
        _node(
            "node-b",
            rating_score=0.90,
            bundles=[
                _bundle(
                    "text-ready",
                    endpoint="https://node-b.example/runtimes/text-ready",
                    supports_allocation=True,
                    supports_queue=True,
                ),
                _bundle(
                    "text-queue-only",
                    endpoint="https://node-b.example/runtimes/text-queue-only",
                    supports_allocation=False,
                    supports_queue=True,
                ),
            ],
        )
    )

    filtered = service.discover(
        RegistryDiscoveryQuery(
            workload_type="llm_text",
            require_allocation_support=True,
            ready_endpoint_only=True,
        )
    )
    queue_only = service.discover(
        RegistryDiscoveryQuery(
            workload_type="llm_text",
            require_queue_support=True,
        )
    )
    unfiltered = service.discover(RegistryDiscoveryQuery(workload_type="llm_text"))

    assert [candidate["bundle_id"] for candidate in filtered["candidates"]] == ["text-ready"]
    assert [candidate["bundle_id"] for candidate in queue_only["candidates"]] == [
        "text-ready",
        "text-queue-only",
        "text-no-endpoint",
    ]
    assert [candidate["bundle_id"] for candidate in unfiltered["candidates"]] == [
        "text-ready",
        "text-queue-only",
        "text-no-endpoint",
    ]
    assert unfiltered["candidates"][0]["endpoint_ready"] is True
    assert unfiltered["candidates"][-1]["endpoint_ready"] is False


def test_registry_service_lists_deduplicated_registry_objects_with_sources(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    object_row = {
        "object_id": "sha256:capdef-1",
        "object_type": "capability_definition",
        "object_version": "capdef.v1",
        "namespace": "protocol",
        "payload_hash": "sha256:payload-1",
        "payload_encoding": "canonical_json",
        "source_reference": "llm.chat",
    }
    service.upsert_node(
        _node(
            "node-a",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[object_row],
        )
    )
    service.upsert_node(
        _node(
            "node-b",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[object_row],
        )
    )

    objects = service.list_registry_objects()

    assert len(objects) == 1
    assert objects[0]["object_id"] == "sha256:capdef-1"
    assert objects[0]["source_count"] == 2
    assert [item["node_id"] for item in objects[0]["sources"]] == ["node-a", "node-b"]


def test_registry_service_queries_registry_objects_by_object_type_and_source_reference(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-a",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[
                {
                    "object_id": "sha256:feature-1",
                    "object_type": "endpoint_feature_profile",
                    "object_version": "feature-profile.v1",
                    "namespace": "marketplace",
                    "payload_hash": "sha256:feature-payload",
                    "payload_encoding": "canonical_json",
                    "source_reference": "adv-pub-1",
                },
                {
                    "object_id": "sha256:capdef-1",
                    "object_type": "capability_definition",
                    "object_version": "capdef.v1",
                    "namespace": "protocol",
                    "payload_hash": "sha256:capdef-payload",
                    "payload_encoding": "canonical_json",
                    "source_reference": "llm.chat",
                },
            ],
        )
    )

    objects = service.list_registry_objects(
        query={
            "object_type": "endpoint_feature_profile",
            "source_reference": "adv-pub-1",
        }
    )

    assert [item["object_id"] for item in objects] == ["sha256:feature-1"]


def test_registry_service_get_registry_object_returns_single_deduplicated_record(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-a",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[
                {
                    "object_id": "sha256:acct-1",
                    "object_type": "accounting_contract",
                    "object_version": "acctobj.v1",
                    "namespace": "usage",
                    "payload_hash": "sha256:acct-payload",
                    "payload_encoding": "canonical_json",
                    "source_reference": "ep-1",
                }
            ],
        )
    )

    item = service.get_registry_object("sha256:acct-1")

    assert item["object_type"] == "accounting_contract"
    assert item["namespace"] == "usage"
    assert item["sources"][0]["node_id"] == "node-a"


def test_registry_service_includes_payload_only_when_requested(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-a",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[
                {
                    "object_id": "sha256:capdef-1",
                    "object_type": "capability_definition",
                    "object_version": "capdef.v1",
                    "namespace": "protocol",
                    "payload_hash": "sha256:capdef-payload",
                    "payload_encoding": "canonical_json",
                    "source_reference": "llm.chat",
                    "payload": {
                        "capability_id": "llm.chat",
                        "capability_version": "2.0.0",
                    },
                }
            ],
        )
    )

    without_payload = service.get_registry_object("sha256:capdef-1")
    with_payload = service.get_registry_object("sha256:capdef-1", include_payload=True)
    listed_with_payload = service.list_registry_objects(query={"include_payload": True})

    assert "payload" not in without_payload
    assert with_payload["payload"]["capability_id"] == "llm.chat"
    assert listed_with_payload[0]["payload"]["capability_version"] == "2.0.0"


def test_registry_service_lists_store_backed_objects_without_node_advertisement() -> None:
    service = RegistryService()

    service.upsert_registry_object(
        {
            "object_id": "sha256:stored-1",
            "object_type": "capability_definition",
            "object_version": "capdef.v1",
            "namespace": "protocol",
            "payload_hash": "sha256:stored-payload-1",
            "payload_encoding": "canonical_json",
            "source_reference": "llm.chat",
        }
    )

    objects = service.list_registry_objects()

    assert objects == [
        {
            "object_id": "sha256:stored-1",
            "object_type": "capability_definition",
            "object_version": "capdef.v1",
            "namespace": "protocol",
            "payload_hash": "sha256:stored-payload-1",
            "payload_encoding": "canonical_json",
            "source_reference": "llm.chat",
            "source_count": 1,
            "sources": [{"node_id": None, "operator_id": None, "status": "stored"}],
        }
    ]


def test_registry_service_returns_empty_local_completeness_summary() -> None:
    service = RegistryService()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        summary = service.get_local_registry_completeness_summary()

    assert summary.summary_version == "registry-local-completeness-summary.v1"
    assert summary.generated_at
    assert summary.generated_at.endswith("Z")
    assert datetime.fromisoformat(summary.generated_at.replace("Z", "+00:00"))
    assert summary.snapshot_schema_version == "registry-object-store.v1"
    assert summary.store_totals.total_object_count == 0
    assert summary.store_totals.payload_object_count == 0
    assert summary.store_totals.payload_bytes_total == 0
    assert summary.by_namespace == {}
    assert summary.by_object_type == {}
    assert summary.integrity.object_count_matches_store is True
    assert summary.integrity.all_object_ids_unique is True
    assert summary.integrity.all_required_fields_present is True
    assert summary.integrity.payload_hash_coverage_count == 0
    assert summary.integrity.issues == []
    assert [
        warning
        for warning in caught
        if issubclass(warning.category, DeprecationWarning)
    ] == []


def test_registry_service_summarizes_local_store_counts_and_payload_bytes() -> None:
    service = RegistryService()
    payload_one = {"capability_id": "llm.chat", "status": "active"}
    payload_two = {"pricing_model": "fixed", "unit_price_q": 2}

    service.ingest_registry_objects(
        [
            {
                "object_id": "sha256:capdef-1",
                "object_type": "capability_definition",
                "object_version": "1.0",
                "namespace": "protocol",
                "payload_hash": "sha256:payload-capdef-1",
                "payload_encoding": "canonical_json",
                "source_reference": "capdef:llm.chat:v1",
                "payload": payload_one,
            },
            {
                "object_id": "sha256:pricing-1",
                "object_type": "pricing_policy",
                "object_version": "1.0",
                "namespace": "marketplace",
                "payload_hash": "sha256:payload-pricing-1",
                "payload_encoding": "canonical_json",
                "source_reference": "pricing:endpoint-1:v1",
                "payload": payload_two,
            },
            {
                "object_id": "sha256:pricing-2",
                "object_type": "pricing_policy",
                "object_version": "1.0",
                "namespace": "marketplace",
                "payload_hash": "sha256:payload-pricing-2",
                "payload_encoding": "canonical_json",
                "source_reference": "pricing:endpoint-2:v1",
            },
        ]
    )

    summary = service.get_local_registry_completeness_summary()
    expected_payload_bytes = sum(
        len(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        )
        for payload in (payload_one, payload_two)
    )

    assert summary.store_totals.total_object_count == 3
    assert summary.store_totals.payload_object_count == 2
    assert summary.store_totals.payload_bytes_total == expected_payload_bytes
    assert summary.by_namespace == {"marketplace": 2, "protocol": 1}
    assert summary.by_object_type == {
        "capability_definition": 1,
        "pricing_policy": 2,
    }
    assert summary.integrity.payload_hash_coverage_count == 3


def test_registry_service_surfaces_missing_required_fields_in_summary_issues() -> None:
    service = RegistryService()
    service._registry_objects["sha256:broken-1"] = {
        "object_id": "sha256:broken-1",
        "object_version": "1.0",
        "payload_hash": "sha256:broken-payload",
        "payload_encoding": "canonical_json",
        "source_reference": "broken:1",
    }

    summary = service.get_local_registry_completeness_summary()

    assert summary.store_totals.total_object_count == 1
    assert summary.integrity.all_required_fields_present is False
    assert summary.integrity.object_count_matches_store is True
    assert summary.integrity.all_object_ids_unique is True
    assert {(issue.code, issue.field) for issue in summary.integrity.issues} == {
        ("missing_required_field", "namespace"),
        ("missing_required_field", "object_type"),
    }


def test_registry_service_raises_for_non_mapping_store_record_in_summary() -> None:
    service = RegistryService()
    service._registry_objects["sha256:bad-shape"] = "not-a-dict"

    with pytest.raises(
        ValueError,
        match="Registry object store contains non-object record for sha256:bad-shape",
    ):
        service.get_local_registry_completeness_summary()


def test_registry_service_local_completeness_summary_survives_restart(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    payload = {"pricing_model": "fixed", "unit_price_q": 2}
    seeded = RegistryService(snapshot_path=snapshot_path)
    seeded.upsert_registry_object(
        {
            "object_id": "sha256:restart-summary-1",
            "object_type": "pricing_policy",
            "object_version": "1.0",
            "namespace": "marketplace",
            "payload_hash": "sha256:restart-payload-1",
            "payload_encoding": "canonical_json",
            "source_reference": "pricing:restart-1",
            "payload": payload,
        }
    )

    before = seeded.get_local_registry_completeness_summary()
    restarted = RegistryService(snapshot_path=snapshot_path)
    after = restarted.get_local_registry_completeness_summary()

    assert after.summary_version == before.summary_version
    assert after.snapshot_schema_version == before.snapshot_schema_version
    assert after.store_totals == before.store_totals
    assert after.by_namespace == before.by_namespace
    assert after.by_object_type == before.by_object_type
    assert after.integrity == before.integrity


def test_registry_service_rejects_conflicting_store_and_node_backed_object(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_registry_object(
        {
            "object_id": "sha256:shared-1",
            "object_type": "capability_definition",
            "object_version": "capdef.v1",
            "namespace": "protocol",
            "payload_hash": "sha256:stored-payload",
            "payload_encoding": "canonical_json",
            "source_reference": "llm.chat",
            "payload": {
                "capability_id": "llm.chat",
                "capability_version": "2.0.1",
            },
        }
    )
    service.upsert_node(
        _node(
            "node-a",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[
                {
                    "object_id": "sha256:shared-1",
                    "object_type": "capability_definition",
                    "object_version": "capdef.v1",
                    "namespace": "protocol",
                    "payload_hash": "sha256:node-payload",
                    "payload_encoding": "canonical_json",
                    "source_reference": "llm.chat",
                    "payload": {
                        "capability_id": "llm.chat",
                        "capability_version": "2.0.0",
                    },
                }
            ],
        )
    )

    with pytest.raises(ValueError, match="sha256:shared-1"):
        service.get_registry_object("sha256:shared-1", include_payload=True)

    with pytest.raises(ValueError, match="sha256:shared-1"):
        service.list_registry_objects(query={"include_payload": True})


def test_registry_service_include_payload_works_for_store_backed_objects() -> None:
    service = RegistryService()
    service.ingest_registry_objects(
        [
            {
                "object_id": "sha256:stored-2",
                "object_type": "endpoint_feature_profile",
                "object_version": "feature-profile.v1",
                "namespace": "marketplace",
                "payload_hash": "sha256:stored-payload-2",
                "payload_encoding": "canonical_json",
                "source_reference": "adv-pub-1",
                "payload": {"feature_flags": ["streaming"]},
            }
        ]
    )

    without_payload = service.get_registry_object("sha256:stored-2")
    with_payload = service.get_registry_object("sha256:stored-2", include_payload=True)
    listed_with_payload = service.list_registry_objects(query={"include_payload": True})

    assert "payload" not in without_payload
    assert with_payload["payload"] == {"feature_flags": ["streaming"]}
    assert listed_with_payload == [
        {
            "object_id": "sha256:stored-2",
            "object_type": "endpoint_feature_profile",
            "object_version": "feature-profile.v1",
            "namespace": "marketplace",
            "payload_hash": "sha256:stored-payload-2",
            "payload_encoding": "canonical_json",
            "source_reference": "adv-pub-1",
            "payload": {"feature_flags": ["streaming"]},
            "source_count": 1,
            "sources": [{"node_id": None, "operator_id": None, "status": "stored"}],
        }
    ]


def test_registry_service_prefers_explicit_source_metadata_for_store_backed_objects() -> None:
    service = RegistryService()
    service.ingest_registry_objects(
        [
            {
                "object_id": "sha256:stored-local",
                "object_type": "capability_definition",
                "object_version": "capdef.v1",
                "namespace": "protocol",
                "payload_hash": "sha256:stored-local-payload",
                "payload_encoding": "canonical_json",
                "source_reference": "llm.chat",
                "_source": {
                    "node_id": "node-local",
                    "operator_id": "operator-local",
                    "status": "ready",
                },
            }
        ]
    )

    listed = service.list_registry_objects()
    fetched = service.get_registry_object("sha256:stored-local")

    assert listed[0]["sources"] == [
        {"node_id": "node-local", "operator_id": "operator-local", "status": "ready"}
    ]
    assert fetched["sources"] == listed[0]["sources"]


def test_registry_service_persists_store_backed_objects_across_restart(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    service = RegistryService(snapshot_path=snapshot_path)

    service.upsert_registry_object(
        {
            "object_id": "sha256:stored-restart",
            "object_type": "capability_definition",
            "object_version": "capdef.v1",
            "namespace": "protocol",
            "payload_hash": "sha256:stored-restart-payload",
            "payload_encoding": "canonical_json",
            "source_reference": "llm.chat",
            "payload": {
                "capability_id": "llm.chat",
                "capability_version": "2.1.0",
            },
            "_source": {
                "node_id": "node-local",
                "operator_id": "operator-local",
                "status": "ready",
            },
        }
    )

    restarted = RegistryService(snapshot_path=snapshot_path)
    fetched = restarted.get_registry_object("sha256:stored-restart", include_payload=True)

    assert fetched["payload"]["capability_version"] == "2.1.0"
    assert fetched["sources"] == [
        {"node_id": "node-local", "operator_id": "operator-local", "status": "ready"}
    ]


def test_registry_service_preserved_snapshot_conflicts_with_node_backed_duplicate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    snapshot_path = tmp_path / "registry-objects.json"

    seeded = RegistryService(snapshot_path=snapshot_path)
    seeded.upsert_registry_object(
        {
            "object_id": "sha256:shared-restart",
            "object_type": "capability_definition",
            "object_version": "capdef.v1",
            "namespace": "protocol",
            "payload_hash": "sha256:stored-shared-payload",
            "payload_encoding": "canonical_json",
            "source_reference": "llm.chat",
            "payload": {"capability_version": "2.1.0"},
        }
    )

    restarted = RegistryService(snapshot_path=snapshot_path)
    restarted.upsert_node(
        _node(
            "node-a",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[
                {
                    "object_id": "sha256:shared-restart",
                    "object_type": "capability_definition",
                    "object_version": "capdef.v1",
                    "namespace": "protocol",
                    "payload_hash": "sha256:node-shared-payload",
                    "payload_encoding": "canonical_json",
                    "source_reference": "llm.chat",
                    "payload": {"capability_version": "2.0.0"},
                }
            ],
        )
    )

    with pytest.raises(ValueError, match="sha256:shared-restart"):
        restarted.get_registry_object("sha256:shared-restart", include_payload=True)


def test_registry_service_writes_versioned_snapshot_file_on_upsert(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    service = RegistryService(snapshot_path=snapshot_path)

    service.upsert_registry_object(
        {
            "object_id": "sha256:stored-file",
            "object_type": "accounting_contract",
            "object_version": "acctobj.v1",
            "namespace": "usage",
            "payload_hash": "sha256:stored-file-payload",
            "payload_encoding": "canonical_json",
            "source_reference": "endpoint-1",
            "payload": {"accounting_mode": "fixed_price"},
        }
    )

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert snapshot["schema_version"] == "registry-object-store.v1"
    assert snapshot["objects"][0]["object_id"] == "sha256:stored-file"
    assert snapshot["objects"][0]["payload"] == {"accounting_mode": "fixed_price"}


def test_registry_service_batch_ingest_persists_all_objects_once_per_batch(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    service = RegistryService(snapshot_path=snapshot_path)

    service.ingest_registry_objects(
        [
            {
                "object_id": "sha256:stored-batch-a",
                "object_type": "capability_definition",
                "object_version": "capdef.v1",
                "namespace": "protocol",
                "payload_hash": "sha256:stored-batch-a-payload",
                "payload_encoding": "canonical_json",
                "source_reference": "llm.chat",
            },
            {
                "object_id": "sha256:stored-batch-b",
                "object_type": "endpoint_feature_profile",
                "object_version": "feature-profile.v1",
                "namespace": "marketplace",
                "payload_hash": "sha256:stored-batch-b-payload",
                "payload_encoding": "canonical_json",
                "source_reference": "adv-pub-1",
            },
        ]
    )

    restarted = RegistryService(snapshot_path=snapshot_path)
    listed = restarted.list_registry_objects()

    assert [item["object_id"] for item in listed] == [
        "sha256:stored-batch-a",
        "sha256:stored-batch-b",
    ]


def test_registry_service_starts_empty_when_snapshot_path_does_not_exist(
    tmp_path: Path,
) -> None:
    service = RegistryService(snapshot_path=tmp_path / "missing.json")

    assert service.list_registry_objects() == []


def test_registry_service_rejects_invalid_snapshot_schema_version(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    snapshot_path.write_text(
        json.dumps({"schema_version": "registry-object-store.v999", "objects": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="registry-object-store.v999"):
        RegistryService(snapshot_path=snapshot_path)


def test_registry_service_rejects_snapshot_with_invalid_object_entry(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": "registry-object-store.v1",
                "objects": ["bad"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid object entry"):
        RegistryService(snapshot_path=snapshot_path)


def test_registry_service_rejects_snapshot_with_malformed_object_entry(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": "registry-object-store.v1",
                "objects": [{}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid object entry"):
        RegistryService(snapshot_path=snapshot_path)


def test_registry_service_rejects_malformed_snapshot_payload(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    snapshot_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError, match="Malformed registry object snapshot"):
        RegistryService(snapshot_path=snapshot_path)


def test_registry_service_rejects_snapshot_with_non_object_root(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    snapshot_path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="Registry object snapshot must be a JSON object"):
        RegistryService(snapshot_path=snapshot_path)


def test_registry_service_rolls_back_upsert_when_snapshot_persist_fails(
    monkeypatch,
) -> None:
    service = RegistryService()

    def fail_persist() -> None:
        raise OSError("disk full")

    monkeypatch.setattr(service, "_persist_registry_object_snapshot", fail_persist)

    with pytest.raises(OSError, match="disk full"):
        service.upsert_registry_object(
            {
                "object_id": "sha256:rollback-upsert",
                "object_type": "capability_definition",
                "object_version": "capdef.v1",
                "namespace": "protocol",
                "payload_hash": "sha256:rollback-upsert-payload",
                "payload_encoding": "canonical_json",
                "source_reference": "llm.chat",
            }
        )

    assert service.list_registry_objects() == []


def test_registry_service_rolls_back_batch_when_snapshot_persist_fails(
    monkeypatch,
) -> None:
    service = RegistryService()
    service.upsert_registry_object(
        {
            "object_id": "sha256:existing",
            "object_type": "capability_definition",
            "object_version": "capdef.v1",
            "namespace": "protocol",
            "payload_hash": "sha256:existing-payload",
            "payload_encoding": "canonical_json",
            "source_reference": "llm.chat.existing",
        },
        persist=False,
    )

    def fail_persist() -> None:
        raise OSError("disk full")

    monkeypatch.setattr(service, "_persist_registry_object_snapshot", fail_persist)

    with pytest.raises(OSError, match="disk full"):
        service.ingest_registry_objects(
            [
                {
                    "object_id": "sha256:new-a",
                    "object_type": "capability_definition",
                    "object_version": "capdef.v1",
                    "namespace": "protocol",
                    "payload_hash": "sha256:new-a-payload",
                    "payload_encoding": "canonical_json",
                    "source_reference": "llm.chat.new-a",
                },
                {
                    "object_id": "sha256:new-b",
                    "object_type": "endpoint_feature_profile",
                    "object_version": "feature-profile.v1",
                    "namespace": "marketplace",
                    "payload_hash": "sha256:new-b-payload",
                    "payload_encoding": "canonical_json",
                    "source_reference": "adv.new-b",
                },
            ]
        )

    assert [item["object_id"] for item in service.list_registry_objects()] == ["sha256:existing"]


def test_registry_service_get_registry_object_looks_past_first_500_items() -> None:
    service = RegistryService()
    for index in range(501):
        service.upsert_registry_object(
            {
                "object_id": f"sha256:stored-{index:03d}",
                "object_type": "capability_definition",
                "object_version": "capdef.v1",
                "namespace": "protocol",
                "payload_hash": f"sha256:payload-{index:03d}",
                "payload_encoding": "canonical_json",
                "source_reference": f"llm.chat.{index:03d}",
            }
        )

    item = service.get_registry_object("sha256:stored-500")

    assert item["object_id"] == "sha256:stored-500"
    assert item["payload_hash"] == "sha256:payload-500"


def test_registry_service_rejects_conflicting_node_backed_duplicate_objects(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    shared_id = "sha256:capdef-conflict"
    service.upsert_node(
        _node(
            "node-a",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[
                {
                    "object_id": shared_id,
                    "object_type": "capability_definition",
                    "object_version": "capdef.v1",
                    "namespace": "protocol",
                    "payload_hash": "sha256:payload-a",
                    "payload_encoding": "canonical_json",
                    "source_reference": "llm.chat",
                    "payload": {"capability_version": "2.0.0"},
                }
            ],
        )
    )
    service.upsert_node(
        _node(
            "node-b",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[
                {
                    "object_id": shared_id,
                    "object_type": "capability_definition",
                    "object_version": "capdef.v2",
                    "namespace": "protocol",
                    "payload_hash": "sha256:payload-b",
                    "payload_encoding": "canonical_json",
                    "source_reference": "llm.chat",
                    "payload": {"capability_version": "2.1.0"},
                }
            ],
        )
    )

    with pytest.raises(ValueError, match=shared_id):
        service.list_registry_objects(query={"include_payload": True})


def test_registry_service_get_node_returns_deep_copied_nested_state() -> None:
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-a",
            bundles=[_bundle("phi4-local")],
        )
    )

    item = service.get_node("node-a")
    item["resources"]["free"]["cpu"] = 0.0
    item["bundles"][0]["endpoint"] = "https://mutated.example/invoke"

    fresh = service.get_node("node-a")

    assert fresh["resources"]["free"]["cpu"] == 6.0
    assert fresh["bundles"][0]["endpoint"] == "https://phi4-local.example/invoke"


def test_registry_service_get_registry_object_returns_deep_copied_payload() -> None:
    service = RegistryService()
    service.upsert_registry_object(
        {
            "object_id": "sha256:stored-copy",
            "object_type": "capability_definition",
            "object_version": "capdef.v1",
            "namespace": "protocol",
            "payload_hash": "sha256:stored-copy-payload",
            "payload_encoding": "canonical_json",
            "source_reference": "llm.chat",
            "payload": {"feature_flags": ["streaming"]},
        }
    )

    item = service.get_registry_object("sha256:stored-copy", include_payload=True)
    item["payload"]["feature_flags"].append("mutated")

    fresh = service.get_registry_object("sha256:stored-copy", include_payload=True)

    assert fresh["payload"] == {"feature_flags": ["streaming"]}
