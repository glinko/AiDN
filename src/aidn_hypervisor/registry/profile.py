"""Required Registry Profile + Registry Classes (RFC-0061 §10, §11)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RegistryClass(str, Enum):
    """Registry service class (RFC-0061 §11)."""

    FULL = "full"
    CACHE = "cache"
    ARCHIVE = "archive"
    BOOTSTRAP = "bootstrap"


class RequiredRegistryProfile(BaseModel, frozen=True):
    """
    RFC-0061 §10 — Required Registry Profile.

    Defines which object types a Full Registry must store.
    """

    version: int = 1
    protocol_version: str = "1.0.0"
    required_object_types: list[str] = Field(
        default_factory=lambda: [
            "finalized_block",
            "ledger_operation",
            "operation_result",
            "state_snapshot",
            "advertisement",
            "validation_report",
            "session_settlement",
            "session_failure",
            "usage_report",
            "reputation_profile",
            "epoch_record",
            "consensus_commitment",
            "registry_profile",
        ]
    )
    optional_object_types: list[str] = Field(
        default_factory=lambda: [
            "derived_index",
            "snapshot_artifact",
            "large_binary_ref",
        ]
    )
    min_completeness: float = Field(default=0.95, ge=0.0, le=1.0)
    max_lag_epochs: int = Field(default=3, ge=1)

    def is_required(self, object_type: str) -> bool:
        return object_type in self.required_object_types

    def is_known(self, object_type: str) -> bool:
        return (
            object_type in self.required_object_types
            or object_type in self.optional_object_types
        )

    def validate_object_type(self, object_type: str) -> bool:
        """Validate that an object type is known to this profile."""
        return self.is_known(object_type)


class RegistryProfileService:
    """Manages registry profiles and class compliance."""

    def __init__(self, registry_class: RegistryClass = RegistryClass.FULL) -> None:
        self.registry_class = registry_class
        self._profiles: dict[int, RequiredRegistryProfile] = {}
        self._current_version: int = 1

    def set_profile(self, profile: RequiredRegistryProfile) -> None:
        self._profiles[profile.version] = profile
        self._current_version = profile.version

    def get_current_profile(self) -> RequiredRegistryProfile | None:
        return self._profiles.get(self._current_version)

    def get_profile(self, version: int) -> RequiredRegistryProfile | None:
        return self._profiles.get(version)

    def is_compliant(self, object_types_stored: set[str]) -> bool:
        """Check if the registry has all required object types."""
        profile = self.get_current_profile()
        if not profile:
            return True  # no profile = no constraints
        required = set(profile.required_object_types)
        return required.issubset(object_types_stored)

    def completeness_score(self, object_types_stored: set[str]) -> float:
        """Calculate completeness score."""
        profile = self.get_current_profile()
        if not profile:
            return 1.0
        required = set(profile.required_object_types)
        if not required:
            return 1.0
        present = required.intersection(object_types_stored)
        return len(present) / len(required)
