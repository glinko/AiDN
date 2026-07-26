"""Tests for SnapshotVerifier, InvariantChecker — RFC-0062 §45-§50.

Snapshot verification and invariant checking.
"""

import hashlib
import json

import pytest

from aidn_hypervisor.snapshot.models import (
    SnapshotChunk,
    SnapshotManifest,
    SnapshotType,
    CompressionAlgorithm,
    Encoding,
)
from aidn_hypervisor.snapshot.chunking import Chunker
from aidn_hypervisor.snapshot.staging import StagingStateStore
from aidn_hypervisor.snapshot.verification import (
    SnapshotVerifier,
    InvariantChecker,
    InvariantError,
    VerificationResult,
    InvariantCheckResult,
)


# ── Helpers ────────────────────────────────────────────────────────

def _make_chunks(data: bytes, snapshot_id: str = "test-snap") -> list[SnapshotChunk]:
    """Split data into chunks."""
    chunker = Chunker(chunk_size=4096)
    return chunker.split(data, snapshot_id=snapshot_id)


def _make_manifest(
    *,
    chunk_root: str = "",
    application_state_hash: str = "",
    chunk_count: int = 0,
    snapshot_content_hash: str = "",
) -> SnapshotManifest:
    """Create a minimal manifest."""
    return SnapshotManifest(
        snapshot_id="test-snap",
        snapshot_type=SnapshotType.FULL_STATE,
        snapshot_format_version=1,
        network_id="testnet",
        chain_id="chain-1",
        network_revision=1,
        protocol_version="1.0.0",
        application_version="1.0.0",
        state_schema_version=1,
        block_height=1000,
        block_hash="0xabc",
        block_time="2025-01-01T00:00:00Z",
        epoch=1,
        application_state_hash=application_state_hash,
        snapshot_content_hash=snapshot_content_hash,
        snapshot_content_size=100,
        chunk_count=chunk_count,
        chunk_size=4096,
        chunk_root=chunk_root,
        compression=CompressionAlgorithm.NONE,
        encoding=Encoding.JSON_DETERMINISTIC,
        creation_time="2025-01-01T00:00:00Z",
        producer_service_id="producer-1",
        producer_signature="sig",
    )


def _make_valid_wallets() -> list[dict]:
    """Create valid wallet data."""
    return [
        {"id": "w1", "balance": 100, "locked": 10, "seq": 5},
        {"id": "w2", "balance": 200, "locked": 0, "seq": 3},
    ]


def _make_valid_state_store():
    """Create a staging store with valid state."""
    store = StagingStateStore()
    store.load_namespace("wallets", {
        "w1": {"balance": 100, "locked": 10, "seq": 5},
        "w2": {"balance": 200, "locked": 0, "seq": 3},
    })
    store.load_namespace("hypervisors", {
        "h1": {"status": "running", "wallet": "w1"},
    })
    store.load_namespace("services", {
        "s1": {"type": "validator", "hypervisor": "h1"},
    })
    store.load_namespace("endpoints", [])
    store.load_namespace("sessions", [
        {"id": "sess1", "wallet": "w1", "deposit": 50, "distributed": 10},
    ])
    store.load_namespace("stakes", [
        {"id": "st1", "wallet": "w1", "amount": 50},
    ])
    store.load_namespace("bonds", [
        {"id": "b1", "wallet": "w1", "amount": 20},
    ])
    store.load_namespace("certifications", [])
    store.load_namespace("reputation", {"w1": 1.0, "w2": 0.8})
    store.load_namespace("epochs", [])
    store.load_namespace("protocol_parameters", {
        "max_block_size": 1_000_000,
        "version": 1,
        "declared_height": 1000,
    })
    store.load_namespace("evidence", [
        {"id": "ev1", "type": "signed", "consumed": False},
    ])
    return store


# ── SnapshotVerifier ──────────────────────────────────────────────

