"""RFC-0054 adapter for Ollama's native ``/api/generate`` endpoint."""

import json
from urllib import request as urllib_request

from aidn_hypervisor.runtime_protocol.adapters.llamacpp import LlamaCppOpenAIAdapter
from aidn_hypervisor.runtime_protocol.models import RuntimeRequestAccept, RuntimeUsageDimension


class OllamaGenerateAdapter(LlamaCppOpenAIAdapter):
    """Normalize Ollama JSON and JSONL responses into the RFC-0054 evidence model.

    Ollama does not expose a portable provider-operation handle that can be
    cancelled after submission, so inherited cancellation remains explicitly
    best-effort and never reports a confirmed provider stop.
    """

    adapter_label = "ollama"

    def _completion(self, execution_request):
        response = self._generate(execution_request, stream=False)
        return self._normalize_response(response)

    def _stream_completion(self, execution_request):
        prompt = self._prompt(execution_request)
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": True,
                "options": {"num_predict": 64, "temperature": 0},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib_request.Request(
            f"{self.endpoint}/api/generate",
            method="POST",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                yield self._normalize_response(json.loads(line))

    def _admit(self, protocol, runtime_connection_id, request, *, accepted_features: list[str]) -> None:
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

    def _generate(self, execution_request, *, stream: bool) -> dict:
        prompt = self._prompt(execution_request)
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": stream,
                "options": {"num_predict": 64, "temperature": 0},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib_request.Request(
            f"{self.endpoint}/api/generate",
            method="POST",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _prompt(self, execution_request) -> str:
        prompt = (execution_request.request_payload or {}).get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("Ollama adapter requires a non-empty prompt")
        return prompt

    def _normalize_response(self, response: dict) -> dict:
        done = bool(response.get("done", False))
        usage = {
            "prompt_tokens": response.get("prompt_eval_count"),
            "completion_tokens": response.get("eval_count"),
        }
        return {
            "model": str(response.get("model", self.model)),
            "choices": [
                {
                    "text": str(response.get("response", "")),
                    "finish_reason": "stop" if done else None,
                }
            ],
            "usage": usage,
        }

    def _usage_dimensions(self, usage: dict) -> list[RuntimeUsageDimension]:
        dimensions: list[RuntimeUsageDimension] = []
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
                            "source_id": "ollama-api-generate",
                        },
                    )
                )
        return dimensions
