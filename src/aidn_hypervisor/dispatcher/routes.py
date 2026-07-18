from datetime import datetime, timezone
from typing import Callable

from aidn_hypervisor.dispatcher.models import DispatcherRoute
from aidn_hypervisor.providers.models import ProviderPluginManifest, RuntimeBinding


RUNTIME_MESSAGE_TYPES = {
    "RUNTIME_EXECUTION_REQUEST",
    "RUNTIME_CANCELLATION",
    "RUNTIME_RECOVERY_STATE",
}

PLUGIN_CONTROL_PERMISSION_TYPES = {
    "PLUGIN_INSTALLATION_PROGRESS": "container_management",
    "PLUGIN_PROVIDER_HEALTH": "private_network",
    "PLUGIN_MODEL_DISCOVERY_RESULT": "model_storage",
    "PLUGIN_RUNTIME_BINDING_REQUEST": "runtime_control",
    "PLUGIN_DIAGNOSTICS": "diagnostics",
}


def runtime_route(
    binding: RuntimeBinding,
    *,
    route_generation: int,
) -> DispatcherRoute:
    if binding.status != "ready":
        raise ValueError("only ready Runtime Bindings may receive RUNTIME routes")
    return DispatcherRoute(
        destination_type="RUNTIME",
        destination_id=binding.runtime_binding_id,
        route_type="LOCAL_RUNTIME",
        route_generation=route_generation,
        allowed_source_types={"HYPERVISOR", "ENDPOINT"},
        allowed_channel_classes={"RUNTIME"},
        allowed_message_types=set(RUNTIME_MESSAGE_TYPES),
        runtime_binding_hash=binding.compatibility_bundle_id,
        created_at=datetime.now(timezone.utc).isoformat(),
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
        created_at=datetime.now(timezone.utc).isoformat(),
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
