"""Strict CometBFT v0.38 Ed25519 primitives for the local light client.

This module implements the protobuf encodings used by CometBFT's ``VoteSignBytes``
and ``ValidatorSet.Hash`` instead of treating the RPC JSON as a signed format.
It intentionally supports only Ed25519 validator keys.  ``cryptography`` applies
strict Ed25519 verification; a verifier with CometBFT's ZIP-215 acceptance rules
must be supplied before relying on signatures that depend on that distinction.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import struct
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from aidn_hypervisor.consensus.light_client import (
    CometBftValidator,
    CometBftValidatorSet,
)

_ED25519_KEY_TYPE = "tendermint/PubKeyEd25519"
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_TIMESTAMP_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d{1,9}))?(?P<zone>Z|[+-]\d{2}:\d{2})$"
)


def cometbft_validator_set_from_rpc(validators: list[Mapping[str, object]]) -> CometBftValidatorSet:
    """Convert one complete CometBFT ``/validators`` page set to typed state.

    Pagination is deliberately outside this helper: accepting a partial validator
    set as a consensus set would make its hash and voting power meaningless.
    """
    converted: list[CometBftValidator] = []
    for item in validators:
        public_key = item.get("pub_key")
        if not isinstance(public_key, Mapping):
            raise ValueError("CometBFT validator public key is missing")
        key_type = public_key.get("type")
        key_value = public_key.get("value")
        address = item.get("address")
        voting_power = item.get("voting_power")
        if (
            key_type != _ED25519_KEY_TYPE
            or not isinstance(key_value, str)
            or not isinstance(address, str)
        ):
            raise ValueError("CometBFT validator is not an Ed25519 RPC record")
        converted.append(
            CometBftValidator(
                address=_normalise_address(address),
                public_key=f"ed25519:{key_value}",
                voting_power=_parse_positive_int(voting_power, "validator voting power"),
            )
        )
    return CometBftValidatorSet(tuple(converted))


def cometbft_vote_sign_bytes(
    *,
    chain_id: str,
    height: int,
    round_number: int,
    block_id: Mapping[str, object] | None,
    timestamp: str,
) -> bytes:
    """Return CometBFT v0.38 ``VoteSignBytes`` for a precommit vote."""
    if height < 0 or round_number < 0:
        raise ValueError("CometBFT vote height and round must not be negative")
    fields = [_proto_varint_field(1, 2)]
    if height:
        fields.append(_proto_fixed64_field(2, height))
    if round_number:
        fields.append(_proto_fixed64_field(3, round_number))
    if block_id is not None:
        fields.append(_proto_message_field(4, _canonical_block_id(block_id)))
    fields.append(_proto_message_field(5, _protobuf_timestamp(timestamp)))
    if chain_id:
        fields.append(_proto_bytes_field(6, chain_id.encode("utf-8")))
    payload = b"".join(fields)
    return _encode_varint(len(payload)) + payload


class StrictCometBftEd25519Backend:
    """Hash validator sets and verify standard Ed25519 CometBFT precommits.

    This backend is deliberately conservative.  Unsupported key encodings,
    malformed RPC values, duplicate commit signatures and every verification
    failure result in no accepted signers.
    """

    def validator_set_hash(self, validator_set: CometBftValidatorSet) -> str:
        leaves = [_simple_validator_bytes(validator) for validator in validator_set.validators]
        return _merkle_hash(leaves).hex().upper()

    def verified_signer_addresses(
        self,
        *,
        signed_header: dict,
        validator_set: CometBftValidatorSet,
        chain_id: str,
        block_height: int,
        block_id: str,
    ) -> set[str]:
        try:
            commit = signed_header["commit"]
            if not isinstance(commit, Mapping):
                return set()
            if _parse_positive_int(commit.get("height"), "commit height") != block_height:
                return set()
            round_number = _parse_nonnegative_int(commit.get("round"), "commit round")
            commit_block_id = commit.get("block_id")
            if not isinstance(commit_block_id, Mapping):
                return set()
            if _normalise_hash(commit_block_id.get("hash")) != _normalise_hash(block_id):
                return set()
            signatures = commit.get("signatures")
            if not isinstance(signatures, list):
                return set()
            validators = {
                _normalise_address(validator.address): validator
                for validator in validator_set.validators
            }
            signers: set[str] = set()
            for signature in signatures:
                if not isinstance(signature, Mapping):
                    return set()
                if _parse_nonnegative_int(signature.get("block_id_flag"), "block ID flag") != 2:
                    continue
                address = _normalise_address(signature.get("validator_address"))
                validator = validators.get(address)
                if validator is None or address in signers:
                    return set()
                raw_signature = _decode_base64(signature.get("signature"), "commit signature")
                if len(raw_signature) != 64:
                    return set()
                sign_bytes = cometbft_vote_sign_bytes(
                    chain_id=chain_id,
                    height=block_height,
                    round_number=round_number,
                    block_id=commit_block_id,
                    timestamp=_required_string(signature.get("timestamp"), "commit timestamp"),
                )
                public_key = _validator_public_key(validator)
                if _address_for_public_key(public_key) != address:
                    return set()
                Ed25519PublicKey.from_public_bytes(public_key).verify(raw_signature, sign_bytes)
                signers.add(address)
            return signers
        except (InvalidSignature, OverflowError, struct.error, TypeError, ValueError, KeyError):
            return set()


def _simple_validator_bytes(validator: CometBftValidator) -> bytes:
    public_key = _validator_public_key(validator)
    if _address_for_public_key(public_key) != _normalise_address(validator.address):
        raise ValueError("CometBFT validator address does not match public key")
    public_key_message = _proto_bytes_field(1, public_key)
    return _proto_message_field(1, public_key_message) + _proto_varint_field(
        2, validator.voting_power
    )


def _canonical_block_id(block_id: Mapping[str, object]) -> bytes:
    block_hash = _decode_hex(_required_string(block_id.get("hash"), "block hash"), 32)
    part_set_header = block_id.get("part_set_header")
    if not isinstance(part_set_header, Mapping):
        raise ValueError("CometBFT block part set header is missing")
    total = _parse_nonnegative_int(part_set_header.get("total"), "part set total")
    part_hash = _decode_hex(
        _required_string(part_set_header.get("hash"), "part set hash"), 32
    )
    part_set = _proto_varint_field(1, total) + _proto_bytes_field(2, part_hash)
    return _proto_bytes_field(1, block_hash) + _proto_message_field(2, part_set)


def _protobuf_timestamp(value: str) -> bytes:
    match = _TIMESTAMP_RE.fullmatch(value)
    if match is None:
        raise ValueError("CometBFT timestamp must be RFC3339 with a timezone")
    fraction = (match.group("fraction") or "").ljust(9, "0")
    zone = match.group("zone")
    tz = UTC if zone == "Z" else timezone(timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6])))
    if zone.startswith("-"):
        tz = timezone(-tz.utcoffset(None))
    parsed = datetime.fromisoformat(f"{match.group('date')}T{match.group('time')}").replace(tzinfo=tz)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = parsed.astimezone(UTC) - epoch
    seconds = delta.days * 86_400 + delta.seconds
    nanos = int(fraction)
    fields = [_proto_varint_field(1, seconds)]
    if nanos:
        fields.append(_proto_varint_field(2, nanos))
    return b"".join(fields)


def _merkle_hash(items: list[bytes]) -> bytes:
    if not items:
        return hashlib.sha256(b"").digest()
    if len(items) == 1:
        return hashlib.sha256(b"\x00" + items[0]).digest()
    split = 1 << (len(items).bit_length() - 1)
    if split == len(items):
        split >>= 1
    return hashlib.sha256(b"\x01" + _merkle_hash(items[:split]) + _merkle_hash(items[split:])).digest()


def _validator_public_key(validator: CometBftValidator) -> bytes:
    prefix, separator, encoded = validator.public_key.partition(":")
    if prefix != "ed25519" or not separator:
        raise ValueError("CometBFT backend requires an ed25519:<base64> public key")
    public_key = _decode_base64(encoded, "validator public key")
    if len(public_key) != 32:
        raise ValueError("CometBFT Ed25519 public key must be 32 bytes")
    return public_key


def _address_for_public_key(public_key: bytes) -> str:
    return hashlib.sha256(public_key).digest()[:20].hex().upper()


def _normalise_address(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("CometBFT validator address is missing")
    text = value.strip()
    if len(text) == 40 and _HEX_RE.fullmatch(text):
        return text.upper()
    decoded = _decode_base64(text, "validator address")
    if len(decoded) != 20:
        raise ValueError("CometBFT validator address must be 20 bytes")
    return decoded.hex().upper()


def _normalise_hash(value: object) -> str:
    return _decode_hex(_required_string(value, "CometBFT hash"), 32).hex().upper()


def _decode_hex(value: str, expected_length: int) -> bytes:
    if len(value) != expected_length * 2 or _HEX_RE.fullmatch(value) is None:
        raise ValueError("CometBFT hash has an invalid length or encoding")
    return bytes.fromhex(value)


def _decode_base64(value: object, field_name: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError(f"CometBFT {field_name} is missing")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"CometBFT {field_name} is not base64") from exc


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"CometBFT {field_name} is missing")
    return value


def _parse_positive_int(value: object, field_name: str) -> int:
    result = _parse_nonnegative_int(value, field_name)
    if result < 1:
        raise ValueError(f"CometBFT {field_name} must be positive")
    return result


def _parse_nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"CometBFT {field_name} is invalid")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isdecimal():
        result = int(value)
    else:
        raise ValueError(f"CometBFT {field_name} is invalid")
    if result < 0:
        raise ValueError(f"CometBFT {field_name} must not be negative")
    return result


def _proto_varint_field(field_number: int, value: int) -> bytes:
    if value < 0:
        value &= (1 << 64) - 1
    return _encode_varint(field_number << 3) + _encode_varint(value)


def _proto_fixed64_field(field_number: int, value: int) -> bytes:
    return _encode_varint((field_number << 3) | 1) + struct.pack("<q", value)


def _proto_bytes_field(field_number: int, value: bytes) -> bytes:
    return _encode_varint((field_number << 3) | 2) + _encode_varint(len(value)) + value


def _proto_message_field(field_number: int, value: bytes) -> bytes:
    return _proto_bytes_field(field_number, value)


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("protobuf varint must not be negative")
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)
