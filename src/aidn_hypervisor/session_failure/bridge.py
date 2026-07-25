"""Failure → Reputation bridge (RFC-0041 integration).

When a FailureReport reaches a conclusive attribution,
the bridge emits a ReputationEvent into the ReputationEngine.
"""

from __future__ import annotations

from aidn_hypervisor.reputation_engine.engine import ReputationEngine
from aidn_hypervisor.reputation_engine.models import ReputationEvent
from aidn_hypervisor.session_failure.models import (
    FailureReport,
    FailureEvidenceRecord,
    FailureClass,
    FailureAttribution,
    EvidenceLevel,
)

# ── FailureClass → Dimension mapping ──

_FAILURE_TO_DIMENSION: dict[str, str] = {
    # Availability failures
    "CONSUMER_DISCONNECTED": "AVAILABILITY",
    "PROVIDER_DISCONNECTED": "AVAILABILITY",
    "UPSTREAM_PROXY_FAILURE": "AVAILABILITY",
    "SESSION_TIMEOUT": "AVAILABILITY",
    "IDLE_TIMEOUT": "AVAILABILITY",
    # Protocol failures
    "PROTOCOL_INCOMPATIBILITY": "PROTOCOL_COMPLIANCE",
    "CONSUMER_FORCE_CLOSE": "PROTOCOL_COMPLIANCE",
    "PROVIDER_FORCE_CLOSE": "PROTOCOL_COMPLIANCE",
    # Accounting failures
    "ACCOUNTING_MISMATCH": "ACCOUNTING_CONSISTENCY",
    "DEPOSIT_EXHAUSTED": "ACCOUNTING_CONSISTENCY",
    # Runtime/endpoint failures
    "RUNTIME_FAILURE": "RELIABILITY",
    "ENDPOINT_FAILURE": "RELIABILITY",
    # Recovery failures
    "STATE_RECOVERY_FAILURE": "RECOVERY_RELIABILITY",
    # Consensus
    "CONSENSUS_INTERRUPTION": "PROTOCOL_COMPLIANCE",
    # Timeout-related
    "USAGE_REPORT_TIMEOUT": "RELIABILITY",
    "ACKNOWLEDGEMENT_TIMEOUT": "RELIABILITY",
    # Unknown → reliability
    "UNKNOWN_FAILURE": "RELIABILITY",
}

# ── FailureClass → Severity mapping ──

_FAILURE_TO_SEVERITY: dict[str, str] = {
    "CONSUMER_DISCONNECTED": "MINOR",
    "PROVIDER_DISCONNECTED": "MINOR",
    "RUNTIME_FAILURE": "MAJOR",
    "ENDPOINT_FAILURE": "MAJOR",
    "UPSTREAM_PROXY_FAILURE": "MODERATE",
    "ACCOUNTING_MISMATCH": "CRITICAL",
    "USAGE_REPORT_TIMEOUT": "MODERATE",
    "ACKNOWLEDGEMENT_TIMEOUT": "MODERATE",
    "DEPOSIT_EXHAUSTED": "MODERATE",
    "SESSION_TIMEOUT": "MINOR",
    "IDLE_TIMEOUT": "INFORMATIONAL",
    "CONSUMER_FORCE_CLOSE": "INFORMATIONAL",
    "PROVIDER_FORCE_CLOSE": "INFORMATIONAL",
    "PROTOCOL_INCOMPATIBILITY": "MODERATE",
    "CONSENSUS_INTERRUPTION": "MAJOR",
    "STATE_RECOVERY_FAILURE": "MAJOR",
    "UNKNOWN_FAILURE": "MINOR",
}

# ── EvidenceLevel → Confidence mapping ──

_EVIDENCE_TO_CONFIDENCE: dict[str, str] = {
    "CRYPTOGRAPHIC": "CRYPTOGRAPHIC",
    "REPRODUCIBLE": "REPRODUCIBLE",
    "OBSERVATIONAL": "OBSERVATIONAL",
}

# Attribution → Direction
# Only conclusive attributions produce negative events
_PUNISHABLE_ATTRIBUTIONS = {
    FailureAttribution.CONSUMER_AT_FAULT,
    FailureAttribution.PROVIDER_AT_FAULT,
    FailureAttribution.BOTH_AT_FAULT,
}


