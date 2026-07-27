"""M11-S7: Full pipeline E2E integration tests.

Tests the complete flow across all M11 components:
Rating → Bond → Eligibility → Reward → Epoch Transition → Validation Report
"""

from __future__ import annotations

from aidn_hypervisor.eligibility.engine import EligibilityEngine
from aidn_hypervisor.eligibility.models import EligibilityState
from aidn_hypervisor.epoch_reward.faucet import FaucetEngine
from aidn_hypervisor.epoch_reward.models import (
    EpochTransitionState,
    RecyclingSource,
)
from aidn_hypervisor.epoch_reward.recycling import RecyclingEngine
from aidn_hypervisor.epoch_reward.transition import EpochTransitionEngine
from aidn_hypervisor.rating.engine import RatingEngine
from aidn_hypervisor.rating.models import RatingDimension, RatingEvidence
from aidn_hypervisor.reward.calculator import RewardCalculator
from aidn_hypervisor.reward.mint import MintGenerator
from aidn_hypervisor.reward.models import (
    BASE_EMISSION_Q_ATOMS,
    MintRecipient,
    ServicePool,
)
from aidn_hypervisor.reward.pools import ServicePoolManager
from aidn_hypervisor.validation_bond.manager import ValidationBondManager
from aidn_hypervisor.validation_bond.models import BondStatus
from aidn_hypervisor.validation_report.engine import ValidationReportEngine
from aidn_hypervisor.validation_report.maintenance import (
    MaintenanceValidationEngine,
)
from aidn_hypervisor.validation_report.models import (
    CertificationStatus,
    MaintenanceTriggerType,
    ValidationRecommendation,
)


# ── E2E Scenario 1: Node → Rating → Eligible → Reward ──────────


class TestNodeLifecycle:
    """Node registers → earns rating → becomes eligible → receives reward."""

    def test_full_node_lifecycle(self):
        # 1. Set up rating engine
        rating = RatingEngine()

        # 2. Feed positive evidence
        rating.ingest_raw_evidence(
            RatingEvidence(
                node_id="node-1",
                dimension=RatingDimension.UPTIME,
                evidence_type="heartbeat",
                value=0.95,
                weight=1.0,
                epoch=1,
                timestamp="2026-01-01T00:00:00Z",
                source="heartbeat",
            )
        )
        rating.ingest_raw_evidence(
            RatingEvidence(
                node_id="node-1",
                dimension=RatingDimension.SUCCESS_RATE,
                evidence_type="session_completion",
                value=0.90,
                weight=1.0,
                epoch=1,
                timestamp="2026-01-01T00:00:00Z",
                source="session_completion",
            )
        )

        # 3. Get rating
        profile = rating.get_rating("node-1", current_epoch=1)
        assert profile is not None
        assert profile.composite_score > 0.0

        # 4. Register for eligibility
        elig = EligibilityEngine()
        elig.register_participant(
            "node-1",
            stake=500_000_000,
            activation_epoch=1,
        )
        elig.update_rating("node-1", profile.composite_score)
        elig.set_duty_proof("node-1", True)

        # 5. Evaluate eligibility at epoch 20 (age >= 10)
        result = elig.evaluate_gates("node-1", current_epoch=20)
        assert result.eligible is True
        assert elig.get_state("node-1") == EligibilityState.ACTIVE

        # 6. Calculate reward
        calc = RewardCalculator()
        reward = calc.calculate(
            participant_id="node-1",
            epoch=20,
            service_pool=ServicePool.CONSENSUS,
            work_units=100.0,
            qualifying_epochs=15,
            health_score=0.95,
            has_duty_proof=True,
            reliability_score=profile.composite_score,
        )
        assert reward.effective_weight > 0
        assert reward.maturity_factor > 0.5


# ── E2E Scenario 2: Bond → Validation → Recovery ──────────────


