import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from aidn_hypervisor.accounting.models import (
    AccountingContract,
    AccountingUnitContract,
    RuntimeUsageProfile,
    RuntimeUsageProfileDimension,
)
from aidn_hypervisor.dispatcher import (
    NetworkDispatcher,
    NetworkMessage,
    canonical_payload_hash,
)
from aidn_hypervisor.dispatcher.models import DispatcherRoute, canonical_payload_bytes
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.providers.models import RuntimeBinding
from aidn_hypervisor.runtime_protocol import (
    LocalIpcRuntimeIngress,
    RuntimeArtifactDeclare,
    RuntimeCancelRequest,
    RuntimeCancelResult,
    RuntimeCapacity,
    RuntimeDrainComplete,
    RuntimeDrainRequest,
    RuntimeDrainStatus,
    RuntimeExecuteRequest,
    RuntimeHealth,
    RuntimeHello,
    RuntimeHelloComplete,
    RuntimeMessage,
    RuntimeProtocolConformanceHarness,
    RuntimeProtocolError,
    RuntimeProtocolService,
    RuntimeProtocolStore,
    RuntimeReadinessDimensions,
    RuntimeReady,
    RuntimeRecoveryResult,
    RuntimeRecoveryState,
    RuntimeRequestAccept,
    RuntimeResult,
    RuntimeShutdown,
    RuntimeStateCheckpoint,
    RuntimeStreamChunk,
    RuntimeStreamClose,
    RuntimeStreamOpen,
    RuntimeUsageDimension,
    RuntimeUsageReport,
    canonical_hash,
)


def _binding(*, runtime_generation: int = 2) -> RuntimeBinding:
    profile = _usage_profile_template(runtime_generation=runtime_generation)
    return RuntimeBinding(
        runtime_binding_id="rtb-1",
        runtime_id="runtime-1",
        runtime_generation=runtime_generation,
        implementation_class="PLUGIN_MANAGED",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="llm.chat",
        capability_version="2.1",
        capability_definition_hash="cap-definition-1",
        plugin_id="aidn.provider.fake",
        plugin_version="1.0.0",
        adapter_id="adapter.chat",
        adapter_version="3",
        supported_features=["streaming", "cancellation"],
        supported_accounting_modes=["provider_metered", "fixed_price"],
        usage_reporting_profile_hash=profile.profile_hash,
        dispatcher_route_scope={"channel_class": "RUNTIME", "runtime_id": "runtime-1"},
        compatibility_bundle_id="bundle-1",
        status="ready",
    )


def _usage_profile_template(*, runtime_generation: int = 2) -> RuntimeUsageProfile:
    return RuntimeUsageProfile(
        runtime_id="runtime-1",
        runtime_generation=runtime_generation,
        runtime_configuration_hash="pending-runtime-configuration",
        adapter_version="3",
        dimensions=[
            RuntimeUsageProfileDimension(
                dimension_id="input_tokens",
                unit="token",
                expected_availability="AVAILABLE",
                authority="AUTHORITATIVE_PROVIDER",
                billing_eligible=True,
            ),
            RuntimeUsageProfileDimension(
                dimension_id="active_execution_milliseconds",
                unit="millisecond",
                expected_availability="AVAILABLE",
                authority="OBSERVABLE_LOCAL",
                billing_eligible=False,
            ),
            RuntimeUsageProfileDimension(
                dimension_id="upstream_cost",
                unit="usd",
                expected_availability="UNAVAILABLE",
            ),
        ],
    )


def _usage_profile(binding: RuntimeBinding) -> RuntimeUsageProfile:
    profile = _usage_profile_template(runtime_generation=binding.runtime_generation)
    return RuntimeUsageProfile.model_validate(
        {
            **profile.model_dump(mode="json"),
            "runtime_configuration_hash": binding.runtime_configuration_hash,
        }
    )


def _accounting_contract() -> AccountingContract:
    return AccountingContract(
        contract_version="acct-v1",
        accounting_mode="provider_metered",
        capability_id="llm.chat",
        endpoint_id="endpoint-1",
        pricing_version="pricing-v1",
        billable_units=[
            AccountingUnitContract(
                unit="input_tokens",
                mode="provider_metered",
                price=0.01,
                measurement_source="provider_api",
                verification_method="provider_report",
                required_authority="AUTHORITATIVE_PROVIDER",
            )
        ],
        checkpoint_policy="per_request",
        maximum_request_charge=2.0,
    )


def _route(binding: RuntimeBinding, *, route_generation: int = 5) -> DispatcherRoute:
    return DispatcherRoute(
        destination_type="RUNTIME",
        destination_id=binding.runtime_id,
        route_type="LOCAL_RUNTIME",
        route_generation=route_generation,
        runtime_generation=binding.runtime_generation,
        allowed_source_types={"HYPERVISOR"},
        allowed_channel_classes={"RUNTIME"},
        allowed_message_types={"RUNTIME_EXECUTE"},
        runtime_binding_hash=binding.binding_hash(),
        created_at=datetime.now(UTC).isoformat(),
    )


def _hello(binding: RuntimeBinding, *, recovery: bool = False) -> RuntimeHello:
    return RuntimeHello(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        instance_id="instance-1",
        runtime_configuration_hash=binding.runtime_configuration_hash,
        capability_id=binding.capability_id,
        supported_capability_versions=[binding.capability_version],
        supported_definition_hashes=[binding.capability_definition_hash],
        supported_runtime_protocol_versions=["1.0", "1.1"],
        supported_runtime_features=["streaming", "cancellation"],
        adapter_id=binding.adapter_id,
        adapter_version=binding.adapter_version,
        recovery_state_available=recovery,
        runtime_nonce="runtime-nonce",
        runtime_challenge="runtime-challenge",
        runtime_signature="runtime-signed",
    )


def _service(
    binding: RuntimeBinding,
    route_holder: dict[str, DispatcherRoute],
    *,
    store: RuntimeProtocolStore | None = None,
    accounting_contract: AccountingContract | None = None,
    usage_profile: RuntimeUsageProfile | None = None,
) -> RuntimeProtocolService:
    contract = accounting_contract or _accounting_contract()
    profile = usage_profile or _usage_profile(binding)
    return RuntimeProtocolService(
        hypervisor_id="hypervisor-1",
        network_revision="revision-1",
        binding_resolver=lambda runtime_id: (
            binding if runtime_id == binding.runtime_id else (_ for _ in ()).throw(KeyError())
        ),
        route_resolver=lambda runtime_id: route_holder.get(runtime_id),
        runtime_authenticator=lambda message: (
            getattr(message, "runtime_signature", None) == "runtime-signed"
        ),
        hypervisor_signer=lambda payload: f"hypervisor:{canonical_hash(payload)}",
        request_authorizer=lambda request: request.session_contract_hash
        == "session-contract-1",
        accounting_contract_resolver=lambda contract_hash: (
            contract
            if contract_hash == contract.payload_hash
            else (_ for _ in ()).throw(KeyError())
        ),
        usage_profile_resolver=lambda runtime_id: (
            profile
            if runtime_id == binding.runtime_id
            else (_ for _ in ()).throw(KeyError())
        ),
        store=store,
        supported_protocol_versions=("1.0", "1.1"),
    )


def _connect(
    service: RuntimeProtocolService,
    binding: RuntimeBinding,
    *,
    recovery: bool = False,
):
    response = service.begin_handshake(_hello(binding, recovery=recovery))
    connection = service.complete_handshake(
        RuntimeHelloComplete(
            handshake_id=response.handshake_id,
            runtime_id=binding.runtime_id,
            runtime_generation=binding.runtime_generation,
            route_generation=response.route_generation,
            hypervisor_challenge_response=service.challenge_response(
                response.hypervisor_challenge
            ),
            current_operational_state="READY",
            runtime_signature="runtime-signed",
        )
    )
    return response, connection


