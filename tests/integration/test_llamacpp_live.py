"""Opt-in smoke profile for a real OpenAI-compatible llama.cpp server."""

import json
import os
from datetime import UTC, datetime, timedelta
from urllib import request

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from aidn_hypervisor.accounting.models import (
    AccountingContract,
    AccountingUnitContract,
    RuntimeUsageProfile,
    RuntimeUsageProfileDimension,
)
from aidn_hypervisor.dispatcher.models import DispatcherRoute
from aidn_hypervisor.domain.models import NodeCapacity
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.models import CreateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.main import build_app
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.providers.models import RuntimeBinding
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.runtime_protocol import (
    ApprovedRuntimeDispatcher,
    LlamaCppOpenAIAdapter,
    RuntimeExecuteRequest,
    RuntimeHello,
    RuntimeHelloComplete,
    RuntimeProtocolConformanceHarness,
    RuntimeProtocolService,
    canonical_hash,
)
from aidn_hypervisor.runtime_protocol.store import RuntimeProtocolStore
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

pytestmark = pytest.mark.integration


def _live_configuration() -> tuple[str, str]:
    if os.environ.get("AIDN_LLAMACPP_LIVE") != "1":
        pytest.skip("set AIDN_LLAMACPP_LIVE=1 to run against a real llama.cpp server")
    endpoint = os.environ.get("AIDN_LLAMACPP_ENDPOINT", "").rstrip("/")
    model = os.environ.get("AIDN_LLAMACPP_MODEL", "")
    if not endpoint or not model:
        pytest.skip("set AIDN_LLAMACPP_ENDPOINT and AIDN_LLAMACPP_MODEL")
    return endpoint, model


def _get_json(url: str) -> dict:
    with request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    http_request = request.Request(
        url=url,
        method="POST",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(http_request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def test_llamacpp_live_openai_completion_profile() -> None:
    endpoint, model = _live_configuration()
    harness = RuntimeProtocolConformanceHarness()

    health = harness.assert_success("llamacpp.health", lambda: _get_json(f"{endpoint}/health"))
    models = harness.assert_success(
        "llamacpp.model_discovery", lambda: _get_json(f"{endpoint}/v1/models")
    )
    completion = harness.assert_success(
        "llamacpp.completion",
        lambda: _post_json(
            f"{endpoint}/v1/completions",
            {
                "model": model,
                "prompt": "Reply with one short word.",
                "max_tokens": 8,
                "temperature": 0,
            },
        ),
    )

    assert health["status"] == "ok"
    assert any(item["id"] == model for item in models["data"])
    assert completion["model"] == model
    assert completion["choices"]
    assert completion["usage"]["prompt_tokens"] > 0
    assert completion["usage"]["completion_tokens"] > 0
    assert completion["usage"]["total_tokens"] == (
        completion["usage"]["prompt_tokens"]
        + completion["usage"]["completion_tokens"]
    )
    assert completion["timings"]["predicted_n"] == completion["usage"]["completion_tokens"]
    assert harness.report().passed is True


def test_llamacpp_live_operator_attach_discover_and_bind() -> None:
    endpoint, model = _live_configuration()
    plugins = PluginRegistry()
    plugins.register(LlamaCppPlugin())
    service = ProviderInventoryService(
        plugins=plugins,
        store=InMemoryProviderInventoryStore(),
    )

    instance = service.attach_provider_instance(
        plugin_id="llama.cpp",
        display_name="Live llama.cpp",
        configuration={"endpoint": endpoint},
    )
    deployments = service.discover_models(instance.provider_instance_id)
    deployment = next(item for item in deployments if item.provider_model_reference == model)
    binding = service.create_runtime_binding(
        model_deployment_id=deployment.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="live-capability-definition",
    )
    bundle = service.bundle_config_for_runtime_binding(binding.runtime_binding_id)

    assert instance.connection_mode == "attached"
    assert instance.configuration["endpoint"] == endpoint
    assert binding.adapter_id == "llamacpp-openai"
    assert binding.adapter_version == "llamacpp-openai.v1"
    assert binding.supported_features == ["streaming", "cancellation"]
    assert bundle.endpoint == endpoint
    assert bundle.model_id == model

    endpoint_payload = {
        "owner_wallet": "live-operator-wallet",
        "model_class": binding.capability_id,
        "capabilities": [binding.capability_id],
        "runtime": {"streaming": True, "max_tokens": 64, "timeout": 90},
        "publication": {
            "visibility": "shared",
            "shared_with_wallet_ids": ["live-consumer-wallet"],
            "discoverable": True,
            "accepts_external_requests": True,
        },
        "pricing": {"rate_card": {"components": [{
            "component_id": "base-request", "dimension": "request_count",
            "kind": "fixed", "unit_price_q_atoms": 1_000_000,
            "accounting_mode": "fixed_price",
        }]}},
        "validation": {
            "enabled": False,
            "model_class_supported": True,
            "verification_status": "active",
        },
    }
    admission = service.runtime_binding_endpoint_admission(
        binding.runtime_binding_id,
        endpoint_payload=endpoint_payload,
    )
    assert admission["ready"] is True

    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            runtime_binding_id=binding.runtime_binding_id,
            bundle_id=bundle.bundle_id,
            bundle_hash=service.bundle_hash_for_runtime_binding(binding.runtime_binding_id),
            display_name=f"Live {model}",
            **endpoint_payload,
        )
    )
    publication = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    ).publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="live-operator-wallet",
        node_id="live-node",
        wallet_private_key="live-test-key",
    )
    assert publication.endpoint_id == created.endpoint.endpoint_id
    assert publication.status == "published"
    assert created.endpoint.runtime_binding_id == binding.runtime_binding_id
    assert publication.execution["runtime_binding_id"] == binding.runtime_binding_id


