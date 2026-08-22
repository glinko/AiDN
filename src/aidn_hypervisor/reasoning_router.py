"""Deterministic provider selection for the Resident Node Steward.

The router is deliberately a policy/read-model boundary.  It never calls a
model, opens a network connection, or reserves resources.  A caller supplies
provider metadata and (optionally) the Resource Broker's admission callback;
the router returns an explainable, fail-closed decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from threading import RLock
from typing import Any, Callable, Iterable, Mapping


PROVIDER_KINDS = {
    "LOCAL_RESIDENT",
    "LOCAL_MODEL",
    "AIDN_ENDPOINT",
    "EXTERNAL_API",
}
DATA_CLASSES = {"PUBLIC", "OPERATOR", "SENSITIVE", "FINANCIAL", "SECURITY", "SECRET"}
COMPLEXITIES = {"SIMPLE", "MEDIUM", "COMPLEX", "RESEARCH"}
MAX_PROVIDERS = 128
MAX_CAPABILITIES = 32
MAX_DATA_CLASSES = len(DATA_CLASSES)
MAX_METADATA = 16
MAX_TEXT = 256
MAX_CANDIDATES = 128


def _bounded_text(value: Any, *, name: str, limit: int = MAX_TEXT) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    if len(text) > limit:
        raise ValueError(f"{name} must be at most {limit} characters")
    return text


def _bounded_optional_text(value: Any, *, name: str, limit: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > limit:
        raise ValueError(f"{name} must be at most {limit} characters")
    return text


def _non_negative_int(value: Any, *, name: str, maximum: int = 2**63 - 1) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer") from error
    if number < 0 or number > maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}")
    return number


def _non_negative_float(value: Any, *, name: str, maximum: float = 1_000_000.0) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a number") from error
    if number < 0 or number > maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}")
    return number


def _normalise_tokens(values: Iterable[Any], *, name: str, limit: int) -> tuple[str, ...]:
    result: list[str] = []
    for raw in list(values)[:limit]:
        value = _bounded_text(raw, name=name, limit=MAX_TEXT).casefold()
        if value not in result:
            result.append(value)
    return tuple(sorted(result))


def _safe_metadata(value: Any) -> dict[str, str | int | float | bool]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("metadata must be an object")
    result: dict[str, str | int | float | bool] = {}
    forbidden = {"token", "secret", "password", "private_key", "api_key", "credential"}
    for raw_key, raw_value in list(value.items())[:MAX_METADATA]:
        key = _bounded_text(raw_key, name="metadata key", limit=64).casefold()
        if any(part in key for part in forbidden):
            raise ValueError("metadata must not contain credentials or secret material")
        if isinstance(raw_value, (str, int, float, bool)) and not isinstance(raw_value, bytes):
            if isinstance(raw_value, str):
                result[key] = _bounded_text(raw_value, name=f"metadata.{key}", limit=MAX_TEXT)
            else:
                result[key] = raw_value
        else:
            raise ValueError("metadata values must be scalar and non-secret")
    return result


@dataclass(frozen=True)
class ReasoningProvider:
    """Non-secret capability and admission metadata for one reasoning source."""

    provider_id: str
    kind: str
    model_id: str | None = None
    capabilities: tuple[str, ...] = ("general",)
    supported_complexities: tuple[str, ...] = tuple(sorted(COMPLEXITIES))
    context_limit: int = 4096
    allowed_data_classes: tuple[str, ...] = ("PUBLIC", "OPERATOR")
    latency_ms: int = 0
    cost_q_atoms: int = 0
    required_cpu: float = 0.0
    required_ram_mb: int = 0
    required_vram_mb: int = 0
    available: bool = True
    enabled: bool = True
    trusted: bool = True
    priority: int = 0
    max_concurrency: int = 1
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        provider_id = _bounded_text(self.provider_id, name="provider_id")
        kind = _bounded_text(self.kind, name="kind").upper()
        if kind not in PROVIDER_KINDS:
            raise ValueError(f"kind must be one of {sorted(PROVIDER_KINDS)}")
        model_id = _bounded_optional_text(self.model_id, name="model_id")
        capabilities = _normalise_tokens(self.capabilities, name="capability", limit=MAX_CAPABILITIES)
        complexities = tuple(str(item).upper() for item in self.supported_complexities)
        if not complexities or any(item not in COMPLEXITIES for item in complexities):
            raise ValueError(f"supported_complexities must contain only {sorted(COMPLEXITIES)}")
        data_classes = tuple(str(item).upper() for item in self.allowed_data_classes)
        if not data_classes or any(item not in DATA_CLASSES for item in data_classes):
            raise ValueError(f"allowed_data_classes must contain only {sorted(DATA_CLASSES)}")
        if len(data_classes) > MAX_DATA_CLASSES:
            raise ValueError("allowed_data_classes is too large")
        context_limit = _non_negative_int(self.context_limit, name="context_limit", maximum=10_000_000)
        if context_limit < 128:
            raise ValueError("context_limit must be at least 128")
        for name in ("latency_ms", "cost_q_atoms", "required_ram_mb", "required_vram_mb", "max_concurrency"):
            value = _non_negative_int(getattr(self, name), name=name, maximum=10_000_000_000)
            if name == "max_concurrency" and value < 1:
                raise ValueError("max_concurrency must be at least 1")
        _non_negative_float(self.required_cpu, name="required_cpu", maximum=1_000_000.0)
        if not isinstance(self.available, bool) or not isinstance(self.enabled, bool) or not isinstance(self.trusted, bool):
            raise ValueError("available, enabled, and trusted must be booleans")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int) or not -1_000_000 <= self.priority <= 1_000_000:
            raise ValueError("priority must be an integer between -1000000 and 1000000")
        metadata = _safe_metadata(self.metadata)
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "supported_complexities", tuple(sorted(set(complexities))))
        object.__setattr__(self, "allowed_data_classes", tuple(sorted(set(data_classes))))
        object.__setattr__(self, "context_limit", context_limit)
        object.__setattr__(self, "latency_ms", int(self.latency_ms))
        object.__setattr__(self, "cost_q_atoms", int(self.cost_q_atoms))
        object.__setattr__(self, "required_cpu", float(self.required_cpu))
        object.__setattr__(self, "required_ram_mb", int(self.required_ram_mb))
        object.__setattr__(self, "required_vram_mb", int(self.required_vram_mb))
        object.__setattr__(self, "max_concurrency", int(self.max_concurrency))
        object.__setattr__(self, "metadata", metadata)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReasoningProvider":
        if not isinstance(value, Mapping):
            raise ValueError("provider must be an object")
        resources = value.get("required_resources", {})
        resources = resources if isinstance(resources, Mapping) else {}
        return cls(
            provider_id=value.get("provider_id", ""),
            kind=value.get("kind", ""),
            model_id=value.get("model_id"),
            capabilities=tuple(value.get("capabilities", ("general",))),
            supported_complexities=tuple(value.get("supported_complexities", tuple(sorted(COMPLEXITIES)))),
            context_limit=value.get("context_limit", 4096),
            allowed_data_classes=tuple(value.get("allowed_data_classes", ("PUBLIC", "OPERATOR"))),
            latency_ms=value.get("latency_ms", 0),
            cost_q_atoms=value.get("cost_q_atoms", 0),
            required_cpu=value.get("required_cpu", resources.get("cpu", 0.0)),
            required_ram_mb=value.get("required_ram_mb", resources.get("ram_mb", 0)),
            required_vram_mb=value.get("required_vram_mb", resources.get("vram_mb", 0)),
            available=value.get("available", True),
            enabled=value.get("enabled", True),
            trusted=value.get("trusted", True),
            priority=value.get("priority", 0),
            max_concurrency=value.get("max_concurrency", 1),
            metadata=value.get("metadata", {}),
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "kind": self.kind,
            "model_id": self.model_id,
            "capabilities": list(self.capabilities),
            "supported_complexities": list(self.supported_complexities),
            "context_limit": self.context_limit,
            "allowed_data_classes": list(self.allowed_data_classes),
            "latency_ms": self.latency_ms,
            "cost_q_atoms": self.cost_q_atoms,
            "required_resources": {
                "cpu": self.required_cpu,
                "ram_mb": self.required_ram_mb,
                "vram_mb": self.required_vram_mb,
            },
            "available": self.available,
            "enabled": self.enabled,
            "trusted": self.trusted,
            "priority": self.priority,
            "max_concurrency": self.max_concurrency,
            "metadata": dict(self.metadata),
        }


class ReasoningProviderRegistry:
    """Bounded in-memory registry with explicit persistence helpers."""

    SNAPSHOT_VERSION = 1

    def __init__(self, providers: Iterable[ReasoningProvider] | None = None) -> None:
        self._lock = RLock()
        self._providers: dict[str, ReasoningProvider] = {}
        for provider in providers or ():
            self.register(provider)

    def register(self, provider: ReasoningProvider | Mapping[str, Any], *, replace: bool = False) -> ReasoningProvider:
        item = provider if isinstance(provider, ReasoningProvider) else ReasoningProvider.from_mapping(provider)
        with self._lock:
            if item.provider_id in self._providers and not replace:
                raise ValueError(f"reasoning provider already exists: {item.provider_id}")
            if item.provider_id not in self._providers and len(self._providers) >= MAX_PROVIDERS:
                raise ValueError("reasoning provider registry is full")
            self._providers[item.provider_id] = item
            return item

    def remove(self, provider_id: str) -> None:
        key = _bounded_text(provider_id, name="provider_id")
        with self._lock:
            if key not in self._providers:
                raise KeyError(key)
            del self._providers[key]

    def get(self, provider_id: str) -> ReasoningProvider | None:
        with self._lock:
            return self._providers.get(str(provider_id))

    def list(self) -> list[ReasoningProvider]:
        with self._lock:
            return [self._providers[key] for key in sorted(self._providers)]

    def as_payload(self) -> dict[str, Any]:
        items = self.list()
        return {"items": [provider.as_payload() for provider in items], "count": len(items)}

    def snapshot_state(self) -> dict[str, Any]:
        return {
            "schema_version": self.SNAPSHOT_VERSION,
            "providers": [provider.as_payload() for provider in self.list()],
        }

    def restore_state(self, snapshot: Mapping[str, Any] | None) -> None:
        if not isinstance(snapshot, Mapping):
            return
        values = snapshot.get("providers", [])
        if not isinstance(values, list) or len(values) > MAX_PROVIDERS:
            raise ValueError("reasoning provider snapshot is invalid")
        restored = [ReasoningProvider.from_mapping(item) for item in values]
        if len({item.provider_id for item in restored}) != len(restored):
            raise ValueError("reasoning provider snapshot contains duplicate IDs")
        with self._lock:
            self._providers = {item.provider_id: item for item in restored}


@dataclass(frozen=True)
class ReasoningRouteRequest:
    """Bounded routing constraints; no prompt or transcript is accepted."""

    capability: str = "general"
    complexity: str = "SIMPLE"
    data_class: str = "OPERATOR"
    minimum_context: int = 4096
    latency_budget_ms: int | None = None
    max_cost_q_atoms: int | None = None
    budget_remaining_q_atoms: int | None = None
    required_cpu: float = 0.0
    required_ram_mb: int = 0
    required_vram_mb: int = 0
    local_only: bool = False
    allow_external: bool = False
    require_trusted: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability", _bounded_text(self.capability, name="capability").casefold())
        complexity = _bounded_text(self.complexity, name="complexity").upper()
        if complexity not in COMPLEXITIES:
            raise ValueError(f"complexity must be one of {sorted(COMPLEXITIES)}")
        data_class = _bounded_text(self.data_class, name="data_class").upper()
        if data_class not in DATA_CLASSES:
            raise ValueError(f"data_class must be one of {sorted(DATA_CLASSES)}")
        object.__setattr__(self, "complexity", complexity)
        object.__setattr__(self, "data_class", data_class)
        object.__setattr__(self, "minimum_context", _non_negative_int(self.minimum_context, name="minimum_context", maximum=10_000_000))
        for name in ("latency_budget_ms", "max_cost_q_atoms", "budget_remaining_q_atoms"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _non_negative_int(value, name=name, maximum=10_000_000_000))
        object.__setattr__(self, "required_cpu", _non_negative_float(self.required_cpu, name="required_cpu"))
        object.__setattr__(self, "required_ram_mb", _non_negative_int(self.required_ram_mb, name="required_ram_mb", maximum=10_000_000_000))
        object.__setattr__(self, "required_vram_mb", _non_negative_int(self.required_vram_mb, name="required_vram_mb", maximum=10_000_000_000))
        for name in ("local_only", "allow_external", "require_trusted"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReasoningRouteRequest":
        if not isinstance(value, Mapping):
            raise ValueError("route request must be an object")
        return cls(
            capability=value.get("capability", "general"),
            complexity=value.get("complexity", "SIMPLE"),
            data_class=value.get("data_class", "OPERATOR"),
            minimum_context=value.get("minimum_context", 4096),
            latency_budget_ms=value.get("latency_budget_ms"),
            max_cost_q_atoms=value.get("max_cost_q_atoms"),
            budget_remaining_q_atoms=value.get("budget_remaining_q_atoms"),
            required_cpu=value.get("required_cpu", 0.0),
            required_ram_mb=value.get("required_ram_mb", 0),
            required_vram_mb=value.get("required_vram_mb", 0),
            local_only=value.get("local_only", False),
            allow_external=value.get("allow_external", False),
            require_trusted=value.get("require_trusted", True),
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "complexity": self.complexity,
            "data_class": self.data_class,
            "minimum_context": self.minimum_context,
            "latency_budget_ms": self.latency_budget_ms,
            "max_cost_q_atoms": self.max_cost_q_atoms,
            "budget_remaining_q_atoms": self.budget_remaining_q_atoms,
            "required_resources": {
                "cpu": self.required_cpu,
                "ram_mb": self.required_ram_mb,
                "vram_mb": self.required_vram_mb,
            },
            "local_only": self.local_only,
            "allow_external": self.allow_external,
            "require_trusted": self.require_trusted,
        }


class ReasoningRouter:
    """Fail-closed, deterministic ranking over registered providers."""

    def __init__(
        self,
        registry: ReasoningProviderRegistry,
        *,
        resource_admission: Callable[..., Mapping[str, Any]] | None = None,
    ) -> None:
        self.registry = registry
        self._resource_admission = resource_admission

    @staticmethod
    def _is_local(provider: ReasoningProvider) -> bool:
        return provider.kind in {"LOCAL_RESIDENT", "LOCAL_MODEL"}

    @staticmethod
    def _resource_details(provider: ReasoningProvider, request: ReasoningRouteRequest) -> dict[str, Any]:
        return {
            "cpu": request.required_cpu + provider.required_cpu,
            "ram_mb": request.required_ram_mb + provider.required_ram_mb,
            "vram_mb": request.required_vram_mb + provider.required_vram_mb,
        }

    def _check_resource_admission(self, provider: ReasoningProvider, request: ReasoningRouteRequest) -> tuple[bool, dict[str, Any] | None]:
        required = self._resource_details(provider, request)
        if not any(required.values()):
            return True, None
        if self._resource_admission is None:
            return False, {"code": "RESOURCE_ADMISSION_UNAVAILABLE", "required": required}
        try:
            report = self._resource_admission(**required)
        except Exception as error:  # fail closed at the routing boundary
            return False, {"code": "RESOURCE_ADMISSION_UNAVAILABLE", "message": type(error).__name__, "required": required}
        if not isinstance(report, Mapping) or not bool(report.get("allowed")):
            return False, {"code": "RESOURCE_ADMISSION_DENIED", "required": required, "broker": dict(report) if isinstance(report, Mapping) else {}}
        return True, {"code": "RESOURCE_ADMITTED", "required": required, "broker": dict(report)}

    def route(self, request: ReasoningRouteRequest | Mapping[str, Any]) -> dict[str, Any]:
        req = request if isinstance(request, ReasoningRouteRequest) else ReasoningRouteRequest.from_mapping(request)
        accepted: list[tuple[tuple[Any, ...], ReasoningProvider, dict[str, Any]]] = []
        rejected: list[dict[str, Any]] = []
        for provider in self.registry.list():
            reason: dict[str, Any] | None = None
            if not provider.enabled:
                reason = {"code": "PROVIDER_DISABLED"}
            elif not provider.available:
                reason = {"code": "PROVIDER_UNAVAILABLE"}
            elif req.capability not in provider.capabilities and "*" not in provider.capabilities:
                reason = {"code": "CAPABILITY_MISMATCH", "required": req.capability}
            elif req.complexity not in provider.supported_complexities:
                reason = {"code": "COMPLEXITY_UNSUPPORTED", "required": req.complexity}
            elif req.minimum_context > provider.context_limit:
                reason = {"code": "CONTEXT_TOO_SMALL", "required": req.minimum_context, "available": provider.context_limit}
            elif req.data_class not in provider.allowed_data_classes:
                reason = {"code": "PRIVACY_POLICY", "data_class": req.data_class}
            elif req.data_class == "SECRET" and (provider.kind != "LOCAL_RESIDENT" or not provider.trusted):
                reason = {"code": "SECRET_DATA_PROVIDER_BLOCKED"}
            elif req.require_trusted and not provider.trusted:
                reason = {"code": "TRUST_REQUIRED"}
            elif req.local_only and not self._is_local(provider):
                reason = {"code": "NON_LOCAL_PROVIDER_DISABLED"}
            elif provider.kind == "EXTERNAL_API" and not req.allow_external:
                reason = {"code": "EXTERNAL_PROVIDER_DISABLED"}
            elif req.latency_budget_ms is not None and provider.latency_ms > req.latency_budget_ms:
                reason = {"code": "LATENCY_BUDGET", "required": req.latency_budget_ms, "provider": provider.latency_ms}
            elif req.max_cost_q_atoms is not None and provider.cost_q_atoms > req.max_cost_q_atoms:
                reason = {"code": "COST_BUDGET", "limit": req.max_cost_q_atoms, "provider": provider.cost_q_atoms}
            elif req.budget_remaining_q_atoms is not None and provider.cost_q_atoms > req.budget_remaining_q_atoms:
                reason = {"code": "DELEGATED_BUDGET", "remaining": req.budget_remaining_q_atoms, "provider": provider.cost_q_atoms}
            if reason is None:
                admitted, resource_reason = self._check_resource_admission(provider, req)
                if not admitted:
                    reason = resource_reason or {"code": "RESOURCE_ADMISSION_DENIED"}
            if reason is not None:
                rejected.append({"provider_id": provider.provider_id, **reason})
                continue
            local_rank = 0 if self._is_local(provider) else 1
            exact_rank = 0 if req.capability in provider.capabilities else 1
            score = (local_rank, -int(provider.priority), exact_rank, provider.latency_ms, provider.cost_q_atoms, provider.provider_id)
            accepted.append((score, provider, {"resource": self._resource_details(provider, req)}))
        accepted.sort(key=lambda item: item[0])
        candidate_ids = [provider.provider_id for _, provider, _ in accepted[:MAX_CANDIDATES]]
        decision_input = {
            "request": req.as_payload(),
            "candidates": candidate_ids,
            "rejected": rejected,
        }
        decision_id = "route_" + hashlib.sha256(json.dumps(decision_input, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:32]
        if not accepted:
            return {
                "decision_id": decision_id,
                "generated_at": datetime.now(UTC).isoformat(),
                "status": "NO_ELIGIBLE_PROVIDER",
                "selected_provider": None,
                "reason_code": "ROUTE_UNAVAILABLE",
                "explanation": "No registered reasoning provider satisfies capability, privacy, budget, context, and resource constraints.",
                "request": req.as_payload(),
                "candidates": [],
                "rejected": rejected[:MAX_CANDIDATES],
                "execution": {"started": False, "side_effects": False},
            }
        _, selected, selected_details = accepted[0]
        return {
            "decision_id": decision_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "ROUTED",
            "selected_provider": selected.as_payload(),
            "reason_code": "ELIGIBLE_PROVIDER",
            "explanation": "Selected the highest-ranked eligible provider using local-first, priority, latency, cost, and stable-id ordering.",
            "request": req.as_payload(),
            "candidates": [
                {"provider": provider.as_payload(), "rank": index + 1, **details}
                for index, (_score, provider, details) in enumerate(accepted[:MAX_CANDIDATES])
            ],
            "rejected": rejected[:MAX_CANDIDATES],
            "execution": {"started": False, "side_effects": False},
            "selection": selected_details,
        }