class TestVerifyManifestHash:

    def test_matching_hash(self):
        verifier = SnapshotVerifier()
        manifest = _make_manifest(application_state_hash="abc123")
        assert verifier.verify_manifest_hash(manifest, "abc123") is True

    def test_mismatching_hash(self):
        verifier = SnapshotVerifier()
        manifest = _make_manifest(application_state_hash="abc123")
        assert verifier.verify_manifest_hash(manifest, "def456") is False

    def test_empty_hash(self):
        verifier = SnapshotVerifier()
        manifest = _make_manifest(application_state_hash="")
        assert verifier.verify_manifest_hash(manifest, "") is True


class TestVerifyChunkRoot:

    def test_valid_chunk_root(self):
        verifier = SnapshotVerifier()
        data = b"test snapshot content for verification"
        chunks = _make_chunks(data)
        chunk_hashes = [c.chunk_hash for c in chunks]
        from aidn_hypervisor.snapshot.chunking import MerkleTree
        expected_root = MerkleTree(chunk_hashes).root_hash()
        assert verifier.verify_chunk_root(chunks, expected_root) is True

    def test_tampered_chunk_root(self):
        verifier = SnapshotVerifier()
        data = b"test snapshot content for verification"
        chunks = _make_chunks(data)
        # Tamper with a chunk payload — rebuild chunk with new payload
        original = chunks[0]
        chunks[0] = SnapshotChunk(
            snapshot_id=original.snapshot_id,
            chunk_index=original.chunk_index,
            total_chunks=original.total_chunks,
            uncompressed_size=len(b"TAMPERED"),
            compressed_size=len(b"TAMPERED"),
            chunk_hash=original.chunk_hash,  # hash doesn't match new payload
            payload=b"TAMPERED",
        )
        chunk_hashes = [c.chunk_hash for c in chunks]
        from aidn_hypervisor.snapshot.chunking import MerkleTree
        expected_root = MerkleTree(chunk_hashes).root_hash()
        # The root won't match because payload was tampered (hash mismatch)
        assert verifier.verify_chunk_root(chunks, expected_root) is False

    def test_wrong_root_hash(self):
        verifier = SnapshotVerifier()
        data = b"test snapshot content for verification"
        chunks = _make_chunks(data)
        assert verifier.verify_chunk_root(chunks, "0" * 64) is False

    def test_empty_chunks(self):
        verifier = SnapshotVerifier()
        assert verifier.verify_chunk_root([], "any") is True


class TestVerifyContentHash:

    def test_valid_content_hash(self):
        verifier = SnapshotVerifier()
        data = b"test snapshot content for hashing"
        chunks = _make_chunks(data)
        expected_hash = hashlib.sha256(data).hexdigest()
        assert verifier.verify_content_hash(chunks, expected_hash) is True

    def test_tampered_content_hash(self):
        verifier = SnapshotVerifier()
        data = b"test snapshot content for hashing"
        chunks = _make_chunks(data)
        assert verifier.verify_content_hash(chunks, "0" * 64) is False

    def test_empty_chunks_hash(self):
        verifier = SnapshotVerifier()
        empty_hash = hashlib.sha256(b"").hexdigest()
        assert verifier.verify_content_hash([], empty_hash) is True