def test_llamacpp_live_approved_binding_dispatches_session_request() -> None:
    endpoint, model = _live_configuration()
    plugins = PluginRegistry()
    plugins.register(LlamaCppPlugin())
    inventory = ProviderInventoryService(
        plugins=plugins,
        store=InMemoryProviderInventoryStore(),
    )
    provider = inventory.attach_provider_instance(
        plugin_id="llama.cpp",
        display_name="Live llama.cpp",
        configuration={"endpoint": endpoint},
    )
    deployment = next(
        item
        for item in inventory.discover_models(provider.provider_instance_id)
        if item.provider_model_reference == model
    )
    binding = inventory.create_runtime_binding(
        model_deployment_id=deployment.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="live-approved-capability",
    )
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="live-operator-wallet",
            runtime_binding_id=binding.runtime_binding_id,
            bundle_id=binding.compatibility_bundle_id,
            bundle_hash=inventory.bundle_hash_for_runtime_binding(
                binding.runtime_binding_id
            ),
            display_name=f"Live approved {model}",
            model_class="llm.chat",
            capabilities=["llm.chat"],
            pricing={"rate_card": {"components": [{"component_id": "base-request", "dimension": "request_count", "kind": "fixed", "unit_price_q_atoms": 1_000_000, "accounting_mode": "fixed_price"}]}},
        )
    )
    contract = AccountingContract(
        accounting_mode="fixed_price",
        contract_version="live-approved-contract",
        capability_id="llm.chat",
        endpoint_id=created.endpoint.endpoint_id,
        pricing_version="live-approved-pricing",
        billable_units=[
            AccountingUnitContract(
                unit="request_fee",
                mode="fixed_price",
                price=1.0,
                measurement_source="endpoint_policy",
                verification_method="fixed_contract",
            )
        ],
        checkpoint_policy="per_request",
    )
    sessions = SessionService(SessionStore())
    session = sessions.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="live-consumer-wallet",
        provider_wallet="live-operator-wallet",
        node_id="live-node",
        deposit_q=2.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
        accounting_contract=contract.model_dump(mode="json"),
        endpoint_configuration_hash=created.endpoint.configuration_hash,
    ).session
    session = session.model_copy(update={"request_charge_ceiling_q_atoms": 1_000_000})
    sessions.store.save_session(session)
    result = ApprovedRuntimeDispatcher(
        provider_inventory=inventory,
        runtime_protocol_store=RuntimeProtocolStore(),
        hypervisor_id="live-node",
    ).execute(
        endpoint=created.endpoint,
        session=session,
        request_id="live-approved-request",
        request_payload={"prompt": "Reply with one short word."},
    )

    assert result.terminal_state == "COMPLETED"
    assert result.result_payload is not None
    assert result.result_payload["text"]


