from aidn_hypervisor.codex_agent_bridge import (
    DEFAULT_PROTOCOL_VERSION,
    OPERATOR_MESSAGE_EVENT,
    McpRemoteClient,
    extract_operator_messages,
)


def test_extract_operator_messages_keeps_only_valid_operator_chat_events() -> None:
    payload = {
        "items": [
            {
                "event_id": "evt-operator",
                "event_type": OPERATOR_MESSAGE_EVENT,
                "details": {"text": " Check resources "},
            },
            {
                "event_id": "evt-other",
                "event_type": "aidn.node.ready",
                "details": {"text": "ignore"},
            },
            {
                "event_id": "evt-empty",
                "event_type": OPERATOR_MESSAGE_EVENT,
                "details": {"text": "   "},
            },
        ]
    }

    assert extract_operator_messages(payload) == [
        {"event_id": "evt-operator", "text": "Check resources"}
    ]


def test_extract_operator_messages_rejects_missing_inbox_shape() -> None:
    assert extract_operator_messages({"items": "not-a-list"}) == []


def test_mcp_remote_client_accepts_lowercase_session_header(monkeypatch) -> None:
    client = McpRemoteClient(url="http://example.invalid/mcp", bearer_token="test-token")
    calls: list[tuple[str, bool]] = []

    def fake_post(method, _params, *, include_id=True):
        calls.append((method, include_id))
        if method == "initialize":
            return ({"result": {"protocolVersion": DEFAULT_PROTOCOL_VERSION}}, {"mcp-session-id": "mcp-test"})
        return ({}, {})

    monkeypatch.setattr(client, "_post", fake_post)

    client.initialize()

    assert client._session_id == "mcp-test"
    assert calls == [("initialize", True), ("notifications/initialized", False)]

    client.initialize()

    assert calls == [("initialize", True), ("notifications/initialized", False)]
