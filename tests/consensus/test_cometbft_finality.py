import base64
import json

import pytest

from aidn_hypervisor.consensus.cometbft import (
    CometBftRpcFinalitySource,
    CometBftRpcValidatorSetProvider,
    HttpCometBftRpcTransport,
    cometbft_transaction_hash,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope


class RecordingTransport:
    def __init__(self, *, transaction_response: dict, commit_response: dict) -> None:
        self.transaction_response = transaction_response
        self.commit_response = commit_response
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, path: str, *, params: dict[str, str], timeout_seconds: int) -> dict:
        self.calls.append((path, params))
        if path == "/tx":
            return self.transaction_response
        if path == "/commit":
            return self.commit_response
        raise AssertionError(f"unexpected path: {path}")


class AcceptingProofVerifier:
    def __init__(self, *, accept_transaction: bool = True, accept_commit: bool = True) -> None:
        self.accept_transaction = accept_transaction
        self.accept_commit = accept_commit
        self.transaction_calls: list[dict] = []
        self.commit_calls: list[dict] = []

    def verify_transaction_proof(self, **kwargs) -> bool:
        self.transaction_calls.append(kwargs)
        return self.accept_transaction

    def verify_commit(self, **kwargs) -> bool:
        self.commit_calls.append(kwargs)
        return self.accept_commit


class ValidatorPagingTransport:
    def __init__(self, pages: dict[tuple[str, str], dict]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, path: str, *, params: dict[str, str], timeout_seconds: int) -> dict:
        self.calls.append((path, params))
        return self.pages[(params["height"], params["page"])]


def _validator(address: str) -> dict:
    return {
        "address": address,
        "pub_key": {"type": "tendermint/PubKeyEd25519", "value": base64.b64encode(b"x" * 32).decode("ascii")},
        "voting_power": "1",
    }


def _validator_page(*, height: int, total: int, validators: list[dict]) -> dict:
    return {
        "result": {
            "block_height": str(height),
            "total": str(total),
            "count": str(len(validators)),
            "validators": validators,
        }
    }


def _responses(*, transaction_bytes: bytes, transaction_hash: str) -> tuple[dict, dict]:
    return (
        {
            "result": {
                "hash": transaction_hash,
                "height": "11",
                "tx_result": {"code": 0},
                "proof": {"ops": []},
                "tx": base64.b64encode(transaction_bytes).decode("ascii"),
            }
        },
        {
            "result": {
                "canonical": True,
                "signed_header": {
                    "header": {
                        "chain_id": "aidn-testnet-1",
                        "height": "11",
                        "app_hash": "A" * 64,
                        "time": "2030-01-01T00:00:00Z",
                    },
                    "commit": {"block_id": {"hash": "B" * 64}},
                },
            }
        },
    )


def _source(*, proof_verifier: AcceptingProofVerifier | None = None):
    envelope = LedgerOperationEnvelope(
        operation_type="REGISTRY_UPSERT",
        origin_type="protocol",
        created_at="2030-01-01T00:00:00Z",
    )
    transaction_bytes = json.dumps(envelope.model_dump(mode="json")).encode("utf-8")
    transaction_hash = cometbft_transaction_hash(transaction_bytes)
    tx_response, commit_response = _responses(
        transaction_bytes=transaction_bytes,
        transaction_hash=transaction_hash,
    )
    transport = RecordingTransport(
        transaction_response=tx_response,
        commit_response=commit_response,
    )
    verifier = proof_verifier or AcceptingProofVerifier()
    source = CometBftRpcFinalitySource(
        chain_id="aidn-testnet-1",
        transaction_hash_for_operation=lambda operation_id: transaction_hash,
        proof_verifier=verifier,
        transport=transport,
        verifier_id="test-light-client",
    )
    return source, envelope, transport, verifier


