"""RFC-0074/IMP-0002 lifecycle boundary.

The first implementation slice deliberately keeps the destructive surface
narrow: every operation is represented by a deterministic plan, plans are
bound to their hash, runtime removal releases the Resource Broker lease before
the scheduler is reconciled, and tombstones prevent stale commands from
recreating an object.  Additional distributed transitions can be added behind
the same boundary without introducing another delete path.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any
from uuid import uuid4


class LifecycleError(ValueError):
    """Stable, machine-readable lifecycle failure."""

    def __init__(self, code: str, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def as_detail(self) -> dict:
        return {"code": self.code, "message": self.message, "details": deepcopy(self.details)}


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


class LifecycleManager:
    """Single entry point for plan/apply object lifecycle operations."""

    _RETENTION_DAYS = {
        "runtime": 7,
        "provider_instance": 30,
        "model_deployment": 30,
        "bundle": 30,
        "endpoint": None,
        "node": None,
    }

    def __init__(self, host) -> None:
        self._host = host
        self._lock = getattr(host, "_lifecycle_lock", RLock())

    @property
    def operations(self) -> dict[str, dict]:
        return self._host._lifecycle_operations

    @property
    def tombstones(self) -> dict[str, dict]:
        return self._host._lifecycle_tombstones

    @property
    def lifecycle_states(self) -> dict[str, dict]:
        """Durable lifecycle projections for objects without a local state field.

        Bundle and Endpoint manifests predate RFC-0074 and therefore cannot
        grow terminal states without breaking their immutable/configuration
        contracts.  Keep those states in a small, JSON-compatible projection
        owned by the host instead.  The snapshot service persists this map;
        lightweight test hosts get it lazily so the lifecycle boundary remains
        backwards compatible.
        """
        states = getattr(self._host, "_lifecycle_states", None)
        if states is None:
            states = {}
            setattr(self._host, "_lifecycle_states", states)
        return states

    def transition_plan(
        self,
        object_type: str,
        object_id: str,
        action: str,
        *,
        actor: str = "operator",
        expires_seconds: int = 900,
    ) -> dict:
        """Create a plan for a reversible/terminal lifecycle transition.

        This is deliberately separate from local removal.  Unpublishing and
        retiring preserve the object and its history, while disabling only
        changes whether the local execution path may use it.
        """
        normalized_type = self._normalize_type(object_type)
        normalized_action = str(action).strip().upper()
        target = self._target(normalized_type, object_id)
        target_state = self._transition_target_state(
            normalized_type,
            target["state"],
            normalized_action,
        )
        now = _now()
        expires_at = now + timedelta(seconds=max(60, int(expires_seconds)))
        network_actions = self._transition_network_actions(
            normalized_type, normalized_action
        )
        plan = {
            "transition_id": f"transition-{uuid4().hex[:16]}",
            "operation_id": None,
            "operation_type": "TRANSITION",
            "target": {"type": normalized_type, "id": object_id},
            "action": normalized_action,
            "current_state": target["state"],
            "target_state": target_state,
            "target_fingerprint": deepcopy(target["fingerprint"]),
            "dependencies": self._dependencies(normalized_type, object_id),
            "network_actions": network_actions,
            "local_actions": self._transition_local_actions(
                normalized_type, normalized_action, object_id
            ),
            "requires_approval": normalized_action in {"UNPUBLISH", "RETIRE"},
            "actor": actor,
            "created_at": _timestamp(now),
            "expires_at": _timestamp(expires_at),
        }
        plan["operation_id"] = plan["transition_id"]
        plan["plan_hash"] = _canonical_hash(plan)
        operation = {
            "operation_id": plan["transition_id"],
            "operation_type": "TRANSITION",
            "target_id": object_id,
            "target_type": normalized_type,
            "plan_hash": plan["plan_hash"],
            "plan": deepcopy(plan),
            "state": "PLANNED",
            "current_step": "PLAN",
            "started_at": None,
            "updated_at": _timestamp(now),
            "error": None,
            "idempotency_key": None,
        }
        with self._lock:
            self.operations[plan["transition_id"]] = operation
            self._persist()
        self._emit(
            "aidn.object.transition_planned",
            "lifecycle transition plan created",
            resource_type=normalized_type,
            resource_id=object_id,
            details={
                "transition_id": plan["transition_id"],
                "plan_hash": plan["plan_hash"],
                "action": normalized_action,
                "target_state": target_state,
            },
        )
        return deepcopy(plan)

    def apply_transition(
        self,
        transition_id: str,
        plan_hash: str,
        *,
        actor: str = "operator",
        idempotency_key: str | None = None,
    ) -> dict:
        with self._lock:
            operation = self.operations.get(transition_id)
            if operation is None or operation.get("operation_type") != "TRANSITION":
                raise LifecycleError("OBJECT_NOT_FOUND", f"Unknown lifecycle transition: {transition_id}")
            if operation["state"] == "COMPLETED":
                return deepcopy(operation)
            if operation["plan_hash"] != plan_hash:
                raise LifecycleError(
                    "REMOVAL_PLAN_STALE",
                    "Lifecycle transition plan hash does not match",
                    details={"expected": operation["plan_hash"], "received": plan_hash},
                )
            if operation.get("idempotency_key") not in {None, idempotency_key}:
                raise LifecycleError(
                    "MCP_CONFLICT_IDEMPOTENCY",
                    "Lifecycle transition was already applied with another idempotency key",
                )
            plan = deepcopy(operation["plan"])
        if plan.get("expires_at") and plan["expires_at"] < _timestamp():
            raise LifecycleError("REMOVAL_PLAN_STALE", "Lifecycle transition plan has expired")

        self._assert_plan_current(plan)
        self._set_operation(
            operation,
            state="PRECHECK",
            step="PRECHECK",
            actor=actor,
            idempotency_key=idempotency_key,
        )
        try:
            self._set_operation(operation, state="APPLYING", step="APPLYING", actor=actor)
            self._apply_transition(plan, actor=actor)
            current = self._target(plan["target"]["type"], plan["target"]["id"])
            if current["state"] != plan["target_state"]:
                raise LifecycleError(
                    "TRANSITION_VERIFY_FAILED",
                    "Lifecycle transition did not reach its target state",
                    details={"expected": plan["target_state"], "actual": current["state"]},
                )
            self._set_operation(operation, state="VERIFYING", step="VERIFY", actor=actor)
            self._set_operation(operation, state="COMPLETED", step="COMPLETE", actor=actor)
            event_type = {
                "DISABLE": "aidn.object.disabled",
                "UNPUBLISH": "aidn.object.unpublished",
                "RETIRE": "aidn.object.retired",
            }[plan["action"]]
            self._emit(
                event_type,
                f"lifecycle transition {plan['action'].lower()} completed",
                resource_type=plan["target"]["type"],
                resource_id=plan["target"]["id"],
                details={
                    "transition_id": transition_id,
                    "plan_hash": plan_hash,
                    "previous_state": plan["current_state"],
                    "new_state": plan["target_state"],
                },
            )
            return deepcopy(self.operations[transition_id])
        except LifecycleError as error:
            self._fail_transition(operation, error)
        except Exception as error:  # pragma: no cover - defensive boundary
            self._fail_transition(operation, LifecycleError("TRANSITION_PARTIAL_FAILURE", str(error)))
        raise AssertionError("unreachable")

    def removal_plan(
        self,
        object_type: str,
        object_id: str,
        *,
        cascade: bool = False,
        actor: str = "operator",
        expires_seconds: int = 900,
    ) -> dict:
        normalized_type = self._normalize_type(object_type)
        target = self._target(normalized_type, object_id)
        dependencies = self._dependencies(normalized_type, object_id)
        blocking = [item for item in dependencies if item.get("blocking", True)]
        if blocking and not cascade:
            actions = [{"action": "BLOCKED_BY_DEPENDENCY", "target": item} for item in blocking]
        else:
            actions = self._actions(normalized_type, target, dependencies, cascade=cascade)

        now = _now()
        expires_at = now + timedelta(seconds=max(60, int(expires_seconds)))
        plan = {
            "plan_id": f"plan-{uuid4().hex[:16]}",
            "target": {"type": normalized_type, "id": object_id},
            "current_state": target["state"],
            "target_fingerprint": target["fingerprint"],
            "dependencies": dependencies,
            "actions": actions,
            "network_actions": self._network_actions(normalized_type, target),
            "local_actions": [item for item in actions if item.get("scope") == "local"],
            "artifacts_to_delete": [],
            "artifacts_to_preserve": [],
            "secrets_affected": [],
            "estimated_freed": self._estimated_freed(target),
            "requires_approval": normalized_type not in {"runtime"},
            "actor": actor,
            "created_at": _timestamp(now),
            "expires_at": _timestamp(expires_at),
            "cascade": bool(cascade),
        }
        plan["plan_hash"] = _canonical_hash(plan)
        operation = {
            "operation_id": plan["plan_id"],
            "operation_type": "REMOVAL",
            "target_id": object_id,
            "target_type": normalized_type,
            "plan_hash": plan["plan_hash"],
            "plan": deepcopy(plan),
            "state": "PLANNED",
            "current_step": "PLAN",
            "started_at": None,
            "updated_at": _timestamp(now),
            "error": None,
            "idempotency_key": None,
        }
        with self._lock:
            self.operations[plan["plan_id"]] = operation
            self._persist()
        self._emit(
            "aidn.object.removal_planned",
            "lifecycle removal plan created",
            resource_type=normalized_type,
            resource_id=object_id,
            details={"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"], "cascade": cascade},
        )
        return deepcopy(plan)

    def apply_removal(
        self,
        plan_id: str,
        plan_hash: str,
        *,
        actor: str = "operator",
        force: bool = False,
        idempotency_key: str | None = None,
    ) -> dict:
        with self._lock:
            operation = self.operations.get(plan_id)
            if operation is None:
                raise LifecycleError("OBJECT_NOT_FOUND", f"Unknown lifecycle plan: {plan_id}")
            if operation["state"] == "COMPLETED":
                return deepcopy(operation)
            if operation["plan_hash"] != plan_hash:
                raise LifecycleError("REMOVAL_PLAN_STALE", "Removal plan hash does not match", details={"expected": operation["plan_hash"], "received": plan_hash})
            if operation.get("idempotency_key") not in {None, idempotency_key}:
                raise LifecycleError("MCP_CONFLICT_IDEMPOTENCY", "Lifecycle operation was already applied with another idempotency key")
            plan = deepcopy(operation["plan"])
        if plan.get("expires_at") and plan["expires_at"] < _timestamp():
            raise LifecycleError("REMOVAL_PLAN_STALE", "Removal plan has expired")

        self._assert_plan_current(plan)
        self._set_operation(operation, state="PRECHECK", step="PRECHECK", actor=actor, idempotency_key=idempotency_key)
        blocking = [item for item in plan["dependencies"] if item.get("blocking", True)]
        if blocking and not plan.get("cascade"):
            self._fail_operation(operation, LifecycleError("DELETE_BLOCKED_BY_DEPENDENCY", "Object has live dependents", details={"dependencies": blocking}))
        try:
            self._set_operation(operation, state="DRAINING", step="DRAINING", actor=actor)
            self._apply_dependencies(plan, force=force)
            self._set_operation(operation, state="LOCAL_REMOVAL", step="LOCAL_REMOVAL", actor=actor)
            self._apply_target(plan, force=force)
            self._set_operation(operation, state="VERIFYING", step="VERIFYING", actor=actor)
            tombstone = self._create_tombstone(plan, actor=actor)
            self._set_operation(operation, state="COMPLETED", step="COMPLETE", actor=actor)
            self._emit(
                "aidn.object.deleted",
                "lifecycle removal completed",
                resource_type=plan["target"]["type"],
                resource_id=plan["target"]["id"],
                details={"plan_id": plan_id, "tombstone": tombstone},
            )
            return deepcopy(self.operations[plan_id])
        except LifecycleError as error:
            self._fail_operation(operation, error)
        except Exception as error:  # pragma: no cover - defensive boundary
            self._fail_operation(operation, LifecycleError("REMOVAL_PARTIAL_FAILURE", str(error)))
        raise AssertionError("unreachable")

    def reset_runtime_plan(self, *, actor: str = "operator", expires_seconds: int = 900) -> dict:
        return ResetManager(self).plan("runtime", actor=actor, expires_seconds=expires_seconds)

    def apply_runtime_reset(
        self,
        reset_id: str,
        plan_hash: str,
        *,
        actor: str = "operator",
        force: bool = False,
        idempotency_key: str | None = None,
    ) -> dict:
        return ResetManager(self).apply(
            reset_id,
            plan_hash,
            actor=actor,
            force=force,
            idempotency_key=idempotency_key,
        )

    def list_tombstones(self) -> list[dict]:
        with self._lock:
            return [deepcopy(item) for item in sorted(self.tombstones.values(), key=lambda value: value["deleted_at"])]

    def get_tombstone(self, object_type: str, object_id: str) -> dict:
        key = self._tombstone_key(self._normalize_type(object_type), object_id)
        with self._lock:
            try:
                return deepcopy(self.tombstones[key])
            except KeyError as error:
                raise LifecycleError("OBJECT_NOT_FOUND", f"Tombstone not found: {object_type}/{object_id}") from error

    def assert_not_tombstoned(self, object_type: str, object_id: str) -> None:
        key = self._tombstone_key(self._normalize_type(object_type), object_id)
        if key in self.tombstones:
            raise LifecycleError("OBJECT_TOMBSTONED", f"Object ID is tombstoned: {object_type}/{object_id}")

    def _normalize_type(self, object_type: str) -> str:
        aliases = {
            "runtime_instance": "runtime",
            "provider": "provider_instance",
            "model": "model_deployment",
            "bundle_revision": "bundle",
        }
        normalized = aliases.get(str(object_type).strip().lower(), str(object_type).strip().lower())
        allowed = {"runtime", "provider_instance", "model_deployment", "bundle", "endpoint", "provider_plugin"}
        if normalized not in allowed:
            raise LifecycleError("OBJECT_TYPE_UNSUPPORTED", f"Unsupported lifecycle object type: {object_type}")
        return normalized

    def _target(self, object_type: str, object_id: str) -> dict:
        self.assert_not_tombstoned(object_type, object_id)
        if object_type == "runtime":
            for runtime in self._host.list_runtimes():
                if runtime.runtime_id == object_id:
                    return {
                        "state": runtime.status.upper(),
                        "fingerprint": {"status": runtime.status, "bundle_id": runtime.bundle_id},
                        "bundle_id": runtime.bundle_id,
                        "runtime": runtime,
                    }
        elif object_type == "bundle":
            for bundle in self._host.bundle_config():
                if bundle.bundle_id == object_id:
                    return self._with_lifecycle_state(
                        object_type,
                        object_id,
                        {
                            "state": "ACTIVE" if bundle.enabled else "DISABLED",
                            "fingerprint": bundle.model_dump(mode="json"),
                            "bundle": bundle,
                        },
                    )
        elif object_type == "provider_instance":
            for item in self._host.provider_inventory.list_provider_instances():
                if item.provider_instance_id == object_id:
                    return {"state": "ACTIVE", "fingerprint": item.model_dump(mode="json"), "provider": item}
        elif object_type == "model_deployment":
            for item in self._host.provider_inventory.list_model_deployments():
                if item.model_deployment_id == object_id:
                    return {"state": "ACTIVE", "fingerprint": item.model_dump(mode="json"), "deployment": item}
        elif object_type == "endpoint":
            service = getattr(self._host, "endpoint_service", None)
            if service is not None:
                for item in service.list_endpoints():
                    if item.endpoint_id == object_id:
                        return self._with_lifecycle_state(
                            object_type,
                            object_id,
                            {
                                "state": item.status.upper(),
                                "fingerprint": item.model_dump(mode="json"),
                                "endpoint": item,
                            },
                        )
        elif object_type == "provider_plugin":
            for item in self._host.provider_inventory.list_installed_plugins():
                if item.plugin_id == object_id or item.installed_plugin_id == object_id:
                    return {"state": "ACTIVE", "fingerprint": item.model_dump(mode="json"), "plugin": item}
        raise LifecycleError("OBJECT_NOT_FOUND", f"Unknown {object_type}: {object_id}")

    def _with_lifecycle_state(self, object_type: str, object_id: str, target: dict) -> dict:
        projection = self.lifecycle_states.get(self._tombstone_key(object_type, object_id))
        if projection is None:
            return target
        enriched = dict(target)
        enriched["state"] = str(projection["state"]).upper()
        fingerprint = dict(target["fingerprint"])
        fingerprint["_lifecycle_state"] = projection["state"]
        enriched["fingerprint"] = fingerprint
        enriched["lifecycle"] = projection
        return enriched

    def _transition_target_state(self, object_type: str, current_state: str, action: str) -> str:
        current = str(current_state).upper()
        if current == "RETIRED":
            raise LifecycleError("OBJECT_RETIRED", "Retired objects cannot be transitioned in place")
        if object_type == "bundle":
            if action == "DISABLE":
                if current == "DISABLED":
                    raise LifecycleError("OBJECT_DISABLED", "Bundle is already disabled")
                if current != "ACTIVE":
                    raise LifecycleError("LIFECYCLE_TRANSITION_UNSUPPORTED", f"Cannot disable Bundle from {current}")
                return "DISABLED"
            if action == "RETIRE":
                if current != "DISABLED":
                    raise LifecycleError("TRANSITION_REQUIRES_DISABLED", "Bundle must be disabled before retirement")
                return "RETIRED"
            raise LifecycleError("LIFECYCLE_TRANSITION_UNSUPPORTED", f"Action {action} is not supported for Bundle")
        if object_type == "endpoint":
            if action == "DISABLE":
                if current == "DISABLED":
                    raise LifecycleError("OBJECT_DISABLED", "Endpoint is already disabled")
                if current in {"DELETED", "RETIRED", "UNPUBLISHED"}:
                    raise LifecycleError("LIFECYCLE_TRANSITION_UNSUPPORTED", f"Cannot disable Endpoint from {current}")
                return "DISABLED"
            if action == "UNPUBLISH":
                if current == "UNPUBLISHED":
                    raise LifecycleError("OBJECT_UNPUBLISHED", "Endpoint is already unpublished")
                if current == "DELETED":
                    raise LifecycleError("OBJECT_DELETED", "Deleted Endpoint cannot be unpublished")
                return "UNPUBLISHED"
            if action == "RETIRE":
                if current != "UNPUBLISHED":
                    raise LifecycleError("TRANSITION_REQUIRES_UNPUBLISHED", "Endpoint must be unpublished before retirement")
                return "RETIRED"
            raise LifecycleError("LIFECYCLE_TRANSITION_UNSUPPORTED", f"Action {action} is not supported for Endpoint")
        raise LifecycleError("LIFECYCLE_TRANSITION_UNSUPPORTED", f"Lifecycle transitions are not implemented for {object_type}")

    def _transition_network_actions(self, object_type: str, action: str) -> list[dict]:
        if object_type == "endpoint" and action == "UNPUBLISH":
            return [{"action": "UNPUBLISH", "status": "LOCAL_PROJECTION_ONLY", "requires_network_finalization": True}]
        if object_type == "endpoint" and action == "RETIRE":
            return [{"action": "RETIRE", "status": "LOCAL_PROJECTION_ONLY", "requires_network_finalization": True}]
        return []

    def _transition_local_actions(self, object_type: str, action: str, object_id: str) -> list[dict]:
        if object_type == "bundle":
            if action == "DISABLE":
                return [{"action": "SET_BUNDLE_ENABLED", "target": object_id, "enabled": False}]
            return [{"action": "RETAIN_HISTORY", "target": object_id}]
        if object_type == "endpoint":
            if action == "DISABLE":
                return [{"action": "DISABLE_ENDPOINT", "target": object_id}]
            if action == "UNPUBLISH":
                return [{"action": "CLOSE_PUBLICATION", "target": object_id}]
            return [{"action": "DISABLE_ENDPOINT", "target": object_id}, {"action": "RETAIN_HISTORY", "target": object_id}]
        return []

    def _apply_transition(self, plan: dict, *, actor: str) -> None:
        object_type = plan["target"]["type"]
        object_id = plan["target"]["id"]
        action = plan["action"]
        if action == "RETIRE":
            live_dependencies = [
                item for item in self._dependencies(object_type, object_id)
                if item.get("blocking", True)
            ]
            if live_dependencies:
                raise LifecycleError(
                    "DELETE_REQUIRES_DRAIN",
                    "Object has live dependents and cannot be retired",
                    details={"dependencies": live_dependencies},
                )
        if object_type == "bundle":
            if action == "DISABLE":
                self._host.set_bundle_enabled(object_id, False)
            elif action == "RETIRE":
                # Retirement is a terminal lifecycle projection; the local
                # Bundle remains available for historical inspection.
                pass
            else:  # pragma: no cover - guarded by _transition_target_state
                raise LifecycleError("LIFECYCLE_TRANSITION_UNSUPPORTED", f"Action {action} is not supported for Bundle")
        elif object_type == "endpoint":
            endpoint_service = getattr(self._host, "endpoint_service", None)
            if endpoint_service is None:
                raise LifecycleError("ENDPOINT_SERVICE_UNAVAILABLE", "Endpoint service is not configured")
            if action == "DISABLE":
                endpoint_service.disable_endpoint(object_id)
            elif action == "UNPUBLISH":
                endpoint_service.unpublish_endpoint(object_id)
            elif action == "RETIRE":
                active_sessions = self._active_endpoint_sessions(object_id)
                if active_sessions:
                    raise LifecycleError(
                        "ACTIVE_SESSIONS",
                        "Endpoint has active sessions and cannot be retired",
                        details={"endpoint_id": object_id, "session_ids": active_sessions},
                    )
                endpoint = self._target(object_type, object_id)["endpoint"]
                if endpoint.status in {"created", "active", "suspended"}:
                    endpoint_service.disable_endpoint(object_id)
            else:  # pragma: no cover - guarded by _transition_target_state
                raise LifecycleError("LIFECYCLE_TRANSITION_UNSUPPORTED", f"Action {action} is not supported for Endpoint")
        else:  # pragma: no cover - guarded by _transition_target_state
            raise LifecycleError("LIFECYCLE_TRANSITION_UNSUPPORTED", f"Lifecycle transitions are not implemented for {object_type}")
        self._set_lifecycle_state(object_type, object_id, plan["target_state"], actor=actor)

    def _set_lifecycle_state(self, object_type: str, object_id: str, state: str, *, actor: str) -> None:
        key = self._tombstone_key(object_type, object_id)
        previous = self.lifecycle_states.get(key, {})
        self.lifecycle_states[key] = {
            "object_type": object_type,
            "object_id": object_id,
            "state": state,
            "revision": int(previous.get("revision", 0)) + 1,
            "actor": actor,
            "updated_at": _timestamp(),
        }
        self._persist()

    def _active_endpoint_sessions(self, endpoint_id: str) -> list[str]:
        session_service = getattr(self._host, "session_service", None)
        store = getattr(session_service, "store", None)
        list_sessions = getattr(store, "list_sessions", None)
        if not callable(list_sessions):
            return []
        active_states = {"queued", "active", "recovering", "paused", "force_closing"}
        return [
            session.session_id
            for session in list_sessions()
            if session.endpoint_id == endpoint_id and session.status in active_states
        ]

    def _dependencies(self, object_type: str, object_id: str) -> list[dict]:
        dependencies: list[dict] = []
        inventory = getattr(self._host, "provider_inventory", None)
        if object_type == "runtime":
            count = self._active_task_count(object_id)
            if count:
                dependencies.append({"type": "session", "id": object_id, "kind": "active_work", "count": count, "blocking": True})
        elif object_type == "provider_instance" and inventory is not None:
            deployments = inventory.list_model_deployments(provider_instance_id=object_id)
            bindings = [item for item in inventory.list_runtime_bindings() if item.provider_instance_id == object_id]
            for deployment in deployments:
                dependencies.append({"type": "model_deployment", "id": deployment.model_deployment_id, "kind": "provider_reference", "blocking": True})
            for binding in bindings:
                dependencies.append({"type": "runtime_binding", "id": binding.runtime_binding_id, "runtime_id": binding.runtime_id, "kind": "runtime_reference", "blocking": True})
        elif object_type == "model_deployment" and inventory is not None:
            for binding in inventory.list_runtime_bindings():
                if binding.model_deployment_id == object_id:
                    dependencies.append({"type": "runtime_binding", "id": binding.runtime_binding_id, "runtime_id": binding.runtime_id, "kind": "runtime_reference", "blocking": True})
        elif object_type in {"bundle", "endpoint"}:
            bundle_id = object_id
            if object_type == "endpoint":
                target = self._target(object_type, object_id)
                bundle_id = target["endpoint"].bundle_id
            for runtime in self._host.list_runtimes():
                if runtime.bundle_id == bundle_id and runtime.status not in {"stopped", "failed"}:
                    dependencies.append({"type": "runtime", "id": runtime.runtime_id, "kind": "runtime_reference", "blocking": True})
        elif object_type == "provider_plugin" and inventory is not None:
            for item in inventory.list_provider_instances():
                if item.plugin_id == object_id:
                    dependencies.append({"type": "provider_instance", "id": item.provider_instance_id, "kind": "plugin_reference", "blocking": True})
        return dependencies

    def _actions(self, object_type: str, target: dict, dependencies: list[dict], *, cascade: bool) -> list[dict]:
        actions: list[dict] = []
        for dependency in dependencies if cascade else []:
            if dependency["type"] == "runtime":
                actions.extend([
                    {"action": "DRAIN_RUNTIME", "target": dependency["id"], "scope": "local"},
                    {"action": "STOP_RUNTIME", "target": dependency["id"], "scope": "local"},
                    {"action": "RELEASE_RESOURCE_LEASE", "target": dependency["id"], "scope": "local"},
                ])
            elif dependency["type"] in {"model_deployment", "provider_instance"}:
                actions.append({"action": "DELETE_LOCAL", "target": dependency["id"], "scope": "local"})
        if object_type == "runtime":
            actions.extend([
                {"action": "DRAIN_RUNTIME", "target": target["runtime"].runtime_id, "scope": "local"},
                {"action": "STOP_RUNTIME", "target": target["runtime"].runtime_id, "scope": "local"},
                {"action": "RELEASE_RESOURCE_LEASE", "target": target["runtime"].bundle_id, "scope": "local"},
                {"action": "DELETE_LOCAL", "target": target["runtime"].runtime_id, "scope": "local"},
            ])
        elif object_type == "endpoint":
            actions.append({"action": "DISABLE_ENDPOINT", "target": target["endpoint"].endpoint_id, "scope": "local"})
            if target["endpoint"].publication.visibility != "private" or target["endpoint"].publication.discoverable:
                actions.extend([
                    {"action": "UNPUBLISH_ENDPOINT", "target": object_id, "scope": "network"},
                    {"action": "RETIRE_ENDPOINT", "target": object_id, "scope": "network"},
                ])
            actions.append({"action": "DELETE_LOCAL", "target": object_id, "scope": "local"})
        elif object_type == "bundle":
            if target["bundle"].enabled:
                actions.append({"action": "DISABLE_BUNDLE", "target": object_id, "scope": "local"})
            actions.append({"action": "DELETE_LOCAL", "target": object_id, "scope": "local"})
        else:
            actions.append({"action": "DELETE_LOCAL", "target": target.get(object_type.split("_")[-1], object_id), "scope": "local"})
        return actions

    def _network_actions(self, object_type: str, target: dict) -> list[dict]:
        if object_type == "endpoint":
            endpoint = target.get("endpoint")
            if endpoint is not None and (endpoint.publication.visibility != "private" or endpoint.publication.discoverable):
                return [{"action": "UNPUBLISH"}, {"action": "RETIRE"}]
        return []

    def _estimated_freed(self, target: dict) -> dict[str, int]:
        bundle = target.get("bundle")
        if bundle is None and target.get("runtime") is not None:
            bundle_id = target["runtime"].bundle_id
            if bundle_id:
                try:
                    bundle = self._host._get_bundle(bundle_id)
                except (KeyError, AttributeError):
                    bundle = None
        profile = getattr(bundle, "resource_profile", None)
        if profile is None:
            return {"ram_bytes": 0, "vram_bytes": 0, "disk_bytes": 0}
        return {
            "ram_bytes": int(profile.steady_ram_mb) * 1024 * 1024,
            "vram_bytes": int(profile.steady_vram_mb) * 1024 * 1024,
            "disk_bytes": 0,
        }

    def _apply_dependencies(self, plan: dict, *, force: bool) -> None:
        if not plan.get("cascade"):
            return
        rank = {"runtime": 0, "runtime_binding": 1, "model_deployment": 2, "provider_instance": 3}
        for dependency in sorted(plan["dependencies"], key=lambda item: rank.get(item["type"], 99)):
            if dependency["type"] == "runtime":
                self._remove_runtime(dependency["id"], force=force)
            elif dependency["type"] == "runtime_binding":
                try:
                    self._host.provider_inventory.store.delete_runtime_binding(dependency["id"])
                except KeyError as error:
                    raise LifecycleError("OBJECT_NOT_FOUND", f"Unknown Runtime Binding: {dependency['id']}") from error
            elif dependency["type"] == "model_deployment":
                self._delete_model(dependency["id"])
            elif dependency["type"] == "provider_instance":
                self._delete_provider(dependency["id"])
            elif dependency.get("blocking"):
                raise LifecycleError("DELETE_BLOCKED_BY_DEPENDENCY", f"Unsupported live dependency: {dependency['id']}")

    def _apply_target(self, plan: dict, *, force: bool) -> None:
        object_type = plan["target"]["type"]
        object_id = plan["target"]["id"]
        if object_type == "runtime":
            self._remove_runtime(object_id, force=force)
        elif object_type == "endpoint":
            target = self._target(object_type, object_id)
            endpoint = target["endpoint"]
            if endpoint.publication.visibility != "private" or endpoint.publication.discoverable:
                raise LifecycleError("DELETE_REQUIRES_UNPUBLISH", "Public Endpoint network transition is required before local deletion")
            self._host.endpoint_service.delete_endpoint(object_id)
        elif object_type == "bundle":
            self._delete_bundle(object_id)
        elif object_type == "model_deployment":
            self._delete_model(object_id)
        elif object_type == "provider_instance":
            self._delete_provider(object_id)
        else:
            raise LifecycleError("LIFECYCLE_NOT_IMPLEMENTED", f"Local removal is not implemented for {object_type}")

    def _remove_runtime(self, runtime_id: str, *, force: bool) -> None:
        active_count = self._active_task_count(runtime_id)
        if active_count and not force:
            raise LifecycleError("DELETE_REQUIRES_DRAIN", "Runtime has active work", details={"runtime_id": runtime_id, "active_tasks": active_count})
        try:
            self._host.force_stop_runtime(runtime_id)
        except KeyError as error:
            raise LifecycleError("OBJECT_NOT_FOUND", f"Unknown runtime: {runtime_id}") from error
        self._emit("aidn.resource.state_changed", "runtime resources released", resource_type="runtime", resource_id=runtime_id, details={"reason": "lifecycle_removal"})
        try:
            self._host.reconcile_scheduler(trigger="lifecycle_runtime_removed")
        except Exception:
            # A failed reconciliation is observable on the next status read;
            # it must not turn a confirmed process stop into a false failure.
            pass

    def _delete_bundle(self, bundle_id: str) -> None:
        bundles = list(self._host.bundle_config())
        if not any(item.bundle_id == bundle_id for item in bundles):
            raise LifecycleError("OBJECT_NOT_FOUND", f"Unknown bundle: {bundle_id}")
        self._host.replace_bundle_config([item for item in bundles if item.bundle_id != bundle_id])

    def _delete_model(self, model_id: str) -> None:
        inventory = self._host.provider_inventory
        if inventory.store.model_deployment_has_runtime_bindings(model_id):
            raise LifecycleError("DELETE_BLOCKED_BY_DEPENDENCY", "Model Deployment still has Runtime Bindings", details={"model_deployment_id": model_id})
        try:
            inventory.store.delete_model_deployment(model_id)
        except KeyError as error:
            raise LifecycleError("OBJECT_NOT_FOUND", f"Unknown Model Deployment: {model_id}") from error

    def _delete_provider(self, provider_id: str) -> None:
        inventory = self._host.provider_inventory
        if inventory.list_model_deployments(provider_instance_id=provider_id):
            raise LifecycleError("DELETE_BLOCKED_BY_DEPENDENCY", "Provider Instance still owns Model Deployments", details={"provider_instance_id": provider_id})
        try:
            inventory.store.delete_provider_instance(provider_id)
        except KeyError as error:
            raise LifecycleError("OBJECT_NOT_FOUND", f"Unknown Provider Instance: {provider_id}") from error

    def _create_tombstone(self, plan: dict, *, actor: str) -> dict:
        target = plan["target"]
        key = self._tombstone_key(target["type"], target["id"])
        days = self._RETENTION_DAYS.get(target["type"])
        expiry = None if days is None else _timestamp(_now() + timedelta(days=days))
        tombstone = {
            "object_id": target["id"],
            "object_type": target["type"],
            "final_revision": plan["target_fingerprint"].get("revision"),
            "previous_state": plan["current_state"],
            "deleted_at": _timestamp(),
            "actor": actor,
            "reason": "lifecycle_removal",
            "network_state": "HISTORICAL" if plan["network_actions"] else "LOCAL_ONLY",
            "expires_at": expiry,
        }
        self.tombstones[key] = tombstone
        self._persist()
        return deepcopy(tombstone)

    def _assert_plan_current(self, plan: dict) -> None:
        target = self._target(plan["target"]["type"], plan["target"]["id"])
        if target["fingerprint"] != plan["target_fingerprint"]:
            raise LifecycleError("REMOVAL_PLAN_STALE", "Target changed since the plan was created")
        if "dependencies" not in plan:
            return
        current_dependencies = self._dependencies(plan["target"]["type"], plan["target"]["id"])
        if current_dependencies != plan["dependencies"]:
            raise LifecycleError("REMOVAL_PLAN_STALE", "Dependencies changed since the plan was created", details={"current": current_dependencies, "planned": plan["dependencies"]})

    def _set_operation(self, operation: dict, *, state: str, step: str, actor: str, idempotency_key: str | None = None) -> None:
        operation["state"] = state
        operation["current_step"] = step
        operation["updated_at"] = _timestamp()
        if operation.get("started_at") is None:
            operation["started_at"] = operation["updated_at"]
        operation["actor"] = actor
        if idempotency_key is not None:
            operation["idempotency_key"] = idempotency_key
        self._persist()

    def _fail_operation(self, operation: dict, error: LifecycleError) -> None:
        operation["state"] = "PARTIALLY_APPLIED" if operation.get("current_step") not in {"PLAN", "PRECHECK"} else "FAILED"
        operation["current_step"] = "FAILED"
        operation["error"] = error.as_detail()
        operation["updated_at"] = _timestamp()
        self._persist()
        self._emit("aidn.object.removal_failed", error.message, resource_type=operation["target_type"], resource_id=operation["target_id"], details=error.as_detail())
        raise error

    def _fail_transition(self, operation: dict, error: LifecycleError) -> None:
        operation["state"] = "PARTIALLY_APPLIED" if operation.get("current_step") not in {"PLAN", "PRECHECK"} else "FAILED"
        operation["current_step"] = "FAILED"
        operation["error"] = error.as_detail()
        operation["updated_at"] = _timestamp()
        self._persist()
        self._emit(
            "aidn.object.transition_failed",
            error.message,
            resource_type=operation["target_type"],
            resource_id=operation["target_id"],
            details=error.as_detail(),
        )
        raise error

    def _active_task_count(self, runtime_id: str) -> int:
        runtime = next((item for item in self._host.list_runtimes() if item.runtime_id == runtime_id), None)
        bundle_id = getattr(runtime, "bundle_id", None)
        if bundle_id is None:
            return 0
        callback = getattr(self._host, "runtime_active_task_count", None)
        if callable(callback):
            return int(callback(bundle_id))
        return 0

    def _tombstone_key(self, object_type: str, object_id: str) -> str:
        return f"{object_type}:{object_id}"

    def _persist(self) -> None:
        callback = getattr(self._host, "_persist_state", None)
        if callable(callback):
            callback()

    def _emit(self, event_type: str, message: str, *, resource_type: str, resource_id: str, details: dict) -> None:
        callback = getattr(self._host, "record_event", None)
        if callable(callback):
            callback(event_type=event_type, message=message, resource_type=resource_type, resource_id=resource_id, details=details)


class ResetManager:
    """Reset orchestration sharing the LifecycleManager operation store."""

    def __init__(self, lifecycle: LifecycleManager) -> None:
        self._lifecycle = lifecycle
        self._host = lifecycle._host

    def plan(self, profile: str, *, actor: str = "operator", expires_seconds: int = 900) -> dict:
        allowed = {"runtime", "configuration", "preserve-identity", "factory"}
        if profile not in allowed:
            raise LifecycleError("RESET_PROFILE_UNSUPPORTED", f"Unsupported reset profile: {profile}")
        runtimes = [item.runtime_id for item in self._host.list_runtimes() if item.status not in {"stopped", "failed"}]
        now = _now()
        plan = {
            "reset_id": f"reset-{uuid4().hex[:16]}",
            "profile": profile,
            "preserve": {
                "node_identity": profile in {"runtime", "configuration", "preserve-identity"},
                "wallet": True,
                "network_registration": profile in {"runtime", "configuration"},
            },
            "delete": {
                "runtimes": runtimes,
                "providers": profile != "runtime",
                "models": profile != "runtime",
                "bundles": profile != "runtime",
                "endpoints": profile != "runtime",
                "network_cache": profile in {"preserve-identity", "factory"},
                "hooks": profile in {"preserve-identity", "factory"},
                "agent_sessions": profile in {"preserve-identity", "factory"},
            },
            "active_sessions": [],
            "pending_jobs": [],
            "pending_validations": [],
            "estimated_reclaimed_disk_bytes": 0,
            "requires_approval": profile != "runtime",
            "actor": actor,
            "created_at": _timestamp(now),
            "expires_at": _timestamp(now + timedelta(seconds=max(60, int(expires_seconds)))),
        }
        plan["plan_hash"] = _canonical_hash(plan)
        operation = {
            "operation_id": plan["reset_id"],
            "operation_type": "RESET",
            "target_id": "node",
            "target_type": "node",
            "plan_hash": plan["plan_hash"],
            "plan": deepcopy(plan),
            "state": "PLANNED",
            "current_step": "PLAN",
            "started_at": None,
            "updated_at": _timestamp(now),
            "error": None,
            "idempotency_key": None,
        }
        self._lifecycle.operations[plan["reset_id"]] = operation
        self._lifecycle._persist()
        self._lifecycle._emit("aidn.node.reset_started", "reset plan created", resource_type="node", resource_id=getattr(self._host, "node_id", "node"), details={"reset_id": plan["reset_id"], "profile": profile, "planned": True})
        return deepcopy(plan)

    def apply(self, reset_id: str, plan_hash: str, *, actor: str, force: bool, idempotency_key: str | None) -> dict:
        operation = self._lifecycle.operations.get(reset_id)
        if operation is None:
            raise LifecycleError("OBJECT_NOT_FOUND", f"Unknown reset plan: {reset_id}")
        if operation["state"] == "COMPLETED":
            return deepcopy(operation)
        if operation["plan_hash"] != plan_hash:
            raise LifecycleError("REMOVAL_PLAN_STALE", "Reset plan hash does not match")
        if operation.get("idempotency_key") not in {None, idempotency_key}:
            raise LifecycleError("MCP_CONFLICT_IDEMPOTENCY", "Reset operation was already applied with another idempotency key")
        if operation["plan"].get("expires_at") and operation["plan"]["expires_at"] < _timestamp():
            raise LifecycleError("REMOVAL_PLAN_STALE", "Reset plan has expired")
        profile = operation["plan"]["profile"]
        if profile != "runtime":
            error = LifecycleError("RESET_PROFILE_NOT_IMPLEMENTED", f"Reset profile is planned but not executable yet: {profile}")
            operation["error"] = error.as_detail()
            operation["state"] = "FAILED"
            operation["current_step"] = "FAILED"
            self._lifecycle._persist()
            raise error
        runtimes = list(operation["plan"]["delete"]["runtimes"])
        self._host._lifecycle_maintenance_state = "PAUSED_MAINTENANCE"
        operation["state"] = "PRECHECK"
        operation["current_step"] = "PAUSE_SCHEDULER"
        operation["started_at"] = operation["started_at"] or _timestamp()
        operation["updated_at"] = _timestamp()
        operation["actor"] = actor
        operation["idempotency_key"] = idempotency_key
        self._lifecycle._persist()
        self._lifecycle._emit("aidn.node.reset_step", "runtime reset paused admission", resource_type="node", resource_id=getattr(self._host, "node_id", "node"), details={"reset_id": reset_id, "profile": profile, "step": "PAUSE_SCHEDULER", "progress": 0.1})
        try:
            queue = getattr(self._host, "queue", None)
            if queue is not None and hasattr(queue, "snapshot") and hasattr(queue, "transition_status"):
                for task in queue.snapshot():
                    if task.status in {"queued", "admitted", "starting", "running"}:
                        queue.transition_status(task.task_id, "cancelled")
            model_installs = getattr(self._host, "_model_installs", None)
            if isinstance(model_installs, dict):
                model_installs.clear()
            self._lifecycle._persist()
            for runtime_id in runtimes:
                self._lifecycle._remove_runtime(runtime_id, force=force)
            operation["state"] = "VERIFYING"
            operation["current_step"] = "VERIFY"
            operation["updated_at"] = _timestamp()
            self._lifecycle._persist()
            if any(item.status not in {"stopped", "failed"} for item in self._host.list_runtimes()):
                raise LifecycleError("RESET_PARTIAL_FAILURE", "Runtime Reset left an active runtime")
            self._host._lifecycle_maintenance_state = "ENABLED"
            operation["state"] = "COMPLETED"
            operation["current_step"] = "COMPLETE"
            operation["updated_at"] = _timestamp()
            operation["error"] = None
            self._lifecycle._persist()
            self._lifecycle._emit("aidn.node.reset_completed", "Runtime Reset completed", resource_type="node", resource_id=getattr(self._host, "node_id", "node"), details={"reset_id": reset_id, "profile": profile})
            return deepcopy(operation)
        except LifecycleError as error:
            self._host._lifecycle_maintenance_state = "PAUSED_MAINTENANCE"
            operation["state"] = "PARTIALLY_APPLIED"
            operation["current_step"] = "FAILED"
            operation["error"] = error.as_detail()
            operation["updated_at"] = _timestamp()
            self._lifecycle._persist()
            self._lifecycle._emit("aidn.node.reset_failed", error.message, resource_type="node", resource_id=getattr(self._host, "node_id", "node"), details={"reset_id": reset_id, **error.as_detail()})
            raise
