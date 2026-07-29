"""Fail-closed OCI launch specifications for package-backed Plugin Hosts."""

from __future__ import annotations

import shutil
from pathlib import Path

from aidn_hypervisor.providers.models import PluginHostEntrypoint, PluginSandboxPolicy


class PluginHostContainerError(ValueError):
    """A requested Plugin Host container boundary cannot be enforced."""


class DockerPluginHostLauncher:
    """Build a restrictive Docker command without granting host capabilities."""

    _INHERITED_ENVIRONMENT = (
        "AIDN_PLUGIN_HOST_INSTALLED_PLUGIN_ID",
        "AIDN_PLUGIN_HOST_PLUGIN_ID",
        "AIDN_PLUGIN_HOST_INSTALLATION_GENERATION",
        "AIDN_PLUGIN_HOST_ACTIVATION_CREDENTIAL_KEY_ID",
        "AIDN_PLUGIN_HOST_ACTIVATION_SECRET",
    )

    def __init__(
        self,
        *,
        image: str = "python:3.11-slim",
        executable: str = "docker",
    ) -> None:
        if not image or not executable:
            raise ValueError("Plugin Host container image and executable are required")
        self.image = image
        self.executable = executable

    def is_available(self) -> bool:
        return shutil.which(self.executable) is not None

    def build_launch_spec(
        self,
        *,
        package_root: Path,
        entrypoint: PluginHostEntrypoint,
        sandbox_policy: PluginSandboxPolicy,
    ) -> dict:
        if sandbox_policy.execution_mode != "SANDBOX_REQUIRED":
            raise PluginHostContainerError("package Plugin Host requires SANDBOX_REQUIRED")
        if sandbox_policy.filesystem_scope != "NONE":
            raise PluginHostContainerError(
                "container Plugin Host supports only filesystem_scope NONE"
            )
        if sandbox_policy.network_scope != "NONE":
            raise PluginHostContainerError(
                "container Plugin Host supports only network_scope NONE"
            )
        if sandbox_policy.secret_scope != "DECLARED_HANDLES_ONLY":
            raise PluginHostContainerError("container Plugin Host secret scope is unsupported")
        root = package_root.resolve()
        target = root.joinpath(*Path(entrypoint.entrypoint_path).parts).resolve()
        if root not in target.parents or not target.is_file():
            raise PluginHostContainerError("Plugin Host entrypoint is outside verified package root")
        container_entrypoint = "/opt/aidn/plugin/" + entrypoint.entrypoint_path
        command = [
            self.executable,
            "run",
            "--rm",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "128",
            "--memory",
            "1g",
            "--network",
            "none",
            "--user",
            "65534:65534",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--mount",
            f"type=bind,src={root},dst=/opt/aidn/plugin,readonly",
            "--workdir",
            "/opt/aidn/plugin",
        ]
        for name in self._INHERITED_ENVIRONMENT:
            command.extend(("--env", name))
        command.extend((self.image, "python", container_entrypoint, *entrypoint.arguments))
        return {
            "command": command,
            "working_directory": None,
            "metadata": {
                "package_execution_mode": "SANDBOX_REQUIRED",
                "container_runtime": "docker",
                "container_image": self.image,
                "network_scope": "NONE",
                "filesystem_scope": "NONE",
            },
        }
