from __future__ import annotations

import hashlib
import json

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.endpoint_publications.models import (
    PublishedEndpointConfiguration,
    canonical_configuration_payload,
    configuration_hash_for_publication,
)
from aidn_hypervisor.endpoint_publications.signing import (
    public_key_for_private_key,
    sign_consensus_bytes,
    sign_publication_payload,
)
from aidn_hypervisor.ledger.service import LedgerOperationService

PRIVATE_KEY = "ed25519:" + "11" * 32


def _publication() -> PublishedEndpointConfiguration:
    public_key = public_key_for_private_key(PRIVATE_KEY)
    wallet_id = "wallet-" + hashlib.sha256(public_key.encode("utf-8")).hexdigest()[:12]
    publication_payload = canonical_configuration_payload(
        bundle_hash="bundle-hash",
        model_class="speech_to_text",
        capabilities=["speech_to_text"],
        runtime={"runtime_binding_id": "binding-1", "adapter": "whisper-http"},
        publication={
            "visibility": "public",
            "discoverable": True,
            "accepts_external_requests": True,
        },
        pricing={"fixed_price": 1.0, "billing_unit": "request"},
        session={"minimum_deposit": 1.0},
        execution={"strategy": "local", "runtime_binding_id": "binding-1"},
    )
    record = PublishedEndpointConfiguration(
        publication_id="pub-consensus-1",
        endpoint_id="endpoint-whisper",
        owner_wallet=wallet_id,
        owner_public_key=public_key,
        node_id="node-127",
        configuration_hash=configuration_hash_for_publication(publication_payload),
        bundle_id="bundle-1",
        bundle_hash="bundle-hash",
        model_class="speech_to_text",
        capabilities=["speech_to_text"],
        profile={"name": "whisper"},
        runtime={"runtime_binding_id": "binding-1", "adapter": "whisper-http"},
        publication=publication_payload["publication"],
        pricing=publication_payload["pricing"],
        session=publication_payload["session"],
        execution=publication_payload["execution"],
        validation_requirement={"enabled": False},
        published_at="2030-01-01T00:00:00Z",
        sequence=1,
        wallet_signature="",
    )
    return record.model_copy(
        update={
            "wallet_signature": sign_publication_payload(
                private_key=PRIVATE_KEY,
                payload=record.signed_payload(),
            )
        }
    )


def _tx(record: PublishedEndpointConfiguration) -> bytes:
    unsigned = LedgerOperationEnvelope(
        operation_type="ENDPOINT_PUBLISH",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="wallet",
        initiator_id=record.endpoint_id,
        sender_wallet=record.owner_wallet,
        sender_sequence=1,
        fee_payer=record.owner_wallet,
        fee_class="standard",
        created_at=record.published_at,
        payload={"publication": record.model_dump(mode="json")},
        evidence_references=[
            record.publication_id,
            record.endpoint_id,
            record.configuration_hash,
        ],
    )
    envelope = unsigned.model_copy(
        update={
            "signatures": [
                sign_consensus_bytes(
                    private_key=PRIVATE_KEY,
                    payload=unsigned.signing_bytes(),
                )
            ]
        }
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def test_abci_applies_signed_endpoint_publication_transition() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"P" * 32,
        txs=[_tx(_publication())],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "ok"
    assert ledger.snapshot_operations()[0]["operation_type"] == "ENDPOINT_PUBLISH"
    assert ledger.snapshot_operations()[0]["result"]["emitted_events"] == [
        "EndpointPublished"
    ]


def test_execution_engine_supports_endpoint_publication_transition() -> None:
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=b"E" * 32,
        txs=[_tx(_publication())],
    )

    assert result.error is None
    assert result.operations_executed == 1
    assert result.execution_events[0].emitted_events == ["EndpointPublished"]


def test_validator_migration_removes_legacy_local_endpoint_updates() -> None:
    ledger = LedgerOperationService()
    ledger.record_operation(
        operation_type="ENDPOINT_UPDATE",
        origin_type="wallet",
        fee_class="standard",
        initiator_id="wallet-legacy",
        sender_wallet="wallet-legacy",
        fee_payer="wallet-legacy",
        payload={"endpoint_id": "endpoint-whisper"},
    )

    removed = ledger.remove_noncanonical_operations({"ENDPOINT_UPDATE"})

    assert len(removed) == 1
    assert ledger.snapshot_operations() == []
    assert ledger.wallet_next_sequence("wallet-legacy") == 1

