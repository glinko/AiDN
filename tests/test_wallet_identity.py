import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.endpoints.models import CreateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore
from aidn_hypervisor.wallet_identity import (
    session_open_authorization_payload,
    verify_wallet_identity_registration,
    wallet_identity_registration_payload,
)


def _registered_identity(service: HypervisorService, wallet_id: str = "wallet-consumer"):
    private_key = Ed25519PrivateKey.generate()
    public_key = f"ed25519:{private_key.public_key().public_bytes_raw().hex()}"
    nonce = "registration-nonce"
    signature = private_key.sign(wallet_identity_registration_payload(
        wallet_id=wallet_id, public_key=public_key, registration_nonce=nonce
    )).hex()
    service.register_wallet_identity(wallet_id=wallet_id, public_key=public_key, registration_nonce=nonce, signature=f"ed25519:{signature}")
    return private_key, public_key


def test_wallet_identity_registration_requires_key_possession() -> None:
    service = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    _, public_key = _registered_identity(service)
    assert service.wallet_identity("wallet-consumer")["public_key"] == public_key


def test_wallet_identity_is_immutable_and_survives_snapshot_restore() -> None:
    service = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    _, public_key = _registered_identity(service)
    restored = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    restored.restore_state(service.snapshot_state())
    assert restored.wallet_identity("wallet-consumer")["public_key"] == public_key


def test_signed_session_open_locks_escrow_once_per_authorization_nonce() -> None:
    hypervisor = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    private_key, public_key = _registered_identity(hypervisor)
    endpoint = EndpointService(EndpointStore()).create_endpoint(CreateEndpointCommand(
        owner_wallet="wallet-operator", bundle_id="bundle-1", bundle_hash="bundle-hash",
        display_name="Paid endpoint", model_class="llm.chat"
    )).endpoint
    hypervisor.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=1_000)
    nonce = "session-nonce"
    expires_at = "2030-01-01T00:00:00+00:00"
    signature = private_key.sign(session_open_authorization_payload(
        wallet_id="wallet-consumer", endpoint_id=endpoint.endpoint_id,
        endpoint_configuration_hash=endpoint.configuration_hash, deposit_q_atoms=1_000,
        fixed_price_q_atoms=900, network_fee_reserve_q_atoms=100, nonce=nonce,
        expires_at=expires_at
    )).hex()
    kwargs = {
        "session_service": SessionService(SessionStore()), "endpoint": endpoint,
        "client_wallet": "wallet-consumer", "deposit_q_atoms": 1_000,
        "fixed_price_q_atoms": 900, "network_fee_reserve_q_atoms": 100,
        "consumer_authorization": {"nonce": nonce, "expires_at": expires_at, "signature": f"ed25519:{signature}"},
    }
    session, _, _ = hypervisor.open_mvp_fixed_price_session(**kwargs)
    assert session.consumer_authorization_public_key == public_key
    hypervisor.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=1_000)
    with pytest.raises(ValueError, match="nonce"):
        hypervisor.open_mvp_fixed_price_session(**kwargs)
