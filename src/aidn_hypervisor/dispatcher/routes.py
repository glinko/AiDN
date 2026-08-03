from collections.abc import Callable
from datetime import UTC, datetime

from aidn_hypervisor.dispatcher.models import DispatcherRoute
from aidn_hypervisor.providers.models import ProviderPluginManifest, RuntimeBinding
from aidn_hypervisor.sessions.models import EndpointSession

RUNTIME_MESSAGE_TYPES = {
    "RUNTIME_EXECUTE",
    "RUNTIME_USAGE_ACK",
    "RUNTIME_CANCEL",
    "RUNTIME_STATE_RESET",
    "RUNTIME_RECOVERY_PLAN",
    "RUNTIME_DRAIN",
    "RUNTIME_SHUTDOWN",
    # Compatibility alias for the pre-RFC-0054 execution projection.
    "RUNTIME_EXECUTION_REQUEST",
    "RUNTIME_CANCELLATION",
    "RUNTIME_RECOVERY_STATE",
    "RUNTIME_DRAIN_STATUS",
    "RUNTIME_DRAIN_COMPLETE",
}

RUNTIME_INGRESS_MESSAGE_TYPES = {
    "RUNTIME_READY",
    "RUNTIME_HEALTH",
    "RUNTIME_CAPACITY",
    "RUNTIME_RESULT",
    "RUNTIME_CANCEL_RESULT",
    "RUNTIME_STREAM_OPEN",
    "RUNTIME_STREAM_CHUNK",
    "RUNTIME_STREAM_CLOSE",
    "RUNTIME_ARTIFACT_DECLARE",
    "RUNTIME_STATE_CHECKPOINT",
    "RUNTIME_RECOVERY_STATE",
}

PLUGIN_CONTROL_PERMISSION_TYPES = {
    "PLUGIN_INSTALLATION_PROGRESS": "container_management",
    "PLUGIN_PROVIDER_HEALTH": "private_network",
    "PLUGIN_MODEL_DISCOVERY_RESULT": "model_storage",
    "PLUGIN_RUNTIME_BINDING_REQUEST": "runtime_control",
    "PLUGIN_DIAGNOSTICS": "diagnostics",
}

SESSION_CONTROL_MESSAGE_TYPES = {
    "SESSION_ACCEPT",
    "SESSION_REJECT",
    "SESSION_DEPOSIT_EXTENSION",
    "SESSION_CLOSE",
    "SESSION_RECOVERY",
    "SESSION_SETTLEMENT_STATUS",
}

SESSION_DATA_MESSAGE_TYPES = {
    "SESSION_REQUEST",
    "SESSION_RESPONSE_STREAM",
    "SESSION_CAPABILITY_EVENT",
    "SESSION_ARTIFACT_REFERENCE",
}


def runtime_route(
    binding: RuntimeBinding,
    *,
    route_generation: int,
) -> DispatcherRoute:
    binding = RuntimeBinding.model_validate(binding.model_dump(mode="json"))
    if binding.operational_state != "READY":
        raise ValueError("only ready Runtime Bindings may receive RUNTIME routes")
    return DispatcherRoute(
        destination_type="RUNTIME",
        destination_id=binding.runtime_id,
        route_type="LOCAL_RUNTIME",
        route_generation=route_generation,
        runtime_generation=binding.runtime_generation,
        allowed_source_types={"HYPERVISOR", "ENDPOINT"},
        allowed_channel_classes={"RUNTIME"},
        allowed_message_types=set(RUNTIME_MESSAGE_TYPES),
        runtime_binding_hash=binding.binding_hash(),
        created_at=datetime.now(UTC).isoformat(),
    )


