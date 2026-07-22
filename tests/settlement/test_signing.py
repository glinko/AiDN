import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.settlement.models import SessionSettlementAcceptance
from aidn_hypervisor.settlement.signing import (
    settlement_acceptance_signing_payload,
    verify_settlement_acceptance,
)


def _acceptance(signature: str = "ed25519:" + "00" * 64) -> SessionSettlementAcceptance:
    return SessionSettlementAcceptance(
        settlement_id="settlement-1",
        session_id="session-1",
        settlement_input_root="input-root",
        accepted_endpoint_payment_q_atoms=900,
        accepted_consumer_refund_q_atoms=100,
        accepted_network_fees_q_atoms=0,
        consumer_signature=signature,
        accepted_at="2026-07-21T00:00:00+00:00",
    )


def test_ed25519_consumer_acceptance_is_bound_to_settlement_amounts() -> None:
    private_key = Ed25519PrivateKey.generate()
    unsigned = _acceptance()
    signature = private_key.sign(settlement_acceptance_signing_payload(unsigned)).hex()
    acceptance = _acceptance(f"ed25519:{signature}")
    public_key = f"ed25519:{private_key.public_key().public_bytes_raw().hex()}"

    verify_settlement_acceptance(acceptance, consumer_public_key=public_key)

    with pytest.raises(ValueError, match="invalid"):
        verify_settlement_acceptance(
            acceptance.model_copy(update={"accepted_endpoint_payment_q_atoms": 901}),
            consumer_public_key=public_key,
        )
