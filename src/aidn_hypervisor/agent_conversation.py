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
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from aidn_hypervisor.hook_dispatcher import HookDispatcher, HookDispatcherError

MAX_MESSAGES = 200
MAX_MESSAGE_CHARS = 16_384
OPERATOR_MESSAGE_EVENT = "aidn.operator.agent_message"


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


class AgentConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=128)
    direction: Literal["OPERATOR", "AGENT"]
    agent_id: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    created_at: str
    event_id: str | None = Field(default=None, max_length=256)


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
    ) -> None:
        self._operator_id = _identifier(operator_id, name="operator identity")
        self._hooks = hook_dispatcher
        self._publish_event = publish_event
        self._on_change = on_change
        self._lock = RLock()
        self._agent_id: str | None = None
        self._messages: list[AgentConversationMessage] = []

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
            self._agent_id = target
        if persist:
            self._changed()
        return self.status()

    def send(self, text: object) -> dict[str, Any]:
        body = _message_text(text)
        with self._lock:
            agent_id = self._agent_id
        if agent_id is None:
            raise ValueError("Connect an MCP agent before sending a message")
        event = self._publish_event(
            event_type=OPERATOR_MESSAGE_EVENT,
            message="Operator sent a message to the connected MCP agent",
            details={"agent_id": agent_id, "text": body, "channel": "operator_chat"},
            source="operator-dashboard",
            severity="NOTICE",
            resource_type="agent_channel",
            resource_id=agent_id,
            requires_action=True,
        )
        event_id = str(
            event.get("event_id") if isinstance(event, Mapping) else getattr(event, "event_id", "")
        )
        record = AgentConversationMessage(
            message_id=f"chat-{uuid4().hex}",
            direction="OPERATOR",
            agent_id=agent_id,
            text=body,
            created_at=_now(),
            event_id=event_id or None,
        )
        with self._lock:
            self._messages.append(record)
            self._messages = self._messages[-MAX_MESSAGES:]
        self._changed()
        return record.model_dump(mode="json")

    def reply(self, *, agent_id: object, text: object) -> dict[str, Any]:
        sender = _identifier(agent_id, name="agent identity")
        body = _message_text(text)
        with self._lock:
            if self._agent_id is None:
                raise ValueError("No MCP agent is connected to the operator channel")
            if sender != self._agent_id:
                raise ValueError("This MCP agent is not bound to the operator channel")
            record = AgentConversationMessage(
                message_id=f"chat-{uuid4().hex}",
                direction="AGENT",
                agent_id=sender,
                text=body,
                created_at=_now(),
            )
            self._messages.append(record)
            self._messages = self._messages[-MAX_MESSAGES:]
        self._changed()
        return record.model_dump(mode="json")

    def status(self) -> dict[str, Any]:
        with self._lock:
            agent_id = self._agent_id
            messages = [item.model_dump(mode="json") for item in self._messages]
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
                "messages": [item.model_dump(mode="json") for item in self._messages[-MAX_MESSAGES:]],
            }

    def restore_state(self, snapshot: object) -> None:
        if not isinstance(snapshot, Mapping):
            return
        agent_id = snapshot.get("agent_id")
        values = snapshot.get("messages")
        restored: list[AgentConversationMessage] = []
        if isinstance(values, list):
            for value in values[-MAX_MESSAGES:]:
                try:
                    restored.append(AgentConversationMessage.model_validate(value))
                except Exception:
                    continue
        with self._lock:
            self._agent_id = _identifier(agent_id, name="agent identity") if agent_id else None
            self._messages = restored
        if self._agent_id:
            self.connect(self._agent_id, persist=False)