class FailureReputationBridge:
    """Translates FailureReports into ReputationEvents.

    Rules:
    - Only conclusive attributions (CONSUMER_AT_FAULT, PROVIDER_AT_FAULT, BOTH_AT_FAULT)
      trigger reputation events
    - External/protocol/inconclusive failures excluded
    - Evidence level maps to confidence class
    - Failure class maps to dimension + severity
    """

    def __init__(self, engine: ReputationEngine) -> None:
        self.engine = engine

    def on_failure_concluded(
        self,
        report: FailureReport,
        evidence: FailureEvidenceRecord | None = None,
        *,
        consumer_wallet: str | None = None,
        provider_wallet: str | None = None,
    ) -> list[ReputationEvent]:
        """Handle a concluded failure report.

        Args:
            report: The concluded FailureReport.
            evidence: Optional evidence record for confidence level.
            consumer_wallet: Consumer wallet address (for attribution mapping).
            provider_wallet: Provider wallet address (for attribution mapping).

        Returns:
            List of emitted ReputationEvents (may be empty).
        """
        # Skip non-punishable attributions
        if report.attribution not in _PUNISHABLE_ATTRIBUTIONS:
            return []

        events: list[ReputationEvent] = []

        # Determine which wallets to penalize
        wallets_to_penalize: list[str] = []
        if report.attribution == FailureAttribution.CONSUMER_AT_FAULT:
            if consumer_wallet:
                wallets_to_penalize.append(consumer_wallet)
        elif report.attribution == FailureAttribution.PROVIDER_AT_FAULT:
            if provider_wallet:
                wallets_to_penalize.append(provider_wallet)
        elif report.attribution == FailureAttribution.BOTH_AT_FAULT:
            if consumer_wallet:
                wallets_to_penalize.append(consumer_wallet)
            if provider_wallet:
                wallets_to_penalize.append(provider_wallet)

        if not wallets_to_penalize:
            return []

        # Determine evidence confidence
        confidence = self._resolve_confidence(evidence)

        # Build and ingest event for each penalized wallet
        for wallet in wallets_to_penalize:
            event = self._build_event(
                wallet=wallet,
                report=report,
                confidence=confidence,
            )
            self.engine.ingest_event(event)
            events.append(event)

        return events

    def on_recovery_succeeded(
        self,
        report: FailureReport,
        evidence: FailureEvidenceRecord | None = None,
        *,
        consumer_wallet: str | None = None,
        provider_wallet: str | None = None,
    ) -> list[ReputationEvent]:
        """Handle a successful recovery — emits a positive signal.

        Recovery reliability dimension gets a positive nudge for
        whoever was originally at fault (shows they recovered).
        """
        events: list[ReputationEvent] = []

        if report.attribution not in _PUNISHABLE_ATTRIBUTIONS:
            return events

        wallets: list[str] = []
        if report.attribution == FailureAttribution.CONSUMER_AT_FAULT:
            if consumer_wallet:
                wallets.append(consumer_wallet)
        elif report.attribution == FailureAttribution.PROVIDER_AT_FAULT:
            if provider_wallet:
                wallets.append(provider_wallet)
        elif report.attribution == FailureAttribution.BOTH_AT_FAULT:
            if consumer_wallet:
                wallets.append(consumer_wallet)
            if provider_wallet:
                wallets.append(provider_wallet)

        for wallet in wallets:
            event = ReputationEvent(
                subject_type="HYPERVISOR",
                subject_id=wallet,
                profile_dimension="RECOVERY_RELIABILITY",
                event_class="RECOVERY_EVENT",
                direction="POSITIVE",
                severity="MINOR",
                evidence_confidence="OBSERVATIONAL",
                source_type="session_failure",
                source_reference=report.session_id,
            )
            self.engine.ingest_event(event)
            events.append(event)

        return events

    def _build_event(
        self,
        wallet: str,
        report: FailureReport,
        confidence: str,
    ) -> ReputationEvent:
        """Build a ReputationEvent from a FailureReport."""
        fc = report.failure_class.value
        dimension = _FAILURE_TO_DIMENSION.get(fc, "AVAILABILITY")
        severity = _FAILURE_TO_SEVERITY.get(fc, "MODERATE")

        return ReputationEvent(
            subject_type="HYPERVISOR",
            subject_id=wallet,
            profile_dimension=dimension,
            event_class="PROTOCOL_EVENT",
            direction="NEGATIVE",
            severity=severity,
            evidence_confidence=confidence,
            source_type="session_failure",
            source_reference=report.session_id,
        )

    @staticmethod
    def _resolve_confidence(evidence: FailureEvidenceRecord | None) -> str:
        """Resolve evidence confidence class from evidence record."""
        if evidence is None:
            return "OBSERVATIONAL"

        el = evidence.evidence_level.value
        return _EVIDENCE_TO_CONFIDENCE.get(el, "OBSERVATIONAL")
