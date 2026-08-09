import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.host import (
    PluginHostHello,
    PluginHostIdentity,
    build_plugin_host_activation_proof,
)
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.providers.executor import (
    ControlledFilesystemProviderInstallationExecutor,
    RecordedProviderInstallationExecutor,
    SandboxEnforcedProviderInstallationExecutor,
)
from aidn_hypervisor.providers.models import (
    InstallationPlan,
    ProviderInstallationApproval,
    ProviderInstallationExecutionResult,
    ProviderInstallationJob,
    ProviderPluginManifest,
)
from aidn_hypervisor.providers.package_store import (
    FilesystemPluginPackageStore,
    HttpsPluginPackageAcquirer,
    PluginPackageStore,
)
from aidn_hypervisor.providers.package_verification import (
    compute_manifest_hash,
    package_signature_payload,
)
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        for relative_path, content in entries.items():
            archive.writestr(relative_path, content)
    return buffer.getvalue()


def _registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())
    return registry


def test_plugin_release_registration_and_local_install_are_metadata_only() -> None:
    registry = _registry()
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    manifest = registry.get("fake-managed").plugin_manifest()

    release = service.register_plugin_release(
        manifest_payload=manifest,
        source_reference="registry://plugins/fake-managed",
    )
    installed = service.install_plugin_release(
        release_id=release.release_id,
        granted_permissions=release.declared_permissions,
    )

    assert release.plugin_id == "fake-managed"
    assert release.release_status == "AVAILABLE"
    assert installed.release_id == release.release_id
    assert installed.package_digest == release.package_digest
    assert installed.granted_permission_hash is not None
    assert installed.installation_generation == 1
    assert installed.state == "INSTALLED"
    assert installed.installation_source == "PACKAGE"
    assert service.list_plugin_releases() == [release]
    assert service.list_installed_plugins() == [installed]
    assert (
        service.register_plugin_release(
            manifest_payload=manifest,
            source_reference="registry://plugins/fake-managed",
        )
        == release
    )

    advanced = service.advance_installed_plugin_generation(
        installed_plugin_id=installed.installed_plugin_id,
        activation_credential_key_id="sha256:" + "c" * 64,
    )

    assert advanced.installation_generation == 2
    assert advanced.activation_credential_key_id == "sha256:" + "c" * 64
    assert advanced.granted_permission_hash == installed.granted_permission_hash
    assert service.list_installed_plugins() == [advanced]


def test_plugin_release_install_rejects_unapproved_or_blocked_permissions() -> None:
    registry = _registry()
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    manifest = registry.get("fake-managed").plugin_manifest()
    release = service.register_plugin_release(manifest_payload=manifest)

    with pytest.raises(ValueError, match="require local approval"):
        service.install_plugin_release(release_id=release.release_id)

    with pytest.raises(ValueError, match="declared by the plugin release"):
        service.install_plugin_release(
            release_id=release.release_id,
            granted_permissions=[*release.declared_permissions, "wallet.keys"],
        )
    service.store.save_plugin_release(release.model_copy(update={"release_status": "SECURITY_BLOCKED"}))

    with pytest.raises(ValueError, match="security_blocked"):
        service.install_plugin_release(
            release_id=release.release_id,
            granted_permissions=release.declared_permissions,
        )


def test_plugin_release_registry_projection_is_public_and_deterministic() -> None:
    registry = _registry()
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    release = service.register_plugin_release(
        manifest_payload=registry.get("fake-managed").plugin_manifest(),
        source_reference="registry://plugins/fake-managed",
    )

    records = service.plugin_release_registry_objects()

    assert records == service.plugin_release_registry_objects()
    assert records[0]["object_type"] == "plugin_release"
    assert records[0]["object_version"] == "plugin-release.v1"
    assert records[0]["namespace"] == "plugin"
    assert records[0]["source_reference"] == release.source_reference
    assert records[0]["payload"]["release_id"] == release.release_id
    assert "installed_plugin_id" not in records[0]["payload"]
    assert "activation_credential_key_id" not in records[0]["payload"]


def test_plugin_release_registry_import_is_hash_bound_and_not_package_trusted() -> None:
    registry = _registry()
    source = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    release = source.register_plugin_release(
        manifest_payload=registry.get("fake-managed").plugin_manifest(),
        source_reference="https://plugins.example/fake-managed.zip",
    )
    target = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
        package_store=PluginPackageStore(),
    )

    imported = target.import_plugin_release_registry_objects(
        source.plugin_release_registry_objects()
    )

    assert imported == [target.store.get_plugin_release(release.release_id)]
    assert imported[0].trust_status == release.trust_status
    assert imported[0].package_verification_status == "UNVERIFIED"
    assert imported[0].trusted_publisher is False
    with pytest.raises(ValueError, match="trusted signed release"):
        target.acquire_plugin_package(release_id=release.release_id)


def test_plugin_release_registry_import_rejects_tampered_payload() -> None:
    registry = _registry()
    source = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    source.register_plugin_release(manifest_payload=registry.get("fake-managed").plugin_manifest())
    record = source.plugin_release_registry_objects()[0]
    record["payload"]["release_status"] = "REVOKED"
    target = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    with pytest.raises(ValueError, match="payload hash mismatch"):
        target.import_plugin_release_registry_objects([record])


def test_package_install_requires_verified_content_addressed_payload() -> None:
    registry = _registry()
    package_store = PluginPackageStore()
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
        package_store=package_store,
    )
    package_bytes = b"fake-provider-package-v1"
    package_digest = f"sha256:{hashlib.sha256(package_bytes).hexdigest()}"
    manifest = registry.get("fake-managed").plugin_manifest()
    manifest = {**manifest, "package_digest": package_digest, "publisher_signature": None}
    manifest["manifest_hash"] = compute_manifest_hash(manifest)
    release = service.register_plugin_release(manifest_payload=manifest)

    with pytest.raises(ValueError, match="verified plugin package"):
        service.install_plugin_release(
            release_id=release.release_id,
            granted_permissions=release.declared_permissions,
        )

    assert (
        service.stage_plugin_package(
            package_bytes=package_bytes,
            expected_digest=package_digest,
        )
        == package_digest
    )
    installed = service.install_plugin_release(
        release_id=release.release_id,
        granted_permissions=release.declared_permissions,
    )

    assert installed.package_digest == package_digest


def test_plugin_package_store_rejects_digest_mismatch() -> None:
    store = PluginPackageStore()

    with pytest.raises(ValueError, match="digest does not match"):
        store.stage(package_bytes=b"package", expected_digest="sha256:" + "0" * 64)


class _PackageResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self._offset = 0
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int) -> bytes:
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def _trusted_signed_manifest(
    *, package_bytes: bytes, private_key: Ed25519PrivateKey
) -> tuple[dict, dict[str, list[str]]]:
    public_key = f"ed25519:{private_key.public_key().public_bytes_raw().hex()}"
    manifest = {
        **_registry().get("fake-managed").plugin_manifest(),
        "publisher": "Trusted Test Publisher",
        "package_digest": f"sha256:{hashlib.sha256(package_bytes).hexdigest()}",
        "publisher_public_key": public_key,
        "publisher_signature": None,
    }
    manifest["manifest_hash"] = compute_manifest_hash(manifest)
    signed_manifest = ProviderPluginManifest.model_validate(manifest)
    manifest["publisher_signature"] = "ed25519:" + private_key.sign(
        package_signature_payload(signed_manifest, manifest_hash=manifest["manifest_hash"])
    ).hex()
    return manifest, {"Trusted Test Publisher": [public_key]}


def test_provider_service_acquires_trusted_signed_package_from_https_source(monkeypatch) -> None:
    package_bytes = b"trusted package bytes"
    manifest, trusted_keys = _trusted_signed_manifest(
        package_bytes=package_bytes,
        private_key=Ed25519PrivateKey.generate(),
    )
    acquirer = HttpsPluginPackageAcquirer()
    monkeypatch.setattr(acquirer, "_open", lambda _: _PackageResponse(package_bytes))
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
        package_store=PluginPackageStore(),
        package_acquirer=acquirer,
        trusted_publisher_keys=trusted_keys,
    )
    release = service.register_plugin_release(
        manifest_payload=manifest,
        source_reference="https://packages.example/fake-managed.package",
    )

    acquired = service.acquire_plugin_package(release_id=release.release_id)

    assert acquired == manifest["package_digest"]
    assert service.package_store.read(acquired) == package_bytes


def test_provider_service_blocks_untrusted_release_before_package_download() -> None:
    package_bytes = b"untrusted package bytes"
    manifest = {
        **_registry().get("fake-managed").plugin_manifest(),
        "package_digest": f"sha256:{hashlib.sha256(package_bytes).hexdigest()}",
        "publisher_signature": None,
    }
    manifest["manifest_hash"] = compute_manifest_hash(manifest)
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
        package_store=PluginPackageStore(),
    )
    release = service.register_plugin_release(
        manifest_payload=manifest,
        source_reference="https://packages.example/untrusted.package",
    )

    with pytest.raises(ValueError, match="trusted signed release"):
        service.acquire_plugin_package(release_id=release.release_id)


def test_https_plugin_package_acquirer_rejects_non_https_and_oversized_payload(monkeypatch) -> None:
    acquirer = HttpsPluginPackageAcquirer(maximum_package_bytes=4)

    with pytest.raises(ValueError, match="credential-free HTTPS"):
        acquirer.acquire("http://packages.example/package")

    monkeypatch.setattr(acquirer, "_open", lambda _: _PackageResponse(b"oversized"))
    with pytest.raises(ValueError, match="maximum size"):
        acquirer.acquire("https://packages.example/package")


def test_filesystem_plugin_package_store_survives_reconstruction_and_rejects_tampering(
    tmp_path,
) -> None:
    package_bytes = b"verified plugin package"
    package_digest = "sha256:" + hashlib.sha256(package_bytes).hexdigest()
    store = FilesystemPluginPackageStore(tmp_path / "packages")

    assert store.stage(package_bytes=package_bytes, expected_digest=package_digest) == package_digest
    reconstructed_store = FilesystemPluginPackageStore(tmp_path / "packages")
    assert reconstructed_store.has(package_digest) is True
    assert reconstructed_store.read(package_digest) == package_bytes

    package_path = reconstructed_store._path_for(package_digest)
    package_path.write_bytes(b"tampered")
    assert reconstructed_store.has(package_digest) is False
    with pytest.raises(ValueError, match="does not match"):
        reconstructed_store.read(package_digest)


