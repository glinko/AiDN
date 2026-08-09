"""Protected dashboard endpoints for local MCP agent credentials."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from aidn_hypervisor.mcp.credentials import McpCredential, McpCredentialStore
from aidn_hypervisor.mcp.enrollment import McpEnrollmentService
from aidn_hypervisor.mcp.permissions import (
    DEFAULT_AGENT_READ_SCOPES,
    normalize_agent_scopes,
    permission_catalog_payload,
)
from aidn_hypervisor.operator_access import DashboardAccessService

_COOKIE_NAME = "aidn_dashboard_access"
_COOKIE_PATH = "/operators/dashboard/access"


class PairingRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class CredentialCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=96)
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_AGENT_READ_SCOPES), min_length=1, max_length=64)


class CredentialScopeUpdateRequest(BaseModel):
    scopes: list[str] = Field(min_length=1, max_length=64)


class EnrollmentCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=96)
    encryption_public_key: str = Field(min_length=40, max_length=128)


def _credential_payload(credential: McpCredential, *, reveal: bool = False) -> dict:
    payload = asdict(credential)
    if not reveal:
        payload.pop("token", None)
    return payload


def build_operator_access_router(
    *,
    access_service: DashboardAccessService | None,
    credential_store: McpCredentialStore | None,
    allow_insecure_lan: bool,
    enrollment_service: McpEnrollmentService | None = None,
    operator_fingerprint: str | None = None,
    invalidate_credential_sessions: Callable[[str], None] | None = None,
) -> APIRouter:
    """Build a browser-only credential management boundary."""
    router = APIRouter(prefix="/operators/dashboard/access")

    def session_expiry(request: Request) -> str | None:
        if access_service is None:
            return None
        return access_service.session_expiry(request.cookies.get(_COOKIE_NAME))

    def require_session(request: Request) -> JSONResponse | None:
        if access_service is None or not access_service.authorize(request.cookies.get(_COOKIE_NAME)):
            return JSONResponse(status_code=401, content={"error": {"code": "DASHBOARD_ACCESS_REQUIRED"}})
        if not allow_insecure_lan and request.url.scheme != "https":
            return JSONResponse(status_code=426, content={"error": {"code": "DASHBOARD_ACCESS_TLS_REQUIRED"}})
        return None

    def enrollment_payload(item) -> dict:
        return asdict(item)

    @router.get("/status")
    async def status(request: Request) -> dict:
        active = session_expiry(request) is not None
        return {
            "enabled": access_service is not None and credential_store is not None,
            "session": {"active": active, "expires_at": session_expiry(request)},
            "transport": {"insecure_lan": allow_insecure_lan},
            "operator_authority": {
                "configured": operator_fingerprint is not None,
                "fingerprint": operator_fingerprint,
            },
            "credentials": (
                []
                if credential_store is None or not active
                else [_credential_payload(item) for item in credential_store.list_credentials()]
            ),
        }

    @router.post("/pair", status_code=204)
    async def pair(payload: PairingRequest, request: Request, response: Response) -> Response:
        if access_service is None:
            return JSONResponse(status_code=404, content={"error": {"code": "DASHBOARD_ACCESS_DISABLED"}})
        if not allow_insecure_lan and request.url.scheme != "https":
            return JSONResponse(status_code=426, content={"error": {"code": "DASHBOARD_ACCESS_TLS_REQUIRED"}})
        session = access_service.exchange_pairing_code(payload.code)
        if session is None:
            return JSONResponse(status_code=403, content={"error": {"code": "DASHBOARD_PAIRING_INVALID"}})
        response.set_cookie(
            _COOKIE_NAME,
            session.session_id,
            httponly=True,
            samesite="strict",
            secure=not allow_insecure_lan,
            path=_COOKIE_PATH,
        )
        return Response(status_code=204, headers=dict(response.headers))

    @router.post("/credentials", status_code=201)
    async def create_credential(payload: CredentialCreateRequest, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        assert credential_store is not None
        try:
            scopes = normalize_agent_scopes(payload.scopes)
        except ValueError:
            return JSONResponse(status_code=422, content={"error": {"code": "MCP_CREDENTIAL_SCOPE_INVALID"}})
        issued = credential_store.create_credential(label=payload.label, scopes=scopes)
        return JSONResponse(status_code=201, content=_credential_payload(issued, reveal=True))

    @router.get("/permission-catalog")
    async def permission_catalog(request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        return JSONResponse(
            status_code=200,
            content={
                "items": permission_catalog_payload(),
                "default_scopes": list(DEFAULT_AGENT_READ_SCOPES),
                "note": (
                    "Permissions control MCP tool visibility and execution. They do not bypass "
                    "operator plan approval or enable deferred tools."
                ),
            },
        )

    @router.put("/credentials/{credential_id}/scopes")
    async def update_credential_scopes(
        credential_id: str,
        payload: CredentialScopeUpdateRequest,
        request: Request,
    ) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        assert credential_store is not None
        try:
            updated = credential_store.update_scopes(
                credential_id,
                scopes=normalize_agent_scopes(payload.scopes),
            )
        except ValueError:
            return JSONResponse(status_code=422, content={"error": {"code": "MCP_CREDENTIAL_SCOPE_INVALID"}})
        if invalidate_credential_sessions is not None:
            invalidate_credential_sessions(credential_id)
        return JSONResponse(status_code=200, content=_credential_payload(updated))

    @router.post("/credentials/{credential_id}/rotate", status_code=201)
    async def rotate_credential(credential_id: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        assert credential_store is not None
        try:
            issued = credential_store.rotate_credential(credential_id)
        except ValueError:
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_CREDENTIAL_NOT_ACTIVE"}})
        if invalidate_credential_sessions is not None:
            invalidate_credential_sessions(credential_id)
        return JSONResponse(status_code=201, content=_credential_payload(issued, reveal=True))

    @router.delete("/credentials/{credential_id}", status_code=204)
    async def revoke_credential(credential_id: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        assert credential_store is not None
        if not credential_store.revoke_credential(credential_id):
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_CREDENTIAL_NOT_ACTIVE"}})
        if invalidate_credential_sessions is not None:
            invalidate_credential_sessions(credential_id)
        return Response(status_code=204)

    @router.post("/logout", status_code=204)
    async def logout(request: Request, response: Response) -> Response:
        if access_service is not None:
            access_service.revoke_session(request.cookies.get(_COOKIE_NAME))
        response.delete_cookie(_COOKIE_NAME, path=_COOKIE_PATH)
        return Response(status_code=204, headers=dict(response.headers))

    @router.post("/agent-enrollment/requests", status_code=201)
    async def create_enrollment(payload: EnrollmentCreateRequest) -> Response:
        if enrollment_service is None:
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_ENROLLMENT_DISABLED"}})
        try:
            created = enrollment_service.create_request(
                label=payload.label,
                encryption_public_key=payload.encryption_public_key,
            )
        except ValueError:
            return JSONResponse(status_code=422, content={"error": {"code": "MCP_ENROLLMENT_INVALID"}})
        return JSONResponse(status_code=201, content=enrollment_payload(created))

    @router.get("/agent-enrollment/requests/{request_id}")
    async def retrieve_enrollment(request_id: str, request: Request) -> Response:
        if enrollment_service is None:
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_ENROLLMENT_NOT_FOUND"}})
        result = enrollment_service.retrieve(
            request_id=request_id,
            retrieval_secret=request.headers.get("X-AiDN-Enrollment-Secret", ""),
        )
        if result is None:
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_ENROLLMENT_NOT_FOUND"}})
        return JSONResponse(status_code=200, content=result)

    @router.get("/enrollment-requests")
    async def list_enrollments(request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if enrollment_service is None:
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_ENROLLMENT_DISABLED"}})
        return JSONResponse(
            status_code=200,
            content={"items": [enrollment_payload(item) for item in enrollment_service.list_requests()]},
        )

    @router.post("/enrollment-requests/{request_id}/approve")
    async def approve_enrollment(request_id: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if enrollment_service is None:
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_ENROLLMENT_DISABLED"}})
        try:
            approved = enrollment_service.approve(request_id)
        except ValueError:
            return JSONResponse(status_code=409, content={"error": {"code": "MCP_ENROLLMENT_NOT_PENDING"}})
        return JSONResponse(status_code=200, content=enrollment_payload(approved))

    @router.post("/enrollment-requests/{request_id}/reject")
    async def reject_enrollment(request_id: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if enrollment_service is None:
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_ENROLLMENT_DISABLED"}})
        try:
            rejected = enrollment_service.reject(request_id)
        except ValueError:
            return JSONResponse(status_code=409, content={"error": {"code": "MCP_ENROLLMENT_NOT_PENDING"}})
        return JSONResponse(status_code=200, content=enrollment_payload(rejected))

    return router
