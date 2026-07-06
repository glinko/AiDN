# Canonical Advertisement Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Project active endpoint publication records into real `canonical_advertisements` so node advertisements and canonical market payloads expose published endpoint identities instead of an empty placeholder list.

**Architecture:** Reuse `EndpointPublicationService` as the single source of truth and add a deterministic projector in `canonical_projection.py` that maps active `PublishedEndpointConfiguration` records into `CanonicalAdvertisementRecord` rows. `HypervisorService.node_advertisement()` remains the publication entrypoint, but it will call the new projector and keep legacy `published_endpoints` unchanged.

**Tech Stack:** Python 3.14, Pydantic v2, FastAPI, pytest

---

### Task 1: Add Canonical Advertisement Projector

**Files:**
- Modify: `src/aidn_hypervisor/canonical_projection.py`
- Modify: `tests/test_canonical_projection.py`

- [ ] **Step 1: Write the failing projector tests**

Add these imports near the top of `tests/test_canonical_projection.py`:

```python
from aidn_hypervisor.canonical_projection import (
    project_canonical_advertisements,
    project_capability_runtimes,
    project_compute_compatibility,
    project_protocol_services,
)
from aidn_hypervisor.endpoint_publications.models import (
    PublishedEndpointConfiguration,
    canonical_configuration_payload,
    configuration_hash_for_publication,
)
```

Add these helpers and tests to `tests/test_canonical_projection.py`:

```python
def _publication(
    *,
    publication_id: str,
    endpoint_id: str = "endpoint-a",
    owner_wallet: str = "wallet-1",
    node_id: str = "node-1",
    model_class: str = "speech.stt",
    capabilities: list[str] | None = None,
    visibility: str = "shared",
    status: str = "published",
) -> PublishedEndpointConfiguration:
    capability_list = ["speech.stt"] if capabilities is None else capabilities
    payload = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class=model_class,
        capabilities=capability_list,
        runtime={"context_length": 8192},
        publication={"visibility": visibility},
        pricing={"billing_unit": "request", "input_price": 1.0},
        session={},
        execution={"strategy": "local"},
    )
    return PublishedEndpointConfiguration(
        publication_id=publication_id,
        endpoint_id=endpoint_id,
        owner_wallet=owner_wallet,
        node_id=node_id,
        configuration_hash=configuration_hash_for_publication(payload),
        previous_configuration_hash=None,
        bundle_id="bundle-a",
        bundle_hash="bundle-hash-a",
        model_class=model_class,
        capabilities=capability_list,
        profile={},
        runtime={"context_length": 8192},
        publication={"visibility": visibility},
        pricing={"billing_unit": "request", "input_price": 1.0},
        session={},
        execution={"strategy": "local"},
        validation_requirement={},
        published_at="2026-07-06T12:00:00+00:00",
        sequence=1,
        status=status,
        wallet_signature=f"sig-{publication_id}",
    )


def test_project_canonical_advertisements_maps_active_publications() -> None:
    records = project_canonical_advertisements(
        [
            _publication(
                publication_id="pub-1",
                owner_wallet="wallet-a",
                node_id="node-a",
                capabilities=["llm.chat"],
                visibility="public",
            )
        ]
    )

    assert len(records) == 1
    assert records[0].advertisement_id == "adv-pub-1"
    assert records[0].resource_type == "endpoint"
    assert records[0].owner_wallet == "wallet-a"
    assert records[0].hypervisor_id == "node-a"
    assert records[0].capability_id == "llm.chat"
    assert records[0].visibility == "public"
    assert records[0].signature_scope == "configuration_publication"


def test_project_canonical_advertisements_uses_first_capability_as_primary() -> None:
    records = project_canonical_advertisements(
        [
            _publication(
                publication_id="pub-2",
                capabilities=["speech.stt", "speech.translate"],
            )
        ]
    )

    assert records[0].capability_id == "speech.stt"
```

- [ ] **Step 2: Run the focused projector tests to verify they fail**

Run: `python -m pytest tests/test_canonical_projection.py -k "canonical_advertisements" -v`

Expected: FAIL because `project_canonical_advertisements` does not exist yet.

- [ ] **Step 3: Implement the canonical advertisement projector**

Add this import in `src/aidn_hypervisor/canonical_projection.py`:

