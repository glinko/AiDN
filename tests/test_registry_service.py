import hashlib
import json
import warnings
from datetime import datetime
from pathlib import Path
from urllib import error as urllib_error

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.registry_models import RegistryDiscoveryQuery, RegistryNodeAdvertisement
from aidn_hypervisor.registry_service import (
    RegistryService,
    WalletIdentityPeerTransport,
)
from aidn_hypervisor.wallet_identity import (
    sign_wallet_identity_sync_envelope,
    wallet_identity_governance_revocation_id,
    wallet_identity_governance_revocation_payload,
    wallet_identity_quorum_approval_payload,
    wallet_identity_quorum_proposal_payload,
)


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
    owner_wallet_id: str | None = None,
    status: str = "ready",
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
        owner_wallet_id=owner_wallet_id,
        base_url=f"https://{node_id}.example",
        heartbeat_at=heartbeat_at,
        heartbeat_ttl_seconds=heartbeat_ttl_seconds,
        status=status,
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


def _wallet_identity_object(
    wallet_id: str,
    *,
    public_key: str,
    registration_nonce: str,
) -> dict:
    payload = {
        "wallet_id": wallet_id,
        "public_key": public_key,
        "registration_nonce": registration_nonce,
    }
    return {
        "object_id": f"sha256:wallet:{wallet_id}:{public_key[-8:]}",
        "object_type": "wallet_identity",
        "object_version": "wallet-identity.v1",
        "namespace": "identity",
        "payload_hash": f"sha256:payload:{wallet_id}:{public_key[-8:]}",
        "payload_encoding": "canonical_json",
        "source_reference": wallet_id,
        "payload": payload,
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
        "public_key": public_key,
        "private_key": private_key,
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


def _sign_governance_revocation(
    identity: dict,
    *,
    certificate_id: str,
    revocation_id: str,
    reason: str,
    eligible_voter_node_ids: list[str],
    quorum_threshold: int,
) -> str:
    signature = identity["private_key"].sign(
        wallet_identity_governance_revocation_payload(
            certificate_id=certificate_id,
            revocation_id=revocation_id,
            reason=reason,
            eligible_voter_node_ids=eligible_voter_node_ids,
            quorum_threshold=quorum_threshold,
        )
    ).hex()
    return f"ed25519:{signature}"


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
                    "audio_input_second": 0.0,
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


def test_registry_service_local_completeness_summary_ignores_node_backed_objects() -> None:
    service = RegistryService()
    service.upsert_registry_object(
        {
            "object_id": "sha256:stored-capdef-1",
            "object_type": "capability_definition",
            "object_version": "1.0",
            "namespace": "protocol",
            "payload_hash": "sha256:stored-capdef-payload-1",
            "payload_encoding": "canonical_json",
            "source_reference": "capdef:llm.chat:v1",
        }
    )
    service.upsert_node(
        _node(
            "node-a",
            canonical_registry_objects=[
                {
                    "object_id": "sha256:node-pricing-1",
                    "object_type": "pricing_policy",
                    "object_version": "1.0",
                    "namespace": "marketplace",
                    "payload_hash": "sha256:node-pricing-payload-1",
                    "payload_encoding": "canonical_json",
                    "source_reference": "pricing:endpoint-1:v1",
                }
            ],
        )
    )

    summary = service.get_local_registry_completeness_summary()

    assert summary.store_totals.total_object_count == 1
    assert summary.store_totals.payload_object_count == 0
    assert summary.store_totals.payload_bytes_total == 0
    assert summary.by_namespace == {"protocol": 1}
    assert summary.by_object_type == {"capability_definition": 1}


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


def test_registry_service_rejects_conflicting_wallet_identity_objects_across_nodes(
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
                _wallet_identity_object(
                    "wallet-consumer",
                    public_key="ed25519:" + "11" * 32,
                    registration_nonce="nonce-a",
                )
            ],
        )
    )

    with pytest.raises(ValueError, match="wallet-consumer"):
        service.upsert_node(
            _node(
                "node-b",
                heartbeat_at="2026-07-05T14:00:00+00:00",
                canonical_registry_objects=[
                    _wallet_identity_object(
                        "wallet-consumer",
                        public_key="ed25519:" + "22" * 32,
                        registration_nonce="nonce-b",
                    )
                ],
            )
        )
    conflicts = service.list_conflicts(
        conflict_class="wallet_identity_binding",
        logical_key="wallet-consumer",
    )
    assert len(conflicts) == 1
    assert conflicts[0]["existing_record"]["source_reference"] == "wallet-consumer"
    assert conflicts[0]["conflicting_record"]["payload"]["public_key"] == (
        "ed25519:" + "22" * 32
    )


def test_registry_service_rejects_conflicting_wallet_identity_store_ingest() -> None:
    service = RegistryService()
    service.upsert_registry_object(
        _wallet_identity_object(
            "wallet-consumer",
            public_key="ed25519:" + "11" * 32,
            registration_nonce="nonce-a",
        )
    )

    with pytest.raises(ValueError, match="wallet-consumer"):
        service.upsert_registry_object(
            _wallet_identity_object(
                "wallet-consumer",
                public_key="ed25519:" + "22" * 32,
                registration_nonce="nonce-b",
            )
        )


def test_registry_service_resolves_wallet_identity_from_registry_objects(
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
                _wallet_identity_object(
                    "wallet-consumer",
                    public_key="ed25519:" + "11" * 32,
                    registration_nonce="nonce-a",
                )
            ],
        )
    )

    resolved = service.resolve_wallet_identity("wallet-consumer")

    assert resolved is not None
    assert resolved["wallet_id"] == "wallet-consumer"
    assert resolved["public_key"] == "ed25519:" + "11" * 32
    assert resolved["identity_source"] == "registry_object"


