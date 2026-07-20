from datetime import datetime, timedelta, timezone

import pytest

from aidn_hypervisor.dispatcher import (
    DispatcherError,
    DispatcherRouteLifecycle,
    DispatcherStore,
    DispatcherRoute,
    NetworkDispatcher,
    NetworkMessage,
    bind_plugin_control_route,
    bind_runtime_route,
    bind_remote_runtime_route,
    bind_session_route,
    canonical_payload_hash,
)
from aidn_hypervisor.dispatcher.models import canonical_payload_bytes
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.providers.models import (
    PluginPermission,
    ProviderPluginManifest,
    RuntimeBinding,
)
from aidn_hypervisor.sessions.models import EndpointSession


def _message(
    *,
    message_id: str = "msg-1",
    route_generation: int = 1,
    runtime_generation: int | None = None,
    network_revision: str = "rev-1",
    payload: dict | None = None,
    channel_class: str = "VALIDATION",
    message_type: str = "VALIDATION_REPORT_TRANSFER",
    source_subject: dict | None = None,
    destination_subject: dict | None = None,
) -> NetworkMessage:
    body = payload or {"value": "ok"}
    now = datetime.now(timezone.utc)
    return NetworkMessage(
        message_id=message_id,
        message_type=message_type,
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision=network_revision,
        channel_id="validation-1",
        channel_class=channel_class,
        source_subject=source_subject or {"subject_type": "SERVICE", "subject_id": "validator-1"},
        destination_subject=destination_subject or {"subject_type": "ENDPOINT", "subject_id": "ep-1"},
        source_sequence=1,
        route_generation=route_generation,
        runtime_generation=runtime_generation,
        created_at=now.isoformat(),
        expiration=(now + timedelta(minutes=5)).isoformat(),
        payload_hash=canonical_payload_hash(body),
        payload_length=len(canonical_payload_bytes(body)),
        payload=body,
    )


