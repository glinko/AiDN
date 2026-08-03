"""Lifecycle supervisor for a Docker Plugin Host with declared egress."""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from aidn_hypervisor.providers.models import PluginEgressRule, plugin_egress_policy_hash


class DockerSupervisorError(RuntimeError):
    """The Docker egress boundary could not be created or cleaned up."""


def _run(docker: str, arguments: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        [docker, *arguments],
        check=True,
        capture_output=capture_output,
        text=True,
    )


def _remove_container(docker: str, name: str) -> None:
    subprocess.run(
        [docker, "rm", "--force", "--volumes", name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _remove_network(docker: str, name: str) -> None:
    subprocess.run(
        [docker, "network", "rm", name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_proxy(docker: str, name: str) -> None:
    for _ in range(100):
        result = subprocess.run(
            [docker, "inspect", "--format", "{{.State.Health.Status}}", name],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip() == "healthy":
            return
        if result.returncode == 0 and result.stdout.strip() == "unhealthy":
            raise DockerSupervisorError("declared-egress proxy failed its health check")
        time.sleep(0.1)
    raise DockerSupervisorError("timed out waiting for declared-egress proxy")


def _validate_egress_spec(egress: dict) -> list[dict]:
    raw_rules = egress.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise DockerSupervisorError("declared-egress supervisor requires exact rules")
    try:
        rules = [PluginEgressRule.model_validate(rule) for rule in raw_rules]
    except (TypeError, ValueError) as error:
        raise DockerSupervisorError("declared-egress supervisor received invalid rules") from error
    if plugin_egress_policy_hash(rules) != egress.get("policy_hash"):
        raise DockerSupervisorError("declared-egress policy hash mismatch")
    return [rule.model_dump(mode="json") for rule in rules]


def _plugin_command(spec: dict, network_name: str) -> list[str]:
    plugin = spec["plugin"]
    command = [
        spec["docker"],
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
        network_name,
        "--user",
        "65534:65534",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--mount",
        f"type=bind,src={plugin['package_root']},dst=/opt/aidn/plugin,readonly",
        "--mount",
        f"type=bind,src={plugin['secret_file']},dst={plugin['secret_path']},readonly",
    ]
    if plugin.get("data_root") is not None:
        command.extend(
            (
                "--mount",
                f"type=bind,src={plugin['data_root']},dst={plugin['data_path']}",
            )
        )
    for name in plugin["identity_environment"]:
        command.extend(("--env", name))
    for name, value in plugin["proxy_environment"].items():
        command.extend(("--env", f"{name}={value}"))
    command.extend((plugin["image"], "python", plugin["container_entrypoint"], *plugin["arguments"]))
    return command


def run_supervised(spec: dict) -> int:
    docker = spec["docker"]
    egress = spec["egress"]
    egress["rules"] = _validate_egress_spec(egress)
    network_name = egress["network_name"]
    proxy_name = egress["proxy_name"]
    plugin_process: subprocess.Popen | None = None

    def _forward_signal(signum, _frame) -> None:
        if plugin_process is not None and plugin_process.poll() is None:
            plugin_process.send_signal(signum)

    old_sigterm = signal.signal(signal.SIGTERM, _forward_signal)
    old_sigint = signal.signal(signal.SIGINT, _forward_signal)
    network_created = False
    try:
        with tempfile.TemporaryDirectory(prefix="aidn-egress-policy-") as directory:
            policy_path = Path(directory) / "policy.json"
            policy_path.write_text(
                json.dumps(egress["rules"], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            _run(docker, ["network", "create", "--internal", "--attachable", network_name])
            network_created = True
            try:
                proxy_script = Path(egress["proxy_script"]).resolve()
                proxy_command = [
                    docker,
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    proxy_name,
                    "--network",
                    "bridge",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    "64",
                    "--memory",
                    "256m",
                    "--user",
                    "65534:65534",
                    "--health-cmd",
                    "python -c \"import socket; s=socket.create_connection(('127.0.0.1',3128),1); s.close()\"",
                    "--health-interval",
                    "100ms",
                    "--health-timeout",
                    "1s",
                    "--health-retries",
                    "30",
                    "--mount",
                    f"type=bind,src={proxy_script},dst=/opt/aidn/egress_proxy.py,readonly",
                    "--mount",
                    f"type=bind,src={policy_path},dst=/run/aidn-egress-policy.json,readonly",
                    egress["proxy_image"],
                    "python",
                    "/opt/aidn/egress_proxy.py",
                    "--policy",
                    "/run/aidn-egress-policy.json",
                    "--listen-host",
                    "0.0.0.0",
                    "--listen-port",
                    "3128",
                ]
                subprocess.run(proxy_command, check=True)
                _run(docker, ["network", "connect", network_name, proxy_name])
                _wait_for_proxy(docker, proxy_name)
                plugin_process = subprocess.Popen(_plugin_command(spec, network_name))
                return plugin_process.wait()
            finally:
                _remove_container(docker, proxy_name)
                if network_created:
                    _remove_network(docker, network_name)
    finally:
        signal.signal(signal.SIGTERM, old_sigterm)
        signal.signal(signal.SIGINT, old_sigint)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-json", required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec_json)
    if not isinstance(spec, dict):
        raise SystemExit("Docker Plugin Host supervisor spec must be an object")
    raise SystemExit(run_supervised(spec))


if __name__ == "__main__":
    main()