```python
from aidn_hypervisor.canonical_models import (
    CanonicalAdvertisementRecord,
    CanonicalCapabilityRuntimeRecord,
    CanonicalComputeCompatibilityRecord,
    CanonicalProtocolServiceRecord,
)
```

Add this function to `src/aidn_hypervisor/canonical_projection.py`:

```python
def project_canonical_advertisements(
    publication_records,
) -> list[CanonicalAdvertisementRecord]:
    records: list[CanonicalAdvertisementRecord] = []
    for publication in publication_records:
        if publication.status != "published":
            continue
        capability_id = publication.capabilities[0] if publication.capabilities else None
        records.append(
            CanonicalAdvertisementRecord(
                advertisement_id=f"adv-{publication.publication_id}",
                resource_type="endpoint",
                owner_wallet=publication.owner_wallet,
                hypervisor_id=publication.node_id,
                capability_id=capability_id,
                visibility=publication.publication.get("visibility", "private"),
                signature_scope="configuration_publication",
            )
        )
    return records
```

- [ ] **Step 4: Run the projector tests to verify they pass**

Run: `python -m pytest tests/test_canonical_projection.py -k "canonical_advertisements" -v`

Expected: PASS with the new projector and primary capability rule green.

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/canonical_projection.py tests/test_canonical_projection.py
git commit -m "feat: add canonical advertisement projector"
```

---

### Task 2: Wire Canonical Advertisements Into Node Advertisement

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `tests/test_service.py`

- [ ] **Step 1: Write the failing node advertisement tests**

Add this import near the existing publication imports in `tests/test_service.py`:

```python
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
```

Add these tests to `tests/test_service.py` after the current canonical advertisement placeholder test:

```python
def test_service_node_advertisement_projects_canonical_advertisements_from_publications() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[_bundle("text-a", "llm_text")],
        node_id="node-local",
    )
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Text Endpoint",
            model_class="llm_text",
            capabilities=["llm.chat"],
            publication={"visibility": "public"},
        )
    )
    publication = publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    service.endpoint_publication_service = publication_service

    payload = service.node_advertisement(heartbeat_at="2026-07-06T14:00:00+00:00")

    assert payload["canonical_advertisements"] == [
        {
            "advertisement_id": f"adv-{publication.publication_id}",
            "resource_type": "endpoint",
            "owner_wallet": service.owner_wallet_state()["wallet_id"],
            "hypervisor_id": service.node_id,
            "capability_id": "llm.chat",
            "visibility": "public",
            "signature_scope": "configuration_publication",
        }
    ]


def test_service_node_advertisement_excludes_revoked_and_superseded_publications() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[_bundle("text-a", "llm_text")],
        node_id="node-local",
    )
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Text Endpoint",
            model_class="llm_text",
            capabilities=["llm.chat"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    publication_service.revoke_publication(created.endpoint.endpoint_id)
    service.endpoint_publication_service = publication_service

    payload = service.node_advertisement(heartbeat_at="2026-07-06T14:00:00+00:00")

    assert payload["canonical_advertisements"] == []
```

- [ ] **Step 2: Run the focused service tests to verify they fail**

Run: `python -m pytest tests/test_service.py -k "projects_canonical_advertisements or excludes_revoked_and_superseded" -v`

Expected: FAIL because `node_advertisement()` still emits `canonical_advertisements=[]`.

- [ ] **Step 3: Wire the projector into `node_advertisement()`**

Update the canonical helper import inside `HypervisorService.canonical_overlay_inventory()` in `src/aidn_hypervisor/service.py` only if needed to keep helper names aligned:

```python
from aidn_hypervisor.canonical_projection import (
    project_capability_runtimes,
    project_compute_compatibility,
    project_protocol_services,
)
```

Then update `node_advertisement()` in `src/aidn_hypervisor/service.py` like this:

```python
from aidn_hypervisor.canonical_projection import project_canonical_advertisements


def node_advertisement(self, *, heartbeat_at: str | None = None) -> dict:
    timestamp = heartbeat_at or datetime.now(timezone.utc).isoformat()
    resources = (
        self.resources.summary()
        if self.resources is not None
        else _empty_resource_summary()
    )
    canonical_overlay = self.canonical_overlay_inventory()
    publication_service = getattr(self, "endpoint_publication_service", None)
    current_publication_records = []
    if publication_service is not None:
        current_publication_records = [
            record
            for record in publication_service.list_publications()
            if record.status == "published"
        ]
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
        bundles=[...],
        published_endpoints=[...],
        canonical_services=canonical_overlay.get("services", []),
        canonical_capability_runtimes=canonical_overlay.get("runtimes", []),
        canonical_compute_compatibility=canonical_overlay.get("compatibility", []),
        canonical_advertisements=project_canonical_advertisements(
            current_publication_records
        ),
    )
    return advertisement.model_dump(mode="json")
