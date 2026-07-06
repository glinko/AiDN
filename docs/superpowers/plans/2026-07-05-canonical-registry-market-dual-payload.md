# Canonical Registry Market Dual Payload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend registry advertisements, discovery, and market payloads so they publish canonical `services / runtimes / advertisements` alongside the existing bundle-centric contract.

**Architecture:** Keep registry and market backward compatible by preserving legacy `bundles` and flattened `candidates`, while adding a dual canonical envelope to node advertisements and a parallel `canonical_candidates` stream to discovery and market read models. Build every canonical field deterministically from existing hypervisor overlay state so no new mutable registry store is required.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, pytest

---

### Task 1: Extend Registry Models And Node Advertisement

**Files:**
- Modify: `src/aidn_hypervisor/registry_models.py`
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/test_service.py`
- Test: `tests/test_registry_service.py`

- [ ] **Step 1: Write the failing node advertisement tests**

```python
def test_service_node_advertisement_includes_canonical_registry_sections() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"endpoint": "http://127.0.0.1:9000"}
            ),
            _bundle("text-a", "llm_text"),
        ],
        runtimes=[
            RuntimeHandle(
                runtime_id="rt-1",
                command=["whisper"],
                status="running",
                bundle_id="whisper-a",
                health_status="healthy",
            )
        ],
    )

    payload = service.node_advertisement(heartbeat_at="2026-07-05T14:00:00+00:00")

    assert payload["canonical_services"][0]["kind"] == "compute"
    assert payload["canonical_capability_runtimes"][0]["capability_id"] == "speech.stt"
    assert payload["canonical_compute_compatibility"][0]["legacy_bundle_id"] == "whisper-a"
    assert payload["canonical_advertisements"] == []


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
        pricing={"unit": "q_per_1kk_tokens", "input": 12, "output": 18, "fixed_request": None},
        rating={"score": 0.91, "tier": "A", "updated_at": "2026-07-05T13:55:00+00:00"},
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
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python -m pytest tests/test_service.py tests/test_registry_service.py -k "canonical_registry_sections or dual_payload_fields" -v`

Expected: FAIL because `RegistryNodeAdvertisement` does not yet define the canonical fields and `node_advertisement()` does not emit them.

- [ ] **Step 3: Extend registry models with canonical dual-payload sections**

```python
from aidn_hypervisor.canonical_models import (
    CanonicalAdvertisementRecord,
    CanonicalCapabilityRuntimeRecord,
    CanonicalComputeCompatibilityRecord,
    CanonicalProtocolServiceRecord,
)


class RegistryNodeAdvertisement(BaseModel):
    node_id: str
    operator_id: str
    registry_version: str = "m2.v2"
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
    published_endpoints: list[RegistryPublishedEndpointSummary] = Field(
        default_factory=list
    )
    canonical_services: list[CanonicalProtocolServiceRecord] = Field(default_factory=list)
    canonical_capability_runtimes: list[CanonicalCapabilityRuntimeRecord] = Field(
        default_factory=list
    )
    canonical_compute_compatibility: list[CanonicalComputeCompatibilityRecord] = Field(
        default_factory=list
    )
    canonical_advertisements: list[CanonicalAdvertisementRecord] = Field(
        default_factory=list
    )
