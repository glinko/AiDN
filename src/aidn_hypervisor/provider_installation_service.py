from __future__ import annotations

import hashlib
import json
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from aidn_hypervisor.plugins.host import PluginHostJsonWireAdapter
from aidn_hypervisor.plugins.host_named_pipe import WindowsNamedPipePluginHostListener
from aidn_hypervisor.plugins.host_unix_socket import UnixSocketPluginHostListener


class _RejectPluginDirectoryPeerRedirects(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class PluginDirectoryPeerTransport:
    """Fetch public directory metadata without following a peer redirect."""

    def fetch(self, request, *, timeout_seconds: int):
        return urllib_request.build_opener(_RejectPluginDirectoryPeerRedirects()).open(
            request, timeout=timeout_seconds
        )


def _normalize_plugin_directory_peer_base_url(peer_base_url: str) -> str:
    parsed = urllib_parse.urlsplit(peer_base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("peer_base_url must be an absolute HTTP URL")
    if parsed.username or parsed.password:
        raise ValueError("peer_base_url must not include credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("peer_base_url must not include a path, query, or fragment")
    try:
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("peer_base_url port is invalid")
    except ValueError as error:
        raise ValueError("peer_base_url port is invalid") from error
    return urllib_parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


class ProviderInstallationService:
    """Provider/plugin installation and plugin-host orchestration."""

    def __init__(self, host) -> None:
        self._host = host
        self._default_plugin_directory_peer_transport = PluginDirectoryPeerTransport()

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

    def provider_plugin_directory_sync_state(self, *, limit: int = 500) -> dict:
        return {"objects": self.provider_plugin_registry_objects()[:limit]}

    def publish_provider_plugin_releases_to_registry(self, registry_service) -> list[dict]:
        return registry_service.ingest_registry_objects(
            self.provider_plugin_registry_objects()
        )

    def import_provider_plugin_registry_objects(self, records: list[dict]) -> list[dict]:
        revoked_release_ids = {
            payload["release_id"]
            for record in records
            if isinstance((payload := record.get("payload")), dict)
            and payload.get("release_status") == "REVOKED"
            and isinstance(payload.get("release_id"), str)
        }
        affected_installed_plugin_ids = [
            installed_plugin.installed_plugin_id
            for installed_plugin in self._host.provider_inventory.list_installed_plugins()
            if installed_plugin.release_id in revoked_release_ids
        ]
        releases = self._host.provider_inventory.import_plugin_release_registry_objects(records)
        self._stop_revoked_plugin_host_processes(affected_installed_plugin_ids)
        self._host._persist_state()
        return [release.model_dump(mode="json") for release in releases]

    def reconcile_provider_plugin_releases_from_registry(
        self,
        registry_service,
        *,
        limit: int = 500,
    ) -> dict:
        """Import Plugin Release metadata already available in the local Registry."""
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        records = registry_service.list_registry_objects(
            {
                "object_type": "plugin_release",
                "namespace": "plugin",
                "include_payload": True,
                "limit": limit,
            }
        )
        items = self.import_provider_plugin_registry_objects(records)
        return {
            "registry_record_count": len(records),
            "imported_release_count": len(items),
            "items": items,
        }

    def bind_provider_plugin_directory_replication(self, registry_replicator) -> None:
        """Project verified replicated Plugin Release objects into the local directory."""
        register_object_handler = getattr(registry_replicator, "register_object_handler", None)
        if not callable(register_object_handler):
            raise ValueError("registry_replicator does not support object handlers")
        register_object_handler("plugin_release", self._import_replicated_plugin_release)

    def _import_replicated_plugin_release(self, _peer_id: str, envelope) -> None:
        if envelope.namespace != "plugin":
            raise ValueError("replicated plugin release has an invalid namespace")
        if envelope.payload_encoding != "canonical_json":
            raise ValueError("replicated plugin release has an invalid payload encoding")
        source_reference = (
            envelope.parent_references[0]
            if envelope.parent_references
            else envelope.payload.get("source_reference")
        )
        self.import_provider_plugin_registry_objects(
            [
                {
                    "object_id": envelope.object_id,
                    "object_type": envelope.object_type,
                    "object_version": "plugin-release.v1",
                    "namespace": envelope.namespace,
                    "payload_hash": f"sha256:{envelope.content_hash}",
                    "payload_encoding": envelope.payload_encoding,
                    "source_reference": source_reference,
                    "payload": envelope.payload,
                }
            ]
        )

    def sync_provider_plugin_directory_from_peer(
        self,
        *,
        peer_base_url: str,
        limit: int = 500,
        timeout_seconds: int = 10,
        expected_node_id: str | None = None,
        expected_operator_id: str | None = None,
        expected_owner_wallet_id: str | None = None,
        expected_public_key: str | None = None,
    ) -> dict:
        base_url = _normalize_plugin_directory_peer_base_url(peer_base_url)
        expected_identity_values = (
            expected_node_id,
            expected_operator_id,
            expected_owner_wallet_id,
            expected_public_key,
        )
        if any(value is not None for value in expected_identity_values) and not all(
            value is not None for value in expected_identity_values
        ):
            raise ValueError("Peer plugin directory expected source identity is incomplete")
        authenticated = all(value is not None for value in expected_identity_values)
        request = urllib_request.Request(
            f"{base_url}/operators/provider-plugin-releases/sync-state?limit={int(limit)}",
            method="GET",
        )
        try:
            with self._plugin_directory_peer_transport().fetch(
                request, timeout_seconds=timeout_seconds
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib_error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ValueError(
                f"Failed to sync plugin directory from peer {peer_base_url}"
            ) from error
        if not isinstance(payload, dict):
            raise ValueError(f"Peer plugin directory response from {peer_base_url} is invalid")
        if not isinstance(payload.get("objects"), list) and not authenticated:
            raise ValueError(f"Peer plugin directory response from {peer_base_url} is invalid")
        if authenticated:
            payload = self._verified_plugin_directory_peer_sync_envelope(
                payload=payload,
                expected_node_id=expected_node_id,
                expected_operator_id=expected_operator_id,
                expected_owner_wallet_id=expected_owner_wallet_id,
                expected_public_key=expected_public_key,
            )
        if not isinstance(payload.get("objects"), list):
            raise ValueError(f"Peer plugin directory response from {peer_base_url} is invalid")
        items = self.import_provider_plugin_registry_objects(payload["objects"])
        return {
            "peer_base_url": base_url,
            "authenticated": authenticated,
            "imported_release_count": len(items),
            "items": items,
        }

    @staticmethod
    def _verified_plugin_directory_peer_sync_envelope(
        *,
        payload: dict,
        expected_node_id: str,
        expected_operator_id: str | None,
        expected_owner_wallet_id: str | None,
        expected_public_key: str | None,
    ) -> dict:
        from aidn_hypervisor.wallet_identity import verify_plugin_directory_sync_envelope

        sync_state = payload.get("sync_state")
        source = payload.get("source")
        signature = payload.get("signature")
        if not isinstance(sync_state, dict) or not isinstance(source, dict):
            raise ValueError("Peer plugin directory sync envelope is required")
        expected_source = {
            "node_id": expected_node_id,
            "operator_id": expected_operator_id,
            "owner_wallet_id": expected_owner_wallet_id,
            "public_key": expected_public_key,
        }
        for field, expected_value in expected_source.items():
            if expected_value is None:
                raise ValueError("Peer plugin directory expected source identity is incomplete")
            if source.get(field) != expected_value:
                raise ValueError(f"Peer plugin directory sync {field} does not match")
        state_hash = "sha256:" + hashlib.sha256(
            json.dumps(sync_state, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        if source.get("state_hash") != state_hash:
            raise ValueError("Peer plugin directory sync state hash does not match")
        try:
            verify_plugin_directory_sync_envelope(
                node_id=source["node_id"],
                operator_id=source["operator_id"],
                owner_wallet_id=source["owner_wallet_id"],
                public_key=source["public_key"],
                state_hash=source["state_hash"],
                signature=signature,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Peer plugin directory sync signature is invalid") from error
        return sync_state

    def _plugin_directory_peer_transport(self):
        return getattr(
            self._host,
            "_plugin_directory_peer_transport",
            self._default_plugin_directory_peer_transport,
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
        command: list[str] | None = None,
    ):
        installed = self._host.provider_inventory.store.get_installed_plugin(
            installed_plugin_id
        )
        release = self._host.provider_inventory.store.get_plugin_release(
            installed.release_id
        )
        if release.release_status in {"SECURITY_BLOCKED", "REVOKED"}:
            raise ValueError("Plugin Host release is not eligible for launch")
        cleanup_paths: tuple = ()
        if installed.installation_source == "PACKAGE":
            if command is not None:
                raise ValueError(
                    "PACKAGE installations cannot launch an operator-supplied command"
                )
            self._host.provider_inventory.validate_package_host_launch(
                installed_plugin_id=installed_plugin_id
            )
        elif not command or not all(isinstance(item, str) and item for item in command):
            raise ValueError("Plugin Host command is required")
        else:
            package_launch_spec = {}
        self._host.provider_inventory.provision_plugin_host_activation_credential(
            installed_plugin_id=installed_plugin_id
        )
        installed = self._host.provider_inventory.store.get_installed_plugin(
            installed_plugin_id
        )
        if installed.installation_source == "PACKAGE":
            secret_file, cleanup_paths = (
                self._host.provider_inventory.create_plugin_host_activation_secret_file(
                    installed_plugin_id=installed_plugin_id
                )
            )
            package_launch_spec = self._host.provider_inventory.package_host_launch_spec(
                installed_plugin_id=installed_plugin_id,
                activation_secret_file=secret_file,
            )
            command = package_launch_spec["command"]
            environment = self.plugin_host_launch_environment(
                installed_plugin_id=installed_plugin_id
            )
            environment.pop("AIDN_PLUGIN_HOST_ACTIVATION_SECRET", None)
        else:
            environment = self.plugin_host_launch_environment(
                installed_plugin_id=installed_plugin_id
            )
        try:
            runtime = self._host.runtimes.start_runtime(
                {
                    "launch_mode": "managed_process",
                    "command": command,
                    "metadata": {
                        "component": "plugin_host",
                        "installed_plugin_id": installed.installed_plugin_id,
                        "plugin_id": installed.plugin_id,
                        "installation_generation": str(installed.installation_generation),
                        **package_launch_spec.get("metadata", {}),
                    },
                    "working_directory": package_launch_spec.get("working_directory"),
                    "environment": environment,
                    "cleanup_paths": cleanup_paths,
                }
            )
        except Exception:
            for path in cleanup_paths:
                try:
                    path.unlink(missing_ok=True)
                except IsADirectoryError:
                    path.rmdir()
            raise
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
