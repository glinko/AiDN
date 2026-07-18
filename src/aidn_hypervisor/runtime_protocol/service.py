from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pydantic import BaseModel

from aidn_hypervisor.dispatcher.models import DispatcherRoute
from aidn_hypervisor.providers.models import RuntimeBinding
from aidn_hypervisor.runtime_protocol.models import (
    HypervisorRuntimeHello,
    RuntimeConnection,
    RuntimeExecuteRequest,
    RuntimeHello,
    RuntimeHelloComplete,
    RuntimeMessage,
    RuntimeRecoveryPlan,
    RuntimeRecoveryResult,
    RuntimeRecoveryState,
    RuntimeRequestAccept,
    RuntimeRequestRecord,
    RuntimeUsageAck,
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

        now = datetime.now(timezone.utc)
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
        if datetime.fromisoformat(message.expiration) <= datetime.now(timezone.utc):
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
        unsupported = set(request.required_features) - set(binding.supported_features)
        if unsupported:
            raise RuntimeProtocolError(
                "RUNTIME_REQUIRED_FEATURE_UNAVAILABLE",
                "request",
                "Required Runtime features are unavailable",
            )
        if datetime.fromisoformat(request.request_deadline) <= datetime.now(timezone.utc):
            raise RuntimeProtocolError(
                "RUNTIME_REQUEST_EXPIRED", "request", "Request deadline expired"
            )
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
            updated_at=datetime.now(timezone.utc).isoformat(),
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
                "updated_at": datetime.now(timezone.utc).isoformat(),
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
        existing = self.store.usage_reports.get(report.usage_report_id)
        if existing is not None:
            if existing.report_hash != report.report_hash:
                raise RuntimeProtocolError(
                    "RUNTIME_USAGE_CHAIN_CONFLICT",
                    "usage",
                    "Usage Report ID conflicts with existing content",
                )
            return RuntimeUsageAck(
                usage_report_id=report.usage_report_id,
                request_id=report.request_id,
                status="DUPLICATE",
                accepted_usage_sequence=existing.usage_sequence,
                accepted_report_hash=existing.report_hash,
                acknowledged_at=datetime.now(timezone.utc).isoformat(),
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
        if report.usage_sequence != expected_sequence:
            raise RuntimeProtocolError(
                "RUNTIME_USAGE_SEQUENCE_INVALID",
                "usage",
                f"Expected Usage sequence {expected_sequence}",
            )
        if report.previous_usage_report_hash != previous_hash:
            raise RuntimeProtocolError(
                "RUNTIME_USAGE_CHAIN_CONFLICT",
                "usage",
                "Usage Report does not extend the accepted hash chain",
            )
        ack = RuntimeUsageAck(
            usage_report_id=report.usage_report_id,
            request_id=report.request_id,
            status="ACCEPTED",
            accepted_usage_sequence=report.usage_sequence,
            accepted_report_hash=report.report_hash,
            acknowledged_at=datetime.now(timezone.utc).isoformat(),
        )
        self.store.usage_reports[report.usage_report_id] = report.model_copy(deep=True)
        self.store.usage_acks[report.usage_report_id] = ack
        self.store.flush()
        return ack

    def build_recovery_plan(
        self,
        runtime_connection_id: str,
        state: RuntimeRecoveryState,
        *,
        allow_route_rebind: bool = False,
    ) -> RuntimeRecoveryPlan:
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
            issued_at=datetime.now(timezone.utc).isoformat(),
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
            permitted_states.add("RECOVERING")
        if connection.connection_state not in permitted_states:
            raise RuntimeProtocolError(
                "RUNTIME_NOT_READY", "connection", "Runtime connection is not ready"
            )
        if datetime.fromisoformat(connection.expires_at) <= datetime.now(timezone.utc):
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
