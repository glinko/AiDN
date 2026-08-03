from __future__ import annotations

import hashlib
import io
import zipfile

from aidn_hypervisor.plugins.container import DockerPluginHostLauncher
from aidn_hypervisor.providers.models import (
    InstalledPlugin,
    PluginHostEntrypoint,
    PluginRelease,
    PluginSandboxPolicy,
)
from aidn_hypervisor.providers.package_store import FilesystemPluginPackageStore
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore


class _AvailableDockerPluginHostLauncher(DockerPluginHostLauncher):
    def is_available(self) -> bool:
        return True


def test_verified_package_host_uses_docker_for_sandbox_required_policy(tmp_path) -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("runtime/host.py", "print('sandboxed host')\n")
    package_bytes = archive.getvalue()
    package_digest = "sha256:" + hashlib.sha256(package_bytes).hexdigest()
    package_store = FilesystemPluginPackageStore(tmp_path / "packages")
    package_store.stage(package_bytes=package_bytes, expected_digest=package_digest)
    store = InMemoryProviderInventoryStore()
    policy = PluginSandboxPolicy(
        execution_mode="SANDBOX_REQUIRED",
        filesystem_scope="PLUGIN_DATA_ONLY",
        network_scope="NONE",
        secret_scope="DECLARED_HANDLES_ONLY",
    )
    release = PluginRelease(
        release_id="release-1",
        plugin_id="aidn.provider.test",
        plugin_version="1.0.0",
        manifest_hash="sha256:" + "a" * 64,
        package_digest=package_digest,
        publisher="test-publisher",
        trust_status="CONFORMANCE_TESTED",
        package_verification_status="VERIFIED",
        package_verification_mode="ED25519",
        trusted_publisher=True,
        host_entrypoint=PluginHostEntrypoint(
            entrypoint_path="runtime/host.py", arguments=["--serve"]
        ),
        host_execution_mode="SANDBOX_REQUIRED",
        host_sandbox_policy=policy,
        published_at="2026-07-29T00:00:00Z",
    )
    store.save_plugin_release(release)
    store.save_installed_plugin(
        InstalledPlugin(
            installed_plugin_id="installed-1",
            release_id=release.release_id,
            plugin_id=release.plugin_id,
            plugin_version=release.plugin_version,
            package_digest=package_digest,
            installation_source="PACKAGE",
            installed_at="2026-07-29T00:00:00Z",
        )
    )
    service = ProviderInventoryService(
        plugins=[],
        store=store,
        package_store=package_store,
        plugin_host_container_launcher=_AvailableDockerPluginHostLauncher(
            image="aidn-plugin-host:test"
        ),
    )
    secret_file = tmp_path / "activation-secret"
    secret_file.write_text("a" * 64, encoding="ascii")
    secret_file.chmod(0o444)

    spec = service.package_host_launch_spec(
        installed_plugin_id="installed-1",
        activation_secret_file=secret_file,
    )

    assert spec["command"][:3] == ["docker", "run", "--rm"]
    assert spec["command"][spec["command"].index("--network") + 1] == "none"
    assert spec["command"][-3:] == ["python", "/opt/aidn/plugin/runtime/host.py", "--serve"]
    assert spec["metadata"]["package_execution_mode"] == "SANDBOX_REQUIRED"
    assert spec["metadata"]["activation_secret_delivery"] == "READ_ONLY_FILE"
    assert spec["metadata"]["filesystem_scope"] == "PLUGIN_DATA_ONLY"
    assert spec["metadata"]["plugin_data_mount"] == "/var/lib/aidn/plugin-data"
    assert any(
        "plugin-data" in argument and "dst=/var/lib/aidn/plugin-data" in argument
        for argument in spec["command"]
    )
