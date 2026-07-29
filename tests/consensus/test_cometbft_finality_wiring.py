import base64
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.cometbft_crypto import Zip215CometBftEd25519Backend
from aidn_hypervisor.consensus.cometbft_finality import (
    CometBftFinalityConfig,
    build_cometbft_finality_source,
)
from aidn_hypervisor.consensus.light_client import (
    CometBftValidator,
    CometBftValidatorSet,
    TrustedCometBftCheckpoint,
)
from aidn_hypervisor.ledger.service import LedgerOperationService


class NoCallTransport:
    def get(self, path: str, *, params: dict[str, str], timeout_seconds: int) -> dict:
        raise AssertionError(f"unexpected RPC request: {path} {params} {timeout_seconds}")


def _trusted_checkpoint(chain_id: str = "aidn-testnet-1") -> TrustedCometBftCheckpoint:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    validator_set = CometBftValidatorSet(
        (
            CometBftValidator(
                address=hashlib.sha256(public_key).digest()[:20].hex().upper(),
                public_key=f"ed25519:{base64.b64encode(public_key).decode('ascii')}",
                voting_power=1,
            ),
        )
    )
    backend = Zip215CometBftEd25519Backend()
    validator_hash = backend.validator_set_hash(validator_set)
    return TrustedCometBftCheckpoint(
        chain_id=chain_id,
        height=10,
        block_id="A" * 64,
        app_hash="B" * 64,
        header_time="2030-01-01T00:00:00Z",
        validator_set=validator_set,
        validator_set_hash=validator_hash,
        next_validator_set_hash=validator_hash,
    )


def test_finality_wiring_requires_an_operator_trusted_checkpoint_for_the_chain():
    checkpoint = _trusted_checkpoint(chain_id="other-chain")

    with pytest.raises(ValueError, match="chain_id"):
        CometBftFinalityConfig(
            rpc_endpoint="https://consensus.example",
            chain_id="aidn-testnet-1",
            verifier_id="operator-checkpoint-1",
            trusted_checkpoint=checkpoint,
            trust_period_seconds=3600,
        )


def test_finality_wiring_composes_strict_rpc_verification_with_local_abci_commitment():
    config = CometBftFinalityConfig(
        rpc_endpoint="https://consensus.example",
        chain_id="aidn-testnet-1",
        verifier_id="operator-checkpoint-1",
        trusted_checkpoint=_trusted_checkpoint(),
        trust_period_seconds=3600,
    )
    source = build_cometbft_finality_source(
        config=config,
        transaction_hash_for_operation=lambda operation_id: None,
        abci_application=AIDNABCIApplication(ledger_service=LedgerOperationService()),
        transport=NoCallTransport(),
    )

    assert source.finality_evidence("unknown-operation") is None
    assert isinstance(source._source._proof_verifier._light_client._cryptography, Zip215CometBftEd25519Backend)