def test_llamacpp_live_fixed_price_session_executes_and_settles_after_restart(tmp_path) -> None:
    endpoint, model = _live_configuration()
    plugins = PluginRegistry()
    plugins.register(LlamaCppPlugin())
    inventory = ProviderInventoryService(
        plugins=plugins,
        store=InMemoryProviderInventoryStore(),
    )
    provider = inventory.attach_provider_instance(
        plugin_id="llama.cpp",
        display_name="Live llama.cpp paid Session",
        configuration={"endpoint": endpoint},
    )
    deployment = next(
        item
        for item in inventory.discover_models(provider.provider_instance_id)
        if item.provider_model_reference == model
    )
    binding = inventory.create_runtime_binding(
        model_deployment_id=deployment.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="live-paid-session-capability",
    )
    state_store = FileStateStore(tmp_path / "live-paid-session-state.json")
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
    hypervisor.configure_owner_wallet(mode="create", label="Live Primary Wallet")
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
            "display_name": "Live llama.cpp Session",
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
    assert created.status_code == 201
    created_endpoint = created.json()["data"]["endpoint"]
    endpoint_id = created_endpoint["endpoint_id"]
    hypervisor.credit_wallet_q_atoms(wallet_id="live-consumer-wallet", amount_q_atoms=1000)
    consumer_key = Ed25519PrivateKey.generate()
    owner_key = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(hypervisor.owner_wallet_private_key().removeprefix("ed25519:"))
    )
    for wallet_id, key, nonce in [
        ("live-consumer-wallet", consumer_key, "live-consumer-registration"),
        (owner_wallet_id, owner_key, "live-operator-registration"),
    ]:
        public_key = f"ed25519:{key.public_key().public_bytes_raw().hex()}"
        signature = key.sign(wallet_identity_registration_payload(
            wallet_id=wallet_id, public_key=public_key, registration_nonce=nonce
        )).hex()
        registered = client.post("/wallets/identity", json={
            "wallet_id": wallet_id, "public_key": public_key,
            "registration_nonce": nonce, "signature": f"ed25519:{signature}",
        })
        assert registered.status_code == 201, registered.text
    published = client.post(f"/api/v1/endpoints/{endpoint_id}/publish-configuration")
    assert published.status_code == 200, published.text
    publication = published.json()["data"]["publication"]
    assert publication is not None
    assert publication["endpoint_id"] == endpoint_id
    assert publication["owner_wallet"] == owner_wallet_id
    assert publication["status"] == "published"
    proof = client.get(f"/api/v1/endpoints/{endpoint_id}/proof")
    assert proof.status_code == 200, proof.text
    assert proof.json()["data"]["proof"]["publication_sync_status"] == "in_sync"
    expires_at = "2030-01-01T00:00:00+00:00"
    authorization_nonce = "live-public-session"
    authorization_signature = consumer_key.sign(session_open_authorization_payload(
        wallet_id="live-consumer-wallet", endpoint_id=endpoint_id,
        endpoint_configuration_hash=created_endpoint["configuration_hash"],
        deposit_q_atoms=1000, fixed_price_q_atoms=900, network_fee_reserve_q_atoms=100,
        nonce=authorization_nonce, expires_at=expires_at,
    )).hex()

    opened = client.post(
        f"/api/v1/endpoints/{endpoint_id}/public-mvp-sessions",
        json={
            "client_wallet": "live-consumer-wallet",
            "deposit_q_atoms": 1000,
            "fixed_price_q_atoms": 900,
            "network_fee_reserve_q_atoms": 100,
            "consumer_authorization": {"nonce": authorization_nonce, "expires_at": expires_at,
                                       "signature": f"ed25519:{authorization_signature}"},
        },
    )
    assert opened.status_code == 201, opened.text
    session = opened.json()["data"]["session"]
    task = client.post("/tasks", json={"task_type": "llm_text.generate",
        "payload": {"prompt": "Reply with one short word."},
        "constraints": {"endpoint_id": endpoint_id, "session_id": session["session_id"]}})
    assert task.status_code == 202, task.text
    request_id = task.json()["task_id"]
    assert hypervisor.task_result(request_id)["output_text"]

    # A restarted Hypervisor must settle the persisted terminal evidence without
    # contacting the provider or recreating the accepted Request.
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
    unsigned = SessionSettlementAcceptance(**preview.json()["data"]["acceptance_payload"],
        consumer_signature="ed25519:" + "00" * 64)
    settlement_signature = consumer_key.sign(settlement_acceptance_signing_payload(unsigned)).hex()
    response = restored_client.post(
        f"/api/v1/endpoints/{endpoint_id}/mvp-sessions/{session['session_id']}/finalize",
        json={"request_id": request_id, "accepted_at": accepted_at,
              "consumer_signature": f"ed25519:{settlement_signature}"},
    )
    body = response.json()["data"]

    assert response.status_code == 200, response.text
    assert restored_hypervisor.task_result(request_id)["output_text"]
    assert body["funding"]["funding_state"] == "RELEASED"
    assert restored_hypervisor.wallet_q_atom_balance(owner_wallet_id) == 900
    assert restored_hypervisor.wallet_q_atom_balance("live-consumer-wallet") == 100


