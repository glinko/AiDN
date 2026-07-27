"""Tests for registry/profile — Registry Profile + Classes (RFC-0061 §10, §11)."""

from __future__ import annotations

import pytest

from aidn_hypervisor.registry import (
    RegistryClass,
    RegistryProfileService,
    RequiredRegistryProfile,
)

# ---------------------------------------------------------------------------
# RegistryClass enum
# ---------------------------------------------------------------------------

def test_registry_class_enum():
    assert RegistryClass.FULL.value == "full"
    assert RegistryClass.CACHE.value == "cache"
    assert RegistryClass.ARCHIVE.value == "archive"
    assert RegistryClass.BOOTSTRAP.value == "bootstrap"


# ---------------------------------------------------------------------------
# RequiredRegistryProfile defaults
# ---------------------------------------------------------------------------

def test_profile_defaults():
    profile = RequiredRegistryProfile()
    assert profile.version == 1
    assert profile.protocol_version == "1.0.0"
    assert len(profile.required_object_types) == 13
    assert len(profile.optional_object_types) == 3
    assert profile.min_completeness == 0.95
    assert profile.max_lag_epochs == 3


def test_profile_required_types():
    profile = RequiredRegistryProfile()
    assert "finalized_block" in profile.required_object_types
    assert "ledger_operation" in profile.required_object_types
    assert "validation_report" in profile.required_object_types
    assert "epoch_record" in profile.required_object_types
    assert "consensus_commitment" in profile.required_object_types
    assert "registry_profile" in profile.required_object_types


def test_profile_optional_types():
    profile = RequiredRegistryProfile()
    assert "derived_index" in profile.optional_object_types
    assert "snapshot_artifact" in profile.optional_object_types
    assert "large_binary_ref" in profile.optional_object_types


# ---------------------------------------------------------------------------
# RequiredRegistryProfile methods
# ---------------------------------------------------------------------------

def test_is_required():
    profile = RequiredRegistryProfile()
    assert profile.is_required("finalized_block") is True
    assert profile.is_required("validation_report") is True
    assert profile.is_required("derived_index") is False
    assert profile.is_required("unknown_type") is False


def test_is_known():
    profile = RequiredRegistryProfile()
    assert profile.is_known("finalized_block") is True
    assert profile.is_known("derived_index") is True
    assert profile.is_known("unknown_type") is False


def test_validate_object_type():
    profile = RequiredRegistryProfile()
    assert profile.validate_object_type("finalized_block") is True
    assert profile.validate_object_type("derived_index") is True
    assert profile.validate_object_type("unknown_type") is False


# ---------------------------------------------------------------------------
# RequiredRegistryProfile frozen
# ---------------------------------------------------------------------------

def test_profile_frozen():
    profile = RequiredRegistryProfile()
    with pytest.raises(Exception):
        profile.version = 2  # type: ignore


# ---------------------------------------------------------------------------
# RegistryProfileService — set / get
# ---------------------------------------------------------------------------

def test_profile_service_set_get():
    svc = RegistryProfileService()
    profile = RequiredRegistryProfile(version=1)
    svc.set_profile(profile)
    assert svc.get_current_profile() is not None
    assert svc.get_current_profile().version == 1


def test_get_profile_by_version():
    svc = RegistryProfileService()
    p1 = RequiredRegistryProfile(version=1)
    p2 = RequiredRegistryProfile(version=2)
    svc.set_profile(p1)
    svc.set_profile(p2)
    assert svc.get_profile(1) is not None
    assert svc.get_profile(2) is not None
    assert svc.get_profile(3) is None


# ---------------------------------------------------------------------------
# RegistryProfileService — compliance
# ---------------------------------------------------------------------------

def test_profile_service_compliance_pass():
    svc = RegistryProfileService()
    profile = RequiredRegistryProfile()
    svc.set_profile(profile)
    # Store all required types
    stored = set(profile.required_object_types)
    assert svc.is_compliant(stored) is True


def test_profile_service_compliance_fail():
    svc = RegistryProfileService()
    profile = RequiredRegistryProfile()
    svc.set_profile(profile)
    # Missing some required types
    stored = {"finalized_block", "ledger_operation"}
    assert svc.is_compliant(stored) is False


# ---------------------------------------------------------------------------
# RegistryProfileService — completeness score
# ---------------------------------------------------------------------------

def test_completeness_score_full():
    svc = RegistryProfileService()
    profile = RequiredRegistryProfile()
    svc.set_profile(profile)
    stored = set(profile.required_object_types)
    score = svc.completeness_score(stored)
    assert score == 1.0


def test_completeness_score_partial():
    svc = RegistryProfileService()
    profile = RequiredRegistryProfile()
    svc.set_profile(profile)
    # Store half of required types
    stored = set(profile.required_object_types[:6])
    score = svc.completeness_score(stored)
    assert 0.0 < score < 1.0


def test_completeness_score_zero():
    svc = RegistryProfileService()
    profile = RequiredRegistryProfile()
    svc.set_profile(profile)
    stored: set[str] = set()
    score = svc.completeness_score(stored)
    assert score == 0.0


# ---------------------------------------------------------------------------
# RegistryProfileService — no profile = no constraints
# ---------------------------------------------------------------------------

def test_profile_no_constraints():
    svc = RegistryProfileService()
    # No profile set
    assert svc.is_compliant({"anything"}) is True
    assert svc.completeness_score({"anything"}) == 1.0


# ---------------------------------------------------------------------------
# RegistryProfileService — versioning
# ---------------------------------------------------------------------------

def test_profile_versioning():
    svc = RegistryProfileService()
    p1 = RequiredRegistryProfile(version=1)
    p2 = RequiredRegistryProfile(version=2)

    svc.set_profile(p1)
    assert svc.get_current_profile().version == 1

    svc.set_profile(p2)
    assert svc.get_current_profile().version == 2
    assert svc.get_profile(1) is not None
    assert svc.get_profile(2) is not None


# ---------------------------------------------------------------------------
# RegistryClass — full / cache
# ---------------------------------------------------------------------------

def test_registry_class_full():
    svc = RegistryProfileService(registry_class=RegistryClass.FULL)
    assert svc.registry_class == RegistryClass.FULL


def test_registry_class_cache():
    svc = RegistryProfileService(registry_class=RegistryClass.CACHE)
    assert svc.registry_class == RegistryClass.CACHE


# ---------------------------------------------------------------------------
# min_completeness / max_lag_epochs constraints
# ---------------------------------------------------------------------------

def test_min_completeness():
    profile = RequiredRegistryProfile(min_completeness=0.8)
    assert profile.min_completeness == 0.8

    with pytest.raises(Exception):
        RequiredRegistryProfile(min_completeness=1.5)

    with pytest.raises(Exception):
        RequiredRegistryProfile(min_completeness=-0.1)


def test_max_lag_epochs():
    profile = RequiredRegistryProfile(max_lag_epochs=5)
    assert profile.max_lag_epochs == 5

    with pytest.raises(Exception):
        RequiredRegistryProfile(max_lag_epochs=0)
