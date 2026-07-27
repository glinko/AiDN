"""RFC-0062 §22-§25 — Snapshot chunking, Merkle tree, and chunk verification.

Chunker splits raw bytes into SnapshotChunk instances.
MerkleTree builds a hash tree over chunk hashes.
ChunkVerifier validates chunk integrity and Merkle inclusion.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from aidn_hypervisor.snapshot.models import SnapshotChunk

# ── Chunker ────────────────────────────────────────────────────────


class Chunker:
    """Split / reassemble / verify snapshot data chunks.

    Default chunk size is 8 MiB per RFC-0062 §24.
    """

    def __init__(self, *, chunk_size: int = 8_388_608) -> None:
        self.chunk_size = chunk_size

    # ── split ────────────────────────────────────────────────────

    def split(self, data: bytes, *, snapshot_id: str = "") -> list[SnapshotChunk]:
        """Split *data* into contiguous chunks of ``chunk_size`` bytes."""
        if not data:
            return []

        total = (len(data) + self.chunk_size - 1) // self.chunk_size

        chunks: list[SnapshotChunk] = []
        for i in range(0, len(data), self.chunk_size):
            payload = data[i : i + self.chunk_size]
            chunk_hash = hashlib.sha256(payload).hexdigest()
            chunks.append(
                SnapshotChunk(
                    snapshot_id=snapshot_id,
                    chunk_index=len(chunks),
                    total_chunks=total,
                    uncompressed_size=len(payload),
                    compressed_size=len(payload),
                    chunk_hash=chunk_hash,
                    payload=payload,
                )
            )

        return chunks

    # ── reassemble ───────────────────────────────────────────────

    def reassemble(self, chunks: list[SnapshotChunk]) -> bytes:
        """Reassemble chunks in order. Raises on out-of-order or duplicates."""
        if not chunks:
            return b""

        seen: set[int] = set()
        for idx, c in enumerate(chunks):
            if c.chunk_index in seen:
                raise ValueError(f"duplicate chunk index {c.chunk_index}")
            if idx != c.chunk_index:
                raise ValueError(
                    f"chunks out of order: expected index {idx}, got {c.chunk_index}"
                )
            seen.add(c.chunk_index)

        return b"".join(c.payload for c in chunks)

    # ── verify_chunk ─────────────────────────────────────────────

    def verify_chunk(self, chunk: SnapshotChunk) -> bool:
        """Return ``True`` when ``chunk.chunk_hash`` matches SHA-256(payload)."""
        return self._verify_chunk_hash(chunk)

    def _verify_chunk_hash(self, chunk: SnapshotChunk) -> bool:
        """Internal: verify a single chunk hash."""
        expected = hashlib.sha256(chunk.payload).hexdigest()
        return chunk.chunk_hash == expected


# ── MerkleTree ─────────────────────────────────────────────────────


class MerkleTree:
    """Merkle hash tree over a list of hex-encoded leaf hashes.

    Odd nodes at any level are duplicated (last node repeated).
    """

    def __init__(self, leaf_hashes: list[str]) -> None:
        if not leaf_hashes:
            raise ValueError("leaf_hashes must contain at least one hash")
        self._leaves = list(leaf_hashes)

    # ── root_hash ────────────────────────────────────────────────

    def root_hash(self) -> str:
        """Compute the Merkle root hash (hex string)."""
        nodes = list(self._leaves)
        if len(nodes) == 1:
            return nodes[0]

        while len(nodes) > 1:
            # Duplicate last if odd
            if len(nodes) % 2:
                nodes.append(nodes[-1])

            next_level: list[str] = []
            for i in range(0, len(nodes), 2):
                combined = bytes.fromhex(nodes[i]) + bytes.fromhex(nodes[i + 1])
                parent = hashlib.sha256(combined).hexdigest()
                next_level.append(parent)
            nodes = next_level

        return nodes[0]

    # ── get_proof ────────────────────────────────────────────────

    def get_proof(self, leaf_index: int) -> list[tuple[str, str]]:
        """Return a Merkle proof for the leaf at *leaf_index*.

        Each element is ``(sibling_hash, position)`` where *position* is
        ``"left"`` or ``"right"``.
        """
        if leaf_index < 0 or leaf_index >= len(self._leaves):
            raise IndexError(f"leaf_index {leaf_index} out of range")

        nodes = list(self._leaves)
        proof: list[tuple[str, str]] = []
        idx = leaf_index

        while len(nodes) > 1:
            if len(nodes) % 2:
                nodes.append(nodes[-1])

            if idx % 2 == 0:
                sibling_idx = idx + 1
                position = "right"
            else:
                sibling_idx = idx - 1
                position = "left"

            proof.append((nodes[sibling_idx], position))

            next_level: list[str] = []
            for i in range(0, len(nodes), 2):
                combined = bytes.fromhex(nodes[i]) + bytes.fromhex(nodes[i + 1])
                next_level.append(hashlib.sha256(combined).hexdigest())
            nodes = next_level
            idx = idx // 2

        return proof

    # ── verify_proof ─────────────────────────────────────────────

    @staticmethod
    def verify_proof(
        leaf_hash: str,
        proof: list[tuple[str, str]],
        root_hash: str,
    ) -> bool:
        """Verify that *leaf_hash* is included under *root_hash*."""
        current = leaf_hash
        for sibling_hash, position in proof:
            if position == "left":
                combined = bytes.fromhex(sibling_hash) + bytes.fromhex(current)
            else:
                combined = bytes.fromhex(current) + bytes.fromhex(sibling_hash)
            current = hashlib.sha256(combined).hexdigest()
        return current == root_hash


# ── ChunkVerifier ──────────────────────────────────────────────────


@dataclass
class _VerifyResult:
    ok: bool
    message: str


class ChunkVerifier:
    """Validate chunk integrity and Merkle inclusion."""

    def verify_all(self, chunks: list[SnapshotChunk], expected_chunk_root: str) -> bool:
        """Verify every chunk hash AND the overall Merkle root.

        Returns ``True`` only when all individual hashes are correct
        and the computed Merkle root matches *expected_chunk_root*.
        """
        if not chunks:
            return True

        chunker = Chunker()

        # Verify each chunk's individual hash
        for c in chunks:
            if not chunker.verify_chunk(c):
                return False

        # Verify Merkle root
        leaf_hashes = [c.chunk_hash for c in chunks]
        computed_root = MerkleTree(leaf_hashes).root_hash()
        return computed_root == expected_chunk_root

    def verify_chunk_inclusion(
        self,
        chunk: SnapshotChunk,
        expected_chunk_root: str,
        all_chunk_hashes: list[str],
    ) -> bool:
        """Verify that *chunk* is included under *expected_chunk_root*.

        Uses a Merkle proof built from *all_chunk_hashes*.
        """
        tree = MerkleTree(all_chunk_hashes)
        proof = tree.get_proof(chunk.chunk_index)
        return tree.verify_proof(chunk.chunk_hash, proof, expected_chunk_root)
