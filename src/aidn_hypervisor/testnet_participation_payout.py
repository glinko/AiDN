"""Durable, ordered submission for testnet participation treasury payouts.

The calculator deliberately has no side effects.  This worker owns only the
operational boundary after a settlement was finalized: persist the exact
signed Wallet transfers, submit one treasury sequence at a time, and reconcile
the same operation after a timeout or restart.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.testnet_participation import (
    TestnetParticipationSettlement,
    TestnetParticipationTransferBatch,
    build_testnet_participation_transfer_batch,
)


class ParticipationTransferSubmission(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(min_length=1)
    status: Literal["FINALIZED", "ADMITTED", "REJECTED", "UNKNOWN"]
    detail: str | None = None


class ParticipationTransferSubmitter(Protocol):
    """Network boundary for the payout worker."""

    def next_sender_sequence(self, wallet_id: str) -> int:
        """Return the next finalized sequence for the incentive treasury."""

    def submit_transfer(
        self, envelope: LedgerOperationEnvelope
    ) -> ParticipationTransferSubmission:
        """Submit one exact signed transfer."""

    def reconcile_transfer(
        self, envelope: LedgerOperationEnvelope
    ) -> ParticipationTransferSubmission:
        """Reconcile/rebroadcast the same operation without changing identity."""

    def treasury_balance_q_atoms(self, wallet_id: str) -> int | None:
        """Return canonical treasury balance when available."""


class TestnetParticipationPayoutStore:
    """SQLite persistence for idempotent, in-order payout batches."""

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
                CREATE TABLE IF NOT EXISTS participation_payout_batches (
                    settlement_id TEXT PRIMARY KEY,
                    settlement_hash TEXT NOT NULL,
                    batch_hash TEXT NOT NULL UNIQUE,
                    batch_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finalized_at TEXT,
                    detail TEXT
                );
                CREATE TABLE IF NOT EXISTS participation_payout_transfers (
                    operation_id TEXT PRIMARY KEY,
                    settlement_id TEXT NOT NULL,
                    sender_sequence INTEGER NOT NULL,
                    envelope_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    detail TEXT,
                    finalized_at TEXT,
                    FOREIGN KEY (settlement_id)
                        REFERENCES participation_payout_batches(settlement_id),
                    UNIQUE (settlement_id, sender_sequence)
                );
                CREATE INDEX IF NOT EXISTS participation_payout_next_idx
                    ON participation_payout_transfers(settlement_id, sender_sequence, status);
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def get_batch(self, settlement_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM participation_payout_batches WHERE settlement_id = ?",
                    (settlement_id,),
                ).fetchone()
            )

    def create_batch(
        self, batch: TestnetParticipationTransferBatch, *, created_at: str
    ) -> dict[str, Any]:
        with self._connect() as connection:
            existing = self._row(
                connection.execute(
                    "SELECT * FROM participation_payout_batches WHERE settlement_id = ?",
                    (batch.settlement_id,),
                ).fetchone()
            )
            if existing is not None:
                if existing["batch_hash"] != batch.batch_hash:
                    raise ValueError("PARTICIPATION_PAYOUT_SETTLEMENT_CONFLICT")
                return existing
            status = "FINALIZED" if not batch.transfers else "PENDING"
            connection.execute(
                """
                INSERT INTO participation_payout_batches (
                    settlement_id, settlement_hash, batch_hash, batch_json,
                    status, created_at, finalized_at, detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    batch.settlement_id,
                    batch.settlement_hash,
                    batch.batch_hash,
                    json.dumps(batch.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
                    status,
                    created_at,
                    created_at if status == "FINALIZED" else None,
                ),
            )
            for transfer in batch.transfers:
                connection.execute(
                    """
                    INSERT INTO participation_payout_transfers (
                        operation_id, settlement_id, sender_sequence,
                        envelope_json, status
                    ) VALUES (?, ?, ?, ?, 'PENDING')
                    """,
                    (
                        transfer.operation_id,
                        batch.settlement_id,
                        transfer.sender_sequence,
                        json.dumps(transfer.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
                    ),
                )
        created = self.get_batch(batch.settlement_id)
        if created is None:
            raise RuntimeError("participation payout batch was not persisted")
        return created

    def next_transfer(self, settlement_id: str) -> dict[str, Any] | None:
        """Return the first transfer that blocks the treasury sequence."""

        with self._connect() as connection:
            return self._row(
                connection.execute(
                    """
                    SELECT * FROM participation_payout_transfers
                    WHERE settlement_id = ? AND status != 'FINALIZED'
                    ORDER BY sender_sequence ASC LIMIT 1
                    """,
                    (settlement_id,),
                ).fetchone()
            )

    def update_transfer(
        self,
        *,
        operation_id: str,
        status: Literal["PENDING", "FINALIZED", "REJECTED"],
        detail: str | None,
        finalized_at: str | None,
        increment_attempts: bool,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            if increment_attempts:
                connection.execute(
                    """
                    UPDATE participation_payout_transfers
                    SET status = ?, detail = ?, finalized_at = ?, attempts = attempts + 1
                    WHERE operation_id = ? AND status != 'FINALIZED'
                    """,
                    (status, detail, finalized_at, operation_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE participation_payout_transfers
                    SET status = ?, detail = ?, finalized_at = ?
                    WHERE operation_id = ? AND status != 'FINALIZED'
                    """,
                    (status, detail, finalized_at, operation_id),
                )
            row = self._row(
                connection.execute(
                    "SELECT * FROM participation_payout_transfers WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
            )
        if row is None:
            raise RuntimeError("participation payout transfer disappeared")
        return row

    def finalize_batch_if_complete(
        self, settlement_id: str, *, finalized_at: str
    ) -> bool:
        with self._connect() as connection:
            unfinished = connection.execute(
                """
                SELECT 1 FROM participation_payout_transfers
                WHERE settlement_id = ? AND status != 'FINALIZED' LIMIT 1
                """,
                (settlement_id,),
            ).fetchone()
            if unfinished is not None:
                return False
            connection.execute(
                """
                UPDATE participation_payout_batches
                SET status = 'FINALIZED', finalized_at = ?, detail = NULL
                WHERE settlement_id = ? AND status != 'FINALIZED'
                """,
                (finalized_at, settlement_id),
            )
            return True

    def block_batch(self, settlement_id: str, *, detail: str) -> None:
        """Stop a batch after a deterministic rejection without skipping a nonce."""

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE participation_payout_batches
                SET status = 'BLOCKED', detail = ?
                WHERE settlement_id = ? AND status = 'PENDING'
                """,
                (detail, settlement_id),
            )


class TestnetParticipationPayoutService:
    """Persist, submit and reconcile a daily settlement in treasury order."""

    def __init__(
        self,
        *,
        treasury_wallet: str,
        signer: Callable[[bytes], str],
        store: TestnetParticipationPayoutStore,
        submitter: ParticipationTransferSubmitter,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not treasury_wallet.strip():
            raise ValueError("PARTICIPATION_TREASURY_WALLET_REQUIRED")
        self.treasury_wallet = treasury_wallet
        self.signer = signer
        self.store = store
        self.submitter = submitter
        self._now = now or (lambda: datetime.now(UTC))

    def schedule(
        self, settlement: TestnetParticipationSettlement
    ) -> TestnetParticipationTransferBatch:
        """Persist one deterministic batch before any transfer is submitted."""

        existing = self.store.get_batch(settlement.settlement_id)
        if existing is not None:
            return TestnetParticipationTransferBatch.model_validate_json(
                str(existing["batch_json"])
            )
        first_sequence = self.submitter.next_sender_sequence(self.treasury_wallet)
        available_balance = self.submitter.treasury_balance_q_atoms(self.treasury_wallet)
        batch = build_testnet_participation_transfer_batch(
            settlement,
            treasury_wallet=self.treasury_wallet,
            first_sender_sequence=first_sequence,
            signer=self.signer,
            available_treasury_q_atoms=available_balance,
        )
        self.store.create_batch(batch, created_at=self._now().isoformat())
        return batch

    def process_next(self, settlement_id: str, *, reconcile: bool = False) -> dict[str, Any] | None:
        """Submit or reconcile exactly one blocking treasury transfer.

        A non-final response remains ``PENDING``. No later sender sequence is
        submitted until it becomes final, preventing sequence gaps after a
        timeout or a process restart.
        """

        batch = self.store.get_batch(settlement_id)
        if batch is None:
            raise ValueError("PARTICIPATION_PAYOUT_SETTLEMENT_UNKNOWN")
        if batch["status"] in {"FINALIZED", "BLOCKED"}:
            return None
        transfer = self.store.next_transfer(settlement_id)
        if transfer is None:
            self.store.finalize_batch_if_complete(
                settlement_id, finalized_at=self._now().isoformat()
            )
            return None
        envelope = LedgerOperationEnvelope.model_validate_json(str(transfer["envelope_json"]))
        result = (
            self.submitter.reconcile_transfer(envelope)
            if reconcile
            else self.submitter.submit_transfer(envelope)
        )
        if result.operation_id != envelope.operation_id:
            raise ValueError("PARTICIPATION_PAYOUT_OPERATION_ID_MISMATCH")
        if result.status == "FINALIZED":
            updated = self.store.update_transfer(
                operation_id=envelope.operation_id,
                status="FINALIZED",
                detail=result.detail,
                finalized_at=self._now().isoformat(),
                increment_attempts=True,
            )
            self.store.finalize_batch_if_complete(
                settlement_id, finalized_at=self._now().isoformat()
            )
            return updated
        updated = self.store.update_transfer(
            operation_id=envelope.operation_id,
            status="REJECTED" if result.status == "REJECTED" else "PENDING",
            detail=result.detail or result.status,
            finalized_at=None,
            increment_attempts=True,
        )
        if result.status == "REJECTED":
            self.store.block_batch(
                settlement_id,
                detail=result.detail or "PARTICIPATION_PAYOUT_TRANSFER_REJECTED",
            )
        return updated


__all__ = [
    "ParticipationTransferSubmission",
    "ParticipationTransferSubmitter",
    "TestnetParticipationPayoutService",
    "TestnetParticipationPayoutStore",
]
