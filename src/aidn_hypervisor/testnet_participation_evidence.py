"""Canonical evidence boundary for Testnet participation rewards.

Registry advertisements remain useful liveness hints but are mutable and not
reward evidence. This store accepts only heartbeats signed by the Wallet
identity canonically bound to a Node through ``OPERATOR_WALLET_BIND`` and
already marked final by the calling Registry/Consensus bridge.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.testnet_participation import (
    TestnetHeartbeatEvidence,
    TestnetParticipantEnrollment,
    TestnetParticipationProgram,
    _timestamp,
)


class TestnetParticipationEvidenceStore:
    """Durable finalized enrollment and signed heartbeat evidence."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level="IMMEDIATE")
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS participation_enrollments (
                    node_id TEXT PRIMARY KEY,
                    binding_operation_id TEXT NOT NULL UNIQUE,
                    public_key TEXT NOT NULL,
                    enrollment_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS participation_heartbeats (
                    evidence_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    FOREIGN KEY (node_id) REFERENCES participation_enrollments(node_id)
                );
                CREATE INDEX IF NOT EXISTS participation_heartbeat_period_idx
                    ON participation_heartbeats(observed_at, node_id);
                """
            )

    def enroll_from_finalized_binding(
        self,
        ledger: LedgerOperationService,
        *,
        node_id: str,
        reward_wallet: str,
        registered_epoch: int,
        banned: bool = False,
    ) -> TestnetParticipantEnrollment:
        """Enroll a Node from its existing canonical Wallet binding."""

        binding = ledger.canonical_operator_wallet_binding(node_id)
        if binding is None:
            raise ValueError("PARTICIPATION_NODE_BINDING_NOT_FINALIZED")
        enrollment = TestnetParticipantEnrollment(
            node_id=node_id,
            owner_wallet=str(binding["wallet_id"]),
            reward_wallet=reward_wallet,
            registered_at=str(binding["registered_at"]),
            registered_epoch=registered_epoch,
            node_identity_verified=True,
            registration_finalized=True,
            banned=banned,
        )
        self.register_enrollment(
            enrollment,
            public_key=str(binding["public_key"]),
            binding_operation_id=str(binding["operation_id"]),
        )
        return enrollment

    def register_enrollment(
        self,
        enrollment: TestnetParticipantEnrollment,
        *,
        public_key: str,
        binding_operation_id: str,
    ) -> None:
        """Persist one finalized Node Identity enrollment exactly once."""

        if not public_key.startswith("ed25519:"):
            raise ValueError("PARTICIPATION_NODE_PUBLIC_KEY_INVALID")
        try:
            if len(bytes.fromhex(public_key.removeprefix("ed25519:"))) != 32:
                raise ValueError("PARTICIPATION_NODE_PUBLIC_KEY_INVALID")
        except ValueError as exc:
            raise ValueError("PARTICIPATION_NODE_PUBLIC_KEY_INVALID") from exc
        if not binding_operation_id.strip():
            raise ValueError("PARTICIPATION_NODE_BINDING_OPERATION_REQUIRED")
        encoded = json.dumps(
            enrollment.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM participation_enrollments WHERE node_id = ?",
                (enrollment.node_id,),
            ).fetchone()
            if row is not None:
                if (
                    row["binding_operation_id"] == binding_operation_id
                    and row["public_key"] == public_key
                    and row["enrollment_json"] == encoded
                ):
                    return
                raise ValueError("PARTICIPATION_ENROLLMENT_CONFLICT")
            connection.execute(
                """
                INSERT INTO participation_enrollments (
                    node_id, binding_operation_id, public_key, enrollment_json
                ) VALUES (?, ?, ?, ?)
                """,
                (enrollment.node_id, binding_operation_id, public_key, encoded),
            )

    def record_finalized_heartbeat(
        self,
        heartbeat: TestnetHeartbeatEvidence,
    ) -> TestnetHeartbeatEvidence:
        """Verify a Node-bound signature, then persist immutable evidence."""

        if not heartbeat.finalized:
            raise ValueError("PARTICIPATION_HEARTBEAT_NOT_FINALIZED")
        if not heartbeat.identity_signature.startswith("ed25519:"):
            raise ValueError("PARTICIPATION_HEARTBEAT_SIGNATURE_REQUIRED")
        if not heartbeat.verify_integrity():
            raise ValueError("PARTICIPATION_HEARTBEAT_INTEGRITY_INVALID")
        with self._connect() as connection:
            enrollment = connection.execute(
                "SELECT public_key FROM participation_enrollments WHERE node_id = ?",
                (heartbeat.node_id,),
            ).fetchone()
            if enrollment is None:
                raise ValueError("PARTICIPATION_HEARTBEAT_NODE_NOT_ENROLLED")
            try:
                public_key = bytes.fromhex(str(enrollment["public_key"])[8:])
                signature = bytes.fromhex(heartbeat.identity_signature.removeprefix("ed25519:"))
                Ed25519PublicKey.from_public_bytes(public_key).verify(
                    signature,
                    heartbeat.signing_bytes(),
                )
            except (ValueError, InvalidSignature) as exc:
                raise ValueError("PARTICIPATION_HEARTBEAT_SIGNATURE_INVALID") from exc
            verified = heartbeat.model_copy(update={"identity_signature_verified": True})
            encoded = json.dumps(
                verified.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            )
            existing = connection.execute(
                "SELECT evidence_hash, evidence_json FROM participation_heartbeats WHERE evidence_id = ?",
                (verified.evidence_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["evidence_hash"] == verified.evidence_hash
                    and existing["evidence_json"] == encoded
                ):
                    return verified
                raise ValueError("PARTICIPATION_HEARTBEAT_ID_CONFLICT")
            connection.execute(
                """
                INSERT INTO participation_heartbeats (
                    evidence_id, node_id, observed_at, evidence_hash, evidence_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    verified.evidence_id,
                    verified.node_id,
                    verified.observed_at,
                    verified.evidence_hash,
                    encoded,
                ),
            )
        return verified

    def settlement_inputs(
        self,
        program: TestnetParticipationProgram,
        *,
        period_start: str,
    ) -> tuple[list[TestnetParticipantEnrollment], list[TestnetHeartbeatEvidence]]:
        """Return exactly the finalized evidence visible for one daily period."""

        start = _timestamp(period_start, field_name="period_start")
        end = start.timestamp() + program.settlement_period_seconds
        with self._connect() as connection:
            enrollment_rows = connection.execute(
                "SELECT enrollment_json FROM participation_enrollments ORDER BY node_id"
            ).fetchall()
            heartbeat_rows = connection.execute(
                "SELECT evidence_json FROM participation_heartbeats ORDER BY evidence_id"
            ).fetchall()
        enrollments = [
            TestnetParticipantEnrollment.model_validate_json(str(row["enrollment_json"]))
            for row in enrollment_rows
        ]
        heartbeats = [
            TestnetHeartbeatEvidence.model_validate_json(str(row["evidence_json"]))
            for row in heartbeat_rows
            if start.timestamp()
            <= _timestamp(
                TestnetHeartbeatEvidence.model_validate_json(
                    str(row["evidence_json"])
                ).observed_at,
                field_name="observed_at",
            ).timestamp()
            < end
        ]
        return enrollments, heartbeats

    def snapshot_enrollments(self) -> Iterable[TestnetParticipantEnrollment]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT enrollment_json FROM participation_enrollments ORDER BY node_id"
            ).fetchall()
        return [
            TestnetParticipantEnrollment.model_validate_json(str(row["enrollment_json"]))
            for row in rows
        ]


__all__ = ["TestnetParticipationEvidenceStore"]