class TestBondValidationLifecycle:
    """Endpoint publishes → locks bond → passes validation → recovers."""

    def test_bond_validation_recovery(self):
        # 1. Lock bond
        bond_mgr = ValidationBondManager()
        bond = bond_mgr.lock_bond(
            endpoint_id="ep-1",
            operator_wallet="0xOP1",
            amount=500_000_000,
            epoch=1,
        )
        assert bond.status == BondStatus.LOCKED

        # 2. Activate by bond_id
        bond_mgr.activate_bond(bond.bond_id, epoch=2)
        bond = bond_mgr.get_bond(bond.bond_id)
        assert bond is not None
        assert bond.status == BondStatus.ACTIVE

        # 3. Create validation report
        vr_engine = ValidationReportEngine()
        report = vr_engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=5,
            recommendation=ValidationRecommendation.CERTIFY,
            evidence=[],
        )
        assert report.certification_status == CertificationStatus.CERTIFIED

        # 4. Maintenance engine tracks validation
        maint = MaintenanceValidationEngine()
        maint.register_endpoint("ep-1", 1)
        maint.update_validation_result("ep-1", 5, True, report.report_id)
        state = maint.get_state("ep-1")
        assert state is not None
        assert state.success_rate == 1.0


# ── E2E Scenario 3: Recycling → Budget ────────────────────────


class TestRecyclingPipeline:
    """Bond forfeited → becomes recyclable → recycled into next epoch budget."""

    def test_forfeit_to_recycling(self):
        # 1. Lock and forfeit bond
        bond_mgr = ValidationBondManager()
        bond = bond_mgr.lock_bond(
            endpoint_id="ep-1",
            operator_wallet="0xOP1",
            amount=500_000_000,
            epoch=1,
        )
        bond_mgr.activate_bond(bond.bond_id, epoch=2)
        bond_mgr.forfeit_bond(bond.bond_id, epoch=3)

        bond = bond_mgr.get_bond(bond.bond_id)
        assert bond is not None
        assert bond.status == BondStatus.FORFEITED

        # 2. Add to recycling
        recycling = RecyclingEngine(max_recycle_lag=5)
        recycling.add_source(
            RecyclingSource.BOND_FORFEIT, 500_000_000, epoch=1
        )
        assert recycling.get_pending_amount(3) == 500_000_000

        # 3. Recycle into epoch budget
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)
        engine.begin_transition(5)
        budget = engine.calculate_budget(5)
        assert budget is not None
        assert budget.total_budget > BASE_EMISSION_Q_ATOMS


# ── E2E Scenario 4: KCG → Concentration Cap ───────────────────


class TestKCGConcentration:
    """Known Control Group detected → concentration cap applied."""

    def test_kcg_concentration_flow(self):
        # 1. Register services with same beneficiary
        elig = EligibilityEngine()
        elig.register_participant(
            "s1",
            stake=500_000_000,
            activation_epoch=1,
            reward_beneficiary="0xW1",
        )
        elig.register_participant(
            "s2",
            stake=500_000_000,
            activation_epoch=1,
            reward_beneficiary="0xW1",
        )

        # 2. KCG should be detected
        group = elig.kcg_manager.get_group_for_wallet("0xW1")
        assert group is not None
        assert group.member_count == 2

        # 3. Both services should be in the same group
        assert elig.kcg_manager.get_service_group_id("s1") == group.group_id
        assert elig.kcg_manager.get_service_group_id("s2") == group.group_id


# ── E2E Scenario 5: Epoch Transition Pipeline ─────────────────


