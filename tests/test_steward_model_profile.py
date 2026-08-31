import pytest

from aidn_hypervisor.steward_model_profile import (
    DEFAULT_STEWARD_MODEL_PROFILE_ID,
    get_steward_model_profile,
    list_steward_model_profiles,
    steward_runtime_parameter_policy,
)


def test_recommended_profile_is_qwen3_q4_cpu_no_think() -> None:
    profile = get_steward_model_profile()

    assert profile.profile_id == DEFAULT_STEWARD_MODEL_PROFILE_ID
    assert profile.model_repo == "unsloth/Qwen3-0.6B-GGUF"
    assert profile.quantization == "Q4_K_M"
    assert profile.provider_type == "llama.cpp"
    assert profile.execution_profile == "CPU_RESIDENT"
    assert profile.context_length == 4096
    assert profile.max_output_tokens == 160
    assert profile.enable_thinking is False
    assert profile.chat_parameters()["chat_template_kwargs"] == {"enable_thinking": False}


def test_runtime_policy_contains_only_supported_llama_parameters() -> None:
    policy = steward_runtime_parameter_policy(provider_type="llama.cpp")

    assert policy["context_length"] == {"value": 4096}
    assert policy["max_tokens"] == {"value": 160}
    assert policy["temperature"] == {"value": 0.0}
    assert policy["top_p"] == {"value": 0.8}
    assert "enable_thinking" not in policy


def test_profile_registry_exposes_baseline_and_comparison_candidate() -> None:
    profiles = {profile.profile_id: profile for profile in list_steward_model_profiles()}

    assert "qwen3-0.6b-baseline-q8.v1" in profiles
    assert "smollm2-1.7b-instruct.v1" in profiles
    smollm = profiles["smollm2-1.7b-instruct.v1"]
    assert smollm.status == "candidate"
    assert smollm.model_repo == "HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF"
    assert smollm.enable_thinking is None
    assert "chat_template_kwargs" not in smollm.chat_parameters()


def test_unknown_profile_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("AIDN_STEWARD_MODEL_PROFILE", "not-a-profile")

    with pytest.raises(ValueError, match="unknown Steward model profile"):
        get_steward_model_profile()