def _dispatcher(*, maximum_queue_messages: int = 2):
    received: list[dict] = []
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
        maximum_queue_messages=maximum_queue_messages,
    )
    route = DispatcherRoute(
        destination_type="ENDPOINT",
        destination_id="ep-1",
        route_type="LOCAL_PROTOCOL_HANDLER",
        route_generation=1,
        allowed_source_types={"SERVICE"},
        allowed_channel_classes={"VALIDATION"},
        allowed_message_types={"VALIDATION_REPORT_TRANSFER"},
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    dispatcher.register_local_route(route, lambda payload: received.append(payload) or {"ok": True})
    return dispatcher, received


def test_dispatcher_queues_delivers_and_deduplicates_message() -> None:
    dispatcher, received = _dispatcher()
    message = _message()

    queued = dispatcher.submit(message)
    delivered, result = dispatcher.drain_once()
    duplicate = dispatcher.submit(message)

    assert queued.delivery_state == "QUEUED"
    assert delivered.delivery_state == "APPLICATION_ACCEPTED"
    assert result == {"ok": True}
    assert received == [{"value": "ok"}]
    assert duplicate.delivery_state == "DUPLICATE"


def test_dispatcher_rejects_stale_route_generation_before_handler() -> None:
    dispatcher, received = _dispatcher()

    with pytest.raises(DispatcherError) as error:
        dispatcher.submit(_message(route_generation=2))

    assert error.value.code == "ROUTE_GENERATION_MISMATCH"
    assert received == []
    assert dispatcher.list_dead_letters()[0].failure_stage == "routing"


def test_dispatcher_revalidates_route_generation_before_delivery() -> None:
    dispatcher, received = _dispatcher()
    dispatcher.submit(_message())
    dispatcher.register_local_route(
        DispatcherRoute(
            destination_type="ENDPOINT",
            destination_id="ep-1",
            route_type="LOCAL_PROTOCOL_HANDLER",
            route_generation=2,
            allowed_source_types={"SERVICE"},
            allowed_channel_classes={"VALIDATION"},
            allowed_message_types={"VALIDATION_REPORT_TRANSFER"},
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
        lambda payload: received.append(payload),
    )

    with pytest.raises(DispatcherError) as error:
        dispatcher.drain_once()

    assert error.value.code == "ROUTE_GENERATION_MISMATCH"
    assert received == []


def test_dispatcher_enforces_domain_authorization_and_bounded_queue() -> None:
    dispatcher, _ = _dispatcher(maximum_queue_messages=1)

    with pytest.raises(DispatcherError) as revision_error:
        dispatcher.submit(_message(network_revision="rev-old"))
    assert revision_error.value.code == "NETWORK_REVISION_MISMATCH"

    dispatcher.submit(_message(message_id="msg-valid"))
    with pytest.raises(DispatcherError) as queue_error:
        dispatcher.submit(_message(message_id="msg-overflow"))
    assert queue_error.value.code == "QUEUE_FULL"


def test_dispatcher_rejects_conflicting_processed_replay() -> None:
    dispatcher, _ = _dispatcher()
    dispatcher.submit(_message())
    dispatcher.drain_once()

    with pytest.raises(DispatcherError) as error:
        dispatcher.submit(_message(payload={"value": "changed"}))

    assert error.value.code == "MESSAGE_REPLAYED"


def test_dispatcher_restores_queue_and_persistent_replay_state(tmp_path) -> None:
    state_store = FileStateStore(tmp_path / "state.json")
    received: list[dict] = []
    first = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
        store=DispatcherStore(state_store),
    )
    route = DispatcherRoute(
        destination_type="ENDPOINT",
        destination_id="ep-1",
        route_type="LOCAL_PROTOCOL_HANDLER",
        route_generation=1,
        allowed_source_types={"SERVICE"},
        allowed_channel_classes={"VALIDATION"},
        allowed_message_types={"VALIDATION_REPORT_TRANSFER"},
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    first.register_local_route(route, lambda payload: received.append(payload))
    message = _message(message_id="durable-msg")
    first.submit(message)

    restored = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
        store=DispatcherStore(state_store),
    )
    restored.register_local_route(
        restored.store.routes[("ENDPOINT", "ep-1")],
        lambda payload: received.append(payload),
    )
    delivered, _ = restored.drain_once()
    duplicate = restored.submit(message)

    assert delivered.delivery_state == "APPLICATION_ACCEPTED"
    assert received == [{"value": "ok"}]
    assert duplicate.delivery_state == "DUPLICATE"


def test_runtime_and_plugin_control_routes_are_scoped_by_binding_and_permissions() -> None:
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
    )
    binding = RuntimeBinding(
        runtime_binding_id="rtb-1",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="llm.chat",
        capability_version="1",
        capability_definition_hash="cap-1",
        plugin_id="plugin-1",
        compatibility_bundle_id="bundle-1",
        status="ready",
    )
    bind_runtime_route(dispatcher, binding, lambda payload: payload, route_generation=1)
    runtime_message = _message(
        message_id="runtime-1",
        runtime_generation=1,
        channel_class="RUNTIME",
        message_type="RUNTIME_EXECUTION_REQUEST",
        source_subject={"subject_type": "ENDPOINT", "subject_id": "ep-1"},
        destination_subject={"subject_type": "RUNTIME", "subject_id": "rtb-1"},
    )
    assert dispatcher.submit(runtime_message).delivery_state == "QUEUED"

    manifest = ProviderPluginManifest(
        plugin_id="plugin-1",
        plugin_version="1",
        display_name="Plugin",
        publisher="test",
        package_digest="digest",
        required_permissions=[
            PluginPermission(
                permission_id="private_network",
                label="Private network",
                reason="Provider health",
            )
        ],
    )
    bind_plugin_control_route(
        dispatcher,
        manifest,
        lambda payload: payload,
        provider_instance_id="pi-1",
        approved_permissions={"private_network"},
        route_generation=1,
    )
    allowed = _message(
        message_id="plugin-1",
        channel_class="PLUGIN_CONTROL",
        message_type="PLUGIN_PROVIDER_HEALTH",
        source_subject={"subject_type": "HYPERVISOR", "subject_id": "local"},
        destination_subject={"subject_type": "PROVIDER_PLUGIN", "subject_id": "pi-1"},
    )
    assert dispatcher.submit(allowed).delivery_state == "QUEUED"

    denied = _message(
        message_id="plugin-2",
        channel_class="PLUGIN_CONTROL",
        message_type="PLUGIN_DIAGNOSTICS",
        source_subject={"subject_type": "HYPERVISOR", "subject_id": "local"},
        destination_subject={"subject_type": "PROVIDER_PLUGIN", "subject_id": "pi-1"},
    )
    with pytest.raises(DispatcherError) as error:
        dispatcher.submit(denied)
    assert error.value.code == "MESSAGE_PROFILE_UNSUPPORTED"


