from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from aidn_hypervisor.installation_onboarding import (
    InstallationOnboardingPlan,
    installation_plan_hash,
    read_installation_plan,
    update_installation_plan,
    validate_model_source,
    write_installation_plan,
)


def test_manual_plan_is_minimal_and_never_claims_ai_control() -> None:
    plan = InstallationOnboardingPlan()

    payload = plan.to_dict()

    assert payload["mode"] == "manual"
    assert payload["ai_assisted"] is False
    assert payload["status"] == "MANUAL"
    assert payload["authority"]["publication"] == "validation_and_operator_policy_required"


def test_ai_plan_preserves_operator_choices_and_is_review_bound() -> None:
    plan = InstallationOnboardingPlan(
        setup_mode="ai_assisted",
        provider="llama.cpp",
        model_id="unsloth/Qwen3.8-27B-GGUF",
        model_source="hf://unsloth/Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-Q4_K_XL.gguf",
        endpoint_action="draft",
        handoff="continue",
    )

    payload = plan.to_dict(plan_path="/var/lib/aidn/installation-plan.json")

    assert payload["ai_assisted"] is True
    assert payload["provider"] == "llama.cpp"
    assert payload["model"]["id"] == "unsloth/Qwen3.8-27B-GGUF"
    assert payload["endpoint"]["requested_action"] == "draft"
    assert payload["next_action"] == "resident_steward_review"
    assert payload["authority"]["downloads"] == "explicit_operator_review_required"


def test_model_source_rejects_credentials_query_and_non_https() -> None:
    with pytest.raises(ValueError):
        validate_model_source("https://user:secret@example.test/model.gguf", provider="llama.cpp")
    with pytest.raises(ValueError):
        validate_model_source("https://huggingface.co/org/model?token=secret", provider="llama.cpp")
    with pytest.raises(ValueError):
        validate_model_source("http://example.test/model.gguf", provider="llama.cpp")


def test_provider_and_model_dependency_is_validated() -> None:
    with pytest.raises(ValueError, match="without a provider"):
        InstallationOnboardingPlan(setup_mode="ai_assisted", model_id="org/model")
    with pytest.raises(ValueError, match="model must be selected"):
        InstallationOnboardingPlan(
            setup_mode="ai_assisted",
            provider="llama.cpp",
            endpoint_action="draft",
        )


def test_plan_write_is_structured_and_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "state" / "installation-plan.json"
    payload = write_installation_plan(
        path,
        InstallationOnboardingPlan(setup_mode="ai_assisted", provider="ollama"),
    )

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["mode"] == "ai_assisted"
    assert payload["plan_path"] == str(path)
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0


def test_plan_read_is_hash_bound_and_updates_atomically(tmp_path: Path) -> None:
    path = tmp_path / "state" / "installation-plan.json"
    write_installation_plan(
        path,
        InstallationOnboardingPlan(
            setup_mode="ai_assisted",
            provider="llama.cpp",
            model_id="org/model",
            model_source="hf://org/model/model.gguf",
        ),
    )

    projection = read_installation_plan(path)
    assert projection["available"] is True
    assert projection["integrity"] == "verified"
    assert projection["status"] == "READY_FOR_REVIEW"
    original_hash = str(projection["plan_hash"])

    updated = update_installation_plan(
        path,
        expected_hash=original_hash,
        status="MODEL_INSTALL_QUEUED",
        application={"actor": "test"},
        next_action="process_model_install",
    )
    assert updated["status"] == "MODEL_INSTALL_QUEUED"
    assert updated["integrity"] == "verified"
    assert updated["plan_hash"] != original_hash


def test_plan_tampering_is_not_treated_as_legacy(tmp_path: Path) -> None:
    path = tmp_path / "installation-plan.json"
    write_installation_plan(path, InstallationOnboardingPlan(setup_mode="ai_assisted", provider="ollama"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["provider"] = "vllm"
    path.write_text(json.dumps(payload), encoding="utf-8")

    projection = read_installation_plan(path)
    assert projection["integrity"] == "mismatch"
    assert projection["status"] == "STALE"
    assert "changed" in str(projection["reason"])


def test_hash_excludes_its_own_field() -> None:
    payload = {"mode": "manual", "plan_hash": "old"}
    assert installation_plan_hash(payload) == installation_plan_hash({"mode": "manual"})
