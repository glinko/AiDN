import json
from datetime import datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from aidn_hypervisor.main import build_registry_app
from aidn_hypervisor.registry_models import RegistryDiscoveryQuery, RegistryNodeAdvertisement
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.wallet_identity import (
    wallet_identity_quorum_approval_payload,
    wallet_identity_quorum_proposal_payload,
)


def _node_payload(
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


def _wallet_identity_object(wallet_id: str, *, public_key: str, registration_nonce: str) -> dict:
    return {
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
            "registration_nonce": registration_nonce,
        },
    }


def _operator_signing_identity(node_id: str) -> dict:
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
        "object": _wallet_identity_object(
            wallet_id,
            public_key=public_key,
            registration_nonce=f"{wallet_id}-nonce",
        ),
        "owner_wallet_object": _wallet_identity_object(
            owner_wallet_id,
            public_key=public_key,
            registration_nonce=f"{owner_wallet_id}-nonce",
        ),
    }


def _sign_quorum_proposal(
    identity: dict,
    *,
    wallet_id: str,
    chosen_object_id: str,
    chosen_payload_hash: str,
    eligible_voter_node_ids: list[str],
    quorum_threshold: int,
    operator_note: str | None,
) -> str:
    signature = identity["private_key"].sign(
        wallet_identity_quorum_proposal_payload(
            wallet_id=wallet_id,
            chosen_object_id=chosen_object_id,
            chosen_payload_hash=chosen_payload_hash,
            proposer_node_id=identity["node_id"],
            eligible_voter_node_ids=eligible_voter_node_ids,
            quorum_threshold=quorum_threshold,
            operator_note=operator_note,
        )
    ).hex()
    return f"ed25519:{signature}"


def _sign_quorum_approval(
    identity: dict,
    *,
    resolution_id: str,
    approval_note: str | None,
) -> str:
    signature = identity["private_key"].sign(
        wallet_identity_quorum_approval_payload(
            resolution_id=resolution_id,
            approver_node_id=identity["node_id"],
            approval_note=approval_note,
        )
    ).hex()
    return f"ed25519:{signature}"


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


def test_registry_wallet_identity_quorum_proposal_endpoints_finalize_after_quorum(
) -> None:
    service = RegistryService()
    operator_a = _operator_signing_identity("node-a")
    operator_b = _operator_signing_identity("node-b")
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
    node_a = _node_payload("node-a")
    node_a["owner_wallet_id"] = operator_a["owner_wallet_id"]
    node_a["heartbeat_at"] = "2030-01-01T00:00:00+00:00"
    node_a["canonical_registry_objects"] = [consumer_object]
    node_b = _node_payload("node-b")
    node_b["owner_wallet_id"] = operator_b["owner_wallet_id"]
    node_b["heartbeat_at"] = "2030-01-01T00:00:00+00:00"
    node_b["canonical_registry_objects"] = [consumer_object]
    service.upsert_node(RegistryNodeAdvertisement(**node_a))
    service.upsert_node(RegistryNodeAdvertisement(**node_b))
    service.upsert_registry_object(operator_a["object"])
    service.upsert_registry_object(operator_b["object"])
    service.upsert_registry_object(operator_a["owner_wallet_object"])
    service.upsert_registry_object(operator_b["owner_wallet_object"])
    service.upsert_registry_object(consumer_object)
    client = TestClient(build_registry_app(service=service))

    proposed = client.post(
        "/registry/wallet-identities/quorum-proposals",
        json={
            "wallet_id": "wallet-consumer",
            "chosen_object_id": "sha256:wallet:consumer:a",
            "proposer_node_id": "node-a",
            "proposer_signature": _sign_quorum_proposal(
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
    resolution_id = proposed.json()["resolution_id"]

    approved = client.post(
        f"/registry/wallet-identities/quorum-proposals/{resolution_id}/approvals",
        json={
            "resolution_id": resolution_id,
            "approver_node_id": "node-b",
            "approval_signature": _sign_quorum_approval(
                operator_b,
                resolution_id=resolution_id,
                approval_note="second vote",
            ),
            "approval_note": "second vote",
        },
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "finalized"
    assert service.resolve_wallet_identity("wallet-consumer")["identity_source"] == (
        "registry_resolution"
    )


def test_registry_wallet_identity_quorum_proposal_endpoint_rejects_missing_signature(
) -> None:
    service = RegistryService()
    operator_a = _operator_signing_identity("node-a")
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
    node_a = _node_payload("node-a")
    node_a["owner_wallet_id"] = operator_a["owner_wallet_id"]
    node_a["heartbeat_at"] = "2030-01-01T00:00:00+00:00"
    node_a["canonical_registry_objects"] = [consumer_object]
    service.upsert_node(RegistryNodeAdvertisement(**node_a))
    service.upsert_registry_object(operator_a["object"])
    service.upsert_registry_object(operator_a["owner_wallet_object"])
    service.upsert_registry_object(consumer_object)
    client = TestClient(build_registry_app(service=service))

    proposed = client.post(
        "/registry/wallet-identities/quorum-proposals",
        json={
            "wallet_id": "wallet-consumer",
            "chosen_object_id": "sha256:wallet:consumer:a",
            "proposer_node_id": "node-a",
            "eligible_voter_node_ids": ["node-a"],
            "quorum_threshold": 1,
            "operator_note": "unsigned proposal",
        },
    )

    assert proposed.status_code == 409
    assert "requires proposer_signature" in proposed.json()["detail"]


def test_registry_wallet_identity_quorum_proposal_endpoint_rejects_non_authoritative_voter_set(
) -> None:
    service = RegistryService()
    operator_a = _operator_signing_identity("node-a")
    operator_b = _operator_signing_identity("node-b")
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
    node_a = _node_payload("node-a")
    node_a["owner_wallet_id"] = operator_a["owner_wallet_id"]
    node_a["heartbeat_at"] = "2030-01-01T00:00:00+00:00"
    node_a["canonical_registry_objects"] = [consumer_object]
    node_b = _node_payload("node-b")
    node_b["owner_wallet_id"] = operator_b["owner_wallet_id"]
    node_b["heartbeat_at"] = "2030-01-01T00:00:00+00:00"
    node_b["canonical_registry_objects"] = [consumer_object]
    service.upsert_node(RegistryNodeAdvertisement(**node_a))
    service.upsert_node(RegistryNodeAdvertisement(**node_b))
    service.upsert_registry_object(operator_a["object"])
    service.upsert_registry_object(operator_b["object"])
    service.upsert_registry_object(operator_a["owner_wallet_object"])
    service.upsert_registry_object(operator_b["owner_wallet_object"])
    service.upsert_registry_object(consumer_object)
    client = TestClient(build_registry_app(service=service))

    proposed = client.post(
        "/registry/wallet-identities/quorum-proposals",
        json={
            "wallet_id": "wallet-consumer",
            "chosen_object_id": "sha256:wallet:consumer:a",
            "proposer_node_id": "node-a",
            "proposer_signature": _sign_quorum_proposal(
                operator_a,
                wallet_id="wallet-consumer",
                chosen_object_id="sha256:wallet:consumer:a",
                chosen_payload_hash="sha256:wallet-payload:a",
                eligible_voter_node_ids=["node-a", "node-b", "node-c"],
                quorum_threshold=2,
                operator_note="oversized voter set",
            ),
            "eligible_voter_node_ids": ["node-a", "node-b", "node-c"],
            "quorum_threshold": 2,
            "operator_note": "oversized voter set",
        },
    )

    assert proposed.status_code == 409
    assert "authoritative wallet identity voter set" in proposed.json()["detail"]


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
