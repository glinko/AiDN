"""Conservative resource estimates for provider admission.

Provider plugins still own the provider-specific resource model, but the
accounting primitives live here so every estimator uses the same units and
assumptions.  Estimates are intentionally conservative: they are used to
decide whether a Runtime may start, not to promise an exact profiler result.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

_MIB = 1024 * 1024
_DEFAULT_KV_BYTES_PER_TOKEN_F16 = 262_144
_KV_BYTES_PER_ELEMENT = {
    "f32": 4.0,
    "f16": 2.0,
    "bf16": 2.0,
    "q8_0": 1.0,
    "q8": 1.0,
    "q6_k": 0.75,
    "q5_k": 0.625,
    "q4_0": 0.5,
    "q4_k": 0.5,
}


def _setting_value(policy: dict[str, Any], name: str, default: Any = None) -> Any:
    raw = policy.get(name, default)
    if raw is None:
        return default
    value = getattr(raw, "value", raw)
    return default if value is None else value


def _non_negative_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return default
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _round_up_mib(byte_count: float) -> int:
    return max(0, math.ceil(max(0.0, byte_count) / _MIB))


def model_size_mb(model_id: str | None) -> int | None:
    """Return a local model's size when the model reference is a file path."""

    candidate = str(model_id or "").strip()
    if not candidate:
        return None
    try:
        path = Path(candidate).expanduser()
        if not path.is_file():
            return None
        return max(1, _round_up_mib(path.stat().st_size))
    except OSError:
        return None


def kv_cache_bytes_per_token(
    policy: dict[str, Any],
    *,
    default: int = _DEFAULT_KV_BYTES_PER_TOKEN_F16,
) -> int:
    """Resolve a conservative per-token KV size.

    Providers may later publish an exact model-specific value through
    ``kv_cache_bytes_per_token``.  Until then the default corresponds to a
    GQA-friendly 64-layer/8-KV-head/128-dimension F16 cache and intentionally
    errs on the side of denying an unsafe cold start.
    """

    explicit = _setting_value(policy, "kv_cache_bytes_per_token")
    if explicit is not None:
        return max(1, _non_negative_int(explicit, default))
    return default


def _kv_precision_multiplier(policy: dict[str, Any]) -> float:
    key = str(_setting_value(policy, "kv_cache_type_k", "f16")).strip().lower()
    value = str(_setting_value(policy, "kv_cache_type_v", key)).strip().lower()
    k_bytes = _KV_BYTES_PER_ELEMENT.get(key, 2.0)
    v_bytes = _KV_BYTES_PER_ELEMENT.get(value, 2.0)
    return max(0.25, (k_bytes + v_bytes) / 4.0)


