from aidn_hypervisor.endpoint_publications.models import (
    PublishedEndpointConfiguration,
    canonical_configuration_payload,
    configuration_hash_for_publication,
)
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.models import CreateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore


def _create_endpoint(endpoint_service: EndpointService):
    return endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            runtime={"context_length": 8192, "timeout": 45, "streaming": True},
            publication={
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a"],
                "discoverable": True,
                "validation": "disabled",
                "accepts_external_requests": True,
            },
            pricing={"billing_unit": "request", "input_price": 1.0},
            validation={
                "enabled": False,
                "model_class_supported": True,
                "verification_status": "active",
            },
        )
    )


def _published_record_for_endpoint(
    *,
    endpoint,
    publication_id: str,
    owner_wallet: str = "wallet-1",
    node_id: str = "node-1",
    sequence: int = 1,
) -> PublishedEndpointConfiguration:
    configuration_hash = configuration_hash_for_publication(
        canonical_configuration_payload(
            bundle_hash=endpoint.bundle_hash,
            model_class=endpoint.model_class,
            capabilities=endpoint.capabilities,
            runtime=endpoint.runtime.model_dump(mode="json"),
            publication=endpoint.publication.model_dump(mode="json"),
            pricing=endpoint.pricing.model_dump(mode="json"),
            execution={"strategy": endpoint.execution_strategy},
        )
    )
    return PublishedEndpointConfiguration(
        publication_id=publication_id,
        endpoint_id=endpoint.endpoint_id,
        owner_wallet=owner_wallet,
        node_id=node_id,
        configuration_hash=configuration_hash,
        previous_configuration_hash=None,
        bundle_id=endpoint.bundle_id,
        bundle_hash=endpoint.bundle_hash,
        model_class=endpoint.model_class,
        capabilities=list(endpoint.capabilities),
        profile=endpoint.profile.model_dump(mode="json"),
        runtime=endpoint.runtime.model_dump(mode="json"),
        publication=endpoint.publication.model_dump(mode="json"),
        pricing=endpoint.pricing.model_dump(mode="json"),
        execution={"strategy": endpoint.execution_strategy},
        validation_requirement=endpoint.validation.model_dump(mode="json"),
        published_at="2026-06-30T00:00:00+00:00",
        sequence=sequence,
        status="published",
        wallet_signature=f"sig-{publication_id}",
    )


def test_publish_configuration_creates_signed_current_record() -> None:
    endpoint_service = EndpointService(EndpointStore())
    created = _create_endpoint(endpoint_service)
    service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )

    record = service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="wallet-1",
        node_id="node-1",
        wallet_private_key="sk-1",
    )
    expected_hash = configuration_hash_for_publication(
        canonical_configuration_payload(
            bundle_hash=created.endpoint.bundle_hash,
            model_class=created.endpoint.model_class,
            capabilities=created.endpoint.capabilities,
            runtime=created.endpoint.runtime.model_dump(mode="json"),
            publication=created.endpoint.publication.model_dump(mode="json"),
            pricing=created.endpoint.pricing.model_dump(mode="json"),
            execution={"strategy": created.endpoint.execution_strategy},
        )
    )

    assert record.endpoint_id == created.endpoint.endpoint_id
    assert record.owner_wallet == "wallet-1"
    assert record.node_id == "node-1"
    assert record.sequence == 1
    assert record.previous_configuration_hash is None
    assert record.configuration_hash == expected_hash
    assert record.status == "published"
    assert record.wallet_signature


def test_publish_configuration_supersedes_prior_publication() -> None:
    endpoint_service = EndpointService(EndpointStore())
    created = _create_endpoint(endpoint_service)
    store = EndpointPublicationStore()
    service = EndpointPublicationService(
        store=store,
        endpoint_service=endpoint_service,
    )

    first = service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="wallet-1",
        node_id="node-1",
        wallet_private_key="sk-1",
    )
    second = service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="wallet-1",
        node_id="node-1",
        wallet_private_key="sk-2",
    )

    records = store.list_records()

    assert len(records) == 2
    assert records[0].status == "superseded"
    assert records[0].publication_id == first.publication_id
    assert second.status == "published"
    assert second.sequence == 2
    assert second.previous_configuration_hash == first.configuration_hash
    assert records[1] == second


def test_publish_configuration_supersedes_using_public_store_api() -> None:
    class ReplaceAwareStore:
        def __init__(self, records: list[PublishedEndpointConfiguration]) -> None:
            self._records = [record.model_copy(deep=True) for record in records]
            self.appended: list[PublishedEndpointConfiguration] = []
            self.replaced: list[PublishedEndpointConfiguration] | None = None

        def list_records(self) -> list[PublishedEndpointConfiguration]:
            return [record.model_copy(deep=True) for record in self._records]

        def append(self, record: PublishedEndpointConfiguration) -> None:
            self.appended.append(record.model_copy(deep=True))

        def replace_records(
            self, records: list[PublishedEndpointConfiguration]
        ) -> None:
            self.replaced = [record.model_copy(deep=True) for record in records]

    endpoint_service = EndpointService(EndpointStore())
    created = _create_endpoint(endpoint_service)
    first = _published_record_for_endpoint(
        endpoint=created.endpoint,
        publication_id="pub-1",
    )
    store = ReplaceAwareStore([first])
    service = EndpointPublicationService(
        store=store,
        endpoint_service=endpoint_service,
    )

    second = service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="wallet-1",
        node_id="node-1",
        wallet_private_key="sk-2",
    )

    assert store.appended == []
    assert store.replaced is not None
    assert len(store.replaced) == 2
    assert store.replaced[0].publication_id == first.publication_id
    assert store.replaced[0].status == "superseded"
    assert store.replaced[1] == second
    assert second.sequence == 2
    assert second.previous_configuration_hash == first.configuration_hash


def test_revoke_publication_marks_current_record_revoked() -> None:
    endpoint_service = EndpointService(EndpointStore())
    created = _create_endpoint(endpoint_service)
    store = EndpointPublicationStore()
    service = EndpointPublicationService(
        store=store,
        endpoint_service=endpoint_service,
    )
    published = service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="wallet-1",
        node_id="node-1",
        wallet_private_key="sk-1",
    )

    revoked = service.revoke_publication(created.endpoint.endpoint_id)

    assert revoked.publication_id == published.publication_id
    assert revoked.status == "revoked"
    assert service.current_publication(created.endpoint.endpoint_id) is None
    assert store.list_records()[0].status == "revoked"
