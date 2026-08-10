from __future__ import annotations

from typing import Any

from aidn_faucet.cometbft_submitter import (
    CometBftFaucetTransferSubmitter,
    FailoverCometBftSubmissionTransport,
    HttpCometBftWalletSequenceProvider,
    serialize_faucet_envelope,
)

from aidn_hypervisor.consensus.cometbft import cometbft_transaction_hash
from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence, QuorumConsensusFinalitySource
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope


def _envelope() -> LedgerOperationEnvelope:
    return LedgerOperationEnvelope(
        operation_type="WALLET_TRANSFER",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="wallet",
        initiator_id="faucet:test",
        sender_wallet="wallet-treasury",
        sender_sequence=1,
        fee_payer="wallet-treasury",
        fee_class="standard",
        created_at="2030-01-01T00:00:00+00:00",
        expires_at="2030-01-01T00:15:00+00:00",
        payload={"recipient_wallet": "wallet-recipient", "amount": 50_000_000},
        signatures=["ed25519:" + "11" * 64],
    )


class SubmissionTransport:
    def __init__(self, response: dict[str, Any] | Exception) -> None:
        self.response = response
        self.calls: list[bytes] = []

    def broadcast_tx_sync(self, tx_data: bytes, *, timeout_seconds: int) -> dict:
        del timeout_seconds
        self.calls.append(tx_data)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FinalitySource:
    def __init__(self, evidence: ConsensusFinalityEvidence | None) -> None:
        self.evidence = evidence
        self.operations: list[str] = []

    def finality_evidence(self, operation_id: str) -> ConsensusFinalityEvidence | None:
        self.operations.append(operation_id)
        return self.evidence


def _submitter(
    *,
    transport: SubmissionTransport,
    finality: FinalitySource,
) -> CometBftFaucetTransferSubmitter:
    return CometBftFaucetTransferSubmitter(
        treasury_wallet_id="wallet-treasury",
        chain_id="aidn-testnet-1",
        sequence_provider=lambda wallet_id: 1,
        submission_transport=transport,
        finality_source=finality,
    )


def test_admission_is_not_finality_and_reconcile_reuses_exact_bytes() -> None:
    envelope = _envelope()
    tx_hash = cometbft_transaction_hash(serialize_faucet_envelope(envelope))
    transport = SubmissionTransport({"result": {"code": 0, "hash": tx_hash}})
    finality = FinalitySource(None)
    submitter = _submitter(transport=transport, finality=finality)

    admitted = submitter.submit_transfer(envelope)
    pending = submitter.reconcile_transfer(envelope)

    assert admitted.status == "ADMITTED"
    assert pending.status == "ADMITTED"
    assert transport.calls == [serialize_faucet_envelope(envelope)]
    assert finality.operations == [envelope.operation_id]


def test_verified_finality_is_the_only_finalized_result() -> None:
    envelope = _envelope()
    evidence = ConsensusFinalityEvidence(
        operation_id=envelope.operation_id,
        chain_id="aidn-testnet-1",
        block_height=17,
        block_id="A" * 64,
        app_hash="B" * 64,
        commit_hash="C" * 64,
        finalized_at="2030-01-01T00:00:01+00:00",
        verifier_id="validator-quorum",
    )
    transport = SubmissionTransport({"result": {"code": 0}})
    submitter = _submitter(transport=transport, finality=FinalitySource(evidence))

    assert submitter.submit_transfer(envelope).status == "ADMITTED"
    finalized = submitter.reconcile_transfer(envelope)

    assert finalized.status == "FINALIZED"
    assert finalized.transaction_hash == cometbft_transaction_hash(
        serialize_faucet_envelope(envelope)
    )


def test_adapter_accepts_finality_only_from_configured_validator_quorum() -> None:
    envelope = _envelope()
    evidence = ConsensusFinalityEvidence(
        operation_id=envelope.operation_id,
        chain_id="aidn-testnet-1",
        block_height=18,
        block_id="D" * 64,
        app_hash="E" * 64,
        commit_hash="F" * 64,
        finalized_at="2030-01-01T00:00:02+00:00",
        verifier_id="validator-0",
    )
    quorum = QuorumConsensusFinalitySource(
        sources=(FinalitySource(evidence), FinalitySource(evidence)),
        quorum=2,
        source_ids=("validator-0", "validator-1"),
    )
    submitter = _submitter(
        transport=SubmissionTransport({"result": {"code": 0}}),
        finality=quorum,
    )

    submitter.submit_transfer(envelope)
    assert submitter.reconcile_transfer(envelope).status == "FINALIZED"


def test_failover_sends_identical_bytes_to_second_rpc() -> None:
    envelope = _envelope()
    first = SubmissionTransport(RuntimeError("rpc-1 timeout"))
    tx_hash = cometbft_transaction_hash(serialize_faucet_envelope(envelope))
    second = SubmissionTransport({"result": {"code": 0, "hash": tx_hash}})
    transport = FailoverCometBftSubmissionTransport((first, second))
    submitter = _submitter(transport=transport, finality=FinalitySource(None))

    result = submitter.submit_transfer(envelope)

    assert result.status == "ADMITTED"
    assert first.calls == [second.calls[0]]


class RpcTransport:
    def __init__(self, sequence: int | None) -> None:
        self.sequence = sequence

    def get(self, path: str, *, params: dict[str, str], timeout_seconds: int) -> dict:
        del path, params, timeout_seconds
        if self.sequence is None:
            return {"result": {"response": {"code": 1}}}
        import base64

        return {
            "result": {
                "response": {
                    "code": 0,
                    "value": base64.b64encode(str(self.sequence).encode()).decode(),
                }
            }
        }


def test_sequence_provider_requires_configured_quorum() -> None:
    provider = HttpCometBftWalletSequenceProvider(
        (RpcTransport(4), RpcTransport(4), RpcTransport(5)),
        quorum=2,
    )
    assert provider("wallet-treasury") == 4

    disagreeing = HttpCometBftWalletSequenceProvider(
        (RpcTransport(4), RpcTransport(5)),
        quorum=2,
    )
    try:
        disagreeing("wallet-treasury")
    except RuntimeError as error:
        assert "disagree" in str(error)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("sequence disagreement must fail closed")
