#!/usr/bin/env python3
"""Run a real Docker acceptance check for declared Plugin Host egress."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from aidn_hypervisor.plugins.container import DockerPluginHostLauncher
from aidn_hypervisor.providers.models import PluginEgressRule, PluginHostEntrypoint, PluginSandboxPolicy

_HOST_CODE = r'''import json, os, socket, urllib.error, urllib.request

proxy = os.environ.get("HTTP_PROXY", "")
def fetch(url):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    try:
        with opener.open(url, timeout=8) as response:
            return 200 <= response.status < 400
    except Exception:
        return False

try:
    socket.create_connection(("1.1.1.1", 443), timeout=2)
    direct_network_blocked = False
except OSError:
    direct_network_blocked = True

print(json.dumps({
    "allowed_request_succeeded": fetch("http://example.com/"),
    "denied_request_blocked": not fetch("http://example.org/"),
    "direct_network_blocked": direct_network_blocked,
    "proxy_configured": proxy.startswith("http://aidn-egress-proxy-"),
}, sort_keys=True))
'''


def main() -> None:
    launcher = DockerPluginHostLauncher()
    if not launcher.is_available():
        raise RuntimeError("Docker is required for declared-egress acceptance")
    with (
        tempfile.TemporaryDirectory(prefix="aidn-plugin-egress-package-") as package_directory,
        tempfile.TemporaryDirectory(prefix="aidn-plugin-egress-secret-") as secret_directory,
    ):
        package_root = Path(package_directory)
        host = package_root / "host.py"
        host.write_text(_HOST_CODE, encoding="utf-8")
        os.chmod(package_root, 0o755)
        os.chmod(host, 0o444)
        secret_file = Path(secret_directory) / "activation-secret"
        secret_file.write_text("616363657074616e63652d736563726574", encoding="ascii")
        os.chmod(secret_file, 0o444)
        spec = launcher.build_launch_spec(
            package_root=package_root,
            entrypoint=PluginHostEntrypoint(entrypoint_path="host.py"),
            sandbox_policy=PluginSandboxPolicy(
                execution_mode="SANDBOX_REQUIRED",
                filesystem_scope="NONE",
                network_scope="DECLARED_EGRESS",
                egress_rules=[PluginEgressRule(host="example.com", port=80)],
                secret_scope="DECLARED_HANDLES_ONLY",
            ),
            activation_secret_file=secret_file,
        )
        environment = {
            **os.environ,
            "AIDN_PLUGIN_HOST_INSTALLED_PLUGIN_ID": "egress-acceptance-installation",
            "AIDN_PLUGIN_HOST_PLUGIN_ID": "aidn.acceptance.plugin",
            "AIDN_PLUGIN_HOST_INSTALLATION_GENERATION": "1",
            "AIDN_PLUGIN_HOST_ACTIVATION_CREDENTIAL_KEY_ID": "sha256:acceptance",
        }
        completed = subprocess.run(
            spec["command"],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
        )
    result = None
    for line in reversed(completed.stdout.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and "allowed_request_succeeded" in candidate:
            result = candidate
            break
    expected = {
        "allowed_request_succeeded": True,
        "denied_request_blocked": True,
        "direct_network_blocked": True,
        "proxy_configured": True,
    }
    if result != expected:
        raise RuntimeError(
            "declared-egress boundary failed: "
            + json.dumps({"expected": expected, "actual": result}, sort_keys=True)
        )
    print(json.dumps({"status": "ok", "result": result}, sort_keys=True))


if __name__ == "__main__":
    main()
