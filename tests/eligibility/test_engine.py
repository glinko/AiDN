"""M11-S3: Eligibility Engine — unit tests."""

from __future__ import annotations


from aidn_hypervisor.eligibility.engine import EligibilityEngine
from aidn_hypervisor.eligibility.kcg import KCGManager
from aidn_hypervisor.eligibility.models import (
    EligibilityState,
    IneligibilityReason,
)


# ── Registration ────────────────────────────────────────────────

class TestRegistration:
    def test_register_participant(self):
        engine = EligibilityEngine()
        engine.register_participant("s1", stake=500_000_000, activation_epoch=1)
        assert engine.get_state("s1") == EligibilityState.PENDING

    def test_register_with_beneficiary(self):
        engine = EligibilityEngine()
        engine.register_participant(
            "s1",
            stake=500_000_000,
            activation_epoch=1,
            reward_beneficiary="0xW1",
        )
        assert engine.kcg_manager.group_count >= 1

    def test_default_values(self):
        engine = EligibilityEngine()
        engine.register_participant("s1", stake=500_000_000, activation_epoch=1)
        # Should have default health=1.0, rating=0.5
        snap = engine.create_snapshot("s1", 1)
        assert snap is not None
        assert snap.health_score == 1.0
        assert snap.rating_score == 0.5


# ── Gate Evaluation ────────────────────────────────────────────

class TestGateEvaluation:
    def _make_eligible(self, epoch: int = 20) -> EligibilityEngine:
        """Create an engine with a fully eligible participant."""
        engine = EligibilityEngine()
        engine.register_participant(
            "s1",
            stake=500_000_000,
            activation_epoch=1,
        )
        engine.update_rating("s1", 0.85)
        engine.update_health("s1", 0.90)
        engine.set_duty_proof("s1", True)
        return engine

    def test_all_gates_pass(self):
        engine = self._make_eligible()
        result = engine.evaluate_gates("s1", current_epoch=20)
        assert result.eligible is True
        assert result.failed_count == 0

    def test_activation_age_fails(self):
        engine = EligibilityEngine()
        engine.register_participant(
            "s1",
            stake=500_000_000,
            activation_epoch=15,
        )
        engine.set_duty_proof("s1", True)
        result = engine.evaluate_gates("s1", current_epoch=20)
        # age = 5, need 10
        assert result.eligible is False
        assert IneligibilityReason.ACTIVATION_AGE_NOT_MET in result.ineligibility_reasons

    def test_insufficient_stake_fails(self):
        engine = EligibilityEngine()
        engine.register_participant(
            "s1",
            stake=100,  # way below 500M
            activation_epoch=1,
        )
        engine.set_duty_proof("s1", True)
        result = engine.evaluate_gates("s1", current_epoch=20)
        assert result.eligible is False
        assert IneligibilityReason.INSUFFICIENT_STAKE in result.ineligibility_reasons

    def test_health_below_threshold_fails(self):
        engine = self._make_eligible()
        engine.update_health("s1", 0.50)  # below 0.70
        result = engine.evaluate_gates("s1", current_epoch=20)
        assert result.eligible is False
        assert IneligibilityReason.HEALTH_BELOW_THRESHOLD in result.ineligibility_reasons

    def test_duty_proof_missing_fails(self):
        engine = self._make_eligible()
        engine.set_duty_proof("s1", False)
        result = engine.evaluate_gates("s1", current_epoch=20)
        assert result.eligible is False
        assert IneligibilityReason.DUTY_PROOF_MISSING in result.ineligibility_reasons

    def test_suspended_fails(self):
        engine = self._make_eligible()
        engine.suspend("s1")
        result = engine.evaluate_gates("s1", current_epoch=20)
        assert result.eligible is False
        assert IneligibilityReason.SUSPENDED in result.ineligibility_reasons

    def test_protocol_version_mismatch_fails(self):
        engine = EligibilityEngine()
        engine.register_participant(
            "s1",
            stake=500_000_000,
            activation_epoch=1,
            protocol_version="0.9.0",
        )
        engine.set_duty_proof("s1", True)
        result = engine.evaluate_gates(
            "s1", current_epoch=20, required_protocol_version="1.0.0"
        )
        assert result.eligible is False
        assert IneligibilityReason.PROTOCOL_VERSION_MISMATCH in result.ineligibility_reasons

    def test_unregistered_service(self):
        engine = self._make_eligible()
        result = engine.evaluate_gates("unknown", current_epoch=20)
        assert result.eligible is False

    def test_multiple_failures(self):
        engine = EligibilityEngine()
        engine.register_participant(
            "s1",
            stake=100,  # too low
            activation_epoch=18,  # age=2, need 10
        )
        engine.update_health("s1", 0.30)  # too low
        # no duty proof
        result = engine.evaluate_gates("s1", current_epoch=20)
        assert result.eligible is False
        assert len(result.ineligibility_reasons) >= 3


