"""Deterministic local acceptance evidence for GATE-0001 G2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import compute_execution_state_root
from aidn_hypervisor.consensus.implementation_profile import (
    build_implementation_profile,
    canonical_json_bytes,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.state_store import ABCIStateStore, ABCIStateStoreError
from aidn_hypervisor.ledger.service import LedgerOperationService

SNAPSHOT_ACCEPTANCE_VERSION = 1
SNAPSHOT_ACCEPTANCE_MODE = "CONTROLLED_LOCAL"
_CURRENT_TIME = "2030-01-01T00:00:00Z"
_SHA256_HEX = "0123456789abcdefABCDEF"
_REQUIRED_CHECKS = frozenset(
    {
        "snapshot_export_succeeds",
        "snapshot_verification_succeeds",
        "restore_yields_identical_state_root",
        "restore_yields_identical_app_hash",
        "state_sync_yields_identical_app_hash",
        "restored_and_state_synced_advance_identically",
        "corrupt_snapshot_rejected",
    }
)


class SnapshotAcceptanceError(ValueError):
    """Raised when local snapshot/state-sync acceptance cannot be proven."""


def _application(*, store: ABCIStateStore | None = None, funded: bool = False) -> AIDNABCIApplication:
    ledger = LedgerOperationService()
    if funded:
        ledger.credit_wallet_q_atoms(wallet_id="wallet:sender", amount_q_atoms=100_000)
    return AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=_CURRENT_TIME),
        genesis_time=_CURRENT_TIME,
        state_store=store,
        strict_operation_coverage=True,
    )


def _transfer(*, sequence: int, amount: int, recipient: str, memo: str) -> bytes:
    envelope = LedgerOperationEnvelope(
        operation_type="WALLET_TRANSFER",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="wallet",
        sender_wallet="wallet:sender",
        sender_sequence=sequence,
        fee_payer="wallet:sender",
        fee_class="standard",
        created_at=_CURRENT_TIME,
        expires_at="2030-01-02T00:00:00Z",
        payload={
            "recipient_wallet": recipient,
            "amount": amount,
            "memo_hash": f"sha256:{memo}",
        },
        signatures=["ed25519:sender"],
    )
    return json.dumps(envelope.model_dump(mode="json"), sort_keys=True).encode("utf-8")


def _finalize(application: AIDNABCIApplication, *, height: int, block_byte: bytes, tx: bytes) -> None:
    result, tx_results = application.finalize_block_with_results(
        block_height=height,
        block_hash=block_byte * 32,
        txs=[tx],
        time=_CURRENT_TIME,
    )
    if result.code != "ok" or len(tx_results) != 1 or tx_results[0].code != "ok":
        detail = tx_results[0].log if tx_results else result.log
        raise SnapshotAcceptanceError(f"G2 block {height} did not finalize: {detail}")
    try:
        application.commit()
    except ABCIStateStoreError as error:
        raise SnapshotAcceptanceError(f"G2 block {height} did not commit: {error}") from error


def _app_hash(application: AIDNABCIApplication) -> str:
    return str(application.prepare_snapshot()["app_hash"])


def _hash_report(body: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def _build_report(body: dict[str, Any]) -> dict[str, Any]:
    report = dict(body)
    report["report_hash"] = _hash_report(report)
    return report


def _require_sha256_hex(value: object, *, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _SHA256_HEX for character in value)
    ):
        raise SnapshotAcceptanceError(f"G2 {label} must be a 64-character SHA-256 hex value")


def _validate_report_shape(report: dict[str, Any]) -> None:
    """Reject malformed evidence before executing the expensive reproduction."""
    if report.get("schema_version") != SNAPSHOT_ACCEPTANCE_VERSION:
        raise SnapshotAcceptanceError("G2 report schema_version is unsupported")
    if report.get("status") != "PASS":
        raise SnapshotAcceptanceError("G2 acceptance report is not passing")
    if report.get("mode") != SNAPSHOT_ACCEPTANCE_MODE:
        raise SnapshotAcceptanceError("G2 report mode is unsupported")
    for field in ("profile_id", "profile_commitment"):
        if not isinstance(report.get(field), str) or not report[field]:
            raise SnapshotAcceptanceError(f"G2 report {field} is missing")
    if report.get("state_root_algorithm") != "aidn-execution-state-root.v1":
        raise SnapshotAcceptanceError("G2 state-root algorithm is unsupported")

    snapshot = report.get("snapshot")
    if not isinstance(snapshot, dict):
        raise SnapshotAcceptanceError("G2 snapshot evidence is missing")
    height = snapshot.get("height")
    chunks = snapshot.get("chunks")
    if not isinstance(height, int) or isinstance(height, bool) or height < 1:
        raise SnapshotAcceptanceError("G2 snapshot height is invalid")
    if snapshot.get("format") != 1:
        raise SnapshotAcceptanceError("G2 snapshot format is unsupported")
    if not isinstance(chunks, int) or isinstance(chunks, bool) or chunks < 1:
        raise SnapshotAcceptanceError("G2 snapshot chunk count is invalid")
    for field in ("payload_hash", "app_hash", "state_root"):
        _require_sha256_hex(snapshot.get(field), label=f"snapshot.{field}")
    state_sync_statuses = snapshot.get("state_sync_statuses")
    if (
        not isinstance(state_sync_statuses, list)
        or len(state_sync_statuses) != chunks
        or any(status != "accept" for status in state_sync_statuses)
    ):
        raise SnapshotAcceptanceError("G2 State Sync status evidence is incomplete")
    corrupt_statuses = snapshot.get("corrupt_state_sync_statuses")
    if (
        not isinstance(corrupt_statuses, list)
        or not corrupt_statuses
        or corrupt_statuses[-1] == "accept"
    ):
        raise SnapshotAcceptanceError("G2 corrupt-snapshot rejection evidence is incomplete")

    for height_label in ("height_one", "height_two"):
        height_evidence = report.get(height_label)
        if not isinstance(height_evidence, dict):
            raise SnapshotAcceptanceError(f"G2 {height_label} evidence is missing")
        for field in (
            "state_root",
            "source_app_hash",
            "restored_app_hash",
            "state_synced_app_hash",
        ):
            _require_sha256_hex(height_evidence.get(field), label=f"{height_label}.{field}")

    checks = report.get("checks")
    if not isinstance(checks, dict) or set(checks) != _REQUIRED_CHECKS:
        raise SnapshotAcceptanceError("G2 report checks are incomplete")
    if any(type(value) is not bool for value in checks.values()):
        raise SnapshotAcceptanceError("G2 report checks must be boolean")
    if not all(checks.values()):
        raise SnapshotAcceptanceError("G2 report contains a failed acceptance check")


def run_snapshot_acceptance() -> dict[str, Any]:
    """Run export, direct restore, chunked State Sync, and one-block continuity."""
    with TemporaryDirectory(prefix="aidn-g2-") as temporary_root:
        root = Path(temporary_root)
        source_store = ABCIStateStore(root / "source", chunk_size=64)
        source = _application(store=source_store, funded=True)
        block_one = _transfer(
            sequence=1,
            amount=25,
            recipient="wallet:recipient-one",
            memo="g2-block-one",
        )
        _finalize(source, height=1, block_byte=b"A", tx=block_one)

        snapshot = source.prepare_snapshot()
        metadata_list = source.list_state_snapshots()
        if len(metadata_list) != 1:
            raise SnapshotAcceptanceError("G2 source did not retain exactly one snapshot")
        metadata = metadata_list[0]
        if metadata.app_hash.hex() != str(snapshot["app_hash"]):
            raise SnapshotAcceptanceError("G2 snapshot metadata AppHash does not match export")

        restored = _application()
        restore_result = restored.apply_snapshot(snapshot)
        if restore_result.code != "ok":
            raise SnapshotAcceptanceError(restore_result.log or "G2 direct snapshot restore failed")

        sync_store = ABCIStateStore(root / "state-sync", chunk_size=64)
        state_synced = _application(store=sync_store)
        if state_synced.offer_state_snapshot(metadata) != "accept":
            raise SnapshotAcceptanceError("G2 State Sync offer was rejected")
        state_sync_statuses: list[str] = []
        for index in range(metadata.chunks):
            status = state_synced.apply_state_snapshot_chunk(
                index=index,
                chunk=source.load_state_snapshot_chunk(
                    height=metadata.height,
                    format=metadata.format,
                    chunk=index,
                ),
            )
            state_sync_statuses.append(status)
        if not state_sync_statuses or state_sync_statuses[-1] != "accept":
            raise SnapshotAcceptanceError("G2 State Sync did not accept the complete snapshot")

        corrupt_store = ABCIStateStore(root / "corrupt-state-sync", chunk_size=64)
        corrupt_target = _application(store=corrupt_store)
        if corrupt_target.offer_state_snapshot(metadata) != "accept":
            raise SnapshotAcceptanceError("G2 corrupt-snapshot offer setup failed")
        corrupt_statuses: list[str] = []
        for index in range(metadata.chunks):
            chunk = source.load_state_snapshot_chunk(
                height=metadata.height,
                format=metadata.format,
                chunk=index,
            )
            if index == 0:
                chunk = bytes([chunk[0] ^ 1]) + chunk[1:]
            corrupt_statuses.append(corrupt_target.apply_state_snapshot_chunk(index=index, chunk=chunk))
            if corrupt_statuses[-1] != "accept":
                break

        source_state_root = compute_execution_state_root(source.ledger)
        restored_state_root = compute_execution_state_root(restored.ledger)
        state_synced_state_root = compute_execution_state_root(state_synced.ledger)
        source_app_hash = _app_hash(source)
        restored_app_hash = _app_hash(restored)
        state_synced_app_hash = _app_hash(state_synced)

        block_two = _transfer(
            sequence=2,
            amount=13,
            recipient="wallet:recipient-two",
            memo="g2-block-two",
        )
        _finalize(source, height=2, block_byte=b"B", tx=block_two)
        _finalize(restored, height=2, block_byte=b"B", tx=block_two)
        _finalize(state_synced, height=2, block_byte=b"B", tx=block_two)

        source_next_state_root = compute_execution_state_root(source.ledger)
        restored_next_state_root = compute_execution_state_root(restored.ledger)
        state_synced_next_state_root = compute_execution_state_root(state_synced.ledger)
        source_next_app_hash = _app_hash(source)
        restored_next_app_hash = _app_hash(restored)
        state_synced_next_app_hash = _app_hash(state_synced)

        checks = {
            "snapshot_export_succeeds": metadata.height == 1 and metadata.chunks >= 1,
            "snapshot_verification_succeeds": (
                restore_result.code == "ok" and str(snapshot["state_root"]) == source_state_root
            ),
            "restore_yields_identical_state_root": (
                source_state_root == restored_state_root == state_synced_state_root
            ),
            "restore_yields_identical_app_hash": (
                source_app_hash == restored_app_hash
            ),
            "state_sync_yields_identical_app_hash": (
                source_app_hash == state_synced_app_hash
            ),
            "restored_and_state_synced_advance_identically": (
                source_next_app_hash == restored_next_app_hash == state_synced_next_app_hash
                and source_next_state_root
                == restored_next_state_root
                == state_synced_next_state_root
            ),
            "corrupt_snapshot_rejected": any(status != "accept" for status in corrupt_statuses),
        }
        body: dict[str, Any] = {
            "schema_version": SNAPSHOT_ACCEPTANCE_VERSION,
            "status": "PASS" if all(checks.values()) else "FAIL",
            "mode": SNAPSHOT_ACCEPTANCE_MODE,
            "profile_id": build_implementation_profile()["profile_id"],
            "profile_commitment": build_implementation_profile()["profile_commitment"],
            "state_root_algorithm": "aidn-execution-state-root.v1",
            "snapshot": {
                "height": metadata.height,
                "format": metadata.format,
                "chunks": metadata.chunks,
                "payload_hash": metadata.hash.hex(),
                "app_hash": metadata.app_hash.hex(),
                "state_root": str(snapshot["state_root"]),
                "state_sync_statuses": state_sync_statuses,
                "corrupt_state_sync_statuses": corrupt_statuses,
            },
            "height_one": {
                "state_root": source_state_root,
                "source_app_hash": source_app_hash,
                "restored_app_hash": restored_app_hash,
                "state_synced_app_hash": state_synced_app_hash,
            },
            "height_two": {
                "state_root": source_next_state_root,
                "source_app_hash": source_next_app_hash,
                "restored_app_hash": restored_next_app_hash,
                "state_synced_app_hash": state_synced_next_app_hash,
            },
            "checks": checks,
        }
        return _build_report(body)


def verify_snapshot_acceptance_report(report: dict[str, Any]) -> dict[str, Any]:
    """Verify report integrity and reproduce its deterministic acceptance run."""
    if not isinstance(report, dict):
        raise SnapshotAcceptanceError("G2 report must be a JSON object")
    _validate_report_shape(report)
    report_hash = report.get("report_hash")
    if not isinstance(report_hash, str):
        raise SnapshotAcceptanceError("G2 report hash is missing")
    body = {key: value for key, value in report.items() if key != "report_hash"}
    if report_hash != _hash_report(body):
        raise SnapshotAcceptanceError("G2 report hash mismatch")
    expected = run_snapshot_acceptance()
    if report != expected:
        raise SnapshotAcceptanceError("G2 report does not match a fresh deterministic acceptance run")
    return report


def load_and_verify_snapshot_acceptance_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SnapshotAcceptanceError(f"cannot load G2 report: {error}") from error
    return verify_snapshot_acceptance_report(value)


__all__ = [
    "SNAPSHOT_ACCEPTANCE_MODE",
    "SNAPSHOT_ACCEPTANCE_VERSION",
    "SnapshotAcceptanceError",
    "load_and_verify_snapshot_acceptance_report",
    "run_snapshot_acceptance",
    "verify_snapshot_acceptance_report",
]
