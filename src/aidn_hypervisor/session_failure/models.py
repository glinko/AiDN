"""RFC-0060 Session Failure, Recovery and Forced Settlement — models."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Failure Classification (§8)
# ---------------------------------------------------------------------------

class FailureClass(str, Enum):
    """Primary failure class for an abnormal Session termination."""

    CONSUMER_DISCONNECTED = "CONSUMER_DISCONNECTED"
    PROVIDER_DISCONNECTED = "PROVIDER_DISCONNECTED"
    RUNTIME_FAILURE = "RUNTIME_FAILURE"
    ENDPOINT_FAILURE = "ENDPOINT_FAILURE"
    UPSTREAM_PROXY_FAILURE = "UPSTREAM_PROXY_FAILURE"
    ACCOUNTING_MISMATCH = "ACCOUNTING_MISMATCH"
    USAGE_REPORT_TIMEOUT = "USAGE_REPORT_TIMEOUT"
    ACKNOWLEDGEMENT_TIMEOUT = "ACKNOWLEDGEMENT_TIMEOUT"
    DEPOSIT_EXHAUSTED = "DEPOSIT_EXHAUSTED"
    SESSION_TIMEOUT = "SESSION_TIMEOUT"
    IDLE_TIMEOUT = "IDLE_TIMEOUT"
    CONSUMER_FORCE_CLOSE = "CONSUMER_FORCE_CLOSE"
    PROVIDER_FORCE_CLOSE = "PROVIDER_FORCE_CLOSE"
    PROTOCOL_INCOMPATIBILITY = "PROTOCOL_INCOMPATIBILITY"
    CONSENSUS_INTERRUPTION = "CONSENSUS_INTERRUPTION"
    STATE_RECOVERY_FAILURE = "STATE_RECOVERY_FAILURE"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


# ---------------------------------------------------------------------------
# Failure Attribution (§9)
# ---------------------------------------------------------------------------

class FailureAttribution(str, Enum):
    """Fault attribution for a Session failure."""

    CONSUMER_AT_FAULT = "CONSUMER_AT_FAULT"
    PROVIDER_AT_FAULT = "PROVIDER_AT_FAULT"
    BOTH_AT_FAULT = "BOTH_AT_FAULT"
    EXTERNAL_FAILURE = "EXTERNAL_FAILURE"
    PROTOCOL_FAILURE = "PROTOCOL_FAILURE"
    INCONCLUSIVE = "INCONCLUSIVE"


# ---------------------------------------------------------------------------
# Evidence Levels (§11)
# ---------------------------------------------------------------------------

class EvidenceLevel(str, Enum):
    """Quality tier for failure evidence."""

    CRYPTOGRAPHIC = "CRYPTOGRAPHIC"
    REPRODUCIBLE = "REPRODUCIBLE"
    OBSERVATIONAL = "OBSERVATIONAL"


# ---------------------------------------------------------------------------
# Extended Session Status (§5)
# ---------------------------------------------------------------------------
# Existing: queued, active, closed
# New failure-related states added below.
# Terminal states: SETTLED, FORCE_SETTLED, REJECTED, CANCELLED, EXPIRED, UNRECOVERABLE

SessionFailureStatus = Literal[
    # existing
    "queued",
    "active",
    "closed",
    # failure / recovery states
    "rejected",
    "cancelled",
    "expired",
    "recovering",
    "paused",
    "deposit_exhausted",
    "accounting_mismatch",
    "provider_unavailable",
    "consumer_unavailable",
    "force_closing",
    "force_settled",
    "unrecoverable",
]


def is_terminal_status(status: str) -> bool:
    """Return True when *status* is a terminal Session state."""
    return status in {
        "closed",
        "rejected",
        "cancelled",
        "expired",
        "force_settled",
        "unrecoverable",
    }


def is_failure_status(status: str) -> bool:
    """Return True when *status* indicates a non-ordinary failure path."""
    return status not in {"queued", "active", "closed"}


# ---------------------------------------------------------------------------
# Failure Evidence Record (§10, §11)
# ---------------------------------------------------------------------------

class FailureEvidenceRecord(BaseModel):
    """A single piece of evidence collected during failure handling."""

    session_id: str = Field(min_length=1)
    evidence_level: EvidenceLevel
    category: str = Field(
        min_length=1,
        description="e.g. transport_timeout, signed_report, hash_mismatch",
    )
    detail: str = Field(
        min_length=1,
        description="Human-readable or structured description of the evidence",
    )
    recorded_at: str = Field(min_length=1)
    source: str = Field(
        default="hypervisor",
        description="Which participant or system produced this evidence",
    )


# ---------------------------------------------------------------------------
# Failure Report (§8, §9)
# ---------------------------------------------------------------------------

class FailureReport(BaseModel):
    """Complete failure classification report for a Session."""

    session_id: str = Field(min_length=1)
    failure_class: FailureClass
    attribution: FailureAttribution = FailureAttribution.INCONCLUSIVE
    evidence_ids: list[str] = Field(default_factory=list)
    failure_timestamp: str = Field(min_length=1)
    previous_status: str = Field(min_length=1)
    resulting_status: str = Field(min_length=1)
    secondary_causes: list[str] = Field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# Recovery Window Configuration (§20, §25)
# ---------------------------------------------------------------------------

class RecoveryWindowConfig(BaseModel):
    """Per-session recovery timing configuration."""

    # Consumer recovery (§20)
    consumer_reconnect_timeout_seconds: int = Field(default=300, ge=0)
    consumer_acknowledgement_timeout_seconds: int = Field(default=120, ge=0)
    consumer_maximum_provider_hold_seconds: int = Field(default=600, ge=0)

    # Provider recovery (§25)
    provider_reconnect_timeout_seconds: int = Field(default=300, ge=0)
    provider_runtime_restart_timeout_seconds: int = Field(default=180, ge=0)

    # General
    session_maximum_duration_seconds: int = Field(default=3600, ge=0)


# ---------------------------------------------------------------------------
# Session Failure Event (emitted by the handler)
# ---------------------------------------------------------------------------

class SessionFailureEvent(BaseModel):
    """Event emitted when the failure handler transitions a Session."""

    session_id: str = Field(min_length=1)
    event_type: str = Field(
        min_length=1,
        description="e.g. failure_detected, recovery_started, recovery_expires",
    )
    failure_class: FailureClass | None = None
    previous_status: str = Field(min_length=1)
    new_status: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)
    details: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Reputation Event (callback payload)
# ---------------------------------------------------------------------------

class ReputationEvent(BaseModel):
    """Payload emitted when a failure should affect Reputation."""

    session_id: str = Field(min_length=1)
    target_wallet: str = Field(min_length=1)
    failure_class: FailureClass
    attribution: FailureAttribution
    evidence_level: EvidenceLevel
    penalty_hint: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Suggested penalty weight (0.0-1.0)",
    )
    timestamp: str = Field(min_length=1)
