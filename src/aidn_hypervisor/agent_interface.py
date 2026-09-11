"""Bounded agent-authored documents; browser edits are intents, never commands.

Only MCP readers register sources. Presentations refer to those snapshots rather
than trusting model-authored values/permissions. All state is included in the
existing operator conversation snapshot, not a second configuration database.
"""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
Scalar = str | bool | int | float | None
MAX_SOURCES = 64
MAX_DOCUMENTS = 8
MAX_INTENTS = 64


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def revision(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class InterfaceField(StrictModel):
    id: Identifier
    label: str = Field(min_length=1, max_length=240)
    type: Literal["text", "number", "integer", "boolean", "select"] = "text"
    value: Scalar
    editable: bool = False
    description: str = Field(default="", max_length=1000)
    minimum: float | None = None
    maximum: float | None = None
    options: list[str] = Field(default_factory=list, max_length=64)

    def validate_value(self, value: Scalar) -> None:
        if self.type in {"number", "integer"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{self.id}: enter a finite number")
            if self.type == "integer" and int(value) != value:
                raise ValueError(f"{self.id}: enter an integer")
            if self.minimum is not None and value < self.minimum:
                raise ValueError(f"{self.id}: below minimum {self.minimum}")
            if self.maximum is not None and value > self.maximum:
                raise ValueError(f"{self.id}: above maximum {self.maximum}")
        elif self.type == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{self.id}: expected a boolean")
        elif self.type in {"text", "select"}:
            if not isinstance(value, str) or not value.strip() or len(value) > 240:
                raise ValueError(f"{self.id}: enter 1..240 characters")
            if self.type == "select" and value not in self.options:
                raise ValueError(f"{self.id}: unsupported option")


class TextBlock(StrictModel):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=8000)


class FieldsBlock(StrictModel):
    type: Literal["fields"]
    source_id: Identifier
    field_ids: list[Identifier] | None = Field(default=None, max_length=64)
    title: str = Field(default="", max_length=240)


class DocumentSpec(StrictModel):
    document_id: Identifier
    title: str = Field(min_length=1, max_length=240)
    blocks: list[Annotated[TextBlock | FieldsBlock, Field(discriminator="type")]] = Field(min_length=1, max_length=16)


class PresentationRequest(StrictModel):
    request_id: Identifier
    document: DocumentSpec | None = None
    scene_source_id: Identifier | None = None

    @model_validator(mode="after")
    def has_content(self):
        if self.document is None and self.scene_source_id is None:
            raise ValueError("A document or scene source is required")
        return self


class FormChange(StrictModel):
    kind: Literal["form_change"]
    document_id: Identifier
    document_revision: int = Field(ge=1)
    source_id: Identifier
    source_revision: str = Field(min_length=1, max_length=128)
    current: dict[Identifier, Scalar] = Field(min_length=1, max_length=64)
    proposed: dict[Identifier, Scalar] = Field(min_length=1, max_length=64)


class AgentInterfaceStore:
    def __init__(self, on_change) -> None:
        self.lock = RLock()
        # Serializes UI mutations without holding the snapshot lock while domain
        # services persist their state (persistence also snapshots this store).
        self.apply_lock = RLock()
        self._changed = on_change
        self.sources: dict[str, dict] = {}
        self.documents: dict[str, dict] = {}
        self.intents: dict[str, dict] = {}
        self.scenes: dict[str, dict] = {}

    def _trim(self) -> None:
        for values, limit in (
            (self.sources, MAX_SOURCES),
            (self.documents, MAX_DOCUMENTS),
            (self.intents, MAX_INTENTS),
            (self.scenes, MAX_DOCUMENTS),
        ):
            while len(values) > limit:
                del values[next(iter(values))]

    def source(self, source_id: str, *, surface_id: str) -> dict:
        with self.lock:
            source = self.sources.get(source_id)
            if source is None or source["surface_id"] != surface_id:
                raise ValueError("Source expired or belongs to another surface; ask the agent to refresh")
            return deepcopy(source)

    def register_source(
        self,
        *,
        surface_id: str,
        kind: str,
        target_id: str,
        source_revision: str,
        fields: list[dict],
        data: dict | None = None,
    ) -> dict:
        validated = [InterfaceField.model_validate(item).model_dump() for item in fields]
        source = {
            "source_id": "source-" + uuid4().hex,
            "surface_id": surface_id,
            "kind": kind,
            "target_id": target_id,
            "revision": source_revision,
            "fields": validated,
            "observed_at": timestamp(),
            "data": data,
        }
        with self.lock:
            self.sources[source["source_id"]] = source
            self._trim()
        self._changed()
        return deepcopy(source)

    def present(self, spec: PresentationRequest, *, surface_id: str) -> dict:
        with self.lock:
            result: dict[str, Any] = {}
            scene_source = self.source(spec.scene_source_id, surface_id=surface_id) if spec.scene_source_id else None
            if scene_source is not None and scene_source["kind"] != "scene":
                raise ValueError("Scene presentation requires a scene source")
            if spec.document is not None:
                key = surface_id + ":" + spec.document.document_id
                previous = self.documents.get(key)
                blocks: list[dict] = []
                field_keys: set[tuple[str, str]] = set()
                for block in spec.document.blocks:
                    if isinstance(block, TextBlock):
                        blocks.append(block.model_dump())
                        continue
                    source = self.source(block.source_id, surface_id=surface_id)
                    if source["kind"] == "scene":
                        raise ValueError("Use scene_source_id for a scene projection")
                    fields = {item["id"]: item for item in source["fields"]}
                    selected = block.field_ids if block.field_ids is not None else list(fields)
                    if not selected or any(field_id not in fields for field_id in selected):
                        raise ValueError("Unknown or empty source fields")
                    for field_id in selected:
                        field_key = (block.source_id, field_id)
                        if field_key in field_keys:
                            raise ValueError("A source field may appear only once in a document")
                        field_keys.add(field_key)
                    blocks.append(
                        {
                            "type": "fields",
                            "title": block.title,
                            "source_id": source["source_id"],
                            "source_revision": source["revision"],
                            "target_id": source["target_id"],
                            "fields": [fields[item] for item in selected],
                        }
                    )
                document = {
                    "schema_version": "agent-document.v1",
                    "document_id": spec.document.document_id,
                    "surface_id": surface_id,
                    "request_id": spec.request_id,
                    "title": spec.document.title,
                    "revision": previous["revision"] + 1 if previous else 1,
                    "blocks": blocks,
                    "updated_at": timestamp(),
                }
                self.documents[key] = document
                result["document"] = deepcopy(document)
            if spec.scene_source_id is not None:
                source = scene_source
                self.scenes[surface_id] = {
                    "source_id": source["source_id"],
                    "revision": source["revision"],
                    "observed_at": source["observed_at"],
                    "data": source["data"],
                }
                result["scene_published"] = True
            self._trim()
        self._changed()
        return result

    def propose(self, change: FormChange, *, surface_id: str, request_id: str) -> dict:
        with self.lock:
            existing = self.intents.get(request_id)
            if existing is not None:
                if existing["surface_id"] != surface_id or existing["change"] != change.model_dump():
                    raise ValueError("Request ID already used for a different change")
                return deepcopy(existing)
            document = self.documents.get(surface_id + ":" + change.document_id)
            if not document or document["revision"] != change.document_revision:
                raise ValueError("Document changed; ask the agent to refresh before applying")
            source = self.source(change.source_id, surface_id=surface_id)
            if source["revision"] != change.source_revision:
                raise ValueError("Source revision does not match")
            visible_ids = {
                field["id"]
                for block in document["blocks"]
                if block["type"] == "fields" and block["source_id"] == change.source_id
                for field in block["fields"]
            }
            fields = {item["id"]: InterfaceField.model_validate(item) for item in source["fields"]}
            if set(change.current) != set(change.proposed):
                raise ValueError("Current and proposed fields must match")
            diff: list[dict] = []
            for field_id, value in change.proposed.items():
                field = fields.get(field_id)
                if field is None or field_id not in visible_ids or not field.editable:
                    raise ValueError("Field is not editable in this document")
                if revision(change.current[field_id]) != revision(field.value):
                    raise ValueError("Original field value does not match the source snapshot")
                field.validate_value(value)
                if value != field.value:
                    diff.append({"path": field_id, "from": field.value, "to": value})
            if not diff:
                raise ValueError("No changed fields")
            if "local_agent_use" in change.proposed and len(diff) > 1:
                raise ValueError("Change local agent access separately from endpoint configuration")
            intent = {
                "intent_id": request_id,
                "surface_id": surface_id,
                "change": change.model_dump(),
                "target": {"kind": source["kind"], "id": source["target_id"], "revision": source["revision"]},
                "diff": diff,
                "state": "PROPOSED",
                "created_at": timestamp(),
                "result": None,
            }
            self.intents[request_id] = intent
            self._trim()
        self._changed()
        return deepcopy(intent)

    def intent(self, intent_id: str) -> dict:
        with self.lock:
            if intent_id not in self.intents:
                raise ValueError("Change intent expired; submit the form again")
            return deepcopy(self.intents[intent_id])

    def complete(self, intent_id: str, result: dict) -> None:
        with self.lock:
            intent = self.intents[intent_id]
            intent.update(state="APPLIED", result=deepcopy(result))
            # The agent's MCP result updates the facts immediately; its next
            # presentation may refine comments/composition in this same frame.
            document = self.documents.get(intent["surface_id"] + ":" + intent["change"]["document_id"])
            source = result.get("source")
            if document is not None and source is not None:
                fields = {item["id"]: item for item in source["fields"]}
                for block in document["blocks"]:
                    if block["type"] == "fields" and block["source_id"] == intent["change"]["source_id"]:
                        block.update(
                            source_id=source["source_id"],
                            source_revision=source["revision"],
                            fields=[fields[item["id"]] for item in block["fields"]],
                        )
                document["revision"] += 1
                document["updated_at"] = timestamp()
                document["request_id"] = intent_id
        self._changed()

    def public(self, surface_id: str | None) -> dict:
        with self.lock:
            return deepcopy(
                {
                    "documents": [item for item in self.documents.values() if item["surface_id"] == surface_id],
                    "intents": [item for item in self.intents.values() if item["surface_id"] == surface_id],
                    "scene": self.scenes.get(surface_id),
                }
            )

    def snapshot(self) -> dict:
        with self.lock:
            return deepcopy(
                {"sources": self.sources, "documents": self.documents, "intents": self.intents, "scenes": self.scenes}
            )

    def restore(self, snapshot: Any) -> None:
        with self.lock:
            for name in ("sources", "documents", "intents", "scenes"):
                values = snapshot.get(name, {}) if isinstance(snapshot, dict) else {}
                setattr(self, name, deepcopy(values) if isinstance(values, dict) else {})
            self._trim()