```

- [ ] **Step 4: Extend node advertisement publication with canonical sections**

```python
def node_advertisement(self, *, heartbeat_at: str | None = None) -> dict:
    timestamp = heartbeat_at or datetime.now(timezone.utc).isoformat()
    resources = (
        self.resources.summary()
        if self.resources is not None
        else _empty_resource_summary()
    )
    publication_service = getattr(self, "endpoint_publication_service", None)
    current_publication_records = []
    if publication_service is not None:
        current_publication_records = [
            record
            for record in publication_service.list_publications()
            if record.status == "published"
        ]
    canonical_overlay = self.canonical_overlay_inventory()
    advertisement = RegistryNodeAdvertisement(
        node_id=self.node_id,
        operator_id=self.operator_id,
        base_url=self.base_url,
        heartbeat_at=timestamp,
        heartbeat_ttl_seconds=self.heartbeat_ttl_seconds,
        status="ready",
        resources=resources,
        providers=sorted({bundle.provider_type for bundle in self.bundles}),
        can_host_custom_model=self.can_host_custom_model,
        pricing=self._pricing,
        rating=self._rating,
        bundles=[
            RegistryBundleAdvertisement(
                bundle_id=bundle.bundle_id,
                plugin_id=bundle.plugin_id,
                workload_type=bundle.workload_type,
                provider_type=bundle.provider_type,
                model_id=bundle.model_id,
                endpoint=bundle.endpoint,
                enabled=bundle.enabled,
                status=self._bundle_registry_status(bundle),
                launch_mode=bundle.launch_mode,
                device_affinity=bundle.device_affinity,
                max_parallel_requests=bundle.max_parallel_requests,
                supports_allocation=True,
                supports_queue=True,
            )
            for bundle in self.bundles
        ],
        published_endpoints=[
            RegistryPublishedEndpointSummary(
                endpoint_id=record.endpoint_id,
                owner_wallet=record.owner_wallet,
                node_id=record.node_id,
                current_publication_id=record.publication_id,
                current_configuration_hash=record.configuration_hash,
                published_at=record.published_at,
                status=record.status,
                visibility=record.publication.get("visibility", "private"),
                model_class=record.model_class,
            )
            for record in current_publication_records
        ],
        canonical_services=canonical_overlay.get("services", []),
        canonical_capability_runtimes=canonical_overlay.get("runtimes", []),
        canonical_compute_compatibility=canonical_overlay.get("compatibility", []),
        canonical_advertisements=[],
    )
    return advertisement.model_dump(mode="json")
```

- [ ] **Step 5: Run the focused tests to verify they pass**

Run: `python -m pytest tests/test_service.py tests/test_registry_service.py -k "canonical_registry_sections or dual_payload_fields" -v`

Expected: PASS with the dual registry model fields and node advertisement canonical sections green.

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/registry_models.py src/aidn_hypervisor/service.py tests/test_service.py tests/test_registry_service.py
git commit -m "feat: publish canonical registry dual payload sections"
```

---

### Task 2: Extend Registry Discovery With Canonical Filters And Candidates

**Files:**
- Modify: `src/aidn_hypervisor/registry_models.py`
- Modify: `src/aidn_hypervisor/registry_service.py`
- Test: `tests/test_registry_service.py`
- Test: `tests/test_registry_api.py`

- [ ] **Step 1: Write the failing discovery tests**

```python
def test_registry_service_discovery_returns_canonical_candidates(monkeypatch) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        _node(
            "node-a",
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
                    "resource_type": "endpoint",
                    "owner_wallet": "wallet-a",
                    "hypervisor_id": "node-a",
                    "capability_id": "llm.chat",
                    "visibility": "public",
                    "signature_scope": "configuration_publication",
                }
            ],
        )
    )

    result = service.discover(RegistryDiscoveryQuery(capability_id="llm.chat"))

    assert result["canonical_candidates"][0]["capability_id"] == "llm.chat"
    assert result["canonical_candidates"][0]["legacy_bundle_id"] == "phi4-local"


def test_registry_discovery_endpoint_returns_canonical_candidates(monkeypatch) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(RegistryNodeAdvertisement(**_node_payload("node-a")))
    client = TestClient(build_registry_app(service))

    response = client.get("/registry/discovery", params={"capability_id": "llm.chat"})

    assert response.status_code == 200
    assert "canonical_candidates" in response.json()
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python -m pytest tests/test_registry_service.py tests/test_registry_api.py -k "canonical_candidates" -v`

Expected: FAIL because `RegistryDiscoveryQuery` does not yet accept canonical filters and discovery does not yet emit `canonical_candidates`.

- [ ] **Step 3: Add canonical query fields**

