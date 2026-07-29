"""Tests for the strict, fail-closed CometBFT Ed25519 backend."""

from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.cometbft_crypto import (
    StrictCometBftEd25519Backend,
    Zip215CometBftEd25519Backend,
    cometbft_validator_set_from_rpc,
    cometbft_vote_sign_bytes,
    zip215_verify,
)
from aidn_hypervisor.consensus.light_client import (
    CometBftValidator,
    CometBftValidatorSet,
)


def _validator(private_key: Ed25519PrivateKey, voting_power: int) -> CometBftValidator:
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    address = hashlib.sha256(public_key).digest()[:20].hex().upper()
    return CometBftValidator(
        address=address,
        public_key=f"ed25519:{base64.b64encode(public_key).decode('ascii')}",
        voting_power=voting_power,
    )


def _block_id() -> dict[str, object]:
    return {
        "hash": "A" * 64,
        "part_set_header": {"total": "1", "hash": "B" * 64},
    }


def test_vote_sign_bytes_match_cometbft_v038_reference_vector():
    assert cometbft_vote_sign_bytes(
        chain_id="",
        height=1,
        round_number=1,
        block_id=None,
        timestamp="0001-01-01T00:00:00Z",
    ) == bytes(
        [
            0x21,
            0x08,
            0x02,
            0x11,
            0x01,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x19,
            0x01,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x2A,
            0x0B,
            0x08,
            0x80,
            0x92,
            0xB8,
            0xC3,
            0x98,
            0xFE,
            0xFF,
            0xFF,
            0xFF,
            0x01,
        ]
    )


def test_backend_hashes_rpc_validator_set_and_verifies_signed_precommits():
    private_keys = [
        Ed25519PrivateKey.from_private_bytes(bytes((offset + value) % 256 for value in range(1, 33)))
        for offset in range(3)
    ]
    validator_set = CometBftValidatorSet(
        tuple(
            _validator(private_key, voting_power)
            for private_key, voting_power in zip(private_keys, (4, 3, 3), strict=True)
        )
    )
    backend = StrictCometBftEd25519Backend()
    block_id = _block_id()
    timestamp = "2030-01-01T00:00:00.123456789Z"
    signatures = []
    for private_key, validator in zip(private_keys, validator_set.validators, strict=True):
        sign_bytes = cometbft_vote_sign_bytes(
            chain_id="aidn-testnet-1",
            height=11,
            round_number=2,
            block_id=block_id,
            timestamp=timestamp,
        )
        signatures.append(
            {
                "block_id_flag": 2,
                "validator_address": validator.address,
                "timestamp": timestamp,
                "signature": base64.b64encode(private_key.sign(sign_bytes)).decode("ascii"),
            }
        )
    signed_header = {
        "commit": {"height": "11", "round": "2", "block_id": block_id, "signatures": signatures}
    }

    assert (
        backend.validator_set_hash(validator_set)
        == "60763925C53BABC0DA3B395149EF1770043742EEFE62A3CE92F3C8BF99794AED"
    )
    assert backend.verified_signer_addresses(
        signed_header=signed_header,
        validator_set=validator_set,
        chain_id="aidn-testnet-1",
        block_height=11,
        block_id="A" * 64,
    ) == {validator.address for validator in validator_set.validators}


def test_backend_accepts_the_cometbft_rpc_block_id_parts_field():
    private_key = Ed25519PrivateKey.generate()
    validator = _validator(private_key, 1)
    validator_set = CometBftValidatorSet((validator,))
    backend = StrictCometBftEd25519Backend()
    block_id = {
        "hash": "A" * 64,
        "parts": {"total": "1", "hash": "B" * 64},
    }
    timestamp = "2030-01-01T00:00:00Z"
    signature = base64.b64encode(
        private_key.sign(
            cometbft_vote_sign_bytes(
                chain_id="aidn-testnet-1",
                height=11,
                round_number=0,
                block_id=block_id,
                timestamp=timestamp,
            )
        )
    ).decode("ascii")

    assert backend.verified_signer_addresses(
        signed_header={
            "commit": {
                "height": "11",
                "round": "0",
                "block_id": block_id,
                "signatures": [
                    {
                        "block_id_flag": 2,
                        "validator_address": validator.address,
                        "timestamp": timestamp,
                        "signature": signature,
                    }
                ],
            }
        },
        validator_set=validator_set,
        chain_id="aidn-testnet-1",
        block_height=11,
        block_id="A" * 64,
    ) == {validator.address}


