import base64
import hashlib

import pytest

from aidn_hypervisor.consensus.cometbft_merkle import (
    verify_cometbft_transaction_inclusion,
)


def _leaf_hash(transaction: bytes) -> bytes:
    transaction_hash = hashlib.sha256(transaction).digest()
    return hashlib.sha256(b"\x00" + transaction_hash).digest()


def _inner_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _proof_for_first_transaction() -> tuple[dict, str]:
    transaction = b'{"operation_id":"operation-1"}'
    sibling = b'{"operation_id":"operation-2"}'
    transaction_hash = hashlib.sha256(transaction).hexdigest().upper()
    root_hash = _inner_hash(_leaf_hash(transaction), _leaf_hash(sibling)).hex().upper()
    transaction_result = {
        "tx": base64.b64encode(transaction).decode("ascii"),
        "proof": {
            "root_hash": root_hash,
            "data": base64.b64encode(transaction).decode("ascii"),
            "proof": {
                "total": "2",
                "index": "0",
                "leaf_hash": _leaf_hash(transaction).hex().upper(),
                "aunts": [_leaf_hash(sibling).hex().upper()],
            },
        },
    }
    return transaction_result, transaction_hash


def test_cometbft_transaction_proof_binds_transaction_to_committed_data_hash():
    transaction_result, transaction_hash = _proof_for_first_transaction()
    data_hash = transaction_result["proof"]["root_hash"]

    assert verify_cometbft_transaction_inclusion(
        transaction_result=transaction_result,
        transaction_hash=transaction_hash,
        block_height=11,
        block_id="A" * 64,
        data_hash=data_hash,
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda result: result["proof"].update({"root_hash": "F" * 64}),
        lambda result: result["proof"]["proof"].update({"aunts": ["0" * 64]}),
        lambda result: result.update({"tx": base64.b64encode(b"other").decode("ascii")}),
        lambda result: result["proof"].update({"data": base64.b64encode(b"other").decode("ascii")}),
        lambda result: result["proof"]["proof"].update({"total": "1"}),
    ],
)
def test_cometbft_transaction_proof_rejects_tampered_or_incomplete_evidence(mutator):
    transaction_result, transaction_hash = _proof_for_first_transaction()
    data_hash = transaction_result["proof"]["root_hash"]
    mutator(transaction_result)

    assert not verify_cometbft_transaction_inclusion(
        transaction_result=transaction_result,
        transaction_hash=transaction_hash,
        block_height=11,
        block_id="A" * 64,
        data_hash=data_hash,
    )
