#!/usr/bin/env python3
"""Install one public protocol-authority policy on validator ABCI containers.

The tool preserves the existing container configuration and state mount. It
adds only the policy path, recreates the ABCI container with the same image,
and verifies health before accepting each host. Private authority keys are not
needed and must never be placed on validators.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import importlib
import json
import os
import shlex
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy  # noqa: E402

RemoteCommandError = RuntimeError
RemoteHost = Any
_create_command = None
_rollback = None


def _load_rollout_helpers() -> None:
    """Load SSH/Docker helpers only for a real (non-dry-run) rollout."""
    global RemoteCommandError, RemoteHost, _create_command, _rollback
    try:
        module = importlib.import_module("rollout_abci_image")
    except ImportError as error:  # pragma: no cover - operator workstation dependency
        raise SystemExit(
            "paramiko is required for a real rollout; install the operator tooling dependencies"
        ) from error
    RemoteCommandError = module.RemoteCommandError
    RemoteHost = module.RemoteHost
    _create_command = module._create_command
    _rollback = module._rollback


def _canonical_policy(path: Path) -> tuple[dict[str, object], bytes, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("protocol authority policy must be a JSON object")
    policy = ProtocolAuthorityPolicy.from_mapping(value)
    encoded = (json.dumps(policy.as_dict(), indent=2, sort_keys=True) + "\n").encode("utf-8")
    return policy.as_dict(), encoded, hashlib.sha256(encoded).hexdigest()


def _absolute_path(value: str, *, label: str) -> str:
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be an absolute path without '..'")
    return value


def _install_policy(
    remote: RemoteHost,
    *,
    host_path: str,
    policy_bytes: bytes,
    content_sha256: str,
) -> None:
    directory = str(PurePosixPath(host_path).parent)
    encoded = base64.b64encode(policy_bytes).decode("ascii")
    temporary = f"{host_path}.tmp-{os.getpid()}"
    command = (
        f"install -d -m 0750 {shlex.quote(directory)} && "
        f"printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(temporary)} && "
        f"chown root:root {shlex.quote(temporary)} && "
        f"chmod 0644 {shlex.quote(temporary)} && "
        f"test \"$(sha256sum {shlex.quote(temporary)} | cut -d ' ' -f1)\" = {shlex.quote(content_sha256)} && "
        f"mv -f {shlex.quote(temporary)} {shlex.quote(host_path)}"
    )
    try:
        remote.run(command, timeout=30)
    except Exception:
        # A failed atomic install must not leave an incomplete policy file.
        try:
            remote.run(f"rm -f {shlex.quote(temporary)}", timeout=15)
        except Exception:
            pass
        raise


def _policy_digest(remote: RemoteHost, host_path: str) -> str:
    return remote.run(
        f"sha256sum {shlex.quote(host_path)} | cut -d ' ' -f1",
        sudo=False,
        timeout=15,
    )


def _container_with_policy(
    current: dict[str, Any],
    *,
    container: str,
    policy_path: str,
) -> str:
    cloned = json.loads(json.dumps(current))
    environment = [
        value
        for value in cloned["Config"].get("Env") or []
        if not value.startswith("AIDN_PROTOCOL_AUTHORITY_POLICY_PATH=")
    ]
    environment.append(f"AIDN_PROTOCOL_AUTHORITY_POLICY_PATH={policy_path}")
    cloned["Config"]["Env"] = environment
    return _create_command(
        cloned,
        container=container,
        image=cloned["Config"].get("Image") or current.get("Image"),
    )


def _rollout_host(
    host: str,
    *,
    username: str,
    password: str,
    container: str,
    backup: str,
    host_policy_path: str,
    container_policy_path: str,
    policy_bytes: bytes,
    policy_sha256: str,
    policy_hash: str,
    expected_mount: tuple[str, str],
    health_url: str,
    health_timeout: int,
) -> dict[str, object]:
    remote = RemoteHost(host, username=username, password=password)
    try:
        current = remote.inspect(container)
        mounts = {
            (mount.get("Source"), mount.get("Destination"))
            for mount in current.get("Mounts", [])
        }
        if expected_mount not in mounts:
            raise RemoteCommandError(f"{host}: unexpected state mount {sorted(mounts)}")
        if remote.exists(backup):
            raise RemoteCommandError(f"{host}: rollback container already exists: {backup}")

        _install_policy(
            remote,
            host_path=host_policy_path,
            policy_bytes=policy_bytes,
            content_sha256=policy_sha256,
        )
        if _policy_digest(remote, host_policy_path) != policy_sha256:
            raise RemoteCommandError(f"{host}: policy digest mismatch after install")

        create = _container_with_policy(
            current,
            container=container,
            policy_path=container_policy_path,
        )
        remote.run(f"docker container stop --time 60 {shlex.quote(container)}", timeout=90)
        remote.run(f"docker container rename {shlex.quote(container)} {shlex.quote(backup)}", timeout=60)
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
                raise RemoteCommandError(f"{host}: policy container did not become healthy: {last_error}")

            running_env = remote.run(
                f"docker inspect {shlex.quote(container)} --format "
                "'{{range .Config.Env}}{{println .}}{{end}}'"
            )
            expected_env = f"AIDN_PROTOCOL_AUTHORITY_POLICY_PATH={container_policy_path}"
            if expected_env not in running_env.splitlines():
                raise RemoteCommandError(f"{host}: running container does not expose policy path")
            return {
                "host": host,
                "policy_hash": policy_hash,
                "policy_file_sha256": policy_sha256,
                "health": health,
                "backup": backup,
            }
        except Exception:
            _rollback(remote, container=container, backup=backup)
            raise
    finally:
        remote.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosts", nargs="+", required=True)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--container", default="aidn-g5-abci")
    parser.add_argument("--backup-suffix", required=True)
    parser.add_argument(
        "--host-policy-path",
        default="/home/user/aidn-g5-clean/state/protocol-authority.json",
    )
    parser.add_argument("--container-policy-path", default="/state/protocol-authority.json")
    parser.add_argument(
        "--expected-state-mount",
        default="/home/user/aidn-g5-clean/state:/state",
        help="required HOST_SOURCE:CONTAINER_DESTINATION state mount",
    )
    parser.add_argument("--health-url", default="http://127.0.0.1:8000/health")
    parser.add_argument("--health-timeout", type=int, default=120)
    parser.add_argument("--ssh-user", default=os.environ.get("AIDN_SSH_USER", "user"))
    parser.add_argument(
        "--ssh-password-env",
        default="AIDN_SSH_PASSWORD",
        help="environment variable containing SSH and sudo password",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.health_timeout <= 0:
        raise SystemExit("--health-timeout must be positive")
    host_policy_path = _absolute_path(args.host_policy_path, label="--host-policy-path")
    container_policy_path = _absolute_path(args.container_policy_path, label="--container-policy-path")
    host_source, separator, container_destination = args.expected_state_mount.partition(":")
    if not separator:
        raise SystemExit("--expected-state-mount must use HOST_SOURCE:CONTAINER_DESTINATION")

    policy, policy_bytes, policy_sha256 = _canonical_policy(args.policy)
    policy_hash = str(policy["policy_hash"])
    print(
        json.dumps(
            {
                "status": "DRY_RUN" if args.dry_run else "READY",
                "hosts": args.hosts,
                "policy_hash": policy_hash,
                "policy_file_sha256": policy_sha256,
                "host_policy_path": host_policy_path,
                "container_policy_path": container_policy_path,
                "broadcast": False,
            },
            sort_keys=True,
        )
    )
    if args.dry_run:
        return 0

    _load_rollout_helpers()
    password = os.environ.get(args.ssh_password_env) or getpass.getpass("SSH/sudo password: ")
    backup = f"{args.container}-prev-authority-{args.backup_suffix}"
    results = []
    for host in args.hosts:
        results.append(
            _rollout_host(
                host,
                username=args.ssh_user,
                password=password,
                container=args.container,
                backup=backup,
                host_policy_path=host_policy_path,
                container_policy_path=container_policy_path,
                policy_bytes=policy_bytes,
                policy_sha256=policy_sha256,
                policy_hash=policy_hash,
                expected_mount=(host_source, container_destination),
                health_url=args.health_url,
                health_timeout=args.health_timeout,
            )
        )
        print(json.dumps(results[-1], sort_keys=True))
    print(json.dumps({"status": "ok", "hosts": results, "policy_hash": policy_hash}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, RemoteCommandError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        raise SystemExit(2) from error