class TestVerifyComplete:

    def test_full_pipeline_passes(self):
        verifier = SnapshotVerifier()
        data = b"test snapshot content for full verification"
        chunks = _make_chunks(data)
        chunk_hashes = [c.chunk_hash for c in chunks]
        from aidn_hypervisor.snapshot.chunking import MerkleTree
        chunk_root = MerkleTree(chunk_hashes).root_hash()
        content_hash = hashlib.sha256(data).hexdigest()

        manifest = _make_manifest(
            chunk_root=chunk_root,
            application_state_hash=content_hash,
            chunk_count=len(chunks),
            snapshot_content_hash=content_hash,
        )

        result = verifier.verify_complete(
            manifest, chunks,
            canonical_state_hash=content_hash,
        )
        assert result.valid
        assert result.errors == []

    def test_detects_chunk_count_mismatch(self):
        verifier = SnapshotVerifier()
        data = b"test content"
        chunks = _make_chunks(data)
        manifest = _make_manifest(chunk_count=len(chunks) + 1)
        result = verifier.verify_complete(
            manifest, chunks,
            canonical_state_hash="any",
        )
        assert not result.valid
        assert not result.chunk_count_ok

    def test_detects_chunk_root_mismatch(self):
        verifier = SnapshotVerifier()
        data = b"test content"
        chunks = _make_chunks(data)
        manifest = _make_manifest(
            chunk_count=len(chunks),
            chunk_root="0" * 64,
        )
        result = verifier.verify_complete(
            manifest, chunks,
            canonical_state_hash="any",
        )
        assert not result.valid
        assert not result.chunk_root_ok

    def test_detects_content_hash_mismatch(self):
        verifier = SnapshotVerifier()
        data = b"test content"
        chunks = _make_chunks(data)
        chunk_hashes = [c.chunk_hash for c in chunks]
        from aidn_hypervisor.snapshot.chunking import MerkleTree
        chunk_root = MerkleTree(chunk_hashes).root_hash()
        manifest = _make_manifest(chunk_root=chunk_root, chunk_count=len(chunks))
        result = verifier.verify_complete(
            manifest, chunks,
            canonical_state_hash="wrong-hash",
        )
        assert not result.valid
        assert not result.state_hash_ok

    def test_detects_state_hash_mismatch(self):
        verifier = SnapshotVerifier()
        data = b"test content"
        chunks = _make_chunks(data)
        chunk_hashes = [c.chunk_hash for c in chunks]
        from aidn_hypervisor.snapshot.chunking import MerkleTree
        chunk_root = MerkleTree(chunk_hashes).root_hash()
        content_hash = hashlib.sha256(data).hexdigest()
        manifest = _make_manifest(
            chunk_root=chunk_root,
            application_state_hash="wrong-state-hash",
            chunk_count=len(chunks),
            snapshot_content_hash=content_hash,
        )
        result = verifier.verify_complete(
            manifest, chunks,
            canonical_state_hash=content_hash,
        )
        assert not result.valid
        assert not result.state_hash_ok


class TestVerificationResult:

    def test_all_fields_populated(self):
        r = VerificationResult(
            valid=True,
            chunk_count_ok=True,
            chunk_root_ok=True,
            content_hash_ok=True,
            state_hash_ok=True,
            errors=[],
        )
        assert r.valid
        assert len(r.errors) == 0

    def test_invalid_with_errors(self):
        r = VerificationResult(
            valid=False,
            chunk_count_ok=False,
            chunk_root_ok=True,
            content_hash_ok=True,
            state_hash_ok=True,
            errors=["chunk count mismatch"],
        )
        assert not r.valid
        assert len(r.errors) == 1


# ── InvariantChecker ──────────────────────────────────────────────

class TestInvariantCheckerValidState:

    def test_valid_state_passes(self):
        checker = InvariantChecker()
        store = _make_valid_state_store()
        result = checker.check_all(store)
        assert result.valid
        assert result.violations == []

    def test_checks_counted(self):
        checker = InvariantChecker()
        store = _make_valid_state_store()
        result = checker.check_all(store)
        assert result.checks_performed > 0
        assert result.checks_passed == result.checks_performed


class TestInvariantCheckerNegativeBalance:

    def test_detects_negative_balance(self):
        checker = InvariantChecker()
        store = StagingStateStore()
        store.load_namespace("wallets", {
            "w1": {"balance": -50, "locked": 0, "seq": 1},
        })
        store.load_namespace("protocol_parameters", {"version": 1, "declared_height": 100})
        result = checker.check_all(store)
        assert not result.valid
        assert any("balance" in v.lower() for v in result.violations)

    def test_detects_negative_locked(self):
        checker = InvariantChecker()
        store = StagingStateStore()
        store.load_namespace("wallets", {
            "w1": {"balance": 100, "locked": -10, "seq": 1},
        })
        store.load_namespace("protocol_parameters", {"version": 1, "declared_height": 100})
        result = checker.check_all(store)
        assert not result.valid


