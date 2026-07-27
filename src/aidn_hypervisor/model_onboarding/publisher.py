"""M6-P2: Onboarding Capability Registry Publisher.

Publishes OnboardingCapability objects to the Registry service,
making them discoverable by agents and operators.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable

from aidn_hypervisor.model_onboarding.models import OnboardingCapability

logger = logging.getLogger(__name__)

CapabilityCallback = Callable[[dict], None]


class OnboardingCapabilityPublisher:
    """Publishes onboarding capability advertisements to the Registry."""

    OBJECT_TYPE = "onboarding_capability"

    def __init__(
        self,
        registry: Any,
        *,
        signing_key: bytes | None = None,
    ) -> None:
        self._registry = registry
        self._signing_key = signing_key
        self._subscribers: dict[str, list[CapabilityCallback]] = {}

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #

    def _serialize_capability(
        self, capability: OnboardingCapability
    ) -> dict:
        """Serialize an OnboardingCapability into a registry record."""
        payload = {
            "node_id": capability.node_id,
            "operator_id": capability.operator_id,
            "can_host_custom_model": capability.can_host_custom_model,
            "supported_providers": [
                p.model_dump() for p in capability.supported_providers
            ],
            "installed_models": [
                m.model_dump() for m in capability.installed_models
            ],
            "resource_limits": (
                capability.resource_limits.model_dump()
                if capability.resource_limits is not None
                else None
            ),
            "created_at": capability.created_at.isoformat(),
            "updated_at": capability.updated_at.isoformat(),
        }

        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()

        return {
            "object_id": f"{self.OBJECT_TYPE}:{capability.node_id}",
            "object_type": self.OBJECT_TYPE,
            "object_version": 1,
            "payload": payload,
            "payload_hash": payload_hash,
            "created_at": capability.created_at.isoformat(),
            "updated_at": capability.updated_at.isoformat(),
            "namespace": "model_onboarding",
        }

    # ------------------------------------------------------------------ #
    # Publication
    # ------------------------------------------------------------------ #

    def publish(self, capability: OnboardingCapability) -> dict | None:
        """Publish a single capability to the registry.

        Returns None if the payload is unchanged (no-op).
        """
        record = self._serialize_capability(capability)

        # Check if already published with same content
        existing = self._registry.get_registry_object(record["object_id"])
        if existing is not None:
            if existing.get("payload_hash") == record["payload_hash"]:
                logger.debug(
                    "Skipping publish for %s — payload unchanged",
                    record["object_id"],
                )
                return None
            record["object_version"] = existing.get("object_version", 1) + 1

        result = self._registry.upsert_registry_object(record)

        # Notify subscribers
        self._notify_subscribers(capability.node_id, record)

        return result

    # ------------------------------------------------------------------ #
    # Query
    # ------------------------------------------------------------------ #

    def query_capability(self, node_id: str) -> dict | None:
        """Query the onboarding capability for a specific node."""
        object_id = f"{self.OBJECT_TYPE}:{node_id}"
        result = self._registry.get_registry_object(object_id)
        if result is None:
            return None
        return result.get("payload")

    def list_capable_nodes(self) -> list[dict]:
        """List all nodes that can host custom models."""
        all_objects = self._registry.list_registry_objects(
            object_type=self.OBJECT_TYPE
        )
        return [
            obj["payload"]
            for obj in all_objects
            if obj.get("payload", {}).get("can_host_custom_model") is True
        ]

    # ------------------------------------------------------------------ #
    # Subscriptions
    # ------------------------------------------------------------------ #

    def subscribe(
        self, node_id: str, callback: CapabilityCallback
    ) -> None:
        """Register a callback for capability changes on a node."""
        if node_id not in self._subscribers:
            self._subscribers[node_id] = []
        self._subscribers[node_id].append(callback)

    def unsubscribe(
        self, node_id: str, callback: CapabilityCallback
    ) -> None:
        """Remove a previously registered callback."""
        callbacks = self._subscribers.get(node_id, [])
        if callback in callbacks:
            callbacks.remove(callback)
            if not callbacks:
                del self._subscribers[node_id]

    def _notify_subscribers(
        self, node_id: str, record: dict
    ) -> None:
        """Notify all subscribers about a capability change."""
        for callback in self._subscribers.get(node_id, []):
            try:
                callback(record.get("payload", {}))
            except Exception:
                logger.exception(
                    "Error notifying subscriber for node %s", node_id
                )
