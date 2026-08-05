#!/usr/bin/env python3
"""Start existing remote CometBFT containers and verify their RPC state."""

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

    def run(self, command: str, *, sudo: bool = False, timeout: int = 30) -> str:
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


def _rpc(remote: RemoteHost, *, port: int, path: str) -> dict[str, Any]:
    raw = remote.run(
        f"curl -fsS --max-time 3 http://127.0.0.1:{port}/{path}",
        timeout=10,
    )
    payload = json.loads(raw)
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RemoteCommandError(f"{remote.host}: invalid CometBFT {path} response")
    return result


def _check_host(
    host: str,
    *,
    username: str,
    password: str,
    container: str,
    rpc_port: int,
    timeout: int,
) -> dict[str, Any]:
    remote = RemoteHost(host, username=username, password=password)
    try:
        remote.run(f"docker container start {shlex.quote(container)}", sudo=True, timeout=60)
        deadline = time.monotonic() + timeout
        status: dict[str, Any] | None = None
        net_info: dict[str, Any] | None = None
        last_error = ""
        while time.monotonic() < deadline:
            try:
                status = _rpc(remote, port=rpc_port, path="status")
                net_info = _rpc(remote, port=rpc_port, path="net_info")
                break
            except (RemoteCommandError, json.JSONDecodeError) as error:
                last_error = str(error)
                time.sleep(2)
        if status is None or net_info is None:
            raise RemoteCommandError(f"{host}: CometBFT RPC did not recover: {last_error}")
        sync_info = status.get("sync_info") or {}
        node_info = status.get("node_info") or {}
        return {
            "host": host,
            "chain_id": node_info.get("network"),
            "height": sync_info.get("latest_block_height"),
            "catching_up": sync_info.get("catching_up"),
            "peer_count": net_info.get("n_peers"),
            "listening": net_info.get("listening"),
        }
    finally:
        remote.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosts", nargs="+", required=True)
    parser.add_argument("--container", default="aidn-g5-comet")
    parser.add_argument("--rpc-port", type=int, default=26657)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--ssh-user", default=os.environ.get("AIDN_SSH_USER", "user"))
    parser.add_argument(
        "--ssh-password-env",
        default="AIDN_SSH_PASSWORD",
        help="Environment variable containing the SSH and sudo password",
    )
    args = parser.parse_args()
    password = os.environ.get(args.ssh_password_env) or getpass.getpass("SSH/sudo password: ")

    results = []
    for host in args.hosts:
        result = _check_host(
            host,
            username=args.ssh_user,
            password=password,
            container=args.container,
            rpc_port=args.rpc_port,
            timeout=args.timeout,
        )
        results.append(result)
        print(json.dumps(result, sort_keys=True))
    print(json.dumps({"status": "ok", "hosts": results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