class TestInvariantCheckerSupplyConservation:

    def test_detects_supply_violation(self):
        checker = InvariantChecker()
        store = StagingStateStore()
        # balance + locked should equal total_supply
        store.load_namespace("wallets", {
            "w1": {"balance": 100, "locked": 10, "seq": 1},
            "w2": {"balance": 200, "locked": 0, "seq": 1},
        })
        # Total supply declared as 500, but actual is 310
        store.load_namespace("protocol_parameters", {
            "total_supply": 500,
            "version": 1,
            "declared_height": 100,
        })
        result = checker.check_all(store)
        assert not result.valid


class TestInvariantCheckerDuplicateIDs:

    def test_detects_duplicate_wallet_ids(self):
        checker = InvariantChecker()
        store = StagingStateStore()
        # Wallets as dict — keys are IDs, so no duplicates possible in dict
        # But if stored as list, duplicates can occur
        store.load_namespace("wallets", [
            {"id": "w1", "balance": 100, "locked": 0, "seq": 1},
            {"id": "w1", "balance": 200, "locked": 0, "seq": 2},
        ])
        store.load_namespace("protocol_parameters", {"version": 1, "declared_height": 100})
        result = checker.check_all(store)
        assert not result.valid

    def test_detects_duplicate_evidence(self):
        checker = InvariantChecker()
        store = StagingStateStore()
        store.load_namespace("wallets", {"w1": {"balance": 100, "locked": 0, "seq": 1}})
        store.load_namespace("evidence", [
            {"id": "ev1", "type": "signed", "consumed": False},
            {"id": "ev1", "type": "signed", "consumed": True},
        ])
        store.load_namespace("protocol_parameters", {"version": 1, "declared_height": 100})
        result = checker.check_all(store)
        assert not result.valid


class TestInvariantCheckerDuplicateEvidence:

    def test_consumed_evidence_not_reused(self):
        checker = InvariantChecker()
        store = StagingStateStore()
        store.load_namespace("wallets", {"w1": {"balance": 100, "locked": 0, "seq": 1}})
        store.load_namespace("evidence", [
            {"id": "ev1", "type": "signed", "consumed": True},
            {"id": "ev1", "type": "signed", "consumed": True},
        ])
        store.load_namespace("protocol_parameters", {"version": 1, "declared_height": 100})
        result = checker.check_all(store)
        assert not result.valid


class TestInvariantCheckerBalances:

    def test_check_balances_valid(self):
        checker = InvariantChecker()
        violations = checker.check_balances(_make_valid_wallets())
        assert violations == []

    def test_check_balances_negative(self):
        checker = InvariantChecker()
        wallets = [
            {"id": "w1", "balance": -10, "locked": 0, "seq": 1},
        ]
        violations = checker.check_balances(wallets)
        assert len(violations) > 0


class TestInvariantCheckerUniqueness:

    def test_check_uniqueness_valid(self):
        checker = InvariantChecker()
        data = {"w1": {"balance": 100}, "w2": {"balance": 200}}
        violations = checker.check_uniqueness(data)
        assert violations == []

    def test_check_uniqueness_with_list_duplicates(self):
        checker = InvariantChecker()
        data = [
            {"id": "x1", "val": 1},
            {"id": "x1", "val": 2},
        ]
        violations = checker.check_uniqueness(data)
        assert len(violations) > 0


class TestInvariantCheckResult:

    def test_result_fields(self):
        r = InvariantCheckResult(
            valid=True,
            checks_performed=5,
            checks_passed=5,
            violations=[],
        )
        assert r.valid
        assert r.checks_performed == 5
        assert r.checks_passed == 5


class TestInvariantError:

    def test_raised_with_message(self):
        with pytest.raises(InvariantError, match="balance"):
            raise InvariantError("negative balance detected")
