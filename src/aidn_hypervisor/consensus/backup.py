"""Verified backup and restore for one validator's durable application state."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.state_store import ABCIStateStore, ABCIStateStoreError
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.persistence import FileStateStore


class ValidatorBackupError(RuntimeError):
    """The backup or its paired Hypervisor/ABCI state is not trustworthy."""


@dataclass(frozen=True)
class ValidatorBackupManifest:
    app_hash: str
    block_height: int
    files: dict[str, str]


def create_validator_backup(
    *,
    hypervisor_state_path: Path | str,
    abci_state_path: Path | str,
    archive_path: Path | str,
) -> ValidatorBackupManifest:
    """Create a hash-verified archive only from a mutually consistent state pair."""
    hypervisor_path = Path(hypervisor_state_path)
    abci_path = Path(abci_state_path)
    archive = Path(archive_path)
    snapshot = _validate_pair(hypervisor_path, abci_path)
    if not hypervisor_path.is_file():
        raise ValidatorBackupError("Hypervisor state file does not exist")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=archive.parent, prefix="aidn-backup-") as temporary:
        root = Path(temporary)
        shutil.copy2(hypervisor_path, root / "hypervisor.json")
        shutil.copytree(abci_path, root / "abci")
        files = _file_hashes(root)
        manifest = ValidatorBackupManifest(
            app_hash=str(snapshot["app_hash"]),
            block_height=int(snapshot["last_block_height"]),
            files=files,
        )
        (root / "manifest.json").write_text(
            json.dumps(manifest.__dict__, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary_archive = archive.with_suffix(f"{archive.suffix}.tmp")
        with zipfile.ZipFile(temporary_archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for file_path in sorted(root.rglob("*")):
                if file_path.is_file():
                    bundle.write(file_path, file_path.relative_to(root).as_posix())
        os.replace(temporary_archive, archive)
    return manifest


def restore_validator_backup(*, archive_path: Path | str, target_root: Path | str) -> ValidatorBackupManifest:
    """Verify an archive in staging, then atomically activate an empty target root."""
    archive = Path(archive_path)
    target = Path(target_root)
    if target.exists() and any(target.iterdir()):
        raise ValidatorBackupError("restore target must be empty")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix="aidn-restore-") as temporary:
        staging = Path(temporary) / "state"
        _safe_extract(archive, staging)
        manifest = _read_and_verify_manifest(staging)
        snapshot = _validate_pair(staging / "hypervisor.json", staging / "abci")
        if (
            str(snapshot["app_hash"]) != manifest.app_hash
            or int(snapshot["last_block_height"]) != manifest.block_height
        ):
            raise ValidatorBackupError("backup manifest does not bind the ABCI snapshot")
        if target.exists():
            target.rmdir()
        os.replace(staging, target)
    return manifest


def _validate_pair(hypervisor_path: Path, abci_path: Path) -> dict:
    try:
        hypervisor = FileStateStore(hypervisor_path).load()
        snapshot = ABCIStateStore(abci_path).load_current()
    except (OSError, ValueError, ABCIStateStoreError) as error:
        raise ValidatorBackupError(f"could not load validator state: {error}") from error
    if snapshot is None:
        raise ValidatorBackupError("ABCI state has no current snapshot")
    ledger = LedgerOperationService()
    ledger.restore(
        operations=[item.model_dump(mode="json") for item in hypervisor.ledger_operations],
        wallet_sequences=hypervisor.wallet_operation_sequences,
        wallet_q_atom_balances=hypervisor.wallet_q_atom_balances,
        session_funding_accounts=[item.model_dump(mode="json") for item in hypervisor.session_funding_accounts],
        settlement_proposals=[item.model_dump(mode="json") for item in hypervisor.settlement_proposals],
        settlement_acceptances=[item.model_dump(mode="json") for item in hypervisor.settlement_acceptances],
        settlement_transition_hashes=hypervisor.settlement_transition_hashes,
    )
    app_hash = AIDNABCIApplication(ledger_service=ledger).prepare_snapshot()["app_hash"]
    if app_hash != snapshot.get("app_hash"):
        raise ValidatorBackupError("Hypervisor Ledger does not match ABCI snapshot")
    return snapshot


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }


def _read_and_verify_manifest(root: Path) -> ValidatorBackupManifest:
    try:
        manifest = ValidatorBackupManifest(**json.loads((root / "manifest.json").read_text(encoding="utf-8")))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValidatorBackupError("backup manifest is invalid") from error
    if _file_hashes(root) != manifest.files:
        raise ValidatorBackupError("backup file hashes do not match manifest")
    return manifest


def _safe_extract(archive: Path, root: Path) -> None:
    try:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                destination = root / member.filename
                resolved = destination.resolve()
                if (
                    Path(member.filename).is_absolute()
                    or (root not in resolved.parents and resolved != root)
                ):
                    raise ValidatorBackupError("backup archive contains an unsafe path")
            bundle.extractall(root)
    except (OSError, zipfile.BadZipFile) as error:
        raise ValidatorBackupError("backup archive is unreadable") from error