def remote_runtime_route(
    binding: RuntimeBinding,
    *,
    route_generation: int,
) -> DispatcherRoute:
    """Create the scoped Dispatcher route for one direct remote Runtime."""
    binding = RuntimeBinding.model_validate(binding.model_dump(mode="json"))
    if binding.operational_state != "READY":
        raise ValueError("only ready Runtime Bindings may receive RUNTIME routes")
    return DispatcherRoute(
        destination_type="RUNTIME",
        destination_id=binding.runtime_id,
        route_type="REMOTE_RUNTIME",
        route_generation=route_generation,
        runtime_generation=binding.runtime_generation,
        allowed_source_types={"HYPERVISOR", "ENDPOINT"},
        allowed_channel_classes={"RUNTIME"},
        allowed_message_types=set(RUNTIME_MESSAGE_TYPES),
        runtime_binding_hash=binding.binding_hash(),
        created_at=datetime.now(UTC).isoformat(),
    )


def runtime_ingress_route(
    binding: RuntimeBinding,
    *,
    route_generation: int,
) -> DispatcherRoute:
    """Scoped Runtime-to-Hypervisor event route for one approved binding."""
    binding = RuntimeBinding.model_validate(binding.model_dump(mode="json"))
    if binding.operational_state != "READY":
        raise ValueError("only ready Runtime Bindings may send Runtime ingress events")
    return DispatcherRoute(
        destination_type="HYPERVISOR_RUNTIME_INGRESS",
        destination_id=binding.runtime_id,
        route_type="LOCAL_PROTOCOL_HANDLER",
        route_generation=route_generation,
        runtime_generation=binding.runtime_generation,
        allowed_source_types={"RUNTIME"},
        allowed_source_ids={binding.runtime_id},
        allowed_channel_classes={"RUNTIME"},
        allowed_message_types=set(RUNTIME_INGRESS_MESSAGE_TYPES),
        runtime_binding_hash=binding.binding_hash(),
        created_at=datetime.now(UTC).isoformat(),
    )


def plugin_control_route(
    manifest: ProviderPluginManifest,
    *,
    provider_instance_id: str,
    approved_permissions: set[str],
    route_generation: int,
) -> DispatcherRoute:
    declared_permissions = {
        permission.permission_id for permission in manifest.required_permissions
    }
    granted_permissions = declared_permissions.intersection(approved_permissions)
    allowed_messages = {
        message_type
        for message_type, required_permission in PLUGIN_CONTROL_PERMISSION_TYPES.items()
        if required_permission in granted_permissions
    }
    if not allowed_messages:
        raise ValueError("plugin has no approved PLUGIN_CONTROL permissions")
    return DispatcherRoute(
        destination_type="PROVIDER_PLUGIN",
        destination_id=provider_instance_id,
        route_type="LOCAL_PLUGIN",
        route_generation=route_generation,
        allowed_source_types={"HYPERVISOR"},
        allowed_channel_classes={"PLUGIN_CONTROL"},
        allowed_message_types=allowed_messages,
        configuration_hash=manifest.manifest_hash,
        created_at=datetime.now(UTC).isoformat(),
    )


def session_route(
    session: EndpointSession,
    *,
    route_generation: int,
) -> DispatcherRoute:
    """Create a route fixed to the Session's accepted contract and Endpoint config."""
    if session.status == "closed":
        raise ValueError("closed Sessions may not receive Dispatcher routes")
    if not session.session_contract_hash:
        raise ValueError("Session route requires a Session Contract hash")
    if not session.endpoint_configuration_hash:
        raise ValueError("Session route requires an accepted Endpoint Configuration Hash")
    allowed_channels = {"SESSION_CONTROL"}
    allowed_messages = set(SESSION_CONTROL_MESSAGE_TYPES)
    if session.status == "active":
        allowed_channels.add("SESSION_DATA")
        allowed_messages.update(SESSION_DATA_MESSAGE_TYPES)
    return DispatcherRoute(
        destination_type="SESSION",
        destination_id=session.session_id,
        route_type="LOCAL_PROTOCOL_HANDLER",
        route_generation=route_generation,
        allowed_source_types={"CONSUMER_SESSION", "ENDPOINT"},
        allowed_source_ids_by_type={
            "CONSUMER_SESSION": {session.session_id},
            "ENDPOINT": {session.endpoint_id},
        },
        allowed_channel_classes=allowed_channels,
        allowed_message_types=allowed_messages,
        configuration_hash=session.endpoint_configuration_hash,
        session_contract_hash=session.session_contract_hash,
        created_at=datetime.now(UTC).isoformat(),
    )


