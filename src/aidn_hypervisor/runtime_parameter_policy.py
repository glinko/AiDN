"""Validated runtime/request parameter policy for operator-managed models.

The operator owns the values that affect residency and allocation (for example
context length and GPU memory limits).  A consumer may only override a value
when the operator explicitly marks that parameter as editable.  This module is
deliberately provider-neutral; plugins translate the canonical names to their
native request/launch flags.
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from aidn_hypervisor.domain.models import BundleConfig, TaskRequest


class RuntimeParameterPolicy(BaseModel):
    """One operator-owned default and its consumer mutability boundary."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    value: Any
    consumer_editable: bool = False
    minimum: float | None = Field(default=None, alias="min")
    maximum: float | None = Field(default=None, alias="max")

    @model_validator(mode="after")
    def validate_bounds(self) -> RuntimeParameterPolicy:
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("runtime parameter minimum must not exceed maximum")
        if isinstance(self.value, bool):
            numeric_value = None
        elif isinstance(self.value, (int, float)):
            numeric_value = float(self.value)
        else:
            numeric_value = None
        if numeric_value is not None:
            if self.minimum is not None and numeric_value < self.minimum:
                raise ValueError("runtime parameter value is below its minimum")
            if self.maximum is not None and numeric_value > self.maximum:
                raise ValueError("runtime parameter value is above its maximum")
        elif self.minimum is not None or self.maximum is not None:
            raise ValueError("runtime parameter bounds require a numeric value")
        return self


# Canonical names are intentionally small and stable. Provider plugins map
# these to their native options (Ollama num_ctx/num_predict, llama.cpp
# --ctx-size/n_predict, and OpenAI-compatible max_tokens/top_k/penalties).
_DEFAULTS: dict[str, dict[str, dict[str, Any]]] = {
    "ollama": {
        "temperature": {"value": 0.7, "consumer_editable": True, "min": 0.0, "max": 2.0},
        "top_p": {"value": 0.9, "consumer_editable": True, "min": 0.0, "max": 1.0},
        "top_k": {"value": 40, "consumer_editable": True, "min": 1, "max": 100000},
        "repeat_penalty": {"value": 1.1, "consumer_editable": True, "min": 0.0, "max": 10.0},
        "max_tokens": {"value": 512, "consumer_editable": True, "min": 1, "max": 32768},
        "context_length": {"value": 4096, "consumer_editable": False, "min": 512, "max": 131072},
        "gpu_memory_utilization": {"value": 0.9, "consumer_editable": False, "min": 0.1, "max": 0.99},
    },
    "llama.cpp": {
        "temperature": {"value": 0.7, "consumer_editable": True, "min": 0.0, "max": 2.0},
        "top_p": {"value": 0.9, "consumer_editable": True, "min": 0.0, "max": 1.0},
        "top_k": {"value": 40, "consumer_editable": True, "min": 1, "max": 100000},
        "repeat_penalty": {"value": 1.1, "consumer_editable": True, "min": 0.0, "max": 10.0},
        "max_tokens": {"value": 512, "consumer_editable": True, "min": 1, "max": 32768},
        "context_length": {"value": 4096, "consumer_editable": False, "min": 512, "max": 131072},
        "gpu_layers": {"value": 99, "consumer_editable": False, "min": 0, "max": 999},
    },
    "vllm": {
        "temperature": {"value": 0.7, "consumer_editable": True, "min": 0.0, "max": 2.0},
        "top_p": {"value": 0.9, "consumer_editable": True, "min": 0.0, "max": 1.0},
        "top_k": {"value": 40, "consumer_editable": True, "min": 1, "max": 100000},
        "frequency_penalty": {"value": 0.0, "consumer_editable": True, "min": -2.0, "max": 2.0},
        "presence_penalty": {"value": 0.0, "consumer_editable": True, "min": -2.0, "max": 2.0},
        "max_tokens": {"value": 512, "consumer_editable": True, "min": 1, "max": 32768},
        "context_length": {"value": 8192, "consumer_editable": False, "min": 512, "max": 131072},
        "gpu_memory_utilization": {"value": 0.9, "consumer_editable": False, "min": 0.1, "max": 0.99},
    },
}


def _provider_key(provider_type: str) -> str:
    return provider_type.strip().lower()


def supported_runtime_parameters(provider_type: str) -> set[str]:
    return set(_DEFAULTS.get(_provider_key(provider_type), {}))