def test_provider_service_builds_install_scoped_plugin_host_ingress() -> None:
    registry = _registry()
    service = ProviderInventoryService(plugins=registry, store=InMemoryProviderInventoryStore())
    release = service.register_plugin_release(manifest_payload=registry.get("fake-managed").plugin_manifest())
    installed = service.install_plugin_release(
        release_id=release.release_id, granted_permissions=release.declared_permissions
    )
    activation = service.provision_plugin_host_activation_credential(
        installed_plugin_id=installed.installed_plugin_id,
    )
    installed = service.store.get_installed_plugin(installed.installed_plugin_id)
    assert "activation_secret" not in installed.model_dump(mode="json")
    assert "activation_secret" not in activation
    launch_environment = service.plugin_host_launch_environment(
        installed_plugin_id=installed.installed_plugin_id
    )
    identity = PluginHostIdentity(
        installed_plugin_id=installed.installed_plugin_id,
        plugin_id=installed.plugin_id,
        installation_generation=installed.installation_generation,
        activation_credential_key_id=installed.activation_credential_key_id,
    )
    hello = PluginHostHello(
        **identity.model_dump(),
        host_nonce="nonce",
        activation_proof=build_plugin_host_activation_proof(
            activation_secret=bytes.fromhex(
                launch_environment["AIDN_PLUGIN_HOST_ACTIVATION_SECRET"]
            ),
            identity=identity,
            host_nonce="nonce",
        ),
    )

    ingress = service.plugin_host_local_ingress()
    connection = ingress.receive({"event_type": "PLUGIN_HOST_HELLO", "event": hello.model_dump(mode="json")})

    assert connection["installed_plugin_id"] == installed.installed_plugin_id
    plan = ingress.receive(
        {
            "event_type": "PLUGIN_CONTROL",
            "event": {
                "plugin_host_connection_id": connection["plugin_host_connection_id"],
                "installed_plugin_id": installed.installed_plugin_id,
                "installation_generation": installed.installation_generation,
                "command": "BUILD_INSTALLATION_PLAN",
                "configuration": {"base_url": "http://localhost"},
            },
        }
    )
    assert plan["installation_plan"]["plugin_id"] == installed.plugin_id
    attached = ingress.receive(
        {
            "event_type": "PLUGIN_CONTROL",
            "event": {
                "plugin_host_connection_id": connection["plugin_host_connection_id"],
                "installed_plugin_id": installed.installed_plugin_id,
                "installation_generation": installed.installation_generation,
                "command": "ATTACH_EXISTING_PROVIDER",
                "display_name": "Local Fake",
                "configuration": {"base_url": "http://localhost"},
            },
        }
    )
    assert attached["provider_instance"]["connection_mode"] == "attached"
    models = ingress.receive(
        {
            "event_type": "PLUGIN_CONTROL",
            "event": {
                "plugin_host_connection_id": connection["plugin_host_connection_id"],
                "installed_plugin_id": installed.installed_plugin_id,
                "installation_generation": installed.installation_generation,
                "command": "DISCOVER_MODELS",
                "provider_instance_id": attached["provider_instance"]["provider_instance_id"],
            },
        }
    )
    assert models["command"] == "DISCOVER_MODELS"
    binding = ingress.receive(
        {
            "event_type": "PLUGIN_CONTROL",
            "event": {
                "plugin_host_connection_id": connection["plugin_host_connection_id"],
                "installed_plugin_id": installed.installed_plugin_id,
                "installation_generation": installed.installation_generation,
                "command": "CREATE_RUNTIME_BINDING",
                "model_deployment_id": models["model_deployments"][0]["model_deployment_id"],
                "capability_id": "llm.chat",
                "capability_version": "2.1",
                "capability_definition_hash": "cap-definition-1",
            },
        }
    )
    assert binding["runtime_binding"]["plugin_id"] == installed.plugin_id
    admission = ingress.receive(
        {
            "event_type": "PLUGIN_CONTROL",
            "event": {
                "plugin_host_connection_id": connection["plugin_host_connection_id"],
                "installed_plugin_id": installed.installed_plugin_id,
                "installation_generation": installed.installation_generation,
                "command": "GET_RUNTIME_BINDING_ADMISSION",
                "runtime_binding_id": binding["runtime_binding"]["runtime_binding_id"],
            },
        }
    )
    assert (
        admission["admission"]["dimensions"]["runtime_binding"]["runtime_binding_id"]
        == binding["runtime_binding"]["runtime_binding_id"]
    )


class ControlledFilesystemPlugin(FakeManagedPlugin):
    plugin_id = "controlled-fs"

    def describe(self) -> dict:
        description = super().describe()
        description["plugin_id"] = self.plugin_id
        description["required_permissions"] = [
            {
                "permission_id": "network.private",
                "label": "Private network",
                "risk_level": "low",
                "reason": "Connect to a local fake provider endpoint",
            },
            {
                "permission_id": "filesystem.controlled_path",
                "label": "Controlled filesystem path",
                "risk_level": "medium",
                "reason": "Persist managed installation state inside a controlled path",
            },
        ]
        description["sandbox_policy"] = {
            "execution_mode": "SANDBOX_REQUIRED",
            "filesystem_scope": "CONTROLLED_PATHS",
            "network_scope": "DECLARED_EGRESS",
            "egress_rules": [{"host": "provider.example.com", "port": 443}],
            "secret_scope": "DECLARED_HANDLES_ONLY",
            "notes": "Managed install may write state inside one controlled host path.",
        }
        return description

    def build_installation_plan(self, configuration: dict) -> dict:
        plan = super().build_installation_plan(configuration)
        plan["plugin_id"] = self.plugin_id
        plan["required_permissions"] = self.plugin_manifest()["required_permissions"]
        plan["volumes"] = [
            {
                "name": "provider-cache",
                "mount_path": "/var/lib/provider-cache",
            }
        ]
        plan["model_downloads"] = [
            {
                "model": "fake-model",
                "source": "registry://fake-model",
                "destination": "provider-cache",
            }
        ]
        return plan


class LocalImportControlledFilesystemPlugin(ControlledFilesystemPlugin):
    plugin_id = "controlled-fs-import"

    def build_installation_plan(self, configuration: dict) -> dict:
        plan = super().build_installation_plan(configuration)
        plan["plugin_id"] = self.plugin_id
        plan["model_downloads"] = [
            {
                "model": "fake-model-imported",
                "source": "local-import://models/fake-model.gguf",
                "destination": "provider-cache/fake-model.gguf",
            }
        ]
        return plan


def test_fake_plugin_exposes_attach_schema_and_discovers_models() -> None:
    plugin = FakeManagedPlugin()

    attach_schema = plugin.attach_provider_schema()
    models = plugin.discover_models(
        {
            "provider_instance_id": "pi-fake",
            "display_name": "Local Fake",
            "configuration": {"base_url": "http://127.0.0.1:9999"},
        }
    )

    assert attach_schema["fields"] == [
        {"id": "display_name", "type": "text", "required": True},
        {"id": "base_url", "type": "text", "required": True},
    ]
    assert models[0]["provider_model_reference"] == "fake-model"
    assert models[0]["capability_bindings"] == ["llm.chat"]
    assert models[0]["operational_state"] == "ready"


def test_fake_plugin_discovery_uses_provider_specific_model_deployment_ids() -> None:
    plugin = FakeManagedPlugin()

    first_models = plugin.discover_models(
        {
            "provider_instance_id": "pi-fake-a",
            "display_name": "Local Fake A",
            "configuration": {"base_url": "http://127.0.0.1:9999"},
        }
    )
    second_models = plugin.discover_models(
        {
            "provider_instance_id": "pi-fake-b",
            "display_name": "Local Fake B",
            "configuration": {"base_url": "http://127.0.0.1:9998"},
        }
    )

    assert first_models[0]["model_deployment_id"] != second_models[0]["model_deployment_id"]
    assert first_models[0]["provider_instance_id"] == "pi-fake-a"
    assert second_models[0]["provider_instance_id"] == "pi-fake-b"


def test_base_plugin_attach_existing_provider_passes_configuration_through() -> None:
    plugin = FakeManagedPlugin()

    attached = plugin.attach_existing_provider({"base_url": "http://127.0.0.1:9999"})

    assert attached == {
        "configuration": {"base_url": "http://127.0.0.1:9999"},
        "connection_mode": "attached",
        "operational_state": "ready",
    }


def test_fake_plugin_creates_runtime_binding_projection() -> None:
    plugin = FakeManagedPlugin()

    binding = plugin.create_runtime_binding(
        model_deployment={
            "model_deployment_id": "md-fake",
            "provider_instance_id": "pi-fake",
            "provider_model_reference": "fake-model",
        },
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )

    assert binding["model_deployment_id"] == "md-fake"
    assert binding["capability_id"] == "llm.chat"
    assert binding["compatibility_bundle"]["plugin_id"] == "fake-managed"
    assert binding["compatibility_bundle"]["provider_type"] == "fake"
    assert binding["compatibility_bundle"]["model_id"] == "fake-model"


def test_provider_inventory_service_attaches_discovers_and_projects_runtime_binding() -> None:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    manifests = service.list_plugin_manifests()
    instance = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    models = service.discover_models(instance.provider_instance_id)
    binding = service.create_runtime_binding(
        model_deployment_id=models[0].model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )
    bundle = service.bundle_config_for_runtime_binding(binding.runtime_binding_id)

    assert manifests[0]["plugin_id"] == "fake-managed"
    assert instance.connection_mode == "attached"
    assert instance.configuration["base_url"] == "http://127.0.0.1:9999"
    assert service.store.get_provider_instance(instance.provider_instance_id).display_name == "Local Fake"
    assert models[0].provider_instance_id == instance.provider_instance_id
    assert service.store.get_model_deployment(models[0].model_deployment_id).provider_model_reference == "fake-model"
    assert binding.provider_instance_id == instance.provider_instance_id
    assert binding.runtime_id.startswith("runtime-")
    assert binding.runtime_id != binding.runtime_binding_id
    assert binding.runtime_generation == 1
    assert binding.implementation_class == "PLUGIN_MANAGED"
    assert binding.runtime_configuration_hash.startswith("sha256:")
    assert binding.dispatcher_route_scope == {
        "channel_class": "RUNTIME",
        "runtime_id": binding.runtime_id,
    }
    assert (
        service.store.get_runtime_binding(binding.runtime_binding_id).compatibility_bundle_id
        == binding.compatibility_bundle_id
    )
    assert bundle.bundle_id == binding.compatibility_bundle_id
    assert bundle.plugin_id == "fake-managed"
    assert bundle.provider_type == "fake"
    assert bundle.workload_type == "llm.chat"
    assert bundle.model_id == "fake-model"
    assert bundle.endpoint == "http://127.0.0.1:9999"


def test_provider_inventory_service_evaluates_runtime_binding_endpoint_admission() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )
    instance = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    model = service.discover_models(instance.provider_instance_id)[0]
    binding = service.create_runtime_binding(
        model_deployment_id=model.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )

    admission = service.runtime_binding_endpoint_admission(
        binding.runtime_binding_id,
        endpoint_payload={
            "owner_wallet": "wallet-operator",
            "model_class": "llm.chat",
            "capabilities": ["llm.chat"],
        },
    )

    assert admission["ready"] is True
    assert admission["dimensions"]["runtime_binding"]["ready"] is True
    assert admission["dimensions"]["artifact_materialization"]["status"] == "NOT_REQUIRED"
    assert admission["dimensions"]["compatibility_bundle"]["bundle_id"] == (binding.compatibility_bundle_id)
    assert admission["dimensions"]["pricing"]["status"] == "DRAFT_PRICE_UNSET"
    assert admission["warnings"][0]["code"] == "ENDPOINT_PRICING_NOT_CONFIGURED"

    mismatch = service.runtime_binding_endpoint_admission(
        binding.runtime_binding_id,
        endpoint_payload={
            "owner_wallet": "wallet-operator",
            "model_class": "image.generate",
            "capabilities": ["image.generate"],
        },
    )

    assert mismatch["ready"] is False
    assert {blocker["code"] for blocker in mismatch["blockers"]} == {
        "ENDPOINT_CAPABILITY_MISMATCH",
        "ENDPOINT_CAPABILITY_NOT_ADVERTISED",
    }


def test_provider_inventory_service_blocks_endpoint_admission_for_stopped_runtime_binding() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )
    instance = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    model = service.discover_models(instance.provider_instance_id)[0]
    binding = service.create_runtime_binding(
        model_deployment_id=model.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )
    service.store.save_runtime_binding(
        binding.model_copy(update={"status": "disabled", "operational_state": "STOPPED"})
    )

    admission = service.runtime_binding_endpoint_admission(
        binding.runtime_binding_id,
        endpoint_payload={
            "owner_wallet": "wallet-operator",
            "model_class": "llm.chat",
            "capabilities": ["llm.chat"],
        },
    )

    assert admission["ready"] is False
    assert admission["blockers"][0]["code"] == "RUNTIME_BINDING_NOT_READY"
    assert admission["dimensions"]["runtime_binding"]["operational_state"] == "STOPPED"


