from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class RegistryRetentionClass(StrEnum):
    """RFC-0046 retention classes for immutable Registry Objects."""

    EPHEMERAL = "EPHEMERAL"
    SESSION_BOUND = "SESSION_BOUND"
    RECENT = "RECENT"
    ACTIVE_LIFECYCLE = "ACTIVE_LIFECYCLE"
    LONG_TERM = "LONG_TERM"
    PERMANENT_ARCHIVE = "PERMANENT_ARCHIVE"


def _canonical_policy_payload(policy: RegistryRetentionPolicy) -> dict:
    return {
        "policy_version": policy.policy_version,
        "default_retention_class": str(policy.default_retention_class),
        "expiration_epochs_by_class": {
            str(key): value
            for key, value in sorted(policy.expiration_epochs_by_class.items())
        },
        "namespace_overrides": {
            str(key): str(value)
            for key, value in sorted(policy.namespace_overrides.items())
        },
        "object_type_overrides": {
            str(key): str(value)
            for key, value in sorted(policy.object_type_overrides.items())
        },
    }


class RegistryRetentionPolicy(BaseModel, frozen=True):
    """Versioned retention rules with no implicit wall-clock eviction."""

    policy_version: str = "registry-retention.v1"
    default_retention_class: RegistryRetentionClass = (
        RegistryRetentionClass.ACTIVE_LIFECYCLE
    )
    expiration_epochs_by_class: dict[str, int | None] = Field(default_factory=dict)
    namespace_overrides: dict[str, RegistryRetentionClass] = Field(default_factory=dict)
    object_type_overrides: dict[str, RegistryRetentionClass] = Field(default_factory=dict)
    policy_hash: str = ""

    @model_validator(mode="after")
    def _populate_policy_hash(self) -> RegistryRetentionPolicy:
        for class_name, duration in self.expiration_epochs_by_class.items():
            RegistryRetentionClass(class_name)
            if duration is not None and int(duration) < 0:
                raise ValueError("retention duration cannot be negative")
        for namespace in self.namespace_overrides:
            if not str(namespace).strip():
                raise ValueError("retention namespace override cannot be empty")
        for object_type in self.object_type_overrides:
            if not str(object_type).strip():
                raise ValueError("retention object type override cannot be empty")
        expected = hashlib.sha256(
            json.dumps(
                _canonical_policy_payload(self),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if self.policy_hash and self.policy_hash != expected:
            raise ValueError("registry retention policy_hash does not match policy")
        object.__setattr__(self, "policy_hash", expected)
        return self

    def retention_class_for(
        self,
        *,
        namespace: str | None = None,
        object_type: str | None = None,
        retention_class: RegistryRetentionClass | str | None = None,
    ) -> RegistryRetentionClass:
        if retention_class is not None:
            return RegistryRetentionClass(retention_class)
        if object_type and object_type in self.object_type_overrides:
            return RegistryRetentionClass(self.object_type_overrides[object_type])
        if namespace and namespace in self.namespace_overrides:
            return RegistryRetentionClass(self.namespace_overrides[namespace])
        return RegistryRetentionClass(self.default_retention_class)

    def expiration_epoch_for(
        self,
        *,
        created_epoch: int | None,
        namespace: str | None = None,
        object_type: str | None = None,
        retention_class: RegistryRetentionClass | str | None = None,
        explicit_expiration_epoch: int | None = None,
    ) -> int | None:
        if explicit_expiration_epoch is not None:
            expiration_epoch = int(explicit_expiration_epoch)
            if created_epoch is not None and expiration_epoch < int(created_epoch):
                raise ValueError("expiration_epoch cannot precede created_epoch")
            return expiration_epoch
        if created_epoch is None:
            return None
        selected_class = self.retention_class_for(
            namespace=namespace,
            object_type=object_type,
            retention_class=retention_class,
        )
        duration = self.expiration_epochs_by_class.get(selected_class.value)
        if duration is None:
            return None
        duration = int(duration)
        if duration < 0:
            raise ValueError("retention duration cannot be negative")
        return int(created_epoch) + duration

    @staticmethod
    def is_expired(*, current_epoch: int, expiration_epoch: int | None) -> bool:
        return expiration_epoch is not None and int(current_epoch) >= int(expiration_epoch)