def default_runtime_parameter_policy(provider_type: str) -> dict[str, RuntimeParameterPolicy]:
    return {
        key: RuntimeParameterPolicy.model_validate(value)
        for key, value in deepcopy(_DEFAULTS.get(_provider_key(provider_type), {})).items()
    }


def normalize_runtime_parameter_policy(
    provider_type: str,
    policy: dict[str, Any] | None,
) -> dict[str, RuntimeParameterPolicy]:
    """Merge operator values with safe defaults and reject unknown parameters."""

    defaults = default_runtime_parameter_policy(provider_type)
    if policy is None:
        return defaults
    if not isinstance(policy, dict):
        raise ValueError("runtime_parameter_policy must be an object")
    unknown = sorted(set(policy) - set(defaults))
    if unknown:
        raise ValueError(
            f"unsupported runtime parameters for {provider_type}: {', '.join(unknown)}"
        )
    result = dict(defaults)
    for key, raw in policy.items():
        base = defaults[key]
        if isinstance(raw, dict):
            payload = dict(raw)
            # Keep provider-safe bounds when the UI only sends value/toggle.
            payload.setdefault("min", base.minimum)
            payload.setdefault("max", base.maximum)
            result[key] = RuntimeParameterPolicy.model_validate(payload)
        else:
            result[key] = base.model_copy(update={"value": raw})
    return result


def policy_json(policy: dict[str, RuntimeParameterPolicy]) -> dict[str, dict[str, Any]]:
    return {
        key: value.model_dump(mode="json", by_alias=True)
        for key, value in policy.items()
    }


def marketplace_parameter_policy(
    policy: dict[str, RuntimeParameterPolicy] | dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the public, machine-readable parameter contract for an Endpoint.

    ``runtime_parameter_policy`` is the signed/internal representation.  The
    Marketplace gets an intentionally explicit projection so a consumer does
    not need to infer checkbox semantics from ``consumer_editable``.
    """

    parameters: list[dict[str, Any]] = []
    for name, raw in (policy or {}).items():
        setting = (
            raw
            if isinstance(raw, RuntimeParameterPolicy)
            else RuntimeParameterPolicy.model_validate(raw)
        )
        parameters.append(
            {
                "name": name,
                "default": setting.value,
                "mutable": setting.consumer_editable,
                "locked": not setting.consumer_editable,
                "minimum": setting.minimum,
                "maximum": setting.maximum,
            }
        )
    parameters.sort(key=lambda item: item["name"])
    return {
        "version": "runtime-parameters.v1",
        "parameters": parameters,
    }


def apply_runtime_parameter_policy_payload(
    payload: dict[str, Any],
    policy: dict[str, RuntimeParameterPolicy] | dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply defaults and enforce the operator's consumer override boundary."""

    if not policy:
        return dict(payload)
    normalized = {
        name: (
            setting
            if isinstance(setting, RuntimeParameterPolicy)
            else RuntimeParameterPolicy.model_validate(setting)
        )
        for name, setting in policy.items()
    }
    result = dict(payload)
    for name, setting in normalized.items():
        if name in result:
            requested = result[name]
            if not setting.consumer_editable and requested != setting.value:
                raise ValueError(
                    f"runtime parameter '{name}' is locked by the operator"
                )
            if (
                setting.consumer_editable
                and isinstance(setting.value, (int, float))
                and not isinstance(setting.value, bool)
            ):
                if not isinstance(requested, (int, float)) or isinstance(requested, bool):
                    raise ValueError(f"runtime parameter '{name}' must be numeric")
                if setting.minimum is not None and requested < setting.minimum:
                    raise ValueError(
                        f"runtime parameter '{name}' is below the operator minimum"
                    )
                if setting.maximum is not None and requested > setting.maximum:
                    raise ValueError(
                        f"runtime parameter '{name}' is above the operator maximum"
                    )
        else:
            result[name] = setting.value
    return result


def apply_runtime_parameter_policy(
    task: TaskRequest,
    bundle: BundleConfig,
    endpoint_policy: dict[str, RuntimeParameterPolicy] | dict[str, Any] | None = None,
) -> TaskRequest:
    """Return a request with policy defaults applied and locked overrides rejected."""

    policy = endpoint_policy or bundle.runtime_parameter_policy
    if not policy:
        return task
    return task.model_copy(
        update={"payload": apply_runtime_parameter_policy_payload(task.payload, policy)}
    )