def test_provider_inventory_service_validates_configuration_before_attach() -> None:
    class ValidationTrackingPlugin(FakeManagedPlugin):
        plugin_id = "fake-validation-tracking"

        def __init__(self) -> None:
            self.validated_configurations: list[dict] = []

        def validate_provider_configuration(self, configuration: dict) -> None:
            self.validated_configurations.append(dict(configuration))

        def attach_existing_provider(self, configuration: dict) -> dict:
            if not self.validated_configurations:
                raise ValueError("validation not run")
            return {
                "configuration": dict(configuration),
                "connection_mode": "attached",
                "operational_state": "ready",
            }

    plugin = ValidationTrackingPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    instance = service.attach_provider_instance(
        plugin_id="fake-validation-tracking",
        display_name="Tracked Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )

    assert instance.plugin_id == "fake-validation-tracking"
    assert plugin.validated_configurations == [{"base_url": "http://127.0.0.1:9999"}]


def test_provider_inventory_service_reuses_runtime_binding_identity_for_same_logical_binding() -> None:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    instance = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    model = service.discover_models(instance.provider_instance_id)[0]

    first = service.create_runtime_binding(
        model_deployment_id=model.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )
    second = service.create_runtime_binding(
        model_deployment_id=model.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )

    assert first.runtime_binding_id == second.runtime_binding_id
    assert first.compatibility_bundle_id == second.compatibility_bundle_id
    assert [binding.runtime_binding_id for binding in service.store.list_runtime_bindings()] == [
        first.runtime_binding_id
    ]


def test_provider_inventory_service_ignores_plugin_supplied_random_runtime_binding_ids() -> None:
    class RandomIdentityPlugin(FakeManagedPlugin):
        plugin_id = "fake-random-identity"

        def create_runtime_binding(
            self,
            *,
            model_deployment: dict,
            capability_id: str,
            capability_version: str,
            capability_definition_hash: str,
        ) -> dict:
            binding = super().create_runtime_binding(
                model_deployment=model_deployment,
                capability_id=capability_id,
                capability_version=capability_version,
                capability_definition_hash=capability_definition_hash,
            )
            suffix = uuid4().hex[:12]
            binding["runtime_binding_id"] = f"plugin-rtb-{suffix}"
            binding["compatibility_bundle_id"] = f"plugin-bundle-{suffix}"
            return binding

    from uuid import uuid4

    plugin = RandomIdentityPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    instance = service.attach_provider_instance(
        plugin_id="fake-random-identity",
        display_name="Random Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    model = service.discover_models(instance.provider_instance_id)[0]

    first = service.create_runtime_binding(
        model_deployment_id=model.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )
    second = service.create_runtime_binding(
        model_deployment_id=model.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )
    bundle = service.bundle_config_for_runtime_binding(first.runtime_binding_id)

    assert first.runtime_binding_id == second.runtime_binding_id
    assert first.compatibility_bundle_id == second.compatibility_bundle_id
    assert not first.runtime_binding_id.startswith("plugin-rtb-")
    assert not first.compatibility_bundle_id.startswith("plugin-bundle-")
    assert [binding.runtime_binding_id for binding in service.store.list_runtime_bindings()] == [
        first.runtime_binding_id
    ]
    assert bundle.bundle_id == first.compatibility_bundle_id


def test_provider_inventory_builds_declarative_installation_plan() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )

    plan = service.build_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        },
    )

    assert plan["plugin_id"] == "fake-managed"
    assert plan["unsupported_actions"] == []
    assert plan["health_checks"][0]["url"] == "http://127.0.0.1:9999"