```python
class RegistryDiscoveryQuery(BaseModel):
    workload_type: str | None = None
    provider_type: str | None = None
    model_id: str | None = None
    bundle_id: str | None = None
    capability_id: str | None = None
    runtime_id: str | None = None
    advertisement_resource_type: str | None = None
    visibility: str | None = None
    owner_wallet: str | None = None
    require_allocation_support: bool = False
    require_queue_support: bool = False
    ready_endpoint_only: bool = False
    can_host_custom_model: bool | None = None
    max_input_price_q_per_1kk: int | None = Field(default=None, ge=0)
    max_output_price_q_per_1kk: int | None = Field(default=None, ge=0)
    min_rating: float | None = Field(default=None, ge=0.0, le=1.0)
    include_stale: bool = False
    limit: int = Field(default=20, ge=1, le=100)
```

- [ ] **Step 4: Add canonical node matching and flattened canonical candidates**

```python
def discover(self, query: RegistryDiscoveryQuery) -> dict:
    matched_nodes: list[dict] = []
    for node_id in self._nodes:
        node = self.get_node(node_id)
        if node["status"] == "offline":
            continue
        if node["status"] == "stale" and not query.include_stale:
            continue
        if (
            query.can_host_custom_model is not None
            and node["can_host_custom_model"] != query.can_host_custom_model
        ):
            continue
        if query.min_rating is not None and node["rating"]["score"] < query.min_rating:
            continue
        if (
            query.max_input_price_q_per_1kk is not None
            and node["pricing"]["input"] > query.max_input_price_q_per_1kk
        ):
            continue
        if (
            query.max_output_price_q_per_1kk is not None
            and node["pricing"]["output"] > query.max_output_price_q_per_1kk
        ):
            continue

        bundles = [
            bundle for bundle in node["bundles"] if self._bundle_matches(bundle, query)
        ]
        canonical_advertisements = [
            advertisement
            for advertisement in node.get("canonical_advertisements", [])
            if self._canonical_advertisement_matches(
                advertisement=advertisement,
                node=node,
                query=query,
            )
        ]
        if not bundles and not canonical_advertisements:
            continue
        node["bundles"] = bundles
        node["canonical_advertisements"] = canonical_advertisements
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
    nodes = matched_nodes[: query.limit]
    return {
        "query": query.model_dump(mode="json"),
        "nodes": nodes,
        "candidates": self._flatten_candidates(nodes),
        "canonical_candidates": self._flatten_canonical_candidates(nodes),
    }
```

```python
def _canonical_advertisement_matches(self, *, advertisement: dict, node: dict, query: RegistryDiscoveryQuery) -> bool:
    if query.capability_id is not None and advertisement.get("capability_id") != query.capability_id:
        return False
    if (
        query.advertisement_resource_type is not None
        and advertisement.get("resource_type") != query.advertisement_resource_type
    ):
        return False
    if query.visibility is not None and advertisement.get("visibility") != query.visibility:
        return False
    if query.owner_wallet is not None and advertisement.get("owner_wallet") != query.owner_wallet:
        return False
    if query.runtime_id is not None:
        runtimes = node.get("canonical_capability_runtimes", [])
        if not any(runtime.get("runtime_id") == query.runtime_id for runtime in runtimes):
            return False
    return True


def _flatten_canonical_candidates(self, nodes: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    for node in nodes:
        runtimes_by_capability = {
            runtime["capability_id"]: runtime
            for runtime in node.get("canonical_capability_runtimes", [])
        }
        compatibility_by_capability = {
            item["canonical_capability_id"]: item
            for item in node.get("canonical_compute_compatibility", [])
        }
        for advertisement in node.get("canonical_advertisements", []):
            capability_id = advertisement.get("capability_id")
            runtime = runtimes_by_capability.get(capability_id, {})
            compatibility = compatibility_by_capability.get(capability_id, {})
            candidates.append(
                {
                    "node_id": node["node_id"],
                    "operator_id": node["operator_id"],
                    "base_url": node["base_url"],
                    "status": node["status"],
                    "service_id": "compute",
                    "capability_id": capability_id,
                    "runtime_id": runtime.get("runtime_id"),
                    "advertisement_id": advertisement["advertisement_id"],
                    "resource_type": advertisement["resource_type"],
                    "visibility": advertisement["visibility"],
                    "pricing": node["pricing"],
                    "rating": node["rating"],
                    "can_host_custom_model": node["can_host_custom_model"],
                    "published_endpoint_count": len(node.get("published_endpoints", [])),
                    "trust_summary": self._canonical_trust_summary(node),
                    "legacy_bundle_id": compatibility.get("legacy_bundle_id"),
                    "legacy_plugin_id": compatibility.get("legacy_plugin_id"),
                    "legacy_provider_type": compatibility.get("legacy_provider_type"),
                }
            )
    candidates.sort(key=self._canonical_candidate_sort_key)
    return candidates
```

