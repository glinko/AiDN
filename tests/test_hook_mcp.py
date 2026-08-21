from tests.test_mcp_server import _call, _initialize, _server


def test_mcp_hook_read_tools_and_resource_are_scope_filtered() -> None:
    server = _server("HOOK:READ")
    _initialize(server)
    server.control.service.create_hook(
        hook_id="watch",
        owner_operator_id="operator:test",
        target_agent_id="agent:test",
        event_filter={"event_types": {"aidn.node.ready"}},
    )

    listed = _call(server, "aidn.hook.list")
    assert listed["isError"] is False
    assert listed["structuredContent"]["items"][0]["hook_id"] == "watch"
    assert _call(server, "aidn.hook.metrics")["structuredContent"]["queue_depth"] == 0

    resource = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "resources/read",
            "params": {"uri": "aidn://hooks"},
        }
    )
    assert resource["result"]["contents"][0]["mimeType"] == "application/json"


def test_mcp_hook_mutations_are_plan_bound_and_operator_owned() -> None:
    server = _server(
        "HOOK:READ",
        "HOOK:MANAGE",
        approval_policy={"hook_manage": "OPERATOR_CONFIRMATION"},
    )
    _initialize(server)
    request = {
        "hook_id": "watch-provider",
        "target_agent_id": "agent:test",
        "event_filter": {"event_types": ["aidn.provider.failed"]},
        "delivery_mode": "DURABLE_INBOX",
        "mode": "plan",
        "request_id": "request-hook-create",
        "idempotency_key": "idem-hook-create",
    }
    plan = _call(server, "aidn.hook.create", request)["structuredContent"]
    assert plan["requires_approval"] is True
    assert "create a DURABLE_INBOX Hook" in plan["changes"][0]

    denied = _call(
        server,
        "aidn.hook.create",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )
    assert denied["structuredContent"]["error"]["code"] == "MCP_APPROVAL_REQUIRED"

    server.control.approve_plan(
        plan["plan_hash"],
        approval_reference="operator-hook-create",
        approver_identity="operator:test",
    )
    created = _call(
        server,
        "aidn.hook.create",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )["structuredContent"]
    assert created["status"] == "created"
    assert created["hook"]["owner_operator_id"] == "operator:test"

    listed = _call(server, "aidn.hook.list")["structuredContent"]["items"]
    assert [item["hook_id"] for item in listed] == ["watch-provider"]
    tested = _call(server, "aidn.hook.test", {"hook_id": "watch-provider"})["structuredContent"]
    assert tested["status"] == "READY"
    assert tested["synthetic"] is True

    update_request = {
        "hook_id": "watch-provider",
        "enabled": False,
        "mode": "plan",
        "request_id": "request-hook-pause",
        "idempotency_key": "idem-hook-pause",
    }
    pause_plan = _call(server, "aidn.hook.pause", update_request)["structuredContent"]
    server.control.approve_plan(
        pause_plan["plan_hash"],
        approval_reference="operator-hook-pause",
        approver_identity="operator:test",
    )
    paused = _call(
        server,
        "aidn.hook.pause",
        {**update_request, "mode": "apply", "plan_hash": pause_plan["plan_hash"]},
    )["structuredContent"]
    assert paused["hook"]["enabled"] is False
    assert _call(server, "aidn.hook.test", {"hook_id": "watch-provider"})["structuredContent"]["status"] == "PAUSED"
