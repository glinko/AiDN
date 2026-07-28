from __future__ import annotations

import json
from urllib import error as urllib_error
from urllib import request as urllib_request

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

    def import_provider_plugin_registry_objects(self, records: list[dict]) -> list[dict]:
        releases = self._host.provider_inventory.import_plugin_release_registry_objects(records)
        self._host._persist_state()
        return [release.model_dump(mode="json") for release in releases]

    def sync_provider_plugin_directory_from_peer(
        self,
        *,
        peer_base_url: str,
        limit: int = 500,
        timeout_seconds: int = 10,
    ) -> dict:
        base_url = peer_base_url.rstrip("/")
        request = urllib_request.Request(
            f"{base_url}/operators/registry/objects?namespace=plugin&include_payload=true&limit={int(limit)}",
            method="GET",
        )
        try:
            with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib_error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ValueError(
                f"Failed to sync plugin directory from peer {peer_base_url}"
            ) from error
        if not isinstance(payload, dict) or not isinstance(payload.get("objects"), list):
            raise ValueError(f"Peer plugin directory response from {peer_base_url} is invalid")
        items = self.import_provider_plugin_registry_objects(payload["objects"])
        return {"peer_base_url": base_url, "imported_release_count": len(items), "items": items}

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

    def revoke_provider_plugin_release(self, *, release_id: str, reason: str) -> dict:
        release, revoked_installed_plugin_ids, revoked_connection_count = (
            self._host.provider_inventory.revoke_plugin_release(
                release_id=release_id, reason=reason
            )
        )
        terminated_runtime_ids = self._stop_revoked_plugin_host_processes(
            revoked_installed_plugin_ids
        )
        self._host._persist_state()
        return {
            **release.model_dump(mode="json"),
            "revoked_installed_plugin_ids": revoked_installed_plugin_ids,
            "revoked_connection_count": revoked_connection_count,
            "terminated_runtime_ids": terminated_runtime_ids,
        }

    def _stop_revoked_plugin_host_processes(
        self, installed_plugin_ids: list[str]
    ) -> list[str]:
        if not installed_plugin_ids or not hasattr(self._host.runtimes, "stop_runtime"):
            return []
        installed_plugin_id_set = set(installed_plugin_ids)
        runtimes = self._host.runtimes.list_runtimes()
        stopped_runtime_ids: list[str] = []
        for runtime in runtimes:
            if (
                runtime.metadata.get("component") != "plugin_host"
                or runtime.metadata.get("installed_plugin_id")
                not in installed_plugin_id_set
            ):
                continue
            self._host.runtimes.stop_runtime(runtime.runtime_id)
            stopped_runtime_ids.append(runtime.runtime_id)
        return stopped_runtime_ids

    def acquire_provider_plugin_package(self, *, release_id: str) -> str:
        package_digest = self._host.provider_inventory.acquire_plugin_package(release_id=release_id)
        self._host._persist_state()
        return package_digest

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

    def plugin_host_launch_environment(self, *, installed_plugin_id: str) -> dict[str, str]:
        return self._host.provider_inventory.plugin_host_launch_environment(
            installed_plugin_id=installed_plugin_id
        )

    def start_plugin_host_process(
        self,
        *,
        installed_plugin_id: str,
        command: list[str],
    ):
        if not command or not all(isinstance(item, str) and item for item in command):
            raise ValueError("Plugin Host command is required")
        installed = self._host.provider_inventory.store.get_installed_plugin(
            installed_plugin_id
        )
        release = self._host.provider_inventory.store.get_plugin_release(
            installed.release_id
        )
        if release.release_status in {"SECURITY_BLOCKED", "REVOKED"}:
            raise ValueError("Plugin Host release is not eligible for launch")
        if installed.installation_source == "PACKAGE":
            package_store = self._host.provider_inventory.package_store
            if package_store is None or not package_store.has(release.package_digest):
                raise ValueError("verified plugin package is required before Host launch")
        self._host.provider_inventory.provision_plugin_host_activation_credential(
            installed_plugin_id=installed_plugin_id
        )
        runtime = self._host.runtimes.start_runtime(
            {
                "launch_mode": "managed_process",
                "command": command,
                "metadata": {
                    "component": "plugin_host",
                    "installed_plugin_id": installed.installed_plugin_id,
                    "plugin_id": installed.plugin_id,
                    "installation_generation": str(installed.installation_generation),
                },
                "environment": self.plugin_host_launch_environment(
                    installed_plugin_id=installed_plugin_id
                ),
            }
        )
        self._host._persist_state()
        return runtime

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
