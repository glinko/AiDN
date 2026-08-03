from __future__ import annotations

import pytest

from aidn_hypervisor.registry.duty import FIXED_POINT_SCALE, RegistryRewardInput
from aidn_hypervisor.reward.registry_distribution import RegistryEpochRewardCalculator


def _input(
    service_id: str,
    *,
    raw_weight: int,
    group_id: str | None,
    epoch: int = 7,
) -> RegistryRewardInput:
    return RegistryRewardInput(
        service_id=service_id,
        epoch=epoch,
        reward_beneficiary=f"wallet:{service_id}",
        known_control_group_id=group_id,
        work_units_millionths=raw_weight,
        maturity_factor_millionths=FIXED_POINT_SCALE,
        health_factor_millionths=FIXED_POINT_SCALE,
        proof_success_millionths=FIXED_POINT_SCALE,
        completeness_millionths=FIXED_POINT_SCALE,
        availability_millionths=FIXED_POINT_SCALE,
        latency_factor_millionths=FIXED_POINT_SCALE,
        reliability_factor_millionths=FIXED_POINT_SCALE,
        raw_weight_millionths=raw_weight,
        evidence_id=f"evidence:{service_id}",
        evidence_hash=f"hash:evidence:{service_id}",
        eligibility_decision_hash=f"decision:{service_id}",
        eligibility_snapshot_id=f"snapshot:{service_id}",
        finalized_operation_id=f"operation:{service_id}",
    )


def test_registry_distribution_is_fixed_point_deterministic_and_diversity_bounded() -> None:
    calculator = RegistryEpochRewardCalculator()
    inputs = [
        _input("registry-b", raw_weight=300, group_id="kcg-b"),
        _input("registry-a", raw_weight=700, group_id="kcg-a"),
    ]

    first = calculator.calculate(
        inputs,
        epoch=7,
        nominal_pool_budget_q_atoms=1_000_000,
        pool_budget_reference="epoch:7:registry",
    )
    second = calculator.calculate(
        list(reversed(inputs)),
        epoch=7,
        nominal_pool_budget_q_atoms=1_000_000,
        pool_budget_reference="epoch:7:registry",
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.independent_group_count == 2
    assert first.diversity_factor_millionths == 400_000
    assert first.distributable_pool_q_atoms == 400_000
    assert sum(item.allocated_q_atoms for item in first.allocations) == 400_000
    assert first.unused_pool_q_atoms == 600_000
    assert first.calculation_root
    assert first.verify_integrity() is True
    assert first.reward_id_for(first.allocations[0]) == second.reward_id_for(second.allocations[0])


def test_registry_distribution_caps_known_control_group_before_redistribution() -> None:
    calculator = RegistryEpochRewardCalculator()
    calculation = calculator.calculate(
        [
            _input("registry-a", raw_weight=900, group_id="kcg-dominant"),
            _input("registry-b", raw_weight=50, group_id="kcg-dominant"),
            _input("registry-c", raw_weight=50, group_id="kcg-independent-1"),
            _input("registry-d", raw_weight=50, group_id="kcg-independent-2"),
        ],
        epoch=7,
        nominal_pool_budget_q_atoms=1_000_000,
        pool_budget_reference="epoch:7:registry",
    )

    dominant = sum(
        item.allocated_q_atoms
        for item in calculation.allocations
        if item.effective_group_id == "kcg-dominant"
    )

    assert calculation.independent_group_count == 3
    assert calculation.diversity_factor_millionths == 600_000
    assert calculation.distributable_pool_q_atoms == 600_000
    assert dominant <= calculation.maximum_group_share_q_atoms
    assert any(item.group_cap_applied for item in calculation.allocations)
    assert sum(item.allocated_q_atoms for item in calculation.allocations) <= 600_000
    assert calculation.unallocated_distributable_q_atoms >= 0


def test_registry_distribution_rejects_duplicate_service_or_mixed_epoch() -> None:
    calculator = RegistryEpochRewardCalculator()
    duplicate = _input("registry-a", raw_weight=1, group_id="kcg-a")

    with pytest.raises(ValueError, match="duplicate service"):
        calculator.calculate(
            [duplicate, duplicate],
            epoch=7,
            nominal_pool_budget_q_atoms=1_000_000,
            pool_budget_reference="epoch:7:registry",
        )

    with pytest.raises(ValueError, match="epoch mismatch"):
        calculator.calculate(
            [_input("registry-b", raw_weight=1, group_id="kcg-b", epoch=8)],
            epoch=7,
            nominal_pool_budget_q_atoms=1_000_000,
            pool_budget_reference="epoch:7:registry",
        )


def test_registry_distribution_with_no_inputs_keeps_budget_unminted() -> None:
    calculation = RegistryEpochRewardCalculator().calculate(
        [],
        epoch=7,
        nominal_pool_budget_q_atoms=123,
        pool_budget_reference="epoch:7:registry",
    )

    assert calculation.independent_group_count == 0
    assert calculation.distributable_pool_q_atoms == 0
    assert calculation.unused_pool_q_atoms == 123
    assert calculation.allocations == []
