"""Agent-mediated presentation and the first real settings-edit vertical slice."""

from __future__ import annotations

from copy import deepcopy

from aidn_hypervisor.agent_interface import InterfaceField, PresentationRequest, revision
from aidn_hypervisor.endpoints.models import UpdateEndpointCommand
from aidn_hypervisor.runtime_parameter_policy import default_runtime_parameter_policy, policy_json
from aidn_hypervisor.session_read_models import build_operator_sessions_payload

REQUEST_PARAMETERS = {
    "temperature",
    "top_p",
    "top_k",
    "repeat_penalty",
    "max_tokens",
    "frequency_penalty",
    "presence_penalty",
}


def _field(key, label, value, **kwargs):
    kind = (
        "boolean"
        if isinstance(value, bool)
        else "integer"
        if isinstance(value, int)
        else "number"
        if isinstance(value, float)
        else "text"
    )
    return InterfaceField(id=key, label=label, value=value, type=kwargs.pop("type", kind), **kwargs).model_dump()


def _endpoint_source(control, endpoint_id):
    if control.endpoint_service is None:
        raise ValueError("Endpoint service is unavailable")
    endpoint = control.endpoint_service.get_endpoint(endpoint_id).endpoint
    published = (
        control.endpoint_publication_service is not None
        and control.endpoint_publication_service.current_publication(endpoint_id) is not None
    )
    writable = "ENDPOINT:WRITE" in control.session.scopes and endpoint.status != "deleted"
    draft = writable and not published
    fields = [
        _field(
            "display_name",
            "Название endpoint",
            endpoint.display_name,
            editable=draft,
            description="Изменение опубликованной конфигурации требует отдельной ревизии."
            if published
            else "Название в конфигурации endpoint.",
        ),
        _field(
            "local_agent_use",
            "Разрешить использование локальным агентом",
            endpoint.local_agent_use,
            editable=writable,
            description="Локальное разрешение доступа. Применяется отдельно от остальных настроек.",
        ),
        _field("endpoint_id", "Endpoint", endpoint.endpoint_id),
        _field("bundle_id", "Bundle", endpoint.bundle_id),
        _field("model_class", "Тип модели", endpoint.model_class),
        _field("status", "Состояние", endpoint.status),
    ]
    bundle = next((item for item in control.service.bundle_config() if item.bundle_id == endpoint.bundle_id), None)
    defaults = default_runtime_parameter_policy(bundle.provider_type) if bundle else {}
    policy = policy_json(endpoint.runtime_parameter_policy)
    for name, setting in policy.items():
        value = setting["value"]
        if not isinstance(value, (str, bool, int, float)):
            continue
        bounds = defaults.get(name)
        limits = {"minimum": setting.get("min"), "maximum": setting.get("max")}
        if bounds is not None:
            if bounds.minimum is not None:
                limits["minimum"] = (
                    max(bounds.minimum, limits["minimum"]) if limits["minimum"] is not None else bounds.minimum
                )
            if bounds.maximum is not None:
                limits["maximum"] = (
                    min(bounds.maximum, limits["maximum"]) if limits["maximum"] is not None else bounds.maximum
                )
        fields.append(
            _field(
                "parameter." + name,
                name,
                value,
                # Type follows the canonical parameter, not today's value:
                # temperature=0 must not turn the next form into an integer field.
                type="integer"
                if name in {"top_k", "max_tokens", "context_length", "gpu_layers"}
                else "number"
                if bounds is not None and isinstance(bounds.value, float)
                else _field(name, name, value)["type"],
                editable=draft and name in REQUEST_PARAMETERS and bounds is not None,
                description=(
                    "Значение по умолчанию для запросов к endpoint."
                    if name in REQUEST_PARAMETERS
                    else "Параметр размещения модели. Изменение через ревизию Bundle будет добавлено отдельно."
                ),
                **limits,
            )
        )
    # Full manifest hash also covers local access and display_name, which the
    # publication configuration_hash deliberately does not cover.
    return {
        "revision": revision({"endpoint": endpoint.model_dump(mode="json"), "published": published}),
        "fields": fields,
    }


