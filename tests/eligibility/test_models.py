"""M11-S3: Eligibility models — unit tests."""

from __future__ import annotations


from aidn_hypervisor.eligibility.models import (
    ACTIVATION_AGE_EPOCHS,
    MIN_GROUP_SHARE_CAP,
    MIN_SERVICE_HEALTH,
    EligibilityGateResult,
    EligibilitySnapshot,
    EligibilityState,
    GateCheck,
    IneligibilityReason,
    KnownControlGroup,
)


# ── Constants ─────────────────────────────────────────────────────

class TestConstants:
    def test_activation_age(self):
        assert ACTIVATION_AGE_EPOCHS == 10

    def test_min_health(self):
        assert MIN_SERVICE_HEALTH == 0.70

    def test_min_group_share_cap(self):
        assert MIN_GROUP_SHARE_CAP == 0.20


# ── Enums ─────────────────────────────────────────────────────────

class TestEligibilityState:
    def test_all_states(self):
        states = [
            EligibilityState.PENDING,
            EligibilityState.ACTIVE,
            EligibilityState.INELIGIBLE,
            EligibilityState.SUSPENDED,
            EligibilityState.RETIRED,
        ]
        assert len(states) == 5

    def test_from_string(self):
        assert EligibilityState("active") == EligibilityState.ACTIVE


class TestIneligibilityReason:
    def test_all_reasons(self):
        reasons = [
            IneligibilityReason.INSUFFICIENT_STAKE,
            IneligibilityReason.HEALTH_BELOW_THRESHOLD,
            IneligibilityReason.ACTIVATION_AGE_NOT_MET,
            IneligibilityReason.SUSPENDED,
            IneligibilityReason.DUTY_PROOF_MISSING,
            IneligibilityReason.PROTOCOL_VERSION_MISMATCH,
            IneligibilityReason.BOND_FORFEITED,
        ]
        assert len(reasons) == 7


# ── GateCheck ────────────────────────────────────────────────────

class TestGateCheck:
    def test_passed(self):
        check = GateCheck(gate_name="test", passed=True, detail="ok")
        assert check.passed is True

    def test_failed(self):
        check = GateCheck(gate_name="test", passed=False, detail="bad")
        assert check.passed is False

    def test_default_detail(self):
        check = GateCheck(gate_name="test", passed=True)
        assert check.detail == ""


# ── EligibilityGateResult ───────────────────────────────────────

class TestEligibilityGateResult:
    def test_eligible(self):
        result = EligibilityGateResult(
            service_id="s1",
            epoch=5,
            eligible=True,
            checks=[GateCheck(gate_name="g1", passed=True)],
        )
        assert result.eligible is True
        assert result.passed_count == 1
        assert result.failed_count == 0

    def test_ineligible(self):
        checks = [
            GateCheck(gate_name="g1", passed=True),
            GateCheck(gate_name="g2", passed=False),
        ]
        result = EligibilityGateResult(
            service_id="s1",
            epoch=5,
            eligible=False,
            checks=checks,
        )
        assert result.passed_count == 1
        assert result.failed_count == 1

    def test_with_reasons(self):
        result = EligibilityGateResult(
            service_id="s1",
            epoch=5,
            eligible=False,
            checks=[],
            ineligibility_reasons=[IneligibilityReason.INSUFFICIENT_STAKE],
        )
        assert len(result.ineligibility_reasons) == 1


# ── KnownControlGroup ───────────────────────────────────────────

class TestKnownControlGroup:
    def test_create(self):
        group = KnownControlGroup(
            group_id="kcg-1",
            reward_beneficiary="0xW1",
            member_service_ids=["s1", "s2"],
            total_stake=1_000_000_000,
            detected_at_epoch=1,
            last_updated_epoch=5,
        )
        assert group.member_count == 2
        assert group.group_id == "kcg-1"

    def test_exceeds_concentration_cap_low(self):
        group = KnownControlGroup(
            group_id="kcg-1",
            reward_beneficiary="0xW1",
            concentration_percentage=10.0,
            detected_at_epoch=1,
            last_updated_epoch=1,
        )
        # 10% < 80% cap → not exceeded
        assert group.exceeds_concentration_cap is False

    def test_exceeds_concentration_cap_high(self):
        group = KnownControlGroup(
            group_id="kcg-1",
            reward_beneficiary="0xW1",
            concentration_percentage=90.0,
            detected_at_epoch=1,
            last_updated_epoch=1,
        )
        # 90% > 80% cap → exceeded
        assert group.exceeds_concentration_cap is True

    def test_empty_members(self):
        group = KnownControlGroup(
            group_id="kcg-1",
            reward_beneficiary="0xW1",
            detected_at_epoch=1,
            last_updated_epoch=1,
        )
        assert group.member_count == 0


# ── EligibilitySnapshot ─────────────────────────────────────────

class TestEligibilitySnapshot:
    def test_create(self):
        snap = EligibilitySnapshot(
            epoch=10,
            service_id="s1",
            state=EligibilityState.ACTIVE,
            rating_score=0.85,
            health_score=0.90,
            kcg_id="kcg-1",
            activation_age=10,
            has_duty_proof=True,
        )
        assert snap.epoch == 10
        assert snap.state == EligibilityState.ACTIVE

    def test_no_kcg(self):
        snap = EligibilitySnapshot(
            epoch=5,
            service_id="s2",
            state=EligibilityState.PENDING,
            rating_score=0.5,
            health_score=1.0,
            kcg_id=None,
            activation_age=3,
            has_duty_proof=False,
        )
        assert snap.kcg_id is None
