"""MCP surface for the Resident Steward (RFC-0075).

Kept as an extension module so the mature MCP catalog remains easy to audit.
The extension is installed once by :mod:`aidn_hypervisor.mcp.server` after the
core control-plane classes have been defined.
"""

from __future__ import annotations

from typing import Any


def _string(arguments: dict[str, Any], key: str, *, required: bool = False) -> str | None:
    value = arguments.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _steward_status(self) -> dict[str, Any]:
    fn = getattr(self.service, "resident_agent_status", None)
    if not callable(fn):
        return {"available": False, "reason": "resident_agent_unavailable"}
    return fn()


def _steward_context(self) -> dict[str, Any]:
    fn = getattr(self.service, "resident_agent_context", None)
    if not callable(fn):
        return {"available": False, "reason": "resident_agent_unavailable"}
    payload = dict(fn() or {})
    payload.setdefault("schema_version", 1)
    omitted = payload.get("omitted")
    payload["omitted"] = ["full event payloads"]
    if omitted is True:
        payload["omitted"].append("long transcript fields")
    return payload


def _steward_installation_workflow(self) -> dict[str, Any]:
    """Return the bounded, restart-safe assisted installer projection."""

    fn = getattr(self.service, "installation_plan", None)
    if not callable(fn):
        return {"available": False, "reason": "installation_workflow_unavailable"}
    plan = dict(fn() or {})
    model = plan.get("model")
    model = model if isinstance(model, dict) else {}
    return {
        "available": bool(plan.get("available")),
        "integrity": plan.get("integrity"),
        "status": plan.get("status"),
        "mode": plan.get("mode"),
        "ai_assisted": bool(plan.get("ai_assisted")),
        "plan_hash": plan.get("plan_hash"),
        "provider": plan.get("provider"),
        "model": {"id": model.get("id"), "source": model.get("source")},
        "workflow": plan.get("workflow"),
        "authority": {
            "provider_installation": "operator_approval_required",
            "model_processing": "explicit_plan_action",
            "publication": "validation_and_operator_policy_required",
        },
    }


def _steward_decide(self, arguments: dict[str, Any]) -> dict[str, Any]:
    goal = _string(arguments, "goal", required=True)
    fn = getattr(self.service, "resident_agent_decide", None)
    if not callable(fn):
        return {"available": False, "reason": "resident_agent_unavailable"}
    return fn(
        goal,
        event_id=_string(arguments, "event_id"),
        event_type=_string(arguments, "event_type"),
        correlation_id=_string(arguments, "correlation_id"),
        causation_id=_string(arguments, "causation_id"),
        automation_depth=int(arguments.get("automation_depth", 0) or 0),
    )


def _steward_action_guard(self, arguments: dict[str, Any]) -> dict[str, Any]:
    action = _string(arguments, "action", required=True)
    fn = getattr(self.service, "resident_agent_guard_action", None)
    if not callable(fn):
        return {"allowed": False, "code": "STEWARD_UNAVAILABLE"}
    return fn(
        action,
        target_id=_string(arguments, "target_id"),
        event_id=_string(arguments, "event_id"),
        event_type=_string(arguments, "event_type"),
        correlation_id=_string(arguments, "correlation_id"),
        causation_id=_string(arguments, "causation_id"),
        automation_depth=int(arguments.get("automation_depth", 0) or 0),
        cooldown_seconds=arguments.get("cooldown_seconds"),
    )


def _steward_action_policy(self) -> dict[str, Any]:
    fn = getattr(self.service, "resident_agent_action_policy", None)
    if not callable(fn):
        return {"available": False, "reason": "resident_agent_unavailable"}
    return fn()


