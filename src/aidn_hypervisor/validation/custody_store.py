import hashlib
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from aidn_hypervisor.validation.models import (
    ValidationReport,
    ValidationReportCustodyObject,
    canonical_validation_report_bytes,
    validation_report_integrity,
)


class ValidationReportCustodyStore:
    """Stores immutable canonical Validation Report bodies below one controlled root."""

    def __init__(self, root_path: Path | str) -> None:
        self.root_path = Path(root_path).resolve()

    def store_report(self, report: ValidationReport) -> ValidationReportCustodyObject:
        report_hash, report_size = validation_report_integrity(report)
        payload = canonical_validation_report_bytes(report)
        destination = self._payload_path(report_hash)
        relative_path = destination.relative_to(self.root_path).as_posix()

        if destination.exists():
            self._verify_path(destination, report_hash, report_size)
            return ValidationReportCustodyObject(
                report_hash=report_hash,
                report_size=report_size,
                storage_relative_path=relative_path,
                stored_at=self._now(),
            )

        staging_root = self.root_path / ".staging" / uuid4().hex
        staging_root.mkdir(parents=True, exist_ok=False)
        staged_payload = staging_root / "report.json"
        try:
            with staged_payload.open("wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            self._verify_path(staged_payload, report_hash, report_size)

            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                self._verify_path(destination, report_hash, report_size)
            else:
                staged_payload.replace(destination)
                destination.chmod(stat.S_IREAD)
            return ValidationReportCustodyObject(
                report_hash=report_hash,
                report_size=report_size,
                storage_relative_path=relative_path,
                stored_at=self._now(),
            )
        finally:
            if staged_payload.exists():
                staged_payload.unlink()
            if staging_root.exists():
                staging_root.rmdir()

    def read_report_body(self, report_hash: str) -> dict:
        path = self._payload_path(report_hash)
        if not path.exists():
            raise KeyError(report_hash)
        self._verify_path(path, report_hash, expected_size=None)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Validation report custody payload must be an object")
        return payload

    def verify_report(self, report_hash: str) -> ValidationReportCustodyObject:
        path = self._payload_path(report_hash)
        if not path.exists():
            raise KeyError(report_hash)
        report_size = self._verify_path(path, report_hash, expected_size=None)
        return ValidationReportCustodyObject(
            report_hash=report_hash,
            report_size=report_size,
            storage_relative_path=path.relative_to(self.root_path).as_posix(),
            stored_at=self._now(),
        )

    def _payload_path(self, report_hash: str) -> Path:
        digest = self._validated_digest(report_hash)
        return self.root_path / "reports" / "sha256" / digest[:2] / digest / "report.json"

    def _verify_path(
        self,
        path: Path,
        report_hash: str,
        expected_size: int | None,
    ) -> int:
        payload = path.read_bytes()
        size = len(payload)
        digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        if digest != report_hash:
            raise ValueError("Validation report custody content hash mismatch")
        if expected_size is not None and size != expected_size:
            raise ValueError("Validation report custody content size mismatch")
        return size

    @staticmethod
    def _validated_digest(report_hash: str) -> str:
        normalized = str(report_hash or "").strip().lower()
        prefix = "sha256:"
        digest = normalized.removeprefix(prefix)
        if (
            not normalized.startswith(prefix)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("report_hash must use sha256:<64-hex> form")
        return digest

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()