def _execute_request(binding: RuntimeBinding, *, request_id: str = "request-1", value="hi"):
    payload = {"prompt": value}
    return RuntimeExecuteRequest(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        endpoint_id="endpoint-1",
        endpoint_configuration_hash="endpoint-config-1",
        session_id="session-1",
        session_contract_hash="session-contract-1",
        request_id=request_id,
        capability_id=binding.capability_id,
        capability_version=binding.capability_version,
        capability_definition_hash=binding.capability_definition_hash,
        required_features=["streaming"],
        request_payload_hash=canonical_hash(payload),
        request_payload=payload,
        request_charge_ceiling=2.0,
        accounting_contract_hash=_accounting_contract().payload_hash,
        idempotency_key=f"idempotency-{request_id}",
        request_deadline=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    )


def _accept_request(
    service: RuntimeProtocolService,
    connection,
    binding: RuntimeBinding,
    request: RuntimeExecuteRequest,
):
    return service.record_request_accept(
        connection.runtime_connection_id,
        RuntimeRequestAccept(
            runtime_id=binding.runtime_id,
            runtime_generation=binding.runtime_generation,
            route_generation=connection.route_generation,
            session_id=request.session_id,
            request_id=request.request_id,
            admission_state="ACCEPTED",
            runtime_request_handle=f"provider-{request.request_id}",
            accepted_capability_definition_hash=binding.capability_definition_hash,
            accepted_features=request.required_features,
            accepted_at=datetime.now(UTC).isoformat(),
        ),
    )


def _ready(binding: RuntimeBinding, *, route_generation: int = 5) -> RuntimeReady:
    return RuntimeReady(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=route_generation,
        operational_state="READY",
        readiness_dimensions=RuntimeReadinessDimensions(
            process_ready=True,
            adapter_ready=True,
            provider_ready=True,
            model_ready=True,
            capability_ready=True,
            usage_reporting_ready=True,
            route_ready=True,
            recovery_ready=True,
        ),
        capability_definition_hash=binding.capability_definition_hash,
        supported_features=binding.supported_features,
        usage_profile_hash=binding.usage_reporting_profile_hash,
        ready_at=datetime.now(UTC).isoformat(),
        runtime_signature="runtime-signed",
    )


def _health(binding: RuntimeBinding, *, sequence: int = 1) -> RuntimeHealth:
    now = datetime.now(UTC)
    return RuntimeHealth(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        health_sequence=sequence,
        overall_state="HEALTHY",
        runtime_process_health="HEALTHY",
        adapter_health="HEALTHY",
        provider_health="HEALTHY",
        model_health="HEALTHY",
        capability_health="HEALTHY",
        resource_health="HEALTHY",
        usage_reporting_health="HEALTHY",
        recovery_health="HEALTHY",
        route_health="HEALTHY",
        observed_at=now.isoformat(),
        valid_until=(now + timedelta(minutes=1)).isoformat(),
        runtime_signature="runtime-signed",
    )


def _capacity(binding: RuntimeBinding, *, sequence: int = 1) -> RuntimeCapacity:
    now = datetime.now(UTC)
    return RuntimeCapacity(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        capacity_sequence=sequence,
        maximum_concurrent_requests=2,
        active_requests=1,
        queued_requests=0,
        maximum_queue_depth=4,
        maximum_active_sessions=2,
        active_sessions=1,
        maximum_input_size=4096,
        maximum_output_size=4096,
        maximum_artifact_size=0,
        observed_at=now.isoformat(),
        valid_until=(now + timedelta(minutes=1)).isoformat(),
        runtime_signature="runtime-signed",
    )


def _runtime_usage_report(
    binding: RuntimeBinding,
    request: RuntimeExecuteRequest,
    *,
    report_id: str,
    sequence: int = 1,
    value: int = 12,
    previous_hash: str | None = None,
    terminal_state: str | None = None,
) -> RuntimeUsageReport:
    return RuntimeUsageReport(
        usage_report_id=report_id,
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        endpoint_id=request.endpoint_id,
        endpoint_configuration_hash=request.endpoint_configuration_hash,
        session_id=request.session_id,
        request_id=request.request_id,
        accounting_contract_hash=request.accounting_contract_hash,
        report_type="FINAL" if terminal_state is not None else "INTERIM",
        usage_sequence=sequence,
        previous_usage_report_hash=previous_hash,
        dimensions=[
            RuntimeUsageDimension(
                dimension_id="input_tokens",
                unit="token",
                value=value,
                availability="AVAILABLE",
                authority="AUTHORITATIVE_PROVIDER",
                billable_eligible=True,
                source_reference={
                    "source_type": "PROVIDER_USAGE_RESPONSE",
                    "source_id": "provider-request-usage",
                },
            )
        ],
        request_state=terminal_state,
        terminal=terminal_state is not None,
        observed_at=datetime.now(UTC).isoformat(),
        runtime_signature="runtime-signed",
    )


def _runtime_result(
    binding: RuntimeBinding,
    request: RuntimeExecuteRequest,
    *,
    final_usage_report_id: str,
    payload: dict | None = None,
    terminal_state: str = "COMPLETED",
    stream_roots: list[str] | None = None,
    artifact_references: list[dict] | None = None,
) -> RuntimeResult:
    return RuntimeResult(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        endpoint_id=request.endpoint_id,
        endpoint_configuration_hash=request.endpoint_configuration_hash,
        session_id=request.session_id,
        request_id=request.request_id,
        terminal_state=terminal_state,
        result_payload=(payload or {"text": "completed"})
        if terminal_state in {"COMPLETED", "PARTIAL"}
        else None,
        stream_roots=stream_roots or [],
        artifact_references=artifact_references or [],
        final_usage_report_id=final_usage_report_id,
        provider_attempt_count=1,
        completed_at=datetime.now(UTC).isoformat(),
        runtime_signature="runtime-signed",
    )


def _runtime_cancel_request(
    binding: RuntimeBinding,
    request: RuntimeExecuteRequest,
    *,
    cancellation_id: str = "cancel-1",
) -> RuntimeCancelRequest:
    now = datetime.now(UTC)
    return RuntimeCancelRequest(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        session_id=request.session_id,
        request_id=request.request_id,
        cancellation_id=cancellation_id,
        cancellation_reason="consumer_requested",
        requested_at=now.isoformat(),
        deadline=(now + timedelta(minutes=1)).isoformat(),
        authorization_reference="session-cancel-authority",
        hypervisor_signature="hypervisor-signed",
    )


def _runtime_cancel_result(
    binding: RuntimeBinding,
    request: RuntimeExecuteRequest,
    *,
    cancellation_id: str = "cancel-1",
    cancellation_state: str = "CANCELLATION_PENDING",
    output_stopped: bool = False,
    provider_confirmed_stopped: bool = False,
) -> RuntimeCancelResult:
    return RuntimeCancelResult(
        cancellation_id=cancellation_id,
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        session_id=request.session_id,
        request_id=request.request_id,
        cancellation_state=cancellation_state,
        provider_execution_state="RUNNING",
        output_stopped=output_stopped,
        provider_confirmed_stopped=provider_confirmed_stopped,
        side_effect_state="NONE",
        observed_at=datetime.now(UTC).isoformat(),
        runtime_signature="runtime-signed",
    )


def _runtime_stream_open(
    binding: RuntimeBinding,
    request: RuntimeExecuteRequest,
    *,
    stream_id: str = "stream-1",
) -> RuntimeStreamOpen:
    return RuntimeStreamOpen(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        session_id=request.session_id,
        request_id=request.request_id,
        stream_id=stream_id,
        stream_type="result",
        modality="text",
        content_type="text/plain",
        result_root_policy="FULL_CONTENT_HASH",
        opened_at=datetime.now(UTC).isoformat(),
        runtime_signature="runtime-signed",
    )


