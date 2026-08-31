"""Bounded local control agent for the AiDN Hypervisor.

This service owns Steward state, bounded event context and a reviewed action
guard.  It deliberately does not execute arbitrary model output or shell
commands; the Hypervisor service remains the mutation authority.
"""
from __future__ import annotations

import os
import time
from collections import deque
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

DEFAULT_MODEL_REPO = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
DEFAULT_MODEL_FILE = "qwen2.5-0.5b-instruct-q4_k_m.gguf"
DEFAULT_QUANTIZATION = "Q4_K_M"
DEFAULT_LICENSE = "apache-2.0"
DEFAULT_PROFILE = "CPU_RESIDENT"
DEFAULT_RAM_BUDGET_MB = 1024
MAX_AUTOMATION_DEPTH = 0
MAX_RECENT_EVENTS = 32
MAX_CONTEXT_CHARS = 512

ACTION_DEFINITIONS: dict[str, dict[str, Any]] = {
    "provider.health_check": {
        "label": "Check provider health", "target_type": "provider",
        "class": "READ_ONLY", "default": "AUTO", "mutating": False,
    },
    "runtime.drain": {
        "label": "Drain runtime", "target_type": "runtime",
        "class": "DISRUPTIVE", "default": "OPERATOR_CONFIRMATION", "mutating": True,
    },
    "runtime.restart": {
        "label": "Restart runtime", "target_type": "runtime",
        "class": "DISRUPTIVE", "default": "OPERATOR_CONFIRMATION", "mutating": True,
    },
    "runtime.stop": {
        "label": "Stop runtime", "target_type": "runtime",
        "class": "DESTRUCTIVE", "default": "OPERATOR_CONFIRMATION", "mutating": True,
    },
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_epoch(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _short(value: Any, limit: int = MAX_CONTEXT_CHARS) -> Any:
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, dict):
        return {str(key): _short(item, limit) for key, item in list(value.items())[:64]}
    if isinstance(value, (list, tuple)):
        return [_short(item, limit) for item in list(value)[:64]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)[:limit]


def _safe_event(event: Any) -> dict[str, Any]:
    return {
        "event_id": str(getattr(event, "event_id", "")),
        "event_type": str(getattr(event, "event_type", "")),
        "sequence": int(getattr(event, "sequence", 0) or 0),
        "timestamp": str(getattr(event, "timestamp", "")),
        "severity": str(getattr(event, "severity", "INFO")),
        "correlation_id": getattr(event, "correlation_id", None),
        "causation_id": getattr(event, "causation_id", None),
        "resource_type": getattr(event, "resource_type", None),
        "resource_id": getattr(event, "resource_id", None),
        "payload": _short(getattr(event, "payload", {})),
    }


class ResidentAgentService:
    SNAPSHOT_VERSION = 2

    def __init__(
        self, *, node_id: str, enabled: bool = True, model_path: str | None = None,
        model_repo: str = DEFAULT_MODEL_REPO, model_file: str = DEFAULT_MODEL_FILE,
        quantization: str = DEFAULT_QUANTIZATION, license_id: str = DEFAULT_LICENSE,
        execution_profile: str = DEFAULT_PROFILE, ram_budget_mb: int = DEFAULT_RAM_BUDGET_MB,
        on_change: Callable[[], None] | None = None,
        context_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._lock = RLock()
        self.node_id = str(node_id or "node-local")
        self._enabled = bool(enabled)
        self._on_change = on_change
        self._context_provider = context_provider
        self._event_bus = None
        self._event_subscription_id: str | None = None
        self._inference_adapter = None
        self._recent_events: deque[dict[str, Any]] = deque(maxlen=MAX_RECENT_EVENTS)
        self._seen_event_ids: deque[str] = deque(maxlen=256)
        self._cooldowns: dict[tuple[str, str], dict[str, Any]] = {}
        self._action_history: deque[dict[str, Any]] = deque(maxlen=256)
        self._model_path = str(model_path or "")
        self._model_repo = str(model_repo or DEFAULT_MODEL_REPO)
        self._model_file = str(model_file or DEFAULT_MODEL_FILE)
        self._quantization = str(quantization or DEFAULT_QUANTIZATION)
        self._license = str(license_id or DEFAULT_LICENSE)
        self._profile = str(execution_profile or DEFAULT_PROFILE).upper()
        self._ram_budget_mb = max(128, int(ram_budget_mb))
        self._last_action: str | None = None
        self._last_heartbeat: str | None = None
        self._restart_count = 0
        self._last_restart_at: str | None = None
        self._action_policy: dict[str, Any] = {
            "version": 2,
            "auto_actions": ["provider.health_check"],
            "approval_actions": ["runtime.drain", "runtime.restart", "runtime.stop"],
            "max_actions_per_hour": 12,
            # Explicitly operator-enabled lab switch.  It is intentionally
            # persisted with the node state rather than inferred from a prompt
            # or model output, so its status is always visible in the Dashboard.
            "test_unrestricted": False,
        }

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def _changed(self, *, persist: bool = True) -> None:
        if persist and callable(self._on_change):
            try:
                self._on_change()
            except Exception:
                pass

    def bind_event_bus(self, event_bus) -> str | None:
        with self._lock:
            if self._event_bus is event_bus and self._event_subscription_id:
                return self._event_subscription_id
            old_bus, old_id = self._event_bus, self._event_subscription_id
            self._event_bus, self._event_subscription_id = event_bus, None
        if old_bus is not None and old_id:
            try:
                old_bus.unsubscribe(old_id)
            except Exception:
                pass
        if event_bus is None:
            return None
        identifier = event_bus.subscribe(self._on_event, subscription_id=f"resident-agent:{self.node_id}")
        with self._lock:
            self._event_subscription_id = identifier
        return identifier

    def bind_inference_adapter(self, adapter) -> None:
        with self._lock:
            self._inference_adapter = adapter

    def configure_model(self, *, model_path: str, model_repo: str | None = None, persist: bool = True, **kwargs) -> dict[str, Any]:
        with self._lock:
            self._model_path = str(model_path or "")
            if model_repo:
                self._model_repo = str(model_repo)
            for source, target in (("model_file", "_model_file"), ("quantization", "_quantization"), ("license_id", "_license"), ("execution_profile", "_profile")):
                if source in kwargs and kwargs[source] is not None:
                    setattr(self, target, str(kwargs[source]))
            if kwargs.get("ram_budget_mb") is not None:
                self._ram_budget_mb = max(128, int(kwargs["ram_budget_mb"]))
            result = self._model_payload_unlocked()
        if persist:
            self._changed()
        return result

    def set_enabled(self, enabled: bool, *, persist: bool = True) -> dict[str, Any]:
        with self._lock:
            self._enabled = bool(enabled)
            if not self._enabled:
                self._last_action = "disabled"
        self._changed(persist=persist)
        return self.status()

    def _on_event(self, event) -> None:
        event_id = str(getattr(event, "event_id", ""))
        if not event_id:
            return
        with self._lock:
            if event_id in self._seen_event_ids:
                return
            self._seen_event_ids.append(event_id)
            self._recent_events.append(_safe_event(event))
        self._changed()

    def _model_payload_unlocked(self) -> dict[str, Any]:
        path = Path(os.path.expanduser(self._model_path)) if self._model_path else None
        return {"repo": self._model_repo, "file": self._model_file, "quantization": self._quantization, "license": self._license, "path": self._model_path or None, "path_exists": bool(path and path.is_file())}

    def _lineage(self, *, event_id=None, event_type=None, correlation_id=None, causation_id=None) -> dict[str, Any]:
        with self._lock:
            match = next((item for item in reversed(self._recent_events) if event_id and item.get("event_id") == event_id), None)
        return {"event_id": event_id, "event_type": event_type, "correlation_id": correlation_id or (match or {}).get("correlation_id"), "causation_id": causation_id or (match or {}).get("causation_id") or event_id}

    def context_snapshot(self) -> dict[str, Any]:
        with self._lock:
            recent = deepcopy(list(self._recent_events))[-16:]
            base = {"node_id": self.node_id, "steward": {"enabled": self._enabled, "profile": self._profile}}
        supplied: dict[str, Any] = {}
        if callable(self._context_provider):
            try:
                supplied = dict(self._context_provider() or {})
            except Exception as error:
                supplied = {"context_error": str(error)[:MAX_CONTEXT_CHARS]}
        omitted = bool(isinstance(supplied.get("transcript"), str) and len(supplied["transcript"]) > MAX_CONTEXT_CHARS)
        state = _short(supplied)
        if omitted:
            state["_truncated_fields"] = ["transcript"]
        return {"state": state, "recent_events": recent, "omitted": omitted, **base}

    def status(self) -> dict[str, Any]:
        with self._lock:
            enabled = self._enabled
            adapter = self._inference_adapter
            active = sum(1 for value in self._cooldowns.values() if float(value.get("expires_at", 0)) > time.time())
            model, profile, ram = self._model_payload_unlocked(), self._profile, self._ram_budget_mb
            recent, last_action, heartbeat = list(self._recent_events), self._last_action, self._last_heartbeat
            last_restart, restart_count = self._last_restart_at, self._restart_count
            policy = deepcopy(self._action_policy)
        adapter_status: dict[str, Any] = {}
        if adapter is not None:
            try:
                adapter_status = adapter.status() or {}
            except Exception:
                adapter_status = {}
        state = "DISABLED" if not enabled else ("DEGRADED" if last_action and str(last_action).startswith("observe") else "CONFIGURED")
        if adapter_status.get("state") in {"RUNNING", "READY_TO_START"} and state == "CONFIGURED":
            state = "READY"
        return {
            "node_id": self.node_id, "enabled": enabled, "state": state,
            "health": "NOT_RUNNING" if not enabled else "READY", "model": model,
            "execution": {"profile": profile, "ram_budget_mb": ram, "vram_mb": 0 if profile in {"CPU_RESIDENT", "IGPU_RESIDENT"} else None, "inference_adapter": str(adapter_status.get("state", "not_started" if adapter is None else "not_configured")).lower(), "resource_lease": adapter_status.get("lease_id") or "not_requested"},
            "event_ingestion": {"events_seen": len(recent), "last_event_sequence": recent[-1].get("sequence", 0) if recent else 0, "dedup_window": len(self._seen_event_ids)},
            "automation": {"active_cooldowns": active, "last_action": last_action, "policy": policy},
            "restart_recovery": {"restart_count": restart_count, "last_restart_at": last_restart},
            "heartbeat": {"last_at": heartbeat},
        }

    def action_catalog(self) -> list[dict[str, Any]]:
        with self._lock:
            policy = deepcopy(self._action_policy)
        unrestricted = bool(policy.get("test_unrestricted"))
        return [
            {
                "action": name,
                **deepcopy(spec),
                "policy": "AUTO" if unrestricted or name in policy["auto_actions"] else "OPERATOR_CONFIRMATION" if name in policy["approval_actions"] else "DISABLED",
            }
            for name, spec in ACTION_DEFINITIONS.items()
        ]

    def action_policy(self) -> dict[str, Any]:
        with self._lock:
            policy = deepcopy(self._action_policy)
        return {**policy, "catalog": self.action_catalog()}

    def configure_action_policy(self, *, auto_actions=None, approval_actions=None, max_actions_per_hour=None, test_unrestricted=None, persist: bool = True) -> dict[str, Any]:
        auto = list(auto_actions) if auto_actions is not None else None
        approval = list(approval_actions) if approval_actions is not None else None
        for values in (auto, approval):
            if values is not None and any(str(action) not in ACTION_DEFINITIONS for action in values):
                raise ValueError("unknown Steward action")
        if auto is not None and approval is not None and set(auto) & set(approval):
            raise ValueError("an action cannot be both automatic and approval-gated")
        with self._lock:
            if test_unrestricted is not None:
                self._action_policy["test_unrestricted"] = bool(test_unrestricted)
            if auto is not None:
                self._action_policy["auto_actions"] = [str(value) for value in auto]
            if approval is not None:
                self._action_policy["approval_actions"] = [str(value) for value in approval]
            if max_actions_per_hour is not None:
                self._action_policy["max_actions_per_hour"] = max(1, min(10_000, int(max_actions_per_hour)))
        if persist:
            self._changed()
        return self.action_policy()

    def _prune_cooldowns(self) -> None:
        now = time.time()
        with self._lock:
            for key, value in list(self._cooldowns.items()):
                if float(value.get("expires_at", 0)) <= now:
                    self._cooldowns.pop(key, None)

    def guard_action(self, action: str, *, target_id: str | None = None, event_id: str | None = None, event_type: str | None = None, correlation_id: str | None = None, causation_id: str | None = None, automation_depth: int = 0, cooldown_seconds: int | None = None, persist: bool = True) -> dict[str, Any]:
        self._prune_cooldowns()
        name, target = str(action or "").strip(), str(target_id or "").strip()
        lineage = self._lineage(event_id=event_id, event_type=event_type, correlation_id=correlation_id, causation_id=causation_id)
        action_id = f"steward-act-{uuid4().hex}"
        common = {"action": name, "target_id": target, "action_id": action_id, "lineage": lineage, "claim_only": True}
        if name not in ACTION_DEFINITIONS:
            return {"allowed": False, "code": "ACTION_NOT_ALLOWED", "reason": "action is not in the bounded catalog", **common}
        if not target:
            return {"allowed": False, "code": "ACTION_TARGET_REQUIRED", "reason": "target_id is required", **common}
        with self._lock:
            test_unrestricted = bool(self._action_policy.get("test_unrestricted"))
        if not test_unrestricted and int(automation_depth) > MAX_AUTOMATION_DEPTH:
            return {"allowed": False, "code": "AUTOMATION_DEPTH_EXCEEDED", "reason": "autonomous action depth is bounded", "automation_depth": int(automation_depth), **common}
        with self._lock:
            if not self._enabled:
                return {"allowed": False, "code": "STEWARD_DISABLED", "reason": "Resident Steward is disabled", **common}
            if test_unrestricted:
                return {
                    "allowed": True,
                    "code": "TEST_UNRESTRICTED",
                    "reason": "operator enabled unrestricted Steward test mode",
                    "automation_depth": int(automation_depth),
                    **common,
                }
            cutoff = time.time() - 3600
            recent_actions = [
                item for item in self._action_history
                if _parse_epoch(item.get("at")) >= cutoff
            ]
            max_actions = int(self._action_policy.get("max_actions_per_hour", 12) or 12)
            if len(recent_actions) >= max_actions:
                return {
                    "allowed": False,
                    "code": "ACTION_RATE_LIMITED",
                    "reason": "Resident Steward action rate limit is exhausted",
                    "max_actions_per_hour": max_actions,
                    **common,
                }
            key = (name, target)
            existing = self._cooldowns.get(key)
            if existing and float(existing.get("expires_at", 0)) > time.time():
                return {"allowed": False, "code": "ACTION_COOLDOWN_ACTIVE", "reason": "action cooldown is active", "blocked_by_action_id": existing.get("action_id"), **common}
            duration = max(0, min(86_400, int(cooldown_seconds or 0)))
            if duration:
                self._cooldowns[key] = {"action_id": action_id, "expires_at": time.time() + duration}
            result = {"allowed": True, "code": "ACTION_GUARDED", "reason": "bounded action slot reserved", "automation_depth": int(automation_depth), **common}
        if persist:
            self._changed()
        return result

    def record_action_result(self, *, action_id: str, action: str, target_id: str, status: str, error: str | None = None, result: dict[str, Any] | None = None, persist: bool = True) -> dict[str, Any]:
        item = {"action_id": str(action_id), "action": str(action), "target_id": str(target_id), "status": str(status).upper(), "error": error, "result": _short(result or {}), "at": _now()}
        with self._lock:
            self._action_history.append(item)
            self._last_action = f"{item['status'].lower()} {item['action']}"
            if item["status"] == "FAILED":
                for key, value in list(self._cooldowns.items()):
                    if value.get("action_id") == action_id:
                        self._cooldowns.pop(key, None)
        if persist:
            self._changed()
        return item

    def heartbeat(self, *, action: str | None = None, persist: bool = True) -> dict[str, Any]:
        with self._lock:
            self._last_heartbeat = _now()
            if action:
                self._last_action = str(action)[:MAX_CONTEXT_CHARS]
        if persist:
            self._changed()
        return self.status()

    def decide(self, goal: str, *, event_id: str | None = None, event_type: str | None = None, correlation_id: str | None = None, causation_id: str | None = None, automation_depth: int = 0) -> dict[str, Any]:
        text = str(goal or "").strip().lower()
        lineage = self._lineage(event_id=event_id, event_type=event_type, correlation_id=correlation_id, causation_id=causation_id)
        with self._lock:
            test_unrestricted = bool(self._action_policy.get("test_unrestricted"))
        if not test_unrestricted and int(automation_depth) > MAX_AUTOMATION_DEPTH:
            return {"mode": "AUTOMATION_BLOCKED", "requires_approval": True, "lineage": lineage, "authority": {"can_mutate_state": False}}
        if test_unrestricted:
            return {
                "mode": "TEST_UNRESTRICTED",
                "requires_approval": False,
                "lineage": lineage,
                "recommendation": {"tool": "aidn.steward.execute_action", "mutating": True},
                "authority": {"can_mutate_state": True},
            }
        if any(word in text for word in ("install", "publish", "delete", "remove", "restart", "stop", "drain", "activate", "configure", "download")):
            return {
                "mode": "POLICY_CONTROLLED",
                "requires_approval": False,
                "lineage": lineage,
                "recommendation": {"tool": "aidn.steward.execute_action", "mutating": True},
                "authority": {"can_mutate_state": True},
            }
        tool = "aidn.provider.list" if any(word in text for word in ("provider", "unhealthy", "health")) else "aidn.node.status"
        return {"mode": "LOCAL_READ_ONLY", "requires_approval": False, "lineage": lineage, "recommendation": {"tool": tool, "mutating": False}, "authority": {"can_mutate_state": False}}

    def snapshot_state(self) -> dict[str, Any]:
        with self._lock:
            cooldowns = {"\u0000".join(key): value for key, value in self._cooldowns.items()}
            return {"version": self.SNAPSHOT_VERSION, "node_id": self.node_id, "enabled": self._enabled, "model_path": self._model_path, "model_repo": self._model_repo, "model_file": self._model_file, "quantization": self._quantization, "license": self._license, "execution_profile": self._profile, "ram_budget_mb": self._ram_budget_mb, "recent_events": list(self._recent_events), "seen_event_ids": list(self._seen_event_ids), "cooldowns": cooldowns, "action_history": list(self._action_history), "action_policy": deepcopy(self._action_policy), "last_action": self._last_action, "last_heartbeat": self._last_heartbeat}

    def restore_state(self, snapshot: dict[str, Any] | None) -> None:
        data = dict(snapshot or {})
        with self._lock:
            self._enabled = bool(data.get("enabled", self._enabled))
            self._model_path = str(data.get("model_path") or self._model_path)
            self._model_repo = str(data.get("model_repo") or self._model_repo)
            self._model_file = str(data.get("model_file") or self._model_file)
            self._quantization = str(data.get("quantization") or self._quantization)
            self._license = str(data.get("license") or self._license)
            self._profile = str(data.get("execution_profile") or self._profile).upper()
            self._ram_budget_mb = max(128, int(data.get("ram_budget_mb") or self._ram_budget_mb))
            self._recent_events = deque([dict(item) for item in data.get("recent_events", []) if isinstance(item, dict)], maxlen=MAX_RECENT_EVENTS)
            self._seen_event_ids = deque([str(item) for item in data.get("seen_event_ids", [])], maxlen=256)
            raw_cooldowns = data.get("cooldowns") if isinstance(data.get("cooldowns"), dict) else {}
            self._cooldowns = {tuple(key.split("\u0000", 1)): value for key, value in raw_cooldowns.items() if isinstance(key, str) and "\u0000" in key}
            self._action_history = deque([dict(item) for item in data.get("action_history", []) if isinstance(item, dict)], maxlen=256)
            if isinstance(data.get("action_policy"), dict):
                self._action_policy.update({key: value for key, value in data["action_policy"].items() if key in {"version", "auto_actions", "approval_actions", "max_actions_per_hour", "test_unrestricted"}})
            self._last_action, self._last_heartbeat = data.get("last_action"), data.get("last_heartbeat")
            self._restart_count += 1
            self._last_restart_at = _now()
        self._changed()
