from __future__ import annotations

import pytest

from aidn_hypervisor.codex_agent_bridge import CodexAgentBridge, CodexThreadState
from aidn_hypervisor.workspace_conversations import WorkspaceChatIntent
from tests.test_agent_interface import setup_frame
from tests.test_mcp_server import _call


def send(
    channel, text="Начнём диалог", *, session="seed-a", request="seed-request", surface="surface-a", action="message"
):
    return channel.send(
        text, request_id=request, surface_id=surface, chat={"conversation_id": session, "action": action}
    )


def accept(server, request="seed-request"):
    result = _call(server, "aidn.ui.conversation", {"request_id": request})
    assert not result["isError"], result
    return result["structuredContent"]


def test_cube_is_created_only_by_bound_agent_mcp_and_reply_stays_in_same_session():
    server, _, _ = setup_frame()
    channel = server.control.service.agent_channel
    send(channel)
    assert channel.workspace.sessions == {}
    assert channel.status("surface-a")["workspace"] is None
    accepted = accept(server)
    assert accepted["conversation"]["artifact"]["turn_count"] == 1
    assert len(channel.workspace.sessions) == 1
    assert channel.status("surface-b")["workspace"] is None
    result = _call(server, "aidn.operator.chat.reply", {"request_id": "seed-request", "text": "Привет!"})
    assert not result["isError"], result
    send(channel, "Продолжим", request="followup")
    accept(server, "followup")
    channel.reply(agent_id="agent:test", text="Конечно", request_id="followup")
    document = channel.status("surface-a")["workspace"]["active"]
    assert document["session"]["node_id"] == server.control.service.node_id
    assert document["session"]["state"] == "ACTIVE"
    assert [turn["text"] for turn in document["turns"]] == ["Начнём диалог", "Привет!", "Продолжим", "Конечно"]
    assert len(channel.workspace.sessions) == 1
    # Inbox replay does not create cubes, turns or rerun a completed reply.
    assert accept(server)["answered"] is True
    channel.reply(agent_id="agent:test", text="different retry", request_id="seed-request")
    assert len(channel.workspace.document("seed-a")["turns"]) == 4


def test_agent_progress_is_surface_bound_ephemeral_and_clears_on_reply():
    server, _, _ = setup_frame()
    channel = server.control.service.agent_channel
    send(channel, request="progress-request")
    streamed = channel.progress(
        agent_id="agent:test", request_id="progress-request", text="Проверяю", phase="streaming"
    )
    assert streamed["phase"] == "streaming"
    assert channel.status("surface-a")["progress"][0]["text"] == "Проверяю"
    assert channel.status("surface-b")["progress"] == []
    channel.reply(agent_id="agent:test", text="Готово", request_id="progress-request")
    assert channel.status("surface-a")["progress"] == []
    late = channel.progress(
        agent_id="agent:test", request_id="progress-request", text="запоздалый фрагмент"
    )
    assert late["phase"] == "completed"
    assert channel.status("surface-a")["progress"] == []


def test_archive_survives_transport_rollover_restart_and_agent_mediated_reopen():
    server, _, _ = setup_frame()
    channel = server.control.service.agent_channel
    for index in range(105):
        request = f"turn-{index}"
        send(channel, f"Вопрос {index}", request=request)
        accept(server, request)
        channel.reply(agent_id="agent:test", text=f"Ответ {index}", request_id=request)
    assert len(channel.status()["messages"]) == 200
    snapshot = channel.snapshot_state()
    channel.restore_state(snapshot)
    assert channel.status("surface-a")["workspace"] is None  # Reauthorize publication after restart.
    send(channel, "Открой этот диалог", request="open", surface="surface-new", action="open")
    accept(server, "open")
    channel.reply(agent_id="agent:test", text="Диалог открыт", request_id="open")
    document = channel.status("surface-new")["workspace"]["active"]
    assert len(document["turns"]) == 210
    assert document["turns"][0]["text"] == "Вопрос 0"
    assert len(channel.workspace.sessions) == 1
    # Request provenance and dedupe are not limited to the display journal.
    assert accept(server, "turn-0")["answered"]
    send(channel, "Вопрос 0", request="turn-0")
    with pytest.raises(ValueError, match="different message"):
        send(channel, "Вопрос 0", session="forged", request="turn-0")


