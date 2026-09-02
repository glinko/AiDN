from aidn_hypervisor.codex_agent_bridge import (
    DEFAULT_CODEX_MODEL,
    DEFAULT_CODEX_REASONING_EFFORT,
    DEFAULT_PROTOCOL_VERSION,
    OPERATOR_MESSAGE_EVENT,
    CodexAgentBridge,
    CodexThreadState,
    McpRemoteClient,
    _notification_turn_id,
    _result_text,
    extract_operator_messages,
)


def test_extract_operator_messages_keeps_only_valid_operator_chat_events() -> None:
    payload = {
        "items": [
            {
                "event_id": "evt-operator",
                "event_type": OPERATOR_MESSAGE_EVENT,
                "payload": {"text": " Check resources "},
            },
            {
                "event_id": "evt-other",
                "event_type": "aidn.node.ready",
                "payload": {"text": "ignore"},
            },
            {
                "event_id": "evt-empty",
                "event_type": OPERATOR_MESSAGE_EVENT,
                "payload": {"text": "   "},
            },
        ]
    }

    assert extract_operator_messages(payload) == [
        {"event_id": "evt-operator", "text": "Check resources"}
    ]


def test_extract_operator_messages_rejects_missing_inbox_shape() -> None:
    assert extract_operator_messages({"items": "not-a-list"}) == []


def test_result_text_accepts_current_app_server_message_item() -> None:
    assert _result_text({"type": "message", "text": " hello "}) == "hello"


def test_notification_turn_id_accepts_nested_turn_shape() -> None:
    assert _notification_turn_id({"turn": {"id": "turn-nested"}}) == "turn-nested"
    assert _notification_turn_id({"turnId": "turn-flat", "turn": {"id": "other"}}) == "turn-flat"


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


def test_new_codex_thread_uses_unrestricted_app_server_sandbox(tmp_path) -> None:
    class Process:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def request(self, method, params):
            self.calls.append((method, params))
            return {"thread": {"id": "thread-test"}}

    bridge = CodexAgentBridge(
        codex_command="codex",
        codex_home=tmp_path / "codex-home",
        state_file=tmp_path / "thread.json",
        mcp_url="http://example.invalid/mcp",
        mcp_token="test-token",
        workspace=tmp_path,
    )
    process = Process()

    assert bridge._load_or_start_thread(process, CodexThreadState()) == "thread-test"
    assert process.calls[0][1]["sandbox"] == "danger-full-access"
    assert process.calls[0][1]["model"] == DEFAULT_CODEX_MODEL
    assert process.calls[0][1]["reasoningEffort"] == DEFAULT_CODEX_REASONING_EFFORT
