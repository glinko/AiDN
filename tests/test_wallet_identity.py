import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.wallet_identity import (
    verify_wallet_identity_registration,
    wallet_identity_registration_payload,
)


def test_wallet_identity_registration_requires_key_possession() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = f"ed25519:{private_key.public_key().public_bytes_raw().hex()}"
    signature = private_key.sign(
        wallet_identity_registration_payload(
            wallet_id="wallet-consumer", public_key=public_key, registration_nonce="nonce-1"
        )
    ).hex()

    identity = verify_wallet_identity_registration(
        wallet_id="wallet-consumer",
        public_key=public_key,
        registration_nonce="nonce-1",
        signature=f"ed25519:{signature}",
    )

    assert identity.wallet_id == "wallet-consumer"
    with pytest.raises(ValueError, match="invalid"):
        verify_wallet_identity_registration(
            wallet_id="wallet-other",
            public_key=public_key,
            registration_nonce="nonce-1",
            signature=f"ed25519:{signature}",
        )


def test_wallet_identity_is_immutable_and_survives_snapshot_restore() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = f"ed25519:{private_key.public_key().public_bytes_raw().hex()}"
    nonce = "nonce-restore"
    signature = private_key.sign(
        wallet_identity_registration_payload(
            wallet_id="wallet-consumer", public_key=public_key, registration_nonce=nonce
        )
    ).hex()
    service = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    service.register_wallet_identity(
        wallet_id="wallet-consumer",
        public_key=public_key,
        registration_nonce=nonce,
        signature=f"ed25519:{signature}",
    )
    restored = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    restored.restore_state(service.snapshot_state())

    assert restored.wallet_identity("wallet-consumer")["public_key"] == public_key
    replacement_key = Ed25519PrivateKey.generate()
    replacement_public_key = (
        f"ed25519:{replacement_key.public_key().public_bytes_raw().hex()}"
    )
    replacement_signature = replacement_key.sign(
        wallet_identity_registration_payload(
            wallet_id="wallet-consumer",
            public_key=replacement_public_key,
            registration_nonce=nonce,
        )
    ).hex()
    with pytest.raises(ValueError, match="key rotation"):
        restored.register_wallet_identity(
            wallet_id="wallet-consumer",
            public_key=replacement_public_key,
            registration_nonce=nonce,
            signature=f"ed25519:{replacement_signature}",
        )
