"""RFC-0054 adapter for an opaque OpenAI-compatible upstream Proxy."""

import json
from urllib import request as urllib_request

from aidn_hypervisor.runtime_protocol.adapters.llamacpp import LlamaCppOpenAIAdapter
from aidn_hypervisor.runtime_protocol.models import (
    RuntimeCancelRequest,
    RuntimeCancelResult,
    RuntimeRecoveryState,
    RuntimeUsageDimension,
)


class ProxyOpenAIAdapter(LlamaCppOpenAIAdapter):
    """Forward completion execution while preserving opaque upstream accounting.

    An upstream operation identifier is optional. When supplied by a provider,
    it is persisted as the Runtime request handle and enables confirmed cancel
    and status recovery. The adapter never infers token usage from text.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        runtime_signature: str,
        cancel_path_template: str = "/v1/operations/{operation_id}/cancel",
        status_path_template: str = "/v1/operations/{operation_id}",
        timeout_seconds: float = 90,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            model=model,
            runtime_signature=runtime_signature,
            timeout_seconds=timeout_seconds,
        )
        self.cancel_path_template = cancel_path_template
        self.status_path_template = status_path_template
        self._operation_ids: dict[str, str] = {}

    def execute(self, protocol, runtime_connection_id: str, request):
        result = super().execute(protocol, runtime_connection_id, request)
        self._persist_operation_handle(protocol, request.request_id)
        return result

    def _completion(self, execution_request) -> dict:
        response = super()._completion(execution_request)
        operation_id = response.get("operation_id") or response.get("id")
        if isinstance(operation_id, str) and operation_id:
            self._operation_ids[execution_request.request_id] = operation_id
        return response

    def cancel(self, protocol, runtime_connection_id: str, cancellation: RuntimeCancelRequest) -> RuntimeCancelResult:
        existing = protocol.store.cancellation_results.get(cancellation.cancellation_id)
        if existing is not None:
            return existing
        operation_id = self._operation_id(protocol, cancellation.request_id)
        if operation_id is None:
            return super().cancel(protocol, runtime_connection_id, cancellation)
        try:
            response = self._request_json(
                "POST",
                self.cancel_path_template.format(operation_id=operation_id),
                {"operation_id": operation_id},
            )
        except Exception:
            return self._record_cancel(
                protocol,
                runtime_connection_id,
                cancellation,
                state="CANCELLATION_PENDING",
                provider_state="UNKNOWN",
                confirmed=False,
            )
        confirmed = response.get("confirmed_stopped") is True or response.get("status") in {
            "cancelled",
            "canceled",
        }
        return self._record_cancel(
            protocol,
            runtime_connection_id,
            cancellation,
            state="CANCELLED" if confirmed else "CANCELLATION_PENDING",
            provider_state=str(response.get("status", "UNKNOWN")).upper(),
            confirmed=confirmed,
        )

    def recovery_state(self, protocol, request, *, instance_id: str) -> RuntimeRecoveryState:
        state = super().recovery_state(protocol, request, instance_id=instance_id)
        record = protocol.store.requests.get(request.request_id)
        operation_id = self._operation_id(protocol, request.request_id)
        if (
            record is None
            or getattr(record, "terminal_result_hash", None) is not None
            or operation_id is None
        ):
            return state
        recoverable = {
            "session_id": request.session_id,
            "request_id": request.request_id,
            "execution_state": record.request_state,
            "provider_execution_reference": operation_id,
            "recovery_capabilities": ["WAIT_FOR_PROVIDER", "CANCEL"],
            "deadline": request.request_deadline,
        }
        return state.model_copy(update={"recoverable_requests": [*state.recoverable_requests, recoverable]})

    def _usage_dimensions(self, usage: dict) -> list[RuntimeUsageDimension]:
        return [
            RuntimeUsageDimension(
                dimension_id=dimension_id,
                unit="token",
                availability="UNAVAILABLE",
                billing_eligible=False,
                limitations=["UPSTREAM_USAGE_OPAQUE"],
            )
            for dimension_id in ("input_tokens", "output_tokens")
        ]

    def _persist_operation_handle(self, protocol, request_id: str) -> None:
        operation_id = self._operation_ids.get(request_id)
        record = protocol.store.requests.get(request_id)
        if operation_id is None or record is None:
            return
        protocol.store.requests[request_id] = record.model_copy(
            update={"runtime_request_handle": operation_id}
        )
        if hasattr(protocol.store, "flush"):
            protocol.store.flush()

    def _operation_id(self, protocol, request_id: str) -> str | None:
        return self._operation_ids.get(request_id) or getattr(
            protocol.store.requests.get(request_id), "runtime_request_handle", None
        )

    def _record_cancel(self, protocol, runtime_connection_id, cancellation, *, state, provider_state, confirmed):
        return protocol.record_runtime_cancel_result(
            runtime_connection_id,
            RuntimeCancelResult(
                cancellation_id=cancellation.cancellation_id,
                runtime_id=cancellation.runtime_id,
                runtime_generation=cancellation.runtime_generation,
                runtime_configuration_hash=cancellation.runtime_configuration_hash,
                route_generation=cancellation.route_generation,
                session_id=cancellation.session_id,
                request_id=cancellation.request_id,
                cancellation_state=state,
                provider_execution_state=provider_state,
                output_stopped=confirmed,
                provider_confirmed_stopped=confirmed,
                side_effect_state="UNKNOWN",
                observed_at=self._now(),
                runtime_signature=self.runtime_signature,
            ),
        )

    def _request_json(self, method: str, path: str, payload: dict) -> dict:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib_request.Request(
            f"{self.endpoint}{path}",
            method=method,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
