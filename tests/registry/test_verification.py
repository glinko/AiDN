"""Tests for registry verification (RFC-0061 §§47-49)."""

from __future__ import annotations

import pytest

from aidn_hypervisor.registry import (
    ConsistencyChecker,
    ConsistencyIssue,
    ImmutableObjectStore,
    ObjectVerifier,
    RegistryObjectEnvelope,
    VerificationBatchResult,
    VerificationResult,
)

# ─── Helpers ────────────────────────────────────────────────────────────────


def _make_envelope(
    *,
    obj_type: str = "test",
    payload: dict | None = None,
    object_id: str | None = None,
    created_epoch: int | None = None,
    parent_references: list[str] | None = None,
    previous_version_reference: str | None = None,
) -> RegistryObjectEnvelope:
    return RegistryObjectEnvelope.create(
        object_type=obj_type,
        payload=payload or {"key": "value"},
        object_id=object_id,
        created_epoch=created_epoch,
        parent_references=parent_references,
        previous_version_reference=previous_version_reference,
    )


def _store_with_objects(
    count: int = 3,
    *,
    epochs: list[int] | None = None,
) -> ImmutableObjectStore:
    store = ImmutableObjectStore()
    for i in range(count):
        epoch = epochs[i] if epochs and i < len(epochs) else (i + 1)
        env = _make_envelope(
            object_id=f"obj-{i}",
            created_epoch=epoch,
            payload={"index": i},
        )
        store.put(env)
    return store


# ─── VerificationResult / VerificationBatchResult ───────────────────────────


class TestVerificationResult:

    def test_verify_object_valid(self) -> None:
        store = ImmutableObjectStore()
        env = _make_envelope(object_id="valid-obj")
        store.put(env)

        verifier = ObjectVerifier(store)
        result = verifier.verify_object("valid-obj")

        assert result.object_id == "valid-obj"
        assert result.valid is True
        assert result.reason == ""
        assert result.verified_at > 0

    def test_verify_object_invalid_hash(self) -> None:
        store = ImmutableObjectStore()
        env = _make_envelope(object_id="bad-hash")
        # Tamper with the content_hash
        tampered = env.model_copy(update={"content_hash": "wrong"})
        store._objects["bad-hash"] = tampered  # bypass put validation

        verifier = ObjectVerifier(store)
        result = verifier.verify_object("bad-hash")

        assert result.valid is False
        assert result.reason == "hash_mismatch"
        assert result.expected_hash == "wrong"
        assert result.actual_hash != "wrong"

    def test_verify_object_not_found(self) -> None:
        store = ImmutableObjectStore()
        verifier = ObjectVerifier(store)
        result = verifier.verify_object("nonexistent")

        assert result.valid is False
        assert result.reason == "not_found"

    def test_verify_object_size_mismatch(self) -> None:
        store = ImmutableObjectStore()
        env = _make_envelope(object_id="bad-size")
        # Tamper with content_size
        tampered = env.model_copy(update={"content_size": 99999})
        store._objects["bad-size"] = tampered

        verifier = ObjectVerifier(store)
        result = verifier.verify_object("bad-size")

        assert result.valid is False
        assert result.reason == "size_mismatch"

    def test_verify_object_with_empty_payload(self) -> None:
        store = ImmutableObjectStore()
        env = _make_envelope(object_id="empty-payload", payload={})
        store.put(env)

        verifier = ObjectVerifier(store)
        result = verifier.verify_object("empty-payload")

        assert result.valid is True

    def test_verification_result_frozen(self) -> None:
        result = VerificationResult(
            object_id="test", valid=True, verified_at=1.0
        )
        with pytest.raises(Exception):
            result.valid = False  # type: ignore

    def test_verification_batch_result_frozen(self) -> None:
        batch = VerificationBatchResult(total=1, valid=1, invalid=0)
        with pytest.raises(Exception):
            batch.valid = 0  # type: ignore


# ─── ObjectVerifier batch ──────────────────────────────────────────────────


class TestObjectVerifierBatch:

    def test_verify_batch(self) -> None:
        store = _store_with_objects(count=3)
        verifier = ObjectVerifier(store)

        result = verifier.verify_batch(["obj-0", "obj-1", "obj-2"])

        assert result.total == 3
        assert result.valid == 3
        assert result.invalid == 0
        assert len(result.results) == 3
        assert result.batch_id != ""

    def test_verify_batch_mixed(self) -> None:
        store = _store_with_objects(count=2)
        verifier = ObjectVerifier(store)

        result = verifier.verify_batch(["obj-0", "obj-1", "nonexistent"])

        assert result.total == 3
        assert result.valid == 2
        assert result.invalid == 1

    def test_verify_all(self) -> None:
        store = _store_with_objects(count=3)
        verifier = ObjectVerifier(store)

        result = verifier.verify_all()

        assert result.total == 3
        assert result.valid == 3

    def test_verify_batch_empty(self) -> None:
        store = ImmutableObjectStore()
        verifier = ObjectVerifier(store)

        result = verifier.verify_batch([])

        assert result.total == 0
        assert result.valid == 0
        assert result.invalid == 0
        assert len(result.results) == 0

    def test_verification_deterministic(self) -> None:
        """Same batch should produce the same batch_id."""
        store = _store_with_objects(count=2)
        verifier = ObjectVerifier(store)

        ids = ["obj-0", "obj-1"]
        result1 = verifier.verify_batch(ids)
        result2 = verifier.verify_batch(ids)

        assert result1.batch_id == result2.batch_id