def test_remote_runtime_route_delivers_only_scoped_runtime_messages() -> None:
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
    )
    binding = RuntimeBinding(
        runtime_binding_id="rtb-remote",
        runtime_id="runtime-remote",
        runtime_generation=3,
        provider_instance_id="pi-remote",
        model_deployment_id="md-remote",
        capability_id="llm.chat",
        capability_version="1",
        capability_definition_hash="cap-remote",
        plugin_id="llama.cpp",
        compatibility_bundle_id="bundle-remote",
        status="ready",
    )
    delivered = []
    route = bind_remote_runtime_route(
        dispatcher,
        binding,
        lambda payload: delivered.append(payload) or {"forwarded": True},
        route_generation=4,
    )
    message = _message(
        message_id="remote-runtime-1",
        route_generation=route.route_generation,
        runtime_generation=binding.runtime_generation,
        channel_class="RUNTIME",
        message_type="RUNTIME_EXECUTE",
        source_subject={"subject_type": "HYPERVISOR", "subject_id": "local"},
        destination_subject={"subject_type": "RUNTIME", "subject_id": binding.runtime_id},
    )

    assert dispatcher.submit(message).delivery_state == "QUEUED"
    record, result = dispatcher.drain_once()

    assert route.route_type == "REMOTE_RUNTIME"
    assert record.delivery_state == "APPLICATION_ACCEPTED"
    assert result == {"forwarded": True}
    assert delivered == [message.payload]
    with pytest.raises(ValueError, match="local route type"):
        dispatcher.register_local_route(route, lambda _: None)


def test_provider_inventory_lifecycle_rotates_and_revokes_scoped_routes() -> None:
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
    )
    lifecycle = DispatcherRouteLifecycle(dispatcher)
    binding = RuntimeBinding(
        runtime_binding_id="rtb-1",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="llm.chat",
        capability_version="1",
        capability_definition_hash="cap-1",
        plugin_id="plugin-1",
        compatibility_bundle_id="bundle-1",
        status="ready",
    )

    initial = lifecycle.sync_runtime_binding(binding, lambda payload: payload)
    compatibility_only = lifecycle.sync_runtime_binding(
        binding.model_copy(update={"compatibility_bundle_id": "bundle-2"}),
        lambda payload: payload,
    )
    changed_binding = RuntimeBinding.model_validate(
        {
            **binding.model_dump(mode="json"),
            "runtime_generation": 2,
            "adapter_version": "2",
            "runtime_configuration_hash": None,
        }
    )
    changed = lifecycle.sync_runtime_binding(changed_binding, lambda payload: payload)
    revoked = lifecycle.sync_runtime_binding(
        RuntimeBinding.model_validate(
            {
                **changed_binding.model_dump(mode="json"),
                "status": "disabled",
                "operational_state": "REVOKED",
            }
        ),
        None,
    )

    assert initial is not None and initial.route_generation == 1
    assert compatibility_only is not None and compatibility_only.route_generation == 1
    assert changed is not None and changed.route_generation == 2
    assert revoked is not None
    assert revoked.route_generation == 3
    assert revoked.route_state == "REVOKED"

    stale_runtime_message = _message(
        message_id="runtime-revoked",
        route_generation=2,
        runtime_generation=1,
        channel_class="RUNTIME",
        message_type="RUNTIME_EXECUTION_REQUEST",
        source_subject={"subject_type": "ENDPOINT", "subject_id": "ep-1"},
        destination_subject={"subject_type": "RUNTIME", "subject_id": "rtb-1"},
    )
    with pytest.raises(DispatcherError) as error:
        dispatcher.submit(stale_runtime_message)
    assert error.value.code == "ROUTE_REVOKED"


