"""RFC-0047 §5, §10-§16 — AIDN ABCI Application."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from aidn_hypervisor.consensus.abci_models import (
    ABCICommitResponse,
    ABCIInfoResponse,
    ABCIQueryResponse,
    ABCIResult,
    ABCITag,
)
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.state_store import (
    ABCIStateSnapshot,
    ABCIStateStore,
    ABCIStateStoreError,
)


@dataclass(frozen=True)
class ABCICanonicalCommitment:
    """The local ABCI state commitment for one finalized CometBFT height."""

    height: int
    block_hash: str
    app_hash: str

    def __post_init__(self) -> None:
        if self.height < 1 or len(self.block_hash) != 64 or len(self.app_hash) != 64:
            raise ValueError("ABCI canonical commitment is invalid")


class ABCIMempool:
    """In-memory mempool for proposed but not yet finalized operations."""

    def __init__(self):
        self._txs: list[bytes] = []
        self._tx_ids: set[str] = set()

    def pending(self) -> list[bytes]:
        return list(self._txs)

    def size(self) -> int:
        return len(self._txs)

    def add(self, tx_data: bytes, operation_id: str) -> bool:
        if operation_id in self._tx_ids:
            return False
        self._txs.append(tx_data)
        self._tx_ids.add(operation_id)
        return True

    def remove(self, operation_id: str) -> None:
        self._tx_ids.discard(operation_id)
        self._txs = [t for t in self._txs if self._extract_id(t) != operation_id]

    def clear(self) -> None:
        self._txs.clear()
        self._tx_ids.clear()

    def _extract_id(self, tx_data: bytes) -> str:
        try:
            obj = json.loads(tx_data)
            envelope = LedgerOperationEnvelope.model_validate(obj)
            return envelope.operation_id
        except (json.JSONDecodeError, TypeError, Exception):
            return ""


class AIDNABCIApplication:
    """
    AiDN ABCI Application — the integration boundary between CometBFT
    and the AiDN Ledger State Machine.

    RFC-0047 §5: exposes deterministic handlers for:
    - application initialization
    - transaction admission
    - proposal preparation
    - proposal validation
    - block finalization
    - state commitment
    - state queries
    - snapshot creation/restoration
    """

    APP_VERSION = 1
    PROTOCOL_VERSION = "0.1"

    def __init__(
        self,
        *,
        ledger_service: Any,  # LedgerOperationService
        admission_validator: AdmissionValidator | None = None,
        genesis_time: str | None = None,
        genesis_accounts: dict[str, int] | None = None,
        state_store: ABCIStateStore | None = None,
        restore_state_from_store: bool = True,
        state_checkpoint_callback: Callable[[], None] | None = None,
    ):
        self.ledger = ledger_service
        self.mempool = ABCIMempool()
        self._admission = admission_validator or AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        )
        self._genesis_time = genesis_time or datetime.now(UTC).isoformat()
        self._last_block_height = 0
        self._last_block_hash = b"\x00" * 32
        self._app_hash = b""
        self._commitments: dict[int, ABCICanonicalCommitment] = {}
        self._state_store = state_store
        self._state_checkpoint_callback = state_checkpoint_callback
        self._restored_from_store = False

        persisted_snapshot = (
            state_store.load_current()
            if state_store is not None and restore_state_from_store
            else None
        )
        if persisted_snapshot is not None:
            if genesis_accounts:
                raise ValueError("genesis accounts cannot be applied over durable ABCI state")
            result = self.apply_snapshot(persisted_snapshot)
            if result.code != "ok":
                raise ABCIStateStoreError(result.log or "could not restore durable ABCI state")
            self._restored_from_store = True
        elif genesis_accounts:
            for wallet_id, amount in genesis_accounts.items():
                ledger_service.credit_wallet_q_atoms(
                    wallet_id=wallet_id,
                    amount_q_atoms=amount,
                )
        if not self._restored_from_store:
            self._app_hash = self._compute_state_hash()

    def restore_durable_state_if_matching_ledger(self) -> bool:
        """Restore ABCI metadata only when its Ledger root already matches.

        Hypervisor persistence owns the complete local service snapshot while
        ABCI persistence owns the consensus height and a Ledger projection.
        Starting a validator must never let the narrower ABCI snapshot silently
        overwrite a newer or different Hypervisor Ledger.
        """
        if self._state_store is None:
            raise ABCIStateStoreError("durable ABCI state is disabled")
        snapshot = self._state_store.load_current()
        if snapshot is None:
            return False
        expected_hash = self._snapshot_app_hash(snapshot)
        actual_hash = self._compute_state_hash()
        if expected_hash != actual_hash:
            raise ABCIStateStoreError(
                "durable ABCI state does not match the restored Hypervisor Ledger"
            )
        result = self.apply_snapshot(snapshot)
        if result.code != "ok":
            raise ABCIStateStoreError(result.log or "could not restore durable ABCI state")
        self._restored_from_store = True
        return True

    def _compute_initial_hash(self) -> bytes:
        return hashlib.sha256(b"AiDN-genesis").digest()

    # ---- ABCI Lifecycle ----

    def info(self) -> ABCIInfoResponse:
        """ABCI info — application metadata."""
        return ABCIInfoResponse(
            data="AiDN Consensus Application",
            version=f"{self.PROTOCOL_VERSION}:{self.APP_VERSION}",
            app_version=self.APP_VERSION,
            last_block_height=self._last_block_height,
            last_block_app_hash=self._app_hash,
        )

    def init_chain(
        self,
        *,
        genesis_time: str | None = None,
        initial_height: int = 0,
    ) -> ABCIResult:
        """Initialize chain from genesis state."""
        if self._restored_from_store:
            return ABCIResult(
                code="rejected",
                log="durable ABCI state is already initialized",
            )
        self._genesis_time = genesis_time or self._genesis_time
        self._last_block_height = initial_height
        self._app_hash = self._compute_state_hash()

        return ABCIResult(
            code="ok",
            info="chain initialized",
            tags=[
                ABCITag(key="genesis_time", value=self._genesis_time),
                ABCITag(key="height", value=str(initial_height)),
            ],
        )

    # ---- Transaction Processing ----

    def process_proposal_transaction(self, tx_data: bytes) -> ABCIResult:
        """
        RFC-0047 §10 — Admission validation for proposed transactions.
        Returns ACCEPT or REJECT with reason.
        """
        return self.check_transaction(tx_data)

    def check_transaction(self, tx_data: bytes, *, recheck: bool = False) -> ABCIResult:
        """Validate one transaction, admitting it only during the initial CheckTx.

        CometBFT replays transactions retained in its own mempool after a
        committed block.  Recheck must not turn an already admitted local
        transaction into a duplicate rejection, or CometBFT will evict it
        before a proposer can include it.
        """
        try:
            envelope = self._parse_envelope(tx_data)
        except Exception as e:
            return ABCIResult(
                code="invalid",
                log=f"parse error: {e}",
            )

        # Admission check
        admission = self._admission.validate(envelope)
        if not admission.admitted:
            return ABCIResult(
                code="rejected",
                log=admission.reason or "admission failed",
                tags=[
                    ABCITag(key="operation_id", value=envelope.operation_id),
                    ABCITag(key="reason", value=admission.reason or "unknown"),
                ],
            )

        if recheck:
            return ABCIResult(
                code="ok",
                tags=[ABCITag(key="operation_id", value=envelope.operation_id)],
            )

        # Add to mempool
        added = self.mempool.add(tx_data, envelope.operation_id)
        if not added:
            return ABCIResult(
                code="duplicate",
                log="already in mempool",
                tags=[ABCITag(key="operation_id", value=envelope.operation_id)],
            )

        return ABCIResult(
            code="ok",
            tags=[ABCITag(key="operation_id", value=envelope.operation_id)],
        )

    def prepare_proposal(self, txs: list[bytes], *, maximum_bytes: int) -> list[bytes]:
        """Select deterministic, valid transactions without mutating mempool state."""
        selected: list[bytes] = []
        selected_ids: set[str] = set()
        total_bytes = 0
        for tx_data in txs:
            try:
                envelope = self._parse_envelope(tx_data)
                if envelope.operation_id in selected_ids or not self._admission.validate(envelope).admitted:
                    continue
            except Exception:
                continue
            if maximum_bytes > 0 and total_bytes + len(tx_data) > maximum_bytes:
                continue
            selected.append(tx_data)
            selected_ids.add(envelope.operation_id)
            total_bytes += len(tx_data)
        return selected

    def process_proposal(self, txs: list[bytes]) -> ABCIResult:
        """Validate a proposed block without changing application state."""
        operation_ids: set[str] = set()
        for tx_data in txs:
            try:
                envelope = self._parse_envelope(tx_data)
            except Exception as error:
                return ABCIResult(code="invalid", log=f"parse error: {error}")
            if envelope.operation_id in operation_ids:
                return ABCIResult(code="duplicate", log="duplicate operation in proposal")
            operation_ids.add(envelope.operation_id)
            admission = self._admission.validate(envelope)
            if not admission.admitted:
                return ABCIResult(code="rejected", log=admission.reason or "admission failed")
        return ABCIResult(code="ok")

    def reject_proposal_transaction(self, tx_data: bytes) -> ABCIResult:
        """Explicitly reject a transaction."""
        try:
            envelope = self._parse_envelope(tx_data)
            return ABCIResult(
                code="rejected",
                log="explicit rejection",
                tags=[ABCITag(key="operation_id", value=envelope.operation_id)],
            )
        except Exception:
            return ABCIResult(code="invalid", log="parse error on rejection")

    # ---- Block Processing ----

    def finalize_block(
        self,
        *,
        block_height: int,
        block_hash: bytes,
        txs: list[bytes],
        time: str | None = None,
    ) -> ABCIResult:
        """
        RFC-0047 §13 — Deterministic block finalization.
        Execute all transactions in order, apply state transitions,
        emit events.
        """
        result, _ = self.finalize_block_with_results(
            block_height=block_height,
            block_hash=block_hash,
            txs=txs,
            time=time,
        )
        return result

    def finalize_block_with_results(
        self,
        *,
        block_height: int,
        block_hash: bytes,
        txs: list[bytes],
        time: str | None = None,
    ) -> tuple[ABCIResult, list[ABCIResult]]:
        """Finalize a block and retain one deterministic result per input tx."""
        previous_snapshot = self.prepare_snapshot()
        previous_admission_state = self._admission.snapshot_state()
        executed: list[ABCIResult] = []
        rejected: list[ABCIResult] = []
        tx_results: list[ABCIResult] = []
        events = []

        for tx_data in txs:
            result = self._execute_one(tx_data)
            tx_results.append(result)
            if result.code == "ok":
                executed.append(result)
                if result.tags:
                    events.extend([t.key + "=" + t.value for t in result.tags])
            else:
                rejected.append(result)

        # Update state
        self._last_block_height = block_height
        self._last_block_hash = block_hash
        self._app_hash = self._compute_state_hash()
        self._commitments[block_height] = ABCICanonicalCommitment(
            height=block_height,
            block_hash=block_hash.hex().upper(),
            app_hash=self._app_hash.hex().upper(),
        )

        try:
            self._persist_durable_state()
        except ABCIStateStoreError as error:
            # Never acknowledge a block whose application state cannot survive
            # a restart.  Restore the pre-block state before returning failure.
            rollback = self.apply_snapshot(previous_snapshot)
            self._admission.restore_state(previous_admission_state)
            rollback_note = "" if rollback.code == "ok" else "; rollback failed"
            if rollback.code == "ok":
                try:
                    self._persist_abci_state()
                except ABCIStateStoreError:
                    rollback_note += "; durable rollback failed"
            failure = ABCIResult(
                code="internal",
                log=f"durable state persistence failed: {error}{rollback_note}",
            )
            return failure, [failure for _ in txs]

        # Clear mempool of included txs
        for tx_data in txs:
            try:
                envelope = self._parse_envelope(tx_data)
                self.mempool.remove(envelope.operation_id)
            except Exception:
                pass

        log_parts = [
            f"executed={len(executed)}",
            f"rejected={len(rejected)}",
        ]

        return ABCIResult(
            code="ok",
            log="; ".join(log_parts),
            info=f"block_{block_height}",
            tags=[
                ABCITag(key="height", value=str(block_height)),
                ABCITag(key="executed", value=str(len(executed))),
                ABCITag(key="rejected", value=str(len(rejected))),
            ],
        ), tx_results

    def commit(self) -> ABCICommitResponse:
        """RFC-0047 §16 — State commitment after block finalization."""
        app_hash = self._compute_state_hash()
        self._app_hash = app_hash

        return ABCICommitResponse(
            data=app_hash,
            version=str(self._last_block_height),
        )

    def commitment_at(self, height: int) -> ABCICanonicalCommitment | None:
        """Return an immutable local commitment for an exact finalized height."""
        return self._commitments.get(height)

    # ---- Queries ----

    def query(
        self,
        *,
        path: str = "",
        data: bytes = b"",
        height: int | None = None,
        prove: bool = False,
    ) -> ABCIQueryResponse:
        """RFC-0047 §30 — Deterministic state queries."""
        # Build keyword args for frozen model
        kwargs: dict = {"height": self._last_block_height}

        if path == "state/app_hash":
            kwargs["key"] = b"app_hash"
            kwargs["value"] = self._app_hash
        elif path == "state/height":
            kwargs["key"] = b"height"
            kwargs["value"] = str(self._last_block_height).encode()
        elif path.startswith("wallet/balance/"):
            wallet_id = path.split("/")[-1]
            balance = self.ledger.wallet_q_atom_balance(wallet_id)
            kwargs["key"] = f"wallet:{wallet_id}:balance".encode()
            kwargs["value"] = str(balance).encode()
        elif path.startswith("wallet/sequence/"):
            wallet_id = path.split("/")[-1]
            seq = self.ledger.wallet_next_sequence(wallet_id)
            kwargs["key"] = f"wallet:{wallet_id}:sequence".encode()
            kwargs["value"] = str(seq).encode()
        elif path == "mempool/size":
            kwargs["key"] = b"mempool_size"
            kwargs["value"] = str(self.mempool.size()).encode()
        else:
            kwargs["key"] = b"unknown_path"
            kwargs["value"] = b""

        return ABCIQueryResponse(**kwargs)

    # ---- Snapshot ----

    def prepare_snapshot(self) -> dict:
        """Export application state for snapshot."""
        return {
            "app_version": self.APP_VERSION,
            "protocol_version": self.PROTOCOL_VERSION,
            "genesis_time": self._genesis_time,
            "last_block_height": self._last_block_height,
            "last_block_hash": self._last_block_hash.hex(),
            "app_hash": self._compute_state_hash().hex(),
            "commitments": [asdict(commitment) for commitment in self._commitments.values()],
            "ledger_operations": self.ledger.snapshot_operations(),
            "wallet_sequences": self.ledger.snapshot_wallet_sequences(),
            "settlement_state": self.ledger.snapshot_settlement_state(),
        }

    def apply_snapshot(self, snapshot: dict) -> ABCIResult:
        """Atomically restore application state from a verified snapshot."""
        previous_snapshot = self.prepare_snapshot()
        try:
            self._apply_snapshot_unchecked(snapshot)

            return ABCIResult(
                code="ok",
                info=f"snapshot restored to height {self._last_block_height}",
                tags=[
                    ABCITag(key="height", value=str(self._last_block_height)),
                ],
            )
        except Exception as e:
            try:
                self._apply_snapshot_unchecked(previous_snapshot)
            except Exception:
                pass
            return ABCIResult(
                code="internal",
                log=f"snapshot restore failed: {e}",
            )

    def _apply_snapshot_unchecked(self, snapshot: dict) -> None:
        """Apply a parsed snapshot; caller owns rollback when validation fails."""
        if int(snapshot["app_version"]) != self.APP_VERSION:
            raise ValueError("snapshot application version is unsupported")
        settlement_state = snapshot.get("settlement_state", {})
        self.ledger.restore(
            operations=snapshot.get("ledger_operations", []),
            wallet_sequences=snapshot.get("wallet_sequences", {}),
            wallet_q_atom_balances=settlement_state.get("wallet_q_atom_balances"),
            session_funding_accounts=settlement_state.get("session_funding_accounts"),
            settlement_proposals=settlement_state.get("settlement_proposals"),
            settlement_acceptances=settlement_state.get("settlement_acceptances"),
            settlement_transition_hashes=settlement_state.get("settlement_transition_hashes"),
        )
        self._last_block_height = int(snapshot["last_block_height"])
        if self._last_block_height < 0:
            raise ValueError("snapshot height is invalid")
        self._last_block_hash = bytes.fromhex(snapshot["last_block_hash"])
        self._app_hash = self._snapshot_app_hash(snapshot)
        if len(self._last_block_hash) != 32 or len(self._app_hash) != 32:
            raise ValueError("snapshot hash length is invalid")
        self._genesis_time = snapshot.get("genesis_time", self._genesis_time)
        self._commitments = {
            commitment["height"]: ABCICanonicalCommitment(**commitment)
            for commitment in snapshot.get("commitments", [])
        }
        if self._compute_state_hash() != self._app_hash:
            raise ValueError("snapshot application hash does not match state")

    # ---- State Sync ----

    def list_state_snapshots(self) -> list[ABCIStateSnapshot]:
        """Return retained snapshots that CometBFT may offer to a syncing peer."""
        return self._state_store.list_snapshots() if self._state_store is not None else []

    def offer_state_snapshot(self, metadata: ABCIStateSnapshot) -> str:
        """Validate an incoming snapshot offer without changing application state."""
        if self._state_store is None:
            return "abort"
        if metadata.height <= self._last_block_height:
            return "reject"
        return "accept" if self._state_store.offer_import(metadata) else "reject"

    def load_state_snapshot_chunk(self, *, height: int, format: int, chunk: int) -> bytes:
        """Load a retained local State Sync chunk."""
        if self._state_store is None:
            raise ABCIStateStoreError("durable ABCI state is disabled")
        return self._state_store.load_snapshot_chunk(height=height, format=format, chunk=chunk)

    def apply_state_snapshot_chunk(self, *, index: int, chunk: bytes) -> str:
        """Apply an incoming State Sync chunk only after complete verification."""
        if self._state_store is None:
            return "abort"
        previous_snapshot = self.prepare_snapshot()
        try:
            imported = self._state_store.add_import_chunk(index=index, payload=chunk)
            if imported is None:
                return "accept"
            metadata, snapshot = imported
            try:
                imported_app_hash = bytes.fromhex(str(snapshot.get("app_hash", "")))
            except ValueError:
                return "reject_snapshot"
            if imported_app_hash != metadata.app_hash:
                return "reject_snapshot"
            result = self.apply_snapshot(snapshot)
            if result.code != "ok":
                return "reject_snapshot"
            try:
                self._persist_durable_state()
            except ABCIStateStoreError:
                rollback = self.apply_snapshot(previous_snapshot)
                if rollback.code == "ok":
                    try:
                        self._persist_abci_state()
                    except ABCIStateStoreError:
                        pass
                return "abort"
            self._restored_from_store = True
            return "accept"
        except ABCIStateStoreError:
            self._state_store.abort_import()
            return "retry_snapshot"

    def _persist_durable_state(self) -> None:
        self._persist_abci_state()
        if self._state_checkpoint_callback is not None:
            try:
                self._state_checkpoint_callback()
            except Exception as error:
                raise ABCIStateStoreError(
                    "Hypervisor state checkpoint failed after ABCI persistence"
                ) from error

    def _persist_abci_state(self) -> None:
        if self._state_store is not None:
            self._state_store.persist(self.prepare_snapshot())

    # ---- Internal helpers ----

    def _parse_envelope(self, tx_data: bytes) -> LedgerOperationEnvelope:
        """Parse raw bytes into LedgerOperationEnvelope."""
        obj = json.loads(tx_data)
        return LedgerOperationEnvelope.model_validate(obj)

    def _execute_one(self, tx_data: bytes) -> ABCIResult:
        """Execute a single transaction against the ledger."""
        try:
            envelope = self._parse_envelope(tx_data)
        except Exception as e:
            return ABCIResult(code="invalid", log=f"parse error: {e}")

        # Admission check
        admission = self._admission.validate(envelope)
        if not admission.admitted:
            return ABCIResult(
                code="rejected",
                log=admission.reason or "admission failed",
                tags=[ABCITag(key="operation_id", value=envelope.operation_id)],
            )

        # Record in ledger
        try:
            self.ledger.record_admitted_envelope(envelope)
            self._admission.record_finalized(envelope.operation_id)
            if envelope.sender_wallet is not None:
                self._admission.advance_wallet_sequence(envelope.sender_wallet)

            return ABCIResult(
                code="ok",
                tags=[
                    ABCITag(key="operation_id", value=envelope.operation_id),
                    ABCITag(key="type", value=envelope.operation_type),
                ],
            )
        except Exception as e:
            return ABCIResult(
                code="internal",
                log=f"execution error: {e}",
            )

    def _compute_state_hash(self) -> bytes:
        """Compute deterministic hash of current application state."""
        state = {
            "operations": self.ledger.snapshot_operations(),
            "wallet_sequences": self.ledger.snapshot_wallet_sequences(),
            "settlement_state": self.ledger.snapshot_settlement_state(),
        }
        canonical = json.dumps(state, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).digest()

    @staticmethod
    def _snapshot_app_hash(snapshot: dict) -> bytes:
        try:
            return bytes.fromhex(str(snapshot["app_hash"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("snapshot application hash is invalid") from error
