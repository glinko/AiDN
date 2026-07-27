"""Tests for snapshot chunking, Merkle tree, and chunk verification.

RFC-0062 §22-§25
"""

import hashlib

import pytest

from aidn_hypervisor.snapshot.chunking import Chunker, ChunkVerifier, MerkleTree
from aidn_hypervisor.snapshot.models import SnapshotChunk

# ── Helpers ────────────────────────────────────────────────────────

SNAPSHOT_ID = "abc123def456"
DEFAULT_CHUNK_SIZE = 8_388_608  # 8 MiB


def make_payload(size: int, pattern: bytes = b"\xff") -> bytes:
    return pattern * size


def sha256hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Chunker.split ──────────────────────────────────────────────────


class TestChunkerSplit:

    def test_split_exact_multiple(self):
        """Data that is an exact multiple of chunk_size splits cleanly."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(300)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        assert len(chunks) == 3
        for i, c in enumerate(chunks):
            assert c.chunk_index == i
            assert c.total_chunks == 3
            assert c.snapshot_id == SNAPSHOT_ID

    def test_split_last_chunk_smaller(self):
        """Last chunk is smaller when data doesn't divide evenly."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(250)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        assert len(chunks) == 3
        assert chunks[0].uncompressed_size == 100
        assert chunks[1].uncompressed_size == 100
        assert chunks[2].uncompressed_size == 50

    def test_split_single_chunk(self):
        """Data smaller than chunk_size produces a single chunk."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(50)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert chunks[0].total_chunks == 1

    def test_split_empty_data(self):
        """Empty data produces an empty list."""
        chunker = Chunker(chunk_size=100)
        chunks = chunker.split(b"", snapshot_id=SNAPSHOT_ID)
        assert chunks == []

    def test_split_chunk_indices_contiguous(self):
        """Chunk indices are contiguous 0..N-1."""
        chunker = Chunker(chunk_size=50)
        data = make_payload(175)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_split_chunk_hash_correct(self):
        """chunk_hash is SHA-256 of the payload."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(200)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        for c in chunks:
            assert c.chunk_hash == sha256hex(c.payload)

    def test_split_uncompressed_size_matches_payload(self):
        """uncompressed_size equals len(payload)."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(250)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        for c in chunks:
            assert c.uncompressed_size == len(c.payload)

    def test_split_compressed_size_equals_uncompressed_for_none(self):
        """compressed_size == uncompressed_size when no compression applied."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(200)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        for c in chunks:
            assert c.compressed_size == c.uncompressed_size

    def test_split_default_chunk_size(self):
        """Default chunk_size is 8 MiB."""
        chunker = Chunker()
        assert chunker.chunk_size == DEFAULT_CHUNK_SIZE

    def test_split_large_data_simulated(self):
        """Splitting ~16 MiB of data produces correct number of chunks."""
        chunker = Chunker(chunk_size=1_000)
        data = make_payload(16_000)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        assert len(chunks) == 16
        for c in chunks:
            assert c.uncompressed_size == 1_000

    def test_split_odd_last_chunk(self):
        """Last chunk handles remainder correctly."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(103)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        assert len(chunks) == 2
        assert chunks[1].uncompressed_size == 3

    def test_split_payload_content_correct(self):
        """Each chunk payload matches the corresponding slice of original data."""
        chunker = Chunker(chunk_size=100)
        data = bytes(range(256)) * 4  # 1024 bytes
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        for i, c in enumerate(chunks):
            start = i * 100
            end = start + 100
            assert c.payload == data[start:end]


# ── Chunker.reassemble ─────────────────────────────────────────────


class TestChunkerReassemble:

    def test_reassemble_identical_data(self):
        """Reassembling chunks produces the original data."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(300)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        result = chunker.reassemble(chunks)
        assert result == data

    def test_reassemble_single_chunk(self):
        """Single chunk reassembles correctly."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(50)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        assert chunker.reassemble(chunks) == data

    def test_reassemble_empty(self):
        """Empty chunk list produces empty bytes."""
        chunker = Chunker(chunk_size=100)
        assert chunker.reassemble([]) == b""

    def test_reassemble_odd_last_chunk(self):
        """Reassemble works when last chunk is smaller."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(250)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        assert chunker.reassemble(chunks) == data

    def test_reassemble_out_of_order_raises(self):
        """Reassemble raises if chunks are out of order."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(200)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        chunks.reverse()
        with pytest.raises(ValueError, match="out of order"):
            chunker.reassemble(chunks)

    def test_reassemble_duplicate_index_raises(self):
        """Reassemble raises if duplicate chunk indices exist."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(200)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        # Duplicate first chunk
        dup = SnapshotChunk(
            snapshot_id=SNAPSHOT_ID,
            chunk_index=0,
            total_chunks=2,
            uncompressed_size=100,
            compressed_size=100,
            chunk_hash=sha256hex(data[:100]),
            payload=data[:100],
        )
        with pytest.raises(ValueError, match="duplicate"):
            chunker.reassemble([chunks[0], dup])


