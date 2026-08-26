"""Opt-in smoke profile for an attached live Ollama service."""

import os

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from aidn_hypervisor.domain.models import NodeCapacity, TaskRequest
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.main import build_app
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.plugins.ollama import OllamaPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager, RuntimeHandle
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore
from aidn_hypervisor.settlement.models import SessionSettlementAcceptance
from aidn_hypervisor.settlement.signing import settlement_acceptance_signing_payload
from aidn_hypervisor.wallet_identity import (
    session_open_authorization_payload,
    wallet_identity_registration_payload,
)

OLLAMA_ENDPOINT = os.getenv("AIDN_OLLAMA_ENDPOINT")
OLLAMA_MODEL = os.getenv("AIDN_OLLAMA_MODEL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not OLLAMA_ENDPOINT or not OLLAMA_MODEL,
        reason="set AIDN_OLLAMA_ENDPOINT and AIDN_OLLAMA_MODEL to run live Ollama smoke",
    ),
]


def test_live_ollama_attach_discovery_and_execution() -> None:
    plugin = OllamaPlugin()
    plugins = PluginRegistry()
    plugins.register(plugin)
    inventory = ProviderInventoryService(
        plugins=plugins,
        store=InMemoryProviderInventoryStore(),
    )
    provider = inventory.attach_provider_instance(
        plugin_id="ollama",
        display_name="Live Ollama",
        configuration={"endpoint": OLLAMA_ENDPOINT},
    )
    deployments = inventory.discover_models(provider.provider_instance_id)
    deployment = next(
        item
        for item in deployments
        if item.provider_model_reference in {OLLAMA_MODEL, f"{OLLAMA_MODEL}:latest"}
    )
    runtime = RuntimeHandle(
        runtime_id="ollama-live",
        command=["ollama", "serve"],
        status="running",
        bundle_id="ollama-live-bundle",
        metadata={"endpoint": OLLAMA_ENDPOINT, "model_id": deployment.provider_model_reference},
    )

    result = plugin.invoke(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "Reply with one word."}),
        runtime,
    )

    assert provider.connection_mode == "attached"
    assert plugin.health_check(runtime) is True
    assert result["ok"] is True
    assert result["output_text"]
    assert result["usage"]["measurement_kind"] == "exact"
    assert result["usage"]["input_tokens"] > 0
    assert result["usage"]["output_tokens"] > 0


