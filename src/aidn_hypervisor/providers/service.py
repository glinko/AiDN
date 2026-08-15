import hashlib
import json
import os
import secrets
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from aidn_hypervisor.accounting.llamacpp import build_llamacpp_usage_profile
from aidn_hypervisor.accounting.ollama import build_ollama_usage_profile
from aidn_hypervisor.accounting.proxy import build_proxy_opaque_usage_profile
from aidn_hypervisor.accounting.vllm import build_vllm_usage_profile
from aidn_hypervisor.accounting.whisper import build_whisper_usage_profile
from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile
from aidn_hypervisor.plugins.container import DockerPluginHostLauncher
from aidn_hypervisor.plugins.host import (
    HmacPluginHostActivationProofVerifier,
    PluginHostActivationCredentialStore,
    PluginHostAuthenticator,
    PluginHostConnectionStore,
    PluginHostHandshakeService,
    PluginHostLocalIpcIngress,
    SecretManagerPluginHostActivationCredentialStore,
)
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.providers.executor import (
    ProviderInstallationExecutor,
    RecordedProviderInstallationExecutor,
    SandboxEnforcedProviderInstallationExecutor,
)
from aidn_hypervisor.providers.models import (
    InstallationPlan,
    InstalledPlugin,
    ModelArtifact,
    ModelArtifactGarbageCollectionResult,
    ModelArtifactInventory,
    ModelArtifactSet,
    ModelDeployment,
    PluginPackageVerification,
    PluginRelease,
    ProviderArtifactMaterialization,
    ProviderInstallationApproval,
    ProviderInstallationArchiveExtractionResult,
    ProviderInstallationArtifact,
    ProviderInstallationArtifactInventory,
    ProviderInstallationDiagnosticCheck,
    ProviderInstallationDiagnostics,
    ProviderInstallationJob,
    ProviderInstallationRollbackResult,
    ProviderInstallationStepResult,
    ProviderInstallationUpgradeReview,
    ProviderInstance,
    ProviderPluginManifest,
    RuntimeBinding,
    SelectedSecretHandle,
)
from aidn_hypervisor.providers.package_store import (
    FilesystemPluginPackageStore,
    HttpsPluginPackageAcquirer,
    PluginPackageStore,
)
from aidn_hypervisor.providers.package_verification import (
    DEFAULT_TRUSTED_PUBLISHER_KEYS,
    verify_plugin_manifest_package,
)
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore
from aidn_hypervisor.secrets import FileSecretManager