def _steward_action_execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
    fn = getattr(self.service, "resident_agent_execute_action", None)
    if not callable(fn):
        return {"available": False, "reason": "resident_agent_unavailable"}
    action = _string(arguments, "action", required=True)
    target_id = _string(arguments, "target_id", required=True)
    mode = str(arguments.get("mode") or "plan")
    plan_hash = arguments.get("plan_hash")
    # The outer MCP plan/approval boundary is authoritative.  The reference
    # is synthesized only after _call_mutating has verified the approved plan.
    approval_reference = arguments.get("approval_reference")
    if mode == "apply" and not approval_reference:
        approval_reference = f"mcp-approved:{plan_hash}"
    try:
        return fn(
            action,
            target_id=target_id,
            mode=mode,
            plan_hash=plan_hash,
            approval_reference=approval_reference,
            event_id=_string(arguments, "event_id"),
            event_type=_string(arguments, "event_type"),
            correlation_id=_string(arguments, "correlation_id"),
            causation_id=_string(arguments, "causation_id"),
            automation_depth=int(arguments.get("automation_depth", 0) or 0),
            cooldown_seconds=arguments.get("cooldown_seconds"),
        )
    except ValueError as error:
        raise RuntimeError(f"MCP_STEWARD_ACTION_INVALID: {error}") from error


def _steward_reasoning_providers(self) -> dict[str, Any]:
    fn = getattr(self.service, "reasoning_provider_list", None)
    if not callable(fn):
        return {"available": False, "reason": "reasoning_router_unavailable"}
    return fn()


def _steward_reasoning_route(self, arguments: dict[str, Any]) -> dict[str, Any]:
    fn = getattr(self.service, "reasoning_route", None)
    if not callable(fn):
        return {"available": False, "reason": "reasoning_router_unavailable"}
    values = dict(arguments or {})
    values.setdefault("budget_remaining_q_atoms", 0)
    return fn(values, budget_remaining_q_atoms=values["budget_remaining_q_atoms"])


def _steward_reasoning_invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
    fn = getattr(self.service, "reasoning_invoke", None)
    if not callable(fn):
        return {"available": False, "reason": "reasoning_adapter_unavailable"}
    return fn(
        _string(arguments, "prompt", required=True),
        route=dict(arguments.get("route") or {}),
        timeout_seconds=float(arguments.get("timeout_seconds", 90) or 90),
        stream=bool(arguments.get("stream", False)),
        parameters=dict(arguments.get("parameters") or {}),
    )


def _steward_escalations(self, arguments: dict[str, Any]) -> dict[str, Any]:
    fn = getattr(self.service, "escalation_task_list", None)
    if not callable(fn):
        return {"available": False, "reason": "escalation_service_unavailable"}
    state = _string(arguments, "state")
    limit = int(arguments.get("limit", 100) or 100)
    return {"items": fn(state=state, limit=max(1, min(500, limit)))}


def _steward_escalate(self, arguments: dict[str, Any]) -> dict[str, Any]:
    fn = getattr(self.service, "escalation_task_create", None)
    if not callable(fn):
        return {"available": False, "reason": "escalation_service_unavailable"}
    return fn(dict(arguments or {}), owner_id=self.session.agent_identity, control_session_id=self.session.control_session_id)


def _steward_escalation_get(self, arguments: dict[str, Any]) -> dict[str, Any]:
    fn = getattr(self.service, "escalation_task_get", None)
    if not callable(fn):
        return {"available": False, "reason": "escalation_service_unavailable"}
    return fn(_string(arguments, "task_id", required=True))


def _steward_escalation_plan(self, arguments: dict[str, Any]) -> dict[str, Any]:
    fn = getattr(self.service, "escalation_task_set_plan", None)
    if not callable(fn):
        return {"available": False, "reason": "escalation_service_unavailable"}
    return fn(
        _string(arguments, "task_id", required=True),
        dict(arguments.get("plan") or {}),
        idempotency_key=_string(arguments, "idempotency_key", required=True),
        requires_operator_approval=arguments.get("requires_operator_approval"),
    )


