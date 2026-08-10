"""Command line entrypoint for running the external Faucet service."""

from __future__ import annotations

import argparse
import importlib
import ipaddress
import json
import os
import sys
from pathlib import Path

import uvicorn

from aidn_faucet.api import build_app
from aidn_faucet.policy import AccumulatingPoolPolicy, FixedDailyPolicy
from aidn_faucet.policy_registry import (
    FaucetPolicyRegistryRoot,
    FaucetPolicyRelease,
    validate_registry_for_manifest,
)
from aidn_faucet.service import FaucetService
from aidn_faucet.store import FaucetStore
from aidn_hypervisor.faucet_treasury import FaucetTreasuryManifest


def _is_loopback_bind_host(host: str) -> bool:
    """Return whether binding to ``host`` keeps the service local-only."""

    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # A hostname may resolve to a LAN address. Require authentication for
        # anything that is not an unambiguous loopback literal.
        return False


def _load_factory(reference: str):
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("submitter factory must use module:attribute")
    factory = getattr(importlib.import_module(module_name), attribute, None)
    if not callable(factory):
        raise ValueError("submitter factory is not callable")
    return factory


def _serve(args: argparse.Namespace) -> int:
    bind_host = "0.0.0.0" if args.lan else args.host
    if not _is_loopback_bind_host(bind_host):
        missing_tokens = [
            name
            for name, value in (
                ("--agent-token/AIDN_FAUCET_AGENT_TOKEN", args.agent_token),
                ("--creator-token/AIDN_FAUCET_CREATOR_TOKEN", args.creator_token),
            )
            if not value
        ]
        if missing_tokens:
            missing = ", ".join(missing_tokens)
            raise ValueError(
                f"non-loopback Faucet bind requires bearer authentication; configure {missing}"
            )
        print(
            "WARNING: Faucet GUI and MCP are exposed over plain HTTP on a non-loopback "
            "interface. Restrict the port to the trusted LAN or use HTTPS through a "
            "reverse proxy.",
            file=sys.stderr,
        )

    manifest = FaucetTreasuryManifest.model_validate(
        json.loads(args.manifest.read_text(encoding="utf-8"))
    )
    from aidn_faucet.service import TreasurySigner

    signer = TreasurySigner.from_file(args.private_key, expected_public_key=manifest.wallet_public_key)
    if (args.policy_registry_root is None) != (args.policy_release is None):
        raise ValueError("--policy-registry-root and --policy-release must be provided together")
    policy_registry_root = None
    policy_release = None
    if args.policy_registry_root is not None:
        policy_registry_root = FaucetPolicyRegistryRoot.model_validate_json(
            args.policy_registry_root.read_text(encoding="utf-8")
        )
        policy_release = FaucetPolicyRelease.model_validate_json(
            args.policy_release.read_text(encoding="utf-8")
        )
        from datetime import UTC, datetime

        policy = validate_registry_for_manifest(
            policy_registry_root,
            policy_release,
            manifest=manifest,
            now=datetime.now(UTC),
        )
    else:
        print(
            "WARNING: running a legacy direct Faucet policy without signed registry provenance",
            file=sys.stderr,
        )
        policy = (
            FixedDailyPolicy(amount_q=args.daily_q)
            if args.policy == "fixed-daily"
            else AccumulatingPoolPolicy(rate_q=args.rate_q, interval_seconds=args.interval_seconds)
        )
    submitter = _load_factory(args.submitter_factory)(args)
    service = FaucetService(
        manifest=manifest,
        signer=signer,
        policy=policy,
        store=FaucetStore(args.state),
        submitter=submitter,
        agent_token=args.agent_token,
        creator_token=args.creator_token,
        policy_registry_root=policy_registry_root,
        policy_release=policy_release,
    )
    print(f"Faucet GUI:  http://{bind_host}:{args.port}/", file=sys.stderr)
    print(f"Faucet MCP:  http://{bind_host}:{args.port}/mcp", file=sys.stderr)
    uvicorn.run(build_app(service), host=bind_host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aidn-faucet")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="run the external Faucet HTTP service")
    serve.add_argument("--manifest", type=Path, required=True)
    serve.add_argument("--private-key", type=Path, required=True)
    serve.add_argument("--state", type=Path, required=True)
    serve.add_argument(
        "--submitter-factory",
        default="aidn_faucet.deployment:build_cometbft_submitter",
        help="module:attribute deployment adapter factory",
    )
    serve.add_argument(
        "--finality-config",
        type=Path,
        help="operator-approved multi-RPC CometBFT finality configuration",
    )
    serve.add_argument("--policy", choices=("fixed-daily", "accumulating-pool"), default="fixed-daily")
    serve.add_argument("--daily-q", type=int, default=50)
    serve.add_argument("--rate-q", type=int, default=5)
    serve.add_argument("--interval-seconds", type=int, default=60)
    serve.add_argument(
        "--policy-registry-root",
        type=Path,
        help="creator-signed immutable policy registry root required by the Treasury manifest",
    )
    serve.add_argument(
        "--policy-release",
        type=Path,
        help="creator-signed active policy release bound to the registry root",
    )
    serve.add_argument(
        "--agent-token",
        default=os.environ.get("AIDN_FAUCET_AGENT_TOKEN"),
    )
    serve.add_argument("--creator-token", default=os.environ.get("AIDN_FAUCET_CREATOR_TOKEN"))
    bind_group = serve.add_mutually_exclusive_group()
    bind_group.add_argument(
        "--host",
        default=os.environ.get("AIDN_FAUCET_HOST", "127.0.0.1"),
        help="bind address; use a specific LAN IP to avoid exposing other interfaces",
    )
    bind_group.add_argument(
        "--lan",
        action="store_true",
        help="bind GUI and MCP to 0.0.0.0; requires both bearer tokens",
    )
    serve.add_argument("--port", type=int, default=8790)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    raise ValueError(f"unsupported command: {args.command}")