def _runtime_stream_chunk(
    binding: RuntimeBinding,
    request: RuntimeExecuteRequest,
    *,
    stream_id: str = "stream-1",
    sequence: int = 1,
    content: str = "hello",
) -> RuntimeStreamChunk:
    encoded = content.encode("utf-8")
    return RuntimeStreamChunk(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        session_id=request.session_id,
        request_id=request.request_id,
        stream_id=stream_id,
        chunk_sequence=sequence,
        chunk_hash=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
        chunk_length=len(encoded),
        content=content,
        emitted_at=datetime.now(UTC).isoformat(),
        runtime_signature="runtime-signed",
    )


def _stream_root(stream_id: str, chunks: list[RuntimeStreamChunk]) -> str:
    return canonical_hash(
        {
            "stream_id": stream_id,
            "chunks": [
                {
                    "sequence": chunk.chunk_sequence,
                    "chunk_hash": chunk.chunk_hash,
                    "chunk_length": chunk.chunk_length,
                }
                for chunk in sorted(chunks, key=lambda item: item.chunk_sequence)
            ],
        }
    )


def _runtime_stream_close(
    binding: RuntimeBinding,
    request: RuntimeExecuteRequest,
    chunks: list[RuntimeStreamChunk],
    *,
    stream_id: str = "stream-1",
) -> RuntimeStreamClose:
    return RuntimeStreamClose(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        session_id=request.session_id,
        request_id=request.request_id,
        stream_id=stream_id,
        terminal_state="COMPLETED",
        final_sequence=max((item.chunk_sequence for item in chunks), default=0),
        final_content_root=_stream_root(stream_id, chunks),
        delivered_length=sum(item.chunk_length for item in chunks),
        close_reason="completed",
        closed_at=datetime.now(UTC).isoformat(),
        runtime_signature="runtime-signed",
    )


def _runtime_artifact(
    binding: RuntimeBinding,
    request: RuntimeExecuteRequest,
    *,
    content_hash: str = "sha256:artifact-content",
    storage_reference: str = "artifact://session-private/artifact-content",
) -> RuntimeArtifactDeclare:
    return RuntimeArtifactDeclare(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        session_id=request.session_id,
        request_id=request.request_id,
        content_hash=content_hash,
        content_type="text/plain",
        content_size=17,
        storage_reference=storage_reference,
        access_class="SESSION_PARTICIPANTS",
        retention_policy="SESSION_RETENTION",
        declared_at=datetime.now(UTC).isoformat(),
        runtime_signature="runtime-signed",
    )


def _runtime_state_checkpoint(
    binding: RuntimeBinding,
    request: RuntimeExecuteRequest,
    *,
    sequence: int = 1,
    state_generation: int = 1,
) -> RuntimeStateCheckpoint:
    return RuntimeStateCheckpoint(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        session_id=request.session_id,
        state_reference={"provider_thread": "thread-1"},
        state_generation=state_generation,
        checkpoint_sequence=sequence,
        recoverability="CHECKPOINT_RECOVERABLE",
        retention="SESSION_RETENTION",
        created_at=datetime.now(UTC).isoformat(),
        runtime_signature="runtime-signed",
    )


def _runtime_drain_request(binding: RuntimeBinding) -> RuntimeDrainRequest:
    return RuntimeDrainRequest(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        drain_id="drain-1",
        reason="rolling_update",
        drain_deadline=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        hypervisor_signature="hypervisor-signed",
    )


def _runtime_drain_status(
    binding: RuntimeBinding,
    *,
    sequence: int = 1,
    state: str = "DRAINING",
) -> RuntimeDrainStatus:
    return RuntimeDrainStatus(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        drain_id="drain-1",
        drain_state=state,
        status_sequence=sequence,
        active_requests=1 if state == "DRAINING" else 0,
        active_sessions=1 if state == "DRAINING" else 0,
        queued_requests=0,
        recoverable_requests=0,
        blocked_requests=0,
        updated_at=datetime.now(UTC).isoformat(),
        runtime_signature="runtime-signed",
    )


def _runtime_drain_complete(binding: RuntimeBinding) -> RuntimeDrainComplete:
    return RuntimeDrainComplete(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        drain_id="drain-1",
        completed_at=datetime.now(UTC).isoformat(),
        runtime_signature="runtime-signed",
    )


def _runtime_shutdown(binding: RuntimeBinding, *, mode: str = "GRACEFUL") -> RuntimeShutdown:
    return RuntimeShutdown(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        shutdown_id=f"shutdown-{mode.lower()}",
        shutdown_mode=mode,
        reason="maintenance",
        deadline=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        preserve_recovery_state=True,
        hypervisor_signature="hypervisor-signed",
    )


def test_handshake_activates_only_preapproved_binding_and_route() -> None:
    binding = _binding()
    route = _route(binding)
    service = _service(binding, {binding.runtime_id: route})

    response, connection = _connect(service, binding)

    assert response.selected_runtime_protocol_version == "1.1"
    assert response.runtime_binding_hash == binding.binding_hash()
    assert response.route_generation == route.route_generation
    assert connection.connection_state == "READY"
    assert connection.runtime_configuration_hash == binding.runtime_configuration_hash


def test_reconnect_closes_previous_runtime_connection() -> None:
    binding = _binding()
    service = _service(binding, {binding.runtime_id: _route(binding)})
    _, first = _connect(service, binding, recovery=True)

    _, second = _connect(service, binding)

    assert service.store.connections[first.runtime_connection_id].connection_state == "CLOSED"
    assert second.connection_state == "READY"


def test_handshake_rejects_stale_generation_and_requires_authentication() -> None:
    binding = _binding()
    service = _service(binding, {binding.runtime_id: _route(binding)})
    stale = _hello(binding).model_copy(
        update={"runtime_generation": binding.runtime_generation - 1}
    )
    with pytest.raises(RuntimeProtocolError) as generation_error:
        service.begin_handshake(stale)
    assert generation_error.value.code == "RUNTIME_GENERATION_MISMATCH"

    unsigned = _hello(binding).model_copy(update={"runtime_signature": "invalid"})
    with pytest.raises(RuntimeProtocolError) as auth_error:
        service.begin_handshake(unsigned)
    assert auth_error.value.code == "RUNTIME_IDENTITY_INVALID"


def test_runtime_message_has_semantic_replay_and_sequence_protection() -> None:
    binding = _binding()
    service = _service(binding, {binding.runtime_id: _route(binding)})
    _, connection = _connect(service, binding)
    payload = {"state": "HEALTHY"}
    message = RuntimeMessage(
        runtime_message_id="runtime-message-1",
        runtime_message_type="RUNTIME_HEALTH",
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        runtime_connection_id=connection.runtime_connection_id,
        runtime_sequence=1,
        created_at=datetime.now(UTC).isoformat(),
        expiration=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        payload_hash=canonical_hash(payload),
        payload=payload,
    )

    assert service.record_runtime_message(message) == message
    assert service.record_runtime_message(message) == message

    conflicting_payload = {"state": "FAILED"}
    conflicting = RuntimeMessage.model_validate(
        {
            **message.model_dump(mode="json"),
            "payload": conflicting_payload,
            "payload_hash": canonical_hash(conflicting_payload),
        }
    )
    with pytest.raises(RuntimeProtocolError) as conflict_error:
        service.record_runtime_message(conflicting)
    assert conflict_error.value.code == "RUNTIME_MESSAGE_REPLAYED"

    gap = message.model_copy(
        update={
            "runtime_message_id": "runtime-message-3",
            "runtime_sequence": 3,
        }
    )
    with pytest.raises(RuntimeProtocolError) as sequence_error:
        service.record_runtime_message(gap)
    assert sequence_error.value.code == "RUNTIME_SEQUENCE_INVALID"


def test_runtime_ready_promotes_recovered_connection() -> None:
    binding = _binding()
    service = _service(binding, {binding.runtime_id: _route(binding)})
    _, connection = _connect(service, binding, recovery=True)

    recorded = service.record_runtime_ready(
        connection.runtime_connection_id,
        _ready(binding),
    )

    assert recorded.operational_state == "READY"
    assert service.store.ready_states[binding.runtime_id] == recorded
    assert (
        service.store.connections[connection.runtime_connection_id].connection_state
        == "READY"
    )


