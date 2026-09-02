from aidn_hypervisor.codex_agent_bridge import OPERATOR_MESSAGE_EVENT, extract_operator_messages


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
