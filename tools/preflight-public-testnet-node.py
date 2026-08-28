#!/usr/bin/env python3
"""Perform read-only admission checks before installing a public Testnet node.

The caller must explicitly confirm the cloud/security-group P2P rule because a
guest cannot inspect that boundary reliably.  The tool makes no host changes.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

from aidn_hypervisor.network_profile import load_network_profile
from aidn_hypervisor.public_node_preflight import (
    PublicNodeHostObservation,
    evaluate_public_node_preflight,
)


def _os_release() -> tuple[str, str]:
    values: dict[str, str] = {}
    try:
        for raw in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            key, separator, value = raw.partition("=")
            if separator:
                values[key] = value.strip().strip('"')
    except OSError:
        return "unknown", "0"
    return values.get("ID", "unknown"), values.get("VERSION_ID", "0")


def _memory_bytes() -> int:
    try:
        for raw in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if raw.startswith("MemTotal:"):
                return int(raw.split()[1]) * 1024
    except (OSError, IndexError, ValueError):
        pass
    return 0


def _time_synchronized() -> bool:
    try:
        completed = subprocess.run(
            ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and completed.stdout.strip().lower() == "yes"


def _port_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, help="verified Network Profile; supplies the P2P port")
    parser.add_argument("--p2p-port", type=int, default=26656)
    parser.add_argument("--public-ipv4", required=True)
    parser.add_argument("--external-p2p-firewall-confirmed", action="store_true")
    parser.add_argument("--api-exposure", choices=("loopback", "public_https"), default="loopback")
    parser.add_argument("--public-dns-name")
    parser.add_argument("--tls-termination")
    parser.add_argument("--data-path", type=Path, default=Path("/var/lib/aidn"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        p2p_port = args.p2p_port
        if args.profile is not None:
            profile = load_network_profile(args.profile)
            p2p_port = profile.network.cometbft.p2p_port
        os_id, version = _os_release()
        disk = shutil.disk_usage(args.data_path if args.data_path.exists() else args.data_path.parent)
        observation = PublicNodeHostObservation(
            os_id=os_id,
            os_version_id=version,
            cpu_cores=os.cpu_count() or 0,
            memory_bytes=_memory_bytes(),
            free_disk_bytes=disk.free,
            p2p_port=p2p_port,
            p2p_port_available=_port_available(p2p_port),
            time_synchronized=_time_synchronized(),
            public_ipv4=args.public_ipv4,
            external_p2p_firewall_confirmed=args.external_p2p_firewall_confirmed,
            api_exposure=args.api_exposure,
            public_dns_name=args.public_dns_name,
            tls_termination=args.tls_termination,
        )
        report = evaluate_public_node_preflight(observation).model_dump(mode="json")
    except (OSError, ValueError) as error:
        report = {"schema_version": "aidn.public-node-preflight.v1", "status": "FAIL", "error": str(error)}
    encoded = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
