import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from aidn_hypervisor.dispatcher import NetworkMessage, canonical_payload_hash
from aidn_hypervisor.dispatcher.models import canonical_payload_bytes
from aidn_hypervisor.runtime_protocol import (
    WindowsNamedPipeRuntimeClient,
    WindowsNamedPipeRuntimeListener,
)


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Named Pipe only")


def _message() -> NetworkMessage:
    payload = {"event_type": "RUNTIME_HEALTH", "event": {"state": "HEALTHY"}}
    now = datetime.now(timezone.utc)
    return NetworkMessage(
        message_id="named-pipe-message-1",
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


def test_windows_named_pipe_routes_json_network_messages() -> None:
    received: list[NetworkMessage] = []
    address = rf"\\.\pipe\aidn-runtime-{uuid4().hex}"
    listener = WindowsNamedPipeRuntimeListener(
        address=address,
        authkey=b"test-runtime-pipe-key",
        ingress=lambda message: received.append(message) or {"accepted": message.message_id},
    )
    listener.start()
    try:
        response = WindowsNamedPipeRuntimeClient(
            address=address,
            authkey=b"test-runtime-pipe-key",
        ).send(_message())
    finally:
        listener.stop()

    assert response == {"ok": True, "result": {"accepted": "named-pipe-message-1"}}
    assert [message.message_id for message in received] == ["named-pipe-message-1"]


def test_windows_named_pipe_rejects_invalid_json_envelope() -> None:
    listener = WindowsNamedPipeRuntimeListener(
        address=rf"\\.\pipe\aidn-runtime-{uuid4().hex}",
        authkey=b"test-runtime-pipe-key",
        ingress=lambda message: message,
    )

    response = listener._handle_payload(b"not-json")

    assert response["ok"] is False
    assert response["error"] == "RUNTIME_LOCAL_IPC_INVALID"
