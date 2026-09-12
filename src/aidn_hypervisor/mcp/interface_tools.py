"""Agent-mediated presentation and the first real settings-edit vertical slice."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from aidn_hypervisor.agent_interface import InterfaceField, PresentationRequest, revision
from aidn_hypervisor.endpoints.models import UpdateEndpointCommand
from aidn_hypervisor.installation_onboarding import CONTEXT_LENGTH_CHOICES
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

INSTALLATION_PROVIDER_OPTIONS = ["llama.cpp", "ollama", "vllm"]
INSTALLATION_ENDPOINT_OPTIONS = ["draft", "start", "skip"]
INSTALLATION_CONTEXT_OPTIONS = [str(item) for item in CONTEXT_LENGTH_CHOICES]
INSTALLATION_TARIFF_DIMENSIONS = [
    "request_count",
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
]


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


def _installation_plan_source(control):
    """Expose the persisted installation intent as safe native form fields.

    The JSON plan remains the canonical owner-readable record.  This source is
    only a projection for ``aidn.ui.present``: no arbitrary HTML or model
    authored values are accepted, and the confirmation checkbox is reset after
    every successful revision so a replay cannot start another install.
    """

    control.session.require("NODE:READ")
    plan = control.service.installation_plan()
    if not isinstance(plan, Mapping) or not plan.get("available"):
        raise ValueError("No AI-assisted installation plan is available; prepare one first")
    model = plan.get("model") if isinstance(plan.get("model"), Mapping) else {}
    runtime = plan.get("runtime_policy") if isinstance(plan.get("runtime_policy"), Mapping) else {}
    context = runtime.get("context_length") if isinstance(runtime.get("context_length"), Mapping) else {}
    replacement = plan.get("replacement_policy") if isinstance(plan.get("replacement_policy"), Mapping) else {}
    publication = plan.get("publication_policy") if isinstance(plan.get("publication_policy"), Mapping) else {}
    tariff = publication.get("tariff") if isinstance(publication.get("tariff"), Mapping) else None
    # Keep tariff controls visible in the first review even while pricing is
    # still ``ask``.  They are recommendations, not an implicit charge; the
    # apply path drops them for a free endpoint and requires a positive price
    # for a paid endpoint.
    tariff_view = {
        "kind": str((tariff or {}).get("kind") or "metered"),
        "dimension": str((tariff or {}).get("dimension") or "request_count"),
        "unit_price_q_atoms": int((tariff or {}).get("unit_price_q_atoms") or 0),
        "unit_divisor": int((tariff or {}).get("unit_divisor") or 1),
        "minimum_charge_q_atoms": int((tariff or {}).get("minimum_charge_q_atoms") or 0),
    }
    fallbacks = {int(item) for item in context.get("fallbacks", []) if str(item).isdigit()}
    requested_context = int(context.get("requested") or CONTEXT_LENGTH_CHOICES[0])
    fields = [
        _field(
            "installation.plan_hash",
            "Хэш плана",
            str(plan.get("plan_hash") or ""),
            description="Ревизия защищает форму от устаревших ответов; агент применит только этот план.",
        ),
        _field(
            "installation.provider",
            "Провайдер",
            str(plan.get("provider") or "llama.cpp"),
            type="select",
            options=INSTALLATION_PROVIDER_OPTIONS,
            editable=True,
            description="Рекомендуемый провайдер можно изменить до начала установки.",
        ),
        _field(
            "installation.model_id",
            "Идентификатор модели",
            str(model.get("id") or ""),
            editable=True,
            description="Путь/идентификатор модели, который агент передаст выбранному провайдеру.",
        ),
        _field(
            "installation.model_source",
            "Источник модели",
            str(model.get("source") or ""),
            editable=True,
            description="HTTPS или hf:// источник конкретного артефакта; секреты и query-параметры запрещены.",
        ),
        _field(
            "installation.endpoint_action",
            "Действие после Bundle",
            str((plan.get("endpoint") or {}).get("requested_action") or "draft"),
            type="select",
            options=INSTALLATION_ENDPOINT_OPTIONS,
            editable=True,
            description="draft создаёт конфигурацию, start дополнительно запускает private Endpoint.",
        ),
        _field(
            "runtime.context_length.requested",
            "Запрошенный контекст",
            str(requested_context),
            type="select",
            options=INSTALLATION_CONTEXT_OPTIONS,
            editable=True,
            description="Сначала проверяется этот размер; затем включённые fallback-значения по порядку.",
        ),
        _field(
            "runtime.context_length.fallback_65536",
            "Разрешить fallback 64K",
            65_536 in fallbacks,
            type="boolean",
            editable=True,
            description="Если 128K не проходит Resource Broker, попробовать 64K.",
        ),
        _field(
            "runtime.context_length.fallback_32768",
            "Разрешить fallback 32K",
            32_768 in fallbacks,
            type="boolean",
            editable=True,
            description="Если предыдущие варианты не проходят, попробовать 32K.",
        ),
        _field(
            "runtime.context_length.on_exhausted",
            "Если места не хватило",
            str(context.get("on_exhausted") or "notify"),
            type="select",
            options=["notify", "ask", "stop"],
            editable=True,
            description="После отказа всех размеров агент сообщает дефицит и не регистрирует Bundle.",
        ),
        _field(
            "runtime.max_tokens",
            "Максимум токенов",
            int(runtime.get("max_tokens") or 8192),
            type="integer",
            minimum=1,
            maximum=32_768,
            editable=True,
            description="Ограничение ответа runtime.",
        ),
        _field(
            "runtime.gpu_layers",
            "GPU layers",
            str(runtime.get("gpu_layers") or "auto"),
            editable=True,
            description="auto или целое число слоёв; фактическое размещение подтверждает Resource Broker.",
        ),
        _field(
            "runtime.kv_cache.type",
            "Тип KV-cache",
            str((runtime.get("kv_cache") or {}).get("type") or "auto"),
            type="select",
            options=["auto", "f16", "q8_0", "q4_0"],
            editable=True,
            description="Рекомендуется auto, если у оператора нет отдельного требования.",
        ),
        _field(
            "runtime.kv_cache.offload",
            "Offload KV-cache",
            str((runtime.get("kv_cache") or {}).get("offload") or "auto").lower(),
            type="select",
            options=["auto", "true", "false"],
            editable=True,
            description="auto позволяет провайдеру выбрать безопасное размещение.",
        ),
        _field(
            "runtime.max_concurrency",
            "Параллельность",
            int(runtime.get("max_concurrency") or 1),
            type="integer",
            minimum=1,
            maximum=4096,
            editable=True,
            description="Количество одновременных запросов runtime.",
        ),
        _field(
            "replacement.mode",
            "Политика текущего runtime",
            str(replacement.get("mode") or "ask"),
            type="select",
            options=["ask", "parallel", "replace", "deny"],
            editable=True,
            description="ask никогда не останавливает текущий runtime без отдельного ответа оператора.",
        ),
        _field(
            "replacement.allow_stop_current",
            "Разрешить остановку текущего runtime",
            str(replacement.get("allow_stop_current") or "ask"),
            type="select",
            options=["ask", "allow", "deny"],
            editable=True,
            description="Даже при replace остановка возможна только при allow и после MCP approval.",
        ),
        _field(
            "publication.visibility",
            "Видимость endpoint",
            str(publication.get("visibility") or "ask"),
            type="select",
            options=["ask", "private", "public"],
            editable=True,
            description="Публикация в сеть отделена от локального запуска.",
        ),
        _field(
            "publication.pricing",
            "Тариф endpoint",
            str(publication.get("pricing") or "ask"),
            type="select",
            options=["ask", "free", "paid", "fixed", "metered"],
            editable=True,
            description="При paid агент запросит и проверит параметры тарифа.",
        ),
        _field(
            "publication.validation",
            "Валидация перед публикацией",
            str(publication.get("validation") or "ask"),
            type="select",
            options=["ask", "required", "disabled"],
            editable=True,
            description="По умолчанию рекомендуется required.",
        ),
        _field(
            "publication.external_requests_without_allowlist",
            "Внешние запросы без allowlist",
            str(publication.get("external_requests_without_allowlist") or "ask"),
            type="select",
            options=["ask", "allow", "deny"],
            editable=True,
            description="По умолчанию deny.",
        ),
        _field(
            "publication.endpoint_name",
            "Имя endpoint",
            str(publication.get("endpoint_name") or "") or "Q-ATOM endpoint",
            editable=True,
            description="Отображаемое имя будущего endpoint.",
        ),
        _field(
            "publication.tariff.kind",
            "Тип тарифа",
            tariff_view["kind"],
            type="select",
            options=["fixed", "metered"],
            editable=True,
            description="Используется только если выбран paid.",
        ),
        _field(
            "publication.tariff.dimension",
            "Единица тарифа",
            tariff_view["dimension"],
            type="select",
            options=INSTALLATION_TARIFF_DIMENSIONS,
            editable=True,
            description="Для fixed используется request_count.",
        ),
        _field(
            "publication.tariff.unit_price_q_atoms",
            "Цена за единицу, Q-ATOM",
            tariff_view["unit_price_q_atoms"],
            type="integer",
            minimum=0,
            maximum=10**12,
            editable=True,
            description="Для paid должна быть положительной.",
        ),
        _field(
            "publication.tariff.unit_divisor",
            "Делитель тарифа",
            tariff_view["unit_divisor"],
            type="integer",
            minimum=1,
            maximum=10**9,
            editable=True,
            description="Например, цена за 1 000 токенов задаётся divisor=1000.",
        ),
        _field(
            "publication.tariff.minimum_charge_q_atoms",
            "Минимальная сумма, Q-ATOM",
            tariff_view["minimum_charge_q_atoms"],
            type="integer",
            minimum=0,
            maximum=10**12,
            editable=True,
            description="Необязательный минимум списания.",
        ),
        _field(
            "workflow.confirm_installation",
            "Подтвердить установку и раскатку Bundle",
            False,
            type="boolean",
            editable=True,
            description="Отметьте после проверки всех полей. Агент применит план по шагам и остановится при approval/error.",
        ),
    ]
    # ``service.installation_plan`` also contains a live workflow projection
    # with checked_at timestamps.  Do not include that volatile read model in
    # the form revision or every polling pass would make a perfectly valid
    # draft look stale.  The persisted plan hash and field snapshot are the
    # optimistic-concurrency boundary.
    return {
        "revision": revision({"plan_hash": plan.get("plan_hash"), "fields": fields}),
        "fields": fields,
    }


def _installation_value(source: Mapping[str, object], changes: Mapping[str, object], field_id: str, default=None):
    if field_id in changes:
        return changes[field_id]
    fields = source.get("fields")
    if isinstance(fields, list):
        for item in fields:
            if isinstance(item, Mapping) and item.get("id") == field_id:
                return item.get("value")
    return default


def _installation_plan_from_form(control, source: Mapping[str, object], changes: Mapping[str, object], *, intent_id: str):
    """Translate the native installation form back into one canonical plan."""

    control.session.require("STEWARD:EXECUTE")
    current = control.service.installation_plan()
    if not isinstance(current, Mapping) or not current.get("available"):
        raise ValueError("The assisted installation plan is unavailable; ask the agent to prepare it again")
    model = current.get("model") if isinstance(current.get("model"), Mapping) else {}
    runtime = current.get("runtime_policy") if isinstance(current.get("runtime_policy"), Mapping) else {}
    current_context = runtime.get("context_length") if isinstance(runtime.get("context_length"), Mapping) else {}
    current_kv = runtime.get("kv_cache") if isinstance(runtime.get("kv_cache"), Mapping) else {}
    replacement = current.get("replacement_policy") if isinstance(current.get("replacement_policy"), Mapping) else {}
    publication = current.get("publication_policy") if isinstance(current.get("publication_policy"), Mapping) else {}

    requested = int(_installation_value(source, changes, "runtime.context_length.requested", current_context.get("requested", CONTEXT_LENGTH_CHOICES[0])))
    fallback_values = []
    if bool(_installation_value(source, changes, "runtime.context_length.fallback_65536", 65_536 in current_context.get("fallbacks", []))) and requested > 65_536:
        fallback_values.append(65_536)
    if bool(_installation_value(source, changes, "runtime.context_length.fallback_32768", 32_768 in current_context.get("fallbacks", []))) and requested > 32_768:
        fallback_values.append(32_768)
    gpu_layers_raw = _installation_value(source, changes, "runtime.gpu_layers", runtime.get("gpu_layers", "auto"))
    gpu_layers = str(gpu_layers_raw).strip().lower() if isinstance(gpu_layers_raw, str) else gpu_layers_raw
    kv_offload_raw = _installation_value(source, changes, "runtime.kv_cache.offload", current_kv.get("offload", "auto"))
    kv_offload = str(kv_offload_raw).strip().lower() if not isinstance(kv_offload_raw, bool) else kv_offload_raw
    runtime_policy = {
        "context_length": {
            "requested": requested,
            "fallbacks": fallback_values,
            "on_exhausted": str(_installation_value(source, changes, "runtime.context_length.on_exhausted", current_context.get("on_exhausted", "notify"))).lower(),
        },
        "max_tokens": int(_installation_value(source, changes, "runtime.max_tokens", runtime.get("max_tokens", 8192))),
        "gpu_layers": gpu_layers,
        "kv_cache": {
            "type": str(_installation_value(source, changes, "runtime.kv_cache.type", current_kv.get("type", "auto"))).lower(),
            "offload": kv_offload,
        },
        "max_concurrency": int(_installation_value(source, changes, "runtime.max_concurrency", runtime.get("max_concurrency", 1))),
    }
    replacement_policy = {
        "mode": str(_installation_value(source, changes, "replacement.mode", replacement.get("mode", "ask"))).lower(),
        "allow_stop_current": str(_installation_value(source, changes, "replacement.allow_stop_current", replacement.get("allow_stop_current", "ask"))).lower(),
    }
    pricing = str(_installation_value(source, changes, "publication.pricing", publication.get("pricing", "ask"))).lower()
    tariff = None
    if pricing in {"paid", "fixed", "metered"}:
        tariff = {
            "kind": str(_installation_value(source, changes, "publication.tariff.kind", "metered")).lower(),
            "dimension": str(_installation_value(source, changes, "publication.tariff.dimension", "request_count")).lower(),
            "unit_price_q_atoms": int(_installation_value(source, changes, "publication.tariff.unit_price_q_atoms", 0)),
            "unit_divisor": int(_installation_value(source, changes, "publication.tariff.unit_divisor", 1)),
            "minimum_charge_q_atoms": int(_installation_value(source, changes, "publication.tariff.minimum_charge_q_atoms", 0)),
        }
        if pricing == "paid" and tariff["unit_price_q_atoms"] <= 0:
            raise ValueError("Paid endpoint requires a positive Q-ATOM tariff before installation can continue")
    publication_policy = {
        "visibility": str(_installation_value(source, changes, "publication.visibility", publication.get("visibility", "ask"))).lower(),
        "pricing": pricing,
        "tariff": tariff,
        "validation": str(_installation_value(source, changes, "publication.validation", publication.get("validation", "ask"))).lower(),
        "external_requests_without_allowlist": str(_installation_value(source, changes, "publication.external_requests_without_allowlist", publication.get("external_requests_without_allowlist", "ask"))).lower(),
        "endpoint_name": str(_installation_value(source, changes, "publication.endpoint_name", publication.get("endpoint_name") or "Q-ATOM endpoint")).strip(),
    }
    result = control.service.prepare_installation_plan(
        provider=str(_installation_value(source, changes, "installation.provider", current.get("provider"))),
        model_id=str(_installation_value(source, changes, "installation.model_id", model.get("id"))),
        model_source=str(_installation_value(source, changes, "installation.model_source", model.get("source"))),
        endpoint_action=str(_installation_value(source, changes, "installation.endpoint_action", (current.get("endpoint") or {}).get("requested_action", "draft"))),
        handoff=str(current.get("handoff") or "dashboard"),
        model_expected_sha256=model.get("expected_sha256"),
        model_expected_bytes=model.get("expected_bytes"),
        runtime_policy=runtime_policy,
        replacement_policy=replacement_policy,
        publication_policy=publication_policy,
        expected_plan_hash=str(current.get("plan_hash") or ""),
        actor=control.session.agent_identity,
        idempotency_key=f"{intent_id}:installation-plan",
    )
    return result


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
    elif kind == "installation":
        target_id = "installation-plan"
        result = _installation_plan_source(control)
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
        if target["kind"] == "installation":
            current_source = _installation_plan_source(control)
            if current_source["revision"] != target["revision"]:
                raise ValueError("The installation plan changed since this form was read. Refresh before applying.")
            changes = {item["path"]: item["to"] for item in intent["diff"]}
            updated_plan = _installation_plan_from_form(control, current_source, changes, intent_id=intent_id)
            refreshed_source = _installation_plan_source(control)
            result = {
                "state": "APPLIED",
                "intent_id": intent_id,
                "source": control.service.agent_channel.interface.register_source(
                    surface_id=intent["surface_id"],
                    kind="installation",
                    target_id="installation-plan",
                    source_revision=refreshed_source["revision"],
                    fields=refreshed_source["fields"],
                ),
                "document_id": intent["change"]["document_id"],
                "verified": True,
                "installation": updated_plan,
                "installation_confirmed": bool(changes.get("workflow.confirm_installation", False)),
            }
            control.service.agent_channel.interface.complete(intent_id, result)
            return result
        if target["kind"] != "endpoint":
            raise ValueError("Unsupported form target")
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
            "Read authoritative fields for an operator's Spatial request. First resolve exact IDs through domain MCP tools. Use kind=installation for the AI-assisted model-install questionnaire. Returns a source_id for aidn.ui.present; never invent values or editable flags.",
            {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string"},
                    "kind": {"enum": ["provider", "bundle", "endpoint", "installation", "scene"]},
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
            "Plan/apply the exact operator-submitted form intent. Endpoint edits and the AI-assisted installation questionnaire are both supported. No replacement values are accepted. Canonical validation, permissions, revision and read-back are enforced. After apply use aidn.ui.present with the returned source and SAME document_id. If approval is required, report it; do not approve on the operator's behalf.",
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
    if intent["target"]["kind"] == "installation":
        current = _installation_plan_source(control)
        if current["revision"] != intent["target"]["revision"]:
            raise ValueError("The installation plan changed since this form was read. Refresh before applying.")
        return current["revision"]
    if intent["target"]["kind"] != "endpoint":
        raise ValueError("Unsupported form target")
    current = _endpoint_source(control, intent["target"]["id"])
    if current["revision"] != intent["target"]["revision"]:
        raise ValueError("The endpoint changed since this form was read. Refresh before applying.")
    return current["revision"]
