from datetime import UTC, datetime, timedelta

from aidn_hypervisor.runtime_protocol import (
    LlamaCppOpenAIAdapter,
    ProxyOpenAIAdapter,
    RuntimeCancelRequest,
    RuntimeExecuteRequest,
    RuntimeRecoveryPlan,
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
        request_deadline=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    )


class _Protocol:
    def __init__(self) -> None:
        self.store = type(
            "Store",
            (),
            {
                "results": {},
                "requests": {},
                "cancellation_results": {},
                "usage_reports": {},
                "recovery_results": {},
                "streams": {},
                "stream_chunks": {},
                "stream_closes": {},
            },
        )()
        self.acceptances = []
        self.usage_reports = []

    def register_execute_request(self, connection_id, execution_request):
        self.connection_id = connection_id
        self.request = execution_request
        self.store.requests[execution_request.request_id] = _RequestRecord()

    def record_request_accept(self, connection_id, acceptance):
        self.acceptances.append(acceptance)

    def record_usage_report(self, connection_id, report):
        self.usage_reports.append(report)
        self.store.usage_reports[report.usage_report_id] = report

    def record_runtime_result(self, connection_id, result):
        self.store.results[result.request_id] = result
        return result

    def record_runtime_cancel_result(self, connection_id, result):
        self.store.cancellation_results[result.cancellation_id] = result
        return result

    def record_recovery_result(self, connection_id, result):
        self.store.recovery_results[result.plan_id] = result
        return result

    def record_runtime_stream_open(self, connection_id, stream):
        self.store.streams[stream.stream_id] = stream
        return stream

    def record_runtime_stream_chunk(self, connection_id, chunk):
        self.store.stream_chunks.setdefault(chunk.stream_id, {})[chunk.chunk_sequence] = chunk
        return chunk

    def record_runtime_stream_close(self, connection_id, close):
        self.store.stream_closes[close.stream_id] = close
        return close


class _RequestRecord:
    def __init__(self, runtime_request_handle: str | None = None) -> None:
        self.runtime_request_handle = runtime_request_handle
        self.request_state = "ADMITTED"

    def model_copy(self, *, update: dict):
        return _RequestRecord(update.get("runtime_request_handle", self.runtime_request_handle))


def _cancellation(request: RuntimeExecuteRequest) -> RuntimeCancelRequest:
    now = datetime.now(UTC)
    return RuntimeCancelRequest(
        runtime_id=request.runtime_id,
        runtime_generation=request.runtime_generation,
        runtime_configuration_hash=request.runtime_configuration_hash,
        route_generation=request.route_generation,
        session_id=request.session_id,
        request_id=request.request_id,
        cancellation_id="cancel-1",
        cancellation_reason="consumer_requested",
        requested_at=now.isoformat(),
        deadline=(now + timedelta(minutes=1)).isoformat(),
        hypervisor_signature="hypervisor-signed",
    )


