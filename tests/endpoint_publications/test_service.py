import pytest

from aidn_hypervisor.endpoint_publications.models import (
    PublishedEndpointConfiguration,
    canonical_configuration_payload,
    configuration_hash_for_publication,
)
from aidn_hypervisor.endpoint_publications.service import (
    EndpointPublicationReadinessError,
    EndpointPublicationService,
)
from aidn_hypervisor.endpoint_publications.signing import (
    public_key_for_private_key,
    verify_publication_signature,
)
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
            pricing={"rate_card": {
                "components": [{
                    "component_id": "input",
                    "dimension": "input_tokens",
                    "unit_price_q_atoms": 1_000_000,
                    "unit_divisor": 1_000_000,
                    "accounting_mode": "provider_metered",
                }],
            }},
            session={"minimum_deposit": 10.0},
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
            session=endpoint.session.model_dump(mode="json"),
            execution={
                "strategy": endpoint.execution_strategy,
                "runtime_binding_id": endpoint.runtime_binding_id,
            },
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
        session=endpoint.session.model_dump(mode="json"),
        execution={
            "strategy": endpoint.execution_strategy,
            "runtime_binding_id": endpoint.runtime_binding_id,
        },
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
            session=created.endpoint.session.model_dump(mode="json"),
            execution={
                "strategy": created.endpoint.execution_strategy,
                "runtime_binding_id": created.endpoint.runtime_binding_id,
            },
        )
    )

    assert record.endpoint_id == created.endpoint.endpoint_id
    assert record.owner_wallet == "wallet-1"
    assert record.node_id == "node-1"
    assert record.sequence == 1
    assert record.previous_configuration_hash is None
    assert record.configuration_hash == expected_hash
    assert record.session == created.endpoint.session.model_dump(mode="json")
    assert record.status == "published"
    assert record.wallet_signature


def test_reconcile_canonical_publication_restores_missing_read_model() -> None:
    endpoint_service = EndpointService(EndpointStore())
    created = _create_endpoint(endpoint_service)
    service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    record = _published_record_for_endpoint(
        endpoint=created.endpoint,
        publication_id="pub-canonical",
    )

    reconciled = service.reconcile_canonical_publications(
        [
            {
                "operation_type": "ENDPOINT_PUBLISH",
                "payload": {"publication": record.model_dump(mode="json")},
                "result": {"status": "applied"},
            }
        ]
    )

    assert reconciled == ["pub-canonical"]
    assert service.current_publication(created.endpoint.endpoint_id) == record


def test_publish_configuration_uses_verifiable_owner_wallet_signature() -> None:
    endpoint_service = EndpointService(EndpointStore())
    created = _create_endpoint(endpoint_service)
    service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    private_key = "ed25519:" + "11" * 32
    public_key = public_key_for_private_key(private_key)

    record = service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="wallet-1",
        owner_public_key=public_key,
        node_id="node-1",
        wallet_private_key=private_key,
    )

    assert record.owner_public_key == public_key
    assert record.wallet_signature.startswith("ed25519:")
    verify_publication_signature(
        public_key=public_key,
        signature=record.wallet_signature,
        payload=record.signed_payload(),
    )


def test_publication_readiness_rejects_signer_not_owned_by_wallet() -> None:
    endpoint_service = EndpointService(EndpointStore())
    created = _create_endpoint(endpoint_service)
    service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )

    readiness = service.publication_readiness(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="wallet-1",
        owner_public_key=public_key_for_private_key("ed25519:" + "22" * 32),
        node_id="node-1",
        wallet_private_key="ed25519:" + "11" * 32,
    )

    assert readiness["ready"] is False
    assert readiness["blockers"][0]["code"] == "ENDPOINT_PUBLICATION_SIGNER_MISMATCH"


def test_publication_readiness_blocks_conflicting_external_policy() -> None:
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Conflicting Endpoint",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "private",
                "accepts_external_requests": True,
            },
        )
    )
    service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )

    readiness = service.publication_readiness(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="wallet-1",
        node_id="node-1",
        wallet_private_key="sk-1",
    )

    assert readiness["ready"] is False
    assert readiness["blockers"][0]["code"] == "ENDPOINT_PUBLICATION_POLICY_CONFLICT"
    with pytest.raises(EndpointPublicationReadinessError):
        service.publish_configuration(
            endpoint_id=created.endpoint.endpoint_id,
            owner_wallet="wallet-1",
            node_id="node-1",
            wallet_private_key="sk-1",
        )


