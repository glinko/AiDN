"""RFC-0047 §5, §10-§16 — AIDN ABCI Application."""

import hashlib
import json
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
    ):
        self.ledger = ledger_service
        self.mempool = ABCIMempool()
        self._admission = admission_validator or AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        )
        self._genesis_time = genesis_time or datetime.now(UTC).isoformat()
        self._last_block_height = 0
        self._last_block_hash = b"\x00" * 32
        self._app_hash = self._compute_initial_hash()

        # Genesis funding
        if genesis_accounts:
            for wallet_id, amount in genesis_accounts.items():
                ledger_service.credit_wallet_q_atoms(
                    wallet_id=wallet_id,
                    amount_q_atoms=amount,
                )

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
        self._genesis_time = genesis_time or self._genesis_time
        self._last_block_height = initial_height
        self._app_hash = self._compute_initial_hash()

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
        executed = []
        rejected = []
        events = []

        for tx_data in txs:
            result = self._execute_one(tx_data)
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
        )

    def commit(self) -> ABCICommitResponse:
        """RFC-0047 §16 — State commitment after block finalization."""
        app_hash = self._compute_state_hash()
        self._app_hash = app_hash

        return ABCICommitResponse(
            data=app_hash,
            version=str(self._last_block_height),
        )

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
            "app_hash": self._app_hash.hex(),
            "ledger_operations": self.ledger.snapshot_operations(),
            "wallet_sequences": self.ledger.snapshot_wallet_sequences(),
            "settlement_state": self.ledger.snapshot_settlement_state(),
        }

    def apply_snapshot(self, snapshot: dict) -> ABCIResult:
        """Restore application state from snapshot."""
        try:
            settlement_state = snapshot.get("settlement_state", {})
            # Restore ledger state
            self.ledger.restore(
                operations=snapshot.get("ledger_operations", []),
                wallet_sequences=snapshot.get("wallet_sequences", {}),
                wallet_q_atom_balances=settlement_state.get("wallet_q_atom_balances"),
                session_funding_accounts=settlement_state.get("session_funding_accounts"),
                settlement_proposals=settlement_state.get("settlement_proposals"),
                settlement_acceptances=settlement_state.get("settlement_acceptances"),
                settlement_transition_hashes=settlement_state.get(
                    "settlement_transition_hashes"
                ),
            )

            self._last_block_height = snapshot["last_block_height"]
            self._last_block_hash = bytes.fromhex(snapshot["last_block_hash"])
            self._app_hash = bytes.fromhex(snapshot["app_hash"])
            self._genesis_time = snapshot.get("genesis_time", self._genesis_time)

            return ABCIResult(
                code="ok",
                info=f"snapshot restored to height {self._last_block_height}",
                tags=[
                    ABCITag(key="height", value=str(self._last_block_height)),
                ],
            )
        except Exception as e:
            return ABCIResult(
                code="internal",
                log=f"snapshot restore failed: {e}",
            )

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
            "operations_count": len(self.ledger._operations),
            "wallets": dict(self.ledger._wallet_q_atom_balances),
            "sequences": dict(self.ledger._wallet_next_sequences),
        }
        canonical = json.dumps(state, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).digest()
