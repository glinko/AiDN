#!/usr/bin/env python3
"""Verify an already configured production Registry replication link.

The command uses local operator configuration and secret handles. It never
generates identities or exports private material, unlike the disposable
cross-host acceptance harness.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aidn_hypervisor.registry.acceptance import (
    RegistryReplicationAcceptanceError,
    verify_registry_replication_acceptance,
)
from aidn_hypervisor.registry.deployment import (
    build_registry_replication_runtime,
    load_file_secret_manager_from_environment,
    load_registry_replication_deployment_config,
)
from aidn_hypervisor.registry_service import RegistryService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--registry-snapshot", required=True, type=Path)
    parser.add_argument("--peer-id", action="append", dest="peer_ids")
    parser.add_argument("--required-object-id", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()

    try:
        if args.timeout <= 0:
            raise ValueError("--timeout must be positive")
        config = load_registry_replication_deployment_config(args.config)
        secret_manager = load_file_secret_manager_from_environment()
        if secret_manager is None:
            raise ValueError("Registry replication secret manager environment is required")
        registry = RegistryService(snapshot_path=args.registry_snapshot)
        configured_peer_ids = {peer.peer_id for peer in config.outbound_peers}
        peer_ids = args.peer_ids or sorted(configured_peer_ids)
        unknown_peer_ids = sorted(set(peer_ids) - configured_peer_ids)
        if unknown_peer_ids:
            raise ValueError(
                "--peer-id is not an outbound peer in the deployment configuration: "
                + ", ".join(unknown_peer_ids)
            )
        for peer_id in peer_ids:
            configured = next(
                (peer for peer in registry.list_replication_peers() if peer["peer_id"] == peer_id),
                None,
            )
            if configured is None or not configured["enabled"]:
                raise ValueError(f"Registry replication peer is not locally approved: {peer_id}")
        runtime = build_registry_replication_runtime(
            config=config,
            registry_service=registry,
            secret_manager=secret_manager,
        )
        try:
            runtime.start()
            result = verify_registry_replication_acceptance(
                runtime=runtime,
                expected_peer_ids=peer_ids,
                required_object_ids=args.required_object_id,
                timeout_seconds=args.timeout,
            )
        finally:
            runtime.stop()
    except (OSError, ValueError, RegistryReplicationAcceptanceError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
