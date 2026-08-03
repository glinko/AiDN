from __future__ import annotations

import json
import sys

import pytest

from aidn_hypervisor.plugins.container import (
    DockerPluginHostLauncher,
    PluginHostContainerError,
)
from aidn_hypervisor.providers.models import (
    PluginEgressRule,
    PluginHostEntrypoint,
    PluginSandboxPolicy,
)


def _sandbox_policy(**overrides) -> PluginSandboxPolicy:
    values = {
        "execution_mode": "SANDBOX_REQUIRED",
        "filesystem_scope": "NONE",
        "network_scope": "NONE",
        "secret_scope": "DECLARED_HANDLES_ONLY",
    }
    values.update(overrides)
    return PluginSandboxPolicy(**values)


def _activation_secret_file(tmp_path):
    secret_file = tmp_path / "activation-secret"
    secret_file.write_text("a" * 64, encoding="ascii")
    secret_file.chmod(0o444)
    return secret_file


def test_docker_plugin_host_launch_spec_is_read_only_non_root_and_network_isolated(tmp_path) -> None:
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "host.py").write_text("print('host')", encoding="utf-8")
    secret_file = _activation_secret_file(tmp_path)

    spec = DockerPluginHostLauncher(image="aidn-plugin-host:test").build_launch_spec(
        package_root=package_root,
        entrypoint=PluginHostEntrypoint(entrypoint_path="host.py", arguments=["--once"]),
        sandbox_policy=_sandbox_policy(),
        activation_secret_file=secret_file,
    )

    command = spec["command"]
    assert command[:3] == ["docker", "run", "--rm"]
    assert "--read-only" in command
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--user") + 1] == "65534:65534"
    assert "/opt/aidn/plugin/host.py" in command
    assert "AIDN_PLUGIN_HOST_ACTIVATION_SECRET" not in command
    assert "AIDN_PLUGIN_HOST_ACTIVATION_SECRET_FILE=/run/aidn-plugin-host-activation-secret" in command
    assert any(str(secret_file) in argument and "readonly" in argument for argument in command)


@pytest.mark.parametrize(
    "policy",
    [
        _sandbox_policy(filesystem_scope="PLUGIN_DATA_ONLY"),
        _sandbox_policy(network_scope="PRIVATE_ONLY"),
        _sandbox_policy(network_scope="DECLARED_EGRESS"),
        _sandbox_policy(secret_scope="NONE"),
    ],
)
def test_docker_plugin_host_launch_spec_rejects_unenforceable_policy(tmp_path, policy) -> None:
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "host.py").write_text("print('host')", encoding="utf-8")
    secret_file = _activation_secret_file(tmp_path)

    with pytest.raises(PluginHostContainerError):
        DockerPluginHostLauncher().build_launch_spec(
            package_root=package_root,
            entrypoint=PluginHostEntrypoint(entrypoint_path="host.py"),
            sandbox_policy=policy,
            activation_secret_file=secret_file,
        )


def test_docker_plugin_host_rejects_writable_activation_secret_file(tmp_path) -> None:
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "host.py").write_text("print('host')", encoding="utf-8")
    secret_file = _activation_secret_file(tmp_path)
    secret_file.chmod(0o644)

    with pytest.raises(PluginHostContainerError, match="secret file is writable"):
        DockerPluginHostLauncher().build_launch_spec(
            package_root=package_root,
            entrypoint=PluginHostEntrypoint(entrypoint_path="host.py"),
            sandbox_policy=_sandbox_policy(),
            activation_secret_file=secret_file,
        )


