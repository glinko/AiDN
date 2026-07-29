#!/usr/bin/env python3
"""Run a real, disposable Docker acceptance test for Plugin Host isolation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from aidn_hypervisor.plugins.container import DockerPluginHostLauncher
from aidn_hypervisor.providers.models import PluginHostEntrypoint, PluginSandboxPolicy


_HOST_CODE = """import json, os, socket
result = {"uid": os.geteuid(), "secret_present": bool(os.getenv("AIDN_PLUGIN_HOST_ACTIVATION_SECRET"))}
try:
    open("/opt/aidn/plugin/host-write-probe", "w").write("blocked")
    result["package_write_blocked"] = False
except OSError:
    result["package_write_blocked"] = True
try:
    socket.create_connection(("1.1.1.1", 53), timeout=1)
    result["network_blocked"] = False
except OSError:
    result["network_blocked"] = True
print(json.dumps(result, sort_keys=True))
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="python:3.11-slim")
    args = parser.parse_args()
    launcher = DockerPluginHostLauncher(image=args.image)
    if not launcher.is_available():
        raise RuntimeError("Docker is required for Plugin Host container acceptance")
    with tempfile.TemporaryDirectory(prefix="aidn-plugin-host-acceptance-") as directory:
        package_root = Path(directory)
        host = package_root / "host.py"
        host.write_text(_HOST_CODE, encoding="utf-8")
        os.chmod(package_root, 0o755)
        os.chmod(host, 0o444)
        spec = launcher.build_launch_spec(
            package_root=package_root,
            entrypoint=PluginHostEntrypoint(entrypoint_path="host.py"),
            sandbox_policy=PluginSandboxPolicy(
                execution_mode="SANDBOX_REQUIRED",
                filesystem_scope="NONE",
                network_scope="NONE",
                secret_scope="DECLARED_HANDLES_ONLY",
            ),
        )
        environment = {
            **os.environ,
            "AIDN_PLUGIN_HOST_INSTALLED_PLUGIN_ID": "acceptance-installation",
            "AIDN_PLUGIN_HOST_PLUGIN_ID": "aidn.acceptance.plugin",
            "AIDN_PLUGIN_HOST_INSTALLATION_GENERATION": "1",
            "AIDN_PLUGIN_HOST_ACTIVATION_CREDENTIAL_KEY_ID": "sha256:acceptance",
            "AIDN_PLUGIN_HOST_ACTIVATION_SECRET": "acceptance-secret",
        }
        completed = subprocess.run(
            spec["command"],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    result = json.loads(completed.stdout)
    if result != {
        "network_blocked": True,
        "package_write_blocked": True,
        "secret_present": True,
        "uid": 65534,
    }:
        raise RuntimeError(f"Plugin Host container boundary failed: {result}")
    print(json.dumps({"status": "ok", "result": result}, sort_keys=True))


if __name__ == "__main__":
    main()