def test_publication_readiness_warns_for_unpriced_external_endpoint() -> None:
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Free Until Priced",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "public",
                "discoverable": True,
                "accepts_external_requests": True,
            },
        )
    )
    service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )

    readiness = service.publication_readiness(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="wallet-1",
        node_id="node-1",
        wallet_private_key="sk-1",
    )

    assert readiness["ready"] is True
    assert readiness["warnings"][0]["code"] == "ENDPOINT_PRICING_NOT_CONFIGURED"


def test_publication_readiness_requires_minimum_escrow_for_paid_endpoint() -> None:
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid Endpoint without escrow policy",
            model_class="llm.chat",
            capabilities=["llm.chat"],
            publication={
                "visibility": "public",
                "discoverable": True,
                "accepts_external_requests": True,
            },
            pricing={
                "rate_card": {
                    "components": [
                        {
                            "component_id": "output",
                            "dimension": "output_tokens",
                            "unit_price_q_atoms": 2,
                        }
                    ]
                }
            },
        )
    )
    service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )

    readiness = service.publication_readiness(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="wallet-1",
        node_id="node-1",
        wallet_private_key="sk-1",
    )

    assert readiness["ready"] is False
    assert any(
        item["code"] == "ENDPOINT_MINIMUM_ESCROW_DEPOSIT_REQUIRED"
        for item in readiness["blockers"]
    )


def test_publication_readiness_exposes_deposit_recommendation_and_missing_working_balance() -> None:
    endpoint_service = EndpointService(EndpointStore())
    created = _create_endpoint(endpoint_service)
    service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )

    readiness = service.publication_readiness(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="wallet-1",
        node_id="node-1",
        wallet_private_key="sk-1",
    )

    recommendation = readiness["dimensions"]["session"]["deposit_recommendation"]
    assert recommendation["automatic"] is True
    assert recommendation["usage_assumptions"]["input_tokens"] == 8192
    assert recommendation["recommended_multiplier"] == 5
    assert any(
        item["code"] == "ENDPOINT_RECOMMENDED_ESCROW_DEPOSIT_NOT_CONFIGURED"
        for item in readiness["warnings"]
    )


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


def test_publication_service_records_canonical_advertisement_operations() -> None:
    endpoint_service = EndpointService(EndpointStore())
    created = _create_endpoint(endpoint_service)
    recorded_operations: list[dict] = []
    service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    service.operation_recorder = lambda **payload: recorded_operations.append(payload)

    published = service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="wallet-1",
        node_id="node-1",
        wallet_private_key="sk-1",
    )
    revoked = service.revoke_publication(created.endpoint.endpoint_id)

    assert published.publication_id == revoked.publication_id
    assert recorded_operations[0]["operation_type"] == "ENDPOINT_ADVERTISEMENT_PUBLISH"
    assert recorded_operations[0]["sender_wallet"] == "wallet-1"
    assert recorded_operations[0]["payload"]["resource_id"] == created.endpoint.endpoint_id
    assert recorded_operations[0]["payload"]["advertisement_id"] == published.publication_id
    assert recorded_operations[1]["operation_type"] == "ENDPOINT_OFFER_PUBLISH"
    assert recorded_operations[1]["sender_wallet"] == "wallet-1"
    assert recorded_operations[1]["payload"]["offer_id"] == f"offer-{published.publication_id}"
    assert recorded_operations[1]["payload"]["advertisement_id"] == published.publication_id
    assert recorded_operations[1]["payload"]["endpoint_id"] == created.endpoint.endpoint_id
    assert recorded_operations[2]["operation_type"] == "ENDPOINT_ADVERTISEMENT_WITHDRAW"
    assert recorded_operations[2]["sender_wallet"] == "wallet-1"
    assert recorded_operations[2]["payload"]["advertisement_id"] == published.publication_id