# ─── ObjectVerifier log ────────────────────────────────────────────────────


class TestObjectVerifierLog:

    def test_verification_log(self) -> None:
        store = _store_with_objects(count=2)
        verifier = ObjectVerifier(store)

        verifier.verify_object("obj-0")
        verifier.verify_object("obj-1")

        log = verifier.get_verification_log()
        assert len(log) == 2
        assert log[0].object_id == "obj-0"
        assert log[1].object_id == "obj-1"

    def test_get_invalid_objects(self) -> None:
        store = _store_with_objects(count=2)
        verifier = ObjectVerifier(store)

        verifier.verify_object("obj-0")
        verifier.verify_object("nonexistent")

        invalid = verifier.get_invalid_objects()
        assert "nonexistent" in invalid
        assert "obj-0" not in invalid


# ─── ConsistencyChecker ────────────────────────────────────────────────────


class TestConsistencyChecker:

    def test_consistency_checker_init(self) -> None:
        store = ImmutableObjectStore()
        checker = ConsistencyChecker(store)
        assert checker.issues == []

    def test_check_parent_references_valid(self) -> None:
        store = ImmutableObjectStore()
        parent = _make_envelope(object_id="parent-1")
        child = _make_envelope(
            object_id="child-1",
            parent_references=["parent-1"],
        )
        store.put(parent)
        store.put(child)

        checker = ConsistencyChecker(store)
        issues = checker.check_parent_references()
        assert len(issues) == 0

    def test_check_parent_references_missing(self) -> None:
        store = ImmutableObjectStore()
        child = _make_envelope(
            object_id="child-1",
            parent_references=["missing-parent"],
        )
        store.put(child)

        checker = ConsistencyChecker(store)
        issues = checker.check_parent_references()
        assert len(issues) == 1
        assert issues[0].issue_type == "missing_parent_ref"
        assert issues[0].severity == "error"

    def test_check_epoch_consistency(self) -> None:
        store = ImmutableObjectStore()
        env1 = _make_envelope(object_id="e1", created_epoch=1)
        env2 = _make_envelope(object_id="e2", created_epoch=2)
        store.put(env1)
        store.put(env2)

        checker = ConsistencyChecker(store)
        issues = checker.check_epoch_consistency()
        assert len(issues) == 0

    def test_consistency_epoch_gap(self) -> None:
        store = ImmutableObjectStore()
        env1 = _make_envelope(object_id="e1", created_epoch=1)
        env2 = _make_envelope(object_id="e2", created_epoch=20)
        store.put(env1)
        store.put(env2)

        checker = ConsistencyChecker(store)
        issues = checker.check_epoch_consistency()
        assert len(issues) == 1
        assert issues[0].issue_type == "epoch_gap"
        assert issues[0].severity == "warning"

    def test_check_version_references_valid(self) -> None:
        store = ImmutableObjectStore()
        v1 = _make_envelope(object_id="v1")
        v2 = _make_envelope(
            object_id="v2",
            previous_version_reference="v1",
        )
        store.put(v1)
        store.put(v2)

        checker = ConsistencyChecker(store)
        issues = checker.check_version_references()
        assert len(issues) == 0

    def test_check_version_references_missing(self) -> None:
        store = ImmutableObjectStore()
        v2 = _make_envelope(
            object_id="v2",
            previous_version_reference="missing-v1",
        )
        store.put(v2)

        checker = ConsistencyChecker(store)
        issues = checker.check_version_references()
        assert len(issues) == 1
        assert issues[0].issue_type == "missing_version_ref"

    def test_run_all_checks(self) -> None:
        store = ImmutableObjectStore()
        parent = _make_envelope(object_id="parent-1")
        child = _make_envelope(
            object_id="child-1",
            parent_references=["missing-parent"],
            previous_version_reference="missing-v1",
            created_epoch=1,
        )
        store.put(parent)
        store.put(child)

        checker = ConsistencyChecker(store)
        all_issues = checker.run_all_checks()

        # Should find both parent_ref and version_ref issues
        types = {i.issue_type for i in all_issues}
        assert "missing_parent_ref" in types
        assert "missing_version_ref" in types

    def test_consistency_multiple_issues(self) -> None:
        store = ImmutableObjectStore()
        child1 = _make_envelope(
            object_id="c1",
            parent_references=["p-missing-1"],
        )
        child2 = _make_envelope(
            object_id="c2",
            parent_references=["p-missing-2"],
        )
        store.put(child1)
        store.put(child2)

        checker = ConsistencyChecker(store)
        issues = checker.check_parent_references()
        assert len(issues) == 2

    def test_clear_issues(self) -> None:
        store = ImmutableObjectStore()
        child = _make_envelope(
            object_id="c1",
            parent_references=["missing"],
        )
        store.put(child)

        checker = ConsistencyChecker(store)
        checker.check_parent_references()
        assert len(checker.issues) > 0

        checker.clear_issues()
        assert len(checker.issues) == 0


# ─── ConsistencyIssue model ────────────────────────────────────────────────


class TestConsistencyIssue:

    def test_consistency_issue_frozen(self) -> None:
        issue = ConsistencyIssue(
            object_id="test",
            issue_type="test",
            details="test",
        )
        with pytest.raises(Exception):
            issue.details = "changed"  # type: ignore

    def test_consistency_issue_severity(self) -> None:
        issue = ConsistencyIssue(
            object_id="test",
            issue_type="test",
            details="test",
            severity="critical",
        )
        assert issue.severity == "critical"
