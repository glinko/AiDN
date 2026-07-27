"""RFC-0062 §47-§48 — Staging state store and restoration.

Staging state never overwrites active state directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from aidn_hypervisor.snapshot.encoding import (
    STATE_NAMESPACES,
    PortableSnapshotEncoder,
)

# ── RestorationResult ─────────────────────────────────────────────


@dataclass
class RestorationResult:
    """Result of a state restoration operation."""

    success: bool
    namespaces_loaded: list[str]
    total_objects: int
    application_state_hash: str
    error: str | None = None


# ── StagingStateStore ─────────────────────────────────────────────


class StagingStateStore:
    """In-memory staging store for snapshot state data.

    Per RFC-0062 §47, staging state is isolated from active state.
    It holds namespace data loaded during restoration before
    verification and activation.
    """

    def __init__(self) -> None:
        self._namespaces: dict[str, dict[str, Any]] = {}

    def load_namespace(self, namespace: str, data: dict[str, Any]) -> None:
        """Load a namespace into staging."""
        self._namespaces[namespace] = data

    def get_namespace(self, namespace: str) -> dict | None:
        """Get staging namespace data, or None if not loaded."""
        return self._namespaces.get(namespace)

    def get_all_namespaces(self) -> list[str]:
        """List loaded namespace names."""
        return list(self._namespaces.keys())

    def calculate_state_hash(self) -> str:
        """Hash staging state with the producer's canonical representation."""
        return PortableSnapshotEncoder().compute_content_hash(self._namespaces)

    def clear(self) -> None:
        """Wipe staging store (for restart after crash per §86)."""
        self._namespaces.clear()

    def is_empty(self) -> bool:
        """Check if staging has any data."""
        return len(self._namespaces) == 0

    def get_state_summary(self) -> dict:
        """Returns namespace names and item counts for diagnostics."""
        ns_summary: dict[str, int] = {}
        total = 0
        for ns, data in self._namespaces.items():
            count = self._count_objects(data)
            ns_summary[ns] = count
            total += count
        return {
            "namespace_count": len(self._namespaces),
            "namespaces": ns_summary,
            "total_objects": total,
        }

    @staticmethod
    def _count_objects(data: Any) -> int:
        """Count top-level items in namespace data."""
        if isinstance(data, dict):
            return len(data)
        if isinstance(data, list):
            return len(data)
        return 1

    # Internal: get raw staging data dict (for activation)
    def _get_raw(self) -> dict[str, Any]:
        return dict(self._namespaces)


# ── StateRestorer ─────────────────────────────────────────────────


class StateRestorer:
    """Restores snapshot state into staging.

    Per RFC-0062 §48:
    1. Create/clear empty staging state
    2. Decode encoded data (via PortableSnapshotEncoder)
    3. Load protocol metadata first
    4. Load namespaces in defined order (STATE_NAMESPACES)
    5. Validate object references (no dangling refs within loaded data)
    6. Calculate application state hash
    7. Return result
    """

    def __init__(self, staging: StagingStateStore) -> None:
        self._staging = staging
        self._encoder = PortableSnapshotEncoder()

    def restore(self, encoded_data: bytes) -> RestorationResult:
        """Full restoration per §48."""
        try:
            # Step 1: Clear staging
            self._staging.clear()

            # Step 2: Decode encoded data
            if not encoded_data or not encoded_data.strip():
                raise ValueError("Empty encoded data")
            decoded = self._encoder.decode(encoded_data)

            # Step 3: Load protocol metadata first
            if "protocol_parameters" in decoded:
                self._staging.load_namespace("protocol_parameters", decoded["protocol_parameters"])

            # Step 4: Load namespaces in defined order
            namespaces_loaded: list[str] = []
            for ns in STATE_NAMESPACES:
                if ns in decoded and ns != "protocol_parameters":
                    self._staging.load_namespace(ns, decoded[ns])
                    namespaces_loaded.append(ns)

            # Also add protocol_parameters to loaded list if it was present
            if "protocol_parameters" in decoded:
                namespaces_loaded.append("protocol_parameters")

            # Step 5: Validate object references
            self._validate_references()

            # Step 6: Calculate application state hash
            state_hash = self._staging.calculate_state_hash()

            # Step 7: Count total objects
            summary = self._staging.get_state_summary()

            return RestorationResult(
                success=True,
                namespaces_loaded=namespaces_loaded,
                total_objects=summary["total_objects"],
                application_state_hash=state_hash,
                error=None,
            )

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Decode error: {e}") from e
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Restoration failed: {e}") from e

    def restore_partial(self, namespace: str, data: dict) -> None:
        """Load single namespace (for partial repair per §58)."""
        self._staging.load_namespace(namespace, data)

    def _validate_references(self) -> None:
        """Validate object references — no dangling refs within loaded data."""
        wallets = self._staging.get_namespace("wallets") or {}
        wallet_ids = set(wallets.keys()) if isinstance(wallets, dict) else set()

        hypervisors = self._staging.get_namespace("hypervisors") or {}
        if isinstance(hypervisors, dict):
            for h_id, h_data in hypervisors.items():
                if isinstance(h_data, dict) and "wallet" in h_data and h_data["wallet"] not in wallet_ids:
                    raise ValueError(f"Hypervisor {h_id} references missing wallet {h_data['wallet']}")

        services = self._staging.get_namespace("services") or {}
        if isinstance(services, dict):
            for s_id, s_data in services.items():
                if isinstance(s_data, dict) and "hypervisor" in s_data:
                    hyp_ids = set(hypervisors.keys()) if isinstance(hypervisors, dict) else set()
                    if s_data["hypervisor"] not in hyp_ids:
                        raise ValueError(f"Service {s_id} references missing hypervisor {s_data['hypervisor']}")

        stakes = self._staging.get_namespace("stakes") or []
        if isinstance(stakes, list):
            for stake in stakes:
                if isinstance(stake, dict) and "wallet" in stake and stake["wallet"] not in wallet_ids:
                    raise ValueError(f"Stake references missing wallet {stake['wallet']}")
