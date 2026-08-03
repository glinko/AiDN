from __future__ import annotations

import json
from pathlib import Path

import pytest

from aidn_hypervisor.consensus.implementation_profile import (
    build_implementation_profile,
    verify_implementation_profile,
)

ROOT = Path(__file__).resolve().parents[2]


def test_checked_in_implementation_profile_matches_current_code() -> None:
    profile = json.loads(
        (ROOT / "profiles/aidn-mainnet-candidate-1.json").read_text(encoding="utf-8")
    )

    verify_implementation_profile(profile)
    assert profile == build_implementation_profile(profile_id=profile["profile_id"])
    assert "WALLET_TRANSFER" in profile["operation_catalog"]["supported_operation_types"]
    assert "REGISTRY_UPSERT" in profile["operation_catalog"]["known_but_unsupported_operation_types"]


def test_implementation_profile_rejects_tampering() -> None:
    profile = build_implementation_profile()
    profile["operation_catalog"]["known_operation_types"].append("FAKE_OPERATION")

    with pytest.raises(ValueError, match="IMPLEMENTATION_PROFILE_MISMATCH"):
        verify_implementation_profile(profile)
