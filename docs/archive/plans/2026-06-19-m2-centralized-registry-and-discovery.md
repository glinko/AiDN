# M2 Centralized Registry And Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a centralized in-memory registry service that accepts node advertisements, tracks heartbeat freshness, and returns bundle-level discovery results for agents and routers.

**Architecture:** Keep the local hypervisor as the execution plane and introduce a separate `RegistryService` bounded context for shared metadata. The hypervisor will expose one derived node advertisement payload, while the new registry app will own advertisement ingestion, freshness state, filtering, and discovery ordering.

**Tech Stack:** `Python`, `FastAPI`, `Pydantic`, `pytest`, existing `HypervisorService`, new `RegistryService`, existing app builder pattern in `main.py`.

---

## File Map

- Create: `src/aidn_hypervisor/registry_models.py`
- Create: `src/aidn_hypervisor/registry_service.py`
- Create: `src/aidn_hypervisor/registry_api.py`
- Create: `tests/test_registry_service.py`
- Create: `tests/test_registry_api.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `src/aidn_hypervisor/main.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_smoke.py`

### Task 1: Hypervisor Node Advertisement Export

**Files:**
- Create: `src/aidn_hypervisor/registry_models.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing service and API tests for a derived node advertisement**

```python
def test_service_node_advertisement_reports_resources_pricing_and_bundles() -> None:
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
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        node_id="node-local",
        operator_id="operator-a",
        base_url="https://node.example",
        can_host_custom_model=True,
        pricing={"unit": "q_per_1kk_tokens", "input": 12, "output": 18, "fixed_request": None},
        rating={"score": 0.91, "tier": "A", "updated_at": "2026-06-19T18:25:00Z"},
    )

    payload = service.node_advertisement(heartbeat_at="2026-06-19T18:30:00Z")

    assert payload["node_id"] == "node-local"
    assert payload["operator_id"] == "operator-a"
    assert payload["can_host_custom_model"] is True
    assert payload["pricing"]["input"] == 12
    assert payload["rating"]["score"] == 0.91
    assert payload["bundles"][0]["bundle_id"] == "whisper-a"
    assert payload["bundles"][0]["status"] == "ready"


def test_operator_registry_advertisement_endpoint_returns_current_node_payload() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    service.node_id = "node-local"
    service.operator_id = "operator-a"
    service.base_url = "https://node.example"
    service.can_host_custom_model = False
    service.pricing = {"unit": "q_per_1kk_tokens", "input": 10, "output": 14, "fixed_request": None}
    service.rating = {"score": 0.88, "tier": "B", "updated_at": "2026-06-19T18:20:00Z"}
    client = TestClient(build_app(service=service))

    response = client.get("/operators/registry/advertisement")

    assert response.status_code == 200
    assert response.json()["node_id"] == "node-local"
    assert response.json()["bundles"][0]["bundle_id"] == "whisper-a"
```

Registry advertisement `status` represents advertisable availability. An enabled bundle without a running runtime may still export as `"ready"` here even if inventory-oriented endpoints would report `"stopped"`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_service.py -k node_advertisement -q`
Expected: FAIL because `HypervisorService` has no node advertisement fields or method.

Run: `python -m pytest tests/test_api.py -k registry_advertisement -q`
Expected: FAIL with missing `/operators/registry/advertisement` route.

- [ ] **Step 3: Create focused registry models for advertisement payloads**

```python
from pydantic import BaseModel, Field


class RegistryPricing(BaseModel):
    unit: str = "q_per_1kk_tokens"
    input: int = Field(ge=0)
    output: int = Field(ge=0)
    fixed_request: int | None = Field(default=None, ge=0)