def _scene_payload(control):
    control.session.require("NODE:READ", "ENDPOINT:READ", "BUNDLE:READ", "AUDIT:READ")
    fleet = control.service.operator_dashboard_fleet()
    from aidn_hypervisor.operator_views import build_operator_endpoints_payload

    endpoint_payload = build_operator_endpoints_payload(
        service=control.service,
        endpoint_service=control.endpoint_service,
        endpoint_publication_service=control.endpoint_publication_service,
        validation_service=control.validation_service,
    )
    session_service = control.session_service
    sessions = build_operator_sessions_payload(
        service=control.service, endpoint_service=control.endpoint_service, session_service=session_service
    )
    # The renderer needs identities/relationships, not private configuration,
    # wallet data, logs, prompts, credentials, or complete runtime descriptors.
    endpoint_keys = (
        "endpoint_id",
        "display_name",
        "bundle_id",
        "model_class",
        "capabilities",
        "local_agent_use",
        "publication_status",
        "runtime_status",
        "publication_ready",
    )
    bundle_keys = ("bundle_id", "model_id", "enabled", "registry_status", "revision")
    endpoints = [
        {key: item[key] for key in endpoint_keys if key in item} for item in endpoint_payload.get("items", [])[:128]
    ]
    bundles = [{key: item[key] for key in bundle_keys if key in item} for item in fleet.get("bundles", [])[:128]]
    session_items = [
        {
            "session": {key: item.get("session", {}).get(key) for key in ("session_id", "endpoint_id", "status")},
            "display_name": item.get("display_name", ""),
        }
        for item in sessions.get("items", [])[:200]
    ]
    resources = {
        key: {name: values.get(name, 0) for name in ("cpu", "ram_mb", "vram_mb")}
        for key, values in fleet["resources"].items()
        if key in {"total", "reserved", "free"}
    }
    return {
        "node_id": control.service.node_id,
        "agent_id": control.session.agent_identity,
        "fleet": {
            "node": {"node_id": control.service.node_id},
            "resources": resources,
            "queue": {key: fleet["queue"].get(key, 0) for key in ("queued", "active", "completed", "failed")},
            "bundles": bundles,
        },
        "endpoints": {"summary": endpoint_payload.get("summary", {}), "items": endpoints},
        "sessions": {"summary": sessions.get("summary", {}), "items": session_items},
        "failures": ["protocol-sessions-unavailable"] if session_service is None else [],
    }


def read_source(control, arguments):
    channel = control.service.agent_channel
    context = channel.request_context(agent_id=control.session.agent_identity, request_id=arguments["request_id"])
    kind = arguments.get("kind")
    target_id = arguments.get("target_id")
    data = None
    if kind == "endpoint":
        control.session.require("ENDPOINT:READ")
        if not isinstance(target_id, str) or not target_id:
            raise ValueError("Resolve one exact endpoint_id using aidn.endpoint.list first")
        result = _endpoint_source(control, target_id)
    elif kind == "bundle":
        control.session.require("BUNDLE:READ")
        bundle = next((item for item in control.service.bundle_config() if item.bundle_id == target_id), None)
        if bundle is None:
            raise ValueError("Resolve one exact bundle_id using aidn.bundle.list first")
        fields = [
            _field(key, key, str(getattr(bundle, key)))
            for key in ("bundle_id", "provider_type", "model_id", "launch_mode", "device_affinity")
        ]
        fields += [
            _field(
                "parameter." + key,
                key,
                setting.value,
                description="Параметр Bundle. Изменение требует новой ревизии; этот frame пока только для просмотра.",
            )
            for key, setting in bundle.runtime_parameter_policy.items()
            if isinstance(setting.value, (str, bool, int, float))
        ]
        result = {"fields": fields, "revision": revision(bundle.model_dump(mode="json"))}
    elif kind == "provider":
        control.session.require("PROVIDER:READ")
        provider = next(
            (
                item
                for item in control.service.list_provider_instances()
                if item.get("provider_instance_id") == target_id
            ),
            None,
        )
        if provider is None:
            raise ValueError("Resolve one exact provider_instance_id using aidn.provider.list first")
        safe = {
            key: provider[key]
            for key in ("provider_instance_id", "display_name", "plugin_id", "provider_type", "status", "health_status")
            if isinstance(provider.get(key), (str, bool, int, float))
        }
        result = {"fields": [_field(key, key, value) for key, value in safe.items()], "revision": revision(safe)}
    elif kind == "scene":
        data = _scene_payload(control)
        channel.publish_workspace(agent_id=control.session.agent_identity, request_id=arguments["request_id"])
        target_id = control.service.node_id
        result = {"fields": [], "revision": revision(data)}
    else:
        raise ValueError("Unsupported source kind")
    source = channel.interface.register_source(
        surface_id=context.surface_id,
        kind=kind,
        target_id=target_id,
        source_revision=result["revision"],
        fields=result["fields"],
        data=data,
    )
    # A model need not copy the graph through its token stream to publish it.
    return {key: value for key, value in source.items() if key != "data"}


