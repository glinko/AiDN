"""RFC-0062 §25 — Snapshot compression handler.

Supports NONE, GZIP, and ZSTD (ZSTD deferred).
Enforces size bounds to prevent decompression bombs.
"""

from __future__ import annotations

import gzip

from aidn_hypervisor.snapshot.models import CompressionAlgorithm


class CompressionHandler:
    """Compress / decompress snapshot data with size-bound enforcement."""

    def __init__(
        self,
        *,
        max_compressed_size: int = 1_073_741_824,   # 1 GiB
        max_uncompressed_size: int = 10_737_418_240,  # 10 GiB
        max_expansion_ratio: float = 10.0,
    ) -> None:
        self.max_compressed_size = max_compressed_size
        self.max_uncompressed_size = max_uncompressed_size
        self.max_expansion_ratio = max_expansion_ratio

    # ── compress ─────────────────────────────────────────────────

    def compress(self, data: bytes, algorithm: CompressionAlgorithm) -> bytes:
        """Compress *data* using the specified algorithm."""
        if algorithm == CompressionAlgorithm.NONE:
            if len(data) > self.max_uncompressed_size:
                raise ValueError(
                    f"uncompressed size {len(data)} exceeds max {self.max_uncompressed_size}"
                )
            return data

        if algorithm == CompressionAlgorithm.GZIP:
            if len(data) > self.max_uncompressed_size:
                raise ValueError(
                    f"uncompressed size {len(data)} exceeds max {self.max_uncompressed_size}"
                )
            compressed = gzip.compress(data)
            if len(compressed) > self.max_compressed_size:
                raise ValueError(
                    f"compressed size {len(compressed)} exceeds max {self.max_compressed_size}"
                )
            return compressed

        if algorithm == CompressionAlgorithm.ZSTD:
            raise NotImplementedError("zstd not available")

        raise ValueError(f"unknown algorithm: {algorithm}")

    # ── decompress ───────────────────────────────────────────────

    def decompress(self, data: bytes, algorithm: CompressionAlgorithm) -> bytes:
        """Decompress *data* using the specified algorithm."""
        if algorithm == CompressionAlgorithm.NONE:
            return data

        if algorithm == CompressionAlgorithm.GZIP:
            decompressed = gzip.decompress(data)
            if len(decompressed) > self.max_uncompressed_size:
                raise ValueError(
                    f"uncompressed size {len(decompressed)} exceeds max {self.max_uncompressed_size}"
                )
            if len(data) > 0:
                ratio = len(decompressed) / len(data)
                if ratio > self.max_expansion_ratio:
                    raise ValueError(
                        f"expansion ratio {ratio:.2f} exceeds max {self.max_expansion_ratio}"
                    )
            return decompressed

        if algorithm == CompressionAlgorithm.ZSTD:
            raise NotImplementedError("zstd not available")

        raise ValueError(f"unknown algorithm: {algorithm}")

    # ── get_compressed_size ──────────────────────────────────────

    def get_compressed_size(
        self, data: bytes, algorithm: CompressionAlgorithm
    ) -> int:
        """Return the compressed size without full decompression."""
        if algorithm == CompressionAlgorithm.NONE:
            return len(data)

        if algorithm == CompressionAlgorithm.GZIP:
            return len(gzip.compress(data))

        if algorithm == CompressionAlgorithm.ZSTD:
            raise NotImplementedError("zstd not available")

        raise ValueError(f"unknown algorithm: {algorithm}")
