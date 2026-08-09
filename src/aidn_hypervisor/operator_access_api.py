"""Protected dashboard endpoints for local MCP agent credentials."""

from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from aidn_hypervisor.mcp.credentials import McpCredential, McpCredentialStore
from aidn_hypervisor.operator_access import DashboardAccessService

_COOKIE_NAME = "aidn_dashboard_access"
_COOKIE_PATH = "/operators/dashboard/access"


class PairingRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class CredentialCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=96)
    scopes: list[str] = Field(min_length=1, max_length=64)


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

    @router.get("/status")
    async def status(request: Request) -> dict:
        active = session_expiry(request) is not None
        return {
            "enabled": access_service is not None and credential_store is not None,
            "session": {"active": active, "expires_at": session_expiry(request)},
            "transport": {"insecure_lan": allow_insecure_lan},
            "credentials": [] if credential_store is None else [_credential_payload(item) for item in credential_store.list_credentials()],
        }

    @router.post("/pair", status_code=204)
    async def pair(payload: PairingRequest, response: Response) -> Response:
        if access_service is None:
            return JSONResponse(status_code=404, content={"error": {"code": "DASHBOARD_ACCESS_DISABLED"}})
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
        issued = credential_store.create_credential(label=payload.label, scopes=tuple(payload.scopes))
        return JSONResponse(status_code=201, content=_credential_payload(issued, reveal=True))

    return router