def apply_change(control, arguments):
    channel = control.service.agent_channel
    intent_id = arguments["intent_id"]
    channel.request_context(agent_id=control.session.agent_identity, request_id=intent_id)
    with channel.interface.apply_lock:
        intent = channel.interface.intent(intent_id)
        if intent["state"] == "APPLIED":
            return intent["result"]
        target = intent["target"]
        if target["kind"] != "endpoint":
            raise ValueError("This slice supports endpoint changes only")
        current = _endpoint_source(control, target["id"])
        if current["revision"] != target["revision"]:
            raise ValueError("The endpoint changed since this form was read. Refresh before applying.")
        fields = {item["id"]: InterfaceField.model_validate(item) for item in current["fields"]}
        for delta in intent["diff"]:
            field = fields.get(delta["path"])
            if field is None or not field.editable:
                raise ValueError("This field is no longer editable")
            field.validate_value(delta["to"])
        changes = {item["path"]: item["to"] for item in intent["diff"]}
        endpoint = control.endpoint_service.get_endpoint(target["id"]).endpoint
        if "local_agent_use" in changes:
            if len(changes) != 1:
                raise ValueError("Apply local agent access separately")
            control.endpoint_service.set_local_agent_use(target["id"], enabled=changes["local_agent_use"])
        else:
            payload = {"endpoint_id": target["id"]}
            if "display_name" in changes:
                payload["display_name"] = changes["display_name"]
            policy = deepcopy(policy_json(endpoint.runtime_parameter_policy))
            changed_policy = False
            for key, value in changes.items():
                if key.startswith("parameter."):
                    name = key.removeprefix("parameter.")
                    if name not in REQUEST_PARAMETERS or name not in policy:
                        raise ValueError("Unsupported request parameter")
                    policy[name]["value"] = value
                    changed_policy = True
            if changed_policy:
                payload["runtime_parameter_policy"] = policy
            control.endpoint_application_service.update_endpoint(
                target["id"], UpdateEndpointCommand.model_validate(payload)
            )
        verified = _endpoint_source(control, target["id"])
        actual = {item["id"]: item["value"] for item in verified["fields"]}
        if any(actual.get(key) != value for key, value in changes.items()):
            raise ValueError("Read-back did not confirm all changes. Inspect the endpoint before retrying.")
        source = channel.interface.register_source(
            surface_id=intent["surface_id"],
            kind="endpoint",
            target_id=target["id"],
            source_revision=verified["revision"],
            fields=verified["fields"],
        )
        result = {
            "state": "APPLIED",
            "intent_id": intent_id,
            "source": source,
            "document_id": intent["change"]["document_id"],
            "verified": True,
        }
        channel.interface.complete(intent_id, result)
        return result


def build_interface_tools(control):
    from aidn_hypervisor.mcp.server import McpTool

    return {
        "aidn.ui.conversation": McpTool(
            "aidn.ui.conversation",
            "Accept/open the exact operator Workspace conversation request and publish its canonical transcript and artifact. Creates one semantic session/cube on first message, never a paid protocol Session. Replays are idempotent. No invented text or session IDs are accepted.",
            {
                "type": "object",
                "properties": {"request_id": {"type": "string"}},
                "required": ["request_id"],
                "additionalProperties": False,
            },
            ("CHAT:WRITE",),
            "OPERATOR_CHAT_REPLY",
            lambda args: control.service.agent_channel.accept_conversation(
                agent_id=control.session.agent_identity, request_id=args["request_id"]
            ),
        ),
        "aidn.ui.read": McpTool(
            "aidn.ui.read",
            "Read authoritative fields for an operator's Spatial request. First resolve exact IDs through domain MCP tools. Returns a source_id for aidn.ui.present; never invent values or editable flags.",
            {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string"},
                    "kind": {"enum": ["provider", "bundle", "endpoint", "scene"]},
                    "target_id": {"type": "string"},
                },
                "required": ["request_id", "kind"],
                "additionalProperties": False,
            },
            ("CHAT:WRITE",),
            "READ_ONLY",
            lambda args: read_source(control, args),
        ),
        "aidn.ui.present": McpTool(
            "aidn.ui.present",
            "Publish/update an agent-authored document from text and fields blocks. Fields reference a source_id from aidn.ui.read and optional field_ids. Reuse document_id when updating the same frame. To publish the scene pass its scene_source_id.",
            PresentationRequest.model_json_schema(),
            ("CHAT:WRITE",),
            "OPERATOR_CHAT_REPLY",
            lambda args: control.service.agent_channel.present(agent_id=control.session.agent_identity, payload=args),
        ),
        "aidn.ui.apply": McpTool(
            "aidn.ui.apply",
            "Plan/apply the exact operator-submitted form intent. No replacement values are accepted. Canonical validation, permissions, revision and read-back are enforced. After apply use aidn.ui.present with the returned source and SAME document_id. If approval is required, report it; do not approve on the operator's behalf.",
            {
                "type": "object",
                "properties": {
                    "intent_id": {"type": "string"},
                    "mode": {"enum": ["plan", "apply"]},
                    "request_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                    "plan_hash": {"type": "string"},
                },
                "required": ["intent_id", "mode", "request_id", "idempotency_key"],
                "additionalProperties": False,
            },
            ("CHAT:WRITE", "ENDPOINT:READ", "ENDPOINT:WRITE"),
            "ENDPOINT_MUTATION",
            lambda args: apply_change(control, args),
            mutating=True,
            approval_key="endpoint_write",
        ),
    }


def intent_revision(control, intent_id):
    channel = control.service.agent_channel
    channel.request_context(agent_id=control.session.agent_identity, request_id=intent_id)
    intent = channel.interface.intent(intent_id)
    if intent["state"] == "APPLIED":
        return intent["target"]["revision"]
    if intent["target"]["kind"] != "endpoint":
        raise ValueError("Unsupported form target")
    current = _endpoint_source(control, intent["target"]["id"])
    if current["revision"] != intent["target"]["revision"]:
        raise ValueError("The endpoint changed since this form was read. Refresh before applying.")
    return current["revision"]