class RegistryRating(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    tier: str
    updated_at: str


class RegistryBundleAdvertisement(BaseModel):
    bundle_id: str
    workload_type: str
    provider_type: str
    model_id: str
    endpoint: str | None = None
    enabled: bool
    status: str
    launch_mode: str
    device_affinity: str
    max_parallel_requests: int
    supports_allocation: bool = True
    supports_queue: bool = True


class RegistryNodeAdvertisement(BaseModel):
    node_id: str
    operator_id: str
    registry_version: str = "m2.v1"
    base_url: str
    heartbeat_at: str
    heartbeat_ttl_seconds: int = 30
    status: str = "ready"
    resources: dict[str, dict[str, float | int]]
    providers: list[str]
    can_host_custom_model: bool
    pricing: RegistryPricing
    rating: RegistryRating
    bundles: list[RegistryBundleAdvertisement]
```

- [ ] **Step 4: Add node advertisement fields and serializer to `HypervisorService`**

```python
def __init__(
    self,
    queue: InMemoryTaskQueue,
    scheduler: Scheduler,
    resources=None,
    bundles=None,
    plugins=None,
    runtimes=None,
    state_store=None,
    bundle_registry=None,
    model_store=None,
    max_active_allocations_per_owner: int = 2,
    max_pending_allocations_per_owner: int = 4,
    node_id: str = "node-local",
    operator_id: str = "operator-local",
    base_url: str = "http://127.0.0.1:8000",
    can_host_custom_model: bool = False,
    pricing: dict | None = None,
    rating: dict | None = None,
    heartbeat_ttl_seconds: int = 30,
) -> None:
    ...
    self.node_id = node_id
    self.operator_id = operator_id
    self.base_url = base_url
    self.can_host_custom_model = can_host_custom_model
    self.pricing = pricing or {
        "unit": "q_per_1kk_tokens",
        "input": 0,
        "output": 0,
        "fixed_request": None,
    }
    self.rating = rating or {
        "score": 0.0,
        "tier": "unrated",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    self.heartbeat_ttl_seconds = heartbeat_ttl_seconds


def node_advertisement(self, *, heartbeat_at: str | None = None) -> dict:
    timestamp = heartbeat_at or datetime.now(timezone.utc).isoformat()
    resources = self.resources.summary() if self.resources is not None else _empty_resource_summary()
    providers = sorted({bundle.provider_type for bundle in self.bundles})
    bundles = [
        {
            "bundle_id": bundle.bundle_id,
            "workload_type": bundle.workload_type,
            "provider_type": bundle.provider_type,
            "model_id": bundle.model_id,
            "endpoint": bundle.endpoint,
            "enabled": bundle.enabled,
            "status": self._bundle_registry_status(bundle),
            "launch_mode": bundle.launch_mode,
            "device_affinity": bundle.device_affinity,
            "max_parallel_requests": bundle.max_parallel_requests,
            "supports_allocation": True,
            "supports_queue": True,
        }
        for bundle in self.bundles
    ]
    return {
        "node_id": self.node_id,
        "operator_id": self.operator_id,
        "registry_version": "m2.v1",
        "base_url": self.base_url,
        "heartbeat_at": timestamp,
        "heartbeat_ttl_seconds": self.heartbeat_ttl_seconds,
        "status": "ready",
        "resources": resources,
        "providers": providers,
        "can_host_custom_model": self.can_host_custom_model,
        "pricing": dict(self.pricing),
        "rating": dict(self.rating),
        "bundles": bundles,
    }
```

- [ ] **Step 5: Expose the operator advertisement preview endpoint**

```python
@router.get("/operators/registry/advertisement")
async def registry_advertisement() -> dict:
    return service.node_advertisement()
```

- [ ] **Step 6: Run tests to verify it passes**

Run: `python -m pytest tests/test_service.py -k node_advertisement -q`
Expected: PASS

Run: `python -m pytest tests/test_api.py -k registry_advertisement -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/aidn_hypervisor/registry_models.py src/aidn_hypervisor/service.py src/aidn_hypervisor/api.py tests/test_service.py tests/test_api.py
git commit -m "feat: add hypervisor registry advertisement export"
```

### Task 2: In-Memory Registry State And Freshness

**Files:**
- Create: `src/aidn_hypervisor/registry_service.py`
- Create: `tests/test_registry_service.py`
- Create: `src/aidn_hypervisor/registry_models.py`

- [ ] **Step 1: Write the failing registry service tests**

```python
def _bundle(
    bundle_id: str,
    *,
    workload_type: str = "llm_text",
    provider_type: str = "llama.cpp",
    model_id: str = "phi-4-mini.gguf",
) -> dict:
    return {
        "bundle_id": bundle_id,
        "workload_type": workload_type,
        "provider_type": provider_type,
        "model_id": model_id,
        "endpoint": f"https://{bundle_id}.example/invoke",
        "enabled": True,
        "status": "ready",
        "launch_mode": "managed_process",
        "device_affinity": "cpu",
        "max_parallel_requests": 1,
        "supports_allocation": True,
        "supports_queue": True,
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
        resources={"total": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 8192}, "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0}, "free": {"cpu": 6.0, "ram_mb": 12000, "vram_mb": 6144}},
        providers=["llama.cpp"],
        can_host_custom_model=True,
        pricing={"unit": "q_per_1kk_tokens", "input": 12, "output": 18, "fixed_request": None},
        rating={"score": 0.91, "tier": "A", "updated_at": "2026-06-19T18:25:00Z"},
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
        resources={"total": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 8192}, "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0}, "free": {"cpu": 6.0, "ram_mb": 12000, "vram_mb": 6144}},
        providers=["llama.cpp"],
        can_host_custom_model=True,
        pricing={"unit": "q_per_1kk_tokens", "input": 12, "output": 18, "fixed_request": None},
        rating={"score": 0.91, "tier": "A", "updated_at": "2026-06-19T18:25:00Z"},
        bundles=[],
    )

    service.upsert_node(payload)
    current_time[0] = 1015.0
    assert service.get_node("node-a")["status"] == "stale"
    current_time[0] = 1045.0
    assert service.get_node("node-a")["status"] == "offline"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_registry_service.py -q`
Expected: FAIL because the registry service and models do not exist yet.

- [ ] **Step 3: Extend the registry models with discovery query types**

```python
class RegistryDiscoveryQuery(BaseModel):
    workload_type: str | None = None
    provider_type: str | None = None
    model_id: str | None = None
    bundle_id: str | None = None
    can_host_custom_model: bool | None = None
    max_input_price_q_per_1kk: int | None = Field(default=None, ge=0)
    max_output_price_q_per_1kk: int | None = Field(default=None, ge=0)
    min_rating: float | None = Field(default=None, ge=0.0, le=1.0)
    include_stale: bool = False
    limit: int = Field(default=20, ge=1, le=100)
```

- [ ] **Step 4: Implement the in-memory registry service**

```python
class RegistryService:
    def __init__(self, *, stale_grace_seconds: int = 30) -> None:
        self.stale_grace_seconds = stale_grace_seconds
        self._nodes: dict[str, dict] = {}

    def upsert_node(self, payload: RegistryNodeAdvertisement) -> dict:
        record = payload.model_dump(mode="json")
        self._nodes[payload.node_id] = record
        return self.get_node(payload.node_id)

    def list_nodes(self) -> list[dict]:
        return [self.get_node(node_id) for node_id in sorted(self._nodes)]

    def get_node(self, node_id: str) -> dict:
        record = dict(self._nodes[node_id])
        record["status"] = self._status_for(record)
        return record

    def _status_for(self, record: dict) -> str:
        heartbeat = datetime.fromisoformat(record["heartbeat_at"]).timestamp()
        ttl = int(record["heartbeat_ttl_seconds"])
        age = time.time() - heartbeat
        if age <= ttl:
            return "ready"
        if age <= ttl + self.stale_grace_seconds:
            return "stale"
        return "offline"
```

- [ ] **Step 5: Run tests to verify it passes**

Run: `python -m pytest tests/test_registry_service.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/registry_models.py src/aidn_hypervisor/registry_service.py tests/test_registry_service.py
git commit -m "feat: add in-memory registry state and freshness"
```

### Task 3: Discovery Filtering And Ordering

**Files:**
- Modify: `src/aidn_hypervisor/registry_service.py`
- Modify: `tests/test_registry_service.py`

- [ ] **Step 1: Write the failing discovery tests**

```python
def test_registry_service_discovers_matching_bundles_by_workload_and_model() -> None:
    service = RegistryService()
    service.upsert_node(_node("node-a", bundles=[_bundle("phi4-local", workload_type="llm_text", provider_type="llama.cpp", model_id="phi-4-mini.gguf")]))
    service.upsert_node(_node("node-b", bundles=[_bundle("whisper-local", workload_type="speech_to_text", provider_type="whisper", model_id="large-v3")]))

    result = service.discover(
        RegistryDiscoveryQuery(workload_type="llm_text", model_id="phi-4-mini")
    )

    assert [node["node_id"] for node in result["nodes"]] == ["node-a"]
    assert result["nodes"][0]["bundles"][0]["bundle_id"] == "phi4-local"


def test_registry_service_orders_ready_nodes_by_rating_then_price() -> None:
    service = RegistryService()
    service.upsert_node(_node("node-cheap", rating_score=0.90, input_price=10, output_price=20))
    service.upsert_node(_node("node-better", rating_score=0.95, input_price=12, output_price=22))

    result = service.discover(RegistryDiscoveryQuery(workload_type="llm_text"))

    assert [node["node_id"] for node in result["nodes"]] == ["node-better", "node-cheap"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_registry_service.py -k "discovers_matching or orders_ready" -q`
Expected: FAIL because `discover()` does not exist yet.

- [ ] **Step 3: Add bundle matching and ordered discovery to the registry service**

```python
def discover(self, query: RegistryDiscoveryQuery) -> dict:
    matched_nodes: list[dict] = []
    for node_id in self._nodes:
        node = self.get_node(node_id)
        if node["status"] == "offline":
            continue
        if node["status"] == "stale" and not query.include_stale:
            continue
        if query.can_host_custom_model is not None and node["can_host_custom_model"] != query.can_host_custom_model:
            continue
        if query.min_rating is not None and node["rating"]["score"] < query.min_rating:
            continue
        if query.max_input_price_q_per_1kk is not None and node["pricing"]["input"] > query.max_input_price_q_per_1kk:
            continue
        if query.max_output_price_q_per_1kk is not None and node["pricing"]["output"] > query.max_output_price_q_per_1kk:
            continue

        bundles = [
            bundle for bundle in node["bundles"]
            if self._bundle_matches(bundle, query)
        ]
        if not bundles:
            continue
        node["bundles"] = bundles
        matched_nodes.append(node)

    matched_nodes.sort(
        key=lambda node: (
            {"ready": 0, "stale": 1, "offline": 2}[node["status"]],
            -node["rating"]["score"],
            node["pricing"]["input"],
            node["pricing"]["output"],
            -datetime.fromisoformat(node["heartbeat_at"]).timestamp(),
        )
    )
    return {
        "query": query.model_dump(mode="json"),
        "nodes": matched_nodes[: query.limit],
    }
```

- [ ] **Step 4: Run tests to verify it passes**

Run: `python -m pytest tests/test_registry_service.py -k "discovers_matching or orders_ready" -q`
Expected: PASS

Run: `python -m pytest tests/test_registry_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/registry_service.py tests/test_registry_service.py
git commit -m "feat: add registry discovery filtering and ordering"
```

### Task 4: Registry HTTP API And App Wiring

**Files:**
- Create: `src/aidn_hypervisor/registry_api.py`
- Modify: `src/aidn_hypervisor/main.py`
- Create: `tests/test_registry_api.py`
- Modify: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing API tests**

```python
def _node_payload(
    node_id: str,
    *,
    heartbeat_at: str = "2026-06-19T18:30:00+00:00",
    heartbeat_ttl_seconds: int = 30,
) -> dict:
    return {
        "node_id": node_id,
        "operator_id": f"{node_id}-operator",
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
                "workload_type": "llm_text",
                "provider_type": "llama.cpp",
                "model_id": "phi-4-mini.gguf",
                "endpoint": "https://node-a.example/runtimes/phi4-local",
                "enabled": True,
                "status": "ready",
                "launch_mode": "managed_process",
                "device_affinity": "cpu",
                "max_parallel_requests": 1,
                "supports_allocation": True,
                "supports_queue": True,
            }
        ],
    }


def test_registry_node_upsert_endpoint_stores_advertisement() -> None:
    service = RegistryService()
    client = TestClient(build_registry_app(service=service))

    response = client.put("/registry/nodes/node-a", json=_node_payload("node-a"))

    assert response.status_code == 200
    assert response.json()["node_id"] == "node-a"


def test_registry_discovery_endpoint_filters_by_workload_and_model() -> None:
    service = RegistryService()
    service.upsert_node(RegistryNodeAdvertisement(**_node_payload("node-a")))
    client = TestClient(build_registry_app(service=service))

    response = client.get("/registry/discovery", params={"workload_type": "llm_text", "model_id": "phi-4-mini"})

    assert response.status_code == 200
    assert response.json()["nodes"][0]["node_id"] == "node-a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_registry_api.py -q`
Expected: FAIL because no registry router or registry app exists.

- [ ] **Step 3: Implement the registry router**

```python
def build_registry_router(service: RegistryService) -> APIRouter:
    router = APIRouter()

    @router.put("/registry/nodes/{node_id}")
    async def upsert_node(node_id: str, payload: RegistryNodeAdvertisement) -> dict:
        if payload.node_id != node_id:
            raise HTTPException(status_code=409, detail="node_id in path and body must match")
        return service.upsert_node(payload)

    @router.get("/registry/nodes")
    async def list_nodes() -> list[dict]:
        return service.list_nodes()

    @router.get("/registry/nodes/{node_id}")
    async def get_node(node_id: str) -> dict:
        try:
            return service.get_node(node_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown node: {node_id}") from error

    @router.get("/registry/discovery")
    async def discover(
        workload_type: str | None = None,
        provider_type: str | None = None,
        model_id: str | None = None,
        bundle_id: str | None = None,
        can_host_custom_model: bool | None = None,
        max_input_price_q_per_1kk: int | None = None,
        max_output_price_q_per_1kk: int | None = None,
        min_rating: float | None = None,
        include_stale: bool = False,
        limit: int = 20,
    ) -> dict:
        query = RegistryDiscoveryQuery(
            workload_type=workload_type,
            provider_type=provider_type,
            model_id=model_id,
            bundle_id=bundle_id,
            can_host_custom_model=can_host_custom_model,
            max_input_price_q_per_1kk=max_input_price_q_per_1kk,
            max_output_price_q_per_1kk=max_output_price_q_per_1kk,
            min_rating=min_rating,
            include_stale=include_stale,
            limit=limit,
        )
        return service.discover(query)

    return router
```

- [ ] **Step 4: Add a registry app builder in `main.py`**

```python
def build_registry_app(service: RegistryService | None = None) -> FastAPI:
    app = FastAPI(
        title="AiDN Registry",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(build_registry_router(service or RegistryService()))
    return app
```

- [ ] **Step 5: Run tests to verify it passes**

Run: `python -m pytest tests/test_registry_api.py -q`
Expected: PASS

Run: `python -m pytest tests/test_smoke.py -k registry -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/registry_api.py src/aidn_hypervisor/main.py tests/test_registry_api.py tests/test_smoke.py
git commit -m "feat: add registry HTTP API"
```

### Task 5: End-To-End Node-To-Registry Discovery Flow

**Files:**
- Modify: `tests/test_api.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_registry_api.py`
- Modify: `src/aidn_hypervisor/main.py`

- [ ] **Step 1: Write the cross-flow tests**

```python
def test_hypervisor_advertisement_can_be_registered_and_discovered() -> None:
    hypervisor = _service(with_runtime=False, use_process_manager=True, whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.node_id = "node-a"
    hypervisor.operator_id = "operator-a"
    hypervisor.base_url = "https://node-a.example"
    hypervisor.can_host_custom_model = True
    hypervisor.pricing = {"unit": "q_per_1kk_tokens", "input": 12, "output": 18, "fixed_request": None}
    hypervisor.rating = {"score": 0.91, "tier": "A", "updated_at": "2026-06-19T18:25:00Z"}
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


def test_registry_discovery_excludes_stale_nodes_by_default(monkeypatch) -> None:
    current_time = [1000.0]
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: current_time[0])
    registry = RegistryService(stale_grace_seconds=30)
    registry.upsert_node(
        RegistryNodeAdvertisement(**_node_payload("node-a", heartbeat_at="1970-01-01T00:16:40+00:00", heartbeat_ttl_seconds=10))
    )

    current_time[0] = 1015.0
    result = registry.discover(RegistryDiscoveryQuery(workload_type="llm_text"))

    assert result["nodes"] == []
```

- [ ] **Step 2: Run the focused verification**

Run: `python -m pytest tests/test_service.py -k node_advertisement -q`
Expected: PASS

Run: `python -m pytest tests/test_registry_service.py tests/test_registry_api.py -q`
Expected: PASS

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_api.py tests/test_service.py tests/test_registry_api.py src/aidn_hypervisor/main.py
git commit -m "test: cover node to registry discovery flow"
```
