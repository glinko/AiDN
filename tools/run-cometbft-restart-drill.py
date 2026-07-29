"""Create, verify and activate a validator backup in a fresh target root."""

from __future__ import annotations

import argparse
from pathlib import Path

from aidn_hypervisor.consensus.backup import create_validator_backup, restore_validator_backup


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--restore-root", required=True)
    args = parser.parse_args()
    source = Path(args.source_root)
    manifest = create_validator_backup(
        hypervisor_state_path=source / "hypervisor.json",
        abci_state_path=source / "abci",
        archive_path=args.archive,
    )
    restored = restore_validator_backup(archive_path=args.archive, target_root=args.restore_root)
    if restored != manifest:
        raise SystemExit("restored manifest differs from backup manifest")
    print(f"restored validator height={manifest.block_height} app_hash={manifest.app_hash}")


if __name__ == "__main__":
    main()
