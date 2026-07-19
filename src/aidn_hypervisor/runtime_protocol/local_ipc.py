"""Authenticated Local IPC ingress adapter for RFC-0054 Runtime events.

The adapter deliberately owns no socket implementation. A named-pipe, Unix-socket
or process-host transport supplies a validated RFC-0042 envelope to ``receive``.
This keeps every local transport on the same Dispatcher authorization and replay
pipeline as future remote transports.
"""

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from aidn_hypervisor.dispatcher import (
    NetworkMessage,
    bind_runtime_ingress_route,
)
from aidn_hypervisor.providers.models import RuntimeBinding
from aidn_hypervisor.runtime_protocol.models import (
    RuntimeCapacity,
    RuntimeArtifactDeclare,
    RuntimeCancelResult,
    RuntimeHealth,
    RuntimeReady,
    RuntimeResult,
    RuntimeStreamChunk,
    RuntimeStreamClose,
    RuntimeStreamOpen,
    RuntimeStateCheckpoint,
    RuntimeRecoveryState,
    RuntimeDrainStatus,
    RuntimeDrainComplete,
)


RuntimeIngressEventType = Literal[
    "RUNTIME_READY",
    "RUNTIME_HEALTH",
    "RUNTIME_CAPACITY",
    "RUNTIME_RESULT",
    "RUNTIME_CANCEL_RESULT",
    "RUNTIME_STREAM_OPEN",
    "RUNTIME_STREAM_CHUNK",
    "RUNTIME_STREAM_CLOSE",
    "RUNTIME_ARTIFACT_DECLARE",
    "RUNTIME_STATE_CHECKPOINT",
    "RUNTIME_RECOVERY_STATE",
    "RUNTIME_DRAIN_STATUS",
    "RUNTIME_DRAIN_COMPLETE",
]


class LocalIpcRuntimeEvent(BaseModel):
    event_type: RuntimeIngressEventType
    runtime_connection_id: str = Field(min_length=1)
    event: dict


class LocalIpcRuntimeIngress:
    """Route authenticated Local IPC Runtime events through the Dispatcher."""

    def __init__(
        self,
        *,
        dispatcher,
        runtime_protocol_service,
        peer_authenticator: Callable[[NetworkMessage], bool],
    ) -> None:
        self.dispatcher = dispatcher
        self.runtime_protocol_service = runtime_protocol_service
        self.peer_authenticator = peer_authenticator

    def bind_runtime(
        self,
        binding: RuntimeBinding,
        *,
        route_generation: int,
    ):
        return bind_runtime_ingress_route(
            self.dispatcher,
            binding,
            self._handle_event,
            route_generation=route_generation,
        )

    def receive(self, message: NetworkMessage) -> object:
        if message.authentication.get("transport") != "LOCAL_IPC":
            raise ValueError("Runtime ingress requires LOCAL_IPC transport")
        if not self.peer_authenticator(message):
            raise ValueError("Runtime Local IPC peer authentication failed")
        self.dispatcher.submit(message)
        delivered = self.dispatcher.drain_once()
        if delivered is None:
            raise RuntimeError("Runtime Local IPC message was not dispatched")
        return delivered[1]

    def _handle_event(self, payload: dict) -> object:
        envelope = LocalIpcRuntimeEvent.model_validate(payload)
        if envelope.event_type == "RUNTIME_READY":
            return self.runtime_protocol_service.record_runtime_ready(
                envelope.runtime_connection_id,
                RuntimeReady.model_validate(envelope.event),
            )
        if envelope.event_type == "RUNTIME_HEALTH":
            return self.runtime_protocol_service.record_runtime_health(
                envelope.runtime_connection_id,
                RuntimeHealth.model_validate(envelope.event),
            )
        if envelope.event_type == "RUNTIME_RESULT":
            return self.runtime_protocol_service.record_runtime_result(
                envelope.runtime_connection_id,
                RuntimeResult.model_validate(envelope.event),
            )
        if envelope.event_type == "RUNTIME_CANCEL_RESULT":
            return self.runtime_protocol_service.record_runtime_cancel_result(
                envelope.runtime_connection_id,
                RuntimeCancelResult.model_validate(envelope.event),
            )
        if envelope.event_type == "RUNTIME_STREAM_OPEN":
            return self.runtime_protocol_service.record_runtime_stream_open(
                envelope.runtime_connection_id,
                RuntimeStreamOpen.model_validate(envelope.event),
            )
        if envelope.event_type == "RUNTIME_STREAM_CHUNK":
            return self.runtime_protocol_service.record_runtime_stream_chunk(
                envelope.runtime_connection_id,
                RuntimeStreamChunk.model_validate(envelope.event),
            )
        if envelope.event_type == "RUNTIME_STREAM_CLOSE":
            return self.runtime_protocol_service.record_runtime_stream_close(
                envelope.runtime_connection_id,
                RuntimeStreamClose.model_validate(envelope.event),
            )
        if envelope.event_type == "RUNTIME_ARTIFACT_DECLARE":
            return self.runtime_protocol_service.record_runtime_artifact(
                envelope.runtime_connection_id,
                RuntimeArtifactDeclare.model_validate(envelope.event),
            )
        if envelope.event_type == "RUNTIME_STATE_CHECKPOINT":
            return self.runtime_protocol_service.record_runtime_state_checkpoint(
                envelope.runtime_connection_id,
                RuntimeStateCheckpoint.model_validate(envelope.event),
            )
        if envelope.event_type == "RUNTIME_RECOVERY_STATE":
            return self.runtime_protocol_service.record_runtime_recovery_state(
                envelope.runtime_connection_id,
                RuntimeRecoveryState.model_validate(envelope.event),
            )
        if envelope.event_type == "RUNTIME_DRAIN_STATUS":
            return self.runtime_protocol_service.record_runtime_drain_status(
                envelope.runtime_connection_id,
                RuntimeDrainStatus.model_validate(envelope.event),
            )
        if envelope.event_type == "RUNTIME_DRAIN_COMPLETE":
            return self.runtime_protocol_service.record_runtime_drain_complete(
                envelope.runtime_connection_id,
                RuntimeDrainComplete.model_validate(envelope.event),
            )
        return self.runtime_protocol_service.record_runtime_capacity(
            envelope.runtime_connection_id,
            RuntimeCapacity.model_validate(envelope.event),
        )