def test_runtime_health_and_capacity_require_monotonic_sequences(tmp_path) -> None:
    binding = _binding()
    state_store = FileStateStore(tmp_path / "runtime-observations.json")
    service = _service(
        binding,
        {binding.runtime_id: _route(binding)},
        store=RuntimeProtocolStore(state_store),
    )
    _, connection = _connect(service, binding)
    health = _health(binding)
    capacity = _capacity(binding)

    assert service.record_runtime_health(connection.runtime_connection_id, health) == health
    assert service.record_runtime_capacity(connection.runtime_connection_id, capacity) == capacity
    assert service.record_runtime_health(connection.runtime_connection_id, health) == health
    assert service.record_runtime_capacity(connection.runtime_connection_id, capacity) == capacity

    with pytest.raises(RuntimeProtocolError) as health_error:
        service.record_runtime_health(
            connection.runtime_connection_id,
            health.model_copy(update={"overall_state": "DEGRADED"}),
        )
    assert health_error.value.code == "RUNTIME_HEALTH_CONFLICT"

    with pytest.raises(RuntimeProtocolError) as capacity_error:
        service.record_runtime_capacity(
            connection.runtime_connection_id,
            capacity.model_copy(update={"active_requests": 0}),
        )
    assert capacity_error.value.code == "RUNTIME_CAPACITY_CONFLICT"

    restored = RuntimeProtocolStore(state_store)
    assert restored.health_records[binding.runtime_id].health_sequence == 1
    assert restored.capacity_records[binding.runtime_id].capacity_sequence == 1


def test_local_ipc_runtime_ingress_uses_dispatcher_route_and_peer_authentication() -> None:
    binding = _binding()
    service = _service(binding, {binding.runtime_id: _route(binding)})
    _, connection = _connect(service, binding)
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="revision-1",
    )
    ingress = LocalIpcRuntimeIngress(
        dispatcher=dispatcher,
        runtime_protocol_service=service,
        peer_authenticator=lambda message: (
            message.authentication.get("peer_runtime_id") == binding.runtime_id
        ),
    )
    ingress.bind_runtime(binding, route_generation=5)
    health = _health(binding)
    payload = {
        "event_type": "RUNTIME_HEALTH",
        "runtime_connection_id": connection.runtime_connection_id,
        "event": health.model_dump(mode="json"),
    }
    now = datetime.now(UTC)
    message = NetworkMessage(
        message_id="local-ipc-health-1",
        message_type="RUNTIME_HEALTH",
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="revision-1",
        connection_id=connection.runtime_connection_id,
        channel_id="runtime-local-ipc",
        channel_class="RUNTIME",
        source_subject={"subject_type": "RUNTIME", "subject_id": binding.runtime_id},
        destination_subject={
            "subject_type": "HYPERVISOR_RUNTIME_INGRESS",
            "subject_id": binding.runtime_id,
        },
        source_sequence=1,
        route_generation=5,
        runtime_generation=binding.runtime_generation,
        created_at=now.isoformat(),
        expiration=(now + timedelta(minutes=5)).isoformat(),
        payload_hash=canonical_payload_hash(payload),
        payload_length=len(canonical_payload_bytes(payload)),
        payload=payload,
        authentication={
            "transport": "LOCAL_IPC",
            "peer_runtime_id": binding.runtime_id,
        },
    )

    result = ingress.receive(message)

    assert result == health
    assert service.store.health_records[binding.runtime_id] == health
    assert dispatcher.delivery_record(message.message_id).delivery_state == "APPLICATION_ACCEPTED"

    rejected = message.model_copy(
        update={
            "message_id": "local-ipc-health-2",
            "authentication": {"transport": "TCP_TLS"},
        }
    )
    with pytest.raises(ValueError, match="LOCAL_IPC"):
        ingress.receive(rejected)


def test_local_ipc_runtime_ingress_routes_terminal_result() -> None:
    binding = _binding()
    service = _service(binding, {binding.runtime_id: _route(binding)})
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)
    final_usage = _runtime_usage_report(
        binding,
        request,
        report_id="usage-local-ipc-result",
        terminal_state="COMPLETED",
    )
    assert service.record_usage_report(connection.runtime_connection_id, final_usage).status == (
        "ACCEPTED"
    )
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="revision-1",
    )
    ingress = LocalIpcRuntimeIngress(
        dispatcher=dispatcher,
        runtime_protocol_service=service,
        peer_authenticator=lambda message: (
            message.authentication.get("peer_runtime_id") == binding.runtime_id
        ),
    )
    ingress.bind_runtime(binding, route_generation=5)
    runtime_result = _runtime_result(
        binding,
        request,
        final_usage_report_id=final_usage.usage_report_id,
    )
    payload = {
        "event_type": "RUNTIME_RESULT",
        "runtime_connection_id": connection.runtime_connection_id,
        "event": runtime_result.model_dump(mode="json"),
    }
    now = datetime.now(UTC)
    message = NetworkMessage(
        message_id="local-ipc-result-1",
        message_type="RUNTIME_RESULT",
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="revision-1",
        connection_id=connection.runtime_connection_id,
        channel_id="runtime-local-ipc",
        channel_class="RUNTIME",
        source_subject={"subject_type": "RUNTIME", "subject_id": binding.runtime_id},
        destination_subject={
            "subject_type": "HYPERVISOR_RUNTIME_INGRESS",
            "subject_id": binding.runtime_id,
        },
        source_sequence=1,
        route_generation=5,
        runtime_generation=binding.runtime_generation,
        created_at=now.isoformat(),
        expiration=(now + timedelta(minutes=5)).isoformat(),
        payload_hash=canonical_payload_hash(payload),
        payload_length=len(canonical_payload_bytes(payload)),
        payload=payload,
        authentication={
            "transport": "LOCAL_IPC",
            "peer_runtime_id": binding.runtime_id,
        },
    )

    accepted = ingress.receive(message)

    assert accepted == runtime_result
    assert service.store.results[request.request_id] == runtime_result
    assert service.store.requests[request.request_id].terminal_result_hash == (
        runtime_result.result_hash
    )


def test_local_ipc_runtime_ingress_routes_cancel_result() -> None:
    binding = _binding()
    service = _service(binding, {binding.runtime_id: _route(binding)})
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)
    cancellation = _runtime_cancel_request(binding, request)
    service.request_runtime_cancellation(connection.runtime_connection_id, cancellation)
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="revision-1",
    )
    ingress = LocalIpcRuntimeIngress(
        dispatcher=dispatcher,
        runtime_protocol_service=service,
        peer_authenticator=lambda message: (
            message.authentication.get("peer_runtime_id") == binding.runtime_id
        ),
    )
    ingress.bind_runtime(binding, route_generation=5)
    cancel_result = _runtime_cancel_result(binding, request)
    payload = {
        "event_type": "RUNTIME_CANCEL_RESULT",
        "runtime_connection_id": connection.runtime_connection_id,
        "event": cancel_result.model_dump(mode="json"),
    }
    now = datetime.now(UTC)
    message = NetworkMessage(
        message_id="local-ipc-cancel-result-1",
        message_type="RUNTIME_CANCEL_RESULT",
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="revision-1",
        connection_id=connection.runtime_connection_id,
        channel_id="runtime-local-ipc",
        channel_class="RUNTIME",
        source_subject={"subject_type": "RUNTIME", "subject_id": binding.runtime_id},
        destination_subject={
            "subject_type": "HYPERVISOR_RUNTIME_INGRESS",
            "subject_id": binding.runtime_id,
        },
        source_sequence=1,
        route_generation=5,
        runtime_generation=binding.runtime_generation,
        created_at=now.isoformat(),
        expiration=(now + timedelta(minutes=5)).isoformat(),
        payload_hash=canonical_payload_hash(payload),
        payload_length=len(canonical_payload_bytes(payload)),
        payload=payload,
        authentication={
            "transport": "LOCAL_IPC",
            "peer_runtime_id": binding.runtime_id,
        },
    )

    accepted = ingress.receive(message)

    assert accepted == cancel_result
    assert service.store.cancellation_results[cancellation.cancellation_id] == cancel_result


