from aidn_hypervisor.steward_bench import (
    evaluate_steward_case,
    load_steward_bench_cases,
    summarize_steward_bench,
)


def test_steward_bench_fixture_has_required_control_plane_scenarios() -> None:
    cases = load_steward_bench_cases()
    categories = {case.category for case in cases}

    assert len(cases) >= 20
    assert {"runtime_failure", "model_artifact", "operator_mutation", "unknown"} <= categories
    assert any(case.expected_tool == "node.factory_reset" for case in cases)


def test_deterministic_bench_guards_match_every_fixture_case() -> None:
    cases = load_steward_bench_cases()
    results = [evaluate_steward_case(case) for case in cases]

    assert all(result.guard_passed for result in results), [
        result.as_payload() for result in results if not result.guard_passed
    ]
    summary = summarize_steward_bench(results)
    assert summary["guard_intent_accuracy"] == 1.0
    assert summary["guard_block_accuracy"] == 1.0
    assert summary["response_cases"] == 0


def test_structured_decision_is_scored_without_executing_the_tool() -> None:
    case = next(case for case in load_steward_bench_cases() if case.id == "cuda_oom")
    output = (
        '{"intent":"information_request","diagnosis":"CUDA out of memory",'
        '"tool":{"name":"resource.inspect_pressure","arguments":{}},'
        '"approval":"NONE","escalate":false,"answer":"The provider lacks VRAM."}'
    )

    result = evaluate_steward_case(case, output_text=output, latency_ms=123.4, usage={"input_tokens": 42, "output_tokens": 17})

    assert result.passed is True
    assert result.structured_output is True
    assert result.tool_match is True
    assert result.approval_match is True
    assert result.escalation_match is True
    assert result.latency_ms == 123.4


def test_unsafe_action_claim_fails_live_case_even_if_guard_matches() -> None:
    case = next(case for case in load_steward_bench_cases() if case.id == "endpoint_publication_request")

    result = evaluate_steward_case(case, output_text="I published the endpoint successfully.")

    assert result.guard_passed is True
    assert result.false_action is True
    assert result.passed is False


def test_latency_percentiles_use_nearest_rank_for_small_samples() -> None:
    case = next(case for case in load_steward_bench_cases() if case.id == "cuda_oom")
    results = [
        evaluate_steward_case(case, output_text="ok", latency_ms=value)
        for value in (10.0, 20.0, 80.0)
    ]

    summary = summarize_steward_bench(results)

    assert summary["p50_latency_ms"] == 20.0
    assert summary["p95_latency_ms"] == 80.0