def test_provider_inventory_rejects_non_declarative_installation_plan() -> None:
    class BadPlanPlugin(FakeManagedPlugin):
        plugin_id = "bad-plan"

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            plan["unsupported_actions"] = ["RUN_SHELL_SCRIPT"]
            return plan

    registry = PluginRegistry()
    registry.register(BadPlanPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    with pytest.raises(ValueError, match="declarative-only"):
        service.build_installation_plan(
            plugin_id="bad-plan",
            configuration={
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
        )


def test_provider_inventory_rejects_installation_plan_for_attach_only_plugin() -> None:
    class AttachOnlyPlugin(FakeManagedPlugin):
        plugin_id = "attach-only"

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["plugin_capability_flags"] = ["CAN_ATTACH_EXISTING"]
            return description

    registry = PluginRegistry()
    registry.register(AttachOnlyPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    with pytest.raises(ValueError, match="does not support managed installation"):
        service.build_installation_plan(
            plugin_id="attach-only",
            configuration={
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
        )


def _installation_configuration() -> dict:
    return {
        "display_name": "Local Fake",
        "base_url": "http://127.0.0.1:9999",
    }


def _installation_plan(*, plugin_id: str = "fake-managed", plan_id: str = "plan-fake-managed") -> InstallationPlan:
    return InstallationPlan(
        plan_id=plan_id,
        plugin_id=plugin_id,
        plan_version="1.0.0",
        summary="Install the fake managed provider",
        containers=[
            {
                "name": "fake-provider",
                "image": "example/fake-provider:latest",
            }
        ],
        processes=[],
        model_downloads=[
            {
                "model": "fake-model",
                "source": "provider-cache",
            }
        ],
        volumes=[
            {
                "name": "fake-model-cache",
                "mount_path": "/models",
            }
        ],
        networks=[],
        environment={"FAKE_PROVIDER_MODE": "managed"},
        resource_limits={"memory": "1Gi"},
        health_checks=[
            {
                "url": "http://127.0.0.1:9999",
                "interval_seconds": 10,
            }
        ],
    )


def _installation_approval(
    *,
    configuration: dict | None = None,
    plugin_id: str = "fake-managed",
    plan_id: str = "plan-fake-managed",
    status: str = "APPROVED",
) -> ProviderInstallationApproval:
    return ProviderInstallationApproval(
        approval_id="approval-fake-managed",
        plugin_id=plugin_id,
        plan_id=plan_id,
        plan_hash="sha256:plan",
        configuration_hash="sha256:configuration",
        configuration=configuration or _installation_configuration(),
        approved_permissions=["container.manage"],
        status=status,
        created_at="2026-07-15T12:00:00Z",
    )


def test_provider_inventory_store_saves_installation_approvals_and_jobs() -> None:
    store = InMemoryProviderInventoryStore()
    approval = _installation_approval(
        configuration={
            **_installation_configuration(),
            "runtime": {"endpoint": "local", "retries": 3},
        }
    )
    job = ProviderInstallationJob(
        job_id="job-fake-managed",
        approval_id=approval.approval_id,
        plugin_id=approval.plugin_id,
        plan_id=approval.plan_id,
        plan_hash=approval.plan_hash,
        configuration_hash=approval.configuration_hash,
        status="QUEUED",
        executor_id="recorded-declarative-v1",
        step_results=[
            {
                "step_id": "containers",
                "step_type": "containers",
                "status": "RECORDED",
                "summary": "Recorded container declaration",
                "details": {
                    "container": {
                        "name": "fake-provider",
                        "image": "example/fake-provider:latest",
                    }
                },
            }
        ],
        created_at="2026-07-15T12:01:00Z",
    )
    expected_approval = approval.model_copy(deep=True)
    expected_job = job.model_copy(deep=True)

    assert store.save_installation_approval(approval) is None
    assert store.save_installation_job(job) is None

    approval.configuration["runtime"]["endpoint"] = "mutated"
    approval.approved_permissions.append("host.write")
    job.step_results[0].details["container"]["image"] = "mutated:latest"
    job.step_results[0].status = "FAILED"

    assert store.get_installation_approval(expected_approval.approval_id) == expected_approval
    assert store.list_installation_approvals() == [expected_approval]
    assert store.get_installation_job(expected_job.job_id) == expected_job
    assert store.list_installation_jobs() == [expected_job]

    returned_approval = store.get_installation_approval(expected_approval.approval_id)
    returned_approval.configuration["runtime"]["retries"] = 99
    returned_approval.approved_permissions.append("container.delete")
    listed_approval = store.list_installation_approvals()[0]
    listed_approval.configuration["runtime"]["endpoint"] = "listed-mutated"
    listed_approval.approved_permissions.clear()

    returned_job = store.get_installation_job(expected_job.job_id)
    returned_job.step_results[0].details["container"]["name"] = "mutated-provider"
    returned_job.step_results[0].status = "FAILED"
    listed_job = store.list_installation_jobs()[0]
    listed_job.step_results[0].details["container"]["image"] = "listed-mutated:latest"
    listed_job.step_results[0].status = "SKIPPED"

    assert store.get_installation_approval(expected_approval.approval_id).configuration["runtime"] == {
        "endpoint": "local",
        "retries": 3,
    }
    assert store.list_installation_approvals()[0].approved_permissions == ["container.manage"]
    assert store.get_installation_job(expected_job.job_id).step_results[0].details == {
        "container": {
            "name": "fake-provider",
            "image": "example/fake-provider:latest",
        }
    }
    assert store.list_installation_jobs()[0].step_results[0].status == "RECORDED"


def test_recorded_provider_installation_executor_records_declarative_plan_without_host_mutation() -> None:
    executor = RecordedProviderInstallationExecutor()
    configuration = _installation_configuration()
    plan = _installation_plan()
    approval = _installation_approval(configuration=configuration)

    result = executor.apply(
        approval=approval,
        plan=plan,
        configuration=dict(configuration),
        manifest={
            "plugin_id": "fake-managed",
            "display_name": "Fake Managed Provider",
            "provider_families": ["fake"],
        },
        provider_instance_id="pi-fake-managed",
    )

    assert executor.executor_id == "recorded-declarative-v1"
    assert [step.step_type for step in result.step_results] == [
        "containers",
        "model_downloads",
        "volumes",
        "environment",
        "resource_limits",
        "health_checks",
    ]
    assert all(step.status == "RECORDED" for step in result.step_results)
    assert result.provider_instance == {
        "provider_instance_id": "pi-fake-managed",
        "plugin_id": "fake-managed",
        "provider_family": "fake",
        "display_name": "Local Fake",
        "connection_mode": "managed",
        "configuration": configuration,
        "operational_state": "created",
        "health_status": "unknown",
        "last_health_check_at": None,
        "last_health_error": None,
    }
    assert result.provider_instance["configuration"] is not configuration


def test_recorded_provider_installation_executor_exposes_sandbox_capabilities() -> None:
    executor = RecordedProviderInstallationExecutor()

    capabilities = executor.sandbox_capabilities()

    assert capabilities.supported_execution_modes == ["RECORDED_ONLY"]
    assert capabilities.supported_filesystem_scopes == ["NONE"]
    assert capabilities.supported_network_scopes == ["NONE"]
    assert capabilities.supported_secret_scopes == ["DECLARED_HANDLES_ONLY"]
    assert capabilities.host_mutation is False


def test_sandbox_enforced_provider_installation_executor_accepts_supported_fake_plan() -> None:
    executor = SandboxEnforcedProviderInstallationExecutor()
    configuration = _installation_configuration()
    approval = _installation_approval(configuration=configuration).model_copy(
        update={
            "approved_permissions": ["network.private"],
            "acknowledged_sandbox_policy": {
                "execution_mode": "RECORDED_ONLY",
                "filesystem_scope": "NONE",
                "network_scope": "NONE",
                "secret_scope": "DECLARED_HANDLES_ONLY",
            },
        }
    )
    plan = InstallationPlan.model_validate(FakeManagedPlugin().build_installation_plan(dict(configuration)))

    result = executor.apply(
        approval=approval,
        plan=plan,
        configuration=dict(configuration),
        manifest=FakeManagedPlugin().plugin_manifest(),
        provider_instance_id="pi-fake-sandboxed",
    )

    assert executor.executor_id == "sandbox-enforced-declarative-v1"
    assert result.step_results[0].step_type == "sandbox_boundary"
    assert result.step_results[0].details["validated_network_names"] == ["private-provider"]
    assert result.step_results[0].details["validated_health_hosts"] == ["127.0.0.1"]
    assert result.provider_instance["provider_instance_id"] == "pi-fake-sandboxed"


def test_sandbox_enforced_provider_installation_executor_rejects_disallowed_plan_sections() -> None:
    executor = SandboxEnforcedProviderInstallationExecutor()
    configuration = _installation_configuration()

    with pytest.raises(
        ValueError,
        match="sandbox executor does not permit non-empty declarative section: containers",
    ):
        executor.apply(
            approval=_installation_approval(configuration=configuration),
            plan=_installation_plan(),
            configuration=dict(configuration),
            manifest={"plugin_id": "fake-managed"},
            provider_instance_id="pi-fake-managed",
        )


def test_sandbox_enforced_provider_installation_executor_rejects_health_check_outside_boundary() -> None:
    executor = SandboxEnforcedProviderInstallationExecutor()
    configuration = _installation_configuration()
    plan = InstallationPlan.model_validate(
        {
            "plan_id": "plan-fake-managed",
            "plugin_id": "fake-managed",
            "plan_version": "1.0.0",
            "summary": "Boundary test plan",
            "containers": [],
            "processes": [],
            "model_downloads": [],
            "volumes": [],
            "networks": [{"name": "private-provider", "scope": "local"}],
            "environment": {},
            "resource_limits": {"cpu": "shared"},
            "health_checks": [
                {
                    "type": "http",
                    "url": "http://example.com:9999",
                    "timeout_seconds": 5,
                }
            ],
            "required_permissions": [],
            "secret_references": [],
            "unsupported_actions": [],
        }
    )
    approval = _installation_approval(configuration=configuration).model_copy(
        update={
            "approved_permissions": [],
            "acknowledged_sandbox_policy": {
                "execution_mode": "RECORDED_ONLY",
                "filesystem_scope": "NONE",
                "network_scope": "NONE",
                "secret_scope": "DECLARED_HANDLES_ONLY",
            },
        }
    )

    with pytest.raises(
        ValueError,
        match="sandbox executor does not permit health check host outside the approved boundary",
    ):
        executor.apply(
            approval=approval,
            plan=plan,
            configuration=dict(configuration),
            manifest={"plugin_id": "fake-managed"},
            provider_instance_id="pi-fake-managed",
        )


def test_sandbox_enforced_provider_installation_executor_rejects_network_keys_outside_bounded_subset() -> None:
    executor = SandboxEnforcedProviderInstallationExecutor()
    configuration = _installation_configuration()
    plan = InstallationPlan.model_validate(
        {
            "plan_id": "plan-fake-managed",
            "plugin_id": "fake-managed",
            "plan_version": "1.0.0",
            "summary": "Network key boundary test plan",
            "containers": [],
            "processes": [],
            "model_downloads": [],
            "volumes": [],
            "networks": [
                {
                    "name": "private-provider",
                    "scope": "local",
                    "driver": "bridge",
                }
            ],
            "environment": {},
            "resource_limits": {"cpu": "shared"},
            "health_checks": [
                {
                    "type": "http",
                    "url": "http://127.0.0.1:9999",
                    "timeout_seconds": 5,
                }
            ],
            "required_permissions": [],
            "secret_references": [],
            "unsupported_actions": [],
        }
    )
    approval = _installation_approval(configuration=configuration)

    with pytest.raises(
        ValueError,
        match="sandbox executor does not permit network declaration keys outside the bounded subset: driver",
    ):
        executor.apply(
            approval=approval,
            plan=plan,
            configuration=dict(configuration),
            manifest={"plugin_id": "fake-managed"},
            provider_instance_id="pi-fake-managed",
        )


def test_sandbox_enforced_provider_installation_executor_rejects_health_check_query_parameters() -> None:
    executor = SandboxEnforcedProviderInstallationExecutor()
    configuration = _installation_configuration()
    plan = InstallationPlan.model_validate(
        {
            "plan_id": "plan-fake-managed",
            "plugin_id": "fake-managed",
            "plan_version": "1.0.0",
            "summary": "Health query boundary test plan",
            "containers": [],
            "processes": [],
            "model_downloads": [],
            "volumes": [],
            "networks": [{"name": "private-provider", "scope": "local"}],
            "environment": {},
            "resource_limits": {"cpu": "shared"},
            "health_checks": [
                {
                    "type": "http",
                    "url": "http://127.0.0.1:9999/health?probe=full",
                    "timeout_seconds": 5,
                }
            ],
            "required_permissions": [],
            "secret_references": [],
            "unsupported_actions": [],
        }
    )
    approval = _installation_approval(configuration=configuration)

    with pytest.raises(
        ValueError,
        match="sandbox executor does not permit health check query or fragment parameters",
    ):
        executor.apply(
            approval=approval,
            plan=plan,
            configuration=dict(configuration),
            manifest={"plugin_id": "fake-managed"},
            provider_instance_id="pi-fake-managed",
        )


def test_sandbox_enforced_provider_installation_executor_rejects_health_check_methods_outside_bounded_subset() -> None:
    executor = SandboxEnforcedProviderInstallationExecutor()
    configuration = _installation_configuration()
    plan = InstallationPlan.model_validate(
        {
            "plan_id": "plan-fake-managed",
            "plugin_id": "fake-managed",
            "plan_version": "1.0.0",
            "summary": "Health method boundary test plan",
            "containers": [],
            "processes": [],
            "model_downloads": [],
            "volumes": [],
            "networks": [{"name": "private-provider", "scope": "local"}],
            "environment": {},
            "resource_limits": {"cpu": "shared"},
            "health_checks": [
                {
                    "type": "http",
                    "url": "http://127.0.0.1:9999/health",
                    "timeout_seconds": 5,
                    "method": "POST",
                }
            ],
            "required_permissions": [],
            "secret_references": [],
            "unsupported_actions": [],
        }
    )
    approval = _installation_approval(configuration=configuration)

    with pytest.raises(
        ValueError,
        match="sandbox executor does not permit health check method outside the bounded subset: POST",
    ):
        executor.apply(
            approval=approval,
            plan=plan,
            configuration=dict(configuration),
            manifest={"plugin_id": "fake-managed"},
            provider_instance_id="pi-fake-managed",
        )


def test_sandbox_enforced_provider_installation_executor_rejects_negative_resource_limits() -> None:
    executor = SandboxEnforcedProviderInstallationExecutor()
    configuration = _installation_configuration()
    plan = InstallationPlan.model_validate(
        {
            "plan_id": "plan-fake-managed",
            "plugin_id": "fake-managed",
            "plan_version": "1.0.0",
            "summary": "Resource limit boundary test plan",
            "containers": [],
            "processes": [],
            "model_downloads": [],
            "volumes": [],
            "networks": [{"name": "private-provider", "scope": "local"}],
            "environment": {},
            "resource_limits": {"memory_mb": -1},
            "health_checks": [
                {
                    "type": "http",
                    "url": "http://127.0.0.1:9999",
                    "timeout_seconds": 5,
                }
            ],
            "required_permissions": [],
            "secret_references": [],
            "unsupported_actions": [],
        }
    )
    approval = _installation_approval(configuration=configuration)

    with pytest.raises(
        ValueError,
        match="sandbox executor does not permit negative resource limits: memory_mb",
    ):
        executor.apply(
            approval=approval,
            plan=plan,
            configuration=dict(configuration),
            manifest={"plugin_id": "fake-managed"},
            provider_instance_id="pi-fake-managed",
        )


def test_controlled_filesystem_executor_writes_and_removes_state(tmp_path) -> None:
    plugin = ControlledFilesystemPlugin()
    configuration = _installation_configuration()
    plan = InstallationPlan.model_validate(plugin.build_installation_plan(configuration))
    approval = _installation_approval(
        configuration=configuration,
        plugin_id=plugin.plugin_id,
    ).model_copy(
        update={
            "approved_permissions": [
                "network.private",
                "filesystem.controlled_path",
            ],
            "acknowledged_sandbox_policy": {
                "execution_mode": "SANDBOX_REQUIRED",
                "filesystem_scope": "CONTROLLED_PATHS",
                "network_scope": "DECLARED_EGRESS",
                "egress_rules": [{"host": "provider.example.com", "port": 443}],
                "secret_scope": "DECLARED_HANDLES_ONLY",
            },
        }
    )
    executor = ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root")

    result = executor.apply(
        approval=approval,
        plan=plan,
        configuration=dict(configuration),
        manifest=plugin.plugin_manifest(),
        provider_instance_id="pi-controlled-fs",
    )

    state_path = tmp_path / "executor-root" / "providers" / "pi-controlled-fs" / "provider-installation-state.json"
    volume_path = tmp_path / "executor-root" / "providers" / "pi-controlled-fs" / "volumes" / "provider-cache"
    download_manifest_path = (
        tmp_path / "executor-root" / "providers" / "pi-controlled-fs" / "downloads" / "01-fake-model.json"
    )
    assert state_path.exists()
    assert volume_path.exists()
    assert download_manifest_path.exists()
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    download_manifest = json.loads(download_manifest_path.read_text(encoding="utf-8"))
    assert state_payload["provider_instance_id"] == "pi-controlled-fs"
    assert state_payload["prepared_volumes"] == ["provider-cache"]
    assert state_payload["staged_model_downloads"] == ["fake-model"]
    assert download_manifest["destination"] == "provider-cache"
    assert result.rollback_result.status == "PENDING"
    assert any(step.step_type == "filesystem_prepare_volume" for step in result.step_results)
    assert any(step.step_type == "filesystem_stage_model_download" for step in result.step_results)
    assert result.step_results[-1].step_type == "filesystem_state_write"

    rollback = executor.rollback(
        approval=approval,
        plan=plan,
        configuration=dict(configuration),
        manifest=plugin.plugin_manifest(),
        provider_instance_id="pi-controlled-fs",
    )

    assert rollback.status == "COMPLETED"
    assert rollback.step_results[0].step_type == "filesystem_state_remove"
    assert not state_path.exists()
    assert not volume_path.exists()
    assert not download_manifest_path.exists()


def test_controlled_filesystem_executor_imports_local_artifact_into_volume(tmp_path) -> None:
    plugin = LocalImportControlledFilesystemPlugin()
    configuration = _installation_configuration()
    plan = InstallationPlan.model_validate(plugin.build_installation_plan(configuration))
    approval = _installation_approval(
        configuration=configuration,
        plugin_id=plugin.plugin_id,
    ).model_copy(
        update={
            "approved_permissions": [
                "network.private",
                "filesystem.controlled_path",
            ],
            "acknowledged_sandbox_policy": {
                "execution_mode": "SANDBOX_REQUIRED",
                "filesystem_scope": "CONTROLLED_PATHS",
                "network_scope": "DECLARED_EGRESS",
                "egress_rules": [{"host": "provider.example.com", "port": 443}],
                "secret_scope": "DECLARED_HANDLES_ONLY",
            },
        }
    )
    imports_root = tmp_path / "executor-root" / "imports" / "models"
    imports_root.mkdir(parents=True, exist_ok=True)
    source_path = imports_root / "fake-model.gguf"
    source_path.write_text("fake-model-bytes", encoding="utf-8")
    executor = ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root")

    result = executor.apply(
        approval=approval,
        plan=plan,
        configuration=dict(configuration),
        manifest=plugin.plugin_manifest(),
        provider_instance_id="pi-controlled-fs-import",
    )

    imported_path = (
        tmp_path
        / "executor-root"
        / "providers"
        / "pi-controlled-fs-import"
        / "volumes"
        / "provider-cache"
        / "fake-model.gguf"
    )
    state_path = (
        tmp_path / "executor-root" / "providers" / "pi-controlled-fs-import" / "provider-installation-state.json"
    )
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert imported_path.exists()
    assert imported_path.read_text(encoding="utf-8") == "fake-model-bytes"
    assert state_payload["imported_local_artifacts"] == ["fake-model-imported"]
    assert any(step.step_type == "filesystem_import_local_artifact" for step in result.step_results)

    rollback = executor.rollback(
        approval=approval,
        plan=plan,
        configuration=dict(configuration),
        manifest=plugin.plugin_manifest(),
        provider_instance_id="pi-controlled-fs-import",
    )

    assert rollback.status == "COMPLETED"
    assert not imported_path.exists()


def test_controlled_filesystem_executor_promotes_and_reuses_model_artifact(
    tmp_path,
) -> None:
    plugin = LocalImportControlledFilesystemPlugin()
    configuration = _installation_configuration()
    executor = ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root")
    executor.stage_local_artifact(
        relative_path="models/fake-model.gguf",
        content_bytes=b"shared-model-bytes",
    )
    artifact = executor.promote_local_artifact_to_model_store(relative_path="models/fake-model.gguf")
    executor.stage_local_artifact(
        relative_path="copies/fake-model.gguf",
        content_bytes=b"shared-model-bytes",
    )
    duplicate = executor.promote_local_artifact_to_model_store(relative_path="copies/fake-model.gguf")

    assert artifact.artifact_id == duplicate.artifact_id
    assert len(executor.model_artifact_inventory().items) == 1

    plan = InstallationPlan.model_validate(plugin.build_installation_plan(configuration))
    plan = plan.model_copy(
        update={
            "model_downloads": [
                {
                    "model": "fake-model-imported",
                    "source": f"model-artifact://{artifact.artifact_id}",
                    "destination": "provider-cache/fake-model.gguf",
                }
            ]
        }
    )
    approval = _installation_approval(
        configuration=configuration,
        plugin_id=plugin.plugin_id,
        plan_id=plan.plan_id,
    ).model_copy(
        update={
            "approved_permissions": ["network.private", "filesystem.controlled_path"],
            "acknowledged_sandbox_policy": {
                "execution_mode": "SANDBOX_REQUIRED",
                "filesystem_scope": "CONTROLLED_PATHS",
                "network_scope": "DECLARED_EGRESS",
                "secret_scope": "DECLARED_HANDLES_ONLY",
            },
        }
    )

    diagnostics = executor.diagnostic_checks(
        approval=approval,
        plan=plan,
        configuration=configuration,
        manifest=plugin.plugin_manifest(),
    )
    assert next(check for check in diagnostics if check.check_id == "model_artifact_store").status == "PASS"

    result = executor.apply(
        approval=approval,
        plan=plan,
        configuration=configuration,
        manifest=plugin.plugin_manifest(),
        provider_instance_id="pi-controlled-fs-shared-model",
    )

    materialized_path = (
        tmp_path
        / "executor-root"
        / "providers"
        / "pi-controlled-fs-shared-model"
        / "volumes"
        / "provider-cache"
        / "fake-model.gguf"
    )
    assert materialized_path.read_bytes() == b"shared-model-bytes"
    assert any(step.step_type == "filesystem_materialize_model_artifact" for step in result.step_results)


def test_model_artifact_inventory_excludes_corrupt_payloads(tmp_path) -> None:
    executor = ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root")
    executor.stage_local_artifact(
        relative_path="models/fake-model.gguf",
        content_bytes=b"verified-model-bytes",
    )
    artifact = executor.promote_local_artifact_to_model_store(relative_path="models/fake-model.gguf")
    payload_path = executor._model_artifact_payload_path(artifact.artifact_id)
    payload_path.chmod(0o644)
    payload_path.write_bytes(b"corrupt")

    assert executor.model_artifact_inventory().items == []


def test_model_artifact_materialization_can_use_readonly_hardlinks(tmp_path) -> None:
    executor = ControlledFilesystemProviderInstallationExecutor(
        tmp_path / "executor-root",
        model_artifact_materialization_mode="HARDLINK_IF_READONLY",
    )
    source = tmp_path / "source.gguf"
    source.write_bytes(b"shared-model")
    source.chmod(0o444)
    destination = tmp_path / "destination.gguf"

    method = executor._materialize_shared_model_artifact(
        source_path=source,
        destination_path=destination,
    )

    assert destination.read_bytes() == b"shared-model"
    assert method in {"HARDLINK", "COPY"}


def test_executor_materializes_artifact_set_into_provider_scoped_root(tmp_path) -> None:
    executor = ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root")
    executor.stage_local_artifact(relative_path="models/model.gguf", content_bytes=b"model")
    artifact = executor.promote_local_artifact_to_model_store(relative_path="models/model.gguf")
    artifact_set = executor.create_model_artifact_set(
        display_name="Model",
        files=[{"relative_path": "weights/model.gguf", "artifact_id": artifact.artifact_id, "role": "WEIGHTS"}],
    )

    result = executor.materialize_model_artifact_set(
        provider_instance_id="pi-local",
        artifact_set_id=artifact_set.artifact_set_id,
        destination="models",
    )

    assert result.status == "READY"
    assert Path(result.files[0]["destination_path"]).read_bytes() == b"model"


def test_model_artifact_sets_protect_referenced_bytes_and_bind_deployments(tmp_path) -> None:
    executor = ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root")
    executor.stage_local_artifact(
        relative_path="models/weights.gguf",
        content_bytes=b"weights",
    )
    executor.stage_local_artifact(
        relative_path="models/tokenizer.json",
        content_bytes=b"tokenizer",
    )
    weights = executor.promote_local_artifact_to_model_store(relative_path="models/weights.gguf")
    tokenizer = executor.promote_local_artifact_to_model_store(relative_path="models/tokenizer.json")
    artifact_set = executor.create_model_artifact_set(
        display_name="Fake model package",
        files=[
            {"relative_path": "weights/model.gguf", "artifact_id": weights.artifact_id, "role": "WEIGHTS"},
            {"relative_path": "tokenizer.json", "artifact_id": tokenizer.artifact_id, "role": "TOKENIZER"},
        ],
    )

    with pytest.raises(ValueError, match="referenced"):
        executor.delete_model_artifact(artifact_id=weights.artifact_id)

    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
        installation_executor=executor,
    )
    instance = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    deployment = service.discover_models(instance.provider_instance_id)[0]
    bound = service.bind_model_artifact_set(
        model_deployment_id=deployment.model_deployment_id,
        artifact_set_id=artifact_set.artifact_set_id,
    )
    assert bound.artifact_set_id == artifact_set.artifact_set_id
    rediscovered = service.discover_models(instance.provider_instance_id)[0]
    assert rediscovered.artifact_set_id == artifact_set.artifact_set_id

    with pytest.raises(ValueError, match="referenced by model deployment"):
        service.delete_model_artifact_set(artifact_set_id=artifact_set.artifact_set_id)


def test_runtime_binding_requires_materialized_model_artifact_set(tmp_path) -> None:
    executor = ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root")
    executor.stage_local_artifact(
        relative_path="models/weights.gguf",
        content_bytes=b"weights",
    )
    weights = executor.promote_local_artifact_to_model_store(relative_path="models/weights.gguf")
    artifact_set = executor.create_model_artifact_set(
        display_name="Fake model package",
        files=[
            {
                "relative_path": "weights/model.gguf",
                "artifact_id": weights.artifact_id,
                "role": "WEIGHTS",
            },
        ],
    )
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
        installation_executor=executor,
    )
    instance = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    deployment = service.discover_models(instance.provider_instance_id)[0]
    bound = service.bind_model_artifact_set(
        model_deployment_id=deployment.model_deployment_id,
        artifact_set_id=artifact_set.artifact_set_id,
    )

    readiness = service.model_deployment_artifact_readiness(bound)

    assert readiness["required"] is True
    assert readiness["ready"] is False
    assert readiness["status"] == "MISSING"
    with pytest.raises(ValueError, match="artifact set must be materialized"):
        service.create_runtime_binding(
            model_deployment_id=bound.model_deployment_id,
            capability_id="llm.chat",
            capability_version="1.0.0",
            capability_definition_hash="cap-hash",
        )


def test_runtime_binding_allows_ready_model_artifact_materialization(tmp_path) -> None:
    executor = ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root")
    executor.stage_local_artifact(
        relative_path="models/weights.gguf",
        content_bytes=b"weights",
    )
    weights = executor.promote_local_artifact_to_model_store(relative_path="models/weights.gguf")
    artifact_set = executor.create_model_artifact_set(
        display_name="Fake model package",
        files=[
            {
                "relative_path": "weights/model.gguf",
                "artifact_id": weights.artifact_id,
                "role": "WEIGHTS",
            },
        ],
    )
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
        installation_executor=executor,
    )
    instance = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    deployment = service.discover_models(instance.provider_instance_id)[0]
    bound = service.bind_model_artifact_set(
        model_deployment_id=deployment.model_deployment_id,
        artifact_set_id=artifact_set.artifact_set_id,
    )
    materialization = service.materialize_model_artifact_set(
        provider_instance_id=instance.provider_instance_id,
        artifact_set_id=artifact_set.artifact_set_id,
        destination="models",
    )

    readiness = service.model_deployment_artifact_readiness(bound)
    binding = service.create_runtime_binding(
        model_deployment_id=bound.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )

    assert materialization.status == "READY"
    assert readiness["ready"] is True
    assert readiness["materialization_id"] == materialization.materialization_id
    assert binding.model_deployment_id == bound.model_deployment_id


def test_model_artifact_garbage_collection_respects_references_and_grace_period(
    tmp_path,
) -> None:
    executor = ControlledFilesystemProviderInstallationExecutor(
        tmp_path / "executor-root",
        model_artifact_gc_grace_seconds=0,
    )
    executor.stage_local_artifact(
        relative_path="models/fake-model.gguf",
        content_bytes=b"model-bytes",
    )
    artifact = executor.promote_local_artifact_to_model_store(relative_path="models/fake-model.gguf")

    first_collection = executor.collect_model_artifact_garbage()
    assert first_collection.pending_artifact_ids == [artifact.artifact_id]
    assert executor.model_artifact_inventory().items[0].unreferenced_since is not None

    artifact_set = executor.create_model_artifact_set(
        display_name="Protected model",
        files=[
            {
                "relative_path": "model.gguf",
                "artifact_id": artifact.artifact_id,
                "role": "WEIGHTS",
            }
        ],
    )
    retained_collection = executor.collect_model_artifact_garbage()
    assert retained_collection.retained_artifact_ids == [artifact.artifact_id]

    executor.delete_model_artifact_set(artifact_set_id=artifact_set.artifact_set_id)
    second_collection = executor.collect_model_artifact_garbage()
    assert second_collection.pending_artifact_ids == [artifact.artifact_id]
    final_collection = executor.collect_model_artifact_garbage()
    assert final_collection.collected_artifact_ids == [artifact.artifact_id]
    assert executor.model_artifact_inventory().items == []


def test_model_artifact_garbage_collection_fails_closed_for_bad_set_manifest(tmp_path) -> None:
    executor = ControlledFilesystemProviderInstallationExecutor(
        tmp_path / "executor-root",
        model_artifact_gc_grace_seconds=0,
    )
    executor.stage_local_artifact(
        relative_path="models/fake-model.gguf",
        content_bytes=b"model-bytes",
    )
    artifact = executor.promote_local_artifact_to_model_store(relative_path="models/fake-model.gguf")
    sets_root = executor._model_artifact_sets_root()
    sets_root.mkdir(parents=True, exist_ok=True)
    (sets_root / "broken.json").write_text("not-json", encoding="utf-8")

    result = executor.collect_model_artifact_garbage()

    assert result.retained_artifact_ids == [artifact.artifact_id]
    with pytest.raises(ValueError, match="unreadable"):
        executor.delete_model_artifact(artifact_id=artifact.artifact_id)


def test_recorded_provider_installation_executor_rejects_revoked_approval() -> None:
    executor = RecordedProviderInstallationExecutor()
    configuration = _installation_configuration()

    with pytest.raises(ValueError, match="approved"):
        executor.apply(
            approval=_installation_approval(configuration=configuration, status="REVOKED"),
            plan=_installation_plan(),
            configuration=configuration,
            manifest={"plugin_id": "fake-managed"},
            provider_instance_id="pi-fake-managed",
        )


def test_recorded_provider_installation_executor_rejects_mismatched_configuration() -> None:
    executor = RecordedProviderInstallationExecutor()
    configuration = _installation_configuration()

    with pytest.raises(ValueError, match="configuration"):
        executor.apply(
            approval=_installation_approval(configuration=configuration),
            plan=_installation_plan(),
            configuration={**configuration, "base_url": "http://127.0.0.1:9998"},
            manifest={"plugin_id": "fake-managed"},
            provider_instance_id="pi-fake-managed",
        )


def test_recorded_provider_installation_executor_rejects_plugin_and_plan_mismatches() -> None:
    executor = RecordedProviderInstallationExecutor()
    configuration = _installation_configuration()

    with pytest.raises(ValueError, match="plugin"):
        executor.apply(
            approval=_installation_approval(configuration=configuration, plugin_id="fake-managed"),
            plan=_installation_plan(plugin_id="other-plugin"),
            configuration=configuration,
            manifest={"plugin_id": "fake-managed"},
            provider_instance_id="pi-fake-managed",
        )

    with pytest.raises(ValueError, match="plan"):
        executor.apply(
            approval=_installation_approval(configuration=configuration, plan_id="plan-fake-managed"),
            plan=_installation_plan(plan_id="other-plan"),
            configuration=configuration,
            manifest={"plugin_id": "fake-managed"},
            provider_instance_id="pi-fake-managed",
        )

    with pytest.raises(ValueError, match="manifest"):
        executor.apply(
            approval=_installation_approval(configuration=configuration, plugin_id="fake-managed"),
            plan=_installation_plan(plugin_id="fake-managed"),
            configuration=configuration,
            manifest={"plugin_id": "other-plugin"},
            provider_instance_id="pi-fake-managed",
        )


def test_provider_inventory_approves_and_applies_installation_plan() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )
    configuration = _installation_configuration()

    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration=configuration,
        operator_note="Approved for local testing",
    )
    configuration["base_url"] = "http://127.0.0.1:9998"
    job = service.apply_installation_approval(approval.approval_id)

    provider = service.store.get_provider_instance(job.provider_instance_id)
    stored_approval = service.list_installation_approvals()[0]

    assert approval.plugin_id == "fake-managed"
    assert approval.plan_id == "plan-fake-managed"
    assert approval.plan_hash.startswith("sha256:")
    assert approval.configuration_hash.startswith("sha256:")
    assert approval.configuration["base_url"] == "http://127.0.0.1:9999"
    assert approval.approved_permissions == ["network.private"]
    assert approval.acknowledged_package_verification["status"] == "VERIFIED"
    assert approval.acknowledged_sandbox_policy["execution_mode"] == "RECORDED_ONLY"
    assert approval.acknowledged_secret_requirements[0]["requirement_key"] == (
        "API_KEY:Optional provider API key handle"
    )
    assert approval.selected_secret_handles == []
    assert approval.operator_note == "Approved for local testing"
    assert stored_approval == approval
    assert job.status == "SUCCEEDED"
    assert job.approval_id == approval.approval_id
    assert job.provider_instance_id == provider.provider_instance_id
    assert job.rollback_status == "NOT_REQUIRED"
    assert "rollback is not required" in (job.rollback_summary or "")
    assert job.step_results
    assert job.executor_id == "sandbox-enforced-declarative-v1"
    assert job.step_results[0].step_type == "sandbox_boundary"
    assert job.completed_at is not None
    assert provider.plugin_id == "fake-managed"
    assert provider.connection_mode == "managed"
    assert provider.operational_state == "created"
    assert provider.configuration["base_url"] == "http://127.0.0.1:9999"
    assert service.list_installation_jobs() == [job]