- [ ] **Step 5: Run the focused tests to verify they pass**

Run: `python -m pytest tests/test_registry_service.py tests/test_registry_api.py -k "canonical_candidates" -v`

Expected: PASS with canonical query fields and dual discovery output green, while legacy discovery remains intact.

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/registry_models.py src/aidn_hypervisor/registry_service.py tests/test_registry_service.py tests/test_registry_api.py
git commit -m "feat: add canonical registry discovery candidates"
```

---

### Task 3: Enrich Market Payloads With Canonical Summary And Candidates

**Files:**
- Modify: `src/aidn_hypervisor/dashboard.py`
- Modify: `src/aidn_hypervisor/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing market payload tests**

```python
def test_operator_dashboard_market_endpoint_includes_canonical_candidates() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    response = client.get("/operators/dashboard/market")

    assert response.status_code == 200
    body = response.json()
    assert "canonical_candidates" in body
    assert "canonical_summary" in body


def test_operator_dashboard_market_payload_builds_canonical_summary() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    payload = build_market_payload(service=hypervisor, registry_service=None)

    assert payload["canonical_summary"]["service_kinds"] == ["compute"]
    assert "speech.stt" in payload["canonical_summary"]["capability_ids"]
    assert payload["canonical_summary"]["runtime_count"] >= 1
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python -m pytest tests/test_api.py -k "canonical_summary or canonical_candidates" -v`

Expected: FAIL because market payloads do not yet include `canonical_candidates` or `canonical_summary`.

- [ ] **Step 3: Extend market payload builder**

```python
def build_market_payload(*, service, registry_service) -> dict:
    if registry_service is None:
        advertisement = service.node_advertisement()
        canonical_candidates = _canonical_candidates_from_node(advertisement)
        return {
            "nodes": [advertisement],
            "candidates": [
                _local_candidate_from_advertisement(advertisement, bundle)
                for bundle in advertisement["bundles"]
            ],
            "canonical_candidates": canonical_candidates,
            "canonical_summary": _canonical_market_summary(canonical_candidates),
        }

    discovery = registry_service.discover(RegistryDiscoveryQuery())
    nodes_by_id = {node["node_id"]: node for node in discovery["nodes"]}
    candidates = []
    for candidate in discovery["candidates"]:
        enriched = dict(candidate)
        node = nodes_by_id.get(enriched["node_id"], {})
        enriched["origin"] = (
            "own" if enriched["node_id"] == service.node_id else "external"
        )
        enriched["published_endpoint_count"] = len(node.get("published_endpoints", []))
        enriched["trust_summary"] = _aggregate_market_trust(
            node.get("published_endpoints", [])
        )
        candidates.append(enriched)
    canonical_candidates = [
        {
            **candidate,
            "origin": "own" if candidate["node_id"] == service.node_id else "external",
        }
        for candidate in discovery.get("canonical_candidates", [])
    ]
    return {
        "query": discovery["query"],
        "nodes": discovery["nodes"],
        "candidates": candidates,
        "canonical_candidates": canonical_candidates,
        "canonical_summary": _canonical_market_summary(canonical_candidates),
    }
```

