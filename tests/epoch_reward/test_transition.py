"""M11-S5: Epoch Transition Engine — unit tests."""

from __future__ import annotations

from aidn_hypervisor.epoch_reward.models import (
    EpochTransitionState,
    RecyclingSource,
)
from aidn_hypervisor.epoch_reward.recycling import RecyclingEngine
from aidn_hypervisor.epoch_reward.transition import EpochTransitionEngine
from aidn_hypervisor.registry.duty import FIXED_POINT_SCALE, RegistryRewardInput
from aidn_hypervisor.reward.pools import ServicePoolManager


def _registry_reward_input() -> RegistryRewardInput:
    return RegistryRewardInput(
        service_id="registry-1",
        epoch=1,
        reward_beneficiary="wallet:registry-1",
        known_control_group_id="kcg-1",
        work_units_millionths=100,
        maturity_factor_millionths=FIXED_POINT_SCALE,
        health_factor_millionths=FIXED_POINT_SCALE,
        proof_success_millionths=FIXED_POINT_SCALE,
        completeness_millionths=FIXED_POINT_SCALE,
        availability_millionths=FIXED_POINT_SCALE,
        latency_factor_millionths=FIXED_POINT_SCALE,
        reliability_factor_millionths=FIXED_POINT_SCALE,
        raw_weight_millionths=100,
        evidence_id="evidence:1",
        evidence_hash="hash:evidence:1",
        eligibility_decision_hash="decision:1",
        eligibility_snapshot_id="snapshot:1",
        finalized_operation_id="operation:1",
    )


class TestTransitionPipeline:
    def test_begin_transition(self):
        recycling = RecyclingEngine()
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)
        record = engine.begin_transition(1)
        assert record.epoch == 1
        assert record.state == EpochTransitionState.IN_PROGRESS

    def test_freeze_evidence(self):
        recycling = RecyclingEngine()
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)
        engine.begin_transition(1)
        record = engine.freeze_evidence(1)
        assert record is not None
        assert record.state == EpochTransitionState.EVIDENCE_FROZEN

    def test_freeze_unregistered(self):
        recycling = RecyclingEngine()
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)
        record = engine.freeze_evidence(99)
        assert record is None

    def test_calculate_budget(self):
        recycling = RecyclingEngine()
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)
        engine.begin_transition(1)
        budget = engine.calculate_budget(1)
        assert budget is not None
        assert budget.consensus_pool > 0
        assert budget.registry_pool > 0
        assert budget.validation_pool > 0
        assert budget.faucet_pool > 0

    def test_registry_reward_calculation_uses_allocated_epoch_pool(self):
        recycling = RecyclingEngine()
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)
        engine.begin_transition(1)
        budget = engine.calculate_budget(1)

        calculation = engine.calculate_registry_rewards(
            1,
            [_registry_reward_input()],
        )

        assert calculation is not None
        assert calculation.nominal_pool_budget_q_atoms == budget.registry_pool
        assert calculation.calculation_root
        assert engine.get_registry_calculation(1) == calculation
        assert engine.get_transition(1).notes["registry_calculation_root"] == calculation.calculation_root


class TestTransitionWithRecycling:
    def test_recyclable_included_in_budget(self):
        recycling = RecyclingEngine(max_recycle_lag=5)
        recycling.add_source(RecyclingSource.BOND_FORFEIT, 100_000_000, 1)
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)
        engine.begin_transition(3)
        budget = engine.calculate_budget(3)
        assert budget is not None
        # Budget should include recyclable
        assert budget.total_budget > budget.base_emission

    def test_recycle_eligible_before_budget(self):
        recycling = RecyclingEngine(max_recycle_lag=5)
        recycling.add_source(RecyclingSource.BOND_FORFEIT, 500_000_000, 1)
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)
        engine.begin_transition(3)
        engine.calculate_budget(3)
        # Records should now be recycled
        assert recycling.get_total_recycled() == 500_000_000


class TestEmissionRecording:
    def test_record_emission(self):
        recycling = RecyclingEngine()
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)
        engine.begin_transition(1)
        emission = engine.record_emission(
            epoch=1,
            consensus_allocated=1_500_000_000,
            registry_allocated=1_500_000_000,
            validation_allocated=1_500_000_000,
            faucet_allocated=500_000_000,
            total_minted=5_000_000_000,
        )
        assert emission is not None
        assert emission.total_minted == 5_000_000_000

    def test_get_emission(self):
        recycling = RecyclingEngine()
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)
        engine.begin_transition(1)
        engine.record_emission(
            epoch=1,
            consensus_allocated=1_500_000_000,
            registry_allocated=1_500_000_000,
            validation_allocated=1_500_000_000,
            faucet_allocated=500_000_000,
            total_minted=5_000_000_000,
        )
        emission = engine.get_emission(1)
        assert emission is not None
        assert emission.epoch == 1


class TestTransitionCompletion:
    def test_complete_transition(self):
        recycling = RecyclingEngine()
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)
        engine.begin_transition(1)
        record = engine.complete_transition(1)
        assert record is not None
        assert record.state == EpochTransitionState.COMPLETE

    def test_fail_transition(self):
        recycling = RecyclingEngine()
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)
        engine.begin_transition(1)
        record = engine.fail_transition(1, "budget overflow")
        assert record is not None
        assert record.state == EpochTransitionState.FAILED
        assert "budget overflow" in record.notes.get("failure_reason", "")

    def test_get_transition(self):
        recycling = RecyclingEngine()
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)
        engine.begin_transition(1)
        record = engine.get_transition(1)
        assert record is not None
        assert record.epoch == 1

    def test_recycling_engine_accessible(self):
        recycling = RecyclingEngine()
        pools = ServicePoolManager()
        engine = EpochTransitionEngine(pools, recycling)
        assert engine.recycling_engine is recycling
