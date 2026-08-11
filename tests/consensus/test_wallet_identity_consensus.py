from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.wallet_identity import wallet_identity_registration_payload


def _identity_envelope(*, sequence: int = 1) -> LedgerOperationEnvelope:
    private_key = Ed25519PrivateKey.generate()
    public_key = "ed25519:" + private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()
    wallet_id = "wallet-" + hashlib.sha256(public_key.encode("utf-8")).hexdigest()[:12]
    created_at = datetime.now(UTC).isoformat()
    nonce = "identity-registration-nonce"
    registration_signature = "ed25519:" + private_key.sign(
        wallet_identity_registration_payload(
            wallet_id=wallet_id,
            public_key=public_key,
            registration_nonce=nonce,
        )
    ).hex()
    unsigned = LedgerOperationEnvelope(
        operation_type="WALLET_IDENTITY_REGISTER",
        origin_type="wallet",
        initiator_id=wallet_id,
        sender_wallet=wallet_id,
        sender_sequence=sequence,
        fee_payer=wallet_id,
        fee_class="onboarding_exempt",
        created_at=created_at,
        payload={
            "wallet_id": wallet_id,
            "public_key": public_key,
            "registration_nonce": nonce,
            "registration_signature": registration_signature,
            "registered_at": created_at,
        },
        evidence_references=[wallet_id],
    )
    return unsigned.model_copy(
        update={"signatures": ["ed25519:" + private_key.sign(unsigned.signing_bytes()).hex()]}
    )


def test_wallet_identity_registration_is_canonical_and_queryable() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(ledger_service=ledger, strict_operation_coverage=True)
    envelope = _identity_envelope()

    result = app._execute_one(
        envelope.model_dump_json().encode("utf-8"),
        finalized_operation_ids=set(),
    )

    assert result.code == "ok"
    identity = ledger.canonical_wallet_identity(str(envelope.sender_wallet))
    assert identity is not None
    assert identity["public_key"] == envelope.payload["public_key"]
    assert ledger.wallet_next_sequence(str(envelope.sender_wallet)) == 2

    response = app.query(path=f"wallet/identity/{envelope.sender_wallet}")
    assert json.loads(response.value.decode("utf-8"))["operation_id"] == envelope.operation_id


def test_wallet_identity_query_returns_empty_only_for_an_absent_identity() -> None:
    app = AIDNABCIApplication(
        ledger_service=LedgerOperationService(), strict_operation_coverage=True
    )

    response = app.query(path="wallet/identity/wallet-missing")

    assert response.value == b""
