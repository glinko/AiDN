"""Object Verification + Consistency Checking (RFC-0061 §§47-49)."""

from __future__ import annotations

import hashlib
import json
import time

from pydantic import BaseModel, Field

from .storage import ImmutableObjectStore

# ---------------------------------------------------------------------------
# Verification results
# ---------------------------------------------------------------------------


class VerificationResult(BaseModel, frozen=True):
    """Result of verifying a single object."""

    object_id: str
    valid: bool
    reason: str = ""
    expected_hash: str = ""
    actual_hash: str = ""
    verified_at: float = 0.0


class VerificationBatchResult(BaseModel, frozen=True):
    """Result of verifying a batch of objects."""

    total: int
    valid: int
    invalid: int
    results: list[VerificationResult] = Field(default_factory=list)
    batch_id: str = ""
    completed_at: float = 0.0


# ---------------------------------------------------------------------------
# Consistency issues
# ---------------------------------------------------------------------------


class ConsistencyIssue(BaseModel, frozen=True):
    """A consistency issue found during verification."""

    object_id: str
    issue_type: str
    details: str
    severity: str = "warning"  # warning | error | critical
    detected_at: float = Field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Object Verifier
# ---------------------------------------------------------------------------


class ObjectVerifier:
    """
    RFC-0061 §47 — Verify integrity of registry objects.

    Checks content hashes, payload structure, and envelope consistency.
    """

    def __init__(self, store: ImmutableObjectStore) -> None:
        self._store = store
        self._verification_log: list[VerificationResult] = []

    def verify_object(self, object_id: str) -> VerificationResult:
        """Verify a single object's integrity."""
        obj = self._store.get(object_id)
        now = time.time()

        if obj is None:
            result = VerificationResult(
                object_id=object_id,
                valid=False,
                reason="not_found",
                verified_at=now,
            )
            self._verification_log.append(result)
            return result

        # Verify content hash
        canonical = json.dumps(
            obj.payload, sort_keys=True, separators=(",", ":")
        )
        actual_hash = hashlib.sha256(canonical.encode()).hexdigest()

        if actual_hash != obj.content_hash:
            result = VerificationResult(
                object_id=object_id,
                valid=False,
                reason="hash_mismatch",
                expected_hash=obj.content_hash,
                actual_hash=actual_hash,
                verified_at=now,
            )
            self._verification_log.append(result)
            return result

        # Verify content size
        actual_size = len(canonical.encode())
        if actual_size != obj.content_size:
            result = VerificationResult(
                object_id=object_id,
                valid=False,
                reason="size_mismatch",
                expected_hash=str(obj.content_size),
                actual_hash=str(actual_size),
                verified_at=now,
            )
            self._verification_log.append(result)
            return result

        result = VerificationResult(
            object_id=object_id,
            valid=True,
            verified_at=now,
        )
        self._verification_log.append(result)
        return result

    def verify_batch(self, object_ids: list[str]) -> VerificationBatchResult:
        """Verify a batch of objects."""
        results = [self.verify_object(oid) for oid in object_ids]
        valid_count = sum(1 for r in results if r.valid)
        invalid_count = len(results) - valid_count

        batch_id = hashlib.sha256(
            json.dumps(sorted(object_ids), sort_keys=True).encode()
        ).hexdigest()

        return VerificationBatchResult(
            total=len(results),
            valid=valid_count,
            invalid=invalid_count,
            results=results,
            batch_id=batch_id,
            completed_at=time.time(),
        )

    def verify_all(self) -> VerificationBatchResult:
        """Verify all objects in the store."""
        return self.verify_batch(self._store.all_ids())

    def get_verification_log(self) -> list[VerificationResult]:
        """Return a copy of the verification log."""
        return list(self._verification_log)

    def get_invalid_objects(self) -> list[str]:
        """Get object ids that failed verification."""
        return [r.object_id for r in self._verification_log if not r.valid]


# ---------------------------------------------------------------------------
# Consistency Checker
# ---------------------------------------------------------------------------


class ConsistencyChecker:
    """
    RFC-0061 §49 — Cross-reference consistency checks.

    Verifies that related objects (parent references, epoch records)
    are internally consistent.
    """

    def __init__(self, store: ImmutableObjectStore) -> None:
        self._store = store
        self._issues: list[ConsistencyIssue] = []

    def check_parent_references(self) -> list[ConsistencyIssue]:
        """Check that all parent references point to existing objects."""
        issues: list[ConsistencyIssue] = []
        for oid in self._store.all_ids():
            obj = self._store.get(oid)
            if obj and obj.parent_references:
                for ref in obj.parent_references:
                    if not self._store.has(ref):
                        issue = ConsistencyIssue(
                            object_id=oid,
                            issue_type="missing_parent_ref",
                            details=f"Parent reference {ref} not found",
                            severity="error",
                        )
                        issues.append(issue)
        self._issues.extend(issues)
        return issues

    def check_epoch_consistency(self) -> list[ConsistencyIssue]:
        """Check that epoch references are consistent."""
        issues: list[ConsistencyIssue] = []
        epochs_seen: set[int] = set()

        for oid in self._store.all_ids():
            obj = self._store.get(oid)
            if obj and obj.created_epoch is not None:
                epochs_seen.add(obj.created_epoch)

        # Check for large epoch gaps (more than 10 epochs)
        if epochs_seen:
            sorted_epochs = sorted(epochs_seen)
            for i in range(1, len(sorted_epochs)):
                gap = sorted_epochs[i] - sorted_epochs[i - 1]
                if gap > 10:
                    issue = ConsistencyIssue(
                        object_id="",
                        issue_type="epoch_gap",
                        details=(
                            f"Gap of {gap} epochs between "
                            f"{sorted_epochs[i - 1]} and {sorted_epochs[i]}"
                        ),
                        severity="warning",
                    )
                    issues.append(issue)

        self._issues.extend(issues)
        return issues

    def check_version_references(self) -> list[ConsistencyIssue]:
        """Check that previous_version_reference points to existing objects."""
        issues: list[ConsistencyIssue] = []
        for oid in self._store.all_ids():
            obj = self._store.get(oid)
            if obj and obj.previous_version_reference:
                if not self._store.has(obj.previous_version_reference):
                    issue = ConsistencyIssue(
                        object_id=oid,
                        issue_type="missing_version_ref",
                        details=(
                            f"Previous version "
                            f"{obj.previous_version_reference} not found"
                        ),
                        severity="error",
                    )
                    issues.append(issue)
        self._issues.extend(issues)
        return issues

    def run_all_checks(self) -> list[ConsistencyIssue]:
        """Run all consistency checks."""
        all_issues: list[ConsistencyIssue] = []
        all_issues.extend(self.check_parent_references())
        all_issues.extend(self.check_epoch_consistency())
        all_issues.extend(self.check_version_references())
        return all_issues

    @property
    def issues(self) -> list[ConsistencyIssue]:
        """Return a copy of all accumulated issues."""
        return list(self._issues)

    def clear_issues(self) -> None:
        """Clear the accumulated issues list."""
        self._issues.clear()
