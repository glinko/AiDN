"""Evidence collection for an operator-configured Registry replication link."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Any

from .runtime import RegistryReplicationRuntime


class RegistryReplicationAcceptanceError(RuntimeError):
    """The configured peer did not satisfy the requested technical evidence."""


def verify_registry_replication_acceptance(
    *,
    runtime: RegistryReplicationRuntime,
    expected_peer_ids: Iterable[str],
    timeout_seconds: float,
    required_object_ids: Iterable[str] = (),
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Collect bounded technical evidence from an already started runtime.

    A successful result proves configured mTLS transport, the strict signed
    Registry handshake and inventory exchange. It deliberately does not claim
    that peer operators are independent: deployment ownership is an external
    fact that a protocol connection cannot establish by itself.
    """
    if timeout_seconds <= 0:
        raise ValueError("Registry replication acceptance timeout must be positive")
    peer_ids = sorted(set(expected_peer_ids))
    if not peer_ids:
        raise ValueError("Registry replication acceptance requires at least one peer")
    object_ids = sorted(set(required_object_ids))
    if any(not peer_id for peer_id in peer_ids):
        raise ValueError("Registry replication acceptance peer IDs must not be empty")
    if any(not object_id for object_id in object_ids):
        raise ValueError("Registry replication acceptance object IDs must not be empty")
    replicator = runtime.replicator
    if replicator is None:
        raise RegistryReplicationAcceptanceError("Registry replication runtime has no replicator")
    if not runtime.is_running:
        raise RegistryReplicationAcceptanceError("Registry replication runtime is not running")

    deadline = clock() + timeout_seconds
    _wait_for(
        lambda: _authenticated_peers(runtime.status(), peer_ids),
        deadline=deadline,
        clock=clock,
        sleep=sleep,
        failure="Registry replication peers did not complete authenticated transport",
    )
    for peer_id in peer_ids:
        replicator.build_inventory_request(peer_id)
    _wait_for(
        lambda: _inventory_exchanged(runtime.status(), peer_ids),
        deadline=deadline,
        clock=clock,
        sleep=sleep,
        failure="Registry replication peers did not complete inventory exchange",
    )
    if object_ids:
        _wait_for(
            lambda: all(replicator.store.has(object_id) for object_id in object_ids),
            deadline=deadline,
            clock=clock,
            sleep=sleep,
            failure="Registry replication required object was not transferred",
        )
    status = runtime.status()
    states = {
        state["peer_id"]: state
        for state in status["replication_peers"]
        if state["peer_id"] in peer_ids
    }
    return {
        "status": "ok",
        "technical_evidence": {
            "authenticated_peer_ids": peer_ids,
            "inventory_exchanged_peer_ids": peer_ids,
            "required_object_ids": object_ids,
            "peer_states": [states[peer_id] for peer_id in peer_ids],
        },
        "ownership_evidence": {
            "status": "NOT_PROVEN_BY_PROTOCOL",
            "reason": (
                "A signed mTLS Registry connection proves the configured peer identity, "
                "not that its operator is organizationally independent."
            ),
        },
    }


def _wait_for(
    predicate: Callable[[], bool],
    *,
    deadline: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    failure: str,
) -> None:
    while clock() < deadline:
        if predicate():
            return
        sleep(min(0.05, max(0.0, deadline - clock())))
    if predicate():
        return
    raise RegistryReplicationAcceptanceError(failure)


def _authenticated_peers(status: dict[str, Any], peer_ids: list[str]) -> bool:
    peers = {peer["peer_id"]: peer for peer in status["outbound_peers"]}
    return all(peers.get(peer_id, {}).get("authenticated") is True for peer_id in peer_ids)


def _inventory_exchanged(status: dict[str, Any], peer_ids: list[str]) -> bool:
    peers = {peer["peer_id"]: peer for peer in status["replication_peers"]}
    return all(peers.get(peer_id, {}).get("inventory_exchanged") is True for peer_id in peer_ids)
