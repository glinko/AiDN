from datetime import datetime, timezone
from uuid import uuid4

from aidn_hypervisor.remote_endpoints.models import (
    RemoteEndpointReference,
    RemoteEndpointRoutingMode,
)


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
        pricing: dict[str, str | int | float | None],
        rating: dict[str, str | int | float | None],
        session_policy: dict | None = None,
        alias: str | None = None,
        routing_mode: RemoteEndpointRoutingMode = "preferred",
    ) -> RemoteEndpointReference:
        records = self.store.list_records()
        now = datetime.now(timezone.utc).isoformat()
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
