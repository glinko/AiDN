"""RFC-0054 executor for a non-streaming OpenAI-compatible llama.cpp server."""

import hashlib
import json
from datetime import UTC, datetime
from urllib import request as urllib_request

from aidn_hypervisor.runtime_protocol.models import (
    RuntimeCancelRequest,
    RuntimeCancelResult,
    RuntimeExecuteRequest,
    RuntimeRecoveryPlan,
    RuntimeRecoveryResult,
    RuntimeRecoveryState,
    RuntimeRequestAccept,
    RuntimeResult,
    RuntimeStreamChunk,
    RuntimeStreamClose,
    RuntimeStreamOpen,
    RuntimeUsageDimension,
    RuntimeUsageReport,
    canonical_hash,
)


class LlamaCppOpenAIAdapter:
    """Translate one accepted `llm.chat` Request into `/v1/completions`."""

    adapter_label = "llamacpp"

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
        self._admit(protocol, runtime_connection_id, request, accepted_features=[])
        started_at = self._now()
        try:
            response = self._completion(request)
            choice = response["choices"][0]
            dimensions = self._usage_dimensions(response.get("usage", {}))
            terminal_state = "COMPLETED"
            result_payload = self._result_payload(response, choice)
            limitations: list[str] = []
        except Exception as exc:
            dimensions = []
            terminal_state = "FAILED"
            result_payload = None
            limitations = [f"UPSTREAM_ERROR:{type(exc).__name__}"]
        report = RuntimeUsageReport(
            usage_report_id=f"{self.adapter_label}-usage-{request.request_id}",
            runtime_id=request.runtime_id,
            runtime_generation=request.runtime_generation,
            runtime_configuration_hash=request.runtime_configuration_hash,
            endpoint_id=request.endpoint_id,
            endpoint_configuration_hash=request.endpoint_configuration_hash,
            session_id=request.session_id,
            request_id=request.request_id,
            effective_terms_hash=request.effective_terms_hash,
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

    def _result_payload(self, response: dict, choice: dict) -> dict:
        result_payload = {
            "text": self._choice_text(choice),
            "model": str(response.get("model", self.model)),
            "finish_reason": choice.get("finish_reason"),
        }
        message = choice.get("message")
        if isinstance(message, dict) and isinstance(message.get("tool_calls"), list):
            # Preserve native OpenAI tool calls for the local-agent gateway.
            result_payload["tool_calls"] = message["tool_calls"]
        return result_payload

    def execute_streaming(
        self,
        protocol,
        runtime_connection_id: str,
        request: RuntimeExecuteRequest,
    ) -> RuntimeResult:
        """Translate OpenAI SSE completion events into RFC-0054 stream evidence."""
        existing = protocol.store.results.get(request.request_id)
        if existing is not None:
            return existing
        self._admit(protocol, runtime_connection_id, request, accepted_features=["streaming"])
        stream_id = f"{self.adapter_label}-stream-{request.request_id}"
        protocol.record_runtime_stream_open(
            runtime_connection_id,
            RuntimeStreamOpen(
                runtime_id=request.runtime_id,
                runtime_generation=request.runtime_generation,
                runtime_configuration_hash=request.runtime_configuration_hash,
                route_generation=request.route_generation,
                session_id=request.session_id,
                request_id=request.request_id,
                stream_id=stream_id,
                stream_type="result",
                modality="text",
                content_type="text/plain",
                result_root_policy="FULL_CONTENT_HASH",
                opened_at=self._now(),
                runtime_signature=self.runtime_signature,
            ),
        )
        started_at = self._now()
        chunks: list[RuntimeStreamChunk] = []
        model = self.model
        finish_reason = None
        try:
            for event in self._stream_completion(request):
                model = str(event.get("model", model))
                choices = event.get("choices", [])
                if not choices:
                    continue
                choice = choices[0]
                finish_reason = choice.get("finish_reason") or finish_reason
                text = self._choice_text(choice)
                if not isinstance(text, str) or not text:
                    continue
                encoded = text.encode("utf-8")
                chunk = RuntimeStreamChunk(
                    runtime_id=request.runtime_id,
                    runtime_generation=request.runtime_generation,
                    runtime_configuration_hash=request.runtime_configuration_hash,
                    route_generation=request.route_generation,
                    session_id=request.session_id,
                    request_id=request.request_id,
                    stream_id=stream_id,
                    chunk_sequence=len(chunks) + 1,
                    chunk_hash=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
                    chunk_length=len(encoded),
                    content=text,
                    cumulative_output_units=sum(item.chunk_length for item in chunks) + len(encoded),
                    emitted_at=self._now(),
                    runtime_signature=self.runtime_signature,
                )
                protocol.record_runtime_stream_chunk(runtime_connection_id, chunk)
                chunks.append(chunk)
            terminal_state = "COMPLETED"
            result_payload = {
                "text": "".join(item.content or "" for item in chunks),
                "model": model,
                "finish_reason": finish_reason,
            }
            limitations = ["PROVIDER_STREAM_USAGE_UNAVAILABLE"]
        except Exception as exc:
            terminal_state = "FAILED"
            result_payload = None
            limitations = [f"UPSTREAM_STREAM_ERROR:{type(exc).__name__}"]
        close = RuntimeStreamClose(
            runtime_id=request.runtime_id,
            runtime_generation=request.runtime_generation,
            runtime_configuration_hash=request.runtime_configuration_hash,
            route_generation=request.route_generation,
            session_id=request.session_id,
            request_id=request.request_id,
            stream_id=stream_id,
            terminal_state=terminal_state,
            final_sequence=len(chunks),
            final_content_root=self._stream_root(stream_id, chunks),
            delivered_length=sum(item.chunk_length for item in chunks),
            close_reason=terminal_state.lower(),
            closed_at=self._now(),
            runtime_signature=self.runtime_signature,
        )
        protocol.record_runtime_stream_close(runtime_connection_id, close)
        report = RuntimeUsageReport(
            usage_report_id=f"{self.adapter_label}-usage-{request.request_id}",
            runtime_id=request.runtime_id,
            runtime_generation=request.runtime_generation,
            runtime_configuration_hash=request.runtime_configuration_hash,
            endpoint_id=request.endpoint_id,
            endpoint_configuration_hash=request.endpoint_configuration_hash,
            session_id=request.session_id,
            request_id=request.request_id,
            effective_terms_hash=request.effective_terms_hash,
            accounting_contract_hash=request.accounting_contract_hash,
            report_type="FINAL",
            usage_sequence=1,
            dimensions=[
                RuntimeUsageDimension(
                    dimension_id="output_bytes",
                    unit="byte",
                    availability="AVAILABLE",
                    authority="OBSERVABLE_LOCAL",
                    value=close.delivered_length,
                    billing_eligible=False,
                    source_reference={
                        "source_type": "RUNTIME_COUNTER",
                        "source_id": "llamacpp-sse-output",
                        "observation_boundary": "adapter-delivered-stream",
                    },
                )
            ],
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
                stream_roots=[close.final_content_root],
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
        path, body = self._upstream_payload(execution_request, stream=False)
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = urllib_request.Request(
            f"{self.endpoint}{path}",
            method="POST",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _stream_completion(self, execution_request: RuntimeExecuteRequest):
        path, body = self._upstream_payload(execution_request, stream=True)
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = urllib_request.Request(
            f"{self.endpoint}{path}",
            method="POST",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    return
                yield json.loads(data)

    def _upstream_payload(self, execution_request: RuntimeExecuteRequest, *, stream: bool) -> tuple[str, dict]:
        request_payload = execution_request.request_payload or {}
        parameters = self._generation_parameters(request_payload)
        messages = request_payload.get("messages")
        if isinstance(messages, list) and messages:
            payload = {
                "model": self.model,
                "messages": messages,
                **parameters,
                **({"stream": True} if stream else {}),
            }
            for key in ("tools", "tool_choice", "parallel_tool_calls"):
                if key in request_payload:
                    payload[key] = request_payload[key]
            return "/v1/chat/completions", payload
        prompt = request_payload.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("llama.cpp adapter requires messages or a non-empty prompt")
        return "/v1/completions", {
            "model": self.model,
            "prompt": prompt,
            **parameters,
            **({"stream": True} if stream else {}),
        }

    @staticmethod
    def _generation_parameters(request_payload: dict) -> dict:
        """Map canonical policy values while ignoring locked launch settings."""
        parameters = {
            "max_tokens": request_payload.get("max_tokens", 64),
            "temperature": request_payload.get("temperature", 0),
            **(
                {"top_p": request_payload["top_p"]}
                if request_payload.get("top_p") is not None
                else {}
            ),
        }
        # Qwen3-style llama.cpp templates spend the entire output budget in
        # hidden reasoning when thinking is left enabled.  That produces a
        # successful upstream response with empty user-facing content, which
        # makes OpenAI-compatible agents retry until their session expires.
        # Keep the operator-facing text path useful by disabling thinking by
        # default while allowing an explicit endpoint/request override.
        chat_template_kwargs = request_payload.get("chat_template_kwargs")
        if isinstance(chat_template_kwargs, dict):
            parameters["chat_template_kwargs"] = chat_template_kwargs
        else:
            parameters["chat_template_kwargs"] = {"enable_thinking": False}
        return parameters

    @staticmethod
    def _choice_text(choice: dict) -> str:
        text = choice.get("text")
        if isinstance(text, str):
            return text
        message = choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
        delta = choice.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                return content
        return ""

    def _admit(
        self,
        protocol,
        runtime_connection_id: str,
        request: RuntimeExecuteRequest,
        *,
        accepted_features: list[str],
    ) -> None:
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
                runtime_request_handle=f"{self.adapter_label}-{request.request_id}",
                accepted_capability_definition_hash=request.capability_definition_hash,
                accepted_features=accepted_features,
                accepted_at=self._now(),
                progress_authority="MEASURED",
            ),
        )

    @staticmethod
    def _stream_root(stream_id: str, chunks: list[RuntimeStreamChunk]) -> str:
        return canonical_hash(
            {
                "stream_id": stream_id,
                "chunks": [
                    {
                        "sequence": chunk.chunk_sequence,
                        "chunk_hash": chunk.chunk_hash,
                        "chunk_length": chunk.chunk_length,
                    }
                    for chunk in chunks
                ],
            }
        )

    def _usage_dimensions(self, usage: dict) -> list[RuntimeUsageDimension]:
        dimensions = []
        details = usage.get("prompt_tokens_details")
        cached_tokens = details.get("cached_tokens") if isinstance(details, dict) else None
        for provider_key, dimension_id in (
            ("prompt_tokens", "input_tokens"),
            ("completion_tokens", "output_tokens"),
        ):
            value = usage.get(provider_key)
            if (
                dimension_id == "input_tokens"
                and isinstance(value, int)
                and isinstance(cached_tokens, int)
                and 0 <= cached_tokens <= value
            ):
                value -= cached_tokens
            if isinstance(value, int) and value >= 0:
                dimensions.append(
                    RuntimeUsageDimension(
                        dimension_id=dimension_id,
                        unit="token",
                        availability="AVAILABLE",
                        authority="AUTHORITATIVE_PROVIDER",
                        value=value,
                        billing_eligible=True,
                        source_reference={
                            "source_type": "PROVIDER_USAGE_RESPONSE",
                            "source_id": "llamacpp-v1-completions",
                        },
                    )
                )
        if isinstance(cached_tokens, int) and cached_tokens >= 0:
            dimensions.append(
                RuntimeUsageDimension(
                    dimension_id="cached_input_tokens",
                    unit="token",
                    availability="AVAILABLE",
                    authority="AUTHORITATIVE_PROVIDER",
                    value=cached_tokens,
                    billing_eligible=True,
                    source_reference={
                        "source_type": "PROVIDER_USAGE_RESPONSE",
                        "source_id": "llamacpp-v1-completions",
                    },
                )
            )
        return dimensions

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()
