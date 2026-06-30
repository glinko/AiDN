from uuid import uuid4

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from aidn_hypervisor.endpoints.models import (
    CreateEndpointCommand,
    EndpointInvokeRequest,
    EndpointPricing,
    EndpointProfile,
    EndpointPublicationPolicy,
    EndpointRuntimeConfig,
    EndpointValidationState,
    InvokeEndpointCommand,
    UpdateEndpointCommand,
)
from aidn_hypervisor.endpoints.runtime_adapter import EndpointExecutionError
from aidn_hypervisor.endpoints.service import EndpointService, EndpointStateError

ENDPOINT_API_PREFIX = "/api/v1/endpoints"


class UpdateEndpointRequest(BaseModel):
    display_name: str | None = None
    capabilities: list[str] | None = None
    profile: EndpointProfile | None = None
    runtime: EndpointRuntimeConfig | None = None
    publication: EndpointPublicationPolicy | None = None
    pricing: EndpointPricing | None = None
    validation: EndpointValidationState | None = None


def build_endpoint_router(service: EndpointService) -> APIRouter:
    router = APIRouter(prefix=ENDPOINT_API_PREFIX, tags=["endpoints"])

    @router.get("")
    async def list_endpoints(request: Request) -> JSONResponse:
        return _success(
            request,
            [
                endpoint.model_dump(mode="json")
                for endpoint in service.list_endpoints()
            ],
        )

    @router.get("/{endpoint_id}")
    async def get_endpoint(endpoint_id: str, request: Request) -> JSONResponse:
        try:
            endpoint = service.get_endpoint(endpoint_id)
        except KeyError:
            return _not_found(request, endpoint_id)
        return _success(request, endpoint.model_dump(mode="json"))

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def create_endpoint(
        command: CreateEndpointCommand,
        request: Request,
    ) -> JSONResponse:
        result = service.create_endpoint(command)
        return _success(
            request,
            result.model_dump(mode="json"),
            status_code=status.HTTP_201_CREATED,
        )

    @router.patch("/{endpoint_id}")
    async def update_endpoint(
        endpoint_id: str,
        command: UpdateEndpointRequest,
        request: Request,
    ) -> JSONResponse:
        try:
            result = service.update_endpoint(
                UpdateEndpointCommand(
                    endpoint_id=endpoint_id,
                    **command.model_dump(mode="python", exclude_unset=True),
                )
            )
        except KeyError:
            return _not_found(request, endpoint_id)
        except EndpointStateError as error:
            return _state_error(request, str(error))
        return _success(request, result.model_dump(mode="json"))

    @router.post("/{endpoint_id}/invoke")
    async def invoke_endpoint(
        endpoint_id: str,
        command: EndpointInvokeRequest,
        request: Request,
    ) -> JSONResponse:
        try:
            result = service.invoke_endpoint(
                InvokeEndpointCommand(
                    endpoint_id=endpoint_id,
                    **command.model_dump(mode="python", exclude_unset=True),
                )
            )
        except KeyError:
            return _not_found(request, endpoint_id)
        except EndpointStateError as error:
            return _not_active(request, str(error))
        except EndpointExecutionError as error:
            return _error(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code=error.code or "endpoint_execution_error",
                message=error.readiness.message or str(error),
            )
        return _success(request, result.model_dump(mode="json"))

    @router.post("/{endpoint_id}/start")
    async def start_endpoint(endpoint_id: str, request: Request) -> JSONResponse:
        return _lifecycle(request, endpoint_id, service.start_endpoint)

    @router.post("/{endpoint_id}/stop")
    async def stop_endpoint(endpoint_id: str, request: Request) -> JSONResponse:
        return _lifecycle(request, endpoint_id, service.stop_endpoint)

    @router.post("/{endpoint_id}/suspend")
    async def suspend_endpoint(endpoint_id: str, request: Request) -> JSONResponse:
        return _lifecycle(request, endpoint_id, service.suspend_endpoint)

    @router.post("/{endpoint_id}/resume")
    async def resume_endpoint(endpoint_id: str, request: Request) -> JSONResponse:
        return _lifecycle(request, endpoint_id, service.resume_endpoint)

    @router.delete("/{endpoint_id}")
    async def delete_endpoint(endpoint_id: str, request: Request) -> JSONResponse:
        return _lifecycle(request, endpoint_id, service.delete_endpoint)

    return router


def _lifecycle(request: Request, endpoint_id: str, operation) -> JSONResponse:
    try:
        result = operation(endpoint_id)
    except KeyError:
        return _not_found(request, endpoint_id)
    except EndpointStateError as error:
        return _state_error(request, str(error))
    return _success(request, result.model_dump(mode="json"))


def _success(
    request: Request,
    data,
    *,
    status_code: int = status.HTTP_200_OK,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "data": data,
            "error": None,
            "correlation_id": _correlation_id(request),
        },
    )


def _not_found(request: Request, endpoint_id: str) -> JSONResponse:
    return _error(
        request,
        status_code=status.HTTP_404_NOT_FOUND,
        code="endpoint_not_found",
        message=f"Unknown endpoint: {endpoint_id}",
    )


def _state_error(request: Request, message: str) -> JSONResponse:
    return _error(
        request,
        status_code=status.HTTP_409_CONFLICT,
        code="endpoint_state_error",
        message=message,
    )


def _not_active(request: Request, message: str) -> JSONResponse:
    return _error(
        request,
        status_code=status.HTTP_409_CONFLICT,
        code="endpoint_not_active",
        message=message,
    )


def validation_error(request: Request) -> JSONResponse:
    return _error(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="endpoint_validation_error",
        message="Request validation failed",
    )


def _error(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "data": None,
            "error": {
                "code": code,
                "message": message,
            },
            "correlation_id": _correlation_id(request),
        },
    )


def _correlation_id(request: Request) -> str:
    header_value = request.headers.get("x-correlation-id")
    if header_value:
        return header_value
    return uuid4().hex
