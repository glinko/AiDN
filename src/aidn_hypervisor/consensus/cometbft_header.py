"""Canonical CometBFT v0.38 header hashing for light-client verification."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone

_HEX_RE = re.compile(r"^[0-9a-fA-F]*$")
_TIMESTAMP_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d{1,9}))?(?P<zone>Z|[+-]\d{2}:\d{2})$"
)


def cometbft_header_hash(header: Mapping[str, object]) -> str:
    """Return the canonical block hash for one CometBFT v0.38 RPC header.

    The header is not JSON-hashed.  CometBFT creates a Merkle tree over its
    ordered, protobuf-encoded fields, including wrapper encodings for string,
    integer and byte values.  Rejecting malformed values is essential because
    the output is compared to the ``block_id`` validators precommitted.
    """
    version = _mapping(header.get("version"), "header version")
    block_version = _nonnegative_int(version.get("block"), "block version")
    app_version = _nonnegative_int(version.get("app"), "app version")
    chain_id = _string(header.get("chain_id"), "header chain_id")
    height = _positive_int(header.get("height"), "header height")
    timestamp = _protobuf_timestamp(_string(header.get("time"), "header time"))
    last_block_id = _protobuf_block_id(header.get("last_block_id"), allow_empty=True)

    fields = [
        _protobuf_consensus_version(block_version, app_version),
        _protobuf_string_wrapper(chain_id),
        _protobuf_int64_wrapper(height),
        timestamp,
        last_block_id,
        _protobuf_bytes_wrapper(_optional_hex_bytes(header.get("last_commit_hash"))),
        _protobuf_bytes_wrapper(_optional_hex_bytes(header.get("data_hash"))),
        _protobuf_bytes_wrapper(_required_hash(header.get("validators_hash"))),
        _protobuf_bytes_wrapper(_required_hash(header.get("next_validators_hash"))),
        _protobuf_bytes_wrapper(_optional_hex_bytes(header.get("consensus_hash"))),
        _protobuf_bytes_wrapper(_optional_hex_bytes(header.get("app_hash"))),
        _protobuf_bytes_wrapper(_optional_hex_bytes(header.get("last_results_hash"))),
        _protobuf_bytes_wrapper(_optional_hex_bytes(header.get("evidence_hash"))),
        _protobuf_bytes_wrapper(_required_bytes(header.get("proposer_address"), 20)),
    ]
    return _merkle_hash(fields).hex().upper()


def _protobuf_consensus_version(block: int, app: int) -> bytes:
    fields: list[bytes] = []
    if block:
        fields.append(_proto_varint_field(1, block))
    if app:
        fields.append(_proto_varint_field(2, app))
    return b"".join(fields)


def _protobuf_string_wrapper(value: str) -> bytes:
    return _proto_bytes_field(1, value.encode("utf-8")) if value else b""


def _protobuf_int64_wrapper(value: int) -> bytes:
    return _proto_varint_field(1, value) if value else b""


def _protobuf_bytes_wrapper(value: bytes) -> bytes:
    return _proto_bytes_field(1, value) if value else b""


def _protobuf_block_id(value: object, *, allow_empty: bool) -> bytes:
    if (value is None or value == "") and allow_empty:
        return b""
    block_id = _mapping(value, "block ID")
    hash_bytes = _optional_hex_bytes(block_id.get("hash"))
    parts = _block_parts(block_id)
    total = _nonnegative_int(parts.get("total"), "block part total")
    part_hash = _optional_hex_bytes(parts.get("hash"))
    if bool(hash_bytes) != bool(part_hash) or (not hash_bytes and total != 0):
        raise ValueError("CometBFT block ID is incomplete")
    part_fields: list[bytes] = []
    if total:
        part_fields.append(_proto_varint_field(1, total))
    if part_hash:
        part_fields.append(_proto_bytes_field(2, part_hash))
    parts_bytes = b"".join(part_fields)
    fields: list[bytes] = []
    if hash_bytes:
        fields.append(_proto_bytes_field(1, hash_bytes))
    if parts_bytes:
        fields.append(_proto_message_field(2, parts_bytes))
    return b"".join(fields)


def _block_parts(block_id: Mapping[str, object]) -> Mapping[str, object]:
    legacy = block_id.get("part_set_header")
    current = block_id.get("parts")
    if legacy is not None and current is not None:
        raise ValueError("CometBFT block ID has ambiguous parts")
    return _mapping(current if current is not None else legacy, "block part set")


def _protobuf_timestamp(value: str) -> bytes:
    match = _TIMESTAMP_RE.fullmatch(value)
    if match is None:
        raise ValueError("CometBFT header time is invalid")
    zone = match.group("zone")
    tz = UTC if zone == "Z" else timezone(timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6])))
    if zone.startswith("-"):
        tz = timezone(-tz.utcoffset(None))
    parsed = datetime.fromisoformat(
        f"{match.group('date')}T{match.group('time')}"
    ).replace(tzinfo=tz)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = parsed.astimezone(UTC) - epoch
    fields = [_proto_varint_field(1, delta.days * 86_400 + delta.seconds)]
    nanoseconds = int((match.group("fraction") or "").ljust(9, "0"))
    if nanoseconds:
        fields.append(_proto_varint_field(2, nanoseconds))
    return b"".join(fields)


def _merkle_hash(values: list[bytes]) -> bytes:
    if len(values) == 1:
        return _leaf_hash(values[0])
    split = 1 << (len(values).bit_length() - 1)
    if split == len(values):
        split >>= 1
    return _inner_hash(_merkle_hash(values[:split]), _merkle_hash(values[split:]))


def _leaf_hash(value: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + value).digest()


def _inner_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"CometBFT {field_name} is invalid")
    return value


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"CometBFT {field_name} is invalid")
    return value


def _required_hash(value: object) -> bytes:
    decoded = _optional_hex_bytes(value)
    if len(decoded) != 32:
        raise ValueError("CometBFT required hash is invalid")
    return decoded


def _required_bytes(value: object, expected_length: int) -> bytes:
    decoded = _optional_hex_bytes(value)
    if len(decoded) != expected_length:
        raise ValueError("CometBFT required bytes are invalid")
    return decoded


def _optional_hex_bytes(value: object) -> bytes:
    if value is None or value == "":
        return b""
    if not isinstance(value, str) or len(value) % 2 or _HEX_RE.fullmatch(value) is None:
        raise ValueError("CometBFT hex bytes are invalid")
    return bytes.fromhex(value)


def _positive_int(value: object, field_name: str) -> int:
    result = _nonnegative_int(value, field_name)
    if result < 1:
        raise ValueError(f"CometBFT {field_name} must be positive")
    return result


def _nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"CometBFT {field_name} is invalid")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isdecimal():
        result = int(value)
    else:
        raise ValueError(f"CometBFT {field_name} is invalid")
    if result < 0:
        raise ValueError(f"CometBFT {field_name} is invalid")
    return result


def _proto_varint_field(field_number: int, value: int) -> bytes:
    return _encode_varint(field_number << 3) + _encode_varint(value)


def _proto_bytes_field(field_number: int, value: bytes) -> bytes:
    return _encode_varint((field_number << 3) | 2) + _encode_varint(len(value)) + value


def _proto_message_field(field_number: int, value: bytes) -> bytes:
    return _proto_bytes_field(field_number, value)


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("CometBFT protobuf integer is invalid")
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)