def test_registry_service_persists_conflict_evidence_in_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    snapshot_path = tmp_path / "registry-objects.json"
    service = RegistryService(snapshot_path=snapshot_path)
    service.upsert_node(
        _node(
            "node-a",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[
                _wallet_identity_object(
                    "wallet-consumer",
                    public_key="ed25519:" + "11" * 32,
                    registration_nonce="nonce-a",
                )
            ],
        )
    )
    with pytest.raises(ValueError, match="wallet-consumer"):
        service.upsert_node(
            _node(
                "node-b",
                heartbeat_at="2026-07-05T14:00:00+00:00",
                canonical_registry_objects=[
                    _wallet_identity_object(
                        "wallet-consumer",
                        public_key="ed25519:" + "22" * 32,
                        registration_nonce="nonce-b",
                    )
                ],
            )
        )

    restarted = RegistryService(snapshot_path=snapshot_path)
    conflicts = restarted.list_conflicts(logical_key="wallet-consumer")

    assert len(conflicts) == 1
    assert conflicts[0]["conflict_class"] == "wallet_identity_binding"


def test_registry_service_exports_and_imports_wallet_identity_sync_state(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    source = RegistryService()
    source.upsert_node(
        _node(
            "node-a",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[
                _wallet_identity_object(
                    "wallet-consumer",
                    public_key="ed25519:" + "11" * 32,
                    registration_nonce="nonce-a",
                )
            ],
        )
    )
    exported = source.export_wallet_identity_sync_state()
    target = RegistryService()

    result = target.import_wallet_identity_sync_state(
        objects=[
            {
                "object_id": item["object_id"],
                "object_type": item["object_type"],
                "object_version": item["object_version"],
                "namespace": item["namespace"],
                "payload_hash": item["payload_hash"],
                "payload_encoding": item["payload_encoding"],
                "source_reference": item["source_reference"],
                "payload": item["payload"],
            }
            for item in exported["objects"]
        ],
        conflicts=exported["conflicts"],
    )

    assert result["imported_object_count"] == 1
    assert result["rejected_objects"] == []
    resolved = target.resolve_wallet_identity("wallet-consumer")
    assert resolved is not None
    assert resolved["public_key"] == "ed25519:" + "11" * 32


def test_registry_service_import_wallet_identity_sync_state_reports_conflicts(
) -> None:
    target = RegistryService()
    target.upsert_registry_object(
        _wallet_identity_object(
            "wallet-consumer",
            public_key="ed25519:" + "11" * 32,
            registration_nonce="nonce-a",
        )
    )

    result = target.import_wallet_identity_sync_state(
        objects=[
            _wallet_identity_object(
                "wallet-consumer",
                public_key="ed25519:" + "22" * 32,
                registration_nonce="nonce-b",
            )
        ],
        conflicts=[],
    )

    assert result["imported_object_count"] == 0
    assert len(result["rejected_objects"]) == 1
    assert "wallet-consumer" in result["rejected_objects"][0]["reason"]
    assert result["conflict_count"] == 1


def test_registry_service_syncs_wallet_identity_from_peer(monkeypatch) -> None:
    service = RegistryService()
    payload = {
        "objects": [
            _wallet_identity_object(
                "wallet-consumer",
                public_key="ed25519:" + "11" * 32,
                registration_nonce="nonce-a",
            )
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
    monkeypatch.setattr(
        service._wallet_identity_peer_transport,
        "fetch",
        lambda request, timeout_seconds=10: _Response(),
    )

    result = service.sync_wallet_identity_from_peer(
        peer_base_url="https://peer-a.example/"
    )

    assert result["peer_base_url"] == "https://peer-a.example"
    assert result["imported_object_count"] == 1
    assert service.resolve_wallet_identity("wallet-consumer")["public_key"] == (
        "ed25519:" + "11" * 32
    )


def test_wallet_identity_peer_transport_rejects_redirects(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Opener:
        def open(self, request, *, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return "response"

    monkeypatch.setattr(
        "aidn_hypervisor.registry_service.urllib_request.build_opener",
        lambda handler: captured.setdefault("handler", handler) and _Opener(),
    )

    response = WalletIdentityPeerTransport().fetch(
        object(), timeout_seconds=7
    )

    assert response == "response"
    assert captured["handler"].redirect_request(None, None, 302, None, None, None) is None
    assert captured["timeout"] == 7


def test_registry_service_requires_valid_signed_peer_envelope(monkeypatch) -> None:
    service = RegistryService()
    private_key = Ed25519PrivateKey.generate()
    public_key = "ed25519:" + private_key.public_key().public_bytes_raw().hex()
    sync_state = {
        "objects": [
            _wallet_identity_object(
                "wallet-consumer",
                public_key="ed25519:" + "11" * 32,
                registration_nonce="nonce-a",
            ),
            _wallet_identity_object(
                "wallet-peer",
                public_key=public_key,
                registration_nonce="peer-nonce",
            ),
        ],
        "conflicts": [],
    }
    state_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            sync_state, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    source = {
        "node_id": "node-peer",
        "operator_id": "operator-peer",
        "owner_wallet_id": "wallet-peer",
        "public_key": public_key,
        "state_hash": state_hash,
    }
    payload = {
        "sync_state": sync_state,
        "source": source,
        "signature": sign_wallet_identity_sync_envelope(
            private_key="ed25519:" + private_key.private_bytes_raw().hex(),
            **source,
        ),
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
    monkeypatch.setattr(
        service._wallet_identity_peer_transport,
        "fetch",
        lambda request, timeout_seconds=10: _Response(),
    )

    result = service.sync_wallet_identity_from_peer(
        peer_base_url="https://peer.example",
        expected_node_id="node-peer",
        expected_operator_id="operator-peer",
        expected_owner_wallet_id="wallet-peer",
    )

    assert result["imported_object_count"] == 2
    payload["source"]["node_id"] = "node-other"
    with pytest.raises(ValueError, match="node_id does not match"):
        service.sync_wallet_identity_from_peer(
            peer_base_url="https://peer.example",
            expected_node_id="node-peer",
        )


def test_registry_service_sync_wallet_identity_from_peer_rejects_invalid_peer(
    monkeypatch,
) -> None:
    service = RegistryService()
    monkeypatch.setattr(
        "aidn_hypervisor.registry_service.urllib_request.urlopen",
        lambda request, timeout=10: (_ for _ in ()).throw(
            urllib_error.URLError("peer unavailable")
        ),
    )

    with pytest.raises(ValueError, match="Failed to sync wallet identities from peer"):
        service.sync_wallet_identity_from_peer(peer_base_url="https://peer-a.example")


@pytest.mark.parametrize(
    "peer_base_url",
    [
        "",
        "ftp://peer-a.example",
        "https://user:secret@peer-a.example",
        "https://peer-a.example/registry",
        "https://peer-a.example?limit=1",
        "https://peer-a.example#fragment",
        "https://peer-a.example:99999",
    ],
)
def test_registry_service_rejects_unsafe_wallet_identity_peer_urls(
    peer_base_url: str,
) -> None:
    service = RegistryService()

    with pytest.raises(ValueError, match="peer_base_url"):
        service.upsert_wallet_identity_peer(peer_base_url=peer_base_url)
    with pytest.raises(ValueError, match="peer_base_url"):
        service.sync_wallet_identity_from_peer(peer_base_url=peer_base_url)


def test_registry_service_persists_wallet_identity_peer_config_and_sync_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    service = RegistryService(snapshot_path=snapshot_path)
    service.upsert_wallet_identity_peer(peer_base_url="https://peer-a.example/")
    payload = {
        "objects": [
            _wallet_identity_object(
                "wallet-consumer",
                public_key="ed25519:" + "11" * 32,
                registration_nonce="nonce-a",
            )
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
    monkeypatch.setattr(
        service._wallet_identity_peer_transport,
        "fetch",
        lambda request, timeout_seconds=10: _Response(),
    )

    result = service.repair_wallet_identity_peers()

    assert result["success_count"] == 1
    restarted = RegistryService(snapshot_path=snapshot_path)
    peers = restarted.list_wallet_identity_peers()
    assert peers == [
        {
            "peer_base_url": "https://peer-a.example",
            "enabled": True,
            "added_at": peers[0]["added_at"],
            "last_sync_at": peers[0]["last_sync_at"],
            "last_sync_status": "ok",
            "last_sync_error": None,
            "last_import_result": {
                "peer_base_url": "https://peer-a.example",
                "imported_object_count": 1,
                "rejected_objects": [],
                "accepted_conflict_count": 0,
                "conflict_count": 0,
            },
        }
    ]


def test_registry_service_repair_wallet_identity_peers_tracks_errors_and_skips_disabled(
    monkeypatch,
) -> None:
    service = RegistryService()
    service.upsert_wallet_identity_peer(peer_base_url="https://peer-a.example/")
    service.upsert_wallet_identity_peer(
        peer_base_url="https://peer-b.example/",
        enabled=False,
    )
    monkeypatch.setattr(
        "aidn_hypervisor.registry_service.urllib_request.urlopen",
        lambda request, timeout=10: (_ for _ in ()).throw(
            urllib_error.URLError("peer unavailable")
        ),
    )
    monkeypatch.setattr(
        service._wallet_identity_peer_transport,
        "fetch",
        lambda request, timeout_seconds=10: (_ for _ in ()).throw(
            urllib_error.URLError("peer unavailable")
        ),
    )

    result = service.repair_wallet_identity_peers()

    assert result["enabled_peer_count"] == 1
    assert result["attempted_peer_count"] == 1
    assert result["error_count"] == 1
    peers = service.list_wallet_identity_peers()
    assert peers[0]["peer_base_url"] == "https://peer-a.example"
    assert peers[0]["last_sync_status"] == "error"
    assert "Failed to sync wallet identities from peer" in peers[0]["last_sync_error"]
    assert peers[1]["peer_base_url"] == "https://peer-b.example"
    assert peers[1]["enabled"] is False
    assert peers[1]["last_sync_status"] is None


def test_registry_service_repair_wallet_identity_peers_uses_configured_identity_pins(
    monkeypatch,
) -> None:
    service = RegistryService()
    service.upsert_wallet_identity_peer(
        peer_base_url="https://peer-a.example/",
        expected_node_id="node-peer-a",
        expected_operator_id="operator-peer-a",
        expected_owner_wallet_id="wallet-peer-a",
    )
    captured: dict[str, object] = {}

    def sync_wallet_identity_from_peer(**kwargs) -> dict:
        captured.update(kwargs)
        return {"imported_object_count": 1}

    monkeypatch.setattr(
        service,
        "sync_wallet_identity_from_peer",
        sync_wallet_identity_from_peer,
    )

    result = service.repair_wallet_identity_peers(limit=321, timeout_seconds=7)

    assert result["success_count"] == 1
    assert captured == {
        "peer_base_url": "https://peer-a.example",
        "limit": 321,
        "timeout_seconds": 7,
        "expected_node_id": "node-peer-a",
        "expected_operator_id": "operator-peer-a",
        "expected_owner_wallet_id": "wallet-peer-a",
    }


def test_registry_service_persists_wallet_identity_peer_identity_pins(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    service = RegistryService(snapshot_path=snapshot_path)
    service.upsert_wallet_identity_peer(
        peer_base_url="https://peer-a.example/",
        expected_node_id="node-peer-a",
        expected_operator_id="operator-peer-a",
        expected_owner_wallet_id="wallet-peer-a",
    )

    restarted = RegistryService(snapshot_path=snapshot_path)

    assert restarted.list_wallet_identity_peers()[0] == {
        "peer_base_url": "https://peer-a.example",
        "enabled": True,
        "expected_node_id": "node-peer-a",
        "expected_operator_id": "operator-peer-a",
        "expected_owner_wallet_id": "wallet-peer-a",
        "added_at": restarted.list_wallet_identity_peers()[0]["added_at"],
        "last_sync_at": None,
        "last_sync_status": None,
        "last_sync_error": None,
        "last_import_result": None,
    }


def test_registry_service_discovers_wallet_identity_peers_from_nodes(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(_node("node-local", heartbeat_at="2026-07-05T14:00:00+00:00"))
    service.upsert_node(
        _node(
            "node-remote-a",
            owner_wallet_id="wallet-remote-a",
            heartbeat_at="2026-07-05T14:00:00+00:00",
        )
    )
    service.upsert_node(_node("node-remote-b", heartbeat_at="2026-07-05T14:00:00+00:00"))

    result = service.discover_wallet_identity_peers_from_nodes(
        self_node_id="node-local",
    )

    assert result["candidate_count"] == 2
    assert result["registered_count"] == 2
    assert [item["peer_base_url"] for item in result["candidates"]] == [
        "https://node-remote-a.example",
        "https://node-remote-b.example",
    ]
    assert [item["peer_base_url"] for item in service.list_wallet_identity_peers()] == [
        "https://node-remote-a.example",
        "https://node-remote-b.example",
    ]
    assert service.list_wallet_identity_peers()[0]["expected_node_id"] == "node-remote-a"
    assert service.list_wallet_identity_peers()[0]["expected_operator_id"] == (
        "node-remote-a-operator"
    )
    assert service.list_wallet_identity_peers()[0]["expected_owner_wallet_id"] == (
        "wallet-remote-a"
    )


def test_registry_service_discover_and_repair_wallet_identity_peers(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(_node("node-local", heartbeat_at="2026-07-05T14:00:00+00:00"))
    service.upsert_node(_node("node-remote-a", heartbeat_at="2026-07-05T14:00:00+00:00"))
    payload = {
        "objects": [
            _wallet_identity_object(
                "wallet-consumer",
                public_key="ed25519:" + "11" * 32,
                registration_nonce="nonce-a",
            )
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
    monkeypatch.setattr(
        service._wallet_identity_peer_transport,
        "fetch",
        lambda request, timeout_seconds=10: _Response(),
    )

    result = service.discover_and_repair_wallet_identity_peers(
        self_node_id="node-local",
    )

    assert result["discovery"]["candidate_count"] == 1
    assert result["repair"]["success_count"] == 1
    assert service.resolve_wallet_identity("wallet-consumer")["public_key"] == (
        "ed25519:" + "11" * 32
    )


def test_registry_service_wallet_identity_reconciliation_report_summarizes_state(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_wallet_identity_peer(peer_base_url="https://peer-a.example/")
    service.upsert_wallet_identity_peer(peer_base_url="https://peer-b.example/")
    service._wallet_identity_peers["https://peer-b.example"]["last_sync_status"] = "error"
    service.upsert_node(
        _node(
            "node-a",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[
                _wallet_identity_object(
                    "wallet-consumer",
                    public_key="ed25519:" + "11" * 32,
                    registration_nonce="nonce-a",
                )
            ],
        )
    )
    service.upsert_node(
        _node(
            "node-b",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[
                _wallet_identity_object(
                    "wallet-auditor",
                    public_key="ed25519:" + "33" * 32,
                    registration_nonce="nonce-c",
                )
            ],
        )
    )

    report = service.wallet_identity_reconciliation_report()

    assert report["summary"]["wallet_count"] == 2
    assert report["summary"]["consistent_count"] == 2
    assert report["summary"]["conflict_count"] == 0
    assert report["summary"]["enabled_peer_count"] == 2
    assert report["summary"]["peer_error_count"] == 1
    assert report["summary"]["peer_pending_count"] == 1
    consumer = next(
        item for item in report["items"] if item["wallet_id"] == "wallet-consumer"
    )
    assert consumer["status"] == "consistent"
    assert consumer["payload_variant_count"] == 1
    assert consumer["source_nodes"] == ["node-a"]


def test_registry_service_resolves_wallet_identity_conflict_with_operator_choice(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    snapshot_path = tmp_path / "registry-objects.json"
    service = RegistryService(snapshot_path=snapshot_path)
    first = _wallet_identity_object(
        "wallet-consumer",
        public_key="ed25519:" + "11" * 32,
        registration_nonce="nonce-a",
    )
    second = _wallet_identity_object(
        "wallet-consumer",
        public_key="ed25519:" + "22" * 32,
        registration_nonce="nonce-b",
    )
    service.upsert_registry_object(first)
    with pytest.raises(ValueError, match="wallet-consumer"):
        service.upsert_registry_object(second)

    resolution = service.resolve_wallet_identity_conflict(
        wallet_id="wallet-consumer",
        chosen_object_id=first["object_id"],
        operator_note="prefer original binding",
    )

    assert resolution["wallet_id"] == "wallet-consumer"
    assert resolution["chosen_object_id"] == first["object_id"]
    assert resolution["public_key"] == "ed25519:" + "11" * 32
    resolved = service.resolve_wallet_identity("wallet-consumer")
    assert resolved is not None
    assert resolved["identity_source"] == "registry_resolution"
    assert resolved["public_key"] == "ed25519:" + "11" * 32
    conflicts = service.list_conflicts(logical_key="wallet-consumer")
    assert conflicts[0]["status"] == "resolved"
    assert conflicts[0]["resolution_payload"]["chosen_object_id"] == first["object_id"]
    report = service.wallet_identity_reconciliation_report()
    consumer = next(item for item in report["items"] if item["wallet_id"] == "wallet-consumer")
    assert consumer["status"] == "resolved"
    assert consumer["resolution"]["chosen_object_id"] == first["object_id"]

    restarted = RegistryService(snapshot_path=snapshot_path)
    restarted_identity = restarted.resolve_wallet_identity("wallet-consumer")
    assert restarted_identity is not None
    assert restarted_identity["identity_source"] == "registry_resolution"
    assert restarted_identity["public_key"] == "ed25519:" + "11" * 32


def test_registry_service_finalizes_wallet_identity_quorum_resolution(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    ledger = LedgerOperationService()
    snapshot_path = tmp_path / "registry-objects.json"
    service = RegistryService(
        snapshot_path=snapshot_path,
        ledger_operation_service=ledger,
    )
    service.update_wallet_identity_governance_policy(
        quorum_resolution_required=True,
        ledger_authorization_required=True,
    )
    operator_a = _operator_signing_identity("node-a")
    operator_b = _operator_signing_identity("node-b")
    consumer_object = _wallet_identity_object(
        "wallet-consumer",
        public_key="ed25519:" + "11" * 32,
        registration_nonce="nonce-a",
    )
    service.upsert_node(
        _node(
            "node-a",
            owner_wallet_id=operator_a["owner_wallet_id"],
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[consumer_object],
        )
    )
    service.upsert_node(
        _node(
            "node-b",
            owner_wallet_id=operator_b["owner_wallet_id"],
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[consumer_object],
        )
    )
    service.upsert_registry_object(operator_a["object"])
    service.upsert_registry_object(operator_b["object"])
    service.upsert_registry_object(operator_a["owner_wallet_object"])
    service.upsert_registry_object(operator_b["owner_wallet_object"])
    proposal_signature = _sign_quorum_proposal(
        operator_a,
        wallet_id="wallet-consumer",
        chosen_object_id=str(consumer_object["object_id"]),
        chosen_payload_hash=str(consumer_object["payload_hash"]),
        eligible_voter_node_ids=["node-a", "node-b"],
        quorum_threshold=2,
        operator_note="network quorum proposal",
    )

    proposal = service.propose_wallet_identity_quorum_resolution(
        wallet_id="wallet-consumer",
        chosen_object_id=str(consumer_object["object_id"]),
        proposer_node_id="node-a",
        proposer_signature=proposal_signature,
        eligible_voter_node_ids=["node-a", "node-b"],
        quorum_threshold=2,
        operator_note="network quorum proposal",
    )

    assert proposal["status"] == "pending"
    assert len(proposal["approvals"]) == 1
    assert (
        proposal["voter_policy"]
        == "wallet_identity_source_nodes_with_owner_wallet_link.v1"
    )
    assert proposal["eligible_voter_node_ids"] == ["node-a", "node-b"]

    approved = service.approve_wallet_identity_quorum_resolution(
        resolution_id=proposal["resolution_id"],
        approver_node_id="node-b",
        approval_signature=_sign_quorum_approval(
            operator_b,
            resolution_id=proposal["resolution_id"],
            approval_note="second vote",
        ),
        approval_note="second vote",
    )

    assert approved["status"] == "finalized"
    assert approved["final_resolution"]["wallet_id"] == "wallet-consumer"
    certificate = approved["governance_certificate"]
    assert certificate["certificate_version"] == "wallet-identity-governance-certificate.v1"
    assert certificate["quorum_threshold"] == 2
    assert [item["approver_node_id"] for item in certificate["approvals"]] == [
        "node-a",
        "node-b",
    ]
    assert approved["final_resolution"]["governance_certificate"] == certificate
    ledger_commitment = certificate["ledger_commitment"]
    assert ledger_commitment["certificate_id"] == certificate["certificate_id"]
    assert ledger_commitment["operation_type"] == "GOVERNANCE_AUTHORIZATION_COMMIT"
    ledger_record = ledger.wallet_identity_governance_certificate_commitment(
        certificate["certificate_id"]
    )
    assert ledger_record is not None
    assert ledger_record["operation_id"] == ledger_commitment["operation_id"]
    certificates = service.list_wallet_identity_governance_certificates()
    assert len(certificates) == 1
    assert certificates[0]["payload"]["certificate_id"] == certificate["certificate_id"]
    resolved = service.resolve_wallet_identity("wallet-consumer")
    assert resolved is not None
    assert resolved["identity_source"] == "registry_resolution"
    assert resolved["resolution"]["chosen_object_id"] == str(consumer_object["object_id"])

    service.upsert_wallet_identity_peer(peer_base_url="https://peer-a.example")
    peer_proof = service.wallet_identity_governance_certificate_ledger_proof(
        certificate["certificate_id"]
    )
    assert peer_proof is not None

    class _ProofResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    monkeypatch.setattr(
        "aidn_hypervisor.registry_service.urllib_request.urlopen",
        lambda request, timeout=10: _ProofResponse(peer_proof),
    )
    peer_report = service.wallet_identity_governance_certificate_peer_proof_report(
        certificate["certificate_id"]
    )
    assert peer_report["matching_peer_count"] == 1
    assert peer_report["consensus_finality"] is False
    assert peer_report["peer_results"][0]["status"] == "matching"

    tampered_peer_proof = json.loads(json.dumps(peer_proof))
    tampered_peer_proof["payload"]["wallet_id"] = "wallet-attacker"
    monkeypatch.setattr(
        "aidn_hypervisor.registry_service.urllib_request.urlopen",
        lambda request, timeout=10: _ProofResponse(tampered_peer_proof),
    )
    invalid_peer_report = service.wallet_identity_governance_certificate_peer_proof_report(
        certificate["certificate_id"]
    )
    assert invalid_peer_report["invalid_peer_count"] == 1

    restored_ledger = LedgerOperationService()
    restored_ledger.restore(
        operations=ledger.snapshot_operations(),
        wallet_sequences=ledger.snapshot_wallet_sequences(),
    )
    restarted = RegistryService(snapshot_path=snapshot_path)
    restarted.bind_ledger_operation_service(restored_ledger)
    restarted_resolution = restarted.resolve_wallet_identity("wallet-consumer")
    assert restarted_resolution is not None
    assert restarted_resolution["identity_source"] == "registry_resolution"

    tampered_resolution = json.loads(json.dumps(approved["final_resolution"]))
    tampered_resolution["governance_certificate"]["approvals"][1][
        "approval_signature"
    ] = "ed25519:" + "00" * 64
    replica = RegistryService()
    with pytest.raises(ValueError, match="governance certificate"):
        replica.upsert_registry_object(
            service._wallet_identity_resolution_registry_object(
                resolution=tampered_resolution
            )
        )
    assert replica.list_wallet_identity_resolutions() == []

    strict_replica = RegistryService(ledger_operation_service=LedgerOperationService())
    strict_replica.update_wallet_identity_governance_policy(
        quorum_resolution_required=True,
        ledger_authorization_required=True,
    )
    with pytest.raises(ValueError, match="Ledger commitment is unknown"):
        strict_replica.upsert_registry_object(
            service._wallet_identity_resolution_registry_object(
                resolution=approved["final_resolution"]
            )
        )

    revocation_reason = "operator key compromise"
    revocation_id = wallet_identity_governance_revocation_id(
        certificate_id=certificate["certificate_id"],
        reason=revocation_reason,
        eligible_voter_node_ids=["node-a", "node-b"],
        quorum_threshold=2,
    )
    revocation = service.revoke_wallet_identity_governance_certificate(
        certificate_id=certificate["certificate_id"],
        reason=revocation_reason,
        approvals=[
            {
                "approver_node_id": "node-a",
                "approval_signature": _sign_governance_revocation(
                    operator_a,
                    certificate_id=certificate["certificate_id"],
                    revocation_id=revocation_id,
                    reason=revocation_reason,
                    eligible_voter_node_ids=["node-a", "node-b"],
                    quorum_threshold=2,
                ),
            },
            {
                "approver_node_id": "node-b",
                "approval_signature": _sign_governance_revocation(
                    operator_b,
                    certificate_id=certificate["certificate_id"],
                    revocation_id=revocation_id,
                    reason=revocation_reason,
                    eligible_voter_node_ids=["node-a", "node-b"],
                    quorum_threshold=2,
                ),
            },
        ],
    )
    assert revocation["ledger_commitment"]["operation_type"] == "GOVERNANCE_AUTHORIZATION_REVOKE"
    assert service.list_wallet_identity_governance_revocations()[0]["payload"]["revocation_id"] == revocation_id
    assert service.list_wallet_identity_resolutions() == []
    revocation_peer_proof = service.wallet_identity_governance_revocation_ledger_proof(
        certificate["certificate_id"]
    )
    assert revocation_peer_proof is not None
    monkeypatch.setattr(
        "aidn_hypervisor.registry_service.urllib_request.urlopen",
        lambda request, timeout=10: _ProofResponse(revocation_peer_proof),
    )
    revocation_peer_report = service.wallet_identity_governance_revocation_peer_proof_report(
        certificate["certificate_id"]
    )
    assert revocation_peer_report["matching_peer_count"] == 1
    assert revocation_peer_report["consensus_finality"] is False

    forged_revocation = json.loads(json.dumps(revocation))
    forged_revocation["voter_authorities"] = []
    forged_replica = RegistryService(ledger_operation_service=ledger)
    forged_replica.update_wallet_identity_governance_policy(
        quorum_resolution_required=True,
        ledger_authorization_required=True,
    )
    forged_replica.upsert_registry_object(
        service._wallet_identity_governance_certificate_registry_object(certificate)
    )
    with pytest.raises(ValueError, match="revocation authority does not match"):
        forged_replica.upsert_registry_object(
            service._wallet_identity_governance_revocation_registry_object(forged_revocation)
        )
    assert forged_replica.list_wallet_identity_governance_revocations() == []

    revoked_ledger = LedgerOperationService()
    revoked_ledger.restore(
        operations=ledger.snapshot_operations(),
        wallet_sequences=ledger.snapshot_wallet_sequences(),
    )
    revoked_restart = RegistryService(snapshot_path=snapshot_path)
    revoked_restart.bind_ledger_operation_service(revoked_ledger)
    assert revoked_restart.list_wallet_identity_resolutions() == []


def test_registry_service_wallet_identity_governance_policy_persists_and_shapes_quorum(
    monkeypatch,
    tmp_path: Path,
) -> None:
    current_time = datetime.fromisoformat("2030-01-01T00:00:35+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: current_time)
    snapshot_path = tmp_path / "registry-objects.json"
    service = RegistryService(snapshot_path=snapshot_path)
    operator_a = _operator_signing_identity("node-a")
    operator_b = _operator_signing_identity("node-b")
    consumer_object = _wallet_identity_object(
        "wallet-consumer",
        public_key="ed25519:" + "11" * 32,
        registration_nonce="nonce-a",
    )
    service.upsert_node(
        _node(
            "node-a",
            owner_wallet_id=operator_a["owner_wallet_id"],
            heartbeat_at="2030-01-01T00:00:05+00:00",
            canonical_registry_objects=[consumer_object],
        )
    )
    service.upsert_node(
        _node(
            "node-b",
            owner_wallet_id=operator_b["owner_wallet_id"],
            heartbeat_at="2030-01-01T00:00:00+00:00",
            canonical_registry_objects=[consumer_object],
        )
    )
    service.upsert_registry_object(operator_a["object"])
    service.upsert_registry_object(operator_b["object"])
    service.upsert_registry_object(operator_a["owner_wallet_object"])
    service.upsert_registry_object(operator_b["owner_wallet_object"])
    service.upsert_registry_object(consumer_object)

    policy = service.update_wallet_identity_governance_policy(
        authorized_voter_statuses=["ready"]
    )
    assert policy["authorized_voter_statuses"] == ["ready"]

    proposal = service.propose_wallet_identity_quorum_resolution(
        wallet_id="wallet-consumer",
        chosen_object_id=str(consumer_object["object_id"]),
        proposer_node_id="node-a",
        proposer_signature=_sign_quorum_proposal(
            operator_a,
            wallet_id="wallet-consumer",
            chosen_object_id=str(consumer_object["object_id"]),
            chosen_payload_hash=str(consumer_object["payload_hash"]),
            eligible_voter_node_ids=["node-a"],
            quorum_threshold=1,
            operator_note="ready-only governance policy",
        ),
        eligible_voter_node_ids=["node-a"],
        quorum_threshold=1,
        operator_note="ready-only governance policy",
    )

    assert proposal["eligible_voter_node_ids"] == ["node-a"]
    assert proposal["status"] == "finalized"
    assert (
        proposal["governance_policy_snapshot"]["authorized_voter_statuses"] == ["ready"]
    )

    restarted = RegistryService(snapshot_path=snapshot_path)
    assert restarted.wallet_identity_governance_policy()["authorized_voter_statuses"] == [
        "ready"
    ]


def test_registry_service_wallet_identity_governance_policy_requires_minimum_voters(
    monkeypatch,
) -> None:
    current_time = datetime.fromisoformat("2030-01-01T00:00:35+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: current_time)
    service = RegistryService()
    operator_a = _operator_signing_identity("node-a")
    operator_b = _operator_signing_identity("node-b")
    consumer_object = _wallet_identity_object(
        "wallet-consumer",
        public_key="ed25519:" + "11" * 32,
        registration_nonce="nonce-a",
    )
    service.upsert_node(
        _node(
            "node-a",
            owner_wallet_id=operator_a["owner_wallet_id"],
            heartbeat_at="2030-01-01T00:00:05+00:00",
            canonical_registry_objects=[consumer_object],
        )
    )
    service.upsert_node(
        _node(
            "node-b",
            owner_wallet_id=operator_b["owner_wallet_id"],
            heartbeat_at="2030-01-01T00:00:00+00:00",
            canonical_registry_objects=[consumer_object],
        )
    )
    service.upsert_registry_object(operator_a["object"])
    service.upsert_registry_object(operator_b["object"])
    service.upsert_registry_object(operator_a["owner_wallet_object"])
    service.upsert_registry_object(operator_b["owner_wallet_object"])
    service.upsert_registry_object(consumer_object)
    service.update_wallet_identity_governance_policy(
        authorized_voter_statuses=["ready"],
        minimum_eligible_voter_count=2,
    )

    with pytest.raises(ValueError, match="policy requires at least 2"):
        service.propose_wallet_identity_quorum_resolution(
            wallet_id="wallet-consumer",
            chosen_object_id=str(consumer_object["object_id"]),
            proposer_node_id="node-a",
            proposer_signature=_sign_quorum_proposal(
                operator_a,
                wallet_id="wallet-consumer",
                chosen_object_id=str(consumer_object["object_id"]),
                chosen_payload_hash=str(consumer_object["payload_hash"]),
                eligible_voter_node_ids=["node-a"],
                quorum_threshold=1,
                operator_note="insufficient ready voters",
            ),
            eligible_voter_node_ids=["node-a"],
            quorum_threshold=1,
            operator_note="insufficient ready voters",
        )


def test_registry_service_exports_and_imports_wallet_identity_quorum_objects(
) -> None:
    source = RegistryService()
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
    source.upsert_node(
        _node(
            "node-a",
            owner_wallet_id=operator_a["owner_wallet_id"],
            heartbeat_at="2030-01-01T00:00:00+00:00",
            canonical_registry_objects=[consumer_object],
        )
    )
    source.upsert_node(
        _node(
            "node-b",
            owner_wallet_id=operator_b["owner_wallet_id"],
            heartbeat_at="2030-01-01T00:00:00+00:00",
            canonical_registry_objects=[consumer_object],
        )
    )
    source.upsert_registry_object(
        consumer_object
    )
    source.upsert_registry_object(operator_a["object"])
    source.upsert_registry_object(operator_b["object"])
    source.upsert_registry_object(operator_a["owner_wallet_object"])
    source.upsert_registry_object(operator_b["owner_wallet_object"])
    source.propose_wallet_identity_quorum_resolution(
        wallet_id="wallet-consumer",
        chosen_object_id="sha256:wallet:consumer:a",
        proposer_node_id="node-a",
        proposer_signature=_sign_quorum_proposal(
            operator_a,
            wallet_id="wallet-consumer",
            chosen_object_id="sha256:wallet:consumer:a",
            chosen_payload_hash="sha256:wallet-payload:a",
            eligible_voter_node_ids=["node-a", "node-b"],
            quorum_threshold=2,
            operator_note="network quorum proposal",
        ),
        eligible_voter_node_ids=["node-a", "node-b"],
        quorum_threshold=2,
        operator_note="network quorum proposal",
    )
    exported = source.export_wallet_identity_sync_state()
    target = RegistryService()

    result = target.import_wallet_identity_sync_state(
        objects=[
            {
                "object_id": item["object_id"],
                "object_type": item["object_type"],
                "object_version": item["object_version"],
                "namespace": item["namespace"],
                "payload_hash": item["payload_hash"],
                "payload_encoding": item["payload_encoding"],
                "source_reference": item["source_reference"],
                "payload": item["payload"],
            }
            for item in exported["objects"]
        ],
        conflicts=exported["conflicts"],
    )

    assert result["imported_object_count"] >= 3
    proposals = target.list_wallet_identity_resolution_proposals()
    assert len(proposals) == 1
    assert proposals[0]["wallet_id"] == "wallet-consumer"
    assert proposals[0]["approvals"][0]["approver_node_id"] == "node-a"
    assert proposals[0]["eligible_voter_node_ids"] == ["node-a", "node-b"]


def test_registry_service_rejects_non_authoritative_wallet_identity_voter_set() -> None:
    service = RegistryService()
    operator_a = _operator_signing_identity("node-a")
    operator_b = _operator_signing_identity("node-b")
    consumer_object = _wallet_identity_object(
        "wallet-consumer",
        public_key="ed25519:" + "11" * 32,
        registration_nonce="nonce-a",
    )
    service.upsert_node(
        _node(
            "node-b",
            owner_wallet_id=operator_b["owner_wallet_id"],
            heartbeat_at="2030-01-01T00:00:00+00:00",
            canonical_registry_objects=[consumer_object],
        )
    )
    service.upsert_node(
        _node(
            "node-a",
            owner_wallet_id=operator_a["owner_wallet_id"],
            heartbeat_at="2030-01-01T00:00:00+00:00",
            canonical_registry_objects=[consumer_object],
        )
    )
    service.upsert_registry_object(operator_a["object"])
    service.upsert_registry_object(operator_b["object"])
    service.upsert_registry_object(operator_a["owner_wallet_object"])
    service.upsert_registry_object(operator_b["owner_wallet_object"])

    with pytest.raises(
        ValueError,
        match="Requested eligible voters do not match the authoritative wallet identity voter set",
    ):
        service.propose_wallet_identity_quorum_resolution(
            wallet_id="wallet-consumer",
            chosen_object_id=str(consumer_object["object_id"]),
            proposer_node_id="node-a",
            proposer_signature=_sign_quorum_proposal(
                operator_a,
                wallet_id="wallet-consumer",
                chosen_object_id=str(consumer_object["object_id"]),
                chosen_payload_hash=str(consumer_object["payload_hash"]),
                eligible_voter_node_ids=["node-a", "node-b", "node-c"],
                quorum_threshold=2,
                operator_note="oversized voter set",
            ),
            eligible_voter_node_ids=["node-a", "node-b", "node-c"],
            quorum_threshold=2,
            operator_note="oversized voter set",
        )


def test_registry_service_rejects_wallet_identity_quorum_signature_mismatch() -> None:
    service = RegistryService()
    operator_a = _operator_signing_identity("node-a")
    wrong_key = _operator_signing_identity("node-x")
    consumer_object = _wallet_identity_object(
        "wallet-consumer",
        public_key="ed25519:" + "11" * 32,
        registration_nonce="nonce-a",
    )
    service.upsert_node(
        _node(
            "node-a",
            owner_wallet_id=operator_a["owner_wallet_id"],
            heartbeat_at="2030-01-01T00:00:00+00:00",
            canonical_registry_objects=[consumer_object],
        )
    )
    service.upsert_registry_object(operator_a["object"])
    service.upsert_registry_object(operator_a["owner_wallet_object"])
    service.upsert_registry_object(consumer_object)

    with pytest.raises(ValueError, match="proposal signature is invalid"):
        service.propose_wallet_identity_quorum_resolution(
            wallet_id="wallet-consumer",
            chosen_object_id="sha256:wallet:wallet-consumer:11111111",
            proposer_node_id="node-a",
            proposer_signature=_sign_quorum_proposal(
                wrong_key,
                wallet_id="wallet-consumer",
                chosen_object_id="sha256:wallet:wallet-consumer:11111111",
                chosen_payload_hash="sha256:payload:wallet-consumer:11111111",
                eligible_voter_node_ids=["node-a"],
                quorum_threshold=1,
                operator_note="invalid signer",
            ),
            eligible_voter_node_ids=["node-a"],
            quorum_threshold=1,
            operator_note="invalid signer",
        )


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


def test_registry_finality_summary_requires_verified_exact_operation_evidence() -> None:
    evidence = ConsensusFinalityEvidence(
        operation_id="operation-final",
        chain_id="aidn-testnet-1",
        block_height=17,
        block_id="block-17",
        app_hash="app-hash-17",
        commit_hash="commit-hash-17",
        finalized_at="2030-01-01T00:00:00Z",
        verifier_id="test-cometbft-verifier",
    )

    class FinalitySource:
        def finality_evidence(self, operation_id: str):
            return evidence

    service = RegistryService(consensus_finality_source=FinalitySource())

    finalized = service._consensus_finality_summary("operation-final")
    mismatched = service._consensus_finality_summary("operation-other")

    assert finalized["consensus_finality"] is True
    assert finalized["finality_evidence"]["block_height"] == 17
    assert mismatched["consensus_finality"] is False
    assert mismatched["finality_evidence"] is None