def test_llamacpp_live_adapter_records_rfc0054_terminal_evidence() -> None:
    endpoint, model = _live_configuration()
    profile = RuntimeUsageProfile(
        runtime_id="live-runtime",
        runtime_generation=1,
        runtime_configuration_hash="live-config",
        adapter_version="llamacpp-openai.v1",
        dimensions=[
            RuntimeUsageProfileDimension(
                dimension_id="input_tokens",
                unit="token",
                expected_availability="AVAILABLE",
                authority="AUTHORITATIVE_PROVIDER",
                billing_eligible=True,
            ),
            RuntimeUsageProfileDimension(
                dimension_id="output_tokens",
                unit="token",
                expected_availability="AVAILABLE",
                authority="AUTHORITATIVE_PROVIDER",
                billing_eligible=False,
            ),
            RuntimeUsageProfileDimension(
                dimension_id="output_bytes",
                unit="byte",
                expected_availability="AVAILABLE",
                authority="OBSERVABLE_LOCAL",
                billing_eligible=False,
            ),
        ],
    )
    binding = RuntimeBinding(
        runtime_binding_id="live-binding",
        runtime_id="live-runtime",
        runtime_generation=1,
        implementation_class="EXTERNAL_DIRECT",
        provider_instance_id="live-provider",
        model_deployment_id="live-model",
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="live-capability-definition",
        plugin_id="llama.cpp",
        plugin_version="live",
        adapter_id="llamacpp-openai",
        adapter_version="llamacpp-openai.v1",
        supported_features=["streaming"],
        supported_accounting_modes=["provider_metered"],
        usage_reporting_profile_hash=profile.profile_hash,
        dispatcher_route_scope={"channel_class": "RUNTIME", "runtime_id": "live-runtime"},
        compatibility_bundle_id="live-bundle",
        status="ready",
    )
    profile = profile.model_copy(
        update={"runtime_configuration_hash": binding.runtime_configuration_hash}
    )
    contract = AccountingContract(
        contract_version="live-contract",
        accounting_mode="provider_metered",
        capability_id="llm.chat",
        endpoint_id="live-endpoint",
        pricing_version="live-pricing",
        billable_units=[
            AccountingUnitContract(
                unit="input_tokens",
                mode="provider_metered",
                price=0,
                measurement_source="llamacpp-v1-completions",
                verification_method="provider_report",
                required_authority="AUTHORITATIVE_PROVIDER",
            )
        ],
        checkpoint_policy="per_request",
    )
    route = DispatcherRoute(
        destination_type="RUNTIME",
        destination_id=binding.runtime_id,
        route_type="REMOTE_RUNTIME",
        route_generation=1,
        runtime_generation=binding.runtime_generation,
        allowed_source_types={"HYPERVISOR"},
        allowed_channel_classes={"RUNTIME"},
        allowed_message_types={"RUNTIME_EXECUTE"},
        runtime_binding_hash=binding.binding_hash(),
        created_at=datetime.now(UTC).isoformat(),
    )
    protocol = RuntimeProtocolService(
        hypervisor_id="live-hypervisor",
        network_revision="live-revision",
        binding_resolver=lambda _: binding,
        route_resolver=lambda _: route,
        runtime_authenticator=lambda item: getattr(item, "runtime_signature", None) == "live-signed",
        hypervisor_signer=lambda _: "hypervisor-signed",
        request_authorizer=lambda _: True,
        accounting_contract_resolver=lambda _: contract,
        usage_profile_resolver=lambda _: profile,
    )
    hello = RuntimeHello(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        instance_id="live-instance",
        runtime_configuration_hash=binding.runtime_configuration_hash,
        capability_id=binding.capability_id,
        supported_capability_versions=[binding.capability_version],
        supported_definition_hashes=[binding.capability_definition_hash],
        supported_runtime_protocol_versions=["1.0"],
        adapter_id=binding.adapter_id,
        adapter_version=binding.adapter_version,
        runtime_nonce="live-nonce",
        runtime_challenge="live-challenge",
        runtime_signature="live-signed",
    )
    hello_response = protocol.begin_handshake(hello)
    connection = protocol.complete_handshake(
        RuntimeHelloComplete(
            handshake_id=hello_response.handshake_id,
            runtime_id=binding.runtime_id,
            runtime_generation=binding.runtime_generation,
            route_generation=route.route_generation,
            hypervisor_challenge_response=protocol.challenge_response(
                hello_response.hypervisor_challenge
            ),
            current_operational_state="READY",
            runtime_signature="live-signed",
        )
    )
    payload = {"prompt": "Reply with one short word."}
    execution_request = RuntimeExecuteRequest(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=route.route_generation,
        endpoint_id="live-endpoint",
        endpoint_configuration_hash="live-endpoint-config",
        session_id="live-session",
        session_contract_hash="live-session-contract",
        request_id="live-request-1",
        capability_id=binding.capability_id,
        capability_version=binding.capability_version,
        capability_definition_hash=binding.capability_definition_hash,
        request_payload_hash=canonical_hash(payload),
        request_payload=payload,
        request_charge_ceiling=1,
        accounting_contract_hash=contract.payload_hash,
        idempotency_key="live-request-1",
        request_deadline=(datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
    )

    adapter = LlamaCppOpenAIAdapter(
        endpoint=endpoint,
        model=model,
        runtime_signature="live-signed",
    )
    result = adapter.execute(protocol, connection.runtime_connection_id, execution_request)

    assert result.terminal_state == "COMPLETED"
    assert result.result_payload is not None
    assert protocol.store.requests[execution_request.request_id].request_state == "COMPLETED"
    report = protocol.store.usage_reports[result.final_usage_report_id]
    assert report.terminal is True
    assert {item.dimension_id for item in report.dimensions} == {"input_tokens", "output_tokens"}
    assert adapter.execute(protocol, connection.runtime_connection_id, execution_request) == result

    recovery_state = adapter.recovery_state(
        protocol,
        execution_request,
        instance_id="live-restarted-instance",
    )
    recovery_plan = protocol.build_recovery_plan(
        connection.runtime_connection_id,
        recovery_state,
    )
    recovery = adapter.apply_recovery_plan(
        protocol,
        connection.runtime_connection_id,
        recovery_plan,
    )
    assert recovery.request_results == {
        execution_request.request_id: "REDELIVERED_FINAL_RESULT"
    }
    assert recovery.remaining_conflicts == []

    stream_request = execution_request.model_copy(
        update={
            "request_id": "live-stream-request-1",
            "idempotency_key": "live-stream-request-1",
            "required_features": ["streaming"],
        }
    )
    stream_result = adapter.execute_streaming(
        protocol,
        connection.runtime_connection_id,
        stream_request,
    )
    assert stream_result.terminal_state == "COMPLETED"
    assert len(stream_result.stream_roots) == 1
    stream_id = f"llamacpp-stream-{stream_request.request_id}"
    assert protocol.store.stream_closes[stream_id].final_content_root == stream_result.stream_roots[0]
    stream_report = protocol.store.usage_reports[stream_result.final_usage_report_id]
    assert [(item.dimension_id, item.authority) for item in stream_report.dimensions] == [
        ("output_bytes", "OBSERVABLE_LOCAL")
    ]
