from datetime import datetime

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
        bundles=bundles or [_bundle("phi4-local")],
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