def test_local_ipc_runtime_ingress_routes_stream_open() -> None:
    binding = _binding()
    service = _service(binding, {binding.runtime_id: _route(binding)})
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="revision-1",
    )
    ingress = LocalIpcRuntimeIngress(
        dispatcher=dispatcher,
        runtime_protocol_service=service,
        peer_authenticator=lambda message: (
            message.authentication.get("peer_runtime_id") == binding.runtime_id
        ),
    )
    ingress.bind_runtime(binding, route_generation=5)
    stream = _runtime_stream_open(binding, request)
    payload = {
        "event_type": "RUNTIME_STREAM_OPEN",
        "runtime_connection_id": connection.runtime_connection_id,
        "event": stream.model_dump(mode="json"),
    }
    now = datetime.now(UTC)
    message = NetworkMessage(
        message_id="local-ipc-stream-open-1",
        message_type="RUNTIME_STREAM_OPEN",
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="revision-1",
        connection_id=connection.runtime_connection_id,
        channel_id="runtime-local-ipc",
        channel_class="RUNTIME",
        source_subject={"subject_type": "RUNTIME", "subject_id": binding.runtime_id},
        destination_subject={
            "subject_type": "HYPERVISOR_RUNTIME_INGRESS",
            "subject_id": binding.runtime_id,
        },
        source_sequence=1,
        route_generation=5,
        runtime_generation=binding.runtime_generation,
        created_at=now.isoformat(),
        expiration=(now + timedelta(minutes=5)).isoformat(),
        payload_hash=canonical_payload_hash(payload),
        payload_length=len(canonical_payload_bytes(payload)),
        payload=payload,
        authentication={
            "transport": "LOCAL_IPC",
            "peer_runtime_id": binding.runtime_id,
        },
    )

    assert ingress.receive(message) == stream
    assert service.store.streams[stream.stream_id] == stream


def test_local_ipc_runtime_ingress_routes_artifact_declaration() -> None:
    binding = _binding()
    service = _service(binding, {binding.runtime_id: _route(binding)})
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="revision-1",
    )
    ingress = LocalIpcRuntimeIngress(
        dispatcher=dispatcher,
        runtime_protocol_service=service,
        peer_authenticator=lambda message: (
            message.authentication.get("peer_runtime_id") == binding.runtime_id
        ),
    )
    ingress.bind_runtime(binding, route_generation=5)
    artifact = _runtime_artifact(binding, request)
    payload = {
        "event_type": "RUNTIME_ARTIFACT_DECLARE",
        "runtime_connection_id": connection.runtime_connection_id,
        "event": artifact.model_dump(mode="json"),
    }
    now = datetime.now(UTC)
    message = NetworkMessage(
        message_id="local-ipc-artifact-1",
        message_type="RUNTIME_ARTIFACT_DECLARE",
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="revision-1",
        connection_id=connection.runtime_connection_id,
        channel_id="runtime-local-ipc",
        channel_class="RUNTIME",
        source_subject={"subject_type": "RUNTIME", "subject_id": binding.runtime_id},
        destination_subject={
            "subject_type": "HYPERVISOR_RUNTIME_INGRESS",
            "subject_id": binding.runtime_id,
        },
        source_sequence=1,
        route_generation=5,
        runtime_generation=binding.runtime_generation,
        created_at=now.isoformat(),
        expiration=(now + timedelta(minutes=5)).isoformat(),
        payload_hash=canonical_payload_hash(payload),
        payload_length=len(canonical_payload_bytes(payload)),
        payload=payload,
        authentication={
            "transport": "LOCAL_IPC",
            "peer_runtime_id": binding.runtime_id,
        },
    )

    assert ingress.receive(message) == artifact
    assert service.store.artifacts[artifact.artifact_id] == artifact


def test_execute_request_is_idempotent_and_acceptance_is_not_completion() -> None:
    binding = _binding()
    service = _service(binding, {binding.runtime_id: _route(binding)})
    _, connection = _connect(service, binding)
    request = _execute_request(binding)

    first = service.register_execute_request(connection.runtime_connection_id, request)
    duplicate = service.register_execute_request(connection.runtime_connection_id, request)
    assert duplicate == first
    assert duplicate.request_state == "SUBMITTED"

    with pytest.raises(RuntimeProtocolError) as conflict_error:
        service.register_execute_request(
            connection.runtime_connection_id,
            _execute_request(binding, value="different"),
        )
    assert conflict_error.value.code == "RUNTIME_REQUEST_CONFLICT"

    accepted = service.record_request_accept(
        connection.runtime_connection_id,
        RuntimeRequestAccept(
            runtime_id=binding.runtime_id,
            runtime_generation=binding.runtime_generation,
            route_generation=5,
            session_id="session-1",
            request_id=request.request_id,
            admission_state="ACCEPTED",
            runtime_request_handle="provider-request-1",
            accepted_capability_definition_hash=binding.capability_definition_hash,
            accepted_features=["streaming"],
            accepted_at=datetime.now(UTC).isoformat(),
        ),
    )
    assert accepted.request_state == "ACCEPTED"
    assert accepted.terminal_result_hash is None

    unauthorized = _execute_request(binding, request_id="request-unauthorized")
    unauthorized = unauthorized.model_copy(
        update={"session_contract_hash": "wrong-contract"}
    )
    with pytest.raises(RuntimeProtocolError) as authorization_error:
        service.register_execute_request(
            connection.runtime_connection_id,
            unauthorized,
        )
    assert authorization_error.value.code == "RUNTIME_SESSION_NOT_AUTHORIZED"


def test_execute_rejects_accounting_contract_incompatible_with_usage_profile() -> None:
    binding = _binding()
    incompatible_contract = AccountingContract(
        contract_version="acct-output-v1",
        accounting_mode="provider_metered",
        capability_id=binding.capability_id,
        endpoint_id="endpoint-1",
        pricing_version="pricing-v1",
        billable_units=[
            AccountingUnitContract(
                unit="output_tokens",
                mode="provider_metered",
                price=0.02,
                measurement_source="provider_api",
                verification_method="provider_report",
                required_authority="AUTHORITATIVE_PROVIDER",
            )
        ],
        checkpoint_policy="per_request",
    )
    service = _service(
        binding,
        {binding.runtime_id: _route(binding)},
        accounting_contract=incompatible_contract,
    )
    _, connection = _connect(service, binding)
    request = _execute_request(binding).model_copy(
        update={"accounting_contract_hash": incompatible_contract.payload_hash}
    )

    with pytest.raises(RuntimeProtocolError) as incompatible:
        service.register_execute_request(connection.runtime_connection_id, request)

    assert incompatible.value.code == "ACCOUNTING_REQUIRED_DIMENSION_UNAVAILABLE"


