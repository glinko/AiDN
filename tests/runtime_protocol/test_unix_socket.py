import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from aidn_hypervisor.dispatcher import NetworkMessage, canonical_payload_hash
from aidn_hypervisor.dispatcher.models import canonical_payload_bytes
from aidn_hypervisor.runtime_protocol import (
    UnixSocketRuntimeClient,
    UnixSocketRuntimeListener,
)


def _message() -> NetworkMessage:
    payload = {"event_type": "RUNTIME_HEALTH", "event": {"state": "HEALTHY"}}
    now = datetime.now(timezone.utc)
    return NetworkMessage(
        message_id="unix-socket-message-1",
        message_type="RUNTIME_HEALTH",
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="revision-1",
        connection_id="runtime-connection-1",
        channel_id="runtime-local-ipc",
        channel_class="RUNTIME",
        source_subject={"subject_type": "RUNTIME", "subject_id": "runtime-1"},
        destination_subject={
            "subject_type": "HYPERVISOR_RUNTIME_INGRESS",
            "subject_id": "runtime-1",
        },
        source_sequence=1,
        route_generation=1,
        runtime_generation=1,
        created_at=now.isoformat(),
        expiration=(now + timedelta(minutes=1)).isoformat(),
        payload_hash=canonical_payload_hash(payload),
        payload_length=len(canonical_payload_bytes(payload)),
        payload=payload,
        authentication={"transport": "LOCAL_IPC"},
    )


@pytest.mark.skipif(os.name == "nt", reason="Unix domain socket only")
def test_unix_socket_routes_json_network_messages(tmp_path) -> None:
    received: list[NetworkMessage] = []
    listener = UnixSocketRuntimeListener(
        address=str(tmp_path / f"aidn-runtime-{uuid4().hex}.sock"),
        ingress=lambda message: received.append(message) or {"accepted": message.message_id},
    )
    listener.start()
    try:
        response = UnixSocketRuntimeClient(address=listener.address).send(_message())
    finally:
        listener.stop()

    assert response == {"ok": True, "result": {"accepted": "unix-socket-message-1"}}
    assert [message.message_id for message in received] == ["unix-socket-message-1"]


def test_unix_socket_listener_rejects_windows() -> None:
    if os.name != "nt":
        pytest.skip("Windows-specific guard")

    with pytest.raises(RuntimeError, match="unavailable on Windows"):
        UnixSocketRuntimeListener(address="/tmp/aidn.sock", ingress=lambda message: message)