def test_provider_inventory_rolls_back_succeeded_installation_job_and_cleans_local_inventory() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )
    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration=_installation_configuration(),
    )
    job = service.apply_installation_approval(approval.approval_id)

    rolled_back = service.rollback_installation_job(job.job_id)

    assert rolled_back.job_id == job.job_id
    assert rolled_back.rollback_status == "COMPLETED"
    assert rolled_back.rollback_started_at is not None
    assert rolled_back.rollback_completed_at is not None
    assert rolled_back.rollback_step_results
    assert rolled_back.rollback_step_results[-1].step_id == ("rollback-delete-local-provider-instance")
    assert service.list_provider_instances() == []


def test_provider_inventory_rollback_marks_not_needed_when_job_never_created_provider_instance() -> None:
    class ExplodingExecutor(RecordedProviderInstallationExecutor):
        executor_id = "exploding-recorded"

        def apply(
            self,
            *,
            approval: ProviderInstallationApproval,
            plan: InstallationPlan,
            configuration: dict,
            manifest: dict,
            provider_instance_id: str,
        ) -> ProviderInstallationExecutionResult:
            raise RuntimeError("executor exploded before provider instance creation")

    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
        installation_executor=ExplodingExecutor(),
    )
    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration=_installation_configuration(),
    )

    job = service.apply_installation_approval(approval.approval_id)

    assert job.status == "FAILED"
    assert job.rollback_status == "COMPLETED"
    assert "local provider inventory cleanup" in (job.rollback_summary or "").lower()
    assert job.rollback_started_at is not None
    assert job.rollback_completed_at is not None
    assert job.rollback_step_results[0].step_id == "rollback-recorded-local-inventory"
    assert service.list_provider_instances() == []


