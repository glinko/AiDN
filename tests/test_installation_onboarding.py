from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from aidn_hypervisor.installation_onboarding import (
    InstallationOnboardingPlan,
    build_installation_workflow_projection,
    installation_plan_hash,
    prepare_assisted_installation_review,
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


def test_hf_model_source_accepts_an_immutable_revision() -> None:
    source = "hf://org/model@0123456789abcdef0123456789abcdef01234567/model.gguf"
    assert validate_model_source(source, provider="llama.cpp") == source
    with pytest.raises(ValueError, match="40-character"):
        validate_model_source("hf://org/model@main/model.gguf", provider="llama.cpp")


def test_plan_persists_pinned_model_integrity_metadata(tmp_path: Path) -> None:
    plan = InstallationOnboardingPlan(
        setup_mode="ai_assisted",
        provider="llama.cpp",
        model_id="org/model",
        model_source="hf://org/model@0123456789abcdef0123456789abcdef01234567/model.gguf",
        model_expected_sha256="a" * 64,
        model_expected_bytes=123,
    )

    payload = write_installation_plan(tmp_path / "installation-plan.json", plan)

    assert payload["model"]["expected_sha256"] == "a" * 64
    assert payload["model"]["expected_bytes"] == 123
    projection = read_installation_plan(tmp_path / "installation-plan.json")
    assert projection["model"]["expected_sha256"] == "a" * 64
    assert projection["model"]["expected_bytes"] == 123


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


def test_assisted_plan_preparation_persists_a_provider_review(tmp_path: Path) -> None:
    path = tmp_path / "installation-plan.json"
    write_installation_plan(
        path,
        InstallationOnboardingPlan(
            setup_mode="ai_assisted",
            provider="llama.cpp",
            model_id="org/model",
            model_source="hf://org/model/model.gguf",
            endpoint_action="draft",
            handoff="continue",
        ),
    )
    current = read_installation_plan(path)
    prepared = prepare_assisted_installation_review(
        path,
        expected_hash=str(current["plan_hash"]),
        actor="operator-test",
        idempotency_key="setup-1",
        provider_plan_builder=lambda plugin_id, configuration: {
            "plan_id": f"plan-{plugin_id}",
            "plan_version": "1",
            "summary": "reviewed provider plan",
            "required_permissions": [{"permission_id": "host.package_manager"}],
            "health_checks": [],
            "secret_references": ["not projected"],
        },
    )

    assert prepared["status"] == "PROVIDER_REVIEW_REQUIRED"
    assert prepared["next_action"] == "approve_provider_installation"
    assert prepared["application"]["provider"]["status"] == "REVIEW_REQUIRED"
    assert prepared["application"]["model"]["status"] == "PENDING_PROVIDER"
    assert prepared["application"]["endpoint"]["status"] == "PENDING_MODEL"
    assert prepared["application"]["provider"]["installation_plan"]["plan_hash"].startswith("sha256:")
    assert "secret_references" not in prepared["application"]["provider"]["installation_plan"]

    replay = prepare_assisted_installation_review(
        path,
        expected_hash=str(prepared["plan_hash"]),
        actor="operator-test",
        idempotency_key="setup-1",
        provider_plan_builder=lambda *_args: pytest.fail("idempotent replay must not rebuild the provider plan"),
    )
    assert replay["application"]["operation_id"] == prepared["operation_id"]


def test_assisted_plan_preparation_rejects_manual_or_stale_plan(tmp_path: Path) -> None:
    path = tmp_path / "installation-plan.json"
    write_installation_plan(path, InstallationOnboardingPlan())
    current = read_installation_plan(path)

    with pytest.raises(ValueError, match="AI-assisted"):
        prepare_assisted_installation_review(
            path,
            expected_hash=str(current["plan_hash"]),
            actor="operator-test",
            provider_plan_builder=lambda *_args: {},
        )

    write_installation_plan(path, InstallationOnboardingPlan(setup_mode="ai_assisted", provider="ollama"))
    with pytest.raises(ValueError, match="changed"):
        prepare_assisted_installation_review(
            path,
            expected_hash="sha256:stale",
            actor="operator-test",
            provider_plan_builder=lambda *_args: {},
        )


def test_hash_excludes_its_own_field() -> None:
    payload = {"mode": "manual", "plan_hash": "old"}
    assert installation_plan_hash(payload) == installation_plan_hash({"mode": "manual"})


def test_workflow_projection_recomputes_next_step_from_observed_state() -> None:
    plan = InstallationOnboardingPlan(
        setup_mode="ai_assisted",
        provider="llama.cpp",
        model_id="org/model",
        model_source="hf://org/model/model.gguf",
        endpoint_action="draft",
    ).to_dict()
    plan.update(
        available=True,
        integrity="verified",
        status="PROVIDER_REVIEW_REQUIRED",
        plan_hash="sha256:test",
        application={"provider": {"status": "REVIEW_REQUIRED"}},
    )

    review = build_installation_workflow_projection(plan)
    assert review["next_action"]["id"] == "approve_provider_installation"
    assert review["stages"][0]["state"] == "REVIEW_REQUIRED"

    provider_plan_hash = "sha256:provider-plan"
    plan["application"]["provider"]["installation_plan"] = {"plan_hash": provider_plan_hash}
    approved = build_installation_workflow_projection(
        plan,
        provider_installation_approvals=[
            {"plugin_id": "llama.cpp", "plan_hash": provider_plan_hash, "status": "APPROVED"}
        ],
    )
    assert approved["next_action"]["id"] == "apply_provider_installation"
    assert approved["stages"][0]["state"] == "IN_PROGRESS"

    provider_ready = build_installation_workflow_projection(
        plan,
        provider_instances=[{"plugin_id": "llama.cpp", "status": "attached"}],
    )
    assert provider_ready["next_action"]["id"] == "request_model_install"
    assert provider_ready["stages"][0]["state"] == "READY"

    model_queued = build_installation_workflow_projection(
        plan,
        provider_instances=[{"plugin_id": "llama.cpp", "status": "attached"}],
        model_installs=[{"model_id": "org/model", "status": "queued"}],
    )
    assert model_queued["next_action"]["id"] == "process_model_install"
    assert model_queued["stages"][1]["state"] == "IN_PROGRESS"

    model_ready = build_installation_workflow_projection(
        plan,
        provider_instances=[{"plugin_id": "llama.cpp", "status": "attached"}],
        model_installs=[{"model_id": "org/model", "status": "completed"}],
    )
    assert model_ready["next_action"]["id"] == "create_bundle"
    assert model_ready["stages"][1]["state"] == "READY"


def test_workflow_projection_marks_tampered_plan_stale() -> None:
    projection = build_installation_workflow_projection(
        {"available": True, "status": "STALE", "integrity": "mismatch"}
    )
    assert projection["status"] == "STALE"
    assert projection["next_action"]["id"] == "regenerate_installation_plan"
