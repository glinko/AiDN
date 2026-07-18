"""Provider Inventory to Dispatcher route lifecycle bridge."""

from collections.abc import Callable, Iterable

from aidn_hypervisor.dispatcher.models import DispatcherRoute
from aidn_hypervisor.dispatcher.routes import plugin_control_route, runtime_route
from aidn_hypervisor.providers.models import ProviderPluginManifest, RuntimeBinding


RouteHandler = Callable[[dict], object]


class DispatcherRouteLifecycle:
    """Synchronize local Dispatcher routes from Provider Inventory state.

    The bridge deliberately owns route lifecycle only. It does not give plugin
    code direct access to the Dispatcher or infer permissions from a package.
    Callers supply the operator-approved permission scope for every provider.
    """

    def __init__(self, dispatcher) -> None:
        self.dispatcher = dispatcher

    def sync_runtime_binding(
        self,
        binding: RuntimeBinding,
        handler: RouteHandler | None,
    ) -> DispatcherRoute | None:
        destination_type = "RUNTIME"
        previous = self.dispatcher.route(
            destination_type=destination_type,
            destination_id=binding.runtime_binding_id,
        )
        if binding.status != "ready":
            return self.dispatcher.revoke_route(
                destination_type=destination_type,
                destination_id=binding.runtime_binding_id,
            )
        if handler is None:
            raise ValueError("ready Runtime Binding requires a local route handler")

        desired = runtime_route(
            binding,
            route_generation=1 if previous is None else previous.route_generation + 1,
        )
        if previous is not None and self._materially_equal(previous, desired):
            # Handler references are process-local and must be rebound after restart.
            self.dispatcher.register_local_route(previous, handler)
            return previous
        self.dispatcher.register_local_route(desired, handler)
        return desired

    def sync_plugin_control(
        self,
        manifest: ProviderPluginManifest,
        *,
        provider_instance_id: str,
        approved_permissions: set[str],
        handler: RouteHandler | None,
    ) -> DispatcherRoute | None:
        destination_type = "PROVIDER_PLUGIN"
        previous = self.dispatcher.route(
            destination_type=destination_type,
            destination_id=provider_instance_id,
        )
        try:
            desired = plugin_control_route(
                manifest,
                provider_instance_id=provider_instance_id,
                approved_permissions=approved_permissions,
                route_generation=(
                    1 if previous is None else previous.route_generation + 1
                ),
            )
        except ValueError:
            return self.dispatcher.revoke_route(
                destination_type=destination_type,
                destination_id=provider_instance_id,
            )
        if handler is None:
            raise ValueError("active Provider Plugin route requires a local handler")
        if previous is not None and self._materially_equal(previous, desired):
            self.dispatcher.register_local_route(previous, handler)
            return previous
        self.dispatcher.register_local_route(desired, handler)
        return desired

    def revoke_missing_runtime_bindings(
        self, active_runtime_binding_ids: Iterable[str]
    ) -> list[DispatcherRoute]:
        active_ids = set(active_runtime_binding_ids)
        revoked: list[DispatcherRoute] = []
        for route in list(self.dispatcher.store.routes.values()):
            if route.destination_type != "RUNTIME" or route.destination_id in active_ids:
                continue
            result = self.dispatcher.revoke_route(
                destination_type=route.destination_type,
                destination_id=route.destination_id,
            )
            if result is not None:
                revoked.append(result)
        return revoked

    @staticmethod
    def _materially_equal(left: DispatcherRoute, right: DispatcherRoute) -> bool:
        excluded = {"route_generation", "route_state", "created_at"}
        return left.model_dump(exclude=excluded) == right.model_dump(exclude=excluded)