def bind_runtime_route(
    dispatcher,
    binding: RuntimeBinding,
    handler: Callable[[dict], object],
    *,
    route_generation: int,
) -> DispatcherRoute:
    route = runtime_route(binding, route_generation=route_generation)
    dispatcher.register_local_route(route, handler)
    return route


def bind_remote_runtime_route(
    dispatcher,
    binding: RuntimeBinding,
    sender: Callable[[dict], object],
    *,
    route_generation: int,
) -> DispatcherRoute:
    route = remote_runtime_route(binding, route_generation=route_generation)
    dispatcher.register_remote_route(route, sender)
    return route


def bind_runtime_ingress_route(
    dispatcher,
    binding: RuntimeBinding,
    handler: Callable[[dict], object],
    *,
    route_generation: int,
) -> DispatcherRoute:
    route = runtime_ingress_route(binding, route_generation=route_generation)
    dispatcher.register_local_route(route, handler)
    return route


def bind_plugin_control_route(
    dispatcher,
    manifest: ProviderPluginManifest,
    handler: Callable[[dict], object],
    *,
    provider_instance_id: str,
    approved_permissions: set[str],
    route_generation: int,
) -> DispatcherRoute:
    route = plugin_control_route(
        manifest,
        provider_instance_id=provider_instance_id,
        approved_permissions=approved_permissions,
        route_generation=route_generation,
    )
    dispatcher.register_local_route(route, handler)
    return route


VALIDATION_MESSAGE_TYPES = {
    "VALIDATION_REPORT_TRANSFER",
}

VALIDATION_CUSTODY_MESSAGE_TYPES = {
    "VALIDATION_REPORT_CUSTODY_GET",
}

VALIDATION_OBSERVER_MESSAGE_TYPES = {
    "VALIDATION_REPORT_CUSTODY_CHALLENGE",
}


def validation_route(
    *,
    destination_id: str = "validation_handler",
    route_generation: int,
    hypervisor_key: str | None = None,
) -> DispatcherRoute:
    """Create a route for VALIDATION-channel messages from validators.

    When ``hypervisor_key`` is provided, the route enforces assignment-key
    validation on every submitted message (canonical Hypervisor-key
    registration).
    """
    return DispatcherRoute(
        destination_type="VALIDATION_TARGET",
        destination_id=destination_id,
        route_type="LOCAL_PROTOCOL_HANDLER",
        route_generation=route_generation,
        allowed_source_types={"VALIDATOR"},
        allowed_channel_classes={"VALIDATION"},
        allowed_message_types=set(VALIDATION_MESSAGE_TYPES),
        hypervisor_key=hypervisor_key,
        created_at=datetime.now(UTC).isoformat(),
    )


def bind_validation_route(
    dispatcher,
    handler: Callable[[dict], object],
    *,
    destination_id: str = "validation_handler",
    route_generation: int,
    hypervisor_key: str | None = None,
) -> DispatcherRoute:
    """Bind the VALIDATION-channel route and optionally register the canonical
    Hypervisor key.

    When ``hypervisor_key`` is supplied the dispatcher will reject any
    VALIDATION_REPORT_TRANSFER message that does not carry a matching
    ``assignment_key``.
    """
    route = validation_route(
        destination_id=destination_id,
        route_generation=route_generation,
        hypervisor_key=hypervisor_key,
    )
    dispatcher.register_local_route(route, handler)
    return route


