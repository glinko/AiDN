"""RFC-0062 §14-§16 — Portable Snapshot Encoder.

Deterministic logical representation with namespace ordering,
database-independent, bit-identical across platforms.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


# ── Namespace ordering (RFC-0062 §14) ─────────────────────────────

STATE_NAMESPACES: list[str] = [
    "wallets",
    "hypervisors",
    "services",
    "endpoints",
    "sessions",
    "stakes",
    "bonds",
    "certifications",
    "reputation",
    "epochs",
    "protocol_parameters",
    "evidence",
]


class PortableSnapshotEncoder:
    """Deterministic encoder for canonical application state snapshots.

    Produces bit-identical output for the same input regardless of
    platform or OS, by:
    1. Ordering namespaces according to STATE_NAMESPACES
    2. Sorting dict keys within each namespace
    3. Using canonical JSON (sorted keys, compact separators)
    4. UTF-8 encoding the final output
    """

    def __init__(self, *, chunk_size: int = 8_388_608) -> None:
        """Create encoder with configurable chunk size.

        Args:
            chunk_size: Maximum chunk size in bytes (default 8 MiB).
        """
        self.chunk_size = chunk_size

    # ── Encode ───────────────────────────────────────────────────

    @staticmethod
    def _sort_recursive(obj: Any) -> Any:
        """Recursively sort dict keys within an object."""
        if isinstance(obj, dict):
            return {k: PortableSnapshotEncoder._sort_recursive(v)
                    for k, v in sorted(obj.items())}
        if isinstance(obj, list):
            return [PortableSnapshotEncoder._sort_recursive(item)
                    for item in obj]
        return obj

    def encode(self, state: dict[str, Any]) -> bytes:
        """Encode state dict into deterministic bytes.

        Args:
            state: Dictionary mapping namespace names to their data.

        Returns:
            UTF-8 encoded canonical JSON bytes.

        Raises:
            ValueError: If any key in state is not a known namespace.
        """
        # Validate all keys are known namespaces
        unknown = set(state.keys()) - set(STATE_NAMESPACES)
        if unknown:
            raise ValueError(
                f"Unknown namespace(s): {', '.join(sorted(unknown))}"
            )

        # Build ordered state: all namespaces present, in STATE_NAMESPACES order
        ordered_state: dict[str, Any] = {}
        for ns in STATE_NAMESPACES:
            if ns in state:
                # Recursively sort keys within each namespace value
                ordered_state[ns] = self._sort_recursive(state[ns])
            else:
                # Missing namespaces become empty entries
                ordered_state[ns] = {}

        # Canonical JSON: NO sort_keys (top-level already ordered by
        # STATE_NAMESPACES), compact separators, no BOM
        canonical = json.dumps(
            ordered_state,
            sort_keys=False,
            separators=(",", ":"),
            ensure_ascii=False,
        )

        return canonical.encode("utf-8")

    # ── Decode ───────────────────────────────────────────────────

    def decode(self, data: bytes) -> dict[str, Any]:
        """Decode bytes back into state dict.

        Args:
            data: UTF-8 encoded canonical JSON bytes.

        Returns:
            Dictionary mapping namespace names to their data.
        """
        text = data.decode("utf-8")
        return json.loads(text)

    # ── Content hash ─────────────────────────────────────────────

    def compute_content_hash(self, state: dict[str, Any]) -> str:
        """Compute SHA-256 hash of encoded state bytes.

        Args:
            state: Dictionary mapping namespace names to their data.

        Returns:
            Hex-encoded SHA-256 hash string.
        """
        encoded = self.encode(state)
        return hashlib.sha256(encoded).hexdigest()

    # ── Content size ─────────────────────────────────────────────

    def compute_content_size(self, state: dict[str, Any]) -> int:
        """Compute size of encoded state bytes.

        Args:
            state: Dictionary mapping namespace names to their data.

        Returns:
            Size in bytes of the encoded representation.
        """
        encoded = self.encode(state)
        return len(encoded)