def test_docker_plugin_host_supports_only_separate_plugin_data_mount(tmp_path) -> None:
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "host.py").write_text("print('host')", encoding="utf-8")
    data_root = tmp_path / "plugin-data"
    data_root.mkdir()
    secret_file = _activation_secret_file(tmp_path)

    spec = DockerPluginHostLauncher().build_launch_spec(
        package_root=package_root,
        entrypoint=PluginHostEntrypoint(entrypoint_path="host.py"),
        sandbox_policy=_sandbox_policy(filesystem_scope="PLUGIN_DATA_ONLY"),
        activation_secret_file=secret_file,
        plugin_data_root=data_root,
    )

    command = spec["command"]
    assert any(
        str(data_root) in argument
        and "dst=/var/lib/aidn/plugin-data" in argument
        and not argument.endswith(",readonly")
        for argument in command
    )
    assert spec["metadata"]["filesystem_scope"] == "PLUGIN_DATA_ONLY"
    assert spec["metadata"]["plugin_data_mount"] == "/var/lib/aidn/plugin-data"


def test_docker_plugin_host_rejects_plugin_data_inside_package_root(tmp_path) -> None:
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "host.py").write_text("print('host')", encoding="utf-8")
    data_root = package_root / "data"
    data_root.mkdir()
    secret_file = _activation_secret_file(tmp_path)

    with pytest.raises(PluginHostContainerError, match="separate"):
        DockerPluginHostLauncher().build_launch_spec(
            package_root=package_root,
            entrypoint=PluginHostEntrypoint(entrypoint_path="host.py"),
            sandbox_policy=_sandbox_policy(filesystem_scope="PLUGIN_DATA_ONLY"),
            activation_secret_file=secret_file,
            plugin_data_root=data_root,
        )


def test_docker_plugin_host_requires_plugin_data_root(tmp_path) -> None:
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "host.py").write_text("print('host')", encoding="utf-8")
    secret_file = _activation_secret_file(tmp_path)

    with pytest.raises(PluginHostContainerError, match="explicit plugin data directory"):
        DockerPluginHostLauncher().build_launch_spec(
            package_root=package_root,
            entrypoint=PluginHostEntrypoint(entrypoint_path="host.py"),
            sandbox_policy=_sandbox_policy(filesystem_scope="PLUGIN_DATA_ONLY"),
            activation_secret_file=secret_file,
        )


def test_docker_plugin_host_declared_egress_uses_supervisor_and_exact_policy(tmp_path) -> None:
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "host.py").write_text("print('host')", encoding="utf-8")
    secret_file = _activation_secret_file(tmp_path)
    policy = _sandbox_policy(
        network_scope="DECLARED_EGRESS",
        egress_rules=[PluginEgressRule(host="API.Example.com.", port=443)],
    )

    spec = DockerPluginHostLauncher(proxy_image="python:3.11-slim").build_launch_spec(
        package_root=package_root,
        entrypoint=PluginHostEntrypoint(entrypoint_path="host.py"),
        sandbox_policy=policy,
        activation_secret_file=secret_file,
    )

    command = spec["command"]
    assert command[:3] == [sys.executable, "-m", "aidn_hypervisor.plugins.docker_supervisor"]
    supervisor_spec = json.loads(command[-1])
    assert supervisor_spec["egress"]["rules"] == [
        {"host": "api.example.com", "port": 443, "protocol": "TCP"}
    ]
    assert supervisor_spec["egress"]["policy_hash"] == spec["metadata"]["egress_policy_hash"]
    assert supervisor_spec["egress"]["network_name"].startswith("aidn-egress-")
    assert supervisor_spec["plugin"]["proxy_environment"]["HTTPS_PROXY"].startswith(
        "http://aidn-egress-proxy-"
    )
    assert spec["metadata"]["network_scope"] == "DECLARED_EGRESS"
    assert spec["metadata"]["egress_rule_count"] == 1
    assert spec["metadata"]["egress_transport"] == "HTTP_CONNECT_ALLOWLIST_PROXY"


def test_plugin_egress_rule_rejects_wildcards_and_ip_literals() -> None:
    with pytest.raises(ValueError, match="exact DNS name"):
        PluginEgressRule(host="*.example.com", port=443)
    with pytest.raises(ValueError, match="IP literal"):
        PluginEgressRule(host="203.0.113.10", port=443)
