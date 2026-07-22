from datetime import datetime
import json

from fastapi.testclient import TestClient

from aidn_hypervisor.main import build_registry_app
from aidn_hypervisor.registry_models import RegistryDiscoveryQuery, RegistryNodeAdvertisement
from aidn_hypervisor.registry_service import RegistryService


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
                "plugin_id": "llama.cpp",
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
        "canonical_services": [],
        "canonical_capability_runtimes": [],
        "canonical_compute_compatibility": [],
        "canonical_advertisements": [],
    }


def test_registry_node_upsert_endpoint_stores_advertisement() -> None:
    service = RegistryService()
    client = TestClient(build_registry_app(service=service))

    response = client.put("/registry/nodes/node-a", json=_node_payload("node-a"))

    assert response.status_code == 200
    assert response.json()["node_id"] == "node-a"


def test_registry_node_upsert_rejects_conflicting_wallet_identity_binding() -> None:
    service = RegistryService()
    client = TestClient(build_registry_app(service=service))
    first = _node_payload("node-a")
    first["canonical_registry_objects"] = [
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
    ]
    second = _node_payload("node-b")
    second["canonical_registry_objects"] = [
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
    ]

    assert client.put("/registry/nodes/node-a", json=first).status_code == 200
    response = client.put("/registry/nodes/node-b", json=second)

    assert response.status_code == 409
    assert "wallet-consumer" in response.json()["detail"]


def test_registry_conflicts_endpoint_lists_wallet_identity_conflicts() -> None:
    service = RegistryService()
    client = TestClient(build_registry_app(service=service))
    first = _node_payload("node-a")
    first["canonical_registry_objects"] = [
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
    ]
    second = _node_payload("node-b")
    second["canonical_registry_objects"] = [
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
    ]

    assert client.put("/registry/nodes/node-a", json=first).status_code == 200
    assert client.put("/registry/nodes/node-b", json=second).status_code == 409

    response = client.get(
        "/registry/conflicts",
        params={
            "conflict_class": "wallet_identity_binding",
            "logical_key": "wallet-consumer",
        },
    )

    assert response.status_code == 200
    assert len(response.json()["conflicts"]) == 1
    assert response.json()["conflicts"][0]["logical_key"] == "wallet-consumer"


def test_registry_wallet_identity_sync_endpoints_export_and_import_state() -> None:
    source = RegistryService()
    source.upsert_registry_object(
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
    )
    source_client = TestClient(build_registry_app(service=source))
    target = RegistryService()
    target_client = TestClient(build_registry_app(service=target))

    exported = source_client.get("/registry/wallet-identities/sync-state")
    assert exported.status_code == 200

    imported = target_client.post(
        "/registry/wallet-identities/import",
        json=exported.json(),
    )

    assert imported.status_code == 200
    assert imported.json()["imported_object_count"] == 1
    assert target.resolve_wallet_identity("wallet-consumer")["public_key"] == (
        "ed25519:" + "11" * 32
    )


