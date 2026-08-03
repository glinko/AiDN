import json
import subprocess
import sys
from pathlib import Path

from aidn_hypervisor.reward.development_scenarios import run_launch_simulation_matrix

REQUIRED_SCENARIOS = {
    "low-contribution-volume",
    "dominant-contributor",
    "many-small-contributors",
    "very-large-pr",
    "pr-fragmentation",
    "reviewer-allocation-control-group",
    "high-security-reserve",
    "inactive-epoch",
    "oversubscribed-pool",
    "high-carryover",
}


def test_launch_matrix_is_deterministic_and_non_emitting():
    first = run_launch_simulation_matrix()
    second = run_launch_simulation_matrix()

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.simulation_only is True
    assert first.emits_q is False
    assert first.ledger_writes is False
    assert first.all_invariants_passed is True
    assert first.verify_integrity()
    assert {item.scenario_id for item in first.scenarios} >= REQUIRED_SCENARIOS
    assert all(item.passed and item.verify_integrity() for item in first.scenarios)


def test_launch_matrix_exercises_caps_reserves_and_empty_epochs():
    report = run_launch_simulation_matrix()
    scenarios = {item.scenario_id: item for item in report.scenarios}

    dominant = scenarios["dominant-contributor"].calculation
    assert dominant.contributor_cap_overflow_q_atoms > 0

    fragmented = scenarios["pr-fragmentation"].calculation
    assert fragmented.group_cap_overflow_q_atoms == 150_000_000
    assert fragmented.accepted_gross_reward_q_atoms == 50_000_000

    reviewer = scenarios["reviewer-allocation-control-group"].calculation
    reviewer_roles = [
        role
        for allocation in reviewer.allocations
        for role in allocation.role_rewards
        if role.role == "PRIMARY_REVIEWER"
    ]
    assert reviewer_roles
    assert reviewer.contributor_cap_overflow_q_atoms > 0

    security = scenarios["high-security-reserve"].calculation
    assert security.pool.security_reserve_q_atoms == 200_000_000
    assert security.pool.available_contribution_budget_q_atoms == 37_500_000

    inactive = scenarios["inactive-epoch"].calculation
    assert inactive.nominal_demand_q_atoms == 0
    assert inactive.accepted_gross_reward_q_atoms == 0

    carryover = scenarios["high-carryover"].calculation
    assert carryover.pool.carryover_out_q_atoms == carryover.pool.carryover_limit_q_atoms
    assert carryover.pool.returned_to_emission_reserve_q_atoms > 0


def test_scenario_cli_reports_the_non_emitting_boundary(tmp_path):
    repository_root = Path(__file__).parents[2]
    output_path = tmp_path / "development-reward-scenarios.json"
    result = subprocess.run(
        [
            sys.executable,
            str(repository_root / "tools" / "simulate-development-reward-scenarios.py"),
            "--output",
            str(output_path),
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout == ""
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["simulation_only"] is True
    assert payload["emits_q"] is False
    assert payload["ledger_writes"] is False
    assert payload["all_invariants_passed"] is True
    assert payload["report_root"].startswith("sha256:")