class TestEpochTransitionPipeline:
    """Epoch transition → evidence freeze → reward calc → mint → complete."""

    def test_full_epoch_transition(self):
        recycling = RecyclingEngine()
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)

        # 1. Begin transition
        record = engine.begin_transition(1)
        assert record.state == EpochTransitionState.IN_PROGRESS

        # 2. Freeze evidence
        record = engine.freeze_evidence(1)
        assert record is not None
        assert record.state == EpochTransitionState.EVIDENCE_FROZEN

        # 3. Calculate budget
        budget = engine.calculate_budget(1)
        assert budget is not None
        assert budget.consensus_pool > 0

        # 4. Distribute rewards
        calc = RewardCalculator()
        r = calc.calculate(
            participant_id="s1",
            epoch=1,
            service_pool=ServicePool.CONSENSUS,
            work_units=100.0,
            qualifying_epochs=10,
            health_score=0.95,
            has_duty_proof=True,
            reliability_score=0.90,
        )
        pools.add_participant(ServicePool.CONSENSUS, r)
        results = pools.distribute_pool(
            ServicePool.CONSENSUS, budget.consensus_pool
        )
        assert len(results) == 1
        assert results[0].final_reward > 0

        # 5. Generate mint
        mint_gen = MintGenerator()
        recipients = mint_gen.build_recipients(
            results, wallet_map={"s1": "0xW1"}
        )
        mint = mint_gen.generate(
            epoch=1,
            base_emission=BASE_EMISSION_Q_ATOMS,
            recyclable_amount=0,
            recipients=recipients,
        )

        # 6. Record emission
        emission = engine.record_emission(
            epoch=1,
            consensus_allocated=results[0].final_reward,
            registry_allocated=0,
            validation_allocated=0,
            faucet_allocated=0,
            total_minted=mint.total_minted,
        )
        assert emission is not None

        # 7. Complete
        record = engine.complete_transition(1)
        assert record is not None
        assert record.state == EpochTransitionState.COMPLETE


# ── E2E Scenario 6: Maturity → Reward Growth ──────────────────


class TestMaturityGrowth:
    """Maturity advances → quality factor improves → reward increases."""

    def test_reward_grows_with_maturity(self):
        calc = RewardCalculator()

        # Epoch 1: low maturity
        r1 = calc.calculate(
            participant_id="s1",
            epoch=1,
            service_pool=ServicePool.CONSENSUS,
            work_units=100.0,
            qualifying_epochs=1,
            health_score=1.0,
            has_duty_proof=True,
            reliability_score=1.0,
        )

        # Epoch 20: high maturity
        r2 = calc.calculate(
            participant_id="s1",
            epoch=20,
            service_pool=ServicePool.CONSENSUS,
            work_units=100.0,
            qualifying_epochs=20,
            health_score=1.0,
            has_duty_proof=True,
            reliability_score=1.0,
        )

        assert r2.effective_weight > r1.effective_weight
        assert r2.maturity_factor > r1.maturity_factor


# ── E2E Scenario 7: Health Drop → Reward Reduction ────────────


class TestHealthPenalty:
    """Downtime detected → health factor decreases → reward reduced."""

    def test_health_reduces_reward(self):
        calc = RewardCalculator()

        # Healthy
        r1 = calc.calculate(
            participant_id="s1",
            epoch=10,
            service_pool=ServicePool.CONSENSUS,
            work_units=100.0,
            qualifying_epochs=10,
            health_score=1.0,
            has_duty_proof=True,
            reliability_score=1.0,
        )

        # Unhealthy
        r2 = calc.calculate(
            participant_id="s1",
            epoch=10,
            service_pool=ServicePool.CONSENSUS,
            work_units=100.0,
            qualifying_epochs=10,
            health_score=0.50,
            has_duty_proof=True,
            reliability_score=1.0,
        )

        assert r2.effective_weight < r1.effective_weight
        assert r2.health_factor == 0.50


# ── E2E Scenario 8: Faucet Anti-Sybil ─────────────────────────


class TestFaucetAntiSybil:
    """Faucet allocation with cooldown and KCG limits."""

    def test_faucet_cooldown_enforced(self):
        engine = FaucetEngine(per_wallet_limit=100_000_000, cooldown_epochs=1)

        # Epoch 1: claim
        r1 = engine.allocate(
            epoch=1,
            budget=500_000_000,
            requests=[("0xW1", None)],
        )
        assert len(r1.allocations) == 1

        # Epoch 2: cooldown
        r2 = engine.allocate(
            epoch=2,
            budget=500_000_000,
            requests=[("0xW1", None)],
        )
        assert len(r2.allocations) == 0

        # Epoch 3: cooldown expired
        r3 = engine.allocate(
            epoch=3,
            budget=500_000_000,
            requests=[("0xW1", None)],
        )
        assert len(r3.allocations) == 1
