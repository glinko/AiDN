"""Tests for Failure→Reputation bridge (RFC-0041 integration).

When session_failure produces a conclusive attribution,
the bridge should emit a ReputationEvent into the engine.
"""


from aidn_hypervisor.reputation_engine.engine import ReputationEngine
from aidn_hypervisor.reputation_engine.models import (
    ReputationEvent as RepEngineEvent,
)
from aidn_hypervisor.reputation_engine.store import ReputationStore
from aidn_hypervisor.session_failure.models import (
    EvidenceLevel,
    FailureAttribution,
    FailureClass,
    FailureEvidenceRecord,
    FailureReport,
)


class TestFailureToReputationBridge:
    """Bridge maps session_failure outcomes to ReputationEvents."""

    def setup_method(self):
        self.store = ReputationStore()
        self.engine = ReputationEngine(self.store)
        from aidn_hypervisor.session_failure.bridge import FailureReputationBridge
        self.bridge = FailureReputationBridge(self.engine)

    def _report(
        self,
        *,
        session_id: str = "sess-1",
        failure_class: FailureClass = FailureClass.CONSUMER_DISCONNECTED,
        attribution: FailureAttribution = FailureAttribution.CONSUMER_AT_FAULT,
        evidence_level: EvidenceLevel = EvidenceLevel.CRYPTOGRAPHIC,
        consumer_wallet: str = "wallet-consumer",
        provider_wallet: str = "wallet-provider",
    ) -> FailureReport:
        return FailureReport(
            session_id=session_id,
            failure_class=failure_class,
            attribution=attribution,
            evidence_ids=["ev-1"],
            failure_timestamp="2026-07-25T10:00:00Z",
            previous_status="active",
            resulting_status="recovering",
            notes="test report",
        )

    def _evidence(
        self,
        *,
        session_id: str = "sess-1",
        evidence_level: EvidenceLevel = EvidenceLevel.CRYPTOGRAPHIC,
    ) -> FailureEvidenceRecord:
        return FailureEvidenceRecord(
            session_id=session_id,
            evidence_level=evidence_level,
            category="transport_timeout",
            detail="consumer disconnected",
            recorded_at="2026-07-25T10:00:00Z",
            source="hypervisor",
        )

    # ── Conclusive attributions trigger events ──

    def test_consumer_at_fault_emits_negative_event(self):
        report = self._report(attribution=FailureAttribution.CONSUMER_AT_FAULT)
        evidence = self._evidence(evidence_level=EvidenceLevel.CRYPTOGRAPHIC)
        events = self.bridge.on_failure_concluded(
            report, evidence,
            consumer_wallet="wallet-consumer",
        )
        assert len(events) == 1
        assert events[0].direction == "NEGATIVE"
        assert events[0].subject_id == "wallet-consumer"

    def test_provider_at_fault_emits_negative_event(self):
        report = self._report(attribution=FailureAttribution.PROVIDER_AT_FAULT)
        evidence = self._evidence(evidence_level=EvidenceLevel.CRYPTOGRAPHIC)
        events = self.bridge.on_failure_concluded(
            report, evidence,
            provider_wallet="wallet-provider",
        )
        assert len(events) == 1
        assert events[0].direction == "NEGATIVE"
        assert events[0].subject_id == "wallet-provider"

    def test_inconclusive_emits_no_event(self):
        report = self._report(attribution=FailureAttribution.INCONCLUSIVE)
        evidence = self._evidence(evidence_level=EvidenceLevel.OBSERVATIONAL)
        events = self.bridge.on_failure_concluded(report, evidence)
        assert len(events) == 0

    def test_external_failure_emits_no_event(self):
        report = self._report(attribution=FailureAttribution.EXTERNAL_FAILURE)
        evidence = self._evidence(evidence_level=EvidenceLevel.CRYPTOGRAPHIC)
        events = self.bridge.on_failure_concluded(report, evidence)
        assert len(events) == 0

    def test_protocol_failure_emits_no_event(self):
        report = self._report(attribution=FailureAttribution.PROTOCOL_FAILURE)
        evidence = self._evidence(evidence_level=EvidenceLevel.CRYPTOGRAPHIC)
        events = self.bridge.on_failure_concluded(report, evidence)
        assert len(events) == 0

    # ── Dimension mapping ──

    def test_disconnect_failure_maps_to_availability(self):
        report = self._report(
            failure_class=FailureClass.CONSUMER_DISCONNECTED,
            attribution=FailureAttribution.CONSUMER_AT_FAULT,
        )
        evidence = self._evidence()
        events = self.bridge.on_failure_concluded(
            report, evidence, consumer_wallet="wallet-consumer",
        )
        assert events[0].profile_dimension == "AVAILABILITY"

    def test_accounting_mismatch_maps_to_accounting(self):
        report = self._report(
            failure_class=FailureClass.ACCOUNTING_MISMATCH,
            attribution=FailureAttribution.CONSUMER_AT_FAULT,
        )
        evidence = self._evidence()
        events = self.bridge.on_failure_concluded(
            report, evidence, consumer_wallet="wallet-consumer",
        )
        assert events[0].profile_dimension == "ACCOUNTING_CONSISTENCY"

    def test_state_recovery_failure_maps_to_recovery(self):
        report = self._report(
            failure_class=FailureClass.STATE_RECOVERY_FAILURE,
            attribution=FailureAttribution.CONSUMER_AT_FAULT,
        )
        evidence = self._evidence()
        events = self.bridge.on_failure_concluded(
            report, evidence, consumer_wallet="wallet-consumer",
        )
        assert events[0].profile_dimension == "RECOVERY_RELIABILITY"

    def test_protocol_incompatibility_maps_to_protocol(self):
        report = self._report(
            failure_class=FailureClass.PROTOCOL_INCOMPATIBILITY,
            attribution=FailureAttribution.CONSUMER_AT_FAULT,
        )
        evidence = self._evidence()
        events = self.bridge.on_failure_concluded(
            report, evidence, consumer_wallet="wallet-consumer",
        )
        assert events[0].profile_dimension == "PROTOCOL_COMPLIANCE"

    # ── Evidence confidence mapping ──

    def test_cryptographic_evidence_yields_high_confidence(self):
        report = self._report(attribution=FailureAttribution.CONSUMER_AT_FAULT)
        evidence = self._evidence(evidence_level=EvidenceLevel.CRYPTOGRAPHIC)
        events = self.bridge.on_failure_concluded(
            report, evidence, consumer_wallet="wallet-consumer",
        )
        assert events[0].evidence_confidence in {
            "FINALIZED_PROTOCOL",
            "CRYPTOGRAPHIC",
            "REPRODUCIBLE",
        }

    def test_observational_evidence_yields_lower_confidence(self):
        report = self._report(attribution=FailureAttribution.CONSUMER_AT_FAULT)
        evidence = self._evidence(evidence_level=EvidenceLevel.OBSERVATIONAL)
        events = self.bridge.on_failure_concluded(
            report, evidence, consumer_wallet="wallet-consumer",
        )
        assert events[0].evidence_confidence in {
            "STATISTICAL",
            "OBSERVATIONAL",
            "SUBJECTIVE",
        }

    # ── Integration: events actually affect score ──

    def test_failure_decreases_availability_score(self):
        # Create profile with positive history
        self.engine.get_or_create_profile("HYPERVISOR", "wallet-consumer")

        for _ in range(20):
            self.engine.ingest_event(RepEngineEvent(
                subject_type="HYPERVISOR",
                subject_id="wallet-consumer",
                profile_dimension="AVAILABILITY",
                event_class="AVAILABILITY_EVENT",
                direction="POSITIVE",
                severity="MODERATE",
                evidence_confidence="MULTI_SOURCE",
            ))

        profile_before = self.engine.get_profile("HYPERVISOR", "wallet-consumer")
        score_before = profile_before.accumulators["AVAILABILITY"].effective_score

        # Now a failure
        report = self._report(attribution=FailureAttribution.CONSUMER_AT_FAULT)
        evidence = self._evidence()
        self.bridge.on_failure_concluded(
            report, evidence, consumer_wallet="wallet-consumer",
        )

        profile_after = self.engine.get_profile("HYPERVISOR", "wallet-consumer")
        score_after = profile_after.accumulators["AVAILABILITY"].effective_score

        assert score_after < score_before

    def test_recovery_succeeds_emits_positive_signal(self):
        self.engine.get_or_create_profile("HYPERVISOR", "wallet-consumer")

        report = self._report(attribution=FailureAttribution.CONSUMER_AT_FAULT)
        evidence = self._evidence()
        events = self.bridge.on_recovery_succeeded(
            report, evidence, consumer_wallet="wallet-consumer",
        )

        assert len(events) == 1
        assert events[0].direction == "POSITIVE"
        assert events[0].profile_dimension == "RECOVERY_RELIABILITY"

    def test_both_at_fault_penalizes_both(self):
        report = self._report(attribution=FailureAttribution.BOTH_AT_FAULT)
        evidence = self._evidence()
        events = self.bridge.on_failure_concluded(
            report, evidence,
            consumer_wallet="wallet-consumer",
            provider_wallet="wallet-provider",
        )
        assert len(events) == 2
        assert all(e.direction == "NEGATIVE" for e in events)
        wallets = {e.subject_id for e in events}
        assert "wallet-consumer" in wallets
        assert "wallet-provider" in wallets
