"""Generate and verify the repository's current implementation profile.

The profile is deliberately derived from the checked-in operation coverage and
the actual envelope/AppHash implementation. It is a candidate release
artifact, not an activation or Governance decision.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from aidn_hypervisor.consensus.coverage import (
    ACTIVE_OPERATION_TYPES,
    CONSENSUS_APPLIED_OPERATION_TYPES,
    LEGACY_OPERATION_TYPES,
    SUPPORTED_OPERATION_VERSIONS,
)
from aidn_hypervisor.consensus.models import KNOWN_OPERATION_TYPES, LedgerOperationEnvelope
from aidn_hypervisor.consensus.state_store import ABCIStateStore

IMPLEMENTATION_PROFILE_VERSION = "imp-0001.v2"
DEFAULT_IMPLEMENTATION_PROFILE_ID = "aidn-mainnet-candidate-1"
IMPLEMENTATION_PROFILE_STATUS = "DRAFT_CANDIDATE"
IMPLEMENTATION_PROFILE_ACTIVATION_STATE = "NOT_ACTIVE"


def canonical_json_bytes(value: Any) -> bytes:
    """Return the canonical JSON bytes used by the current implementation."""

    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_digest(value: Any) -> str:
    """Hash a JSON value using the current repository hash representation."""

    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def operation_catalog_payload() -> dict[str, Any]:
    """Return the deterministic operation catalog input and derived coverage."""

    known = sorted(KNOWN_OPERATION_TYPES)
    active = sorted(ACTIVE_OPERATION_TYPES)
    supported = sorted(CONSENSUS_APPLIED_OPERATION_TYPES & ACTIVE_OPERATION_TYPES)
    unsupported = sorted(ACTIVE_OPERATION_TYPES - CONSENSUS_APPLIED_OPERATION_TYPES)
    legacy = sorted(LEGACY_OPERATION_TYPES)
    payload = {
        "operation_catalog_version": 1,
        "known_operation_types": known,
        "active_operation_types": active,
        "supported_operation_types": supported,
        "active_but_unsupported_operation_types": unsupported,
        "legacy_operation_types": legacy,
        "known_but_unsupported_operation_types": sorted(
            set(unsupported) | set(legacy)
        ),
    }
    return {**payload, "operation_catalog_hash": sha256_digest(payload)}


def build_implementation_profile(
    *, profile_id: str = DEFAULT_IMPLEMENTATION_PROFILE_ID
) -> dict[str, Any]:
    """Build a deterministic profile from the active Python implementation."""

    operation_catalog = operation_catalog_payload()
    envelope_default_version = LedgerOperationEnvelope.model_fields["operation_version"].default
    profile: dict[str, Any] = {
        "profile_version": IMPLEMENTATION_PROFILE_VERSION,
        "profile_id": profile_id,
        "status": IMPLEMENTATION_PROFILE_STATUS,
        "activation_state": IMPLEMENTATION_PROFILE_ACTIVATION_STATE,
        "state_schema_version": ABCIStateStore.SCHEMA_VERSION,
        "snapshot_format_version": ABCIStateStore.SNAPSHOT_FORMAT,
        "canonical_encoding": {
            "version": 1,
            "format": "json",
            "utf8": True,
            "ensure_ascii": True,
            "sort_keys": True,
            "separators": [",", ":"],
            "floating_point": "forbidden",
        },
        "operation_envelope": {
            "default_operation_version": envelope_default_version,
            "supported_operation_versions": sorted(SUPPORTED_OPERATION_VERSIONS),
            "operation_id": "sha256(canonical envelope with operation_id empty and signatures empty)",
            "signing_bytes": "canonical envelope with signatures empty",
        },
        "operation_catalog": operation_catalog,
        "state_commitment": {
            "abci_app_hash_version": "aidn-abci-state-hash.v1",
            "abci_app_hash": (
                "sha256(canonical JSON of operations, wallet_sequences, settlement_state, "
                "and populated consensus_state)"
            ),
            "execution_state_root": (
                "sha256(canonical JSON of operation count, wallet_sequences, "
                "and populated consensus_state)"
            ),
            "empty_extension_compatibility": "empty post-MVP extensions are omitted from historical AppHash",
        },
        "stable_error_policy": "symbolic deterministic errors; human text is non-consensus",
    }
    profile["profile_commitment"] = sha256_digest(profile)
    return profile


def verify_implementation_profile(profile: dict[str, Any]) -> None:
    """Raise ``ValueError`` when a generated profile is stale or tampered."""

    if not isinstance(profile, dict):
        raise ValueError("IMPLEMENTATION_PROFILE_INVALID")
    expected = build_implementation_profile(profile_id=profile.get("profile_id", ""))
    if profile != expected:
        raise ValueError("IMPLEMENTATION_PROFILE_MISMATCH")


__all__ = [
    "DEFAULT_IMPLEMENTATION_PROFILE_ID",
    "IMPLEMENTATION_PROFILE_ACTIVATION_STATE",
    "IMPLEMENTATION_PROFILE_STATUS",
    "IMPLEMENTATION_PROFILE_VERSION",
    "build_implementation_profile",
    "canonical_json_bytes",
    "operation_catalog_payload",
    "sha256_digest",
    "verify_implementation_profile",
]
