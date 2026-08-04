"""Minimal CometBFT v0.38 ABCI socket transport for the AiDN application."""

from __future__ import annotations

import base64
import binascii
import socket
from collections.abc import Iterable
from datetime import UTC, datetime
from threading import Event, RLock, Thread

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.abci_models import ABCIResult
from aidn_hypervisor.consensus.state_store import ABCIStateSnapshot, ABCIStateStoreError


class ABCIWireError(ValueError):
    """A malformed or unsupported bounded ABCI protobuf frame."""


class AIDNABCISocketServer:
    """Serve CometBFT's length-delimited protobuf ABCI socket protocol.

    The server deliberately implements only the v0.38 request set used by a
    normal validator.  Unsupported or malformed frames receive an ABCI
    ``ResponseException`` and never reach the Ledger state machine.
    """

    def __init__(
        self,
        *,
        application: AIDNABCIApplication,
        host: str = "127.0.0.1",
        port: int = 26658,
        maximum_message_size: int = 1_048_576,
    ) -> None:
        if not host.strip() or not 0 <= port <= 65535:
            raise ValueError("ABCI socket address is invalid")
        if maximum_message_size < 1:
            raise ValueError("ABCI maximum_message_size must be positive")
        self.application = application
        self.host = host
        self.port = port
        self.maximum_message_size = maximum_message_size
        self._lock = RLock()
        self._stopped = Event()
        self._server: socket.socket | None = None
        self._thread: Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            raise RuntimeError("ABCI socket server is already running")
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen()
        server.settimeout(0.2)
        self.port = server.getsockname()[1]
        self._server = server
        self._stopped.clear()
        self._thread = Thread(target=self._serve, name="aidn-abci-socket", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._server is not None:
            self._server.close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None

    def _serve(self) -> None:
        assert self._server is not None
        while not self._stopped.is_set():
            try:
                connection, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            Thread(target=self._serve_connection, args=(connection,), daemon=True).start()

    def _serve_connection(self, connection: socket.socket) -> None:
        with connection:
            # CometBFT holds several dedicated ABCI channels open, including
            # an idle snapshot channel. A read timeout would turn normal idle
            # time into EOF and halt the validator.
            connection.settimeout(None)
            while not self._stopped.is_set():
                try:
                    request = _read_frame(connection, self.maximum_message_size)
                except EOFError:
                    return
                except (OSError, ABCIWireError):
                    return
                with self._lock:
                    response = self._dispatch(request)
                try:
                    _write_frame(connection, response)
                except OSError:
                    return

    def _dispatch(self, request: bytes) -> bytes:
        try:
            kind, payload = _oneof(request, _REQUEST_FIELDS)
            if kind == "echo":
                return _response("echo", _string_field(payload, 1))
            if kind == "flush":
                return _response("flush", b"")
            if kind == "info":
                info = self.application.info()
                return _response(
                    "info",
                    _fields(
                        _string(1, info.data),
                        _string(2, info.version),
                        _varint_field(3, info.app_version),
                        _varint_field(4, info.last_block_height),
                        _bytes_field(5, info.last_block_app_hash),
                    ),
                )
            if kind == "init_chain":
                initial_height = _int_field(payload, 6, default=0)
                initialized = self.application.init_chain(
                    genesis_time=_timestamp_field(payload, 1),
                    initial_height=initial_height,
                )
                if initialized.code != "ok":
                    raise ABCIWireError(initialized.log or "ABCI chain initialization failed")
                return _response("init_chain", _bytes_field(3, self.application.commit().data))
            if kind == "check_tx":
                check_tx_type = _int_field(payload, 2, default=0)
                if check_tx_type not in {0, 1}:
                    raise ABCIWireError("ABCI CheckTx type is invalid")
                result = self.application.check_transaction(
                    _bytes_field_value(payload, 1),
                    recheck=check_tx_type == 1,
                )
                return _response("check_tx", _result_message(result))
            if kind == "query":
                query = self.application.query(
                    data=_bytes_field_value(payload, 1, default=b""),
                    path=_string_field(payload, 2, default=""),
                    height=_int_field(payload, 3, default=0) or None,
                    prove=bool(_int_field(payload, 4, default=0)),
                )
                return _response(
                    "query",
                    _fields(
                        _bytes_field(6, query.key),
                        _bytes_field(7, query.value),
                        _varint_field(5, query.index),
                        _varint_field(9, query.height),
                    ),
                )
            if kind == "prepare_proposal":
                return _response(
                    "prepare_proposal",
                    _repeated_bytes(1, self.application.prepare_proposal(
                        _repeated_bytes_value(payload, 2),
                        maximum_bytes=_int_field(payload, 1, default=0),
                    )),
                )
            if kind == "process_proposal":
                accepted = self.application.process_proposal(_repeated_bytes_value(payload, 1)).code == "ok"
                return _response("process_proposal", _varint_field(1, 1 if accepted else 2))
            if kind == "finalize_block":
                result, tx_results = self.application.finalize_block_with_results(
                    block_height=_int_field(payload, 5),
                    block_hash=_bytes_field_value(payload, 4),
                    txs=_repeated_bytes_value(payload, 1),
                    time=_timestamp_field(payload, 6),
                )
                return _response(
                    "finalize_block",
                    _fields(
                        *(_message_field(2, _result_message(item)) for item in tx_results),
                        *(
                            _message_field(3, _validator_update_message(item))
                            for item in result.validator_updates
                        ),
                        _bytes_field(5, self.application.preview_commit().data),
                    ),
                )
            if kind == "commit":
                self.application.commit()
                return _response("commit", b"")
            if kind == "list_snapshots":
                snapshots = (
                    _message_field(
                        1,
                        _fields(
                            _varint_field(1, snapshot.height),
                            _varint_field(2, snapshot.format),
                            _varint_field(3, snapshot.chunks),
                            _bytes_field(4, snapshot.hash),
                        ),
                    )
                    for snapshot in self.application.list_state_snapshots()
                )
                return _response("list_snapshots", _fields(*snapshots))
            if kind == "offer_snapshot":
                offered = _snapshot_from_offer(payload)
                status = self.application.offer_state_snapshot(offered)
                return _response("offer_snapshot", _varint_field(1, _OFFER_SNAPSHOT_STATUS[status]))
            if kind == "load_snapshot_chunk":
                chunk = self.application.load_state_snapshot_chunk(
                    height=_int_field(payload, 1),
                    format=_int_field(payload, 2),
                    # Proto3 omits a zero-valued scalar. CometBFT therefore
                    # omits `chunk` for the first snapshot chunk.
                    chunk=_int_field(payload, 3, default=0),
                )
                return _response("load_snapshot_chunk", _bytes_field(1, chunk))
            if kind == "apply_snapshot_chunk":
                status = self.application.apply_state_snapshot_chunk(
                    # Proto3 omits a zero-valued scalar. The first incoming
                    # chunk consequently has no `index` field on the wire.
                    index=_int_field(payload, 1, default=0),
                    chunk=_bytes_field_value(payload, 2),
                )
                return _response("apply_snapshot_chunk", _varint_field(1, _APPLY_SNAPSHOT_STATUS[status]))
            if kind == "extend_vote":
                return _response("extend_vote", b"")
            if kind == "verify_vote_extension":
                return _response("verify_vote_extension", _varint_field(1, 1))
            raise ABCIWireError("unsupported ABCI request")
        except (ABCIStateStoreError, ABCIWireError, ValueError, TypeError) as error:
            return _response("exception", _string(1, str(error)))


_REQUEST_FIELDS = {
    1: "echo", 2: "flush", 3: "info", 5: "init_chain", 6: "query", 8: "check_tx",
    11: "commit", 12: "list_snapshots", 13: "offer_snapshot", 14: "load_snapshot_chunk",
    15: "apply_snapshot_chunk", 16: "prepare_proposal", 17: "process_proposal",
    18: "extend_vote", 19: "verify_vote_extension", 20: "finalize_block",
}
_RESPONSE_FIELDS = {
    "exception": 1, "echo": 2, "flush": 3, "info": 4, "init_chain": 6, "query": 7,
    "check_tx": 9, "commit": 12, "list_snapshots": 13, "offer_snapshot": 14,
    "load_snapshot_chunk": 15, "apply_snapshot_chunk": 16, "prepare_proposal": 17,
    "process_proposal": 18, "extend_vote": 19, "verify_vote_extension": 20,
    "finalize_block": 21,
}
_CODE = {"ok": 0, "rejected": 1, "invalid": 2, "duplicate": 3, "expired": 4, "sequence": 5, "internal": 6}
_OFFER_SNAPSHOT_STATUS = {"accept": 1, "abort": 2, "reject": 3}
_APPLY_SNAPSHOT_STATUS = {"accept": 1, "abort": 2, "retry_snapshot": 4, "reject_snapshot": 5}


def _response(kind: str, payload: bytes) -> bytes:
    return _message_field(_RESPONSE_FIELDS[kind], payload)


def _snapshot_from_offer(payload: bytes) -> ABCIStateSnapshot:
    """Decode v0.38 RequestOfferSnapshot's snapshot plus the committed app hash."""
    snapshot_payload = _bytes_field_value(payload, 1)
    return ABCIStateSnapshot(
        height=_int_field(snapshot_payload, 1),
        format=_int_field(snapshot_payload, 2),
        chunks=_int_field(snapshot_payload, 3),
        hash=_bytes_field_value(snapshot_payload, 4),
        app_hash=_bytes_field_value(payload, 2),
    )


def _result_message(result: ABCIResult) -> bytes:
    return _fields(
        _varint_field(1, _CODE[result.code]),
        _bytes_field(2, result.data),
        _string(3, result.log),
        _varint_field(5, result.gas_wanted),
        _varint_field(6, result.gas_used),
        _string(8, result.codespace),
    )


def _validator_update_message(update: dict) -> bytes:
    """Encode one CometBFT ``ValidatorUpdate`` protobuf message."""
    public_key = update.get("public_key")
    if not isinstance(public_key, str) or not public_key.startswith("ed25519:"):
        raise ABCIWireError("validator update public key is invalid")
    try:
        public_key_bytes = base64.b64decode(
            public_key.removeprefix("ed25519:"),
            validate=True,
        )
    except (ValueError, binascii.Error) as error:
        raise ABCIWireError("validator update public key is invalid") from error
    if len(public_key_bytes) != 32:
        raise ABCIWireError("validator update public key must contain 32 bytes")

    power = update.get("power")
    if isinstance(power, bool) or not isinstance(power, int) or power < 0:
        raise ABCIWireError("validator update voting power is invalid")
    public_key_message = _fields(_bytes_field(1, public_key_bytes))
    return _fields(
        _message_field(1, public_key_message),
        _varint_field(2, power),
    )


def _read_frame(connection: socket.socket, maximum_size: int) -> bytes:
    length = _read_varint(connection)
    if length > maximum_size:
        raise ABCIWireError("ABCI frame exceeds configured limit")
    return _read_exact(connection, length)


def _write_frame(connection: socket.socket, payload: bytes) -> None:
    connection.sendall(_varint(payload.__len__()) + payload)


def _read_exact(connection: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            raise EOFError
        data.extend(chunk)
    return bytes(data)


def _read_varint(connection: socket.socket) -> int:
    value = 0
    for offset in range(10):
        chunk = connection.recv(1)
        if not chunk:
            raise EOFError
        byte = chunk[0]
        value |= (byte & 0x7F) << (offset * 7)
        if not byte & 0x80:
            return value
    raise ABCIWireError("ABCI frame length is invalid")


def _oneof(payload: bytes, mapping: dict[int, str]) -> tuple[str, bytes]:
    matches = [(number, value) for number, wire, value in _fields_value(payload) if number in mapping and wire == 2]
    if len(matches) != 1:
        raise ABCIWireError("ABCI request oneof is invalid")
    number, value = matches[0]
    return mapping[number], value


def _fields_value(payload: bytes) -> list[tuple[int, int, bytes | int]]:
    fields: list[tuple[int, int, bytes | int]] = []
    offset = 0
    while offset < len(payload):
        key, offset = _varint_from(payload, offset)
        number, wire = key >> 3, key & 7
        if number < 1:
            raise ABCIWireError("ABCI protobuf field number is invalid")
        if wire == 0:
            value, offset = _varint_from(payload, offset)
        elif wire == 2:
            length, offset = _varint_from(payload, offset)
            end = offset + length
            if end > len(payload):
                raise ABCIWireError("ABCI protobuf field is truncated")
            value, offset = payload[offset:end], end
        elif wire == 1:
            end = offset + 8
            if end > len(payload):
                raise ABCIWireError("ABCI protobuf field is truncated")
            value, offset = payload[offset:end], end
        elif wire == 5:
            end = offset + 4
            if end > len(payload):
                raise ABCIWireError("ABCI protobuf field is truncated")
            value, offset = payload[offset:end], end
        else:
            raise ABCIWireError("ABCI protobuf wire type is unsupported")
        fields.append((number, wire, value))
    return fields


def _bytes_field_value(payload: bytes, number: int, *, default: bytes | None = None) -> bytes:
    values = [value for field, wire, value in _fields_value(payload) if field == number and wire == 2]
    if not values:
        if default is None:
            raise ABCIWireError("required ABCI bytes field is missing")
        return default
    value = values[-1]
    if not isinstance(value, bytes):
        raise ABCIWireError("ABCI bytes field is invalid")
    return value


def _repeated_bytes_value(payload: bytes, number: int) -> list[bytes]:
    return [
        value
        for field, wire, value in _fields_value(payload)
        if field == number and wire == 2 and isinstance(value, bytes)
    ]


def _string_field(payload: bytes, number: int, *, default: str | None = None) -> str:
    try:
        default_bytes = None if default is None else default.encode()
        return _bytes_field_value(payload, number, default=default_bytes).decode("utf-8")
    except UnicodeDecodeError as error:
        raise ABCIWireError("ABCI string field is invalid") from error


def _int_field(payload: bytes, number: int, *, default: int | None = None) -> int:
    values = [value for field, wire, value in _fields_value(payload) if field == number and wire == 0]
    if not values:
        if default is None:
            raise ABCIWireError("required ABCI integer field is missing")
        return default
    value = values[-1]
    if not isinstance(value, int):
        raise ABCIWireError("ABCI integer field is invalid")
    return value if value < 1 << 63 else value - (1 << 64)


def _timestamp_field(payload: bytes, number: int) -> str | None:
    values = [value for field, wire, value in _fields_value(payload) if field == number and wire == 2]
    if not values:
        return None
    value = values[-1]
    if not isinstance(value, bytes):
        raise ABCIWireError("ABCI timestamp field is invalid")
    seconds = _int_field(value, 1, default=0)
    nanos = _int_field(value, 2, default=0)
    if not 0 <= nanos < 1_000_000_000:
        raise ABCIWireError("ABCI timestamp nanoseconds are invalid")
    return datetime.fromtimestamp(seconds + nanos / 1_000_000_000, UTC).isoformat().replace("+00:00", "Z")


def _varint_from(payload: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(payload):
            raise ABCIWireError("ABCI protobuf varint is truncated")
        byte = payload[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
    raise ABCIWireError("ABCI protobuf varint is invalid")


def _varint(value: int) -> bytes:
    if value < 0:
        value &= (1 << 64) - 1
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _varint_field(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _bytes_field(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _message_field(number: int, value: bytes) -> bytes:
    return _bytes_field(number, value)


def _string(number: int, value: str) -> bytes:
    return _bytes_field(number, value.encode("utf-8"))


def _repeated_bytes(number: int, values: Iterable[bytes]) -> bytes:
    return b"".join(_bytes_field(number, value) for value in values)


def _fields(*items: bytes) -> bytes:
    return b"".join(item for item in items if item)