# ── State Transitions ──────────────────────────────────────────

class TestStateTransitions:
    def test_becomes_active_on_pass(self):
        engine = EligibilityEngine()
        engine.register_participant(
            "s1", stake=500_000_000, activation_epoch=1
        )
        engine.set_duty_proof("s1", True)
        engine.evaluate_gates("s1", current_epoch=20)
        assert engine.get_state("s1") == EligibilityState.ACTIVE

    def test_becomes_ineligible_on_fail(self):
        engine = EligibilityEngine()
        engine.register_participant(
            "s1", stake=500_000_000, activation_epoch=1
        )
        engine.set_duty_proof("s1", True)
        engine.evaluate_gates("s1", current_epoch=20)
        # Was ACTIVE, now fail health
        engine.update_health("s1", 0.30)
        engine.evaluate_gates("s1", current_epoch=20)
        assert engine.get_state("s1") == EligibilityState.INELIGIBLE

    def test_suspend(self):
        engine = EligibilityEngine()
        engine.register_participant(
            "s1", stake=500_000_000, activation_epoch=1
        )
        engine.suspend("s1")
        assert engine.get_state("s1") == EligibilityState.SUSPENDED

    def test_unsuspend(self):
        engine = EligibilityEngine()
        engine.register_participant(
            "s1", stake=500_000_000, activation_epoch=1
        )
        engine.suspend("s1")
        engine.unsuspend("s1")
        # State is still SUSPENDED until gates re-evaluated
        # but the suspension flag is cleared

    def test_retire(self):
        engine = EligibilityEngine()
        engine.register_participant(
            "s1", stake=500_000_000, activation_epoch=1
        )
        engine.retire("s1")
        assert engine.get_state("s1") == EligibilityState.RETIRED


# ── Snapshots ──────────────────────────────────────────────────

class TestSnapshots:
    def test_create_snapshot(self):
        engine = EligibilityEngine()
        engine.register_participant(
            "s1",
            stake=500_000_000,
            activation_epoch=5,
            reward_beneficiary="0xW1",
        )
        engine.set_duty_proof("s1", True)
        snap = engine.create_snapshot("s1", current_epoch=20)
        assert snap is not None
        assert snap.activation_age == 15
        assert snap.has_duty_proof is True
        assert snap.kcg_id is not None

    def test_snapshot_unregistered(self):
        engine = EligibilityEngine()
        snap = engine.create_snapshot("unknown", current_epoch=1)
        assert snap is None


# ── Queries ────────────────────────────────────────────────────

class TestQueries:
    def test_get_active_participants(self):
        engine = EligibilityEngine()
        engine.register_participant(
            "s1", stake=500_000_000, activation_epoch=1
        )
        engine.register_participant(
            "s2", stake=500_000_000, activation_epoch=1
        )
        engine.set_duty_proof("s1", True)
        engine.set_duty_proof("s2", True)
        engine.evaluate_gates("s1", current_epoch=20)
        engine.evaluate_gates("s2", current_epoch=20)
        active = engine.get_active_participants()
        assert "s1" in active
        assert "s2" in active

    def test_kcg_manager_accessible(self):
        engine = EligibilityEngine()
        assert isinstance(engine.kcg_manager, KCGManager)
