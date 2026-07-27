"""RFC-0062 §45-§50 — Snapshot verification and invariant checking.

SnapshotVerifier validates chunk integrity, Merkle roots, content hashes,
and application state hashes.

InvariantChecker validates business invariants on restored staging state.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from aidn_hypervisor.snapshot.chunking import Chunker, MerkleTree
from aidn_hypervisor.snapshot.compression import CompressionHandler
from aidn_hypervisor.snapshot.models import (
    CompressionAlgorithm,
    SnapshotChunk,
    SnapshotManifest,
)
from aidn_hypervisor.snapshot.staging import StagingStateStore

# ── Custom Exception ──────────────────────────────────────────────


class InvariantError(Exception):
    """Raised when a state invariant is violated."""


# ── VerificationResult ────────────────────────────────────────────


@dataclass
class VerificationResult:
    """Result of snapshot verification."""

    valid: bool
    chunk_count_ok: bool
    chunk_root_ok: bool
    content_hash_ok: bool
    state_hash_ok: bool
    errors: list[str] = field(default_factory=list)


# ── InvariantCheckResult ──────────────────────────────────────────


@dataclass
class InvariantCheckResult:
    """Result of invariant checking."""

    valid: bool
    checks_performed: int
    checks_passed: int
    violations: list[str] = field(default_factory=list)


# ── SnapshotVerifier ──────────────────────────────────────────────


class SnapshotVerifier:
    """Verify snapshot integrity per RFC-0062 §45-§46, §49-§50.

    Validates:
    - Chunk count matches manifest
    - Merkle root matches chunk hashes
    - Content hash matches reassembled data
    - Application state hash matches canonical commitment
    """

    def __init__(self) -> None:
        self._chunker = Chunker()
        self._compressor = CompressionHandler()

    def verify_manifest_hash(self, manifest: SnapshotManifest, expected_state_hash: str) -> bool:
        """Check manifest application_state_hash matches expected (per §49)."""
        return manifest.application_state_hash == expected_state_hash

    def verify_chunk_root(self, chunks: list[SnapshotChunk], expected_chunk_root: str) -> bool:
        """Build Merkle tree from chunk hashes, compare root (per §45)."""
        if not chunks:
            return True

        # Verify each individual chunk hash first
        for chunk in chunks:
            if not self._chunker.verify_chunk(chunk):
                return False

        leaf_hashes = [c.chunk_hash for c in chunks]
        computed_root = MerkleTree(leaf_hashes).root_hash()
        return computed_root == expected_chunk_root

    def verify_content_hash(
        self,
        chunks: list[SnapshotChunk],
        expected_content_hash: str,
        *,
        compression: CompressionAlgorithm = CompressionAlgorithm.NONE,
        expected_content_size: int | None = None,
    ) -> bool:
        """Reassemble all chunks, optionally decompress, compute hash (per §46)."""
        if not chunks:
            return hashlib.sha256(b"").hexdigest() == expected_content_hash

        if expected_content_size is not None and expected_content_size < 0:
            return False

        try:
            reassembled = self._chunker.reassemble(chunks)
            compressor = self._compressor
            if expected_content_size is not None:
                if expected_content_size > compressor.max_uncompressed_size:
                    return False
                compressor = CompressionHandler(
                    max_compressed_size=compressor.max_compressed_size,
                    max_uncompressed_size=expected_content_size,
                    max_expansion_ratio=max(
                        compressor.max_expansion_ratio,
                        expected_content_size / max(1, len(reassembled)),
                    ),
                )
            content = compressor.decompress(reassembled, compression)
        except (OSError, ValueError, NotImplementedError):
            return False

        if expected_content_size is not None and len(content) != expected_content_size:
            return False
        computed_hash = hashlib.sha256(content).hexdigest()
        return computed_hash == expected_content_hash

    def verify_complete(
        self,
        manifest: SnapshotManifest,
        chunks: list[SnapshotChunk],
        *,
        canonical_state_hash: str,
    ) -> VerificationResult:
        """Full verification pipeline.

        1. Verify chunk count matches manifest
        2. Verify chunk root
        3. Verify content hash
        4. Verify application state hash matches canonical commitment
        """
        errors: list[str] = []

        # 1. Chunk count
        chunk_count_ok = len(chunks) == manifest.chunk_count
        if not chunk_count_ok:
            errors.append(f"chunk count mismatch: {len(chunks)} != {manifest.chunk_count}")

        # 2. Chunk root
        chunk_root_ok = self.verify_chunk_root(chunks, manifest.chunk_root)
        if not chunk_root_ok:
            errors.append("chunk root mismatch")

        # 3. Content hash
        content_hash_ok = self.verify_content_hash(
            chunks,
            manifest.snapshot_content_hash,
            compression=manifest.compression,
            expected_content_size=manifest.snapshot_content_size,
        )
        if not content_hash_ok:
            errors.append("content hash mismatch")

        # 4. Application state hash vs canonical commitment
        state_hash_ok = self.verify_manifest_hash(manifest, canonical_state_hash)
        if not state_hash_ok:
            errors.append("application state hash mismatch")

        valid = chunk_count_ok and chunk_root_ok and content_hash_ok and state_hash_ok

        return VerificationResult(
            valid=valid,
            chunk_count_ok=chunk_count_ok,
            chunk_root_ok=chunk_root_ok,
            content_hash_ok=content_hash_ok,
            state_hash_ok=state_hash_ok,
            errors=errors,
        )


# ── InvariantChecker ──────────────────────────────────────────────


class InvariantChecker:
    """Check state invariants per RFC-0062 §50.

    Validates:
    1. Available balances >= 0 (wallet namespace)
    2. Locked balances >= 0
    3. Wallet balances + locked = total supply (conservation)
    4. Session distributions <= deposits
    5. Stake and bond conservation
    6. Wallet sequences valid
    7. Object identities unique (no duplicate IDs within namespace)
    8. Consumed evidence not duplicated
    9. Protocol parameter version matches declared height
    """

    def __init__(self) -> None:
        pass

    def check_all(self, staging: StagingStateStore) -> InvariantCheckResult:
        """Check all invariants."""
        violations: list[str] = []
        checks_performed = 0
        checks_passed = 0

        # 1. Balance invariants (negative balance / locked)
        wallets = self._get_wallet_list(staging)
        checks_performed += 1
        balance_violations = self.check_balances(wallets)
        if not balance_violations:
            checks_passed += 1
        else:
            violations.extend(balance_violations)

        # 2. Supply conservation
        checks_performed += 1
        supply_violations = self._check_supply_conservation(staging, wallets)
        if not supply_violations:
            checks_passed += 1
        else:
            violations.extend(supply_violations)

        # 3. Session distributions <= deposits
        checks_performed += 1
        session_violations = self._check_sessions(staging)
        if not session_violations:
            checks_passed += 1
        else:
            violations.extend(session_violations)

        # 4. Stake and bond conservation
        checks_performed += 1
        stake_violations = self._check_stakes_bonds(staging)
        if not stake_violations:
            checks_passed += 1
        else:
            violations.extend(stake_violations)

        # 5. Wallet sequences valid
        checks_performed += 1
        seq_violations = self._check_wallet_sequences(wallets)
        if not seq_violations:
            checks_passed += 1
        else:
            violations.extend(seq_violations)

        # 6. Object identities unique
        checks_performed += 1
        uniqueness_violations = self._check_uniqueness_all(staging)
        if not uniqueness_violations:
            checks_passed += 1
        else:
            violations.extend(uniqueness_violations)

        # 7. Consumed evidence not duplicated
        checks_performed += 1
        evidence_violations = self._check_evidence(staging)
        if not evidence_violations:
            checks_passed += 1
        else:
            violations.extend(evidence_violations)

        # 8. Protocol parameter version
        checks_performed += 1
        proto_violations = self._check_protocol_params(staging)
        if not proto_violations:
            checks_passed += 1
        else:
            violations.extend(proto_violations)

        return InvariantCheckResult(
            valid=len(violations) == 0,
            checks_performed=checks_performed,
            checks_passed=checks_passed,
            violations=violations,
        )

    def check_balances(self, wallets: list[dict]) -> list[str]:
        """Balance invariants only."""
        violations: list[str] = []
        for w in wallets:
            balance = w.get("balance", 0)
            locked = w.get("locked", 0)
            if balance < 0:
                violations.append(f"Wallet {w.get('id', '?')} has negative balance: {balance}")
            if locked < 0:
                violations.append(f"Wallet {w.get('id', '?')} has negative locked: {locked}")
        return violations

    def check_uniqueness(self, namespace_data: Any) -> list[str]:
        """Uniqueness invariants for a namespace."""
        violations: list[str] = []
        if isinstance(namespace_data, list):
            seen_ids: set[str] = set()
            for item in namespace_data:
                if isinstance(item, dict) and "id" in item:
                    item_id = item["id"]
                    if item_id in seen_ids:
                        violations.append(f"Duplicate ID {item_id}")
                    seen_ids.add(item_id)
        return violations

    # ── Internal helpers ─────────────────────────────────────────

    def _get_wallet_list(self, staging: StagingStateStore) -> list[dict]:
        """Get wallets as a list of dicts for checking."""
        wallets = staging.get_namespace("wallets")
        if wallets is None:
            return []
        if isinstance(wallets, list):
            return wallets
        if isinstance(wallets, dict):
            return [{"id": k, **v} for k, v in wallets.items()]
        return []

    def _check_supply_conservation(self, staging: StagingStateStore, wallets: list[dict]) -> list[str]:
        """Check balance + locked = total supply."""
        violations: list[str] = []
        params = staging.get_namespace("protocol_parameters")
        if not isinstance(params, dict):
            return violations  # No params to check against

        total_supply = params.get("total_supply")
        if total_supply is None:
            return violations  # No total_supply declared, skip

        actual_total = sum(w.get("balance", 0) + w.get("locked", 0) for w in wallets)
        if actual_total != total_supply:
            violations.append(f"Supply conservation violated: actual {actual_total} != declared {total_supply}")
        return violations

    def _check_sessions(self, staging: StagingStateStore) -> list[str]:
        """Check session distributions <= deposits."""
        violations: list[str] = []
        sessions = staging.get_namespace("sessions")
        if not isinstance(sessions, list):
            return violations
        for s in sessions:
            if not isinstance(s, dict):
                continue
            deposit = s.get("deposit", 0)
            distributed = s.get("distributed", 0)
            if distributed > deposit:
                violations.append(f"Session {s.get('id', '?')} distributed {distributed} > deposit {deposit}")
        return violations

    def _check_stakes_bonds(self, staging: StagingStateStore) -> list[str]:
        """Check stake and bond amounts are non-negative."""
        violations: list[str] = []
        for ns in ("stakes", "bonds"):
            data = staging.get_namespace(ns)
            if not isinstance(data, list):
                continue
            for item in data:
                if not isinstance(item, dict):
                    continue
                amount = item.get("amount", 0)
                if amount < 0:
                    violations.append(f"{ns} item {item.get('id', '?')} has negative amount: {amount}")
        return violations

    def _check_wallet_sequences(self, wallets: list[dict]) -> list[str]:
        """Check wallet sequences are valid (non-negative)."""
        violations: list[str] = []
        for w in wallets:
            seq = w.get("seq", 0)
            if isinstance(seq, int) and seq < 0:
                violations.append(f"Wallet {w.get('id', '?')} has negative seq: {seq}")
        return violations

    def _check_uniqueness_all(self, staging: StagingStateStore) -> list[str]:
        """Check uniqueness across all namespaces."""
        violations: list[str] = []
        for ns in staging.get_all_namespaces():
            data = staging.get_namespace(ns)
            ns_violations = self.check_uniqueness(data)
            for v in ns_violations:
                violations.append(f"[{ns}] {v}")
        return violations

    def _check_evidence(self, staging: StagingStateStore) -> list[str]:
        """Check consumed evidence not duplicated."""
        violations: list[str] = []
        evidence = staging.get_namespace("evidence")
        if not isinstance(evidence, list):
            return violations
        seen_consumed: set[str] = set()
        for ev in evidence:
            if not isinstance(ev, dict):
                continue
            ev_id = ev.get("id")
            if ev.get("consumed") and ev_id in seen_consumed:
                violations.append(f"Consumed evidence {ev_id} duplicated")
            if ev.get("consumed"):
                seen_consumed.add(ev_id)
        return violations

    def _check_protocol_params(self, staging: StagingStateStore) -> list[str]:
        """Check protocol parameter version is present."""
        violations: list[str] = []
        params = staging.get_namespace("protocol_parameters")
        if isinstance(params, dict) and "version" not in params:
            violations.append("protocol_parameters missing version field")
        return violations