def test_chat_authority_limits_and_pending_intents_preserve_history(monkeypatch):
    server, _, _ = setup_frame()
    channel = server.control.service.agent_channel
    send(channel)
    for index in range(220):
        channel.send(f"Другой запрос {index}")
    assert channel.request_context(agent_id="agent:test", request_id="seed-request").text == "Начнём диалог"
    with pytest.raises(ValueError, match="not bound"):
        channel.accept_conversation(agent_id="other", request_id="seed-request")
    assert _call(server, "aidn.ui.conversation", {"request_id": "made-up"})["isError"]
    with pytest.raises(ValueError, match="Wait"):
        send(channel, "Ещё один", request="racing")
    accept(server)
    channel.reply(agent_id="agent:test", text="Привет", request_id="seed-request")
    monkeypatch.setattr("aidn_hypervisor.workspace_conversations.MAX_WORKSPACE_SESSIONS", 1)
    with pytest.raises(ValueError, match="archive is full"):
        send(channel, session="seed-b", request="new")
    assert len(channel.workspace.document("seed-a")["turns"]) == 2
    with pytest.raises(ValueError, match="does not exist"):
        send(channel, session="unknown", request="open-missing", action="open")
    with pytest.raises(ValueError):
        WorkspaceChatIntent.model_validate({"conversation_id": "bad id", "action": "message"})
    with pytest.raises(ValueError):
        channel.send(
            "Bad", request_id="mixed", surface_id="surface-a", chat={"conversation_id": "seed-a"}, interaction={}
        )


def test_independent_workspace_sessions_have_stable_birth_order_and_survive_rebinding():
    server, _, _ = setup_frame()
    channel = server.control.service.agent_channel
    for name in ("a", "b", "c"):
        send(channel, session=name, request=name)
        accept(server, name)
        channel.reply(agent_id="agent:test", text=name, request_id=name)
    before = channel.status("surface-a")["workspace"]["artifacts"]
    assert [(item["artifact"]["session_id"], item["order"]) for item in before] == [("a", 0), ("b", 1), ("c", 2)]
    channel.connect("new-agent")
    assert channel.status("surface-a")["workspace"] is None
    assert len(channel.workspace.sessions) == 3
    with pytest.raises(ValueError):
        channel.accept_conversation(agent_id="new-agent", request_id="a")
    send(channel, session="a", request="reopen", action="open")
    opened = channel.accept_conversation(agent_id="new-agent", request_id="reopen")
    assert opened["conversation"]["turns"][0]["provenance"]["binding_id"] == "agent:test"


def test_bridge_uses_distinct_durable_model_threads_per_workspace_session(tmp_path):
    class Process:
        calls = []

        def request(self, method, params):
            self.calls.append((method, params))
            return {"thread": {"id": params.get("threadId", f"thread-{len(self.calls)}")}}

    bridge = CodexAgentBridge(
        codex_command="codex",
        codex_home=tmp_path,
        state_file=tmp_path / "state.json",
        mcp_url="http://example.invalid/mcp",
        mcp_token="test",
        workspace=tmp_path,
    )
    process = Process()
    state = CodexThreadState()
    first = bridge._load_or_start_thread(process, state, conversation_id="a")
    second = bridge._load_or_start_thread(process, state, conversation_id="b")
    assert first != second
    restored = CodexThreadState.load(bridge._state_file)
    assert bridge._load_or_start_thread(process, restored, conversation_id="a") == first
    assert restored.thread_id is None
    assert process.calls[-1] == ("thread/resume", {"threadId": first, "excludeTurns": True})


