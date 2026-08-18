"""OpenAI-compatible inference gateway for a personal agent on one node.

The gateway is intentionally a narrow data plane.  Control operations remain
behind MCP; this surface only accepts chat requests for a dashboard-issued
credential, turns them into the normal Hypervisor task lifecycle, and returns
the provider result in the OpenAI response shape.
"""

from __future__ import annotations

import html
import json
import re
import time
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aidn_hypervisor.accounting.models import AccountingContract
from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.mcp.credentials import InferenceCredential, McpCredentialStore
from aidn_hypervisor.runtime_parameter_policy import (
    apply_runtime_parameter_policy_payload,
)

# Provider plugins expose the OpenAI-compatible text generation surface as
# ``llm.chat``, while the model-install flow historically stored its workload
# as ``llm_text``.  Both are local text-generation routes; treating only the
# latter as eligible made a valid Runtime Binding impossible to use from the
# personal-agent gateway.
_PERSONAL_AGENT_MODEL_CLASSES = frozenset({"llm_text", "llm.chat"})


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["system", "user", "assistant", "tool", "developer"]
    content: str | list[dict[str, Any]] | None = None
    name: str | None = Field(default=None, max_length=128)
    tool_calls: list[dict[str, Any]] | None = Field(default=None, max_length=128)
    tool_call_id: str | None = Field(default=None, max_length=256)


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str = Field(min_length=1, max_length=256)
    messages: list[ChatMessage] = Field(min_length=1, max_length=128)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=1, le=100000)
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    context_length: int | None = Field(default=None, ge=1, le=131072)
    repeat_penalty: float | None = Field(default=None, ge=0.0, le=10.0)
    extra_body: dict[str, Any] = Field(default_factory=dict, max_length=32)
    tools: list[dict[str, Any]] | None = Field(default=None, max_length=128)
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None
    stream: bool = False
    user: str | None = Field(default=None, max_length=256)


def _error(
    status_code: int,
    message: str,
    *,
    code: str,
    error_type: str = "invalid_request_error",
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": error_type, "code": code}},
    )


def _message_size(messages: list[ChatMessage]) -> int:
    total = 0
    for message in messages:
        content = message.content
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            total += sum(len(str(item)) for item in content)
    return total


def _stream_event(payload: dict[str, Any]) -> str:
    """Encode one OpenAI-compatible server-sent event."""

    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


