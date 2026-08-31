"""Versioned model profiles for the local Resident Steward.

The profile is deliberately separate from the model lifecycle adapter.  It
describes a reviewed *starting point* for Steward inference (model family,
bounded decoding and context limits); the operator may still keep an existing
artifact or choose another provider through the normal lifecycle APIs.

This module does not download models and it never changes a running node by
itself.  That separation lets us benchmark the current node 118 Q8 artifact
against the recommended Q4 profile before making an operational switch.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from aidn_hypervisor.runtime_parameter_policy import (
    supported_runtime_parameters,
)

DEFAULT_STEWARD_MODEL_PROFILE_ID = "qwen3-0.6b-steward.v1"


@dataclass(frozen=True)
class StewardModelProfile:
    """Reviewed defaults for one Steward model candidate."""

    profile_id: str
    display_name: str
    provider_type: str
    execution_profile: str
    model_repo: str
    model_file: str | None
    quantization: str
    context_length: int
    max_output_tokens: int
    request_timeout_seconds: float
    temperature: float
    top_p: float
    # ``None`` means the model family has no reviewed thinking toggle.  Do not
    # forward Qwen-specific chat-template kwargs to unrelated templates.
    enable_thinking: bool | None
    status: str
    task_scope: tuple[str, ...]
    notes: str

    def chat_parameters(self) -> dict[str, Any]:
        """Return bounded, deterministic request defaults for the chat path."""

        # Thinking is intentionally not configurable through the operator chat
        # payload.  The Qwen3 profile is a dispatcher, not a long-form reasoner.
        parameters: dict[str, Any] = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_output_tokens,
        }
        if self.enable_thinking is not None:
            parameters["chat_template_kwargs"] = {
                "enable_thinking": self.enable_thinking
            }
        return parameters

    def runtime_parameter_policy(self, provider_type: str | None = None) -> dict[str, Any]:
        """Return only supported canonical runtime overrides for this profile.

        The lifecycle adapter merges these values with the provider's complete
        policy.  In particular, the context length remains operator-owned while
        request decoding remains bounded and explicit.
        """

        provider = (provider_type or self.provider_type).strip().lower()
        supported = supported_runtime_parameters(provider)
        values = {
            "context_length": self.context_length,
            "max_tokens": self.max_output_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }
        return {
            name: {"value": value}
            for name, value in values.items()
            if name in supported
        }

    def as_payload(self) -> dict[str, Any]:
        """Return a secret-free projection suitable for status and benchmarks."""

        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "provider_type": self.provider_type,
            "execution_profile": self.execution_profile,
            "model_repo": self.model_repo,
            "model_file": self.model_file,
            "quantization": self.quantization,
            "context_length": self.context_length,
            "max_output_tokens": self.max_output_tokens,
            "request_timeout_seconds": self.request_timeout_seconds,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "thinking": self.enable_thinking,
            "status": self.status,
            "task_scope": list(self.task_scope),
            "notes": self.notes,
        }


_PROFILES: dict[str, StewardModelProfile] = {
    DEFAULT_STEWARD_MODEL_PROFILE_ID: StewardModelProfile(
        profile_id=DEFAULT_STEWARD_MODEL_PROFILE_ID,
        display_name="Qwen3 0.6B Steward (recommended Q4)",
        provider_type="llama.cpp",
        execution_profile="CPU_RESIDENT",
        model_repo="unsloth/Qwen3-0.6B-GGUF",
        model_file="Qwen3-0.6B-Q4_K_M.gguf",
        quantization="Q4_K_M",
        context_length=4096,
        max_output_tokens=160,
        request_timeout_seconds=24.0,
        temperature=0.0,
        top_p=0.8,
        enable_thinking=False,
        status="recommended",
        task_scope=(
            "node_status",
            "event_log_summary",
            "installation_next_step",
            "tool_selection",
            "escalation",
        ),
        notes=(
            "Small deterministic dispatcher profile. Keep policy and tool "
            "execution in Hypervisor code; switch from the current Q8 baseline "
            "only after a measured benchmark run."
        ),
    ),
    "qwen3-0.6b-baseline-q8.v1": StewardModelProfile(
        profile_id="qwen3-0.6b-baseline-q8.v1",
        display_name="Qwen3 0.6B Steward (node 118 Q8 baseline)",
        provider_type="llama.cpp",
        execution_profile="CPU_RESIDENT",
        model_repo="Qwen/Qwen3-0.6B-GGUF",
        model_file="Qwen3-0.6B-Q8_0.gguf",
        quantization="Q8_0",
        context_length=4096,
        max_output_tokens=160,
        request_timeout_seconds=24.0,
        temperature=0.0,
        top_p=0.8,
        enable_thinking=False,
        status="baseline",
        task_scope=(
            "node_status",
            "event_log_summary",
            "installation_next_step",
            "tool_selection",
            "escalation",
        ),
        notes="Current node 118 artifact; use as the first measured control.",
    ),
    "smollm2-1.7b-instruct.v1": StewardModelProfile(
        profile_id="smollm2-1.7b-instruct.v1",
        display_name="SmolLM2 1.7B Instruct (comparison candidate)",
        provider_type="llama.cpp",
        execution_profile="CPU_RESIDENT",
        model_repo="HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF",
        model_file="smollm2-1.7b-instruct-q4_k_m.gguf",
        quantization="Q4_K_M",
        context_length=4096,
        max_output_tokens=64,
        request_timeout_seconds=24.0,
        temperature=0.0,
        top_p=0.8,
        enable_thinking=None,
        status="candidate",
        task_scope=(
            "node_status",
            "event_log_summary",
            "installation_next_step",
            "tool_selection",
            "escalation",
        ),
        notes="Do not install automatically; compare on StewardBench first.",
    ),
}


def get_steward_model_profile(profile_id: str | None = None) -> StewardModelProfile:
    """Resolve one profile, defaulting to the reviewed local recommendation."""

    selected = (
        profile_id
        or os.getenv("AIDN_STEWARD_MODEL_PROFILE", "")
        or DEFAULT_STEWARD_MODEL_PROFILE_ID
    ).strip()
    try:
        return _PROFILES[selected]
    except KeyError as error:
        available = ", ".join(sorted(_PROFILES))
        raise ValueError(
            f"unknown Steward model profile '{selected}'; choose one of: {available}"
        ) from error


def list_steward_model_profiles() -> list[StewardModelProfile]:
    """Return profiles in stable id order for CLI/UI and benchmark discovery."""

    return [_PROFILES[key] for key in sorted(_PROFILES)]


def steward_chat_parameters(profile_id: str | None = None) -> dict[str, Any]:
    return get_steward_model_profile(profile_id).chat_parameters()


def steward_runtime_parameter_policy(
    *, profile_id: str | None = None, provider_type: str | None = None
) -> dict[str, Any]:
    profile = get_steward_model_profile(profile_id)
    return profile.runtime_parameter_policy(provider_type)


__all__ = [
    "DEFAULT_STEWARD_MODEL_PROFILE_ID",
    "StewardModelProfile",
    "get_steward_model_profile",
    "list_steward_model_profiles",
    "steward_chat_parameters",
    "steward_runtime_parameter_policy",
]
