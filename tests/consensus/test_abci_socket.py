"""ABCI v0.38 socket interoperability tests without a Python protobuf runtime."""

from __future__ import annotations

import base64
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
from aidn_hypervisor.consensus.state_store import ABCIStateStore
from aidn_hypervisor.consensus.validator_schedule import compute_validator_set_hash
from aidn_hypervisor.ledger.service import LedgerOperationService

PUBLIC_KEY = bytes(range(32))
PUBLIC_KEY_TEXT = "ed25519:" + base64.b64encode(PUBLIC_KEY).decode("ascii")


def _application(state_store: ABCIStateStore | None = None) -> AIDNABCIApplication:
    return AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=state_store,
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


def _protocol_operation(operation_type: str, payload: dict, target_epoch: str) -> bytes:
    envelope = LedgerOperationEnvelope(
        operation_type=operation_type,
        origin_type="protocol",
        initiator_id="epoch-engine",
        created_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-02T00:00:00Z",
        target_epoch=target_epoch,
        payload=payload,
        evidence_references=["sha256:eligibility"],
        signatures=["ed25519:epoch-engine"],
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def _validator_schedule_bytes() -> bytes:
    additions = [
        {
            "node_id": "node-1",
            "operator_id": "operator-1",
            "consensus_address": "sha256:node-1",
            "consensus_public_key": PUBLIC_KEY_TEXT,
            "stake": 500_000_000_000,
            "voting_power": 1,
        }
    ]
    return _protocol_operation(
        "CONSENSUS_VALIDATOR_SET_UPDATE",
        {
            "activation_epoch": 2,
            "validator_additions": additions,
            "validator_removals": [],
            "voting_power_updates": [],
            "validator_set_hash": compute_validator_set_hash(additions),
            "eligibility_evidence_root": "sha256:eligibility-2",
        },
        "2",
    )


def _epoch_transition_bytes() -> bytes:
    return _protocol_operation(
        "EPOCH_TRANSITION",
        {
            "closing_epoch": 1,
            "opening_epoch": 2,
            "closing_state_root": "sha256:closing-1",
            "epoch_task_result_root": "sha256:tasks-1",
            "eligibility_snapshot_root": "sha256:eligibility-snapshot-1",
            "reward_calculation_root": "sha256:rewards-1",
            "next_protocol_parameters_hash": "sha256:params-2",
            "pool_budgets": {"registry": 0},
            "pool_budget_references": {"registry": "epoch:1:registry"},
        },
        "1",
    )


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

            rechecked = _request(
                connection,
                8,
                _fields(_bytes_field(1, tx), _varint_field(2, 1)),
            )
            assert _field_values(rechecked, 1) == [0]

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


def test_abci_socket_emits_cometbft_validator_updates_after_epoch_transition():
    application = _application()
    server = AIDNABCISocketServer(application=application, port=0)
    server.start()

    try:
        with socket.create_connection(("127.0.0.1", server.port), timeout=2) as connection:
            schedule = _validator_schedule_bytes()
            _request(
                connection,
                20,
                _fields(
                    _bytes_field(1, schedule),
                    _bytes_field(4, b"A" * 32),
                    _varint_field(5, 1),
                ),
            )

            finalized = _request(
                connection,
                20,
                _fields(
                    _bytes_field(1, _epoch_transition_bytes()),
                    _bytes_field(4, b"B" * 32),
                    _varint_field(5, 2),
                ),
            )
            updates = _field_values(finalized, 3)
            assert len(updates) == 1
            validator_update = updates[0]
            assert isinstance(validator_update, bytes)
            public_key_message = _field_values(validator_update, 1)[0]
            assert isinstance(public_key_message, bytes)
            assert _field_values(public_key_message, 1) == [PUBLIC_KEY]
            assert _field_values(validator_update, 2) == [1]
    finally:
        server.stop()


def test_abci_socket_exposes_durable_state_sync_snapshots(tmp_path):
    application = _application(ABCIStateStore(tmp_path / "abci", chunk_size=64))
    application.finalize_block(block_height=1, block_hash=b"S" * 32, txs=[])
    server = AIDNABCISocketServer(application=application, port=0)
    server.start()

    try:
        with socket.create_connection(("127.0.0.1", server.port), timeout=2) as connection:
            listed = _request(connection, 12)
            snapshots = _field_values(listed, 1)
            assert len(snapshots) == 1
            assert isinstance(snapshots[0], bytes)
            snapshot = snapshots[0]
            height = _field_values(snapshot, 1)[0]
            format_value = _field_values(snapshot, 2)[0]
            assert height == 1
            assert format_value == 1

            chunk = _request(
                connection,
                14,
                _fields(
                    _varint_field(1, height),
                    _varint_field(2, format_value),
                ),
            )
            assert _field_values(chunk, 1)[0]
    finally:
        server.stop()


def test_abci_socket_applies_verified_state_sync_snapshot(tmp_path):
    source_store = ABCIStateStore(tmp_path / "source", chunk_size=64)
    source = _application(source_store)
    source.finalize_block(block_height=1, block_hash=b"T" * 32, txs=[])
    snapshot = source.list_state_snapshots()[0]
    destination = _application(ABCIStateStore(tmp_path / "destination", chunk_size=64))
    server = AIDNABCISocketServer(application=destination, port=0)
    server.start()

    try:
        # Snapshot restore includes a durable write on the final chunk and is
        # materially slower under coverage instrumentation on Windows.
        with socket.create_connection(("127.0.0.1", server.port), timeout=10) as connection:
            offered = _request(
                connection,
                13,
                _fields(
                    _message_field(
                        1,
                        _fields(
                            _varint_field(1, snapshot.height),
                            _varint_field(2, snapshot.format),
                            _varint_field(3, snapshot.chunks),
                            _bytes_field(4, snapshot.hash),
                        ),
                    ),
                    _bytes_field(2, snapshot.app_hash),
                ),
            )
            assert _field_values(offered, 1) == [1]

            for index in range(snapshot.chunks):
                apply_fields = [
                    _bytes_field(
                        2,
                        source.load_state_snapshot_chunk(
                            height=snapshot.height,
                            format=snapshot.format,
                            chunk=index,
                        ),
                    ),
                ]
                if index:
                    apply_fields.insert(0, _varint_field(1, index))
                applied = _request(
                    connection,
                    15,
                    _fields(*apply_fields),
                )
                assert _field_values(applied, 1) == [1]
    finally:
        server.stop()

    assert destination.info().last_block_height == 1
    assert destination.info().last_block_app_hash == source.info().last_block_app_hash