def validation_custody_route(
    *,
    destination_id: str = "validation_custody_handler",
    route_generation: int,
    hypervisor_key: str | None = None,
) -> DispatcherRoute:
    """Create a scoped RFC-0042 route for authenticated custody retrieval."""
    return DispatcherRoute(
        destination_type="VALIDATION_CUSTODY_TARGET",
        destination_id=destination_id,
        route_type="LOCAL_PROTOCOL_HANDLER",
        route_generation=route_generation,
        allowed_source_types={
            "ENDPOINT",
            "HYPERVISOR",
            "VALIDATION_AUTHORITY",
            "VALIDATOR",
        },
        allowed_channel_classes={"VALIDATION"},
        allowed_message_types=set(VALIDATION_CUSTODY_MESSAGE_TYPES),
        hypervisor_key=hypervisor_key,
        created_at=datetime.now(UTC).isoformat(),
    )


def bind_validation_custody_route(
    dispatcher,
    handler: Callable[..., object],
    *,
    destination_id: str = "validation_custody_handler",
    route_generation: int,
    hypervisor_key: str | None = None,
) -> DispatcherRoute:
    route = validation_custody_route(
        destination_id=destination_id,
        route_generation=route_generation,
        hypervisor_key=hypervisor_key,
    )
    dispatcher.register_local_route(route, handler, pass_message_context=True)
    return route


def validation_observer_route(
    *,
    observer_id: str,
    route_generation: int,
    allowed_source_ids: set[str] | None = None,
    hypervisor_key: str | None = None,
) -> DispatcherRoute:
    """Create a route for one observer's scheduled custody challenge queue."""
    if not observer_id.strip():
        raise ValueError("observer_id is required")
    return DispatcherRoute(
        destination_type="VALIDATION_OBSERVER",
        destination_id=observer_id,
        route_type="LOCAL_PROTOCOL_HANDLER",
        route_generation=route_generation,
        allowed_source_types={"VALIDATION_AUTHORITY", "HYPERVISOR", "VALIDATOR"},
        allowed_source_ids=set(allowed_source_ids or set()),
        allowed_channel_classes={"VALIDATION"},
        allowed_message_types=set(VALIDATION_OBSERVER_MESSAGE_TYPES),
        hypervisor_key=hypervisor_key,
        created_at=datetime.now(UTC).isoformat(),
    )


def bind_validation_observer_route(
    dispatcher,
    handler: Callable[..., object],
    *,
    observer_id: str,
    route_generation: int,
    allowed_source_ids: set[str] | None = None,
    hypervisor_key: str | None = None,
) -> DispatcherRoute:
    route = validation_observer_route(
        observer_id=observer_id,
        route_generation=route_generation,
        allowed_source_ids=allowed_source_ids,
        hypervisor_key=hypervisor_key,
    )
    dispatcher.register_local_route(route, handler, pass_message_context=True)
    return route


def remote_validation_observer_route(
    *,
    observer_id: str,
    route_generation: int,
    allowed_source_ids: set[str] | None = None,
    hypervisor_key: str | None = None,
) -> DispatcherRoute:
    """Create a remote route for an observer reached through authenticated transport."""
    route = validation_observer_route(
        observer_id=observer_id,
        route_generation=route_generation,
        allowed_source_ids=allowed_source_ids,
        hypervisor_key=hypervisor_key,
    )
    return route.model_copy(update={"route_type": "REMOTE_HYPERVISOR"})


def bind_remote_validation_observer_route(
    dispatcher,
    sender: Callable[[dict], object],
    *,
    observer_id: str,
    route_generation: int,
    allowed_source_ids: set[str] | None = None,
    hypervisor_key: str | None = None,
) -> DispatcherRoute:
    route = remote_validation_observer_route(
        observer_id=observer_id,
        route_generation=route_generation,
        allowed_source_ids=allowed_source_ids,
        hypervisor_key=hypervisor_key,
    )
    dispatcher.register_remote_route(route, sender)
    return route


def bind_session_route(
    dispatcher,
    session: EndpointSession,
    handler: Callable[[dict], object],
    *,
    route_generation: int,
) -> DispatcherRoute:
    route = session_route(session, route_generation=route_generation)
    dispatcher.register_local_route(route, handler)
    return route