def test_provider_inventory_rejects_duplicate_installation_job_rollback() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )
    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration=_installation_configuration(),
    )
    job = service.apply_installation_approval(approval.approval_id)

    service.rollback_installation_job(job.job_id)

    with pytest.raises(ValueError, match="rollback already completed"):
        service.rollback_installation_job(job.job_id)


def test_provider_inventory_uses_controlled_filesystem_executor_for_real_host_state(
    tmp_path,
) -> None:
    registry = PluginRegistry()
    registry.register(ControlledFilesystemPlugin())
    executor = ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root")
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
        installation_executor=executor,
    )
    approval = service.approve_installation_plan(
        plugin_id="controlled-fs",
        configuration=_installation_configuration(),
        approved_permissions=[
            "network.private",
            "filesystem.controlled_path",
        ],
    )

    job = service.apply_installation_approval(approval.approval_id)
    state_path = (
        tmp_path / "executor-root" / "providers" / job.provider_instance_id / "provider-installation-state.json"
    )
    volume_path = tmp_path / "executor-root" / "providers" / job.provider_instance_id / "volumes" / "provider-cache"
    download_manifest_path = (
        tmp_path / "executor-root" / "providers" / job.provider_instance_id / "downloads" / "01-fake-model.json"
    )

    assert job.status == "SUCCEEDED"
    assert job.executor_id == "controlled-filesystem-v1"
    assert job.rollback_status == "PENDING"
    assert state_path.exists()
    assert volume_path.exists()
    assert download_manifest_path.exists()

    rolled_back = service.rollback_installation_job(job.job_id)

    assert rolled_back.rollback_status == "COMPLETED"
    assert not state_path.exists()
    assert not volume_path.exists()
    assert not download_manifest_path.exists()
    assert service.list_provider_instances() == []


def test_provider_inventory_uses_controlled_filesystem_executor_for_local_imports(
    tmp_path,
) -> None:
    registry = PluginRegistry()
    registry.register(LocalImportControlledFilesystemPlugin())
    imports_root = tmp_path / "executor-root" / "imports" / "models"
    imports_root.mkdir(parents=True, exist_ok=True)
    source_path = imports_root / "fake-model.gguf"
    source_path.write_text("fake-model-bytes", encoding="utf-8")
    executor = ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root")
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
        installation_executor=executor,
    )
    approval = service.approve_installation_plan(
        plugin_id="controlled-fs-import",
        configuration=_installation_configuration(),
        approved_permissions=[
            "network.private",
            "filesystem.controlled_path",
        ],
    )

    job = service.apply_installation_approval(approval.approval_id)
    imported_path = (
        tmp_path
        / "executor-root"
        / "providers"
        / job.provider_instance_id
        / "volumes"
        / "provider-cache"
        / "fake-model.gguf"
    )

    assert job.status == "SUCCEEDED"
    assert imported_path.exists()
    assert imported_path.read_text(encoding="utf-8") == "fake-model-bytes"
    assert any(step.step_type == "filesystem_import_local_artifact" for step in job.step_results)

    rolled_back = service.rollback_installation_job(job.job_id)

    assert rolled_back.rollback_status == "COMPLETED"
    assert not imported_path.exists()


def test_provider_inventory_apply_rejects_revoked_approval() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )
    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration=_installation_configuration(),
    )
    service.store.save_installation_approval(approval.model_copy(update={"status": "REVOKED"}))

    with pytest.raises(ValueError, match="installation approval is not active"):
        service.apply_installation_approval(approval.approval_id)


def test_provider_inventory_probe_persists_observed_health() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )
    instance = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )

    assert instance.health_status == "unknown"
    result = service.probe_provider_instance(instance.provider_instance_id)

    assert result["healthy"] is True
    assert result["error"] is None
    observed = service.store.get_provider_instance(instance.provider_instance_id)
    assert observed.operational_state == "ready"
    assert observed.health_status == "healthy"
    assert observed.last_health_check_at == result["checked_at"]
    assert observed.last_health_error is None


def test_provider_inventory_run_installation_diagnostics_reports_ready_when_inputs_match() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )

    diagnostics = service.run_installation_diagnostics(
        plugin_id="fake-managed",
        configuration=_installation_configuration(),
        approved_permissions=["network.private"],
        selected_secret_handles=[
            {
                "requirement_key": "API_KEY:Optional provider API key handle",
                "secret_handle": "secret://providers/fake-managed/api-key",
            }
        ],
    )

    assert diagnostics.plugin_id == "fake-managed"
    assert diagnostics.readiness_status == "READY"
    assert diagnostics.rollback_result.status == "NOT_REQUIRED"
    assert diagnostics.rollback_result.details["executor_id"] == "sandbox-enforced-declarative-v1"
    assert [check.status for check in diagnostics.checks] == [
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
    ]
    package_check = next(check for check in diagnostics.checks if check.check_id == "package_verification")
    assert package_check.status == "PASS"
    assert package_check.details["status"] == "VERIFIED"


def test_provider_inventory_run_installation_diagnostics_reports_action_required_for_optional_secret_gap() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )

    diagnostics = service.run_installation_diagnostics(
        plugin_id="fake-managed",
        configuration=_installation_configuration(),
        approved_permissions=["network.private"],
    )

    assert diagnostics.readiness_status == "ACTION_REQUIRED"
    secret_check = next(check for check in diagnostics.checks if check.check_id == "secret_handles")
    assert secret_check.status == "WARN"
    assert "missing_optional_requirements" in secret_check.details


