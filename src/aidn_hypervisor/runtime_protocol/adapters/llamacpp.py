"""RFC-0054 executor for a non-streaming OpenAI-compatible llama.cpp server."""

from datetime import datetime, timezone
import json
import time
from urllib import request as urllib_request

from aidn_hypervisor.runtime_protocol.models import (
    RuntimeCancelRequest,
    RuntimeCancelResult,
    RuntimeExecuteRequest,
    RuntimeRequestAccept,
    RuntimeRecoveryPlan,
    RuntimeRecoveryResult,
    RuntimeRecoveryState,
    RuntimeResult,
    RuntimeUsageDimension,
    RuntimeUsageReport,
)


class LlamaCppOpenAIAdapter:
    """Translate one accepted `llm.chat` Request into `/v1/completions`."""

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        runtime_signature: str,
        timeout_seconds: float = 90,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.runtime_signature = runtime_signature
        self.timeout_seconds = timeout_seconds

    def execute(self, protocol, runtime_connection_id: str, request: RuntimeExecuteRequest) -> RuntimeResult:
        existing = protocol.store.results.get(request.request_id)
        if existing is not None:
            return existing
        protocol.register_execute_request(runtime_connection_id, request)
        protocol.record_request_accept(
            runtime_connection_id,
            RuntimeRequestAccept(
                runtime_id=request.runtime_id,
                runtime_generation=request.runtime_generation,
                route_generation=request.route_generation,
                session_id=request.session_id,
                request_id=request.request_id,
                admission_state="ACCEPTED",
                runtime_request_handle=f"llamacpp-{request.request_id}",
                accepted_capability_definition_hash=request.capability_definition_hash,
                accepted_features=[],
                accepted_at=self._now(),
                progress_authority="MEASURED",
            ),
        )
        started_at = self._now()
        try:
            response = self._completion(request)
            dimensions = self._usage_dimensions(response.get("usage", {}))
            terminal_state = "COMPLETED"
            result_payload = {
                "text": str(response["choices"][0].get("text", "")),
                "model": str(response.get("model", self.model)),
                "finish_reason": response["choices"][0].get("finish_reason"),
            }
            limitations: list[str] = []
        except Exception as exc:
            dimensions = []
            terminal_state = "FAILED"
            result_payload = None
            limitations = [f"UPSTREAM_ERROR:{type(exc).__name__}"]
        report = RuntimeUsageReport(
            usage_report_id=f"llamacpp-usage-{request.request_id}",
            runtime_id=request.runtime_id,
            runtime_generation=request.runtime_generation,
            runtime_configuration_hash=request.runtime_configuration_hash,
            endpoint_id=request.endpoint_id,
            endpoint_configuration_hash=request.endpoint_configuration_hash,
            session_id=request.session_id,
            request_id=request.request_id,
            accounting_contract_hash=request.accounting_contract_hash,
            report_type="FINAL",
            usage_sequence=1,
            dimensions=dimensions,
            provider_attempt_count=1,
            request_state=terminal_state,
            terminal=True,
            observed_from=started_at,
            observed_to=self._now(),
            limitations=limitations,
            created_at=self._now(),
            runtime_signature=self.runtime_signature,
        )
        protocol.record_usage_report(runtime_connection_id, report)
        return protocol.record_runtime_result(
            runtime_connection_id,
            RuntimeResult(
                runtime_id=request.runtime_id,
                runtime_generation=request.runtime_generation,
                runtime_configuration_hash=request.runtime_configuration_hash,
                route_generation=request.route_generation,
                endpoint_id=request.endpoint_id,
                endpoint_configuration_hash=request.endpoint_configuration_hash,
                session_id=request.session_id,
                request_id=request.request_id,
                terminal_state=terminal_state,
                result_payload=result_payload,
                final_usage_report_id=report.usage_report_id,
                provider_attempt_count=1,
                completed_at=self._now(),
                runtime_signature=self.runtime_signature,
            ),
        )

    def cancel(
        self,
        protocol,
        runtime_connection_id: str,
        cancellation: RuntimeCancelRequest,
    ) -> RuntimeCancelResult:
        """Report best-effort cancellation without claiming upstream confirmation.

        The non-streaming OpenAI-compatible endpoint has no portable operation
        handle for a later cancellation request.  The adapter therefore leaves
        the Request in cancellation-pending state until recovery can observe
        the Provider outcome.
        """
        existing = protocol.store.cancellation_results.get(cancellation.cancellation_id)
        if existing is not None:
            return existing
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
                cancellation_state="CANCELLATION_PENDING",
                provider_execution_state="UNKNOWN",
                output_stopped=False,
                provider_confirmed_stopped=False,
                side_effect_state="UNKNOWN",
                observed_at=self._now(),
                runtime_signature=self.runtime_signature,
            ),
        )

    def recovery_state(
        self,
        protocol,
        request: RuntimeExecuteRequest,
        *,
        instance_id: str,
    ) -> RuntimeRecoveryState:
        """Describe only terminal evidence that this synchronous adapter can recover."""
        terminal_requests = sorted(
            result.request_id
            for result in protocol.store.results.values()
            if result.runtime_id == request.runtime_id
        )
        usage_chain_heads = {
            report.request_id: report.report_hash
            for report in protocol.store.usage_reports.values()
            if report.runtime_id == request.runtime_id and report.terminal
        }
        return RuntimeRecoveryState(
            runtime_id=request.runtime_id,
            runtime_generation=request.runtime_generation,
            runtime_configuration_hash=request.runtime_configuration_hash,
            route_generation=request.route_generation,
            instance_id=instance_id,
            terminal_requests=terminal_requests,
            usage_chain_heads=usage_chain_heads,
            runtime_signature=self.runtime_signature,
        )

    def apply_recovery_plan(
        self,
        protocol,
        runtime_connection_id: str,
        plan: RuntimeRecoveryPlan,
    ) -> RuntimeRecoveryResult:
        """Redeliver durable terminal evidence without restarting Provider work."""
        existing = protocol.store.recovery_results.get(plan.plan_id)
        if existing is not None:
            return existing
        request_results: dict[str, str] = {}
        remaining_conflicts: list[str] = []
        for request_id, directive in plan.request_directives.items():
            if directive == "REDELIVER_FINAL_RESULT":
                if request_id in protocol.store.results:
                    request_results[request_id] = "REDELIVERED_FINAL_RESULT"
                else:
                    remaining_conflicts.append(f"{request_id}:RESULT_NOT_FOUND")
            elif directive == "REDELIVER_USAGE":
                if any(
                    report.request_id == request_id
                    for report in protocol.store.usage_reports.values()
                ):
                    request_results[request_id] = "USAGE_REDELIVERY_AVAILABLE"
                else:
                    remaining_conflicts.append(f"{request_id}:USAGE_NOT_FOUND")
            elif directive == "CONTINUE_EXISTING_EXECUTION":
                remaining_conflicts.append(f"{request_id}:ACTIVE_EXECUTION_UNRECOVERABLE")
            else:
                request_results[request_id] = directive
        result = RuntimeRecoveryResult(
            runtime_id=plan.runtime_id,
            runtime_generation=plan.runtime_generation,
            route_generation=plan.route_generation,
            plan_id=plan.plan_id,
            request_results=request_results,
            remaining_conflicts=remaining_conflicts,
            completed_at=self._now(),
        )
        protocol.record_recovery_result(runtime_connection_id, result)
        return result

    def _completion(self, execution_request: RuntimeExecuteRequest) -> dict:
        prompt = (execution_request.request_payload or {}).get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("llama.cpp adapter requires a non-empty prompt")
        payload = json.dumps(
            {"model": self.model, "prompt": prompt, "max_tokens": 64, "temperature": 0},
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib_request.Request(
            f"{self.endpoint}/v1/completions",
            method="POST",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _usage_dimensions(self, usage: dict) -> list[RuntimeUsageDimension]:
        dimensions = []
        for provider_key, dimension_id in (
            ("prompt_tokens", "input_tokens"),
            ("completion_tokens", "output_tokens"),
        ):
            value = usage.get(provider_key)
            if isinstance(value, int) and value >= 0:
                dimensions.append(
                    RuntimeUsageDimension(
                        dimension_id=dimension_id,
                        unit="token",
                        availability="AVAILABLE",
                        authority="AUTHORITATIVE_PROVIDER",
                        value=value,
                        billing_eligible=dimension_id == "input_tokens",
                        source_reference={
                            "source_type": "PROVIDER_USAGE_RESPONSE",
                            "source_id": "llamacpp-v1-completions",
                        },
                    )
                )
        return dimensions

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
