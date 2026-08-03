from __future__ import annotations

import subprocess

import pytest

from aidn_hypervisor.plugins import docker_supervisor
from aidn_hypervisor.providers.models import PluginEgressRule, plugin_egress_policy_hash


def _spec(tmp_path) -> dict:
    proxy_script = tmp_path / "egress_proxy.py"
    proxy_script.write_text("# test proxy", encoding="utf-8")
    rules = [PluginEgressRule(host="example.com", port=80)]
    return {
        "docker": "docker",
        "egress": {
            "network_name": "aidn-egress-test",
            "proxy_name": "aidn-egress-proxy-test",
            "proxy_image": "python:3.11-slim",
            "proxy_script": str(proxy_script),
            "rules": [rule.model_dump(mode="json") for rule in rules],
            "policy_hash": plugin_egress_policy_hash(rules),
        },
        "plugin": {
            "image": "python:3.11-slim",
            "package_root": str(tmp_path / "package"),
            "secret_file": str(tmp_path / "secret"),
            "secret_path": "/run/secret",
            "data_root": None,
            "data_path": "/var/lib/aidn/plugin-data",
            "container_entrypoint": "/opt/aidn/plugin/host.py",
            "arguments": [],
            "identity_environment": [],
            "proxy_environment": {},
        },
    }


def test_supervisor_cleans_proxy_and_network_when_network_connect_fails(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []

    def fake_run(command, check=False, **_kwargs):
        calls.append(list(command))
        if command[1:3] == ["network", "connect"]:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(docker_supervisor.subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        docker_supervisor.run_supervised(_spec(tmp_path))

    assert any(command[1:4] == ["rm", "--force", "--volumes"] for command in calls)
    assert any(command[1:3] == ["network", "rm"] for command in calls)


def test_supervisor_rejects_egress_policy_hash_mismatch(monkeypatch, tmp_path) -> None:
    def fail_if_docker_runs(*_args, **_kwargs):
        raise AssertionError("Docker must not start for an invalid policy binding")

    monkeypatch.setattr(docker_supervisor, "_run", fail_if_docker_runs)
    spec = _spec(tmp_path)
    spec["egress"]["policy_hash"] = "sha256:" + "0" * 64

    with pytest.raises(docker_supervisor.DockerSupervisorError, match="policy hash mismatch"):
        docker_supervisor.run_supervised(spec)
