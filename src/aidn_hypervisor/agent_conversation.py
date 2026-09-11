"""Durable operator-to-agent conversation over the existing MCP event path.

The conversation does not invent another agent transport.  Operator messages
become canonical events and a dedicated durable Hook puts them in the bound
MCP agent's inbox.  The agent writes its reply through a narrow MCP tool.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import uuid4

from aidn_hypervisor.agent_interface import AgentInterfaceStore, FormChange, PresentationRequest
from aidn_hypervisor.hook_dispatcher import HookDispatcher, HookDispatcherError
from aidn_hypervisor.workspace_conversations import (
    MAX_MESSAGE_CHARS,
    AgentConversationMessage,
    WorkspaceChatIntent,
    WorkspaceConversationStore,
)

MAX_MESSAGES = 200
OPERATOR_MESSAGE_EVENT = "aidn.operator.agent_message"
MAX_PROGRESS_CHARS = MAX_MESSAGE_CHARS


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _identifier(value: object, *, name: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 256:
        raise ValueError(f"{name} must contain 1..256 characters")
    if any(character.isspace() for character in text):
        raise ValueError(f"{name} must not contain whitespace")
    return text


def _message_text(value: object) -> str:
    text = str(value or "").strip()
    if not text or len(text) > MAX_MESSAGE_CHARS:
        raise ValueError(f"message must contain 1..{MAX_MESSAGE_CHARS} characters")
    return text


class AgentConversationService:
    """Small persistence-friendly chat journal plus one dedicated Hook."""

    SNAPSHOT_VERSION = 1

    def __init__(
        self,
        *,
        operator_id: str,
        hook_dispatcher: HookDispatcher,
        publish_event: Callable[..., Any],
        on_change: Callable[[], None] | None = None,
        node_id: str = "local-node",
    ) -> None:
        self._operator_id = _identifier(operator_id, name="operator identity")
        self._hooks = hook_dispatcher
        self._publish_event = publish_event
        self._on_change = on_change
        self._lock = RLock()
        self._send_lock = RLock()
        self._agent_id: str | None = None
        self._messages: list[AgentConversationMessage] = []
        # Streaming text is deliberately ephemeral.  The completed reply is
        # the only transcript record; keeping deltas out of the durable event
        # journal prevents one model response from becoming hundreds of turns.
        self._progress: dict[str, dict[str, Any]] = {}
        self._sequence = 0
        self.interface = AgentInterfaceStore(self._changed)
        self.workspace = WorkspaceConversationStore(node_id)

    @staticmethod
    def _hook_id(agent_id: str) -> str:
        suffix = hashlib.sha256(agent_id.encode("utf-8")).hexdigest()[:16]
        return f"operator-chat-{suffix}"

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def connect(self, agent_id: object, *, persist: bool = True) -> dict[str, Any]:
        target = _identifier(agent_id, name="agent identity")
        hook_id = self._hook_id(target)
        try:
            self._hooks.create_hook(
                hook_id=hook_id,
                owner_operator_id=self._operator_id,
                target_agent_id=target,
                event_filter={"event_types": {OPERATOR_MESSAGE_EVENT}},
                delivery_mode="DURABLE_INBOX",
            )
        except HookDispatcherError as error:
            if error.code != "MCP_HOOK_EXISTS":
                raise
            existing = self._hooks.get_hook(hook_id)
            if existing.target_agent_id != target:
                raise ValueError("Conversation Hook is bound to another agent") from error
        with self._lock:
            if self._agent_id is not None and self._agent_id != target:
                self.interface.restore({})
                self.workspace.views.clear()
            self._agent_id = target
        if persist:
            self._changed()
        return self.status()

    def send(
        self,
        text: object,
        *,
        request_id: str | None = None,
        surface_id: str | None = None,
        interaction: dict | None = None,
        chat: dict | None = None,
    ) -> dict[str, Any]:
        with self._send_lock:
            return self._send(text, request_id=request_id, surface_id=surface_id, interaction=interaction, chat=chat)

    def _send(
        self,
        text: object,
        *,
        request_id: str | None = None,
        surface_id: str | None = None,
        interaction: dict | None = None,
        chat: dict | None = None,
    ) -> dict[str, Any]:
        body = _message_text(text)
        chat_intent = WorkspaceChatIntent.model_validate(chat) if chat is not None else None
        if chat_intent is not None and (not request_id or not surface_id or interaction is not None):
            raise ValueError("Workspace chat requires request/surface IDs and cannot carry form changes")
        with self._lock:
            agent_id = self._agent_id
            if request_id:
                previous = next(
                    (
                        item
                        for item in self._messages
                        if item.direction == "OPERATOR" and item.request_id == request_id and item.agent_id == agent_id
                    ),
                    self.workspace.lookup(request_id, "OPERATOR"),
                )
                if previous is not None:
                    if previous.agent_id != agent_id or previous.text != body or previous.surface_id != surface_id or previous.chat != chat_intent:
                        raise ValueError("Request ID already used for a different message")
                    if interaction is not None:
                        self.interface.propose(
                            FormChange.model_validate(interaction), surface_id=surface_id, request_id=request_id
                        )
                    return previous.model_dump(mode="json")
            if chat_intent is not None:
                self.workspace.validate(chat_intent, body)
                if chat_intent.action == "message" and any(
                    item.direction == "OPERATOR" and item.agent_id == agent_id and item.chat is not None
                    and item.chat.action == "message" and item.chat.conversation_id == chat_intent.conversation_id
                    and not self.workspace.lookup(item.request_id, "AGENT")
                    for item in self._messages
                ):
                    raise ValueError("Wait for the agent's reply before continuing this conversation")
                if sum(1 for item in self._messages if item.chat and item.chat.action == "message" and item.direction == "OPERATOR"
                       and item.agent_id == agent_id and not self.workspace.lookup(item.request_id, "OPERATOR")) >= 64:
                    raise ValueError("The agent has too many pending Workspace requests; wait for it to catch up")
        if agent_id is None:
            raise ValueError("Connect an MCP agent before sending a message")
        ui = None
        if surface_id is not None:
            if request_id is None:
                raise ValueError("Spatial messages require a request_id")
            ui = {"surface_id": surface_id, "request_id": request_id}
            if chat_intent is not None:
                ui["chat"] = chat_intent.model_dump()
        if interaction is not None:
            if ui is None:
                raise ValueError("Form changes require a surface and request ID")
            intent = self.interface.propose(
                FormChange.model_validate(interaction), surface_id=surface_id, request_id=request_id
            )
            ui["intent_id"] = intent["intent_id"]
            ui["diff"] = intent["diff"]
        event = self._publish_event(
            event_type=OPERATOR_MESSAGE_EVENT,
            message="Operator sent a message to the connected MCP agent",
            details={"agent_id": agent_id, "text": body, "channel": "operator_chat", **({"ui": ui} if ui else {})},
            source="operator-dashboard",
            severity="NOTICE",
            resource_type="agent_channel",
            resource_id=agent_id,
            requires_action=True,
        )
        event_id = str(event.get("event_id") if isinstance(event, Mapping) else getattr(event, "event_id", ""))
        record = AgentConversationMessage(
            message_id=f"chat-{uuid4().hex}",
            direction="OPERATOR",
            agent_id=agent_id,
            text=body,
            created_at=_now(),
            event_id=event_id or None,
            request_id=request_id,
            surface_id=surface_id,
            chat=chat_intent,
        )
        with self._lock:
            self._sequence += 1
            record.sequence = self._sequence
            self._messages.append(record)
            self._trim_messages()
        self._changed()
        return record.model_dump(mode="json")

    def require_agent(self, agent_id: object) -> None:
        if self._agent_id is None or _identifier(agent_id, name="agent identity") != self._agent_id:
            raise ValueError("This MCP agent is not bound to the operator channel")

    def request_context(self, *, agent_id: str, request_id: str) -> AgentConversationMessage:
        with self._lock:
            self.require_agent(agent_id)
            message = next(
                (
                    item
                    for item in self._messages
                    if item.direction == "OPERATOR" and item.request_id == request_id and item.agent_id == agent_id
                ),
                self.workspace.lookup(request_id, "OPERATOR"),
            )
            if message is None or message.surface_id is None or message.agent_id != agent_id:
                raise ValueError("Unknown spatial request for this agent")
            return message.model_copy(deep=True)

    def _trim_messages(self) -> None:
        # Retain unaccepted Workspace intents until MCP consumes them, even if
        # unrelated transport traffic rolls past the 200-message display window.
        pending = [item for item in self._messages[:-MAX_MESSAGES] if item.chat and item.chat.action == "message"
                   and item.direction == "OPERATOR" and item.agent_id == self._agent_id
                   and not self.workspace.lookup(item.request_id, "OPERATOR")]
        self._messages = pending + self._messages[-MAX_MESSAGES:]

    def accept_conversation(self, *, agent_id: str, request_id: str) -> dict:
        with self._lock:
            context = self.request_context(agent_id=agent_id, request_id=request_id)
            result = self.workspace.accept(context)
        self._changed()
        return result

    def publish_workspace(self, *, agent_id: str, request_id: str) -> None:
        with self._lock:
            context = self.request_context(agent_id=agent_id, request_id=request_id)
            self.workspace.publish_catalog(context.surface_id)

    def present(self, *, agent_id: str, payload: dict) -> dict:
        spec = PresentationRequest.model_validate(payload)
        context = self.request_context(agent_id=agent_id, request_id=spec.request_id)
        return self.interface.present(spec, surface_id=context.surface_id)

    def reply(self, *, agent_id: object, text: object, request_id: str | None = None) -> dict[str, Any]:
        sender = _identifier(agent_id, name="agent identity")
        body = _message_text(text)
        with self._lock:
            if self._agent_id is None:
                raise ValueError("No MCP agent is connected to the operator channel")
            if sender != self._agent_id:
                raise ValueError("This MCP agent is not bound to the operator channel")
            context = self.request_context(agent_id=sender, request_id=request_id) if request_id else None
            if request_id:
                previous = next(
                    (
                        item
                        for item in self._messages
                        if item.direction == "AGENT" and item.request_id == request_id and item.agent_id == sender
                    ),
                    self.workspace.lookup(request_id, "AGENT"),
                )
                if previous is not None:
                    return previous.model_dump(mode="json")
            record = AgentConversationMessage(
                message_id=f"chat-{uuid4().hex}",
                direction="AGENT",
                agent_id=sender,
                text=body,
                created_at=_now(),
                request_id=request_id,
                surface_id=context.surface_id if context else None,
                chat=context.chat if context else None,
            )
            self._sequence += 1
            record.sequence = self._sequence
            if context and context.chat:
                # A direct MCP chat.reply is also an agent acceptance, never an
                # HTTP-side write. Dedicated ui.conversation enables early birth.
                self.workspace.accept(context)
                self.workspace.reply(record)
            if request_id:
                self._progress.pop(request_id, None)
            self._messages.append(record)
            self._trim_messages()
        self._changed()
        return record.model_dump(mode="json")

    def progress(
        self,
        *,
        agent_id: object,
        request_id: str,
        text: object = "",
        phase: str = "streaming",
    ) -> dict[str, Any]:
        """Publish ephemeral progress for one exact operator request.

        Progress is an observation for the Spatial surface, not a second
        transcript.  It is bound to the same request context and agent identity
        as the eventual ``reply`` so a stale or foreign agent cannot paint
        arbitrary text into an operator frame.
        """

        sender = _identifier(agent_id, name="agent identity")
        request = _identifier(request_id, name="request ID")
        body = str(text or "")
        if len(body) > MAX_PROGRESS_CHARS:
            raise ValueError(f"progress text must contain at most {MAX_PROGRESS_CHARS} characters")
        if phase not in {"thinking", "streaming"}:
            raise ValueError("progress phase must be thinking or streaming")
        with self._lock:
            context = self.request_context(agent_id=sender, request_id=request)
            # A late delta after the durable reply is harmless and must not
            # resurrect a spinner over the completed message.
            if self.workspace.lookup(request, "AGENT") is not None:
                return {"request_id": request, "surface_id": context.surface_id, "phase": "completed", "text": body}
            record = {
                "request_id": request,
                "surface_id": context.surface_id,
                "conversation_id": context.chat.conversation_id if context.chat else None,
                "agent_id": sender,
                "phase": phase,
                "text": body,
                "updated_at": _now(),
            }
            self._progress[request] = record
        # Do not invoke the persistence callback here.  Progress can arrive
        # many times per second, while the canonical snapshot is intentionally
        # updated only when the final reply is committed.
        return dict(record)

    def status(self, surface_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            agent_id = self._agent_id
            messages = [
                item.model_dump(mode="json")
                for item in self._messages
                if surface_id is None or (item.surface_id == surface_id and item.agent_id == agent_id)
            ]
            workspace = self.workspace.public(surface_id)
            progress = [
                dict(item)
                for item in self._progress.values()
                if surface_id is None or (item["surface_id"] == surface_id and item["agent_id"] == agent_id)
            ]
        hook_id = self._hook_id(agent_id) if agent_id else None
        hook_status: dict[str, Any] | None = None
        if hook_id:
            try:
                hook_status = self._hooks.test_hook(hook_id)
            except HookDispatcherError:
                hook_status = {"status": "NOT_CONFIGURED"}
        return {
            "agent_id": agent_id,
            "connected": agent_id is not None,
            "delivery": hook_status,
            "messages": messages,
            "interface": self.interface.public(surface_id),
            "workspace": workspace,
            "progress": progress,
            "message_limit": MAX_MESSAGES,
            "message_event_type": OPERATOR_MESSAGE_EVENT,
            "media": {
                "text": True,
                "attachments": False,
                "detail": "Binary voice and image attachments require a content-addressed media store and are not written into the event log.",
            },
        }

    def snapshot_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": self.SNAPSHOT_VERSION,
                "agent_id": self._agent_id,
                "sequence": self._sequence,
                "messages": [item.model_dump(mode="json") for item in self._messages],
                "interface": self.interface.snapshot(),
                "workspace": self.workspace.snapshot(),
            }

    def restore_state(self, snapshot: object) -> None:
        if not isinstance(snapshot, Mapping):
            return
        agent_id = snapshot.get("agent_id")
        values = snapshot.get("messages")
        restored: list[AgentConversationMessage] = []
        if isinstance(values, list):
            for value in values[-(MAX_MESSAGES + 64):]:
                try:
                    restored.append(AgentConversationMessage.model_validate(value))
                except Exception:
                    continue
        with self._lock:
            self._agent_id = _identifier(agent_id, name="agent identity") if agent_id else None
            self._messages = restored
            # Progress is intentionally not restored: a process restart must
            # never make an old partial answer look live.
            self._progress = {}
            self.interface.restore(snapshot.get("interface", {}))
            self.workspace.restore(snapshot.get("workspace", {}))
            self._sequence = max(
                int(snapshot.get("sequence", 0)),
                max((item.sequence for item in self._messages), default=0),
                max((item.sequence for session in self.workspace.sessions.values() for item in session.messages), default=0),
            )
        if self._agent_id:
            self.connect(self._agent_id, persist=False)
