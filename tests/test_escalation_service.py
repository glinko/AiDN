from aidn_hypervisor.escalation_service import EscalationTaskError, EscalationTaskService


def _route(provider="large-local"):
    return {
        "status": "ROUTED",
        "selected_provider_id": provider,
        "decision_id": "decision-1",
        "execution": {"started": False, "side_effects": False},
    }


def test_create_bounds_context_and_is_idempotent():
    events = []
    service = EscalationTaskService(on_event=lambda *args: events.append(args))
    first = service.create(
        goal="Diagnose the provider",
        route_decision=_route(),
        context={"authorization": "secret", "nested": {"value": "ok"}},
        idempotency_key="esc-1",
        postconditions=[{"path": "status", "expected": "healthy"}],
    )
    second = service.create(
        goal="Diagnose the provider",
        route_decision=_route(),
        context={"authorization": "secret", "nested": {"value": "ok"}},
        idempotency_key="esc-1",
        postconditions=[{"path": "status", "expected": "healthy"}],
    )
    assert first == second
    assert first["context"]["authorization"] == "[REDACTED]"
    assert first["state"] == "CONTEXT_PREPARED"
    assert any(event[0] == "aidn.escalation.created" for event in events)

    try:
        service.create(
            goal="Different goal",
            route_decision=_route(),
            idempotency_key="esc-1",
        )
    except EscalationTaskError as error:
        assert error.code == "ESCALATION_IDEMPOTENCY_CONFLICT"
    else:
        raise AssertionError("reusing an idempotency key with different content must fail")


def test_plan_hash_approval_and_postcondition_verification():
    service = EscalationTaskService()
    task = service.create(
        goal="Investigate endpoint",
        route_decision=_route(),
        idempotency_key="esc-2",
        postconditions=[
            {"path": "endpoint.health", "expected": "healthy"},
            {"path": "runtime.state", "expected": "running"},
        ],
    )
    planned = service.set_plan(
        task["task_id"],
        {"summary": "Inspect only", "actions": [{"tool": "aidn.endpoint.list", "arguments": {}}]},
        idempotency_key="plan-2",
    )
    assert planned["state"] == "WAITING_APPROVAL"
    assert planned["plan_hash"].startswith("sha256:")
    approved = service.approve(
        task["task_id"],
        plan_hash=planned["plan_hash"],
        approval_reference="approval-2",
        approver_id="operator-1",
    )
    assert approved["state"] == "APPROVED"
    completed = service.verify(
        task["task_id"],
        observed={"endpoint": {"health": "healthy"}, "runtime": {"state": "running"}},
    )
    assert completed["state"] == "COMPLETED"
    assert completed["verification"]["passed"] is True


def test_postcondition_failure_and_snapshot_round_trip():
    service = EscalationTaskService()
    task = service.create(
        goal="Check a node",
        route_decision={"status": "NO_ELIGIBLE_PROVIDER", "selected_provider_id": None},
        idempotency_key="esc-3",
        postconditions=[{"path": "ready", "expected": True}],
    )
    assert task["state"] == "WAITING_PROVIDER"
    planned = service.set_plan(
        task["task_id"],
        {"actions": [{"tool": "aidn.node.status", "arguments": {"verbose": False}}]},
        idempotency_key="plan-3",
        requires_operator_approval=False,
    )
    assert planned["plan"]["actions"][0]["tool"] == "aidn.node.status"
    failed = service.verify(task["task_id"], observed={"ready": False})
    assert failed["state"] == "FAILED"
    assert failed["last_error"]["code"] == "ESCALATION_POSTCONDITION_FAILED"

    restored = EscalationTaskService()
    restored.restore_state(service.snapshot_state())
    restored_task = restored.get(task["task_id"])
    assert restored_task["state"] == "FAILED"
    assert restored_task["plan"]["actions"][0]["tool"] == "aidn.node.status"