def test_runtime_route_rejects_stale_runtime_generation() -> None:
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
    )
    binding = RuntimeBinding(
        runtime_binding_id="rtb-generation",
        runtime_id="runtime-generation",
        runtime_generation=2,
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="llm.chat",
        capability_version="1",
        capability_definition_hash="cap-1",
        plugin_id="plugin-1",
        compatibility_bundle_id="bundle-1",
        status="ready",
    )
    bind_runtime_route(dispatcher, binding, lambda payload: payload, route_generation=3)

    stale = _message(
        message_id="runtime-stale-generation",
        route_generation=3,
        runtime_generation=1,
        channel_class="RUNTIME",
        message_type="RUNTIME_EXECUTION_REQUEST",
        source_subject={"subject_type": "ENDPOINT", "subject_id": "ep-1"},
        destination_subject={
            "subject_type": "RUNTIME",
            "subject_id": "runtime-generation",
        },
    )

    with pytest.raises(DispatcherError) as error:
        dispatcher.submit(stale)
    assert error.value.code == "RUNTIME_GENERATION_MISMATCH"


def test_provider_inventory_lifecycle_rotates_plugin_route_on_permission_change() -> None:
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
    )
    lifecycle = DispatcherRouteLifecycle(dispatcher)
    manifest = ProviderPluginManifest(
        plugin_id="plugin-1",
        plugin_version="1",
        display_name="Plugin",
        publisher="test",
        package_digest="digest",
        required_permissions=[
            PluginPermission(
                permission_id="private_network",
                label="Private network",
                reason="Provider health",
            ),
            PluginPermission(
                permission_id="diagnostics",
                label="Diagnostics",
                reason="Support bundle",
            ),
        ],
    )

    first = lifecycle.sync_plugin_control(
        manifest,
        provider_instance_id="pi-1",
        approved_permissions={"private_network"},
        handler=lambda payload: payload,
    )
    expanded = lifecycle.sync_plugin_control(
        manifest,
        provider_instance_id="pi-1",
        approved_permissions={"private_network", "diagnostics"},
        handler=lambda payload: payload,
    )
    revoked = lifecycle.sync_plugin_control(
        manifest,
        provider_instance_id="pi-1",
        approved_permissions=set(),
        handler=None,
    )

    assert first is not None and first.route_generation == 1
    assert expanded is not None and expanded.route_generation == 2
    assert "PLUGIN_DIAGNOSTICS" in expanded.allowed_message_types
    assert revoked is not None
    assert revoked.route_generation == 3
    assert revoked.route_state == "REVOKED"


def test_session_route_binds_contract_configuration_and_subject_identity() -> None:
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
    )
    session = EndpointSession(
        session_id="sess-1",
        endpoint_id="ep-1",
        client_wallet="wallet-1",
        provider_wallet="wallet-provider",
        node_id="node-1",
        status="active",
        created_at=datetime.now(timezone.utc).isoformat(),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        idle_deadline_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        deposit_locked_q=10.0,
        queue_policy_snapshot="busy",
        endpoint_configuration_hash="cfg-accepted",
        session_contract_hash="sha256:contract-accepted",
    )
    route = bind_session_route(dispatcher, session, lambda payload: payload, route_generation=1)
    assert route.configuration_hash == "cfg-accepted"
    assert route.session_contract_hash == "sha256:contract-accepted"

    allowed = _message(
        message_id="session-request",
        channel_class="SESSION_DATA",
        message_type="SESSION_REQUEST",
        source_subject={"subject_type": "CONSUMER_SESSION", "subject_id": "sess-1"},
        destination_subject={"subject_type": "SESSION", "subject_id": "sess-1"},
    )
    assert dispatcher.submit(allowed).delivery_state == "QUEUED"

    wrong_consumer = _message(
        message_id="session-wrong-consumer",
        channel_class="SESSION_DATA",
        message_type="SESSION_REQUEST",
        source_subject={"subject_type": "CONSUMER_SESSION", "subject_id": "sess-other"},
        destination_subject={"subject_type": "SESSION", "subject_id": "sess-1"},
    )
    with pytest.raises(DispatcherError) as error:
        dispatcher.submit(wrong_consumer)
    assert error.value.code == "SOURCE_NOT_AUTHORIZED"