def test_controlled_filesystem_executor_diagnostics_block_missing_local_import_artifacts(
    tmp_path,
) -> None:
    registry = PluginRegistry()
    registry.register(LocalImportControlledFilesystemPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
        installation_executor=ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root"),
    )

    diagnostics = service.run_installation_diagnostics(
        plugin_id="controlled-fs-import",
        configuration=_installation_configuration(),
        approved_permissions=["network.private", "filesystem.controlled_path"],
        selected_secret_handles=[
            {
                "requirement_key": "API_KEY:Optional provider API key handle",
                "secret_handle": "secret://providers/controlled-fs-import/api-key",
            }
        ],
    )

    assert diagnostics.readiness_status == "BLOCKED"
    import_check = next(check for check in diagnostics.checks if check.check_id == "local_import_artifacts")
    assert import_check.status == "FAIL"
    assert import_check.details["required_local_import_count"] == 1
    assert import_check.details["missing_local_import_count"] == 1
    assert import_check.details["local_imports"][0]["exists"] is False


def test_controlled_filesystem_executor_diagnostics_confirm_ready_local_import_artifacts(
    tmp_path,
) -> None:
    registry = PluginRegistry()
    registry.register(LocalImportControlledFilesystemPlugin())
    imports_root = tmp_path / "executor-root" / "imports" / "models"
    imports_root.mkdir(parents=True, exist_ok=True)
    source_path = imports_root / "fake-model.gguf"
    source_path.write_text("fake-model-bytes", encoding="utf-8")
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
        installation_executor=ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root"),
    )

    diagnostics = service.run_installation_diagnostics(
        plugin_id="controlled-fs-import",
        configuration=_installation_configuration(),
        approved_permissions=["network.private", "filesystem.controlled_path"],
        selected_secret_handles=[
            {
                "requirement_key": "API_KEY:Optional provider API key handle",
                "secret_handle": "secret://providers/controlled-fs-import/api-key",
            }
        ],
    )

    assert diagnostics.readiness_status == "READY"
    import_check = next(check for check in diagnostics.checks if check.check_id == "local_import_artifacts")
    assert import_check.status == "PASS"
    assert import_check.details["ready_local_import_count"] == 1
    assert import_check.details["missing_local_import_count"] == 0
    assert import_check.details["local_imports"][0]["exists"] is True
    assert import_check.details["local_imports"][0]["size_bytes"] == len("fake-model-bytes")


def test_provider_inventory_stages_lists_and_deletes_controlled_installation_artifacts(
    tmp_path,
) -> None:
    registry = PluginRegistry()
    registry.register(LocalImportControlledFilesystemPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
        installation_executor=ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root"),
    )

    created = service.stage_local_artifact(
        relative_path="models/fake-model.gguf",
        content_bytes=b"fake-model-bytes",
    )
    inventory = service.installation_artifact_inventory()

    assert created.relative_path == "models/fake-model.gguf"
    assert created.size_bytes == len(b"fake-model-bytes")
    assert created.sha256.startswith("sha256:")
    assert inventory.supported is True
    assert inventory.imports_root.endswith("executor-root\\imports") or inventory.imports_root.endswith(
        "executor-root/imports"
    )
    assert inventory.items[0].relative_path == "models/fake-model.gguf"

    service.delete_local_artifact(relative_path="models/fake-model.gguf")
    inventory_after_delete = service.installation_artifact_inventory()

    assert inventory_after_delete.items == []


def test_provider_inventory_extracts_staged_archive_into_controlled_imports_root(
    tmp_path,
) -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
        installation_executor=ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root"),
    )

    service.stage_local_artifact(
        relative_path="archives/fake-model.zip",
        content_bytes=_zip_bytes(
            {
                "weights/model.gguf": b"fake-model-bytes",
                "metadata/config.json": b'{"name":"fake"}',
            }
        ),
    )

    result = service.extract_local_artifact_archive(
        archive_relative_path="archives/fake-model.zip",
        destination_directory="models/fake-model",
    )
    inventory = service.installation_artifact_inventory()

    assert result.archive_relative_path == "archives/fake-model.zip"
    assert result.destination_directory == "models/fake-model"
    assert result.extracted_file_count == 2
    assert "models/fake-model/weights/model.gguf" in result.extracted_relative_paths
    assert "models/fake-model/metadata/config.json" in result.extracted_relative_paths
    assert any(item.relative_path == "models/fake-model/weights/model.gguf" for item in inventory.items)
    assert any(item.relative_path == "models/fake-model/metadata/config.json" for item in inventory.items)


def test_provider_inventory_rejects_archive_members_outside_controlled_imports_root(
    tmp_path,
) -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
        installation_executor=ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root"),
    )

    service.stage_local_artifact(
        relative_path="archives/escape.zip",
        content_bytes=_zip_bytes({"../escape.txt": b"nope"}),
    )

    with pytest.raises(
        ValueError,
        match="does not permit archive members outside the extraction target",
    ):
        service.extract_local_artifact_archive(
            archive_relative_path="archives/escape.zip",
            destination_directory="models/fake-model",
        )


def test_provider_inventory_rejects_local_artifact_staging_for_non_staging_executor() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )

    with pytest.raises(
        ValueError,
        match="does not support local artifact staging",
    ):
        service.stage_local_artifact(
            relative_path="models/fake-model.gguf",
            content_bytes=b"fake-model-bytes",
        )

    with pytest.raises(
        ValueError,
        match="does not support local artifact archive extraction",
    ):
        service.extract_local_artifact_archive(
            archive_relative_path="archives/fake-model.zip",
            destination_directory="models/fake-model",
        )


def test_provider_inventory_run_installation_diagnostics_blocks_missing_permission_ack() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )

    diagnostics = service.run_installation_diagnostics(
        plugin_id="fake-managed",
        configuration=_installation_configuration(),
        approved_permissions=[],
    )

    assert diagnostics.readiness_status == "BLOCKED"
    permission_check = next(check for check in diagnostics.checks if check.check_id == "permissions_acknowledged")
    assert permission_check.status == "FAIL"
    assert "approved permissions must match requested permissions exactly" in permission_check.summary


def test_provider_inventory_run_installation_diagnostics_blocks_unsupported_sandbox_policy() -> None:
    class SandboxedPlugin(FakeManagedPlugin):
        plugin_id = "sandbox-required"

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["sandbox_policy"] = {
                "execution_mode": "UNSANDBOXED_HOST",
                "filesystem_scope": "CONTROLLED_PATHS",
                "network_scope": "DECLARED_EGRESS",
                "secret_scope": "DECLARED_HANDLES_ONLY",
            }
            return description

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            return plan

    registry = PluginRegistry()
    registry.register(SandboxedPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    diagnostics = service.run_installation_diagnostics(
        plugin_id="sandbox-required",
        configuration=_installation_configuration(),
        approved_permissions=["network.private"],
        selected_secret_handles=[
            {
                "requirement_key": "API_KEY:Optional provider API key handle",
                "secret_handle": "secret://providers/sandbox-required/api-key",
            }
        ],
    )

    assert diagnostics.readiness_status == "BLOCKED"
    sandbox_check = next(check for check in diagnostics.checks if check.check_id == "sandbox_policy")
    assert sandbox_check.status == "FAIL"
    assert "unsupported execution mode" in sandbox_check.summary


def test_provider_inventory_executor_capabilities_allow_stricter_sandbox_policy_when_supported() -> None:
    class SandboxedPlugin(FakeManagedPlugin):
        plugin_id = "sandbox-supported"

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["sandbox_policy"] = {
                "execution_mode": "SANDBOX_REQUIRED",
                "filesystem_scope": "CONTROLLED_PATHS",
                "network_scope": "DECLARED_EGRESS",
                "egress_rules": [{"host": "provider.example.com", "port": 443}],
                "secret_scope": "DECLARED_HANDLES_ONLY",
            }
            return description

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            return plan

    class SandboxedExecutor(RecordedProviderInstallationExecutor):
        executor_id = "sandboxed-declarative-v1"

        def sandbox_capabilities(self):
            capabilities = super().sandbox_capabilities()
            return capabilities.model_copy(
                update={
                    "supported_execution_modes": ["RECORDED_ONLY", "SANDBOX_REQUIRED"],
                    "supported_filesystem_scopes": ["NONE", "CONTROLLED_PATHS"],
                    "supported_network_scopes": ["NONE", "DECLARED_EGRESS"],
                    "host_mutation": True,
                    "notes": "Sandboxed executor contract for future host-mutating apply.",
                }
            )

    registry = PluginRegistry()
    registry.register(SandboxedPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
        installation_executor=SandboxedExecutor(),
    )

    diagnostics = service.run_installation_diagnostics(
        plugin_id="sandbox-supported",
        configuration=_installation_configuration(),
        approved_permissions=["network.private"],
        selected_secret_handles=[
            {
                "requirement_key": "API_KEY:Optional provider API key handle",
                "secret_handle": "secret://providers/sandbox-supported/api-key",
            }
        ],
    )
    approval = service.approve_installation_plan(
        plugin_id="sandbox-supported",
        configuration=_installation_configuration(),
        approved_permissions=["network.private"],
        selected_secret_handles=[
            {
                "requirement_key": "API_KEY:Optional provider API key handle",
                "secret_handle": "secret://providers/sandbox-supported/api-key",
            }
        ],
    )

    assert diagnostics.readiness_status == "READY"
    sandbox_check = next(check for check in diagnostics.checks if check.check_id == "sandbox_policy")
    assert sandbox_check.status == "PASS"
    assert sandbox_check.details["executor_sandbox_capabilities"]["host_mutation"] is True
    assert approval.acknowledged_sandbox_policy["execution_mode"] == "SANDBOX_REQUIRED"


def test_provider_inventory_run_installation_diagnostics_blocks_unsupported_sandbox_scope() -> None:
    class FilesystemHeavyPlugin(FakeManagedPlugin):
        plugin_id = "sandbox-fs-heavy"

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["sandbox_policy"] = {
                "execution_mode": "RECORDED_ONLY",
                "filesystem_scope": "MODEL_STORAGE_ONLY",
                "network_scope": "NONE",
                "secret_scope": "DECLARED_HANDLES_ONLY",
            }
            return description

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            return plan

    registry = PluginRegistry()
    registry.register(FilesystemHeavyPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    diagnostics = service.run_installation_diagnostics(
        plugin_id="sandbox-fs-heavy",
        configuration=_installation_configuration(),
        approved_permissions=["network.private"],
        selected_secret_handles=[
            {
                "requirement_key": "API_KEY:Optional provider API key handle",
                "secret_handle": "secret://providers/sandbox-fs-heavy/api-key",
            }
        ],
    )

    assert diagnostics.readiness_status == "BLOCKED"
    sandbox_check = next(check for check in diagnostics.checks if check.check_id == "sandbox_policy")
    assert sandbox_check.status == "FAIL"
    assert "unsupported filesystem scope" in sandbox_check.summary


def test_provider_inventory_approval_rejects_incomplete_explicit_permission_acknowledgement() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )

    with pytest.raises(
        ValueError,
        match="approved permissions must match requested permissions exactly",
    ):
        service.approve_installation_plan(
            plugin_id="fake-managed",
            configuration=_installation_configuration(),
            approved_permissions=[],
        )


def test_provider_inventory_run_installation_diagnostics_blocks_changed_permission_contract_without_upgrade_ack() -> (
    None
):
    class MutablePermissionPlugin(FakeManagedPlugin):
        plugin_id = "mutable-permissions"

        def __init__(self) -> None:
            self.required_permissions = [
                {
                    "permission_id": "network.private",
                    "label": "Private network",
                    "risk_level": "low",
                    "reason": "Connect to a local fake provider endpoint",
                }
            ]

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["required_permissions"] = list(self.required_permissions)
            return description

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            plan["required_permissions"] = list(self.required_permissions)
            return plan

    plugin = MutablePermissionPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    service.approve_installation_plan(
        plugin_id="mutable-permissions",
        configuration=_installation_configuration(),
        approved_permissions=["network.private"],
    )
    plugin.required_permissions = [
        *plugin.required_permissions,
        {
            "permission_id": "filesystem.write",
            "label": "Filesystem write",
            "risk_level": "medium",
            "reason": "Write provider files into a controlled location",
        },
    ]

    diagnostics = service.run_installation_diagnostics(
        plugin_id="mutable-permissions",
        configuration=_installation_configuration(),
        approved_permissions=["network.private", "filesystem.write"],
    )

    assert diagnostics.readiness_status == "BLOCKED"
    upgrade_check = next(check for check in diagnostics.checks if check.check_id == "upgrade_review")
    assert upgrade_check.status == "FAIL"
    assert "requires explicit upgrade acknowledgement" in upgrade_check.summary
    assert upgrade_check.details["status"] == "CHANGED"
    assert upgrade_check.details["added_permissions"] == ["filesystem.write"]


def test_provider_inventory_approval_records_selected_secret_handles() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )

    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration=_installation_configuration(),
        approved_permissions=["network.private"],
        selected_secret_handles=[
            {
                "requirement_key": "API_KEY:Optional provider API key handle",
                "secret_handle": "secret://providers/fake-managed/api-key",
            }
        ],
    )

    assert approval.selected_secret_handles[0].secret_handle == ("secret://providers/fake-managed/api-key")
    assert approval.selected_secret_handles[0].label == "Optional provider API key handle"


