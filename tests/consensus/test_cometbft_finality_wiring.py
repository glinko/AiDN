import base64
import hashlib
import json
from urllib import error as urllib_error

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.abci_finality import ABCICommittedFinalitySource
from aidn_hypervisor.consensus.cometbft import (
    CometBftRpcFinalitySource,
    HttpCometBftWalletBalanceProvider,
    HttpCometBftWalletIdentityProvider,
)
from aidn_hypervisor.consensus.cometbft_crypto import Zip215CometBftEd25519Backend
from aidn_hypervisor.consensus.cometbft_finality import (
    CometBftFinalityConfig,
    CometBftMultiRpcFinalityConfig,
    build_cometbft_finality_source,
    build_cometbft_multi_rpc_finality_source,
)
from aidn_hypervisor.consensus.finality import QuorumConsensusFinalitySource
from aidn_hypervisor.consensus.light_client import (
    CometBftValidator,
    CometBftValidatorSet,
    TrustedCometBftCheckpoint,
)
from aidn_hypervisor.ledger.service import LedgerOperationService


class NoCallTransport:
    def get(self, path: str, *, params: dict[str, str], timeout_seconds: int) -> dict:
        raise AssertionError(f"unexpected RPC request: {path} {params} {timeout_seconds}")


def test_wallet_balance_provider_requires_a_matching_rpc_quorum():
    class BalanceTransport:
        def __init__(self, balance: int) -> None:
            self.balance = balance

        def get(self, path: str, *, params: dict[str, str], timeout_seconds: int) -> dict:
            assert path == "/abci_query"
            assert params["path"] == '"wallet/balance/wallet-owner"'
            assert params["prove"] == "false"
            assert timeout_seconds == 2
            return {
                "result": {
                    "response": {
                        "code": 0,
                        "value": base64.b64encode(str(self.balance).encode("ascii")).decode("ascii"),
                    }
                }
            }

    provider = HttpCometBftWalletBalanceProvider(
        [BalanceTransport(50_000_000), BalanceTransport(50_000_000), BalanceTransport(900)],
        quorum=2,
        timeout_seconds=2,
    )

    assert provider("wallet-owner") == 50_000_000


def test_wallet_balance_provider_fails_closed_without_quorum():
    class BalanceTransport:
        def __init__(self, balance: int) -> None:
            self.balance = balance

        def get(self, path: str, *, params: dict[str, str], timeout_seconds: int) -> dict:
            del path, params, timeout_seconds
            return {
                "result": {
                    "response": {
                        "code": 0,
                        "value": base64.b64encode(str(self.balance).encode("ascii")).decode("ascii"),
                    }
                }
            }

    provider = HttpCometBftWalletBalanceProvider(
        [BalanceTransport(50_000_000), BalanceTransport(900)],
        quorum=2,
    )

    with pytest.raises(RuntimeError, match="disagree"):
        provider("wallet-owner")


def test_wallet_balance_provider_ignores_an_unavailable_rpc_when_quorum_remains():
    class UnavailableTransport:
        def get(self, path: str, *, params: dict[str, str], timeout_seconds: int) -> dict:
            del path, params, timeout_seconds
            raise urllib_error.URLError("connection refused")

    class BalanceTransport:
        def get(self, path: str, *, params: dict[str, str], timeout_seconds: int) -> dict:
            del path, params, timeout_seconds
            return {
                "result": {
                    "response": {
                        "code": 0,
                        "value": base64.b64encode(b"150000000").decode("ascii"),
                    }
                }
            }

    provider = HttpCometBftWalletBalanceProvider(
        [UnavailableTransport(), BalanceTransport(), BalanceTransport()],
        quorum=2,
    )

    assert provider("wallet-owner") == 150_000_000