def _steward_escalation_verify(self, arguments: dict[str, Any]) -> dict[str, Any]:
    fn = getattr(self.service, "escalation_task_verify", None)
    if not callable(fn):
        return {"available": False, "reason": "escalation_service_unavailable"}
    return fn(_string(arguments, "task_id", required=True), observed=dict(arguments.get("observed") or {}))


def _steward_escalation_cancel(self, arguments: dict[str, Any]) -> dict[str, Any]:
    fn = getattr(self.service, "escalation_task_cancel", None)
    if not callable(fn):
        return {"available": False, "reason": "escalation_service_unavailable"}
    return fn(_string(arguments, "task_id", required=True), reason=_string(arguments, "reason") or "cancelled")


def _install_plan_wrapper(control_cls: type, original: Any) -> Any:
    def _build_plan(self, tool: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool.name != "aidn.steward.action_execute":
            return original(self, tool, arguments)
        service_plan = self.service._resident_agent_action_plan(
            str(arguments.get("action") or ""),
            str(arguments.get("target_id") or ""),
            event_id=arguments.get("event_id"),
            event_type=arguments.get("event_type"),
            correlation_id=arguments.get("correlation_id"),
            causation_id=arguments.get("causation_id"),
            automation_depth=int(arguments.get("automation_depth", 0) or 0),
        )
        plan = {
            **service_plan,
            "tool": tool.name,
            "request_id": arguments.get("request_id"),
            "target": arguments.get("target_id"),
            "arguments": self._plan_arguments(arguments),
            "changes": list(service_plan.get("changes") or []),
            "risks": ["bounded local action; normal policy and resource checks apply"],
            "estimated_downtime_seconds": 30,
            "estimated_q_atoms": 0,
            "validation_impact": "UNCHANGED",
        }
        self._plans[plan["plan_hash"]] = plan
        return plan

    return _build_plan


def install_steward_extensions(control_cls: type, tool_cls: type, resource_cls: type) -> None:
    """Install Steward tools/resources on the core MCP control plane once."""

    if getattr(control_cls, "_steward_extensions_installed", False):
        return
    methods = {
        "_steward_status": _steward_status,
        "_steward_context": _steward_context,
        "_steward_installation_workflow": _steward_installation_workflow,
        "_steward_decide": _steward_decide,
        "_steward_action_guard": _steward_action_guard,
        "_steward_action_policy": _steward_action_policy,
        "_steward_action_execute": _steward_action_execute,
        "_steward_reasoning_providers": _steward_reasoning_providers,
        "_steward_reasoning_route": _steward_reasoning_route,
        "_steward_reasoning_invoke": _steward_reasoning_invoke,
        "_steward_escalations": _steward_escalations,
        "_steward_escalate": _steward_escalate,
        "_steward_escalation_get": _steward_escalation_get,
        "_steward_escalation_plan": _steward_escalation_plan,
        "_steward_escalation_verify": _steward_escalation_verify,
        "_steward_escalation_cancel": _steward_escalation_cancel,
    }
    for name, fn in methods.items():
        setattr(control_cls, name, fn)

    original_tools = control_cls._build_tools
    original_resources = control_cls._build_resources
    original_plan = control_cls._build_plan

    def _build_tools(self):
        tools = original_tools(self)
        read = {"type": "object", "properties": {}, "additionalProperties": False}
        decide = {"type": "object", "properties": {"goal": {"type": "string", "minLength": 1}}, "required": ["goal"], "additionalProperties": False}
        guard = {"type": "object", "properties": {"action": {"type": "string"}, "target_id": {"type": "string"}, "event_id": {"type": "string"}, "event_type": {"type": "string"}, "correlation_id": {"type": "string"}, "causation_id": {"type": "string"}, "automation_depth": {"type": "integer", "minimum": 0}, "cooldown_seconds": {"type": "integer", "minimum": 0}}, "required": ["action"], "additionalProperties": False}
        route = {"type": "object", "properties": {"capability": {"type": "string"}, "complexity": {"type": "string"}, "minimum_context": {"type": "integer", "minimum": 1}, "data_class": {"type": "string"}, "allow_external": {"type": "boolean"}, "budget_remaining_q_atoms": {"type": "integer", "minimum": 0}}, "additionalProperties": False}
        invoke = {"type": "object", "properties": {"prompt": {"type": "string", "minLength": 1, "maxLength": 131072}, "route": {"type": "object"}, "timeout_seconds": {"type": "number", "minimum": 0.1, "maximum": 3600}, "stream": {"type": "boolean"}, "parameters": {"type": "object"}, "mode": {"enum": ["plan", "apply"]}, "request_id": {"type": "string", "minLength": 1}, "idempotency_key": {"type": "string", "minLength": 1}, "plan_hash": {"type": "string"}}, "required": ["prompt", "mode", "request_id", "idempotency_key"], "additionalProperties": False}
        create = {"type": "object", "properties": {"goal": {"type": "string", "minLength": 1}, "task_class": {"type": "string"}, "data_class": {"type": "string"}, "route": {"type": "object"}, "context": {"type": "object"}, "idempotency_key": {"type": "string"}, "correlation_id": {"type": "string"}, "causation_id": {"type": "string"}, "expires_in_seconds": {"type": "integer", "minimum": 60}}, "required": ["goal"], "additionalProperties": False}
        execute = {"type": "object", "properties": {"action": {"type": "string", "minLength": 1}, "target_id": {"type": "string", "minLength": 1}, "mode": {"enum": ["plan", "apply"]}, "request_id": {"type": "string", "minLength": 1}, "idempotency_key": {"type": "string", "minLength": 1}, "plan_hash": {"type": "string"}, "approval_reference": {"type": "string"}, "event_id": {"type": "string"}, "event_type": {"type": "string"}, "correlation_id": {"type": "string"}, "causation_id": {"type": "string"}, "automation_depth": {"type": "integer", "minimum": 0}, "cooldown_seconds": {"type": "integer", "minimum": 0}}, "required": ["action", "target_id", "mode", "request_id", "idempotency_key"], "additionalProperties": False}
        escalation_plan = {"type": "object", "properties": {"task_id": {"type": "string", "minLength": 1}, "request_id": {"type": "string"}, "idempotency_key": {"type": "string"}, "plan": {"type": "object"}, "requires_operator_approval": {"type": "boolean"}}, "required": ["task_id", "idempotency_key", "plan"], "additionalProperties": False}
        escalation_cancel = {"type": "object", "properties": {"task_id": {"type": "string", "minLength": 1}, "reason": {"type": "string"}}, "required": ["task_id"], "additionalProperties": False}
        escalation_get = {"type": "object", "properties": {"task_id": {"type": "string", "minLength": 1}}, "required": ["task_id"], "additionalProperties": False}
        tools.update({
            "aidn.steward.status": tool_cls("aidn.steward.status", "Return Resident Steward status.", read, ("STEWARD:READ",), "READ_ONLY", lambda _a: self._steward_status()),
            "aidn.steward.context": tool_cls("aidn.steward.context", "Return bounded redacted Steward context.", read, ("STEWARD:READ",), "READ_ONLY", lambda _a: self._steward_context()),
            "aidn.steward.installation_workflow": tool_cls("aidn.steward.installation_workflow", "Return the bounded assisted-installation workflow and next action.", read, ("STEWARD:READ",), "READ_ONLY", lambda _a: self._steward_installation_workflow()),
            "aidn.steward.decide": tool_cls("aidn.steward.decide", "Return a read-only Steward recommendation.", decide, ("STEWARD:READ",), "READ_ONLY", lambda a: self._steward_decide(a)),
            "aidn.steward.action_guard": tool_cls("aidn.steward.action_guard", "Guard a bounded action without executing it.", guard, ("STEWARD:GUARD",), "READ_ONLY", lambda a: self._steward_action_guard(a)),
            "aidn.steward.action_policy": tool_cls("aidn.steward.action_policy", "Return Steward action policy.", read, ("STEWARD:EXECUTE",), "READ_ONLY", lambda _a: self._steward_action_policy()),
            "aidn.steward.action_execute": tool_cls("aidn.steward.action_execute", "Plan or apply one allow-listed Steward action.", execute, ("STEWARD:EXECUTE",), "STEWARD_EXECUTE", lambda a: self._steward_action_execute(a), mutating=True, approval_key="steward_execute"),
            "aidn.steward.reasoning.providers": tool_cls("aidn.steward.reasoning.providers", "List reasoning providers.", read, ("STEWARD:READ",), "READ_ONLY", lambda _a: self._steward_reasoning_providers()),
            "aidn.steward.reasoning.route": tool_cls("aidn.steward.reasoning.route", "Select a reasoning provider without execution.", route, ("STEWARD:READ",), "READ_ONLY", lambda a: self._steward_reasoning_route(a)),
            "aidn.steward.reasoning.invoke": tool_cls("aidn.steward.reasoning.invoke", "Route and invoke one approved reasoning provider.", invoke, ("STEWARD:REASON",), "STEWARD_REASON", lambda a: self._steward_reasoning_invoke(a), mutating=True, approval_key="steward_reason"),
            "aidn.steward.escalations": tool_cls("aidn.steward.escalations", "List reasoning escalations.", read, ("STEWARD:READ",), "READ_ONLY", lambda a: self._steward_escalations(a)),
            "aidn.steward.escalate": tool_cls("aidn.steward.escalate", "Create a durable reasoning escalation.", create, ("STEWARD:ESCALATE",), "STEWARD_ESCALATE", lambda a: self._steward_escalate(a)),
            "aidn.steward.escalation.get": tool_cls("aidn.steward.escalation.get", "Read one escalation task.", escalation_get, ("STEWARD:READ",), "READ_ONLY", lambda a: self._steward_escalation_get(a)),
            "aidn.steward.escalation.plan": tool_cls("aidn.steward.escalation.plan", "Attach a typed plan to an escalation; execution remains separate.", escalation_plan, ("STEWARD:ESCALATE",), "STEWARD_ESCALATE", lambda a: self._steward_escalation_plan(a)),
            "aidn.steward.escalation.cancel": tool_cls("aidn.steward.escalation.cancel", "Cancel an escalation without executing its plan.", escalation_cancel, ("STEWARD:ESCALATE",), "STEWARD_ESCALATE", lambda a: self._steward_escalation_cancel(a)),
        })
        return tools

    def _build_resources(self):
        resources = original_resources(self)
        resources.update({
            "aidn://steward/status": resource_cls("aidn://steward/status", "Steward status", "Resident Steward status.", "STEWARD:READ", lambda _u: self._steward_status()),
            "aidn://steward/context": resource_cls("aidn://steward/context", "Steward context", "Bounded Steward context.", "STEWARD:READ", lambda _u: self._steward_context()),
            "aidn://steward/installation": resource_cls("aidn://steward/installation", "Steward installation workflow", "Assisted installation workflow.", "STEWARD:READ", lambda _u: self._steward_installation_workflow()),
            "aidn://steward/reasoning/providers": resource_cls("aidn://steward/reasoning/providers", "Reasoning providers", "Available reasoning providers.", "STEWARD:READ", lambda _u: self._steward_reasoning_providers()),
            "aidn://steward/escalations": resource_cls("aidn://steward/escalations", "Steward escalations", "Durable escalation tasks.", "STEWARD:READ", lambda _u: self._steward_escalations({})),
        })
        return resources

    control_cls._build_tools = _build_tools
    control_cls._build_resources = _build_resources
    control_cls._build_plan = _install_plan_wrapper(control_cls, original_plan)
    control_cls._steward_extensions_installed = True