def test_cometbft_finality_source_requires_verified_transaction_and_commit_proofs():
    source, envelope, transport, verifier = _source()
    expected_hash = cometbft_transaction_hash(
        json.dumps(envelope.model_dump(mode="json")).encode("utf-8")
    )

    evidence = source.finality_evidence(envelope.operation_id)

    assert evidence is not None
    assert evidence.operation_id == envelope.operation_id
    assert evidence.chain_id == "aidn-testnet-1"
    assert evidence.block_height == 11
    assert evidence.block_id == "B" * 64
    assert evidence.app_hash == "A" * 64
    assert len(evidence.commit_hash) == 64
    assert transport.calls == [
        ("/tx", {"hash": f"0x{expected_hash}", "prove": "true"}),
        ("/commit", {"height": "11"}),
    ]
    assert verifier.transaction_calls[0]["transaction_hash"] == transport.calls[0][1]["hash"][2:]
    assert verifier.commit_calls[0]["chain_id"] == "aidn-testnet-1"


@pytest.mark.parametrize("accept_transaction,accept_commit", [(False, True), (True, False)])
def test_cometbft_finality_source_fails_closed_when_a_proof_verification_fails(
    accept_transaction: bool,
    accept_commit: bool,
):
    source, envelope, _, _ = _source(
        proof_verifier=AcceptingProofVerifier(
            accept_transaction=accept_transaction,
            accept_commit=accept_commit,
        )
    )

    assert source.finality_evidence(envelope.operation_id) is None


def test_cometbft_finality_source_rejects_mismatched_operation_transaction():
    source, envelope, transport, _ = _source()
    other = LedgerOperationEnvelope(
        operation_type="REGISTRY_UPSERT",
        origin_type="protocol",
        created_at="2030-01-02T00:00:00Z",
    )
    other_bytes = json.dumps(other.model_dump(mode="json")).encode("utf-8")
    transport.transaction_response["result"]["tx"] = base64.b64encode(other_bytes).decode("ascii")
    transport.transaction_response["result"]["hash"] = cometbft_transaction_hash(other_bytes)

    assert source.finality_evidence(envelope.operation_id) is None


def test_cometbft_finality_source_requires_canonical_commit_response():
    source, envelope, transport, _ = _source()
    transport.commit_response["result"]["canonical"] = False

    assert source.finality_evidence(envelope.operation_id) is None


def test_http_cometbft_transport_rejects_unsafe_endpoint_configuration():
    with pytest.raises(ValueError, match="credentials"):
        HttpCometBftRpcTransport("https://token@example.test")
    with pytest.raises(ValueError, match="path"):
        HttpCometBftRpcTransport("https://example.test/rpc")


def test_validator_set_provider_fetches_every_page_for_current_and_next_sets():
    first = [_validator("A" * 40), _validator("B" * 40)]
    second = [_validator("C" * 40)]
    next_first = [_validator("D" * 40), _validator("E" * 40)]
    next_second = [_validator("F" * 40)]
    transport = ValidatorPagingTransport(
        {
            ("11", "1"): _validator_page(height=11, total=3, validators=first),
            ("11", "2"): _validator_page(height=11, total=3, validators=second),
            ("12", "1"): _validator_page(height=12, total=3, validators=next_first),
            ("12", "2"): _validator_page(height=12, total=3, validators=next_second),
        }
    )
    provider = CometBftRpcValidatorSetProvider(transport=transport, per_page=2)

    current, next_set = provider.validator_sets_for_height(11)

    assert [validator.address for validator in current.validators] == ["A" * 40, "B" * 40, "C" * 40]
    assert [validator.address for validator in next_set.validators] == ["D" * 40, "E" * 40, "F" * 40]
    assert len(transport.calls) == 4


def test_validator_set_provider_rejects_changed_total_during_pagination():
    transport = ValidatorPagingTransport(
        {
            ("11", "1"): _validator_page(height=11, total=3, validators=[_validator("A" * 40)]),
            ("11", "2"): _validator_page(height=11, total=2, validators=[_validator("B" * 40)]),
        }
    )
    provider = CometBftRpcValidatorSetProvider(transport=transport, per_page=1)

    with pytest.raises(ValueError, match="changed"):
        provider.validator_set_at(11)
