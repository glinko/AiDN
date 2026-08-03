from __future__ import annotations

from aidn_hypervisor.endpoints.models import (
    CreateEndpointCommand,
    UpdateEndpointCommand,
)


class RemoteEndpointServiceUnavailableError(RuntimeError):
    """Raised when proxy attachment is requested without remote endpoint support."""


class RemoteEndpointNotFoundError(KeyError):
    """Raised when the requested remote endpoint does not exist."""


class EndpointApplicationService:
    """Application-layer orchestration for endpoint write flows."""

    def __init__(
        self,
        *,
        endpoint_service,
        hypervisor_service=None,
        remote_endpoint_service=None,
        validation_service=None,
    ) -> None:
        self._endpoint_service = endpoint_service
        self._hypervisor_service = hypervisor_service
        self._remote_endpoint_service = remote_endpoint_service
        self._validation_service = validation_service

    def create_endpoint(self, payload: dict) -> dict:
        command_data = dict(payload)
        runtime_binding_id = command_data.get("runtime_binding_id")
        if runtime_binding_id and self._hypervisor_service is not None:
            admission = self._hypervisor_service.runtime_binding_endpoint_admission(
                str(runtime_binding_id),
                endpoint_payload=command_data,
            )
            if not admission["ready"]:
                raise ValueError("endpoint_admission_blocked")
            compatibility_bundle = self._hypervisor_service.bundle_for_runtime_binding(
                str(runtime_binding_id)
            )
            command_data["bundle_id"] = compatibility_bundle.bundle_id
            command_data["bundle_hash"] = command_data.get("bundle_hash") or (
                self._hypervisor_service.bundle_hash_for_runtime_binding(
                    str(runtime_binding_id)
                )
            )

        command = CreateEndpointCommand(**command_data)
        created = self._endpoint_service.create_endpoint(command)
        onboarding = None
        if self._hypervisor_service is not None:
            onboarding = self._hypervisor_service.sync_operator_onboarding_state(
                endpoint_items=[
                    {
                        "endpoint_id": created.endpoint.endpoint_id,
                        "bundle_id": created.endpoint.bundle_id,
                        "publication_status": "configured",
                        "visibility": created.endpoint.publication.visibility,
                    }
                ]
            )
        return {
            "created": created,
            "onboarding": onboarding,
            "payload": {
                "endpoint": created.endpoint.model_dump(mode="json"),
                "snapshot": created.snapshot.model_dump(mode="json"),
                "onboarding": onboarding,
            },
        }

    def update_endpoint(self, endpoint_id: str, command: UpdateEndpointCommand) -> dict:
        if command.endpoint_id != endpoint_id:
            command = command.model_copy(update={"endpoint_id": endpoint_id})
        current = self._endpoint_service.get_endpoint(endpoint_id).endpoint
        updated = self._endpoint_service.update_endpoint(command)
        self._supersede_validation_if_needed(
            endpoint_id=endpoint_id,
            previous_configuration_hash=current.configuration_hash,
            updated=updated,
        )
        return {
            "updated": updated,
            "payload": {
                "endpoint": updated.endpoint.model_dump(mode="json"),
                "snapshot": (
                    updated.snapshot.model_dump(mode="json")
                    if updated.snapshot is not None
                    else None
                ),
            },
        }

    def delete_endpoint(self, endpoint_id: str) -> dict:
        """Soft-delete an Endpoint and schedule its report custody grace."""
        deleted = self._endpoint_service.delete_endpoint(endpoint_id)
        retirements = []
        if self._validation_service is not None:
            retirements = self._validation_service.request_endpoint_retirement(
                endpoint_id=endpoint_id,
            )
        return {
            "deleted": deleted,
            "retirements": retirements,
            "payload": {
                "endpoint": deleted.endpoint.model_dump(mode="json"),
                "custody_retirements": [
                    item.model_dump(mode="json") for item in retirements
                ],
            },
        }

    def attach_proxy_target(self, endpoint_id: str, remote_endpoint_id: str) -> dict:
        if self._remote_endpoint_service is None:
            raise RemoteEndpointServiceUnavailableError(
                "Remote endpoint service is not configured"
            )
        try:
            remote_endpoint = self._remote_endpoint_service.get_remote_endpoint(
                remote_endpoint_id
            )
        except KeyError as error:
            raise RemoteEndpointNotFoundError(remote_endpoint_id) from error
        current = self._endpoint_service.get_endpoint(endpoint_id).endpoint
        updated = self._endpoint_service.attach_proxy_target(
            endpoint_id, remote_endpoint
        )
        self._supersede_validation_if_needed(
            endpoint_id=endpoint_id,
            previous_configuration_hash=current.configuration_hash,
            updated=updated,
        )
        return {
            "updated": updated,
            "payload": {
                "endpoint": updated.endpoint.model_dump(mode="json"),
                "snapshot": (
                    updated.snapshot.model_dump(mode="json")
                    if updated.snapshot is not None
                    else None
                ),
            },
        }

    def detach_proxy_target(self, endpoint_id: str) -> dict:
        current = self._endpoint_service.get_endpoint(endpoint_id).endpoint
        updated = self._endpoint_service.detach_proxy_target(endpoint_id)
        self._supersede_validation_if_needed(
            endpoint_id=endpoint_id,
            previous_configuration_hash=current.configuration_hash,
            updated=updated,
        )
        return {
            "updated": updated,
            "payload": {
                "endpoint": updated.endpoint.model_dump(mode="json"),
                "snapshot": (
                    updated.snapshot.model_dump(mode="json")
                    if updated.snapshot is not None
                    else None
                ),
            },
        }

    def _supersede_validation_if_needed(
        self,
        *,
        endpoint_id: str,
        previous_configuration_hash: str,
        updated,
    ) -> None:
        if (
            self._validation_service is None
            or updated.snapshot is None
            or previous_configuration_hash == updated.endpoint.configuration_hash
        ):
            return
        self._validation_service.supersede_configuration(
            endpoint_id=endpoint_id,
            previous_configuration_hash=previous_configuration_hash,
            replacement_configuration_hash=updated.endpoint.configuration_hash,
            superseded_at=updated.snapshot.created_at,
        )
