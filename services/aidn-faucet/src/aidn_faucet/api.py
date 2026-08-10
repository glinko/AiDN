"""Small authenticated HTTP surface for agents and operators."""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

from aidn_faucet.mcp import FaucetMcpServer
from aidn_faucet.models import (
    FaucetChallengeRequest,
    FaucetClaimRequest,
    FaucetLowBalanceRequest,
    FaucetPauseRequest,
)
from aidn_faucet.service import FaucetService


def build_app(service: FaucetService, *, mcp_server: FaucetMcpServer | None = None) -> FastAPI:
    app = FastAPI(title="AiDN Faucet Treasury", version="0.1.0")
    mcp = mcp_server or FaucetMcpServer(service)

    def authorize(authorization: str | None) -> None:
        token = None
        if authorization is not None and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
        try:
            service.authorize_agent(token)
        except PermissionError as error:
            raise HTTPException(status_code=401, detail=str(error)) from error

    def authorize_creator(authorization: str | None) -> None:
        token = None
        if authorization is not None and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
        try:
            service.authorize_creator(token)
        except PermissionError as error:
            raise HTTPException(status_code=401, detail=str(error)) from error

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "aidn-faucet"}

    @app.get("/", include_in_schema=False)
    def admin_ui():
        return FileResponse(
            __file__.replace("api.py", "static/faucet_admin.html"),
            media_type="text/html",
        )

    @app.get("/v1/status")
    def status(authorization: str | None = Header(default=None)):
        authorize(authorization)
        return service.status()

    @app.get("/v1/admin/status")
    def admin_status(authorization: str | None = Header(default=None)):
        authorize_creator(authorization)
        return service.creator_status()

    @app.post("/v1/admin/pause")
    def pause(
        request: FaucetPauseRequest,
        authorization: str | None = Header(default=None),
    ):
        authorize_creator(authorization)
        try:
            return service.pause(reason=request.reason)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/v1/admin/resume")
    def resume(authorization: str | None = Header(default=None)):
        authorize_creator(authorization)
        return service.resume()

    @app.post("/v1/admin/low-balance-watermark")
    def low_balance_watermark(
        request: FaucetLowBalanceRequest,
        authorization: str | None = Header(default=None),
    ):
        authorize_creator(authorization)
        try:
            return service.set_low_balance_watermark(
                watermark_q_atoms=request.watermark_q_atoms,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/v1/admin/claims/{request_id}")
    def admin_claim_status(request_id: str, authorization: str | None = Header(default=None)):
        authorize_creator(authorization)
        try:
            return service.claim_status(request_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/v1/admin/claims/{request_id}/reconcile")
    def admin_reconcile(request_id: str, authorization: str | None = Header(default=None)):
        authorize_creator(authorization)
        try:
            return service.reconcile_as_creator(request_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/v1/challenges")
    def issue_challenge(
        request: FaucetChallengeRequest,
        authorization: str | None = Header(default=None),
    ):
        authorize(authorization)
        try:
            return service.issue_challenge(request)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/v1/claims")
    def claim(
        request: FaucetClaimRequest,
        authorization: str | None = Header(default=None),
    ):
        authorize(authorization)
        try:
            return service.claim(request)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/claims/{request_id}/reconcile")
    def reconcile(request_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return service.reconcile(request_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/mcp")
    def mcp_endpoint(
        payload: dict,
        authorization: str | None = Header(default=None),
        mcp_session_id: str | None = Header(default=None, alias="Mcp-Session-Id"),
    ):
        token = None
        if authorization is not None and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
        result, response_session_id = mcp.handle(
            payload,
            token=token,
            session_id=mcp_session_id,
        )
        headers = {}
        if response_session_id is not None:
            headers["Mcp-Session-Id"] = response_session_id
        if result is None:
            return Response(status_code=202, headers=headers)
        if "error" in result and result["error"].get("code") == -32001:
            return JSONResponse(result, status_code=401, headers=headers)
        return JSONResponse(result, headers=headers)

    return app
