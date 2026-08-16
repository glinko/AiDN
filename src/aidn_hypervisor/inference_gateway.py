"""OpenAI-compatible inference gateway for a personal agent on one node.

The gateway is intentionally a narrow data plane.  Control operations remain
behind MCP; this surface only accepts chat requests for a dashboard-issued
credential, turns them into the normal Hypervisor task lifecycle, and returns
the provider result in the OpenAI response shape.
"""

from __future__ import annotations

import time
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.mcp.credentials import InferenceCredential, McpCredentialStore


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["system", "user", "assistant", "tool", "developer"]
    content: str | list[dict[str, Any]] | None = None
    name: str | None = Field(default=None, max_length=128)


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str = Field(min_length=1, max_length=256)
    messages: list[ChatMessage] = Field(min_length=1, max_length=128)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
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
        if endpoint.execution_strategy != "local":
            raise ValueError("Personal agent inference requires a local endpoint")
        if endpoint.model_class != "llm_text":
            raise ValueError("Personal agent inference requires an llm_text endpoint")
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
            session_policy=endpoint.session.model_dump(mode="json"),
            accounting_contract={"maximum_request_charge": 0.0, "profile": "OWNER_AGENT"},
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

    @router.get("/models")
    async def list_models(request: Request) -> Response:
        authenticated = authenticate(request)
        if isinstance(authenticated, JSONResponse):
            return authenticated
        credential = authenticated
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
        if payload.stream:
            return _error(
                400,
                "Streaming is not enabled for this personal endpoint yet",
                code="streaming_not_supported",
            )
        if _message_size(payload.messages) > 262_144:
            return _error(413, "The request messages exceed the 256 KiB limit", code="request_too_large")
        try:
            endpoint = endpoint_for(credential, payload.model)
        except LookupError as error:
            return _error(404, str(error), code="model_not_found")
        except ValueError as error:
            return _error(409, str(error), code="endpoint_unavailable")
        try:
            session_id = ensure_session(credential, endpoint)
            request_id = "agent-" + uuid4().hex
            request_payload: dict[str, Any] = {
                "messages": [message.model_dump(exclude_none=True, mode="json") for message in payload.messages],
            }
            if payload.temperature is not None:
                request_payload["temperature"] = payload.temperature
            if payload.top_p is not None:
                request_payload["top_p"] = payload.top_p
            if payload.max_tokens is not None:
                request_payload["max_tokens"] = payload.max_tokens
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
        if getattr(task, "status", None) != "completed" or not isinstance(result, dict):
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
        text = result.get("output_text")
        if not isinstance(text, str):
            text = str(text or "")
        return JSONResponse(
            status_code=200,
            content={
                "id": "chatcmpl-" + task.task_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": credential.model_alias,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "aidn": {"endpoint_id": endpoint.endpoint_id, "task_id": task.task_id},
            },
        )

    return router
