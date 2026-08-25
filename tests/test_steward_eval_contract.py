import json
from pathlib import Path

import pytest

from aidn_hypervisor.steward_safety import classify_steward_request

_CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "steward_eval_cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_steward_eval_cases_keep_high_risk_intent_deterministic(case: dict) -> None:
    decision = classify_steward_request(case["message"])

    assert decision.intent == case["expected_intent"]
    assert decision.blocked is case["expected_blocked"]
