"""RFC-0047 §3 — Consensus Service as an optional Hypervisor service."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from urllib.parse import urlsplit, urlunsplit

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.cometbft import (
    CometBftSubmissionTransport,
    HttpCometBftRpcTransport,
    HttpCometBftSubmissionTransport,
    cometbft_transaction_hash,
)
from aidn_hypervisor.consensus.finality import (
    ConsensusFinalityEvidence,
    ConsensusFinalitySource,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.state_store import ABCIStateStore, ABCIStateStoreError


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
    managed_service_name: str | None = None
    gas_limit: int = 1_000_000
    max_mempool_size: int = 1000
    submission_timeout_seconds: float = 30.0
    retry_interval_seconds: float = 5.0
    max_retries: int = 3
    abci_state_path: str | None = None
    abci_listen_host: str = "127.0.0.1"
    abci_listen_port: int = 26658
    abci_maximum_message_size: int = 1_048_576
    abci_retained_snapshots: int = ABCIStateStore.DEFAULT_RETAINED_SNAPSHOTS
    abci_snapshot_lease_seconds: int = ABCIStateStore.DEFAULT_SNAPSHOT_LEASE_SECONDS
    strict_operation_coverage: bool = False


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
        submission_transport: CometBftSubmissionTransport | None = None,
    ):
        self.config = config
        self.abci = abci_app
        self._abci_socket_server = None
        self._time_now = time_now or time.monotonic
        self._submission_transport: CometBftSubmissionTransport | None = submission_transport
        if submission_transport is not None:
            self._submission_transport = submission_transport
        elif config.cometbft_endpoint.startswith(("http://", "https://")):
            self._submission_transport = HttpCometBftSubmissionTransport(
                config.cometbft_endpoint
            )
        elif config.mode == ConsensusMode.VALIDATOR:
            parsed_endpoint = urlsplit(config.cometbft_endpoint)
            if parsed_endpoint.scheme in {"tcp", "tcp4", "tcp6"} and parsed_endpoint.netloc:
                # Operator profiles historically use tcp:// for the CometBFT
                # authority even though its RPC submission API is HTTP.
                http_endpoint = urlunsplit(("http", parsed_endpoint.netloc, "", "", ""))
                self._submission_transport = HttpCometBftSubmissionTransport(http_endpoint)
        else:
            self._submission_transport = None

        # Submission tracking
        self._submissions: dict[str, SubmissionRecord] = {}
        self._submitted_envelopes: dict[str, LedgerOperationEnvelope] = {}
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

    def status(self) -> dict:
        """Return bounded local and CometBFT synchronization status.

        The Hypervisor may configure a ``tcp://`` submission endpoint while
        CometBFT exposes its read-only RPC over HTTP on the same authority.
        Convert only that transport label; never follow redirects or expose
        remote exception details through the control plane.
        """
        payload = {
            "enabled": self.is_enabled,
            "mode": self.config.mode.value,
            "node_id": self.config.node_id,
            "chain_id": self.config.chain_id,
            "management": {
                "managed": bool(self.config.managed_service_name),
                "service": self.config.managed_service_name,
            },
            "metrics": self.get_metrics(),
            "rpc": {"available": False},
        }
        if not self.is_enabled:
            payload["rpc"] = {"available": False, "reason": "consensus_disabled"}
            return payload

        parsed = urlsplit(self.config.cometbft_endpoint)
        rpc_endpoint = self.config.cometbft_endpoint
        if parsed.scheme not in {"http", "https"}:
            if not parsed.netloc:
                payload["rpc"] = {"available": False, "reason": "invalid_rpc_endpoint"}
                return payload
            rpc_endpoint = urlunsplit(("http", parsed.netloc, "", "", ""))

        try:
            transport = HttpCometBftRpcTransport(rpc_endpoint)
            status = transport.get("/status", params={}, timeout_seconds=2)
            net_info = transport.get("/net_info", params={}, timeout_seconds=2)
            status_result = status.get("result", {})
            sync_info = status_result.get("sync_info", {})
            node_info = status_result.get("node_info", {})
            net_result = net_info.get("result", {})
            height_raw = sync_info.get("latest_block_height")
            try:
                height = int(height_raw) if height_raw is not None else None
            except (TypeError, ValueError):
                height = None
            peer_count_raw = net_result.get("n_peers")
            try:
                peer_count = int(peer_count_raw) if peer_count_raw is not None else None
            except (TypeError, ValueError):
                peer_count = None
            payload["rpc"] = {
                "available": True,
                "catching_up": bool(sync_info.get("catching_up", False)),
                "latest_block_height": height,
                "chain_id": node_info.get("network"),
                "peer_count": peer_count,
                "listening": bool(net_result.get("listening", False)),
            }
        except Exception as error:  # pragma: no cover - defensive RPC boundary
            payload["rpc"] = {
                "available": False,
                "error_type": type(error).__name__,
            }
        return payload

    # ---- Submission ----

    def submit_operation(
        self,
        envelope: LedgerOperationEnvelope,
        *,
        retry_existing: bool = False,
    ) -> SubmissionRecord:
        """
        RFC-0047 §28 — Submit a signed Ledger Operation to consensus.

        For non-validators: sends to CometBFT mempool.
        For validators: includes in next proposal.

        Existing submissions remain idempotent by default. Recovery callers
        may opt into rebroadcasting the exact same transaction after a
        restart, because CometBFT mempool admission is not durable state.
        """
        transaction_bytes = self._serialize_envelope(envelope)
        transaction_hash = cometbft_transaction_hash(transaction_bytes)
        self._submitted_envelopes[envelope.operation_id] = envelope
        existing = self._submissions.get(envelope.operation_id)
        if existing is not None:
            if existing.transaction_hash != transaction_hash:
                raise ValueError("operation_id is already bound to another transaction")
            if existing.status == SubmissionStatus.FINALIZED or not retry_existing:
                return existing
            record = existing
        elif not self.is_enabled:
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
        else:
            record = SubmissionRecord(
                operation_id=envelope.operation_id,
                status=SubmissionStatus.PENDING,
                submitted_at=self._time_now(),
                transaction_hash=transaction_hash,
            )
            self._submissions[envelope.operation_id] = record
            self._total_submitted += 1

        # A validator may have a local ABCI application and an HTTP CometBFT
        # RPC at the same time. The RPC path is canonical: local CheckTx is
        # only a fallback for isolated tests or explicitly local deployments.
        if self._submission_transport is not None:
            try:
                response = self._submission_transport.broadcast_tx_sync(
                    transaction_bytes,
                    timeout_seconds=max(1, int(self.config.submission_timeout_seconds)),
                )
                if self._is_cached_transaction_response(response):
                    # CometBFT can report an already-admitted transaction as
                    # an RPC error when a recovered node rebroadcasts it.
                    # The transaction hash is already bound to this record,
                    # so this is an idempotent admission, not a failure.
                    record.status = SubmissionStatus.ADMITTED
                    record.admitted_at = self._time_now()
                    record.error = None
                else:
                    submission_result = self._submission_result(response)
                    code = self._submission_code(submission_result.get("code"))
                    if code != 0:
                        raise ValueError(
                            str(
                                submission_result.get("log")
                                or submission_result.get("info")
                                or f"CometBFT CheckTx code {code}"
                            )
                        )
                    response_hash = submission_result.get("hash")
                    if response_hash is not None and not self._matches_transaction_hash(
                        response_hash,
                        transaction_hash,
                    ):
                        raise ValueError("CometBFT submission hash does not match transaction")
                    record.status = SubmissionStatus.ADMITTED
                    record.admitted_at = self._time_now()
            except Exception as error:
                record.status = SubmissionStatus.FAILED
                record.error = str(error) or error.__class__.__name__
                self._total_failed += 1
        elif self.abci:
            result = self.abci.process_proposal_transaction(transaction_bytes)

            if result.code == "ok":
                record.status = SubmissionStatus.ADMITTED
                record.admitted_at = self._time_now()
            else:
                record.status = SubmissionStatus.FAILED
                record.error = result.log
                self._total_failed += 1

        return record

    def get_operation_envelope(self, operation_id: str) -> LedgerOperationEnvelope | None:
        """Return the exact envelope retained for an idempotent retry."""
        return self._submitted_envelopes.get(operation_id)

    def restore_submission(self, envelope: LedgerOperationEnvelope) -> SubmissionRecord:
        """Restore submission identity before checking external finality.

        A restart may retain a canonical operation in the local ledger while
        losing the in-memory submission index.  Reconstructing the exact
        transaction hash lets the verified finality source inspect the chain
        before recovery decides whether a rebroadcast is necessary.
        """
        transaction_bytes = self._serialize_envelope(envelope)
        transaction_hash = cometbft_transaction_hash(transaction_bytes)
        self._submitted_envelopes[envelope.operation_id] = envelope
        existing = self._submissions.get(envelope.operation_id)
        if existing is not None:
            if existing.transaction_hash != transaction_hash:
                raise ValueError("operation_id is already bound to another transaction")
            return existing
        record = SubmissionRecord(
            operation_id=envelope.operation_id,
            status=SubmissionStatus.PENDING,
            submitted_at=self._time_now(),
            transaction_hash=transaction_hash,
        )
        self._submissions[envelope.operation_id] = record
        return record

    def find_submitted_envelope(
        self,
        operation_type: str,
        *,
        predicate: Callable[[LedgerOperationEnvelope], bool] | None = None,
    ) -> LedgerOperationEnvelope | None:
        """Find a previously submitted semantic operation for reconnect recovery."""
        for envelope in reversed(tuple(self._submitted_envelopes.values())):
            if envelope.operation_type != operation_type:
                continue
            if predicate is None or predicate(envelope):
                return envelope
        return None

    def get_submission(self, operation_id: str) -> SubmissionRecord | None:
        """Get submission tracking record."""
        return self._submissions.get(operation_id)

    def transaction_hash_for_operation(self, operation_id: str) -> str | None:
        """Return an exact transaction hash, including after a restart.

        Submission tracking is in-memory, but the canonical Ledger record is
        durable. Falling back to that record lets finality verification inspect
        an already committed transaction without rebroadcasting it.
        """
        record = self._submissions.get(operation_id)
        if record is not None and record.transaction_hash is not None:
            return record.transaction_hash
        abci = self.abci
        ledger = getattr(abci, "ledger", None) if abci is not None else None
        get_operation = getattr(ledger, "get_operation", None)
        if not callable(get_operation):
            return None
        operation = get_operation(operation_id)
        if not isinstance(operation, dict):
            return None
        transaction_hash = operation.get("transaction_hash")
        if isinstance(transaction_hash, str):
            return transaction_hash
        # Legacy Ledger snapshots contain the complete envelope but predate
        # the persisted transaction_hash field. Recreate the exact bytes used
        # by broadcast_tx_sync before falling back to an RPC block scan.
        try:
            envelope = LedgerOperationEnvelope.model_validate(operation)
            if envelope.operation_id != operation_id:
                return None
            return cometbft_transaction_hash(self._serialize_envelope(envelope))
        except (TypeError, ValueError):
            return None

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
        if block_height < 1:
            return False
        record = self._submissions.get(operation_id)
        if not record:
            return False
        if record.status == SubmissionStatus.FINALIZED:
            return record.block_height == block_height
        if record.status == SubmissionStatus.INCLUDED:
            return record.block_height == block_height
        record.status = SubmissionStatus.INCLUDED
        record.included_at = self._time_now()
        record.block_height = block_height
        return True

    def mark_finalized(self, operation_id: str, block_height: int) -> bool:
        """Mark an operation as finalized."""
        if block_height < 1:
            return False
        record = self._submissions.get(operation_id)
        if not record:
            return False
        if record.status == SubmissionStatus.FINALIZED:
            return record.block_height == block_height
        record.status = SubmissionStatus.FINALIZED
        record.finalized_at = self._time_now()
        record.block_height = block_height
        self._finalized_operation_ids.add(operation_id)
        self._total_finalized += 1
        return True

    def reconcile_finality(
        self,
        operation_id: str,
        *,
        finality_source: ConsensusFinalitySource,
    ) -> SubmissionRecord | None:
        """Apply only verified, operation-bound finality evidence."""
        record = self._submissions.get(operation_id)
        if record is None:
            return None
        try:
            evidence = finality_source.finality_evidence(operation_id)
        except Exception:
            return None
        if not isinstance(evidence, ConsensusFinalityEvidence):
            return None
        if evidence.operation_id != operation_id or evidence.chain_id != self.config.chain_id:
            return None
        if not self.mark_included(operation_id, evidence.block_height):
            return None
        if not self.mark_finalized(operation_id, evidence.block_height):
            return None
        return record

    def is_finalized(self, operation_id: str) -> bool:
        """Check if an operation has been finalized."""
        return operation_id in self._finalized_operation_ids

    # ---- Validator ABCI bootstrap ----

    def bootstrap_validator_abci(
        self,
        *,
        ledger_service,
        admission_validator: AdmissionValidator | None = None,
        genesis_accounts: dict[str, int] | None = None,
        restore_state_from_store: bool = False,
        state_checkpoint_callback: Callable[[], None] | None = None,
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
            genesis_accounts=genesis_accounts,
            state_store=ABCIStateStore(
                self.config.abci_state_path,
                retained_snapshots=self.config.abci_retained_snapshots,
                snapshot_lease_seconds=self.config.abci_snapshot_lease_seconds,
            ),
            restore_state_from_store=restore_state_from_store,
            state_checkpoint_callback=state_checkpoint_callback,
            strict_operation_coverage=self.config.strict_operation_coverage,
        )
        return self.abci

    def restore_validator_abci_state_if_matching_ledger(self) -> bool:
        """Complete a Hypervisor-first validator restart without state takeover."""
        if self.abci is None:
            raise ValueError("bootstrap validator ABCI before restoring its durable state")
        return self.abci.restore_durable_state_if_matching_ledger()

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

        result, transaction_results = self.abci.finalize_block_with_results(
            block_height=block_height,
            block_hash=block_hash,
            txs=txs,
            time=datetime.now(UTC).isoformat(),
        )

        self._blocks_proposed += 1
        self._participation_count += 1

        if result.code != "ok":
            for tx_data in txs:
                self._mark_proposal_transaction_failed(
                    tx_data,
                    block_height=block_height,
                    error=result.log or "ABCI block finalization failed",
                )
            return {
                "block_height": block_height,
                "executed": 0,
                "app_hash": "",
                "code": result.code,
            }

        # Commit
        try:
            commit = self.abci.commit()
        except ABCIStateStoreError as error:
            for tx_data in txs:
                self._mark_proposal_transaction_failed(
                    tx_data,
                    block_height=block_height,
                    error=str(error),
                )
            return {
                "block_height": block_height,
                "executed": 0,
                "app_hash": "",
                "code": "internal",
            }

        for tx_data, transaction_result in zip(txs, transaction_results, strict=True):
            try:
                envelope = self._parse_envelope(tx_data)
                op_id = envelope.operation_id
                self._ensure_submission_record(op_id, tx_data)
                if transaction_result.code == "ok":
                    self.mark_included(op_id, block_height)
                    self.mark_finalized(op_id, block_height)
                else:
                    self._mark_proposal_transaction_failed(
                        tx_data,
                        block_height=block_height,
                        error=transaction_result.log or transaction_result.code,
                    )
            except Exception:
                pass

        return {
            "block_height": block_height,
            "executed": sum(1 for item in transaction_results if item.code == "ok"),
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

    def _ensure_submission_record(self, operation_id: str, tx_data: bytes) -> SubmissionRecord:
        record = self._submissions.get(operation_id)
        if record is None:
            record = SubmissionRecord(
                operation_id=operation_id,
                status=SubmissionStatus.PENDING,
                submitted_at=self._time_now(),
                transaction_hash=cometbft_transaction_hash(tx_data),
            )
            self._submissions[operation_id] = record
        else:
            record.transaction_hash = cometbft_transaction_hash(tx_data)
        return record

    def _mark_proposal_transaction_failed(
        self,
        tx_data: bytes,
        *,
        block_height: int,
        error: str,
    ) -> None:
        try:
            envelope = self._parse_envelope(tx_data)
        except Exception:
            return
        record = self._ensure_submission_record(envelope.operation_id, tx_data)
        if record.status == SubmissionStatus.FINALIZED:
            return
        if record.status != SubmissionStatus.FAILED:
            self._total_failed += 1
        record.status = SubmissionStatus.FAILED
        record.error = error
        record.block_height = block_height

    def _serialize_envelope(self, envelope: LedgerOperationEnvelope) -> bytes:
        return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")

    def _submission_result(self, response: dict) -> dict:
        if not isinstance(response, dict):
            raise ValueError("CometBFT submission response is invalid")
        if response.get("error") not in {None, ""}:
            raise ValueError("CometBFT submission returned an RPC error")
        result = response.get("result", response)
        if not isinstance(result, dict):
            raise ValueError("CometBFT submission result is invalid")
        return result

    def _is_cached_transaction_response(self, response: object) -> bool:
        """Return whether CometBFT reports an idempotently cached transaction."""
        if not isinstance(response, dict):
            return False
        fragments: list[str] = []
        error = response.get("error")
        if isinstance(error, dict):
            fragments.extend(str(error.get(key, "")) for key in ("message", "data"))
        result = response.get("result")
        if isinstance(result, dict):
            fragments.extend(str(result.get(key, "")) for key in ("log", "info"))
        return "tx already exists in cache" in " ".join(fragments).lower()

    def _submission_code(self, value: object) -> int:
        if isinstance(value, bool):
            raise ValueError("CometBFT submission code is invalid")
        if value is None:
            return 0
        if isinstance(value, int):
            code = value
        elif isinstance(value, str):
            try:
                code = int(value)
            except ValueError as error:
                raise ValueError("CometBFT submission code is invalid") from error
        else:
            raise ValueError("CometBFT submission code is invalid")
        if code < 0:
            raise ValueError("CometBFT submission code is invalid")
        return code

    def _matches_transaction_hash(self, value: object, expected: str) -> bool:
        if not isinstance(value, str):
            return False
        normalized = value.removeprefix("0x").upper()
        return normalized == expected