# ── Chunker.verify_chunk ──────────────────────────────────────────


class TestChunkerVerifyChunk:

    def test_verify_valid_chunk(self):
        """Valid chunk passes verification."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(100)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        assert chunker.verify_chunk(chunks[0]) is True

    def test_verify_tampered_payload(self):
        """Tampered payload fails verification."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(100)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        tampered = SnapshotChunk(
            snapshot_id=chunks[0].snapshot_id,
            chunk_index=chunks[0].chunk_index,
            total_chunks=chunks[0].total_chunks,
            uncompressed_size=chunks[0].uncompressed_size,
            compressed_size=chunks[0].compressed_size,
            chunk_hash=chunks[0].chunk_hash,
            payload=b"\x00" * 100,
        )
        assert chunker.verify_chunk(tampered) is False

    def test_verify_tampered_hash(self):
        """Tampered hash fails verification."""
        chunker = Chunker(chunk_size=100)
        data = make_payload(100)
        chunks = chunker.split(data, snapshot_id=SNAPSHOT_ID)
        tampered = SnapshotChunk(
            snapshot_id=chunks[0].snapshot_id,
            chunk_index=chunks[0].chunk_index,
            total_chunks=chunks[0].total_chunks,
            uncompressed_size=chunks[0].uncompressed_size,
            compressed_size=chunks[0].compressed_size,
            chunk_hash="0" * 64,
            payload=chunks[0].payload,
        )
        assert chunker.verify_chunk(tampered) is False


# ── MerkleTree ─────────────────────────────────────────────────────


