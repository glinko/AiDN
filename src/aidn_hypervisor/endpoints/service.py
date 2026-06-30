import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from aidn_hypervisor.endpoints.models import (
    CreateEndpointCommand,
    CreateEndpointResult,
    EndpointConfigurationSnapshot,
    EndpointManifest,
    EndpointPricing,
    EndpointProfile,
    EndpointPublicationPolicy,
    EndpointReadiness,
    EndpointResult,
    EndpointRuntimeConfig,
    EndpointValidationState,
    InvokeEndpointCommand,
    InvokeEndpointResult,
    UpdateEndpointCommand,
    UpdateEndpointResult,
)
from aidn_hypervisor.endpoints.runtime_adapter import EndpointRuntimeAdapter
from aidn_hypervisor.endpoints.store import EndpointStore


class EndpointStateError(ValueError):
    pass


class EndpointService:
    def __init__(
        self,
        store: EndpointStore,
        runtime_adapter: EndpointRuntimeAdapter | None = None,
    ) -> None:
        self.store = store
        self.runtime_adapter = runtime_adapter

    def list_endpoints(self) -> list[EndpointManifest]:
        return self.store.list_manifests()

    def get_endpoint(self, endpoint_id: str) -> EndpointManifest:
        return self.store.get_manifest(endpoint_id)

    def create_endpoint(self, cmd: CreateEndpointCommand) -> CreateEndpointResult:
        endpoint_id = f"ep-{uuid4().hex[:12]}"
        created_at = datetime.now(timezone.utc).isoformat()
        execution_config = self._execution_config(cmd.runtime, cmd.publication)
        configuration_hash = self._configuration_hash(
            bundle_hash=cmd.bundle_hash,
            runtime=cmd.runtime,
            publication=cmd.publication,
            execution_config=execution_config,
        )
        manifest = EndpointManifest(
            endpoint_id=endpoint_id,
            owner_wallet=cmd.owner_wallet,
            created_at=created_at,
            bundle_id=cmd.bundle_id,
            bundle_hash=cmd.bundle_hash,
            configuration_hash=configuration_hash,
            display_name=cmd.display_name,
            model_class=cmd.model_class,
            capabilities=cmd.capabilities,
            profile=cmd.profile,
            runtime=cmd.runtime,
            publication=cmd.publication,
            pricing=cmd.pricing,
            validation=cmd.validation,
            status="created",
        )
        snapshot = EndpointConfigurationSnapshot(
            configuration_hash=configuration_hash,
            endpoint_id=endpoint_id,
            bundle_hash=cmd.bundle_hash,
            created_at=created_at,
            runtime=cmd.runtime,
            publication=cmd.publication,
            execution_config=execution_config,
        )
        self.store.save_endpoint(manifest, snapshot)
        return CreateEndpointResult(endpoint=manifest, snapshot=snapshot)

    def update_endpoint(self, cmd: UpdateEndpointCommand) -> UpdateEndpointResult:
        current = self.store.get_manifest(cmd.endpoint_id)
        if current.status == "deleted":
            raise EndpointStateError(f"Endpoint {cmd.endpoint_id} is deleted")

        next_runtime = self._merge_runtime(current.runtime, cmd.runtime)
        next_publication = self._merge_publication(
            current.publication, cmd.publication
        )
        next_profile = self._merge_profile(current.profile, cmd.profile)
        next_pricing = self._merge_pricing(current.pricing, cmd.pricing)
        next_validation = self._merge_validation(current.validation, cmd.validation)
        should_rotate_config = (
            next_runtime != current.runtime or next_publication != current.publication
        )
        configuration_hash = current.configuration_hash
        snapshot = None
        if should_rotate_config:
            execution_config = self._execution_config(next_runtime, next_publication)
            configuration_hash = self._configuration_hash(
                bundle_hash=current.bundle_hash,
                runtime=next_runtime,
                publication=next_publication,
                execution_config=execution_config,
            )
            snapshot = EndpointConfigurationSnapshot(
                configuration_hash=configuration_hash,
                endpoint_id=current.endpoint_id,
                bundle_hash=current.bundle_hash,
                created_at=datetime.now(timezone.utc).isoformat(),
                runtime=next_runtime,
                publication=next_publication,
                execution_config=execution_config,
            )

        updated = current.model_copy(
            update={
                "display_name": (
                    cmd.display_name
                    if cmd.display_name is not None
                    else current.display_name
                ),
                "capabilities": (
                    cmd.capabilities
                    if cmd.capabilities is not None
                    else current.capabilities
                ),
                "profile": next_profile,
                "runtime": next_runtime,
                "publication": next_publication,
                "pricing": next_pricing,
                "validation": next_validation,
                "configuration_hash": configuration_hash,
            }
        )
        self.store.save_endpoint(updated, snapshot)
        return UpdateEndpointResult(endpoint=updated, snapshot=snapshot)

    def start_endpoint(self, endpoint_id: str) -> EndpointResult:
        return self._transition(
            endpoint_id,
            allowed={"created", "stopped"},
            next_status="active",
        )

    def stop_endpoint(self, endpoint_id: str) -> EndpointResult:
        return self._transition(
            endpoint_id,
            allowed={"active", "suspended"},
            next_status="stopped",
        )

    def suspend_endpoint(self, endpoint_id: str) -> EndpointResult:
        return self._transition(
            endpoint_id,
            allowed={"active"},
            next_status="suspended",
        )

    def resume_endpoint(self, endpoint_id: str) -> EndpointResult:
        return self._transition(
            endpoint_id,
            allowed={"suspended"},
            next_status="active",
        )

    def delete_endpoint(self, endpoint_id: str) -> EndpointResult:
        return self._transition(
            endpoint_id,
            allowed={"created", "stopped", "active", "suspended"},
            next_status="deleted",
        )

    def list_configuration_snapshots(
        self, endpoint_id: str
    ) -> list[EndpointConfigurationSnapshot]:
        return self.store.list_configuration_snapshots(endpoint_id)

    def endpoint_readiness(
        self,
        endpoint_id: str,
        command: InvokeEndpointCommand,
    ) -> EndpointReadiness:
        if command.endpoint_id != endpoint_id:
            raise EndpointStateError(
                f"Command endpoint_id {command.endpoint_id} does not match {endpoint_id}"
            )
        endpoint = self.store.get_manifest(endpoint_id)
        if endpoint.status != "active":
            raise EndpointStateError(f"Endpoint {endpoint.endpoint_id} is not active")
        return self._require_runtime_adapter().endpoint_readiness(endpoint, command)

    def invoke_endpoint(self, cmd: InvokeEndpointCommand) -> InvokeEndpointResult:
        endpoint = self.store.get_manifest(cmd.endpoint_id)
        if endpoint.status != "active":
            raise EndpointStateError(f"Endpoint {endpoint.endpoint_id} is not active")

        readiness, result = self._require_runtime_adapter().invoke_endpoint(endpoint, cmd)
        runtime_id = readiness.runtime_id
        if runtime_id is None:
            raise RuntimeError(
                f"Ready endpoint invocation did not return a runtime_id: {endpoint.endpoint_id}"
            )
        return InvokeEndpointResult(
            endpoint=endpoint,
            bundle_id=endpoint.bundle_id,
            runtime_id=runtime_id,
            readiness=readiness,
            result=result,
        )

    def _transition(
        self,
        endpoint_id: str,
        *,
        allowed: set[str],
        next_status: str,
    ) -> EndpointResult:
        current = self.store.get_manifest(endpoint_id)
        if current.status not in allowed:
            raise EndpointStateError(
                f"Endpoint {endpoint_id} cannot move from {current.status} to {next_status}"
            )
        updated = current.model_copy(update={"status": next_status})
        self.store.save_endpoint(updated)
        return EndpointResult(endpoint=updated)

    def _configuration_hash(
        self,
        *,
        bundle_hash: str,
        runtime: EndpointRuntimeConfig,
        publication: EndpointPublicationPolicy,
        execution_config: dict[str, bool | int | str | None],
    ) -> str:
        payload = {
            "bundle_hash": bundle_hash,
            "runtime": runtime.model_dump(mode="json"),
            "publication": publication.model_dump(mode="json"),
            "execution_config": execution_config,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _execution_config(
        self,
        runtime: EndpointRuntimeConfig,
        publication: EndpointPublicationPolicy,
    ) -> dict[str, bool | int | str | None]:
        return {
            "accepts_external_requests": publication.accepts_external_requests,
            "streaming": runtime.streaming,
            "timeout": runtime.timeout,
            "max_concurrency": runtime.max_tokens,
        }

    def _merge_runtime(
        self,
        current: EndpointRuntimeConfig,
        patch: EndpointRuntimeConfig | None,
    ) -> EndpointRuntimeConfig:
        if patch is None:
            return current
        return EndpointRuntimeConfig.model_validate(
            {
                **current.model_dump(mode="python"),
                **patch.model_dump(mode="python", exclude_unset=True),
            }
        )

    def _merge_publication(
        self,
        current: EndpointPublicationPolicy,
        patch: EndpointPublicationPolicy | None,
    ) -> EndpointPublicationPolicy:
        if patch is None:
            return current
        return EndpointPublicationPolicy.model_validate(
            {
                **current.model_dump(mode="python"),
                **patch.model_dump(mode="python", exclude_unset=True),
            }
        )

    def _merge_profile(
        self,
        current: EndpointProfile,
        patch: EndpointProfile | None,
    ) -> EndpointProfile:
        if patch is None:
            return current
        return EndpointProfile.model_validate(
            {
                **current.model_dump(mode="python"),
                **patch.model_dump(mode="python", exclude_unset=True),
            }
        )

    def _merge_pricing(
        self,
        current: EndpointPricing,
        patch: EndpointPricing | None,
    ) -> EndpointPricing:
        if patch is None:
            return current
        return EndpointPricing.model_validate(
            {
                **current.model_dump(mode="python"),
                **patch.model_dump(mode="python", exclude_unset=True),
            }
        )

    def _merge_validation(
        self,
        current: EndpointValidationState,
        patch: EndpointValidationState | None,
    ) -> EndpointValidationState:
        if patch is None:
            return current
        return EndpointValidationState.model_validate(
            {
                **current.model_dump(mode="python"),
                **patch.model_dump(mode="python", exclude_unset=True),
            }
        )

    def _require_runtime_adapter(self) -> EndpointRuntimeAdapter:
        if self.runtime_adapter is None:
            raise RuntimeError("Endpoint runtime adapter is not configured")
        return self.runtime_adapter
