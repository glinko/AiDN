from datetime import datetime, timedelta, timezone

from aidn_hypervisor.runtime_protocol import (
    LlamaCppOpenAIAdapter,
    RuntimeExecuteRequest,
    canonical_hash,
)


def _request(*, request_id: str = "request-1") -> RuntimeExecuteRequest:
    payload = {"prompt": "hello"}
    return RuntimeExecuteRequest(
        runtime_id="runtime-1",
        runtime_generation=1,
        runtime_configuration_hash="runtime-config-1",
        route_generation=1,
        endpoint_id="endpoint-1",
        endpoint_configuration_hash="endpoint-config-1",
        session_id="session-1",
        session_contract_hash="session-contract-1",
        request_id=request_id,
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="capability-definition-1",
        request_payload_hash=canonical_hash(payload),
        request_payload=payload,
        request_charge_ceiling=1,
        accounting_contract_hash="accounting-contract-1",
        idempotency_key=f"key-{request_id}",
        request_deadline=(datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
    )


class _Protocol:
    def __init__(self) -> None:
        self.store = type("Store", (), {"results": {}})()
        self.acceptances = []
        self.usage_reports = []

    def register_execute_request(self, connection_id, execution_request):
        self.connection_id = connection_id
        self.request = execution_request

    def record_request_accept(self, connection_id, acceptance):
        self.acceptances.append(acceptance)

    def record_usage_report(self, connection_id, report):
        self.usage_reports.append(report)

    def record_runtime_result(self, connection_id, result):
        self.store.results[result.request_id] = result
        return result


def test_llamacpp_adapter_maps_provider_usage_into_final_runtime_evidence(monkeypatch) -> None:
    adapter = LlamaCppOpenAIAdapter(
        endpoint="http://provider",
        model="qwen",
        runtime_signature="runtime-signed",
    )
    monkeypatch.setattr(
        adapter,
        "_completion",
        lambda _: {
            "model": "qwen",
            "choices": [{"text": "ok", "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        },
    )
    protocol = _Protocol()

    result = adapter.execute(protocol, "connection-1", _request())

    assert result.terminal_state == "COMPLETED"
    assert result.result_payload == {"text": "ok", "model": "qwen", "finish_reason": "stop"}
    assert protocol.acceptances[0].admission_state == "ACCEPTED"
    report = protocol.usage_reports[0]
    assert report.terminal is True
    assert [(item.dimension_id, item.value) for item in report.dimensions] == [
        ("input_tokens", 3),
        ("output_tokens", 2),
    ]
    assert all(item.authority == "AUTHORITATIVE_PROVIDER" for item in report.dimensions)
    assert adapter.execute(protocol, "connection-1", _request()) == result


def test_llamacpp_adapter_records_failed_terminal_evidence_for_upstream_error(monkeypatch) -> None:
    adapter = LlamaCppOpenAIAdapter(
        endpoint="http://provider",
        model="qwen",
        runtime_signature="runtime-signed",
    )
    monkeypatch.setattr(adapter, "_completion", lambda _: (_ for _ in ()).throw(TimeoutError()))
    protocol = _Protocol()

    result = adapter.execute(protocol, "connection-1", _request())

    assert result.terminal_state == "FAILED"
    assert protocol.usage_reports[0].terminal is True
    assert protocol.usage_reports[0].limitations == ["UPSTREAM_ERROR:TimeoutError"]
