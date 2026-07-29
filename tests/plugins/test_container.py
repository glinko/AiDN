from __future__ import annotations

import pytest

from aidn_hypervisor.plugins.container import (
    DockerPluginHostLauncher,
    PluginHostContainerError,
)
from aidn_hypervisor.providers.models import PluginHostEntrypoint, PluginSandboxPolicy


def _sandbox_policy(**overrides) -> PluginSandboxPolicy:
    values = {
        "execution_mode": "SANDBOX_REQUIRED",
        "filesystem_scope": "NONE",
        "network_scope": "NONE",
        "secret_scope": "DECLARED_HANDLES_ONLY",
    }
    values.update(overrides)
    return PluginSandboxPolicy(**values)


def test_docker_plugin_host_launch_spec_is_read_only_non_root_and_network_isolated(tmp_path) -> None:
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "host.py").write_text("print('host')", encoding="utf-8")

    spec = DockerPluginHostLauncher(image="aidn-plugin-host:test").build_launch_spec(
        package_root=package_root,
        entrypoint=PluginHostEntrypoint(entrypoint_path="host.py", arguments=["--once"]),
        sandbox_policy=_sandbox_policy(),
    )

    command = spec["command"]
    assert command[:3] == ["docker", "run", "--rm"]
    assert "--read-only" in command
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--user") + 1] == "65534:65534"
    assert "/opt/aidn/plugin/host.py" in command
    assert "AIDN_PLUGIN_HOST_ACTIVATION_SECRET" in command


@pytest.mark.parametrize(
    "policy",
    [
        _sandbox_policy(filesystem_scope="PLUGIN_DATA_ONLY"),
        _sandbox_policy(network_scope="PRIVATE_ONLY"),
        _sandbox_policy(secret_scope="NONE"),
    ],
)
def test_docker_plugin_host_launch_spec_rejects_unenforceable_policy(tmp_path, policy) -> None:
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "host.py").write_text("print('host')", encoding="utf-8")

    with pytest.raises(PluginHostContainerError):
        DockerPluginHostLauncher().build_launch_spec(
            package_root=package_root,
            entrypoint=PluginHostEntrypoint(entrypoint_path="host.py"),
            sandbox_policy=policy,
        )
