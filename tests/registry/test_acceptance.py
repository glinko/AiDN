from __future__ import annotations

import pytest

from aidn_hypervisor.registry.acceptance import (
    RegistryReplicationAcceptanceError,
    verify_registry_replication_acceptance,
)


class _Store:
    def __init__(self, object_ids: set[str] | None = None) -> None:
        self._object_ids = object_ids or set()

    def has(self, object_id: str) -> bool:
        return object_id in self._object_ids


class _Replicator:
    def __init__(self) -> None:
        self.store = _Store({"object-from-peer"})
        self.inventory_requests: list[str] = []

    def build_inventory_request(self, peer_id: str) -> None:
        self.inventory_requests.append(peer_id)


class _Runtime:
    def __init__(self, *, authenticated: bool = True, inventory_exchanged: bool = True) -> None:
        self.is_running = True
        self.replicator = _Replicator()
        self._authenticated = authenticated
        self._inventory_exchanged = inventory_exchanged

    def status(self) -> dict:
        return {
            "outbound_peers": [
                {"peer_id": "registry-independent", "authenticated": self._authenticated}
            ],
            "replication_peers": [
                {
                    "peer_id": "registry-independent",
                    "inventory_exchanged": self._inventory_exchanged,
                    "objects_transferred": 1,
                }
            ],
        }


def test_acceptance_requires_authenticated_inventory_and_can_require_object() -> None:
    runtime = _Runtime()

    result = verify_registry_replication_acceptance(
        runtime=runtime,
        expected_peer_ids=["registry-independent"],
        required_object_ids=["object-from-peer"],
        timeout_seconds=1,
    )

    assert runtime.replicator.inventory_requests == ["registry-independent"]
    assert result["status"] == "ok"
    assert result["technical_evidence"]["required_object_ids"] == ["object-from-peer"]
    assert result["ownership_evidence"]["status"] == "NOT_PROVEN_BY_PROTOCOL"


def test_acceptance_does_not_treat_an_unverified_transport_as_evidence() -> None:
    runtime = _Runtime(authenticated=False)

    with pytest.raises(
        RegistryReplicationAcceptanceError,
        match="did not complete authenticated transport",
    ):
        verify_registry_replication_acceptance(
            runtime=runtime,
            expected_peer_ids=["registry-independent"],
            timeout_seconds=0.001,
        )


def test_acceptance_rejects_empty_peer_set() -> None:
    with pytest.raises(ValueError, match="at least one peer"):
        verify_registry_replication_acceptance(
            runtime=_Runtime(),
            expected_peer_ids=[],
            timeout_seconds=1,
        )