def test_usage_reports_preserve_dimension_authority_and_hash_chain(tmp_path) -> None:
    binding = _binding()
    route_holder = {binding.runtime_id: _route(binding)}
    state_store = FileStateStore(tmp_path / "runtime-state.json")
    service = _service(
        binding,
        route_holder,
        store=RuntimeProtocolStore(state_store),
    )
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)

    report = RuntimeUsageReport(
        usage_report_id="usage-1",
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        endpoint_id="endpoint-1",
        endpoint_configuration_hash="endpoint-config-1",
        session_id="session-1",
        request_id=request.request_id,
        accounting_contract_hash=request.accounting_contract_hash,
        usage_sequence=1,
        dimensions=[
            RuntimeUsageDimension(
                dimension_id="input_tokens",
                unit="token",
                value=12,
                availability="AVAILABLE",
                authority="AUTHORITATIVE_PROVIDER",
                billable_eligible=True,
                source_reference={
                    "source_type": "PROVIDER_USAGE_RESPONSE",
                    "source_id": "provider-request-usage",
                },
            ),
            RuntimeUsageDimension(
                dimension_id="upstream_cost",
                unit="usd",
                availability="UNAVAILABLE",
            ),
        ],
        observed_at=datetime.now(UTC).isoformat(),
        runtime_signature="runtime-signed",
    )
    ack = service.record_usage_report(connection.runtime_connection_id, report)
    duplicate = service.record_usage_report(connection.runtime_connection_id, report)

    assert ack.status == "ACCEPTED"
    assert duplicate.status == "DUPLICATE"
    restored = RuntimeProtocolStore(state_store)
    assert restored.usage_reports[report.usage_report_id].report_hash == report.report_hash
    assert restored.requests[request.request_id].request_hash == request.semantic_hash()


def test_terminal_runtime_request_persistence_elides_replay_payload(tmp_path) -> None:
    binding = _binding()
    state_store = FileStateStore(tmp_path / "runtime-terminal-state.json")
    store = RuntimeProtocolStore(state_store)
    service = _service(
        binding,
        {binding.runtime_id: _route(binding)},
        store=store,
    )
    _, connection = _connect(service, binding)
    request = _execute_request(binding, value="large transcript")
    service.register_execute_request(connection.runtime_connection_id, request)

    store.requests[request.request_id] = store.requests[request.request_id].model_copy(
        update={"request_state": "COMPLETED"}
    )
    store.flush()

    restored = RuntimeProtocolStore(state_store)
    persisted_request = restored.requests[request.request_id].request
    assert persisted_request.request_payload is None
    assert persisted_request.request_payload_reference.startswith(
        "state://runtime-request/"
    )
    assert persisted_request.request_payload_hash == request.request_payload_hash


def test_recovery_requires_explicit_route_rebind(tmp_path) -> None:
    binding = _binding()
    route_holder = {binding.runtime_id: _route(binding)}
    state_store = FileStateStore(tmp_path / "runtime-recovery-state.json")
    service = _service(
        binding,
        route_holder,
        store=RuntimeProtocolStore(state_store),
    )
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    route_holder[binding.runtime_id] = _route(binding, route_generation=6)
    state = RuntimeRecoveryState(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        instance_id="instance-1",
        active_requests=[request.request_id, "runtime-only"],
        runtime_signature="runtime-signed",
    )

    with pytest.raises(RuntimeProtocolError) as route_error:
        service.build_recovery_plan(connection.runtime_connection_id, state)
    assert route_error.value.code == "RUNTIME_ROUTE_GENERATION_MISMATCH"

    plan = service.build_recovery_plan(
        connection.runtime_connection_id,
        state,
        allow_route_rebind=True,
    )
    assert plan.route_generation == 6
    assert plan.request_directives[request.request_id] == "CONTINUE_EXISTING_EXECUTION"
    assert plan.request_directives["runtime-only"] == "IGNORE_UNKNOWN_REQUEST"

    result = RuntimeRecoveryResult(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        route_generation=6,
        plan_id=plan.plan_id,
        request_results={request.request_id: "CONTINUING"},
        completed_at=datetime.now(UTC).isoformat(),
    )
    ready = service.record_recovery_result(connection.runtime_connection_id, result)
    assert ready.connection_state == "READY"
    assert service.store.recovery_results[plan.plan_id].result_hash == result.result_hash
    restored = RuntimeProtocolStore(state_store)
    assert restored.recovery_results[plan.plan_id].result_hash == result.result_hash
    assert restored.recovery_states[binding.runtime_id].recovery_state_hash == (
        state.recovery_state_hash
    )


def test_recovery_conflicts_keep_connection_recovering() -> None:
    binding = _binding()
    route_holder = {binding.runtime_id: _route(binding)}
    service = _service(binding, route_holder)
    _, connection = _connect(service, binding, recovery=True)
    state = RuntimeRecoveryState(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=5,
        instance_id="instance-1",
        runtime_signature="runtime-signed",
    )
    plan = service.build_recovery_plan(connection.runtime_connection_id, state)
    result = RuntimeRecoveryResult(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        route_generation=5,
        plan_id=plan.plan_id,
        remaining_conflicts=["request-unknown"],
        completed_at=datetime.now(UTC).isoformat(),
    )

    recovering = service.record_recovery_result(
        connection.runtime_connection_id,
        result,
    )

    assert recovering.connection_state == "RECOVERING"


def test_unavailable_usage_cannot_be_encoded_as_zero() -> None:
    with pytest.raises(ValueError, match="unavailable or not-applicable Usage"):
        RuntimeUsageDimension(
            dimension_id="tokens",
            unit="token",
            value=0,
            availability="UNAVAILABLE",
        )


def test_usage_conflict_and_sequence_gap_return_auditable_acknowledgments(tmp_path) -> None:
    binding = _binding()
    state_store = FileStateStore(tmp_path / "usage-conflicts.json")
    service = _service(
        binding,
        {binding.runtime_id: _route(binding)},
        store=RuntimeProtocolStore(state_store),
    )
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)
    first = _runtime_usage_report(binding, request, report_id="usage-first")
    assert service.record_usage_report(connection.runtime_connection_id, first).status == (
        "ACCEPTED"
    )

    conflicting = _runtime_usage_report(
        binding,
        request,
        report_id="usage-conflicting",
        value=13,
    )
    conflict_ack = service.record_usage_report(
        connection.runtime_connection_id,
        conflicting,
    )
    gap = _runtime_usage_report(
        binding,
        request,
        report_id="usage-gap",
        sequence=3,
        previous_hash=first.report_hash,
    )
    gap_ack = service.record_usage_report(connection.runtime_connection_id, gap)

    assert conflict_ack.status == "CONFLICT"
    assert gap_ack.status == "OUT_OF_SEQUENCE"
    assert conflict_ack.hypervisor_signature.startswith("hypervisor:")
    assert len(service.store.usage_conflicts) == 2
    assert len(RuntimeProtocolStore(state_store).usage_conflicts) == 2


def test_runtime_conformance_fault_injection_preserves_usage_and_rejects_stale_route() -> None:
    binding = _binding()
    service = _service(binding, {binding.runtime_id: _route(binding)})
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)
    report = _runtime_usage_report(binding, request, report_id="usage-lost-ack")
    harness = RuntimeProtocolConformanceHarness()

    def submit_then_lose_ack() -> None:
        accepted = service.record_usage_report(connection.runtime_connection_id, report)
        assert accepted.status == "ACCEPTED"
        raise TimeoutError("simulated Usage acknowledgment loss")

    harness.assert_transport_failure(
        "usage_ack_lost_after_persistence",
        submit_then_lose_ack,
        TimeoutError,
    )
    redelivered = harness.assert_success(
        "usage_report_redelivery",
        lambda: service.record_usage_report(connection.runtime_connection_id, report),
    )
    harness.assert_protocol_error(
        "stale_route_health",
        lambda: service.record_runtime_health(
            connection.runtime_connection_id,
            _health(binding).model_copy(update={"route_generation": 4}),
        ),
        "RUNTIME_ROUTE_GENERATION_MISMATCH",
    )

    assert redelivered.status == "DUPLICATE"
    assert redelivered.accepted_report_hash == report.report_hash
    assert len(service.store.usage_reports) == 1
    assert harness.report().passed is True


