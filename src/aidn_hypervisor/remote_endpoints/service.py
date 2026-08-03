from datetime import UTC, datetime
from uuid import uuid4

from aidn_hypervisor.remote_endpoints.models import (
    RemoteEndpointReference,
    RemoteEndpointRoutingMode,
    RemotePublicationVerification,
)


class RemoteEndpointDependencyError(RuntimeError):
    def __init__(
        self,
        remote_endpoint_id: str,
        dependent_endpoint_ids: list[str],
    ) -> None:
        super().__init__(
            f"remote endpoint {remote_endpoint_id} is still used by local endpoints"
        )
        self.remote_endpoint_id = remote_endpoint_id
        self.dependent_endpoint_ids = dependent_endpoint_ids


class RemoteEndpointService:
    def __init__(self, store) -> None:
        self.store = store

    def list_remote_endpoints(self) -> list[RemoteEndpointReference]:
        return self.store.list_records()

    def get_remote_endpoint(self, remote_endpoint_id: str) -> RemoteEndpointReference:
        for record in self.store.list_records():
            if record.remote_endpoint_id == remote_endpoint_id:
                return record
        raise KeyError(remote_endpoint_id)

    def detach_remote_endpoint(
        self,
        remote_endpoint_id: str,
        *,
        endpoint_service,
    ) -> RemoteEndpointReference:
        detached = self.get_remote_endpoint(remote_endpoint_id)
        dependent_endpoint_ids: list[str] = []
        for manifest in endpoint_service.store.list_manifests():
            proxy_target = manifest.proxy_target
            if (
                manifest.status != "deleted"
                and proxy_target is not None
                and proxy_target.remote_endpoint_id == remote_endpoint_id
            ):
                dependent_endpoint_ids.append(manifest.endpoint_id)
        if dependent_endpoint_ids:
            raise RemoteEndpointDependencyError(
                remote_endpoint_id=remote_endpoint_id,
                dependent_endpoint_ids=dependent_endpoint_ids,
            )
        self.store.replace_records(
            [
                item
                for item in self.store.list_records()
                if item.remote_endpoint_id != remote_endpoint_id
            ]
        )
        return detached

    def attach_remote_endpoint(
        self,
        *,
        source_node_id: str,
        source_endpoint_id: str,
        source_owner_wallet: str,
        source_publication_id: str,
        source_configuration_hash: str,
        source_visibility: str,
        source_model_class: str,
        source_status: str,
        source_base_url: str,
        operator_id: str,
        source_owner_public_key: str | None = None,
        source_wallet_signature: str | None = None,
        publication_verification: RemotePublicationVerification = "LEGACY_UNVERIFIED",
        pricing: dict[str, str | int | float | None],
        rating: dict[str, str | int | float | None],
        session_policy: dict | None = None,
        alias: str | None = None,
        routing_mode: RemoteEndpointRoutingMode = "preferred",
    ) -> RemoteEndpointReference:
        if publication_verification == "VERIFIED" and not (
            source_owner_public_key and source_wallet_signature
        ):
            raise ValueError(
                "Verified remote Endpoint publication requires owner key and signature"
            )
        records = self.store.list_records()
        now = datetime.now(UTC).isoformat()
        existing = next(
            (
                item
                for item in records
                if item.source_node_id == source_node_id
                and item.source_endpoint_id == source_endpoint_id
            ),
            None,
        )
        if existing is None:
            attached = RemoteEndpointReference(
                remote_endpoint_id=f"remote-{uuid4().hex[:12]}",
                source_node_id=source_node_id,
                source_endpoint_id=source_endpoint_id,
                source_owner_wallet=source_owner_wallet,
                source_publication_id=source_publication_id,
                source_configuration_hash=source_configuration_hash,
                source_visibility=source_visibility,
                source_model_class=source_model_class,
                source_status=source_status,
                source_base_url=source_base_url,
                operator_id=operator_id,
                source_owner_public_key=source_owner_public_key,
                source_wallet_signature=source_wallet_signature,
                publication_verification=publication_verification,
                alias=alias,
                routing_mode=routing_mode,
                attached_at=now,
                last_seen_at=now,
                pricing=dict(pricing),
                rating=dict(rating),
                session_policy=dict(session_policy or {}),
            )
            self.store.replace_records([*records, attached])
            return attached

        attached = existing.model_copy(
            update={
                "source_owner_wallet": source_owner_wallet,
                "source_publication_id": source_publication_id,
                "source_configuration_hash": source_configuration_hash,
                "source_visibility": source_visibility,
                "source_model_class": source_model_class,
                "source_status": source_status,
                "source_base_url": source_base_url,
                "operator_id": operator_id,
                "source_owner_public_key": source_owner_public_key,
                "source_wallet_signature": source_wallet_signature,
                "publication_verification": publication_verification,
                "alias": alias if alias is not None else existing.alias,
                "routing_mode": routing_mode,
                "last_seen_at": now,
                "pricing": dict(pricing),
                "rating": dict(rating),
                "session_policy": dict(session_policy or existing.session_policy),
            }
        )
        self.store.replace_records(
            [
                attached if item.remote_endpoint_id == existing.remote_endpoint_id else item
                for item in records
            ]
        )
        return attached
