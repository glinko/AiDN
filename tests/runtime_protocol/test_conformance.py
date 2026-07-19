import pytest

from aidn_hypervisor.runtime_protocol import (
    RuntimeProtocolConformanceHarness,
    RuntimeProtocolError,
)


def test_conformance_harness_records_success_error_and_idempotency() -> None:
    harness = RuntimeProtocolConformanceHarness()
    calls = 0

    def idempotent_operation() -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"request_id": "request-1", "result_hash": "sha256:result"}

    first = harness.assert_idempotent(
        "result_redelivery",
        idempotent_operation,
        identity=lambda result: result["result_hash"],
    )
    error = harness.assert_protocol_error(
        "stale_route",
        lambda: (_ for _ in ()).throw(
            RuntimeProtocolError("RUNTIME_ROUTE_GENERATION_MISMATCH", "route", "stale")
        ),
        "RUNTIME_ROUTE_GENERATION_MISMATCH",
    )

    report = harness.report()

    assert first["request_id"] == "request-1"
    assert error.code == "RUNTIME_ROUTE_GENERATION_MISMATCH"
    assert calls == 2
    assert report.passed is True
    assert [case.case_id for case in report.cases] == [
        "result_redelivery.initial",
        "result_redelivery.redelivery",
        "result_redelivery",
        "stale_route",
    ]


def test_conformance_harness_fails_when_wrong_error_is_returned() -> None:
    harness = RuntimeProtocolConformanceHarness()

    with pytest.raises(AssertionError, match="unexpected Runtime Protocol error"):
        harness.assert_protocol_error(
            "wrong_error",
            lambda: (_ for _ in ()).throw(
                RuntimeProtocolError("RUNTIME_NOT_READY", "connection", "not ready")
            ),
            "RUNTIME_ROUTE_GENERATION_MISMATCH",
        )

    assert harness.report().passed is False