def test_late_reply_does_not_replace_the_newer_foreground_conversation():
    server, _, _ = setup_frame()
    channel = server.control.service.agent_channel
    send(channel, session="first", request="first")
    accept(server, "first")
    send(channel, session="second", request="second")
    accept(server, "second")
    channel.reply(agent_id="agent:test", text="Late answer", request_id="first")
    assert channel.status("surface-a")["workspace"]["active"]["session"]["session_id"] == "second"
    assert channel.workspace.document("first")["turns"][-1]["text"] == "Late answer"
    assert accept(server, "first")["answered"]
    assert channel.status("surface-a")["workspace"]["active"]["session"]["session_id"] == "second"


def test_corrupt_archive_does_not_silently_replace_saved_history():
    server, _, _ = setup_frame()
    channel = server.control.service.agent_channel
    send(channel)
    accept(server)
    snapshot = channel.workspace.snapshot()
    snapshot["sessions"].append(snapshot["sessions"][0])
    with pytest.raises(ValueError, match="duplicate"):
        channel.workspace.restore(snapshot)
    assert len(channel.workspace.sessions) == 1


def test_bridge_accepts_via_mcp_isolates_turns_and_skips_inference_on_replay_and_open(tmp_path, monkeypatch):
    server, _, _ = setup_frame()
    channel = server.control.service.agent_channel
    inbox = []
    for name in ("a", "b"):
        record = send(channel, name, session=name, request=name)
        inbox.append(
            {
                "event_id": record["event_id"] or "event-" + name,
                "event_type": "aidn.operator.agent_message",
                "payload": {
                    "text": name,
                    "ui": {
                        "surface_id": "surface-a",
                        "request_id": name,
                        "chat": {"conversation_id": name, "action": "message"},
                    },
                },
            }
        )

    class Mcp:
        def initialize(self):
            pass

        def call_tool(self, name, arguments):
            if name == "aidn.event.inbox":
                return {"items": inbox}
            if name == "aidn.event.ack":
                return {"acked": arguments["event_ids"]}
            result = _call(server, name, arguments)
            assert not result["isError"], result
            return result["structuredContent"]

    class Process:
        count = 0

        def request(self, method, params):
            if method == "thread/start":
                self.count += 1
            return {"thread": {"id": params.get("threadId", f"thread-{self.count}")}}

        def close(self):
            pass

    bridge = CodexAgentBridge(
        codex_command="codex",
        codex_home=tmp_path,
        state_file=tmp_path / "threads.json",
        mcp_url="http://example.invalid/mcp",
        mcp_token="test",
        workspace=tmp_path,
    )
    monkeypatch.setattr(bridge, "_mcp", Mcp())
    starts = []
    turns = []

    def start():
        starts.append(True)
        return Process()

    def run(_process, thread, text, *, ui):
        turns.append((thread, text, ui["chat"]["conversation_id"]))
        return "Ответ " + text

    monkeypatch.setattr(bridge, "_app_server", start)
    monkeypatch.setattr(bridge, "_run_turn", run)
    assert bridge.relay_once() == 2
    assert turns == [("thread-1", "a", "a"), ("thread-2", "b", "b")]
    assert bridge.relay_once() == 2  # Simulated lost ACK.
    assert len(turns) == 2 and len(starts) == 1
    record = send(channel, "Open", session="a", request="open-a", action="open")
    inbox[:] = [
        {
            "event_id": record["event_id"] or "event-open",
            "event_type": "aidn.operator.agent_message",
            "payload": {
                "text": "Open",
                "ui": {
                    "surface_id": "surface-a",
                    "request_id": "open-a",
                    "chat": {"conversation_id": "a", "action": "open"},
                },
            },
        }
    ]
    assert bridge.relay_once() == 1
    assert len(turns) == 2 and len(starts) == 1
    assert len(channel.workspace.document("a")["turns"]) == 2
