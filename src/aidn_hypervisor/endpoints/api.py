from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from aidn_hypervisor.endpoints.models import CreateEndpointCommand, UpdateEndpointCommand
from pydantic import BaseModel, Field


class AttachProxyTargetRequest(BaseModel):
    remote_endpoint_id: str


class OpenSessionRequest(BaseModel):
    client_wallet: str
    deposit_q: float


class OpenMvpFixedPriceSessionRequest(BaseModel):
    client_wallet: str
    deposit_q_atoms: int = Field(gt=0)
    fixed_price_q_atoms: int = Field(ge=0)
    network_fee_reserve_q_atoms: int = Field(default=0, ge=0)


def build_endpoint_router(
    service,
    hypervisor_service=None,
    remote_endpoint_service=None,
    session_service=None,
    validation_service=None,
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
    async def create_endpoint(payload: dict) -> JSONResponse:
        command_data = dict(payload)
        runtime_binding_id = command_data.get("runtime_binding_id")
        if runtime_binding_id and hypervisor_service is not None:
            compatibility_bundle = hypervisor_service.bundle_for_runtime_binding(
                str(runtime_binding_id)
            )
            command_data["bundle_id"] = compatibility_bundle.bundle_id
            command_data["bundle_hash"] = command_data.get("bundle_hash") or (
                hypervisor_service.bundle_hash_for_runtime_binding(
                    str(runtime_binding_id)
                )
            )
        command = CreateEndpointCommand(**command_data)
        created = service.create_endpoint(command)
        onboarding = None
        if hypervisor_service is not None:
            onboarding = hypervisor_service.sync_operator_onboarding_state(
                endpoint_items=[
                    {
                        "endpoint_id": created.endpoint.endpoint_id,
                        "bundle_id": created.endpoint.bundle_id,
                        "publication_status": "configured",
                        "visibility": created.endpoint.publication.visibility,
                    }
                ]
            )
        return _ok(
            {
                "endpoint": created.endpoint.model_dump(mode="json"),
                "snapshot": created.snapshot.model_dump(mode="json"),
                "onboarding": onboarding,
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
            current = service.get_endpoint(endpoint_id).endpoint
            updated = service.update_endpoint(command)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        if (
            validation_service is not None
            and updated.snapshot is not None
            and current.configuration_hash != updated.endpoint.configuration_hash
        ):
            validation_service.supersede_configuration(
                endpoint_id=endpoint_id,
                previous_configuration_hash=current.configuration_hash,
                replacement_configuration_hash=updated.endpoint.configuration_hash,
                superseded_at=updated.snapshot.created_at,
            )
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
            current = service.get_endpoint(endpoint_id).endpoint
            updated = service.attach_proxy_target(endpoint_id, remote_endpoint)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        if (
            validation_service is not None
            and updated.snapshot is not None
            and current.configuration_hash != updated.endpoint.configuration_hash
        ):
            validation_service.supersede_configuration(
                endpoint_id=endpoint_id,
                previous_configuration_hash=current.configuration_hash,
                replacement_configuration_hash=updated.endpoint.configuration_hash,
                superseded_at=updated.snapshot.created_at,
            )
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

    @router.delete("/{endpoint_id}/proxy-target")
    async def detach_proxy_target(endpoint_id: str) -> JSONResponse:
        try:
            current = service.get_endpoint(endpoint_id).endpoint
            updated = service.detach_proxy_target(endpoint_id)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        if (
            validation_service is not None
            and updated.snapshot is not None
            and current.configuration_hash != updated.endpoint.configuration_hash
        ):
            validation_service.supersede_configuration(
                endpoint_id=endpoint_id,
                previous_configuration_hash=current.configuration_hash,
                replacement_configuration_hash=updated.endpoint.configuration_hash,
                superseded_at=updated.snapshot.created_at,
            )
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
            accounting_contract = None
            if hypervisor_service is not None:
                try:
                    accounting_contract = hypervisor_service.accounting_contract_for_endpoint(
                        endpoint
                    )
                except KeyError:
                    accounting_contract = None
            result = session_service.open_session(
                endpoint_id=endpoint_id,
                client_wallet=request.client_wallet,
                provider_wallet=endpoint.owner_wallet,
                node_id="node-local",
                deposit_q=request.deposit_q,
                session_policy=endpoint.session.model_dump(mode="json"),
                accounting_contract=accounting_contract,
                endpoint_configuration_hash=endpoint.configuration_hash,
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

    @router.post("/{endpoint_id}/mvp-sessions", status_code=201)
    async def open_mvp_fixed_price_session(
        endpoint_id: str,
        request: OpenMvpFixedPriceSessionRequest,
    ) -> JSONResponse:
        if session_service is None or hypervisor_service is None:
            return _error(
                503,
                "mvp_session_unavailable",
                "MVP economic Session service is not configured",
            )
        try:
            endpoint = service.get_endpoint(endpoint_id).endpoint
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        try:
            accounting_contract = hypervisor_service.accounting_contract_for_endpoint(
                endpoint
            )
        except KeyError:
            accounting_contract = None
        try:
            session, deposit, funding = hypervisor_service.open_mvp_fixed_price_session(
                session_service=session_service,
                endpoint=endpoint,
                client_wallet=request.client_wallet,
                deposit_q_atoms=request.deposit_q_atoms,
                fixed_price_q_atoms=request.fixed_price_q_atoms,
                network_fee_reserve_q_atoms=request.network_fee_reserve_q_atoms,
                accounting_contract=accounting_contract,
            )
        except ValueError as error:
            return _error(409, "mvp_session_open_rejected", str(error))
        return _ok(
            {
                "session": session.model_dump(mode="json"),
                "deposit": deposit.model_dump(mode="json"),
                "funding": funding.model_dump(mode="json"),
            },
            status_code=201,
        )

    return router