def test_provider_inventory_approval_requires_upgrade_acknowledgement_for_changed_contract() -> None:
    class MutablePermissionPlugin(FakeManagedPlugin):
        plugin_id = "mutable-permissions"

        def __init__(self) -> None:
            self.required_permissions = [
                {
                    "permission_id": "network.private",
                    "label": "Private network",
                    "risk_level": "low",
                    "reason": "Connect to a local fake provider endpoint",
                }
            ]

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["required_permissions"] = list(self.required_permissions)
            return description

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            plan["required_permissions"] = list(self.required_permissions)
            return plan

    plugin = MutablePermissionPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    service.approve_installation_plan(
        plugin_id="mutable-permissions",
        configuration=_installation_configuration(),
        approved_permissions=["network.private"],
    )
    plugin.required_permissions = [
        *plugin.required_permissions,
        {
            "permission_id": "filesystem.write",
            "label": "Filesystem write",
            "risk_level": "medium",
            "reason": "Write provider files into a controlled location",
        },
    ]

    with pytest.raises(
        ValueError,
        match="installation permission or sandbox change requires explicit upgrade acknowledgement",
    ):
        service.approve_installation_plan(
            plugin_id="mutable-permissions",
            configuration=_installation_configuration(),
            approved_permissions=["network.private", "filesystem.write"],
        )


def test_provider_inventory_approval_records_upgrade_review_when_contract_change_is_acknowledged() -> None:
    class MutablePermissionPlugin(FakeManagedPlugin):
        plugin_id = "mutable-permissions"

        def __init__(self) -> None:
            self.required_permissions = [
                {
                    "permission_id": "network.private",
                    "label": "Private network",
                    "risk_level": "low",
                    "reason": "Connect to a local fake provider endpoint",
                }
            ]

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["required_permissions"] = list(self.required_permissions)
            return description

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            plan["required_permissions"] = list(self.required_permissions)
            return plan

    plugin = MutablePermissionPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    service.approve_installation_plan(
        plugin_id="mutable-permissions",
        configuration=_installation_configuration(),
        approved_permissions=["network.private"],
    )
    plugin.required_permissions = [
        *plugin.required_permissions,
        {
            "permission_id": "filesystem.write",
            "label": "Filesystem write",
            "risk_level": "medium",
            "reason": "Write provider files into a controlled location",
        },
    ]

    approval = service.approve_installation_plan(
        plugin_id="mutable-permissions",
        configuration=_installation_configuration(),
        approved_permissions=["network.private", "filesystem.write"],
        upgrade_acknowledged=True,
    )

    assert approval.upgrade_acknowledged is True
    assert approval.upgrade_review["status"] == "CHANGED"
    assert approval.upgrade_review["requires_acknowledgement"] is True
    assert approval.upgrade_review["added_permissions"] == ["filesystem.write"]


def test_provider_inventory_approval_rejects_unsupported_sandbox_policy() -> None:
    class SandboxedPlugin(FakeManagedPlugin):
        plugin_id = "sandbox-required"

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["sandbox_policy"] = {
                "execution_mode": "UNSANDBOXED_HOST",
                "filesystem_scope": "CONTROLLED_PATHS",
                "network_scope": "DECLARED_EGRESS",
                "secret_scope": "DECLARED_HANDLES_ONLY",
            }
            return description

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            return plan

    registry = PluginRegistry()
    registry.register(SandboxedPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    with pytest.raises(
        ValueError,
        match="plugin sandbox policy requires an unsupported execution mode",
    ):
        service.approve_installation_plan(
            plugin_id="sandbox-required",
            configuration=_installation_configuration(),
            approved_permissions=["network.private"],
        )


def test_provider_inventory_approval_requires_handles_for_required_secret_requirements() -> None:
    class RequiredSecretPlugin(FakeManagedPlugin):
        plugin_id = "required-secret"

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["secret_requirements"] = [
                {
                    "secret_type": "API_KEY",
                    "label": "Required provider API key handle",
                    "required": True,
                    "allowed_usage": ["provider.connect"],
                }
            ]
            return description

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            return plan

    registry = PluginRegistry()
    registry.register(RequiredSecretPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    with pytest.raises(ValueError, match="required secret handles are missing"):
        service.approve_installation_plan(
            plugin_id="required-secret",
            configuration=_installation_configuration(),
            approved_permissions=["network.private"],
        )


def test_provider_inventory_apply_rejects_secret_requirement_drift() -> None:
    class MutableSecretPlugin(FakeManagedPlugin):
        plugin_id = "mutable-secret"

        def __init__(self) -> None:
            self.secret_label = "Optional provider API key handle"

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["secret_requirements"] = [
                {
                    "secret_type": "API_KEY",
                    "label": self.secret_label,
                    "required": False,
                    "allowed_usage": ["provider.connect"],
                }
            ]
            return description

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            return plan

    plugin = MutableSecretPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    approval = service.approve_installation_plan(
        plugin_id="mutable-secret",
        configuration=_installation_configuration(),
        approved_permissions=["network.private"],
    )
    plugin.secret_label = "Changed provider API key handle"

    with pytest.raises(
        ValueError,
        match="installation secret requirements changed since approval",
    ):
        service.apply_installation_approval(approval.approval_id)


def test_provider_inventory_apply_rejects_sandbox_policy_drift() -> None:
    class MutableSandboxPlugin(FakeManagedPlugin):
        plugin_id = "mutable-sandbox"

        def __init__(self) -> None:
            self.execution_mode = "RECORDED_ONLY"

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["sandbox_policy"] = {
                "execution_mode": self.execution_mode,
                "filesystem_scope": "NONE",
                "network_scope": "NONE",
                "secret_scope": "DECLARED_HANDLES_ONLY",
            }
            return description

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            return plan

    plugin = MutableSandboxPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    approval = service.approve_installation_plan(
        plugin_id="mutable-sandbox",
        configuration=_installation_configuration(),
        approved_permissions=["network.private"],
    )
    plugin.execution_mode = "SANDBOX_REQUIRED"

    with pytest.raises(
        ValueError,
        match="installation sandbox policy changed since approval",
    ):
        service.apply_installation_approval(approval.approval_id)


def test_provider_inventory_apply_rejects_plan_hash_mismatch() -> None:
    class MutablePlanPlugin(FakeManagedPlugin):
        plugin_id = "mutable-plan"

        def __init__(self) -> None:
            self.summary = "Original plan"

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            plan["summary"] = self.summary
            return plan

    plugin = MutablePlanPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    approval = service.approve_installation_plan(
        plugin_id="mutable-plan",
        configuration=_installation_configuration(),
    )
    plugin.summary = "Updated plan"

    with pytest.raises(ValueError, match="installation plan hash mismatch"):
        service.apply_installation_approval(approval.approval_id)


def test_provider_inventory_apply_isolates_nested_approval_configuration_from_plan_rebuild() -> None:
    class NestedMutatingPlanPlugin(FakeManagedPlugin):
        plugin_id = "nested-mutating-plan"

        def build_installation_plan(self, configuration: dict) -> dict:
            configuration["runtime"]["endpoint"] = "mutated-by-plan"
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            return plan

    registry = PluginRegistry()
    registry.register(NestedMutatingPlanPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    configuration = {
        **_installation_configuration(),
        "runtime": {"endpoint": "approved", "retries": 3},
    }

    approval = service.approve_installation_plan(
        plugin_id="nested-mutating-plan",
        configuration=configuration,
    )
    job = service.apply_installation_approval(approval.approval_id)
    provider = service.store.get_provider_instance(job.provider_instance_id)
    stored_approval = service.store.get_installation_approval(approval.approval_id)

    assert job.status == "SUCCEEDED"
    assert approval.configuration["runtime"] == {"endpoint": "approved", "retries": 3}
    assert stored_approval.configuration["runtime"] == {"endpoint": "approved", "retries": 3}
    assert provider.configuration["runtime"] == {"endpoint": "approved", "retries": 3}


def test_provider_inventory_apply_fails_when_executor_returns_mismatched_provider_identity() -> None:
    class MismatchedProviderExecutor:
        executor_id = "mismatched-provider"

        def apply(
            self,
            *,
            approval: ProviderInstallationApproval,
            plan: InstallationPlan,
            configuration: dict,
            manifest: dict,
            provider_instance_id: str,
        ) -> ProviderInstallationExecutionResult:
            return ProviderInstallationExecutionResult(
                provider_instance={
                    "provider_instance_id": f"{provider_instance_id}-other",
                    "plugin_id": approval.plugin_id,
                    "provider_family": "fake",
                    "display_name": "Local Fake",
                    "connection_mode": "managed",
                    "configuration": configuration,
                    "operational_state": "created",
                },
            )

    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
        installation_executor=MismatchedProviderExecutor(),
    )
    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration=_installation_configuration(),
    )

    job = service.apply_installation_approval(approval.approval_id)

    assert job.status == "FAILED"
    assert job.error_code == "ValueError"
    assert "provider_instance_id" in (job.error_message or "")
    assert service.list_provider_instances() == []


def test_provider_inventory_apply_fails_when_executor_returns_mismatched_plugin() -> None:
    class MismatchedPluginExecutor:
        executor_id = "mismatched-plugin"

        def apply(
            self,
            *,
            approval: ProviderInstallationApproval,
            plan: InstallationPlan,
            configuration: dict,
            manifest: dict,
            provider_instance_id: str,
        ) -> ProviderInstallationExecutionResult:
            return ProviderInstallationExecutionResult(
                provider_instance={
                    "provider_instance_id": provider_instance_id,
                    "plugin_id": "other-plugin",
                    "provider_family": "fake",
                    "display_name": "Local Fake",
                    "connection_mode": "managed",
                    "configuration": configuration,
                    "operational_state": "created",
                },
            )

    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
        installation_executor=MismatchedPluginExecutor(),
    )
    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration=_installation_configuration(),
    )

    job = service.apply_installation_approval(approval.approval_id)

    assert job.status == "FAILED"
    assert job.error_code == "ValueError"
    assert "plugin_id" in (job.error_message or "")
    assert service.list_provider_instances() == []


def test_provider_inventory_approval_hashes_are_deterministic_for_key_order() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )

    first = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        },
    )
    second = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "base_url": "http://127.0.0.1:9999",
            "display_name": "Local Fake",
        },
    )

    assert first.configuration_hash == second.configuration_hash
    assert first.plan_hash == second.plan_hash