def _canonical_hash(value: dict) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ProviderInventoryService:
    def __init__(
        self,
        *,
        plugins,
        store: InMemoryProviderInventoryStore,
        installation_executor: ProviderInstallationExecutor | None = None,
        trusted_publisher_keys: dict[str, list[str]] | None = None,
        package_store: PluginPackageStore | None = None,
        package_acquirer: HttpsPluginPackageAcquirer | None = None,
        plugin_host_connections: list[dict] | None = None,
        plugin_host_secret_manager: FileSecretManager | None = None,
        plugin_host_container_launcher: DockerPluginHostLauncher | None = None,
    ) -> None:
        self.plugins = plugins
        self.store = store
        self.installation_executor = (
            installation_executor or SandboxEnforcedProviderInstallationExecutor()
        )
        self.trusted_publisher_keys = deepcopy(
            trusted_publisher_keys or DEFAULT_TRUSTED_PUBLISHER_KEYS
        )
        self.package_store = package_store
        self.package_acquirer = package_acquirer or HttpsPluginPackageAcquirer()
        self.plugin_host_activation_credentials = (
            SecretManagerPluginHostActivationCredentialStore(plugin_host_secret_manager)
            if plugin_host_secret_manager is not None
            else PluginHostActivationCredentialStore()
        )
        self.plugin_host_container_launcher = (
            plugin_host_container_launcher or DockerPluginHostLauncher()
        )
        self.plugin_host_connection_store = PluginHostConnectionStore(plugin_host_connections)
        self._runtime_binding_projections: dict[str, dict] = {}

    def list_plugin_manifests(self) -> list[dict]:
        return [self._plugin_manifest_payload(plugin) for plugin in self._list_plugins()]

    def list_plugin_releases(self) -> list[PluginRelease]:
        return self.store.list_plugin_releases()

    def list_installed_plugins(self) -> list[InstalledPlugin]:
        return self.store.list_installed_plugins()

    def plugin_release_registry_objects(self) -> list[dict]:
        """Project immutable, public Plugin Release metadata into Registry objects."""
        records: list[dict] = []
        for release in self.store.list_plugin_releases():
            payload = {
                "release_id": release.release_id,
                "plugin_id": release.plugin_id,
                "plugin_version": release.plugin_version,
                "manifest_hash": release.manifest_hash,
                "package_digest": release.package_digest,
                "publisher": release.publisher,
                "trust_status": release.trust_status,
                "declared_permissions": list(release.declared_permissions),
                "release_status": release.release_status,
                "revocation_reason": release.revocation_reason,
                "revoked_at": release.revoked_at,
                "source_reference": release.source_reference,
                "package_verification_status": release.package_verification_status,
                "package_verification_mode": release.package_verification_mode,
                "trusted_publisher": release.trusted_publisher,
                "host_entrypoint": (
                    release.host_entrypoint.model_dump(mode="json")
                    if release.host_entrypoint is not None
                    else None
                ),
                "host_execution_mode": release.host_execution_mode,
                "host_sandbox_policy": release.host_sandbox_policy.model_dump(mode="json"),
                "published_at": release.published_at,
            }
            payload_hash = _canonical_hash(payload)
            records.append(
                {
                    "object_id": _canonical_hash(
                        {
                            "object_type": "plugin_release",
                            "object_version": "plugin-release.v1",
                            "payload_hash": payload_hash,
                        }
                    ),
                    "object_type": "plugin_release",
                    "object_version": "plugin-release.v1",
                    "namespace": "plugin",
                    "payload_hash": payload_hash,
                    "payload_encoding": "canonical_json",
                    "source_reference": release.source_reference or release.release_id,
                    "payload": payload,
                }
            )
        return records

    def import_plugin_release_registry_objects(self, records: list[dict]) -> list[PluginRelease]:
        """Import hash-bound directory metadata without inheriting package trust."""
        imported: list[PluginRelease] = []
        for record in records:
            if record.get("object_type") != "plugin_release" or record.get("namespace") != "plugin":
                raise ValueError("registry object is not a plugin release")
            payload = record.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("plugin release registry object has no payload")
            payload_hash = _canonical_hash(payload)
            if record.get("payload_hash") != payload_hash:
                raise ValueError("plugin release registry payload hash mismatch")
            expected_object_id = _canonical_hash(
                {
                    "object_type": "plugin_release",
                    "object_version": "plugin-release.v1",
                    "payload_hash": payload_hash,
                }
            )
            if record.get("object_id") != expected_object_id:
                raise ValueError("plugin release registry object identity mismatch")
            incoming_release = PluginRelease(
                release_id=payload["release_id"],
                plugin_id=payload["plugin_id"],
                plugin_version=payload["plugin_version"],
                manifest_hash=payload["manifest_hash"],
                package_digest=payload["package_digest"],
                publisher=payload["publisher"],
                trust_status=payload["trust_status"],
                declared_permissions=payload.get("declared_permissions", []),
                release_status=payload.get("release_status", "AVAILABLE"),
                revocation_reason=payload.get("revocation_reason"),
                revoked_at=payload.get("revoked_at"),
                source_reference=payload.get("source_reference"),
                package_verification_status="UNVERIFIED",
                package_verification_mode="NONE",
                trusted_publisher=False,
                host_entrypoint=payload.get("host_entrypoint"),
                host_execution_mode=payload.get("host_execution_mode", "RECORDED_ONLY"),
                host_sandbox_policy=payload.get("host_sandbox_policy", {}),
                published_at=payload["published_at"],
            )
            try:
                existing_release = self.store.get_plugin_release(incoming_release.release_id)
            except KeyError:
                existing_release = None
            release = self._merge_imported_plugin_release(
                existing_release=existing_release,
                incoming_release=incoming_release,
            )
            self.store.save_plugin_release(release)
            if release.release_status == "REVOKED":
                self._revoke_installed_plugins_for_release(release.release_id)
            imported.append(release)
        return imported

    @staticmethod
    def _merge_imported_plugin_release(
        *,
        existing_release: PluginRelease | None,
        incoming_release: PluginRelease,
    ) -> PluginRelease:
        """Keep local execution trust and never downgrade a local security revoke."""
        if existing_release is None:
            return incoming_release
        if existing_release.release_status == "REVOKED":
            return existing_release
        return incoming_release.model_copy(
            update={
                "package_verification_status": existing_release.package_verification_status,
                "package_verification_mode": existing_release.package_verification_mode,
                "trusted_publisher": existing_release.trusted_publisher,
            }
        )

    def plugin_host_local_ingress(self) -> PluginHostLocalIpcIngress:
        """Expose only identity-bound manifest and validation controls to a Plugin Host."""
        return PluginHostLocalIpcIngress(
            PluginHostHandshakeService(
                authenticator=PluginHostAuthenticator(self.store.get_installed_plugin),
                activation_proof_verifier=HmacPluginHostActivationProofVerifier(
                    self.plugin_host_activation_credentials.get
                ),
                now=_now_iso,
            ),
            manifest_resolver=lambda plugin_id: self._get_plugin(plugin_id).plugin_manifest(),
            configuration_validator=lambda plugin_id, configuration: self._get_plugin(
                plugin_id
            ).validate_provider_configuration(configuration),
            installation_plan_builder=lambda plugin_id, configuration: self.build_installation_plan(
                plugin_id=plugin_id, configuration=configuration
            ),
            attach_existing_provider=lambda plugin_id, display_name, configuration: self.attach_provider_instance(
                plugin_id=plugin_id, display_name=display_name, configuration=configuration
            ).model_dump(mode="json"),
            model_discoverer=lambda plugin_id, provider_instance_id: self._host_discover_models(
                plugin_id, provider_instance_id
            ),
            runtime_binding_creator=lambda plugin_id, model_deployment_id, capability_id, capability_version, capability_definition_hash: self._host_create_runtime_binding(  # noqa: E501
                plugin_id, model_deployment_id, capability_id, capability_version, capability_definition_hash
            ),
            runtime_binding_admission=lambda plugin_id, runtime_binding_id: self._host_runtime_binding_admission(  # noqa: E501
                plugin_id, runtime_binding_id
            ),
            connection_store=self.plugin_host_connection_store,
        )

    def provision_plugin_host_activation_credential(
        self,
        *,
        installed_plugin_id: str,
    ) -> dict:
        """Rotate an install generation and retain its ephemeral Host secret."""
        activation_secret = secrets.token_bytes(32)
        credential_key_id = "sha256:" + hashlib.sha256(activation_secret).hexdigest()
        installed = self.advance_installed_plugin_generation(
            installed_plugin_id=installed_plugin_id,
            activation_credential_key_id=credential_key_id,
        )
        self.plugin_host_activation_credentials.save(
            credential_key_id=credential_key_id,
            activation_secret=activation_secret,
        )
        return {
            "installed_plugin_id": installed.installed_plugin_id,
            "plugin_id": installed.plugin_id,
            "installation_generation": installed.installation_generation,
            "activation_credential_key_id": credential_key_id,
        }

    def plugin_host_launch_environment(self, *, installed_plugin_id: str) -> dict[str, str]:
        """Build the private child-process environment for one authorized Host."""
        installed = self.store.get_installed_plugin(installed_plugin_id)
        credential_key_id = installed.activation_credential_key_id
        if credential_key_id is None:
            raise ValueError("Plugin Host activation credential is not provisioned")
        activation_secret = self.plugin_host_activation_credentials.get(credential_key_id)
        if activation_secret is None:
            raise ValueError("Plugin Host activation credential is unavailable")
        return {
            "AIDN_PLUGIN_HOST_INSTALLED_PLUGIN_ID": installed.installed_plugin_id,
            "AIDN_PLUGIN_HOST_PLUGIN_ID": installed.plugin_id,
            "AIDN_PLUGIN_HOST_INSTALLATION_GENERATION": str(installed.installation_generation),
            "AIDN_PLUGIN_HOST_ACTIVATION_CREDENTIAL_KEY_ID": credential_key_id,
            "AIDN_PLUGIN_HOST_ACTIVATION_SECRET": activation_secret.hex(),
        }

    def create_plugin_host_activation_secret_file(
        self,
        *,
        installed_plugin_id: str,
    ) -> tuple[Path, tuple[Path, Path]]:
        """Materialize one package Host secret in a private, short-lived directory."""
        installed = self.store.get_installed_plugin(installed_plugin_id)
        credential_key_id = installed.activation_credential_key_id
        if credential_key_id is None:
            raise ValueError("Plugin Host activation credential is not provisioned")
        activation_secret = self.plugin_host_activation_credentials.get(credential_key_id)
        if activation_secret is None:
            raise ValueError("Plugin Host activation credential is unavailable")
        secret_directory = Path(tempfile.mkdtemp(prefix="aidn-plugin-host-secret-"))
        try:
            os.chmod(secret_directory, 0o700)
            secret_file = secret_directory / "activation-secret"
            descriptor = os.open(
                secret_file,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o444,
            )
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(activation_secret.hex())
            os.chmod(secret_file, 0o444)
        except Exception:
            try:
                secret_file.unlink(missing_ok=True)
            except UnboundLocalError:
                pass
            secret_directory.rmdir()
            raise
        return secret_file, (secret_file, secret_directory)

    def _host_discover_models(self, plugin_id: str, provider_instance_id: str) -> list[dict]:
        instance = self.store.get_provider_instance(provider_instance_id)
        if instance.plugin_id != plugin_id:
            raise ValueError("Provider Instance does not belong to the Plugin Host")
        return [item.model_dump(mode="json") for item in self.discover_models(provider_instance_id)]

    def _host_create_runtime_binding(
        self, plugin_id: str, model_deployment_id: str, capability_id: str,
        capability_version: str, capability_definition_hash: str
    ) -> dict:
        deployment = self.store.get_model_deployment(model_deployment_id)
        if self.store.get_provider_instance(deployment.provider_instance_id).plugin_id != plugin_id:
            raise ValueError("Model Deployment does not belong to the Plugin Host")
        return self.create_runtime_binding(
            model_deployment_id=model_deployment_id, capability_id=capability_id,
            capability_version=capability_version,
            capability_definition_hash=capability_definition_hash
        ).model_dump(mode="json")

    def _host_runtime_binding_admission(self, plugin_id: str, runtime_binding_id: str) -> dict:
        binding = self.store.get_runtime_binding(runtime_binding_id)
        if binding.plugin_id != plugin_id:
            raise ValueError("Runtime Binding does not belong to the Plugin Host")
        return self.runtime_binding_endpoint_admission(runtime_binding_id)

    def stage_plugin_package(self, *, package_bytes: bytes, expected_digest: str) -> str:
        if self.package_store is None:
            raise ValueError("Plugin package store is not configured")
        return self.package_store.stage(
            package_bytes=package_bytes,
            expected_digest=expected_digest,
        )

    def acquire_plugin_package(self, *, release_id: str) -> str:
        """Fetch only a signed, trusted release into the verified package store."""
        if self.package_store is None:
            raise ValueError("Plugin package store is not configured")
        release = self.store.get_plugin_release(release_id)
        if (
            release.package_verification_status != "VERIFIED"
            or not release.trusted_publisher
        ):
            raise ValueError("plugin package acquisition requires a trusted signed release")
        if release.source_reference is None:
            raise ValueError("plugin release does not declare a package source")
        return self.package_acquirer.acquire_and_stage(
            package_store=self.package_store,
            source_reference=release.source_reference,
            expected_digest=release.package_digest,
        )

    def register_plugin_release(
        self,
        *,
        manifest_payload: dict,
        source_reference: str | None = None,
        release_status: str = "AVAILABLE",
    ) -> PluginRelease:
        """Record a directory release without loading or executing its package."""
        manifest = ProviderPluginManifest.model_validate(manifest_payload)
        package_verification = self._package_verification(manifest)
        self._validate_package_verification(package_verification)
        if manifest.manifest_hash is None:
            raise ValueError("plugin release requires a declared manifest hash")

        release_identity = {
            "plugin_id": manifest.plugin_id,
            "plugin_version": manifest.plugin_version,
            "manifest_hash": manifest.manifest_hash,
            "package_digest": manifest.package_digest,
            "publisher": manifest.publisher,
        }
        release_id = f"prl-{_canonical_hash(release_identity).split(':', 1)[1][:20]}"
        try:
            return self.store.get_plugin_release(release_id)
        except KeyError:
            pass
        release = PluginRelease(
            release_id=release_id,
            plugin_id=manifest.plugin_id,
            plugin_version=manifest.plugin_version,
            manifest_hash=manifest.manifest_hash,
            package_digest=manifest.package_digest,
            publisher=manifest.publisher,
            trust_status=manifest.trust_status,
            declared_permissions=[
                permission.permission_id for permission in manifest.required_permissions
            ],
            release_status=release_status,
            source_reference=source_reference,
            package_verification_status=package_verification.status,
            package_verification_mode=package_verification.verification_mode,
            trusted_publisher=package_verification.trusted_publisher,
            host_entrypoint=manifest.host_entrypoint,
            host_execution_mode=manifest.sandbox_policy.execution_mode,
            host_sandbox_policy=manifest.sandbox_policy,
            published_at=_now_iso(),
        )
        self.store.save_plugin_release(release)
        return release

    def _package_host_entrypoint(self, *, installed_plugin_id: str) -> tuple[PluginRelease, Path]:
        """Validate package Host eligibility and return its verified entrypoint."""
        installed = self.store.get_installed_plugin(installed_plugin_id)
        if installed.installation_source != "PACKAGE":
            raise ValueError("package Plugin Host launch requires a PACKAGE installation")
        release = self.store.get_plugin_release(installed.release_id)
        if release.release_status in {"SECURITY_BLOCKED", "REVOKED"}:
            raise ValueError("Plugin Host release is not eligible for launch")
        if release.package_verification_status != "VERIFIED" or not release.trusted_publisher:
            raise ValueError("package Plugin Host launch requires a trusted signed release")
        if release.host_entrypoint is None:
            raise ValueError("package Plugin Host release does not declare a signed entrypoint")
        if release.host_execution_mode != "SANDBOX_REQUIRED":
            raise ValueError("package Plugin Host launch requires SANDBOX_REQUIRED")
        if not isinstance(self.package_store, FilesystemPluginPackageStore):
            raise ValueError("package Plugin Host launch requires durable filesystem package storage")
        entrypoint = self.package_store.materialize_python_host(
            package_digest=release.package_digest,
            entrypoint_path=release.host_entrypoint.entrypoint_path,
        )
        if not self.plugin_host_container_launcher.is_available():
            raise ValueError("package Plugin Host container runtime is unavailable")
        return release, entrypoint

    def validate_package_host_launch(self, *, installed_plugin_id: str) -> None:
        """Fail before credential provisioning when a package Host cannot launch."""
        self._package_host_entrypoint(installed_plugin_id=installed_plugin_id)

    def package_host_launch_spec(
        self,
        *,
        installed_plugin_id: str,
        activation_secret_file: Path,
    ) -> dict:
        """Build the only allowed launch command for a verified package release."""
        release, entrypoint = self._package_host_entrypoint(
            installed_plugin_id=installed_plugin_id
        )
        entrypoint_depth = len(release.host_entrypoint.entrypoint_path.split("/"))
        plugin_data_root = None
        if release.host_sandbox_policy.filesystem_scope == "PLUGIN_DATA_ONLY":
            if not isinstance(self.package_store, FilesystemPluginPackageStore):
                raise ValueError("PLUGIN_DATA_ONLY requires durable filesystem package storage")
            plugin_data_root = (
                self.package_store.root
                / "plugin-data"
                / hashlib.sha256(installed_plugin_id.encode("utf-8")).hexdigest()
            )
            if plugin_data_root.is_symlink():
                raise ValueError("Plugin Host data directory cannot be a symbolic link")
            plugin_data_root.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(plugin_data_root, 0o777)
            except OSError as error:
                raise ValueError("Plugin Host data directory permissions cannot be prepared") from error
        launch_spec = self.plugin_host_container_launcher.build_launch_spec(
            package_root=entrypoint.parents[entrypoint_depth - 1],
            entrypoint=release.host_entrypoint,
            sandbox_policy=release.host_sandbox_policy,
            activation_secret_file=activation_secret_file,
            plugin_data_root=plugin_data_root,
        )
        launch_spec["metadata"].update(
            {
                "package_digest": release.package_digest,
                "package_entrypoint": release.host_entrypoint.entrypoint_path,
            }
        )
        return launch_spec

    def revoke_plugin_release(self, *, release_id: str, reason: str) -> tuple[PluginRelease, list[str], int]:
        if not reason.strip():
            raise ValueError("plugin release revocation reason must not be blank")
        release = self.store.get_plugin_release(release_id)
        if release.release_status == "REVOKED":
            if release.revocation_reason != reason:
                raise ValueError("plugin release revocation reason is immutable")
            return release, [], 0
        revoked = release.model_copy(
            update={
                "release_status": "REVOKED",
                "revocation_reason": reason,
                "revoked_at": _now_iso(),
            }
        )
        self.store.save_plugin_release(revoked)
        revoked_installed_plugin_ids, revoked_connection_count = (
            self._revoke_installed_plugins_for_release(release_id)
        )
        return revoked, revoked_installed_plugin_ids, revoked_connection_count

    def _revoke_installed_plugins_for_release(self, release_id: str) -> tuple[list[str], int]:
        revoked_installed_plugin_ids: list[str] = []
        revoked_connection_count = 0
        for installed in self.store.list_installed_plugins():
            if installed.release_id != release_id or installed.state == "REVOKED":
                continue
            if installed.activation_credential_key_id is not None:
                self.plugin_host_activation_credentials.remove(
                    installed.activation_credential_key_id
                )
            revoked_connection_count += self.plugin_host_connection_store.remove_for_installed_plugin(
                installed.installed_plugin_id
            )
            self.store.save_installed_plugin(
                installed.model_copy(
                    update={
                        "state": "REVOKED",
                        "activation_credential_key_id": None,
                        "activated_at": None,
                    }
                )
            )
            revoked_installed_plugin_ids.append(installed.installed_plugin_id)
        return revoked_installed_plugin_ids, revoked_connection_count

    def install_plugin_release(
        self,
        *,
        release_id: str,
        granted_permissions: list[str] | None = None,
        installation_source: str = "PACKAGE",
    ) -> InstalledPlugin:
        """Persist local approval; package acquisition and Plugin Host activation are separate."""
        release = self.store.get_plugin_release(release_id)
        if (
            installation_source == "PACKAGE"
            and self.package_store is not None
            and not self.package_store.has(release.package_digest)
        ):
            raise ValueError("verified plugin package is required before activation")
        if release.release_status in {"SECURITY_BLOCKED", "REVOKED"}:
            raise ValueError(
                f"plugin release cannot be installed while {release.release_status.lower()}"
            )
        normalized_permissions = sorted(set(granted_permissions or []))
        if not all(permission.strip() for permission in normalized_permissions):
            raise ValueError("granted permissions must not contain blank values")
        undeclared_permissions = sorted(
            set(normalized_permissions) - set(release.declared_permissions)
        )
        if undeclared_permissions:
            raise ValueError(
                "granted permissions must be declared by the plugin release: "
                + ", ".join(undeclared_permissions)
            )
        missing_permissions = sorted(
            set(release.declared_permissions) - set(normalized_permissions)
        )
        if missing_permissions:
            raise ValueError(
                "all declared plugin permissions require local approval: "
                + ", ".join(missing_permissions)
            )
        existing = next(
            (
                installed_plugin
                for installed_plugin in self.store.list_installed_plugins()
                if installed_plugin.release_id == release.release_id
            ),
            None,
        )
        if existing is not None:
            if (
                existing.granted_permissions != normalized_permissions
                or existing.installation_source != installation_source
            ):
                raise ValueError(
                    "installed plugin permissions and source are immutable; "
                    "install a new release or advance its installation generation"
                )
            return existing
        installed_plugin = InstalledPlugin(
            installed_plugin_id=f"iplg-{uuid4().hex[:12]}",
            release_id=release.release_id,
            plugin_id=release.plugin_id,
            plugin_version=release.plugin_version,
            package_digest=release.package_digest,
            granted_permissions=normalized_permissions,
            state="INSTALLED",
            installation_source=installation_source,
            installed_at=_now_iso(),
        )
        self.store.save_installed_plugin(installed_plugin)
        return installed_plugin

    def advance_installed_plugin_generation(
        self,
        *,
        installed_plugin_id: str,
        activation_credential_key_id: str | None = None,
    ) -> InstalledPlugin:
        """Invalidate stale Plugin Host processes before replacement or reauthorization."""
        installed_plugin = self.store.get_installed_plugin(installed_plugin_id)
        if installed_plugin.state == "REMOVED":
            raise ValueError("removed plugin installation cannot advance generation")
        updated = InstalledPlugin.model_validate(
            {
                **installed_plugin.model_dump(mode="json"),
                "installation_generation": installed_plugin.installation_generation + 1,
                "activation_credential_key_id": activation_credential_key_id,
                "state": "INSTALLED",
                "activated_at": None,
            }
        )
        self.store.save_installed_plugin(updated)
        return updated

    def list_provider_instances(self) -> list[ProviderInstance]:
        return self.store.list_provider_instances()

    def list_model_deployments(self) -> list[ModelDeployment]:
        return self.store.list_model_deployments()

    def list_runtime_bindings(self) -> list[RuntimeBinding]:
        return self.store.list_runtime_bindings()

    def build_installation_plan(self, *, plugin_id: str, configuration: dict) -> dict:
        plugin = self._get_plugin(plugin_id)
        manifest = plugin.plugin_manifest()
        if "CAN_INSTALL_PROVIDER" not in manifest.get("plugin_capability_flags", []):
            raise ValueError(f"Plugin does not support managed installation: {plugin_id}")
        plan = plugin.build_installation_plan(deepcopy(configuration))
        return InstallationPlan.model_validate(plan).model_dump(mode="json")

    def approve_installation_plan(
        self,
        plugin_id: str,
        configuration: dict,
        approved_permissions: list[str] | None = None,
        upgrade_acknowledged: bool = False,
        selected_secret_handles: list[dict] | None = None,
        operator_note: str | None = None,
    ) -> ProviderInstallationApproval:
        plugin = self._get_plugin(plugin_id)
        manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
        package_verification = self._package_verification(manifest)
        self._validate_package_verification(package_verification)
        approved_configuration = deepcopy(configuration)
        plan = self.build_installation_plan(
            plugin_id=plugin_id,
            configuration=approved_configuration,
        )
        requested_permission_ids = [
            permission["permission_id"] for permission in plan.get("required_permissions", [])
        ]
        normalized_sandbox_policy = self._normalized_sandbox_policy(manifest)
        self._validate_supported_sandbox_policy(
            normalized_sandbox_policy,
            executor_sandbox_capabilities=self._executor_sandbox_capabilities(),
        )
        upgrade_review = self._build_upgrade_review(
            plugin_id=plugin_id,
            requested_permissions=requested_permission_ids,
            package_verification=package_verification,
            normalized_sandbox_policy=normalized_sandbox_policy,
        )
        self._validate_upgrade_acknowledgement(
            upgrade_review=upgrade_review,
            upgrade_acknowledged=upgrade_acknowledged,
        )
        normalized_secret_requirements = self._normalized_secret_requirements(manifest)
        normalized_approved_permissions = self._validate_approved_permissions(
            requested_permissions=requested_permission_ids,
            approved_permissions=approved_permissions,
        )
        normalized_selected_secret_handles = self._validate_selected_secret_handles(
            normalized_requirements=normalized_secret_requirements,
            selected_secret_handles=selected_secret_handles,
        )
        approval = ProviderInstallationApproval(
            approval_id=f"pia-{uuid4().hex[:12]}",
            plugin_id=plugin_id,
            plan_id=plan["plan_id"],
            plan_hash=_canonical_hash(deepcopy(plan)),
            configuration_hash=_canonical_hash(deepcopy(approved_configuration)),
            configuration=deepcopy(approved_configuration),
            approved_permissions=normalized_approved_permissions,
            upgrade_review=upgrade_review.model_dump(mode="json"),
            upgrade_acknowledged=upgrade_acknowledged,
            acknowledged_package_verification=package_verification.model_dump(mode="json"),
            acknowledged_sandbox_policy=normalized_sandbox_policy,
            acknowledged_secret_requirements=normalized_secret_requirements,
            selected_secret_handles=normalized_selected_secret_handles,
            operator_note=operator_note,
            status="APPROVED",
            created_at=_now_iso(),
        )
        self.store.save_installation_approval(approval)
        return approval

    def list_installation_approvals(self) -> list[ProviderInstallationApproval]:
        return self.store.list_installation_approvals()

    def installation_artifact_inventory(self) -> ProviderInstallationArtifactInventory:
        inventory = getattr(
            self.installation_executor,
            "installation_artifact_inventory",
            None,
        )
        if inventory is None:
            return ProviderInstallationArtifactInventory(supported=False)
        return inventory()

    def stage_local_artifact(
        self,
        *,
        relative_path: str,
        content_bytes: bytes,
    ) -> ProviderInstallationArtifact:
        stage_artifact = getattr(
            self.installation_executor,
            "stage_local_artifact",
            None,
        )
        if stage_artifact is None:
            raise ValueError(
                "current installation executor does not support local artifact staging"
            )
        return stage_artifact(relative_path=relative_path, content_bytes=content_bytes)

    def delete_local_artifact(self, *, relative_path: str) -> None:
        delete_artifact = getattr(
            self.installation_executor,
            "delete_local_artifact",
            None,
        )
        if delete_artifact is None:
            raise ValueError(
                "current installation executor does not support local artifact deletion"
            )
        delete_artifact(relative_path=relative_path)

    def extract_local_artifact_archive(
        self,
        *,
        archive_relative_path: str,
        destination_directory: str,
    ) -> ProviderInstallationArchiveExtractionResult:
        extract_archive = getattr(
            self.installation_executor,
            "extract_local_artifact_archive",
            None,
        )
        if extract_archive is None:
            raise ValueError(
                "current installation executor does not support local artifact archive extraction"
            )
        return extract_archive(
            archive_relative_path=archive_relative_path,
            destination_directory=destination_directory,
        )

    def model_artifact_inventory(self) -> ModelArtifactInventory:
        inventory = getattr(self.installation_executor, "model_artifact_inventory", None)
        if inventory is None:
            return ModelArtifactInventory(supported=False)
        return inventory()

    def promote_local_artifact_to_model_store(
        self,
        *,
        relative_path: str,
    ) -> ModelArtifact:
        promote_artifact = getattr(
            self.installation_executor,
            "promote_local_artifact_to_model_store",
            None,
        )
        if promote_artifact is None:
            raise ValueError(
                "current installation executor does not support model artifact storage"
            )
        return promote_artifact(relative_path=relative_path)

    def delete_model_artifact(self, *, artifact_id: str) -> None:
        delete_artifact = getattr(
            self.installation_executor,
            "delete_model_artifact",
            None,
        )
        if delete_artifact is None:
            raise ValueError(
                "current installation executor does not support model artifact storage"
            )
        delete_artifact(artifact_id=artifact_id)

    def list_model_artifact_sets(self) -> list[ModelArtifactSet]:
        list_sets = getattr(self.installation_executor, "list_model_artifact_sets", None)
        if list_sets is None:
            return []
        return list_sets()

    def create_model_artifact_set(
        self,
        *,
        display_name: str,
        files: list[dict],
    ) -> ModelArtifactSet:
        create_set = getattr(self.installation_executor, "create_model_artifact_set", None)
        if create_set is None:
            raise ValueError(
                "current installation executor does not support model artifact storage"
            )
        return create_set(display_name=display_name, files=files)

    def delete_model_artifact_set(self, *, artifact_set_id: str) -> None:
        deployments = self.store.model_deployments_for_artifact_set(artifact_set_id)
        if deployments:
            raise ValueError(
                "cannot delete a model artifact set referenced by model deployment: "
                f"{deployments[0].model_deployment_id}"
            )
        delete_set = getattr(self.installation_executor, "delete_model_artifact_set", None)
        if delete_set is None:
            raise ValueError(
                "current installation executor does not support model artifact storage"
            )
        delete_set(artifact_set_id=artifact_set_id)

    def bind_model_artifact_set(
        self,
        *,
        model_deployment_id: str,
        artifact_set_id: str,
    ) -> ModelDeployment:
        deployment = self.store.get_model_deployment(model_deployment_id)
        if self.store.model_deployment_has_runtime_bindings(model_deployment_id):
            raise ValueError(
                "cannot change a model deployment artifact set after runtime bindings exist"
            )
        get_set = getattr(self.installation_executor, "get_model_artifact_set", None)
        if get_set is None:
            raise ValueError(
                "current installation executor does not support model artifact storage"
            )
        get_set(artifact_set_id)
        updated = deployment.model_copy(update={"artifact_set_id": artifact_set_id})
        self.store.save_model_deployment(updated)
        return updated

    def collect_model_artifact_garbage(self) -> ModelArtifactGarbageCollectionResult:
        collect = getattr(
            self.installation_executor,
            "collect_model_artifact_garbage",
            None,
        )
        if collect is None:
            raise ValueError(
                "current installation executor does not support model artifact storage"
            )
        return collect()

    def materialize_model_artifact_set(
        self, *, provider_instance_id: str, artifact_set_id: str, destination: str
    ) -> ProviderArtifactMaterialization:
        self.store.get_provider_instance(provider_instance_id)
        materialize = getattr(self.installation_executor, "materialize_model_artifact_set", None)
        if materialize is None:
            raise ValueError("current installation executor does not support model artifact materialization")
        result = materialize(
            provider_instance_id=provider_instance_id,
            artifact_set_id=artifact_set_id,
            destination=destination,
        )
        self.store.save_artifact_materialization(result)
        return result

    def list_artifact_materializations(self) -> list[ProviderArtifactMaterialization]:
        return self.store.list_artifact_materializations()

    def model_deployment_artifact_readiness(
        self, deployment: ModelDeployment
    ) -> dict:
        if deployment.artifact_set_id is None:
            return {
                "required": False,
                "ready": True,
                "status": "NOT_REQUIRED",
                "artifact_set_id": None,
                "materialization_id": None,
                "destination": None,
            }
        materializations = [
            item
            for item in self.store.list_artifact_materializations(
                provider_instance_id=deployment.provider_instance_id
            )
            if item.artifact_set_id == deployment.artifact_set_id
        ]
        ready = next(
            (item for item in materializations if item.status == "READY"),
            None,
        )
        if ready is not None:
            return {
                "required": True,
                "ready": True,
                "status": "READY",
                "artifact_set_id": deployment.artifact_set_id,
                "materialization_id": ready.materialization_id,
                "destination": ready.destination,
            }
        failed = next(
            (item for item in materializations if item.status == "FAILED"),
            None,
        )
        return {
            "required": True,
            "ready": False,
            "status": "FAILED" if failed is not None else "MISSING",
            "artifact_set_id": deployment.artifact_set_id,
            "materialization_id": (
                failed.materialization_id if failed is not None else None
            ),
            "destination": failed.destination if failed is not None else None,
        }

    def _ensure_model_deployment_artifacts_ready(
        self, deployment: ModelDeployment
    ) -> None:
        readiness = self.model_deployment_artifact_readiness(deployment)
        if not readiness["ready"]:
            raise ValueError(
                "model deployment artifact set must be materialized before "
                "creating a Runtime Binding"
            )

    def runtime_binding_endpoint_admission(
        self,
        runtime_binding_id: str,
        endpoint_payload: dict | None = None,
    ) -> dict:
        binding = self.store.get_runtime_binding(runtime_binding_id)
        deployment = self.store.get_model_deployment(binding.model_deployment_id)
        blockers: list[dict] = []
        warnings: list[dict] = []
        dimensions: dict[str, dict] = {}

        runtime_ready = binding.status == "ready" and binding.operational_state == "READY"
        dimensions["runtime_binding"] = {
            "ready": runtime_ready,
            "status": binding.status,
            "operational_state": binding.operational_state,
            "runtime_binding_id": binding.runtime_binding_id,
            "runtime_id": binding.runtime_id,
            "runtime_generation": binding.runtime_generation,
            "runtime_configuration_hash": binding.runtime_configuration_hash,
        }
        if not runtime_ready:
            blockers.append(
                {
                    "code": "RUNTIME_BINDING_NOT_READY",
                    "message": "Runtime Binding must be ready before creating an Endpoint draft.",
                    "status": binding.status,
                    "operational_state": binding.operational_state,
                }
            )

        artifact_readiness = self.model_deployment_artifact_readiness(deployment)
        dimensions["artifact_materialization"] = artifact_readiness
        if not artifact_readiness["ready"]:
            blockers.append(
                {
                    "code": "MODEL_ARTIFACTS_NOT_READY",
                    "message": "Model artifacts must be materialized before Endpoint draft creation.",
                    "status": artifact_readiness["status"],
                    "artifact_set_id": artifact_readiness["artifact_set_id"],
                }
            )

        try:
            compatibility_bundle = self.bundle_config_for_runtime_binding(
                runtime_binding_id
            )
            bundle_hash = self.bundle_hash_for_runtime_binding(runtime_binding_id)
            bundle_ready = bool(compatibility_bundle.bundle_id and bundle_hash)
            dimensions["compatibility_bundle"] = {
                "ready": bundle_ready,
                "bundle_id": compatibility_bundle.bundle_id,
                "bundle_hash": bundle_hash,
                "workload_type": compatibility_bundle.workload_type,
                "endpoint": compatibility_bundle.endpoint,
            }
            if not bundle_ready:
                blockers.append(
                    {
                        "code": "COMPATIBILITY_BUNDLE_INVALID",
                        "message": "Runtime Binding compatibility bundle projection is incomplete.",
                    }
                )
        except (KeyError, ValueError) as error:
            dimensions["compatibility_bundle"] = {
                "ready": False,
                "status": "ERROR",
            }
            blockers.append(
                {
                    "code": "COMPATIBILITY_BUNDLE_UNAVAILABLE",
                    "message": str(error),
                }
            )

        payload = endpoint_payload or {}
        owner_wallet = str(payload.get("owner_wallet") or "").strip()
        owner_ready = endpoint_payload is None or bool(owner_wallet)
        dimensions["endpoint_identity"] = {
            "ready": owner_ready,
            "owner_wallet_present": bool(owner_wallet),
        }
        if not owner_ready:
            blockers.append(
                {
                    "code": "ENDPOINT_OWNER_WALLET_REQUIRED",
                    "message": "Endpoint draft creation requires an owner wallet.",
                }
            )

        model_class = payload.get("model_class")
        capabilities = payload.get("capabilities")
        capability_ready = True
        capability_status = "MATCHED"
        if model_class is not None and model_class != binding.capability_id:
            capability_ready = False
            capability_status = "MODEL_CLASS_MISMATCH"
            blockers.append(
                {
                    "code": "ENDPOINT_CAPABILITY_MISMATCH",
                    "message": "Endpoint model_class must match the Runtime Binding capability.",
                    "expected": binding.capability_id,
                    "actual": model_class,
                }
            )
        if capabilities is not None and binding.capability_id not in capabilities:
            capability_ready = False
            capability_status = "CAPABILITIES_MISSING_BINDING"
            blockers.append(
                {
                    "code": "ENDPOINT_CAPABILITY_NOT_ADVERTISED",
                    "message": "Endpoint capabilities must include the Runtime Binding capability.",
                    "expected": binding.capability_id,
                }
            )
        dimensions["capability"] = {
            "ready": capability_ready,
            "status": capability_status,
            "capability_id": binding.capability_id,
            "capability_version": binding.capability_version,
            "capability_definition_hash": binding.capability_definition_hash,
        }

        pricing = payload.get("pricing") or {}
        configured_prices = [
            pricing.get("fixed_price"),
            pricing.get("input_price"),
            pricing.get("output_price"),
            pricing.get("audio_input_second_price"),
        ]
        pricing_configured = any(value is not None for value in configured_prices)
        dimensions["pricing"] = {
            "ready": True,
            "status": "CONFIGURED" if pricing_configured else "DRAFT_PRICE_UNSET",
            "billing_unit": pricing.get("billing_unit", "request"),
        }
        if not pricing_configured:
            warnings.append(
                {
                    "code": "ENDPOINT_PRICING_NOT_CONFIGURED",
                    "message": "Endpoint pricing is unset; keep the draft private until pricing is reviewed.",
                }
            )

        publication = payload.get("publication") or {}
        visibility = publication.get("visibility", "private")
        shared_wallets = publication.get("shared_with_wallet_ids") or []
        accepts_external_requests = bool(
            publication.get("accepts_external_requests", False)
        )
        publication_ready = True
        publication_status = "DRAFT_PRIVATE"
        if visibility == "public":
            publication_status = "PUBLIC_READY"
        elif visibility == "shared":
            publication_status = "SHARED_READY"
            if not shared_wallets:
                publication_ready = False
                publication_status = "SHARED_ALLOWLIST_MISSING"
                blockers.append(
                    {
                        "code": "ENDPOINT_SHARED_ALLOWLIST_REQUIRED",
                        "message": "Shared Endpoint drafts require at least one allowed wallet.",
                    }
                )
        if accepts_external_requests and visibility == "private":
            publication_ready = False
            publication_status = "PRIVATE_EXTERNAL_REQUESTS_CONFLICT"
            blockers.append(
                {
                    "code": "ENDPOINT_PUBLICATION_POLICY_CONFLICT",
                    "message": "Private Endpoint drafts cannot accept external requests.",
                }
            )
        dimensions["publication"] = {
            "ready": publication_ready,
            "status": publication_status,
            "visibility": visibility,
            "accepts_external_requests": accepts_external_requests,
        }

        return {
            "runtime_binding_id": binding.runtime_binding_id,
            "ready": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "dimensions": dimensions,
        }

    def run_installation_diagnostics(
        self,
        *,
        plugin_id: str,
        configuration: dict,
        approved_permissions: list[str] | None = None,
        upgrade_acknowledged: bool = False,
        selected_secret_handles: list[dict] | None = None,
    ) -> ProviderInstallationDiagnostics:
        plugin = self._get_plugin(plugin_id)
        manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
        package_verification = self._package_verification(manifest)
        diagnostics_configuration = deepcopy(configuration)
        plan = InstallationPlan.model_validate(
            self.build_installation_plan(
                plugin_id=plugin_id,
                configuration=diagnostics_configuration,
            )
        )
        plan_hash = _canonical_hash(plan.model_dump(mode="json"))
        configuration_hash = _canonical_hash(deepcopy(diagnostics_configuration))
        requested_permission_ids = [
            permission.permission_id for permission in plan.required_permissions
        ]
        normalized_sandbox_policy = self._normalized_sandbox_policy(manifest)
        executor_sandbox_capabilities = self._executor_sandbox_capabilities()
        upgrade_review = self._build_upgrade_review(
            plugin_id=plugin_id,
            requested_permissions=requested_permission_ids,
            package_verification=package_verification,
            normalized_sandbox_policy=normalized_sandbox_policy,
        )
        normalized_secret_requirements = self._normalized_secret_requirements(manifest)
        checks: list[ProviderInstallationDiagnosticCheck] = [
            ProviderInstallationDiagnosticCheck(
                check_id="configuration_valid",
                status="PASS",
                summary="Declarative installation plan built successfully.",
                details={
                    "plan_id": plan.plan_id,
                    "declared_sections": [
                        section
                        for section in (
                            "containers",
                            "processes",
                            "model_downloads",
                            "volumes",
                            "networks",
                            "environment",
                            "resource_limits",
                            "health_checks",
                        )
                        if getattr(plan, section)
                    ],
                },
            )
        ]
        package_status_to_check_status = {
            "VERIFIED": "PASS",
            "UNVERIFIED": "WARN",
            "INVALID": "FAIL",
        }
        checks.append(
            ProviderInstallationDiagnosticCheck(
                check_id="package_verification",
                status=package_status_to_check_status[package_verification.status],
                summary=package_verification.summary,
                details=package_verification.model_dump(mode="json"),
            )
        )
        try:
            self._validate_supported_sandbox_policy(
                normalized_sandbox_policy,
                executor_sandbox_capabilities=executor_sandbox_capabilities,
            )
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="sandbox_policy",
                    status="PASS",
                    summary=(
                        "Plugin sandbox policy is supported by the current executor "
                        "sandbox boundary."
                    ),
                    details={
                        "plugin_sandbox_policy": deepcopy(normalized_sandbox_policy),
                        "executor_sandbox_capabilities": (
                            executor_sandbox_capabilities.model_dump(mode="json")
                        ),
                    },
                )
            )
        except ValueError as exc:
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="sandbox_policy",
                    status="FAIL",
                    summary=str(exc),
                    details={
                        "plugin_sandbox_policy": deepcopy(normalized_sandbox_policy),
                        "executor_sandbox_capabilities": (
                            executor_sandbox_capabilities.model_dump(mode="json")
                        ),
                    },
                )
            )

        try:
            self._validate_upgrade_acknowledgement(
                upgrade_review=upgrade_review,
                upgrade_acknowledged=upgrade_acknowledged,
            )
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="upgrade_review",
                    status="PASS",
                    summary=upgrade_review.summary,
                    details=upgrade_review.model_dump(mode="json"),
                )
            )
        except ValueError as exc:
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="upgrade_review",
                    status="FAIL",
                    summary=str(exc),
                    details=upgrade_review.model_dump(mode="json"),
                )
            )

        try:
            normalized_permissions = self._validate_approved_permissions(
                requested_permissions=requested_permission_ids,
                approved_permissions=approved_permissions,
            )
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="permissions_acknowledged",
                    status="PASS",
                    summary="Requested permissions are fully acknowledged.",
                    details={
                        "requested_permissions": [
                            permission.permission_id for permission in plan.required_permissions
                        ],
                        "approved_permissions": normalized_permissions,
                    },
                )
            )
        except ValueError as exc:
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="permissions_acknowledged",
                    status="FAIL",
                    summary=str(exc),
                    details={
                        "requested_permissions": [
                            permission.permission_id for permission in plan.required_permissions
                        ],
                        "approved_permissions": list(approved_permissions or []),
                    },
                )
            )

        normalized_selected_handles: list[SelectedSecretHandle] = []
        try:
            normalized_selected_handles = self._validate_selected_secret_handles(
                normalized_requirements=normalized_secret_requirements,
                selected_secret_handles=selected_secret_handles,
            )
            missing_optional_requirements = [
                requirement["requirement_key"]
                for requirement in normalized_secret_requirements
                if not requirement["required"]
                and requirement["requirement_key"]
                not in {
                    handle.requirement_key for handle in normalized_selected_handles
                }
            ]
            if missing_optional_requirements:
                checks.append(
                    ProviderInstallationDiagnosticCheck(
                        check_id="secret_handles",
                        status="WARN",
                        summary="Optional secret handles are still unassigned.",
                        details={
                            "selected_secret_handles": [
                                handle.model_dump(mode="json")
                                for handle in normalized_selected_handles
                            ],
                            "missing_optional_requirements": missing_optional_requirements,
                        },
                    )
                )
            else:
                checks.append(
                    ProviderInstallationDiagnosticCheck(
                        check_id="secret_handles",
                        status="PASS",
                        summary="Secret handle requirements are satisfied.",
                        details={
                            "selected_secret_handles": [
                                handle.model_dump(mode="json")
                                for handle in normalized_selected_handles
                            ],
                        },
                    )
                )
        except ValueError as exc:
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="secret_handles",
                    status="FAIL",
                    summary=str(exc),
                    details={
                        "selected_secret_handles": list(selected_secret_handles or []),
                        "requirements": normalized_secret_requirements,
                    },
                )
            )

        diagnostic_approval = ProviderInstallationApproval(
            approval_id="diagnostic-preview",
            plugin_id=plugin_id,
            plan_id=plan.plan_id,
            plan_hash=plan_hash,
            configuration_hash=configuration_hash,
            configuration=deepcopy(diagnostics_configuration),
            approved_permissions=requested_permission_ids,
            upgrade_review=upgrade_review.model_dump(mode="json"),
            upgrade_acknowledged=upgrade_acknowledged,
            acknowledged_package_verification=package_verification.model_dump(mode="json"),
            acknowledged_sandbox_policy=deepcopy(normalized_sandbox_policy),
            acknowledged_secret_requirements=normalized_secret_requirements,
            selected_secret_handles=normalized_selected_handles,
            created_at=_now_iso(),
        )
        checks.extend(
            self._executor_diagnostic_checks(
                approval=diagnostic_approval,
                plan=plan,
                configuration=deepcopy(diagnostics_configuration),
                manifest=manifest.model_dump(mode="json"),
            )
        )
        rollback_result = self._rollback_preview(
            approval=diagnostic_approval,
            plan=plan,
            configuration=deepcopy(diagnostics_configuration),
            manifest=manifest.model_dump(mode="json"),
        )
        checks.append(
            ProviderInstallationDiagnosticCheck(
                check_id="executor_readiness",
                status="PASS",
                summary=f"Executor {self.installation_executor.executor_id} accepted the dry-run preview.",
                details={"executor_id": self.installation_executor.executor_id},
            )
        )
        checks.append(
            ProviderInstallationDiagnosticCheck(
                check_id="rollback_preview",
                status="FAIL" if rollback_result.status == "FAILED" else "PASS",
                summary=rollback_result.summary,
                details=deepcopy(rollback_result.details),
            )
        )

        readiness_status = self._diagnostic_readiness_status(checks)
        return ProviderInstallationDiagnostics(
            diagnostics_id=f"pid-{uuid4().hex[:12]}",
            plugin_id=plugin_id,
            plan_id=plan.plan_id,
            plan_hash=plan_hash,
            configuration_hash=configuration_hash,
            executor_id=self.installation_executor.executor_id,
            readiness_status=readiness_status,
            checks=checks,
            rollback_result=rollback_result,
            created_at=_now_iso(),
        )

    def apply_installation_approval(self, approval_id: str) -> ProviderInstallationJob:
        approval = self.store.get_installation_approval(approval_id)
        if approval.status != "APPROVED":
            raise ValueError("installation approval is not active")
        approved_configuration = deepcopy(approval.configuration)
        if _canonical_hash(deepcopy(approved_configuration)) != approval.configuration_hash:
            raise ValueError("installation configuration hash mismatch")

        plugin = self._get_plugin(approval.plugin_id)
        manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
        package_verification = self._package_verification(manifest)
        self._validate_package_verification(package_verification)
        plan_dict = self.build_installation_plan(
            plugin_id=approval.plugin_id,
            configuration=approved_configuration,
        )
        plan = InstallationPlan.model_validate(plan_dict)
        if _canonical_hash(deepcopy(plan_dict)) != approval.plan_hash:
            raise ValueError("installation plan hash mismatch")
        normalized_sandbox_policy = self._normalized_sandbox_policy(manifest)
        self._validate_supported_sandbox_policy(
            normalized_sandbox_policy,
            executor_sandbox_capabilities=self._executor_sandbox_capabilities(),
        )
        if approval.upgrade_review.get("requires_acknowledgement") and not approval.upgrade_acknowledged:
            raise ValueError("installation approval missing required upgrade acknowledgement")
        if normalized_sandbox_policy != approval.acknowledged_sandbox_policy:
            raise ValueError("installation sandbox policy changed since approval")
        normalized_secret_requirements = self._normalized_secret_requirements(manifest)
        if normalized_secret_requirements != approval.acknowledged_secret_requirements:
            raise ValueError("installation secret requirements changed since approval")
        if self._package_verification_binding(
            package_verification.model_dump(mode="json")
        ) != self._package_verification_binding(approval.acknowledged_package_verification):
            raise ValueError("installation package identity changed since approval")
        rebuilt_permission_ids = [
            permission.permission_id for permission in plan.required_permissions
        ]
        if approval.approved_permissions != rebuilt_permission_ids:
            raise ValueError("installation approved permissions do not match current plan")

        job = ProviderInstallationJob(
            job_id=f"pij-{uuid4().hex[:12]}",
            approval_id=approval.approval_id,
            plugin_id=approval.plugin_id,
            plan_id=approval.plan_id,
            plan_hash=approval.plan_hash,
            configuration_hash=approval.configuration_hash,
            status="QUEUED",
            executor_id=self.installation_executor.executor_id,
            created_at=_now_iso(),
        )
        self.store.save_installation_job(job)
        job = job.model_copy(update={"status": "RUNNING", "started_at": _now_iso()})
        self.store.save_installation_job(job)

        provider_instance_id = f"pi-{uuid4().hex[:12]}"
        try:
            approval_for_executor = approval.model_copy(deep=True)
            result = self.installation_executor.apply(
                approval=approval_for_executor,
                plan=plan,
                configuration=deepcopy(approved_configuration),
                manifest=manifest.model_dump(mode="json"),
                provider_instance_id=provider_instance_id,
            )
            provider_instance = ProviderInstance.model_validate(result.provider_instance)
            self._validate_applied_provider_instance(
                provider_instance=provider_instance,
                provider_instance_id=provider_instance_id,
                approval=approval,
                approved_configuration=approved_configuration,
            )
            self.store.save_provider_instance(provider_instance)
            job = job.model_copy(
                update={
                    "status": "SUCCEEDED",
                    "step_results": result.step_results,
                    "provider_instance_id": provider_instance.provider_instance_id,
                    "rollback_status": (
                        result.rollback_result.status
                        if result.rollback_result is not None
                        else "NOT_NEEDED"
                    ),
                    "rollback_summary": (
                        result.rollback_result.summary
                        if result.rollback_result is not None
                        else None
                    ),
                    "rollback_step_results": (
                        result.rollback_result.step_results
                        if result.rollback_result is not None
                        else []
                    ),
                    "completed_at": _now_iso(),
                }
            )
        except Exception as exc:
            rollback_started_at = _now_iso()
            rollback_result = self._rollback_execution(
                approval=approval,
                plan=plan,
                configuration=deepcopy(approved_configuration),
                manifest=manifest.model_dump(mode="json"),
                provider_instance_id=provider_instance_id,
            )
            rollback_result = self._finalize_local_inventory_cleanup(
                rollback_result=rollback_result,
                provider_instance_id=provider_instance_id,
            )
            job = job.model_copy(
                update={
                    "status": "FAILED",
                    "rollback_status": rollback_result.status,
                    "rollback_summary": rollback_result.summary,
                    "rollback_step_results": rollback_result.step_results,
                    "rollback_started_at": rollback_started_at,
                    "rollback_completed_at": _now_iso(),
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                    "completed_at": _now_iso(),
                }
            )
        self.store.save_installation_job(job)
        return job

    def rollback_installation_job(self, job_id: str) -> ProviderInstallationJob:
        job = self.store.get_installation_job(job_id)
        if job.status not in {"SUCCEEDED", "FAILED"}:
            raise ValueError("installation job must be terminal before rollback can run")
        if job.rollback_status == "COMPLETED":
            raise ValueError("installation job rollback already completed")

        approval = self.store.get_installation_approval(job.approval_id)
        plugin = self._get_plugin(approval.plugin_id)
        manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
        plan_dict = self.build_installation_plan(
            plugin_id=approval.plugin_id,
            configuration=deepcopy(approval.configuration),
        )
        plan = InstallationPlan.model_validate(plan_dict)

        job = job.model_copy(update={"rollback_started_at": _now_iso()})
        self.store.save_installation_job(job)

        rollback_result = self._rollback_execution(
            approval=approval,
            plan=plan,
            configuration=deepcopy(approval.configuration),
            manifest=manifest.model_dump(mode="json"),
            provider_instance_id=job.provider_instance_id,
        )
        rollback_result = self._finalize_local_inventory_cleanup(
            rollback_result=rollback_result,
            provider_instance_id=job.provider_instance_id,
        )

        job = job.model_copy(
            update={
                "rollback_status": rollback_result.status,
                "rollback_summary": rollback_result.summary,
                "rollback_step_results": rollback_result.step_results,
                "rollback_completed_at": _now_iso(),
            }
        )
        self.store.save_installation_job(job)
        return job

    def list_installation_jobs(self) -> list[ProviderInstallationJob]:
        return self.store.list_installation_jobs()

    def _diagnostic_readiness_status(
        self,
        checks: list[ProviderInstallationDiagnosticCheck],
    ) -> str:
        statuses = [check.status for check in checks]
        if "FAIL" in statuses:
            return "BLOCKED"
        if "WARN" in statuses:
            return "ACTION_REQUIRED"
        return "READY"

    def _executor_diagnostic_checks(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> list[ProviderInstallationDiagnosticCheck]:
        diagnostic_checks = getattr(self.installation_executor, "diagnostic_checks", None)
        if diagnostic_checks is None:
            return []
        try:
            return list(
                diagnostic_checks(
                    approval=approval,
                    plan=plan,
                    configuration=configuration,
                    manifest=manifest,
                )
            )
        except Exception as exc:
            return [
                ProviderInstallationDiagnosticCheck(
                    check_id="executor_diagnostics",
                    status="FAIL",
                    summary=f"Executor diagnostics failed: {exc}",
                    details={"executor_id": self.installation_executor.executor_id},
                )
            ]

    def _rollback_preview(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> ProviderInstallationRollbackResult:
        executor = self.installation_executor
        rollback_preview = getattr(executor, "rollback_preview", None)
        if rollback_preview is None:
            return ProviderInstallationRollbackResult(
                status="FAILED",
                summary=(
                    f"Executor {executor.executor_id} does not expose rollback preview; "
                    "manual cleanup guidance is required."
                ),
                details={
                    "executor_id": executor.executor_id,
                    "rollback_preview_available": False,
                },
            )
        try:
            return rollback_preview(
                approval=approval,
                plan=plan,
                configuration=configuration,
                manifest=manifest,
            )
        except Exception as exc:
            return ProviderInstallationRollbackResult(
                status="FAILED",
                summary=(
                    f"Rollback preview failed for executor {executor.executor_id}: {exc}"
                ),
                details={
                    "executor_id": executor.executor_id,
                    "rollback_preview_available": True,
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                },
            )

    def _rollback_execution(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
        provider_instance_id: str | None,
    ) -> ProviderInstallationRollbackResult:
        executor = self.installation_executor
        rollback = getattr(executor, "rollback", None)
        if rollback is None:
            preview = self._rollback_preview(
                approval=approval,
                plan=plan,
                configuration=configuration,
                manifest=manifest,
            )
            return preview.model_copy(
                update={
                    "status": "FAILED",
                    "summary": (
                        f"Executor {executor.executor_id} does not expose rollback execution; "
                        "manual cleanup guidance is required."
                    ),
                    "details": {
                        **deepcopy(preview.details),
                        "executor_id": executor.executor_id,
                        "rollback_execution_available": False,
                        "provider_instance_id": provider_instance_id,
                    },
                }
            )
        try:
            return rollback(
                approval=approval,
                plan=plan,
                configuration=configuration,
                manifest=manifest,
                provider_instance_id=provider_instance_id,
            )
        except Exception as exc:
            return ProviderInstallationRollbackResult(
                status="FAILED",
                summary=(
                    f"Rollback execution failed for executor {executor.executor_id}: {exc}"
                ),
                details={
                    "executor_id": executor.executor_id,
                    "rollback_execution_available": True,
                    "provider_instance_id": provider_instance_id,
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                },
            )

    def _finalize_local_inventory_cleanup(
        self,
        *,
        rollback_result: ProviderInstallationRollbackResult,
        provider_instance_id: str | None,
    ) -> ProviderInstallationRollbackResult:
        if provider_instance_id is None:
            return rollback_result
        if rollback_result.status not in {"COMPLETED", "NOT_REQUIRED", "NOT_NEEDED"}:
            return rollback_result

        cleanup_step: ProviderInstallationStepResult
        if any(
            instance.provider_instance_id == provider_instance_id
            for instance in self.store.list_provider_instances()
        ):
            self.store.delete_provider_instance(provider_instance_id)
            cleanup_step = ProviderInstallationStepResult(
                step_id="rollback-delete-local-provider-instance",
                step_type="rollback_local_inventory_delete",
                status="RECORDED",
                summary="Removed local provider inventory state for the rolled back install job.",
                details={"provider_instance_id": provider_instance_id},
            )
        else:
            cleanup_step = ProviderInstallationStepResult(
                step_id="rollback-local-provider-instance-missing",
                step_type="rollback_local_inventory_delete",
                status="SKIPPED",
                summary="Local provider inventory state was already absent before rollback cleanup.",
                details={"provider_instance_id": provider_instance_id},
            )

        return rollback_result.model_copy(
            update={
                "step_results": [*rollback_result.step_results, cleanup_step],
                "details": {
                    **deepcopy(rollback_result.details),
                    "local_inventory_cleanup": cleanup_step.status,
                },
            }
        )

    def _latest_installation_approval_for_plugin(
        self,
        plugin_id: str,
    ) -> ProviderInstallationApproval | None:
        approvals = [
            approval
            for approval in self.store.list_installation_approvals()
            if approval.plugin_id == plugin_id
        ]
        return approvals[-1] if approvals else None

    def _build_upgrade_review(
        self,
        *,
        plugin_id: str,
        requested_permissions: list[str],
        package_verification: PluginPackageVerification,
        normalized_sandbox_policy: dict,
    ) -> ProviderInstallationUpgradeReview:
        latest_approval = self._latest_installation_approval_for_plugin(plugin_id)
        if latest_approval is None:
            return ProviderInstallationUpgradeReview(
                status="INITIAL_APPROVAL",
                requires_acknowledgement=False,
                current_package_verification=package_verification.model_dump(mode="json"),
                current_sandbox_policy=deepcopy(normalized_sandbox_policy),
                summary="No previous installation approval exists for this plugin.",
            )
        previous_permissions = set(latest_approval.approved_permissions)
        current_permissions = set(requested_permissions)
        added_permissions = sorted(current_permissions - previous_permissions)
        removed_permissions = sorted(previous_permissions - current_permissions)
        previous_package_verification = deepcopy(
            latest_approval.acknowledged_package_verification
        )
        current_package_verification = package_verification.model_dump(mode="json")
        package_verification_changed = self._package_verification_binding(
            previous_package_verification
        ) != self._package_verification_binding(current_package_verification)
        previous_sandbox_policy = deepcopy(latest_approval.acknowledged_sandbox_policy)
        sandbox_policy_changed = previous_sandbox_policy != normalized_sandbox_policy
        if (
            not added_permissions
            and not removed_permissions
            and not sandbox_policy_changed
            and not package_verification_changed
        ):
            return ProviderInstallationUpgradeReview(
                status="UNCHANGED",
                requires_acknowledgement=False,
                previous_package_verification=previous_package_verification,
                current_package_verification=current_package_verification,
                previous_sandbox_policy=previous_sandbox_policy,
                current_sandbox_policy=deepcopy(normalized_sandbox_policy),
                summary="Permission, sandbox contract, and package identity match the latest approval.",
            )
        return ProviderInstallationUpgradeReview(
            status="CHANGED",
            requires_acknowledgement=True,
            added_permissions=added_permissions,
            removed_permissions=removed_permissions,
            package_verification_changed=package_verification_changed,
            previous_package_verification=previous_package_verification,
            current_package_verification=current_package_verification,
            sandbox_policy_changed=sandbox_policy_changed,
            previous_sandbox_policy=previous_sandbox_policy,
            current_sandbox_policy=deepcopy(normalized_sandbox_policy),
            summary="Installation permission, sandbox contract, or package identity changed since the latest approval.",
        )

    def _validate_upgrade_acknowledgement(
        self,
        *,
        upgrade_review: ProviderInstallationUpgradeReview,
        upgrade_acknowledged: bool,
    ) -> None:
        if upgrade_review.requires_acknowledgement and not upgrade_acknowledged:
            raise ValueError(
                "installation permission or sandbox change requires explicit upgrade acknowledgement"
            )

    def _normalized_sandbox_policy(
        self,
        manifest: ProviderPluginManifest,
    ) -> dict:
        return manifest.sandbox_policy.model_dump(mode="json")

    def _package_verification(
        self,
        manifest: ProviderPluginManifest,
    ) -> PluginPackageVerification:
        return verify_plugin_manifest_package(
            manifest,
            trusted_publisher_keys=self.trusted_publisher_keys,
        )

    def _package_verification_binding(self, verification: dict) -> dict:
        return {
            "status": verification.get("status"),
            "verification_mode": verification.get("verification_mode"),
            "package_digest": verification.get("package_digest"),
            "declared_manifest_hash": verification.get("declared_manifest_hash"),
            "computed_manifest_hash": verification.get("computed_manifest_hash"),
            "publisher_key_id": verification.get("publisher_key_id"),
            "signature_present": verification.get("signature_present"),
            "trusted_publisher": verification.get("trusted_publisher"),
        }

    def _validate_package_verification(
        self,
        package_verification: PluginPackageVerification,
    ) -> None:
        if package_verification.status == "INVALID":
            raise ValueError(package_verification.summary)

    def _plugin_manifest_payload(self, plugin) -> dict:
        manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
        payload = manifest.model_dump(mode="json")
        payload["package_verification"] = self._package_verification(manifest).model_dump(
            mode="json"
        )
        return payload

    def executor_sandbox_capabilities(self) -> dict:
        return self._executor_sandbox_capabilities().model_dump(mode="json")

    def _executor_sandbox_capabilities(self):
        sandbox_capabilities = getattr(self.installation_executor, "sandbox_capabilities", None)
        if sandbox_capabilities is None:
            return RecordedProviderInstallationExecutor().sandbox_capabilities()
        return sandbox_capabilities()

    def _validate_supported_sandbox_policy(
        self,
        normalized_sandbox_policy: dict,
        *,
        executor_sandbox_capabilities,
    ) -> None:
        execution_mode = normalized_sandbox_policy.get("execution_mode", "RECORDED_ONLY")
        filesystem_scope = normalized_sandbox_policy.get("filesystem_scope", "NONE")
        network_scope = normalized_sandbox_policy.get("network_scope", "NONE")
        egress_rules = normalized_sandbox_policy.get("egress_rules", [])
        secret_scope = normalized_sandbox_policy.get("secret_scope", "DECLARED_HANDLES_ONLY")
        if execution_mode not in executor_sandbox_capabilities.supported_execution_modes:
            raise ValueError(
                "plugin sandbox policy requires an unsupported execution mode: "
                f"{execution_mode}"
            )
        if filesystem_scope not in executor_sandbox_capabilities.supported_filesystem_scopes:
            raise ValueError(
                "plugin sandbox policy requires an unsupported filesystem scope: "
                f"{filesystem_scope}"
            )
        if network_scope not in executor_sandbox_capabilities.supported_network_scopes:
            raise ValueError(
                "plugin sandbox policy requires an unsupported network scope: "
                f"{network_scope}"
            )
        if network_scope == "DECLARED_EGRESS" and not egress_rules:
            raise ValueError(
                "plugin sandbox policy requires at least one exact egress rule"
            )
        if network_scope != "DECLARED_EGRESS" and egress_rules:
            raise ValueError(
                "plugin sandbox policy cannot contain egress rules outside DECLARED_EGRESS"
            )
        if secret_scope not in executor_sandbox_capabilities.supported_secret_scopes:
            raise ValueError(
                "plugin sandbox policy requires an unsupported secret scope: "
                f"{secret_scope}"
            )

    def _normalized_secret_requirements(
        self,
        manifest: ProviderPluginManifest,
    ) -> list[dict]:
        normalized: list[dict] = []
        for requirement in manifest.secret_requirements:
            normalized.append(
                {
                    "requirement_key": self._secret_requirement_key(
                        secret_type=requirement.secret_type,
                        label=requirement.label,
                    ),
                    "secret_type": requirement.secret_type,
                    "label": requirement.label,
                    "required": requirement.required,
                    "allowed_usage": list(requirement.allowed_usage),
                }
            )
        return normalized

    def _validate_approved_permissions(
        self,
        *,
        requested_permissions: list[str],
        approved_permissions: list[str] | None,
    ) -> list[str]:
        requested_permission_ids = list(requested_permissions)
        if approved_permissions is None:
            return requested_permission_ids
        normalized_approved_permissions = list(approved_permissions)
        missing_permissions = [
            permission_id
            for permission_id in requested_permission_ids
            if permission_id not in normalized_approved_permissions
        ]
        unexpected_permissions = [
            permission_id
            for permission_id in normalized_approved_permissions
            if permission_id not in requested_permission_ids
        ]
        if missing_permissions or unexpected_permissions:
            raise ValueError(
                "approved permissions must match requested permissions exactly"
            )
        return requested_permission_ids

    def _validate_selected_secret_handles(
        self,
        *,
        normalized_requirements: list[dict],
        selected_secret_handles: list[dict] | None,
    ) -> list[SelectedSecretHandle]:
        selected_handles = list(selected_secret_handles or [])
        requirement_by_key = {
            requirement["requirement_key"]: requirement
            for requirement in normalized_requirements
        }
        matched_keys: set[str] = set()
        normalized_selected_handles: list[SelectedSecretHandle] = []
        for item in selected_handles:
            requirement_key = str(item.get("requirement_key") or "").strip()
            if not requirement_key or requirement_key not in requirement_by_key:
                raise ValueError("selected secret handle does not match a known requirement")
            if requirement_key in matched_keys:
                raise ValueError("selected secret handle requirement keys must be unique")
            secret_handle = str(item.get("secret_handle") or "").strip()
            if not secret_handle:
                raise ValueError("selected secret handle must be non-empty")
            requirement = requirement_by_key[requirement_key]
            normalized_selected_handles.append(
                SelectedSecretHandle(
                    requirement_key=requirement_key,
                    secret_type=requirement["secret_type"],
                    label=requirement["label"],
                    secret_handle=secret_handle,
                    allowed_usage=list(requirement["allowed_usage"]),
                )
            )
            matched_keys.add(requirement_key)

        missing_required_keys = [
            requirement["requirement_key"]
            for requirement in normalized_requirements
            if requirement["required"] and requirement["requirement_key"] not in matched_keys
        ]
        if missing_required_keys:
            raise ValueError("required secret handles are missing")
        return normalized_selected_handles

    def _secret_requirement_key(self, *, secret_type: str, label: str) -> str:
        return f"{secret_type}:{label}"

    def attach_provider_instance(
        self,
        *,
        plugin_id: str,
        display_name: str,
        configuration: dict,
    ) -> ProviderInstance:
        plugin = self._get_plugin(plugin_id)
        normalized_configuration = deepcopy(configuration)
        plugin.validate_provider_configuration(deepcopy(normalized_configuration))
        attached = plugin.attach_existing_provider(deepcopy(normalized_configuration))
        manifest = plugin.plugin_manifest()
        instance = ProviderInstance(
            provider_instance_id=f"pi-{uuid4().hex[:12]}",
            plugin_id=plugin_id,
            provider_family=self._provider_family(manifest, plugin_id),
            display_name=str(attached.get("display_name") or display_name),
            connection_mode=attached.get("connection_mode", "attached"),
            configuration=deepcopy(attached.get("configuration") or normalized_configuration),
            operational_state=attached.get("operational_state", "ready"),
        )
        self.store.save_provider_instance(instance)
        return instance

    def probe_provider_instance(self, provider_instance_id: str) -> dict:
        """Probe an attached or managed provider without starting host processes.

        Installation apply is deliberately declarative in the MVP. A separate,
        explicit probe turns that inventory record into an observed health state
        and gives the operator a useful failure boundary before model discovery.
        """
        instance = self.store.get_provider_instance(provider_instance_id)
        if instance.operational_state == "removed":
            raise ValueError("removed provider instances cannot be probed")
        plugin = self._get_plugin(instance.plugin_id)
        metadata = {
            str(key): str(value)
            for key, value in instance.configuration.items()
            if isinstance(value, (str, int, float, bool))
        }
        runtime = RuntimeHandle(
            runtime_id=f"provider-health-{provider_instance_id}",
            command=[],
            status="running",
            metadata=metadata,
        )
        checked_at = _now_iso()
        health_error: str | None = None
        diagnostic: dict | None = None
        try:
            diagnostic_builder = getattr(plugin, "health_check_diagnostic", None)
            if callable(diagnostic_builder):
                candidate = diagnostic_builder(runtime)
                diagnostic = candidate if isinstance(candidate, dict) else None
                healthy = bool(diagnostic.get("healthy")) if diagnostic is not None else bool(candidate)
            else:  # pragma: no cover - compatibility for external plugins
                healthy = bool(plugin.health_check(runtime))
        except Exception as exc:  # pragma: no cover - plugin boundary
            healthy = False
            health_error = str(exc)
            diagnostic = {
                "healthy": False,
                "code": "provider_health_check_failed",
                "message": health_error or "provider health check failed",
            }
        if not healthy and health_error is None:
            health_error = (
                str(diagnostic.get("message"))
                if diagnostic and diagnostic.get("message")
                else "provider health check returned an unhealthy result"
            )

        updated = instance.model_copy(
            update={
                "operational_state": "ready" if healthy else "error",
                "health_status": "healthy" if healthy else "unhealthy",
                "last_health_check_at": checked_at,
                "last_health_error": None if healthy else health_error,
            }
        )
        self.store.save_provider_instance(updated)
        return {
            "provider_instance": updated.model_dump(mode="json"),
            "healthy": healthy,
            "checked_at": checked_at,
            "error": health_error,
            "diagnostic": diagnostic,
        }

    def _validate_applied_provider_instance(
        self,
        *,
        provider_instance: ProviderInstance,
        provider_instance_id: str,
        approval: ProviderInstallationApproval,
        approved_configuration: dict,
    ) -> None:
        expected = {
            "provider_instance_id": provider_instance_id,
            "plugin_id": approval.plugin_id,
            "connection_mode": "managed",
            "operational_state": "created",
            "configuration": approved_configuration,
        }
        actual = {
            "provider_instance_id": provider_instance.provider_instance_id,
            "plugin_id": provider_instance.plugin_id,
            "connection_mode": provider_instance.connection_mode,
            "operational_state": provider_instance.operational_state,
            "configuration": provider_instance.configuration,
        }
        for field, expected_value in expected.items():
            if actual[field] != expected_value:
                raise ValueError(
                    "provider installation executor returned mismatched "
                    f"{field}: expected {expected_value!r}, got {actual[field]!r}"
                )

    def discover_models(self, provider_instance_id: str) -> list[ModelDeployment]:
        instance = self.store.get_provider_instance(provider_instance_id)
        plugin = self._get_plugin(instance.plugin_id)
        discovered = plugin.discover_models(instance.model_dump(mode="json"))
        deployments: list[ModelDeployment] = []
        for item in discovered:
            model_deployment_id = item.get("model_deployment_id") or (
                f"md-{provider_instance_id}-{uuid4().hex[:8]}"
            )
            try:
                existing = self.store.get_model_deployment(model_deployment_id)
            except KeyError:
                existing = None
            deployment = ModelDeployment(
                model_deployment_id=model_deployment_id,
                provider_instance_id=provider_instance_id,
                provider_model_reference=item["provider_model_reference"],
                operator_display_name=item.get("operator_display_name")
                or item["provider_model_reference"],
                declared_model_name=item.get("declared_model_name"),
                artifact_set_id=(
                    existing.artifact_set_id if existing is not None else None
                ),
                metadata_sources=dict(item.get("metadata_sources") or {}),
                capability_bindings=list(item.get("capability_bindings") or []),
                operational_state=item.get("operational_state", "ready"),
            )
            self.store.save_model_deployment(deployment)
            deployments.append(deployment)
        return deployments

    def create_runtime_binding(
        self,
        *,
        model_deployment_id: str,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> RuntimeBinding:
        deployment = self.store.get_model_deployment(model_deployment_id)
        self._ensure_model_deployment_artifacts_ready(deployment)
        instance = self.store.get_provider_instance(deployment.provider_instance_id)
        plugin = self._get_plugin(instance.plugin_id)
        model_deployment_payload = deployment.model_dump(mode="json")
        model_deployment_payload["provider_configuration"] = dict(
            instance.configuration
        )
        projection = plugin.create_runtime_binding(
            model_deployment=model_deployment_payload,
            capability_id=capability_id,
            capability_version=capability_version,
            capability_definition_hash=capability_definition_hash,
        )
        logical_suffix = self._runtime_binding_logical_suffix(
            model_deployment_id=model_deployment_id,
            capability_id=capability_id,
            capability_version=capability_version,
            capability_definition_hash=capability_definition_hash,
        )
        runtime_binding_id = f"rtb-{logical_suffix}"
        runtime_id = f"runtime-{logical_suffix}"
        compatibility_bundle_id = f"bundle-{runtime_binding_id}"
        manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
        installed_plugin = next(
            (
                item
                for item in self.store.list_installed_plugins()
                if item.plugin_id == instance.plugin_id
                and item.plugin_version == manifest.plugin_version
                and item.state in {"INSTALLED", "ACTIVE"}
            ),
            None,
        )
        binding = RuntimeBinding(
            runtime_binding_id=runtime_binding_id,
            runtime_id=runtime_id,
            runtime_generation=1,
            implementation_class="PLUGIN_MANAGED",
            provider_instance_id=instance.provider_instance_id,
            model_deployment_id=deployment.model_deployment_id,
            capability_id=projection.get("capability_id", capability_id),
            capability_version=projection.get("capability_version", capability_version),
            capability_definition_hash=projection.get(
                "capability_definition_hash",
                capability_definition_hash,
            ),
            plugin_id=instance.plugin_id,
            installed_plugin_id=(
                installed_plugin.installed_plugin_id
                if installed_plugin is not None
                else None
            ),
            plugin_version=manifest.plugin_version,
            adapter_id=projection.get("adapter_id"),
            adapter_version=projection.get("adapter_version"),
            supported_features=list(projection.get("supported_features") or []),
            supported_modalities=list(projection.get("supported_modalities") or []),
            supported_accounting_modes=list(
                projection.get("supported_accounting_modes") or []
            ),
            usage_reporting_profile_hash=projection.get(
                "usage_reporting_profile_hash"
            ),
            dispatcher_route_scope={
                "channel_class": "RUNTIME",
                "runtime_id": runtime_id,
            },
            compatibility_bundle_id=compatibility_bundle_id,
            status=projection.get("status", "ready"),
        )
        profile_builder = {
            "llamacpp-openai": build_llamacpp_usage_profile,
            "ollama-generate": build_ollama_usage_profile,
            "proxy-openai": build_proxy_opaque_usage_profile,
            "vllm-openai": build_vllm_usage_profile,
            "whisper-http": build_whisper_usage_profile,
        }.get(binding.adapter_id)
        if profile_builder is not None:
            profile = profile_builder(
                runtime_id=binding.runtime_id,
                runtime_generation=binding.runtime_generation,
                runtime_configuration_hash=binding.runtime_configuration_hash,
                adapter_version=binding.adapter_version or f"{binding.adapter_id}.v1",
            )
            binding_payload = binding.model_dump(mode="json")
            binding_payload.pop("runtime_configuration_hash", None)
            binding_payload["usage_reporting_profile_hash"] = profile.profile_hash
            binding = RuntimeBinding.model_validate(
                binding_payload
            )
        self.store.save_runtime_binding(binding)
        self._runtime_binding_projections[binding.runtime_binding_id] = dict(
            projection.get("compatibility_bundle") or {}
        )
        return binding

    def bundle_config_for_runtime_binding(self, runtime_binding_id: str) -> BundleConfig:
        binding = self.store.get_runtime_binding(runtime_binding_id)
        deployment = self.store.get_model_deployment(binding.model_deployment_id)
        instance = self.store.get_provider_instance(binding.provider_instance_id)
        projection = dict(
            self._runtime_binding_projections.get(runtime_binding_id)
            or self._rebuild_runtime_binding_projection(binding, deployment)
        )
        endpoint = projection.get("endpoint")
        if endpoint is None:
            endpoint = instance.configuration.get("endpoint") or instance.configuration.get(
                "base_url"
            )
        return BundleConfig(
            bundle_id=binding.compatibility_bundle_id,
            plugin_id=projection.get("plugin_id", instance.plugin_id),
            provider_type=projection.get("provider_type", instance.provider_family),
            workload_type=projection.get("workload_type", binding.capability_id),
            model_id=projection.get("model_id", deployment.provider_model_reference),
            launch_mode=projection.get("launch_mode", "managed_process"),
            endpoint=endpoint,
            provider_api_format=projection.get("provider_api_format"),
            device_affinity=projection.get("device_affinity", "cpu"),
            resource_profile=ResourceProfile(),
            warm_policy="auto",
            priority_class=50,
            max_parallel_requests=1,
            enabled=True,
        )

    def bundle_hash_for_runtime_binding(self, runtime_binding_id: str) -> str:
        return self._bundle_hash(self.bundle_config_for_runtime_binding(runtime_binding_id))

    def _rebuild_runtime_binding_projection(
        self,
        binding: RuntimeBinding,
        deployment: ModelDeployment,
    ) -> dict:
        plugin = self._get_plugin(binding.plugin_id)
        instance = self.store.get_provider_instance(binding.provider_instance_id)
        model_deployment_payload = deployment.model_dump(mode="json")
        model_deployment_payload["provider_configuration"] = dict(
            instance.configuration
        )
        projection = plugin.create_runtime_binding(
            model_deployment=model_deployment_payload,
            capability_id=binding.capability_id,
            capability_version=binding.capability_version,
            capability_definition_hash=binding.capability_definition_hash,
        )
        return dict(projection.get("compatibility_bundle") or {})

    def _get_plugin(self, plugin_id: str):
        if hasattr(self.plugins, "get"):
            return self.plugins.get(plugin_id)
        for plugin in self._list_plugins():
            if plugin.plugin_id == plugin_id:
                return plugin
        raise KeyError(plugin_id)

    def _list_plugins(self) -> list:
        if hasattr(self.plugins, "list"):
            return list(self.plugins.list())
        return list(self.plugins or [])

    def _provider_family(self, manifest: dict, plugin_id: str) -> str:
        families = manifest.get("provider_families") or []
        if families:
            return str(families[0])
        return plugin_id

    def _runtime_binding_logical_suffix(
        self,
        *,
        model_deployment_id: str,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> str:
        digest = hashlib.sha256(
            "|".join(
                [
                    model_deployment_id,
                    capability_id,
                    capability_version,
                    capability_definition_hash,
            ]
        ).encode("utf-8")
        ).hexdigest()
        return digest[:16]

    def _bundle_hash(self, bundle: BundleConfig) -> str:
        payload = json.dumps(
            bundle.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
