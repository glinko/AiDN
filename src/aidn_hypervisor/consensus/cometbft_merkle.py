"""Strict verification for CometBFT ``/tx?prove=true`` transaction proofs."""

from __future__ import annotations

import base64
import hashlib

_HASH_LENGTH = 32
_MAX_AUNTS = 100


def verify_cometbft_transaction_inclusion(
    *,
    transaction_result: dict,
    transaction_hash: str,
    block_height: int,
    block_id: str,
    data_hash: str,
) -> bool:
    """Verify a CometBFT ``TxProof`` against the committed header data hash.

    CometBFT computes the block ``data_hash`` from transaction hashes, rather
    than raw transactions.  Its proof leaf is consequently
    ``SHA256(0x00 || SHA256(raw_transaction))``.  The explicit raw-byte checks
    prevent an RPC response from mixing a valid proof with another operation.
    """
    try:
        if block_height < 1 or not block_id.strip():
            return False
        normalized_transaction_hash = _decode_hash(transaction_hash)
        committed_data_hash = _decode_hash(data_hash)
        transaction_bytes = _decode_base64(transaction_result.get("tx"))
        if hashlib.sha256(transaction_bytes).digest() != normalized_transaction_hash:
            return False

        tx_proof = transaction_result.get("proof")
        if not isinstance(tx_proof, dict):
            return False
        if _decode_base64(tx_proof.get("data")) != transaction_bytes:
            return False
        if _decode_hash(tx_proof.get("root_hash")) != committed_data_hash:
            return False

        proof = tx_proof.get("proof")
        if not isinstance(proof, dict):
            return False
        total = _positive_int(proof.get("total"))
        index = _nonnegative_int(proof.get("index"))
        if index >= total:
            return False
        leaf_hash = _decode_hash(proof.get("leaf_hash"))
        expected_leaf_hash = _leaf_hash(normalized_transaction_hash)
        if leaf_hash != expected_leaf_hash:
            return False
        aunts_value = proof.get("aunts")
        if not isinstance(aunts_value, list) or len(aunts_value) > _MAX_AUNTS:
            return False
        aunts = [_decode_hash(aunt) for aunt in aunts_value]
        root_hash = _compute_root(index=index, total=total, leaf_hash=leaf_hash, aunts=aunts)
        return root_hash == committed_data_hash
    except (TypeError, ValueError):
        return False


def _decode_base64(value: object) -> bytes:
    if not isinstance(value, str):
        raise ValueError("CometBFT proof data is invalid")
    return base64.b64decode(value, validate=True)


def _decode_hash(value: object) -> bytes:
    if not isinstance(value, str):
        raise ValueError("CometBFT hash is invalid")
    normalized = value.removeprefix("0x")
    if len(normalized) != _HASH_LENGTH * 2:
        raise ValueError("CometBFT hash is invalid")
    try:
        decoded = bytes.fromhex(normalized)
    except ValueError as error:
        raise ValueError("CometBFT hash is invalid") from error
    if len(decoded) != _HASH_LENGTH:
        raise ValueError("CometBFT hash is invalid")
    return decoded


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("CometBFT proof integer is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("CometBFT proof integer is invalid") from error
    if result < 0:
        raise ValueError("CometBFT proof integer is invalid")
    return result


def _positive_int(value: object) -> int:
    result = _nonnegative_int(value)
    if result < 1:
        raise ValueError("CometBFT proof total is invalid")
    return result


def _leaf_hash(value: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + value).digest()


def _inner_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _compute_root(*, index: int, total: int, leaf_hash: bytes, aunts: list[bytes]) -> bytes:
    if total == 1:
        if index != 0 or aunts:
            raise ValueError("CometBFT proof shape is invalid")
        return leaf_hash
    if not aunts:
        raise ValueError("CometBFT proof is incomplete")
    left_total = _largest_power_of_two_less_than(total)
    aunt = aunts[-1]
    if index < left_total:
        return _inner_hash(
            _compute_root(
                index=index,
                total=left_total,
                leaf_hash=leaf_hash,
                aunts=aunts[:-1],
            ),
            aunt,
        )
    return _inner_hash(
        aunt,
        _compute_root(
            index=index - left_total,
            total=total - left_total,
            leaf_hash=leaf_hash,
            aunts=aunts[:-1],
        ),
    )


def _largest_power_of_two_less_than(value: int) -> int:
    if value < 2:
        raise ValueError("CometBFT proof total is invalid")
    return 1 << (value.bit_length() - 2)