```python
def _canonical_candidates_from_node(advertisement: dict) -> list[dict]:
    candidates: list[dict] = []
    runtimes_by_capability = {
        runtime["capability_id"]: runtime
        for runtime in advertisement.get("canonical_capability_runtimes", [])
    }
    compatibility_by_capability = {
        item["canonical_capability_id"]: item
        for item in advertisement.get("canonical_compute_compatibility", [])
    }
    for item in advertisement.get("canonical_advertisements", []):
        capability_id = item.get("capability_id")
        runtime = runtimes_by_capability.get(capability_id, {})
        compatibility = compatibility_by_capability.get(capability_id, {})
        candidates.append(
            {
                "node_id": advertisement["node_id"],
                "operator_id": advertisement["operator_id"],
                "base_url": advertisement["base_url"],
                "status": advertisement["status"],
                "service_id": "compute",
                "capability_id": capability_id,
                "runtime_id": runtime.get("runtime_id"),
                "advertisement_id": item["advertisement_id"],
                "resource_type": item["resource_type"],
                "visibility": item["visibility"],
                "pricing": advertisement["pricing"],
                "rating": advertisement["rating"],
                "can_host_custom_model": advertisement["can_host_custom_model"],
                "published_endpoint_count": len(advertisement.get("published_endpoints", [])),
                "trust_summary": _aggregate_market_trust(advertisement.get("published_endpoints", [])),
                "legacy_bundle_id": compatibility.get("legacy_bundle_id"),
                "legacy_plugin_id": compatibility.get("legacy_plugin_id"),
                "legacy_provider_type": compatibility.get("legacy_provider_type"),
            }
        )
    return candidates


def _canonical_market_summary(canonical_candidates: list[dict]) -> dict:
    return {
        "service_kinds": sorted({"compute" for _ in canonical_candidates}),
        "capability_ids": sorted(
            {item["capability_id"] for item in canonical_candidates if item.get("capability_id")}
        ),
        "runtime_count": len({item.get("runtime_id") for item in canonical_candidates if item.get("runtime_id")}),
        "endpoint_advertisement_count": sum(
            1 for item in canonical_candidates if item.get("resource_type") == "endpoint"
        ),
    }
```

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `python -m pytest tests/test_api.py -k "canonical_summary or canonical_candidates" -v`

Expected: PASS with market payloads exposing additive canonical read models without removing legacy `candidates`.

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/dashboard.py src/aidn_hypervisor/api.py tests/test_api.py
git commit -m "feat: expose canonical market dual payload"
```

---

### Task 4: Run Full Dual-Payload Verification

**Files:**
- Verify only: `tests/test_service.py`
- Verify only: `tests/test_registry_service.py`
- Verify only: `tests/test_registry_api.py`
- Verify only: `tests/test_api.py`

- [ ] **Step 1: Run the full focused verification suite**

Run: `python -m pytest tests/test_service.py tests/test_registry_service.py tests/test_registry_api.py tests/test_api.py -q`

Expected: PASS with all legacy registry, operator market, and new canonical dual-payload tests green.

- [ ] **Step 2: Inspect the branch diff**

Run: `git diff --stat HEAD~3..HEAD`

Expected: only registry, service, dashboard, API, and related tests changed.

- [ ] **Step 3: Commit any final cleanup if required**

```bash
git status --short
```

Expected: clean working tree. If not clean because of intentional follow-up fixes, commit them with a focused message before completion.

---

## Self-Review

Spec coverage:
- dual registry advertisement payload is covered by Task 1;
- canonical discovery query fields and `canonical_candidates` are covered by Task 2;
- market payload `canonical_candidates` and `canonical_summary` are covered by Task 3;
- regression safety for legacy clients is covered by Tasks 2 through 4.

Placeholder scan:
- no `TBD`, `TODO`, or deferred implementation placeholders remain;
- each test and implementation step includes concrete code or a concrete command.

Type consistency:
- canonical node fields are named consistently as `canonical_services`, `canonical_capability_runtimes`, `canonical_compute_compatibility`, and `canonical_advertisements`;
- discovery output uses `canonical_candidates` consistently across registry service, market payload, and API tests;
- canonical market aggregation uses `capability_id`, `runtime_id`, and `resource_type` consistently with the approved spec.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-05-canonical-registry-market-dual-payload.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints
