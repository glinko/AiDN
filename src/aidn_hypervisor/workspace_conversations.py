"""Node-owned Workspace conversations, not economic/protocol AiDN Sessions.

The operator channel transports intents. Only a bound MCP agent accepts them
into this archive. The channel's lock and persistence callback own this store;
there is no second database, browser authority, or time-based transcript eviction.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aidn_hypervisor.agent_interface import Identifier

MAX_MESSAGE_CHARS = 16_384
MAX_WORKSPACE_SESSIONS = 128
MAX_SESSION_TURNS = 2_000
MAX_ARCHIVE_CHARS = 8 * 1024 * 1024


class WorkspaceChatIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: Identifier
    action: Literal["message", "open"] = "message"


class AgentConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=128)
    direction: Literal["OPERATOR", "AGENT"]
    agent_id: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    created_at: str
    sequence: int = Field(default=0, ge=0)
    event_id: str | None = Field(default=None, max_length=256)
    request_id: str | None = Field(default=None, max_length=128)
    surface_id: str | None = Field(default=None, max_length=128)
    chat: WorkspaceChatIntent | None = None


class WorkspaceConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: Identifier
    title: str = Field(min_length=1, max_length=240)
    order: int = Field(ge=0)
    messages: list[AgentConversationMessage]


class WorkspaceConversationStore:
    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.sessions: dict[str, WorkspaceConversation] = {}
        self.views: dict[str, tuple[str | None, str | None, int, str]] = {}
        self.revision = 0
        self._index: dict[tuple[str, str], AgentConversationMessage] = {}

    def lookup(self, request_id: str, direction: str) -> AgentConversationMessage | None:
        return self._index.get((request_id, direction))

    def validate(self, chat: WorkspaceChatIntent, text: str) -> None:
        session = self.sessions.get(chat.conversation_id)
        if chat.action == "open":
            if session is None:
                raise ValueError("This Workspace Session does not exist")
            return
        if session is None and len(self.sessions) >= MAX_WORKSPACE_SESSIONS:
            raise ValueError(
                "Workspace archive is full. Existing conversations are preserved; export/archiving is required."
            )
        if session and len(session.messages) + 2 > MAX_SESSION_TURNS:
            raise ValueError("This conversation is full. Start a new Workspace Session; its history is preserved.")
        if session and session.messages[-1].direction == "OPERATOR":
            raise ValueError("Wait for the agent's reply before continuing this conversation")
        # Reserve space for every pending agent response, not just today's text.
        used = sum(len(message.text) for item in self.sessions.values() for message in item.messages)
        reserved = sum(
            MAX_MESSAGE_CHARS for item in self.sessions.values() if item.messages[-1].direction == "OPERATOR"
        )
        if used + reserved + len(text) + MAX_MESSAGE_CHARS > MAX_ARCHIVE_CHARS:
            raise ValueError("Workspace archive is full. No conversation history was removed.")

    def publish_catalog(self, surface_id: str) -> None:
        self.views.setdefault(surface_id, (None, None, 0, ""))
        # Publications are ephemeral and re-authorized through MCP after reload.
        while len(self.views) > 64:
            del self.views[next(iter(self.views))]

    def accept(self, message: AgentConversationMessage) -> dict:
        chat = message.chat
        if chat is None or not message.request_id or not message.surface_id:
            raise ValueError("This request is not a Workspace conversation intent")
        if chat.action == "open":
            self.validate(chat, message.text)
        elif self.lookup(message.request_id, "OPERATOR") is None:
            self.validate(chat, message.text)
            session = self.sessions.get(chat.conversation_id)
            if session is None:
                session = WorkspaceConversation(
                    conversation_id=chat.conversation_id,
                    title=" ".join(message.text.split())[:120],
                    order=len(self.sessions),
                    messages=[],
                )
                self.sessions[chat.conversation_id] = session
            saved = message.model_copy(deep=True)
            session.messages.append(saved)
            self._index[(message.request_id, "OPERATOR")] = saved
            self.revision += 1
        self.publish_catalog(message.surface_id)
        # A late reply or replay from a previously closed chat must not steal
        # the operator's newer foreground conversation on the same surface.
        if (message.sequence, message.created_at) >= self.views[message.surface_id][2:]:
            self.views[message.surface_id] = (
                chat.conversation_id,
                message.request_id,
                message.sequence,
                message.created_at,
            )
        return {
            "conversation_id": chat.conversation_id,
            "action": chat.action,
            "answered": self.lookup(message.request_id, "AGENT") is not None,
            "conversation": self.document(chat.conversation_id),
        }

    def reply(self, message: AgentConversationMessage) -> None:
        if message.chat is None or message.chat.action == "open":
            return
        if self.lookup(message.request_id, "AGENT") is not None:
            return
        if self.lookup(message.request_id, "OPERATOR") is None:
            raise ValueError("Accept the Workspace request before replying")
        session = self.sessions[message.chat.conversation_id]
        saved = message.model_copy(deep=True)
        session.messages.append(saved)
        self._index[(message.request_id, "AGENT")] = saved
        self.revision += 1

    def artifact(self, session: WorkspaceConversation) -> dict:
        first, last = session.messages[0], session.messages[-1]
        return {
            "schema_version": "spatial.artifact.v1",
            "artifact_id": f"artifact:{session.conversation_id}",
            "session_id": session.conversation_id,
            "workspace_id": f"workspace:{self.node_id}",
            "node_id": self.node_id,
            "revision": len(session.messages),
            "title": session.title,
            "summary": last.text[:240],
            "turn_count": len(session.messages),
            "turn_refs": [message.message_id for message in session.messages],
            "object_refs": [],
            "context_root_ref": f"context:{session.conversation_id}",
            "state": "ACTIVE",
            "pinned": False,
            "camera_snapshot": None,
            "created_at": first.created_at,
            "updated_at": last.created_at,
        }

    def document(self, conversation_id: str) -> dict:
        record = self.sessions[conversation_id]
        artifact = self.artifact(record)
        first, last = record.messages[0], record.messages[-1]
        session = {
            "schema_version": "spatial.workspace-session.v1",
            **{
                key: artifact[key]
                for key in (
                    "session_id",
                    "workspace_id",
                    "node_id",
                    "revision",
                    "title",
                    "summary",
                    "turn_refs",
                    "object_refs",
                    "context_root_ref",
                    "created_at",
                    "updated_at",
                )
            },
            "state": "SUBMITTING" if last.direction == "OPERATOR" else "ACTIVE",
            "root_intent_id": first.request_id,
            "parent_session_id": None,
            "structural_parent_ref": None,
            "semantic_anchor": "primary-agent",
            "artifact_ref": artifact["artifact_id"],
        }
        turns = [
            {
                "schema_version": "spatial.conversation-turn.v1",
                "turn_id": message.message_id,
                "session_id": conversation_id,
                "workspace_id": artifact["workspace_id"],
                "node_id": self.node_id,
                "revision": 1,
                "sequence": index,
                "role": "operator" if message.direction == "OPERATOR" else "agent",
                "state": "COMPLETED",
                "text": message.text,
                "intent_id": message.request_id,
                "provenance": {
                    "intent_id": message.request_id,
                    "correlation_id": message.request_id,
                    "binding_id": message.agent_id,
                    "source_ref": message.event_id,
                },
                "citation_refs": [],
                "attachment_refs": [],
                "created_at": message.created_at,
                "updated_at": message.created_at,
            }
            for index, message in enumerate(record.messages)
        ]
        return {"session": session, "artifact": artifact, "turns": turns}

    def public(self, surface_id: str | None) -> dict | None:
        if surface_id not in self.views:
            return None
        active_id, request_id, _, _ = self.views[surface_id]
        return {
            "revision": self.revision,
            "artifacts": [{"artifact": self.artifact(item), "order": item.order} for item in self.sessions.values()],
            "active": {**self.document(active_id), "request_id": request_id} if active_id else None,
        }

    def snapshot(self) -> dict:
        return {"version": 1, "sessions": [item.model_dump(mode="json") for item in self.sessions.values()]}

    def restore(self, snapshot: dict) -> None:
        # Fail closed on malformed archives, never silently discard durable turns.
        records = [WorkspaceConversation.model_validate(item) for item in snapshot.get("sessions", [])]
        if any(not item.messages for item in records):
            raise ValueError("Workspace archive contains an empty session")
        if len({item.conversation_id for item in records}) != len(records):
            raise ValueError("Workspace archive contains duplicate session identities")
        seen = set()
        for item in records:
            for index, message in enumerate(item.messages):
                key = (message.request_id, message.direction)
                if (
                    not message.request_id
                    or not message.surface_id
                    or not message.chat
                    or message.chat.conversation_id != item.conversation_id
                    or message.chat.action != "message"
                    or message.direction != ("OPERATOR" if index % 2 == 0 else "AGENT")
                    or key in seen
                    or (index % 2 and message.request_id != item.messages[index - 1].request_id)
                ):
                    raise ValueError("Workspace archive has invalid turn provenance; history was not replaced")
                seen.add(key)
        self.sessions = {item.conversation_id: item for item in records}
        self._index = {
            (message.request_id, message.direction): message for item in records for message in item.messages
        }
        self.revision = sum(len(item.messages) for item in records)
        self.views = {}