def test_wallet_identity_provider_requires_a_matching_rpc_quorum():
    identity = {
        "wallet_id": "wallet-owner",
        "public_key": "ed25519:abcd",
        "registration_nonce": "nonce-1",
        "registered_at": "2030-01-01T00:00:00+00:00",
        "operation_id": "operation-1",
    }

    class IdentityTransport:
        def __init__(self, value: dict | None) -> None:
            self.value = value

        def get(self, path: str, *, params: dict[str, str], timeout_seconds: int) -> dict:
            assert path == "/abci_query"
            assert params["path"] == '"wallet/identity/wallet-owner"'
            assert params["prove"] == "false"
            assert timeout_seconds == 2
            value = b"" if self.value is None else json.dumps(self.value).encode("utf-8")
            return {
                "result": {
                    "response": {
                        "code": 0,
                        "value": base64.b64encode(value).decode("ascii"),
                    }
                }
            }

    provider = HttpCometBftWalletIdentityProvider(
        [IdentityTransport(identity), IdentityTransport(identity), IdentityTransport(None)],
        quorum=2,
        timeout_seconds=2,
    )

    assert provider("wallet-owner") == identity


def test_wallet_identity_provider_treats_quorum_empty_as_not_registered():
    class EmptyIdentityTransport:
        def get(self, path: str, *, params: dict[str, str], timeout_seconds: int) -> dict:
            del path, params, timeout_seconds
            return {"result": {"response": {"code": 0, "value": ""}}}

    provider = HttpCometBftWalletIdentityProvider(
        [EmptyIdentityTransport(), EmptyIdentityTransport()], quorum=2
    )

    assert provider("wallet-owner") is None


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


def test_finality_wiring_supports_non_validator_without_local_abci_commitment():
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
        transport=NoCallTransport(),
    )

    assert source.finality_evidence("unknown-operation") is None
    assert isinstance(source, CometBftRpcFinalitySource)
    assert not isinstance(source, ABCICommittedFinalitySource)


def test_multi_rpc_finality_wiring_requires_agreement_and_local_abci_commitment():
    config = CometBftMultiRpcFinalityConfig(
        rpc_endpoints=("https://consensus-a.example", "https://consensus-b.example"),
        minimum_agreement=2,
        chain_id="aidn-testnet-1",
        verifier_id="operator-checkpoint-quorum",
        trusted_checkpoint=_trusted_checkpoint(),
        trust_period_seconds=3600,
    )
    source = build_cometbft_multi_rpc_finality_source(
        config=config,
        transaction_hash_for_operation=lambda operation_id: None,
        abci_application=AIDNABCIApplication(ledger_service=LedgerOperationService()),
        transports=[NoCallTransport(), NoCallTransport()],
    )

    assert source.finality_evidence("unknown-operation") is None
    assert isinstance(source._source, QuorumConsensusFinalitySource)
    assert source._source.quorum == 2
    assert source._source.source_count == 2


def test_multi_rpc_finality_wiring_can_run_without_local_abci_for_non_validator():
    config = CometBftMultiRpcFinalityConfig(
        rpc_endpoints=("https://consensus-a.example", "https://consensus-b.example"),
        minimum_agreement=2,
        chain_id="aidn-testnet-1",
        verifier_id="operator-checkpoint-quorum",
        trusted_checkpoint=_trusted_checkpoint(),
        trust_period_seconds=3600,
    )

    source = build_cometbft_multi_rpc_finality_source(
        config=config,
        transaction_hash_for_operation=lambda operation_id: None,
        transports=[NoCallTransport(), NoCallTransport()],
    )

    assert source.finality_evidence("unknown-operation") is None
    assert isinstance(source, QuorumConsensusFinalitySource)


def test_multi_rpc_finality_wiring_rejects_insufficient_transport_count():
    config = CometBftMultiRpcFinalityConfig(
        rpc_endpoints=("https://consensus-a.example", "https://consensus-b.example"),
        minimum_agreement=2,
        chain_id="aidn-testnet-1",
        verifier_id="operator-checkpoint-quorum",
        trusted_checkpoint=_trusted_checkpoint(),
        trust_period_seconds=3600,
    )

    with pytest.raises(ValueError, match="match endpoint count"):
        build_cometbft_multi_rpc_finality_source(
            config=config,
            transaction_hash_for_operation=lambda operation_id: None,
            abci_application=AIDNABCIApplication(ledger_service=LedgerOperationService()),
            transports=[NoCallTransport()],
        )