def estimate_llama_cpp_resources(
    *,
    model_id: str | None,
    policy: dict[str, Any] | None,
    resource_profile: Any,
    max_parallel_requests: int = 1,
    runtime_warm: bool = False,
) -> dict[str, Any]:
    """Return a conservative llama.cpp admission estimate.

    Explicit ResourceProfile values remain authoritative.  Derived values are
    used only for dimensions left at zero, which preserves existing operator
    tuning while making legacy empty profiles safe for local GGUF files.
    """

    policy = policy or {}
    model_mb = model_size_mb(model_id)
    # A remote/provider reference is not enough evidence for a local GGUF
    # estimate. Preserve the declared profile and the historical shape until
    # the artifact is materialized locally; inventing workspace numbers here
    # would block attached/test providers without improving safety.
    if model_mb is None:
        return {
            "startup_transient": {
                "cpu": float(getattr(resource_profile, "cold_start_cpu", 0.0) or 0.0),
                "ram_mb": int(getattr(resource_profile, "cold_start_ram_mb", 0) or 0),
                "vram_mb": int(getattr(resource_profile, "cold_start_vram_mb", 0) or 0),
            }
            if not runtime_warm
            else {},
            "runtime_resident": {
                "cpu": float(getattr(resource_profile, "steady_cpu", 0.0) or 0.0),
                "ram_mb": int(getattr(resource_profile, "steady_ram_mb", 0) or 0),
                "vram_mb": int(getattr(resource_profile, "steady_vram_mb", 0) or 0),
            },
            "request_active": {
                "cpu": float(getattr(resource_profile, "per_request_cpu", 0.0) or 0.0),
                "ram_mb": int(getattr(resource_profile, "per_request_ram_mb", 0) or 0),
                "vram_mb": int(getattr(resource_profile, "per_request_vram_mb", 0) or 0),
            },
            "concurrency_limit": 1,
        }
    context = max(1, _non_negative_int(_setting_value(policy, "context_length", 4096), 4096))
    concurrency = max(1, _non_negative_int(max_parallel_requests, 1))
    batch = max(1, _non_negative_int(_setting_value(policy, "batch_size", 512), 512))
    gpu_layers_raw = _setting_value(policy, "gpu_layers", 99)
    gpu_layers = _non_negative_int(gpu_layers_raw, 99)
    # llama.cpp's 99 means "all layers".  Without GGUF metadata we use 99 as
    # the denominator and cap the fraction to avoid an invalid estimate.
    gpu_fraction = min(1.0, gpu_layers / 99.0)

    breakdown: dict[str, int] = {
        "model_weights_mb": model_mb or 0,
        "gpu_model_weights_mb": 0,
        "kv_cache_mb": 0,
        "runtime_workspace_mb": 0,
        "provider_overhead_mb": 0,
        "fragmentation_allowance_mb": 0,
        "host_model_staging_mb": 0,
    }
    assumptions: list[str] = []
    if model_mb is None:
        assumptions.append("model_size_unavailable")
    else:
        breakdown["gpu_model_weights_mb"] = math.ceil(model_mb * gpu_fraction)

    kv_bytes = (
        kv_cache_bytes_per_token(policy)
        * context
        * concurrency
        * _kv_precision_multiplier(policy)
    )
    breakdown["kv_cache_mb"] = _round_up_mib(kv_bytes)
    breakdown["runtime_workspace_mb"] = max(512, math.ceil((model_mb or 0) * 0.05))
    breakdown["provider_overhead_mb"] = max(256, math.ceil((model_mb or 0) * 0.02))
    breakdown["fragmentation_allowance_mb"] = max(
        256,
        math.ceil(
            (
                breakdown["gpu_model_weights_mb"]
                + breakdown["kv_cache_mb"]
                + breakdown["runtime_workspace_mb"]
                + breakdown["provider_overhead_mb"]
            )
            * 0.05
        ),
    )
    kv_offload = bool(_setting_value(policy, "kv_offload", True))
    if kv_offload:
        breakdown["host_model_staging_mb"] = max(0, math.ceil((model_mb or 0) * 0.10))
    else:
        assumptions.append("kv_cache_on_gpu")

    derived_gpu = (
        breakdown["gpu_model_weights_mb"]
        + (0 if kv_offload else breakdown["kv_cache_mb"])
        + breakdown["runtime_workspace_mb"]
        + breakdown["provider_overhead_mb"]
        + breakdown["fragmentation_allowance_mb"]
    )
    derived_ram = (
        breakdown["host_model_staging_mb"]
        + (breakdown["kv_cache_mb"] if kv_offload else 0)
        + max(256, math.ceil((model_mb or 0) * 0.02))
    )

    steady_vram = int(getattr(resource_profile, "steady_vram_mb", 0) or 0)
    steady_ram = int(getattr(resource_profile, "steady_ram_mb", 0) or 0)
    steady_cpu = float(getattr(resource_profile, "steady_cpu", 0.0) or 0.0)
    cold_vram = int(getattr(resource_profile, "cold_start_vram_mb", 0) or 0)
    cold_ram = int(getattr(resource_profile, "cold_start_ram_mb", 0) or 0)
    cold_cpu = float(getattr(resource_profile, "cold_start_cpu", 0.0) or 0.0)
    request_vram = int(getattr(resource_profile, "per_request_vram_mb", 0) or 0)
    request_ram = int(getattr(resource_profile, "per_request_ram_mb", 0) or 0)
    request_cpu = float(getattr(resource_profile, "per_request_cpu", 0.0) or 0.0)

    if steady_vram == 0:
        steady_vram = derived_gpu
    if steady_ram == 0:
        steady_ram = derived_ram
    if cold_ram == 0 and not runtime_warm:
        cold_ram = max(0, breakdown["host_model_staging_mb"])
    if cold_vram == 0 and not runtime_warm:
        # Workspace and allocation fragmentation occur during cold start too.
        cold_vram = max(0, math.ceil(derived_gpu * 0.10))

    return {
        "startup_transient": {
            "cpu": cold_cpu,
            "ram_mb": cold_ram,
            "vram_mb": cold_vram,
        }
        if not runtime_warm
        else {},
        "runtime_resident": {
            "cpu": steady_cpu,
            "ram_mb": steady_ram,
            "vram_mb": steady_vram,
        },
        "request_active": {
            "cpu": request_cpu,
            "ram_mb": request_ram,
            "vram_mb": request_vram,
        },
        "concurrency_limit": concurrency,
        "estimate_confidence": "ESTIMATED" if model_mb is not None else "DECLARED",
        "estimate_breakdown": breakdown,
        "estimate_assumptions": assumptions,
        "context_length": context,
        "batch_size": batch,
        "kv_offload": kv_offload,
    }