def test_backend_rejects_any_invalid_or_duplicate_commit_signature():
    private_keys = [Ed25519PrivateKey.generate() for _ in range(2)]
    validator_set = CometBftValidatorSet(tuple(_validator(key, 5) for key in private_keys))
    backend = StrictCometBftEd25519Backend()
    block_id = _block_id()
    timestamp = "2030-01-01T00:00:00Z"
    signature = base64.b64encode(
        private_keys[0].sign(
            cometbft_vote_sign_bytes(
                chain_id="aidn-testnet-1",
                height=11,
                round_number=0,
                block_id=block_id,
                timestamp=timestamp,
            )
        )
    ).decode("ascii")
    signed_header = {
        "commit": {
            "height": "11",
            "round": "0",
            "block_id": block_id,
            "signatures": [
                {
                    "block_id_flag": 2,
                    "validator_address": validator_set.validators[0].address,
                    "timestamp": timestamp,
                    "signature": signature,
                },
                {
                    "block_id_flag": 2,
                    "validator_address": validator_set.validators[0].address,
                    "timestamp": timestamp,
                    "signature": signature,
                },
            ],
        }
    }

    assert not backend.verified_signer_addresses(
        signed_header=signed_header,
        validator_set=validator_set,
        chain_id="aidn-testnet-1",
        block_height=11,
        block_id="A" * 64,
    )


def test_zip215_accepts_noncanonical_identity_encoding_that_strict_ed25519_rejects():
    identity_encoding = (2**255 - 18).to_bytes(32, "little")
    signature = identity_encoding + b"\x00" * 32

    assert zip215_verify(
        signature=signature,
        public_key=identity_encoding,
        message=b"consensus test",
    )

    validator = CometBftValidator(
        address=hashlib.sha256(identity_encoding).digest()[:20].hex().upper(),
        public_key=f"ed25519:{base64.b64encode(identity_encoding).decode('ascii')}",
        voting_power=1,
    )
    validator_set = CometBftValidatorSet((validator,))
    block_id = _block_id()
    signed_header = {
        "commit": {
            "height": "11",
            "round": "0",
            "block_id": block_id,
            "signatures": [
                {
                    "block_id_flag": 2,
                    "validator_address": validator.address,
                    "timestamp": "2030-01-01T00:00:00Z",
                    "signature": base64.b64encode(signature).decode("ascii"),
                }
            ],
        }
    }

    assert not StrictCometBftEd25519Backend().verified_signer_addresses(
        signed_header=signed_header,
        validator_set=validator_set,
        chain_id="aidn-testnet-1",
        block_height=11,
        block_id="A" * 64,
    )
    assert Zip215CometBftEd25519Backend().verified_signer_addresses(
        signed_header=signed_header,
        validator_set=validator_set,
        chain_id="aidn-testnet-1",
        block_height=11,
        block_id="A" * 64,
    ) == {validator.address}


def test_rpc_validator_conversion_rejects_non_ed25519_keys():
    assert cometbft_validator_set_from_rpc(
        [
            {
                "address": "A" * 40,
                "pub_key": {"type": "tendermint/PubKeyEd25519", "value": base64.b64encode(b"x" * 32).decode("ascii")},
                "voting_power": "7",
            }
        ]
    ).validators[0].public_key.startswith("ed25519:")

    try:
        cometbft_validator_set_from_rpc(
            [
                {
                    "address": "A" * 40,
                    "pub_key": {"type": "tendermint/PubKeySecp256k1", "value": "ignored"},
                    "voting_power": "7",
                }
            ]
        )
    except ValueError as exc:
        assert "Ed25519" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("non-Ed25519 validator key was accepted")