def test_live_ollama_public_paid_session_settles_after_restart(tmp_path) -> None:
    plugin = OllamaPlugin()
    plugins = PluginRegistry()
    plugins.register(plugin)
    inventory = ProviderInventoryService(
        plugins=plugins,
        store=InMemoryProviderInventoryStore(),
    )
    provider = inventory.attach_provider_instance(
        plugin_id="ollama",
        display_name="Live Ollama paid Session",
        configuration={"endpoint": OLLAMA_ENDPOINT},
    )
    deployment = next(
        item
        for item in inventory.discover_models(provider.provider_instance_id)
        if item.provider_model_reference in {OLLAMA_MODEL, f"{OLLAMA_MODEL}:latest"}
    )
    binding = inventory.create_runtime_binding(
        model_deployment_id=deployment.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="ollama-live-paid-session-capability",
    )
    state_store = FileStateStore(tmp_path / "ollama-live-paid-session-state.json")
    bundle = inventory.bundle_config_for_runtime_binding(binding.runtime_binding_id)
    hypervisor = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=2048)),
        bundles=[bundle],
        plugins=plugins,
        runtimes=ProviderProcessManager(),
        provider_inventory=inventory,
        state_store=state_store,
    )
    hypervisor.configure_owner_wallet(mode="create", label="Live Ollama Primary Wallet")
    owner_wallet_id = hypervisor.owner_wallet_state()["wallet_id"]
    endpoint_service = EndpointService(EndpointStore(state_store))
    endpoint_publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(state_store),
        endpoint_service=endpoint_service,
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            endpoint_publication_service=endpoint_publication_service,
            session_service=SessionService(SessionStore(state_store)),
        )
    )
    created = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": owner_wallet_id,
            "runtime_binding_id": binding.runtime_binding_id,
            "bundle_id": binding.compatibility_bundle_id,
            "bundle_hash": inventory.bundle_hash_for_runtime_binding(
                binding.runtime_binding_id
            ),
            "display_name": "Live Ollama Session",
            "model_class": "llm.chat",
            "capabilities": ["llm.chat"],
            "publication": {
                "visibility": "public",
                "discoverable": True,
                "accepts_external_requests": True,
            },
            "pricing": {"rate_card": {"components": [{"component_id": "base-request", "dimension": "request_count", "kind": "fixed", "unit_price_q_atoms": 900, "accounting_mode": "fixed_price"}]}},
        },
    )
    assert created.status_code == 201, created.text
    endpoint = created.json()["data"]["endpoint"]
    endpoint_id = endpoint["endpoint_id"]
    hypervisor.credit_wallet_q_atoms(wallet_id="ollama-live-consumer", amount_q_atoms=1000)
    consumer_key = Ed25519PrivateKey.generate()
    owner_key = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(hypervisor.owner_wallet_private_key().removeprefix("ed25519:"))
    )
    for wallet_id, key, nonce in [
        ("ollama-live-consumer", consumer_key, "ollama-live-consumer-registration"),
        (owner_wallet_id, owner_key, "ollama-live-operator-registration"),
    ]:
        public_key = f"ed25519:{key.public_key().public_bytes_raw().hex()}"
        signature = key.sign(
            wallet_identity_registration_payload(
                wallet_id=wallet_id,
                public_key=public_key,
                registration_nonce=nonce,
            )
        ).hex()
        registered = client.post(
            "/wallets/identity",
            json={
                "wallet_id": wallet_id,
                "public_key": public_key,
                "registration_nonce": nonce,
                "signature": f"ed25519:{signature}",
            },
        )
        assert registered.status_code == 201, registered.text
    published = client.post(f"/api/v1/endpoints/{endpoint_id}/publish-configuration")
    assert published.status_code == 200, published.text

    authorization_nonce = "ollama-live-public-session"
    expires_at = "2030-01-01T00:00:00+00:00"
    authorization_signature = consumer_key.sign(
        session_open_authorization_payload(
            wallet_id="ollama-live-consumer",
            endpoint_id=endpoint_id,
            endpoint_configuration_hash=endpoint["configuration_hash"],
            deposit_q_atoms=1000,
            fixed_price_q_atoms=900,
            network_fee_reserve_q_atoms=100,
            nonce=authorization_nonce,
            expires_at=expires_at,
        )
    ).hex()
    opened = client.post(
        f"/api/v1/endpoints/{endpoint_id}/public-mvp-sessions",
        json={
            "client_wallet": "ollama-live-consumer",
            "deposit_q_atoms": 1000,
            "fixed_price_q_atoms": 900,
            "network_fee_reserve_q_atoms": 100,
            "consumer_authorization": {
                "nonce": authorization_nonce,
                "expires_at": expires_at,
                "signature": f"ed25519:{authorization_signature}",
            },
        },
    )
    assert opened.status_code == 201, opened.text
    session = opened.json()["data"]["session"]
    task = client.post(
        "/tasks",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "Reply with one short word."},
            "constraints": {"endpoint_id": endpoint_id, "session_id": session["session_id"]},
        },
    )
    assert task.status_code == 202, task.text
    request_id = task.json()["task_id"]
    assert hypervisor.task_result(request_id)["output_text"]

    restored_hypervisor = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=2048)),
        bundles=[bundle],
        plugins=plugins,
        runtimes=ProviderProcessManager(),
        state_store=state_store,
    )
    restored_hypervisor.restore_state(state_store.load())
    restored_endpoint_service = EndpointService(EndpointStore(state_store))
    restored_client = TestClient(
        build_app(
            service=restored_hypervisor,
            endpoint_service=restored_endpoint_service,
            endpoint_publication_service=EndpointPublicationService(
                store=EndpointPublicationStore(state_store),
                endpoint_service=restored_endpoint_service,
            ),
            session_service=SessionService(SessionStore(state_store)),
        )
    )
    accepted_at = "2026-07-21T12:00:00+00:00"
    preview = restored_client.post(
        f"/api/v1/endpoints/{endpoint_id}/mvp-sessions/{session['session_id']}/settlement-preview",
        json={"request_id": request_id, "accepted_at": accepted_at},
    )
    assert preview.status_code == 200, preview.text
    unsigned = SessionSettlementAcceptance(
        **preview.json()["data"]["acceptance_payload"],
        consumer_signature="ed25519:" + "00" * 64,
    )
    settlement_signature = consumer_key.sign(
        settlement_acceptance_signing_payload(unsigned)
    ).hex()
    response = restored_client.post(
        f"/api/v1/endpoints/{endpoint_id}/mvp-sessions/{session['session_id']}/finalize",
        json={
            "request_id": request_id,
            "accepted_at": accepted_at,
            "consumer_signature": f"ed25519:{settlement_signature}",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["funding"]["funding_state"] == "RELEASED"
    assert restored_hypervisor.wallet_q_atom_balance(owner_wallet_id) == 900
    assert restored_hypervisor.wallet_q_atom_balance("ollama-live-consumer") == 100