```

- [ ] **Step 4: Run the focused service tests to verify they pass**

Run: `python -m pytest tests/test_service.py -k "projects_canonical_advertisements or excludes_revoked_and_superseded" -v`

Expected: PASS with real canonical publication rows and lifecycle exclusion behavior green.

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/service.py tests/test_service.py
git commit -m "feat: publish canonical advertisements in node payloads"
```

---

### Task 3: Add Market Regression Coverage For Real Canonical Publications

**Files:**
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing market regression test**

Add this test to `tests/test_api.py` near the other market payload tests:

```python
def test_operator_dashboard_market_payload_surfaces_local_canonical_publication_identity() -> None:
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
            publication={"visibility": "public"},
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

    assert payload["canonical_candidates"][0]["advertisement_id"] == f"adv-{publication.publication_id}"
    assert payload["canonical_candidates"][0]["capability_id"] == "speech.stt"
    assert payload["canonical_candidates"][0]["visibility"] == "public"
```

- [ ] **Step 2: Run the focused market test to verify it fails**

Run: `python -m pytest tests/test_api.py -k "surfaces_local_canonical_publication_identity" -v`

Expected: FAIL because the local market payload currently sees no canonical advertisements from a real publication record.

- [ ] **Step 3: Re-run the market test after Task 2 wiring**

Run: `python -m pytest tests/test_api.py -k "surfaces_local_canonical_publication_identity" -v`

Expected: PASS without additional production changes because `build_market_payload()` already reads `canonical_advertisements` from `node_advertisement()`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_api.py
git commit -m "test: cover canonical publication market identity"
```

---

### Task 4: Run Full Verification For Canonical Advertisement Publication

**Files:**
- Verify only: `tests/test_canonical_projection.py`
- Verify only: `tests/test_service.py`
- Verify only: `tests/endpoint_publications/test_service.py`
- Verify only: `tests/test_api.py`

- [ ] **Step 1: Run the focused publication verification suite**

Run: `python -m pytest tests/test_canonical_projection.py tests/test_service.py tests/endpoint_publications/test_service.py tests/test_api.py -k "canonical_advertisements or canonical_publication or publication_identity or projects_canonical_advertisements or excludes_revoked_and_superseded" -v`

Expected: PASS for projector, service publication, lifecycle, and market identity coverage.

- [ ] **Step 2: Run the broader regression suite**

Run: `python -m pytest tests/test_service.py tests/test_registry_service.py tests/test_registry_api.py tests/test_api.py tests/endpoint_publications/test_service.py tests/test_canonical_projection.py -q`

Expected: PASS with no legacy registry, endpoint publication, or market regressions.

- [ ] **Step 3: Inspect branch cleanliness**

Run: `git status --short`

Expected: clean working tree after the task commits above. If not clean because of intentional cleanup, commit the remaining files with a focused message before completion.

---

## Self-Review

Spec coverage:
- active published endpoint records become canonical advertisements in Task 1 and Task 2;
- revoked and superseded records are excluded in Task 2;
- legacy `published_endpoints` behavior is preserved because Task 2 only adds the canonical projection beside the existing summary;
- canonical market read-models start consuming the real publication identity in Task 3;
- end-to-end regression coverage is captured in Task 4.

Placeholder scan:
- no `TBD`, `TODO`, or deferred implementation placeholders remain;
- every test and implementation step has an explicit code or command block.

Type consistency:
- `CanonicalAdvertisementRecord` fields match the current canonical model names;
- `PublishedEndpointConfiguration` field names match the existing endpoint publication model;
- `advertisement_id`, `owner_wallet`, `hypervisor_id`, `capability_id`, `visibility`, and `signature_scope` are used consistently across projector, service, and tests.