def test_llamacpp_adapter_maps_provider_usage_into_final_runtime_evidence(monkeypatch) -> None:
    adapter = LlamaCppOpenAIAdapter(
        endpoint="http://provider",
        model="qwen",
        runtime_signature="runtime-signed",
    )
    calls = []

    def completion(_):
        calls.append(True)
        return {
            "model": "qwen",
            "choices": [{"text": "ok", "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }

    monkeypatch.setattr(adapter, "_completion", completion)
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
    assert calls == [True]


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


def test_llamacpp_adapter_maps_sse_events_to_ordered_stream_evidence(monkeypatch) -> None:
    adapter = LlamaCppOpenAIAdapter(
        endpoint="http://provider",
        model="qwen",
        runtime_signature="runtime-signed",
    )
    monkeypatch.setattr(
        adapter,
        "_stream_completion",
        lambda _: iter(
            [
                {"model": "qwen", "choices": [{"text": "hel", "finish_reason": None}]},
                {"model": "qwen", "choices": [{"text": "lo", "finish_reason": "stop"}]},
            ]
        ),
    )
    protocol = _Protocol()

    result = adapter.execute_streaming(protocol, "connection-1", _request(request_id="stream-1"))

    assert result.terminal_state == "COMPLETED"
    assert result.result_payload == {"text": "hello", "model": "qwen", "finish_reason": "stop"}
    stream = protocol.store.streams["llamacpp-stream-stream-1"]
    assert stream.ordering_model == "STRICT_ORDERED"
    chunks = protocol.store.stream_chunks[stream.stream_id]
    assert [chunks[index].content for index in sorted(chunks)] == ["hel", "lo"]
    close = protocol.store.stream_closes[stream.stream_id]
    assert result.stream_roots == [close.final_content_root]
    assert protocol.usage_reports[0].dimensions[0].model_dump() == {
        "dimension_id": "output_bytes",
        "unit": "byte",
        "availability": "AVAILABLE",
        "authority": "OBSERVABLE_LOCAL",
        "value": 5,
        "cumulative": True,
        "billing_eligible": False,
        "source_reference": {
            "source_type": "RUNTIME_COUNTER",
            "source_id": "llamacpp-sse-output",
            "source_version": None,
            "source_hash": None,
            "observation_boundary": "adapter-delivered-stream",
        },
        "limitations": [],
    }


def test_llamacpp_adapter_reports_unconfirmed_best_effort_cancellation() -> None:
    adapter = LlamaCppOpenAIAdapter(
        endpoint="http://provider",
        model="qwen",
        runtime_signature="runtime-signed",
    )
    protocol = _Protocol()
    cancellation = _cancellation(_request())

    result = adapter.cancel(protocol, "connection-1", cancellation)

    assert result.cancellation_state == "CANCELLATION_PENDING"
    assert result.provider_execution_state == "UNKNOWN"
    assert result.output_stopped is False
    assert result.provider_confirmed_stopped is False
    assert result.side_effect_state == "UNKNOWN"
    assert adapter.cancel(protocol, "connection-1", cancellation) == result


def test_llamacpp_adapter_recovers_only_durable_terminal_evidence(monkeypatch) -> None:
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
    execution_request = _request()
    adapter.execute(protocol, "connection-1", execution_request)

    state = adapter.recovery_state(protocol, execution_request, instance_id="restarted")
    assert state.terminal_requests == [execution_request.request_id]
    assert state.usage_chain_heads[execution_request.request_id]
    recovered = adapter.apply_recovery_plan(
        protocol,
        "connection-2",
        RuntimeRecoveryPlan(
            runtime_id=execution_request.runtime_id,
            runtime_generation=execution_request.runtime_generation,
            route_generation=execution_request.route_generation,
            plan_id="plan-1",
            request_directives={execution_request.request_id: "REDELIVER_FINAL_RESULT"},
            issued_at=datetime.now(UTC).isoformat(),
        ),
    )

    assert recovered.request_results == {execution_request.request_id: "REDELIVERED_FINAL_RESULT"}
    assert recovered.remaining_conflicts == []


def test_proxy_adapter_reports_opaque_usage_and_persists_upstream_operation(monkeypatch) -> None:
    adapter = ProxyOpenAIAdapter(
        endpoint="http://provider",
        model="opaque-model",
        runtime_signature="runtime-signed",
    )
    monkeypatch.setattr(
        adapter,
        "_completion",
        lambda _: {
            "id": "operation-1",
            "model": "opaque-model",
            "choices": [{"text": "ok", "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 99, "completion_tokens": 42},
        },
    )
    protocol = _Protocol()
    request = _request()
    adapter._operation_ids[request.request_id] = "operation-1"

    result = adapter.execute(protocol, "connection-1", request)

    assert result.terminal_state == "COMPLETED"
    assert protocol.store.requests[request.request_id].runtime_request_handle == "operation-1"
    assert [(item.dimension_id, item.availability) for item in protocol.usage_reports[0].dimensions] == [
        ("input_tokens", "UNAVAILABLE"),
        ("output_tokens", "UNAVAILABLE"),
    ]


def test_proxy_adapter_confirms_cancellation_only_from_upstream_operation(monkeypatch) -> None:
    adapter = ProxyOpenAIAdapter(
        endpoint="http://provider",
        model="opaque-model",
        runtime_signature="runtime-signed",
    )
    protocol = _Protocol()
    request = _request()
    adapter._operation_ids[request.request_id] = "operation-1"
    monkeypatch.setattr(
        adapter,
        "_request_json",
        lambda *_: {"status": "cancelled", "confirmed_stopped": True},
    )

    result = adapter.cancel(protocol, "connection-1", _cancellation(request))

    assert result.cancellation_state == "CANCELLED"
    assert result.output_stopped is True
    assert result.provider_confirmed_stopped is True


def test_proxy_adapter_recovers_upstream_operation_without_reexecution(monkeypatch) -> None:
    adapter = ProxyOpenAIAdapter(
        endpoint="http://provider",
        model="opaque-model",
        runtime_signature="runtime-signed",
    )
    protocol = _Protocol()
    request = _request()
    protocol.register_execute_request("connection-1", request)
    adapter._operation_ids[request.request_id] = "operation-1"
    monkeypatch.setattr(adapter, "_request_json", lambda *_: {"status": "running"})

    state = adapter.recovery_state(protocol, request, instance_id="restarted")
    result = adapter.apply_recovery_plan(
        protocol,
        "connection-2",
        RuntimeRecoveryPlan(
            runtime_id=request.runtime_id,
            runtime_generation=request.runtime_generation,
            route_generation=request.route_generation,
            plan_id="proxy-plan-1",
            request_directives={request.request_id: "WAIT_FOR_PROVIDER"},
            issued_at=datetime.now(UTC).isoformat(),
        ),
    )

    assert state.recoverable_requests[0]["provider_execution_reference"] == "operation-1"
    assert result.request_results == {request.request_id: "UPSTREAM_OPERATION_ACTIVE"}
    assert result.remaining_conflicts == []
