from aidn_hypervisor.accounting.models import AccountingContract, AccountingUnitContract
from aidn_hypervisor.domain.models import NodeCapacity, TaskRequest
from aidn_hypervisor.endpoints.models import CreateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.plugins.whisper import WhisperPlugin
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.runtime_protocol.adapters.llamacpp import LlamaCppOpenAIAdapter
from aidn_hypervisor.runtime_protocol.approved_dispatch import ApprovedRuntimeDispatcher
from aidn_hypervisor.runtime_protocol.store import RuntimeProtocolStore
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore


def test_approved_llamacpp_binding_executes_through_runtime_protocol(monkeypatch) -> None:
    plugins = PluginRegistry()
    plugin = LlamaCppPlugin()
    monkeypatch.setattr(
        plugin,
        "_request_json",
        lambda *_: {"data": [{"id": "qwen3.6"}]},
    )
    plugins.register(plugin)
    inventory = ProviderInventoryService(
        plugins=plugins,
        store=InMemoryProviderInventoryStore(),
    )
    provider = inventory.attach_provider_instance(
        plugin_id="llama.cpp",
        display_name="Remote llama.cpp",
        configuration={"endpoint": "http://llama.example"},
    )
    deployment = inventory.discover_models(provider.provider_instance_id)[0]
    binding = inventory.create_runtime_binding(
        model_deployment_id=deployment.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="capability-hash",
    )
    endpoint = EndpointService(EndpointStore()).create_endpoint(
        CreateEndpointCommand(
            owner_wallet="operator-wallet",
            runtime_binding_id=binding.runtime_binding_id,
            bundle_id=binding.compatibility_bundle_id,
            bundle_hash="bundle-hash",
            display_name="Qwen",
            model_class="llm.chat",
            capabilities=["llm.chat"],
            pricing={"billing_unit": "request", "fixed_price": 1.0},
        )
    ).endpoint
    contract = AccountingContract(
        accounting_mode="fixed_price",
        contract_version="contract.v1",
        capability_id="llm.chat",
        endpoint_id=endpoint.endpoint_id,
        pricing_version="pricing.v1",
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
        endpoint_id=endpoint.endpoint_id,
        client_wallet="consumer-wallet",
        provider_wallet="operator-wallet",
        node_id="node-1",
        deposit_q=2.0,
        session_policy=endpoint.session.model_dump(mode="json"),
        accounting_contract=contract.model_dump(mode="json"),
        endpoint_configuration_hash=endpoint.configuration_hash,
    ).session
    session = session.model_copy(update={"request_charge_ceiling_q_atoms": 1_000_000})
    sessions.store.save_session(session)

    monkeypatch.setattr(
        LlamaCppOpenAIAdapter,
        "_completion",
        lambda self, _: {
            "model": "qwen3.6",
            "choices": [{"text": "ok", "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        },
    )
    store = RuntimeProtocolStore()
    result = ApprovedRuntimeDispatcher(
        provider_inventory=inventory,
        runtime_protocol_store=store,
        hypervisor_id="node-1",
    ).execute(
        endpoint=endpoint,
        session=session,
        request_id="request-1",
        request_payload={"prompt": "hello"},
    )

    assert result.terminal_state == "COMPLETED"
    assert result.result_payload["text"] == "ok"
    record = store.requests["request-1"]
    assert record.request.runtime_id == binding.runtime_id
    assert record.request.endpoint_configuration_hash == endpoint.configuration_hash
    report = store.usage_reports[result.final_usage_report_id]
    assert report.terminal is True
    assert [item.dimension_id for item in report.dimensions] == [
        "input_tokens",
        "output_tokens",
    ]

    hypervisor = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=1.0, ram_mb=1024)),
        bundles=[inventory.bundle_config_for_runtime_binding(binding.runtime_binding_id)],
        plugins=plugins,
        provider_inventory=inventory,
    )
    hypervisor.endpoint_service = EndpointService(EndpointStore())
    created_for_queue = hypervisor.endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="operator-wallet",
            runtime_binding_id=binding.runtime_binding_id,
            bundle_id=binding.compatibility_bundle_id,
            bundle_hash="bundle-hash-queue",
            display_name="Queued Qwen",
            model_class="llm.chat",
            capabilities=["llm.chat"],
            pricing={"billing_unit": "request", "fixed_price": 1.0},
        )
    ).endpoint
    queue_contract_payload = contract.model_dump(mode="json")
    for field in ("payload_hash", "registry_object_id", "accounting_contract_id"):
        queue_contract_payload.pop(field, None)
    queue_contract_payload["endpoint_id"] = created_for_queue.endpoint_id
    queue_contract = AccountingContract.model_validate(queue_contract_payload)
    hypervisor.session_service = SessionService(SessionStore())
    queued_session = hypervisor.session_service.open_session(
        endpoint_id=created_for_queue.endpoint_id,
        client_wallet="consumer-wallet",
        provider_wallet="operator-wallet",
        node_id="node-1",
        deposit_q=2.0,
        session_policy=created_for_queue.session.model_dump(mode="json"),
        accounting_contract=queue_contract.model_dump(mode="json"),
        endpoint_configuration_hash=created_for_queue.configuration_hash,
    ).session
    hypervisor.session_service.store.save_session(
        queued_session.model_copy(update={"request_charge_ceiling_q_atoms": 1_000_000})
    )

    task = hypervisor.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={
                "endpoint_id": created_for_queue.endpoint_id,
                "session_id": queued_session.session_id,
            },
        )
    )

    assert hypervisor.queue.get(task.task_id).status == "completed"
    assert hypervisor.task_result(task.task_id)["output_text"] == "ok"
    runtime_record = hypervisor.runtime_protocol_store.requests[task.task_id]
    assert runtime_record.request.runtime_id == binding.runtime_id
    assert runtime_record.request.session_id == queued_session.session_id
    persisted_session = hypervisor.session_service.store.get_session(
        queued_session.session_id
    )
    assert len(persisted_session.runtime_terminal_evidence) == 1
    terminal = persisted_session.runtime_terminal_evidence[0]
    assert terminal.request_id == task.task_id
    assert terminal.runtime_binding_id == binding.runtime_binding_id
    assert terminal.result_hash == hypervisor.runtime_protocol_store.results[
        task.task_id
    ].result_hash


