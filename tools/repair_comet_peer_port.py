#!/usr/bin/env python3
"""Repair one persisted CometBFT peer endpoint and restart existing nodes."""

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

    def run(self, command: str, *, sudo: bool = False, timeout: int = 60) -> str:
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
    raw = remote.run(f"curl -fsS --max-time 3 http://127.0.0.1:{port}/{path}", timeout=10)
    payload = json.loads(raw)
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RemoteCommandError(f"{remote.host}: invalid CometBFT {path} response")
    return result


def _repair_host(
    host: str,
    *,
    username: str,
    password: str,
    config_path: str,
    container: str,
    old_peer: str,
    new_peer: str,
    backup_suffix: str,
    rpc_port: int,
    timeout: int,
) -> dict[str, Any]:
    remote = RemoteHost(host, username=username, password=password)
    config = shlex.quote(config_path)
    old = shlex.quote(old_peer)
    backup = shlex.quote(f"{config_path}.before-{backup_suffix}")
    occurrences = int(
        remote.run(
            f"grep -o -- {old} {config} | wc -l",
            sudo=True,
        )
        or "0"
    )
    if occurrences != 1:
        raise RemoteCommandError(
            f"{host}: expected one {old_peer!r} occurrence, found {occurrences}"
        )
    try:
        remote.run(f"test ! -e {backup}", sudo=True, timeout=10)
    except RemoteCommandError as error:
        raise RemoteCommandError(f"{host}: config backup already exists") from error

    remote.run(f"cp -- {config} {backup}", sudo=True)
    # The exact peer token is validated above; only its port is changed.
    remote.run(f"sed -i 's#@192.168.88.127:26656#@192.168.88.127:27656#g' {config}", sudo=True)
    updated = remote.run(f"grep -E '^persistent_peers' {config}", sudo=True)
    if new_peer not in updated:
        raise RemoteCommandError(f"{host}: persistent peer replacement was not applied")

    remote.run(f"docker container restart {shlex.quote(container)}", sudo=True, timeout=90)
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
        raise RemoteCommandError(f"{host}: RPC did not recover: {last_error}")
    sync_info = status.get("sync_info") or {}
    node_info = status.get("node_info") or {}
    return {
        "host": host,
        "chain_id": node_info.get("network"),
        "height": sync_info.get("latest_block_height"),
        "catching_up": sync_info.get("catching_up"),
        "peer_count": net_info.get("n_peers"),
        "persistent_peer": new_peer,
        "config_backup": f"{config_path}.before-{backup_suffix}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosts", nargs="+", required=True)
    parser.add_argument("--config-path", default="/home/user/aidn-g5-clean/node/config/config.toml")
    parser.add_argument("--container", default="aidn-g5-comet")
    parser.add_argument("--old-peer", default="@192.168.88.127:26656")
    parser.add_argument("--new-peer", default="@192.168.88.127:27656")
    parser.add_argument("--backup-suffix", required=True)
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
        result = _repair_host(
            host,
            username=args.ssh_user,
            password=password,
            config_path=args.config_path,
            container=args.container,
            old_peer=args.old_peer,
            new_peer=args.new_peer,
            backup_suffix=args.backup_suffix,
            rpc_port=args.rpc_port,
            timeout=args.timeout,
        )
        results.append(result)
        print(json.dumps(result, sort_keys=True))
    print(json.dumps({"status": "ok", "hosts": results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
