"""Shared validation and persistence contract for the Ubuntu installer wizard.

The shell bootstrap owns the interactive terminal experience, but the data it
collects is deliberately represented by a small, testable Python contract.  A
later Resident Steward or Dashboard flow can resume the same plan without
guessing what the operator already approved.  The plan is advisory: it never
grants permission to install a plugin, download an artifact, publish an
Endpoint, or mutate the node by itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

SETUP_MODES = {"manual", "ai_assisted"}
PROVIDER_CHOICES = {"skip", "ollama", "llama.cpp", "vllm"}
ENDPOINT_ACTIONS = {"skip", "draft", "start"}
HANDOFF_ACTIONS = {"continue", "dashboard"}
PLAN_MAX_BYTES = 128 * 1024

# The assisted workflow keeps resource-sensitive choices explicit in the plan
# instead of allowing an agent to invent launch flags.  Context fallback is
# deterministic: try the requested 128K window, then 64K, then 32K, and stop
# with a user-visible explanation if none fits the Resource Broker forecast.
CONTEXT_LENGTH_CHOICES = (131_072, 65_536, 32_768)
DEFAULT_RUNTIME_POLICY: dict[str, object] = {
    "context_length": {
        "requested": CONTEXT_LENGTH_CHOICES[0],
        "fallbacks": list(CONTEXT_LENGTH_CHOICES[1:]),
        "on_exhausted": "notify",
    },
    "max_tokens": 8192,
    "gpu_layers": "auto",
    "kv_cache": {"type": "auto", "offload": "auto"},
    "max_concurrency": 1,
}
DEFAULT_REPLACEMENT_POLICY: dict[str, object] = {
    "mode": "ask",
    "allow_stop_current": "ask",
}
DEFAULT_PUBLICATION_POLICY: dict[str, object] = {
    "visibility": "ask",
    "pricing": "ask",
    "tariff": None,
    "validation": "ask",
    "external_requests_without_allowlist": "ask",
    "endpoint_name": None,
}
_POLICY_KV_TYPES = {"auto", "f16", "q8_0", "q4_0"}
_POLICY_ASK = "ask"


def _set_owner_only_permissions(fd: int) -> None:
    """Apply POSIX owner-only permissions when the platform supports them.

    The installation target is Ubuntu, where the plan is deliberately written
    as ``0600``.  Windows does not expose ``os.fchmod`` and enforces access
    through ACLs instead; skipping the POSIX mode change there keeps plan
    creation portable without weakening the supported-host guarantee.
    """

    fchmod = getattr(os, "fchmod", None)
    if fchmod is not None:
        fchmod(fd, 0o600)
MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}$")
HF_REVISION_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")


def _clean(value: object) -> str:
    return str(value or "").strip()


def validate_model_id(value: str) -> str:
    """Validate a bounded provider/model identifier without filesystem paths."""

    normalized = _clean(value)
    if normalized.lower() == "skip":
        return "skip"
    if not MODEL_ID_PATTERN.fullmatch(normalized) or ".." in normalized:
        raise ValueError("setup model id must be a bounded provider/model identifier")
    return normalized


def validate_model_source(value: str, *, provider: str) -> str:
    """Accept reviewed HTTPS/HF sources while rejecting embedded credentials."""

    source = _clean(value)
    if not source:
        raise ValueError("setup model source is required when a model is selected")
    if len(source) > 2048 or any(char in source for char in ("?", "#")):
        raise ValueError("setup model source must be a bounded URL without credentials or query data")
    if source.startswith("hf://"):
        parts = [part for part in source[5:].strip("/").split("/") if part]
        if len(parts) < 2:
            raise ValueError("hf:// source must include an owner and repository")
        repository = parts[1]
        if "@" in repository:
            repository_name, revision = repository.rsplit("@", 1)
            if not repository_name or not HF_REVISION_PATTERN.fullmatch(revision):
                raise ValueError("hf:// source revision must be a 40-character hexadecimal commit")
        if any("@" in part for part in [parts[0], *parts[2:]]):
            raise ValueError("hf:// source must not contain credentials or an @ character outside its revision")
        return source
    if "@" in source:
        raise ValueError("setup model source must be a URL without credentials")
    parsed = urlparse(source)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("setup model source must be an HTTPS URL or hf:// reference")
    if parsed.username or parsed.password:
        raise ValueError("setup model source must not contain credentials")
    # Hugging Face is the reviewed default source, while allowing a trusted
    # operator-owned HTTPS mirror keeps the CLI useful on private networks.
    if provider == "llama.cpp" and parsed.path.rstrip("/") == "":
        raise ValueError("llama.cpp setup source must identify a concrete model artifact")
    return source


def _bounded_integer(value: object, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer") from error
    if normalized < minimum or normalized > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return normalized


def normalize_installation_runtime_policy(value: Mapping[str, object] | None) -> dict[str, object]:
    """Normalize the resource-sensitive runtime choices stored in a plan.

    This policy is intentionally separate from the provider's lower-level
    ``runtime_parameter_policy``.  It describes the operator's decision tree
    (including context fallbacks), while the service translates the selected
    values into provider-safe launch parameters only after a resource forecast.
    """

    raw = dict(value or {})
    allowed = {"context_length", "max_tokens", "gpu_layers", "kv_cache", "max_concurrency"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"unsupported installation runtime policy fields: {', '.join(unknown)}")

    context_raw = raw.get("context_length", {})
    if isinstance(context_raw, Mapping):
        requested_raw = context_raw.get("requested", CONTEXT_LENGTH_CHOICES[0])
        fallbacks_raw = context_raw.get("fallbacks", list(CONTEXT_LENGTH_CHOICES[1:]))
        exhausted = str(context_raw.get("on_exhausted", _POLICY_ASK)).strip().lower()
        selected_raw = context_raw.get("selected")
    else:
        requested_raw = context_raw
        fallbacks_raw = list(CONTEXT_LENGTH_CHOICES[1:])
        exhausted = _POLICY_ASK
        selected_raw = None
    requested = _bounded_integer(
        requested_raw,
        name="runtime context_length.requested",
        minimum=32_768,
        maximum=CONTEXT_LENGTH_CHOICES[0],
    )
    if requested not in CONTEXT_LENGTH_CHOICES:
        raise ValueError("runtime context_length.requested must be 131072, 65536, or 32768")
    if not isinstance(fallbacks_raw, Sequence) or isinstance(fallbacks_raw, (str, bytes)):
        raise ValueError("runtime context_length.fallbacks must be an array")
    fallbacks: list[int] = []
    for item in fallbacks_raw:
        candidate = _bounded_integer(
            item,
            name="runtime context_length fallback",
            minimum=32_768,
            maximum=CONTEXT_LENGTH_CHOICES[0],
        )
        if candidate not in CONTEXT_LENGTH_CHOICES:
            raise ValueError("runtime context_length fallbacks must be 131072, 65536, or 32768")
        if candidate < requested and candidate not in fallbacks:
            fallbacks.append(candidate)
    # The policy requested by the operator is always evaluated first.  Keep
    # the canonical descending fallback order even when a UI submits fields in
    # a different order, and fill the standard lower choices when omitted.
    fallbacks = [candidate for candidate in CONTEXT_LENGTH_CHOICES if candidate < requested and candidate in fallbacks]
    if not fallbacks:
        fallbacks = [candidate for candidate in CONTEXT_LENGTH_CHOICES if candidate < requested]
    if exhausted not in {"notify", "ask", "stop"}:
        raise ValueError("runtime context_length.on_exhausted must be notify, ask, or stop")
    selected: int | None = None
    if selected_raw is not None:
        selected = _bounded_integer(
            selected_raw,
            name="runtime context_length.selected",
            minimum=32_768,
            maximum=CONTEXT_LENGTH_CHOICES[0],
        )
        if selected not in [requested, *fallbacks]:
            raise ValueError("runtime context_length.selected must be one of the requested or fallback sizes")
    context_payload: dict[str, object] = {
        "requested": requested,
        "fallbacks": fallbacks,
        "on_exhausted": exhausted,
    }
    if selected is not None:
        context_payload["selected"] = selected

    max_tokens = _bounded_integer(
        raw.get("max_tokens", 8192),
        name="runtime max_tokens",
        minimum=1,
        maximum=32_768,
    )
    gpu_layers_raw = raw.get("gpu_layers", "auto")
    if isinstance(gpu_layers_raw, str) and gpu_layers_raw.strip().lower() == "auto":
        gpu_layers: int | str = "auto"
    else:
        gpu_layers = _bounded_integer(gpu_layers_raw, name="runtime gpu_layers", minimum=0, maximum=999)

    kv_raw = raw.get("kv_cache", {})
    if not isinstance(kv_raw, Mapping):
        raise ValueError("runtime kv_cache must be an object")
    kv_type = str(kv_raw.get("type", "auto")).strip().lower()
    if kv_type not in _POLICY_KV_TYPES:
        raise ValueError("runtime kv_cache.type must be auto, f16, q8_0, or q4_0")
    offload_raw = kv_raw.get("offload", "auto")
    if isinstance(offload_raw, bool):
        kv_offload: bool | str = offload_raw
    else:
        offload = str(offload_raw).strip().lower()
        if offload not in {"auto", "true", "false"}:
            raise ValueError("runtime kv_cache.offload must be auto, true, or false")
        kv_offload = "auto" if offload == "auto" else offload == "true"

    max_concurrency = _bounded_integer(
        raw.get("max_concurrency", 1),
        name="runtime max_concurrency",
        minimum=1,
        maximum=4096,
    )
    return {
        "context_length": context_payload,
        "max_tokens": max_tokens,
        "gpu_layers": gpu_layers,
        "kv_cache": {"type": kv_type, "offload": kv_offload},
        "max_concurrency": max_concurrency,
    }


def _normalize_tri_state(value: object, *, name: str, true_label: str = "allow") -> str:
    if isinstance(value, bool):
        return true_label if value else "deny"
    normalized = str(value).strip().lower()
    if normalized in {"ask", true_label, "deny"}:
        return normalized
    raise ValueError(f"{name} must be ask, {true_label}, or deny")


def normalize_installation_replacement_policy(value: Mapping[str, object] | None) -> dict[str, object]:
    raw = dict(value or {})
    unknown = sorted(set(raw) - {"mode", "allow_stop_current"})
    if unknown:
        raise ValueError(f"unsupported installation replacement policy fields: {', '.join(unknown)}")
    mode = str(raw.get("mode", "ask")).strip().lower()
    if mode not in {"ask", "replace", "parallel", "deny"}:
        raise ValueError("replacement mode must be ask, replace, parallel, or deny")
    return {
        "mode": mode,
        "allow_stop_current": _normalize_tri_state(
            raw.get("allow_stop_current", "ask"),
            name="replacement allow_stop_current",
        ),
    }


def normalize_installation_publication_policy(value: Mapping[str, object] | None) -> dict[str, object]:
    raw = dict(value or {})
    unknown = sorted(
        set(raw)
        - {"visibility", "pricing", "tariff", "validation", "external_requests_without_allowlist", "endpoint_name"}
    )
    if unknown:
        raise ValueError(f"unsupported installation publication policy fields: {', '.join(unknown)}")
    visibility = str(raw.get("visibility", "ask")).strip().lower()
    if visibility not in {"ask", "private", "public"}:
        raise ValueError("publication visibility must be ask, private, or public")
    pricing = str(raw.get("pricing", "ask")).strip().lower()
    if pricing not in {"ask", "free", "paid", "fixed", "metered"}:
        raise ValueError("publication pricing must be ask, free, paid, fixed, or metered")
    tariff_raw = raw.get("tariff")
    tariff: dict[str, object] | None = None
    if tariff_raw is not None:
        if not isinstance(tariff_raw, Mapping):
            raise ValueError("publication tariff must be an object")
        tariff_unknown = sorted(
            set(tariff_raw) - {"kind", "dimension", "unit_price_q_atoms", "unit_divisor", "minimum_charge_q_atoms"}
        )
        if tariff_unknown:
            raise ValueError(f"unsupported publication tariff fields: {', '.join(tariff_unknown)}")
        tariff_kind = str(tariff_raw.get("kind", "metered")).strip().lower()
        if tariff_kind not in {"fixed", "metered"}:
            raise ValueError("publication tariff.kind must be fixed or metered")
        dimension = str(tariff_raw.get("dimension", "request_count")).strip().lower()
        if dimension not in {
            "request_count",
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
        }:
            raise ValueError("publication tariff.dimension is not supported")
        if tariff_kind == "fixed" and dimension != "request_count":
            raise ValueError("fixed publication tariff must use request_count")
        tariff = {
            "kind": tariff_kind,
            "dimension": dimension,
            "unit_price_q_atoms": _bounded_integer(
                tariff_raw.get("unit_price_q_atoms", 0),
                name="publication tariff.unit_price_q_atoms",
                minimum=0,
                maximum=10**12,
            ),
            "unit_divisor": _bounded_integer(
                tariff_raw.get("unit_divisor", 1),
                name="publication tariff.unit_divisor",
                minimum=1,
                maximum=10**9,
            ),
            "minimum_charge_q_atoms": _bounded_integer(
                tariff_raw.get("minimum_charge_q_atoms", 0),
                name="publication tariff.minimum_charge_q_atoms",
                minimum=0,
                maximum=10**12,
            ),
        }
        if pricing in {"fixed", "metered"} and tariff["kind"] != pricing:
            raise ValueError("publication tariff.kind must match the selected pricing mode")
        if pricing == "free" and int(tariff["unit_price_q_atoms"]) > 0:
            raise ValueError("a free endpoint cannot include a positive tariff")
    validation = str(raw.get("validation", "ask")).strip().lower()
    if validation not in {"ask", "required", "disabled"}:
        raise ValueError("publication validation must be ask, required, or disabled")
    endpoint_name_raw = raw.get("endpoint_name")
    endpoint_name = _clean(endpoint_name_raw) or None
    if endpoint_name is not None:
        if len(endpoint_name) > 128 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._:/-]*", endpoint_name):
            raise ValueError("publication endpoint_name must be a bounded display name")
    return {
        "visibility": visibility,
        "pricing": pricing,
        "tariff": tariff,
        "validation": validation,
        "external_requests_without_allowlist": _normalize_tri_state(
            raw.get("external_requests_without_allowlist", "ask"),
            name="publication external_requests_without_allowlist",
            true_label="allow",
        ),
        "endpoint_name": endpoint_name,
    }


def installation_plan_questions(
    *,
    runtime_policy: Mapping[str, object],
    replacement_policy: Mapping[str, object],
    publication_policy: Mapping[str, object],
) -> list[dict[str, object]]:
    """Return the bounded questions an agent must ask before mutating setup."""

    questions: list[dict[str, object]] = []
    context = runtime_policy.get("context_length")
    if isinstance(context, Mapping) and context.get("on_exhausted") == "ask":
        questions.append(
            {
                "id": "context_fallback_exhausted",
                "prompt": "If 128K, 64K, and 32K all fail resource admission, should installation stop and ask for a smaller configuration?",
                "choices": ["ask", "stop"],
                "default": "ask",
            }
        )
    if replacement_policy.get("mode") == "ask" or replacement_policy.get("allow_stop_current") == "ask":
        questions.append(
            {
                "id": "replace_current_runtime",
                "prompt": "May the workflow stop the current runtime if the selected model needs the GPU?",
                "choices": ["allow", "deny"],
                "default": "deny",
            }
        )
    if publication_policy.get("pricing") == "ask":
        questions.append(
            {
                "id": "endpoint_pricing",
                "prompt": "Should the endpoint be free or paid?",
                "choices": ["free", "paid"],
            }
        )
    if publication_policy.get("pricing") in {"paid", "fixed", "metered"} and not publication_policy.get("tariff"):
        questions.append(
            {
                "id": "endpoint_tariff",
                "prompt": "Which Q-ATOM tariff should be applied to the paid endpoint?",
                "choices": ["fixed request price", "metered input/output price"],
                "required_fields": ["kind", "dimension", "unit_price_q_atoms"],
            }
        )
    if publication_policy.get("validation") == "ask":
        questions.append(
            {
                "id": "endpoint_validation",
                "prompt": "Run endpoint validation before it can be published?",
                "choices": ["required", "disabled"],
                "default": "required",
            }
        )
    if publication_policy.get("external_requests_without_allowlist") == "ask":
        questions.append(
            {
                "id": "external_requests_without_allowlist",
                "prompt": "Allow external requests without an allowlist?",
                "choices": ["allow", "deny"],
                "default": "deny",
            }
        )
    if publication_policy.get("visibility") == "ask":
        questions.append(
            {
                "id": "endpoint_visibility",
                "prompt": "Keep the endpoint private or publish it?",
                "choices": ["private", "public"],
                "default": "private",
            }
        )
    return questions


def installation_context_candidates(runtime_policy: Mapping[str, object]) -> list[int]:
    """Return the ordered context sizes a forecast may try."""

    normalized = normalize_installation_runtime_policy(runtime_policy)
    context = normalized["context_length"]
    assert isinstance(context, Mapping)
    return [int(context["requested"]), *[int(item) for item in context["fallbacks"]]]


def provider_runtime_parameter_policy(
    provider: str,
    runtime_policy: Mapping[str, object],
    *,
    context_length: int | None = None,
) -> dict[str, object]:
    """Translate assisted choices into the provider-neutral runtime contract."""

    normalized = normalize_installation_runtime_policy(runtime_policy)
    context = normalized["context_length"]
    assert isinstance(context, Mapping)
    selected_context = context_length or context.get("selected") or context["requested"]
    selected_context = _bounded_integer(
        selected_context,
        name="runtime context_length",
        minimum=32_768,
        maximum=CONTEXT_LENGTH_CHOICES[0],
    )
    result: dict[str, object] = {
        "context_length": selected_context,
        "max_tokens": normalized["max_tokens"],
    }
    provider_key = str(provider).strip().lower()
    if provider_key == "llama.cpp":
        gpu_layers = normalized["gpu_layers"]
        if gpu_layers != "auto":
            result["gpu_layers"] = gpu_layers
        kv_cache = normalized["kv_cache"]
        assert isinstance(kv_cache, Mapping)
        if kv_cache.get("offload") != "auto":
            result["kv_offload"] = kv_cache["offload"]
        if kv_cache.get("type") != "auto":
            result["kv_cache_type_k"] = kv_cache["type"]
            result["kv_cache_type_v"] = kv_cache["type"]
    return result


@dataclass(frozen=True)
class InstallationOnboardingPlan:
    """Serializable, resumable choices collected by the installer."""

    setup_mode: str = "manual"
    provider: str = "skip"
    model_id: str = "skip"
    model_source: str | None = None
    model_expected_sha256: str | None = None
    model_expected_bytes: int | None = None
    endpoint_action: str = "skip"
    handoff: str = "dashboard"
    runtime_policy: Mapping[str, object] = field(default_factory=dict)
    replacement_policy: Mapping[str, object] = field(default_factory=dict)
    publication_policy: Mapping[str, object] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        mode = _clean(self.setup_mode).lower()
        provider = _clean(self.provider).lower()
        endpoint_action = _clean(self.endpoint_action).lower()
        handoff = _clean(self.handoff).lower()
        if mode == "ai":
            mode = "ai_assisted"
        if mode not in SETUP_MODES:
            raise ValueError("setup mode must be manual or ai_assisted")
        if provider not in PROVIDER_CHOICES:
            raise ValueError("setup provider must be skip, ollama, llama.cpp, or vllm")
        if endpoint_action not in ENDPOINT_ACTIONS:
            raise ValueError("setup endpoint action must be skip, draft, or start")
        if handoff not in HANDOFF_ACTIONS:
            raise ValueError("setup handoff must be continue or dashboard")
        model_id = validate_model_id(self.model_id)
        model_source = _clean(self.model_source) or None
        model_expected_sha256 = _clean(self.model_expected_sha256).lower() or None
        if model_expected_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", model_expected_sha256):
            raise ValueError("model expected SHA-256 must be a 64-character hexadecimal digest")
        model_expected_bytes = self.model_expected_bytes
        if model_expected_bytes is not None:
            if isinstance(model_expected_bytes, bool):
                raise ValueError("model expected byte size must be a positive integer")
            try:
                model_expected_bytes = int(model_expected_bytes)
            except (TypeError, ValueError) as error:
                raise ValueError("model expected byte size must be a positive integer") from error
            if model_expected_bytes <= 0:
                raise ValueError("model expected byte size must be a positive integer")
        if (model_expected_sha256 is None) != (model_expected_bytes is None):
            raise ValueError("model expected SHA-256 and byte size must be supplied together")
        if provider == "skip":
            if model_id != "skip" or model_source is not None or model_expected_sha256 is not None:
                raise ValueError("a model cannot be selected without a provider")
            if endpoint_action != "skip":
                raise ValueError("an endpoint action requires a provider and model")
        elif model_id == "skip":
            if (
                model_source is not None
                or model_expected_sha256 is not None
                or endpoint_action != "skip"
            ):
                raise ValueError("a model must be selected before endpoint setup")
        else:
            if model_source is not None:
                model_source = validate_model_source(model_source, provider=provider)
            if model_expected_sha256 is not None and model_source is None:
                raise ValueError("model integrity metadata requires a model source")
            if endpoint_action != "skip" and model_source is None:
                raise ValueError("endpoint setup requires a model source")
        runtime_policy = normalize_installation_runtime_policy(self.runtime_policy)
        replacement_policy = normalize_installation_replacement_policy(self.replacement_policy)
        publication_policy = normalize_installation_publication_policy(self.publication_policy)
        object.__setattr__(self, "setup_mode", mode)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_source", model_source)
        object.__setattr__(self, "model_expected_sha256", model_expected_sha256)
        object.__setattr__(self, "model_expected_bytes", model_expected_bytes)
        object.__setattr__(self, "endpoint_action", endpoint_action)
        object.__setattr__(self, "handoff", handoff)
        object.__setattr__(self, "runtime_policy", runtime_policy)
        object.__setattr__(self, "replacement_policy", replacement_policy)
        object.__setattr__(self, "publication_policy", publication_policy)

    @property
    def ai_assisted(self) -> bool:
        return self.setup_mode == "ai_assisted"

    def to_dict(self, *, plan_path: str | None = None) -> dict[str, object]:
        next_action = "manual_dashboard_setup"
        if self.ai_assisted:
            if self.provider == "skip":
                next_action = "open_dashboard_provider_setup"
            elif self.model_id == "skip":
                next_action = "choose_model_in_dashboard"
            elif self.endpoint_action == "skip":
                next_action = "review_bundle_and_endpoint_in_dashboard"
            elif self.handoff == "dashboard":
                next_action = "review_ai_plan_in_dashboard"
            else:
                next_action = "resident_steward_review"
        model_payload: dict[str, object] = {
            "id": self.model_id,
            "source": self.model_source,
        }
        if self.model_expected_sha256 is not None:
            model_payload.update(
                {
                    "expected_sha256": self.model_expected_sha256,
                    "expected_bytes": self.model_expected_bytes,
                }
            )
        questions = installation_plan_questions(
            runtime_policy=self.runtime_policy,
            replacement_policy=self.replacement_policy,
            publication_policy=self.publication_policy,
        )
        return {
            "schema_version": self.schema_version,
            "created_at": datetime.now(UTC).isoformat(),
            "mode": self.setup_mode,
            "ai_assisted": self.ai_assisted,
            "provider": self.provider,
            "model": model_payload,
            "endpoint": {"requested_action": self.endpoint_action},
            "runtime_policy": dict(self.runtime_policy),
            "replacement_policy": dict(self.replacement_policy),
            "publication_policy": dict(self.publication_policy),
            "questions": questions,
            "handoff": self.handoff,
            "status": "READY_FOR_REVIEW" if self.ai_assisted else "MANUAL",
            "next_action": next_action,
            "plan_path": plan_path,
            "authority": {
                "installs": "explicit_operator_review_required",
                "downloads": "explicit_operator_review_required",
                "publication": "validation_and_operator_policy_required",
                "secrets": "never_in_plan",
            },
        }


def write_installation_plan(path: str | os.PathLike[str], plan: InstallationOnboardingPlan) -> dict[str, object]:
    """Atomically write a mode/plan file with owner-only permissions."""

    destination = Path(path).expanduser()
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = plan.to_dict(plan_path=str(destination))
    payload["plan_hash"] = installation_plan_hash(payload)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        _set_owner_only_permissions(fd)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return payload


def create_installation_plan(
    path: str | os.PathLike[str],
    *,
    provider: str,
    model_id: str,
    model_source: str | None,
    endpoint_action: str = "draft",
    handoff: str = "dashboard",
    model_expected_sha256: str | None = None,
    model_expected_bytes: int | None = None,
    runtime_policy: Mapping[str, object] | None = None,
    replacement_policy: Mapping[str, object] | None = None,
    publication_policy: Mapping[str, object] | None = None,
    expected_plan_hash: str | None = None,
) -> dict[str, object]:
    """Create or revise an AI-assisted plan without executing host actions.

    Revision is allowed only while the plan is still an un-applied review.  A
    caller must provide the current hash for a revision, which lets a chat
    agent safely collect the pricing/validation/runtime answers over several
    turns without overwriting another operator's choices.
    """

    current = read_installation_plan(path)
    preserve_application: dict[str, object] | None = None
    preserve_status: str | None = None
    preserve_next_action: str | None = None
    if current.get("available"):
        if expected_plan_hash is None:
            raise ValueError("an installation plan already exists; provide expected_plan_hash to revise it")
        if str(current.get("plan_hash") or "") != str(expected_plan_hash):
            raise ValueError("installation plan changed; refresh before revising")
        application = current.get("application")
        if isinstance(application, Mapping) and application:
            current_model = current.get("model") if isinstance(current.get("model"), Mapping) else {}
            if (
                str(current.get("provider") or "") != str(provider)
                or str(current_model.get("id") or "") != str(model_id)
                or str(current_model.get("source") or "") != str(model_source or "")
            ):
                raise ValueError("provider and model choices cannot change after the workflow has started")
            current_runtime = application.get("runtime")
            current_runtime = current_runtime if isinstance(current_runtime, Mapping) else {}
            if current_runtime.get("runtime_id"):
                raise ValueError("installation plan has already started a runtime; revise it through the workflow actions")
            preserve_application = dict(application)
            preserve_status = str(current.get("status") or "") or None
            preserve_next_action = str(current.get("next_action") or "") or None
    elif expected_plan_hash is not None:
        raise ValueError("expected_plan_hash was supplied but no installation plan exists")
    plan = InstallationOnboardingPlan(
        setup_mode="ai_assisted",
        provider=provider,
        model_id=model_id,
        model_source=model_source,
        model_expected_sha256=model_expected_sha256,
        model_expected_bytes=model_expected_bytes,
        endpoint_action=endpoint_action,
        handoff=handoff,
        runtime_policy=runtime_policy or {},
        replacement_policy=replacement_policy or {},
        publication_policy=publication_policy or {},
    )
    payload = write_installation_plan(path, plan)
    if preserve_application is not None:
        # Keep completed provider/model/bundle observations while changing only
        # the still-unresolved policy answers.  The update rebinds the hash.
        return update_installation_plan(
            path,
            expected_hash=str(payload["plan_hash"]),
            status=preserve_status or str(payload.get("status") or "READY_FOR_REVIEW"),
            application=preserve_application,
            next_action=preserve_next_action,
        )
    return payload


def installation_plan_hash(payload: dict[str, object]) -> str:
    """Return a stable hash for the operator-approved plan contents.

    ``plan_hash`` itself is excluded so callers can persist the hash beside the
    canonical JSON without creating a self-referential value.
    """

    canonical = dict(payload)
    canonical.pop("plan_hash", None)
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def installation_plan_path(path: str | os.PathLike[str] | None = None) -> Path | None:
    """Resolve the plan path without inventing a plan on an unconfigured node."""

    candidate = path if path is not None else os.getenv("AIDN_INSTALLATION_PLAN_PATH")
    if not candidate:
        return None
    return Path(candidate).expanduser()


def read_installation_plan(
    path: str | os.PathLike[str] | None = None,
    *,
    max_bytes: int = PLAN_MAX_BYTES,
) -> dict[str, object]:
    """Load and validate the persisted plan as a bounded, secret-free projection."""

    resolved = installation_plan_path(path)
    if resolved is None:
        return {
            "available": False,
            "status": "NOT_CONFIGURED",
            "reason": "No installation plan path is configured for this node.",
            "plan_path": None,
        }
    projection: dict[str, object] = {
        "available": False,
        "status": "NOT_CONFIGURED",
        "plan_path": str(resolved),
    }
    try:
        metadata = resolved.stat()
        if os.name != "nt" and metadata.st_mode & 0o077:
            raise ValueError("installation plan permissions must be owner-only")
        size = metadata.st_size
        if size > max_bytes:
            raise ValueError("installation plan exceeds the configured size limit")
        if size <= 0:
            raise ValueError("installation plan is empty")
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError:
        projection.update(
            available=False,
            status="NOT_FOUND",
            reason="The installer has not written an installation plan yet.",
        )
        return projection
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        projection.update(
            available=False,
            status="INVALID",
            reason=f"Installation plan could not be read: {error}",
        )
        return projection
    if not isinstance(payload, dict):
        projection.update(available=False, status="INVALID", reason="Installation plan must be a JSON object.")
        return projection
    try:
        model = payload.get("model") if isinstance(payload.get("model"), dict) else {}
        plan = InstallationOnboardingPlan(
            setup_mode=str(payload.get("mode") or "manual"),
            provider=str(payload.get("provider") or "skip"),
            model_id=str(model.get("id") or "skip"),
            model_source=model.get("source"),
            model_expected_sha256=model.get("expected_sha256"),
            model_expected_bytes=model.get("expected_bytes"),
            endpoint_action=str(
                (payload.get("endpoint") or {}).get("requested_action")
                if isinstance(payload.get("endpoint"), dict)
                else "skip"
            ),
            handoff=str(payload.get("handoff") or "dashboard"),
            runtime_policy=(
                payload.get("runtime_policy")
                if isinstance(payload.get("runtime_policy"), Mapping)
                else {}
            ),
            replacement_policy=(
                payload.get("replacement_policy")
                if isinstance(payload.get("replacement_policy"), Mapping)
                else {}
            ),
            publication_policy=(
                payload.get("publication_policy")
                if isinstance(payload.get("publication_policy"), Mapping)
                else {}
            ),
            schema_version=int(payload.get("schema_version") or 1),
        )
        normalized = plan.to_dict(plan_path=str(resolved))
    except (TypeError, ValueError, AttributeError) as error:
        projection.update(available=False, status="INVALID", reason=f"Installation plan is invalid: {error}")
        return projection

    expected_hash = installation_plan_hash(payload)
    stored_hash = str(payload.get("plan_hash") or "")
    if not stored_hash:
        integrity = "legacy_unhashed"
    elif stored_hash == expected_hash:
        integrity = "verified"
    else:
        integrity = "mismatch"
    persisted_status = str(payload.get("status") or normalized["status"])
    projection = {
        **normalized,
        **{
            "available": True,
            "status": persisted_status,
            "plan_hash": expected_hash,
            "stored_plan_hash": stored_hash or None,
            "integrity": integrity,
            "created_at": payload.get("created_at") or normalized["created_at"],
            "updated_at": payload.get("updated_at"),
            "applied_at": payload.get("applied_at"),
            "application": payload.get("application"),
            "next_action": payload.get("next_action") or normalized["next_action"],
            "plan_path": str(resolved),
        },
    }
    if integrity == "legacy_unhashed":
        projection["status"] = "LEGACY_REVIEW_REQUIRED"
        projection["reason"] = "This plan predates plan-hash binding; regenerate or review it before applying."
    elif integrity == "mismatch":
        projection["status"] = "STALE"
        projection["reason"] = "The persisted plan changed after it was written; regenerate it before applying."
    return projection


def build_installation_workflow_projection(
    plan: Mapping[str, object],
    *,
    provider_instances: Sequence[Mapping[str, object]] = (),
    provider_installation_jobs: Sequence[Mapping[str, object]] = (),
    provider_installation_approvals: Sequence[Mapping[str, object]] = (),
    model_installs: Sequence[Mapping[str, object]] = (),
    bundles: Sequence[Mapping[str, object]] = (),
    endpoints: Sequence[Mapping[str, object]] = (),
    checked_at: str | None = None,
) -> dict[str, object]:
    """Project the resumable installer state from persisted intent and reality.

    The installer plan is deliberately only intent.  This projection joins it
    with the current provider/model/bundle/endpoint read models so a resident
    agent or dashboard can resume after a restart without guessing which step
    actually completed.  It is read-only and never grants an install or
    publication authority.
    """

    timestamp = checked_at or datetime.now(UTC).isoformat()
    if not bool(plan.get("available")):
        return {
            "status": "UNAVAILABLE",
            "checked_at": timestamp,
            "plan_hash": None,
            "stages": [],
            "progress": {"completed": 0, "required": 0, "percent": 0},
            "next_action": {
                "id": "install_plan_unavailable",
                "label": "Run the installer to create a plan",
                "reason": str(plan.get("reason") or "No installation plan is available."),
            },
        }

    plan_status = str(plan.get("status") or "").upper()
    integrity = str(plan.get("integrity") or "").lower()
    if integrity in {"mismatch", "legacy_unhashed"} or plan_status == "STALE":
        return {
            "status": "STALE",
            "checked_at": timestamp,
            "plan_hash": plan.get("plan_hash"),
            "stages": [],
            "progress": {"completed": 0, "required": 0, "percent": 0},
            "next_action": {
                "id": "regenerate_installation_plan",
                "label": "Regenerate the installation plan",
                "reason": str(plan.get("reason") or "The saved plan is no longer trustworthy."),
            },
        }

    def _status(value: object) -> str:
        return str(value or "").strip().upper()

    def _provider_id(item: Mapping[str, object]) -> str:
        return str(item.get("plugin_id") or item.get("provider_type") or item.get("id") or "")

    provider_id = str(plan.get("provider") or "skip")
    application = plan.get("application")
    application = application if isinstance(application, Mapping) else {}
    application_provider = application.get("provider")
    application_provider = (
        application_provider if isinstance(application_provider, Mapping) else {}
    )
    matching_providers = [
        item for item in provider_instances if _provider_id(item) == provider_id
    ]
    provider_runtime_state = _status(
        matching_providers[0].get("status") if matching_providers else None
    )
    provider_application_status = _status(application_provider.get("status"))
    provider_job_error = str(application_provider.get("last_error") or "")
    provider_job_id = str(application_provider.get("job_id") or "")
    reviewed_provider_plan = application_provider.get("installation_plan")
    reviewed_provider_plan = (
        reviewed_provider_plan if isinstance(reviewed_provider_plan, Mapping) else {}
    )
    reviewed_provider_plan_hash = str(reviewed_provider_plan.get("plan_hash") or "")
    approved_provider = next(
        (
            item
            for item in reversed(list(provider_installation_approvals))
            if str(item.get("plugin_id") or "") == provider_id
            and reviewed_provider_plan_hash
            and str(item.get("plan_hash") or "") == reviewed_provider_plan_hash
            and _status(item.get("status")) == "APPROVED"
        ),
        {},
    )
    provider_approval_ready = bool(approved_provider) and not provider_job_id
    provider_job = next(
        (
            item
            for item in reversed(list(provider_installation_jobs))
            if provider_job_id and str(item.get("job_id") or "") == provider_job_id
        ),
        {},
    )
    if provider_job:
        provider_application_status = _status(provider_job.get("status"))
        provider_job_error = str(
            provider_job.get("error_message")
            or provider_job.get("error_code")
            or provider_job_error
        )
    if provider_id == "skip":
        provider_state = "SKIPPED"
    elif matching_providers and provider_runtime_state not in {"FAILED", "DISABLED"}:
        provider_state = "READY"
    elif provider_application_status in {"QUEUED", "RUNNING", "PROCESSING"}:
        provider_state = "IN_PROGRESS"
    elif provider_application_status in {"FAILED", "ERROR", "CANCELLED"}:
        provider_state = "ERROR"
    elif provider_approval_ready:
        provider_state = "IN_PROGRESS"
    elif provider_application_status == "REVIEW_REQUIRED":
        provider_state = "REVIEW_REQUIRED"
    elif matching_providers:
        provider_state = "ERROR"
    else:
        provider_state = "NOT_STARTED"

    model = plan.get("model")
    model = model if isinstance(model, Mapping) else {}
    model_id = str(model.get("id") or "skip")
    matching_installs = [
        item for item in model_installs if str(item.get("model_id") or "") == model_id
    ]
    latest_install = matching_installs[-1] if matching_installs else {}
    install_state = _status(latest_install.get("status"))
    if model_id == "skip":
        model_state = "SKIPPED"
    elif provider_state in {"NOT_STARTED", "REVIEW_REQUIRED", "ERROR"}:
        model_state = "BLOCKED"
    elif install_state in {"COMPLETED", "REGISTERED", "READY", "SUCCEEDED"}:
        model_state = "READY"
    elif install_state in {"QUEUED", "RUNNING", "PROCESSING"}:
        model_state = "IN_PROGRESS"
    elif install_state in {"FAILED", "ERROR"}:
        model_state = "ERROR"
    else:
        model_state = "NOT_STARTED"

    endpoint_plan = plan.get("endpoint")
    endpoint_plan = endpoint_plan if isinstance(endpoint_plan, Mapping) else {}
    endpoint_action = str(endpoint_plan.get("requested_action") or "skip")
    application_endpoint = application.get("endpoint")
    application_endpoint = (
        application_endpoint if isinstance(application_endpoint, Mapping) else {}
    )
    application_forecast = application.get("forecast")
    application_forecast = (
        application_forecast if isinstance(application_forecast, Mapping) else {}
    )
    application_runtime = application.get("runtime")
    application_runtime = (
        application_runtime if isinstance(application_runtime, Mapping) else {}
    )
    application_bundle = application.get("bundle")
    application_bundle = (
        application_bundle if isinstance(application_bundle, Mapping) else {}
    )
    application_bundle_id = str(application_bundle.get("bundle_id") or "")
    matching_bundles = [
        item
        for item in bundles
        if (
            str(item.get("model_id") or "") == model_id
            or str(item.get("bundle_id") or "")
            == application_bundle_id
        )
    ]
    bundle_item = matching_bundles[-1] if matching_bundles else {}
    if endpoint_action == "skip":
        bundle_state = "SKIPPED"
        endpoint_state = "SKIPPED"
    elif model_state != "READY":
        bundle_state = "BLOCKED"
        endpoint_state = "BLOCKED"
    elif bundle_item:
        bundle_state = "READY" if bool(bundle_item.get("enabled", True)) else "WARNING"
        bundle_id = str(bundle_item.get("bundle_id") or "")
        matching_endpoints = [
            item for item in endpoints if str(item.get("bundle_id") or "") == bundle_id
        ]
        endpoint_item = matching_endpoints[-1] if matching_endpoints else {}
        if not endpoint_item and application_endpoint.get("endpoint_id"):
            endpoint_item = application_endpoint
        endpoint_runtime_state = _status(endpoint_item.get("status"))
        endpoint_publication = endpoint_item.get("publication")
        endpoint_publication = (
            endpoint_publication if isinstance(endpoint_publication, Mapping) else {}
        )
        publication_state = _status(endpoint_publication.get("visibility"))
        runtime_readiness = application_runtime.get("readiness")
        runtime_readiness = (
            runtime_readiness if isinstance(runtime_readiness, Mapping) else {}
        )
        runtime_readiness_status = _status(runtime_readiness.get("status"))
        runtime_status = _status(application_runtime.get("status"))
        if runtime_readiness_status == "READY":
            endpoint_state = "READY"
        elif runtime_readiness_status in {"FAILED", "ERROR"} or runtime_status in {"FAILED", "ERROR"}:
            endpoint_state = "ERROR"
        elif application_runtime.get("runtime_id"):
            endpoint_state = "IN_PROGRESS"
        elif not endpoint_item or endpoint_item is application_endpoint or (
            endpoint_item.get("status") == "CREATED"
            and application_endpoint.get("endpoint_id")
        ):
            endpoint_state = "NOT_STARTED"
        elif endpoint_runtime_state in {"ACTIVE"} or publication_state in {"PUBLIC", "SHARED"}:
            endpoint_state = "READY"
        elif endpoint_runtime_state in {"DELETED", "SUSPENDED"}:
            endpoint_state = "WARNING"
        else:
            endpoint_state = "IN_PROGRESS"
    else:
        bundle_state = "NOT_STARTED"
        endpoint_state = "BLOCKED"

    stage_specs = (
        ("provider", "Provider", provider_state, provider_id != "skip"),
        ("model", "Model", model_state, model_id != "skip"),
        ("bundle", "Bundle", bundle_state, endpoint_action != "skip"),
        ("endpoint", "Endpoint", endpoint_state, endpoint_action != "skip"),
    )
    stages = [
        {"id": stage_id, "label": label, "state": state, "required": required}
        for stage_id, label, state, required in stage_specs
    ]
    required_stages = [stage for stage in stages if stage["required"]]
    completed = sum(1 for stage in required_stages if stage["state"] in {"READY", "SKIPPED"})
    required = len(required_stages)

    context_exhausted = str(application_runtime.get("status") or "").upper() == "CONTEXT_RESOURCE_EXHAUSTED"
    replacement_confirmation = str(application_runtime.get("status") or "").upper() == "REPLACEMENT_CONFIRMATION_REQUIRED"
    if context_exhausted:
        action_id = "ask_for_smaller_runtime_configuration"
        action_label = "Choose a smaller runtime configuration"
        reason = str(
            application_runtime.get("message")
            or "None of the configured context sizes fit current allocatable resources."
        )
    elif replacement_confirmation:
        action_id = "ask_replace_current_runtime"
        action_label = "Confirm replacing the current runtime"
        reason = str(
            application_runtime.get("message")
            or "A current runtime is active; the workflow will not stop it without an explicit operator answer."
        )
    elif plan_status in {"READY_FOR_REVIEW", "PLAN_READY"} and not application:
        action_id = "prepare_assisted_installation_review"
        action_label = "Prepare the assisted installation review"
        reason = "The saved choices are ready, but no provider review has been prepared."
    elif provider_state == "REVIEW_REQUIRED":
        action_id = "approve_provider_installation"
        action_label = "Review and approve the provider installation"
        reason = "Provider permissions and installation effects require explicit operator approval."
    elif provider_state == "IN_PROGRESS":
        if provider_approval_ready:
            action_id = "apply_provider_installation"
            action_label = "Install the approved provider runtime"
            reason = "An exact reviewed provider approval is ready; submit it to the privileged broker."
        else:
            action_id = "wait_provider_installation"
            action_label = "Wait for provider installation"
            reason = "The reviewed provider runtime is being installed through the privileged broker."
    elif provider_state == "ERROR":
        action_id = "inspect_provider_installation"
        action_label = "Inspect the failed provider installation"
        reason = provider_job_error or "The provider installation failed; inspect the broker job before retrying."
    elif provider_state == "NOT_STARTED" and provider_id != "skip":
        action_id = "configure_provider"
        action_label = "Configure the selected provider"
        reason = "The selected provider is not attached to this node yet."
    elif model_state == "NOT_STARTED":
        action_id = "request_model_install"
        action_label = "Request the selected model"
        reason = "The provider is ready; model download still requires an explicit request."
    elif model_state == "IN_PROGRESS":
        if install_state == "QUEUED":
            action_id = "process_model_install"
            action_label = "Download and verify the selected model"
            reason = "The model is queued; start the explicit materialization step to download and verify it."
        else:
            action_id = "wait_model_install"
            action_label = "Wait for model installation"
            reason = "The model install is currently running."
    elif model_state == "ERROR":
        action_id = "inspect_model_install"
        action_label = "Inspect the failed model installation"
        reason = str(latest_install.get("last_error") or "The model installation failed.")
    elif bundle_state == "NOT_STARTED":
        action_id = "create_bundle"
        action_label = "Create a Bundle from the installed model"
        reason = "The model is ready; create a reproducible runtime Bundle next."
    elif endpoint_action != "skip" and application_endpoint.get("endpoint_id") and not application_runtime.get("runtime_id"):
        forecast_decision = str(application_forecast.get("decision") or "").upper()
        if forecast_decision == "ADMIT":
            action_id = "start_private_endpoint"
            action_label = "Start the private Endpoint"
            reason = "The Resource Broker forecast admits this Bundle; start it and verify readiness."
        elif forecast_decision == "RESOURCE_WAIT":
            action_id = "forecast_private_endpoint"
            action_label = "Recheck resource availability"
            reason = "The Bundle does not fit current allocatable resources yet; no process was started."
        else:
            action_id = "forecast_private_endpoint"
            action_label = "Forecast private Endpoint resources"
            reason = "Check Resource Broker capacity before activating the private Endpoint."
    elif endpoint_state in {"NOT_STARTED", "BLOCKED"}:
        action_id = "create_private_endpoint"
        action_label = "Create a private Endpoint"
        reason = "Keep publication separate; first validate a local/private Endpoint."
    elif endpoint_state in {"IN_PROGRESS", "ERROR"}:
        action_id = "verify_endpoint_readiness"
        action_label = "Verify Endpoint readiness"
        reason = "The Endpoint runtime needs a fresh readiness probe before it can be treated as healthy."
    else:
        action_id = "continue_in_dashboard"
        action_label = "Continue in the dashboard"
        reason = "The assisted installation path has reached its current safe handoff."

    workflow_status = "READY" if required and completed == required else "IN_PROGRESS"
    if required == 0:
        workflow_status = "READY_FOR_DASHBOARD"
    completion = None
    if endpoint_state == "READY" and application_endpoint.get("endpoint_id"):
        readiness = application_runtime.get("readiness")
        readiness = readiness if isinstance(readiness, Mapping) else {}
        completion = {
            "state": "READY",
            "handoff": str(plan.get("handoff") or "dashboard"),
            "summary": "Private Endpoint is healthy and ready for operator validation/publication review.",
            "provider_id": provider_id,
            "model_id": model_id,
            "bundle_id": application_bundle_id or None,
            "endpoint_id": str(application_endpoint.get("endpoint_id") or "") or None,
            "runtime_id": str(application_runtime.get("runtime_id") or "") or None,
            "readiness": dict(readiness),
            "publication": "NOT_PUBLISHED",
            "next_operator_step": "validate_and_publish_when_policy_allows",
        }
    return {
        "status": workflow_status,
        "checked_at": timestamp,
        "plan_hash": plan.get("plan_hash"),
        "stages": stages,
        "progress": {
            "completed": completed,
            "required": required,
            "percent": round(completed / required * 100) if required else 100,
        },
        "provider_installation": (
            {
                "job_id": provider_job.get("job_id") or provider_job_id or None,
                "status": provider_application_status or None,
                "last_error": provider_job_error or None,
            }
            if provider_job_id or provider_job
            else None
        ),
        "runtime_policy": plan.get("runtime_policy"),
        "questions": list(plan.get("questions") or []) if isinstance(plan.get("questions"), list) else [],
        "forecast": dict(application_forecast) if application_forecast else None,
        "completion": completion,
        "next_action": {"id": action_id, "label": action_label, "reason": reason},
    }


def update_installation_plan(
    path: str | os.PathLike[str] | None,
    *,
    expected_hash: str,
    status: str,
    application: dict[str, object] | None = None,
    next_action: str | None = None,
) -> dict[str, object]:
    """Atomically update only review metadata and re-bind the plan hash."""

    resolved = installation_plan_path(path)
    if resolved is None:
        raise ValueError("installation plan path is not configured")
    current = read_installation_plan(resolved)
    if not current.get("available"):
        raise ValueError(str(current.get("reason") or "installation plan is unavailable"))
    if current.get("integrity") != "verified":
        raise ValueError(str(current.get("reason") or "installation plan integrity is not verified"))
    if str(current.get("plan_hash")) != str(expected_hash):
        raise ValueError("installation plan changed; refresh before applying")
    raw = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("installation plan must be a JSON object")
    raw["status"] = status
    raw["updated_at"] = datetime.now(UTC).isoformat()
    if application is not None:
        raw["application"] = application
    if next_action is not None:
        raw["next_action"] = next_action
    raw.pop("plan_hash", None)
    raw["plan_hash"] = installation_plan_hash(raw)
    destination = Path(resolved)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        _set_owner_only_permissions(fd)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(raw, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return read_installation_plan(destination)


def prepare_assisted_installation_review(
    path: str | os.PathLike[str] | None,
    *,
    expected_hash: str,
    actor: str,
    idempotency_key: str | None = None,
    provider_plan_builder,
) -> dict[str, object]:
    """Advance one assistant-created plan to an explicit provider review.

    This is intentionally *not* a shortcut around the Provider lifecycle:
    it materializes the reviewed provider installation plan and records the
    model/Endpoint work still waiting behind it.  The operator must still use
    the existing plan/approval/apply flow for the provider and the normal
    model/Bundle/Endpoint lifecycle thereafter.
    """

    current = read_installation_plan(path)
    if not current.get("available"):
        raise ValueError(str(current.get("reason") or "installation plan is unavailable"))
    if current.get("integrity") != "verified":
        raise ValueError(str(current.get("reason") or "installation plan integrity is not verified"))
    if current.get("mode") != "ai_assisted":
        raise ValueError("only an AI-assisted installation plan can be prepared")
    if str(current.get("plan_hash")) != str(expected_hash):
        raise ValueError("installation plan changed; refresh before applying")

    existing = current.get("application")
    if (
        idempotency_key
        and isinstance(existing, dict)
        and existing.get("idempotency_key") == idempotency_key
    ):
        current["operation_id"] = existing.get("operation_id")
        current["review"] = existing
        return current

    provider = str(current.get("provider") or "skip")
    model = current.get("model") if isinstance(current.get("model"), dict) else {}
    endpoint = current.get("endpoint") if isinstance(current.get("endpoint"), dict) else {}
    operation_id = f"install-review-{uuid4().hex}"
    application: dict[str, object] = {
        "operation_id": operation_id,
        "actor": str(actor or "operator"),
        "idempotency_key": idempotency_key,
        "prepared_at": datetime.now(UTC).isoformat(),
        "provider": {"status": "SKIPPED"},
        "model": {
            "id": model.get("id", "skip"),
            "source": model.get("source"),
            "status": "NOT_REQUESTED" if model.get("id", "skip") == "skip" else "PENDING_PROVIDER",
        },
        "endpoint": {
            "requested_action": endpoint.get("requested_action", "skip"),
            "status": "NOT_REQUESTED" if endpoint.get("requested_action", "skip") == "skip" else "PENDING_MODEL",
        },
        "authority": {
            "provider_install": "provider_plan_approval_required",
            "model_download": "explicit_model_install_required",
            "endpoint": "bundle_and_endpoint_lifecycle_required",
        },
    }
    if model.get("expected_sha256") is not None:
        application_model = application["model"]
        if isinstance(application_model, dict):
            application_model.update(
                {
                    "expected_sha256": model.get("expected_sha256"),
                    "expected_bytes": model.get("expected_bytes"),
                }
            )

    if provider == "skip":
        status = "COMPLETED"
        next_action = "open_dashboard_provider_setup"
    else:
        provider_plan = dict(provider_plan_builder(provider, {}))
        provider_application: dict[str, object] = {
            "plugin_id": provider,
            "configuration": {},
            "status": "REVIEW_REQUIRED",
            # Only share the reviewed declarative fields. This plan must never
            # turn into a vehicle for secret-bearing provider configuration.
            "installation_plan": {
                key: provider_plan.get(key)
                for key in ("plan_id", "plan_version", "summary", "required_permissions", "health_checks")
            },
        }
        provider_application_plan = provider_application["installation_plan"]
        if isinstance(provider_application_plan, dict):
            provider_application_plan["plan_hash"] = installation_plan_hash(provider_plan)
        application["provider"] = provider_application
        status = "PROVIDER_REVIEW_REQUIRED"
        next_action = "approve_provider_installation"

    updated = update_installation_plan(
        path,
        expected_hash=expected_hash,
        status=status,
        application=application,
        next_action=next_action,
    )
    updated["operation_id"] = operation_id
    updated["review"] = application
    return updated


__all__ = [
    "ENDPOINT_ACTIONS",
    "HANDOFF_ACTIONS",
    "InstallationOnboardingPlan",
    "CONTEXT_LENGTH_CHOICES",
    "DEFAULT_PUBLICATION_POLICY",
    "DEFAULT_REPLACEMENT_POLICY",
    "DEFAULT_RUNTIME_POLICY",
    "PLAN_MAX_BYTES",
    "PROVIDER_CHOICES",
    "SETUP_MODES",
    "validate_model_id",
    "validate_model_source",
    "normalize_installation_runtime_policy",
    "normalize_installation_replacement_policy",
    "normalize_installation_publication_policy",
    "installation_plan_questions",
    "installation_context_candidates",
    "provider_runtime_parameter_policy",
    "installation_plan_hash",
    "installation_plan_path",
    "read_installation_plan",
    "build_installation_workflow_projection",
    "prepare_assisted_installation_review",
    "create_installation_plan",
    "update_installation_plan",
    "write_installation_plan",
]
