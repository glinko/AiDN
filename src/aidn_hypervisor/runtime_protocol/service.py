from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel

from aidn_hypervisor.accounting.models import AccountingContract, RuntimeUsageProfile
from aidn_hypervisor.dispatcher.models import DispatcherRoute
from aidn_hypervisor.providers.models import RuntimeBinding
from aidn_hypervisor.runtime_protocol.models import (
    HypervisorRuntimeHello,
    RuntimeArtifactDeclare,
    RuntimeCancellationRecord,
    RuntimeCancelRequest,
    RuntimeCancelResult,
    RuntimeCapacity,
    RuntimeConnection,
    RuntimeDrainComplete,
    RuntimeDrainRequest,
    RuntimeDrainStatus,
    RuntimeExecuteRequest,
    RuntimeHealth,
    RuntimeHello,
    RuntimeHelloComplete,
    RuntimeMessage,
    RuntimeReady,
    RuntimeRecoveryPlan,
    RuntimeRecoveryResult,
    RuntimeRecoveryState,
    RuntimeRequestAccept,
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
    canonical_hash,
)
from aidn_hypervisor.runtime_protocol.store import RuntimeProtocolStore


class RuntimeProtocolError(ValueError):
    def __init__(self, code: str, stage: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage


class RuntimeProtocolService:
    """RFC-0054 execution control independent from Provider management."""

    def __init__(
        self,
        *,
        hypervisor_id: str,
        network_revision: str,
        binding_resolver: Callable[[str], RuntimeBinding],
        route_resolver: Callable[[str], DispatcherRoute | None],
        runtime_authenticator: Callable[[BaseModel], bool],
        hypervisor_signer: Callable[[dict], str],
        request_authorizer: Callable[[RuntimeExecuteRequest], bool],
        accounting_contract_resolver: Callable[[str], AccountingContract],
        usage_profile_resolver: Callable[[str], RuntimeUsageProfile],
        store: RuntimeProtocolStore | None = None,
        supported_protocol_versions: tuple[str, ...] = ("1.0",),
        connection_lifetime_seconds: int = 3600,
    ) -> None:
        if not supported_protocol_versions:
            raise ValueError("supported_protocol_versions must not be empty")
        if connection_lifetime_seconds <= 0:
            raise ValueError("connection_lifetime_seconds must be positive")
        self.hypervisor_id = hypervisor_id
        self.network_revision = network_revision
        self.binding_resolver = binding_resolver
        self.route_resolver = route_resolver
        self.runtime_authenticator = runtime_authenticator
        self.hypervisor_signer = hypervisor_signer
        self.request_authorizer = request_authorizer
        self.accounting_contract_resolver = accounting_contract_resolver
        self.usage_profile_resolver = usage_profile_resolver
        self.store = store or RuntimeProtocolStore()
        self.supported_protocol_versions = supported_protocol_versions
        self.connection_lifetime_seconds = connection_lifetime_seconds
        self._pending_handshakes: dict[str, tuple[RuntimeHello, HypervisorRuntimeHello]] = {}

    def begin_handshake(self, hello: RuntimeHello) -> HypervisorRuntimeHello:
        if not self.runtime_authenticator(hello):
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID",
                "identity",
                "Runtime Hello authentication failed",
            )
        binding = self._binding(hello.runtime_id)
        route = self._route(hello.runtime_id)
        self._validate_hello_binding(hello, binding, route)
        selected_protocol = self._select_protocol_version(
            hello.supported_runtime_protocol_versions
        )
        handshake_id = f"rth-{uuid4().hex}"
        challenge = f"challenge-{uuid4().hex}"
        response_payload = {
            "handshake_id": handshake_id,
            "runtime_id": binding.runtime_id,
            "accepted_runtime_generation": binding.runtime_generation,
            "accepted_runtime_configuration_hash": binding.runtime_configuration_hash,
            "runtime_binding_hash": binding.binding_hash(),
            "selected_runtime_protocol_version": selected_protocol,
            "selected_capability_version": binding.capability_version,
            "selected_capability_definition_hash": binding.capability_definition_hash,
            "route_generation": route.route_generation,
            "granted_route_scope": binding.dispatcher_route_scope,
            "network_revision": self.network_revision,
            "hypervisor_command_sequence": hello.last_hypervisor_command_sequence,
            "runtime_challenge_response": self.challenge_response(
                hello.runtime_challenge
            ),
            "hypervisor_challenge": challenge,
            "recovery_directive": (
                "RECONCILE"
                if hello.recovery_state_available
                or self.store.runtime_sequences.get(hello.runtime_id, 0)
                != hello.last_runtime_event_sequence
                else "NONE"
            ),
        }
        response = HypervisorRuntimeHello(
            **response_payload,
            hypervisor_signature=self.hypervisor_signer(response_payload),
        )
        self._pending_handshakes[handshake_id] = (hello, response)
        return response

    def complete_handshake(self, complete: RuntimeHelloComplete) -> RuntimeConnection:
        pending = self._pending_handshakes.get(complete.handshake_id)
        if pending is None:
            raise RuntimeProtocolError(
                "RUNTIME_HANDSHAKE_INVALID",
                "handshake",
                "Unknown or expired Runtime handshake",
            )
        hello, response = pending
        if not self.runtime_authenticator(complete):
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID",
                "identity",
                "Runtime Hello completion authentication failed",
            )
        if complete.runtime_id != hello.runtime_id:
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID", "identity", "Runtime ID changed during handshake"
            )
        if complete.runtime_generation != response.accepted_runtime_generation:
            raise RuntimeProtocolError(
                "RUNTIME_GENERATION_MISMATCH",
                "configuration",
                "Runtime Generation changed during handshake",
            )
        if complete.route_generation != response.route_generation:
            raise RuntimeProtocolError(
                "RUNTIME_ROUTE_GENERATION_MISMATCH",
                "route",
                "Route Generation changed during handshake",
            )
        if complete.hypervisor_challenge_response != self.challenge_response(
            response.hypervisor_challenge
        ):
            raise RuntimeProtocolError(
                "RUNTIME_HANDSHAKE_INVALID",
                "handshake",
                "Hypervisor challenge response is invalid",
            )
        route = self._route(complete.runtime_id)
        binding = self._binding(complete.runtime_id)
        self._validate_hello_binding(hello, binding, route)
        if route.route_generation != complete.route_generation:
            raise RuntimeProtocolError(
                "RUNTIME_ROUTE_GENERATION_MISMATCH",
                "route",
                "Runtime route changed before handshake completion",
            )

        now = datetime.now(UTC)
        for connection_id, connection in list(self.store.connections.items()):
            if (
                connection.runtime_id == complete.runtime_id
                and connection.connection_state not in {"CLOSED", "REJECTED"}
            ):
                self.store.connections[connection_id] = connection.model_copy(
                    update={"connection_state": "CLOSED"}
                )
        connection = RuntimeConnection(
            runtime_connection_id=f"rtc-{uuid4().hex}",
            runtime_id=complete.runtime_id,
            runtime_generation=complete.runtime_generation,
            runtime_configuration_hash=response.accepted_runtime_configuration_hash,
            runtime_binding_hash=response.runtime_binding_hash,
            instance_id=hello.instance_id,
            route_generation=complete.route_generation,
            selected_runtime_protocol_version=response.selected_runtime_protocol_version,
            connection_state=(
                "RECOVERING" if response.recovery_directive == "RECONCILE" else "READY"
            ),
            established_at=now.isoformat(),
            expires_at=(
                now + timedelta(seconds=self.connection_lifetime_seconds)
            ).isoformat(),
        )
        self.store.connections[connection.runtime_connection_id] = connection
        self.store.flush()
        del self._pending_handshakes[complete.handshake_id]
        return connection

    def record_runtime_message(self, message: RuntimeMessage) -> RuntimeMessage:
        self._validate_connection(
            message.runtime_connection_id,
            runtime_id=message.runtime_id,
            runtime_generation=message.runtime_generation,
            runtime_configuration_hash=message.runtime_configuration_hash,
            route_generation=message.route_generation,
            allow_recovering=True,
        )
        if datetime.fromisoformat(message.expiration) <= datetime.now(UTC):
            raise RuntimeProtocolError(
                "RUNTIME_MESSAGE_EXPIRED", "message", "Runtime message expired"
            )
        existing = self.store.messages.get(message.runtime_message_id)
        if existing is not None:
            if existing.payload_hash != message.payload_hash:
                raise RuntimeProtocolError(
                    "RUNTIME_MESSAGE_REPLAYED",
                    "replay",
                    "Runtime Message ID conflicts with existing semantic content",
                )
            return existing
        expected_sequence = self.store.runtime_sequences.get(message.runtime_id, 0) + 1
        if message.runtime_sequence != expected_sequence:
            raise RuntimeProtocolError(
                "RUNTIME_SEQUENCE_INVALID",
                "sequence",
                f"Expected Runtime sequence {expected_sequence}",
            )
        self.store.messages[message.runtime_message_id] = message.model_copy(deep=True)
        self.store.runtime_sequences[message.runtime_id] = message.runtime_sequence
        self.store.flush()
        return message

    def record_runtime_ready(
        self,
        runtime_connection_id: str,
        ready: RuntimeReady,
    ) -> RuntimeReady:
        if not self.runtime_authenticator(ready):
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID",
                "ready",
                "Runtime Ready authentication failed",
            )
        connection = self._validate_connection(
            runtime_connection_id,
            runtime_id=ready.runtime_id,
            runtime_generation=ready.runtime_generation,
            runtime_configuration_hash=ready.runtime_configuration_hash,
            route_generation=ready.route_generation,
            allow_recovering=True,
        )
        binding = self._binding(ready.runtime_id)
        if ready.capability_definition_hash != binding.capability_definition_hash:
            raise RuntimeProtocolError(
                "RUNTIME_CAPABILITY_DEFINITION_MISMATCH",
                "ready",
                "Runtime Ready Capability Definition mismatch",
            )
        if (
            ready.usage_profile_hash is not None
            and ready.usage_profile_hash != binding.usage_reporting_profile_hash
        ):
            raise RuntimeProtocolError(
                "USAGE_PROFILE_MISMATCH",
                "ready",
                "Runtime Ready Usage Profile mismatch",
            )
        if ready.operational_state != "READY" or not ready.readiness_dimensions.is_ready():
            raise RuntimeProtocolError(
                "RUNTIME_NOT_READY",
                "ready",
                "Runtime Ready requires operational READY and all readiness dimensions",
            )
        existing = self.store.ready_states.get(ready.runtime_id)
        if existing is not None and existing == ready:
            return existing
        self.store.ready_states[ready.runtime_id] = ready.model_copy(deep=True)
        if connection.connection_state != "READY":
            self.store.connections[runtime_connection_id] = connection.model_copy(
                update={"connection_state": "READY"}
            )
        self.store.flush()
        return ready

    def record_runtime_health(
        self,
        runtime_connection_id: str,
        health: RuntimeHealth,
    ) -> RuntimeHealth:
        if not self.runtime_authenticator(health):
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID",
                "health",
                "Runtime Health authentication failed",
            )
        self._validate_connection(
            runtime_connection_id,
            runtime_id=health.runtime_id,
            runtime_generation=health.runtime_generation,
            runtime_configuration_hash=health.runtime_configuration_hash,
            route_generation=health.route_generation,
            allow_recovering=True,
        )
        existing = self.store.health_records.get(health.runtime_id)
        if existing is not None:
            if health.health_sequence < existing.health_sequence:
                raise RuntimeProtocolError(
                    "RUNTIME_HEALTH_SEQUENCE_INVALID",
                    "health",
                    "Runtime Health sequence is stale",
                )
            if health.health_sequence == existing.health_sequence:
                if health == existing:
                    return existing
                raise RuntimeProtocolError(
                    "RUNTIME_HEALTH_CONFLICT",
                    "health",
                    "Runtime Health sequence conflicts with existing record",
                )
        self.store.health_records[health.runtime_id] = health.model_copy(deep=True)
        self.store.flush()
        return health

    def record_runtime_capacity(
        self,
        runtime_connection_id: str,
        capacity: RuntimeCapacity,
    ) -> RuntimeCapacity:
        if not self.runtime_authenticator(capacity):
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID",
                "capacity",
                "Runtime Capacity authentication failed",
            )
        self._validate_connection(
            runtime_connection_id,
            runtime_id=capacity.runtime_id,
            runtime_generation=capacity.runtime_generation,
            runtime_configuration_hash=capacity.runtime_configuration_hash,
            route_generation=capacity.route_generation,
            allow_recovering=True,
        )
        existing = self.store.capacity_records.get(capacity.runtime_id)
        if existing is not None:
            if capacity.capacity_sequence < existing.capacity_sequence:
                raise RuntimeProtocolError(
                    "RUNTIME_CAPACITY_SEQUENCE_INVALID",
                    "capacity",
                    "Runtime Capacity sequence is stale",
                )
            if capacity.capacity_sequence == existing.capacity_sequence:
                if capacity == existing:
                    return existing
                raise RuntimeProtocolError(
                    "RUNTIME_CAPACITY_CONFLICT",
                    "capacity",
                    "Runtime Capacity sequence conflicts with existing record",
                )
        self.store.capacity_records[capacity.runtime_id] = capacity.model_copy(deep=True)
        self.store.flush()
        return capacity

    def register_execute_request(
        self,
        runtime_connection_id: str,
        request: RuntimeExecuteRequest,
    ) -> RuntimeRequestRecord:
        self._validate_connection(
            runtime_connection_id,
            runtime_id=request.runtime_id,
            runtime_generation=request.runtime_generation,
            runtime_configuration_hash=request.runtime_configuration_hash,
            route_generation=request.route_generation,
        )
        binding = self._binding(request.runtime_id)
        if not self.request_authorizer(request):
            raise RuntimeProtocolError(
                "RUNTIME_SESSION_NOT_AUTHORIZED",
                "request",
                "Endpoint, Session or Accounting binding is not authorized",
            )
        if request.capability_id != binding.capability_id:
            raise RuntimeProtocolError(
                "RUNTIME_CAPABILITY_MISMATCH", "request", "Capability ID mismatch"
            )
        if request.capability_version != binding.capability_version:
            raise RuntimeProtocolError(
                "RUNTIME_CAPABILITY_MISMATCH", "request", "Capability version mismatch"
            )
        if request.capability_definition_hash != binding.capability_definition_hash:
            raise RuntimeProtocolError(
                "RUNTIME_CAPABILITY_DEFINITION_MISMATCH",
                "request",
                "Capability Definition Hash mismatch",
            )
        contract = self._accounting_contract(request.accounting_contract_hash)
        profile = self._usage_profile(request.runtime_id)
        self._validate_accounting_compatibility(
            request=request,
            binding=binding,
            contract=contract,
            profile=profile,
        )
        unsupported = set(request.required_features) - set(binding.supported_features)
        if unsupported:
            raise RuntimeProtocolError(
                "RUNTIME_REQUIRED_FEATURE_UNAVAILABLE",
                "request",
                "Required Runtime features are unavailable",
            )
        if datetime.fromisoformat(request.request_deadline) <= datetime.now(UTC):
            raise RuntimeProtocolError(
                "RUNTIME_REQUEST_EXPIRED", "request", "Request deadline expired"
            )
        if request.state_reference is not None:
            self._validate_request_state_reference(request)
        request_hash = request.semantic_hash()
        existing = self.store.requests.get(request.request_id)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise RuntimeProtocolError(
                    "RUNTIME_REQUEST_CONFLICT",
                    "request",
                    "Request ID conflicts with existing semantic content",
                )
            return existing
        record = RuntimeRequestRecord(
            request_id=request.request_id,
            runtime_id=request.runtime_id,
            runtime_generation=request.runtime_generation,
            route_generation=request.route_generation,
            request_hash=request_hash,
            request=request,
            request_state="SUBMITTED",
            updated_at=datetime.now(UTC).isoformat(),
        )
        self.store.requests[request.request_id] = record
        self.store.flush()
        return record

    def record_request_accept(
        self,
        runtime_connection_id: str,
        acceptance: RuntimeRequestAccept,
    ) -> RuntimeRequestRecord:
        self._validate_connection(
            runtime_connection_id,
            runtime_id=acceptance.runtime_id,
            runtime_generation=acceptance.runtime_generation,
            route_generation=acceptance.route_generation,
        )
        record = self.store.requests.get(acceptance.request_id)
        if record is None:
            raise RuntimeProtocolError(
                "RUNTIME_REQUEST_NOT_FOUND", "request", "Unknown Runtime Request"
            )
        if acceptance.session_id != record.request.session_id:
            raise RuntimeProtocolError(
                "RUNTIME_SESSION_NOT_AUTHORIZED",
                "request",
                "Request acceptance Session mismatch",
            )
        if (
            acceptance.accepted_capability_definition_hash
            != record.request.capability_definition_hash
        ):
            raise RuntimeProtocolError(
                "RUNTIME_CAPABILITY_DEFINITION_MISMATCH",
                "request",
                "Request acceptance Capability Definition mismatch",
            )
        state = {
            "ACCEPTED": "ACCEPTED",
            "QUEUED": "QUEUED",
            "RECOVERY_REQUIRED": "RECOVERING",
        }.get(acceptance.admission_state, "FAILED")
        updated = record.model_copy(
            update={
                "request_state": state,
                "admission_state": acceptance.admission_state,
                "runtime_request_handle": acceptance.runtime_request_handle,
                "accepted_at": acceptance.accepted_at,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        self.store.requests[record.request_id] = updated
        self.store.flush()
        return updated

    def record_usage_report(
        self,
        runtime_connection_id: str,
        report: RuntimeUsageReport,
    ) -> RuntimeUsageAck:
        self._validate_connection(
            runtime_connection_id,
            runtime_id=report.runtime_id,
            runtime_generation=report.runtime_generation,
            runtime_configuration_hash=report.runtime_configuration_hash,
            allow_recovering=True,
        )
        if not self.runtime_authenticator(report):
            raise RuntimeProtocolError(
                "RUNTIME_USAGE_REPORT_INVALID",
                "usage",
                "Usage Report authentication failed",
            )
        request = self.store.requests.get(report.request_id)
        if request is None or request.request.session_id != report.session_id:
            raise RuntimeProtocolError(
                "RUNTIME_REQUEST_NOT_FOUND", "usage", "Usage Report Request is unknown"
            )
        if request.admission_state not in {"ACCEPTED", "QUEUED"}:
            return self._usage_ack(
                report,
                status="REJECTED",
                rejection_code="USAGE_REPORT_BEFORE_REQUEST_ACCEPTANCE",
            )
        if (
            report.endpoint_id != request.request.endpoint_id
            or report.endpoint_configuration_hash
            != request.request.endpoint_configuration_hash
            or (
                report.effective_terms_hash is not None
                and report.effective_terms_hash
                != request.request.effective_terms_hash
            )
            or report.accounting_contract_hash
            != request.request.accounting_contract_hash
        ):
            return self._usage_ack(
                report,
                status="REJECTED",
                rejection_code="USAGE_REPORT_IDENTITY_MISMATCH",
            )
        profile = self._usage_profile(report.runtime_id)
        profile_dimensions = {item.dimension_id: item for item in profile.dimensions}
        seen_dimensions: set[str] = set()
        for dimension in report.dimensions:
            if dimension.dimension_id in seen_dimensions:
                return self._usage_ack(
                    report,
                    status="REJECTED",
                    rejection_code="USAGE_DIMENSION_DUPLICATE",
                )
            seen_dimensions.add(dimension.dimension_id)
            declared = profile_dimensions.get(dimension.dimension_id)
            if declared is None or declared.unit != dimension.unit:
                return self._usage_ack(
                    report,
                    status="REJECTED",
                    rejection_code="USAGE_PROFILE_MISMATCH",
                )
            if (
                dimension.authority is not None
                and declared.authority is not None
                and dimension.authority != declared.authority
            ):
                return self._usage_ack(
                    report,
                    status="REJECTED",
                    rejection_code="USAGE_AUTHORITY_INVALID",
                )
            if dimension.billing_eligible and not declared.billing_eligible:
                return self._usage_ack(
                    report,
                    status="REJECTED",
                    rejection_code="USAGE_BILLING_ELIGIBILITY_INVALID",
                )
            if dimension.cumulative != declared.cumulative:
                return self._usage_ack(
                    report,
                    status="REJECTED",
                    rejection_code="USAGE_CUMULATIVE_SEMANTICS_INVALID",
                )
        existing = self.store.usage_reports.get(report.usage_report_id)
        if existing is not None:
            if existing.report_hash != report.report_hash:
                self._record_usage_conflict(
                    report,
                    accepted_report_hash=existing.report_hash,
                    conflict_type="CONTENT",
                )
                return self._usage_ack(
                    report,
                    status="CONFLICT",
                    accepted_sequence=existing.usage_sequence,
                    accepted_hash=existing.report_hash,
                    rejection_code="USAGE_REPORT_CONFLICT",
                )
            return self._usage_ack(
                report,
                status="DUPLICATE",
                accepted_sequence=existing.usage_sequence,
                accepted_hash=existing.report_hash,
            )
        request_reports = sorted(
            (
                item
                for item in self.store.usage_reports.values()
                if item.request_id == report.request_id
            ),
            key=lambda item: item.usage_sequence,
        )
        expected_sequence = len(request_reports) + 1
        previous_hash = request_reports[-1].report_hash if request_reports else None
        same_sequence = next(
            (
                item
                for item in request_reports
                if item.usage_sequence == report.usage_sequence
            ),
            None,
        )
        if same_sequence is not None:
            self._record_usage_conflict(
                report,
                accepted_report_hash=same_sequence.report_hash,
                conflict_type="SEQUENCE",
            )
            return self._usage_ack(
                report,
                status="CONFLICT",
                accepted_sequence=same_sequence.usage_sequence,
                accepted_hash=same_sequence.report_hash,
                rejection_code="USAGE_CHAIN_CONFLICT",
            )
        if report.usage_sequence != expected_sequence:
            self._record_usage_conflict(
                report,
                accepted_report_hash=previous_hash,
                conflict_type="SEQUENCE",
            )
            return self._usage_ack(
                report,
                status="OUT_OF_SEQUENCE",
                accepted_sequence=(request_reports[-1].usage_sequence if request_reports else None),
                accepted_hash=previous_hash,
                rejection_code="USAGE_SEQUENCE_INVALID",
            )
        if report.previous_usage_report_hash != previous_hash:
            self._record_usage_conflict(
                report,
                accepted_report_hash=previous_hash,
                conflict_type="CHAIN",
            )
            return self._usage_ack(
                report,
                status="OUT_OF_SEQUENCE",
                accepted_sequence=(request_reports[-1].usage_sequence if request_reports else None),
                accepted_hash=previous_hash,
                rejection_code="USAGE_CHAIN_HASH_MISMATCH",
            )
        ack = self._usage_ack(
            report,
            status="ACCEPTED",
            accepted_sequence=report.usage_sequence,
            accepted_hash=report.report_hash,
        )
        self.store.usage_reports[report.usage_report_id] = report.model_copy(deep=True)
        self.store.usage_acks[ack.usage_acknowledgment_id] = ack
        self.store.flush()
        return ack

    def request_runtime_cancellation(
        self,
        runtime_connection_id: str,
        cancellation: RuntimeCancelRequest,
    ) -> RuntimeCancelRequest:
        """Persist a Hypervisor cancellation command before it reaches the Runtime."""
        self._validate_connection(
            runtime_connection_id,
            runtime_id=cancellation.runtime_id,
            runtime_generation=cancellation.runtime_generation,
            runtime_configuration_hash=cancellation.runtime_configuration_hash,
            route_generation=cancellation.route_generation,
        )
        record = self.store.requests.get(cancellation.request_id)
        if record is None:
            raise RuntimeProtocolError(
                "RUNTIME_REQUEST_NOT_FOUND", "cancellation", "Unknown Runtime Request"
            )
        if (
            record.request.session_id != cancellation.session_id
            or record.runtime_id != cancellation.runtime_id
            or record.runtime_generation != cancellation.runtime_generation
            or record.route_generation != cancellation.route_generation
            or record.request.runtime_configuration_hash
            != cancellation.runtime_configuration_hash
        ):
            raise RuntimeProtocolError(
                "RUNTIME_CANCELLATION_FAILED",
                "cancellation",
                "Cancellation identity does not match accepted Request",
            )
        if "cancellation" not in self._binding(cancellation.runtime_id).supported_features:
            raise RuntimeProtocolError(
                "RUNTIME_CANCELLATION_UNSUPPORTED",
                "cancellation",
                "Runtime Binding does not declare cancellation support",
            )
        if datetime.fromisoformat(cancellation.deadline) <= datetime.now(UTC):
            raise RuntimeProtocolError(
                "RUNTIME_CANCELLATION_TOO_LATE",
                "cancellation",
                "Cancellation deadline has expired",
            )
        terminal_states = {
            "COMPLETED",
            "PARTIAL",
            "CANCELLED",
            "FAILED",
            "EXPIRED",
            "UNRECOVERABLE",
        }
        if record.request_state in terminal_states:
            raise RuntimeProtocolError(
                "RUNTIME_CANCELLATION_TOO_LATE",
                "cancellation",
                "Runtime Request is already terminal",
            )
        existing = self.store.cancellations.get(cancellation.cancellation_id)
        if existing is not None:
            if existing.cancellation.cancellation_hash != cancellation.cancellation_hash:
                raise RuntimeProtocolError(
                    "RUNTIME_CANCELLATION_FAILED",
                    "cancellation",
                    "Cancellation ID conflicts with existing command",
                )
            return existing.cancellation
        if any(
            item.cancellation.request_id == cancellation.request_id
            and item.cancellation.cancellation_id not in self.store.cancellation_results
            for item in self.store.cancellations.values()
        ):
            raise RuntimeProtocolError(
                "RUNTIME_CANCELLATION_FAILED",
                "cancellation",
                "Runtime Request already has a pending cancellation",
            )
        self.store.cancellations[cancellation.cancellation_id] = RuntimeCancellationRecord(
            cancellation=cancellation.model_copy(deep=True),
            request_state_before_cancel=record.request_state,
            updated_at=datetime.now(UTC).isoformat(),
        )
        self.store.requests[cancellation.request_id] = record.model_copy(
            update={
                "request_state": "CANCEL_REQUESTED",
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        self.store.flush()
        return cancellation

    def record_runtime_cancel_result(
        self,
        runtime_connection_id: str,
        result: RuntimeCancelResult,
    ) -> RuntimeCancelResult:
        if not self.runtime_authenticator(result):
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID",
                "cancellation",
                "Runtime Cancel Result authentication failed",
            )
        cancellation_record = self.store.cancellations.get(result.cancellation_id)
        if cancellation_record is None:
            raise RuntimeProtocolError(
                "RUNTIME_CANCELLATION_FAILED",
                "cancellation",
                "Unknown Runtime cancellation command",
            )
        cancellation = cancellation_record.cancellation
        self._validate_connection(
            runtime_connection_id,
            runtime_id=result.runtime_id,
            runtime_generation=result.runtime_generation,
            runtime_configuration_hash=result.runtime_configuration_hash,
            route_generation=result.route_generation,
            allow_recovering=True,
        )
        if (
            result.runtime_id != cancellation.runtime_id
            or result.runtime_generation != cancellation.runtime_generation
            or result.runtime_configuration_hash
            != cancellation.runtime_configuration_hash
            or result.route_generation != cancellation.route_generation
            or result.session_id != cancellation.session_id
            or result.request_id != cancellation.request_id
        ):
            raise RuntimeProtocolError(
                "RUNTIME_CANCELLATION_FAILED",
                "cancellation",
                "Runtime Cancel Result identity does not match cancellation command",
            )
        existing = self.store.cancellation_results.get(result.cancellation_id)
        if existing is not None:
            if existing.cancellation_result_hash != result.cancellation_result_hash:
                raise RuntimeProtocolError(
                    "RUNTIME_CANCELLATION_FAILED",
                    "cancellation",
                    "Runtime Cancel Result conflicts with accepted result",
                )
            return existing
        if result.cancellation_state in {
            "CANCELLATION_TOO_LATE",
            "CANCELLATION_UNSUPPORTED",
            "ALREADY_TERMINAL",
            "FAILED",
        }:
            request = self.store.requests[result.request_id]
            if request.request_state == "CANCEL_REQUESTED":
                self.store.requests[result.request_id] = request.model_copy(
                    update={
                        "request_state": cancellation_record.request_state_before_cancel,
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                )
        self.store.cancellation_results[result.cancellation_id] = result.model_copy(
            deep=True
        )
        self.store.flush()
        return result

    def record_runtime_stream_open(
        self,
        runtime_connection_id: str,
        stream: RuntimeStreamOpen,
    ) -> RuntimeStreamOpen:
        self._validate_stream_event(
            runtime_connection_id,
            stream,
            stage="stream",
        )
        if "streaming" not in self._binding(stream.runtime_id).supported_features:
            raise RuntimeProtocolError(
                "RUNTIME_REQUIRED_FEATURE_UNAVAILABLE",
                "stream",
                "Runtime Binding does not declare streaming support",
            )
        existing = self.store.streams.get(stream.stream_id)
        if existing is not None:
            if existing.stream_open_hash != stream.stream_open_hash:
                raise RuntimeProtocolError(
                    "RUNTIME_STREAM_SEQUENCE_CONFLICT",
                    "stream",
                    "Stream ID conflicts with existing Stream Open",
                )
            return existing
        self.store.streams[stream.stream_id] = stream.model_copy(deep=True)
        self.store.flush()
        return stream

    def record_runtime_stream_chunk(
        self,
        runtime_connection_id: str,
        chunk: RuntimeStreamChunk,
    ) -> RuntimeStreamChunk:
        stream = self._validate_stream_event(
            runtime_connection_id,
            chunk,
            stage="stream",
            require_open=True,
        )
        if chunk.stream_id in self.store.stream_closes:
            raise RuntimeProtocolError(
                "RUNTIME_STREAM_INTERRUPTED",
                "stream",
                "Stream is already closed",
            )
        chunks = self.store.stream_chunks.setdefault(chunk.stream_id, {})
        existing = chunks.get(chunk.chunk_sequence)
        if existing is not None:
            if existing == chunk:
                return existing
            raise RuntimeProtocolError(
                "RUNTIME_STREAM_SEQUENCE_CONFLICT",
                "stream",
                "Stream Chunk conflicts with an existing sequence",
            )
        if stream.ordering_model == "STRICT_ORDERED":
            expected_sequence = max(chunks, default=0) + 1
            if chunk.chunk_sequence != expected_sequence:
                raise RuntimeProtocolError(
                    "RUNTIME_STREAM_SEQUENCE_INVALID",
                    "stream",
                    "Strictly ordered Stream Chunk sequence is invalid",
                )
        chunks[chunk.chunk_sequence] = chunk.model_copy(deep=True)
        self.store.flush()
        return chunk

    def record_runtime_stream_close(
        self,
        runtime_connection_id: str,
        close: RuntimeStreamClose,
    ) -> RuntimeStreamClose:
        stream = self._validate_stream_event(
            runtime_connection_id,
            close,
            stage="stream",
            require_open=True,
        )
        existing = self.store.stream_closes.get(close.stream_id)
        if existing is not None:
            if existing.stream_close_hash != close.stream_close_hash:
                raise RuntimeProtocolError(
                    "RUNTIME_STREAM_SEQUENCE_CONFLICT",
                    "stream",
                    "Stream Close conflicts with the accepted terminal event",
                )
            return existing
        chunks = self.store.stream_chunks.get(close.stream_id, {})
        if close.final_sequence != max(chunks, default=0):
            raise RuntimeProtocolError(
                "RUNTIME_STREAM_SEQUENCE_INVALID",
                "stream",
                "Stream Close final sequence does not match received chunks",
            )
        if stream.ordering_model == "STRICT_ORDERED" and set(chunks) != set(
            range(1, close.final_sequence + 1)
        ):
            raise RuntimeProtocolError(
                "RUNTIME_STREAM_SEQUENCE_INVALID",
                "stream",
                "Strictly ordered Stream has a sequence gap",
            )
        delivered_length = sum(item.chunk_length for item in chunks.values())
        if close.delivered_length != delivered_length:
            raise RuntimeProtocolError(
                "RUNTIME_STREAM_HASH_MISMATCH",
                "stream",
                "Stream Close delivered length does not match chunks",
            )
        if close.final_content_root != self._stream_root(close.stream_id, chunks):
            raise RuntimeProtocolError(
                "RUNTIME_STREAM_HASH_MISMATCH",
                "stream",
                "Stream Close content root does not match chunks",
            )
        self.store.stream_closes[close.stream_id] = close.model_copy(deep=True)
        self.store.flush()
        return close

    def record_runtime_artifact(
        self,
        runtime_connection_id: str,
        artifact: RuntimeArtifactDeclare,
    ) -> RuntimeArtifactDeclare:
        if not self.runtime_authenticator(artifact):
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID",
                "artifact",
                "Runtime Artifact authentication failed",
            )
        self._validate_connection(
            runtime_connection_id,
            runtime_id=artifact.runtime_id,
            runtime_generation=artifact.runtime_generation,
            runtime_configuration_hash=artifact.runtime_configuration_hash,
            route_generation=artifact.route_generation,
            allow_recovering=True,
        )
        request = self.store.requests.get(artifact.request_id)
        if request is None or request.request.session_id != artifact.session_id:
            raise RuntimeProtocolError(
                "RUNTIME_REQUEST_NOT_FOUND",
                "artifact",
                "Runtime Artifact Request is unknown",
            )
        if request.admission_state not in {"ACCEPTED", "QUEUED"}:
            raise RuntimeProtocolError(
                "RUNTIME_REQUEST_REJECTED",
                "artifact",
                "Runtime Artifact Request was not accepted",
            )
        existing = self.store.artifacts.get(artifact.artifact_id)
        if existing is not None:
            if existing.declaration_hash != artifact.declaration_hash:
                raise RuntimeProtocolError(
                    "RUNTIME_ARTIFACT_INVALID",
                    "artifact",
                    "Artifact ID conflicts with an existing declaration",
                )
            return existing
        self.store.artifacts[artifact.artifact_id] = artifact.model_copy(deep=True)
        self.store.flush()
        return artifact

    def record_runtime_state_checkpoint(
        self,
        runtime_connection_id: str,
        checkpoint: RuntimeStateCheckpoint,
    ) -> RuntimeStateCheckpoint:
        if not self.runtime_authenticator(checkpoint):
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID",
                "state",
                "Runtime State Checkpoint authentication failed",
            )
        self._validate_connection(
            runtime_connection_id,
            runtime_id=checkpoint.runtime_id,
            runtime_generation=checkpoint.runtime_generation,
            runtime_configuration_hash=checkpoint.runtime_configuration_hash,
            route_generation=checkpoint.route_generation,
            allow_recovering=True,
        )
        session_requests = [
            record
            for record in self.store.requests.values()
            if record.runtime_id == checkpoint.runtime_id
            and record.request.session_id == checkpoint.session_id
            and record.admission_state in {"ACCEPTED", "QUEUED"}
        ]
        if not session_requests:
            raise RuntimeProtocolError(
                "RUNTIME_STATE_NOT_FOUND",
                "state",
                "State Checkpoint Session has no accepted Runtime Request",
            )
        key = self.store._checkpoint_key(checkpoint)
        existing = self.store.state_checkpoints.get(key)
        if existing is not None:
            if existing.checkpoint_hash != checkpoint.checkpoint_hash:
                raise RuntimeProtocolError(
                    "RUNTIME_STATE_GENERATION_MISMATCH",
                    "state",
                    "State Checkpoint conflicts with an existing sequence",
                )
            return existing
        prior_sequences = [
            item.checkpoint_sequence
            for item in self.store.state_checkpoints.values()
            if item.runtime_id == checkpoint.runtime_id
            and item.session_id == checkpoint.session_id
            and item.state_generation == checkpoint.state_generation
        ]
        expected_sequence = max(prior_sequences, default=0) + 1
        if checkpoint.checkpoint_sequence != expected_sequence:
            raise RuntimeProtocolError(
                "RUNTIME_STATE_GENERATION_MISMATCH",
                "state",
                "State Checkpoint sequence is invalid",
            )
        self.store.state_checkpoints[key] = checkpoint.model_copy(deep=True)
        self.store.flush()
        return checkpoint

    def request_runtime_drain(
        self,
        runtime_connection_id: str,
        drain: RuntimeDrainRequest,
    ) -> RuntimeDrainRequest:
        connection = self._validate_connection(
            runtime_connection_id,
            runtime_id=drain.runtime_id,
            runtime_generation=drain.runtime_generation,
            runtime_configuration_hash=drain.runtime_configuration_hash,
            route_generation=drain.route_generation,
            allow_recovering=True,
        )
        existing = self.store.drain_requests.get(drain.drain_id)
        if existing is not None:
            if existing.drain_hash != drain.drain_hash:
                raise RuntimeProtocolError(
                    "RUNTIME_DRAINING", "drain", "Drain ID conflicts with existing command"
                )
            return existing
        if any(
            item.runtime_id == drain.runtime_id
            and item.drain_id not in self.store.drain_completes
            for item in self.store.drain_requests.values()
        ):
            raise RuntimeProtocolError(
                "RUNTIME_DRAINING", "drain", "Runtime already has an active drain"
            )
        self.store.drain_requests[drain.drain_id] = drain.model_copy(deep=True)
        self.store.connections[runtime_connection_id] = connection.model_copy(
            update={"connection_state": "DRAINING"}
        )
        self.store.flush()
        return drain

    def record_runtime_drain_status(
        self,
        runtime_connection_id: str,
        status: RuntimeDrainStatus,
    ) -> RuntimeDrainStatus:
        if not self.runtime_authenticator(status):
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID", "drain", "Runtime Drain Status authentication failed"
            )
        self._validate_connection(
            runtime_connection_id,
            runtime_id=status.runtime_id,
            runtime_generation=status.runtime_generation,
            runtime_configuration_hash=status.runtime_configuration_hash,
            route_generation=status.route_generation,
            allow_recovering=True,
        )
        drain = self.store.drain_requests.get(status.drain_id)
        if drain is None or (
            drain.runtime_id != status.runtime_id
            or drain.runtime_generation != status.runtime_generation
            or drain.route_generation != status.route_generation
        ):
            raise RuntimeProtocolError(
                "RUNTIME_DRAINING", "drain", "Runtime Drain Status references an unknown drain"
            )
        existing = self.store.drain_statuses.get(status.drain_id)
        if existing is not None:
            if status.status_sequence < existing.status_sequence:
                raise RuntimeProtocolError(
                    "RUNTIME_DRAINING", "drain", "Runtime Drain Status is stale"
                )
            if status.status_sequence == existing.status_sequence:
                if status.status_hash == existing.status_hash:
                    return existing
                raise RuntimeProtocolError(
                    "RUNTIME_DRAINING", "drain", "Runtime Drain Status conflicts"
                )
        self.store.drain_statuses[status.drain_id] = status.model_copy(deep=True)
        self.store.flush()
        return status

    def record_runtime_drain_complete(
        self,
        runtime_connection_id: str,
        complete: RuntimeDrainComplete,
    ) -> RuntimeDrainComplete:
        if not self.runtime_authenticator(complete):
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID", "drain", "Runtime Drain Complete authentication failed"
            )
        self._validate_connection(
            runtime_connection_id,
            runtime_id=complete.runtime_id,
            runtime_generation=complete.runtime_generation,
            runtime_configuration_hash=complete.runtime_configuration_hash,
            route_generation=complete.route_generation,
            allow_recovering=True,
        )
        drain = self.store.drain_requests.get(complete.drain_id)
        if drain is None or (
            drain.runtime_id != complete.runtime_id
            or drain.runtime_generation != complete.runtime_generation
            or drain.route_generation != complete.route_generation
        ):
            raise RuntimeProtocolError(
                "RUNTIME_DRAINING", "drain", "Runtime Drain Complete references an unknown drain"
            )
        existing = self.store.drain_completes.get(complete.drain_id)
        if existing is not None:
            if existing.completion_hash != complete.completion_hash:
                raise RuntimeProtocolError(
                    "RUNTIME_DRAINING", "drain", "Runtime Drain Complete conflicts"
                )
            return existing
        self.store.drain_completes[complete.drain_id] = complete.model_copy(deep=True)
        self.store.flush()
        return complete

    def request_runtime_shutdown(
        self,
        runtime_connection_id: str,
        shutdown: RuntimeShutdown,
    ) -> RuntimeShutdown:
        connection = self._validate_connection(
            runtime_connection_id,
            runtime_id=shutdown.runtime_id,
            runtime_generation=shutdown.runtime_generation,
            runtime_configuration_hash=shutdown.runtime_configuration_hash,
            route_generation=shutdown.route_generation,
            allow_recovering=True,
        )
        existing = self.store.shutdowns.get(shutdown.shutdown_id)
        if existing is not None:
            if existing.shutdown_hash != shutdown.shutdown_hash:
                raise RuntimeProtocolError(
                    "RUNTIME_STOPPED", "shutdown", "Shutdown ID conflicts with existing command"
                )
            return existing
        if shutdown.shutdown_mode == "GRACEFUL" and not any(
            drain.runtime_id == shutdown.runtime_id
            for drain in self.store.drain_completes.values()
        ):
            raise RuntimeProtocolError(
                "RUNTIME_DRAINING",
                "shutdown",
                "Graceful Runtime Shutdown requires a completed drain",
            )
        self.store.shutdowns[shutdown.shutdown_id] = shutdown.model_copy(deep=True)
        if shutdown.shutdown_mode != "GRACEFUL":
            self.store.connections[runtime_connection_id] = connection.model_copy(
                update={"connection_state": "CLOSED"}
            )
        self.store.flush()
        return shutdown

    def record_request_terminal(
        self,
        runtime_connection_id: str,
        *,
        request_id: str,
        terminal_state: str,
        terminal_result_hash: str,
        final_usage_report_id: str,
    ) -> RuntimeRequestRecord:
        record = self.store.requests.get(request_id)
        if record is None:
            raise RuntimeProtocolError(
                "RUNTIME_REQUEST_NOT_FOUND", "result", "Unknown Runtime Request"
            )
        self._validate_connection(
            runtime_connection_id,
            runtime_id=record.runtime_id,
            runtime_generation=record.runtime_generation,
            runtime_configuration_hash=record.request.runtime_configuration_hash,
            route_generation=record.route_generation,
            allow_recovering=True,
        )
        terminal_states = {
            "COMPLETED",
            "PARTIAL",
            "CANCELLED",
            "FAILED",
            "EXPIRED",
            "UNRECOVERABLE",
        }
        if terminal_state not in terminal_states:
            raise RuntimeProtocolError(
                "RUNTIME_RESULT_FINALIZATION_FAILED",
                "result",
                "Request terminal state is invalid",
            )
        report = self.store.usage_reports.get(final_usage_report_id)
        request_reports = [
            item
            for item in self.store.usage_reports.values()
            if item.request_id == request_id
        ]
        chain_head = max(
            request_reports,
            key=lambda item: item.usage_sequence,
            default=None,
        )
        if (
            report is None
            or chain_head is None
            or chain_head.usage_report_id != final_usage_report_id
            or report.request_id != request_id
            or report.report_type != "FINAL"
            or not report.terminal
            or report.request_state != terminal_state
        ):
            raise RuntimeProtocolError(
                "USAGE_FINAL_REPORT_REQUIRED",
                "result",
                "Terminal Request requires a matching accepted Final Usage Report",
            )
        updated = record.model_copy(
            update={
                "request_state": terminal_state,
                "terminal_result_hash": terminal_result_hash,
                "terminal_final_usage_report_id": final_usage_report_id,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        self.store.requests[request_id] = updated
        self.store.flush()
        return updated

    def record_runtime_result(
        self,
        runtime_connection_id: str,
        result: RuntimeResult,
    ) -> RuntimeResult:
        if not self.runtime_authenticator(result):
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID",
                "result",
                "Runtime Result authentication failed",
            )
        record = self.store.requests.get(result.request_id)
        if record is None:
            raise RuntimeProtocolError(
                "RUNTIME_REQUEST_NOT_FOUND", "result", "Unknown Runtime Request"
            )
        if (
            result.runtime_id != record.runtime_id
            or result.runtime_generation != record.runtime_generation
            or result.runtime_configuration_hash
            != record.request.runtime_configuration_hash
            or result.route_generation != record.route_generation
            or result.endpoint_id != record.request.endpoint_id
            or result.endpoint_configuration_hash
            != record.request.endpoint_configuration_hash
            or result.session_id != record.request.session_id
        ):
            raise RuntimeProtocolError(
                "RUNTIME_RESULT_FINALIZATION_FAILED",
                "result",
                "Runtime Result identity does not match accepted Request",
            )
        existing = self.store.results.get(result.request_id)
        if existing is not None:
            if existing.result_hash != result.result_hash:
                raise RuntimeProtocolError(
                    "RUNTIME_RESULT_FINALIZATION_FAILED",
                    "result",
                    "Runtime Result conflicts with the accepted terminal Result",
                )
            return existing
        for stream_root in result.stream_roots:
            if not any(
                close.request_id == result.request_id
                and close.final_content_root == stream_root
                for close in self.store.stream_closes.values()
            ):
                raise RuntimeProtocolError(
                    "RUNTIME_STREAM_NOT_FOUND",
                    "result",
                    "Runtime Result references an unknown closed Stream root",
                )
        for reference in result.artifact_references:
            artifact_id = reference.get("artifact_id")
            artifact = self.store.artifacts.get(artifact_id)
            if (
                artifact is None
                or artifact.request_id != result.request_id
                or artifact.session_id != result.session_id
                or (
                    "content_hash" in reference
                    and reference["content_hash"] != artifact.content_hash
                )
            ):
                raise RuntimeProtocolError(
                    "RUNTIME_ARTIFACT_INVALID",
                    "result",
                    "Runtime Result references an unknown Artifact declaration",
                )
        self.record_request_terminal(
            runtime_connection_id,
            request_id=result.request_id,
            terminal_state=result.terminal_state,
            terminal_result_hash=result.result_hash,
            final_usage_report_id=result.final_usage_report_id,
        )
        self.store.results[result.request_id] = result.model_copy(deep=True)
        self.store.flush()
        return result

    def _validate_stream_event(
        self,
        runtime_connection_id: str,
        event: RuntimeStreamOpen | RuntimeStreamChunk | RuntimeStreamClose,
        *,
        stage: str,
        require_open: bool = False,
    ) -> RuntimeStreamOpen:
        if not self.runtime_authenticator(event):
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID", stage, "Runtime Stream authentication failed"
            )
        self._validate_connection(
            runtime_connection_id,
            runtime_id=event.runtime_id,
            runtime_generation=event.runtime_generation,
            runtime_configuration_hash=event.runtime_configuration_hash,
            route_generation=event.route_generation,
            allow_recovering=True,
        )
        request = self.store.requests.get(event.request_id)
        if request is None or request.request.session_id != event.session_id:
            raise RuntimeProtocolError(
                "RUNTIME_REQUEST_NOT_FOUND", stage, "Runtime Stream Request is unknown"
            )
        if request.admission_state not in {"ACCEPTED", "QUEUED"}:
            raise RuntimeProtocolError(
                "RUNTIME_REQUEST_REJECTED",
                stage,
                "Runtime Stream Request was not accepted",
            )
        if require_open:
            stream = self.store.streams.get(event.stream_id)
            if stream is None:
                raise RuntimeProtocolError(
                    "RUNTIME_STREAM_NOT_FOUND", stage, "Runtime Stream is not open"
                )
            if (
                stream.runtime_id != event.runtime_id
                or stream.runtime_generation != event.runtime_generation
                or stream.runtime_configuration_hash != event.runtime_configuration_hash
                or stream.route_generation != event.route_generation
                or stream.session_id != event.session_id
                or stream.request_id != event.request_id
            ):
                raise RuntimeProtocolError(
                    "RUNTIME_STREAM_SEQUENCE_CONFLICT",
                    stage,
                    "Runtime Stream event identity does not match Stream Open",
                )
            return stream
        return event

    @staticmethod
    def _stream_root(
        stream_id: str,
        chunks: dict[int, RuntimeStreamChunk],
    ) -> str:
        return canonical_hash(
            {
                "stream_id": stream_id,
                "chunks": [
                    {
                        "sequence": sequence,
                        "chunk_hash": chunk.chunk_hash,
                        "chunk_length": chunk.chunk_length,
                    }
                    for sequence, chunk in sorted(chunks.items())
                ],
            }
        )

    def _usage_ack(
        self,
        report: RuntimeUsageReport,
        *,
        status: str,
        accepted_sequence: int | None = None,
        accepted_hash: str | None = None,
        rejection_code: str | None = None,
    ) -> RuntimeUsageAck:
        ack = RuntimeUsageAck(
            usage_report_id=report.usage_report_id,
            session_id=report.session_id,
            request_id=report.request_id,
            status=status,
            accepted_usage_sequence=accepted_sequence,
            accepted_report_hash=accepted_hash,
            rejection_code=rejection_code,
            acknowledged_at=datetime.now(UTC).isoformat(),
        )
        signature_payload = ack.model_dump(
            mode="json",
            exclude={"hypervisor_signature"},
        )
        ack = ack.model_copy(
            update={"hypervisor_signature": self.hypervisor_signer(signature_payload)}
        )
        self.store.usage_acks[ack.usage_acknowledgment_id] = ack
        if status != "ACCEPTED":
            self.store.flush()
        return ack

    def _record_usage_conflict(
        self,
        report: RuntimeUsageReport,
        *,
        accepted_report_hash: str | None,
        conflict_type: str,
    ) -> RuntimeUsageConflict:
        conflict = RuntimeUsageConflict(
            usage_report_id=report.usage_report_id,
            runtime_id=report.runtime_id,
            session_id=report.session_id,
            request_id=report.request_id,
            usage_sequence=report.usage_sequence,
            accepted_report_hash=accepted_report_hash,
            conflicting_report_hash=report.report_hash,
            conflict_type=conflict_type,
            observed_at=datetime.now(UTC).isoformat(),
        )
        self.store.usage_conflicts[conflict.conflict_id] = conflict
        return conflict

    def _accounting_contract(self, contract_hash: str) -> AccountingContract:
        try:
            contract = self.accounting_contract_resolver(contract_hash)
        except KeyError as exc:
            raise RuntimeProtocolError(
                "ACCOUNTING_CONTRACT_MISMATCH",
                "accounting",
                "Accounting Contract is unknown",
            ) from exc
        contract = AccountingContract.model_validate(contract.model_dump(mode="json"))
        if contract.payload_hash != contract_hash:
            raise RuntimeProtocolError(
                "ACCOUNTING_CONTRACT_MISMATCH",
                "accounting",
                "Accounting Contract Hash mismatch",
            )
        return contract

    def _usage_profile(self, runtime_id: str) -> RuntimeUsageProfile:
        try:
            profile = self.usage_profile_resolver(runtime_id)
        except KeyError as exc:
            raise RuntimeProtocolError(
                "USAGE_PROFILE_MISMATCH",
                "accounting",
                "Runtime Usage Profile is unknown",
            ) from exc
        return RuntimeUsageProfile.model_validate(profile.model_dump(mode="json"))

    def _validate_accounting_compatibility(
        self,
        *,
        request: RuntimeExecuteRequest,
        binding: RuntimeBinding,
        contract: AccountingContract,
        profile: RuntimeUsageProfile,
    ) -> None:
        if contract.capability_id not in {None, request.capability_id}:
            raise RuntimeProtocolError(
                "ACCOUNTING_CONTRACT_MISMATCH",
                "accounting",
                "Accounting Contract Capability mismatch",
            )
        if contract.endpoint_id not in {None, request.endpoint_id}:
            raise RuntimeProtocolError(
                "ACCOUNTING_CONTRACT_MISMATCH",
                "accounting",
                "Accounting Contract Endpoint mismatch",
            )
        if (
            profile.runtime_id != request.runtime_id
            or profile.runtime_generation != request.runtime_generation
            or profile.runtime_configuration_hash != request.runtime_configuration_hash
        ):
            raise RuntimeProtocolError(
                "USAGE_PROFILE_MISMATCH",
                "accounting",
                "Runtime Usage Profile identity mismatch",
            )
        if (
            binding.usage_reporting_profile_hash is None
            or profile.profile_hash != binding.usage_reporting_profile_hash
        ):
            raise RuntimeProtocolError(
                "USAGE_PROFILE_MISMATCH",
                "accounting",
                "Runtime Binding does not authorize this Usage Profile",
            )
        contract_modes = {unit.mode for unit in contract.billable_units}
        if binding.supported_accounting_modes and not contract_modes.issubset(
            set(binding.supported_accounting_modes)
        ):
            raise RuntimeProtocolError(
                "ACCOUNTING_MODE_UNSUPPORTED",
                "accounting",
                "Runtime Binding does not support the Accounting Mode",
            )
        errors = contract.compatibility_errors(profile)
        if errors:
            raise RuntimeProtocolError(
                "ACCOUNTING_REQUIRED_DIMENSION_UNAVAILABLE",
                "accounting",
                "; ".join(errors),
            )

    def _validate_request_state_reference(self, request: RuntimeExecuteRequest) -> None:
        reference = request.state_reference or {}
        checkpoint_hash = reference.get("checkpoint_hash")
        state_generation = reference.get("state_generation")
        if not checkpoint_hash or not isinstance(state_generation, int):
            raise RuntimeProtocolError(
                "RUNTIME_STATE_REFERENCE_INVALID",
                "state",
                "State Reference requires checkpoint_hash and state_generation",
            )
        if not any(
            checkpoint.runtime_id == request.runtime_id
            and checkpoint.session_id == request.session_id
            and checkpoint.state_generation == state_generation
            and checkpoint.checkpoint_hash == checkpoint_hash
            for checkpoint in self.store.state_checkpoints.values()
        ):
            raise RuntimeProtocolError(
                "RUNTIME_STATE_REFERENCE_INVALID",
                "state",
                "State Reference does not match a Session-scoped checkpoint",
            )

    def build_recovery_plan(
        self,
        runtime_connection_id: str,
        state: RuntimeRecoveryState,
        *,
        allow_route_rebind: bool = False,
    ) -> RuntimeRecoveryPlan:
        state = self.record_runtime_recovery_state(
            runtime_connection_id,
            state,
            allow_route_rebind=allow_route_rebind,
        )
        connection = self.store.connections[runtime_connection_id]
        current_route = self._route(state.runtime_id)
        runtime_request_ids = set(state.active_requests) | set(state.terminal_requests)
        runtime_request_ids.update(
            str(item["request_id"])
            for item in state.recoverable_requests
            if item.get("request_id")
        )
        local_requests = {
            request_id: record
            for request_id, record in self.store.requests.items()
            if record.runtime_id == state.runtime_id
        }
        directives: dict[str, str] = {}
        for request_id in sorted(runtime_request_ids):
            record = local_requests.get(request_id)
            if record is None:
                directives[request_id] = "IGNORE_UNKNOWN_REQUEST"
            elif request_id in state.terminal_requests:
                directives[request_id] = "REDELIVER_FINAL_RESULT"
            else:
                directives[request_id] = "CONTINUE_EXISTING_EXECUTION"
        terminal_states = {"COMPLETED", "PARTIAL", "CANCELLED", "FAILED", "EXPIRED"}
        for request_id, record in sorted(local_requests.items()):
            if request_id not in runtime_request_ids and record.request_state not in terminal_states:
                directives[request_id] = "FAIL_UNRECOVERABLE"
        local_usage_heads = {
            request_id: reports[-1].report_hash
            for request_id in local_requests
            if (
                reports := sorted(
                    (
                        item
                        for item in self.store.usage_reports.values()
                        if item.request_id == request_id
                    ),
                    key=lambda item: item.usage_sequence,
                )
            )
        }
        for request_id, local_head in local_usage_heads.items():
            if state.usage_chain_heads.get(request_id) != local_head:
                directives[request_id] = "REDELIVER_USAGE"
        plan = RuntimeRecoveryPlan(
            runtime_id=state.runtime_id,
            runtime_generation=state.runtime_generation,
            route_generation=current_route.route_generation,
            plan_id=f"rrp-{uuid4().hex}",
            request_directives=directives,
            issued_at=datetime.now(UTC).isoformat(),
        )
        self.store.recovery_plans[plan.plan_id] = plan
        self.store.connections[runtime_connection_id] = connection.model_copy(
            update={
                "route_generation": current_route.route_generation,
                "connection_state": "RECOVERING",
            }
        )
        self.store.flush()
        return plan

    def record_runtime_recovery_state(
        self,
        runtime_connection_id: str,
        state: RuntimeRecoveryState,
        *,
        allow_route_rebind: bool = False,
    ) -> RuntimeRecoveryState:
        if not self.runtime_authenticator(state):
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID",
                "recovery",
                "Runtime Recovery State authentication failed",
            )
        connection = self._validate_connection(
            runtime_connection_id,
            runtime_id=state.runtime_id,
            runtime_generation=state.runtime_generation,
            runtime_configuration_hash=state.runtime_configuration_hash,
            allow_recovering=True,
            skip_route_check=allow_route_rebind,
        )
        if state.route_generation != connection.route_generation and not allow_route_rebind:
            raise RuntimeProtocolError(
                "RUNTIME_ROUTE_GENERATION_MISMATCH",
                "recovery",
                "Recovery state uses a stale Route Generation",
            )
        existing = self.store.recovery_states.get(state.runtime_id)
        if existing is not None and existing.recovery_state_hash == state.recovery_state_hash:
            return existing
        self.store.recovery_states[state.runtime_id] = state.model_copy(deep=True)
        self.store.flush()
        return state

    def record_recovery_result(
        self,
        runtime_connection_id: str,
        result: RuntimeRecoveryResult,
    ) -> RuntimeConnection:
        connection = self._validate_connection(
            runtime_connection_id,
            runtime_id=result.runtime_id,
            runtime_generation=result.runtime_generation,
            route_generation=result.route_generation,
            allow_recovering=True,
        )
        plan = self.store.recovery_plans.get(result.plan_id)
        if plan is None:
            raise RuntimeProtocolError(
                "RUNTIME_RECOVERY_PLAN_INVALID",
                "recovery",
                "Runtime Recovery Result references an unknown plan",
            )
        if (
            plan.runtime_id != result.runtime_id
            or plan.runtime_generation != result.runtime_generation
            or plan.route_generation != result.route_generation
        ):
            raise RuntimeProtocolError(
                "RUNTIME_RECOVERY_CONFLICT",
                "recovery",
                "Runtime Recovery Result does not match its plan identity",
            )
        existing = self.store.recovery_results.get(result.plan_id)
        if existing is not None and existing.result_hash != result.result_hash:
            raise RuntimeProtocolError(
                "RUNTIME_RECOVERY_CONFLICT",
                "recovery",
                "Recovery Plan already has a conflicting result",
            )
        self.store.recovery_results[result.plan_id] = result.model_copy(deep=True)
        updated = connection.model_copy(
            update={
                "connection_state": (
                    "RECOVERING" if result.remaining_conflicts else "READY"
                )
            }
        )
        self.store.connections[runtime_connection_id] = updated
        self.store.flush()
        return updated

    @staticmethod
    def challenge_response(challenge: str) -> str:
        return canonical_hash({"challenge": challenge})

    def _binding(self, runtime_id: str) -> RuntimeBinding:
        try:
            binding = self.binding_resolver(runtime_id)
        except KeyError as exc:
            raise RuntimeProtocolError(
                "RUNTIME_NOT_REGISTERED", "identity", "Runtime ID is not approved"
            ) from exc
        return RuntimeBinding.model_validate(binding.model_dump(mode="json"))

    def _route(self, runtime_id: str) -> DispatcherRoute:
        route = self.route_resolver(runtime_id)
        if route is None or route.route_state != "ACTIVE":
            raise RuntimeProtocolError(
                "RUNTIME_ROUTE_NOT_FOUND", "route", "Approved Runtime route is unavailable"
            )
        return route

    def _validate_hello_binding(
        self,
        hello: RuntimeHello,
        binding: RuntimeBinding,
        route: DispatcherRoute,
    ) -> None:
        if binding.operational_state != "READY":
            raise RuntimeProtocolError(
                "RUNTIME_NOT_READY", "configuration", "Runtime Binding is not ready"
            )
        if hello.runtime_generation != binding.runtime_generation:
            raise RuntimeProtocolError(
                "RUNTIME_GENERATION_MISMATCH", "configuration", "Runtime Generation mismatch"
            )
        if hello.runtime_configuration_hash != binding.runtime_configuration_hash:
            raise RuntimeProtocolError(
                "RUNTIME_CONFIGURATION_MISMATCH",
                "configuration",
                "Runtime Configuration Hash mismatch",
            )
        if hello.capability_id != binding.capability_id:
            raise RuntimeProtocolError(
                "RUNTIME_CAPABILITY_MISMATCH", "capability", "Capability ID mismatch"
            )
        if binding.capability_version not in hello.supported_capability_versions:
            raise RuntimeProtocolError(
                "RUNTIME_CAPABILITY_MISMATCH", "capability", "Capability version mismatch"
            )
        if binding.capability_definition_hash not in hello.supported_definition_hashes:
            raise RuntimeProtocolError(
                "RUNTIME_CAPABILITY_DEFINITION_MISMATCH",
                "capability",
                "Capability Definition Hash mismatch",
            )
        if binding.adapter_id is not None and hello.adapter_id != binding.adapter_id:
            raise RuntimeProtocolError(
                "RUNTIME_ADAPTER_MISMATCH", "identity", "Runtime Adapter ID mismatch"
            )
        if binding.adapter_version is not None and hello.adapter_version != binding.adapter_version:
            raise RuntimeProtocolError(
                "RUNTIME_ADAPTER_MISMATCH", "identity", "Runtime Adapter version mismatch"
            )
        if route.runtime_generation != binding.runtime_generation:
            raise RuntimeProtocolError(
                "RUNTIME_GENERATION_MISMATCH", "route", "Runtime route lineage mismatch"
            )
        if route.runtime_binding_hash != binding.binding_hash():
            raise RuntimeProtocolError(
                "RUNTIME_CONFIGURATION_MISMATCH", "route", "Runtime route Binding Hash mismatch"
            )
        if (
            "RUNTIME" not in route.allowed_channel_classes
            or "RUNTIME_EXECUTE" not in route.allowed_message_types
        ):
            raise RuntimeProtocolError(
                "RUNTIME_ROUTE_SCOPE_DENIED",
                "route",
                "Runtime route does not authorize RFC-0054 execution",
            )

    def _select_protocol_version(self, runtime_versions: list[str]) -> str:
        mutual = set(runtime_versions).intersection(self.supported_protocol_versions)
        if not mutual:
            raise RuntimeProtocolError(
                "RUNTIME_PROTOCOL_VERSION_UNSUPPORTED",
                "version",
                "No mutually supported Runtime Protocol version",
            )
        return max(mutual, key=self._version_key)

    def _validate_connection(
        self,
        runtime_connection_id: str,
        *,
        runtime_id: str,
        runtime_generation: int,
        runtime_configuration_hash: str | None = None,
        route_generation: int | None = None,
        allow_recovering: bool = False,
        skip_route_check: bool = False,
    ) -> RuntimeConnection:
        connection = self.store.connections.get(runtime_connection_id)
        if connection is None:
            raise RuntimeProtocolError(
                "RUNTIME_CONNECTION_NOT_FOUND", "connection", "Runtime connection is unknown"
            )
        permitted_states = {"READY"}
        if allow_recovering:
            permitted_states.update({"RECOVERING", "DRAINING"})
        if connection.connection_state not in permitted_states:
            raise RuntimeProtocolError(
                "RUNTIME_NOT_READY", "connection", "Runtime connection is not ready"
            )
        if datetime.fromisoformat(connection.expires_at) <= datetime.now(UTC):
            raise RuntimeProtocolError(
                "RUNTIME_CONNECTION_EXPIRED", "connection", "Runtime connection expired"
            )
        if connection.runtime_id != runtime_id:
            raise RuntimeProtocolError(
                "RUNTIME_IDENTITY_INVALID", "identity", "Runtime connection ID mismatch"
            )
        if connection.runtime_generation != runtime_generation:
            raise RuntimeProtocolError(
                "RUNTIME_GENERATION_MISMATCH", "configuration", "Runtime Generation mismatch"
            )
        if (
            runtime_configuration_hash is not None
            and connection.runtime_configuration_hash != runtime_configuration_hash
        ):
            raise RuntimeProtocolError(
                "RUNTIME_CONFIGURATION_MISMATCH",
                "configuration",
                "Runtime Configuration Hash mismatch",
            )
        route = self._route(runtime_id)
        if not skip_route_check:
            expected_route_generation = (
                route_generation
                if route_generation is not None
                else connection.route_generation
            )
            if (
                connection.route_generation != expected_route_generation
                or route.route_generation != expected_route_generation
            ):
                raise RuntimeProtocolError(
                    "RUNTIME_ROUTE_GENERATION_MISMATCH",
                    "route",
                    "Runtime Route Generation mismatch",
                )
        return connection

    @staticmethod
    def _version_key(version: str) -> tuple[int, int]:
        try:
            major, minor = version.split(".", maxsplit=1)
            return int(major), int(minor)
        except (ValueError, AttributeError) as exc:
            raise RuntimeProtocolError(
                "RUNTIME_PROTOCOL_VERSION_UNSUPPORTED",
                "version",
                f"Invalid Runtime Protocol version: {version}",
            ) from exc