def test_approved_whisper_binding_executes_native_audio_through_runtime_protocol(
    monkeypatch,
) -> None:
    plugins = PluginRegistry()
    plugin = WhisperPlugin()
    plugins.register(plugin)
    inventory = ProviderInventoryService(
        plugins=plugins,
        store=InMemoryProviderInventoryStore(),
    )
    provider = inventory.attach_provider_instance(
        plugin_id="whisper",
        display_name="Local Whisper",
        configuration={
            "display_name": "Local Whisper",
            "endpoint": "http://whisper.example",
            "model_id": "small",
            "api_format": "whisper_asr_webservice",
        },
    )
    deployment = inventory.discover_models(provider.provider_instance_id)[0]
    binding = inventory.create_runtime_binding(
        model_deployment_id=deployment.model_deployment_id,
        capability_id="speech_to_text",
        capability_version="1.0.0",
        capability_definition_hash="capability:speech_to_text:1.0.0",
    )

    assert binding.adapter_id == "whisper-http"
    assert binding.adapter_version == "whisper-http.v1"
    assert binding.supported_modalities == ["audio", "text"]
    assert binding.usage_reporting_profile_hash

    endpoint = EndpointService(EndpointStore()).create_endpoint(
        CreateEndpointCommand(
            owner_wallet="operator-wallet",
            runtime_binding_id=binding.runtime_binding_id,
            bundle_id=binding.compatibility_bundle_id,
            bundle_hash="bundle-hash",
            display_name="Whisper",
            model_class="speech_to_text",
            capabilities=["speech_to_text"],
            pricing={"billing_unit": "request", "fixed_price": 1.0},
        )
    ).endpoint
    contract = AccountingContract(
        accounting_mode="fixed_price",
        contract_version="contract.v1",
        capability_id="speech_to_text",
        endpoint_id=endpoint.endpoint_id,
        pricing_version="pricing.v1",
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
        endpoint_id=endpoint.endpoint_id,
        client_wallet="consumer-wallet",
        provider_wallet="operator-wallet",
        node_id="node-1",
        deposit_q=2.0,
        session_policy=endpoint.session.model_dump(mode="json"),
        accounting_contract=contract.model_dump(mode="json"),
        endpoint_configuration_hash=endpoint.configuration_hash,
    ).session
    session = session.model_copy(update={"request_charge_ceiling_q_atoms": 1_000_000})
    sessions.store.save_session(session)

    monkeypatch.setattr(
        WhisperPlugin,
        "_invoke_native_asr",
        lambda self, *, endpoint, audio_ref: {
            "text": "hello native",
            "language": "en",
        },
    )
    runtime_store = RuntimeProtocolStore()
    result = ApprovedRuntimeDispatcher(
        provider_inventory=inventory,
        runtime_protocol_store=runtime_store,
        hypervisor_id="node-1",
    ).execute(
        endpoint=endpoint,
        session=session,
        request_id="whisper-request-1",
        request_payload={"audio_ref": "data:audio/wav;base64,YQ=="},
    )

    assert result.terminal_state == "COMPLETED"
    assert result.result_payload["text"] == "hello native"
    report = runtime_store.usage_reports[result.final_usage_report_id]
    assert report.request_state == "COMPLETED"
    assert {
        item.dimension_id: item.availability for item in report.dimensions
    }["input_tokens"] == "UNAVAILABLE"
    assert {
        item.dimension_id: item.availability for item in report.dimensions
    }["output_bytes"] == "AVAILABLE"