def test_usage_report_cannot_expand_profile_billing_eligibility() -> None:
    binding = _binding()
    service = _service(binding, {binding.runtime_id: _route(binding)})
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)
    report_payload = _runtime_usage_report(
        binding,
        request,
        report_id="usage-diagnostic-promoted",
    ).model_dump(mode="json")
    report_payload.update(
        {
            "dimensions": [
                {
                    "dimension_id": "active_execution_milliseconds",
                    "unit": "millisecond",
                    "availability": "AVAILABLE",
                    "authority": "OBSERVABLE_LOCAL",
                    "value": 100,
                    "cumulative": True,
                    "billing_eligible": True,
                }
            ],
            "report_hash": None,
        }
    )
    report = RuntimeUsageReport.model_validate(report_payload)

    ack = service.record_usage_report(connection.runtime_connection_id, report)

    assert ack.status == "REJECTED"
    assert ack.rejection_code == "USAGE_BILLING_ELIGIBILITY_INVALID"


def test_terminal_request_requires_matching_final_usage_report() -> None:
    binding = _binding()
    service = _service(binding, {binding.runtime_id: _route(binding)})
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)

    with pytest.raises(RuntimeProtocolError) as missing_usage:
        service.record_request_terminal(
            connection.runtime_connection_id,
            request_id=request.request_id,
            terminal_state="COMPLETED",
            terminal_result_hash="sha256:result",
            final_usage_report_id="missing-final-usage",
        )
    assert missing_usage.value.code == "USAGE_FINAL_REPORT_REQUIRED"

    final = _runtime_usage_report(
        binding,
        request,
        report_id="usage-final",
        terminal_state="COMPLETED",
    )
    ack = service.record_usage_report(connection.runtime_connection_id, final)
    terminal = service.record_request_terminal(
        connection.runtime_connection_id,
        request_id=request.request_id,
        terminal_state="COMPLETED",
        terminal_result_hash="sha256:result",
        final_usage_report_id=final.usage_report_id,
    )

    assert ack.status == "ACCEPTED"
    assert terminal.request_state == "COMPLETED"
    assert terminal.terminal_result_hash == "sha256:result"


def test_runtime_result_is_idempotent_and_persists_after_restart(tmp_path) -> None:
    binding = _binding()
    state_store = FileStateStore(tmp_path / "runtime-result-state.json")
    store = RuntimeProtocolStore(state_store)
    service = _service(
        binding,
        {binding.runtime_id: _route(binding)},
        store=store,
    )
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)
    result = _runtime_result(
        binding,
        request,
        final_usage_report_id="usage-result-final",
    )

    with pytest.raises(RuntimeProtocolError) as missing_usage:
        service.record_runtime_result(connection.runtime_connection_id, result)
    assert missing_usage.value.code == "USAGE_FINAL_REPORT_REQUIRED"

    final_usage = _runtime_usage_report(
        binding,
        request,
        report_id="usage-result-final",
        terminal_state="COMPLETED",
    )
    assert service.record_usage_report(connection.runtime_connection_id, final_usage).status == (
        "ACCEPTED"
    )
    accepted = service.record_runtime_result(connection.runtime_connection_id, result)

    assert service.record_runtime_result(connection.runtime_connection_id, result) == accepted
    assert store.requests[request.request_id].terminal_result_hash == result.result_hash

    conflicting = _runtime_result(
        binding,
        request,
        final_usage_report_id=final_usage.usage_report_id,
        payload={"text": "conflicting"},
    )
    with pytest.raises(RuntimeProtocolError) as conflict:
        service.record_runtime_result(connection.runtime_connection_id, conflicting)
    assert conflict.value.code == "RUNTIME_RESULT_FINALIZATION_FAILED"

    restored = RuntimeProtocolStore(state_store)
    assert restored.results[request.request_id].result_hash == result.result_hash


def test_runtime_cancellation_preserves_evidence_and_restores_rejected_cancel(tmp_path) -> None:
    binding = _binding()
    state_store = FileStateStore(tmp_path / "runtime-cancel-state.json")
    store = RuntimeProtocolStore(state_store)
    service = _service(
        binding,
        {binding.runtime_id: _route(binding)},
        store=store,
    )
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)
    cancellation = _runtime_cancel_request(binding, request)

    assert service.request_runtime_cancellation(
        connection.runtime_connection_id,
        cancellation,
    ) == cancellation
    assert service.store.requests[request.request_id].request_state == "CANCEL_REQUESTED"

    cancelled = _runtime_cancel_result(
        binding,
        request,
        cancellation_state="CANCELLED",
        output_stopped=True,
        provider_confirmed_stopped=False,
    )
    assert service.record_runtime_cancel_result(
        connection.runtime_connection_id,
        cancelled,
    ) == cancelled
    assert service.record_runtime_cancel_result(
        connection.runtime_connection_id,
        cancelled,
    ) == cancelled
    assert service.store.requests[request.request_id].request_state == "CANCEL_REQUESTED"

    final_usage = _runtime_usage_report(
        binding,
        request,
        report_id="usage-cancelled-final",
        terminal_state="CANCELLED",
    )
    assert service.record_usage_report(connection.runtime_connection_id, final_usage).status == (
        "ACCEPTED"
    )
    final_result = _runtime_result(
        binding,
        request,
        final_usage_report_id=final_usage.usage_report_id,
        terminal_state="CANCELLED",
    )
    service.record_runtime_result(connection.runtime_connection_id, final_result)
    assert service.store.requests[request.request_id].request_state == "CANCELLED"

    restored = RuntimeProtocolStore(state_store)
    assert restored.cancellation_results[cancellation.cancellation_id] == cancelled

    second_request = _execute_request(binding).model_copy(
        update={"request_id": "request-cancel-unsupported", "idempotency_key": "cancel-unsupported"}
    )
    service.register_execute_request(connection.runtime_connection_id, second_request)
    _accept_request(service, connection, binding, second_request)
    second_cancellation = _runtime_cancel_request(
        binding,
        second_request,
        cancellation_id="cancel-unsupported",
    )
    service.request_runtime_cancellation(connection.runtime_connection_id, second_cancellation)
    unsupported = _runtime_cancel_result(
        binding,
        second_request,
        cancellation_id=second_cancellation.cancellation_id,
        cancellation_state="CANCELLATION_UNSUPPORTED",
    )
    service.record_runtime_cancel_result(connection.runtime_connection_id, unsupported)
    assert service.store.requests[second_request.request_id].request_state == "ACCEPTED"


def test_runtime_stream_requires_ordered_chunks_and_closed_root(tmp_path) -> None:
    binding = _binding()
    state_store = FileStateStore(tmp_path / "runtime-stream-state.json")
    store = RuntimeProtocolStore(state_store)
    service = _service(
        binding,
        {binding.runtime_id: _route(binding)},
        store=store,
    )
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)
    stream = _runtime_stream_open(binding, request)
    assert service.record_runtime_stream_open(connection.runtime_connection_id, stream) == stream
    first = _runtime_stream_chunk(binding, request, sequence=1, content="hello")
    assert service.record_runtime_stream_chunk(connection.runtime_connection_id, first) == first
    assert service.record_runtime_stream_chunk(connection.runtime_connection_id, first) == first

    gap = _runtime_stream_chunk(binding, request, sequence=3, content="gap")
    with pytest.raises(RuntimeProtocolError) as sequence_error:
        service.record_runtime_stream_chunk(connection.runtime_connection_id, gap)
    assert sequence_error.value.code == "RUNTIME_STREAM_SEQUENCE_INVALID"

    second = _runtime_stream_chunk(binding, request, sequence=2, content=" world")
    assert service.record_runtime_stream_chunk(connection.runtime_connection_id, second) == second
    close = _runtime_stream_close(binding, request, [first, second])
    assert service.record_runtime_stream_close(connection.runtime_connection_id, close) == close
    assert service.record_runtime_stream_close(connection.runtime_connection_id, close) == close

    final_usage = _runtime_usage_report(
        binding,
        request,
        report_id="usage-stream-final",
        terminal_state="COMPLETED",
    )
    assert service.record_usage_report(connection.runtime_connection_id, final_usage).status == (
        "ACCEPTED"
    )
    result = _runtime_result(
        binding,
        request,
        final_usage_report_id=final_usage.usage_report_id,
        stream_roots=[close.final_content_root],
    )
    assert service.record_runtime_result(connection.runtime_connection_id, result) == result

    restored = RuntimeProtocolStore(state_store)
    assert restored.stream_chunks[stream.stream_id][2] == second
    assert restored.stream_closes[stream.stream_id] == close