_TOOL_CALL_BLOCK_RE = re.compile(
    r"<tool_call>\s*(?P<body>.*?)\s*</tool_call>",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_FUNCTION_RE = re.compile(
    r"<function\s*=\s*(?P<name>[A-Za-z_][\w.-]*)\s*>(?P<body>.*?)</function>",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_PARAMETER_RE = re.compile(
    r"<parameter\s*=\s*(?P<name>[A-Za-z_][\w.-]*)\s*>(?P<value>.*?)</parameter>",
    re.IGNORECASE | re.DOTALL,
)


def _decode_tool_parameter(value: str) -> Any:
    """Decode a llama.cpp XML parameter without losing plain text values."""

    text = html.unescape(value.strip())
    if not text:
        return ""
    # Tool arguments are often strings, but accepting JSON scalars/containers
    # keeps the bridge compatible with model-generated numeric and structured
    # parameters as well.
    try:
        decoded = json.loads(text)
    except (TypeError, ValueError):
        return text
    return decoded


def _new_tool_call(*, name: str, arguments: dict[str, Any], call_id: str | None = None) -> dict[str, Any]:
    return {
        "id": call_id or f"call-{uuid4().hex}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False, separators=(",", ":")),
        },
    }


def _normalize_native_tool_calls(raw_calls: Any) -> list[dict[str, Any]]:
    """Normalize provider tool calls to the OpenAI response shape."""

    if not isinstance(raw_calls, list):
        return []
    normalized: list[dict[str, Any]] = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            continue
        function = raw_call.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            arguments_json = arguments
        else:
            arguments_json = json.dumps(
                arguments,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        normalized.append(
            {
                "id": str(raw_call.get("id") or f"call-{uuid4().hex}"),
                "type": str(raw_call.get("type") or "function"),
                "function": {"name": name.strip(), "arguments": arguments_json},
            }
        )
    return normalized


def _parse_tool_call_markup(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Convert llama.cpp's legacy XML tool syntax into structured calls.

    Some llama.cpp/Qwen combinations emit ``<tool_call>`` markup when a
    request reaches the server without its OpenAI ``tools`` field.  Keeping a
    narrow compatibility parser here prevents that protocol artifact from
    leaking into Telegram or other agent UIs.  Unparseable markup is left
    untouched so a malformed model response remains diagnosable.
    """

    if not isinstance(text, str) or "<tool_call" not in text.lower():
        return text, []
    calls: list[dict[str, Any]] = []
    removable_spans: list[tuple[int, int]] = []
    for block in _TOOL_CALL_BLOCK_RE.finditer(text):
        body = block.group("body")
        parsed_in_block: list[dict[str, Any]] = []
        for function in _TOOL_FUNCTION_RE.finditer(body):
            name = function.group("name").strip()
            arguments = {
                parameter.group("name").strip(): _decode_tool_parameter(parameter.group("value"))
                for parameter in _TOOL_PARAMETER_RE.finditer(function.group("body"))
            }
            parsed_in_block.append(_new_tool_call(name=name, arguments=arguments))
        if not parsed_in_block:
            # A few templates use JSON inside the tool_call wrapper instead
            # of the function/parameter tags.  Accept only the explicit
            # name+arguments contract; arbitrary JSON must stay visible.
            try:
                decoded = json.loads(html.unescape(body.strip()))
            except (TypeError, ValueError):
                decoded = None
            if isinstance(decoded, dict):
                name = decoded.get("name") or decoded.get("function")
                arguments = decoded.get("arguments", {})
                if isinstance(name, str) and isinstance(arguments, dict):
                    parsed_in_block.append(_new_tool_call(name=name, arguments=arguments))
        if parsed_in_block:
            calls.extend(parsed_in_block)
            removable_spans.append((block.start(), block.end()))
    if not calls:
        return text, []
    visible_parts: list[str] = []
    cursor = 0
    for start, end in removable_spans:
        visible_parts.append(text[cursor:start])
        cursor = end
    visible_parts.append(text[cursor:])
    return "".join(visible_parts).strip(), calls


def _assistant_output(result: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    """Return visible assistant text and structured tool calls from a task."""

    raw_text = result.get("output_text")
    text = raw_text if isinstance(raw_text, str) else str(raw_text or "")
    tool_calls = _normalize_native_tool_calls(result.get("tool_calls"))
    if not tool_calls:
        text, tool_calls = _parse_tool_call_markup(text)
    else:
        # A provider can include a compatibility block alongside native calls;
        # strip only the block while retaining the native call payload.
        text, _ = _parse_tool_call_markup(text)
    return (text or None), tool_calls


def build_inference_router(
    *,
    hypervisor_service: Any,
    endpoint_service: Any,
    session_service: Any,
    credential_store: McpCredentialStore | None,
) -> APIRouter:
    """Build the `/v1` data-plane router.

    A credential is scoped to exactly one EndpointManifest.  The first request
    opens a zero-priced owner session; subsequent requests reuse that session
    until it expires or is closed, at which point a new one is opened.
    """

    router = APIRouter(prefix="/v1")

    def authenticate(request: Request) -> InferenceCredential | JSONResponse:
        if credential_store is None:
            return _error(
                503,
                "Inference gateway is not configured",
                code="gateway_unavailable",
                error_type="server_error",
            )
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "Authentication required",
                        "type": "invalid_request_error",
                        "code": "invalid_api_key",
                    }
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        credential = credential_store.resolve_inference(token.strip())
        if credential is None:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "Invalid inference API key",
                        "type": "invalid_request_error",
                        "code": "invalid_api_key",
                    }
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        credential_store.record_use(credential.credential_id)
        return credential

    def endpoint_for(credential: InferenceCredential, model: str):
        try:
            endpoint = endpoint_service.get_endpoint(credential.endpoint_id).endpoint
        except (KeyError, ValueError) as error:
            raise ValueError("The endpoint granted to this token no longer exists") from error
        if endpoint.status == "deleted":
            raise ValueError("The endpoint granted to this token has been deleted")
        if not endpoint.local_agent_use:
            raise ValueError("Local Agent Use is not enabled for this endpoint")
        if endpoint.execution_strategy != "local":
            raise ValueError("Personal agent inference requires a local endpoint")
        if endpoint.model_class not in _PERSONAL_AGENT_MODEL_CLASSES:
            raise ValueError("Personal agent inference requires a local text-generation endpoint")
        if endpoint.runtime_binding_id is None:
            raise ValueError("The endpoint has no active runtime binding")
        if endpoint.owner_wallet != credential.owner_wallet:
            raise ValueError("The endpoint owner no longer matches this credential")
        aliases = {
            credential.model_alias,
            endpoint.endpoint_id,
            endpoint.bundle_id,
            endpoint.model_class,
        }
        if model not in aliases:
            raise LookupError(f"Model '{model}' is not available to this credential")
        pricing = endpoint.pricing.model_dump(mode="json")
        if any(float(pricing.get(key) or 0.0) != 0.0 for key in (
            "input_price",
            "output_price",
            "audio_input_second_price",
            "fixed_price",
        )):
            raise ValueError("Personal agent inference is limited to zero-priced endpoints")
        session_policy = endpoint.session.model_dump(mode="json")
        if any(float(session_policy.get(key) or 0.0) != 0.0 for key in (
            "minimum_deposit",
            "minimum_session_fee",
            "idle_fee_per_minute",
        )):
            raise ValueError("Personal agent inference requires a zero-fee session policy")
        return endpoint

    def ensure_session(credential: InferenceCredential, endpoint) -> str:
        if credential.session_id:
            try:
                session = session_service.require_active_session(
                    endpoint_id=endpoint.endpoint_id,
                    session_id=credential.session_id,
                )
            except (KeyError, ValueError):
                # Closed/expired sessions are intentionally replaced on the
                # next request; the credential itself remains valid.
                session = None
            if session is not None:
                if session.client_wallet != credential.owner_wallet:
                    raise ValueError("Inference session owner does not match the credential")
                # Endpoint configuration changes (for example a context
                # window revision) invalidate the immutable session snapshot.
                # Retire the stale owner-agent session before dispatch so the
                # next request is opened against the current configuration
                # instead of failing later in the Runtime boundary.
                session_configuration_hash = getattr(
                    session, "endpoint_configuration_hash", None
                )
                if (
                    session_configuration_hash is not None
                    and session_configuration_hash != endpoint.configuration_hash
                ):
                    session_service.close_session(credential.session_id)
                    session = None
                if session is not None:
                    # Prior gateway versions persisted a minimal,
                    # non-canonical accounting payload. It cannot be sent to
                    # an approved runtime, so retire only that legacy
                    # owner-agent session and replace it below with the
                    # Endpoint's immutable contract.
                    try:
                        AccountingContract.model_validate(
                            getattr(session, "accounting_contract_snapshot", {})
                        )
                        if (
                            getattr(session, "economic_profile", None) == "OWNER_AGENT"
                            and getattr(session, "request_charge_ceiling_q_atoms", None)
                            != 0
                        ):
                            raise ValueError("legacy owner-agent request ceiling")
                    except (ValidationError, ValueError):
                        if getattr(session, "economic_profile", None) != "OWNER_AGENT":
                            raise ValueError(
                                "Inference session has an invalid accounting contract"
                            ) from None
                        session_service.close_session(credential.session_id)
                        session = None
                    if session is not None:
                        session_service.require_request_budget(
                            endpoint_id=endpoint.endpoint_id,
                            session_id=credential.session_id,
                        )
                        return credential.session_id
        result = session_service.open_session(
            endpoint_id=endpoint.endpoint_id,
            client_wallet=credential.owner_wallet,
            provider_wallet=endpoint.owner_wallet,
            node_id=hypervisor_service.node_id,
            deposit_q=0.0,
            deposit_q_atoms=0,
            fixed_price_q_atoms=0,
            request_charge_ceiling_q_atoms=0,
            session_policy=endpoint.session.model_dump(mode="json"),
            accounting_contract=hypervisor_service.accounting_contract_for_endpoint(
                endpoint
            ),
            endpoint_configuration_hash=endpoint.configuration_hash,
            endpoint_payment_beneficiary=endpoint.owner_wallet,
            consumer_refund_beneficiary=credential.owner_wallet,
            economic_profile="OWNER_AGENT",
        )
        if result.session.status != "active":
            raise RuntimeError("The endpoint is busy; no personal inference session was opened")
        assert credential_store is not None
        credential_store.bind_inference_session(credential.credential_id, result.session.session_id)
        return result.session.session_id

    def endpoint_runtime_policy(endpoint) -> dict:
        policy = getattr(endpoint, "runtime_parameter_policy", None)
        if policy:
            return policy
        # Legacy endpoints predate the endpoint-level copy.  Keep them safe by
        # enforcing the Bundle policy until the operator republishes them.
        try:
            bundle = hypervisor_service._get_bundle(endpoint.bundle_id)
        except (AttributeError, KeyError, ValueError):
            return {}
        return getattr(bundle, "runtime_parameter_policy", {}) or {}

    @router.get("/models")
    async def list_models(request: Request) -> Response:
        authenticated = authenticate(request)
        if isinstance(authenticated, JSONResponse):
            return authenticated
        credential = authenticated
        try:
            endpoint_for(credential, credential.model_alias)
        except LookupError as error:
            return _error(404, str(error), code="model_not_found")
        except ValueError as error:
            return _error(409, str(error), code="endpoint_unavailable")
        return JSONResponse(
            status_code=200,
            content={
                "object": "list",
                "data": [
                    {
                        "id": credential.model_alias,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "aidn",
                        "aidn_endpoint_id": credential.endpoint_id,
                    }
                ],
            },
        )

    @router.post("/chat/completions")
    async def chat_completions(payload: ChatCompletionRequest, request: Request) -> Response:
        authenticated = authenticate(request)
        if isinstance(authenticated, JSONResponse):
            return authenticated
        credential = authenticated
        if _message_size(payload.messages) > 262_144:
            return _error(413, "The request messages exceed the 256 KiB limit", code="request_too_large")
        try:
            endpoint = endpoint_for(credential, payload.model)
        except LookupError as error:
            return _error(404, str(error), code="model_not_found")
        except ValueError as error:
            return _error(409, str(error), code="endpoint_unavailable")
        try:
            request_payload: dict[str, Any] = {
                "messages": [message.model_dump(exclude_none=True, mode="json") for message in payload.messages],
            }
            if payload.temperature is not None:
                request_payload["temperature"] = payload.temperature
            if payload.top_p is not None:
                request_payload["top_p"] = payload.top_p
            if payload.max_tokens is not None:
                request_payload["max_tokens"] = payload.max_tokens
            if payload.top_k is not None:
                request_payload["top_k"] = payload.top_k
            if payload.frequency_penalty is not None:
                request_payload["frequency_penalty"] = payload.frequency_penalty
            if payload.presence_penalty is not None:
                request_payload["presence_penalty"] = payload.presence_penalty
            if payload.context_length is not None:
                request_payload["context_length"] = payload.context_length
            if payload.repeat_penalty is not None:
                request_payload["repeat_penalty"] = payload.repeat_penalty
            request_payload.update(
                {
                    key: value
                    for key, value in payload.extra_body.items()
                    if key
                    not in {
                        "messages",
                        "prompt",
                        "model",
                        "tools",
                        "tool_choice",
                        "parallel_tool_calls",
                    }
                }
            )
            # Preserve the OpenAI tool contract all the way to the reviewed
            # Provider adapter.  Older gateway versions silently discarded
            # these fields, which made Qwen/llama.cpp fall back to emitting
            # ``<tool_call>`` XML as ordinary assistant text.
            if payload.tools is not None:
                request_payload["tools"] = payload.tools
            if payload.tool_choice is not None:
                request_payload["tool_choice"] = payload.tool_choice
            if payload.parallel_tool_calls is not None:
                request_payload["parallel_tool_calls"] = payload.parallel_tool_calls
            try:
                request_payload = apply_runtime_parameter_policy_payload(
                    request_payload,
                    endpoint_runtime_policy(endpoint),
                )
            except ValueError as error:
                return _error(
                    422,
                    str(error),
                    code="parameter_policy_violation",
                )
            session_id = ensure_session(credential, endpoint)
            request_id = "agent-" + uuid4().hex
            task = hypervisor_service.submit(
                TaskRequest(
                    task_type="llm_text.generate",
                    payload=request_payload,
                    mode="manual",
                    constraints={
                        "endpoint_id": endpoint.endpoint_id,
                        "session_id": session_id,
                        "request_id": request_id,
                        "streaming": False,
                        "inference_credential_id": credential.credential_id,
                        "agent_identity": credential.credential_id,
                    },
                )
            )
        except (RuntimeError, ValueError, KeyError) as error:
            return _error(503, str(error), code="inference_execution_failed", error_type="server_error")
        result = hypervisor_service.task_result(task.task_id)
        # ``submit`` returns the queue snapshot created before its synchronous
        # processing pass. A successfully completed task therefore still has
        # its original ``queued`` status on that stale object. The committed
        # result is the authoritative completion signal for this request.
        if not isinstance(result, dict):
            return _error(
                503,
                "The inference runtime did not complete the request",
                code="inference_not_ready",
                error_type="server_error",
            )
        if not result.get("ok", False):
            return _error(
                502,
                "The inference runtime rejected the request",
                code="upstream_error",
                error_type="server_error",
            )
        text, tool_calls = _assistant_output(result)
        completion_id = "chatcmpl-" + task.task_id
        created = int(time.time())
        finish_reason = "tool_calls" if tool_calls else "stop"
        if payload.stream:
            # Runtime execution is currently request/response based. Emit a
            # standards-compatible buffered stream after the approved task
            # completes so OpenAI clients (including Hermes) can use their
            # normal streaming path without exposing an unbounded provider
            # connection or pretending that tokens arrived incrementally.
            delta: dict[str, Any] = {"role": "assistant"}
            if text is not None:
                delta["content"] = text
            if tool_calls:
                delta["tool_calls"] = [
                    {
                        "index": index,
                        "id": call["id"],
                        "type": call["type"],
                        "function": call["function"],
                    }
                    for index, call in enumerate(tool_calls)
                ]
            if len(delta) == 1:
                delta["content"] = ""
            events = [
                _stream_event(
                    {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": credential.model_alias,
                        "choices": [
                            {
                                "index": 0,
                                "delta": delta,
                                "finish_reason": None,
                            }
                        ],
                    }
                ),
                _stream_event(
                    {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": credential.model_alias,
                        "choices": [
                            {"index": 0, "delta": {}, "finish_reason": finish_reason}
                        ],
                    }
                ),
                "data: [DONE]\n\n",
            ]
            return StreamingResponse(
                iter(events),
                status_code=200,
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache"},
            )
        return JSONResponse(
            status_code=200,
            content={
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": credential.model_alias,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": text,
                            **({"tool_calls": tool_calls} if tool_calls else {}),
                        },
                        "finish_reason": finish_reason,
                    }
                ],
                "aidn": {"endpoint_id": endpoint.endpoint_id, "task_id": task.task_id},
            },
        )

    return router
