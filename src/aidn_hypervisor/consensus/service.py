"""RFC-0047 §3 — Consensus Service as an optional Hypervisor service."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.cometbft import cometbft_transaction_hash
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.state_store import ABCIStateStore


class ConsensusMode(str, Enum):
    VALIDATOR = "validator"
    NON_VALIDATOR = "non_validator"
    DISABLED = "disabled"


class SubmissionStatus(str, Enum):
    PENDING = "pending"
    ADMITTED = "admitted"
    INCLUDED = "included"
    FINALIZED = "finalized"
    FAILED = "failed"


@dataclass
class ConsensusServiceConfig:
    """Configuration for ConsensusService."""
    node_id: str = "local-node"
    mode: ConsensusMode = ConsensusMode.NON_VALIDATOR
    cometbft_endpoint: str = "tcp://localhost:26657"
    validator_pubkey: str = ""
    chain_id: str = "aidn-localnet-1"
    gas_limit: int = 1_000_000
    max_mempool_size: int = 1000
    submission_timeout_seconds: float = 30.0
    retry_interval_seconds: float = 5.0
    max_retries: int = 3
    abci_state_path: str | None = None
    abci_listen_host: str = "127.0.0.1"
    abci_listen_port: int = 26658
    abci_maximum_message_size: int = 1_048_576


@dataclass
class SubmissionRecord:
    """Tracks the lifecycle of a submitted operation."""
    operation_id: str
    status: SubmissionStatus = SubmissionStatus.PENDING
    submitted_at: float = 0.0
    admitted_at: float | None = None
    included_at: float | None = None
    finalized_at: float | None = None
    block_height: int | None = None
    transaction_hash: str | None = None
    retry_count: int = 0
    error: str | None = None


class ConsensusService:
    """
    RFC-0047 §3 — Consensus Service as an optional Hypervisor service.

    Two modes:
    - Validator: participates in block proposal and voting
    - Non-validator: submits transactions and monitors finalization

    When disabled, operations are processed locally without consensus.
    """

    def __init__(
        self,
        config: ConsensusServiceConfig,
        abci_app: AIDNABCIApplication | None = None,
        *,
        time_now: Callable[[], float] | None = None,
    ):
        self.config = config
        self.abci = abci_app
        self._abci_socket_server = None
        self._time_now = time_now or time.monotonic

        # Submission tracking
        self._submissions: dict[str, SubmissionRecord] = {}
        self._finalized_operation_ids: set[str] = set()

        # Validator state
        self._validator_signing_key = config.validator_pubkey
        self._participation_count = 0
        self._missed_blocks = 0
        self._blocks_proposed = 0

        # Metrics
        self._total_submitted = 0
        self._total_finalized = 0
        self._total_failed = 0

    @property
    def is_validator(self) -> bool:
        return self.config.mode == ConsensusMode.VALIDATOR

    @property
    def is_enabled(self) -> bool:
        return self.config.mode != ConsensusMode.DISABLED

    # ---- Submission ----

    def submit_operation(self, envelope: LedgerOperationEnvelope) -> SubmissionRecord:
        """
        RFC-0047 §28 — Submit a signed Ledger Operation to consensus.

        For non-validators: sends to CometBFT mempool.
        For validators: includes in next proposal.
        """
        transaction_bytes = self._serialize_envelope(envelope)
        transaction_hash = cometbft_transaction_hash(transaction_bytes)
        if not self.is_enabled:
            # Local processing — no consensus
            record = SubmissionRecord(
                operation_id=envelope.operation_id,
                status=SubmissionStatus.FINALIZED,
                submitted_at=self._time_now(),
                finalized_at=self._time_now(),
                transaction_hash=transaction_hash,
            )
            self._submissions[envelope.operation_id] = record
            self._finalized_operation_ids.add(envelope.operation_id)
            self._total_submitted += 1
            self._total_finalized += 1
            return record

        record = SubmissionRecord(
            operation_id=envelope.operation_id,
            status=SubmissionStatus.PENDING,
            submitted_at=self._time_now(),
            transaction_hash=transaction_hash,
        )
        self._submissions[envelope.operation_id] = record
        self._total_submitted += 1

        # Simulate admission
        if self.abci:
            result = self.abci.process_proposal_transaction(transaction_bytes)

            if result.code == "ok":
                record.status = SubmissionStatus.ADMITTED
                record.admitted_at = self._time_now()
            else:
                record.status = SubmissionStatus.FAILED
                record.error = result.log
                self._total_failed += 1

        return record

    def get_submission(self, operation_id: str) -> SubmissionRecord | None:
        """Get submission tracking record."""
        return self._submissions.get(operation_id)

    def transaction_hash_for_operation(self, operation_id: str) -> str | None:
        """Return the exact transaction hash submitted for one operation."""
        record = self._submissions.get(operation_id)
        return record.transaction_hash if record is not None else None

    def list_submissions(
        self,
        status: SubmissionStatus | None = None,
        limit: int = 100,
    ) -> list[SubmissionRecord]:
        """List submission records with optional filter."""
        records = list(self._submissions.values())
        if status:
            records = [r for r in records if r.status == status]
        return records[:limit]

    # ---- Finalization ----

    def mark_included(self, operation_id: str, block_height: int) -> bool:
        """Mark an operation as included in a block."""
        record = self._submissions.get(operation_id)
        if not record:
            return False
        record.status = SubmissionStatus.INCLUDED
        record.included_at = self._time_now()
        record.block_height = block_height
        return True

    def mark_finalized(self, operation_id: str, block_height: int) -> bool:
        """Mark an operation as finalized."""
        record = self._submissions.get(operation_id)
        if not record:
            return False
        record.status = SubmissionStatus.FINALIZED
        record.finalized_at = self._time_now()
        record.block_height = block_height
        self._finalized_operation_ids.add(operation_id)
        self._total_finalized += 1
        return True

    def is_finalized(self, operation_id: str) -> bool:
        """Check if an operation has been finalized."""
        return operation_id in self._finalized_operation_ids

    # ---- Validator ABCI bootstrap ----

    def bootstrap_validator_abci(
        self,
        *,
        ledger_service,
        admission_validator: AdmissionValidator | None = None,
    ) -> AIDNABCIApplication:
        """Create the only durable ABCI app allowed for this validator service.

        The caller supplies the canonical Ledger service explicitly.  This
        avoids silently creating a second local Ledger alongside Hypervisor
        state, which would make a restart appear healthy while diverging from
        CometBFT's application root.
        """
        if not self.is_validator:
            raise ValueError("only validator consensus services may host ABCI")
        if self.abci is not None:
            if self.abci.ledger is not ledger_service:
                raise ValueError("validator ABCI is already bound to another Ledger service")
            return self.abci
        if not self.config.abci_state_path:
            raise ValueError("validator ABCI requires an explicit durable state path")
        self.abci = AIDNABCIApplication(
            ledger_service=ledger_service,
            admission_validator=admission_validator,
            state_store=ABCIStateStore(self.config.abci_state_path),
        )
        return self.abci

    def start_validator_abci_server(self):
        """Start the local CometBFT ABCI socket after durable bootstrap."""
        if self.abci is None:
            raise ValueError("bootstrap validator ABCI before starting its socket server")
        if self._abci_socket_server is not None and self._abci_socket_server.is_running:
            return self._abci_socket_server
        from aidn_hypervisor.consensus.abci_socket import AIDNABCISocketServer

        server = AIDNABCISocketServer(
            application=self.abci,
            host=self.config.abci_listen_host,
            port=self.config.abci_listen_port,
            maximum_message_size=self.config.abci_maximum_message_size,
        )
        server.start()
        self._abci_socket_server = server
        return server

    def stop_validator_abci_server(self) -> None:
        """Stop the locally owned ABCI socket without changing durable state."""
        if self._abci_socket_server is not None:
            self._abci_socket_server.stop()
            self._abci_socket_server = None

    # ---- Validator duties ----

    def propose_block(
        self,
        txs: list[bytes],
        block_height: int,
        block_hash: bytes,
    ) -> dict:
        """
        RFC-0047 §36 — Propose a block (validator duty).

        Runs finalize_block on ABCI app.
        """
        if not self.is_validator:
            return {"error": "not a validator"}

        if not self.abci:
            return {"error": "no ABCI application"}

        result = self.abci.finalize_block(
            block_height=block_height,
            block_hash=block_hash,
            txs=txs,
            time=datetime.now(UTC).isoformat(),
        )

        self._blocks_proposed += 1
        self._participation_count += 1

        # Mark included txs as included
        for tx_data in txs:
            try:
                envelope = self._parse_envelope(tx_data)
                op_id = envelope.operation_id
                # Create submission record if it doesn't exist
                if op_id not in self._submissions:
                    self._submissions[op_id] = SubmissionRecord(
                        operation_id=op_id,
                        status=SubmissionStatus.PENDING,
                        submitted_at=self._time_now(),
                        transaction_hash=cometbft_transaction_hash(tx_data),
                    )
                else:
                    self._submissions[op_id].transaction_hash = cometbft_transaction_hash(
                        tx_data
                    )
                self.mark_included(op_id, block_height)
                self.mark_finalized(op_id, block_height)
            except Exception:
                pass

        # Commit
        commit = self.abci.commit()

        return {
            "block_height": block_height,
            "executed": int(result.tags[0].value) if result.tags else 0,
            "app_hash": commit.data.hex() if commit.data else "",
            "code": result.code,
        }

    def sign_block(self, block_hash: bytes) -> dict:
        """Sign a block (validator participation)."""
        if not self.is_validator:
            return {"error": "not a validator"}

        self._participation_count += 1

        return {
            "validator": self._validator_signing_key,
            "block_hash": block_hash.hex(),
            "signed": True,
        }

    def record_missed_block(self) -> None:
        """Record a missed block (downtime tracking)."""
        self._missed_blocks += 1

    # ---- Metrics ----

    def get_metrics(self) -> dict:
        """RFC-0047 §39 — Consensus participation metrics."""
        total = self._total_submitted
        finalized = self._total_finalized

        participation_rate = 1.0
        if self.is_validator:
            total_expected = self._participation_count + self._missed_blocks
            if total_expected > 0:
                participation_rate = self._participation_count / total_expected

        return {
            "mode": self.config.mode.value,
            "node_id": self.config.node_id,
            "chain_id": self.config.chain_id,
            "total_submitted": total,
            "total_finalized": finalized,
            "total_failed": self._total_failed,
            "pending_count": sum(
                1 for r in self._submissions.values()
                if r.status in (SubmissionStatus.PENDING, SubmissionStatus.ADMITTED, SubmissionStatus.INCLUDED)
            ),
            "participation_count": self._participation_count,
            "missed_blocks": self._missed_blocks,
            "blocks_proposed": self._blocks_proposed,
            "participation_rate": round(participation_rate, 4),
        }

    # ---- Inclusion monitoring ----

    def monitor_inclusion(self) -> dict[str, SubmissionRecord]:
        """
        RFC-0047 §29 — Monitor pending submissions for inclusion.

        Returns dict of operation_id -> SubmissionRecord for pending items.
        """
        pending = {
            op_id: record
            for op_id, record in self._submissions.items()
            if record.status in (
                SubmissionStatus.PENDING,
                SubmissionStatus.ADMITTED,
                SubmissionStatus.INCLUDED,
            )
        }
        return pending

    # ---- Resubmission ----

    def resubmit_pending(self, max_retries: int | None = None) -> int:
        """
        RFC-0047 §29 — Resubmit operations that haven't been included.

        Returns number of resubmitted operations.
        """
        limit = max_retries or self.config.max_retries
        count = 0

        for record in self._submissions.values():
            if record.status in (SubmissionStatus.PENDING, SubmissionStatus.FAILED):
                if record.retry_count < limit:
                    record.retry_count += 1
                    record.status = SubmissionStatus.PENDING
                    count += 1

        return count

    # ---- Snapshot ----

    def snapshot_state(self) -> dict:
        """Export consensus service state."""
        return {
            "config": {
                "node_id": self.config.node_id,
                "mode": self.config.mode.value,
                "chain_id": self.config.chain_id,
            },
            "finalized_count": len(self._finalized_operation_ids),
            "submissions_count": len(self._submissions),
            "metrics": self.get_metrics(),
            "abci_snapshot": self.abci.prepare_snapshot() if self.abci else None,
        }

    def restore_state(self, snapshot: dict) -> bool:
        """Restore consensus service state from snapshot."""
        if self.abci and snapshot.get("abci_snapshot"):
            result = self.abci.apply_snapshot(snapshot["abci_snapshot"])
            if result.code != "ok":
                return False
        return True

    # ---- Internal ----

    def _parse_envelope(self, tx_data: bytes) -> LedgerOperationEnvelope:
        obj = json.loads(tx_data)
        return LedgerOperationEnvelope.model_validate(obj)

    def _serialize_envelope(self, envelope: LedgerOperationEnvelope) -> bytes:
        return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")