def test_queued_session_route_allows_control_but_not_data() -> None:
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
    )
    session = EndpointSession(
        session_id="sess-queued",
        endpoint_id="ep-1",
        client_wallet="wallet-1",
        provider_wallet="wallet-provider",
        node_id="node-1",
        status="queued",
        created_at=datetime.now(timezone.utc).isoformat(),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        idle_deadline_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        deposit_locked_q=10.0,
        queue_policy_snapshot="queue",
        endpoint_configuration_hash="cfg-accepted",
        session_contract_hash="sha256:contract-accepted",
    )
    bind_session_route(dispatcher, session, lambda payload: payload, route_generation=1)
    control = _message(
        message_id="session-close",
        channel_class="SESSION_CONTROL",
        message_type="SESSION_CLOSE",
        source_subject={"subject_type": "CONSUMER_SESSION", "subject_id": "sess-queued"},
        destination_subject={"subject_type": "SESSION", "subject_id": "sess-queued"},
    )
    assert dispatcher.submit(control).delivery_state == "QUEUED"
    data = _message(
        message_id="session-queued-data",
        channel_class="SESSION_DATA",
        message_type="SESSION_REQUEST",
        source_subject={"subject_type": "CONSUMER_SESSION", "subject_id": "sess-queued"},
        destination_subject={"subject_type": "SESSION", "subject_id": "sess-queued"},
    )
    with pytest.raises(DispatcherError) as error:
        dispatcher.submit(data)
    assert error.value.code == "CHANNEL_NOT_AUTHORIZED"


def test_session_lifecycle_rotates_on_activation_and_revokes_on_close() -> None:
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
    )
    lifecycle = DispatcherRouteLifecycle(dispatcher)
    session = EndpointSession(
        session_id="sess-lifecycle",
        endpoint_id="ep-1",
        client_wallet="wallet-1",
        provider_wallet="wallet-provider",
        node_id="node-1",
        status="queued",
        created_at=datetime.now(timezone.utc).isoformat(),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        idle_deadline_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        deposit_locked_q=10.0,
        queue_policy_snapshot="queue",
        endpoint_configuration_hash="cfg-accepted",
        session_contract_hash="sha256:contract-accepted",
    )

    queued = lifecycle.sync_session(session, lambda payload: payload)
    active = lifecycle.sync_session(
        session.model_copy(update={"status": "active"}),
        lambda payload: payload,
    )
    closed = lifecycle.sync_session(
        session.model_copy(update={"status": "closed"}),
        None,
    )

    assert queued is not None and queued.route_generation == 1
    assert active is not None and active.route_generation == 2
    assert "SESSION_DATA" in active.allowed_channel_classes
    assert closed is not None and closed.route_generation == 3
    assert closed.route_state == "REVOKED"


def test_dispatcher_derives_priority_from_message_policy() -> None:
    delivered: list[str] = []
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
    )
    route = DispatcherRoute(
        destination_type="SESSION",
        destination_id="sess-1",
        route_type="LOCAL_PROTOCOL_HANDLER",
        route_generation=1,
        allowed_source_types={"CONSUMER_SESSION"},
        allowed_channel_classes={"SESSION_CONTROL", "SESSION_DATA"},
        allowed_message_types={"SESSION_CLOSE", "SESSION_REQUEST"},
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    dispatcher.register_local_route(route, lambda payload: delivered.append(payload["kind"]))
    request = _message(
        message_id="interactive-request",
        channel_class="SESSION_DATA",
        message_type="SESSION_REQUEST",
        payload={"kind": "request"},
        source_subject={"subject_type": "CONSUMER_SESSION", "subject_id": "sess-1"},
        destination_subject={"subject_type": "SESSION", "subject_id": "sess-1"},
    )
    close = _message(
        message_id="close-priority",
        channel_class="SESSION_CONTROL",
        message_type="SESSION_CLOSE",
        payload={"kind": "close"},
        source_subject={"subject_type": "CONSUMER_SESSION", "subject_id": "sess-1"},
        destination_subject={"subject_type": "SESSION", "subject_id": "sess-1"},
    )
    dispatcher.submit(request)
    dispatcher.submit(close)

    dispatcher.drain_once()
    dispatcher.drain_once()

    assert delivered == ["close", "request"]