class TestMerkleTree:

    def test_single_leaf(self):
        """Root hash equals the single leaf hash."""
        h = "a" * 64
        tree = MerkleTree([h])
        assert tree.root_hash() == h

    def test_two_leaves(self):
        """Two leaves produce SHA-256(h1+h2) root."""
        h1, h2 = "a" * 64, "b" * 64
        tree = MerkleTree([h1, h2])
        expected = sha256hex(bytes.fromhex(h1) + bytes.fromhex(h2))
        assert tree.root_hash() == expected

    def test_three_leaves_odd_duplication(self):
        """Odd leaves: last leaf is duplicated before pairing."""
        h1, h2, h3 = "a" * 64, "b" * 64, "c" * 64
        tree = MerkleTree([h1, h2, h3])
        # Level 1: [h1, h2, h3, h3]
        # pairs: (h1,h2), (h3,h3)
        p1 = sha256hex(bytes.fromhex(h1) + bytes.fromhex(h2))
        p2 = sha256hex(bytes.fromhex(h3) + bytes.fromhex(h3))
        expected = sha256hex(bytes.fromhex(p1) + bytes.fromhex(p2))
        assert tree.root_hash() == expected

    def test_four_leaves(self):
        """Four leaves produce correct two-level tree."""
        hashes = ["a" * 64, "b" * 64, "c" * 64, "d" * 64]
        tree = MerkleTree(hashes)
        p1 = sha256hex(bytes.fromhex(hashes[0]) + bytes.fromhex(hashes[1]))
        p2 = sha256hex(bytes.fromhex(hashes[2]) + bytes.fromhex(hashes[3]))
        expected = sha256hex(bytes.fromhex(p1) + bytes.fromhex(p2))
        assert tree.root_hash() == expected

    def test_proof_single_leaf(self):
        """Single leaf: proof is empty."""
        tree = MerkleTree(["a" * 64])
        proof = tree.get_proof(0)
        assert proof == []

    def test_proof_two_leaves(self):
        """Two leaves: proof for leaf 0 contains leaf 1 as sibling."""
        h1, h2 = "a" * 64, "b" * 64
        tree = MerkleTree([h1, h2])
        proof = tree.get_proof(0)
        assert len(proof) == 1
        sibling_hash, position = proof[0]
        assert sibling_hash == h2
        assert position == "right"

    def test_proof_verify_valid(self):
        """Valid proof verifies successfully."""
        hashes = ["a" * 64, "b" * 64, "c" * 64]
        tree = MerkleTree(hashes)
        proof = tree.get_proof(1)
        root = tree.root_hash()
        assert tree.verify_proof(hashes[1], proof, root) is True

    def test_proof_verify_wrong_leaf(self):
        """Proof verification rejects a wrong leaf hash."""
        hashes = ["a" * 64, "b" * 64, "c" * 64]
        tree = MerkleTree(hashes)
        proof = tree.get_proof(1)
        root = tree.root_hash()
        wrong_leaf = "d" * 64
        assert tree.verify_proof(wrong_leaf, proof, root) is False

    def test_proof_verify_wrong_root(self):
        """Proof verification rejects a wrong root hash."""
        hashes = ["a" * 64, "b" * 64]
        tree = MerkleTree(hashes)
        proof = tree.get_proof(0)
        wrong_root = "0" * 64
        assert tree.verify_proof(hashes[0], proof, wrong_root) is False

    def test_proof_out_of_range_index(self):
        """get_proof raises for out-of-range index."""
        tree = MerkleTree(["a" * 64, "b" * 64])
        with pytest.raises(IndexError):
            tree.get_proof(5)

    def test_merkle_root_deterministic(self):
        """Same leaves always produce the same root."""
        hashes = ["a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64]
        r1 = MerkleTree(hashes).root_hash()
        r2 = MerkleTree(hashes).root_hash()
        assert r1 == r2

    def test_empty_leaves_raises(self):
        """Empty leaf list raises ValueError."""
        with pytest.raises(ValueError, match="at least one"):
            MerkleTree([])


# ── ChunkVerifier ──────────────────────────────────────────────────


class TestChunkVerifier:

    def _make_chunks(self, size: int, chunk_size: int = 100) -> list[SnapshotChunk]:
        chunker = Chunker(chunk_size=chunk_size)
        data = make_payload(size)
        return chunker.split(data, snapshot_id=SNAPSHOT_ID)

    def test_verify_all_valid(self):
        """All valid chunks pass verification."""
        verifier = ChunkVerifier()
        chunks = self._make_chunks(300)
        chunker = Chunker(chunk_size=100)
        root = MerkleTree([c.chunk_hash for c in chunks]).root_hash()
        assert verifier.verify_all(chunks, root) is True

    def test_verify_all_tampered_chunk(self):
        """Tampered chunk causes verification to fail."""
        verifier = ChunkVerifier()
        chunks = self._make_chunks(300)
        chunker = Chunker(chunk_size=100)
        root = MerkleTree([c.chunk_hash for c in chunks]).root_hash()
        # Tamper with chunk 1
        tampered = SnapshotChunk(
            snapshot_id=chunks[1].snapshot_id,
            chunk_index=chunks[1].chunk_index,
            total_chunks=chunks[1].total_chunks,
            uncompressed_size=chunks[1].uncompressed_size,
            compressed_size=chunks[1].compressed_size,
            chunk_hash=chunks[1].chunk_hash,
            payload=b"\x00" * 100,
        )
        assert verifier.verify_all([chunks[0], tampered, chunks[2]], root) is False

    def test_verify_all_wrong_root(self):
        """Wrong chunk root causes verification to fail."""
        verifier = ChunkVerifier()
        chunks = self._make_chunks(300)
        wrong_root = "0" * 64
        assert verifier.verify_all(chunks, wrong_root) is False

    def test_verify_all_empty_chunks(self):
        """Empty chunk list returns True (vacuous truth)."""
        verifier = ChunkVerifier()
        assert verifier.verify_all([], "any_root") is True

    def test_verify_chunk_inclusion_valid(self):
        """Single chunk inclusion verified under correct root."""
        verifier = ChunkVerifier()
        chunks = self._make_chunks(300)
        root = MerkleTree([c.chunk_hash for c in chunks]).root_hash()
        all_hashes = [c.chunk_hash for c in chunks]
        assert verifier.verify_chunk_inclusion(chunks[1], root, all_hashes) is True

    def test_verify_chunk_inclusion_wrong_root(self):
        """Chunk inclusion fails with wrong root."""
        verifier = ChunkVerifier()
        chunks = self._make_chunks(300)
        wrong_root = "0" * 64
        all_hashes = [c.chunk_hash for c in chunks]
        assert verifier.verify_chunk_inclusion(chunks[0], wrong_root, all_hashes) is False

    def test_verify_chunk_inclusion_tampered_hash(self):
        """Chunk inclusion fails if chunk hash doesn't match its index in all_hashes."""
        verifier = ChunkVerifier()
        chunks = self._make_chunks(300)
        root = MerkleTree([c.chunk_hash for c in chunks]).root_hash()
        all_hashes = [c.chunk_hash for c in chunks]
        # Provide a chunk whose hash doesn't match position in all_hashes
        bad_chunk = SnapshotChunk(
            snapshot_id=chunks[0].snapshot_id,
            chunk_index=0,
            total_chunks=chunks[0].total_chunks,
            uncompressed_size=chunks[0].uncompressed_size,
            compressed_size=chunks[0].compressed_size,
            chunk_hash="d" * 64,
            payload=b"\x00" * 100,
        )
        assert verifier.verify_chunk_inclusion(bad_chunk, root, all_hashes) is False

    def test_verify_all_detects_missing_chunk(self):
        """Missing a chunk changes the Merkle root, causing failure."""
        verifier = ChunkVerifier()
        chunks = self._make_chunks(300)
        root = MerkleTree([c.chunk_hash for c in chunks]).root_hash()
        # Remove middle chunk
        reduced = [chunks[0], chunks[2]]
        assert verifier.verify_all(reduced, root) is False
