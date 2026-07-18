import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator


ChannelClass = Literal[
    "CONTROL",
    "SERVICE_CONTROL",
    "SESSION_CONTROL",
    "SESSION_DATA",
    "RUNTIME",
    "REGISTRY",
    "VALIDATION",
    "GOVERNANCE",
    "OBSERVABILITY",
    "PLUGIN_CONTROL",
]
PriorityClass = Literal[
    "CRITICAL_CONTROL",
    "HIGH",
    "INTERACTIVE",
    "NORMAL",
    "BULK",
    "BACKGROUND",
]
RouteState = Literal[
    "ACTIVE",
    "STALE",
    "DRAINING",
    "UNREACHABLE",
    "QUARANTINED",
    "REVOKED",
]
DeliveryState = Literal[
    "RECEIVED",
    "ENVELOPE_VALIDATED",
    "AUTHENTICATED",
    "AUTHORIZED",
    "ROUTE_RESOLVED",
    "QUEUED",
    "DELIVERY_ATTEMPTED",
    "DELIVERED",
    "APPLICATION_ACCEPTED",
    "APPLICATION_REJECTED",
    "EXPIRED",
    "RATE_LIMITED",
    "ROUTE_FAILED",
    "DELIVERY_FAILED",
    "DEAD_LETTERED",
    "DUPLICATE",
    "CANCELLED",
]


def canonical_payload_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_payload_hash(payload: dict) -> str:
    return f"sha256:{hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()}"


class NetworkSubject(BaseModel):
    subject_type: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)


class NetworkMessage(BaseModel):
    message_id: str = Field(min_length=1)
    message_type: str = Field(min_length=1)
    message_version: str = "1"
    network_id: str
    chain_id: str
    network_revision: str
    connection_id: str | None = None
    channel_id: str
    channel_class: ChannelClass
    source_subject: NetworkSubject
    destination_subject: NetworkSubject
    correlation_id: str | None = None
    causation_id: str | None = None
    source_sequence: int = Field(ge=0)
    priority_class: PriorityClass = "NORMAL"
    route_generation: int = Field(ge=1)
    created_at: str
    expiration: str
    hop_limit: int = Field(default=0, ge=0)
    payload_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    payload_length: int = Field(ge=0)
    payload_encoding: str = "CANONICAL_JSON"
    payload: dict
    authentication: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_payload_metadata(self):
        encoded = canonical_payload_bytes(self.payload)
        if len(encoded) != self.payload_length:
            raise ValueError("payload_length does not match canonical payload")
        if canonical_payload_hash(self.payload) != self.payload_hash:
            raise ValueError("payload_hash does not match canonical payload")
        return self


class DispatcherRoute(BaseModel):
    destination_type: str
    destination_id: str
    route_type: Literal[
        "LOCAL_PROTOCOL_HANDLER",
        "LOCAL_SERVICE",
        "LOCAL_RUNTIME",
        "LOCAL_PLUGIN",
        "REMOTE_HYPERVISOR",
        "RELAY_PATH",
        "REGISTRY_OBJECT_TRANSFER",
        "UNREACHABLE",
    ]
    route_generation: int = Field(ge=1)
    route_state: RouteState = "ACTIVE"
    allowed_source_types: set[str] = Field(default_factory=set)
    allowed_source_ids: set[str] = Field(default_factory=set)
    allowed_channel_classes: set[ChannelClass] = Field(default_factory=set)
    allowed_message_types: set[str] = Field(default_factory=set)
    configuration_hash: str | None = None
    runtime_binding_hash: str | None = None
    session_contract_hash: str | None = None
    created_at: str
    expires_at: str | None = None


class DeliveryRecord(BaseModel):
    message_id: str
    source_subject: NetworkSubject
    destination_subject: NetworkSubject
    route_generation: int
    delivery_state: DeliveryState
    received_at: str
    queued_at: str | None = None
    delivered_at: str | None = None
    completed_at: str | None = None
    attempt_count: int = Field(default=0, ge=0)
    last_error_code: str | None = None
    payload_hash: str


class DeadLetterRecord(BaseModel):
    message_id: str
    source_subject: NetworkSubject
    destination_subject: NetworkSubject
    message_type: str
    route_generation: int
    failure_stage: str
    error_code: str
    received_at: str
    failed_at: str
    payload_hash: str
    payload_retention_class: str = "HASH_ONLY"
    retryable: bool = False
    operator_action_required: bool = True


class DispatcherReplayRecord(BaseModel):
    message_id: str
    payload_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    processed_at: str
