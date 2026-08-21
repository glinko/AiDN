import hashlib
import json
from datetime import UTC, datetime
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
    def __init__(
        self,
        store,
        *,
        operation_recorder=None,
        record_creation_operation: bool = True,
        record_update_operation: bool = True,
    ) -> None:
        self.store = store
        self.operation_recorder = operation_recorder
        # Validator-mode Endpoint creation is a local draft operation. The
        # canonical ENDPOINT_PUBLISH transaction is submitted separately.
        self.record_creation_operation = record_creation_operation
        # Draft configuration changes are also local projections in validator
        # mode. A future typed consensus transition will own published edits.
        self.record_update_operation = record_update_operation

    def list_endpoints(self) -> list[EndpointManifest]:
        return self.store.list_manifests()

    def get_endpoint(self, endpoint_id: str) -> EndpointResult:
        return EndpointResult(endpoint=self.store.get_manifest(endpoint_id))

    def create_endpoint(self, cmd: CreateEndpointCommand) -> CreateEndpointResult:
        endpoint_id = f"ep-{uuid4().hex[:12]}"
        created_at = datetime.now(UTC).isoformat()
        execution_config = self._execution_config(
            cmd.runtime,
            cmd.publication,
            cmd.session,
            runtime_binding_id=cmd.runtime_binding_id,
            execution_strategy="local",
            proxy_target=None,
        )
        configuration_hash = self._configuration_hash(
            bundle_hash=cmd.bundle_hash,
            runtime_binding_id=cmd.runtime_binding_id,
            runtime=cmd.runtime,
            publication=cmd.publication,
            pricing=cmd.pricing,
            session=cmd.session,
            proxy_target=None,
            execution_config=execution_config,
            profile=cmd.profile,
            runtime_parameter_policy=cmd.runtime_parameter_policy,
        )
        manifest = EndpointManifest(
            endpoint_id=endpoint_id,
            owner_wallet=cmd.owner_wallet,
            created_at=created_at,
            bundle_id=cmd.bundle_id,
            bundle_hash=cmd.bundle_hash,
            runtime_binding_id=cmd.runtime_binding_id,
            configuration_hash=configuration_hash,
            display_name=cmd.display_name,
            model_class=cmd.model_class,
            capabilities=cmd.capabilities,
            runtime_parameter_policy=cmd.runtime_parameter_policy,
            profile=cmd.profile,
            runtime=cmd.runtime,
            publication=cmd.publication,
            pricing=cmd.pricing,
            session=cmd.session,
            validation=cmd.validation,
            execution_strategy="local",
            proxy_target=None,
            status="created",
        )
        snapshot = EndpointConfigurationSnapshot(
            configuration_hash=configuration_hash,
            endpoint_id=endpoint_id,
            bundle_hash=cmd.bundle_hash,
            runtime_binding_id=cmd.runtime_binding_id,
            created_at=created_at,
            profile=cmd.profile,
            runtime_parameter_policy=cmd.runtime_parameter_policy,
            runtime=cmd.runtime,
            publication=cmd.publication,
            pricing=cmd.pricing,
            session=cmd.session,
            proxy_target=None,
            execution_config=execution_config,
        )
        self.store.save_manifest(manifest)
        self.store.save_configuration_snapshot(snapshot)
        if self.record_creation_operation:
            self._record_endpoint_publish(manifest)
        return CreateEndpointResult(endpoint=manifest, snapshot=snapshot)

    def update_endpoint(self, cmd: UpdateEndpointCommand) -> UpdateEndpointResult:
        current = self.store.get_manifest(cmd.endpoint_id)
        next_runtime = cmd.runtime or current.runtime
        next_publication = cmd.publication or current.publication
        next_pricing = cmd.pricing or current.pricing
        next_session = cmd.session or current.session
        next_profile = cmd.profile or current.profile
        next_runtime_parameter_policy = (
            cmd.runtime_parameter_policy
            if cmd.runtime_parameter_policy is not None
            else current.runtime_parameter_policy
        )
        next_validation = cmd.validation or current.validation
        next_execution_strategy = cmd.execution_strategy or current.execution_strategy
        next_proxy_target = cmd.proxy_target if cmd.proxy_target is not None else current.proxy_target
        should_rotate_config = (
            cmd.profile is not None
            or cmd.runtime_parameter_policy is not None
            or cmd.runtime is not None
            or cmd.publication is not None
            or cmd.pricing is not None
            or cmd.session is not None
            or cmd.execution_strategy is not None
            or cmd.proxy_target is not None
        )
        configuration_hash = current.configuration_hash
        snapshot = None
        if should_rotate_config:
            execution_config = self._execution_config(
                next_runtime,
                next_publication,
                next_session,
                runtime_binding_id=current.runtime_binding_id,
                execution_strategy=next_execution_strategy,
                proxy_target=next_proxy_target,
            )
            configuration_hash = self._configuration_hash(
                bundle_hash=current.bundle_hash,
                runtime_binding_id=current.runtime_binding_id,
                runtime=next_runtime,
                publication=next_publication,
                pricing=next_pricing,
                session=next_session,
                proxy_target=next_proxy_target,
                execution_config=execution_config,
                profile=next_profile,
                runtime_parameter_policy=next_runtime_parameter_policy,
            )
            snapshot = EndpointConfigurationSnapshot(
                configuration_hash=configuration_hash,
                endpoint_id=current.endpoint_id,
                bundle_hash=current.bundle_hash,
                runtime_binding_id=current.runtime_binding_id,
                created_at=datetime.now(UTC).isoformat(),
                profile=next_profile,
                runtime_parameter_policy=next_runtime_parameter_policy,
                runtime=next_runtime,
                publication=next_publication,
                pricing=next_pricing,
                session=next_session,
                proxy_target=next_proxy_target,
                execution_config=execution_config,
            )
            self.store.save_configuration_snapshot(snapshot)
        updated = current.model_copy(
            update={
                "display_name": cmd.display_name or current.display_name,
                "profile": next_profile,
                "runtime_parameter_policy": next_runtime_parameter_policy,
                "runtime": next_runtime,
                "publication": next_publication,
                "pricing": next_pricing,
                "session": next_session,
                "validation": next_validation,
                "execution_strategy": next_execution_strategy,
                "proxy_target": next_proxy_target,
                "configuration_hash": configuration_hash,
            }
        )
        self.store.save_manifest(updated)
        self._record_endpoint_update(
            previous=current,
            current=updated,
            snapshot=snapshot,
        )
        return UpdateEndpointResult(endpoint=updated, snapshot=snapshot)

    def set_local_agent_use(self, endpoint_id: str, *, enabled: bool) -> EndpointResult:
        """Set the local owner-agent permission without rotating configuration.

        This value governs only the local inference gateway.  It must never
        affect Bundle identity, immutable snapshots, publication hashes, or
        consensus operations.
        """
        current = self.store.get_manifest(endpoint_id)
        if current.status == "deleted":
            raise EndpointStateError("Local Agent Use cannot be changed on a deleted endpoint")
        updated = current.model_copy(update={"local_agent_use": enabled})
        self.store.save_manifest(updated)
        return EndpointResult(endpoint=updated)

    def attach_proxy_target(self, endpoint_id: str, remote_endpoint) -> UpdateEndpointResult:
        current = self.store.get_manifest(endpoint_id)
        attached_at = datetime.now(UTC).isoformat()
        proxy_target = EndpointProxyTarget(
            remote_endpoint_id=remote_endpoint.remote_endpoint_id,
            source_node_id=remote_endpoint.source_node_id,
            source_endpoint_id=remote_endpoint.source_endpoint_id,
            source_publication_id=remote_endpoint.source_publication_id,
            source_configuration_hash=remote_endpoint.source_configuration_hash,
            source_base_url=remote_endpoint.source_base_url,
            source_model_class=remote_endpoint.source_model_class,
            operator_id=remote_endpoint.operator_id,
            source_owner_public_key=remote_endpoint.source_owner_public_key,
            source_wallet_signature=remote_endpoint.source_wallet_signature,
            publication_verification=remote_endpoint.publication_verification,
            alias=remote_endpoint.alias,
            attached_at=attached_at,
        )
        execution_config = self._execution_config(
            current.runtime,
            current.publication,
            current.session,
            runtime_binding_id=current.runtime_binding_id,
            execution_strategy="proxy",
            proxy_target=proxy_target,
        )
        configuration_hash = self._configuration_hash(
            bundle_hash=current.bundle_hash,
            runtime_binding_id=current.runtime_binding_id,
            runtime=current.runtime,
            publication=current.publication,
            pricing=current.pricing,
            session=current.session,
            proxy_target=proxy_target,
            execution_config=execution_config,
            profile=current.profile,
            runtime_parameter_policy=current.runtime_parameter_policy,
        )
        snapshot = EndpointConfigurationSnapshot(
            configuration_hash=configuration_hash,
            endpoint_id=current.endpoint_id,
            bundle_hash=current.bundle_hash,
            runtime_binding_id=current.runtime_binding_id,
            created_at=attached_at,
            profile=current.profile,
            runtime_parameter_policy=current.runtime_parameter_policy,
            runtime=current.runtime,
            publication=current.publication,
            pricing=current.pricing,
            session=current.session,
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
        self._record_endpoint_update(
            previous=current,
            current=updated,
            snapshot=snapshot,
        )
        return UpdateEndpointResult(endpoint=updated, snapshot=snapshot)

    def detach_proxy_target(self, endpoint_id: str) -> UpdateEndpointResult:
        current = self.store.get_manifest(endpoint_id)
        detached_at = datetime.now(UTC).isoformat()
        execution_config = self._execution_config(
            current.runtime,
            current.publication,
            current.session,
            runtime_binding_id=current.runtime_binding_id,
            execution_strategy="local",
            proxy_target=None,
        )
        configuration_hash = self._configuration_hash(
            bundle_hash=current.bundle_hash,
            runtime_binding_id=current.runtime_binding_id,
            runtime=current.runtime,
            publication=current.publication,
            pricing=current.pricing,
            session=current.session,
            proxy_target=None,
            execution_config=execution_config,
            profile=current.profile,
            runtime_parameter_policy=current.runtime_parameter_policy,
        )
        snapshot = EndpointConfigurationSnapshot(
            configuration_hash=configuration_hash,
            endpoint_id=current.endpoint_id,
            bundle_hash=current.bundle_hash,
            runtime_binding_id=current.runtime_binding_id,
            created_at=detached_at,
            profile=current.profile,
            runtime_parameter_policy=current.runtime_parameter_policy,
            runtime=current.runtime,
            publication=current.publication,
            pricing=current.pricing,
            session=current.session,
            proxy_target=None,
            execution_config=execution_config,
        )
        self.store.save_configuration_snapshot(snapshot)
        updated = current.model_copy(
            update={
                "execution_strategy": "local",
                "proxy_target": None,
                "configuration_hash": configuration_hash,
            }
        )
        self.store.save_manifest(updated)
        self._record_endpoint_update(
            previous=current,
            current=updated,
            snapshot=snapshot,
        )
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

    def disable_endpoint(self, endpoint_id: str) -> EndpointResult:
        """Stop local execution without deleting Endpoint history.

        LifecycleManager owns the durable DISABLED projection.  The manifest
        only records the executable process state, so a created/active/
        suspended endpoint can be made non-runnable through one idempotent
        local operation.
        """
        current = self.store.get_manifest(endpoint_id)
        if current.status == "deleted":
            raise EndpointStateError("Deleted Endpoint cannot be disabled")
        if current.status == "stopped":
            return EndpointResult(endpoint=current)
        updated = current.model_copy(update={"status": "stopped"})
        self.store.save_manifest(updated)
        return EndpointResult(endpoint=updated)

    def unpublish_endpoint(self, endpoint_id: str) -> EndpointResult:
        """Close discovery/external access while retaining the manifest.

        Consensus finalization is intentionally handled by the publication
        application service.  This method is the local projection used by the
        lifecycle plan/apply boundary and never erases publication history.
        """
        current = self.store.get_manifest(endpoint_id)
        if current.status == "deleted":
            raise EndpointStateError("Deleted Endpoint cannot be unpublished")
        publication = current.publication.model_copy(
            update={"discoverable": False, "accepts_external_requests": False}
        )
        if publication == current.publication:
            return EndpointResult(endpoint=current)
        updated = current.model_copy(update={"publication": publication})
        self.store.save_manifest(updated)
        return EndpointResult(endpoint=updated)

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

    def _record_endpoint_publish(self, manifest: EndpointManifest) -> None:
        if self.operation_recorder is None or not self.record_creation_operation:
            return
        self.operation_recorder(
            operation_type="ENDPOINT_PUBLISH",
            origin_type="wallet",
            fee_class="standard",
            initiator_id=manifest.owner_wallet,
            sender_wallet=manifest.owner_wallet,
            fee_payer=manifest.owner_wallet,
            payload={
                "endpoint_id": manifest.endpoint_id,
                "bundle_id": manifest.bundle_id,
                "display_name": manifest.display_name,
                "endpoint_configuration_hash": manifest.configuration_hash,
                "visibility": manifest.publication.visibility,
                "execution_strategy": manifest.execution_strategy,
            },
            created_at=manifest.created_at,
            emitted_events=["EndpointPublished"],
        )

    def _record_endpoint_update(
        self,
        *,
        previous: EndpointManifest,
        current: EndpointManifest,
        snapshot: EndpointConfigurationSnapshot | None,
    ) -> None:
        if self.operation_recorder is None or not self.record_update_operation:
            return
        self.operation_recorder(
            operation_type="ENDPOINT_UPDATE",
            origin_type="wallet",
            fee_class="standard",
            initiator_id=current.owner_wallet,
            sender_wallet=current.owner_wallet,
            fee_payer=current.owner_wallet,
            payload={
                "endpoint_id": current.endpoint_id,
                "previous_configuration_hash": previous.configuration_hash,
                "next_configuration_hash": current.configuration_hash,
                "visibility": current.publication.visibility,
                "execution_strategy": current.execution_strategy,
                "status": current.status,
            },
            created_at=(
                snapshot.created_at
                if snapshot is not None
                else datetime.now(UTC).isoformat()
            ),
            emitted_events=["EndpointUpdated"],
        )

    def _configuration_hash(
        self,
        *,
        bundle_hash: str,
        runtime_binding_id: str | None,
        runtime,
        publication,
        pricing,
        session,
        proxy_target,
        execution_config,
        profile,
        runtime_parameter_policy,
    ) -> str:
        payload = {
            "bundle_hash": bundle_hash,
            "runtime_binding_id": runtime_binding_id,
            "runtime": runtime.model_dump(mode="json"),
            "publication": publication.model_dump(mode="json"),
            "pricing": pricing.model_dump(mode="json"),
            "session": session.model_dump(mode="json"),
            "proxy_target": (
                proxy_target.model_dump(mode="json")
                if proxy_target is not None
                else None
            ),
            "execution_config": execution_config,
        }
        if runtime_parameter_policy:
            payload["runtime_parameter_policy"] = {
                key: value.model_dump(mode="json", by_alias=True)
                for key, value in runtime_parameter_policy.items()
            }
        marketplace_description = profile.model_dump(mode="json").get(
            "marketplace_description"
        )
        if marketplace_description is not None:
            payload["marketplace_description"] = marketplace_description
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))
        return digest.hexdigest()

    def _execution_config(
        self,
        runtime: EndpointRuntimeConfig,
        publication,
        session,
        *,
        runtime_binding_id: str | None,
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
            "session_queue_policy": session.queue_policy,
            "session_max_concurrency": session.max_concurrent_sessions,
            "runtime_binding_id": runtime_binding_id,
            "proxy_source_hash": (
                proxy_target.source_configuration_hash
                if proxy_target is not None
                else None
            ),
        }
