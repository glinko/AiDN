"""ABCI v0.38 socket interoperability tests without a Python protobuf runtime."""

from __future__ import annotations

import json
import socket

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.abci_socket import (
    AIDNABCISocketServer,
    _bytes_field,
    _fields,
    _fields_value,
    _message_field,
    _read_frame,
    _varint_field,
    _write_frame,
)
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService


def _application() -> AIDNABCIApplication:
    return AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
    )


def _field_values(payload: bytes, field_number: int) -> list[bytes | int]:
    return [value for number, _, value in _fields_value(payload) if number == field_number]


def _request(connection: socket.socket, field_number: int, payload: bytes = b"") -> bytes:
    _write_frame(connection, _message_field(field_number, payload))
    response = _read_frame(connection, 1_048_576)
    fields = _fields_value(response)
    assert len(fields) == 1
    number, wire, value = fields[0]
    assert wire == 2
    assert isinstance(value, bytes)
    assert number != 1, value.decode("utf-8")
    return value


def _operation_bytes() -> bytes:
    envelope = LedgerOperationEnvelope(
        operation_type="REGISTRY_UPSERT",
        origin_type="protocol",
        created_at="2030-01-01T00:00:00Z",
        payload={"abci_socket": True},
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def test_abci_socket_handles_real_v038_request_lifecycle():
    application = _application()
    server = AIDNABCISocketServer(application=application, port=0)
    server.start()
    tx = _operation_bytes()

    try:
        with socket.create_connection(("127.0.0.1", server.port), timeout=2) as connection:
            info = _request(connection, 3)
            assert _field_values(info, 1) == [b"AiDN Consensus Application"]
            assert _field_values(info, 4) == [0]

            query = _request(connection, 6, _bytes_field(2, b"state/app_hash"))
            assert _field_values(query, 6) == [b"app_hash"]
            assert len(_field_values(query, 7)[0]) == 32

            check = _request(connection, 8, _bytes_field(1, tx))
            assert _field_values(check, 1) == [0]

            prepared = _request(
                connection,
                16,
                _fields(_varint_field(1, 1_000_000), _bytes_field(2, tx)),
            )
            assert _field_values(prepared, 1) == [tx]

            processed = _request(connection, 17, _bytes_field(1, tx))
            assert _field_values(processed, 1) == [1]

            finalized = _request(
                connection,
                20,
                _fields(_bytes_field(1, tx), _bytes_field(4, b"A" * 32), _varint_field(5, 1)),
            )
            tx_result = _field_values(finalized, 2)
            assert len(tx_result) == 1
            assert isinstance(tx_result[0], bytes)
            assert _field_values(tx_result[0], 1) == [0]
            assert len(_field_values(finalized, 5)[0]) == 32

            committed = _request(connection, 11)
            assert committed == b""
    finally:
        server.stop()


def test_abci_socket_returns_exception_for_unknown_request():
    server = AIDNABCISocketServer(application=_application(), port=0)
    server.start()
    try:
        with socket.create_connection(("127.0.0.1", server.port), timeout=2) as connection:
            _write_frame(connection, _message_field(99, b""))
            response = _read_frame(connection, 1_048_576)
            fields = _fields_value(response)
            assert fields[0][0] == 1
    finally:
        server.stop()