def test_runtime_artifact_is_content_addressed_persistent_and_result_bound(tmp_path) -> None:
    binding = _binding()
    state_store = FileStateStore(tmp_path / "runtime-artifact-state.json")
    store = RuntimeProtocolStore(state_store)
    service = _service(
        binding,
        {binding.runtime_id: _route(binding)},
        store=store,
    )
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)
    artifact = _runtime_artifact(binding, request)

    assert service.record_runtime_artifact(connection.runtime_connection_id, artifact) == artifact
    assert service.record_runtime_artifact(connection.runtime_connection_id, artifact) == artifact

    conflicting = _runtime_artifact(
        binding,
        request,
        storage_reference="artifact://other-location",
    )
    with pytest.raises(RuntimeProtocolError) as conflict:
        service.record_runtime_artifact(connection.runtime_connection_id, conflicting)
    assert conflict.value.code == "RUNTIME_ARTIFACT_INVALID"

    final_usage = _runtime_usage_report(
        binding,
        request,
        report_id="usage-artifact-final",
        terminal_state="COMPLETED",
    )
    assert service.record_usage_report(connection.runtime_connection_id, final_usage).status == (
        "ACCEPTED"
    )
    result = _runtime_result(
        binding,
        request,
        final_usage_report_id=final_usage.usage_report_id,
        artifact_references=[
            {"artifact_id": artifact.artifact_id, "content_hash": artifact.content_hash}
        ],
    )
    assert service.record_runtime_result(connection.runtime_connection_id, result) == result

    restored = RuntimeProtocolStore(state_store)
    assert restored.artifacts[artifact.artifact_id] == artifact


def test_runtime_state_checkpoint_is_session_scoped_and_persistent(tmp_path) -> None:
    binding = _binding()
    state_store = FileStateStore(tmp_path / "runtime-state-checkpoint.json")
    service = _service(
        binding,
        {binding.runtime_id: _route(binding)},
        store=RuntimeProtocolStore(state_store),
    )
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)
    checkpoint = _runtime_state_checkpoint(binding, request)

    assert service.record_runtime_state_checkpoint(
        connection.runtime_connection_id,
        checkpoint,
    ) == checkpoint
    assert service.record_runtime_state_checkpoint(
        connection.runtime_connection_id,
        checkpoint,
    ) == checkpoint

    gap = _runtime_state_checkpoint(binding, request, sequence=3)
    with pytest.raises(RuntimeProtocolError) as sequence_error:
        service.record_runtime_state_checkpoint(connection.runtime_connection_id, gap)
    assert sequence_error.value.code == "RUNTIME_STATE_GENERATION_MISMATCH"

    resumed_request = _execute_request(binding).model_copy(
        update={
            "request_id": "request-with-state",
            "idempotency_key": "request-with-state",
            "state_reference": {
                "checkpoint_hash": checkpoint.checkpoint_hash,
                "state_generation": checkpoint.state_generation,
            },
        }
    )
    assert service.register_execute_request(
        connection.runtime_connection_id,
        resumed_request,
    ).request_id == resumed_request.request_id

    invalid_state_request = resumed_request.model_copy(
        update={
            "request_id": "request-with-invalid-state",
            "idempotency_key": "request-with-invalid-state",
            "state_reference": {"checkpoint_hash": "sha256:unknown", "state_generation": 1},
        }
    )
    with pytest.raises(RuntimeProtocolError) as state_error:
        service.register_execute_request(
            connection.runtime_connection_id,
            invalid_state_request,
        )
    assert state_error.value.code == "RUNTIME_STATE_REFERENCE_INVALID"

    restored = RuntimeProtocolStore(state_store)
    assert restored.state_checkpoints


def test_runtime_drain_blocks_admission_and_preserves_terminal_events(tmp_path) -> None:
    binding = _binding()
    state_store = FileStateStore(tmp_path / "runtime-drain-state.json")
    service = _service(
        binding,
        {binding.runtime_id: _route(binding)},
        store=RuntimeProtocolStore(state_store),
    )
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)
    drain = _runtime_drain_request(binding)

    assert service.request_runtime_drain(connection.runtime_connection_id, drain) == drain
    assert service.request_runtime_drain(connection.runtime_connection_id, drain) == drain
    assert service.store.connections[connection.runtime_connection_id].connection_state == (
        "DRAINING"
    )

    new_request = _execute_request(binding).model_copy(
        update={"request_id": "request-after-drain", "idempotency_key": "after-drain"}
    )
    with pytest.raises(RuntimeProtocolError) as not_ready:
        service.register_execute_request(connection.runtime_connection_id, new_request)
    assert not_ready.value.code == "RUNTIME_NOT_READY"

    status = _runtime_drain_status(binding)
    assert service.record_runtime_drain_status(connection.runtime_connection_id, status) == status
    complete_status = _runtime_drain_status(binding, sequence=2, state="COMPLETE")
    assert service.record_runtime_drain_status(
        connection.runtime_connection_id,
        complete_status,
    ) == complete_status

    final_usage = _runtime_usage_report(
        binding,
        request,
        report_id="usage-drain-final",
        terminal_state="COMPLETED",
    )
    assert service.record_usage_report(connection.runtime_connection_id, final_usage).status == (
        "ACCEPTED"
    )
    final_result = _runtime_result(
        binding,
        request,
        final_usage_report_id=final_usage.usage_report_id,
    )
    assert service.record_runtime_result(connection.runtime_connection_id, final_result) == final_result

    complete = _runtime_drain_complete(binding)
    assert service.record_runtime_drain_complete(
        connection.runtime_connection_id,
        complete,
    ) == complete
    graceful = _runtime_shutdown(binding)
    assert service.request_runtime_shutdown(
        connection.runtime_connection_id,
        graceful,
    ) == graceful

    emergency = _runtime_shutdown(binding, mode="IMMEDIATE")
    service.request_runtime_shutdown(connection.runtime_connection_id, emergency)
    assert service.store.connections[connection.runtime_connection_id].connection_state == "CLOSED"

    restored = RuntimeProtocolStore(state_store)
    assert restored.drain_completes[drain.drain_id] == complete
    assert restored.shutdowns[emergency.shutdown_id] == emergency


def test_terminal_request_requires_final_usage_to_be_current_chain_head() -> None:
    binding = _binding()
    service = _service(binding, {binding.runtime_id: _route(binding)})
    _, connection = _connect(service, binding)
    request = _execute_request(binding)
    service.register_execute_request(connection.runtime_connection_id, request)
    _accept_request(service, connection, binding, request)
    final = _runtime_usage_report(
        binding,
        request,
        report_id="usage-final-before-correction",
        terminal_state="COMPLETED",
    )
    assert service.record_usage_report(connection.runtime_connection_id, final).status == (
        "ACCEPTED"
    )
    correction_payload = final.model_dump(mode="json")
    correction_payload.update(
        {
            "usage_report_id": "usage-correction-after-final",
            "report_type": "CORRECTION",
            "usage_sequence": 2,
            "previous_usage_report_hash": final.report_hash,
            "request_state": None,
            "terminal": False,
            "report_hash": None,
        }
    )
    correction = RuntimeUsageReport.model_validate(correction_payload)
    assert service.record_usage_report(
        connection.runtime_connection_id,
        correction,
    ).status == "ACCEPTED"

    with pytest.raises(RuntimeProtocolError) as stale_final:
        service.record_request_terminal(
            connection.runtime_connection_id,
            request_id=request.request_id,
            terminal_state="COMPLETED",
            terminal_result_hash="sha256:result",
            final_usage_report_id=final.usage_report_id,
        )

    assert stale_final.value.code == "USAGE_FINAL_REPORT_REQUIRED"
