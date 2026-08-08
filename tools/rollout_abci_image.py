#!/usr/bin/env python3
"""Roll out one immutable ABCI image while retaining a rollback container."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shlex
import sys
import time
from typing import Any

try:
    import paramiko
except ImportError as error:  # pragma: no cover - operator workstation dependency
    raise SystemExit("paramiko is required; install it on the operator workstation") from error


class RemoteCommandError(RuntimeError):
    """A remote command failed."""


class RemoteHost:
    def __init__(self, host: str, *, username: str, password: str) -> None:
        self.host = host
        self.password = password
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
            host,
            username=username,
            password=password,
            timeout=20,
            banner_timeout=20,
            auth_timeout=20,
        )

    def close(self) -> None:
        self.client.close()

    def run(self, command: str, *, sudo: bool = True, timeout: int = 120) -> str:
        wrapped = f"sudo -S -p '' {command}" if sudo else command
        stdin, stdout, stderr = self.client.exec_command(
            wrapped,
            get_pty=False,
            timeout=timeout,
        )
        if sudo:
            stdin.write(self.password + "\n")
            stdin.flush()
        output = stdout.read().decode("utf-8", "replace")
        error = stderr.read().decode("utf-8", "replace")
        exit_code = stdout.channel.recv_exit_status()
        if exit_code:
            raise RemoteCommandError(
                f"{self.host}: command exited {exit_code}: {error.strip()} {output.strip()}"
            )
        return output.strip()

    def inspect(self, name: str) -> dict[str, Any]:
        return json.loads(self.run(f"docker inspect {shlex.quote(name)}"))[0]

    def exists(self, name: str) -> bool:
        try:
            self.inspect(name)
        except (RemoteCommandError, IndexError, json.JSONDecodeError):
            return False
        return True


def _parse_expected_mounts(values: list[str]) -> dict[str, tuple[str, str]]:
    mounts: dict[str, tuple[str, str]] = {}
    for value in values:
        host, separator, mount = value.partition("=")
        source, separator2, destination = mount.rpartition(":")
        if not separator or not separator2 or not host or not source or not destination:
            raise ValueError(
                "expected mounts must use HOST=/absolute/source:/absolute/destination"
            )
        mounts[host] = (source, destination)
    return mounts


def _create_command(
    item: dict[str, Any],
    *,
    container: str,
    image: str,
) -> str:
    config = item["Config"]
    host_config = item["HostConfig"]
    arguments = ["docker", "container", "create", "--name", container]

    network = host_config.get("NetworkMode")
    if network:
        arguments.extend(("--network", network))

    restart = host_config.get("RestartPolicy") or {}
    restart_name = restart.get("Name")
    if restart_name:
        if restart_name == "on-failure" and restart.get("MaximumRetryCount"):
            restart_name = f"on-failure:{restart['MaximumRetryCount']}"
        arguments.extend(("--restart", restart_name))
    else:
        arguments.extend(("--restart", "unless-stopped"))

    if config.get("WorkingDir"):
        arguments.extend(("--workdir", config["WorkingDir"]))
    if config.get("User"):
        arguments.extend(("--user", config["User"]))
    if host_config.get("ReadonlyRootfs"):
        arguments.append("--read-only")
    if host_config.get("Privileged"):
        arguments.append("--privileged")
    if host_config.get("Init"):
        arguments.append("--init")
    if host_config.get("ShmSize"):
        arguments.extend(("--shm-size", str(host_config["ShmSize"])))

    for option, key in (("--ipc", "IpcMode"), ("--pid", "PidMode"), ("--uts", "UTSMode")):
        value = host_config.get(key)
        if value:
            arguments.extend((option, value))
    userns_mode = host_config.get("UsernsMode")
    if userns_mode:
        arguments.extend(("--userns", userns_mode))

    for capability in host_config.get("CapAdd") or []:
        arguments.extend(("--cap-add", capability))
    for capability in host_config.get("CapDrop") or []:
        arguments.extend(("--cap-drop", capability))
    for device in host_config.get("Devices") or []:
        path = device.get("PathOnHost") or device.get("PathInContainer")
        if path:
            arguments.extend(("--device", path))

    for label, value in (config.get("Labels") or {}).items():
        arguments.extend(("--label", f"{label}={value}"))
    for environment in config.get("Env") or []:
        arguments.extend(("--env", environment))
    for mount in item.get("Mounts") or []:
        mode = "rw" if mount.get("RW", True) else "ro"
        if mount.get("Type") == "bind":
            arguments.extend(
                ("--volume", f"{mount['Source']}:{mount['Destination']}:{mode}")
            )
        else:
            arguments.extend(("--volume", f"{mount['Name']}:{mount['Destination']}:{mode}"))

    entrypoint = config.get("Entrypoint")
    if entrypoint:
        arguments.extend(("--entrypoint", entrypoint[0]))
    if config.get("Tty"):
        arguments.append("--tty")
    if config.get("OpenStdin"):
        arguments.append("--interactive")

    arguments.append(image)
    arguments.extend(config.get("Cmd") or [])
    return shlex.join(arguments)


def _rollback(remote: RemoteHost, *, container: str, backup: str) -> None:
    if remote.exists(container):
        remote.run(f"docker container rm --force {shlex.quote(container)}", timeout=60)
    remote.run(
        f"docker container rename {shlex.quote(backup)} {shlex.quote(container)}",
        timeout=60,
    )
    remote.run(f"docker container start {shlex.quote(container)}", timeout=60)


def _rollout_host(
    host: str,
    *,
    username: str,
    password: str,
    container: str,
    image: str,
    expected_image_id: str,
    backup: str,
    expected_mount: tuple[str, str] | None,
    health_url: str,
    health_timeout: int,
    consensus_container: str | None,
    consensus_service: str | None,
    consensus_rpc_url: str,
) -> dict[str, Any]:
    remote = RemoteHost(host, username=username, password=password)
    try:
        current = remote.inspect(container)
        mounts = {
            (mount.get("Source"), mount.get("Destination"))
            for mount in current.get("Mounts", [])
        }
        if expected_mount is not None and expected_mount not in mounts:
            raise RemoteCommandError(f"{host}: unexpected state mount {sorted(mounts)}")
        if remote.exists(backup):
            raise RemoteCommandError(f"{host}: rollback container already exists: {backup}")

        create = _create_command(current, container=container, image=image)
        remote.run(f"docker container stop --time 60 {shlex.quote(container)}", timeout=90)
        remote.run(
            f"docker container rename {shlex.quote(container)} {shlex.quote(backup)}",
            timeout=60,
        )
        try:
            remote.run(create, timeout=120)
            remote.run(f"docker container start {shlex.quote(container)}", timeout=60)
            deadline = time.monotonic() + health_timeout
            last_error = ""
            health = ""
            while time.monotonic() < deadline:
                try:
                    health = remote.run(
                        f"curl -fsS --max-time 3 {shlex.quote(health_url)}",
                        sudo=False,
                        timeout=10,
                    )
                    break
                except RemoteCommandError as error:
                    last_error = str(error)
                    time.sleep(2)
            else:
                raise RemoteCommandError(
                    f"{host}: new container did not become healthy: {last_error}"
                )
            running_image = remote.run(
                f"docker inspect {shlex.quote(container)} --format '{{{{.Image}}}}'"
            )
            if not running_image.startswith(expected_image_id):
                raise RemoteCommandError(
                    f"{host}: unexpected running image {running_image}; "
                    f"expected {expected_image_id}"
                )
            consensus_runtime = None
            if consensus_service is not None:
                remote.run(
                    "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user restart "
                    + shlex.quote(consensus_service),
                    sudo=False,
                    timeout=90,
                )
                consensus_runtime = f"service:{consensus_service}"
            elif consensus_container is not None and remote.exists(consensus_container):
                remote.run(
                    "docker update --restart unless-stopped "
                    + shlex.quote(consensus_container),
                    timeout=60,
                )
                remote.run(
                    "docker container start " + shlex.quote(consensus_container),
                    timeout=60,
                )
                consensus_runtime = f"container:{consensus_container}"
            if consensus_runtime is not None:
                deadline = time.monotonic() + health_timeout
                while time.monotonic() < deadline:
                    try:
                        remote.run(
                            f"curl -fsS --max-time 3 {shlex.quote(consensus_rpc_url)}",
                            sudo=False,
                            timeout=10,
                        )
                        break
                    except RemoteCommandError:
                        time.sleep(2)
                else:
                    raise RemoteCommandError(
                        f"{host}: consensus RPC did not recover: {consensus_rpc_url}"
                    )
            return {
                "host": host,
                "health": health,
                "image": running_image,
                "backup": backup,
                "consensus_runtime": consensus_runtime,
            }
        except Exception:
            _rollback(remote, container=container, backup=backup)
            raise
    finally:
        remote.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosts", nargs="+", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--expected-mount", action="append", default=[])
    parser.add_argument("--container", default="aidn-g5-abci")
    parser.add_argument("--backup-suffix", required=True)
    parser.add_argument("--health-url", default="http://127.0.0.1:8000/health")
    parser.add_argument("--health-timeout", type=int, default=120)
    parser.add_argument("--consensus-container", default="aidn-g5-comet")
    parser.add_argument(
        "--consensus-service",
        action="append",
        default=[],
        metavar="HOST=SERVICE",
    )
    parser.add_argument(
        "--consensus-rpc-url",
        action="append",
        default=[],
        metavar="HOST=URL",
    )
    parser.add_argument("--ssh-user", default=os.environ.get("AIDN_SSH_USER", "user"))
    parser.add_argument(
        "--ssh-password-env",
        default="AIDN_SSH_PASSWORD",
        help="Environment variable containing the SSH and sudo password",
    )
    args = parser.parse_args()
    password = os.environ.get(args.ssh_password_env) or getpass.getpass("SSH/sudo password: ")
    expected_mounts = _parse_expected_mounts(args.expected_mount)
    consensus_services = dict(value.split("=", 1) for value in args.consensus_service)
    consensus_rpc_urls = dict(value.split("=", 1) for value in args.consensus_rpc_url)
    backup = f"{args.container}-prev-{args.backup_suffix}"

    results = []
    for host in args.hosts:
        result = _rollout_host(
            host,
            username=args.ssh_user,
            password=password,
            container=args.container,
            image=args.image,
            expected_image_id=args.expected_image_id,
            backup=backup,
            expected_mount=expected_mounts.get(host),
            health_url=args.health_url,
            health_timeout=args.health_timeout,
            consensus_container=args.consensus_container or None,
            consensus_service=consensus_services.get(host),
            consensus_rpc_url=consensus_rpc_urls.get(
                host, "http://127.0.0.1:26657/status"
            ),
        )
        results.append(result)
        print(json.dumps(result, sort_keys=True))
    print(json.dumps({"status": "ok", "hosts": results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
