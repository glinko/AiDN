from datetime import datetime, timedelta, timezone

import pytest

from aidn_hypervisor.dispatcher.models import DispatcherRoute
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.providers.models import RuntimeBinding
from aidn_hypervisor.runtime_protocol import (
    RuntimeExecuteRequest,
    RuntimeHello,
    RuntimeHelloComplete,
    RuntimeMessage,
    RuntimeProtocolError,
    RuntimeProtocolService,
    RuntimeProtocolStore,
    RuntimeRecoveryState,
    RuntimeRecoveryResult,
    RuntimeRequestAccept,
    RuntimeUsageDimension,
    RuntimeUsageReport,
    canonical_hash,
)


def _binding(*, runtime_generation: int = 2) -> RuntimeBinding:
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
        dispatcher_route_scope={"channel_class": "RUNTIME", "runtime_id": "runtime-1"},
        compatibility_bundle_id="bundle-1",
        status="ready",
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
        created_at=datetime.now(timezone.utc).isoformat(),
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
) -> RuntimeProtocolService:
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
        accounting_contract_hash="accounting-1",
        idempotency_key=f"idempotency-{request_id}",
        request_deadline=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
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
        created_at=datetime.now(timezone.utc).isoformat(),
        expiration=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
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
            accepted_at=datetime.now(timezone.utc).isoformat(),
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

    report = RuntimeUsageReport(
        usage_report_id="usage-1",
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        endpoint_id="endpoint-1",
        session_id="session-1",
        request_id=request.request_id,
        usage_sequence=1,
        dimensions=[
            RuntimeUsageDimension(
                dimension_id="input_tokens",
                unit="token",
                value=12,
                availability="AVAILABLE",
                authority="AUTHORITATIVE_PROVIDER",
                billable_eligible=True,
            ),
            RuntimeUsageDimension(
                dimension_id="upstream_cost",
                unit="usd",
                availability="UNAVAILABLE",
                authority="UNAVAILABLE",
            ),
        ],
        observed_at=datetime.now(timezone.utc).isoformat(),
        runtime_signature="runtime-signed",
    )
    ack = service.record_usage_report(connection.runtime_connection_id, report)
    duplicate = service.record_usage_report(connection.runtime_connection_id, report)

    assert ack.status == "ACCEPTED"
    assert duplicate.status == "DUPLICATE"
    restored = RuntimeProtocolStore(state_store)
    assert restored.usage_reports[report.usage_report_id].report_hash == report.report_hash
    assert restored.requests[request.request_id].request_hash == request.semantic_hash()


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
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
    ready = service.record_recovery_result(connection.runtime_connection_id, result)
    assert ready.connection_state == "READY"
    assert service.store.recovery_results[plan.plan_id].result_hash == result.result_hash
    restored = RuntimeProtocolStore(state_store)
    assert restored.recovery_results[plan.plan_id].result_hash == result.result_hash


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
    )
    plan = service.build_recovery_plan(connection.runtime_connection_id, state)
    result = RuntimeRecoveryResult(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        route_generation=5,
        plan_id=plan.plan_id,
        remaining_conflicts=["request-unknown"],
        completed_at=datetime.now(timezone.utc).isoformat(),
    )

    recovering = service.record_recovery_result(
        connection.runtime_connection_id,
        result,
    )

    assert recovering.connection_state == "RECOVERING"


def test_unavailable_usage_cannot_be_encoded_as_zero() -> None:
    with pytest.raises(ValueError, match="unavailable Usage"):
        RuntimeUsageDimension(
            dimension_id="tokens",
            unit="token",
            value=0,
            availability="UNAVAILABLE",
            authority="UNAVAILABLE",
        )
