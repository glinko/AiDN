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
from aidn_hypervisor.consensus.coverage import (
    VALIDATION_EVIDENCE_OPERATION_TYPES,
    strict_operation_coverage_error,
    strict_operation_version_error,
)
from aidn_hypervisor.consensus.epoch_transition_inputs import (
    build_epoch_transition_input_report,
)
from aidn_hypervisor.consensus.execution import compute_execution_state_root
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy
from aidn_hypervisor.consensus.state_store import (
    ABCIStateSnapshot,
    ABCIStateStore,
    ABCIStateStoreError,
)
from aidn_hypervisor.faucet_treasury import (
    FaucetTreasuryManifest,
    validate_faucet_treasury_manifest,
)

# Runtime evidence is persisted in the Hypervisor Ledger for local recovery,
# but it is not a consensus transition. It must not change the CometBFT AppHash
# or make a validator restart discard newer local execution evidence.
LOCAL_ONLY_OPERATION_TYPES = frozenset({"SESSION_RUNTIME_EVIDENCE_COMMIT"})


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
        genesis_treasury_manifest: dict | FaucetTreasuryManifest | None = None,
        state_store: ABCIStateStore | None = None,
        restore_state_from_store: bool = True,
        state_checkpoint_callback: Callable[[], None] | None = None,
        strict_operation_coverage: bool = False,
        protocol_authority_policy: ProtocolAuthorityPolicy | None = None,
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
        self._strict_operation_coverage = strict_operation_coverage
        self._protocol_authority_policy = protocol_authority_policy
        self._restored_from_store = False
        self._pending_commit_snapshot: dict[str, Any] | None = None
        self._pending_commit_admission_state: dict[str, Any] | None = None
        treasury_manifest = (
            genesis_treasury_manifest
            if isinstance(genesis_treasury_manifest, FaucetTreasuryManifest)
            else FaucetTreasuryManifest.model_validate(genesis_treasury_manifest)
            if genesis_treasury_manifest is not None
            else None
        )
        self._genesis_treasury_manifest = (
            treasury_manifest.model_dump(mode="json") if treasury_manifest is not None else None
        )
        if treasury_manifest is not None:
            self.ledger.bind_faucet_treasury_manifest(treasury_manifest)
        persisted_snapshot = (
            state_store.load_current() if state_store is not None and restore_state_from_store else None
        )
        # Genesis inputs are only applied while creating a new ABCI state. A
        # restart must bind the configured manifest to the durable snapshot,
        # never project its balance a second time.
        if treasury_manifest is not None and persisted_snapshot is None:
            genesis_accounts = dict(genesis_accounts or {})
            treasury_accounts = (
                treasury_manifest.genesis_accounts()
                if treasury_manifest.funding_mode == "GENESIS"
                else {}
            )
            for wallet_id, amount in treasury_accounts.items():
                existing = genesis_accounts.get(wallet_id)
                if existing is not None and existing != amount:
                    raise ValueError("Genesis Treasury allocation conflicts with genesis account")
                genesis_accounts[wallet_id] = amount

        if persisted_snapshot is not None:
            if genesis_accounts:
                raise ValueError("genesis accounts cannot be applied over durable ABCI state")
            snapshot_manifest = persisted_snapshot.get("genesis_treasury_manifest")
            if snapshot_manifest is not None:
                persisted_manifest = FaucetTreasuryManifest.model_validate(snapshot_manifest)
                if (
                    treasury_manifest is not None
                    and persisted_manifest.manifest_hash != treasury_manifest.manifest_hash
                ):
                    raise ValueError("durable ABCI Treasury manifest does not match configured Genesis")
                self._genesis_treasury_manifest = persisted_manifest.model_dump(mode="json")
                self.ledger.bind_faucet_treasury_manifest(persisted_manifest)
            elif treasury_manifest is not None:
                raise ValueError("durable ABCI state is missing the configured Treasury manifest")
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
            # Older validators included transaction_hash in the operation
            # projection.  That field is transport evidence, not consensus
            # state, so migrate only when the mismatch is exactly that known
            # serialization change. Any other divergence remains fatal.
            legacy_hash = self._compute_state_hash(include_transaction_hash_metadata=True)
            if expected_hash != legacy_hash:
                raise ABCIStateStoreError("durable ABCI state does not match the restored Hypervisor Ledger")
            self._restore_snapshot_metadata(snapshot, app_hash_override=actual_hash)
            self._restored_from_store = True
            self._persist_abci_state()
            return True
        self._restore_snapshot_metadata(snapshot)
        self._restored_from_store = True
        return True

    def reconcile_durable_state_to_canonical_ledger(self) -> bool:
        """Restore a verified durable Ledger projection when local state lags.

        A validator restart may load an older Hypervisor snapshot that has the
        same operation history but is missing consensus-owned derived state.
        In that case comparing roots alone is too strict, while blindly
        replacing local state is unsafe.  The durable ABCI snapshot is the
        canonical source for the Ledger projection, so reconciliation is
        allowed only when local operations are a subset of the durable set and
        no legacy local-only operation is present.

        Provider, Bundle and other Hypervisor-local objects are intentionally
        left untouched; ``apply_snapshot`` replaces only the bound Ledger and
        ABCI metadata.  A caller must persist the resulting Hypervisor state.
        """
        if self._state_store is None:
            raise ABCIStateStoreError("durable ABCI state is disabled")
        snapshot = self._state_store.load_current()
        if snapshot is None:
            return False

        local_operations = self.ledger.snapshot_operations()
        durable_operations = snapshot.get("ledger_operations", [])
        if not isinstance(durable_operations, list):
            raise ABCIStateStoreError("durable ABCI Ledger projection is invalid")

        def normalized_operations(operations: list[dict]) -> dict[str, dict]:
            result: dict[str, dict] = {}
            for operation in operations:
                if not isinstance(operation, dict) or not operation.get("operation_id"):
                    raise ABCIStateStoreError("ABCI Ledger operation is invalid")
                operation_id = str(operation["operation_id"])
                result[operation_id] = {
                    key: value for key, value in operation.items() if key != "transaction_hash"
                }
            return result

        local_by_id = normalized_operations(local_operations)
        durable_by_id = normalized_operations(durable_operations)
        for operation_id, operation in local_by_id.items():
            if durable_by_id.get(operation_id) != operation:
                raise ABCIStateStoreError(
                    "local Hypervisor Ledger contains operations absent from durable ABCI state"
                )
        if any(
            operation.get("operation_type") == "ENDPOINT_UPDATE"
            for operation in durable_operations
            if isinstance(operation, dict)
        ):
            raise ABCIStateStoreError(
                "durable ABCI state contains a non-canonical Endpoint update"
            )

        current_projection = self.prepare_snapshot()
        if current_projection["wallet_sequences"] != snapshot.get("wallet_sequences", {}):
            raise ABCIStateStoreError(
                "local Hypervisor Ledger wallet sequences do not match durable ABCI state"
            )
        current_settlement = dict(current_projection["settlement_state"])
        durable_settlement = dict(snapshot.get("settlement_state", {}))
        current_ready = current_settlement.pop("settlement_ready_commits", [])
        durable_ready = durable_settlement.pop("settlement_ready_commits", [])
        if current_settlement != durable_settlement:
            raise ABCIStateStoreError(
                "local Hypervisor Ledger settlement state does not match durable ABCI state"
            )
        if current_ready not in ([], durable_ready):
            raise ABCIStateStoreError(
                "local Hypervisor Ledger checkpoint state does not match durable ABCI state"
            )
        current_consensus = current_projection.get("consensus_state") or {}
        durable_consensus = snapshot.get("consensus_state") or {}
        current_has_consensus_state = bool(
            current_consensus.get("active_validator_set")
            or current_consensus.get("active_validator_set_epoch") is not None
            or current_consensus.get("activated_validator_set_epochs")
        )
        if current_has_consensus_state and current_consensus != durable_consensus:
            raise ABCIStateStoreError(
                "local Hypervisor Ledger consensus state does not match durable ABCI state"
            )

        result = self.apply_snapshot(snapshot)
        if result.code != "ok":
            raise ABCIStateStoreError(result.log or "could not reconcile durable ABCI state")
        self._restored_from_store = True
        return True

    def _restore_snapshot_metadata(
        self,
        snapshot: dict[str, Any],
        *,
        app_hash_override: bytes | None = None,
    ) -> None:
        """Restore consensus metadata without overwriting local Hypervisor state."""
        try:
            last_block_height = int(snapshot["last_block_height"])
            last_block_hash = bytes.fromhex(str(snapshot["last_block_hash"]))
            app_hash = app_hash_override or self._snapshot_app_hash(snapshot)
        except (KeyError, TypeError, ValueError) as error:
            raise ABCIStateStoreError("durable ABCI metadata is invalid") from error
        if last_block_height < 0 or len(last_block_hash) != 32 or len(app_hash) != 32:
            raise ABCIStateStoreError("durable ABCI metadata hash or height is invalid")
        try:
            commitments = {
                commitment["height"]: ABCICanonicalCommitment(**commitment)
                for commitment in snapshot.get("commitments", [])
            }
        except (KeyError, TypeError, ValueError) as error:
            raise ABCIStateStoreError("durable ABCI commitments are invalid") from error

        self._last_block_height = last_block_height
        self._last_block_hash = last_block_hash
        self._app_hash = app_hash
        self._genesis_time = snapshot.get("genesis_time", self._genesis_time)
        self._commitments = commitments
        # The Hypervisor Ledger is the authoritative local snapshot here. Local
        # evidence may be newer than the last committed ABCI snapshot, so do not
        # replace its wallet sequence state while restoring consensus metadata.
        # Canonical replay protection is queried from the Ledger per CheckTx.
        # Keep the process-local cache empty so a reset cannot retain IDs from
        # a discarded chain generation.
        self._admission.restore_state(
            {
                "finalized_ids": set(),
                "wallet_sequences": {
                    str(wallet_id): int(sequence)
                    for wallet_id, sequence in self.ledger.snapshot_wallet_sequences().items()
                },
            }
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

        if not recheck:
            finalized_error = self._canonical_finalized_operation_error(envelope)
            if finalized_error is not None:
                return ABCIResult(
                    code="rejected",
                    log=finalized_error,
                    tags=[
                        ABCITag(key="operation_id", value=envelope.operation_id),
                        ABCITag(key="reason", value=finalized_error),
                    ],
                )

        # Admission check
        admission = self._admission.validate(envelope)
        if (
            not admission.admitted
            and admission.reason == "duplicate_operation_id"
            # The canonical registry was checked immediately above. A duplicate
            # only in AdmissionValidator is stale process memory, not a replay.
            and envelope.operation_id not in self._finalized_operation_ids()
        ):
            self._admission.discard_finalized(envelope.operation_id)
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

        if not recheck:
            special_error = self._special_operation_error(
                envelope,
                finalized_operation_ids=self._finalized_operation_ids(),
            )
            if special_error is not None:
                return ABCIResult(
                    code="rejected",
                    log=special_error,
                    tags=[
                        ABCITag(key="operation_id", value=envelope.operation_id),
                        ABCITag(key="reason", value=special_error),
                    ],
                )

        authority_error = self._protocol_authority_error(envelope)
        if authority_error is not None:
            return ABCIResult(
                code="rejected",
                log=authority_error,
                tags=[
                    ABCITag(key="operation_id", value=envelope.operation_id),
                    ABCITag(key="reason", value=authority_error),
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
                if (
                    envelope.operation_id in selected_ids
                    or self._canonical_finalized_operation_error(envelope) is not None
                    or not self._admission.validate(envelope).admitted
                ):
                    continue
                if (
                    self._special_operation_error(
                        envelope,
                        finalized_operation_ids=self._finalized_operation_ids(),
                    )
                    is not None
                ):
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
        finalized_operation_ids = self._finalized_operation_ids()
        for tx_data in txs:
            try:
                envelope = self._parse_envelope(tx_data)
            except Exception as error:
                return ABCIResult(code="invalid", log=f"parse error: {error}")
            if envelope.operation_id in operation_ids:
                return ABCIResult(code="duplicate", log="duplicate operation in proposal")
            operation_ids.add(envelope.operation_id)
            finalized_error = self._canonical_finalized_operation_error(
                envelope,
                finalized_operation_ids=finalized_operation_ids,
            )
            if finalized_error is not None:
                return ABCIResult(code="rejected", log=finalized_error)
            admission = self._admission.validate(envelope)
            if not admission.admitted:
                return ABCIResult(code="rejected", log=admission.reason or "admission failed")
            special_error = self._special_operation_error(
                envelope,
                finalized_operation_ids=finalized_operation_ids,
            )
            if special_error is not None:
                return ABCIResult(code="rejected", log=special_error)
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
        if result.code == "ok":
            try:
                self.commit()
            except ABCIStateStoreError as error:
                return ABCIResult(code="internal", log=str(error))
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
        finalized_operation_ids = self._finalized_operation_ids()
        validator_updates: list[dict] = []

        for tx_data in txs:
            result = self._execute_one(
                tx_data,
                finalized_operation_ids=finalized_operation_ids,
            )
            tx_results.append(result)
            if result.code == "ok":
                executed.append(result)
                if result.tags:
                    events.extend([t.key + "=" + t.value for t in result.tags])
            else:
                rejected.append(result)

        # A Validator Set schedule is only activated at the matching Epoch
        # transition and only when it was finalized before this block.
        try:
            for result, tx_data in zip(tx_results, txs, strict=True):
                if result.code != "ok":
                    continue
                envelope = self._parse_envelope(tx_data)
                if envelope.operation_type != "EPOCH_TRANSITION":
                    continue
                validator_updates.extend(
                    self.ledger.activate_consensus_validator_set_update(
                        activation_epoch=int(envelope.payload["opening_epoch"]),
                        finalized_operation_ids=finalized_operation_ids,
                    )
                )
        except (ValueError, TypeError, KeyError) as error:
            rollback = self.apply_snapshot(previous_snapshot)
            self._admission.restore_state(previous_admission_state)
            rollback_note = "" if rollback.code == "ok" else "; rollback failed"
            failure = ABCIResult(
                code="internal",
                log=f"validator set activation failed: {error}{rollback_note}",
            )
            return failure, [failure for _ in txs]

        # Update state
        self._last_block_height = block_height
        self._last_block_hash = block_hash
        self._app_hash = self._compute_state_hash()
        self._commitments[block_height] = ABCICanonicalCommitment(
            height=block_height,
            block_hash=block_hash.hex().upper(),
            app_hash=self._app_hash.hex().upper(),
        )

        # CometBFT persists the finalized application state only in the
        # subsequent Commit call.  Keep the pre-block state in memory so a
        # failed Commit can roll back both the Ledger and admission projection.
        if self._pending_commit_snapshot is None:
            self._pending_commit_snapshot = previous_snapshot
            self._pending_commit_admission_state = previous_admission_state

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
            validator_updates=validator_updates,
        ), tx_results

    def commit(self) -> ABCICommitResponse:
        """RFC-0047 §16 — State commitment after block finalization."""
        app_hash = self._compute_state_hash()
        self._app_hash = app_hash

        pending_snapshot = self._pending_commit_snapshot
        pending_admission_state = self._pending_commit_admission_state
        if pending_snapshot is not None:
            try:
                self._persist_durable_state()
            except ABCIStateStoreError as error:
                rollback = self.apply_snapshot(pending_snapshot)
                if pending_admission_state is not None:
                    self._admission.restore_state(pending_admission_state)
                rollback_note = "" if rollback.code == "ok" else "; rollback failed"
                if rollback.code == "ok":
                    try:
                        self._persist_abci_state()
                    except ABCIStateStoreError:
                        rollback_note += "; durable rollback failed"
                self._pending_commit_snapshot = None
                self._pending_commit_admission_state = None
                raise ABCIStateStoreError(
                    f"durable state persistence failed: {error}{rollback_note}"
                ) from error
            self._pending_commit_snapshot = None
            self._pending_commit_admission_state = None

        return ABCICommitResponse(
            data=app_hash,
            version=str(self._last_block_height),
        )

    def preview_commit(self) -> ABCICommitResponse:
        """Return the post-FinalizeBlock hash without persisting application state."""
        return ABCICommitResponse(
            data=self._compute_state_hash(),
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
        elif path.startswith("wallet/identity/"):
            wallet_id = path.split("/")[-1]
            identity = self.ledger.canonical_wallet_identity(wallet_id)
            kwargs["key"] = f"wallet:{wallet_id}:identity".encode()
            kwargs["value"] = (
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
                if identity is not None
                else b""
            )
        elif path.startswith("operation/finalized/"):
            operation_id = path.removeprefix("operation/finalized/")
            reference = self.ledger.finalized_operation_reference(operation_id)
            kwargs["key"] = f"operation:{operation_id}:finalized".encode()
            # Expose replay provenance only; payloads and signatures remain
            # restricted settlement and execution evidence.
            kwargs["value"] = (
                json.dumps(reference, sort_keys=True, separators=(",", ":")).encode("utf-8")
                if reference is not None
                else b""
            )
        elif path == "faucet/treasury-manifest":
            kwargs["key"] = b"faucet:treasury:manifest"
            kwargs["value"] = (
                json.dumps(
                    self._genesis_treasury_manifest,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                if self._genesis_treasury_manifest is not None
                else b""
            )
        elif path == "faucet/treasury-funding":
            funding_record = self.ledger.faucet_treasury_funding_record()
            kwargs["key"] = b"faucet:treasury:funding"
            kwargs["value"] = (
                json.dumps(
                    funding_record,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                if funding_record is not None
                else b""
            )
        elif path == "protocol/authority-policy":
            policy = self._protocol_authority_policy
            configured = bool(policy is not None and policy.authorities)
            value = {
                "version": policy.version if configured else None,
                "configured": configured,
                "policy_hash": policy.policy_hash if configured else None,
                "threshold": policy.threshold if configured else None,
                "authority_count": len(policy.authorities) if configured else 0,
                "epoch_transition_mode": (
                    "THRESHOLD_AUTHORIZED" if configured else "FAIL_CLOSED"
                ),
            }
            kwargs["key"] = b"protocol:authority-policy"
            kwargs["value"] = json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        elif path == "epoch/transition-inputs":
            report = self.epoch_transition_input_report()
            kwargs["key"] = b"epoch:transition-inputs"
            kwargs["value"] = json.dumps(
                report,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        elif path == "development/reward-preflight" or path.startswith("development/reward-preflight/"):
            pool_id = path.removeprefix("development/reward-preflight/") or "GENERAL_DEVELOPMENT"
            try:
                preflight = self.ledger.development_reward_preflight(pool_id=pool_id)
            except ValueError:
                preflight = None
            kwargs["key"] = f"development:reward-preflight:{pool_id}".encode()
            kwargs["value"] = (
                json.dumps(preflight, sort_keys=True, separators=(",", ":")).encode("utf-8")
                if preflight is not None
                else b""
            )
        elif path.startswith("endpoint/publication/"):
            endpoint_id = path.removeprefix("endpoint/publication/")
            publication = self.ledger.canonical_endpoint_publication(endpoint_id)
            kwargs["key"] = f"endpoint:{endpoint_id}:publication".encode()
            kwargs["value"] = (
                json.dumps(publication, sort_keys=True, separators=(",", ":")).encode()
                if publication is not None
                else b""
            )
        elif path == "mempool/size":
            kwargs["key"] = b"mempool_size"
            kwargs["value"] = str(self.mempool.size()).encode()
        else:
            kwargs["key"] = b"unknown_path"
            kwargs["value"] = b""

        return ABCIQueryResponse(**kwargs)

    def epoch_transition_input_report(self) -> dict:
        """Expose only roots observed from the current canonical state.

        Epoch boundaries, task results, eligibility and reward roots are not
        inferred here.  The resulting BLOCKED report is intentional until a
        live Epoch Engine publishes those artifacts.
        """
        closing_height = self._last_block_height or None
        closing_block_hash = (
            "sha256:" + self._last_block_hash.hex() if closing_height is not None else None
        )
        closing_state_root = (
            "sha256:" + compute_execution_state_root(self.ledger)
            if closing_height is not None
            else None
        )
        source_app_hash = "sha256:" + self._app_hash.hex() if self._app_hash else None
        return build_epoch_transition_input_report(
            closing_height=closing_height,
            closing_block_hash=closing_block_hash,
            closing_state_root=closing_state_root,
            source_app_hash=source_app_hash,
        ).model_dump(mode="json")

    # ---- Snapshot ----

    def prepare_snapshot(self) -> dict:
        """Export application state for snapshot."""
        snapshot = {
            "app_version": self.APP_VERSION,
            "protocol_version": self.PROTOCOL_VERSION,
            "genesis_time": self._genesis_time,
            "last_block_height": self._last_block_height,
            "last_block_hash": self._last_block_hash.hex(),
            "app_hash": self._compute_state_hash().hex(),
            "state_root": compute_execution_state_root(self.ledger),
            "commitments": [asdict(commitment) for commitment in self._commitments.values()],
            "ledger_operations": self.ledger.snapshot_operations(),
            "wallet_sequences": self.ledger.snapshot_wallet_sequences(),
            "settlement_state": self.ledger.snapshot_settlement_state(),
            "consensus_state": self.ledger.snapshot_consensus_state(),
        }
        if self._genesis_treasury_manifest is not None:
            snapshot["genesis_treasury_manifest"] = dict(self._genesis_treasury_manifest)
        return snapshot

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
        snapshot_manifest = snapshot.get("genesis_treasury_manifest")
        if snapshot_manifest is not None:
            manifest = validate_faucet_treasury_manifest(
                FaucetTreasuryManifest.model_validate(snapshot_manifest)
            )
            if (
                self._genesis_treasury_manifest is not None
                and self._genesis_treasury_manifest["manifest_hash"] != manifest.manifest_hash
            ):
                raise ValueError("snapshot Treasury manifest does not match configured Genesis")
            self._genesis_treasury_manifest = manifest.model_dump(mode="json")
            self.ledger.bind_faucet_treasury_manifest(manifest)
        elif self._genesis_treasury_manifest is not None:
            raise ValueError("snapshot is missing the configured Treasury manifest")
        settlement_state = snapshot.get("settlement_state", {})
        self.ledger.restore(
            operations=snapshot.get("ledger_operations", []),
            wallet_sequences=snapshot.get("wallet_sequences", {}),
            wallet_q_atom_balances=settlement_state.get("wallet_q_atom_balances"),
            recyclable_q_atoms=int(settlement_state.get("recyclable_q_atoms", 0)),
            burned_q_atoms=int(settlement_state.get("burned_q_atoms", 0)),
            stake_records=settlement_state.get("stake_records"),
            participant_suspensions=settlement_state.get("participant_suspensions"),
            session_funding_accounts=settlement_state.get("session_funding_accounts"),
            settlement_ready_commits=settlement_state.get("settlement_ready_commits"),
            settlement_proposals=settlement_state.get("settlement_proposals"),
            settlement_acceptances=settlement_state.get("settlement_acceptances"),
            session_checkpoints=settlement_state.get("session_checkpoints"),
            settlement_disputes=settlement_state.get("settlement_disputes"),
            settlement_corrections=settlement_state.get("settlement_corrections"),
            settlement_transition_hashes=settlement_state.get("settlement_transition_hashes"),
            development_pool_allocations=settlement_state.get("development_pool_allocations"),
            development_pool_carryovers=settlement_state.get("development_pool_carryovers"),
            development_bounty_states=settlement_state.get("development_bounty_states"),
            development_reward_reserves=settlement_state.get("development_reward_reserves"),
            development_reward_payment_records=settlement_state.get("development_reward_payment_records"),
            development_reward_unclaimed_records=settlement_state.get("development_reward_unclaimed_records"),
            development_reward_claim_records=settlement_state.get("development_reward_claim_records"),
            development_reward_expiry_records=settlement_state.get("development_reward_expiry_records"),
            development_reward_finalized_commitments=settlement_state.get("development_reward_finalized_commitments"),
            development_reward_adjustment_snapshots=settlement_state.get("development_reward_adjustment_snapshots"),
            development_reward_cancellations=settlement_state.get("development_reward_cancellations"),
            development_reward_corrections=settlement_state.get("development_reward_corrections"),
            consensus_state=snapshot.get("consensus_state"),
        )
        self._last_block_height = int(snapshot["last_block_height"])
        if self._last_block_height < 0:
            raise ValueError("snapshot height is invalid")
        self._last_block_hash = bytes.fromhex(snapshot["last_block_hash"])
        self._app_hash = self._snapshot_app_hash(snapshot)
        if len(self._last_block_hash) != 32 or len(self._app_hash) != 32:
            raise ValueError("snapshot hash length is invalid")
        declared_state_root = snapshot.get("state_root")
        if declared_state_root is not None:
            if (
                not isinstance(declared_state_root, str)
                or len(declared_state_root) != 64
                or declared_state_root != compute_execution_state_root(self.ledger)
            ):
                raise ValueError("snapshot state root does not match state")
        self._genesis_time = snapshot.get("genesis_time", self._genesis_time)
        self._commitments = {
            commitment["height"]: ABCICanonicalCommitment(**commitment)
            for commitment in snapshot.get("commitments", [])
        }
        if self._compute_state_hash() != self._app_hash:
            raise ValueError("snapshot application hash does not match state")
        # Wallet sequences are part of the executable consensus projection.
        # Finalized operation IDs are checked directly against the restored
        # canonical Ledger so a process-local cache cannot survive a reset.
        self._admission.restore_state(
            {
                "finalized_ids": set(),
                "wallet_sequences": {
                    str(wallet_id): int(sequence)
                    for wallet_id, sequence in snapshot.get("wallet_sequences", {}).items()
                },
            }
        )

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
                raise ABCIStateStoreError("Hypervisor state checkpoint failed after ABCI persistence") from error

    def _persist_abci_state(self) -> None:
        if self._state_store is not None:
            self._state_store.persist(self.prepare_snapshot())

    # ---- Internal helpers ----

    def _parse_envelope(self, tx_data: bytes) -> LedgerOperationEnvelope:
        """Parse raw bytes into LedgerOperationEnvelope."""
        obj = json.loads(tx_data)
        return LedgerOperationEnvelope.model_validate(obj)

    def _execute_one(
        self,
        tx_data: bytes,
        *,
        finalized_operation_ids: set[str],
    ) -> ABCIResult:
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

        authority_error = self._protocol_authority_error(envelope)
        if authority_error is not None:
            return ABCIResult(
                code="rejected",
                log=authority_error,
                tags=[
                    ABCITag(key="operation_id", value=envelope.operation_id),
                    ABCITag(key="reason", value=authority_error),
                ],
            )

        coverage_error = self._operation_coverage_error(envelope.operation_type)
        if coverage_error is not None:
            return ABCIResult(
                code="rejected",
                log=coverage_error,
                tags=[
                    ABCITag(key="operation_id", value=envelope.operation_id),
                    ABCITag(key="reason", value=coverage_error),
                ],
            )

        # Record in ledger
        try:
            if envelope.operation_type == "WALLET_TRANSFER" and self._strict_operation_coverage:
                self.ledger.apply_consensus_wallet_transfer(envelope)
            elif envelope.operation_type == "WALLET_IDENTITY_REGISTER":
                self.ledger.apply_consensus_wallet_identity_register(envelope)
            elif envelope.operation_type == "OPERATOR_WALLET_BIND":
                self.ledger.apply_consensus_operator_wallet_bind(envelope)
            elif envelope.operation_type == "ENDPOINT_PUBLISH":
                self.ledger.apply_consensus_endpoint_publish(envelope)
            elif envelope.operation_type == "SESSION_OPEN" and self._strict_operation_coverage:
                self.ledger.apply_consensus_session_open(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_ACCEPT" and self._strict_operation_coverage:
                self.ledger.apply_consensus_session_accept(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "EPOCH_TRANSITION":
                self.ledger.apply_consensus_epoch_transition(envelope)
            elif envelope.operation_type == "SERVICE_VERIFICATION_COMMIT":
                self.ledger.apply_consensus_service_verification(envelope)
            elif envelope.operation_type == "REPUTATION_PROFILE_UPDATE":
                self.ledger.apply_consensus_reputation_profile_update(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type in VALIDATION_EVIDENCE_OPERATION_TYPES:
                self.ledger.apply_consensus_validation_evidence(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SNAPSHOT_COMMIT":
                self.ledger.apply_consensus_snapshot_commit(envelope)
            elif envelope.operation_type == "SESSION_FAILURE_EVIDENCE":
                self.ledger.apply_consensus_session_failure_evidence(envelope)
            elif envelope.operation_type == "CONSENSUS_VALIDATOR_SET_UPDATE":
                self.ledger.apply_consensus_validator_set_update(envelope)
            elif envelope.operation_type == "TREASURY_MANIFEST_BIND":
                self.ledger.apply_consensus_treasury_manifest_bind(envelope)
                self._genesis_treasury_manifest = self.ledger.faucet_treasury_manifest()
            elif envelope.operation_type == "TREASURY_FUND":
                self.ledger.apply_consensus_treasury_fund(envelope)
            elif envelope.operation_type == "REWARD_MINT":
                self.ledger.apply_consensus_reward_mint(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_CALCULATE":
                self.ledger.apply_consensus_development_reward_calculate(envelope)
            elif envelope.operation_type == "DEVELOPMENT_POOL_ALLOCATE":
                self.ledger.apply_consensus_development_pool_allocate(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_POOL_CARRYOVER":
                self.ledger.apply_consensus_development_pool_carryover(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_BOUNTY_CREATE":
                self.ledger.apply_consensus_development_bounty_create(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_BOUNTY_RESERVE":
                self.ledger.apply_consensus_development_bounty_reserve(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_BOUNTY_RELEASE":
                self.ledger.apply_consensus_development_bounty_release(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_BOUNTY_EXPIRE":
                self.ledger.apply_consensus_development_bounty_expire(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_RESERVE":
                self.ledger.apply_consensus_development_reward_reserve(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_PAY_IMMEDIATE":
                self.ledger.apply_consensus_development_reward_pay_immediate(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_PAY_MATURITY":
                self.ledger.apply_consensus_development_reward_pay_maturity(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_MARK_UNCLAIMED":
                self.ledger.apply_consensus_development_reward_mark_unclaimed(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_CLAIM":
                self.ledger.apply_consensus_development_reward_claim(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED":
                self.ledger.apply_consensus_development_reward_expire_unclaimed(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_FINALIZE_COMMITMENT":
                self.ledger.apply_consensus_development_reward_finalize_commitment(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_CANCEL_UNVESTED":
                self.ledger.apply_consensus_development_reward_cancel_unvested(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_CORRECT":
                self.ledger.apply_consensus_development_reward_correct(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "PENALTY_APPLY":
                self.ledger.apply_consensus_penalty_apply(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_ESCROW_LOCK":
                self.ledger.apply_consensus_session_escrow_lock(envelope)
            elif envelope.operation_type == "SESSION_ESCROW_EXTEND":
                self.ledger.apply_consensus_session_escrow_extend(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_ESCROW_RELEASE":
                self.ledger.apply_consensus_session_escrow_release(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_CHECKPOINT_COMMIT":
                self.ledger.apply_consensus_session_checkpoint_commit(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_SETTLEMENT_READY_COMMIT":
                self.ledger.apply_consensus_settlement_ready_commit(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_SETTLEMENT_PROPOSE":
                self.ledger.apply_consensus_settlement_propose(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_SETTLEMENT_ACCEPT":
                self.ledger.apply_consensus_settlement_accept(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_SETTLEMENT_DISPUTE":
                self.ledger.apply_consensus_settlement_dispute(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_SETTLEMENT_PARTIAL_FINALIZE":
                self.ledger.apply_consensus_settlement_partial_finalize(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_SETTLEMENT_CORRECT":
                self.ledger.apply_consensus_settlement_correct(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_SETTLEMENT_FINALIZE":
                self.ledger.apply_consensus_settlement_finalize(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_FORCE_SETTLE":
                self.ledger.apply_consensus_force_settle(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "STAKE_LOCK":
                self.ledger.apply_consensus_stake_lock(envelope)
            elif envelope.operation_type == "UNSTAKE_REQUEST":
                self.ledger.apply_consensus_unstake_request(envelope)
            elif envelope.operation_type == "STAKE_RELEASE":
                self.ledger.apply_consensus_stake_release(envelope)
            elif envelope.operation_type == "PARTICIPANT_SUSPEND":
                self.ledger.apply_consensus_participant_suspend(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "PARTICIPANT_REINSTATE":
                self.ledger.apply_consensus_participant_reinstate(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            else:
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
        except ValueError as e:
            return ABCIResult(
                code="rejected",
                log=str(e),
                tags=[ABCITag(key="operation_id", value=envelope.operation_id)],
            )
        except Exception as e:
            return ABCIResult(
                code="internal",
                log=f"execution error: {e}",
            )

    def _finalized_operation_ids(self) -> set[str]:
        finalized_operation_ids = getattr(self.ledger, "finalized_operation_ids", None)
        if callable(finalized_operation_ids):
            return set(finalized_operation_ids())
        return {
            str(operation["operation_id"])
            for operation in self.ledger.snapshot_operations()
            if operation.get("operation_id")
        }

    def _canonical_finalized_operation_error(
        self,
        envelope: LedgerOperationEnvelope,
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> str | None:
        """Return the deterministic replay result from the canonical Ledger.

        AdmissionValidator's finalized-ID set is intentionally process-local:
        it accelerates a running node but is not an authority after restart or
        a controlled chain reset. The Ledger replay registry is the committed
        source of truth. Typed operations retain their domain-specific replay
        error; a completed Wallet transfer has no richer replay state and uses
        the stable generic code.
        """

        operation_ids = (
            finalized_operation_ids
            if finalized_operation_ids is not None
            else self._finalized_operation_ids()
        )
        if envelope.operation_id not in operation_ids:
            return None
        if envelope.operation_type == "WALLET_TRANSFER":
            return "duplicate_operation_id"
        return (
            self._special_operation_error(
                envelope,
                finalized_operation_ids=operation_ids,
            )
            or "duplicate_operation_id"
        )

    def _special_operation_error(
        self,
        envelope: LedgerOperationEnvelope,
        *,
        finalized_operation_ids: set[str],
    ) -> str | None:
        coverage_error = self._operation_coverage_error(envelope.operation_type)
        if coverage_error is not None:
            return coverage_error
        version_error = strict_operation_version_error(
            envelope.operation_type,
            envelope.operation_version,
        )
        if version_error is not None:
            return version_error
        authority_error = self._protocol_authority_error(envelope)
        if authority_error is not None:
            return authority_error
        try:
            if envelope.operation_type == "WALLET_TRANSFER" and self._strict_operation_coverage:
                self.ledger.validate_consensus_wallet_transfer(envelope)
            elif envelope.operation_type == "WALLET_IDENTITY_REGISTER":
                self.ledger.validate_consensus_wallet_identity_register(envelope)
            elif envelope.operation_type == "OPERATOR_WALLET_BIND":
                self.ledger.validate_consensus_operator_wallet_bind(envelope)
            elif envelope.operation_type == "ENDPOINT_PUBLISH":
                self.ledger.validate_consensus_endpoint_publish(envelope)
            elif envelope.operation_type == "SESSION_OPEN" and self._strict_operation_coverage:
                self.ledger.validate_consensus_session_open(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_ACCEPT" and self._strict_operation_coverage:
                self.ledger.validate_consensus_session_accept(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "EPOCH_TRANSITION":
                self.ledger.validate_consensus_epoch_transition(envelope)
            elif envelope.operation_type == "SERVICE_VERIFICATION_COMMIT":
                self.ledger.validate_consensus_service_verification(envelope)
            elif envelope.operation_type == "SNAPSHOT_COMMIT":
                self.ledger.validate_consensus_snapshot_commit(envelope)
            elif envelope.operation_type == "SESSION_FAILURE_EVIDENCE":
                self.ledger.validate_consensus_session_failure_evidence(envelope)
            elif envelope.operation_type == "CONSENSUS_VALIDATOR_SET_UPDATE":
                self.ledger.validate_consensus_validator_set_update(envelope)
            elif envelope.operation_type == "TREASURY_MANIFEST_BIND":
                self.ledger.validate_consensus_treasury_manifest_bind(envelope)
            elif envelope.operation_type == "TREASURY_FUND":
                self.ledger.validate_consensus_treasury_fund(envelope)
            elif envelope.operation_type == "REWARD_MINT":
                self.ledger.validate_consensus_reward_mint(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_CALCULATE":
                self.ledger.validate_consensus_development_reward_calculate(envelope)
            elif envelope.operation_type == "DEVELOPMENT_POOL_ALLOCATE":
                self.ledger.validate_consensus_development_pool_allocate(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_POOL_CARRYOVER":
                self.ledger.validate_consensus_development_pool_carryover(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_BOUNTY_CREATE":
                self.ledger.validate_consensus_development_bounty_create(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_BOUNTY_RESERVE":
                self.ledger.validate_consensus_development_bounty_reserve(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_BOUNTY_RELEASE":
                self.ledger.validate_consensus_development_bounty_release(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_BOUNTY_EXPIRE":
                self.ledger.validate_consensus_development_bounty_expire(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_RESERVE":
                self.ledger.validate_consensus_development_reward_reserve(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_PAY_IMMEDIATE":
                self.ledger.validate_consensus_development_reward_pay_immediate(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_PAY_MATURITY":
                self.ledger.validate_consensus_development_reward_pay_maturity(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_MARK_UNCLAIMED":
                self.ledger.validate_consensus_development_reward_mark_unclaimed(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_CLAIM":
                self.ledger.validate_consensus_development_reward_claim(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED":
                self.ledger.validate_consensus_development_reward_expire_unclaimed(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_FINALIZE_COMMITMENT":
                self.ledger.validate_consensus_development_reward_finalize_commitment(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_CANCEL_UNVESTED":
                self.ledger.validate_consensus_development_reward_cancel_unvested(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "DEVELOPMENT_REWARD_CORRECT":
                self.ledger.validate_consensus_development_reward_correct(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "PENALTY_APPLY":
                self.ledger.validate_consensus_penalty_apply(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_ESCROW_LOCK":
                self.ledger.validate_consensus_session_escrow_lock(envelope)
            elif envelope.operation_type == "SESSION_ESCROW_EXTEND":
                self.ledger.validate_consensus_session_escrow_extend(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_ESCROW_RELEASE":
                self.ledger.validate_consensus_session_escrow_release(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_CHECKPOINT_COMMIT":
                self.ledger.validate_consensus_session_checkpoint_commit(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_SETTLEMENT_READY_COMMIT":
                self.ledger.validate_consensus_settlement_ready_commit(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_SETTLEMENT_PROPOSE":
                self.ledger.validate_consensus_settlement_propose(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_SETTLEMENT_ACCEPT":
                self.ledger.validate_consensus_settlement_accept(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_SETTLEMENT_DISPUTE":
                self.ledger.validate_consensus_settlement_dispute(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_SETTLEMENT_PARTIAL_FINALIZE":
                self.ledger.validate_consensus_settlement_partial_finalize(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_SETTLEMENT_CORRECT":
                self.ledger.validate_consensus_settlement_correct(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_SETTLEMENT_FINALIZE":
                self.ledger.validate_consensus_settlement_finalize(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "SESSION_FORCE_SETTLE":
                self.ledger.validate_consensus_force_settle(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "STAKE_LOCK":
                self.ledger.validate_consensus_stake_lock(envelope)
            elif envelope.operation_type == "UNSTAKE_REQUEST":
                self.ledger.validate_consensus_unstake_request(envelope)
            elif envelope.operation_type == "STAKE_RELEASE":
                self.ledger.validate_consensus_stake_release(envelope)
            elif envelope.operation_type == "PARTICIPANT_SUSPEND":
                self.ledger.validate_consensus_participant_suspend(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            elif envelope.operation_type == "PARTICIPANT_REINSTATE":
                self.ledger.validate_consensus_participant_reinstate(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
            else:
                return None
        except ValueError as error:
            return str(error)
        return None

    def _protocol_authority_error(
        self,
        envelope: LedgerOperationEnvelope,
    ) -> str | None:
        if envelope.operation_type != "EPOCH_TRANSITION":
            return None
        if self._protocol_authority_policy is None:
            return None
        try:
            self._protocol_authority_policy.verify_epoch_transition(envelope)
        except ValueError as error:
            return str(error)
        return None

    def _operation_coverage_error(self, operation_type: str) -> str | None:
        if not self._strict_operation_coverage:
            return None
        return strict_operation_coverage_error(operation_type)

    def _compute_state_hash(self, *, include_transaction_hash_metadata: bool = False) -> bytes:
        """Compute deterministic hash of current application state."""
        consensus_state = self.ledger.snapshot_consensus_state()
        settlement_state = self._canonical_settlement_state_for_hash(self.ledger.snapshot_settlement_state())
        state = {
            "operations": self._canonical_operations_for_hash(
                self.ledger.snapshot_operations(),
                include_transaction_hash_metadata=include_transaction_hash_metadata,
            ),
            "wallet_sequences": self.ledger.snapshot_wallet_sequences(),
            "settlement_state": settlement_state,
        }
        if (
            consensus_state["active_validator_set"]
            or consensus_state["active_validator_set_epoch"] is not None
            or consensus_state["activated_validator_set_epochs"]
        ):
            state["consensus_state"] = consensus_state
        if self._genesis_treasury_manifest is not None:
            state["genesis_treasury_manifest"] = self._genesis_treasury_manifest
        canonical = json.dumps(state, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).digest()

    @staticmethod
    def _canonical_operations_for_hash(
        operations: list[dict],
        *,
        include_transaction_hash_metadata: bool = False,
    ) -> list[dict]:
        """Project operation records into consensus state.

        ``transaction_hash`` binds a record to transport evidence, but does
        not change the Ledger transition. It must therefore never affect a
        CometBFT AppHash. The opt-in legacy mode exists only to recognize and
        migrate snapshots produced by the short-lived metadata-inclusive
        projection.
        """
        canonical_operations: list[dict] = []
        for operation in operations:
            canonical = dict(operation)
            if canonical.get("operation_type") in LOCAL_ONLY_OPERATION_TYPES:
                continue
            if not include_transaction_hash_metadata or canonical.get("transaction_hash") is None:
                canonical.pop("transaction_hash", None)
            canonical_operations.append(canonical)
        return canonical_operations

    @staticmethod
    def _canonical_settlement_state_for_hash(settlement_state: dict) -> dict:
        """Keep empty post-MVP extensions out of the historical AppHash.

        Older ABCI snapshots did not serialize newer stake, penalty,
        checkpoint and dispute collections. Treating their empty defaults as
        absent preserves replay compatibility while retaining every populated
        extension in the commitment.
        """
        canonical = dict(settlement_state)
        empty_extension_defaults = {
            "recyclable_q_atoms": 0,
            "burned_q_atoms": 0,
            "stake_records": [],
            "participant_suspensions": [],
            "settlement_ready_commits": [],
            "session_checkpoints": [],
            "settlement_disputes": [],
            "settlement_corrections": [],
            "development_pool_allocations": [],
            "development_pool_carryovers": [],
            "development_bounty_states": [],
            "development_reward_reserves": [],
            "development_reward_payment_records": [],
            "development_reward_unclaimed_records": [],
            "development_reward_claim_records": [],
            "development_reward_expiry_records": [],
            "development_reward_finalized_commitments": [],
            "development_reward_adjustment_snapshots": [],
            "development_reward_cancellations": [],
            "development_reward_corrections": [],
        }
        for field_name, default in empty_extension_defaults.items():
            if canonical.get(field_name) == default:
                canonical.pop(field_name, None)
        return canonical

    @staticmethod
    def _snapshot_app_hash(snapshot: dict) -> bytes:
        try:
            return bytes.fromhex(str(snapshot["app_hash"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("snapshot application hash is invalid") from error
