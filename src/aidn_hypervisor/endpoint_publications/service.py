from datetime import datetime, timezone
from uuid import uuid4

from aidn_hypervisor.endpoint_publications.models import (
    PublishedEndpointConfiguration,
    canonical_configuration_payload,
    configuration_hash_for_publication,
)


class EndpointPublicationService:
    def __init__(self, *, store, endpoint_service) -> None:
        self.store = store
        self.endpoint_service = endpoint_service

    def publish_configuration(
        self,
        *,
        endpoint_id: str,
        owner_wallet: str,
        node_id: str,
        wallet_private_key: str,
    ) -> PublishedEndpointConfiguration:
        manifest = self.endpoint_service.get_endpoint(endpoint_id).endpoint
        records = self.store.list_records()
        previous = self._current_publication_from_records(records, endpoint_id)
        execution_payload = self._execution_payload(manifest)
        payload = canonical_configuration_payload(
            bundle_hash=manifest.bundle_hash,
            model_class=manifest.model_class,
            capabilities=manifest.capabilities,
            runtime=manifest.runtime.model_dump(mode="json"),
            publication=manifest.publication.model_dump(mode="json"),
            pricing=manifest.pricing.model_dump(mode="json"),
            execution=execution_payload,
        )
        configuration_hash = configuration_hash_for_publication(payload)
        sequence = 1 if previous is None else previous.sequence + 1
        if previous is not None:
            previous.status = "superseded"
        record = PublishedEndpointConfiguration(
            publication_id=f"pub-{uuid4().hex[:12]}",
            endpoint_id=endpoint_id,
            owner_wallet=owner_wallet,
            node_id=node_id,
            configuration_hash=configuration_hash,
            previous_configuration_hash=(
                previous.configuration_hash if previous is not None else None
            ),
            bundle_id=manifest.bundle_id,
            bundle_hash=manifest.bundle_hash,
            model_class=manifest.model_class,
            capabilities=list(manifest.capabilities),
            profile=manifest.profile.model_dump(mode="json"),
            runtime=manifest.runtime.model_dump(mode="json"),
            publication=manifest.publication.model_dump(mode="json"),
            pricing=manifest.pricing.model_dump(mode="json"),
            execution=execution_payload,
            validation_requirement=manifest.validation.model_dump(mode="json"),
            published_at=datetime.now(timezone.utc).isoformat(),
            sequence=sequence,
            status="published",
            wallet_signature=f"sig-{configuration_hash[:16]}-{wallet_private_key[:8]}",
        )
        if previous is None:
            self.store.append(record)
            return record

        updated_records = [
            existing.model_copy(update={"status": "superseded"})
            if existing.publication_id == previous.publication_id
            else existing
            for existing in records
        ]
        updated_records.append(record)
        self.store.replace_records(updated_records)
        return record

    def current_publication(
        self, endpoint_id: str
    ) -> PublishedEndpointConfiguration | None:
        return self._current_publication_from_records(
            self.store.list_records(),
            endpoint_id,
        )

    def list_publications(
        self,
        *,
        endpoint_id: str | None = None,
    ) -> list[PublishedEndpointConfiguration]:
        records = self.store.list_records()
        if endpoint_id is None:
            return records
        return [record for record in records if record.endpoint_id == endpoint_id]

    def revoke_publication(
        self,
        endpoint_id: str,
    ) -> PublishedEndpointConfiguration:
        records = self.store.list_records()
        current = self._current_publication_from_records(records, endpoint_id)
        if current is None:
            raise ValueError(
                f"No active published configuration for endpoint: {endpoint_id}"
            )
        updated_records = [
            existing.model_copy(update={"status": "revoked"})
            if existing.publication_id == current.publication_id
            else existing
            for existing in records
        ]
        self.store.replace_records(updated_records)
        return current.model_copy(update={"status": "revoked"})

    def _current_publication_from_records(
        self,
        records: list[PublishedEndpointConfiguration],
        endpoint_id: str,
    ) -> PublishedEndpointConfiguration | None:
        for record in reversed(records):
            if record.endpoint_id == endpoint_id and record.status == "published":
                return record
        return None

    def _execution_payload(self, manifest) -> dict:
        if manifest.execution_strategy != "proxy" or manifest.proxy_target is None:
            return {"strategy": manifest.execution_strategy}
        fingerprint = configuration_hash_for_publication(
            {
                "remote_endpoint_id": manifest.proxy_target.remote_endpoint_id,
                "source_publication_id": manifest.proxy_target.source_publication_id,
                "source_configuration_hash": manifest.proxy_target.source_configuration_hash,
            }
        )
        return {
            "strategy": manifest.execution_strategy,
            "target_fingerprint": fingerprint,
        }
