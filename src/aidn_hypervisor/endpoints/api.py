from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from aidn_hypervisor.endpoints.models import CreateEndpointCommand, UpdateEndpointCommand
from pydantic import BaseModel


class AttachProxyTargetRequest(BaseModel):
    remote_endpoint_id: str


class OpenSessionRequest(BaseModel):
    client_wallet: str
    deposit_q: float


def build_endpoint_router(
    service,
    remote_endpoint_service=None,
    session_service=None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/endpoints")

    def _ok(data: dict, *, status_code: int = 200) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "data": data,
                "error": None,
                "correlation_id": str(uuid4()),
            },
        )

    def _error(status_code: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "data": None,
                "error": {"code": code, "message": message},
                "correlation_id": str(uuid4()),
            },
        )

    @router.get("")
    async def list_endpoints() -> JSONResponse:
        items = [item.model_dump(mode="json") for item in service.list_endpoints()]
        return _ok({"items": items})

    @router.post("", status_code=201)
    async def create_endpoint(command: CreateEndpointCommand) -> JSONResponse:
        created = service.create_endpoint(command)
        return _ok(
            {
                "endpoint": created.endpoint.model_dump(mode="json"),
                "snapshot": created.snapshot.model_dump(mode="json"),
            },
            status_code=201,
        )

    @router.get("/{endpoint_id}")
    async def get_endpoint(endpoint_id: str) -> JSONResponse:
        try:
            result = service.get_endpoint(endpoint_id)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        return _ok({"endpoint": result.endpoint.model_dump(mode="json")})

    @router.patch("/{endpoint_id}")
    async def update_endpoint(
        endpoint_id: str,
        command: UpdateEndpointCommand,
    ) -> JSONResponse:
        if command.endpoint_id != endpoint_id:
            command = command.model_copy(update={"endpoint_id": endpoint_id})
        try:
            updated = service.update_endpoint(command)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        return _ok(
            {
                "endpoint": updated.endpoint.model_dump(mode="json"),
                "snapshot": (
                    updated.snapshot.model_dump(mode="json")
                    if updated.snapshot is not None
                    else None
                ),
            }
        )

    @router.post("/{endpoint_id}/proxy-target")
    async def attach_proxy_target(
        endpoint_id: str,
        request: AttachProxyTargetRequest,
    ) -> JSONResponse:
        if remote_endpoint_service is None:
            return _error(
                503,
                "remote_endpoint_unavailable",
                "Remote endpoint service is not configured",
            )
        try:
            remote_endpoint = remote_endpoint_service.get_remote_endpoint(
                request.remote_endpoint_id
            )
        except KeyError:
            return _error(
                404,
                "remote_endpoint_not_found",
                f"Unknown remote endpoint: {request.remote_endpoint_id}",
            )
        try:
            updated = service.attach_proxy_target(endpoint_id, remote_endpoint)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        return _ok(
            {
                "endpoint": updated.endpoint.model_dump(mode="json"),
                "snapshot": (
                    updated.snapshot.model_dump(mode="json")
                    if updated.snapshot is not None
                    else None
                ),
            }
        )

    @router.post("/{endpoint_id}/sessions", status_code=201)
    async def open_session(
        endpoint_id: str,
        request: OpenSessionRequest,
    ) -> JSONResponse:
        if session_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        try:
            endpoint = service.get_endpoint(endpoint_id).endpoint
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        try:
            result = session_service.open_session(
                endpoint_id=endpoint_id,
                client_wallet=request.client_wallet,
                provider_wallet=endpoint.owner_wallet,
                node_id="node-local",
                deposit_q=request.deposit_q,
                session_policy=endpoint.session.model_dump(mode="json"),
            )
        except ValueError as error:
            return _error(409, "session_open_rejected", str(error))
        return _ok(
            {
                "session": result.session.model_dump(mode="json"),
                "deposit": result.deposit.model_dump(mode="json"),
            },
            status_code=201,
        )

    return router
