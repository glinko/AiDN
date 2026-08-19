from typing import TYPE_CHECKING

from aidn_hypervisor.runtime_protocol.models import (
    RuntimeArtifactDeclare,
    RuntimeCancellationRecord,
    RuntimeCancelResult,
    RuntimeCapacity,
    RuntimeConnection,
    RuntimeDrainComplete,
    RuntimeDrainRequest,
    RuntimeDrainStatus,
    RuntimeHealth,
    RuntimeMessage,
    RuntimeReady,
    RuntimeRecoveryPlan,
    RuntimeRecoveryResult,
    RuntimeRecoveryState,
    RuntimeRequestRecord,
    RuntimeResult,
    RuntimeShutdown,
    RuntimeStateCheckpoint,
    RuntimeStreamChunk,
    RuntimeStreamClose,
    RuntimeStreamOpen,
    RuntimeUsageAck,
    RuntimeUsageConflict,
    RuntimeUsageReport,
)

_TERMINAL_REQUEST_STATES = {"COMPLETED", "PARTIAL", "CANCELLED", "FAILED", "EXPIRED", "UNRECOVERABLE"}

if TYPE_CHECKING:
    from aidn_hypervisor.state import HypervisorStateSnapshot


class RuntimeProtocolStore:
    """Durable semantic replay, Request, Usage and recovery state."""

    def __init__(self, state_store=None) -> None:
        self._state_store = state_store
        self.connections: dict[str, RuntimeConnection] = {}
        self.ready_states: dict[str, RuntimeReady] = {}
        self.health_records: dict[str, RuntimeHealth] = {}
        self.capacity_records: dict[str, RuntimeCapacity] = {}
        self.messages: dict[str, RuntimeMessage] = {}
        self.runtime_sequences: dict[str, int] = {}
        self.requests: dict[str, RuntimeRequestRecord] = {}
        self.cancellations: dict[str, RuntimeCancellationRecord] = {}
        self.cancellation_results: dict[str, RuntimeCancelResult] = {}
        self.results: dict[str, RuntimeResult] = {}
        self.streams: dict[str, RuntimeStreamOpen] = {}
        self.stream_chunks: dict[str, dict[int, RuntimeStreamChunk]] = {}
        self.stream_closes: dict[str, RuntimeStreamClose] = {}
        self.artifacts: dict[str, RuntimeArtifactDeclare] = {}
        self.state_checkpoints: dict[str, RuntimeStateCheckpoint] = {}
        self.recovery_states: dict[str, RuntimeRecoveryState] = {}
        self.usage_reports: dict[str, RuntimeUsageReport] = {}
        self.usage_acks: dict[str, RuntimeUsageAck] = {}
        self.usage_conflicts: dict[str, RuntimeUsageConflict] = {}
        self.recovery_plans: dict[str, RuntimeRecoveryPlan] = {}
        self.recovery_results: dict[str, RuntimeRecoveryResult] = {}
        self.drain_requests: dict[str, RuntimeDrainRequest] = {}
        self.drain_statuses: dict[str, RuntimeDrainStatus] = {}
        self.drain_completes: dict[str, RuntimeDrainComplete] = {}
        self.shutdowns: dict[str, RuntimeShutdown] = {}
        self.restore()

    def restore(self, snapshot: "HypervisorStateSnapshot | None" = None) -> None:
        if snapshot is None:
            if self._state_store is None:
                return
            if not hasattr(self._state_store, "load"):
                return
            snapshot = self._state_store.load()
        self.connections = {
            item.runtime_connection_id: item
            for item in snapshot.runtime_protocol_connections
        }
        self.ready_states = {
            item.runtime_id: item for item in snapshot.runtime_protocol_ready_states
        }
        self.health_records = {
            item.runtime_id: item for item in snapshot.runtime_protocol_health_records
        }
        self.capacity_records = {
            item.runtime_id: item
            for item in snapshot.runtime_protocol_capacity_records
        }
        self.messages = {
            item.runtime_message_id: item
            for item in snapshot.runtime_protocol_messages
        }
        self.runtime_sequences = dict(snapshot.runtime_protocol_sequences)
        self.requests = {
            item.request_id: item for item in snapshot.runtime_protocol_requests
        }
        self.cancellations = {
            item.cancellation.cancellation_id: item
            for item in snapshot.runtime_protocol_cancellations
        }
        self.cancellation_results = {
            item.cancellation_id: item
            for item in snapshot.runtime_protocol_cancellation_results
        }
        self.results = {
            item.request_id: item for item in snapshot.runtime_protocol_results
        }
        self.streams = {
            item.stream_id: item for item in snapshot.runtime_protocol_streams
        }
        self.stream_chunks = {}
        for item in snapshot.runtime_protocol_stream_chunks:
            self.stream_chunks.setdefault(item.stream_id, {})[item.chunk_sequence] = item
        self.stream_closes = {
            item.stream_id: item for item in snapshot.runtime_protocol_stream_closes
        }
        self.artifacts = {
            item.artifact_id: item for item in snapshot.runtime_protocol_artifacts
        }
        self.state_checkpoints = {
            self._checkpoint_key(item): item
            for item in snapshot.runtime_protocol_state_checkpoints
        }
        self.recovery_states = {
            item.runtime_id: item for item in snapshot.runtime_protocol_recovery_states
        }
        self.usage_reports = {
            item.usage_report_id: item
            for item in snapshot.runtime_protocol_usage_reports
        }
        self.usage_acks = {
            item.usage_acknowledgment_id: item
            for item in snapshot.runtime_protocol_usage_acks
        }
        self.usage_conflicts = {
            item.conflict_id: item
            for item in snapshot.runtime_protocol_usage_conflicts
        }
        self.recovery_plans = {
            item.plan_id: item for item in snapshot.runtime_protocol_recovery_plans
        }
        self.recovery_results = {
            item.plan_id: item for item in snapshot.runtime_protocol_recovery_results
        }
        self.drain_requests = {
            item.drain_id: item for item in snapshot.runtime_protocol_drain_requests
        }
        self.drain_statuses = {
            item.drain_id: item for item in snapshot.runtime_protocol_drain_statuses
        }
        self.drain_completes = {
            item.drain_id: item for item in snapshot.runtime_protocol_drain_completes
        }
        self.shutdowns = {
            item.shutdown_id: item for item in snapshot.runtime_protocol_shutdowns
        }

    def flush(self) -> None:
        if self._state_store is None:
            return
        if not hasattr(self._state_store, "load") or not hasattr(
            self._state_store, "save"
        ):
            return
        snapshot = self._state_store.load().model_copy(
            update={
                "runtime_protocol_connections": list(self.connections.values()),
                "runtime_protocol_ready_states": list(self.ready_states.values()),
                "runtime_protocol_health_records": list(self.health_records.values()),
                "runtime_protocol_capacity_records": list(
                    self.capacity_records.values()
                ),
                "runtime_protocol_messages": list(self.messages.values()),
                "runtime_protocol_sequences": dict(self.runtime_sequences),
                "runtime_protocol_requests": self._persisted_requests(),
                "runtime_protocol_cancellations": list(self.cancellations.values()),
                "runtime_protocol_cancellation_results": list(
                    self.cancellation_results.values()
                ),
                "runtime_protocol_results": list(self.results.values()),
                "runtime_protocol_streams": list(self.streams.values()),
                "runtime_protocol_stream_chunks": [
                    chunk
                    for chunks in self.stream_chunks.values()
                    for chunk in chunks.values()
                ],
                "runtime_protocol_stream_closes": list(self.stream_closes.values()),
                "runtime_protocol_artifacts": list(self.artifacts.values()),
                "runtime_protocol_state_checkpoints": list(
                    self.state_checkpoints.values()
                ),
                "runtime_protocol_recovery_states": list(
                    self.recovery_states.values()
                ),
                "runtime_protocol_usage_reports": list(self.usage_reports.values()),
                "runtime_protocol_usage_acks": list(self.usage_acks.values()),
                "runtime_protocol_usage_conflicts": list(
                    self.usage_conflicts.values()
                ),
                "runtime_protocol_recovery_plans": list(self.recovery_plans.values()),
                "runtime_protocol_recovery_results": list(
                    self.recovery_results.values()
                ),
                "runtime_protocol_drain_requests": list(self.drain_requests.values()),
                "runtime_protocol_drain_statuses": list(self.drain_statuses.values()),
                "runtime_protocol_drain_completes": list(
                    self.drain_completes.values()
                ),
                "runtime_protocol_shutdowns": list(self.shutdowns.values()),
            }
        )
        self._state_store.save(snapshot)

    def _persisted_requests(self) -> list[RuntimeRequestRecord]:
        """Persist terminal request identity without replaying full transcripts.

        Runtime request hashes, lifecycle fields, and usage evidence remain
        durable and sufficient for replay/finality checks.  The full MCP
        payload is needed only while a request is active; once terminal, a
        stable state reference prevents the shared Hypervisor snapshot from
        growing by the same transcript on every inference turn.
        """

        persisted: list[RuntimeRequestRecord] = []
        for record in self.requests.values():
            if record.request_state not in _TERMINAL_REQUEST_STATES:
                persisted.append(record)
                continue
            request = record.request
            if request.request_payload is None:
                persisted.append(record)
                continue
            compact_request = request.model_copy(
                update={
                    "request_payload": None,
                    "request_payload_reference": (
                        "state://runtime-request/"
                        f"{request.request_id}/{request.request_payload_hash}"
                    ),
                }
            )
            persisted.append(record.model_copy(update={"request": compact_request}))
        return persisted

    @staticmethod
    def _checkpoint_key(checkpoint: RuntimeStateCheckpoint) -> str:
        return (
            f"{checkpoint.runtime_id}:{checkpoint.session_id}:"
            f"{checkpoint.state_generation}:{checkpoint.checkpoint_sequence}"
        )
