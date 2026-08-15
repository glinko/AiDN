"""Canonical content hash helpers for immutable Bundle configurations."""

from __future__ import annotations

import hashlib
import json

from aidn_hypervisor.domain.models import BundleConfig


def bundle_config_hash(bundle: BundleConfig) -> str:
    """Return the stable hash used when a Bundle is exposed as an Endpoint.

    ``enabled`` is operational state rather than immutable Bundle content, so
    it is intentionally excluded from the commitment.  The stored hash is
    also excluded to make loading legacy bundles with a missing hash safe.
    """

    payload = bundle.model_dump(mode="json")
    payload.pop("bundle_hash", None)
    payload.pop("enabled", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
