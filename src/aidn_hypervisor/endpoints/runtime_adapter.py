from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.endpoints.models import (
    EndpointManifest,
    EndpointReadiness,
    InvokeEndpointCommand,
)
from aidn_hypervisor.service import BundleRuntimeReadinessError, HypervisorService


class EndpointExecutionError(RuntimeError):
    def __init__(self, readiness: EndpointReadiness) -> None:
        super().__init__(readiness.message or "endpoint runtime is not ready")
        self.readiness = readiness
        self.code = readiness.code


class EndpointRuntimeAdapter:
    _CODE_BY_REASON = {
        "bundle_disabled": "bundle_disabled",
        "bundle_draining": "bundle_draining",
        "concurrency_limit": "concurrency_limit",
        "insufficient_resources": "insufficient_resources",
        "provider_cooldown": "provider_cooldown",
        "runtime_unavailable": "runtime_unavailable",
        "runtime_unhealthy": "runtime_unhealthy",
    }

    def __init__(self, hypervisor: HypervisorService) -> None:
        self.hypervisor = hypervisor

    def endpoint_readiness(
        self,
        endpoint: EndpointManifest,
        command: InvokeEndpointCommand,
    ) -> EndpointReadiness:
        task_request = self._task_request(endpoint, command)
        readiness = self.hypervisor.bundle_runtime_readiness(
            endpoint.bundle_id,
            task_request,
        )
        return self._endpoint_readiness(endpoint, readiness)

    def invoke_endpoint(
        self,
        endpoint: EndpointManifest,
        command: InvokeEndpointCommand,
    ) -> tuple[EndpointReadiness, dict]:
        task_request = self._task_request(endpoint, command)
        hypervisor_readiness = self.hypervisor.bundle_runtime_readiness(
            endpoint.bundle_id,
            task_request,
        )
        endpoint_readiness = self._endpoint_readiness(endpoint, hypervisor_readiness)
        if not endpoint_readiness.ready:
            raise EndpointExecutionError(endpoint_readiness)

        try:
            result = self.hypervisor.invoke_bundle_sync(
                endpoint.bundle_id,
                task_request,
                readiness=hypervisor_readiness,
            )
        except BundleRuntimeReadinessError as error:
            raise EndpointExecutionError(
                self._endpoint_readiness(endpoint, error.readiness)
            ) from error
        except Exception as error:
            raise EndpointExecutionError(
                self._failure_readiness(endpoint, hypervisor_readiness, error)
            ) from error
        return self._endpoint_readiness(endpoint, hypervisor_readiness), result

    def _failure_readiness(
        self,
        endpoint: EndpointManifest,
        readiness: dict,
        error: Exception,
    ) -> EndpointReadiness:
        message = str(error) or error.__class__.__name__
        code = "endpoint_execution_error"
        if isinstance(error, ValueError) and message == "insufficient resources":
            code = "insufficient_resources"
        return EndpointReadiness(
            endpoint_id=endpoint.endpoint_id,
            bundle_id=endpoint.bundle_id,
            ready=False,
            code=code,
            message=message,
            runtime_id=readiness.get("runtime_id"),
            runtime_status=readiness.get("runtime_status"),
            runtime_health_status=readiness.get("runtime_health_status"),
        )

    def _endpoint_readiness(
        self,
        endpoint: EndpointManifest,
        readiness: dict,
    ) -> EndpointReadiness:
        reason = readiness.get("reason")
        code = self._CODE_BY_REASON.get(reason) if isinstance(reason, str) else None
        return EndpointReadiness(
            endpoint_id=endpoint.endpoint_id,
            bundle_id=endpoint.bundle_id,
            ready=bool(readiness["ready"]),
            code=code,
            message=readiness.get("message"),
            runtime_id=readiness.get("runtime_id"),
            runtime_status=readiness.get("runtime_status"),
            runtime_health_status=readiness.get("runtime_health_status"),
        )

    def _task_request(
        self,
        endpoint: EndpointManifest,
        command: InvokeEndpointCommand,
    ) -> TaskRequest:
        return TaskRequest(
            task_type=command.task_type,
            payload=command.payload,
            mode="manual",
            bundle_override=endpoint.bundle_id,
            constraints=command.constraints,
        )
