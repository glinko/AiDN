from __future__ import annotations

from aidn_hypervisor.plugins.host import PluginHostJsonWireAdapter
from aidn_hypervisor.plugins.host_named_pipe import WindowsNamedPipePluginHostListener
from aidn_hypervisor.plugins.host_unix_socket import UnixSocketPluginHostListener


class ProviderInstallationService:
    """Provider/plugin installation and plugin-host orchestration."""

    def __init__(self, host) -> None:
        self._host = host

    def attach_provider_instance(
        self,
        *,
        plugin_id: str,
        display_name: str,
        configuration: dict,
    ) -> dict:
        instance = self._host.provider_inventory.attach_provider_instance(
            plugin_id=plugin_id,
            display_name=display_name,
            configuration=configuration,
        )
        self._host._persist_state()
        return instance.model_dump(mode="json")

    def list_provider_instances(self) -> list[dict]:
        return [
            instance.model_dump(mode="json")
            for instance in self._host.provider_inventory.list_provider_instances()
        ]

    def list_model_deployments(self) -> list[dict]:
        return [
            deployment.model_dump(mode="json")
            for deployment in self._host.provider_inventory.list_model_deployments()
        ]

    def list_runtime_bindings(self) -> list[dict]:
        return [
            binding.model_dump(mode="json")
            for binding in self._host.provider_inventory.list_runtime_bindings()
        ]

    def build_provider_installation_plan(
        self,
        *,
        plugin_id: str,
        configuration: dict,
    ) -> dict:
        return self._host.provider_inventory.build_installation_plan(
            plugin_id=plugin_id,
            configuration=configuration,
        )

    def approve_provider_installation_plan(
        self,
        plugin_id: str,
        configuration: dict,
        approved_permissions: list[str] | None = None,
        upgrade_acknowledged: bool = False,
        selected_secret_handles: list[dict] | None = None,
        operator_note: str | None = None,
    ) -> dict:
        approval = self._host.provider_inventory.approve_installation_plan(
            plugin_id=plugin_id,
            configuration=configuration,
            approved_permissions=approved_permissions,
            upgrade_acknowledged=upgrade_acknowledged,
            selected_secret_handles=selected_secret_handles,
            operator_note=operator_note,
        )
        self._host._persist_state()
        return approval.model_dump(mode="json")

    def run_provider_installation_diagnostics(
        self,
        plugin_id: str,
        configuration: dict,
        approved_permissions: list[str] | None = None,
        upgrade_acknowledged: bool = False,
        selected_secret_handles: list[dict] | None = None,
    ) -> dict:
        diagnostics = self._host.provider_inventory.run_installation_diagnostics(
            plugin_id=plugin_id,
            configuration=configuration,
            approved_permissions=approved_permissions,
            upgrade_acknowledged=upgrade_acknowledged,
            selected_secret_handles=selected_secret_handles,
        )
        return diagnostics.model_dump(mode="json")

    def apply_provider_installation_approval(self, approval_id: str) -> dict:
        job = self._host.provider_inventory.apply_installation_approval(approval_id)
        self._host._persist_state()
        return job.model_dump(mode="json")

    def rollback_provider_installation_job(self, job_id: str) -> dict:
        job = self._host.provider_inventory.rollback_installation_job(job_id)
        self._host._persist_state()
        return job.model_dump(mode="json")

    def list_provider_installation_approvals(self) -> list[dict]:
        return [
            approval.model_dump(mode="json")
            for approval in self._host.provider_inventory.list_installation_approvals()
        ]

    def list_provider_plugin_releases(self) -> list[dict]:
        return [
            release.model_dump(mode="json")
            for release in self._host.provider_inventory.list_plugin_releases()
        ]

    def provider_plugin_registry_objects(self) -> list[dict]:
        return self._host.provider_inventory.plugin_release_registry_objects()

    def publish_provider_plugin_releases_to_registry(self, registry_service) -> list[dict]:
        return registry_service.ingest_registry_objects(
            self.provider_plugin_registry_objects()
        )

    def list_installed_provider_plugins(self) -> list[dict]:
        return [
            installed_plugin.model_dump(mode="json")
            for installed_plugin in self._host.provider_inventory.list_installed_plugins()
        ]

    def register_provider_plugin_release(
        self,
        *,
        manifest: dict,
        source_reference: str | None = None,
        release_status: str = "AVAILABLE",
    ) -> dict:
        release = self._host.provider_inventory.register_plugin_release(
            manifest_payload=manifest,
            source_reference=source_reference,
            release_status=release_status,
        )
        self._host._persist_state()
        return release.model_dump(mode="json")

    def install_provider_plugin_release(
        self,
        *,
        release_id: str,
        granted_permissions: list[str] | None = None,
        installation_source: str = "PACKAGE",
    ) -> dict:
        installed_plugin = self._host.provider_inventory.install_plugin_release(
            release_id=release_id,
            granted_permissions=granted_permissions,
            installation_source=installation_source,
        )
        self._host._persist_state()
        return installed_plugin.model_dump(mode="json")

    def list_provider_installation_jobs(self) -> list[dict]:
        return [
            job.model_dump(mode="json")
            for job in self._host.provider_inventory.list_installation_jobs()
        ]

    def plugin_host_local_ingress(self):
        return self._host.provider_inventory.plugin_host_local_ingress()

    def start_windows_plugin_host_listener(self, *, address: str, authkey: bytes):
        listener = WindowsNamedPipePluginHostListener(
            address=address,
            authkey=authkey,
            wire_adapter=PluginHostJsonWireAdapter(self.plugin_host_local_ingress()),
        )
        listener.start()
        self._host._plugin_host_listeners.append(listener)
        return listener

    def start_unix_plugin_host_listener(self, *, address: str):
        listener = UnixSocketPluginHostListener(
            address=address,
            wire_adapter=PluginHostJsonWireAdapter(self.plugin_host_local_ingress()),
        )
        listener.start()
        self._host._plugin_host_listeners.append(listener)
        return listener

    def stop_plugin_host_listeners(self) -> None:
        for listener in self._host._plugin_host_listeners:
            listener.stop()  # type: ignore[attr-defined]
        self._host._plugin_host_listeners.clear()

    def plugin_host_status(self) -> dict:
        connections = self._host.provider_inventory.plugin_host_connection_store.snapshot()
        return {
            "active_connection_count": len(connections),
            "connections": [
                {
                    key: value
                    for key, value in item.items()
                    if key != "activation_credential_key_id"
                }
                for item in connections
            ],
            "listener_count": len(self._host._plugin_host_listeners),
            "listener_transports": [
                type(item).__name__ for item in self._host._plugin_host_listeners
            ],
        }
