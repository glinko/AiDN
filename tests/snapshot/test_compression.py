"""Tests for snapshot compression handler.

RFC-0062 §25
"""

import gzip
import hashlib

import pytest

from aidn_hypervisor.snapshot.compression import CompressionHandler
from aidn_hypervisor.snapshot.models import CompressionAlgorithm

# ── Helpers ────────────────────────────────────────────────────────

COMPRESSIBLE_DATA = b"AAAAABBBBBCCCCCDDDDDEEEEE" * 1000  # repetitive → compresses well
RANDOM_LIKE_DATA = bytes([i % 256 for i in range(10_000)])


def _make_incompressible(size: int) -> bytes:
    """Generate deterministic pseudo-random bytes (incompressible by GZIP)."""
    parts = []
    idx = 0
    while len(b"".join(parts)) < size:
        h = hashlib.sha256(f"block{idx}".encode()).digest()
        parts.append(h)
        idx += 1
    return b"".join(parts)[:size]


ROUNDTRIP_DATA = _make_incompressible(5_000)


# ── NONE compression ──────────────────────────────────────────────


class TestNoneCompression:

    def test_none_compress_passthrough(self):
        """NONE compression returns data unchanged."""
        handler = CompressionHandler()
        result = handler.compress(COMPRESSIBLE_DATA, CompressionAlgorithm.NONE)
        assert result == COMPRESSIBLE_DATA

    def test_none_decompress_passthrough(self):
        """NONE decompression returns data unchanged."""
        handler = CompressionHandler()
        result = handler.decompress(COMPRESSIBLE_DATA, CompressionAlgorithm.NONE)
        assert result == COMPRESSIBLE_DATA

    def test_none_get_compressed_size(self):
        """NONE compressed size equals original size."""
        handler = CompressionHandler()
        size = handler.get_compressed_size(COMPRESSIBLE_DATA, CompressionAlgorithm.NONE)
        assert size == len(COMPRESSIBLE_DATA)


# ── GZIP compression ──────────────────────────────────────────────


class TestGzipCompression:

    def test_gzip_round_trip(self):
        """GZIP compress then decompress yields original data."""
        handler = CompressionHandler()
        compressed = handler.compress(ROUNDTRIP_DATA, CompressionAlgorithm.GZIP)
        decompressed = handler.decompress(compressed, CompressionAlgorithm.GZIP)
        assert decompressed == ROUNDTRIP_DATA

    def test_gzip_round_trip_random_data(self):
        """GZIP round-trip works for random-like data too."""
        handler = CompressionHandler()
        compressed = handler.compress(ROUNDTRIP_DATA, CompressionAlgorithm.GZIP)
        decompressed = handler.decompress(compressed, CompressionAlgorithm.GZIP)
        assert decompressed == ROUNDTRIP_DATA

    def test_gzip_reduces_size(self):
        """GZIP reduces size of compressible data."""
        handler = CompressionHandler()
        compressed = handler.compress(COMPRESSIBLE_DATA, CompressionAlgorithm.GZIP)
        assert len(compressed) < len(COMPRESSIBLE_DATA)

    def test_gzip_compressed_size_estimate(self):
        """get_compressed_size for GZIP returns actual compressed size."""
        handler = CompressionHandler()
        estimated = handler.get_compressed_size(COMPRESSIBLE_DATA, CompressionAlgorithm.GZIP)
        actual = len(handler.compress(COMPRESSIBLE_DATA, CompressionAlgorithm.GZIP))
        assert estimated == actual

    def test_gzip_empty_data(self):
        """GZIP handles empty data."""
        handler = CompressionHandler()
        compressed = handler.compress(b"", CompressionAlgorithm.GZIP)
        decompressed = handler.decompress(compressed, CompressionAlgorithm.GZIP)
        assert decompressed == b""

    def test_gzip_invalid_data_raises(self):
        """Decompressing invalid gzip data raises an error."""
        handler = CompressionHandler()
        with pytest.raises(gzip.BadGzipFile):
            handler.decompress(b"not gzip data", CompressionAlgorithm.GZIP)

    def test_gzip_large_data(self):
        """GZIP handles larger payloads."""
        handler = CompressionHandler()
        data = _make_incompressible(50_000)
        compressed = handler.compress(data, CompressionAlgorithm.GZIP)
        decompressed = handler.decompress(compressed, CompressionAlgorithm.GZIP)
        assert decompressed == data


# ── ZSTD ──────────────────────────────────────────────────────────


class TestZstdNotImplemented:

    def test_zstd_compress_raises(self):
        """ZSTD compress raises NotImplementedError."""
        handler = CompressionHandler()
        with pytest.raises(NotImplementedError, match="zstd"):
            handler.compress(COMPRESSIBLE_DATA, CompressionAlgorithm.ZSTD)

    def test_zstd_decompress_raises(self):
        """ZSTD decompress raises NotImplementedError."""
        handler = CompressionHandler()
        with pytest.raises(NotImplementedError, match="zstd"):
            handler.decompress(COMPRESSIBLE_DATA, CompressionAlgorithm.ZSTD)

    def test_zstd_get_compressed_size_raises(self):
        """ZSTD get_compressed_size raises NotImplementedError."""
        handler = CompressionHandler()
        with pytest.raises(NotImplementedError, match="zstd"):
            handler.get_compressed_size(COMPRESSIBLE_DATA, CompressionAlgorithm.ZSTD)


# ── Size bounds enforcement ───────────────────────────────────────


class TestSizeBounds:

    def test_max_compressed_size_exceeded(self):
        """Compressed data exceeding max_compressed_size raises ValueError."""
        handler = CompressionHandler(max_compressed_size=10)
        with pytest.raises(ValueError, match="compressed"):
            handler.compress(COMPRESSIBLE_DATA, CompressionAlgorithm.GZIP)

    def test_max_uncompressed_size_exceeded(self):
        """Uncompressed data exceeding max_uncompressed_size raises ValueError."""
        handler = CompressionHandler(max_uncompressed_size=10)
        with pytest.raises(ValueError, match="uncompressed"):
            handler.compress(COMPRESSIBLE_DATA, CompressionAlgorithm.NONE)

    def test_expansion_ratio_exceeded(self):
        """Decompressed data exceeding expansion ratio raises ValueError."""
        handler = CompressionHandler(max_expansion_ratio=0.5)
        compressed = gzip.compress(COMPRESSIBLE_DATA)
        with pytest.raises(ValueError, match="expansion"):
            handler.decompress(compressed, CompressionAlgorithm.GZIP)

    def test_bounds_custom_values(self):
        """Custom bounds are respected."""
        handler = CompressionHandler(
            max_compressed_size=1_000_000,
            max_uncompressed_size=5_000_000,
            max_expansion_ratio=20.0,
        )
        # Should work fine for small data
        result = handler.compress(COMPRESSIBLE_DATA, CompressionAlgorithm.GZIP)
        assert len(result) > 0

    def test_default_bounds(self):
        """Default bounds are 1 GiB compressed, 10 GiB uncompressed, 10x ratio."""
        handler = CompressionHandler()
        assert handler.max_compressed_size == 1_073_741_824  # 1 GiB
        assert handler.max_uncompressed_size == 10_737_418_240  # 10 GiB
        assert handler.max_expansion_ratio == 10.0