def test_registry_wallet_identity_sync_from_peer_endpoint_pulls_remote_state(
    monkeypatch,
) -> None:
    service = RegistryService()
    client = TestClient(build_registry_app(service=service))
    payload = {
        "objects": [
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
        "conflicts": [],
    }

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(
        "aidn_hypervisor.registry_service.urllib_request.urlopen",
        lambda request, timeout=10: _Response(),
    )

    response = client.post(
        "/registry/wallet-identities/sync-from-peer",
        json={"peer_base_url": "https://peer-a.example/", "limit": 500},
    )

    assert response.status_code == 200
    assert response.json()["peer_base_url"] == "https://peer-a.example"
    assert response.json()["imported_object_count"] == 1
    assert service.resolve_wallet_identity("wallet-consumer")["public_key"] == (
        "ed25519:" + "11" * 32
    )


def test_registry_wallet_identity_peer_endpoints_store_and_list_peers() -> None:
    service = RegistryService()
    client = TestClient(build_registry_app(service=service))

    created = client.put(
        "/registry/wallet-identities/peers",
        json={"peer_base_url": "https://peer-a.example/", "enabled": True},
    )

    assert created.status_code == 200
    assert created.json()["peer_base_url"] == "https://peer-a.example"

    listed = client.get("/registry/wallet-identities/peers")

    assert listed.status_code == 200
    assert listed.json()["peers"][0]["peer_base_url"] == "https://peer-a.example"
    assert listed.json()["peers"][0]["enabled"] is True


def test_registry_wallet_identity_repair_endpoint_runs_known_peers(
    monkeypatch,
) -> None:
    service = RegistryService()
    service.upsert_wallet_identity_peer(peer_base_url="https://peer-a.example/")
    client = TestClient(build_registry_app(service=service))
    payload = {
        "objects": [
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
        "conflicts": [],
    }

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(
        "aidn_hypervisor.registry_service.urllib_request.urlopen",
        lambda request, timeout=10: _Response(),
    )

    response = client.post(
        "/registry/wallet-identities/repair",
        json={"limit": 500},
    )

    assert response.status_code == 200
    assert response.json()["success_count"] == 1
    assert response.json()["results"][0]["peer_base_url"] == "https://peer-a.example"
    assert service.resolve_wallet_identity("wallet-consumer")["public_key"] == (
        "ed25519:" + "11" * 32
    )


def test_registry_wallet_identity_discover_peers_endpoint_registers_remote_nodes(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        RegistryNodeAdvertisement(
            **_node_payload("node-local", heartbeat_at="2026-07-05T14:00:00+00:00")
        )
    )
    service.upsert_node(
        RegistryNodeAdvertisement(
            **_node_payload("node-remote", heartbeat_at="2026-07-05T14:00:00+00:00")
        )
    )
    client = TestClient(build_registry_app(service=service))

    response = client.post(
        "/registry/wallet-identities/discover-peers",
        json={"self_node_id": "node-local"},
    )

    assert response.status_code == 200
    assert response.json()["candidate_count"] == 1
    assert response.json()["registered_count"] == 1
    assert response.json()["candidates"][0]["peer_base_url"] == "https://node-remote.example"
    assert service.list_wallet_identity_peers()[0]["peer_base_url"] == (
        "https://node-remote.example"
    )


def test_registry_wallet_identity_discover_peers_endpoint_can_repair_after_discovery(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(
        RegistryNodeAdvertisement(
            **_node_payload("node-local", heartbeat_at="2026-07-05T14:00:00+00:00")
        )
    )
    service.upsert_node(
        RegistryNodeAdvertisement(
            **_node_payload("node-remote", heartbeat_at="2026-07-05T14:00:00+00:00")
        )
    )
    client = TestClient(build_registry_app(service=service))
    payload = {
        "objects": [
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
        "conflicts": [],
    }

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(
        "aidn_hypervisor.registry_service.urllib_request.urlopen",
        lambda request, timeout=10: _Response(),
    )

    response = client.post(
        "/registry/wallet-identities/discover-peers",
        json={
            "self_node_id": "node-local",
            "repair_after_discovery": True,
            "limit": 500,
        },
    )

    assert response.status_code == 200
    assert response.json()["discovery"]["candidate_count"] == 1
    assert response.json()["repair"]["success_count"] == 1
    assert service.resolve_wallet_identity("wallet-consumer")["public_key"] == (
        "ed25519:" + "11" * 32
    )


def test_registry_wallet_identity_reconciliation_endpoint_reports_status(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_wallet_identity_peer(peer_base_url="https://peer-a.example/")
    service.upsert_registry_object(
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
    )
    client = TestClient(build_registry_app(service=service))

    response = client.get("/registry/wallet-identities/reconciliation")

    assert response.status_code == 200
    assert response.json()["summary"]["wallet_count"] == 1
    assert response.json()["summary"]["enabled_peer_count"] == 1
    assert response.json()["items"][0]["wallet_id"] == "wallet-consumer"
    assert response.json()["items"][0]["status"] == "consistent"


def test_registry_wallet_identity_resolve_conflict_endpoint_applies_resolution() -> None:
    service = RegistryService()
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
    service.upsert_registry_object(first)
    try:
        service.upsert_registry_object(second)
    except ValueError:
        pass
    client = TestClient(build_registry_app(service=service))

    response = client.post(
        "/registry/wallet-identities/resolve-conflict",
        json={
            "wallet_id": "wallet-consumer",
            "chosen_object_id": first["object_id"],
            "operator_note": "prefer original binding",
        },
    )

    assert response.status_code == 200
    assert response.json()["chosen_object_id"] == first["object_id"]
    assert service.resolve_wallet_identity("wallet-consumer")["identity_source"] == (
        "registry_resolution"
    )


def test_registry_discovery_endpoint_filters_by_workload_and_model(monkeypatch) -> None:
    ready_time = datetime.fromisoformat("2026-06-19T18:30:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(RegistryNodeAdvertisement(**_node_payload("node-a")))
    client = TestClient(build_registry_app(service=service))

    response = client.get(
        "/registry/discovery",
        params={"workload_type": "llm_text", "model_id": "phi-4-mini"},
    )

    assert response.status_code == 200
    assert response.json()["nodes"][0]["node_id"] == "node-a"
    assert response.json()["nodes"][0]["bundles"][0]["plugin_id"] == "llama.cpp"


def test_registry_discovery_excludes_stale_nodes_by_default(monkeypatch) -> None:
    current_time = [1000.0]
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: current_time[0])
    registry = RegistryService(stale_grace_seconds=30)
    registry.upsert_node(
        RegistryNodeAdvertisement(
            **_node_payload(
                "node-a",
                heartbeat_at="1970-01-01T00:16:40+00:00",
                heartbeat_ttl_seconds=10,
            )
        )
    )

    current_time[0] = 1015.0
    result = registry.discover(RegistryDiscoveryQuery(workload_type="llm_text"))

    assert result["nodes"] == []


def test_registry_discovery_endpoint_returns_flattened_candidates(monkeypatch) -> None:
    ready_time = datetime.fromisoformat("2026-06-19T18:30:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(RegistryNodeAdvertisement(**_node_payload("node-a")))
    client = TestClient(build_registry_app(service=service))

    response = client.get("/registry/discovery", params={"workload_type": "llm_text"})

    assert response.status_code == 200
    assert response.json()["candidates"] == [
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
            "endpoint": "https://node-a.example/runtimes/phi4-local",
            "endpoint_ready": True,
            "supports_allocation": True,
            "supports_queue": True,
        }
    ]


def test_registry_discovery_endpoint_returns_canonical_candidates(monkeypatch) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    payload = _node_payload("node-a", heartbeat_at="2026-07-05T14:00:00+00:00")
    payload["canonical_services"] = [
        {
            "service_id": "compute",
            "kind": "compute",
            "enabled": True,
            "derived_roles": ["compute_provider"],
            "responsibilities": ["endpoint_hosting"],
        }
    ]
    payload["canonical_capability_runtimes"] = [
        {
            "runtime_id": "runtime-phi4-local",
            "capability_id": "llm.chat",
            "runtime_version": "legacy.bundle.v1",
            "protocol_version": "runtime.v1",
            "location_kind": "local_process",
            "health_status": "healthy",
            "supported_features": ["legacy_bundle_compatibility"],
        }
    ]
    payload["canonical_compute_compatibility"] = [
        {
            "compatibility_id": "bundle:phi4-local",
            "legacy_bundle_id": "phi4-local",
            "legacy_plugin_id": "llama.cpp",
            "legacy_provider_type": "llama.cpp",
            "canonical_capability_id": "llm.chat",
            "canonical_runtime_id": "runtime-phi4-local",
        }
    ]
    payload["canonical_advertisements"] = [
        {
            "advertisement_id": "adv-endpoint-1",
            "resource_type": "endpoint",
            "owner_wallet": "wallet-a",
            "hypervisor_id": "node-a",
            "capability_id": "llm.chat",
            "visibility": "public",
            "signature_scope": "configuration_publication",
        }
    ]
    service.upsert_node(RegistryNodeAdvertisement(**payload))
    client = TestClient(build_registry_app(service=service))

    response = client.get("/registry/discovery", params={"capability_id": "llm.chat"})

    assert response.status_code == 200
    assert "canonical_candidates" in response.json()
    assert response.json()["canonical_candidates"][0]["capability_id"] == "llm.chat"


def test_registry_discovery_endpoint_filters_candidates_by_execution_flags(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-06-19T18:30:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    payload = _node_payload("node-a")
    payload["bundles"] = [
        {
            "bundle_id": "text-ready",
            "plugin_id": "llama.cpp",
            "workload_type": "llm_text",
            "provider_type": "llama.cpp",
            "model_id": "phi-4-mini.gguf",
            "endpoint": "https://node-a.example/runtimes/text-ready",
            "enabled": True,
            "status": "ready",
            "launch_mode": "managed_process",
            "device_affinity": "cpu",
            "max_parallel_requests": 1,
            "supports_allocation": True,
            "supports_queue": True,
        },
        {
            "bundle_id": "text-no-endpoint",
            "plugin_id": "llama.cpp",
            "workload_type": "llm_text",
            "provider_type": "llama.cpp",
            "model_id": "phi-4-mini.gguf",
            "endpoint": None,
            "enabled": True,
            "status": "ready",
            "launch_mode": "managed_process",
            "device_affinity": "cpu",
            "max_parallel_requests": 1,
            "supports_allocation": True,
            "supports_queue": True,
        },
    ]
    service.upsert_node(RegistryNodeAdvertisement(**payload))
    client = TestClient(build_registry_app(service=service))

    response = client.get(
        "/registry/discovery",
        params={
            "workload_type": "llm_text",
            "require_allocation_support": "true",
            "ready_endpoint_only": "true",
        },
    )

    assert response.status_code == 200
    assert [candidate["bundle_id"] for candidate in response.json()["candidates"]] == [
        "text-ready"
    ]
    assert response.json()["query"]["require_allocation_support"] is True
    assert response.json()["query"]["ready_endpoint_only"] is True
