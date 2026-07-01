import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from aidn_hypervisor.endpoints.models import (
    CreateEndpointCommand,
    CreateEndpointResult,
    EndpointConfigurationSnapshot,
    EndpointManifest,
    EndpointProxyTarget,
    EndpointResult,
    EndpointRuntimeConfig,
    UpdateEndpointCommand,
    UpdateEndpointResult,
)


class EndpointStateError(ValueError):
    pass


class EndpointService:
    def __init__(self, store) -> None:
        self.store = store

    def list_endpoints(self) -> list[EndpointManifest]:
        return self.store.list_manifests()

    def get_endpoint(self, endpoint_id: str) -> EndpointResult:
        return EndpointResult(endpoint=self.store.get_manifest(endpoint_id))

    def create_endpoint(self, cmd: CreateEndpointCommand) -> CreateEndpointResult:
        endpoint_id = f"ep-{uuid4().hex[:12]}"
        created_at = datetime.now(timezone.utc).isoformat()
        execution_config = self._execution_config(
            cmd.runtime,
            cmd.publication,
            execution_strategy="local",
            proxy_target=None,
        )
        configuration_hash = self._configuration_hash(
            bundle_hash=cmd.bundle_hash,
            runtime=cmd.runtime,
            publication=cmd.publication,
            proxy_target=None,
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
            execution_strategy="local",
            proxy_target=None,
            status="created",
        )
        snapshot = EndpointConfigurationSnapshot(
            configuration_hash=configuration_hash,
            endpoint_id=endpoint_id,
            bundle_hash=cmd.bundle_hash,
            created_at=created_at,
            runtime=cmd.runtime,
            publication=cmd.publication,
            proxy_target=None,
            execution_config=execution_config,
        )
        self.store.save_manifest(manifest)
        self.store.save_configuration_snapshot(snapshot)
        return CreateEndpointResult(endpoint=manifest, snapshot=snapshot)

    def update_endpoint(self, cmd: UpdateEndpointCommand) -> UpdateEndpointResult:
        current = self.store.get_manifest(cmd.endpoint_id)
        next_runtime = cmd.runtime or current.runtime
        next_publication = cmd.publication or current.publication
        next_validation = cmd.validation or current.validation
        next_execution_strategy = cmd.execution_strategy or current.execution_strategy
        next_proxy_target = cmd.proxy_target if cmd.proxy_target is not None else current.proxy_target
        should_rotate_config = (
            cmd.runtime is not None
            or cmd.publication is not None
            or cmd.execution_strategy is not None
            or cmd.proxy_target is not None
        )
        configuration_hash = current.configuration_hash
        snapshot = None
        if should_rotate_config:
            execution_config = self._execution_config(
                next_runtime,
                next_publication,
                execution_strategy=next_execution_strategy,
                proxy_target=next_proxy_target,
            )
            configuration_hash = self._configuration_hash(
                bundle_hash=current.bundle_hash,
                runtime=next_runtime,
                publication=next_publication,
                proxy_target=next_proxy_target,
                execution_config=execution_config,
            )
            snapshot = EndpointConfigurationSnapshot(
                configuration_hash=configuration_hash,
                endpoint_id=current.endpoint_id,
                bundle_hash=current.bundle_hash,
                created_at=datetime.now(timezone.utc).isoformat(),
                runtime=next_runtime,
                publication=next_publication,
                proxy_target=next_proxy_target,
                execution_config=execution_config,
            )
            self.store.save_configuration_snapshot(snapshot)
        updated = current.model_copy(
            update={
                "display_name": cmd.display_name or current.display_name,
                "profile": cmd.profile or current.profile,
                "runtime": next_runtime,
                "publication": next_publication,
                "pricing": cmd.pricing or current.pricing,
                "validation": next_validation,
                "execution_strategy": next_execution_strategy,
                "proxy_target": next_proxy_target,
                "configuration_hash": configuration_hash,
            }
        )
        self.store.save_manifest(updated)
        return UpdateEndpointResult(endpoint=updated, snapshot=snapshot)

    def attach_proxy_target(self, endpoint_id: str, remote_endpoint) -> UpdateEndpointResult:
        current = self.store.get_manifest(endpoint_id)
        attached_at = datetime.now(timezone.utc).isoformat()
        proxy_target = EndpointProxyTarget(
            remote_endpoint_id=remote_endpoint.remote_endpoint_id,
            source_node_id=remote_endpoint.source_node_id,
            source_endpoint_id=remote_endpoint.source_endpoint_id,
            source_publication_id=remote_endpoint.source_publication_id,
            source_configuration_hash=remote_endpoint.source_configuration_hash,
            source_base_url=remote_endpoint.source_base_url,
            source_model_class=remote_endpoint.source_model_class,
            operator_id=remote_endpoint.operator_id,
            alias=remote_endpoint.alias,
            attached_at=attached_at,
        )
        execution_config = self._execution_config(
            current.runtime,
            current.publication,
            execution_strategy="proxy",
            proxy_target=proxy_target,
        )
        configuration_hash = self._configuration_hash(
            bundle_hash=current.bundle_hash,
            runtime=current.runtime,
            publication=current.publication,
            proxy_target=proxy_target,
            execution_config=execution_config,
        )
        snapshot = EndpointConfigurationSnapshot(
            configuration_hash=configuration_hash,
            endpoint_id=current.endpoint_id,
            bundle_hash=current.bundle_hash,
            created_at=attached_at,
            runtime=current.runtime,
            publication=current.publication,
            proxy_target=proxy_target,
            execution_config=execution_config,
        )
        self.store.save_configuration_snapshot(snapshot)
        updated = current.model_copy(
            update={
                "execution_strategy": "proxy",
                "proxy_target": proxy_target,
                "configuration_hash": configuration_hash,
            }
        )
        self.store.save_manifest(updated)
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
        return self._transition(endpoint_id, allowed={"active"}, next_status="suspended")

    def resume_endpoint(self, endpoint_id: str) -> EndpointResult:
        return self._transition(endpoint_id, allowed={"suspended"}, next_status="active")

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
        self.store.save_manifest(updated)
        return EndpointResult(endpoint=updated)

    def _configuration_hash(
        self,
        *,
        bundle_hash: str,
        runtime,
        publication,
        proxy_target,
        execution_config,
    ) -> str:
        payload = {
            "bundle_hash": bundle_hash,
            "runtime": runtime.model_dump(mode="json"),
            "publication": publication.model_dump(mode="json"),
            "proxy_target": (
                proxy_target.model_dump(mode="json")
                if proxy_target is not None
                else None
            ),
            "execution_config": execution_config,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))
        return digest.hexdigest()

    def _execution_config(
        self,
        runtime: EndpointRuntimeConfig,
        publication,
        *,
        execution_strategy: str,
        proxy_target,
    ) -> dict:
        return {
            "accepts_external_requests": publication.accepts_external_requests,
            "streaming": runtime.streaming,
            "timeout": runtime.timeout,
            "max_concurrency": runtime.max_tokens,
            "execution_strategy": execution_strategy,
            "proxy_target_id": (
                proxy_target.remote_endpoint_id if proxy_target is not None else None
            ),
            "proxy_source_hash": (
                proxy_target.source_configuration_hash
                if proxy_target is not None
                else None
            ),
        }
