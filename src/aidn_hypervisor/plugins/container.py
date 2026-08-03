"""Fail-closed OCI launch specifications for package-backed Plugin Hosts."""

from __future__ import annotations

import json
import shutil
import stat
import sys
import uuid
from pathlib import Path

from aidn_hypervisor.providers.models import (
    PluginHostEntrypoint,
    PluginSandboxPolicy,
    plugin_egress_policy_hash,
)


class PluginHostContainerError(ValueError):
    """A requested Plugin Host container boundary cannot be enforced."""


class DockerPluginHostLauncher:
    """Build a restrictive Docker command without granting host capabilities."""

    _IDENTITY_ENVIRONMENT = (
        "AIDN_PLUGIN_HOST_INSTALLED_PLUGIN_ID",
        "AIDN_PLUGIN_HOST_PLUGIN_ID",
        "AIDN_PLUGIN_HOST_INSTALLATION_GENERATION",
        "AIDN_PLUGIN_HOST_ACTIVATION_CREDENTIAL_KEY_ID",
    )
    _ACTIVATION_SECRET_PATH = "/run/aidn-plugin-host-activation-secret"
    _PLUGIN_DATA_PATH = "/var/lib/aidn/plugin-data"

    def __init__(
        self,
        *,
        image: str = "python:3.11-slim",
        proxy_image: str | None = None,
        executable: str = "docker",
    ) -> None:
        if not image or (proxy_image is not None and not proxy_image) or not executable:
            raise ValueError("Plugin Host container image and executable are required")
        self.image = image
        self.proxy_image = proxy_image or image
        self.executable = executable

    def is_available(self) -> bool:
        return shutil.which(self.executable) is not None

    def build_launch_spec(
        self,
        *,
        package_root: Path,
        entrypoint: PluginHostEntrypoint,
        sandbox_policy: PluginSandboxPolicy,
        activation_secret_file: Path,
        plugin_data_root: Path | None = None,
    ) -> dict:
        if sandbox_policy.execution_mode != "SANDBOX_REQUIRED":
            raise PluginHostContainerError("package Plugin Host requires SANDBOX_REQUIRED")
        if sandbox_policy.filesystem_scope not in {"NONE", "PLUGIN_DATA_ONLY"}:
            raise PluginHostContainerError(
                "container Plugin Host supports only filesystem_scope NONE or PLUGIN_DATA_ONLY"
            )
        if sandbox_policy.network_scope not in {"NONE", "DECLARED_EGRESS"}:
            raise PluginHostContainerError(
                "container Plugin Host supports only network_scope NONE or DECLARED_EGRESS"
            )
        if sandbox_policy.network_scope == "DECLARED_EGRESS" and not sandbox_policy.egress_rules:
            raise PluginHostContainerError(
                "DECLARED_EGRESS requires at least one exact egress rule"
            )
        if sandbox_policy.secret_scope != "DECLARED_HANDLES_ONLY":
            raise PluginHostContainerError("container Plugin Host secret scope is unsupported")
        root = package_root.resolve()
        secret_file = activation_secret_file.resolve()
        data_root: Path | None = None
        if sandbox_policy.filesystem_scope == "PLUGIN_DATA_ONLY":
            if plugin_data_root is None:
                raise PluginHostContainerError(
                    "PLUGIN_DATA_ONLY requires an explicit plugin data directory"
                )
            data_root = plugin_data_root.resolve()
            if plugin_data_root.is_symlink() or not data_root.is_dir():
                raise PluginHostContainerError("Plugin Host data directory is invalid")
            if data_root == root or root in data_root.parents or data_root in root.parents:
                raise PluginHostContainerError(
                    "Plugin Host data directory must be separate from the package root"
                )
        if activation_secret_file.is_symlink() or not secret_file.is_file():
            raise PluginHostContainerError("Plugin Host activation secret file is invalid")
        if stat.S_IMODE(secret_file.stat().st_mode) & 0o022:
            raise PluginHostContainerError("Plugin Host activation secret file is writable")
        target = root.joinpath(*Path(entrypoint.entrypoint_path).parts).resolve()
        if root not in target.parents or not target.is_file():
            raise PluginHostContainerError("Plugin Host entrypoint is outside verified package root")
        container_entrypoint = "/opt/aidn/plugin/" + entrypoint.entrypoint_path
        if sandbox_policy.network_scope == "DECLARED_EGRESS":
            return self._build_declared_egress_launch_spec(
                package_root=root,
                entrypoint=entrypoint,
                container_entrypoint=container_entrypoint,
                sandbox_policy=sandbox_policy,
                activation_secret_file=secret_file,
                plugin_data_root=data_root,
            )
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
            "--mount",
            f"type=bind,src={secret_file},dst={self._ACTIVATION_SECRET_PATH},readonly",
            "--workdir",
            "/opt/aidn/plugin",
        ]
        if data_root is not None:
            command[command.index("--workdir") : command.index("--workdir")] = [
                "--mount",
                f"type=bind,src={data_root},dst={self._PLUGIN_DATA_PATH}",
            ]
        for name in self._IDENTITY_ENVIRONMENT:
            command.extend(("--env", name))
        command.extend(
            (
                "--env",
                f"AIDN_PLUGIN_HOST_ACTIVATION_SECRET_FILE={self._ACTIVATION_SECRET_PATH}",
            )
        )
        command.extend((self.image, "python", container_entrypoint, *entrypoint.arguments))
        return {
            "command": command,
            "working_directory": None,
            "metadata": {
                "package_execution_mode": "SANDBOX_REQUIRED",
                "container_runtime": "docker",
                "container_image": self.image,
                "network_scope": sandbox_policy.network_scope,
                "filesystem_scope": sandbox_policy.filesystem_scope,
                "activation_secret_delivery": "READ_ONLY_FILE",
                "plugin_data_mount": self._PLUGIN_DATA_PATH if data_root is not None else None,
            },
        }

    def _build_declared_egress_launch_spec(
        self,
        *,
        package_root: Path,
        entrypoint: PluginHostEntrypoint,
        container_entrypoint: str,
        sandbox_policy: PluginSandboxPolicy,
        activation_secret_file: Path,
        plugin_data_root: Path | None,
    ) -> dict:
        proxy_script = Path(__file__).with_name("egress_proxy.py").resolve()
        if not proxy_script.is_file() or proxy_script.is_symlink():
            raise PluginHostContainerError("declared-egress proxy implementation is unavailable")
        suffix = uuid.uuid4().hex[:20]
        network_name = f"aidn-egress-{suffix}"
        proxy_name = f"aidn-egress-proxy-{suffix}"
        proxy_url = f"http://{proxy_name}:3128"
        proxy_environment = {
            "HTTP_PROXY": proxy_url,
            "HTTPS_PROXY": proxy_url,
            "ALL_PROXY": proxy_url,
            "http_proxy": proxy_url,
            "https_proxy": proxy_url,
            "all_proxy": proxy_url,
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
        supervisor_spec = {
            "docker": self.executable,
            "egress": {
                "network_name": network_name,
                "proxy_name": proxy_name,
                "proxy_image": self.proxy_image,
                "proxy_script": str(proxy_script),
                "rules": [rule.model_dump(mode="json") for rule in sandbox_policy.egress_rules],
                "policy_hash": plugin_egress_policy_hash(sandbox_policy.egress_rules),
            },
            "plugin": {
                "image": self.image,
                "package_root": str(package_root),
                "secret_file": str(activation_secret_file),
                "secret_path": self._ACTIVATION_SECRET_PATH,
                "data_root": str(plugin_data_root) if plugin_data_root is not None else None,
                "data_path": self._PLUGIN_DATA_PATH,
                "container_entrypoint": container_entrypoint,
                "arguments": list(entrypoint.arguments),
                "identity_environment": list(self._IDENTITY_ENVIRONMENT),
                "proxy_environment": proxy_environment,
            },
        }
        command = [
            sys.executable,
            "-m",
            "aidn_hypervisor.plugins.docker_supervisor",
            "--spec-json",
            json.dumps(supervisor_spec, sort_keys=True, separators=(",", ":")),
        ]
        return {
            "command": command,
            "working_directory": None,
            "metadata": {
                "package_execution_mode": "SANDBOX_REQUIRED",
                "container_runtime": "docker",
                "container_image": self.image,
                "network_scope": "DECLARED_EGRESS",
                "filesystem_scope": sandbox_policy.filesystem_scope,
                "activation_secret_delivery": "READ_ONLY_FILE",
                "plugin_data_mount": (
                    self._PLUGIN_DATA_PATH if plugin_data_root is not None else None
                ),
                "egress_policy_hash": plugin_egress_policy_hash(sandbox_policy.egress_rules),
                "egress_rule_count": len(sandbox_policy.egress_rules),
                "egress_transport": "HTTP_CONNECT_ALLOWLIST_PROXY",
                "egress_network_isolation": "DOCKER_INTERNAL_NETWORK",
                "egress_supervisor": "aidn_hypervisor.plugins.docker_supervisor",
            },
        }
