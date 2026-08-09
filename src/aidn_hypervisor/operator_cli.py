"""Host-local commands for an AiDN Hypervisor operator."""

from __future__ import annotations

import argparse
import base64
from pathlib import Path

from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.secrets import FileSecretManager, SecretManagerError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate one local AiDN Hypervisor")
    commands = parser.add_subparsers(dest="command", required=True)
    pair = commands.add_parser("pair", help="create a one-time dashboard pairing code")
    pair.add_argument("--secret-manager-path", required=True)
    pair.add_argument("--master-key-file", required=True)
    pair.add_argument("--dashboard-url", required=True)
    pair.add_argument("--ttl-seconds", type=int, default=600)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute a local operator command without persisting secret values."""
    args = _build_parser().parse_args(argv)
    if args.command != "pair":
        return 2
    if args.ttl_seconds <= 0:
        raise SystemExit("--ttl-seconds must be positive")
    try:
        encoded_key = Path(args.master_key_file).read_text(encoding="utf-8").strip()
        master_key = base64.b64decode(encoded_key, validate=True)
        manager = FileSecretManager(path=Path(args.secret_manager_path), master_key=master_key)
        pairing = McpCredentialStore(secret_manager=manager).create_pairing_code(
            ttl_seconds=args.ttl_seconds
        )
    except (OSError, ValueError, SecretManagerError) as exc:
        raise SystemExit(f"Unable to create dashboard pairing code: {exc}") from exc

    print("Dashboard pairing code created.")
    print(f"Open: {args.dashboard_url}")
    print(f"Expires: {pairing.expires_at}")
    print(f"Code: {pairing.code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
