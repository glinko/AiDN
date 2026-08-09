import base64
import binascii
import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from aidn_hypervisor.consensus.replay import FinalizedOperationRegistry
from aidn_hypervisor.ledger.models import (
    LedgerFeeClass,
    LedgerOperationRecord,
    LedgerOperationResult,
    LedgerOriginType,
)
from aidn_hypervisor.settlement.models import (
    AtomicSettlementTransition,
    SessionFundingAccount,
    SessionSettlementAcceptance,
    SessionSettlementProposal,
    SessionUsageCheckpoint,
    SettlementCorrection,
    SettlementDispute,
    SettlementEvaluation,
    SettlementReadyCommitment,
)

if TYPE_CHECKING:
    from aidn_hypervisor.consensus.admission import AdmissionValidator
    from aidn_hypervisor.consensus.finality import ConsensusFinalitySource
    from aidn_hypervisor.consensus.models import LedgerOperationEnvelope


SESSION_FORCE_SETTLE_OPERATION = "SESSION_FORCE_SETTLE"
SESSION_OPEN_OPERATION = "SESSION_OPEN"
SESSION_ACCEPT_OPERATION = "SESSION_ACCEPT"
SESSION_ESCROW_EXTEND_OPERATION = "SESSION_ESCROW_EXTEND"
SESSION_ESCROW_RELEASE_OPERATION = "SESSION_ESCROW_RELEASE"
SESSION_CHECKPOINT_COMMIT_OPERATION = "SESSION_CHECKPOINT_COMMIT"
SESSION_SETTLEMENT_READY_COMMIT_OPERATION = "SESSION_SETTLEMENT_READY_COMMIT"
SESSION_FAILURE_EVIDENCE_OPERATION = "SESSION_FAILURE_EVIDENCE"
SESSION_SETTLEMENT_DISPUTE_OPERATION = "SESSION_SETTLEMENT_DISPUTE"
SESSION_SETTLEMENT_PARTIAL_FINALIZE_OPERATION = "SESSION_SETTLEMENT_PARTIAL_FINALIZE"
SESSION_SETTLEMENT_CORRECT_OPERATION = "SESSION_SETTLEMENT_CORRECT"
CONSENSUS_PENALTY_APPLY_OPERATION = "PENALTY_APPLY"
OPERATOR_WALLET_BIND_OPERATION = "OPERATOR_WALLET_BIND"
ENDPOINT_PUBLISH_OPERATION = "ENDPOINT_PUBLISH"
VALIDATION_REPORT_COMMIT_OPERATION = "VALIDATION_REPORT_COMMIT"
VALIDATION_REPORT_STORAGE_RECEIPT_OPERATION = "VALIDATION_REPORT_STORAGE_RECEIPT"
VALIDATION_REPORT_STORAGE_FAILURE_OPERATION = "VALIDATION_REPORT_STORAGE_FAILURE"
VALIDATION_REPORT_AVAILABILITY_COMMIT_OPERATION = "VALIDATION_REPORT_AVAILABILITY_COMMIT"
VALIDATION_REPORT_CUSTODY_RELEASE_OPERATION = "VALIDATION_REPORT_CUSTODY_RELEASE"
REPUTATION_PROFILE_UPDATE_OPERATION = "REPUTATION_PROFILE_UPDATE"
REPUTATION_FORMULA_VERSION = "reputation.v1"
DEFAULT_UNBONDING_PERIOD_EPOCHS = 14
STANDARD_NETWORK_FEE_Q_ATOMS = 10_000


def _consensus_transaction_hash(envelope: object) -> str:
    """Hash the exact JSON form used by the consensus submission transport."""
    model_dump = getattr(envelope, "model_dump", None)
    if not callable(model_dump):
        raise ValueError("consensus envelope serializer is unavailable")
    transaction_bytes = json.dumps(model_dump(mode="json")).encode("utf-8")
    return hashlib.sha256(transaction_bytes).hexdigest().upper()


def _failure_evidence_classes_for_force_settlement(failure_class: str) -> set[str]:
    if failure_class in {"ENDPOINT_UNAVAILABLE", "ENDPOINT_FAILURE"}:
        return {"ENDPOINT_UNAVAILABLE", "ENDPOINT_FAILURE"}
    if failure_class == "CONSUMER_TIMEOUT_AFTER_COMPLETED_FIXED_PRICE":
        return {"CONSUMER_DISCONNECTED"}
    return {failure_class}


_STAKE_TYPES = frozenset(
    {
        "CONSENSUS_STAKE",
        "VALIDATION_STAKE",
        "REGISTRY_BOND",
        "NODE_ACTIVATION_BOND",
    }
)

_CONSENSUS_PENALTY_TYPES = frozenset(
    {
        "CONSENSUS_SLASH",
        "DOUBLE_SIGNING",
        "FORGED_CONSENSUS_EVIDENCE",
        "UNAUTHORIZED_VALIDATOR_SET_MANIPULATION",
        "REPUTATION_PENALTY",
    }
)

_CONSENSUS_FAILURE_CLASSES = frozenset(
    {
        "CONSUMER_DISCONNECTED",
        "PROVIDER_DISCONNECTED",
        "RUNTIME_FAILURE",
        "ENDPOINT_FAILURE",
        "ENDPOINT_UNAVAILABLE",  # MVP compatibility alias for endpoint timeout
        "UPSTREAM_PROXY_FAILURE",
        "ACCOUNTING_MISMATCH",
        "USAGE_REPORT_TIMEOUT",
        "ACKNOWLEDGEMENT_TIMEOUT",
        "DEPOSIT_EXHAUSTED",
        "SESSION_TIMEOUT",
        "IDLE_TIMEOUT",
        "CONSUMER_FORCE_CLOSE",
        "PROVIDER_FORCE_CLOSE",
        "PROTOCOL_INCOMPATIBILITY",
        "CONSENSUS_INTERRUPTION",
        "STATE_RECOVERY_FAILURE",
        "UNKNOWN_FAILURE",
    }
)


def _canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash_dict(value: dict) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _decode_consensus_public_key(value: object) -> bytes:
    if not isinstance(value, str) or not value.startswith("ed25519:"):
        raise ValueError("validator consensus public key must use ed25519 encoding")
    encoded = value.removeprefix("ed25519:")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("validator consensus public key is invalid") from error
    if len(decoded) != 32:
        raise ValueError("validator consensus public key must contain 32 bytes")
    return decoded


def _with_funding_updates(
    funding: SessionFundingAccount,
    updates: dict,
) -> SessionFundingAccount:
    payload = funding.model_dump(mode="json")
    payload.update(updates)
    payload.pop("funding_state_hash", None)
    return SessionFundingAccount.model_validate(payload)


def _funding_lock_identity(funding: SessionFundingAccount) -> dict:
    payload = funding.model_dump(mode="json")
    payload.pop("funding_state", None)
    payload.pop("funding_state_hash", None)
    return payload


class LedgerOperationService:
    def __init__(self, *, protocol_version: str = "0.1") -> None:
        self.protocol_version = protocol_version
        self._operations: list[dict] = []
        self._operation_ids: set[str] = set()
        self._finalized_operation_registry = FinalizedOperationRegistry()
        self._wallet_next_sequences: dict[str, int] = {}
        self._wallet_q_atom_balances: dict[str, int] = {}
        self._recyclable_q_atoms = 0
        self._burned_q_atoms = 0
        self._stake_records: dict[str, dict] = {}
        self._participant_suspensions: dict[str, dict] = {}
        self._session_funding_accounts: dict[str, SessionFundingAccount] = {}
        # SESSION_OPEN is a canonical lifecycle projection, not another
        # funding mutation. Rebuild this index from the operation log on
        # restore so old snapshots do not need a new state field.
        self._session_open_records: dict[str, dict] = {}
        self._session_accept_records: dict[str, dict] = {}
        self._settlement_proposals: dict[str, SessionSettlementProposal] = {}
        self._settlement_ready_commits: dict[str, SettlementReadyCommitment] = {}
        self._settlement_acceptances: dict[str, SessionSettlementAcceptance] = {}
        self._settlement_disputes: dict[str, SettlementDispute] = {}
        self._settlement_corrections: dict[str, SettlementCorrection] = {}
        self._session_checkpoints: dict[str, SessionUsageCheckpoint] = {}
        self._settlement_transition_hashes: dict[str, str] = {}
        self._development_pool_allocations: dict[str, dict] = {}
        self._development_reward_reserves: dict[str, dict] = {}
        self._development_reward_payment_records: dict[str, dict] = {}
        self._development_reward_unclaimed_records: dict[str, dict] = {}
        self._development_reward_claim_records: dict[str, dict] = {}
        self._development_reward_expiry_records: dict[str, dict] = {}
        self._development_reward_finalized_commitments: dict[str, dict] = {}
        self._development_pool_carryovers: dict[str, dict] = {}
        self._development_bounty_states: dict[str, dict] = {}
        self._development_reward_adjustment_snapshots: dict[str, dict] = {}
        self._development_reward_cancellations: dict[str, dict] = {}
        self._development_reward_corrections: dict[str, dict] = {}
        self._active_validator_set: dict[str, dict] = {}
        self._active_validator_set_epoch: int | None = None
        self._activated_validator_set_epochs: set[int] = set()
        self._next_sequence_id = 1

    def wallet_q_atom_balance(self, wallet_id: str) -> int:
        return int(self._wallet_q_atom_balances.get(wallet_id, 0))

    def credit_wallet_q_atoms(self, *, wallet_id: str, amount_q_atoms: int) -> int:
        if amount_q_atoms < 0:
            raise ValueError("wallet credit must be non-negative")
        balance = self.wallet_q_atom_balance(wallet_id) + int(amount_q_atoms)
        self._wallet_q_atom_balances[wallet_id] = balance
        return balance

    def debit_wallet_q_atoms(self, *, wallet_id: str, amount_q_atoms: int) -> int:
        """Debit Q atoms without allowing a wallet to become negative."""
        if amount_q_atoms <= 0:
            raise ValueError("wallet debit must be positive")
        balance = self.wallet_q_atom_balance(wallet_id)
        if balance < amount_q_atoms:
            raise ValueError("insufficient q_atoms for wallet debit")
        remaining = balance - int(amount_q_atoms)
        self._wallet_q_atom_balances[wallet_id] = remaining
        return remaining

    def validate_consensus_wallet_transfer(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Validate the canonical MVP Wallet transfer transition."""
        if envelope.operation_type != "WALLET_TRANSFER":
            raise ValueError("consensus wallet transfer requires WALLET_TRANSFER operation")
        if envelope.origin_type != "wallet" or envelope.sender_wallet is None:
            raise ValueError("wallet transfer requires wallet origin")
        if envelope.fee_class != "standard":
            raise ValueError("wallet transfer requires standard fee class")
        if envelope.fee_payer != envelope.sender_wallet:
            raise ValueError("wallet transfer fee payer must be the sender Wallet")

        payload = dict(envelope.payload)
        recipient = payload.get("recipient_wallet")
        amount = payload.get("amount")
        if not isinstance(recipient, str) or not recipient.strip():
            raise ValueError("wallet transfer recipient_wallet is invalid")
        if recipient == envelope.sender_wallet:
            raise ValueError("wallet transfer recipient must differ from sender")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("wallet transfer amount is invalid")

        total = amount + STANDARD_NETWORK_FEE_Q_ATOMS
        if self.wallet_q_atom_balance(envelope.sender_wallet) < total:
            raise ValueError("insufficient q_atoms for wallet transfer and fee")
        return {
            "payload": payload,
            "recipient_wallet": recipient,
            "amount_q_atoms": amount,
            "network_fee_q_atoms": STANDARD_NETWORK_FEE_Q_ATOMS,
        }

    def apply_consensus_wallet_transfer(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Apply one replay-protected Wallet transfer and recycle its fee."""
        validated = self.validate_consensus_wallet_transfer(envelope)
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["WalletTransferred", "NetworkFeeRecycled"],
        )
        self.debit_wallet_q_atoms(
            wallet_id=str(envelope.sender_wallet),
            amount_q_atoms=(int(validated["amount_q_atoms"]) + int(validated["network_fee_q_atoms"])),
        )
        self.credit_wallet_q_atoms(
            wallet_id=str(validated["recipient_wallet"]),
            amount_q_atoms=int(validated["amount_q_atoms"]),
        )
        self._recyclable_q_atoms += int(validated["network_fee_q_atoms"])
        return record

    def recyclable_q_atom_balance(self) -> int:
        return int(self._recyclable_q_atoms)

    def burned_q_atom_balance(self) -> int:
        return int(self._burned_q_atoms)

    def get_stake_record(self, stake_id: str) -> dict:
        return dict(self._stake_records[stake_id])

    def snapshot_stake_records(self) -> list[dict]:
        return [dict(record) for _, record in sorted(self._stake_records.items())]

    def validate_consensus_stake_lock(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        if envelope.operation_type != "STAKE_LOCK":
            raise ValueError("consensus stake lock requires STAKE_LOCK operation")
        if envelope.origin_type != "wallet" or envelope.sender_wallet is None:
            raise ValueError("stake lock requires wallet origin")
        if envelope.fee_class != "standard":
            raise ValueError("stake lock requires standard fee class")

        payload = dict(envelope.payload)
        for field_name in (
            "stake_id",
            "stake_type",
            "beneficiary_object_id",
            "lock_policy_version",
        ):
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"stake lock field is invalid: {field_name}")
        if payload["stake_type"] not in _STAKE_TYPES:
            raise ValueError("stake lock type is not supported")

        amount = payload.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("stake lock amount is invalid")
        if payload["stake_id"] in self._stake_records:
            raise ValueError("stake is already registered")
        if self.wallet_q_atom_balance(envelope.sender_wallet) < amount:
            raise ValueError("insufficient q_atoms for stake lock")
        return {"payload": payload, "amount_q_atoms": amount}

    def apply_consensus_stake_lock(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        validated = self.validate_consensus_stake_lock(envelope)
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["StakeLocked"],
        )
        payload = validated["payload"]
        self.debit_wallet_q_atoms(
            wallet_id=str(envelope.sender_wallet),
            amount_q_atoms=int(validated["amount_q_atoms"]),
        )
        self._stake_records[payload["stake_id"]] = {
            "stake_id": payload["stake_id"],
            "stake_type": payload["stake_type"],
            "amount": int(validated["amount_q_atoms"]),
            "beneficiary_object_id": payload["beneficiary_object_id"],
            "lock_policy_version": payload["lock_policy_version"],
            "owner_wallet": envelope.sender_wallet,
            "state": "LOCKED",
            "locked_by_operation_id": envelope.operation_id,
            "unbonding_start_epoch": None,
            "release_epoch": None,
            "penalty_blocked": False,
        }
        return record

    def validate_consensus_unstake_request(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        if envelope.operation_type != "UNSTAKE_REQUEST":
            raise ValueError("consensus unstake requires UNSTAKE_REQUEST operation")
        if envelope.origin_type != "wallet" or envelope.sender_wallet is None:
            raise ValueError("unstake request requires wallet origin")
        if envelope.fee_class != "standard":
            raise ValueError("unstake request requires standard fee class")

        payload = dict(envelope.payload)
        stake_id = payload.get("stake_id")
        request_epoch = payload.get("request_epoch")
        if not isinstance(stake_id, str) or not stake_id.strip():
            raise ValueError("unstake request stake_id is invalid")
        if isinstance(request_epoch, bool) or not isinstance(request_epoch, int) or request_epoch < 0:
            raise ValueError("unstake request epoch is invalid")
        if envelope.target_epoch is not None and envelope.target_epoch != str(request_epoch):
            raise ValueError("unstake request target epoch does not match payload")
        requested_period = payload.get("unbonding_period_epochs", DEFAULT_UNBONDING_PERIOD_EPOCHS)
        if requested_period != DEFAULT_UNBONDING_PERIOD_EPOCHS:
            raise ValueError("unstake request uses unsupported unbonding period")

        stake = self._stake_records.get(stake_id)
        if stake is None:
            raise ValueError("stake does not exist")
        if stake["owner_wallet"] != envelope.sender_wallet:
            raise ValueError("unstake request is not authorized by stake owner")
        if stake["state"] != "LOCKED":
            raise ValueError("stake is not locked")
        if stake.get("penalty_blocked"):
            raise ValueError("stake is blocked by unresolved penalty")
        return {
            "payload": payload,
            "release_epoch": request_epoch + DEFAULT_UNBONDING_PERIOD_EPOCHS,
        }

    def apply_consensus_unstake_request(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        validated = self.validate_consensus_unstake_request(envelope)
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["StakeUnbondingStarted"],
        )
        payload = validated["payload"]
        stake = dict(self._stake_records[payload["stake_id"]])
        stake.update(
            {
                "state": "UNBONDING",
                "unbonding_start_epoch": int(payload["request_epoch"]),
                "release_epoch": int(validated["release_epoch"]),
                "unstake_request_operation_id": envelope.operation_id,
            }
        )
        self._stake_records[payload["stake_id"]] = stake
        return record

    def validate_consensus_stake_release(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        if envelope.operation_type != "STAKE_RELEASE":
            raise ValueError("consensus stake release requires STAKE_RELEASE operation")
        if envelope.origin_type != "protocol" or envelope.sender_wallet is not None:
            raise ValueError("stake release requires protocol origin")
        if envelope.fee_class != "protocol_sponsored":
            raise ValueError("stake release requires protocol-sponsored fee class")

        payload = dict(envelope.payload)
        stake_id = payload.get("stake_id")
        current_epoch = payload.get("current_epoch")
        if not isinstance(stake_id, str) or not stake_id.strip():
            raise ValueError("stake release stake_id is invalid")
        if isinstance(current_epoch, bool) or not isinstance(current_epoch, int) or current_epoch < 0:
            raise ValueError("stake release epoch is invalid")
        if envelope.target_epoch is not None and envelope.target_epoch != str(current_epoch):
            raise ValueError("stake release target epoch does not match payload")

        stake = self._stake_records.get(stake_id)
        if stake is None:
            raise ValueError("stake does not exist")
        if stake["state"] != "UNBONDING":
            raise ValueError("stake is not unbonding")
        release_epoch = stake.get("release_epoch")
        if not isinstance(release_epoch, int) or current_epoch < release_epoch:
            raise ValueError("stake release epoch has not been reached")
        if stake.get("penalty_blocked"):
            raise ValueError("stake release is blocked by unresolved penalty")
        return {"payload": payload, "stake": dict(stake)}

    def apply_consensus_stake_release(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        validated = self.validate_consensus_stake_release(envelope)
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["StakeReleased"],
        )
        stake = validated["stake"]
        self.credit_wallet_q_atoms(
            wallet_id=str(stake["owner_wallet"]),
            amount_q_atoms=int(stake["amount"]),
        )
        stake.update(
            {
                "state": "RELEASED",
                "released_by_operation_id": envelope.operation_id,
            }
        )
        self._stake_records[stake["stake_id"]] = stake
        return record

    def get_participant_suspension(self, target_id: str) -> dict:
        return dict(self._participant_suspensions[target_id])

    def participant_suspensions(self) -> dict[str, dict]:
        return {target_id: dict(record) for target_id, record in sorted(self._participant_suspensions.items())}

    def validate_consensus_participant_suspend(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        if envelope.operation_type != "PARTICIPANT_SUSPEND":
            raise ValueError("participant suspension requires PARTICIPANT_SUSPEND operation")
        if envelope.origin_type != "evidence_triggered" or envelope.sender_wallet is not None:
            raise ValueError("participant suspension requires evidence-triggered origin")
        if envelope.fee_class != "protocol_sponsored":
            raise ValueError("participant suspension requires protocol-sponsored fee class")

        payload = dict(envelope.payload)
        for field_name in (
            "target_id",
            "target_type",
            "scope",
            "reason_code",
            "evidence_root",
            "evidence_operation_id",
        ):
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"participant suspension field is invalid: {field_name}")
        effective_epoch = payload.get("effective_epoch")
        minimum_recovery_epoch = payload.get("minimum_recovery_epoch")
        if isinstance(effective_epoch, bool) or not isinstance(effective_epoch, int) or effective_epoch < 0:
            raise ValueError("participant suspension effective epoch is invalid")
        if (
            isinstance(minimum_recovery_epoch, bool)
            or not isinstance(minimum_recovery_epoch, int)
            or minimum_recovery_epoch < effective_epoch
        ):
            raise ValueError("participant suspension recovery epoch is invalid")
        if envelope.target_epoch is not None and envelope.target_epoch != str(effective_epoch):
            raise ValueError("participant suspension target epoch does not match payload")

        evidence_operation_id = payload["evidence_operation_id"]
        if evidence_operation_id not in finalized_operation_ids:
            raise ValueError("participant suspension evidence operation is not finalized")
        if evidence_operation_id not in envelope.evidence_references:
            raise ValueError("participant suspension evidence operation is not referenced")
        if payload["evidence_root"] not in envelope.evidence_references:
            raise ValueError("participant suspension evidence root is not referenced")
        if not any(operation.get("operation_id") == evidence_operation_id for operation in self._operations):
            raise ValueError("participant suspension evidence operation is unavailable")
        existing = self._participant_suspensions.get(payload["target_id"])
        if existing is not None and existing.get("state") == "SUSPENDED":
            raise ValueError("participant is already suspended")
        return {"payload": payload}

    def apply_consensus_participant_suspend(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        validated = self.validate_consensus_participant_suspend(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["ParticipantSuspended"],
        )
        payload = validated["payload"]
        self._participant_suspensions[payload["target_id"]] = {
            **payload,
            "state": "SUSPENDED",
            "suspension_operation_id": envelope.operation_id,
        }
        return record

    def validate_consensus_participant_reinstate(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        if envelope.operation_type != "PARTICIPANT_REINSTATE":
            raise ValueError("participant reinstatement requires PARTICIPANT_REINSTATE operation")
        if envelope.origin_type != "protocol" or envelope.sender_wallet is not None:
            raise ValueError("participant reinstatement requires protocol origin")
        if envelope.fee_class != "protocol_sponsored":
            raise ValueError("participant reinstatement requires protocol-sponsored fee class")

        payload = dict(envelope.payload)
        for field_name in (
            "target_id",
            "recovery_evidence_root",
            "recovery_evidence_operation_id",
        ):
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"participant reinstatement field is invalid: {field_name}")
        current_epoch = payload.get("current_epoch")
        if isinstance(current_epoch, bool) or not isinstance(current_epoch, int) or current_epoch < 0:
            raise ValueError("participant reinstatement epoch is invalid")
        if envelope.target_epoch is not None and envelope.target_epoch != str(current_epoch):
            raise ValueError("participant reinstatement target epoch does not match payload")

        evidence_operation_id = payload["recovery_evidence_operation_id"]
        if evidence_operation_id not in finalized_operation_ids:
            raise ValueError("participant recovery evidence is not finalized")
        if evidence_operation_id not in envelope.evidence_references:
            raise ValueError("participant recovery evidence operation is not referenced")
        if payload["recovery_evidence_root"] not in envelope.evidence_references:
            raise ValueError("participant recovery evidence root is not referenced")
        if not any(operation.get("operation_id") == evidence_operation_id for operation in self._operations):
            raise ValueError("participant recovery evidence is unavailable")

        suspension = self._participant_suspensions.get(payload["target_id"])
        if suspension is None or suspension.get("state") != "SUSPENDED":
            raise ValueError("participant is not suspended")
        minimum_recovery_epoch = suspension.get("minimum_recovery_epoch")
        if not isinstance(minimum_recovery_epoch, int) or current_epoch < minimum_recovery_epoch:
            raise ValueError("participant minimum recovery epoch has not been reached")
        return {"payload": payload, "suspension": dict(suspension)}

    def apply_consensus_participant_reinstate(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        validated = self.validate_consensus_participant_reinstate(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["ParticipantReinstated"],
        )
        payload = validated["payload"]
        suspension = validated["suspension"]
        suspension.update(
            {
                "state": "ACTIVE",
                "current_epoch": int(payload["current_epoch"]),
                "recovery_evidence_root": payload["recovery_evidence_root"],
                "recovery_evidence_operation_id": payload["recovery_evidence_operation_id"],
                "reinstatement_operation_id": envelope.operation_id,
            }
        )
        self._participant_suspensions[payload["target_id"]] = suspension
        return record

    def get_session_funding_account(self, session_id: str) -> SessionFundingAccount:
        return self._session_funding_accounts[session_id]

    def get_funding_predecessor_operation(self, session_id: str) -> dict | None:
        """Return the operation that produced the current Funding Account hash."""
        funding = self._session_funding_accounts.get(session_id)
        if funding is None:
            return None
        predecessor = self._find_funding_predecessor_operation(funding)
        return dict(predecessor) if predecessor is not None else None

    def get_settlement_ready_operation(self, session_id: str) -> dict | None:
        """Return the local operation carrying the Session readiness commitment."""
        commitment = self._settlement_ready_commits.get(session_id)
        if commitment is None:
            return None
        for operation in reversed(self._operations):
            if operation.get("operation_type") != SESSION_SETTLEMENT_READY_COMMIT_OPERATION:
                continue
            payload = operation.get("payload")
            ready_payload = payload.get("ready") if isinstance(payload, dict) else None
            if (
                isinstance(payload, dict)
                and payload.get("session_id") == session_id
                and isinstance(ready_payload, dict)
                and ready_payload.get("commitment_hash") == commitment.commitment_hash
            ):
                return dict(operation)
        return None

    def get_settlement_proposal(self, settlement_id: str) -> SessionSettlementProposal:
        return self._settlement_proposals[settlement_id]

    def get_settlement_acceptance(self, settlement_id: str) -> SessionSettlementAcceptance:
        return self._settlement_acceptances[settlement_id]

    def get_settlement_ready_commitment(self, session_id: str) -> SettlementReadyCommitment:
        return self._settlement_ready_commits[session_id]

    def find_settlement_ready_commitment(self, session_id: str) -> SettlementReadyCommitment | None:
        """Return a readiness commitment when one has already been recorded."""
        return self._settlement_ready_commits.get(session_id)

    def get_settlement_dispute(self, settlement_id: str) -> SettlementDispute:
        return self._settlement_disputes[settlement_id]

    def get_settlement_transition_hash(self, settlement_id: str) -> str | None:
        """Return the immutable final transition hash, if one exists."""
        return self._settlement_transition_hashes.get(settlement_id)

    def get_settlement_correction(self, correction_id: str) -> SettlementCorrection:
        return self._settlement_corrections[correction_id]

    def get_session_checkpoint(self, checkpoint_id: str) -> SessionUsageCheckpoint:
        return self._session_checkpoints[checkpoint_id]

    def list_session_checkpoints(self, session_id: str | None = None) -> list[SessionUsageCheckpoint]:
        checkpoints = list(self._session_checkpoints.values())
        if session_id is None:
            return sorted(checkpoints, key=lambda item: (item.session_id, item.checkpoint_sequence))
        return sorted(
            (item for item in checkpoints if item.session_id == session_id),
            key=lambda item: item.checkpoint_sequence,
        )

    def commit_wallet_identity_governance_certificate(
        self,
        certificate: dict,
        *,
        created_at: str | None = None,
    ) -> dict:
        """Commit verified quorum authority without making Registry state canonical itself."""
        from aidn_hypervisor.wallet_identity import verify_wallet_identity_governance_certificate

        try:
            verify_wallet_identity_governance_certificate(
                certificate_id=str(certificate["certificate_id"]),
                resolution_id=str(certificate["resolution_id"]),
                wallet_id=str(certificate["wallet_id"]),
                chosen_object_id=str(certificate["chosen_object_id"]),
                chosen_payload_hash=str(certificate["chosen_payload_hash"]),
                governance_policy_hash=str(certificate["governance_policy_hash"]),
                eligible_voter_node_ids=list(certificate["eligible_voter_node_ids"]),
                voter_authorities=list(certificate["voter_authorities"]),
                quorum_threshold=int(certificate["quorum_threshold"]),
                approvals=list(certificate["approvals"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Wallet-identity governance certificate is invalid") from exc

        commitment_payload = {
            "certificate_id": str(certificate["certificate_id"]),
            "resolution_id": str(certificate["resolution_id"]),
            "wallet_id": str(certificate["wallet_id"]),
            "chosen_object_id": str(certificate["chosen_object_id"]),
            "chosen_payload_hash": str(certificate["chosen_payload_hash"]),
            "governance_policy_hash": str(certificate["governance_policy_hash"]),
            "scope": "wallet_identity_resolution",
        }
        existing = self.wallet_identity_governance_certificate_commitment(commitment_payload["certificate_id"])
        if existing is not None:
            if existing["payload"] != commitment_payload:
                raise ValueError("conflicting wallet-identity governance certificate commitment")
            return existing

        return self.record_operation(
            operation_type="GOVERNANCE_AUTHORIZATION_COMMIT",
            origin_type="multi_party",
            fee_class="protocol_sponsored",
            initiator_id=commitment_payload["wallet_id"],
            payload=commitment_payload,
            evidence_references=[commitment_payload["certificate_id"]],
            signatures=[
                str(item["approval_signature"])
                for item in certificate["approvals"]
                if isinstance(item.get("approval_signature"), str)
            ],
            created_at=created_at,
            emitted_events=["WalletIdentityGovernanceCertificateCommitted"],
        )

    def wallet_identity_governance_certificate_commitment(
        self,
        certificate_id: str,
    ) -> dict | None:
        for operation in reversed(self._operations):
            if operation.get("operation_type") != "GOVERNANCE_AUTHORIZATION_COMMIT":
                continue
            payload = operation.get("payload") or {}
            if payload.get("scope") == "wallet_identity_resolution" and payload.get("certificate_id") == certificate_id:
                return dict(operation)
        return None

    def commit_wallet_identity_governance_revocation(
        self,
        revocation: dict,
        *,
        created_at: str | None = None,
    ) -> dict:
        from aidn_hypervisor.wallet_identity import verify_wallet_identity_governance_revocation

        try:
            verify_wallet_identity_governance_revocation(
                certificate_id=str(revocation["certificate_id"]),
                revocation_id=str(revocation["revocation_id"]),
                reason=str(revocation["reason"]),
                eligible_voter_node_ids=list(revocation["eligible_voter_node_ids"]),
                voter_authorities=list(revocation["voter_authorities"]),
                quorum_threshold=int(revocation["quorum_threshold"]),
                approvals=list(revocation["approvals"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Wallet-identity governance revocation is invalid") from exc
        payload = {
            "certificate_id": str(revocation["certificate_id"]),
            "revocation_id": str(revocation["revocation_id"]),
            "reason": str(revocation["reason"]),
            "scope": "wallet_identity_resolution",
        }
        existing = self.wallet_identity_governance_certificate_revocation(payload["certificate_id"])
        if existing is not None:
            if existing["payload"] != payload:
                raise ValueError("conflicting wallet-identity governance certificate revocation")
            return existing
        return self.record_operation(
            operation_type="GOVERNANCE_AUTHORIZATION_REVOKE",
            origin_type="multi_party",
            fee_class="protocol_sponsored",
            initiator_id=payload["certificate_id"],
            payload=payload,
            evidence_references=[payload["certificate_id"], payload["revocation_id"]],
            signatures=[
                str(item["approval_signature"])
                for item in revocation["approvals"]
                if isinstance(item.get("approval_signature"), str)
            ],
            created_at=created_at,
            emitted_events=["WalletIdentityGovernanceCertificateRevoked"],
        )

    def wallet_identity_governance_certificate_revocation(
        self,
        certificate_id: str,
    ) -> dict | None:
        for operation in reversed(self._operations):
            if operation.get("operation_type") != "GOVERNANCE_AUTHORIZATION_REVOKE":
                continue
            payload = operation.get("payload") or {}
            if payload.get("scope") == "wallet_identity_resolution" and payload.get("certificate_id") == certificate_id:
                return dict(operation)
        return None

    @staticmethod
    def governance_commitment_subject_hash(operation: dict) -> str:
        """Return the peer-comparable commitment, excluding local sequence and time."""
        subject = {
            "operation_type": operation["operation_type"],
            "origin_type": operation["origin_type"],
            "fee_class": operation["fee_class"],
            "payload": operation["payload"],
            "evidence_references": sorted(operation["evidence_references"]),
            "signatures": sorted(operation["signatures"]),
        }
        return f"sha256:{_hash_dict(subject)}"

    @staticmethod
    def verify_operation_record(operation: dict) -> None:
        """Validate the deterministic parts of one exported local Ledger record.

        This proves record integrity, not that a remote Ledger is consensus-final.
        """
        model = LedgerOperationRecord.model_validate(operation)
        unsigned = {
            "operation_type": model.operation_type,
            "operation_version": model.operation_version,
            "protocol_version": model.protocol_version,
            "origin_type": model.origin_type,
            "initiator_id": model.initiator_id,
            "sender_wallet": model.sender_wallet,
            "sender_sequence": model.sender_sequence,
            "fee_class": model.fee_class,
            "fee_payer": model.fee_payer,
            "created_at": model.created_at,
            "expires_at": model.expires_at,
            "target_epoch": model.target_epoch,
            "payload": model.payload,
            "evidence_references": model.evidence_references,
            "signatures": model.signatures,
        }
        local_operation_id = _hash_dict(unsigned)

        # Locally-created records hash their authorization signatures. Records
        # projected from a canonical consensus envelope preserve the envelope
        # identity, whose hash intentionally excludes signatures. Recovery and
        # consensus settlement must accept both representations.
        from aidn_hypervisor.consensus.models import LedgerOperationEnvelope

        canonical_operation_id = LedgerOperationEnvelope(
            operation_type=model.operation_type,
            operation_version=model.operation_version,
            protocol_version=model.protocol_version,
            origin_type=model.origin_type,
            initiator_id=model.initiator_id,
            sender_wallet=model.sender_wallet,
            sender_sequence=model.sender_sequence,
            fee_payer=model.fee_payer,
            fee_class=model.fee_class,
            created_at=model.created_at,
            expires_at=model.expires_at,
            target_epoch=model.target_epoch,
            payload=model.payload,
            evidence_references=model.evidence_references,
            signatures=model.signatures,
        ).operation_id
        if model.operation_id not in {local_operation_id, canonical_operation_id}:
            raise ValueError("Ledger operation record identity is invalid")
        expected_state_changes_root = _hash_dict(
            {
                "operation_id": model.operation_id,
                "operation_type": model.operation_type,
                "payload": model.payload,
            }
        )
        if model.result.state_changes_root != expected_state_changes_root:
            raise ValueError("Ledger operation record state root is invalid")

    def governance_commitment_proof(self, operation: dict) -> dict:
        self.verify_operation_record(operation)
        proof = dict(operation)
        proof.update(
            {
                "proof_version": "ledger-governance-commitment-proof.v1",
                "commitment_subject_hash": self.governance_commitment_subject_hash(operation),
                "verification_scope": "local_ledger_record",
                "consensus_finality": False,
            }
        )
        return proof

    def verify_governance_commitment_proof(
        self,
        proof: dict,
        *,
        certificate_id: str,
        expected_operation_type: str,
    ) -> dict:
        self.verify_operation_record(proof)
        if proof.get("proof_version") != "ledger-governance-commitment-proof.v1":
            raise ValueError("Ledger governance proof version is invalid")
        if proof.get("verification_scope") != "local_ledger_record":
            raise ValueError("Ledger governance proof scope is invalid")
        if proof.get("consensus_finality") is not False:
            raise ValueError("Ledger governance proof falsely claims consensus finality")
        if proof.get("operation_type") != expected_operation_type:
            raise ValueError("Ledger governance proof operation type is invalid")
        payload = proof.get("payload")
        if not isinstance(payload, dict) or payload.get("certificate_id") != certificate_id:
            raise ValueError("Ledger governance proof certificate binding is invalid")
        expected_subject_hash = self.governance_commitment_subject_hash(proof)
        if proof.get("commitment_subject_hash") != expected_subject_hash:
            raise ValueError("Ledger governance proof subject hash is invalid")
        return {
            "operation_id": proof["operation_id"],
            "commitment_subject_hash": expected_subject_hash,
            "operation_type": proof["operation_type"],
        }

    def service_verification_commitment(
        self,
        verification_report_id: str,
    ) -> dict | None:
        """Return the local idempotent commitment for one service report."""
        for operation in reversed(self._operations):
            if operation.get("operation_type") != "SERVICE_VERIFICATION_COMMIT":
                continue
            payload = operation.get("payload") or {}
            if payload.get("verification_report_id") == verification_report_id:
                return dict(operation)
        return None

    def validation_report_commitment(self, report_id: str) -> dict | None:
        """Return the canonical commitment for one Validation Report ID."""
        for operation in reversed(self._operations):
            if operation.get("operation_type") != VALIDATION_REPORT_COMMIT_OPERATION:
                continue
            payload = operation.get("payload") or {}
            if payload.get("report_id") == report_id:
                return dict(operation)
        return None

    def _validation_report_commitment_for_scope(
        self,
        *,
        report_hash: str,
        endpoint_id: str,
        endpoint_configuration_hash: str,
        validation_request_id: str | None = None,
    ) -> dict:
        matches: list[dict] = []
        for operation in self._operations:
            if operation.get("operation_type") != VALIDATION_REPORT_COMMIT_OPERATION:
                continue
            payload = operation.get("payload") or {}
            if (
                payload.get("report_hash") == report_hash
                and payload.get("endpoint_id") == endpoint_id
                and payload.get("endpoint_configuration_hash") == endpoint_configuration_hash
                and (validation_request_id is None or payload.get("validation_request_id") == validation_request_id)
            ):
                matches.append(operation)
        if not matches:
            raise ValueError("Validation Report commitment is not finalized")
        if len({item.get("payload", {}).get("report_id") for item in matches}) != 1:
            raise ValueError("conflicting Validation Report commitments")
        return dict(matches[-1])

    @staticmethod
    def _require_validation_text(payload: dict, field_name: str) -> str:
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Validation evidence field is invalid: {field_name}")
        return value

    @staticmethod
    def _require_validation_size(payload: dict) -> int:
        value = payload.get("report_size")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("Validation report size is invalid")
        return value

    def validate_consensus_validation_evidence(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate evidence-only Validation custody operations.

        These operations commit report identity and custody observations only.
        They never credit wallets or derive Certification by themselves.
        """
        if envelope.operation_type not in {
            VALIDATION_REPORT_COMMIT_OPERATION,
            VALIDATION_REPORT_STORAGE_RECEIPT_OPERATION,
            VALIDATION_REPORT_STORAGE_FAILURE_OPERATION,
            VALIDATION_REPORT_AVAILABILITY_COMMIT_OPERATION,
            VALIDATION_REPORT_CUSTODY_RELEASE_OPERATION,
        }:
            raise ValueError("unsupported Validation evidence operation")
        if envelope.origin_type != "protocol" or envelope.sender_wallet is not None:
            raise ValueError("Validation evidence requires protocol origin")
        payload = dict(envelope.payload)
        operation_type = envelope.operation_type
        if operation_type == VALIDATION_REPORT_COMMIT_OPERATION:
            report_id = self._require_validation_text(payload, "report_id")
            for field_name in (
                "report_hash",
                "validation_request_id",
                "assignment_id",
                "endpoint_id",
                "endpoint_configuration_hash",
                "evidence_root",
                "evidence_access_class",
                "report_locator",
                "retention_policy_id",
            ):
                self._require_validation_text(payload, field_name)
            self._require_validation_size(payload)
            if payload["evidence_access_class"] not in {
                "public",
                "encrypted",
                "restricted",
                "hash_committed",
            }:
                raise ValueError("Validation evidence access class is invalid")
            if self.validation_report_commitment(report_id) is not None:
                raise ValueError("Validation Report is already committed")
            return {"payload": payload}

        report_hash = self._require_validation_text(payload, "report_hash")
        endpoint_id = self._require_validation_text(payload, "endpoint_id")
        endpoint_configuration_hash = self._require_validation_text(payload, "endpoint_configuration_hash")
        self._require_validation_text(payload, "report_locator")
        report_size = self._require_validation_size(payload)
        validation_request_id = payload.get("validation_id")
        if validation_request_id is not None and (
            not isinstance(validation_request_id, str) or not validation_request_id.strip()
        ):
            raise ValueError("Validation evidence validation_id is invalid")
        commitment = self._validation_report_commitment_for_scope(
            report_hash=report_hash,
            endpoint_id=endpoint_id,
            endpoint_configuration_hash=endpoint_configuration_hash,
            validation_request_id=validation_request_id,
        )
        commitment_payload = commitment.get("payload") or {}
        if report_size != commitment_payload.get("report_size"):
            raise ValueError("Validation evidence report size does not match commitment")
        if payload["report_locator"] != commitment_payload.get("report_locator"):
            raise ValueError("Validation evidence report locator does not match commitment")
        if payload.get("retention_policy_id") != commitment_payload.get("retention_policy_id"):
            raise ValueError("Validation evidence retention policy does not match commitment")

        if operation_type == VALIDATION_REPORT_STORAGE_RECEIPT_OPERATION:
            for field_name in ("receipt_id", "endpoint_public_key", "receipt_hash"):
                self._require_validation_text(payload, field_name)
            existing = self._validation_child_operation(
                operation_type=operation_type,
                report_hash=report_hash,
            )
            if existing is not None:
                raise ValueError("Validation Report storage receipt is already committed")
        elif operation_type == VALIDATION_REPORT_STORAGE_FAILURE_OPERATION:
            for field_name in (
                "failure_id",
                "failure_code",
                "failure_evidence_root",
                "reported_by",
            ):
                self._require_validation_text(payload, field_name)
            if (
                self._validation_child_operation(
                    operation_type=VALIDATION_REPORT_STORAGE_RECEIPT_OPERATION,
                    report_hash=report_hash,
                )
                is not None
            ):
                raise ValueError("Validation storage failure conflicts with receipt")
            existing = self._validation_child_operation(
                operation_type=operation_type,
                report_hash=report_hash,
            )
            if existing is not None:
                raise ValueError("Validation Report storage failure is already committed")
        elif operation_type == VALIDATION_REPORT_CUSTODY_RELEASE_OPERATION:
            for field_name in ("release_reason", "released_at"):
                self._require_validation_text(payload, field_name)
            if (
                self._validation_child_operation(
                    operation_type=operation_type,
                    report_hash=report_hash,
                )
                is not None
            ):
                raise ValueError("Validation Report custody release is already committed")
        else:
            report_id = self._require_validation_text(payload, "report_id")
            if report_id != commitment_payload.get("report_id"):
                raise ValueError("Validation custody report ID does not match commitment")
            custody_status = self._require_validation_text(payload, "custody_status")
            if custody_status not in {
                "available",
                "temporarily_unavailable",
                "withheld",
                "lost",
                "corrupted",
                "access_restricted",
            }:
                raise ValueError("Validation custody status is invalid")
            failure_streak = payload.get("failure_streak")
            if isinstance(failure_streak, bool) or not isinstance(failure_streak, int) or failure_streak < 0:
                raise ValueError("Validation custody failure streak is invalid")
            challenge_id = payload.get("challenge_id")
            if challenge_id is not None and (not isinstance(challenge_id, str) or not challenge_id.strip()):
                raise ValueError("Validation custody challenge ID is invalid")
            challenger_id = payload.get("challenger_id")
            independence_key = payload.get("independence_key")
            if challenge_id is None and (challenger_id is not None or independence_key is not None):
                raise ValueError("Validation custody observer identity requires a challenge ID")
            if challenger_id is not None and (not isinstance(challenger_id, str) or not challenger_id.strip()):
                raise ValueError("Validation custody challenger ID is invalid")
            if independence_key is not None and (not isinstance(independence_key, str) or not independence_key.strip()):
                raise ValueError("Validation custody independence key is invalid")
            if challenger_id is not None and independence_key is None:
                raise ValueError("Validation custody independence key is required for an observer")
            if challenge_id is not None:
                existing_challenge = next(
                    (
                        operation
                        for operation in reversed(self._operations)
                        if operation.get("operation_type") == VALIDATION_REPORT_AVAILABILITY_COMMIT_OPERATION
                        and (operation.get("payload") or {}).get("challenge_id") == challenge_id
                    ),
                    None,
                )
                if existing_challenge is not None:
                    if (existing_challenge.get("payload") or {}) != payload:
                        raise ValueError("conflicting Validation custody challenge")
                    raise ValueError("Validation custody challenge is already committed")

        return {"payload": payload, "commitment": commitment}

    def _validation_child_operation(
        self,
        *,
        operation_type: str,
        report_hash: str,
    ) -> dict | None:
        for operation in reversed(self._operations):
            if operation.get("operation_type") != operation_type:
                continue
            if (operation.get("payload") or {}).get("report_hash") == report_hash:
                return dict(operation)
        return None

    def apply_consensus_validation_evidence(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Persist one already-validated Validation custody commitment."""
        self.validate_consensus_validation_evidence(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        event_by_type = {
            VALIDATION_REPORT_COMMIT_OPERATION: "ValidationReportCommitted",
            VALIDATION_REPORT_STORAGE_RECEIPT_OPERATION: "ValidationReportStorageReceiptCommitted",
            VALIDATION_REPORT_STORAGE_FAILURE_OPERATION: "ValidationReportStorageFailureCommitted",
            VALIDATION_REPORT_AVAILABILITY_COMMIT_OPERATION: "ValidationReportAvailabilityCommitted",
            VALIDATION_REPORT_CUSTODY_RELEASE_OPERATION: "ValidationReportCustodyReleased",
        }
        return self.record_admitted_envelope(
            envelope,
            emitted_events=[event_by_type[envelope.operation_type]],
        )

    def commit_service_verification(
        self,
        *,
        verification_report_id: str,
        service_id: str,
        service_type: str,
        report_hash: str,
        evidence_root: str,
        verification_epoch: int,
        result_summary: dict,
        registry_reference: dict,
        evidence_references: list[str] | None = None,
        signatures: list[str] | None = None,
        created_at: str | None = None,
    ) -> dict:
        """Record a finalized service-verification commitment, never a reward.

        The operation is deliberately idempotent by report ID.  It records
        evidence for the epoch engine; it does not credit wallets and cannot
        create ``REWARD_MINT`` state on its own.
        """
        if not verification_report_id.strip():
            raise ValueError("verification_report_id is required")
        if not service_id.strip() or not service_type.strip():
            raise ValueError("service identity is required")
        if not report_hash.strip() or not evidence_root.strip():
            raise ValueError("service verification hashes are required")
        if int(verification_epoch) < 0:
            raise ValueError("verification_epoch must be non-negative")
        payload = {
            "verification_report_id": verification_report_id,
            "service_id": service_id,
            "service_type": service_type,
            "report_hash": report_hash,
            "evidence_root": evidence_root,
            "verification_epoch": int(verification_epoch),
            "result_summary": dict(result_summary),
            "registry_reference": dict(registry_reference),
        }
        existing = self.service_verification_commitment(verification_report_id)
        if existing is not None:
            if existing.get("payload") != payload:
                raise ValueError("conflicting service verification commitment")
            return existing
        return self.record_operation(
            operation_type="SERVICE_VERIFICATION_COMMIT",
            origin_type="protocol",
            fee_class="protocol_sponsored",
            initiator_id=service_id,
            target_epoch=str(int(verification_epoch)),
            payload=payload,
            evidence_references=sorted(set(evidence_references or [])),
            signatures=sorted(set(signatures or [])),
            created_at=created_at,
            emitted_events=["ServiceVerificationCommitted"],
        )

    def validate_consensus_service_verification(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Validate an evidence-only service verification operation."""
        if envelope.operation_type != "SERVICE_VERIFICATION_COMMIT":
            raise ValueError("consensus service verification requires SERVICE_VERIFICATION_COMMIT")
        if envelope.origin_type != "protocol" or envelope.sender_wallet is not None:
            raise ValueError("service verification commit requires protocol origin")

        payload = dict(envelope.payload)
        required_text = (
            "verification_report_id",
            "service_id",
            "service_type",
            "report_hash",
            "evidence_root",
        )
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"service verification field is invalid: {field_name}")

        verification_epoch = payload.get("verification_epoch")
        if isinstance(verification_epoch, bool) or not isinstance(verification_epoch, int) or verification_epoch < 0:
            raise ValueError("service verification epoch is invalid")
        if envelope.target_epoch is not None and envelope.target_epoch != str(verification_epoch):
            raise ValueError("service verification target epoch does not match payload")

        result_summary = payload.get("result_summary")
        registry_reference = payload.get("registry_reference")
        if not isinstance(result_summary, dict):
            raise ValueError("service verification result summary is required")
        if not isinstance(registry_reference, dict) or not registry_reference:
            raise ValueError("service verification registry reference is required")

        existing = self.service_verification_commitment(payload["verification_report_id"])
        if existing is not None:
            raise ValueError("service verification report is already committed")

        return {
            "payload": payload,
            "verification_epoch": verification_epoch,
        }

    def apply_consensus_service_verification(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Validate and persist one evidence-only service verification."""
        self.validate_consensus_service_verification(envelope)
        return self.record_admitted_envelope(
            envelope,
            emitted_events=["ServiceVerificationCommitted"],
        )

    def reputation_profile_update_commitment(
        self,
        object_id: str,
        *,
        effective_epoch: int | None = None,
    ) -> dict | None:
        """Return the latest canonical profile-root update for one object."""
        matches: list[dict] = []
        for operation in self._operations:
            if operation.get("operation_type") != REPUTATION_PROFILE_UPDATE_OPERATION:
                continue
            payload = operation.get("payload") or {}
            if payload.get("object_id") != object_id:
                continue
            if effective_epoch is not None and payload.get("effective_epoch") != effective_epoch:
                continue
            matches.append(operation)
        return dict(matches[-1]) if matches else None

    @staticmethod
    def _require_reputation_hash(payload: dict, field_name: str) -> str:
        value = payload.get(field_name)
        if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
            raise ValueError(f"reputation profile hash is invalid: {field_name}")
        return value

    @staticmethod
    def _validate_reputation_metric_deltas(value: object) -> dict:
        """Validate the fixed-point accumulator delta wire shape.

        The Ledger commits the deterministic input to profile calculation; it
        does not calculate scores. Milli-mass values avoid floating-point
        consensus state while keeping the profile engine free to derive its
        local presentation scores.
        """
        if not isinstance(value, dict) or not value:
            raise ValueError("reputation profile metric_deltas are required")
        required_fields = {
            "positive_mass_milli",
            "negative_mass_milli",
            "event_count",
        }
        normalized: dict[str, dict[str, int]] = {}
        for dimension, delta in value.items():
            if not isinstance(dimension, str) or not dimension.strip():
                raise ValueError("reputation profile metric dimension is invalid")
            if not isinstance(delta, dict) or set(delta) != required_fields:
                raise ValueError("reputation profile metric delta fields are invalid")
            normalized_delta: dict[str, int] = {}
            for field_name in sorted(required_fields):
                field_value = delta[field_name]
                if isinstance(field_value, bool) or not isinstance(field_value, int) or field_value < 0:
                    raise ValueError(f"reputation profile metric delta is invalid: {field_name}")
                normalized_delta[field_name] = field_value
            if (
                normalized_delta["positive_mass_milli"] == 0
                and normalized_delta["negative_mass_milli"] == 0
                and normalized_delta["event_count"] == 0
            ):
                raise ValueError("reputation profile metric delta is empty")
            normalized[dimension] = normalized_delta
        return normalized

    def validate_consensus_reputation_profile_update(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate one protocol-finalized Reputation profile root update."""
        if envelope.operation_type != REPUTATION_PROFILE_UPDATE_OPERATION:
            raise ValueError("consensus Reputation update requires REPUTATION_PROFILE_UPDATE")
        if envelope.origin_type != "protocol" or envelope.sender_wallet is not None:
            raise ValueError("Reputation profile update requires protocol origin")
        if envelope.fee_class != "protocol_sponsored":
            raise ValueError("Reputation profile update requires protocol-sponsored fee class")
        payload = dict(envelope.payload)
        object_id = payload.get("object_id")
        object_type = payload.get("object_type")
        if not isinstance(object_id, str) or not object_id.strip():
            raise ValueError("reputation profile object_id is invalid")
        if object_type != "reputation_profile":
            raise ValueError("reputation profile object_type is invalid")
        previous_profile_hash = self._require_reputation_hash(
            payload,
            "previous_profile_hash",
        )
        new_profile_hash = self._require_reputation_hash(payload, "new_profile_hash")
        if previous_profile_hash == new_profile_hash:
            raise ValueError("reputation profile root must change")
        evidence_root = self._require_reputation_hash(payload, "evidence_root")

        formula_version = payload.get("formula_version", REPUTATION_FORMULA_VERSION)
        if formula_version != REPUTATION_FORMULA_VERSION:
            raise ValueError("unsupported Reputation formula version")

        effective_epoch = payload.get("effective_epoch")
        if isinstance(effective_epoch, bool) or not isinstance(effective_epoch, int) or effective_epoch < 0:
            raise ValueError("reputation profile effective_epoch is invalid")
        if envelope.target_epoch is not None and envelope.target_epoch != str(effective_epoch):
            raise ValueError("reputation profile target epoch does not match payload")

        metric_deltas = self._validate_reputation_metric_deltas(payload.get("metric_deltas"))
        evidence_references = list(envelope.evidence_references)
        if not evidence_references:
            raise ValueError("reputation profile evidence references are required")
        finalized = (
            set(finalized_operation_ids) if finalized_operation_ids is not None else set(self.finalized_operation_ids())
        )
        missing_references = sorted(
            {
                reference
                for reference in evidence_references
                if not isinstance(reference, str) or not reference.strip() or reference not in finalized
            }
        )
        if missing_references:
            raise ValueError("reputation profile evidence is not finalized: " + ",".join(missing_references))

        previous = self.reputation_profile_update_commitment(object_id)
        if previous is not None:
            previous_payload = previous.get("payload") or {}
            previous_epoch = previous_payload.get("effective_epoch")
            if isinstance(previous_epoch, bool) or not isinstance(previous_epoch, int) or previous_epoch < 0:
                raise ValueError("stored Reputation profile epoch is invalid")
            if effective_epoch <= previous_epoch:
                raise ValueError("reputation profile update epoch is not increasing")
            if previous_profile_hash != previous_payload.get("new_profile_hash"):
                raise ValueError("reputation profile previous root does not match")

        if (
            self.reputation_profile_update_commitment(
                object_id,
                effective_epoch=effective_epoch,
            )
            is not None
        ):
            raise ValueError("reputation profile update is already committed")

        return {
            "payload": {
                **payload,
                "formula_version": formula_version,
                "metric_deltas": metric_deltas,
                "evidence_root": evidence_root,
            },
            "object_id": object_id,
            "effective_epoch": effective_epoch,
        }

    def apply_consensus_reputation_profile_update(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Persist a finalized Reputation root without calculating a score."""
        self.validate_consensus_reputation_profile_update(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        return self.record_admitted_envelope(
            envelope,
            emitted_events=["ReputationProfileUpdated"],
        )

    def snapshot_commitment(self, snapshot_id: str) -> dict | None:
        """Return the local idempotent commitment for one Snapshot ID."""
        for operation in reversed(self._operations):
            if operation.get("operation_type") != "SNAPSHOT_COMMIT":
                continue
            payload = operation.get("payload") or {}
            if payload.get("snapshot_id") == snapshot_id:
                return dict(operation)
        return None

    def validate_consensus_snapshot_commit(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Validate a metadata-only Snapshot commitment."""
        if envelope.operation_type != "SNAPSHOT_COMMIT":
            raise ValueError("consensus snapshot commit requires SNAPSHOT_COMMIT")
        if envelope.origin_type != "protocol" or envelope.sender_wallet is not None:
            raise ValueError("snapshot commit requires protocol origin")

        payload = dict(envelope.payload)
        required_text = (
            "snapshot_id",
            "application_state_hash",
            "snapshot_hash",
            "chunk_root",
            "protocol_version",
        )
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"snapshot commit field is invalid: {field_name}")

        block_height = payload.get("block_height")
        epoch = payload.get("epoch")
        if isinstance(block_height, bool) or not isinstance(block_height, int) or block_height < 0:
            raise ValueError("snapshot commit block height is invalid")
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
            raise ValueError("snapshot commit epoch is invalid")
        if envelope.target_epoch is not None and envelope.target_epoch != str(epoch):
            raise ValueError("snapshot commit target epoch does not match payload")

        registry_references = payload.get("registry_references")
        if not isinstance(registry_references, list) or not registry_references:
            raise ValueError("snapshot commit Registry references are required")
        if any(not isinstance(reference, dict) for reference in registry_references):
            raise ValueError("snapshot commit Registry reference is invalid")

        existing = self.snapshot_commitment(payload["snapshot_id"])
        if existing is not None:
            raise ValueError("snapshot is already committed")

        return {
            "payload": payload,
            "block_height": block_height,
            "epoch": epoch,
        }

    def apply_consensus_snapshot_commit(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Validate and persist one metadata-only Snapshot commitment."""
        self.validate_consensus_snapshot_commit(envelope)
        return self.record_admitted_envelope(
            envelope,
            emitted_events=["SnapshotCommitted"],
        )

    def validate_consensus_session_failure_evidence(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Validate one compact RFC-0060 failure-evidence commitment.

        The full Failure Evidence and Failure Report remain in restricted
        Hypervisor storage. Consensus commits only the Session binding,
        classification, and canonical evidence root consumed by a later
        Forced Settlement.
        """
        if envelope.operation_type != SESSION_FAILURE_EVIDENCE_OPERATION:
            raise ValueError("consensus Session failure evidence requires SESSION_FAILURE_EVIDENCE")
        if envelope.origin_type != "evidence_triggered":
            raise ValueError("Session failure evidence requires evidence-triggered origin")
        if envelope.sender_wallet is not None:
            raise ValueError("Session failure evidence cannot be wallet-originated")
        if envelope.fee_class != "session":
            raise ValueError("Session failure evidence requires session fee class")

        payload = dict(envelope.payload)
        for field_name in ("session_id", "failure_class", "failure_evidence_root"):
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Session failure evidence field is invalid: {field_name}")

        session_id = str(payload["session_id"])
        if envelope.initiator_id != session_id:
            raise ValueError("Session failure evidence initiator does not match Session")
        failure_class = str(payload["failure_class"])
        if failure_class not in _CONSENSUS_FAILURE_CLASSES:
            raise ValueError("Session failure evidence class is unsupported")

        root = str(payload["failure_evidence_root"])
        if root not in envelope.evidence_references:
            raise ValueError("Session failure evidence root is not referenced")
        details = payload.get("details")
        if details is not None and (not isinstance(details, str) or len(details) > 4_096):
            raise ValueError("Session failure evidence details are invalid")

        for operation in reversed(self._operations):
            if operation.get("operation_type") != SESSION_FAILURE_EVIDENCE_OPERATION:
                continue
            existing_payload = operation.get("payload")
            if not isinstance(existing_payload, dict):
                continue
            if existing_payload.get("session_id") != session_id:
                continue
            if existing_payload.get("failure_evidence_root") != root:
                continue
            if existing_payload.get("failure_class") != failure_class:
                raise ValueError("conflicting Session failure evidence commitment")
            raise ValueError("Session failure evidence is already committed")

        return {"payload": payload}

    def apply_consensus_session_failure_evidence(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Validate and persist one immutable RFC-0060 evidence commitment."""
        self.validate_consensus_session_failure_evidence(envelope)
        return self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionFailureEvidenceCommitted"],
        )

    def validate_consensus_operator_wallet_bind(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Validate the public, consensus-bound half of wallet bootstrap."""
        if envelope.operation_type != OPERATOR_WALLET_BIND_OPERATION:
            raise ValueError("operator wallet bind requires OPERATOR_WALLET_BIND")
        if envelope.origin_type != "protocol":
            raise ValueError("operator wallet bind requires protocol origin")
        if envelope.sender_wallet is not None or envelope.fee_payer is not None:
            raise ValueError("operator wallet bind cannot be wallet-originated")
        if envelope.fee_class != "onboarding_exempt":
            raise ValueError("operator wallet bind requires onboarding-exempt fee class")

        payload = dict(envelope.payload)
        required_fields = (
            "node_id",
            "operator_id",
            "wallet_id",
            "public_key",
            "bootstrap_mode",
            "wallet_binding_version",
            "created_at",
        )
        for field_name in required_fields:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"operator wallet bind field is invalid: {field_name}")
        if envelope.initiator_id != payload["node_id"]:
            raise ValueError("operator wallet bind initiator does not match node")
        if payload["created_at"] != envelope.created_at:
            raise ValueError("operator wallet bind timestamp does not match envelope")
        if payload["bootstrap_mode"] not in {"create", "import"}:
            raise ValueError("operator wallet bootstrap mode is invalid")
        if payload["wallet_binding_version"] != "1":
            raise ValueError("operator wallet binding version is unsupported")
        label = payload.get("label")
        if label is not None and (not isinstance(label, str) or len(label) > 256):
            raise ValueError("operator wallet label is invalid")

        public_key = payload["public_key"]
        if not public_key.startswith("ed25519:"):
            raise ValueError("operator wallet public key must use ed25519:<32-byte hex>")
        try:
            public_key_bytes = bytes.fromhex(public_key.removeprefix("ed25519:"))
        except ValueError as error:
            raise ValueError("operator wallet public key is invalid") from error
        if len(public_key_bytes) != 32:
            raise ValueError("operator wallet public key must contain 32 bytes")
        expected_wallet_id = "wallet-" + hashlib.sha256(public_key.encode("utf-8")).hexdigest()[:12]
        if payload["wallet_id"] != expected_wallet_id:
            raise ValueError("operator wallet id does not match public key")

        if len(envelope.signatures) != 1:
            raise ValueError("operator wallet bind requires exactly one wallet signature")
        signature = envelope.signatures[0]
        if not signature.startswith("ed25519:"):
            raise ValueError("operator wallet bind signature is invalid")
        try:
            signature_bytes = bytes.fromhex(signature.removeprefix("ed25519:"))
            Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
                signature_bytes,
                envelope.signing_bytes(),
            )
        except (ValueError, InvalidSignature) as error:
            raise ValueError("operator wallet bind signature verification failed") from error

        for operation in self._operations:
            if operation.get("operation_type") != OPERATOR_WALLET_BIND_OPERATION:
                continue
            existing_payload = operation.get("payload") or {}
            if existing_payload.get("node_id") == payload["node_id"]:
                if existing_payload == payload:
                    raise ValueError("operator wallet bind is already committed")
                raise ValueError("operator already has a different wallet binding")
            if existing_payload.get("wallet_id") == payload["wallet_id"]:
                raise ValueError("operator wallet is already bound to another node")
        return {"payload": payload}

    def apply_consensus_operator_wallet_bind(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Validate and persist one canonical operator wallet binding."""
        self.validate_consensus_operator_wallet_bind(envelope)
        return self.record_admitted_envelope(
            envelope,
            emitted_events=["OperatorWalletBound"],
        )

    def validate_consensus_endpoint_publish(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Validate one wallet-authorized Endpoint publication transition."""
        from aidn_hypervisor.endpoint_publications.models import (
            PublishedEndpointConfiguration,
        )
        from aidn_hypervisor.endpoint_publications.signing import (
            verify_publication_signature,
        )

        if envelope.operation_type != ENDPOINT_PUBLISH_OPERATION:
            raise ValueError("endpoint publication requires ENDPOINT_PUBLISH")
        if envelope.origin_type != "wallet":
            raise ValueError("endpoint publication requires wallet origin")
        if envelope.fee_class != "standard":
            raise ValueError("endpoint publication requires standard fee class")
        if envelope.sender_wallet is None or envelope.fee_payer != envelope.sender_wallet:
            raise ValueError("endpoint publication requires one wallet fee payer")
        publication_payload = envelope.payload.get("publication")
        if not isinstance(publication_payload, dict):
            raise ValueError("endpoint publication payload is missing publication")
        try:
            publication = PublishedEndpointConfiguration.model_validate(
                publication_payload
            )
        except ValueError as error:
            raise ValueError(f"endpoint publication payload is invalid: {error}") from error
        if publication.status != "published":
            raise ValueError("endpoint publication status must be published")
        if envelope.initiator_id != publication.endpoint_id:
            raise ValueError("endpoint publication initiator does not match Endpoint")
        if publication.owner_wallet != envelope.sender_wallet:
            raise ValueError("endpoint publication owner does not match sender wallet")
        if not publication.owner_public_key:
            raise ValueError("endpoint publication requires an owner public key")
        expected_wallet_id = "wallet-" + hashlib.sha256(
            publication.owner_public_key.encode("utf-8")
        ).hexdigest()[:12]
        if publication.owner_wallet != expected_wallet_id:
            raise ValueError("endpoint publication owner wallet does not match public key")
        try:
            verify_publication_signature(
                public_key=publication.owner_public_key,
                signature=publication.wallet_signature,
                payload=publication.signed_payload(),
            )
        except ValueError as error:
            raise ValueError(str(error)) from error
        if len(envelope.signatures) != 1:
            raise ValueError("endpoint publication requires exactly one wallet signature")
        signature = envelope.signatures[0]
        if not signature.startswith("ed25519:"):
            raise ValueError("endpoint publication envelope signature is invalid")
        try:
            signature_bytes = bytes.fromhex(signature.removeprefix("ed25519:"))
            public_key_bytes = bytes.fromhex(
                publication.owner_public_key.removeprefix("ed25519:")
            )
            Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
                signature_bytes,
                envelope.signing_bytes(),
            )
        except (ValueError, InvalidSignature) as error:
            raise ValueError("endpoint publication envelope signature verification failed") from error

        for operation in self._operations:
            if operation.get("operation_type") != ENDPOINT_PUBLISH_OPERATION:
                continue
            existing_payload = operation.get("payload") or {}
            existing_publication = existing_payload.get("publication")
            if not isinstance(existing_publication, dict):
                continue
            if existing_publication.get("publication_id") == publication.publication_id:
                if existing_publication == publication_payload:
                    raise ValueError("endpoint publication is already committed")
                raise ValueError("endpoint publication id is already bound to another record")
            if existing_publication.get("endpoint_id") != publication.endpoint_id:
                continue
            if existing_publication.get("configuration_hash") == publication.configuration_hash:
                raise ValueError("endpoint publication configuration is already committed")
            if publication.sequence != int(existing_publication.get("sequence", 0)) + 1:
                raise ValueError("endpoint publication sequence is invalid")
            if publication.previous_configuration_hash != existing_publication.get(
                "configuration_hash"
            ):
                raise ValueError("endpoint publication previous hash is invalid")
        if publication.sequence == 1 and publication.previous_configuration_hash is not None:
            raise ValueError("first endpoint publication cannot have a previous hash")
        return {"publication": publication}

    def apply_consensus_endpoint_publish(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Persist one canonical Endpoint publication commitment."""
        self.validate_consensus_endpoint_publish(envelope)
        return self.record_admitted_envelope(
            envelope,
            emitted_events=["EndpointPublished"],
        )

    def validator_set_update_commitment(
        self,
        activation_epoch: int,
    ) -> dict | None:
        """Return the scheduled Validator Set update for one activation Epoch."""
        for operation in reversed(self._operations):
            if operation.get("operation_type") != "CONSENSUS_VALIDATOR_SET_UPDATE":
                continue
            payload = operation.get("payload") or {}
            if payload.get("activation_epoch") == activation_epoch:
                return dict(operation)
        return None

    def active_validator_set(self) -> dict[str, dict]:
        """Return the canonical active Validator Set in node-id order."""
        return {node_id: dict(entry) for node_id, entry in sorted(self._active_validator_set.items())}

    def active_validator_set_epoch(self) -> int | None:
        return self._active_validator_set_epoch

    def snapshot_consensus_state(self) -> dict:
        """Return consensus-owned state required for replay and State Sync."""
        return {
            "active_validator_set": self.active_validator_set(),
            "active_validator_set_epoch": self._active_validator_set_epoch,
            "activated_validator_set_epochs": sorted(self._activated_validator_set_epochs),
        }

    def restore_consensus_state(self, state: dict | None) -> None:
        """Restore consensus-owned state with bounded structural validation."""
        state = state or {}
        active = state.get("active_validator_set", {})
        if not isinstance(active, dict):
            raise ValueError("active validator set state is invalid")

        restored_active: dict[str, dict] = {}
        public_keys: set[str] = set()
        for raw_node_id, raw_entry in active.items():
            node_id = str(raw_node_id)
            if not node_id.strip() or not isinstance(raw_entry, dict):
                raise ValueError("active validator entry is invalid")
            entry = dict(raw_entry)
            public_key = entry.get("consensus_public_key")
            _decode_consensus_public_key(public_key)
            if not isinstance(public_key, str):
                raise ValueError("active validator public key is invalid")
            voting_power = entry.get("voting_power")
            if isinstance(voting_power, bool) or not isinstance(voting_power, int) or voting_power <= 0:
                raise ValueError("active validator voting power is invalid")
            if public_key in public_keys:
                raise ValueError("active validator public keys are not unique")
            public_keys.add(public_key)
            restored_active[node_id] = entry

        raw_epoch = state.get("active_validator_set_epoch")
        if raw_epoch is not None and (isinstance(raw_epoch, bool) or not isinstance(raw_epoch, int) or raw_epoch < 0):
            raise ValueError("active validator set epoch is invalid")

        raw_activated = state.get("activated_validator_set_epochs", [])
        if not isinstance(raw_activated, list):
            raise ValueError("activated validator set epochs are invalid")
        activated: set[int] = set()
        for value in raw_activated:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("activated validator set epoch is invalid")
            activated.add(value)

        self._active_validator_set = restored_active
        self._active_validator_set_epoch = raw_epoch
        self._activated_validator_set_epochs = activated

    def validate_consensus_validator_set_update(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        reject_existing: bool = True,
    ) -> dict:
        """Validate one protocol-only, typed Validator Set schedule."""
        if envelope.operation_type != "CONSENSUS_VALIDATOR_SET_UPDATE":
            raise ValueError("consensus validator set update requires CONSENSUS_VALIDATOR_SET_UPDATE")
        if envelope.origin_type != "protocol" or envelope.sender_wallet is not None:
            raise ValueError("validator set update requires protocol origin")

        payload = dict(envelope.payload)
        activation_epoch = payload.get("activation_epoch")
        if isinstance(activation_epoch, bool) or not isinstance(activation_epoch, int) or activation_epoch < 0:
            raise ValueError("validator set activation epoch is invalid")
        if envelope.target_epoch is not None and envelope.target_epoch != str(activation_epoch):
            raise ValueError("validator set target epoch does not match payload")

        for field_name in ("validator_set_hash", "eligibility_evidence_root"):
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"validator set field is invalid: {field_name}")

        additions = payload.get("validator_additions")
        removals = payload.get("validator_removals")
        voting_power_updates = payload.get("voting_power_updates")
        if not isinstance(additions, list):
            raise ValueError("validator additions must be a list")
        if not isinstance(removals, list):
            raise ValueError("validator removals must be a list")
        if not isinstance(voting_power_updates, list):
            raise ValueError("validator voting-power updates must be a list")
        if not additions and not removals and not voting_power_updates:
            raise ValueError("validator set update cannot be empty")

        def node_id(entry: object, field_name: str) -> str:
            if not isinstance(entry, dict):
                raise ValueError(f"{field_name} entry is invalid")
            value = entry.get("node_id")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} node_id is invalid")
            return value

        addition_ids: list[str] = []
        for entry in additions:
            identifier = node_id(entry, "validator addition")
            for field_name in (
                "operator_id",
                "consensus_address",
                "consensus_public_key",
            ):
                value = entry.get(field_name)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"validator addition field is invalid: {field_name}")
            _decode_consensus_public_key(entry["consensus_public_key"])
            for field_name in ("stake", "voting_power"):
                value = entry.get(field_name)
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ValueError(f"validator addition field is invalid: {field_name}")
            addition_ids.append(identifier)

        removal_ids = [node_id(entry, "validator removal") for entry in removals]
        update_ids: list[str] = []
        for entry in voting_power_updates:
            identifier = node_id(entry, "validator voting-power update")
            value = entry.get("voting_power") if isinstance(entry, dict) else None
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("validator voting-power update is invalid")
            update_ids.append(identifier)

        all_ids = addition_ids + removal_ids + update_ids
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("validator set membership update has overlap")

        existing = self.validator_set_update_commitment(activation_epoch)
        if reject_existing and existing is not None:
            raise ValueError("validator set update is already committed for activation epoch")

        from aidn_hypervisor.consensus.validator_schedule import (
            compute_validator_set_hash,
        )

        future_active = {node_id: dict(entry) for node_id, entry in self._active_validator_set.items()}
        active_public_keys = {
            str(entry.get("consensus_public_key")): node_id for node_id, entry in future_active.items()
        }
        for entry in additions:
            identifier = str(entry["node_id"])
            if identifier in future_active:
                raise ValueError("validator addition already exists in active set")
            public_key = str(entry["consensus_public_key"])
            if public_key in active_public_keys:
                raise ValueError("validator consensus public key is already active")
            future_active[identifier] = dict(entry)
            active_public_keys[public_key] = identifier

        for entry in removals:
            identifier = str(entry["node_id"])
            if identifier not in future_active:
                raise ValueError("validator removal does not target active member")
            public_key = str(future_active[identifier]["consensus_public_key"])
            del future_active[identifier]
            active_public_keys.pop(public_key, None)

        for entry in voting_power_updates:
            identifier = str(entry["node_id"])
            current = future_active.get(identifier)
            if current is None:
                raise ValueError("validator voting-power update does not target active member")
            current["voting_power"] = int(entry["voting_power"])

        expected_hash = compute_validator_set_hash(future_active.values())
        if payload["validator_set_hash"] != expected_hash:
            raise ValueError("validator set hash does not match final Validator Set")

        return {
            "payload": payload,
            "activation_epoch": activation_epoch,
            "addition_ids": addition_ids,
            "removal_ids": removal_ids,
            "update_ids": update_ids,
        }

    def apply_consensus_validator_set_update(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Validate and persist one scheduled Validator Set update."""
        self.validate_consensus_validator_set_update(envelope)
        return self.record_admitted_envelope(
            envelope,
            emitted_events=["ValidatorSetUpdateScheduled"],
        )

    def activate_consensus_validator_set_update(
        self,
        *,
        activation_epoch: int,
        finalized_operation_ids: set[str],
    ) -> list[dict]:
        """Activate a finalized schedule and return CometBFT updates.

        A schedule is only a Ledger commitment.  Activation happens once,
        at the matching Epoch transition, and is rejected unless the schedule
        was finalized before that transition's block.
        """
        if isinstance(activation_epoch, bool) or not isinstance(activation_epoch, int) or activation_epoch < 0:
            raise ValueError("validator set activation epoch is invalid")
        if activation_epoch in self._activated_validator_set_epochs:
            return []

        scheduled = self.validator_set_update_commitment(activation_epoch)
        if scheduled is None:
            return []
        operation_id = scheduled.get("operation_id")
        if not isinstance(operation_id, str) or operation_id not in finalized_operation_ids:
            raise ValueError("validator set schedule is not finalized")

        from aidn_hypervisor.consensus.models import LedgerOperationEnvelope

        envelope = LedgerOperationEnvelope.model_validate(scheduled)
        validated = self.validate_consensus_validator_set_update(
            envelope,
            reject_existing=False,
        )
        payload = validated["payload"]
        active = {node_id: dict(entry) for node_id, entry in self._active_validator_set.items()}
        active_public_keys = {str(entry["consensus_public_key"]): node_id for node_id, entry in active.items()}
        updates: list[dict] = []

        for entry in payload["validator_additions"]:
            node_id = str(entry["node_id"])
            if node_id in active:
                raise ValueError("validator addition already exists in active set")
            public_key = str(entry["consensus_public_key"])
            _decode_consensus_public_key(public_key)
            if public_key in active_public_keys:
                raise ValueError("validator consensus public key is already active")
            active[node_id] = dict(entry)
            active_public_keys[public_key] = node_id
            updates.append({"public_key": public_key, "power": int(entry["voting_power"])})

        for entry in payload["validator_removals"]:
            node_id = str(entry["node_id"])
            current = active.get(node_id)
            if current is None:
                raise ValueError("validator removal does not target active member")
            public_key = str(current["consensus_public_key"])
            updates.append({"public_key": public_key, "power": 0})
            del active[node_id]
            active_public_keys.pop(public_key, None)

        for entry in payload["voting_power_updates"]:
            node_id = str(entry["node_id"])
            current = active.get(node_id)
            if current is None:
                raise ValueError("validator voting-power update does not target active member")
            current["voting_power"] = int(entry["voting_power"])
            updates.append(
                {
                    "public_key": str(current["consensus_public_key"]),
                    "power": int(current["voting_power"]),
                }
            )

        self._active_validator_set = {node_id: dict(entry) for node_id, entry in sorted(active.items())}
        self._active_validator_set_epoch = activation_epoch
        self._activated_validator_set_epochs.add(activation_epoch)
        return sorted(updates, key=lambda item: (item["public_key"], item["power"]))

    def reward_mint_commitment(self, reward_id: str) -> dict | None:
        """Return the local idempotent commitment for one reward stage."""
        for operation in reversed(self._operations):
            if operation.get("operation_type") != "REWARD_MINT":
                continue
            payload = operation.get("payload") or {}
            if payload.get("reward_id") == reward_id:
                return dict(operation)
        return None

    def development_reward_calculation_commitment(
        self,
        commitment_id: str,
    ) -> dict | None:
        """Return one finalized ECO-0007 calculation evidence record."""
        for operation in reversed(self._operations):
            if operation.get("operation_type") != "DEVELOPMENT_REWARD_CALCULATE":
                continue
            payload = operation.get("payload") or {}
            if payload.get("commitment_id") == commitment_id:
                return dict(operation)
        return None

    def _validate_development_reward_calculation_payload(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        expected_operation_type: str = "DEVELOPMENT_REWARD_CALCULATE",
    ) -> dict:
        """Validate one self-contained, non-emitting ECO-0007 calculation."""
        from aidn_hypervisor.reward.development_activation import (
            DevelopmentRewardActivationApproval,
            verify_development_reward_activation_approval,
        )
        from aidn_hypervisor.reward.development_commitments import (
            DevelopmentRewardCommitment,
            build_development_reward_commitment,
        )
        from aidn_hypervisor.reward.development_distribution import (
            DevelopmentRewardCalculation,
            canonical_hash,
        )
        from aidn_hypervisor.reward.development_rollout import validate_development_reward_rollout

        if envelope.operation_type != expected_operation_type:
            raise ValueError("DEVELOPMENT_REWARD_CALCULATION_OPERATION_INVALID")
        if envelope.origin_type != "protocol" or envelope.sender_wallet is not None:
            raise ValueError("DEVELOPMENT_REWARD_CALCULATION_ORIGIN_INVALID")
        if envelope.fee_class != "protocol_sponsored":
            raise ValueError("DEVELOPMENT_REWARD_CALCULATION_FEE_INVALID")

        payload = dict(envelope.payload)
        payload_hash = payload.get("payload_hash")
        if not isinstance(payload_hash, str) or not payload_hash.strip():
            raise ValueError("DEVELOPMENT_REWARD_CALCULATION_PAYLOAD_HASH_INVALID")
        unsigned_payload = dict(payload)
        unsigned_payload.pop("payload_hash", None)
        if payload_hash != canonical_hash(unsigned_payload):
            raise ValueError("DEVELOPMENT_REWARD_CALCULATION_PAYLOAD_HASH_INVALID")

        epoch = payload.get("epoch")
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
            raise ValueError("DEVELOPMENT_REWARD_CALCULATION_EPOCH_INVALID")
        if envelope.target_epoch != str(epoch):
            raise ValueError("DEVELOPMENT_REWARD_CALCULATION_TARGET_EPOCH_INVALID")

        try:
            calculation = DevelopmentRewardCalculation.model_validate(payload.get("calculation"))
        except Exception as error:
            raise ValueError("DEVELOPMENT_REWARD_CALCULATION_EVIDENCE_INVALID") from error
        try:
            commitment = DevelopmentRewardCommitment.model_validate(payload.get("commitment"))
            approval = DevelopmentRewardActivationApproval.model_validate(payload.get("activation_approval"))
        except Exception as error:
            raise ValueError("DEVELOPMENT_REWARD_CALCULATION_EVIDENCE_INVALID") from error

        if not calculation.verify_integrity():
            raise ValueError("DEVELOPMENT_REWARD_CALCULATION_ROOT_INVALID")
        validate_development_reward_rollout(calculation, approval.rollout_profile)
        if not commitment.verify_integrity():
            raise ValueError("DEVELOPMENT_REWARD_COMMITMENT_INVALID")
        if commitment.activation_state != "ACTIVATION_VERIFIED":
            raise ValueError("DEVELOPMENT_REWARD_ACTIVATION_REQUIRED")
        if not commitment.simulation_only or commitment.emits_q or commitment.ledger_writes:
            raise ValueError("DEVELOPMENT_REWARD_COMMITMENT_EFFECT_INVALID")

        identity_fields = {
            "commitment_id": commitment.commitment_id,
            "commitment_hash": commitment.commitment_hash,
            "activation_id": approval.activation_id,
            "activation_approval_hash": approval.approval_hash,
            "policy_hash": commitment.policy_hash,
            "calculation_root": calculation.calculation_root,
            "epoch": calculation.epoch,
        }
        for field_name, expected in identity_fields.items():
            if payload.get(field_name) != expected:
                raise ValueError(f"DEVELOPMENT_REWARD_CALCULATION_BINDING_INVALID:{field_name}")

        if calculation.epoch != epoch:
            raise ValueError("DEVELOPMENT_REWARD_CALCULATION_EPOCH_MISMATCH")
        if commitment.calculation_root != calculation.calculation_root:
            raise ValueError("DEVELOPMENT_REWARD_COMMITMENT_CALCULATION_MISMATCH")
        if commitment.activation_id != approval.activation_id:
            raise ValueError("DEVELOPMENT_REWARD_COMMITMENT_ACTIVATION_MISMATCH")
        if commitment.activation_approval_hash != approval.approval_hash:
            raise ValueError("DEVELOPMENT_REWARD_COMMITMENT_APPROVAL_MISMATCH")

        try:
            expected_commitment = build_development_reward_commitment(
                calculation,
                activation_approval=approval,
                current_epoch=epoch,
            )
            verify_development_reward_activation_approval(approval)
        except ValueError as error:
            raise ValueError("DEVELOPMENT_REWARD_ACTIVATION_INVALID") from error
        if expected_commitment.model_dump(mode="json") != commitment.model_dump(mode="json"):
            raise ValueError("DEVELOPMENT_REWARD_COMMITMENT_MISMATCH")
        if expected_operation_type not in approval.authorized_operation_types:
            raise ValueError("DEVELOPMENT_REWARD_OPERATION_NOT_AUTHORIZED")
        if expected_operation_type == "DEVELOPMENT_POOL_ALLOCATE" and approval.economic_effect_profile not in {
            "POOL_ALLOCATION",
            "DEVELOPMENT_RESERVES",
            "DEVELOPMENT_PAYMENTS",
        }:
            raise ValueError("DEVELOPMENT_REWARD_POOL_ALLOCATION_SCOPE_INVALID")
        if expected_operation_type == "DEVELOPMENT_REWARD_RESERVE" and approval.economic_effect_profile not in {
            "DEVELOPMENT_RESERVES",
            "DEVELOPMENT_PAYMENTS",
        }:
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_SCOPE_INVALID")
        if (
            expected_operation_type == "DEVELOPMENT_REWARD_RESERVE"
            and approval.economic_effect_profile == "DEVELOPMENT_PAYMENTS"
            and not {
                "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
                "DEVELOPMENT_REWARD_PAY_MATURITY",
                "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
                "DEVELOPMENT_REWARD_CLAIM",
                "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED",
            }.intersection(approval.authorized_operation_types)
        ):
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_PAYMENT_SCOPE_INVALID")
        if (
            expected_operation_type
            in {
                "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
                "DEVELOPMENT_REWARD_PAY_MATURITY",
                "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
                "DEVELOPMENT_REWARD_CLAIM",
                "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED",
            }
            and approval.economic_effect_profile != "DEVELOPMENT_PAYMENTS"
        ):
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_SCOPE_INVALID")

        required_evidence = {
            commitment.commitment_id,
            commitment.commitment_hash,
            calculation.calculation_root,
            approval.activation_id,
            approval.approval_hash,
        }
        if not required_evidence.issubset(set(envelope.evidence_references)):
            raise ValueError("DEVELOPMENT_REWARD_CALCULATION_EVIDENCE_REFERENCES_INVALID")

        if expected_operation_type == "DEVELOPMENT_REWARD_CALCULATE":
            existing = self.development_reward_calculation_commitment(commitment.commitment_id)
            if existing is not None:
                if existing.get("payload") != payload:
                    raise ValueError("DEVELOPMENT_REWARD_CALCULATION_CONFLICT")
                raise ValueError("DEVELOPMENT_REWARD_CALCULATION_ALREADY_FINALIZED")
            for operation in self._operations:
                if operation.get("operation_type") != "DEVELOPMENT_REWARD_CALCULATE":
                    continue
                previous_payload = operation.get("payload") or {}
                if previous_payload.get("calculation_root") == calculation.calculation_root:
                    raise ValueError("DEVELOPMENT_REWARD_CALCULATION_ALREADY_FINALIZED")

        return {
            "payload": payload,
            "calculation": calculation,
            "commitment": commitment,
            "approval": approval,
        }

    def validate_consensus_development_reward_calculate(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        return self._validate_development_reward_calculation_payload(envelope)

    def apply_consensus_development_reward_calculate(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Commit calculation evidence without reserving or transferring Q."""
        self.validate_consensus_development_reward_calculate(envelope)
        return self.record_admitted_envelope(
            envelope,
            emitted_events=["DevelopmentRewardCalculationCommitted"],
        )

    def development_pool_allocation(self, allocation_id: str) -> dict | None:
        """Return one canonical development-pool allocation record."""

        allocation = self._development_pool_allocations.get(allocation_id)
        return None if allocation is None else dict(allocation)

    def _operation_by_id(self, operation_id: str) -> dict | None:
        for operation in reversed(self._operations):
            if operation.get("operation_id") == operation_id:
                return dict(operation)
        return None

    def validate_consensus_development_pool_allocate(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Validate a source-bound development-pool reservation.

        The source epoch budget and calculation must be finalized before this
        operation's block. The transition records a pool liability only; it
        never mints Q or credits a Wallet.
        """

        from aidn_hypervisor.reward.development_pool import (
            DevelopmentPoolAllocation,
            build_development_pool_allocation,
        )

        validated = self._validate_development_reward_calculation_payload(
            envelope,
            expected_operation_type="DEVELOPMENT_POOL_ALLOCATE",
        )
        payload = validated["payload"]
        calculation = validated["calculation"]
        commitment = validated["commitment"]

        calculation_operation_id = payload.get("calculation_operation_id")
        source_operation_id = payload.get("source_epoch_transition_operation_id")
        pool_budget_reference = payload.get("pool_budget_reference")
        pool_id = payload.get("pool_id")
        amount = payload.get("amount_q_atoms")
        if not isinstance(calculation_operation_id, str) or not calculation_operation_id.strip():
            raise ValueError("DEVELOPMENT_POOL_CALCULATION_OPERATION_REQUIRED")
        if not isinstance(source_operation_id, str) or not source_operation_id.strip():
            raise ValueError("DEVELOPMENT_POOL_EPOCH_TRANSITION_REQUIRED")
        if not isinstance(pool_budget_reference, str) or not pool_budget_reference.strip():
            raise ValueError("DEVELOPMENT_POOL_BUDGET_REFERENCE_INVALID")
        if not isinstance(pool_id, str) or not pool_id.strip():
            raise ValueError("DEVELOPMENT_POOL_ID_INVALID")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("DEVELOPMENT_POOL_ALLOCATION_AMOUNT_INVALID")

        if calculation_operation_id not in finalized_operation_ids:
            raise ValueError("DEVELOPMENT_POOL_CALCULATION_NOT_FINALIZED")
        calculation_operation = self._operation_by_id(calculation_operation_id)
        if calculation_operation is None or calculation_operation.get("operation_type") != (
            "DEVELOPMENT_REWARD_CALCULATE"
        ):
            raise ValueError("DEVELOPMENT_POOL_CALCULATION_OPERATION_INVALID")
        calculation_payload = calculation_operation.get("payload") or {}
        if (
            calculation_payload.get("commitment_id") != commitment.commitment_id
            or calculation_payload.get("calculation_root") != calculation.calculation_root
        ):
            raise ValueError("DEVELOPMENT_POOL_CALCULATION_BINDING_INVALID")

        if source_operation_id not in finalized_operation_ids:
            raise ValueError("DEVELOPMENT_POOL_EPOCH_TRANSITION_NOT_FINALIZED")
        source_operation = self._operation_by_id(source_operation_id)
        if source_operation is None or source_operation.get("operation_type") != "EPOCH_TRANSITION":
            raise ValueError("DEVELOPMENT_POOL_EPOCH_TRANSITION_INVALID")
        source_payload = source_operation.get("payload") or {}
        if source_payload.get("closing_epoch") != calculation.epoch:
            raise ValueError("DEVELOPMENT_POOL_EPOCH_MISMATCH")
        pool_budgets = source_payload.get("pool_budgets")
        if not isinstance(pool_budgets, dict) or pool_id not in pool_budgets:
            raise ValueError("DEVELOPMENT_POOL_BUDGET_NOT_AUTHORIZED")
        authorized_budget = pool_budgets[pool_id]
        if isinstance(authorized_budget, bool) or not isinstance(authorized_budget, int) or authorized_budget <= 0:
            raise ValueError("DEVELOPMENT_POOL_BUDGET_INVALID")
        pool_references = source_payload.get("pool_budget_references")
        if not isinstance(pool_references, dict) or pool_references.get(pool_id) != pool_budget_reference:
            raise ValueError("DEVELOPMENT_POOL_BUDGET_REFERENCE_MISMATCH")
        if amount != authorized_budget:
            raise ValueError("DEVELOPMENT_POOL_ALLOCATION_BUDGET_MISMATCH")
        if calculation.pool.base_allocation_q_atoms != amount or calculation.pool.pool_in_q_atoms != amount:
            raise ValueError("DEVELOPMENT_POOL_CALCULATION_BUDGET_MISMATCH")

        try:
            allocation = DevelopmentPoolAllocation.model_validate(payload.get("pool_allocation"))
        except Exception as error:
            raise ValueError("DEVELOPMENT_POOL_ALLOCATION_EVIDENCE_INVALID") from error
        if not allocation.verify_integrity():
            raise ValueError("DEVELOPMENT_POOL_ALLOCATION_HASH_INVALID")
        expected_allocation = build_development_pool_allocation(
            pool_id=pool_id,
            epoch=calculation.epoch,
            calculation_operation_id=calculation_operation_id,
            calculation_commitment_id=commitment.commitment_id,
            calculation_root=calculation.calculation_root,
            source_epoch_transition_operation_id=source_operation_id,
            source_pool_budget_reference=pool_budget_reference,
            authorized_budget_q_atoms=authorized_budget,
            allocated_q_atoms=amount,
        )
        if allocation.model_dump(mode="json") != expected_allocation.model_dump(mode="json"):
            raise ValueError("DEVELOPMENT_POOL_ALLOCATION_BINDING_INVALID")

        existing = self._development_pool_allocations.get(allocation.allocation_id)
        if existing is not None:
            if existing != allocation.model_dump(mode="json"):
                raise ValueError("DEVELOPMENT_POOL_ALLOCATION_CONFLICT")
            raise ValueError("DEVELOPMENT_POOL_ALLOCATION_ALREADY_FINALIZED")
        return {
            **validated,
            "allocation": allocation,
            "authorized_budget_q_atoms": authorized_budget,
        }

    def apply_consensus_development_pool_allocate(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Persist a source-bound pool reservation without Q movement."""

        validated = self.validate_consensus_development_pool_allocate(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        allocation = validated["allocation"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["DevelopmentPoolAllocated"],
        )
        self._development_pool_allocations[allocation.allocation_id] = allocation.model_dump(mode="json")
        return record

    def _validate_development_reward_adjustment_context(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        expected_operation_type: str,
    ) -> dict:
        """Validate activation/evidence binding for non-calculation ECO-0007 ops."""

        from aidn_hypervisor.reward.development_activation import (
            DevelopmentRewardActivationApproval,
            verify_development_reward_activation_approval,
        )
        from aidn_hypervisor.reward.development_commitments import DevelopmentRewardCommitment
        from aidn_hypervisor.reward.development_distribution import canonical_hash

        if envelope.operation_type != expected_operation_type:
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_OPERATION_INVALID")
        if envelope.origin_type != "protocol" or envelope.sender_wallet is not None:
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_ORIGIN_INVALID")
        if envelope.fee_class != "protocol_sponsored":
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_FEE_INVALID")
        payload = dict(envelope.payload)
        payload_hash = payload.get("payload_hash")
        if not isinstance(payload_hash, str) or payload_hash != canonical_hash(
            {key: value for key, value in payload.items() if key != "payload_hash"}
        ):
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_PAYLOAD_HASH_INVALID")
        epoch = payload.get("epoch")
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_EPOCH_INVALID")
        if envelope.target_epoch != str(epoch):
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_TARGET_EPOCH_INVALID")
        try:
            commitment = DevelopmentRewardCommitment.model_validate(payload.get("commitment"))
            approval = DevelopmentRewardActivationApproval.model_validate(payload.get("activation_approval"))
        except Exception as error:
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_EVIDENCE_INVALID") from error
        if not commitment.verify_integrity() or commitment.activation_state != "ACTIVATION_VERIFIED":
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_COMMITMENT_INVALID")
        if commitment.simulation_only is not True or commitment.emits_q or commitment.ledger_writes:
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_COMMITMENT_EFFECT_INVALID")
        try:
            verify_development_reward_activation_approval(approval)
        except ValueError as error:
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_ACTIVATION_INVALID") from error
        identity_fields = {
            "commitment_id": commitment.commitment_id,
            "commitment_hash": commitment.commitment_hash,
            "activation_id": approval.activation_id,
            "activation_approval_hash": approval.approval_hash,
            "policy_hash": commitment.policy_hash,
            "calculation_root": commitment.calculation_root,
        }
        for field_name, expected in identity_fields.items():
            if payload.get(field_name) != expected:
                raise ValueError(f"DEVELOPMENT_REWARD_ADJUSTMENT_BINDING_INVALID:{field_name}")
        if payload.get("epoch") != commitment.epoch:
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_BINDING_INVALID:epoch")
        if (
            commitment.activation_id != approval.activation_id
            or commitment.activation_approval_hash != approval.approval_hash
        ):
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_ACTIVATION_MISMATCH")
        if expected_operation_type not in approval.authorized_operation_types:
            raise ValueError("DEVELOPMENT_REWARD_OPERATION_NOT_AUTHORIZED")
        if expected_operation_type == "DEVELOPMENT_POOL_CARRYOVER":
            allowed_profiles = {"POOL_ALLOCATION", "DEVELOPMENT_RESERVES", "DEVELOPMENT_PAYMENTS"}
        else:
            allowed_profiles = {"DEVELOPMENT_RESERVES", "DEVELOPMENT_PAYMENTS"}
        if approval.economic_effect_profile not in allowed_profiles:
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_SCOPE_INVALID")
        required_evidence = {
            commitment.commitment_id,
            commitment.commitment_hash,
            commitment.calculation_root,
            approval.activation_id,
            approval.approval_hash,
        }
        if not required_evidence.issubset(set(envelope.evidence_references)):
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_EVIDENCE_REFERENCES_INVALID")
        return {
            "payload": payload,
            "commitment": commitment,
            "approval": approval,
            "epoch": epoch,
        }

    def development_pool_carryover(self, carryover_id: str) -> dict | None:
        record = self._development_pool_carryovers.get(carryover_id)
        return None if record is None else dict(record)

    def validate_consensus_development_pool_carryover(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        from aidn_hypervisor.reward.development_carryover import DevelopmentPoolCarryoverRecord

        validated = self._validate_development_reward_adjustment_context(
            envelope,
            expected_operation_type="DEVELOPMENT_POOL_CARRYOVER",
        )
        payload = validated["payload"]
        try:
            carryover = DevelopmentPoolCarryoverRecord.model_validate(payload.get("pool_carryover"))
        except Exception as error:
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_RECORD_INVALID") from error
        if not carryover.verify_integrity():
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_HASH_INVALID")
        source_operation_id = payload.get("source_epoch_transition_operation_id")
        if not isinstance(source_operation_id, str) or source_operation_id not in finalized_operation_ids:
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_EPOCH_TRANSITION_NOT_FINALIZED")
        source_operation = self._operation_by_id(source_operation_id)
        if source_operation is None or source_operation.get("operation_type") != "EPOCH_TRANSITION":
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_EPOCH_TRANSITION_INVALID")
        source_payload = source_operation.get("payload") or {}
        if (
            source_payload.get("closing_epoch") != carryover.source_epoch
            or source_payload.get("opening_epoch") != carryover.target_epoch
        ):
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_EPOCH_MISMATCH")
        if carryover.source_epoch != validated["commitment"].epoch:
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_SOURCE_EPOCH_INVALID")
        if carryover.carryover_id in self._development_pool_carryovers:
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_DUPLICATE")
        return {**validated, "carryover": carryover}

    def apply_consensus_development_pool_carryover(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        validated = self.validate_consensus_development_pool_carryover(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        carryover = validated["carryover"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["DevelopmentPoolCarriedOver"],
        )
        self._development_pool_carryovers[carryover.carryover_id] = carryover.model_dump(mode="json")
        return record

    def development_bounty_state(self, bounty_id: str) -> dict | None:
        state = self._development_bounty_states.get(bounty_id)
        return None if state is None else dict(state)

    def _bounty_state(self, bounty_id: str):
        from aidn_hypervisor.reward.development_bounty import DevelopmentBountyState

        raw = self._development_bounty_states.get(bounty_id)
        if raw is None:
            raise ValueError("DEVELOPMENT_BOUNTY_NOT_FOUND")
        try:
            state = DevelopmentBountyState.model_validate(raw)
        except Exception as error:
            raise ValueError("DEVELOPMENT_BOUNTY_STATE_INVALID") from error
        if not state.verify_integrity():
            raise ValueError("DEVELOPMENT_BOUNTY_STATE_HASH_INVALID")
        return state

    def validate_consensus_development_bounty_create(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        from aidn_hypervisor.reward.development_bounty import (
            DevelopmentBounty,
            build_development_bounty_state,
        )

        validated = self._validate_development_reward_adjustment_context(
            envelope,
            expected_operation_type="DEVELOPMENT_BOUNTY_CREATE",
        )
        try:
            bounty = DevelopmentBounty.model_validate(validated["payload"].get("bounty"))
        except Exception as error:
            raise ValueError("DEVELOPMENT_BOUNTY_RECORD_INVALID") from error
        if not bounty.verify_integrity() or bounty.bounty_id != validated["payload"].get("bounty_id"):
            raise ValueError("DEVELOPMENT_BOUNTY_BINDING_INVALID")
        if bounty.created_epoch != validated["epoch"]:
            raise ValueError("DEVELOPMENT_BOUNTY_EPOCH_INVALID")
        if bounty.bounty_id in self._development_bounty_states:
            raise ValueError("DEVELOPMENT_BOUNTY_DUPLICATE")
        return {**validated, "bounty": bounty, "bounty_state": build_development_bounty_state(bounty)}

    def apply_consensus_development_bounty_create(
        self, envelope: "LedgerOperationEnvelope", *, finalized_operation_ids: set[str]
    ) -> dict:
        validated = self.validate_consensus_development_bounty_create(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        state = validated["bounty_state"]
        record = self.record_admitted_envelope(envelope, emitted_events=["DevelopmentBountyCreated"])
        self._development_bounty_states[state.bounty.bounty_id] = state.model_dump(mode="json")
        return record

    def validate_consensus_development_bounty_reserve(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        from aidn_hypervisor.reward.development_bounty import (
            DevelopmentBountyReservation,
            apply_development_bounty_reservation,
        )

        validated = self._validate_development_reward_adjustment_context(
            envelope,
            expected_operation_type="DEVELOPMENT_BOUNTY_RESERVE",
        )
        payload = validated["payload"]
        state = self._bounty_state(str(payload.get("bounty_id")))
        try:
            reservation = DevelopmentBountyReservation.model_validate(payload.get("bounty_reservation"))
        except Exception as error:
            raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_INVALID") from error
        if not reservation.verify_integrity() or reservation.bounty_id != state.bounty.bounty_id:
            raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_BINDING_INVALID")
        allocation_id = payload.get("pool_allocation_id")
        allocation_operation_id = payload.get("pool_allocation_operation_id")
        if not isinstance(allocation_id, str) or not isinstance(allocation_operation_id, str):
            raise ValueError("DEVELOPMENT_BOUNTY_POOL_ALLOCATION_REQUIRED")
        if allocation_operation_id not in finalized_operation_ids:
            raise ValueError("DEVELOPMENT_BOUNTY_POOL_ALLOCATION_NOT_FINALIZED")
        allocation = self._development_pool_allocations.get(allocation_id)
        allocation_operation = self._operation_by_id(allocation_operation_id)
        if (
            allocation is None
            or allocation_operation is None
            or allocation_operation.get("operation_type") != "DEVELOPMENT_POOL_ALLOCATE"
        ):
            raise ValueError("DEVELOPMENT_BOUNTY_POOL_ALLOCATION_INVALID")
        if reservation.source_pool_reference != allocation_id or reservation.source_pool_id != allocation.get(
            "pool_id"
        ):
            raise ValueError("DEVELOPMENT_BOUNTY_POOL_ALLOCATION_BINDING_INVALID")
        active_bounty_reserved = 0
        for raw_state in self._development_bounty_states.values():
            other = self._bounty_state(str(raw_state["bounty"]["bounty_id"]))
            active_bounty_reserved += sum(
                item.amount_q_atoms for item in other.active_reservations if item.source_pool_reference == allocation_id
            )
        reward_reserved = sum(
            int(item.get("reserved_q_atoms", 0))
            for item in self._development_reward_reserves.values()
            if item.get("pool_allocation_id") == allocation_id
        )
        if active_bounty_reserved + reward_reserved + reservation.amount_q_atoms > int(allocation["allocated_q_atoms"]):
            raise ValueError("DEVELOPMENT_BOUNTY_POOL_EXCEEDED")
        try:
            next_state = apply_development_bounty_reservation(state, reservation)
        except ValueError as error:
            raise ValueError(str(error)) from error
        return {**validated, "reservation": reservation, "bounty_state": next_state}

    def apply_consensus_development_bounty_reserve(
        self, envelope: "LedgerOperationEnvelope", *, finalized_operation_ids: set[str]
    ) -> dict:
        validated = self.validate_consensus_development_bounty_reserve(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        state = validated["bounty_state"]
        record = self.record_admitted_envelope(envelope, emitted_events=["DevelopmentBountyReserved"])
        self._development_bounty_states[state.bounty.bounty_id] = state.model_dump(mode="json")
        return record

    def validate_consensus_development_bounty_release(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        from aidn_hypervisor.reward.development_bounty import (
            DevelopmentBountyRelease,
            apply_development_bounty_release,
        )

        validated = self._validate_development_reward_adjustment_context(
            envelope,
            expected_operation_type="DEVELOPMENT_BOUNTY_RELEASE",
        )
        state = self._bounty_state(str(validated["payload"].get("bounty_id")))
        try:
            release = DevelopmentBountyRelease.model_validate(validated["payload"].get("bounty_release"))
            next_state = apply_development_bounty_release(state, release)
        except Exception as error:
            raise ValueError("DEVELOPMENT_BOUNTY_RELEASE_INVALID") from error
        return {**validated, "release": release, "bounty_state": next_state}

    def apply_consensus_development_bounty_release(
        self, envelope: "LedgerOperationEnvelope", *, finalized_operation_ids: set[str]
    ) -> dict:
        validated = self.validate_consensus_development_bounty_release(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        state = validated["bounty_state"]
        record = self.record_admitted_envelope(envelope, emitted_events=["DevelopmentBountyReleased"])
        self._development_bounty_states[state.bounty.bounty_id] = state.model_dump(mode="json")
        return record

    def validate_consensus_development_bounty_expire(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        from aidn_hypervisor.reward.development_bounty import (
            DevelopmentBountyExpiry,
            apply_development_bounty_expiry,
        )

        validated = self._validate_development_reward_adjustment_context(
            envelope,
            expected_operation_type="DEVELOPMENT_BOUNTY_EXPIRE",
        )
        state = self._bounty_state(str(validated["payload"].get("bounty_id")))
        try:
            expiry = DevelopmentBountyExpiry.model_validate(validated["payload"].get("bounty_expiry"))
            next_state = apply_development_bounty_expiry(state, expiry)
        except Exception as error:
            raise ValueError("DEVELOPMENT_BOUNTY_EXPIRY_INVALID") from error
        return {**validated, "expiry": expiry, "bounty_state": next_state}

    def apply_consensus_development_bounty_expire(
        self, envelope: "LedgerOperationEnvelope", *, finalized_operation_ids: set[str]
    ) -> dict:
        validated = self.validate_consensus_development_bounty_expire(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        state = validated["bounty_state"]
        record = self.record_admitted_envelope(envelope, emitted_events=["DevelopmentBountyExpired"])
        self._development_bounty_states[state.bounty.bounty_id] = state.model_dump(mode="json")
        return record

    def _validate_adjustment_snapshot(self, payload: dict):
        from aidn_hypervisor.reward.development_adjustments import DevelopmentRewardStateSnapshot

        try:
            snapshot = DevelopmentRewardStateSnapshot.model_validate(payload.get("reward_state_snapshot"))
        except Exception as error:
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_SNAPSHOT_INVALID") from error
        if not snapshot.verify_integrity():
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_SNAPSHOT_HASH_INVALID")
        existing = self._development_reward_adjustment_snapshots.get(snapshot.snapshot_id)
        if existing is not None and existing != snapshot.model_dump(mode="json"):
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_SNAPSHOT_CONFLICT")
        return snapshot

    def validate_consensus_development_reward_cancel_unvested(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        from aidn_hypervisor.reward.development_cancellation import (
            DevelopmentRewardCancellationRecord,
            validate_cancellation_history,
        )

        validated = self._validate_development_reward_adjustment_context(
            envelope,
            expected_operation_type="DEVELOPMENT_REWARD_CANCEL_UNVESTED",
        )
        snapshot = self._validate_adjustment_snapshot(validated["payload"])
        try:
            cancellation = DevelopmentRewardCancellationRecord.model_validate(
                validated["payload"].get("reward_cancellation")
            )
            previous = [
                DevelopmentRewardCancellationRecord.model_validate(item)
                for item in self._development_reward_cancellations.values()
                if item.get("source_snapshot_id") == snapshot.snapshot_id
            ]
            validate_cancellation_history(snapshot, [*previous, cancellation])
        except ValueError as error:
            raise ValueError(str(error)) from error
        if cancellation.cancellation_id in self._development_reward_cancellations:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_DUPLICATE")
        if cancellation.reward_id != validated["payload"].get("reward_id"):
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_REWARD_MISMATCH")
        return {**validated, "snapshot": snapshot, "cancellation": cancellation}

    def apply_consensus_development_reward_cancel_unvested(
        self, envelope: "LedgerOperationEnvelope", *, finalized_operation_ids: set[str]
    ) -> dict:
        validated = self.validate_consensus_development_reward_cancel_unvested(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        snapshot = validated["snapshot"]
        cancellation = validated["cancellation"]
        record = self.record_admitted_envelope(envelope, emitted_events=["DevelopmentRewardUnvestedCancelled"])
        self._development_reward_adjustment_snapshots[snapshot.snapshot_id] = snapshot.model_dump(mode="json")
        self._development_reward_cancellations[cancellation.cancellation_id] = cancellation.model_dump(mode="json")
        return record

    def validate_consensus_development_reward_correct(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        from aidn_hypervisor.reward.development_correction import (
            DevelopmentRewardCorrectionRecord,
            validate_reward_correction_history,
        )

        validated = self._validate_development_reward_adjustment_context(
            envelope,
            expected_operation_type="DEVELOPMENT_REWARD_CORRECT",
        )
        snapshot = self._validate_adjustment_snapshot(validated["payload"])
        try:
            correction = DevelopmentRewardCorrectionRecord.model_validate(validated["payload"].get("reward_correction"))
            previous = [
                DevelopmentRewardCorrectionRecord.model_validate(item)
                for item in self._development_reward_corrections.values()
                if item.get("source_snapshot_id") == snapshot.snapshot_id
            ]
            validate_reward_correction_history(snapshot, [*previous, correction])
        except ValueError as error:
            raise ValueError(str(error)) from error
        if correction.correction_id in self._development_reward_corrections:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_DUPLICATE")
        if correction.reward_id != validated["payload"].get("reward_id"):
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_REWARD_MISMATCH")
        return {**validated, "snapshot": snapshot, "correction": correction}

    def apply_consensus_development_reward_correct(
        self, envelope: "LedgerOperationEnvelope", *, finalized_operation_ids: set[str]
    ) -> dict:
        validated = self.validate_consensus_development_reward_correct(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        snapshot = validated["snapshot"]
        correction = validated["correction"]
        record = self.record_admitted_envelope(envelope, emitted_events=["DevelopmentRewardCorrected"])
        self._development_reward_adjustment_snapshots[snapshot.snapshot_id] = snapshot.model_dump(mode="json")
        self._development_reward_corrections[correction.correction_id] = correction.model_dump(mode="json")
        return record

    def development_reward_reserve(self, reserve_id: str) -> dict | None:
        """Return one canonical development reward reserve record."""

        reserve = self._development_reward_reserves.get(reserve_id)
        return None if reserve is None else dict(reserve)

    def validate_consensus_development_reward_reserve(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Validate one reward reserve against finalized source records."""

        from aidn_hypervisor.reward.development_reserve import (
            DevelopmentRewardReserve,
            build_development_reward_reserve,
        )

        validated = self._validate_development_reward_calculation_payload(
            envelope,
            expected_operation_type="DEVELOPMENT_REWARD_RESERVE",
        )
        payload = validated["payload"]
        calculation = validated["calculation"]
        commitment = validated["commitment"]

        calculation_operation_id = payload.get("calculation_operation_id")
        pool_allocation_id = payload.get("pool_allocation_id")
        pool_allocation_operation_id = payload.get("pool_allocation_operation_id")
        reward_id = payload.get("reward_id")
        if not isinstance(calculation_operation_id, str) or not calculation_operation_id.strip():
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_CALCULATION_OPERATION_REQUIRED")
        if not isinstance(pool_allocation_id, str) or not pool_allocation_id.strip():
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_POOL_ALLOCATION_REQUIRED")
        if not isinstance(pool_allocation_operation_id, str) or not pool_allocation_operation_id.strip():
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_POOL_ALLOCATION_OPERATION_REQUIRED")
        if not isinstance(reward_id, str) or not reward_id.strip():
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_REWARD_REQUIRED")

        if calculation_operation_id not in finalized_operation_ids:
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_CALCULATION_NOT_FINALIZED")
        calculation_operation = self._operation_by_id(calculation_operation_id)
        if calculation_operation is None or calculation_operation.get("operation_type") != (
            "DEVELOPMENT_REWARD_CALCULATE"
        ):
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_CALCULATION_OPERATION_INVALID")
        calculation_payload = calculation_operation.get("payload") or {}
        if (
            calculation_payload.get("commitment_id") != commitment.commitment_id
            or calculation_payload.get("calculation_root") != calculation.calculation_root
        ):
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_CALCULATION_BINDING_INVALID")

        if pool_allocation_operation_id not in finalized_operation_ids:
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_POOL_ALLOCATION_NOT_FINALIZED")
        pool_allocation_operation = self._operation_by_id(pool_allocation_operation_id)
        if pool_allocation_operation is None or pool_allocation_operation.get("operation_type") != (
            "DEVELOPMENT_POOL_ALLOCATE"
        ):
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_POOL_ALLOCATION_OPERATION_INVALID")
        pool_allocation_payload = pool_allocation_operation.get("payload") or {}
        nested_allocation = pool_allocation_payload.get("pool_allocation") or {}
        if nested_allocation.get("allocation_id") != pool_allocation_id:
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_POOL_ALLOCATION_BINDING_INVALID")
        allocation = self._development_pool_allocations.get(pool_allocation_id)
        if allocation is None:
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_POOL_ALLOCATION_NOT_FOUND")
        if (
            allocation.get("calculation_operation_id") != calculation_operation_id
            or allocation.get("calculation_commitment_id") != commitment.commitment_id
            or allocation.get("calculation_root") != calculation.calculation_root
        ):
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_POOL_ALLOCATION_SOURCE_MISMATCH")

        schedule = next(
            (item for item in calculation.schedules if item.reward_id == reward_id),
            None,
        )
        if schedule is None:
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_REWARD_NOT_FOUND")
        try:
            reserve = DevelopmentRewardReserve.model_validate(payload.get("reward_reserve"))
        except Exception as error:
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_EVIDENCE_INVALID") from error
        if not reserve.verify_integrity():
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_HASH_INVALID")
        expected_reserve = build_development_reward_reserve(
            pool_allocation_id=pool_allocation_id,
            pool_allocation_operation_id=pool_allocation_operation_id,
            calculation_operation_id=calculation_operation_id,
            calculation_commitment_id=commitment.commitment_id,
            calculation_root=calculation.calculation_root,
            schedule=schedule,
        )
        if reserve.model_dump(mode="json") != expected_reserve.model_dump(mode="json"):
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_BINDING_INVALID")

        existing = self._development_reward_reserves.get(reserve.reserve_id)
        if existing is not None:
            if existing != reserve.model_dump(mode="json"):
                raise ValueError("DEVELOPMENT_REWARD_RESERVE_CONFLICT")
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_ALREADY_FINALIZED")
        reserved_total = sum(
            int(item.get("reserved_q_atoms", 0))
            for item in self._development_reward_reserves.values()
            if item.get("pool_allocation_id") == pool_allocation_id
        )
        returned_total = sum(
            int(item.get("amount_q_atoms", 0))
            for item in self._development_reward_expiry_records.values()
            if item.get("pool_allocation_id") == pool_allocation_id
        )
        allocation_budget = allocation.get("allocated_q_atoms")
        if (
            isinstance(allocation_budget, bool)
            or not isinstance(allocation_budget, int)
            or allocation_budget <= 0
            or reserved_total - returned_total + reserve.reserved_q_atoms > allocation_budget
            or reserved_total - returned_total < 0
        ):
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_POOL_EXCEEDED")
        return {
            **validated,
            "reserve": reserve,
            "allocation": allocation,
            "reserved_total_q_atoms": reserved_total,
        }

    def apply_consensus_development_reward_reserve(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Persist a reward reserve without transferring or minting Q."""

        validated = self.validate_consensus_development_reward_reserve(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        reserve = validated["reserve"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["DevelopmentRewardReserved"],
        )
        self._development_reward_reserves[reserve.reserve_id] = reserve.model_dump(mode="json")
        return record

    def development_reward_payment(self, payment_id: str) -> dict | None:
        """Return one canonical ECO-0007 payment record."""

        payment = self._development_reward_payment_records.get(payment_id)
        return None if payment is None else dict(payment)

    def development_reward_unclaimed(self, unclaimed_id: str) -> dict | None:
        """Return one canonical ECO-0007 unclaimed record."""

        record = self._development_reward_unclaimed_records.get(unclaimed_id)
        return None if record is None else dict(record)

    def development_reward_claim(self, claim_id: str) -> dict | None:
        """Return one canonical ECO-0007 Wallet claim record."""

        record = self._development_reward_claim_records.get(claim_id)
        return None if record is None else dict(record)

    def development_reward_expiry(self, expiry_id: str) -> dict | None:
        """Return one canonical ECO-0007 expiry-return record."""

        record = self._development_reward_expiry_records.get(expiry_id)
        return None if record is None else dict(record)

    def development_reward_finalized_commitment(self, commitment_id: str) -> dict | None:
        """Return one canonical finalized ECO-0007 evidence commitment."""

        record = self._development_reward_finalized_commitments.get(commitment_id)
        return None if record is None else dict(record)

    def _validate_consensus_development_reward_payment(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
        expected_operation_type: str,
        expected_payment_stages: set[str],
        expected_payment_states: set[str],
    ) -> dict:
        """Validate one development reward payment against finalized evidence."""

        from aidn_hypervisor.reward.development_distribution import (
            DevelopmentRewardPayment,
            canonical_hash,
        )
        from aidn_hypervisor.reward.development_payment import (
            build_development_reward_payment_record,
            development_reward_payment_id,
        )
        from aidn_hypervisor.reward.development_unclaimed import (
            build_development_reward_unclaimed_record,
            development_reward_unclaimed_id,
        )

        validated = self._validate_development_reward_calculation_payload(
            envelope,
            expected_operation_type=expected_operation_type,
        )
        payload = validated["payload"]
        calculation = validated["calculation"]
        commitment = validated["commitment"]

        required_text = [
            "calculation_operation_id",
            "pool_allocation_id",
            "pool_allocation_operation_id",
            "reserve_id",
            "reserve_operation_id",
            "reward_id",
            "contributor_id",
            "role",
            "payment_hash",
        ]
        if expected_operation_type != "DEVELOPMENT_REWARD_MARK_UNCLAIMED":
            required_text.append("recipient_wallet")
        if expected_operation_type == "DEVELOPMENT_REWARD_PAY_MATURITY":
            required_text.append("source_epoch_transition_operation_id")
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"DEVELOPMENT_REWARD_PAYMENT_FIELD_INVALID:{field_name}")

        if payload.get("payment_stage") not in expected_payment_stages:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_STAGE_INVALID")
        amount = payload.get("amount_q_atoms")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_AMOUNT_INVALID")

        calculation_operation_id = payload["calculation_operation_id"]
        pool_allocation_operation_id = payload["pool_allocation_operation_id"]
        reserve_operation_id = payload["reserve_operation_id"]
        for operation_id, error_code in (
            (calculation_operation_id, "DEVELOPMENT_REWARD_PAYMENT_CALCULATION_NOT_FINALIZED"),
            (pool_allocation_operation_id, "DEVELOPMENT_REWARD_PAYMENT_POOL_ALLOCATION_NOT_FINALIZED"),
            (reserve_operation_id, "DEVELOPMENT_REWARD_PAYMENT_RESERVE_NOT_FINALIZED"),
        ):
            if operation_id not in finalized_operation_ids:
                raise ValueError(error_code)
        if expected_operation_type == "DEVELOPMENT_REWARD_PAY_MATURITY":
            source_epoch_transition_operation_id = payload["source_epoch_transition_operation_id"]
            if source_epoch_transition_operation_id not in finalized_operation_ids:
                raise ValueError("DEVELOPMENT_REWARD_PAYMENT_MATURITY_EPOCH_NOT_FINALIZED")

        calculation_operation = self._operation_by_id(calculation_operation_id)
        if calculation_operation is None or calculation_operation.get("operation_type") != (
            "DEVELOPMENT_REWARD_CALCULATE"
        ):
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_CALCULATION_OPERATION_INVALID")
        calculation_payload = calculation_operation.get("payload") or {}
        if (
            calculation_payload.get("commitment_id") != commitment.commitment_id
            or calculation_payload.get("calculation_root") != calculation.calculation_root
        ):
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_CALCULATION_BINDING_INVALID")

        pool_allocation_operation = self._operation_by_id(pool_allocation_operation_id)
        if pool_allocation_operation is None or pool_allocation_operation.get("operation_type") != (
            "DEVELOPMENT_POOL_ALLOCATE"
        ):
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_POOL_ALLOCATION_OPERATION_INVALID")
        pool_allocation_payload = pool_allocation_operation.get("payload") or {}
        nested_allocation = pool_allocation_payload.get("pool_allocation") or {}
        pool_allocation_id = payload["pool_allocation_id"]
        if nested_allocation.get("allocation_id") != pool_allocation_id:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_POOL_ALLOCATION_BINDING_INVALID")
        allocation = self._development_pool_allocations.get(pool_allocation_id)
        if allocation is None:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_POOL_ALLOCATION_NOT_FOUND")

        reserve_operation = self._operation_by_id(reserve_operation_id)
        if reserve_operation is None or reserve_operation.get("operation_type") != ("DEVELOPMENT_REWARD_RESERVE"):
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_RESERVE_OPERATION_INVALID")
        reserve_payload = reserve_operation.get("payload") or {}
        nested_reserve = reserve_payload.get("reward_reserve") or {}
        reserve_id = payload["reserve_id"]
        if nested_reserve.get("reserve_id") != reserve_id:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_RESERVE_BINDING_INVALID")
        reserve = self._development_reward_reserves.get(reserve_id)
        if reserve is None:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_RESERVE_NOT_FOUND")
        if (
            reserve.get("pool_allocation_id") != pool_allocation_id
            or reserve.get("pool_allocation_operation_id") != pool_allocation_operation_id
            or reserve.get("calculation_operation_id") != calculation_operation_id
            or reserve.get("calculation_commitment_id") != commitment.commitment_id
            or reserve.get("calculation_root") != calculation.calculation_root
        ):
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_RESERVE_SOURCE_MISMATCH")

        try:
            payment = DevelopmentRewardPayment.model_validate(payload.get("reward_payment"))
        except Exception as error:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_EVIDENCE_INVALID") from error
        if payment.payment_hash != canonical_hash(payment.model_dump(mode="json", exclude={"payment_hash"})):
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_HASH_INVALID")
        expected_payment = {
            "reward_id": payment.reward_id,
            "contributor_id": payment.contributor_id,
            "recipient_wallet": payment.wallet_address,
            "role": payment.role,
            "payment_stage": payment.payment_stage,
            "payment_hash": payment.payment_hash,
            "amount_q_atoms": payment.amount_q_atoms,
        }
        actual_payment = {
            "reward_id": payload["reward_id"],
            "contributor_id": payload["contributor_id"],
            "recipient_wallet": payload.get("recipient_wallet"),
            "role": payload["role"],
            "payment_stage": payload["payment_stage"],
            "payment_hash": payload["payment_hash"],
            "amount_q_atoms": amount,
        }
        if expected_payment != actual_payment:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_BINDING_INVALID")
        if payment.state not in expected_payment_states or payment.payment_stage not in expected_payment_stages:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_NOT_PAYABLE")
        if expected_operation_type == "DEVELOPMENT_REWARD_MARK_UNCLAIMED":
            if payment.state != "UNCLAIMED" or payment.wallet_address is not None:
                raise ValueError("DEVELOPMENT_REWARD_UNCLAIMED_STATE_INVALID")
        elif not payment.wallet_address:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_NOT_PAYABLE")
        if payment.reward_id != reserve.get("reward_id"):
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_REWARD_MISMATCH")

        schedule = next(
            (item for item in calculation.schedules if item.reward_id == payment.reward_id),
            None,
        )
        if schedule is None or schedule.schedule_hash != reserve.get("schedule_hash"):
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_SCHEDULE_MISMATCH")
        if expected_operation_type == "DEVELOPMENT_REWARD_PAY_MATURITY":
            source_operation = self._operation_by_id(payload["source_epoch_transition_operation_id"])
            if source_operation is None or source_operation.get("operation_type") != "EPOCH_TRANSITION":
                raise ValueError("DEVELOPMENT_REWARD_PAYMENT_MATURITY_EPOCH_INVALID")
            source_payload = source_operation.get("payload") or {}
            opening_epoch = source_payload.get("opening_epoch")
            maturity_epoch = (
                schedule.maturity_stage_one_epoch
                if payment.payment_stage == "MATURITY_STAGE_ONE"
                else schedule.maturity_stage_two_epoch
            )
            if isinstance(opening_epoch, bool) or not isinstance(opening_epoch, int):
                raise ValueError("DEVELOPMENT_REWARD_PAYMENT_MATURITY_EPOCH_INVALID")
            if opening_epoch < maturity_epoch:
                raise ValueError("DEVELOPMENT_REWARD_MATURITY_NOT_REACHED")

        payment_id = development_reward_payment_id(
            reserve_id=reserve_id,
            payment_hash=payment.payment_hash,
            payment_stage=payment.payment_stage,
        )
        unclaimed_id = development_reward_unclaimed_id(
            reserve_id=reserve_id,
            payment_hash=payment.payment_hash,
            payment_stage=payment.payment_stage,
        )
        if expected_operation_type == "DEVELOPMENT_REWARD_MARK_UNCLAIMED":
            if self._development_reward_unclaimed_records.get(unclaimed_id) is not None:
                raise ValueError("DEVELOPMENT_REWARD_UNCLAIMED_DUPLICATE")
        elif self._development_reward_payment_records.get(payment_id) is not None:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_DUPLICATE")

        reserve_records = [
            item for item in self._development_reward_payment_records.values() if item.get("reserve_id") == reserve_id
        ]
        reserve_paid_before = sum(int(item.get("amount_q_atoms", 0)) for item in reserve_records)
        consumed_amount = 0 if expected_operation_type == "DEVELOPMENT_REWARD_MARK_UNCLAIMED" else amount
        reserve_remaining = int(reserve.get("reserved_q_atoms", 0)) - reserve_paid_before - consumed_amount
        if reserve_remaining < 0:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_RESERVE_EXCEEDED")
        stage_amount_field = {
            "IMMEDIATE": "immediate_amount_q_atoms",
            "MATURITY_STAGE_ONE": "maturity_stage_one_amount_q_atoms",
            "MATURITY_STAGE_TWO": "maturity_stage_two_amount_q_atoms",
        }[payment.payment_stage]
        stage_paid_before = sum(
            int(item.get("amount_q_atoms", 0))
            for item in reserve_records
            if item.get("payment_stage") == payment.payment_stage
        )
        stage_unclaimed_before = sum(
            int(item.get("amount_q_atoms", 0))
            for item in self._development_reward_unclaimed_records.values()
            if item.get("reserve_id") == reserve_id and item.get("payment_stage") == payment.payment_stage
        )
        if stage_paid_before + stage_unclaimed_before + amount > int(reserve.get(stage_amount_field, 0)):
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_STAGE_EXCEEDED")

        allocation_reserves = [
            item
            for item in self._development_reward_reserves.values()
            if item.get("pool_allocation_id") == pool_allocation_id
        ]
        allocated_total = sum(int(item.get("reserved_q_atoms", 0)) for item in allocation_reserves)
        paid_before = sum(
            int(item.get("amount_q_atoms", 0))
            for item in self._development_reward_payment_records.values()
            if item.get("pool_allocation_id") == pool_allocation_id
        )
        paid_after = paid_before + amount
        outstanding_after = allocated_total - paid_after
        allocation_budget = int(allocation.get("allocated_q_atoms", 0))
        if allocated_total > allocation_budget or outstanding_after < 0:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_POOL_EXCEEDED")
        pool_remaining = allocation_budget - allocated_total

        if expected_operation_type == "DEVELOPMENT_REWARD_MARK_UNCLAIMED":
            unclaimed_record = build_development_reward_unclaimed_record(
                reserve_id=reserve_id,
                reserve_operation_id=reserve_operation_id,
                pool_allocation_id=pool_allocation_id,
                pool_allocation_operation_id=pool_allocation_operation_id,
                calculation_operation_id=calculation_operation_id,
                calculation_commitment_id=commitment.commitment_id,
                calculation_root=calculation.calculation_root,
                payment=payment,
                distribution_epoch=calculation.epoch,
                claim_expiration_epoch=calculation.epoch + calculation.policy.claim_window_epochs,
            )
            if unclaimed_record.unclaimed_id != unclaimed_id:
                raise ValueError("DEVELOPMENT_REWARD_UNCLAIMED_ID_INVALID")
            return {
                **validated,
                "payment": payment,
                "unclaimed_record": unclaimed_record,
                "amount_q_atoms": amount,
            }
        payment_record = build_development_reward_payment_record(
            reserve_id=reserve_id,
            reserve_operation_id=reserve_operation_id,
            pool_allocation_id=pool_allocation_id,
            pool_allocation_operation_id=pool_allocation_operation_id,
            calculation_operation_id=calculation_operation_id,
            calculation_commitment_id=commitment.commitment_id,
            calculation_root=calculation.calculation_root,
            payment=payment,
            reserve_remaining_q_atoms=reserve_remaining,
            pool_remaining_q_atoms=pool_remaining,
        )
        if payment_record.payment_id != payment_id:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_ID_INVALID")
        return {
            **validated,
            "payment": payment,
            "payment_record": payment_record,
            "amount_q_atoms": amount,
        }

    def validate_consensus_development_reward_pay_immediate(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Validate one immediate payment against finalized pool evidence."""

        return self._validate_consensus_development_reward_payment(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
            expected_operation_type="DEVELOPMENT_REWARD_PAY_IMMEDIATE",
            expected_payment_stages={"IMMEDIATE"},
            expected_payment_states={"PAYABLE"},
        )

    def validate_consensus_development_reward_pay_maturity(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Validate one maturity payment after its epoch boundary is final."""

        return self._validate_consensus_development_reward_payment(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
            expected_operation_type="DEVELOPMENT_REWARD_PAY_MATURITY",
            expected_payment_stages={"MATURITY_STAGE_ONE", "MATURITY_STAGE_TWO"},
            expected_payment_states={"RESERVED"},
        )

    def validate_consensus_development_reward_mark_unclaimed(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Validate one unclaimed reward stage without changing Q balances."""

        return self._validate_consensus_development_reward_payment(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
            expected_operation_type="DEVELOPMENT_REWARD_MARK_UNCLAIMED",
            expected_payment_stages={"IMMEDIATE", "MATURITY_STAGE_ONE", "MATURITY_STAGE_TWO"},
            expected_payment_states={"UNCLAIMED"},
        )

    def validate_consensus_development_reward_claim(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Validate one Wallet-bound claim against an immutable unclaimed stage."""

        from aidn_hypervisor.reward.development_claim import (
            DevelopmentRewardWalletBindingProof,
            build_development_reward_claim_record,
            development_reward_claim_id,
        )
        from aidn_hypervisor.reward.development_unclaimed import DevelopmentRewardUnclaimedRecord

        validated = self._validate_development_reward_calculation_payload(
            envelope,
            expected_operation_type="DEVELOPMENT_REWARD_CLAIM",
        )
        payload = validated["payload"]
        calculation = validated["calculation"]
        commitment = validated["commitment"]
        required_text = [
            "calculation_operation_id",
            "pool_allocation_id",
            "pool_allocation_operation_id",
            "reserve_id",
            "reserve_operation_id",
            "unclaimed_id",
            "unclaimed_operation_id",
            "reward_id",
            "contributor_id",
            "contribution_id",
            "recipient_wallet",
            "role",
            "payment_hash",
            "source_epoch_transition_operation_id",
        ]
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"DEVELOPMENT_REWARD_CLAIM_FIELD_INVALID:{field_name}")
        amount = payload.get("amount_q_atoms")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_AMOUNT_INVALID")
        claim_epoch = payload.get("claim_epoch")
        if isinstance(claim_epoch, bool) or not isinstance(claim_epoch, int) or claim_epoch < 0:
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_EPOCH_INVALID")

        source_ids = (
            (payload["calculation_operation_id"], "DEVELOPMENT_REWARD_CLAIM_CALCULATION_NOT_FINALIZED"),
            (payload["pool_allocation_operation_id"], "DEVELOPMENT_REWARD_CLAIM_POOL_ALLOCATION_NOT_FINALIZED"),
            (payload["reserve_operation_id"], "DEVELOPMENT_REWARD_CLAIM_RESERVE_NOT_FINALIZED"),
            (payload["unclaimed_operation_id"], "DEVELOPMENT_REWARD_CLAIM_UNCLAIMED_NOT_FINALIZED"),
            (payload["source_epoch_transition_operation_id"], "DEVELOPMENT_REWARD_CLAIM_EPOCH_NOT_FINALIZED"),
        )
        for operation_id, error_code in source_ids:
            if operation_id not in finalized_operation_ids:
                raise ValueError(error_code)

        calculation_operation = self._operation_by_id(payload["calculation_operation_id"])
        if calculation_operation is None or calculation_operation.get("operation_type") != (
            "DEVELOPMENT_REWARD_CALCULATE"
        ):
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_CALCULATION_OPERATION_INVALID")
        calculation_payload = calculation_operation.get("payload") or {}
        if (
            calculation_payload.get("commitment_id") != commitment.commitment_id
            or calculation_payload.get("calculation_root") != calculation.calculation_root
        ):
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_CALCULATION_BINDING_INVALID")

        allocation_operation = self._operation_by_id(payload["pool_allocation_operation_id"])
        if allocation_operation is None or allocation_operation.get("operation_type") != ("DEVELOPMENT_POOL_ALLOCATE"):
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_POOL_ALLOCATION_OPERATION_INVALID")
        allocation_payload = allocation_operation.get("payload") or {}
        nested_allocation = allocation_payload.get("pool_allocation") or {}
        allocation = self._development_pool_allocations.get(payload["pool_allocation_id"])
        if allocation is None or nested_allocation.get("allocation_id") != payload["pool_allocation_id"]:
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_POOL_ALLOCATION_BINDING_INVALID")

        reserve_operation = self._operation_by_id(payload["reserve_operation_id"])
        if reserve_operation is None or reserve_operation.get("operation_type") != ("DEVELOPMENT_REWARD_RESERVE"):
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_RESERVE_OPERATION_INVALID")
        reserve_payload = reserve_operation.get("payload") or {}
        nested_reserve = reserve_payload.get("reward_reserve") or {}
        reserve = self._development_reward_reserves.get(payload["reserve_id"])
        if reserve is None or nested_reserve.get("reserve_id") != payload["reserve_id"]:
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_RESERVE_BINDING_INVALID")
        if (
            reserve.get("pool_allocation_id") != payload["pool_allocation_id"]
            or reserve.get("pool_allocation_operation_id") != payload["pool_allocation_operation_id"]
            or reserve.get("calculation_operation_id") != payload["calculation_operation_id"]
            or reserve.get("calculation_commitment_id") != commitment.commitment_id
            or reserve.get("calculation_root") != calculation.calculation_root
        ):
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_RESERVE_SOURCE_MISMATCH")

        unclaimed = self._development_reward_unclaimed_records.get(payload["unclaimed_id"])
        if unclaimed is None:
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_UNCLAIMED_NOT_FOUND")
        if any(
            item.get("unclaimed_id") == payload["unclaimed_id"]
            for item in self._development_reward_expiry_records.values()
        ):
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_EXPIRED_RETURNED")
        for field_name in (
            "reserve_id",
            "reserve_operation_id",
            "pool_allocation_id",
            "pool_allocation_operation_id",
            "calculation_operation_id",
            "calculation_commitment_id",
            "calculation_root",
            "reward_id",
            "contribution_id",
            "contributor_id",
            "role",
            "payment_hash",
            "payment_stage",
            "amount_q_atoms",
        ):
            if payload.get(field_name) != unclaimed.get(field_name):
                raise ValueError("DEVELOPMENT_REWARD_CLAIM_UNCLAIMED_BINDING_INVALID")
        if unclaimed.get("unclaimed_id") != payload["unclaimed_id"]:
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_UNCLAIMED_ID_INVALID")

        unclaimed_operation = self._operation_by_id(payload["unclaimed_operation_id"])
        if unclaimed_operation is None or unclaimed_operation.get("operation_type") != (
            "DEVELOPMENT_REWARD_MARK_UNCLAIMED"
        ):
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_UNCLAIMED_OPERATION_INVALID")
        unclaimed_payload = unclaimed_operation.get("payload") or {}
        if (
            unclaimed_payload.get("payment_hash") != unclaimed.get("payment_hash")
            or unclaimed_payload.get("payment_stage") != unclaimed.get("payment_stage")
            or unclaimed_payload.get("reward_id") != unclaimed.get("reward_id")
            or unclaimed_payload.get("amount_q_atoms") != unclaimed.get("amount_q_atoms")
            or (unclaimed_payload.get("reward_payment") or {}).get("state") != "UNCLAIMED"
        ):
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_UNCLAIMED_OPERATION_BINDING_INVALID")

        epoch_operation = self._operation_by_id(payload["source_epoch_transition_operation_id"])
        if epoch_operation is None or epoch_operation.get("operation_type") != "EPOCH_TRANSITION":
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_EPOCH_INVALID")
        epoch_payload = epoch_operation.get("payload") or {}
        opening_epoch = epoch_payload.get("opening_epoch")
        if isinstance(opening_epoch, bool) or not isinstance(opening_epoch, int) or opening_epoch != claim_epoch:
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_EPOCH_INVALID")
        if claim_epoch < int(unclaimed["distribution_epoch"]):
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_EPOCH_INVALID")
        if claim_epoch > int(unclaimed["claim_expiration_epoch"]):
            raise ValueError("DEVELOPMENT_CLAIM_WINDOW_EXPIRED")

        try:
            binding = DevelopmentRewardWalletBindingProof.model_validate(payload.get("wallet_binding"))
            binding.verify_signature()
        except ValueError as error:
            error_code = str(error)
            if error_code.startswith("DEVELOPMENT_REWARD_"):
                raise
            raise ValueError("DEVELOPMENT_REWARD_WALLET_BINDING_INVALID") from error
        except Exception as error:
            raise ValueError("DEVELOPMENT_REWARD_WALLET_BINDING_INVALID") from error
        if (
            binding.contributor_id != unclaimed["contributor_id"]
            or binding.wallet_address != payload["recipient_wallet"]
        ):
            raise ValueError("DEVELOPMENT_REWARD_WALLET_BINDING_MISMATCH")

        claim_id = development_reward_claim_id(
            unclaimed_id=payload["unclaimed_id"],
            wallet_binding_id=binding.binding_id,
            claim_epoch=claim_epoch,
        )
        if any(
            item.get("unclaimed_id") == payload["unclaimed_id"]
            for item in self._development_reward_claim_records.values()
        ):
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_DUPLICATE")
        if claim_id in self._development_reward_claim_records:
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_DUPLICATE")

        reserve_records = [
            item
            for item in self._development_reward_payment_records.values()
            if item.get("reserve_id") == payload["reserve_id"]
        ]
        claim_records = [
            item
            for item in self._development_reward_claim_records.values()
            if item.get("reserve_id") == payload["reserve_id"]
        ]
        reserve_remaining = (
            int(reserve.get("reserved_q_atoms", 0))
            - sum(int(item.get("amount_q_atoms", 0)) for item in reserve_records)
            - sum(int(item.get("amount_q_atoms", 0)) for item in claim_records)
            - amount
        )
        if reserve_remaining < 0:
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_RESERVE_EXCEEDED")
        stage_amount_field = {
            "IMMEDIATE": "immediate_amount_q_atoms",
            "MATURITY_STAGE_ONE": "maturity_stage_one_amount_q_atoms",
            "MATURITY_STAGE_TWO": "maturity_stage_two_amount_q_atoms",
        }[payload["payment_stage"]]
        stage_consumed = sum(
            int(item.get("amount_q_atoms", 0))
            for item in reserve_records + claim_records
            if item.get("payment_stage") == payload["payment_stage"]
        )
        if stage_consumed + amount > int(reserve.get(stage_amount_field, 0)):
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_STAGE_EXCEEDED")
        allocation_reserves = [
            item
            for item in self._development_reward_reserves.values()
            if item.get("pool_allocation_id") == payload["pool_allocation_id"]
        ]
        allocated_total = sum(int(item.get("reserved_q_atoms", 0)) for item in allocation_reserves)
        allocation_budget = int(allocation.get("allocated_q_atoms", 0))
        if allocated_total > allocation_budget:
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_POOL_EXCEEDED")
        claim_record = build_development_reward_claim_record(
            unclaimed=DevelopmentRewardUnclaimedRecord.model_validate(unclaimed),
            claim_operation_id=envelope.operation_id,
            unclaimed_operation_id=payload["unclaimed_operation_id"],
            binding=binding,
            claim_epoch=claim_epoch,
            reserve_remaining_q_atoms=reserve_remaining,
            pool_remaining_q_atoms=allocation_budget - allocated_total,
        )
        if claim_record.claim_id != claim_id:
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_ID_INVALID")
        return {
            **validated,
            "unclaimed": unclaimed,
            "binding": binding,
            "claim_record": claim_record,
            "amount_q_atoms": amount,
        }

    def validate_consensus_development_reward_expire_unclaimed(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Validate one expired unclaimed stage returning to carryover."""

        from aidn_hypervisor.reward.development_distribution import DevelopmentRewardPayment, canonical_hash
        from aidn_hypervisor.reward.development_expiry import (
            build_development_reward_expiry_record,
            development_reward_expiry_id,
        )
        from aidn_hypervisor.reward.development_unclaimed import DevelopmentRewardUnclaimedRecord

        validated = self._validate_development_reward_calculation_payload(
            envelope,
            expected_operation_type="DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED",
        )
        payload = validated["payload"]
        calculation = validated["calculation"]
        commitment = validated["commitment"]

        required_text = (
            "calculation_operation_id",
            "pool_allocation_id",
            "pool_allocation_operation_id",
            "reserve_id",
            "reserve_operation_id",
            "unclaimed_id",
            "unclaimed_operation_id",
            "source_epoch_transition_operation_id",
            "reward_id",
            "contribution_id",
            "role",
            "payment_hash",
        )
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"DEVELOPMENT_REWARD_EXPIRY_FIELD_INVALID:{field_name}")
        if payload.get("return_destination") != "CARRYOVER":
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_DESTINATION_INVALID")
        expiry_epoch = payload.get("expiry_epoch")
        if isinstance(expiry_epoch, bool) or not isinstance(expiry_epoch, int) or expiry_epoch < 0:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_EPOCH_INVALID")
        amount = payload.get("amount_q_atoms")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_AMOUNT_INVALID")

        source_ids = (
            (payload["calculation_operation_id"], "DEVELOPMENT_REWARD_EXPIRY_CALCULATION_NOT_FINALIZED"),
            (payload["pool_allocation_operation_id"], "DEVELOPMENT_REWARD_EXPIRY_POOL_ALLOCATION_NOT_FINALIZED"),
            (payload["reserve_operation_id"], "DEVELOPMENT_REWARD_EXPIRY_RESERVE_NOT_FINALIZED"),
            (payload["unclaimed_operation_id"], "DEVELOPMENT_REWARD_EXPIRY_UNCLAIMED_NOT_FINALIZED"),
            (payload["source_epoch_transition_operation_id"], "DEVELOPMENT_REWARD_EXPIRY_EPOCH_NOT_FINALIZED"),
        )
        for operation_id, error_code in source_ids:
            if operation_id not in finalized_operation_ids:
                raise ValueError(error_code)

        calculation_operation = self._operation_by_id(payload["calculation_operation_id"])
        if calculation_operation is None or calculation_operation.get("operation_type") != (
            "DEVELOPMENT_REWARD_CALCULATE"
        ):
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_CALCULATION_OPERATION_INVALID")
        calculation_payload = calculation_operation.get("payload") or {}
        if (
            calculation_payload.get("commitment_id") != commitment.commitment_id
            or calculation_payload.get("calculation_root") != calculation.calculation_root
        ):
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_CALCULATION_BINDING_INVALID")

        allocation_operation = self._operation_by_id(payload["pool_allocation_operation_id"])
        if allocation_operation is None or allocation_operation.get("operation_type") != ("DEVELOPMENT_POOL_ALLOCATE"):
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_POOL_ALLOCATION_OPERATION_INVALID")
        nested_allocation = (allocation_operation.get("payload") or {}).get("pool_allocation") or {}
        if nested_allocation.get("allocation_id") != payload["pool_allocation_id"]:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_POOL_ALLOCATION_BINDING_INVALID")
        allocation = self._development_pool_allocations.get(payload["pool_allocation_id"])
        if allocation is None:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_POOL_ALLOCATION_NOT_FOUND")

        reserve_operation = self._operation_by_id(payload["reserve_operation_id"])
        if reserve_operation is None or reserve_operation.get("operation_type") != ("DEVELOPMENT_REWARD_RESERVE"):
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_RESERVE_OPERATION_INVALID")
        nested_reserve = (reserve_operation.get("payload") or {}).get("reward_reserve") or {}
        if nested_reserve.get("reserve_id") != payload["reserve_id"]:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_RESERVE_BINDING_INVALID")
        reserve = self._development_reward_reserves.get(payload["reserve_id"])
        if reserve is None:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_RESERVE_NOT_FOUND")
        if (
            reserve.get("pool_allocation_id") != payload["pool_allocation_id"]
            or reserve.get("pool_allocation_operation_id") != payload["pool_allocation_operation_id"]
            or reserve.get("calculation_operation_id") != payload["calculation_operation_id"]
            or reserve.get("calculation_commitment_id") != commitment.commitment_id
            or reserve.get("calculation_root") != calculation.calculation_root
            or reserve.get("reward_id") != payload["reward_id"]
        ):
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_RESERVE_SOURCE_MISMATCH")

        unclaimed = self._development_reward_unclaimed_records.get(payload["unclaimed_id"])
        if unclaimed is None:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_UNCLAIMED_NOT_FOUND")
        try:
            unclaimed_record = DevelopmentRewardUnclaimedRecord.model_validate(unclaimed)
        except Exception as error:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_UNCLAIMED_INVALID") from error
        if not unclaimed_record.verify_integrity():
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_UNCLAIMED_INVALID")
        unclaimed_operation = self._operation_by_id(payload["unclaimed_operation_id"])
        if unclaimed_operation is None or unclaimed_operation.get("operation_type") != (
            "DEVELOPMENT_REWARD_MARK_UNCLAIMED"
        ):
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_UNCLAIMED_OPERATION_INVALID")
        unclaimed_payload = unclaimed_operation.get("payload") or {}
        source_payment = unclaimed_payload.get("reward_payment") or {}
        if (
            unclaimed_payload.get("commitment_id") != unclaimed_record.calculation_commitment_id
            or unclaimed_payload.get("reserve_id") != unclaimed_record.reserve_id
            or unclaimed_payload.get("reserve_operation_id") != unclaimed_record.reserve_operation_id
            or unclaimed_payload.get("pool_allocation_id") != unclaimed_record.pool_allocation_id
            or unclaimed_payload.get("pool_allocation_operation_id") != unclaimed_record.pool_allocation_operation_id
            or unclaimed_payload.get("calculation_operation_id") != unclaimed_record.calculation_operation_id
            or unclaimed_payload.get("calculation_root") != unclaimed_record.calculation_root
            or unclaimed_payload.get("reward_id") != unclaimed_record.reward_id
            or unclaimed_payload.get("contributor_id") != unclaimed_record.contributor_id
            or unclaimed_payload.get("role") != unclaimed_record.role
            or unclaimed_payload.get("payment_hash") != unclaimed_record.payment_hash
            or unclaimed_payload.get("payment_stage") != unclaimed_record.payment_stage
            or unclaimed_payload.get("amount_q_atoms") != unclaimed_record.amount_q_atoms
            or source_payment.get("reward_id") != unclaimed_record.reward_id
            or source_payment.get("contribution_id") != unclaimed_record.contribution_id
            or source_payment.get("contributor_id") != unclaimed_record.contributor_id
            or source_payment.get("role") != unclaimed_record.role
            or source_payment.get("payment_stage") != unclaimed_record.payment_stage
            or source_payment.get("amount_q_atoms") != unclaimed_record.amount_q_atoms
            or source_payment.get("state") != "UNCLAIMED"
            or source_payment.get("payment_hash") != unclaimed_record.payment_hash
        ):
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_UNCLAIMED_OPERATION_BINDING_INVALID")

        for field_name in (
            "unclaimed_id",
            "reserve_id",
            "reserve_operation_id",
            "pool_allocation_id",
            "pool_allocation_operation_id",
            "calculation_operation_id",
            "calculation_commitment_id",
            "calculation_root",
            "reward_id",
            "contribution_id",
            "contributor_id",
            "role",
            "payment_hash",
            "payment_stage",
            "amount_q_atoms",
        ):
            if payload.get(field_name) != unclaimed.get(field_name):
                raise ValueError("DEVELOPMENT_REWARD_EXPIRY_UNCLAIMED_BINDING_INVALID")
        if expiry_epoch <= int(unclaimed["claim_expiration_epoch"]):
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_NOT_REACHED")
        if amount != int(unclaimed["amount_q_atoms"]):
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_AMOUNT_MISMATCH")

        epoch_operation = self._operation_by_id(payload["source_epoch_transition_operation_id"])
        if epoch_operation is None or epoch_operation.get("operation_type") != "EPOCH_TRANSITION":
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_EPOCH_INVALID")
        if (epoch_operation.get("payload") or {}).get("opening_epoch") != expiry_epoch:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_EPOCH_INVALID")

        payment = DevelopmentRewardPayment.model_validate(payload.get("reward_payment"))
        if (
            payment.state != "UNCLAIMED"
            or payment.wallet_address is not None
            or payment.payment_hash != canonical_hash(payment.model_dump(mode="json", exclude={"payment_hash"}))
            or payment.payment_hash != payload["payment_hash"]
            or payment.amount_q_atoms != amount
        ):
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_PAYMENT_BINDING_INVALID")

        expiry_id = development_reward_expiry_id(
            unclaimed_id=unclaimed_record.unclaimed_id,
            return_destination="CARRYOVER",
        )
        if expiry_id in self._development_reward_expiry_records or any(
            item.get("unclaimed_id") == unclaimed_record.unclaimed_id
            for item in self._development_reward_expiry_records.values()
        ):
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_DUPLICATE")
        if any(
            item.get("unclaimed_id") == unclaimed_record.unclaimed_id
            for item in self._development_reward_claim_records.values()
        ):
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_ALREADY_CLAIMED")

        reserve_payments = [
            item
            for item in self._development_reward_payment_records.values()
            if item.get("reserve_id") == payload["reserve_id"]
        ]
        reserve_claims = [
            item
            for item in self._development_reward_claim_records.values()
            if item.get("reserve_id") == payload["reserve_id"]
        ]
        reserve_expiries = [
            item
            for item in self._development_reward_expiry_records.values()
            if item.get("reserve_id") == payload["reserve_id"]
        ]
        reserve_remaining = (
            int(reserve.get("reserved_q_atoms", 0))
            - sum(int(item.get("amount_q_atoms", 0)) for item in reserve_payments)
            - sum(int(item.get("amount_q_atoms", 0)) for item in reserve_claims)
            - sum(int(item.get("amount_q_atoms", 0)) for item in reserve_expiries)
            - amount
        )
        if reserve_remaining < 0:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_RESERVE_EXCEEDED")
        stage_amount_field = {
            "IMMEDIATE": "immediate_amount_q_atoms",
            "MATURITY_STAGE_ONE": "maturity_stage_one_amount_q_atoms",
            "MATURITY_STAGE_TWO": "maturity_stage_two_amount_q_atoms",
        }[unclaimed_record.payment_stage]
        stage_consumed = sum(
            int(item.get("amount_q_atoms", 0))
            for item in reserve_payments + reserve_claims + reserve_expiries
            if item.get("payment_stage") == unclaimed_record.payment_stage
        )
        if stage_consumed + amount > int(reserve.get(stage_amount_field, 0)):
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_STAGE_EXCEEDED")

        allocation_reserves = [
            item
            for item in self._development_reward_reserves.values()
            if item.get("pool_allocation_id") == payload["pool_allocation_id"]
        ]
        allocated_total = sum(int(item.get("reserved_q_atoms", 0)) for item in allocation_reserves)
        returned_total = sum(
            int(item.get("amount_q_atoms", 0))
            for item in self._development_reward_expiry_records.values()
            if item.get("pool_allocation_id") == payload["pool_allocation_id"]
        )
        net_reserved_after = allocated_total - returned_total - amount
        allocation_budget = int(allocation.get("allocated_q_atoms", 0))
        if allocated_total > allocation_budget or net_reserved_after < 0 or net_reserved_after > allocation_budget:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_POOL_EXCEEDED")
        expiry_record = build_development_reward_expiry_record(
            unclaimed=unclaimed_record,
            expiry_operation_id=envelope.operation_id,
            unclaimed_operation_id=payload["unclaimed_operation_id"],
            source_epoch_transition_operation_id=payload["source_epoch_transition_operation_id"],
            expiry_epoch=expiry_epoch,
            reserve_remaining_q_atoms=reserve_remaining,
            pool_remaining_q_atoms=allocation_budget - net_reserved_after,
        )
        if expiry_record.expiry_id != expiry_id:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_ID_INVALID")
        return {
            **validated,
            "unclaimed": unclaimed_record,
            "expiry_record": expiry_record,
            "amount_q_atoms": amount,
        }

    def validate_consensus_development_reward_finalize_commitment(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Close an exact, already-finalized ECO-0007 evidence set."""

        from aidn_hypervisor.reward.development_distribution import (
            DevelopmentRewardPayment,
            canonical_hash,
        )
        from aidn_hypervisor.reward.development_finalized_commitments import (
            build_development_reward_finalized_commitment,
        )
        from aidn_hypervisor.reward.development_payment import (
            DevelopmentRewardPaymentRecord,
            development_reward_payment_id,
        )
        from aidn_hypervisor.reward.development_reserve import DevelopmentRewardReserve
        from aidn_hypervisor.reward.development_unclaimed import (
            build_development_reward_unclaimed_record,
        )

        validated = self._validate_development_reward_calculation_payload(
            envelope,
            expected_operation_type="DEVELOPMENT_REWARD_FINALIZE_COMMITMENT",
        )
        payload = validated["payload"]
        calculation = validated["calculation"]
        commitment = validated["commitment"]

        required_text = (
            "calculation_operation_id",
            "pool_allocation_id",
            "pool_allocation_operation_id",
            "source_epoch_transition_operation_id",
            "source_operation_root",
            "reserve_root",
            "payment_root",
            "unclaimed_root",
            "claim_root",
            "expiry_root",
            "calculation_commitment_id",
            "finalized_commitment_id",
        )
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"DEVELOPMENT_REWARD_FINALIZED_FIELD_INVALID:{field_name}")
        if payload["calculation_commitment_id"] != commitment.commitment_id:
            raise ValueError("DEVELOPMENT_REWARD_FINALIZED_COMMITMENT_BINDING_INVALID")
        finalization_epoch = payload.get("finalization_epoch")
        if isinstance(finalization_epoch, bool) or not isinstance(finalization_epoch, int):
            raise ValueError("DEVELOPMENT_REWARD_FINALIZED_EPOCH_INVALID")
        if finalization_epoch < calculation.epoch:
            raise ValueError("DEVELOPMENT_REWARD_FINALIZED_EPOCH_INVALID")

        def operation_ids(field_name: str) -> list[str]:
            values = payload.get(field_name)
            if not isinstance(values, list) or any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"DEVELOPMENT_REWARD_FINALIZED_{field_name.upper()}_INVALID")
            if len(set(values)) != len(values):
                raise ValueError(f"DEVELOPMENT_REWARD_FINALIZED_{field_name.upper()}_DUPLICATE")
            return list(values)

        reserve_operation_ids = operation_ids("reserve_operation_ids")
        payment_operation_ids = operation_ids("payment_operation_ids")
        unclaimed_operation_ids = operation_ids("unclaimed_operation_ids")
        claim_operation_ids = operation_ids("claim_operation_ids")
        expiry_operation_ids = operation_ids("expiry_operation_ids")
        all_source_ids = [
            payload["calculation_operation_id"],
            payload["pool_allocation_operation_id"],
            payload["source_epoch_transition_operation_id"],
            *reserve_operation_ids,
            *payment_operation_ids,
            *unclaimed_operation_ids,
            *claim_operation_ids,
            *expiry_operation_ids,
        ]
        if len(set(all_source_ids)) != len(all_source_ids):
            raise ValueError("DEVELOPMENT_REWARD_FINALIZED_SOURCE_OPERATION_DUPLICATE")
        for operation_id in all_source_ids:
            if operation_id not in finalized_operation_ids:
                raise ValueError("DEVELOPMENT_REWARD_FINALIZED_SOURCE_NOT_FINALIZED")

        def source_operation(operation_id: str, expected_type: str, error_code: str) -> dict:
            operation = self._operation_by_id(operation_id)
            if operation is None or operation.get("operation_type") != expected_type:
                raise ValueError(error_code)
            return operation

        calculation_operation = source_operation(
            payload["calculation_operation_id"],
            "DEVELOPMENT_REWARD_CALCULATE",
            "DEVELOPMENT_REWARD_FINALIZED_CALCULATION_OPERATION_INVALID",
        )
        if (calculation_operation.get("payload") or {}).get("commitment_id") != commitment.commitment_id or (
            calculation_operation.get("payload") or {}
        ).get("calculation_root") != calculation.calculation_root:
            raise ValueError("DEVELOPMENT_REWARD_FINALIZED_CALCULATION_BINDING_INVALID")

        allocation_operation = source_operation(
            payload["pool_allocation_operation_id"],
            "DEVELOPMENT_POOL_ALLOCATE",
            "DEVELOPMENT_REWARD_FINALIZED_POOL_ALLOCATION_OPERATION_INVALID",
        )
        nested_allocation = (allocation_operation.get("payload") or {}).get("pool_allocation") or {}
        if nested_allocation.get("allocation_id") != payload["pool_allocation_id"]:
            raise ValueError("DEVELOPMENT_REWARD_FINALIZED_POOL_ALLOCATION_BINDING_INVALID")
        allocation = self._development_pool_allocations.get(payload["pool_allocation_id"])
        if allocation is None:
            raise ValueError("DEVELOPMENT_REWARD_FINALIZED_POOL_ALLOCATION_NOT_FOUND")

        epoch_operation = source_operation(
            payload["source_epoch_transition_operation_id"],
            "EPOCH_TRANSITION",
            "DEVELOPMENT_REWARD_FINALIZED_EPOCH_OPERATION_INVALID",
        )
        if (epoch_operation.get("payload") or {}).get("opening_epoch") != calculation.epoch + 1:
            raise ValueError("DEVELOPMENT_REWARD_FINALIZED_EPOCH_OPERATION_INVALID")

        reserve_records: list[dict] = []
        reserve_ids: set[str] = set()
        for operation_id in reserve_operation_ids:
            operation = source_operation(
                operation_id,
                "DEVELOPMENT_REWARD_RESERVE",
                "DEVELOPMENT_REWARD_FINALIZED_RESERVE_OPERATION_INVALID",
            )
            nested = (operation.get("payload") or {}).get("reward_reserve") or {}
            reserve_id = nested.get("reserve_id")
            reserve = self._development_reward_reserves.get(reserve_id)
            if reserve is None:
                raise ValueError("DEVELOPMENT_REWARD_FINALIZED_RESERVE_NOT_FOUND")
            try:
                reserve_model = DevelopmentRewardReserve.model_validate(reserve)
            except Exception as error:
                raise ValueError("DEVELOPMENT_REWARD_FINALIZED_RESERVE_INVALID") from error
            if (
                nested.get("reserve_id") != reserve_model.reserve_id
                or reserve_model.pool_allocation_id != payload["pool_allocation_id"]
                or reserve_model.pool_allocation_operation_id != payload["pool_allocation_operation_id"]
                or reserve_model.calculation_operation_id != payload["calculation_operation_id"]
                or reserve_model.calculation_commitment_id != commitment.commitment_id
                or reserve_model.calculation_root != calculation.calculation_root
            ):
                raise ValueError("DEVELOPMENT_REWARD_FINALIZED_RESERVE_BINDING_INVALID")
            if reserve_model.reserve_id in reserve_ids:
                raise ValueError("DEVELOPMENT_REWARD_FINALIZED_RESERVE_DUPLICATE")
            reserve_ids.add(reserve_model.reserve_id)
            reserve_records.append(reserve_model.model_dump(mode="json"))
        expected_reward_ids = {item.reward_id for item in calculation.schedules}
        actual_reward_ids = {item["reward_id"] for item in reserve_records}
        if actual_reward_ids != expected_reward_ids:
            raise ValueError("DEVELOPMENT_REWARD_FINALIZED_RESERVE_SET_INCOMPLETE")

        def record_root(records: list[dict], identity_field: str) -> str:
            return canonical_hash(sorted(records, key=lambda item: str(item[identity_field])))

        payment_records: list[dict] = []
        for operation_id in payment_operation_ids:
            operation = self._operation_by_id(operation_id)
            if operation is None or operation.get("operation_type") not in {
                "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
                "DEVELOPMENT_REWARD_PAY_MATURITY",
            }:
                raise ValueError("DEVELOPMENT_REWARD_FINALIZED_PAYMENT_OPERATION_INVALID")
            operation_payload = operation.get("payload") or {}
            payment_id = development_reward_payment_id(
                reserve_id=operation_payload.get("reserve_id", ""),
                payment_hash=operation_payload.get("payment_hash", ""),
                payment_stage=operation_payload.get("payment_stage", ""),
            )
            payment = self._development_reward_payment_records.get(payment_id)
            if payment is None:
                raise ValueError("DEVELOPMENT_REWARD_FINALIZED_PAYMENT_NOT_FOUND")
            try:
                payment_model = DevelopmentRewardPaymentRecord.model_validate(payment)
            except Exception as error:
                raise ValueError("DEVELOPMENT_REWARD_FINALIZED_PAYMENT_INVALID") from error
            if payment_model.reserve_id not in {item["reserve_id"] for item in reserve_records}:
                raise ValueError("DEVELOPMENT_REWARD_FINALIZED_PAYMENT_RESERVE_INVALID")
            payment_records.append(payment_model.model_dump(mode="json"))

        unclaimed_records: list[dict] = []
        for operation_id in unclaimed_operation_ids:
            operation = source_operation(
                operation_id,
                "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
                "DEVELOPMENT_REWARD_FINALIZED_UNCLAIMED_OPERATION_INVALID",
            )
            operation_payload = operation.get("payload") or {}
            payment_payload = operation_payload.get("reward_payment") or {}
            try:
                payment = DevelopmentRewardPayment.model_validate(payment_payload)
                unclaimed_record = build_development_reward_unclaimed_record(
                    reserve_id=operation_payload.get("reserve_id", ""),
                    reserve_operation_id=operation_payload.get("reserve_operation_id", ""),
                    pool_allocation_id=operation_payload.get("pool_allocation_id", ""),
                    pool_allocation_operation_id=operation_payload.get("pool_allocation_operation_id", ""),
                    calculation_operation_id=operation_payload.get("calculation_operation_id", ""),
                    calculation_commitment_id=operation_payload.get("commitment_id", ""),
                    calculation_root=operation_payload.get("calculation_root", ""),
                    payment=payment,
                    distribution_epoch=calculation.epoch,
                    claim_expiration_epoch=calculation.epoch + calculation.policy.claim_window_epochs,
                )
            except Exception as error:
                raise ValueError("DEVELOPMENT_REWARD_FINALIZED_UNCLAIMED_INVALID") from error
            stored = self._development_reward_unclaimed_records.get(unclaimed_record.unclaimed_id)
            if stored is None or stored != unclaimed_record.model_dump(mode="json"):
                raise ValueError("DEVELOPMENT_REWARD_FINALIZED_UNCLAIMED_BINDING_INVALID")
            if unclaimed_record.reserve_id not in {item["reserve_id"] for item in reserve_records}:
                raise ValueError("DEVELOPMENT_REWARD_FINALIZED_UNCLAIMED_RESERVE_INVALID")
            unclaimed_records.append(unclaimed_record.model_dump(mode="json"))

        claim_records: list[dict] = []
        for operation_id in claim_operation_ids:
            source_operation(
                operation_id,
                "DEVELOPMENT_REWARD_CLAIM",
                "DEVELOPMENT_REWARD_FINALIZED_CLAIM_OPERATION_INVALID",
            )
            claim = next(
                (
                    item
                    for item in self._development_reward_claim_records.values()
                    if item.get("claim_operation_id") == operation_id
                ),
                None,
            )
            if claim is None:
                raise ValueError("DEVELOPMENT_REWARD_FINALIZED_CLAIM_NOT_FOUND")
            claim_records.append(dict(claim))

        expiry_records: list[dict] = []
        for operation_id in expiry_operation_ids:
            source_operation(
                operation_id,
                "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED",
                "DEVELOPMENT_REWARD_FINALIZED_EXPIRY_OPERATION_INVALID",
            )
            expiry = next(
                (
                    item
                    for item in self._development_reward_expiry_records.values()
                    if item.get("expiry_operation_id") == operation_id
                ),
                None,
            )
            if expiry is None:
                raise ValueError("DEVELOPMENT_REWARD_FINALIZED_EXPIRY_NOT_FOUND")
            expiry_records.append(dict(expiry))

        source_operation_root = canonical_hash(sorted(all_source_ids))
        roots = {
            "source_operation_root": source_operation_root,
            "reserve_root": record_root(reserve_records, "reserve_id"),
            "payment_root": record_root(payment_records, "payment_id"),
            "unclaimed_root": record_root(unclaimed_records, "unclaimed_id"),
            "claim_root": record_root(claim_records, "claim_id"),
            "expiry_root": record_root(expiry_records, "expiry_id"),
        }
        for field_name, expected in roots.items():
            if payload[field_name] != expected:
                raise ValueError(f"DEVELOPMENT_REWARD_FINALIZED_{field_name.upper()}_MISMATCH")
        if payload["finalized_commitment_id"] in self._development_reward_finalized_commitments:
            raise ValueError("DEVELOPMENT_REWARD_FINALIZED_COMMITMENT_DUPLICATE")

        finalized_record = build_development_reward_finalized_commitment(
            finalized_operation_id=envelope.operation_id,
            calculation_operation_id=payload["calculation_operation_id"],
            calculation_commitment_id=payload["calculation_commitment_id"],
            calculation_root=calculation.calculation_root,
            pool_allocation_id=payload["pool_allocation_id"],
            pool_allocation_operation_id=payload["pool_allocation_operation_id"],
            source_epoch_transition_operation_id=payload["source_epoch_transition_operation_id"],
            reserve_operation_ids=reserve_operation_ids,
            payment_operation_ids=payment_operation_ids,
            unclaimed_operation_ids=unclaimed_operation_ids,
            claim_operation_ids=claim_operation_ids,
            expiry_operation_ids=expiry_operation_ids,
            **roots,
            finalization_epoch=finalization_epoch,
        )
        if finalized_record.finalized_commitment_id != payload["finalized_commitment_id"]:
            raise ValueError("DEVELOPMENT_REWARD_FINALIZED_COMMITMENT_ID_INVALID")
        return {**validated, "finalized_record": finalized_record}

    def apply_consensus_development_reward_pay_immediate(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Apply one source-bound immediate payment and credit its Wallet."""

        validated = self.validate_consensus_development_reward_pay_immediate(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        payment_record = validated["payment_record"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["DevelopmentRewardPaidImmediate"],
        )
        self._development_reward_payment_records[payment_record.payment_id] = payment_record.model_dump(mode="json")
        self.credit_wallet_q_atoms(
            wallet_id=payment_record.wallet_address,
            amount_q_atoms=payment_record.amount_q_atoms,
        )
        return record

    def apply_consensus_development_reward_pay_maturity(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Apply one epoch-qualified maturity payment and credit its Wallet."""

        validated = self.validate_consensus_development_reward_pay_maturity(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        payment_record = validated["payment_record"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["DevelopmentRewardPaidMaturity"],
        )
        self._development_reward_payment_records[payment_record.payment_id] = payment_record.model_dump(mode="json")
        self.credit_wallet_q_atoms(
            wallet_id=payment_record.wallet_address,
            amount_q_atoms=payment_record.amount_q_atoms,
        )
        return record

    def apply_consensus_development_reward_mark_unclaimed(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Persist one unclaimed stage while leaving its reserve untouched."""

        validated = self.validate_consensus_development_reward_mark_unclaimed(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        unclaimed_record = validated["unclaimed_record"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["DevelopmentRewardMarkedUnclaimed"],
        )
        self._development_reward_unclaimed_records[unclaimed_record.unclaimed_id] = unclaimed_record.model_dump(
            mode="json"
        )
        return record

    def apply_consensus_development_reward_claim(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Consume one unclaimed stage and credit its verified Wallet."""

        validated = self.validate_consensus_development_reward_claim(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        claim_record = validated["claim_record"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["DevelopmentRewardClaimed"],
        )
        self._development_reward_claim_records[claim_record.claim_id] = claim_record.model_dump(mode="json")
        self.credit_wallet_q_atoms(
            wallet_id=claim_record.wallet_address,
            amount_q_atoms=claim_record.amount_q_atoms,
        )
        return record

    def apply_consensus_development_reward_expire_unclaimed(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Record an expired stage returning to carryover without a Wallet effect."""

        validated = self.validate_consensus_development_reward_expire_unclaimed(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        expiry_record = validated["expiry_record"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["DevelopmentRewardExpiredReturned"],
        )
        self._development_reward_expiry_records[expiry_record.expiry_id] = expiry_record.model_dump(mode="json")
        return record

    def apply_consensus_development_reward_finalize_commitment(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Persist a finalized evidence commitment without an economic effect."""

        validated = self.validate_consensus_development_reward_finalize_commitment(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        finalized_record = validated["finalized_record"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["DevelopmentRewardCommitmentFinalized"],
        )
        self._development_reward_finalized_commitments[finalized_record.finalized_commitment_id] = (
            finalized_record.model_dump(mode="json")
        )
        return record

    def commit_reward_mint(
        self,
        *,
        reward_id: str,
        reward_type: str,
        reward_epoch: int,
        recipient_wallet: str,
        amount_q_atoms: int,
        pool_id: str,
        pool_budget_reference: str,
        contribution_evidence_root: str,
        calculation_version: str,
        reward_calculation_root: str,
        calculation_operation_id: str,
        finality_source: "ConsensusFinalitySource",
        created_at: str | None = None,
    ) -> dict:
        """Apply one consensus-authorized ``REWARD_MINT`` exactly once.

        The local Registry or Epoch worker may calculate a reward, but it may
        not mint it.  The authorization operation must be an existing
        ``EPOCH_TRANSITION`` whose committed calculation root and pool budget
        match this request, and its finality must be supplied by a verified
        consensus source.
        """
        required_text = {
            "reward_id": reward_id,
            "reward_type": reward_type,
            "recipient_wallet": recipient_wallet,
            "pool_id": pool_id,
            "pool_budget_reference": pool_budget_reference,
            "contribution_evidence_root": contribution_evidence_root,
            "calculation_version": calculation_version,
            "reward_calculation_root": reward_calculation_root,
            "calculation_operation_id": calculation_operation_id,
        }
        if any(not value.strip() for value in required_text.values()):
            raise ValueError("reward mint identity is required")
        if reward_epoch < 0:
            raise ValueError("reward epoch must be non-negative")
        if amount_q_atoms <= 0:
            raise ValueError("reward mint amount must be positive")

        transition = next(
            (
                operation
                for operation in reversed(self._operations)
                if operation.get("operation_id") == calculation_operation_id
            ),
            None,
        )
        if transition is None or transition.get("operation_type") != "EPOCH_TRANSITION":
            raise ValueError("reward mint calculation operation is not an epoch transition")
        transition_payload = transition.get("payload") or {}
        if transition_payload.get("reward_calculation_root") != reward_calculation_root:
            raise ValueError("reward mint calculation root does not match epoch transition")
        transition_epoch = transition_payload.get(
            "closing_epoch",
            transition_payload.get("reward_epoch"),
        )
        if transition_epoch is not None and int(transition_epoch) != reward_epoch:
            raise ValueError("reward mint epoch does not match epoch transition")
        pool_budgets = transition_payload.get("pool_budgets")
        if not isinstance(pool_budgets, dict) or pool_id not in pool_budgets:
            raise ValueError("reward mint pool budget is not authorized")
        pool_budget = int(pool_budgets[pool_id])
        if pool_budget < 0:
            raise ValueError("reward mint pool budget is invalid")
        pool_references = transition_payload.get("pool_budget_references")
        if isinstance(pool_references, dict) and pool_references.get(pool_id) != pool_budget_reference:
            raise ValueError("reward mint pool budget reference does not match epoch transition")

        try:
            finality = finality_source.finality_evidence(calculation_operation_id)
        except Exception as exc:
            raise ValueError("reward mint consensus finality is unavailable") from exc
        from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence

        if not isinstance(finality, ConsensusFinalityEvidence):
            raise ValueError("reward mint consensus finality is unavailable")
        if finality.operation_id != calculation_operation_id:
            raise ValueError("reward mint consensus finality is mismatched")

        payload = {
            "reward_id": reward_id,
            "reward_type": reward_type,
            "reward_epoch": int(reward_epoch),
            "recipient_wallet": recipient_wallet,
            "amount": int(amount_q_atoms),
            "pool_id": pool_id,
            "pool_budget_reference": pool_budget_reference,
            "contribution_evidence_root": contribution_evidence_root,
            "calculation_version": calculation_version,
            "reward_calculation_root": reward_calculation_root,
            "calculation_operation_id": calculation_operation_id,
        }
        existing = self.reward_mint_commitment(reward_id)
        if existing is not None:
            if existing.get("payload") != payload:
                raise ValueError("conflicting reward mint retry")
            return existing

        already_minted = sum(
            int((operation.get("payload") or {}).get("amount", 0))
            for operation in self._operations
            if operation.get("operation_type") == "REWARD_MINT"
            and (operation.get("payload") or {}).get("pool_id") == pool_id
            and (operation.get("payload") or {}).get("reward_calculation_root") == reward_calculation_root
        )
        if already_minted + amount_q_atoms > pool_budget:
            raise ValueError("reward mint exceeds authorized pool budget")

        finality_reference = _hash_dict(finality.model_dump())
        record = self.record_operation(
            operation_type="REWARD_MINT",
            origin_type="protocol",
            fee_class="protocol_sponsored",
            initiator_id="epoch-engine",
            target_epoch=str(int(reward_epoch)),
            payload=payload,
            evidence_references=sorted(
                {
                    calculation_operation_id,
                    contribution_evidence_root,
                    finality_reference,
                }
            ),
            signatures=[f"consensus:{finality.verifier_id}"],
            created_at=created_at,
            emitted_events=["RewardMinted"],
        )
        self.credit_wallet_q_atoms(
            wallet_id=recipient_wallet,
            amount_q_atoms=amount_q_atoms,
        )
        return record

    def validate_consensus_reward_mint(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Validate an on-chain reward mint against prior ABCI state.

        The ABCI application is itself the consensus execution boundary, so
        it cannot require an external finality source while executing a block.
        Instead, the referenced transition must already be present in the
        pre-block finalized operation set.  This method is validation-only.
        """
        if envelope.operation_type != "REWARD_MINT":
            raise ValueError("consensus reward mint requires REWARD_MINT operation")
        if envelope.origin_type != "protocol" or envelope.sender_wallet is not None:
            raise ValueError("consensus reward mint requires protocol origin")
        payload = dict(envelope.payload)

        required_text = (
            "reward_id",
            "reward_type",
            "recipient_wallet",
            "pool_id",
            "pool_budget_reference",
            "contribution_evidence_root",
            "calculation_version",
            "reward_calculation_root",
            "calculation_operation_id",
        )
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"reward mint field is invalid: {field_name}")

        reward_epoch = payload.get("reward_epoch")
        amount = payload.get("amount")
        if isinstance(reward_epoch, bool) or not isinstance(reward_epoch, int) or reward_epoch < 0:
            raise ValueError("reward mint epoch is invalid")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("reward mint amount is invalid")

        calculation_operation_id = payload["calculation_operation_id"]
        if calculation_operation_id not in finalized_operation_ids:
            raise ValueError("reward mint calculation operation is not finalized")
        transition = next(
            (
                operation
                for operation in reversed(self._operations)
                if operation.get("operation_id") == calculation_operation_id
            ),
            None,
        )
        if transition is None or transition.get("operation_type") != "EPOCH_TRANSITION":
            raise ValueError("reward mint calculation operation is not an epoch transition")
        transition_payload = transition.get("payload") or {}
        if transition_payload.get("reward_calculation_root") != payload["reward_calculation_root"]:
            raise ValueError("reward mint calculation root does not match epoch transition")
        transition_epoch = transition_payload.get(
            "closing_epoch",
            transition_payload.get("reward_epoch"),
        )
        if transition_epoch is not None and int(transition_epoch) != reward_epoch:
            raise ValueError("reward mint epoch does not match epoch transition")

        pool_id = payload["pool_id"]
        pool_budgets = transition_payload.get("pool_budgets")
        if not isinstance(pool_budgets, dict) or pool_id not in pool_budgets:
            raise ValueError("reward mint pool budget is not authorized")
        pool_budget = pool_budgets[pool_id]
        if isinstance(pool_budget, bool) or not isinstance(pool_budget, int) or pool_budget < 0:
            raise ValueError("reward mint pool budget is invalid")
        pool_references = transition_payload.get("pool_budget_references")
        if isinstance(pool_references, dict) and pool_references.get(pool_id) != payload["pool_budget_reference"]:
            raise ValueError("reward mint pool budget reference does not match epoch transition")

        existing = self.reward_mint_commitment(payload["reward_id"])
        if existing is not None:
            raise ValueError("reward mint reward_id is already finalized")

        already_minted = sum(
            int((operation.get("payload") or {}).get("amount", 0))
            for operation in self._operations
            if operation.get("operation_type") == "REWARD_MINT"
            and (operation.get("payload") or {}).get("pool_id") == pool_id
            and (operation.get("payload") or {}).get("reward_calculation_root") == payload["reward_calculation_root"]
        )
        if already_minted + amount > pool_budget:
            raise ValueError("reward mint exceeds authorized pool budget")

        return {
            "payload": payload,
            "amount_q_atoms": amount,
            "recipient_wallet": payload["recipient_wallet"],
        }

    def validate_consensus_epoch_transition(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Validate the canonical payload used to authorize epoch rewards."""
        if envelope.operation_type != "EPOCH_TRANSITION":
            raise ValueError("consensus epoch transition requires EPOCH_TRANSITION")
        if envelope.origin_type != "protocol" or envelope.sender_wallet is not None:
            raise ValueError("consensus epoch transition requires protocol origin")

        payload = dict(envelope.payload)
        required_text = (
            "closing_state_root",
            "epoch_task_result_root",
            "eligibility_snapshot_root",
            "reward_calculation_root",
            "next_protocol_parameters_hash",
        )
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"epoch transition field is invalid: {field_name}")

        closing_epoch = payload.get("closing_epoch")
        opening_epoch = payload.get("opening_epoch")
        if isinstance(closing_epoch, bool) or not isinstance(closing_epoch, int) or closing_epoch < 0:
            raise ValueError("epoch transition closing epoch is invalid")
        if isinstance(opening_epoch, bool) or not isinstance(opening_epoch, int) or opening_epoch < 0:
            raise ValueError("epoch transition opening epoch is invalid")
        if opening_epoch != closing_epoch + 1:
            raise ValueError("opening epoch must immediately follow closing epoch")
        if envelope.target_epoch is not None and envelope.target_epoch != str(closing_epoch):
            raise ValueError("epoch transition target epoch does not match closing epoch")

        pool_budgets = payload.get("pool_budgets")
        if not isinstance(pool_budgets, dict):
            raise ValueError("epoch transition pool budgets are required")
        for pool_id, budget in pool_budgets.items():
            if not isinstance(pool_id, str) or not pool_id.strip():
                raise ValueError("epoch transition pool id is invalid")
            if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
                raise ValueError("epoch transition pool budget is invalid")

        pool_references = payload.get("pool_budget_references")
        if pool_references is not None:
            if not isinstance(pool_references, dict):
                raise ValueError("epoch transition pool budget references are invalid")
            for pool_id in pool_budgets:
                reference = pool_references.get(pool_id)
                if not isinstance(reference, str) or not reference.strip():
                    raise ValueError(f"epoch transition pool budget reference is invalid: {pool_id}")

        if any(
            operation.get("operation_type") == "EPOCH_TRANSITION"
            and (operation.get("payload") or {}).get("closing_epoch") == closing_epoch
            for operation in self._operations
        ):
            raise ValueError("epoch transition for closing epoch is already finalized")

        return {
            "payload": payload,
            "closing_epoch": closing_epoch,
            "opening_epoch": opening_epoch,
            "pool_budgets": pool_budgets,
        }

    def apply_consensus_epoch_transition(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Validate and persist one canonical epoch transition."""
        self.validate_consensus_epoch_transition(envelope)
        return self.record_admitted_envelope(
            envelope,
            emitted_events=["EpochTransition"],
        )

    def apply_consensus_reward_mint(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Validate, persist and apply an ABCI-authorized reward mint."""
        validated = self.validate_consensus_reward_mint(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["RewardMinted"],
        )
        self.credit_wallet_q_atoms(
            wallet_id=str(validated["recipient_wallet"]),
            amount_q_atoms=int(validated["amount_q_atoms"]),
        )
        return record

    def consensus_penalty_commitment(self, penalty_id: str) -> dict | None:
        """Return the canonical record for one applied penalty ID."""
        for operation in reversed(self._operations):
            if operation.get("operation_type") != CONSENSUS_PENALTY_APPLY_OPERATION:
                continue
            if (operation.get("payload") or {}).get("penalty_id") == penalty_id:
                return dict(operation)
        return None

    def validate_consensus_penalty_apply(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Validate an evidence-bound, consensus-authorized penalty.

        Evidence must already be finalized before the block containing this
        operation.  This prevents a proposer from manufacturing evidence and
        spending against it in the same block.
        """
        if envelope.operation_type != CONSENSUS_PENALTY_APPLY_OPERATION:
            raise ValueError("consensus penalty requires PENALTY_APPLY operation")
        if envelope.origin_type != "evidence_triggered" or envelope.sender_wallet is not None:
            raise ValueError("consensus penalty requires evidence-triggered origin")
        if envelope.fee_class != "protocol_sponsored":
            raise ValueError("consensus penalty requires protocol-sponsored fee class")

        payload = dict(envelope.payload)
        required_text = (
            "penalty_id",
            "target_wallet_or_lock",
            "penalty_type",
            "evidence_root",
            "evidence_operation_id",
        )
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"consensus penalty field is invalid: {field_name}")

        penalty_type = payload["penalty_type"]
        if penalty_type not in _CONSENSUS_PENALTY_TYPES:
            raise ValueError("consensus penalty type is not authorized")

        amount = payload.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("consensus penalty amount is invalid")

        recyclable = payload.get("recyclable")
        if not isinstance(recyclable, bool):
            raise ValueError("consensus penalty recyclable flag is invalid")

        target = payload["target_wallet_or_lock"]

        evidence_operation_id = payload["evidence_operation_id"]
        if evidence_operation_id not in finalized_operation_ids:
            raise ValueError("consensus penalty evidence operation is not finalized")
        evidence_operation = next(
            (
                operation
                for operation in reversed(self._operations)
                if operation.get("operation_id") == evidence_operation_id
            ),
            None,
        )
        if evidence_operation is None:
            raise ValueError("consensus penalty evidence operation is unavailable")
        if payload["evidence_root"] not in envelope.evidence_references:
            raise ValueError("consensus penalty evidence root is not referenced")
        if evidence_operation_id not in envelope.evidence_references:
            raise ValueError("consensus penalty evidence operation is not referenced")

        if self.consensus_penalty_commitment(payload["penalty_id"]) is not None:
            raise ValueError("consensus penalty is already finalized")

        if target.startswith("lock:"):
            stake_id = target.removeprefix("lock:")
            if not stake_id.strip():
                raise ValueError("consensus penalty target stake is invalid")
            stake = self._stake_records.get(stake_id)
            if stake is None:
                raise ValueError("consensus penalty target stake does not exist")
            if stake.get("state") not in {"LOCKED", "UNBONDING"}:
                raise ValueError("consensus penalty target stake is not slashable")
            stake_amount = stake.get("amount")
            if isinstance(stake_amount, bool) or not isinstance(stake_amount, int) or stake_amount < amount:
                raise ValueError("consensus penalty exceeds target stake")
            return {
                "payload": payload,
                "target_kind": "stake",
                "target_stake_id": stake_id,
                "amount_q_atoms": amount,
                "recyclable": recyclable,
            }

        if self.wallet_q_atom_balance(target) < amount:
            raise ValueError("consensus penalty exceeds target wallet balance")

        return {
            "payload": payload,
            "target_kind": "wallet",
            "target_wallet": target,
            "amount_q_atoms": amount,
            "recyclable": recyclable,
        }

    def apply_consensus_penalty_apply(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str],
    ) -> dict:
        """Apply one validated penalty and update recyclable/burned totals."""
        validated = self.validate_consensus_penalty_apply(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        target_kind = str(validated["target_kind"])
        emitted_events = ["PenaltyApplied"]
        if target_kind == "stake":
            emitted_events.append("StakeSlashed")
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=emitted_events,
        )
        if target_kind == "stake":
            stake_id = str(validated["target_stake_id"])
            stake = dict(self._stake_records[stake_id])
            slashed_amount = int(validated["amount_q_atoms"])
            remaining_amount = int(stake["amount"]) - slashed_amount
            stake["amount"] = remaining_amount
            stake["slashed_amount"] = int(stake.get("slashed_amount", 0)) + slashed_amount
            if remaining_amount == 0:
                stake["state"] = "SLASHED"
                stake["release_epoch"] = None
            self._stake_records[stake_id] = stake
        else:
            self.debit_wallet_q_atoms(
                wallet_id=str(validated["target_wallet"]),
                amount_q_atoms=int(validated["amount_q_atoms"]),
            )
        if bool(validated["recyclable"]):
            self._recyclable_q_atoms += int(validated["amount_q_atoms"])
        else:
            self._burned_q_atoms += int(validated["amount_q_atoms"])
        return record

    def propose_settlement(
        self,
        evaluation: SettlementEvaluation,
        *,
        created_at: str | None = None,
    ) -> SessionSettlementProposal:
        proposal = evaluation.proposal
        funding = self.get_session_funding_account(proposal.session_id)
        if evaluation.input_set.funding_state_reference != funding.funding_state_hash:
            raise ValueError("Settlement input does not match current funding state")
        existing = self._settlement_proposals.get(proposal.settlement_id)
        if existing is not None:
            if existing.model_dump(mode="json") != proposal.model_dump(mode="json"):
                raise ValueError("conflicting Settlement proposal")
            return existing
        ready_operation = self.commit_settlement_ready(
            evaluation,
            created_at=created_at,
        )
        ready_payload = ready_operation.get("payload")
        if not isinstance(ready_payload, dict):
            raise ValueError("Settlement readiness operation payload is invalid")
        predecessor_operation_id = ready_payload.get("funding_predecessor_operation_id")
        if not isinstance(predecessor_operation_id, str) or not predecessor_operation_id:
            raise ValueError("Settlement readiness predecessor is invalid")
        self.record_operation(
            operation_type="SESSION_SETTLEMENT_PROPOSE",
            origin_type="multi_party",
            fee_class="session",
            initiator_id=proposal.session_id,
            fee_payer=funding.consumer_funding_account,
            payload={
                "settlement_id": proposal.settlement_id,
                "session_id": proposal.session_id,
                "settlement_input_root": proposal.settlement_input_root,
                "endpoint_payment_q_atoms": proposal.final_endpoint_payment_q_atoms,
                "consumer_refund_q_atoms": (
                    proposal.consumer_payment_refund_q_atoms + proposal.consumer_fee_refund_q_atoms
                ),
                "network_fees_q_atoms": proposal.actual_network_fees_q_atoms,
                "dispute_reserve_q_atoms": proposal.dispute_reserve_q_atoms,
                "funding_predecessor_operation_id": predecessor_operation_id,
                "settlement_ready_operation_id": ready_operation["operation_id"],
            },
            created_at=created_at,
            evidence_references=[
                predecessor_operation_id,
                ready_operation["operation_id"],
                proposal.settlement_input_root,
                str(ready_payload["ready"]["commitment_hash"]),
            ],
            emitted_events=["SessionSettlementProposed"],
        )
        self._settlement_proposals[proposal.settlement_id] = proposal
        return proposal

    def commit_settlement_ready(
        self,
        evaluation: SettlementEvaluation,
        *,
        created_at: str | None = None,
    ) -> dict:
        """Commit an immutable local readiness boundary before a proposal.

        The commitment records only Settlement Input Set identity and the
        exact predecessor Funding Account operation. It never releases,
        debits, credits, or otherwise changes economic state.
        """
        proposal = evaluation.proposal
        funding = self.get_session_funding_account(proposal.session_id)
        if funding.funding_state != "LOCKED":
            raise ValueError("Settlement readiness requires locked funding")
        if proposal.settlement_sequence != 1:
            raise ValueError("Settlement readiness only supports sequence one in the MVP profile")
        if evaluation.input_set.funding_state_reference != funding.funding_state_hash:
            raise ValueError("Settlement readiness funding state does not match current funding")
        if (
            funding.session_contract_hash is not None
            and evaluation.input_set.session_contract_hash != funding.session_contract_hash
        ):
            raise ValueError("Settlement readiness Session Contract does not match funding")
        if (
            evaluation.input_set.endpoint_payment_beneficiary != funding.endpoint_payment_beneficiary
            or evaluation.input_set.consumer_refund_beneficiary != funding.consumer_refund_beneficiary
        ):
            raise ValueError("Settlement readiness beneficiaries do not match funding")

        def identity(commitment: SettlementReadyCommitment) -> dict:
            return commitment.model_dump(mode="json", exclude={"ready_at"})

        existing = self._settlement_ready_commits.get(proposal.session_id)
        if existing is not None:
            expected = SettlementReadyCommitment(
                session_id=evaluation.input_set.session_id,
                settlement_sequence=proposal.settlement_sequence,
                session_contract_hash=evaluation.input_set.session_contract_hash,
                effective_terms_hash=evaluation.input_set.effective_terms_hash,
                funding_state_reference=evaluation.input_set.funding_state_reference,
                endpoint_payment_beneficiary=(evaluation.input_set.endpoint_payment_beneficiary),
                consumer_refund_beneficiary=(evaluation.input_set.consumer_refund_beneficiary),
                request_settlement_root=evaluation.input_set.request_settlement_root,
                usage_chain_root=evaluation.input_set.usage_chain_root,
                checkpoint_root=evaluation.input_set.checkpoint_root,
                settlement_input_root=evaluation.input_set.settlement_input_root,
                session_close_reference=evaluation.input_set.session_close_reference,
                ready_at=existing.ready_at,
            )
            if identity(existing) != identity(expected):
                raise ValueError("conflicting Settlement readiness commitment")
            operation = self.get_settlement_ready_operation(proposal.session_id)
            if operation is None:
                raise ValueError("Settlement readiness operation is missing")
            return operation

        predecessor = self._find_funding_predecessor_operation(funding)
        if predecessor is None:
            raise ValueError("Settlement readiness funding predecessor is missing")

        ready = SettlementReadyCommitment(
            session_id=evaluation.input_set.session_id,
            settlement_sequence=proposal.settlement_sequence,
            session_contract_hash=evaluation.input_set.session_contract_hash,
            effective_terms_hash=evaluation.input_set.effective_terms_hash,
            funding_state_reference=evaluation.input_set.funding_state_reference,
            endpoint_payment_beneficiary=evaluation.input_set.endpoint_payment_beneficiary,
            consumer_refund_beneficiary=evaluation.input_set.consumer_refund_beneficiary,
            request_settlement_root=evaluation.input_set.request_settlement_root,
            usage_chain_root=evaluation.input_set.usage_chain_root,
            checkpoint_root=evaluation.input_set.checkpoint_root,
            settlement_input_root=evaluation.input_set.settlement_input_root,
            session_close_reference=evaluation.input_set.session_close_reference,
            ready_at=created_at or datetime.now(UTC).isoformat(),
        )
        operation = self.record_operation(
            operation_type=SESSION_SETTLEMENT_READY_COMMIT_OPERATION,
            origin_type="multi_party",
            fee_class="session",
            initiator_id=ready.session_id,
            fee_payer=funding.consumer_funding_account,
            payload={
                "session_id": ready.session_id,
                "funding_predecessor_operation_id": predecessor["operation_id"],
                "ready": ready.model_dump(mode="json"),
            },
            created_at=ready.ready_at,
            evidence_references=[
                predecessor["operation_id"],
                ready.settlement_input_root,
                ready.commitment_hash,
                ready.session_close_reference,
            ],
            emitted_events=["SessionSettlementReadyCommitted"],
        )
        self._settlement_ready_commits[ready.session_id] = ready
        return operation

    def _find_funding_predecessor_operation(
        self,
        funding: SessionFundingAccount,
    ) -> dict | None:
        """Find the local operation that produced the current Funding hash."""
        funding_operation_types = {
            "SESSION_ESCROW_LOCK",
            SESSION_ESCROW_EXTEND_OPERATION,
            SESSION_ESCROW_RELEASE_OPERATION,
        }
        for operation in reversed(self._operations):
            if operation.get("operation_type") not in funding_operation_types:
                continue
            payload = operation.get("payload")
            if not isinstance(payload, dict):
                continue
            if operation.get("operation_type") == "SESSION_ESCROW_LOCK":
                session_id = payload.get("session_id")
                state_hash = payload.get("funding_state_hash")
            else:
                next_funding = payload.get("funding")
                if not isinstance(next_funding, dict):
                    continue
                session_id = next_funding.get("session_id")
                state_hash = next_funding.get("funding_state_hash")
            if session_id == funding.session_id and state_hash == funding.funding_state_hash:
                return dict(operation)
        return None

    def accept_settlement(
        self,
        acceptance: SessionSettlementAcceptance,
        *,
        created_at: str | None = None,
    ) -> SessionSettlementAcceptance:
        proposal = self.get_settlement_proposal(acceptance.settlement_id)
        if (
            acceptance.session_id != proposal.session_id
            or acceptance.settlement_input_root != proposal.settlement_input_root
            or acceptance.accepted_endpoint_payment_q_atoms != proposal.final_endpoint_payment_q_atoms
            or acceptance.accepted_consumer_refund_q_atoms
            != proposal.consumer_payment_refund_q_atoms + proposal.consumer_fee_refund_q_atoms
            or acceptance.accepted_network_fees_q_atoms != proposal.actual_network_fees_q_atoms
        ):
            raise ValueError("Settlement acceptance does not match proposal")
        existing = self._settlement_acceptances.get(acceptance.settlement_id)
        if existing is not None:
            if existing.acceptance_hash != acceptance.acceptance_hash:
                raise ValueError("conflicting Settlement acceptance")
            return existing
        funding = self.get_session_funding_account(proposal.session_id)
        self.record_operation(
            operation_type="SESSION_SETTLEMENT_ACCEPT",
            origin_type="multi_party",
            fee_class="session",
            initiator_id=proposal.session_id,
            fee_payer=funding.consumer_funding_account,
            payload={
                "settlement_id": proposal.settlement_id,
                "session_id": proposal.session_id,
                "settlement_input_root": proposal.settlement_input_root,
                "acceptance_hash": acceptance.acceptance_hash,
            },
            created_at=created_at,
            emitted_events=["SessionSettlementAccepted"],
        )
        self._settlement_acceptances[acceptance.settlement_id] = acceptance
        return acceptance

    def finalize_accepted_settlement(
        self,
        evaluation: SettlementEvaluation,
        *,
        created_at: str | None = None,
    ) -> SessionFundingAccount:
        proposal = self.get_settlement_proposal(evaluation.proposal.settlement_id)
        if proposal.model_dump(mode="json") != evaluation.proposal.model_dump(mode="json"):
            raise ValueError("Settlement evaluation does not match proposal")
        if proposal.settlement_id not in self._settlement_acceptances:
            raise ValueError("Settlement acceptance is required")
        return self.apply_settlement_evaluation(evaluation, created_at=created_at)

    def commit_session_failure_evidence(
        self,
        *,
        session_id: str,
        failure_class: str,
        failure_evidence_root: str,
        details: str | None = None,
        created_at: str | None = None,
        stage_only: bool = False,
    ) -> dict:
        """Commit the evidence reference consumed by a Forced Settlement.

        The evidence payload is deliberately compact. Full RFC-0060 evidence
        remains in the durable Hypervisor snapshot or restricted evidence
        storage; consensus receives the Session-bound root and classification.
        """
        if not session_id or not failure_class or not failure_evidence_root:
            raise ValueError("Session failure evidence fields are required")
        payload = {
            "session_id": session_id,
            "failure_class": failure_class,
            "failure_evidence_root": failure_evidence_root,
        }
        if details:
            payload["details"] = details
        for operation in reversed(self._operations):
            if operation.get("operation_type") != "SESSION_FAILURE_EVIDENCE":
                continue
            existing_payload = operation.get("payload")
            if not isinstance(existing_payload, dict):
                continue
            if existing_payload.get("session_id") != session_id:
                continue
            if existing_payload.get("failure_evidence_root") != failure_evidence_root:
                continue
            if existing_payload != payload:
                raise ValueError("conflicting Session failure evidence commitment")
            return operation
        record_operation = self.stage_operation if stage_only else self.record_operation
        return record_operation(
            operation_type="SESSION_FAILURE_EVIDENCE",
            origin_type="evidence_triggered",
            fee_class="session",
            initiator_id=session_id,
            payload=payload,
            evidence_references=[failure_evidence_root],
            created_at=created_at,
            emitted_events=["SessionFailureEvidenceCommitted"],
        )

    def force_finalize_fixed_price_settlement(
        self,
        evaluation: SettlementEvaluation,
        *,
        reason: str,
        force_after: str,
        now: str | None = None,
        failure_evidence_root: str | None = None,
        failure_evidence_operation_id: str | None = None,
        last_accepted_checkpoint: str | None = None,
        provider_usage_report_hash: str | None = None,
        consumer_ack_hash: str | None = None,
        attribution_claim: str | None = None,
        initiator_signature: str | None = None,
        created_at: str | None = None,
    ) -> SessionFundingAccount:
        if reason not in {
            "ENDPOINT_UNAVAILABLE",
            "CONSUMER_TIMEOUT_AFTER_COMPLETED_FIXED_PRICE",
        }:
            raise ValueError("unsupported forced Settlement reason")
        return self.force_finalize_settlement(
            evaluation,
            failure_class=reason,
            force_after=force_after,
            now=now,
            failure_evidence_root=failure_evidence_root,
            failure_evidence_operation_id=failure_evidence_operation_id,
            last_accepted_checkpoint=last_accepted_checkpoint,
            provider_usage_report_hash=provider_usage_report_hash,
            consumer_ack_hash=consumer_ack_hash,
            attribution_claim=attribution_claim,
            initiator_signature=initiator_signature,
            created_at=created_at,
            require_completed_fixed_price=(reason == "CONSUMER_TIMEOUT_AFTER_COMPLETED_FIXED_PRICE"),
        )

    def prepare_force_settlement_operation(
        self,
        evaluation: SettlementEvaluation,
        *,
        failure_class: str,
        force_after: str,
        now: str | None = None,
        failure_evidence_root: str | None = None,
        failure_evidence_operation_id: str | None = None,
        last_accepted_checkpoint: str | None = None,
        provider_usage_report_hash: str | None = None,
        consumer_ack_hash: str | None = None,
        attribution_claim: str | None = None,
        initiator_signature: str | None = None,
        created_at: str | None = None,
        require_completed_fixed_price: bool = False,
        failure_evidence_operation: dict | None = None,
        stage_only: bool = False,
    ) -> dict:
        """Prepare a Forced Settlement operation without applying its funds.

        ``SettlementEngine.evaluate_session`` is the single charge calculator.
        This method only verifies timeout/evidence/funding preconditions, records
        the local forced-settlement claim, and returns the exact operation that
        may later be projected to consensus. Each request remains visible in the
        evidence payload so a multi-request Session cannot be reduced to one
        opaque amount.

        The operation is deliberately separate from the economic transition.
        A consensus-enabled caller must not apply the transition until the
        projected canonical operation has verified finality.
        """
        current_time = datetime.fromisoformat(now) if now else datetime.now(UTC)
        deadline = datetime.fromisoformat(force_after)
        if current_time < deadline:
            raise ValueError("forced Settlement timeout has not elapsed")
        proposal = evaluation.proposal
        records = evaluation.input_set.request_settlement_records
        if not failure_class:
            raise ValueError("forced Settlement requires failure_class")
        if failure_class == "ENDPOINT_UNAVAILABLE":
            if proposal.final_endpoint_payment_q_atoms != 0:
                raise ValueError("unavailable Endpoint requires a zero-payment Settlement")
        if require_completed_fixed_price:
            if not records or any(
                record.terminal_state != "COMPLETED"
                or record.dispute_state != "NONE"
                or record.final_usage_report_hash is None
                or any(component.dimension_id is not None for component in record.billable_components)
                for record in records
            ):
                raise ValueError("forced payment requires completed fixed-price evidence")
        if any(not record.request_id for record in records):
            raise ValueError("forced Settlement requires request evidence")
        funding = self.get_session_funding_account(proposal.session_id)
        existing_hash = self._settlement_transition_hashes.get(evaluation.transition.settlement_id)
        if existing_hash is not None:
            if existing_hash != evaluation.transition.transition_hash:
                raise ValueError("conflicting Settlement transition")
            existing_operation = self._find_forced_settlement_operation(
                settlement_id=proposal.settlement_id,
            )
            if existing_operation is None:
                raise ValueError("finalized Forced Settlement operation is missing")
            return {"funding": funding, "operation": existing_operation}
        if funding.funding_state in {"RELEASED", "REFUNDED"}:
            raise ValueError("Session funding account is already finalized")
        if evaluation.input_set.funding_state_reference != funding.funding_state_hash:
            raise ValueError("Settlement input does not match current funding state")

        if proposal.requested_endpoint_payment_q_atoms > funding.endpoint_payment_reserve_q_atoms:
            raise ValueError("forced Settlement payment exceeds Endpoint Payment Reserve")
        if proposal.consumer_payment_refund_q_atoms < 0 or proposal.consumer_fee_refund_q_atoms < 0:
            raise ValueError("forced Settlement refund cannot be negative")

        request_usage_hashes = {
            record.final_usage_report_hash for record in records if record.final_usage_report_hash is not None
        }
        if provider_usage_report_hash is None and len(request_usage_hashes) == 1:
            provider_usage_report_hash = next(iter(request_usage_hashes))
        if last_accepted_checkpoint is None:
            checkpoints = evaluation.input_set.accepted_checkpoint_references
            last_accepted_checkpoint = checkpoints[-1] if checkpoints else None
        failure_evidence_root = failure_evidence_root or evaluation.input_set.settlement_input_root
        if not failure_evidence_root:
            raise ValueError("forced Settlement requires failure evidence")

        forced_payload = {
            "session_id": proposal.session_id,
            "failure_class": failure_class,
            "requested_at": created_at or current_time.isoformat(),
            "last_accepted_checkpoint": last_accepted_checkpoint,
            "provider_usage_report_hash": provider_usage_report_hash,
            "consumer_ack_hash": consumer_ack_hash,
            "failure_evidence_root": failure_evidence_root,
            "requested_payment_q_atoms": proposal.requested_endpoint_payment_q_atoms,
            "requested_refund_q_atoms": (
                proposal.consumer_payment_refund_q_atoms + proposal.consumer_fee_refund_q_atoms
            ),
            "attribution_claim": attribution_claim or failure_class,
            "initiator_signature": initiator_signature,
            "force_after": force_after,
            "settlement_input_root": proposal.settlement_input_root,
            "request_settlement_root": evaluation.input_set.request_settlement_root,
            "usage_chain_root": evaluation.input_set.usage_chain_root,
            "checkpoint_root": evaluation.input_set.checkpoint_root,
            "request_evidence": [
                {
                    "request_id": record.request_id,
                    "terminal_state": record.terminal_state,
                    "record_hash": record.record_hash,
                    "final_usage_report_hash": record.final_usage_report_hash,
                    "capped_request_charge_q_atoms": record.capped_request_charge_q_atoms,
                    "disputed_amount_q_atoms": record.disputed_amount_q_atoms,
                    "dispute_state": record.dispute_state,
                }
                for record in sorted(records, key=lambda item: item.request_id)
            ],
            "provider_usage_report_hashes": sorted(request_usage_hashes),
            "failure_references": list(evaluation.input_set.failure_references),
            "artifact_commitments": list(evaluation.input_set.artifact_commitments),
        }
        if failure_evidence_operation is not None and stage_only:
            evidence_operation = dict(failure_evidence_operation)
            if evidence_operation.get("operation_type") != SESSION_FAILURE_EVIDENCE_OPERATION:
                raise ValueError("Forced Settlement failure evidence operation type is invalid")
            if (
                failure_evidence_operation_id is not None
                and evidence_operation.get("operation_id") != failure_evidence_operation_id
            ):
                raise ValueError("Forced Settlement failure evidence identity is invalid")
        elif failure_evidence_operation_id is not None:
            evidence_operation = self._require_finalized_operation(
                failure_evidence_operation_id,
                finalized_operation_ids=None,
                error_message="Forced Settlement failure evidence is not available",
            )
            if failure_evidence_operation is not None and evidence_operation != failure_evidence_operation:
                raise ValueError("Forced Settlement failure evidence projection conflicts")
            evidence_payload = evidence_operation.get("payload")
            if not isinstance(evidence_payload, dict) or (
                evidence_payload.get("session_id") != proposal.session_id
                or evidence_payload.get("failure_class")
                not in _failure_evidence_classes_for_force_settlement(failure_class)
                or evidence_payload.get("failure_evidence_root") != failure_evidence_root
            ):
                raise ValueError("Forced Settlement failure evidence binding is invalid")
            forced_payload["failure_evidence_operation_id"] = failure_evidence_operation_id
        evidence_references = list(
            dict.fromkeys(
                [
                    failure_evidence_root,
                    *([failure_evidence_operation_id] if failure_evidence_operation_id is not None else []),
                    *(item for item in evaluation.input_set.accepted_checkpoint_references),
                    *sorted(request_usage_hashes),
                ]
            )
        )
        existing_operation = self._find_forced_settlement_operation(
            settlement_id=proposal.settlement_id,
        )
        if existing_operation is not None:
            existing_payload = existing_operation.get("payload")
            if not isinstance(existing_payload, dict) or existing_payload != {
                **forced_payload,
                "settlement_id": proposal.settlement_id,
            }:
                raise ValueError("conflicting prepared Forced Settlement operation")
            return {"funding": funding, "operation": existing_operation}

        record_operation = self.stage_operation if stage_only else self.record_operation
        forced_operation = record_operation(
            operation_type=SESSION_FORCE_SETTLE_OPERATION,
            origin_type="evidence_triggered",
            fee_class="session",
            initiator_id=proposal.session_id,
            fee_payer=funding.consumer_funding_account,
            payload={**forced_payload, "settlement_id": proposal.settlement_id},
            evidence_references=evidence_references,
            signatures=([initiator_signature] if initiator_signature is not None else []),
            created_at=created_at or current_time.isoformat(),
            emitted_events=["SessionForcedSettlementAuthorized"],
        )
        return {"funding": funding, "operation": forced_operation}

    def apply_prepared_force_settlement(
        self,
        evaluation: SettlementEvaluation,
        *,
        force_operation_id: str,
        created_at: str | None = None,
    ) -> SessionFundingAccount:
        """Apply exactly one previously prepared Forced Settlement operation."""
        operation = self._require_finalized_operation(
            force_operation_id,
            finalized_operation_ids=None,
            error_message="prepared Forced Settlement operation is not available",
        )
        if operation.get("operation_type") != SESSION_FORCE_SETTLE_OPERATION:
            raise ValueError("prepared operation is not SESSION_FORCE_SETTLE")
        payload = operation.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("prepared Forced Settlement payload is invalid")
        if (
            payload.get("session_id") != evaluation.proposal.session_id
            or payload.get("settlement_id") != evaluation.proposal.settlement_id
            or payload.get("settlement_input_root") != evaluation.proposal.settlement_input_root
            or payload.get("requested_payment_q_atoms") != evaluation.proposal.requested_endpoint_payment_q_atoms
        ):
            raise ValueError("prepared Forced Settlement does not match evaluation")
        return self.apply_settlement_evaluation(evaluation, created_at=created_at)

    def force_finalize_settlement(
        self,
        evaluation: SettlementEvaluation,
        *,
        failure_class: str,
        force_after: str,
        now: str | None = None,
        failure_evidence_root: str | None = None,
        failure_evidence_operation_id: str | None = None,
        last_accepted_checkpoint: str | None = None,
        provider_usage_report_hash: str | None = None,
        consumer_ack_hash: str | None = None,
        attribution_claim: str | None = None,
        initiator_signature: str | None = None,
        created_at: str | None = None,
        require_completed_fixed_price: bool = False,
    ) -> SessionFundingAccount:
        """Prepare and immediately apply a local Forced Settlement.

        This is the legacy/local convenience path. Consensus-enabled callers
        must call ``prepare_force_settlement_operation`` and apply the returned
        operation only after verified network finality.
        """
        prepared = self.prepare_force_settlement_operation(
            evaluation,
            failure_class=failure_class,
            force_after=force_after,
            now=now,
            failure_evidence_root=failure_evidence_root,
            failure_evidence_operation_id=failure_evidence_operation_id,
            last_accepted_checkpoint=last_accepted_checkpoint,
            provider_usage_report_hash=provider_usage_report_hash,
            consumer_ack_hash=consumer_ack_hash,
            attribution_claim=attribution_claim,
            initiator_signature=initiator_signature,
            created_at=created_at,
            require_completed_fixed_price=require_completed_fixed_price,
        )
        operation = prepared["operation"]
        return self.apply_prepared_force_settlement(
            evaluation,
            force_operation_id=str(operation["operation_id"]),
            created_at=created_at,
        )

    def _find_forced_settlement_operation(
        self,
        *,
        settlement_id: str,
    ) -> dict | None:
        for operation in reversed(self._operations):
            if operation.get("operation_type") != SESSION_FORCE_SETTLE_OPERATION:
                continue
            payload = operation.get("payload")
            if isinstance(payload, dict) and payload.get("settlement_id") == settlement_id:
                return dict(operation)
        return None

    def lock_session_funding(
        self,
        funding: SessionFundingAccount,
        *,
        created_at: str | None = None,
    ) -> SessionFundingAccount:
        existing = self._session_funding_accounts.get(funding.session_id)
        if existing is not None:
            if _funding_lock_identity(existing) != _funding_lock_identity(funding):
                raise ValueError("conflicting Session Funding Account")
            return existing

        if funding.funding_class == "ESCROW_PREPAID":
            balance = self.wallet_q_atom_balance(funding.consumer_funding_account)
            if balance < funding.total_locked_amount_q_atoms:
                raise ValueError("insufficient q_atoms for Session escrow lock")

        locked = _with_funding_updates(funding, {"funding_state": "LOCKED"})
        self.record_operation(
            operation_type="SESSION_ESCROW_LOCK",
            origin_type="wallet",
            fee_class="session",
            initiator_id=funding.session_id,
            sender_wallet=funding.consumer_funding_account,
            fee_payer=funding.consumer_funding_account,
            # Keep the complete locked Funding Account in the local evidence.
            # Consensus projection needs the same conservation fields after a
            # local restart or after the local account has been finalized.
            payload=locked.model_dump(mode="json"),
            created_at=created_at,
            emitted_events=["SessionEscrowLocked"],
        )
        if funding.funding_class == "ESCROW_PREPAID":
            self._wallet_q_atom_balances[funding.consumer_funding_account] = (
                self.wallet_q_atom_balance(funding.consumer_funding_account) - funding.total_locked_amount_q_atoms
            )
        self._session_funding_accounts[funding.session_id] = locked
        return locked

    def validate_consensus_session_escrow_lock(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Validate a canonical, wallet-authorized Session escrow lock.

        The payload carries the complete initial Funding Account so every
        consensus node can reconstruct the same conservation and beneficiary
        bindings before debiting the Consumer wallet.
        """
        if envelope.operation_type != "SESSION_ESCROW_LOCK":
            raise ValueError("consensus escrow lock requires SESSION_ESCROW_LOCK operation")
        if envelope.origin_type != "wallet" or envelope.sender_wallet is None:
            raise ValueError("consensus escrow lock requires wallet origin")
        if envelope.fee_class != "session":
            raise ValueError("consensus escrow lock requires session fee class")

        payload = dict(envelope.payload)
        required_fields = (
            "session_id",
            "session_contract_hash",
            "funding_class",
            "consumer_funding_account",
            "endpoint_payment_beneficiary",
            "consumer_refund_beneficiary",
            "total_locked_amount_q_atoms",
            "endpoint_payment_reserve_q_atoms",
            "network_fee_reserve_q_atoms",
            "unsettled_payment_reserve_q_atoms",
            "unsettled_fee_reserve_q_atoms",
            "funding_state",
            "funding_state_hash",
        )
        missing = [field_name for field_name in required_fields if field_name not in payload]
        if missing:
            raise ValueError("consensus escrow lock payload is missing: " + ", ".join(missing))

        try:
            funding = SessionFundingAccount.model_validate(payload)
        except ValueError as error:
            raise ValueError(f"consensus escrow funding is invalid: {error}") from error

        if funding.funding_state != "LOCKED":
            raise ValueError("consensus escrow funding must be LOCKED")
        if funding.consumer_funding_account != envelope.sender_wallet:
            raise ValueError("consensus escrow sender does not own Funding Account")
        if envelope.fee_payer != envelope.sender_wallet:
            raise ValueError("consensus escrow fee payer must be the Consumer wallet")
        if any(
            value != 0
            for value in (
                funding.released_to_endpoint_q_atoms,
                funding.consumer_payment_refund_q_atoms,
                funding.active_dispute_reserve_q_atoms,
                funding.consumed_network_fees_q_atoms,
                funding.consumer_fee_refund_q_atoms,
            )
        ):
            raise ValueError("consensus escrow lock cannot contain released funds")
        if self._session_funding_accounts.get(funding.session_id) is not None:
            raise ValueError("Session Funding Account is already locked")
        if funding.funding_class == "ESCROW_PREPAID" and (
            self.wallet_q_atom_balance(funding.consumer_funding_account) < funding.total_locked_amount_q_atoms
        ):
            raise ValueError("insufficient q_atoms for consensus Session escrow lock")

        return {"payload": payload, "funding": funding}

    def apply_consensus_session_escrow_lock(
        self,
        envelope: "LedgerOperationEnvelope",
    ) -> dict:
        """Apply one consensus-authorized Session escrow lock atomically."""
        validated = self.validate_consensus_session_escrow_lock(envelope)
        funding = validated["funding"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionEscrowLocked"],
        )
        if funding.funding_class == "ESCROW_PREPAID":
            self._wallet_q_atom_balances[funding.consumer_funding_account] = (
                self.wallet_q_atom_balance(funding.consumer_funding_account) - funding.total_locked_amount_q_atoms
            )
        self._session_funding_accounts[funding.session_id] = funding
        return record

    def validate_consensus_session_open(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate the non-economic Session-open transition.

        The canonical funding debit is owned exclusively by
        ``SESSION_ESCROW_LOCK``. Opening a Session only binds the finalized
        funding record to the accepted Session/Endpoint metadata.
        """
        if envelope.operation_type != SESSION_OPEN_OPERATION:
            raise ValueError("consensus Session open requires SESSION_OPEN operation")
        if envelope.origin_type != "wallet" or envelope.sender_wallet is None:
            raise ValueError("consensus Session open requires wallet origin")
        if envelope.fee_class != "session":
            raise ValueError("consensus Session open requires session fee class")
        if envelope.fee_payer != envelope.sender_wallet:
            raise ValueError("consensus Session open fee payer must be the Consumer wallet")

        payload = dict(envelope.payload)
        required_text = (
            "session_id",
            "consumer_hypervisor_id",
            "provider_hypervisor_id",
            "endpoint_id",
            "endpoint_version",
            "endpoint_configuration_hash",
            "pricing_policy_hash",
            "accounting_contract_hash",
            "session_policy_hash",
            "session_contract_hash",
            "effective_terms_hash",
            "endpoint_payment_beneficiary",
            "consumer_refund_beneficiary",
            "funding_lock_operation_id",
            "funding_state_reference",
            "open_expiration",
        )
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"consensus Session open field is invalid: {field_name}")

        deposit_amount = payload.get("deposit_amount_q_atoms")
        if isinstance(deposit_amount, bool) or not isinstance(deposit_amount, int) or deposit_amount < 0:
            raise ValueError("consensus Session open deposit amount is invalid")

        session_id = str(payload["session_id"])
        if session_id in self._session_open_records:
            raise ValueError("Session is already opened")

        funding = self._session_funding_accounts.get(session_id)
        if funding is None:
            raise ValueError("Session Funding Account is not locked")
        if funding.funding_state != "LOCKED":
            raise ValueError("Session Funding Account is not openable")
        if funding.session_contract_hash != payload["session_contract_hash"]:
            raise ValueError("Session open contract binding is invalid")
        if funding.funding_state_hash != payload["funding_state_reference"]:
            raise ValueError("Session open funding state reference is invalid")
        if funding.consumer_funding_account != envelope.sender_wallet:
            raise ValueError("Session open sender does not own Funding Account")
        if funding.endpoint_payment_beneficiary != payload["endpoint_payment_beneficiary"]:
            raise ValueError("Session open Endpoint beneficiary is invalid")
        if funding.consumer_refund_beneficiary != payload["consumer_refund_beneficiary"]:
            raise ValueError("Session open Consumer refund beneficiary is invalid")
        if deposit_amount != funding.total_locked_amount_q_atoms:
            raise ValueError("Session open deposit does not match Funding Account")

        lock_operation_id = str(payload["funding_lock_operation_id"])
        lock_operation = self._require_finalized_dependency(
            lock_operation_id,
            expected_operation_type="SESSION_ESCROW_LOCK",
            finalized_operation_ids=finalized_operation_ids,
            error_message="Session open escrow lock is not finalized",
        )
        lock_payload = lock_operation.get("payload")
        if (
            not isinstance(lock_payload, dict)
            or lock_operation_id not in envelope.evidence_references
            or lock_payload.get("session_id") != session_id
            or lock_payload.get("session_contract_hash") != payload["session_contract_hash"]
            or lock_payload.get("funding_state_hash") != payload["funding_state_reference"]
            or lock_payload.get("endpoint_payment_beneficiary") != payload["endpoint_payment_beneficiary"]
            or lock_payload.get("consumer_refund_beneficiary") != payload["consumer_refund_beneficiary"]
        ):
            raise ValueError("Session open escrow lock binding is invalid")
        if payload["funding_state_reference"] not in envelope.evidence_references:
            raise ValueError("Session open funding state evidence is missing")

        return {"payload": payload, "funding": funding, "lock_operation": lock_operation}

    def apply_consensus_session_open(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Apply a canonical Session-open projection without moving funds."""
        validated = self.validate_consensus_session_open(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        payload = dict(validated["payload"])
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionOpened"],
        )
        self._session_open_records[str(payload["session_id"])] = payload
        return record

    def session_open_record(self, session_id: str) -> dict | None:
        """Return the canonical non-economic Session-open projection."""
        record = self._session_open_records.get(session_id)
        return dict(record) if record is not None else None

    def validate_consensus_session_accept(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate the endpoint-authenticated Session acceptance projection."""
        if envelope.operation_type != SESSION_ACCEPT_OPERATION:
            raise ValueError("consensus Session acceptance requires SESSION_ACCEPT operation")
        if envelope.origin_type != "wallet" or envelope.sender_wallet is None:
            raise ValueError("consensus Session acceptance requires wallet origin")
        if envelope.fee_class != "session":
            raise ValueError("consensus Session acceptance requires session fee class")
        if envelope.fee_payer != envelope.sender_wallet:
            raise ValueError("consensus Session acceptance fee payer must be the Endpoint wallet")

        payload = dict(envelope.payload)
        required_text = (
            "session_id",
            "session_open_operation_id",
            "session_contract_hash",
            "effective_terms_hash",
            "endpoint_id",
            "endpoint_configuration_hash",
            "provider_hypervisor_id",
            "accepted_by",
            "accepted_at",
        )
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"consensus Session acceptance field is invalid: {field_name}")

        session_id = str(payload["session_id"])
        if session_id in self._session_accept_records:
            raise ValueError("Session is already accepted")
        open_operation_id = str(payload["session_open_operation_id"])
        open_operation = self._require_finalized_dependency(
            open_operation_id,
            expected_operation_type=SESSION_OPEN_OPERATION,
            finalized_operation_ids=finalized_operation_ids,
            error_message="Session acceptance open operation is not finalized",
        )
        if open_operation_id not in envelope.evidence_references:
            raise ValueError("Session acceptance open evidence is missing")
        open_payload = open_operation.get("payload")
        if not isinstance(open_payload, dict):
            raise ValueError("Session acceptance open binding is invalid")
        if self._session_open_records.get(session_id) != open_payload:
            raise ValueError("Session acceptance open projection is unavailable")
        if open_payload.get("session_id") != session_id:
            raise ValueError("Session acceptance Session binding is invalid")
        for field_name in ("funding_lock_operation_id", "funding_state_reference"):
            value = open_payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Session acceptance requires canonical Session open")
        for field_name in (
            "session_contract_hash",
            "effective_terms_hash",
            "endpoint_id",
            "endpoint_configuration_hash",
            "provider_hypervisor_id",
        ):
            if payload[field_name] != open_payload.get(field_name):
                raise ValueError(f"Session acceptance binding is invalid: {field_name}")

        funding = self._session_funding_accounts.get(session_id)
        if funding is None or funding.funding_state != "LOCKED":
            raise ValueError("Session Funding Account is not acceptably locked")
        if funding.endpoint_payment_beneficiary != envelope.sender_wallet:
            raise ValueError("Session acceptance sender is not the Endpoint beneficiary")
        if payload["accepted_by"] != envelope.sender_wallet:
            raise ValueError("Session acceptance actor does not match the Endpoint wallet")
        return {"payload": payload, "open_operation": open_operation, "funding": funding}

    def apply_consensus_session_accept(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Apply a canonical Session acceptance without moving funds."""
        validated = self.validate_consensus_session_accept(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        payload = dict(validated["payload"])
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionAccepted"],
        )
        self._session_accept_records[str(payload["session_id"])] = payload
        return record

    def session_accept_record(self, session_id: str) -> dict | None:
        """Return the canonical non-economic Session-accept projection."""
        record = self._session_accept_records.get(session_id)
        return dict(record) if record is not None else None

    def validate_consensus_session_escrow_extend(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate an atomic prepaid Session escrow extension."""
        if envelope.operation_type != SESSION_ESCROW_EXTEND_OPERATION:
            raise ValueError("consensus escrow extension requires SESSION_ESCROW_EXTEND operation")
        if envelope.origin_type != "wallet" or envelope.sender_wallet is None:
            raise ValueError("consensus escrow extension requires wallet origin")
        if envelope.fee_class != "session":
            raise ValueError("consensus escrow extension requires session fee class")

        payload = dict(envelope.payload)
        for field_name in (
            "session_id",
            "extension_id",
            "funding_state_reference",
            "previous_funding_operation_id",
        ):
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"consensus escrow extension field is invalid: {field_name}")
        added_payment = payload.get("added_endpoint_payment_reserve_q_atoms")
        added_fees = payload.get("added_network_fee_reserve_q_atoms")
        for field_name, value in (
            ("added_endpoint_payment_reserve_q_atoms", added_payment),
            ("added_network_fee_reserve_q_atoms", added_fees),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"consensus escrow extension amount is invalid: {field_name}")
        added_payment = cast(int, added_payment)
        added_fees = cast(int, added_fees)
        if added_payment == 0 and added_fees == 0:
            raise ValueError("consensus escrow extension must add funds")

        funding_payload = payload.get("funding")
        if not isinstance(funding_payload, dict):
            raise ValueError("consensus escrow extension funding is required")
        try:
            next_funding = SessionFundingAccount.model_validate(funding_payload)
        except ValueError as error:
            raise ValueError(f"consensus escrow extension funding is invalid: {error}") from error

        session_id = cast(str, payload["session_id"])
        current = self._session_funding_accounts.get(session_id)
        if current is None:
            raise ValueError("Session Funding Account is not locked")
        if current.funding_class != "ESCROW_PREPAID":
            raise ValueError("consensus escrow extension supports prepaid funding only")
        if current.funding_state != "LOCKED":
            raise ValueError("Session Funding Account is not extendable")
        if envelope.sender_wallet != current.consumer_funding_account:
            raise ValueError("consensus escrow extension sender is not the Consumer")
        if envelope.fee_payer != current.consumer_funding_account:
            raise ValueError("consensus escrow extension fee payer is not the Consumer")
        if payload["funding_state_reference"] != current.funding_state_hash:
            raise ValueError("consensus escrow extension funding state does not match")
        if next_funding.session_id != current.session_id:
            raise ValueError("consensus escrow extension Session binding is invalid")
        if next_funding.funding_state != "LOCKED":
            raise ValueError("consensus escrow extension result must remain LOCKED")

        immutable_fields = (
            "session_contract_hash",
            "funding_class",
            "consumer_funding_account",
            "endpoint_payment_beneficiary",
            "consumer_refund_beneficiary",
            "postpaid_credit_limit_q_atoms",
        )
        for field_name in immutable_fields:
            if getattr(next_funding, field_name) != getattr(current, field_name):
                raise ValueError(f"consensus escrow extension changed {field_name}")
        expected_values = {
            "total_locked_amount_q_atoms": (current.total_locked_amount_q_atoms + added_payment + added_fees),
            "endpoint_payment_reserve_q_atoms": (current.endpoint_payment_reserve_q_atoms + added_payment),
            "network_fee_reserve_q_atoms": (current.network_fee_reserve_q_atoms + added_fees),
            "unsettled_payment_reserve_q_atoms": (current.unsettled_payment_reserve_q_atoms + added_payment),
            "unsettled_fee_reserve_q_atoms": (current.unsettled_fee_reserve_q_atoms + added_fees),
        }
        for field_name, expected in expected_values.items():
            if getattr(next_funding, field_name) != expected:
                raise ValueError(f"consensus escrow extension {field_name} is invalid")
        unchanged_fields = (
            "active_dispute_reserve_q_atoms",
            "released_to_endpoint_q_atoms",
            "consumer_payment_refund_q_atoms",
            "consumed_network_fees_q_atoms",
            "consumer_fee_refund_q_atoms",
        )
        for field_name in unchanged_fields:
            if getattr(next_funding, field_name) != getattr(current, field_name):
                raise ValueError(f"consensus escrow extension changed {field_name}")
        if self.wallet_q_atom_balance(current.consumer_funding_account) < added_payment + added_fees:
            raise ValueError("insufficient q_atoms for consensus escrow extension")

        if any(
            operation.get("operation_type") == SESSION_ESCROW_EXTEND_OPERATION
            and (operation.get("payload") or {}).get("extension_id") == payload["extension_id"]
            for operation in self._operations
        ):
            raise ValueError("consensus escrow extension is already committed")
        self._require_funding_predecessor(
            cast(str, payload["previous_funding_operation_id"]),
            funding=current,
            finalized_operation_ids=finalized_operation_ids,
            evidence_references=envelope.evidence_references,
            error_message="consensus escrow extension predecessor is invalid",
        )
        for reference in (
            cast(str, payload["funding_state_reference"]),
            cast(str, next_funding.funding_state_hash),
        ):
            if reference not in envelope.evidence_references:
                raise ValueError("consensus escrow extension funding evidence is not referenced")
        return {
            "payload": payload,
            "funding": current,
            "next_funding": next_funding,
            "added_q_atoms": added_payment + added_fees,
        }

    def apply_consensus_session_escrow_extend(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Apply one validated prepaid Session escrow extension."""
        validated = self.validate_consensus_session_escrow_extend(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        current = validated["funding"]
        next_funding = validated["next_funding"]
        added_q_atoms = int(validated["added_q_atoms"])
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionEscrowExtended"],
        )
        self._wallet_q_atom_balances[current.consumer_funding_account] = (
            self.wallet_q_atom_balance(current.consumer_funding_account) - added_q_atoms
        )
        self._session_funding_accounts[current.session_id] = next_funding
        return record

    def validate_consensus_session_escrow_release(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate a co-authorized refund of currently unsettled escrow."""
        if envelope.operation_type != SESSION_ESCROW_RELEASE_OPERATION:
            raise ValueError("consensus escrow release requires SESSION_ESCROW_RELEASE operation")
        if envelope.origin_type != "multi_party":
            raise ValueError("consensus escrow release requires multi-party origin")
        if envelope.fee_class != "session" or not envelope.fee_payer:
            raise ValueError("consensus escrow release requires a session fee payer")
        if len(envelope.signatures) < 2:
            raise ValueError("consensus escrow release requires both participant signatures")

        payload = dict(envelope.payload)
        for field_name in (
            "session_id",
            "release_id",
            "funding_state_reference",
            "previous_funding_operation_id",
            "consumer_signature",
            "endpoint_signature",
        ):
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"consensus escrow release field is invalid: {field_name}")
        release_payment = payload.get("release_payment_q_atoms")
        release_fees = payload.get("release_fee_q_atoms")
        for field_name, value in (
            ("release_payment_q_atoms", release_payment),
            ("release_fee_q_atoms", release_fees),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"consensus escrow release amount is invalid: {field_name}")
        release_payment = cast(int, release_payment)
        release_fees = cast(int, release_fees)
        if release_payment == 0 and release_fees == 0:
            raise ValueError("consensus escrow release must release funds")

        funding_payload = payload.get("funding")
        if not isinstance(funding_payload, dict):
            raise ValueError("consensus escrow release funding is required")
        try:
            next_funding = SessionFundingAccount.model_validate(funding_payload)
        except ValueError as error:
            raise ValueError(f"consensus escrow release funding is invalid: {error}") from error

        session_id = cast(str, payload["session_id"])
        current = self._session_funding_accounts.get(session_id)
        if current is None:
            raise ValueError("Session Funding Account is not found")
        if current.funding_state not in {"LOCKED", "PARTIALLY_RELEASED"}:
            raise ValueError("Session Funding Account is not releasable")
        if current.active_dispute_reserve_q_atoms != 0:
            raise ValueError("consensus escrow release cannot consume dispute reserve")
        if envelope.fee_payer != current.consumer_funding_account:
            raise ValueError("consensus escrow release fee payer is not the Consumer")
        if payload["funding_state_reference"] != current.funding_state_hash:
            raise ValueError("consensus escrow release funding state does not match")
        if next_funding.session_id != current.session_id:
            raise ValueError("consensus escrow release Session binding is invalid")
        if next_funding.consumer_refund_beneficiary != current.consumer_refund_beneficiary:
            raise ValueError("consensus escrow release refund beneficiary is invalid")
        immutable_fields = (
            "session_contract_hash",
            "funding_class",
            "consumer_funding_account",
            "endpoint_payment_beneficiary",
            "consumer_refund_beneficiary",
            "total_locked_amount_q_atoms",
            "endpoint_payment_reserve_q_atoms",
            "network_fee_reserve_q_atoms",
            "active_dispute_reserve_q_atoms",
            "released_to_endpoint_q_atoms",
            "consumed_network_fees_q_atoms",
        )
        for field_name in immutable_fields:
            if getattr(next_funding, field_name) != getattr(current, field_name):
                raise ValueError(f"consensus escrow release changed {field_name}")
        if release_payment > current.unsettled_payment_reserve_q_atoms:
            raise ValueError("consensus escrow release exceeds unsettled payment reserve")
        if release_fees > current.unsettled_fee_reserve_q_atoms:
            raise ValueError("consensus escrow release exceeds unsettled fee reserve")
        expected_payment_refund = current.consumer_payment_refund_q_atoms + release_payment
        expected_fee_refund = current.consumer_fee_refund_q_atoms + release_fees
        expected_unsettled_payment = current.unsettled_payment_reserve_q_atoms - release_payment
        expected_unsettled_fees = current.unsettled_fee_reserve_q_atoms - release_fees
        if (
            next_funding.consumer_payment_refund_q_atoms != expected_payment_refund
            or next_funding.consumer_fee_refund_q_atoms != expected_fee_refund
            or next_funding.unsettled_payment_reserve_q_atoms != expected_unsettled_payment
            or next_funding.unsettled_fee_reserve_q_atoms != expected_unsettled_fees
        ):
            raise ValueError("consensus escrow release transition is invalid")
        expected_state = (
            "REFUNDED"
            if expected_unsettled_payment == 0
            and expected_unsettled_fees == 0
            and current.released_to_endpoint_q_atoms == 0
            else (
                "RELEASED" if expected_unsettled_payment == 0 and expected_unsettled_fees == 0 else "PARTIALLY_RELEASED"
            )
        )
        if next_funding.funding_state != expected_state:
            raise ValueError("consensus escrow release funding state is invalid")
        if any(
            operation.get("operation_type") == SESSION_ESCROW_RELEASE_OPERATION
            and (operation.get("payload") or {}).get("release_id") == payload["release_id"]
            for operation in self._operations
        ):
            raise ValueError("consensus escrow release is already committed")
        self._require_funding_predecessor(
            cast(str, payload["previous_funding_operation_id"]),
            funding=current,
            finalized_operation_ids=finalized_operation_ids,
            evidence_references=envelope.evidence_references,
            error_message="consensus escrow release predecessor is invalid",
        )
        for reference in (
            cast(str, payload["funding_state_reference"]),
            cast(str, next_funding.funding_state_hash),
        ):
            if reference not in envelope.evidence_references:
                raise ValueError("consensus escrow release funding evidence is not referenced")
        return {
            "payload": payload,
            "funding": current,
            "next_funding": next_funding,
            "release_q_atoms": release_payment + release_fees,
        }

    def apply_consensus_session_escrow_release(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Apply one co-authorized refund of unsettled Session escrow."""
        validated = self.validate_consensus_session_escrow_release(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        current = validated["funding"]
        next_funding = validated["next_funding"]
        payload = validated["payload"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionEscrowReleased", "SessionRefunded"],
        )
        self.credit_wallet_q_atoms(
            wallet_id=current.consumer_refund_beneficiary,
            amount_q_atoms=int(payload["release_payment_q_atoms"]) + int(payload["release_fee_q_atoms"]),
        )
        self._session_funding_accounts[current.session_id] = next_funding
        return record

    def validate_consensus_session_checkpoint_commit(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate one accepted integer exposure checkpoint."""
        if envelope.operation_type != SESSION_CHECKPOINT_COMMIT_OPERATION:
            raise ValueError("consensus checkpoint requires SESSION_CHECKPOINT_COMMIT operation")
        if envelope.origin_type != "multi_party":
            raise ValueError("consensus checkpoint requires multi-party origin")
        if envelope.fee_class != "session" or not envelope.fee_payer:
            raise ValueError("consensus checkpoint requires a session fee payer")

        payload = dict(envelope.payload)
        for field_name in (
            "session_id",
            "funding_state_reference",
            "previous_funding_operation_id",
            "consumer_wallet",
        ):
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"consensus checkpoint field is invalid: {field_name}")
        checkpoint_payload = payload.get("checkpoint")
        if not isinstance(checkpoint_payload, dict):
            raise ValueError("consensus checkpoint payload is missing checkpoint")
        try:
            checkpoint = SessionUsageCheckpoint.model_validate(checkpoint_payload)
        except ValueError as error:
            raise ValueError(f"consensus checkpoint is invalid: {error}") from error

        session_id = cast(str, payload["session_id"])
        current = self._session_funding_accounts.get(session_id)
        if current is None:
            raise ValueError("Session Funding Account is not found")
        if current.funding_state != "LOCKED":
            raise ValueError("consensus checkpoint requires locked funding")
        if envelope.fee_payer != current.consumer_funding_account:
            raise ValueError("consensus checkpoint fee payer is not the Consumer")
        if payload["consumer_wallet"] != current.consumer_funding_account:
            raise ValueError("consensus checkpoint wallet is not the Consumer")
        if payload["funding_state_reference"] != current.funding_state_hash:
            raise ValueError("consensus checkpoint funding state does not match")
        if checkpoint.session_id != current.session_id:
            raise ValueError("consensus checkpoint Session binding is invalid")
        if checkpoint.current_session_exposure_q_atoms > current.total_locked_amount_q_atoms:
            raise ValueError("consensus checkpoint exposure exceeds locked funding")
        if (
            checkpoint.current_session_exposure_q_atoms + checkpoint.remaining_deposit_q_atoms
            != current.total_locked_amount_q_atoms
        ):
            raise ValueError("consensus checkpoint exposure is not conserved")
        if checkpoint.calculated_charge_q_atoms > checkpoint.current_session_exposure_q_atoms:
            raise ValueError("consensus checkpoint charge exceeds exposure")
        if checkpoint.calculated_charge_q_atoms > current.endpoint_payment_reserve_q_atoms:
            raise ValueError("consensus checkpoint charge exceeds payment reserve")
        existing = [item for item in self._session_checkpoints.values() if item.session_id == current.session_id]
        if any(item.checkpoint_id == checkpoint.checkpoint_id for item in existing):
            raise ValueError("consensus checkpoint is already committed")
        latest_sequence = max((item.checkpoint_sequence for item in existing), default=0)
        if checkpoint.checkpoint_sequence != latest_sequence + 1:
            raise ValueError("consensus checkpoint sequence is invalid")
        if existing:
            latest = max(existing, key=lambda item: item.checkpoint_sequence)
            if (
                checkpoint.current_session_exposure_q_atoms < latest.current_session_exposure_q_atoms
                or checkpoint.calculated_charge_q_atoms < latest.calculated_charge_q_atoms
            ):
                raise ValueError("consensus checkpoint exposure cannot decrease")

        self._require_funding_predecessor(
            cast(str, payload["previous_funding_operation_id"]),
            funding=current,
            finalized_operation_ids=finalized_operation_ids,
            evidence_references=envelope.evidence_references,
            error_message="consensus checkpoint predecessor is invalid",
        )
        for reference in (
            cast(str, payload["funding_state_reference"]),
            checkpoint.checkpoint_id,
            checkpoint.checkpoint_hash,
            checkpoint.usage_report_hash,
        ):
            if reference not in envelope.evidence_references:
                raise ValueError("consensus checkpoint evidence is not referenced")
        return {"payload": payload, "funding": current, "checkpoint": checkpoint}

    def apply_consensus_session_checkpoint_commit(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Persist one accepted checkpoint without moving funds."""
        validated = self.validate_consensus_session_checkpoint_commit(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        checkpoint = validated["checkpoint"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionCheckpointCommitted"],
        )
        self._session_checkpoints[checkpoint.checkpoint_id] = checkpoint
        return record

    def validate_consensus_settlement_ready_commit(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate the immutable Settlement Input commitment boundary."""
        if envelope.operation_type != SESSION_SETTLEMENT_READY_COMMIT_OPERATION:
            raise ValueError("Settlement readiness requires SESSION_SETTLEMENT_READY_COMMIT")
        if envelope.origin_type != "multi_party":
            raise ValueError("Settlement readiness requires multi-party origin")
        if envelope.fee_class != "session" or not envelope.fee_payer:
            raise ValueError("Settlement readiness requires a session fee payer")

        payload = dict(envelope.payload)
        ready_payload = payload.get("ready")
        predecessor_operation_id = payload.get("funding_predecessor_operation_id")
        if not isinstance(ready_payload, dict):
            raise ValueError("Settlement readiness payload is missing ready")
        if not isinstance(predecessor_operation_id, str) or not predecessor_operation_id.strip():
            raise ValueError("Settlement readiness funding predecessor is invalid")
        try:
            ready = SettlementReadyCommitment.model_validate(ready_payload)
        except ValueError as error:
            raise ValueError(f"Settlement readiness is invalid: {error}") from error

        if payload.get("session_id") != ready.session_id:
            raise ValueError("Settlement readiness session binding is invalid")
        if ready.settlement_sequence != 1:
            raise ValueError("Settlement readiness only supports sequence one in the MVP profile")
        funding = self._session_funding_accounts.get(ready.session_id)
        if funding is None:
            raise ValueError("Session Funding Account is not locked")
        if envelope.fee_payer != funding.consumer_funding_account:
            raise ValueError("Settlement readiness fee payer is not the Consumer")
        if ready.funding_state_reference != funding.funding_state_hash:
            raise ValueError("Settlement readiness funding state does not match")
        if ready.session_contract_hash != funding.session_contract_hash:
            raise ValueError("Settlement readiness Session Contract does not match")
        if (
            ready.endpoint_payment_beneficiary != funding.endpoint_payment_beneficiary
            or ready.consumer_refund_beneficiary != funding.consumer_refund_beneficiary
        ):
            raise ValueError("Settlement readiness beneficiaries do not match funding")

        self._require_funding_predecessor(
            predecessor_operation_id,
            funding=funding,
            finalized_operation_ids=finalized_operation_ids,
            evidence_references=envelope.evidence_references,
            error_message="Settlement readiness funding predecessor is not finalized",
        )
        for reference in (
            ready.settlement_input_root,
            ready.commitment_hash,
            ready.session_close_reference,
        ):
            if reference not in envelope.evidence_references:
                raise ValueError("Settlement readiness evidence is not referenced")

        existing = self._settlement_ready_commits.get(ready.session_id)
        if existing is not None:
            if existing != ready:
                raise ValueError("conflicting Settlement readiness commitment")
            raise ValueError("Settlement readiness is already committed")
        return {"payload": payload, "ready": ready, "funding": funding}

    def apply_consensus_settlement_ready_commit(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Persist one immutable Settlement Input commitment without payment."""
        validated = self.validate_consensus_settlement_ready_commit(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        ready = validated["ready"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionSettlementReadyCommitted"],
        )
        self._settlement_ready_commits[ready.session_id] = ready
        return record

    def validate_consensus_settlement_propose(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate a typed Settlement proposal against locked funding."""
        if envelope.operation_type != "SESSION_SETTLEMENT_PROPOSE":
            raise ValueError("consensus Settlement proposal requires SESSION_SETTLEMENT_PROPOSE")
        if envelope.origin_type != "multi_party":
            raise ValueError("Settlement proposal requires multi-party origin")
        if envelope.fee_class != "session" or not envelope.fee_payer:
            raise ValueError("Settlement proposal requires a session fee payer")

        payload = dict(envelope.payload)
        proposal_payload = payload.get("proposal")
        if not isinstance(proposal_payload, dict):
            raise ValueError("Settlement proposal payload is missing proposal")
        required_text = (
            "funding_state_reference",
            "endpoint_payment_beneficiary",
            "consumer_refund_beneficiary",
        )
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Settlement proposal field is invalid: {field_name}")
        predecessor_operation_id = payload.get("funding_predecessor_operation_id")
        legacy_lock_operation_id = payload.get("funding_lock_operation_id")
        if not isinstance(predecessor_operation_id, str) or not predecessor_operation_id.strip():
            predecessor_operation_id = legacy_lock_operation_id
        elif isinstance(legacy_lock_operation_id, str) and legacy_lock_operation_id != predecessor_operation_id:
            raise ValueError("Settlement proposal funding predecessor fields conflict")
        if not isinstance(predecessor_operation_id, str) or not predecessor_operation_id.strip():
            raise ValueError("Settlement proposal field is invalid: funding_predecessor_operation_id")

        try:
            proposal = SessionSettlementProposal.model_validate(proposal_payload)
        except ValueError as error:
            raise ValueError(f"Settlement proposal is invalid: {error}") from error
        for field_name in (
            "settlement_id",
            "session_id",
            "settlement_input_root",
            "request_settlement_root",
            "usage_chain_root",
            "checkpoint_root",
        ):
            value = getattr(proposal, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Settlement proposal field is invalid: {field_name}")
        if payload.get("session_id") != proposal.session_id:
            raise ValueError("Settlement proposal session binding is invalid")

        funding = self._session_funding_accounts.get(proposal.session_id)
        if funding is None:
            raise ValueError("Session Funding Account is not locked")
        if envelope.fee_payer != funding.consumer_funding_account:
            raise ValueError("Settlement proposal fee payer is not the Consumer")
        if payload["funding_state_reference"] != funding.funding_state_hash:
            raise ValueError("Settlement proposal funding state does not match")
        if (
            payload["endpoint_payment_beneficiary"] != funding.endpoint_payment_beneficiary
            or payload["consumer_refund_beneficiary"] != funding.consumer_refund_beneficiary
        ):
            raise ValueError("Settlement proposal beneficiaries do not match funding")

        if proposal.settlement_mode == "PARTIAL_UNDISPUTED":
            if (
                proposal.disputed_amount_q_atoms <= 0
                or proposal.dispute_reserve_q_atoms <= 0
                or proposal.disputed_amount_q_atoms != proposal.dispute_reserve_q_atoms
            ):
                raise ValueError("partial Settlement dispute reserve is invalid")
        elif proposal.disputed_amount_q_atoms != 0 or proposal.dispute_reserve_q_atoms != 0:
            raise ValueError("Settlement dispute amounts require PARTIAL_UNDISPUTED mode")

        self._require_funding_predecessor(
            cast(str, predecessor_operation_id),
            funding=funding,
            finalized_operation_ids=finalized_operation_ids,
            evidence_references=envelope.evidence_references,
            error_message="Settlement proposal funding predecessor is not finalized",
        )
        if proposal.settlement_input_root not in envelope.evidence_references:
            raise ValueError("Settlement proposal input root is not referenced")
        ready_operation_id = payload.get("settlement_ready_operation_id")
        ready_commitment = self._settlement_ready_commits.get(proposal.session_id)
        if ready_commitment is not None:
            if not isinstance(ready_operation_id, str) or not ready_operation_id.strip():
                raise ValueError("Settlement proposal requires finalized readiness commitment")
            ready_operation = self._require_finalized_dependency(
                ready_operation_id,
                expected_operation_type=SESSION_SETTLEMENT_READY_COMMIT_OPERATION,
                finalized_operation_ids=finalized_operation_ids,
                error_message="Settlement readiness commitment is not finalized",
            )
            ready_payload = ready_operation.get("payload")
            if not isinstance(ready_payload, dict):
                raise ValueError("Settlement readiness operation payload is invalid")
            recorded_ready_data = ready_payload.get("ready")
            if not isinstance(recorded_ready_data, dict):
                raise ValueError("Settlement readiness operation payload is incomplete")
            try:
                recorded_ready = SettlementReadyCommitment.model_validate(recorded_ready_data)
            except ValueError as error:
                raise ValueError("Settlement readiness operation payload is invalid") from error
            if recorded_ready != ready_commitment:
                raise ValueError("Settlement readiness commitment binding is invalid")
            if ready_operation_id not in envelope.evidence_references:
                raise ValueError("Settlement readiness commitment is not referenced")
            if (
                ready_commitment.settlement_input_root != proposal.settlement_input_root
                or ready_commitment.request_settlement_root != proposal.request_settlement_root
                or ready_commitment.usage_chain_root != proposal.usage_chain_root
                or ready_commitment.checkpoint_root != proposal.checkpoint_root
                or ready_commitment.funding_state_reference != payload["funding_state_reference"]
            ):
                raise ValueError("Settlement proposal does not match readiness commitment")
        if proposal.settlement_id in self._settlement_proposals:
            raise ValueError("Settlement proposal is already committed")
        if funding.funding_state in {"RELEASED", "REFUNDED"}:
            raise ValueError("Session funding account is already finalized")
        if proposal.capped_session_charge_q_atoms > funding.endpoint_payment_reserve_q_atoms:
            raise ValueError("Settlement charge exceeds Endpoint Payment reserve")
        if proposal.final_endpoint_payment_q_atoms > proposal.capped_session_charge_q_atoms:
            raise ValueError("Settlement Endpoint Payment exceeds capped charge")
        if proposal.final_endpoint_payment_q_atoms < funding.released_to_endpoint_q_atoms:
            raise ValueError("Settlement Endpoint Payment is below prior release")
        prior_consumer_refund = funding.consumer_payment_refund_q_atoms + funding.consumer_fee_refund_q_atoms
        proposed_consumer_refund = proposal.consumer_payment_refund_q_atoms + proposal.consumer_fee_refund_q_atoms
        if proposed_consumer_refund < prior_consumer_refund:
            raise ValueError("Settlement Consumer refund is below prior refund")
        if proposal.actual_network_fees_q_atoms < funding.consumed_network_fees_q_atoms:
            raise ValueError("Settlement Network Fees are below prior consumption")
        if (
            proposal.final_endpoint_payment_q_atoms
            + proposal.consumer_payment_refund_q_atoms
            + proposal.dispute_reserve_q_atoms
            != funding.endpoint_payment_reserve_q_atoms
        ):
            raise ValueError("Settlement Endpoint Payment reserve is not conserved")
        if (
            proposal.actual_network_fees_q_atoms + proposal.consumer_fee_refund_q_atoms
            != funding.network_fee_reserve_q_atoms
        ):
            raise ValueError("Settlement Network Fee reserve is not conserved")
        if proposal.requested_endpoint_payment_q_atoms != (
            proposal.final_endpoint_payment_q_atoms - funding.released_to_endpoint_q_atoms
        ):
            raise ValueError("Settlement requested Endpoint Payment is invalid")

        return {"payload": payload, "proposal": proposal, "funding": funding}

    def apply_consensus_settlement_propose(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Persist one typed Settlement proposal without moving funds."""
        validated = self.validate_consensus_settlement_propose(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        proposal = validated["proposal"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionSettlementProposed"],
        )
        self._settlement_proposals[proposal.settlement_id] = proposal
        return record

    def validate_consensus_settlement_accept(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate a Consumer acceptance of an existing Settlement proposal."""
        if envelope.operation_type != "SESSION_SETTLEMENT_ACCEPT":
            raise ValueError("consensus Settlement acceptance requires SESSION_SETTLEMENT_ACCEPT")
        if envelope.origin_type != "multi_party":
            raise ValueError("Settlement acceptance requires multi-party origin")
        if envelope.fee_class != "session" or not envelope.fee_payer:
            raise ValueError("Settlement acceptance requires a session fee payer")

        payload = dict(envelope.payload)
        acceptance_payload = payload.get("acceptance")
        if not isinstance(acceptance_payload, dict):
            raise ValueError("Settlement acceptance payload is missing acceptance")
        proposal_operation_id = payload.get("proposal_operation_id")
        consumer_wallet = payload.get("consumer_wallet")
        if not isinstance(proposal_operation_id, str) or not proposal_operation_id.strip():
            raise ValueError("Settlement acceptance proposal operation is invalid")
        if not isinstance(consumer_wallet, str) or not consumer_wallet.strip():
            raise ValueError("Settlement acceptance consumer wallet is invalid")
        try:
            acceptance = SessionSettlementAcceptance.model_validate(acceptance_payload)
        except ValueError as error:
            raise ValueError(f"Settlement acceptance is invalid: {error}") from error

        proposal = self._settlement_proposals.get(acceptance.settlement_id)
        if proposal is None:
            raise ValueError("Settlement proposal is not found")
        funding = self._session_funding_accounts.get(proposal.session_id)
        if funding is None:
            raise ValueError("Session Funding Account is not found")
        proposal_operation = self._require_finalized_dependency(
            proposal_operation_id,
            expected_operation_type="SESSION_SETTLEMENT_PROPOSE",
            finalized_operation_ids=finalized_operation_ids,
            error_message="Settlement proposal is not finalized",
        )
        recorded_proposal_payload = proposal_operation.get("payload")
        if not isinstance(recorded_proposal_payload, dict):
            raise ValueError("Settlement proposal operation payload is invalid")
        recorded_proposal_data = recorded_proposal_payload.get("proposal")
        if not isinstance(recorded_proposal_data, dict):
            raise ValueError("Settlement proposal operation payload is missing proposal")
        try:
            recorded_proposal = SessionSettlementProposal.model_validate(recorded_proposal_data)
        except ValueError as error:
            raise ValueError("Settlement proposal operation payload is invalid") from error
        if recorded_proposal != proposal:
            raise ValueError("Settlement acceptance proposal binding is invalid")
        if proposal_operation_id not in envelope.evidence_references:
            raise ValueError("Settlement acceptance proposal is not referenced")
        if envelope.fee_payer != funding.consumer_funding_account:
            raise ValueError("Settlement acceptance fee payer is not the Consumer")
        if consumer_wallet != funding.consumer_funding_account:
            raise ValueError("Settlement acceptance wallet is not the Consumer")
        if (
            acceptance.session_id != proposal.session_id
            or acceptance.settlement_input_root != proposal.settlement_input_root
            or acceptance.accepted_endpoint_payment_q_atoms != proposal.final_endpoint_payment_q_atoms
            or acceptance.accepted_consumer_refund_q_atoms
            != proposal.consumer_payment_refund_q_atoms + proposal.consumer_fee_refund_q_atoms
            or acceptance.accepted_network_fees_q_atoms != proposal.actual_network_fees_q_atoms
        ):
            raise ValueError("Settlement acceptance does not match proposal")
        if acceptance.settlement_input_root not in envelope.evidence_references:
            raise ValueError("Settlement acceptance input root is not referenced")
        if acceptance.settlement_id in self._settlement_acceptances:
            raise ValueError("Settlement acceptance is already committed")
        return {"payload": payload, "acceptance": acceptance, "proposal": proposal}

    def apply_consensus_settlement_accept(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Persist one typed Consumer Settlement acceptance."""
        validated = self.validate_consensus_settlement_accept(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        acceptance = validated["acceptance"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionSettlementAccepted"],
        )
        self._settlement_acceptances[acceptance.settlement_id] = acceptance
        return record

    def validate_consensus_settlement_dispute(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate the single bounded dispute supported by the MVP profile."""
        if envelope.operation_type != SESSION_SETTLEMENT_DISPUTE_OPERATION:
            raise ValueError("Settlement dispute requires SESSION_SETTLEMENT_DISPUTE")
        if envelope.origin_type != "multi_party":
            raise ValueError("Settlement dispute requires multi-party origin")
        if envelope.fee_class != "session" or not envelope.fee_payer:
            raise ValueError("Settlement dispute requires a session fee payer")

        payload = dict(envelope.payload)
        dispute_payload = payload.get("dispute")
        proposal_operation_id = payload.get("proposal_operation_id")
        claimant_wallet = payload.get("claimant_wallet")
        for field_name, value in (
            ("session_id", payload.get("session_id")),
            ("settlement_id", payload.get("settlement_id")),
            ("settlement_input_root", payload.get("settlement_input_root")),
            ("proposal_operation_id", proposal_operation_id),
            ("claimant_wallet", claimant_wallet),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Settlement dispute field is invalid: {field_name}")
        if not isinstance(dispute_payload, dict):
            raise ValueError("Settlement dispute payload is missing dispute")
        try:
            dispute = SettlementDispute.model_validate(dispute_payload)
        except ValueError as error:
            raise ValueError(f"Settlement dispute is invalid: {error}") from error

        proposal = self._settlement_proposals.get(dispute.settlement_id)
        if proposal is None:
            raise ValueError("Settlement proposal is not found")
        funding = self._session_funding_accounts.get(proposal.session_id)
        if funding is None:
            raise ValueError("Session Funding Account is not found")
        if envelope.fee_payer != funding.consumer_funding_account:
            raise ValueError("Settlement dispute fee payer is not the Consumer")
        if claimant_wallet not in {
            funding.consumer_funding_account,
            funding.endpoint_payment_beneficiary,
        }:
            raise ValueError("Settlement dispute claimant is not a Session participant")
        if (
            payload["session_id"] != proposal.session_id
            or payload["settlement_id"] != proposal.settlement_id
            or payload["settlement_input_root"] != proposal.settlement_input_root
            or dispute.session_id != proposal.session_id
            or dispute.settlement_id != proposal.settlement_id
        ):
            raise ValueError("Settlement dispute binding is invalid")
        if proposal.settlement_mode != "PARTIAL_UNDISPUTED":
            raise ValueError("Settlement dispute requires PARTIAL_UNDISPUTED proposal")
        if (
            proposal.disputed_amount_q_atoms <= 0
            or proposal.dispute_reserve_q_atoms <= 0
            or proposal.disputed_amount_q_atoms != proposal.dispute_reserve_q_atoms
            or dispute.disputed_amount_q_atoms != proposal.dispute_reserve_q_atoms
        ):
            raise ValueError("Settlement dispute amount does not match proposal reserve")
        if funding.active_dispute_reserve_q_atoms != 0:
            raise ValueError("Settlement already has an active dispute reserve")
        if funding.funding_state in {"RELEASED", "REFUNDED", "DISPUTE_RESERVED"}:
            raise ValueError("Session funding account is already finalized or disputed")
        if dispute.settlement_id in self._settlement_disputes:
            raise ValueError("Settlement dispute is already committed")
        if any(existing.dispute_id == dispute.dispute_id for existing in self._settlement_disputes.values()):
            raise ValueError("Settlement dispute ID is already committed")

        proposal_operation = self._require_finalized_dependency(
            cast(str, proposal_operation_id),
            expected_operation_type="SESSION_SETTLEMENT_PROPOSE",
            finalized_operation_ids=finalized_operation_ids,
            error_message="Settlement proposal is not finalized",
        )
        recorded_payload = proposal_operation.get("payload")
        recorded_proposal_data = recorded_payload.get("proposal") if isinstance(recorded_payload, dict) else None
        if not isinstance(recorded_proposal_data, dict):
            raise ValueError("Settlement proposal operation payload is invalid")
        try:
            recorded_proposal = SessionSettlementProposal.model_validate(recorded_proposal_data)
        except ValueError as error:
            raise ValueError("Settlement proposal operation payload is invalid") from error
        if recorded_proposal != proposal:
            raise ValueError("Settlement dispute proposal binding is invalid")
        for reference in (
            cast(str, proposal_operation_id),
            proposal.settlement_input_root,
            dispute.dispute_id,
            cast(str, dispute.dispute_hash),
            dispute.evidence_root,
        ):
            if reference not in envelope.evidence_references:
                raise ValueError("Settlement dispute evidence is not referenced")
        return {
            "payload": payload,
            "dispute": dispute,
            "proposal": proposal,
            "funding": funding,
        }

    def apply_consensus_settlement_dispute(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Persist one bounded Settlement dispute without moving funds."""
        validated = self.validate_consensus_settlement_dispute(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        dispute = validated["dispute"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionSettlementDisputed"],
        )
        self._settlement_disputes[dispute.settlement_id] = dispute
        return record

    def validate_consensus_settlement_partial_finalize(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate release of undisputed funds while retaining dispute reserve."""
        if envelope.operation_type != SESSION_SETTLEMENT_PARTIAL_FINALIZE_OPERATION:
            raise ValueError("partial Settlement finalization requires SESSION_SETTLEMENT_PARTIAL_FINALIZE")
        if envelope.origin_type != "multi_party":
            raise ValueError("partial Settlement finalization requires multi-party origin")
        if envelope.fee_class != "session" or not envelope.fee_payer:
            raise ValueError("partial Settlement finalization requires a session fee payer")

        payload = dict(envelope.payload)
        transition_payload = payload.get("transition")
        if not isinstance(transition_payload, dict):
            raise ValueError("partial Settlement finalization transition is required")
        required_text = (
            "session_id",
            "settlement_input_root",
            "proposal_operation_id",
            "acceptance_operation_id",
            "dispute_operation_id",
            "acceptance_hash",
            "dispute_hash",
        )
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"partial Settlement finalization field is invalid: {field_name}")
        try:
            transition = AtomicSettlementTransition.model_validate(transition_payload)
        except ValueError as error:
            raise ValueError(f"partial Settlement transition is invalid: {error}") from error

        proposal = self._settlement_proposals.get(transition.settlement_id)
        acceptance = self._settlement_acceptances.get(transition.settlement_id)
        dispute = self._settlement_disputes.get(transition.settlement_id)
        if proposal is None:
            raise ValueError("Settlement proposal is not found")
        if acceptance is None:
            raise ValueError("Settlement acceptance is required")
        if dispute is None:
            raise ValueError("Settlement dispute is required")
        funding = self._session_funding_accounts.get(transition.session_id)
        if funding is None:
            raise ValueError("Session Funding Account is not found")
        if envelope.fee_payer != funding.consumer_funding_account:
            raise ValueError("partial Settlement finalization fee payer is not the Consumer")
        if proposal.settlement_mode != "PARTIAL_UNDISPUTED":
            raise ValueError("partial Settlement finalization requires disputed proposal")
        if (
            proposal.dispute_reserve_q_atoms <= 0
            or proposal.disputed_amount_q_atoms != proposal.dispute_reserve_q_atoms
            or dispute.disputed_amount_q_atoms != proposal.dispute_reserve_q_atoms
        ):
            raise ValueError("partial Settlement dispute reserve is invalid")
        if funding.funding_state in {"RELEASED", "REFUNDED", "DISPUTE_RESERVED"}:
            raise ValueError("Session funding account is already finalized or disputed")
        if self._settlement_transition_hashes.get(transition.settlement_id) is not None:
            raise ValueError("Settlement transition is already finalized")

        proposal_operation_id = cast(str, payload["proposal_operation_id"])
        acceptance_operation_id = cast(str, payload["acceptance_operation_id"])
        dispute_operation_id = cast(str, payload["dispute_operation_id"])
        proposal_operation = self._require_finalized_dependency(
            proposal_operation_id,
            expected_operation_type="SESSION_SETTLEMENT_PROPOSE",
            finalized_operation_ids=finalized_operation_ids,
            error_message="Settlement proposal is not finalized",
        )
        acceptance_operation = self._require_finalized_dependency(
            acceptance_operation_id,
            expected_operation_type="SESSION_SETTLEMENT_ACCEPT",
            finalized_operation_ids=finalized_operation_ids,
            error_message="Settlement acceptance is not finalized",
        )
        dispute_operation = self._require_finalized_dependency(
            dispute_operation_id,
            expected_operation_type=SESSION_SETTLEMENT_DISPUTE_OPERATION,
            finalized_operation_ids=finalized_operation_ids,
            error_message="Settlement dispute is not finalized",
        )
        proposal_payload = proposal_operation.get("payload")
        acceptance_payload = acceptance_operation.get("payload")
        dispute_payload = dispute_operation.get("payload")
        recorded_proposal_data = proposal_payload.get("proposal") if isinstance(proposal_payload, dict) else None
        recorded_acceptance_data = (
            acceptance_payload.get("acceptance") if isinstance(acceptance_payload, dict) else None
        )
        recorded_dispute_data = dispute_payload.get("dispute") if isinstance(dispute_payload, dict) else None
        if (
            not isinstance(recorded_proposal_data, dict)
            or not isinstance(recorded_acceptance_data, dict)
            or not isinstance(recorded_dispute_data, dict)
        ):
            raise ValueError("Settlement partial-finalize dependency payload is invalid")
        try:
            recorded_proposal = SessionSettlementProposal.model_validate(recorded_proposal_data)
            recorded_acceptance = SessionSettlementAcceptance.model_validate(recorded_acceptance_data)
            recorded_dispute = SettlementDispute.model_validate(recorded_dispute_data)
        except ValueError as error:
            raise ValueError("Settlement partial-finalize dependency payload is invalid") from error
        if recorded_proposal != proposal or recorded_acceptance != acceptance or recorded_dispute != dispute:
            raise ValueError("Settlement partial-finalize dependency binding is invalid")
        if (
            payload["session_id"] != proposal.session_id
            or payload["settlement_input_root"] != proposal.settlement_input_root
            or payload["acceptance_hash"] != acceptance.acceptance_hash
            or payload["dispute_hash"] != dispute.dispute_hash
            or transition.session_id != proposal.session_id
        ):
            raise ValueError("Settlement partial-finalize binding is invalid")
        for reference in (
            proposal_operation_id,
            acceptance_operation_id,
            dispute_operation_id,
            proposal.settlement_input_root,
            transition.settlement_id,
            cast(str, acceptance.acceptance_hash),
            cast(str, dispute.dispute_hash),
            dispute.evidence_root,
        ):
            if reference not in envelope.evidence_references:
                raise ValueError("Settlement partial-finalize evidence is not referenced")
        if (
            transition.endpoint_payment_beneficiary != funding.endpoint_payment_beneficiary
            or transition.consumer_refund_beneficiary != funding.consumer_refund_beneficiary
        ):
            raise ValueError("Settlement partial-finalize beneficiaries do not match funding")
        if transition.total_locked_amount_q_atoms != funding.total_locked_amount_q_atoms:
            raise ValueError("Settlement partial-finalize amount does not match funding")
        if transition.previously_released_to_endpoint_q_atoms != (funding.released_to_endpoint_q_atoms):
            raise ValueError("Settlement partial-finalize prior Endpoint release is invalid")
        if transition.previously_refunded_to_consumer_q_atoms != (
            funding.consumer_payment_refund_q_atoms + funding.consumer_fee_refund_q_atoms
        ):
            raise ValueError("Settlement partial-finalize prior Consumer refund is invalid")
        if transition.previously_consumed_network_fees_q_atoms != (funding.consumed_network_fees_q_atoms):
            raise ValueError("Settlement partial-finalize prior Network Fees are invalid")

        expected_endpoint_credit = proposal.final_endpoint_payment_q_atoms - funding.released_to_endpoint_q_atoms
        expected_consumer_credit = (
            proposal.consumer_payment_refund_q_atoms
            + proposal.consumer_fee_refund_q_atoms
            - funding.consumer_payment_refund_q_atoms
            - funding.consumer_fee_refund_q_atoms
        )
        expected_network_fees = proposal.actual_network_fees_q_atoms - funding.consumed_network_fees_q_atoms
        if transition.credit_endpoint_q_atoms != expected_endpoint_credit:
            raise ValueError("Settlement partial-finalize Endpoint Payment is invalid")
        if transition.credit_consumer_q_atoms != expected_consumer_credit:
            raise ValueError("Settlement partial-finalize Consumer refund is invalid")
        if transition.consume_network_fees_q_atoms != expected_network_fees:
            raise ValueError("Settlement partial-finalize Network Fees are invalid")
        if transition.retain_dispute_reserve_q_atoms != proposal.dispute_reserve_q_atoms:
            raise ValueError("Settlement partial-finalize dispute reserve is invalid")
        return {
            "payload": payload,
            "transition": transition,
            "proposal": proposal,
            "acceptance": acceptance,
            "dispute": dispute,
            "funding": funding,
        }

    def apply_consensus_settlement_partial_finalize(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Release undisputed amounts and retain the active dispute reserve."""
        validated = self.validate_consensus_settlement_partial_finalize(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        transition = validated["transition"]
        proposal = validated["proposal"]
        funding = validated["funding"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionSettlementPartiallyFinalized"],
        )
        self.credit_wallet_q_atoms(
            wallet_id=transition.endpoint_payment_beneficiary,
            amount_q_atoms=transition.credit_endpoint_q_atoms,
        )
        self.credit_wallet_q_atoms(
            wallet_id=transition.consumer_refund_beneficiary,
            amount_q_atoms=transition.credit_consumer_q_atoms,
        )
        next_funding = _with_funding_updates(
            funding,
            {
                "released_to_endpoint_q_atoms": proposal.final_endpoint_payment_q_atoms,
                "consumer_payment_refund_q_atoms": proposal.consumer_payment_refund_q_atoms,
                "consumer_fee_refund_q_atoms": proposal.consumer_fee_refund_q_atoms,
                "consumed_network_fees_q_atoms": proposal.actual_network_fees_q_atoms,
                "active_dispute_reserve_q_atoms": proposal.dispute_reserve_q_atoms,
                "unsettled_payment_reserve_q_atoms": 0,
                "unsettled_fee_reserve_q_atoms": 0,
                "funding_state": "DISPUTE_RESERVED",
            },
        )
        self._session_funding_accounts[transition.session_id] = next_funding
        self._settlement_transition_hashes[transition.settlement_id] = str(transition.transition_hash)
        return record

    def validate_consensus_settlement_correct(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate MVP resolution of the active dispute reserve.

        The first typed correction profile is intentionally narrow: it can only
        consume the reserve created by partial finalization and distribute that
        reserve to the Endpoint or Consumer. It cannot claw back prior credits,
        change Network Fees, or rewrite a finalized usage chain.
        """
        if envelope.operation_type != SESSION_SETTLEMENT_CORRECT_OPERATION:
            raise ValueError("Settlement correction requires SESSION_SETTLEMENT_CORRECT")
        if envelope.origin_type != "multi_party":
            raise ValueError("Settlement correction requires multi-party origin")
        if envelope.fee_class != "session" or not envelope.fee_payer:
            raise ValueError("Settlement correction requires a session fee payer")
        if len(envelope.signatures) < 2:
            raise ValueError("Settlement correction requires both participant signatures")

        payload = dict(envelope.payload)
        correction_payload = payload.get("correction")
        partial_finalize_operation_id = payload.get("partial_finalize_operation_id")
        required_text = (
            "session_id",
            "settlement_id",
            "settlement_input_root",
            "partial_finalize_operation_id",
            "endpoint_payment_beneficiary",
            "consumer_refund_beneficiary",
        )
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Settlement correction field is invalid: {field_name}")
        if not isinstance(correction_payload, dict):
            raise ValueError("Settlement correction payload is missing correction")
        try:
            correction = SettlementCorrection.model_validate(correction_payload)
        except ValueError as error:
            raise ValueError(f"Settlement correction is invalid: {error}") from error

        session_id = cast(str, payload["session_id"])
        settlement_id = cast(str, payload["settlement_id"])
        partial_finalize_operation_id = cast(str, partial_finalize_operation_id)
        proposal = self._settlement_proposals.get(settlement_id)
        dispute = self._settlement_disputes.get(settlement_id)
        funding = self._session_funding_accounts.get(session_id)
        if proposal is None:
            raise ValueError("Settlement proposal is not found")
        if dispute is None:
            raise ValueError("Settlement dispute is not found")
        if funding is None:
            raise ValueError("Session Funding Account is not found")
        if proposal.session_id != session_id or dispute.session_id != session_id:
            raise ValueError("Settlement correction Session binding is invalid")
        if correction.settlement_id != settlement_id:
            raise ValueError("Settlement correction Settlement binding is invalid")
        if payload["settlement_input_root"] != proposal.settlement_input_root:
            raise ValueError("Settlement correction Input Root is invalid")
        if envelope.fee_payer != funding.consumer_funding_account:
            raise ValueError("Settlement correction fee payer is not the Consumer")
        if (
            payload["endpoint_payment_beneficiary"] != funding.endpoint_payment_beneficiary
            or payload["consumer_refund_beneficiary"] != funding.consumer_refund_beneficiary
        ):
            raise ValueError("Settlement correction beneficiaries do not match funding")
        if funding.funding_state != "DISPUTE_RESERVED":
            raise ValueError("Settlement correction requires DISPUTE_RESERVED funding")
        if funding.active_dispute_reserve_q_atoms <= 0:
            raise ValueError("Settlement correction requires an active dispute reserve")
        if (
            proposal.dispute_reserve_q_atoms != funding.active_dispute_reserve_q_atoms
            or dispute.disputed_amount_q_atoms != funding.active_dispute_reserve_q_atoms
        ):
            raise ValueError("Settlement correction dispute reserve does not match funding")
        if correction.correction_id in self._settlement_corrections:
            raise ValueError("Settlement correction is already committed")
        if any(item.settlement_id == settlement_id for item in self._settlement_corrections.values()):
            raise ValueError("Settlement already has a correction")
        if correction.prior_result_hash != self._settlement_transition_hashes.get(settlement_id):
            raise ValueError("Settlement correction prior result does not match partial finalization")
        if correction.network_fee_delta_q_atoms != 0:
            raise ValueError("MVP Settlement correction cannot change Network Fees")
        if correction.dispute_reserve_delta_q_atoms != (-funding.active_dispute_reserve_q_atoms):
            raise ValueError("Settlement correction must consume the active dispute reserve")
        if (
            correction.endpoint_payment_delta_q_atoms < 0
            or correction.consumer_refund_delta_q_atoms < 0
            or correction.endpoint_payment_delta_q_atoms + correction.consumer_refund_delta_q_atoms
            != funding.active_dispute_reserve_q_atoms
        ):
            raise ValueError("Settlement correction reserve allocation is invalid")

        partial_operation = self._require_finalized_dependency(
            partial_finalize_operation_id,
            expected_operation_type=SESSION_SETTLEMENT_PARTIAL_FINALIZE_OPERATION,
            finalized_operation_ids=finalized_operation_ids,
            error_message="Settlement partial finalization is not finalized",
        )
        partial_payload = partial_operation.get("payload")
        if not isinstance(partial_payload, dict):
            raise ValueError("Settlement partial finalization payload is invalid")
        partial_transition_payload = partial_payload.get("transition")
        if not isinstance(partial_transition_payload, dict):
            raise ValueError("Settlement partial finalization transition is invalid")
        try:
            partial_transition = AtomicSettlementTransition.model_validate(partial_transition_payload)
        except ValueError as error:
            raise ValueError("Settlement partial finalization transition is invalid") from error
        if (
            partial_transition.session_id != session_id
            or partial_transition.settlement_id != settlement_id
            or partial_transition.transition_hash != correction.prior_result_hash
            or partial_payload.get("settlement_input_root") != proposal.settlement_input_root
        ):
            raise ValueError("Settlement correction partial-finalization binding is invalid")
        if partial_transition.retain_dispute_reserve_q_atoms != funding.active_dispute_reserve_q_atoms:
            raise ValueError("Settlement correction partial-finalization reserve is invalid")
        for reference in (
            partial_finalize_operation_id,
            proposal.settlement_input_root,
            correction.correction_id,
            cast(str, correction.correction_hash),
            correction.prior_result_hash,
            correction.authorization_reference,
            correction.evidence_root,
        ):
            if reference not in envelope.evidence_references:
                raise ValueError("Settlement correction evidence is not referenced")
        return {
            "payload": payload,
            "correction": correction,
            "proposal": proposal,
            "dispute": dispute,
            "funding": funding,
            "partial_transition": partial_transition,
        }

    def apply_consensus_settlement_correct(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Resolve the active dispute reserve without rewriting prior records."""
        validated = self.validate_consensus_settlement_correct(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        correction = validated["correction"]
        funding = validated["funding"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionSettlementCorrected", "SessionSettlementDisputeResolved"],
        )
        self.credit_wallet_q_atoms(
            wallet_id=funding.endpoint_payment_beneficiary,
            amount_q_atoms=correction.endpoint_payment_delta_q_atoms,
        )
        self.credit_wallet_q_atoms(
            wallet_id=funding.consumer_refund_beneficiary,
            amount_q_atoms=correction.consumer_refund_delta_q_atoms,
        )
        next_released = funding.released_to_endpoint_q_atoms + correction.endpoint_payment_delta_q_atoms
        next_payment_refund = funding.consumer_payment_refund_q_atoms + correction.consumer_refund_delta_q_atoms
        next_state = (
            "RELEASED"
            if funding.unsettled_payment_reserve_q_atoms == 0
            and funding.unsettled_fee_reserve_q_atoms == 0
            and next_released > 0
            else (
                "REFUNDED"
                if funding.unsettled_payment_reserve_q_atoms == 0 and funding.unsettled_fee_reserve_q_atoms == 0
                else "PARTIALLY_RELEASED"
            )
        )
        next_funding = _with_funding_updates(
            funding,
            {
                "released_to_endpoint_q_atoms": next_released,
                "consumer_payment_refund_q_atoms": next_payment_refund,
                "active_dispute_reserve_q_atoms": 0,
                "funding_state": next_state,
            },
        )
        self._session_funding_accounts[funding.session_id] = next_funding
        self._settlement_corrections[correction.correction_id] = correction
        return record

    def validate_consensus_settlement_finalize(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate an accepted Settlement's atomic funding transition."""
        if envelope.operation_type != "SESSION_SETTLEMENT_FINALIZE":
            raise ValueError("consensus Settlement finalization requires SESSION_SETTLEMENT_FINALIZE")
        if envelope.origin_type != "multi_party":
            raise ValueError("Settlement finalization requires multi-party origin")
        if envelope.fee_class != "session" or not envelope.fee_payer:
            raise ValueError("Settlement finalization requires a session fee payer")

        payload = dict(envelope.payload)
        transition_payload = payload.get("transition")
        if not isinstance(transition_payload, dict):
            raise ValueError("Settlement finalization payload is missing transition")
        proposal_operation_id = payload.get("proposal_operation_id")
        acceptance_operation_id = payload.get("acceptance_operation_id")
        acceptance_hash = payload.get("acceptance_hash")
        for field_name, value in (
            ("proposal_operation_id", proposal_operation_id),
            ("acceptance_operation_id", acceptance_operation_id),
            ("acceptance_hash", acceptance_hash),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Settlement finalization field is invalid: {field_name}")
        proposal_operation_id = cast(str, proposal_operation_id)
        acceptance_operation_id = cast(str, acceptance_operation_id)
        acceptance_hash = cast(str, acceptance_hash)
        try:
            transition = AtomicSettlementTransition.model_validate(transition_payload)
        except ValueError as error:
            raise ValueError(f"Settlement transition is invalid: {error}") from error

        proposal = self._settlement_proposals.get(transition.settlement_id)
        acceptance = self._settlement_acceptances.get(transition.settlement_id)
        if proposal is None:
            raise ValueError("Settlement proposal is not found")
        if acceptance is None:
            raise ValueError("Settlement acceptance is required")
        funding = self._session_funding_accounts.get(transition.session_id)
        if funding is None:
            raise ValueError("Session Funding Account is not found")
        proposal_operation = self._require_finalized_dependency(
            proposal_operation_id,
            expected_operation_type="SESSION_SETTLEMENT_PROPOSE",
            finalized_operation_ids=finalized_operation_ids,
            error_message="Settlement proposal is not finalized",
        )
        acceptance_operation = self._require_finalized_dependency(
            acceptance_operation_id,
            expected_operation_type="SESSION_SETTLEMENT_ACCEPT",
            finalized_operation_ids=finalized_operation_ids,
            error_message="Settlement acceptance is not finalized",
        )
        recorded_proposal_payload = proposal_operation.get("payload")
        recorded_acceptance_payload = acceptance_operation.get("payload")
        if not isinstance(recorded_proposal_payload, dict) or not isinstance(recorded_acceptance_payload, dict):
            raise ValueError("Settlement dependency payload is invalid")
        recorded_proposal_data = recorded_proposal_payload.get("proposal")
        recorded_acceptance_data = recorded_acceptance_payload.get("acceptance")
        if not isinstance(recorded_proposal_data, dict) or not isinstance(recorded_acceptance_data, dict):
            raise ValueError("Settlement dependency payload is incomplete")
        try:
            recorded_proposal = SessionSettlementProposal.model_validate(recorded_proposal_data)
            recorded_acceptance = SessionSettlementAcceptance.model_validate(recorded_acceptance_data)
        except ValueError as error:
            raise ValueError("Settlement dependency payload is invalid") from error
        if recorded_proposal != proposal or recorded_acceptance != acceptance:
            raise ValueError("Settlement finalization dependency binding is invalid")
        if (
            proposal_operation_id not in envelope.evidence_references
            or acceptance_operation_id not in envelope.evidence_references
        ):
            raise ValueError("Settlement finalization dependency is not referenced")
        if (
            payload.get("session_id") != proposal.session_id
            or payload.get("settlement_input_root") != proposal.settlement_input_root
            or payload.get("acceptance_hash") != acceptance.acceptance_hash
            or transition.session_id != proposal.session_id
        ):
            raise ValueError("Settlement finalization binding is invalid")
        if envelope.fee_payer != funding.consumer_funding_account:
            raise ValueError("Settlement finalization fee payer is not the Consumer")
        if funding.funding_state in {"RELEASED", "REFUNDED"}:
            raise ValueError("Session funding account is already finalized")
        if proposal.dispute_reserve_q_atoms != 0:
            raise ValueError("Settlement with dispute reserve requires partial finalization")
        if self._settlement_transition_hashes.get(transition.settlement_id) is not None:
            raise ValueError("Settlement transition is already finalized")
        if (
            transition.endpoint_payment_beneficiary != funding.endpoint_payment_beneficiary
            or transition.consumer_refund_beneficiary != funding.consumer_refund_beneficiary
        ):
            raise ValueError("Settlement finalization beneficiaries do not match funding")
        if transition.total_locked_amount_q_atoms != funding.total_locked_amount_q_atoms:
            raise ValueError("Settlement finalization amount does not match funding")
        if transition.previously_released_to_endpoint_q_atoms != funding.released_to_endpoint_q_atoms:
            raise ValueError("Settlement finalization prior Endpoint release is invalid")
        if transition.previously_refunded_to_consumer_q_atoms != (
            funding.consumer_payment_refund_q_atoms + funding.consumer_fee_refund_q_atoms
        ):
            raise ValueError("Settlement finalization prior Consumer refund is invalid")
        if transition.previously_consumed_network_fees_q_atoms != funding.consumed_network_fees_q_atoms:
            raise ValueError("Settlement finalization prior Network Fees are invalid")

        expected_endpoint_credit = proposal.final_endpoint_payment_q_atoms - funding.released_to_endpoint_q_atoms
        expected_consumer_credit = (
            proposal.consumer_payment_refund_q_atoms
            + proposal.consumer_fee_refund_q_atoms
            - funding.consumer_payment_refund_q_atoms
            - funding.consumer_fee_refund_q_atoms
        )
        expected_network_fees = proposal.actual_network_fees_q_atoms - funding.consumed_network_fees_q_atoms
        if transition.credit_endpoint_q_atoms != expected_endpoint_credit:
            raise ValueError("Settlement finalization Endpoint Payment is invalid")
        if transition.credit_consumer_q_atoms != expected_consumer_credit:
            raise ValueError("Settlement finalization Consumer refund is invalid")
        if transition.consume_network_fees_q_atoms != expected_network_fees:
            raise ValueError("Settlement finalization Network Fees are invalid")
        if transition.retain_dispute_reserve_q_atoms != proposal.dispute_reserve_q_atoms:
            raise ValueError("Settlement finalization dispute reserve is invalid")
        if transition.settlement_id not in envelope.evidence_references:
            raise ValueError("Settlement finalization settlement ID is not referenced")
        if proposal.settlement_input_root not in envelope.evidence_references:
            raise ValueError("Settlement finalization input root is not referenced")
        return {
            "payload": payload,
            "transition": transition,
            "proposal": proposal,
            "acceptance": acceptance,
            "funding": funding,
        }

    def apply_consensus_settlement_finalize(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Apply one accepted Settlement transition atomically."""
        validated = self.validate_consensus_settlement_finalize(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        transition = validated["transition"]
        proposal = validated["proposal"]
        funding = validated["funding"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionSettlementFinalized"],
        )
        self.credit_wallet_q_atoms(
            wallet_id=transition.endpoint_payment_beneficiary,
            amount_q_atoms=transition.credit_endpoint_q_atoms,
        )
        self.credit_wallet_q_atoms(
            wallet_id=transition.consumer_refund_beneficiary,
            amount_q_atoms=transition.credit_consumer_q_atoms,
        )
        next_funding = _with_funding_updates(
            funding,
            {
                "released_to_endpoint_q_atoms": proposal.final_endpoint_payment_q_atoms,
                "consumer_payment_refund_q_atoms": proposal.consumer_payment_refund_q_atoms,
                "consumer_fee_refund_q_atoms": proposal.consumer_fee_refund_q_atoms,
                "consumed_network_fees_q_atoms": proposal.actual_network_fees_q_atoms,
                "active_dispute_reserve_q_atoms": proposal.dispute_reserve_q_atoms,
                "unsettled_payment_reserve_q_atoms": 0,
                "unsettled_fee_reserve_q_atoms": 0,
                "funding_state": ("DISPUTE_RESERVED" if proposal.dispute_reserve_q_atoms else "RELEASED"),
            },
        )
        self._session_funding_accounts[transition.session_id] = next_funding
        self._settlement_transition_hashes[transition.settlement_id] = str(transition.transition_hash)
        return record

    def validate_consensus_force_settle(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Validate the conservative MVP Forced Settlement boundary.

        The first consensus profile only handles a proven Endpoint/Runtime
        unavailability.  It refuses all requested payment claims and refunds
        the remaining locked exposure instead of deriving payment from opaque
        or unacknowledged usage.
        """
        if envelope.operation_type != SESSION_FORCE_SETTLE_OPERATION:
            raise ValueError("consensus Forced Settlement requires SESSION_FORCE_SETTLE")
        if envelope.origin_type != "evidence_triggered":
            raise ValueError("Forced Settlement requires evidence-triggered origin")
        if envelope.fee_class != "session" or not envelope.fee_payer:
            raise ValueError("Forced Settlement requires a session fee payer")

        payload = dict(envelope.payload)
        required_text = (
            "session_id",
            "failure_class",
            "requested_at",
            "force_after",
            "observed_at",
            "failure_evidence_root",
            "failure_evidence_operation_id",
            "funding_lock_operation_id",
            "request_settlement_root",
            "usage_chain_root",
            "checkpoint_root",
            "initiator_wallet",
            "initiator_signature",
        )
        for field_name in required_text:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Forced Settlement field is invalid: {field_name}")
        failure_class = str(payload["failure_class"])
        if failure_class not in {
            "ENDPOINT_UNAVAILABLE",
            "ENDPOINT_FAILURE",
            "CONSUMER_TIMEOUT_AFTER_COMPLETED_FIXED_PRICE",
        }:
            raise ValueError("Forced Settlement failure class is unsupported")

        transition_payload = payload.get("transition")
        if not isinstance(transition_payload, dict):
            raise ValueError("Forced Settlement transition is required")
        try:
            transition = AtomicSettlementTransition.model_validate(transition_payload)
        except ValueError as error:
            raise ValueError(f"Forced Settlement transition is invalid: {error}") from error

        requested_payment = payload.get("requested_payment_q_atoms")
        requested_refund = payload.get("requested_refund_q_atoms")
        for field_name, value in (
            ("requested_payment_q_atoms", requested_payment),
            ("requested_refund_q_atoms", requested_refund),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"Forced Settlement amount is invalid: {field_name}")
        requested_payment = cast(int, requested_payment)
        requested_refund = cast(int, requested_refund)

        try:
            force_after = datetime.fromisoformat(str(payload["force_after"]).replace("Z", "+00:00"))
            observed_at = datetime.fromisoformat(str(payload["observed_at"]).replace("Z", "+00:00"))
            requested_at = datetime.fromisoformat(str(payload["requested_at"]).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("Forced Settlement timestamp is invalid") from error
        if force_after.tzinfo is None or observed_at.tzinfo is None or requested_at.tzinfo is None:
            raise ValueError("Forced Settlement timestamps require timezone")
        if observed_at < force_after or observed_at < requested_at:
            raise ValueError("Forced Settlement timeout has not elapsed")

        funding = self._session_funding_accounts.get(str(payload["session_id"]))
        if funding is None:
            raise ValueError("Session Funding Account is not found")
        if envelope.fee_payer != funding.consumer_funding_account:
            raise ValueError("Forced Settlement fee payer is not the Consumer")
        if payload["initiator_wallet"] not in {
            funding.consumer_funding_account,
            funding.endpoint_payment_beneficiary,
        }:
            raise ValueError("Forced Settlement initiator is not a Session participant")
        if funding.funding_state in {"RELEASED", "REFUNDED"}:
            raise ValueError("Session funding account is already finalized")
        if funding.active_dispute_reserve_q_atoms != 0:
            raise ValueError("Forced Settlement cannot consume an active dispute reserve")

        lock_operation_id = str(payload["funding_lock_operation_id"])
        failure_operation_id = str(payload["failure_evidence_operation_id"])
        lock_operation = self._require_finalized_dependency(
            lock_operation_id,
            expected_operation_type="SESSION_ESCROW_LOCK",
            finalized_operation_ids=finalized_operation_ids,
            error_message="Forced Settlement escrow lock is not finalized",
        )
        failure_operation = self._require_finalized_operation(
            failure_operation_id,
            finalized_operation_ids=finalized_operation_ids,
            error_message="Forced Settlement failure evidence is not finalized",
        )
        lock_payload = lock_operation.get("payload")
        if not isinstance(lock_payload, dict) or (
            lock_payload.get("session_id") != funding.session_id
            or lock_payload.get("funding_state_hash") != funding.funding_state_hash
        ):
            raise ValueError("Forced Settlement escrow lock binding is invalid")
        failure_payload = failure_operation.get("payload")
        if not isinstance(failure_payload, dict) or (
            failure_payload.get("session_id") != funding.session_id
            or failure_payload.get("failure_evidence_root") != payload["failure_evidence_root"]
            or failure_payload.get("failure_class") not in _failure_evidence_classes_for_force_settlement(failure_class)
        ):
            raise ValueError("Forced Settlement failure evidence binding is invalid")
        for reference in (
            lock_operation_id,
            failure_operation_id,
            str(payload["failure_evidence_root"]),
        ):
            if reference not in envelope.evidence_references:
                raise ValueError("Forced Settlement evidence reference is missing")

        if transition.session_id != funding.session_id:
            raise ValueError("Forced Settlement session binding is invalid")
        if transition.endpoint_payment_beneficiary != funding.endpoint_payment_beneficiary:
            raise ValueError("Forced Settlement Endpoint beneficiary is invalid")
        if transition.consumer_refund_beneficiary != funding.consumer_refund_beneficiary:
            raise ValueError("Forced Settlement Consumer beneficiary is invalid")
        if transition.total_locked_amount_q_atoms != funding.total_locked_amount_q_atoms:
            raise ValueError("Forced Settlement amount does not match funding")
        if transition.previously_released_to_endpoint_q_atoms != funding.released_to_endpoint_q_atoms:
            raise ValueError("Forced Settlement prior Endpoint release is invalid")
        if transition.previously_refunded_to_consumer_q_atoms != (
            funding.consumer_payment_refund_q_atoms + funding.consumer_fee_refund_q_atoms
        ):
            raise ValueError("Forced Settlement prior Consumer refund is invalid")
        if transition.previously_consumed_network_fees_q_atoms != funding.consumed_network_fees_q_atoms:
            raise ValueError("Forced Settlement prior Network Fees are invalid")
        remaining_locked = (
            funding.total_locked_amount_q_atoms
            - funding.released_to_endpoint_q_atoms
            - funding.consumer_payment_refund_q_atoms
            - funding.consumer_fee_refund_q_atoms
            - funding.consumed_network_fees_q_atoms
        )
        if failure_class in {"ENDPOINT_UNAVAILABLE", "ENDPOINT_FAILURE"}:
            if (
                transition.credit_endpoint_q_atoms != 0
                or transition.consume_network_fees_q_atoms != 0
                or transition.retain_dispute_reserve_q_atoms != 0
            ):
                raise ValueError("Forced Settlement cannot pay unacknowledged exposure")
            if transition.credit_consumer_q_atoms != remaining_locked:
                raise ValueError("Forced Settlement refund does not conserve remaining funding")
            if requested_payment != 0:
                raise ValueError("Forced Settlement requested payment must be zero")
        elif requested_payment > 0:
            request_evidence = payload.get("request_evidence")
            if not isinstance(request_evidence, list) or not request_evidence:
                raise ValueError("Forced Settlement payment requires terminal Request evidence")
            if str(payload["request_settlement_root"]) not in envelope.evidence_references:
                raise ValueError("Forced Settlement Request Settlement root is not referenced")
            settlement_input_root = payload.get("settlement_input_root")
            if not isinstance(settlement_input_root, str) or not settlement_input_root.strip():
                raise ValueError("Forced Settlement payment requires Settlement Input root")
            if settlement_input_root not in envelope.evidence_references:
                raise ValueError("Forced Settlement Settlement Input root is not referenced")
            evidence_request_ids: set[str] = set()
            evidence_charge = 0
            for item in request_evidence:
                if not isinstance(item, dict):
                    raise ValueError("Forced Settlement Request evidence is invalid")
                request_id = item.get("request_id")
                if not isinstance(request_id, str) or not request_id.strip():
                    raise ValueError("Forced Settlement Request ID is invalid")
                if request_id in evidence_request_ids:
                    raise ValueError("Forced Settlement Request evidence is duplicated")
                evidence_request_ids.add(request_id)
                if item.get("terminal_state") != "COMPLETED":
                    raise ValueError("Forced Settlement payment requires completed Request evidence")
                usage_hash = item.get("final_usage_report_hash")
                if not isinstance(usage_hash, str) or not usage_hash.strip():
                    raise ValueError("Forced Settlement payment requires Final Usage evidence")
                record_hash = item.get("record_hash")
                if not isinstance(record_hash, str) or not record_hash.strip():
                    raise ValueError("Forced Settlement Request record hash is invalid")
                if item.get("dispute_state") != "NONE":
                    raise ValueError("Forced Settlement payment cannot use disputed Request evidence")
                disputed_amount = item.get("disputed_amount_q_atoms", 0)
                charge = item.get("capped_request_charge_q_atoms")
                if isinstance(disputed_amount, bool) or not isinstance(disputed_amount, int) or disputed_amount != 0:
                    raise ValueError("Forced Settlement payment cannot use disputed Request amounts")
                if isinstance(charge, bool) or not isinstance(charge, int) or charge < 0:
                    raise ValueError("Forced Settlement Request charge evidence is invalid")
                evidence_charge += charge
                if record_hash not in envelope.evidence_references:
                    raise ValueError("Forced Settlement Request record is not referenced")
                if usage_hash not in envelope.evidence_references:
                    raise ValueError("Forced Settlement Final Usage is not referenced")
            if evidence_charge != requested_payment:
                raise ValueError("Forced Settlement payment does not match Request evidence")
            if transition.credit_endpoint_q_atoms != requested_payment:
                raise ValueError("Forced Settlement Endpoint Payment does not match request")
            if transition.retain_dispute_reserve_q_atoms != 0:
                raise ValueError("Forced Settlement payment cannot retain a dispute reserve")
            expected_payment_available = (
                funding.endpoint_payment_reserve_q_atoms
                - funding.released_to_endpoint_q_atoms
                - funding.consumer_payment_refund_q_atoms
            )
            if requested_payment > expected_payment_available:
                raise ValueError("Forced Settlement payment exceeds unsettled Endpoint reserve")
            expected_payment_refund = (
                funding.endpoint_payment_reserve_q_atoms
                - funding.released_to_endpoint_q_atoms
                - funding.consumer_payment_refund_q_atoms
                - transition.credit_endpoint_q_atoms
            )
            expected_fee_refund = (
                funding.network_fee_reserve_q_atoms
                - funding.consumed_network_fees_q_atoms
                - transition.consume_network_fees_q_atoms
            )
            if expected_payment_refund < 0 or expected_fee_refund < 0:
                raise ValueError("Forced Settlement refund exceeds available reserve")
            if transition.credit_consumer_q_atoms != (expected_payment_refund + expected_fee_refund):
                raise ValueError("Forced Settlement Consumer refund does not match reserves")
        else:
            if transition.credit_endpoint_q_atoms != 0:
                raise ValueError("Forced Settlement payment is not requested")
            if transition.credit_consumer_q_atoms != remaining_locked:
                raise ValueError("Forced Settlement refund does not conserve remaining funding")
        if requested_refund > funding.total_locked_amount_q_atoms:
            raise ValueError("Forced Settlement requested refund exceeds funding")
        if str(payload["failure_evidence_root"]) not in envelope.evidence_references:
            raise ValueError("Forced Settlement failure evidence root is not referenced")
        if transition.settlement_id not in envelope.evidence_references:
            raise ValueError("Forced Settlement settlement ID is not referenced")
        if transition.settlement_id in self._settlement_transition_hashes:
            raise ValueError("Forced Settlement transition is already finalized")

        return {
            "payload": payload,
            "transition": transition,
            "funding": funding,
        }

    def apply_consensus_force_settle(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        finalized_operation_ids: set[str] | None = None,
    ) -> dict:
        """Refund remaining locked exposure for a conservative failure case."""
        validated = self.validate_consensus_force_settle(
            envelope,
            finalized_operation_ids=finalized_operation_ids,
        )
        transition = validated["transition"]
        funding = validated["funding"]
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=["SessionForcedSettlementAuthorized", "SessionRefunded"],
        )
        if transition.credit_endpoint_q_atoms:
            self.credit_wallet_q_atoms(
                wallet_id=transition.endpoint_payment_beneficiary,
                amount_q_atoms=transition.credit_endpoint_q_atoms,
            )
        if transition.credit_consumer_q_atoms:
            self.credit_wallet_q_atoms(
                wallet_id=transition.consumer_refund_beneficiary,
                amount_q_atoms=transition.credit_consumer_q_atoms,
            )
        released_to_endpoint = funding.released_to_endpoint_q_atoms + transition.credit_endpoint_q_atoms
        consumer_payment_refund = (
            funding.endpoint_payment_reserve_q_atoms - released_to_endpoint - transition.retain_dispute_reserve_q_atoms
        )
        consumer_fee_refund = (
            funding.network_fee_reserve_q_atoms
            - funding.consumed_network_fees_q_atoms
            - transition.consume_network_fees_q_atoms
        )
        next_funding = _with_funding_updates(
            funding,
            {
                "released_to_endpoint_q_atoms": released_to_endpoint,
                "consumer_payment_refund_q_atoms": consumer_payment_refund,
                "consumer_fee_refund_q_atoms": consumer_fee_refund,
                "active_dispute_reserve_q_atoms": transition.retain_dispute_reserve_q_atoms,
                "unsettled_payment_reserve_q_atoms": transition.retain_dispute_reserve_q_atoms,
                "unsettled_fee_reserve_q_atoms": 0,
                "funding_state": (
                    "DISPUTE_RESERVED"
                    if transition.retain_dispute_reserve_q_atoms
                    else ("RELEASED" if transition.credit_endpoint_q_atoms else "REFUNDED")
                ),
            },
        )
        self._session_funding_accounts[funding.session_id] = next_funding
        self._settlement_transition_hashes[transition.settlement_id] = str(transition.transition_hash)
        return record

    def _require_finalized_dependency(
        self,
        operation_id: str,
        *,
        expected_operation_type: str,
        finalized_operation_ids: set[str] | None,
        error_message: str,
    ) -> dict:
        operation = self._require_finalized_operation(
            operation_id,
            finalized_operation_ids=finalized_operation_ids,
            error_message=error_message,
        )
        if operation.get("operation_type") != expected_operation_type:
            raise ValueError(error_message)
        return operation

    def _require_funding_predecessor(
        self,
        operation_id: str,
        *,
        funding: SessionFundingAccount,
        finalized_operation_ids: set[str] | None,
        evidence_references: list[str],
        error_message: str,
    ) -> dict:
        """Bind a funding mutation to the exact prior Funding Account hash."""
        operation = self._require_finalized_operation(
            operation_id,
            finalized_operation_ids=finalized_operation_ids,
            error_message=error_message,
        )
        if operation.get("operation_type") not in {
            "SESSION_ESCROW_LOCK",
            SESSION_ESCROW_EXTEND_OPERATION,
            SESSION_ESCROW_RELEASE_OPERATION,
        }:
            raise ValueError(error_message)
        payload = operation.get("payload")
        if not isinstance(payload, dict):
            raise ValueError(error_message)
        if operation_id not in evidence_references:
            raise ValueError(error_message)
        if operation.get("operation_type") == "SESSION_ESCROW_LOCK":
            previous_session_id = payload.get("session_id")
            previous_state_hash = payload.get("funding_state_hash")
        else:
            previous_funding = payload.get("funding")
            previous_session_id = previous_funding.get("session_id") if isinstance(previous_funding, dict) else None
            previous_state_hash = (
                previous_funding.get("funding_state_hash") if isinstance(previous_funding, dict) else None
            )
        if previous_session_id != funding.session_id or previous_state_hash != funding.funding_state_hash:
            raise ValueError(error_message)
        return operation

    def _require_finalized_operation(
        self,
        operation_id: str,
        *,
        finalized_operation_ids: set[str] | None,
        error_message: str,
    ) -> dict:
        if finalized_operation_ids is not None:
            if operation_id not in finalized_operation_ids:
                raise ValueError(error_message)
        elif not self._finalized_operation_registry.contains(operation_id):
            raise ValueError(error_message)
        operation = next(
            (item for item in reversed(self._operations) if item.get("operation_id") == operation_id),
            None,
        )
        if operation is None:
            raise ValueError(error_message)
        return operation

    def apply_settlement_evaluation(
        self,
        evaluation: SettlementEvaluation,
        *,
        created_at: str | None = None,
    ) -> SessionFundingAccount:
        transition = evaluation.transition
        proposal = evaluation.proposal
        funding = self.get_session_funding_account(transition.session_id)
        existing_hash = self._settlement_transition_hashes.get(transition.settlement_id)
        if existing_hash is not None:
            if existing_hash != transition.transition_hash:
                raise ValueError("conflicting Settlement transition")
            return funding
        if funding.funding_state in {"RELEASED", "REFUNDED"}:
            raise ValueError("Session funding account is already finalized")
        if (
            transition.endpoint_payment_beneficiary != funding.endpoint_payment_beneficiary
            or transition.consumer_refund_beneficiary != funding.consumer_refund_beneficiary
        ):
            raise ValueError("Settlement beneficiaries do not match Session funding")
        if evaluation.input_set.funding_state_reference != funding.funding_state_hash:
            raise ValueError("Settlement input does not match current funding state")
        if funding.funding_class == "TRUSTED_POSTPAID":
            raise ValueError("postpaid obligations require a collection ledger")
        elif transition.total_locked_amount_q_atoms != funding.total_locked_amount_q_atoms:
            raise ValueError("Settlement transition does not match locked funding")

        self.record_operation(
            operation_type=(
                "SESSION_SETTLEMENT_PARTIAL_FINALIZE"
                if proposal.dispute_reserve_q_atoms
                else "SESSION_SETTLEMENT_FINALIZE"
            ),
            origin_type="multi_party",
            fee_class="session",
            initiator_id=transition.session_id,
            fee_payer=funding.consumer_funding_account,
            payload={
                "settlement_id": transition.settlement_id,
                "session_id": transition.session_id,
                "settlement_input_root": proposal.settlement_input_root,
                "transition_hash": transition.transition_hash,
                "funding_state_hash": funding.funding_state_hash,
                "endpoint_payment_q_atoms": transition.credit_endpoint_q_atoms,
                "consumer_refund_q_atoms": transition.credit_consumer_q_atoms,
                "network_fees_q_atoms": transition.consume_network_fees_q_atoms,
                "dispute_reserve_q_atoms": transition.retain_dispute_reserve_q_atoms,
                "postpaid_obligation_q_atoms": transition.postpaid_obligation_q_atoms,
            },
            created_at=created_at,
            emitted_events=["SessionSettlementFinalized"],
        )

        self.credit_wallet_q_atoms(
            wallet_id=transition.endpoint_payment_beneficiary,
            amount_q_atoms=transition.credit_endpoint_q_atoms,
        )
        self.credit_wallet_q_atoms(
            wallet_id=transition.consumer_refund_beneficiary,
            amount_q_atoms=transition.credit_consumer_q_atoms,
        )
        next_funding = _with_funding_updates(
            funding,
            {
                "released_to_endpoint_q_atoms": proposal.final_endpoint_payment_q_atoms,
                "consumer_payment_refund_q_atoms": proposal.consumer_payment_refund_q_atoms,
                "consumer_fee_refund_q_atoms": proposal.consumer_fee_refund_q_atoms,
                "consumed_network_fees_q_atoms": proposal.actual_network_fees_q_atoms,
                "active_dispute_reserve_q_atoms": proposal.dispute_reserve_q_atoms,
                "unsettled_payment_reserve_q_atoms": 0,
                "unsettled_fee_reserve_q_atoms": 0,
                "funding_state": ("DISPUTE_RESERVED" if proposal.dispute_reserve_q_atoms else "RELEASED"),
            },
        )
        self._session_funding_accounts[transition.session_id] = next_funding
        self._settlement_transition_hashes[transition.settlement_id] = str(transition.transition_hash)
        return next_funding

    def list_operations(self, *, limit: int | None = None) -> list[dict]:
        events = list(self._operations)
        if limit is None or limit >= len(events):
            return events
        return events[-limit:]

    def get_operation(self, operation_id: str) -> dict | None:
        """Return one immutable local operation by its local correlation ID."""
        for operation in reversed(self._operations):
            if operation.get("operation_id") == operation_id:
                return dict(operation)
        return None

    def finalized_operation_ids(self) -> set[str]:
        """Return finalized operation IDs from the canonical replay index."""
        return self._finalized_operation_registry.operation_ids()

    def finalized_operation_reference(self, operation_id: str) -> dict | None:
        """Return the immutable replay reference for one finalized operation."""
        reference = self._finalized_operation_registry.get(operation_id)
        return reference.as_dict() if reference is not None else None

    def snapshot_finalized_operation_registry(self) -> list[dict]:
        """Return the deterministic derived finalized-operation index."""
        return self._finalized_operation_registry.snapshot()

    def export_operations(
        self,
        *,
        after_operation_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        items = list(self._operations)
        if after_operation_id is not None:
            found = next(
                (index for index, item in enumerate(items) if item["operation_id"] == after_operation_id),
                None,
            )
            if found is None:
                return {
                    "items": [],
                    "count": 0,
                    "cursor_status": "stale",
                    "watermark_sequence": items[-1]["sequence_id"] if items else 0,
                }
            items = items[found + 1 :]
        elif after_sequence is not None:
            items = [item for item in items if int(item["sequence_id"]) > int(after_sequence)]
        limit = max(0, int(limit))
        page = items[:limit]
        return {
            "items": page,
            "count": len(page),
            "cursor_status": "ok",
            "retained_from_sequence": page[0]["sequence_id"] if page else None,
            "retained_through_sequence": page[-1]["sequence_id"] if page else None,
            "watermark_sequence": self._operations[-1]["sequence_id"] if self._operations else 0,
        }

    def wallet_next_sequence(self, wallet_id: str) -> int:
        return int(self._wallet_next_sequences.get(wallet_id, 1))

    def get_next_sequence(self, wallet_id: str) -> int:
        """Get the next expected sequence number for a wallet."""
        return self.wallet_next_sequence(wallet_id)

    def submit_operation(
        self,
        *,
        operation_type: str,
        origin_type: str,
        fee_class: str,
        admission_validator: "AdmissionValidator",
        envelope: "LedgerOperationEnvelope",
        **kwargs,
    ) -> dict:
        """Submit an operation through admission validation, then record."""
        result = admission_validator.validate(envelope)
        if not result.admitted:
            return {
                "admitted": False,
                "reason": result.reason,
                "operation_id": envelope.operation_id,
            }

        # Record the operation — pass envelope fields through
        if operation_type != envelope.operation_type:
            raise ValueError("operation_type must match the admitted envelope")
        if origin_type != envelope.origin_type:
            raise ValueError("origin_type must match the admitted envelope")
        if fee_class != envelope.fee_class:
            raise ValueError("fee_class must match the admitted envelope")

        emitted_events = kwargs.pop("emitted_events", None)
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"unexpected submit_operation arguments: {unexpected}")
        record = self.record_admitted_envelope(
            envelope,
            emitted_events=emitted_events,
        )

        # Advance wallet sequence for subsequent operations
        if envelope.sender_wallet is not None:
            admission_validator.advance_wallet_sequence(envelope.sender_wallet)

        # Mark as finalized for duplicate detection
        admission_validator.record_finalized(envelope.operation_id)

        return {"admitted": True, "operation_id": envelope.operation_id, "record": record}

    def record_admitted_envelope(
        self,
        envelope: "LedgerOperationEnvelope",
        *,
        emitted_events: list[str] | None = None,
    ) -> dict:
        """Persist one already-admitted consensus envelope without rehashing it."""
        operation_id = envelope.operation_id
        if self._finalized_operation_registry.contains(operation_id):
            raise ValueError(f"duplicate operation id: {operation_id}")

        wallet_next_sequence: int | None = None
        if envelope.origin_type == "wallet":
            if envelope.sender_wallet is None or envelope.sender_sequence is None:
                raise ValueError("wallet operations require sender_wallet and sender_sequence")
            expected_sequence = self.wallet_next_sequence(envelope.sender_wallet)
            if envelope.sender_sequence != expected_sequence:
                raise ValueError(
                    f"invalid wallet sequence for {envelope.sender_wallet}: "
                    f"expected {expected_sequence}, got {envelope.sender_sequence}"
                )
            wallet_next_sequence = envelope.sender_sequence + 1

        result = LedgerOperationResult(
            status="applied",
            state_changes_root=_hash_dict(
                {
                    "operation_id": operation_id,
                    "operation_type": envelope.operation_type,
                    "payload": envelope.payload,
                }
            ),
            emitted_events=list(emitted_events or []),
        )
        record = LedgerOperationRecord(
            sequence_id=self._next_sequence_id,
            operation_id=operation_id,
            operation_type=envelope.operation_type,
            operation_version=envelope.operation_version,
            protocol_version=envelope.protocol_version,
            origin_type=envelope.origin_type,
            initiator_id=envelope.initiator_id,
            sender_wallet=envelope.sender_wallet,
            sender_sequence=envelope.sender_sequence,
            fee_class=envelope.fee_class,
            fee_payer=envelope.fee_payer,
            created_at=envelope.created_at,
            expires_at=envelope.expires_at,
            target_epoch=envelope.target_epoch,
            payload=dict(envelope.payload),
            evidence_references=list(envelope.evidence_references),
            signatures=list(envelope.signatures),
            transaction_hash=_consensus_transaction_hash(envelope),
            result=result,
            wallet_next_sequence=wallet_next_sequence,
        ).model_dump(mode="json")
        self._finalized_operation_registry.register(record)
        self._operations.append(record)
        self._operation_ids.add(operation_id)
        self._next_sequence_id += 1
        if envelope.sender_wallet is not None and wallet_next_sequence is not None:
            self._wallet_next_sequences[envelope.sender_wallet] = wallet_next_sequence
        return record

    def stage_operation(self, **kwargs) -> dict:
        """Build an operation projection without changing canonical Ledger state."""
        # Record construction currently mutates only operation metadata, but
        # staging must remain safe if admission later grows additional derived
        # state. Preserve the complete private state instead of maintaining a
        # second, easy-to-forget list of mutable fields.
        canonical_state = deepcopy(self.__dict__)
        try:
            return self.record_operation(**kwargs)
        finally:
            self.__dict__.clear()
            self.__dict__.update(canonical_state)

    def record_operation(
        self,
        *,
        operation_type: str,
        origin_type: str,
        fee_class: str,
        initiator_id: str | None = None,
        sender_wallet: str | None = None,
        fee_payer: str | None = None,
        payload: dict | None = None,
        created_at: str | None = None,
        expires_at: str | None = None,
        target_epoch: str | None = None,
        evidence_references: list[str] | None = None,
        signatures: list[str] | None = None,
        emitted_events: list[str] | None = None,
        expected_sequence: int | None = None,
        operation_version: str = "0.1",
    ) -> dict:
        now = created_at or datetime.now(UTC).isoformat()
        sender_sequence: int | None = None
        next_wallet_sequence: int | None = None
        if origin_type == "wallet":
            if sender_wallet is None:
                raise ValueError("wallet operations require sender_wallet")
            next_wallet_sequence = self.wallet_next_sequence(sender_wallet)
            sender_sequence = int(expected_sequence) if expected_sequence is not None else next_wallet_sequence
            if sender_sequence != next_wallet_sequence:
                raise ValueError(
                    f"invalid wallet sequence for {sender_wallet}: "
                    f"expected {next_wallet_sequence}, got {sender_sequence}"
                )

        unsigned = {
            "operation_type": operation_type,
            "operation_version": operation_version,
            "protocol_version": self.protocol_version,
            "origin_type": origin_type,
            "initiator_id": initiator_id,
            "sender_wallet": sender_wallet,
            "sender_sequence": sender_sequence,
            "fee_class": fee_class,
            "fee_payer": fee_payer,
            "created_at": now,
            "expires_at": expires_at,
            "target_epoch": target_epoch,
            "payload": dict(payload or {}),
            "evidence_references": list(evidence_references or []),
            "signatures": list(signatures or []),
        }
        operation_id = _hash_dict(unsigned)
        if self._finalized_operation_registry.contains(operation_id):
            raise ValueError(f"duplicate operation id: {operation_id}")
        result = LedgerOperationResult(
            status="applied",
            state_changes_root=_hash_dict(
                {
                    "operation_id": operation_id,
                    "operation_type": operation_type,
                    "payload": unsigned["payload"],
                }
            ),
            emitted_events=list(emitted_events or []),
        )
        wallet_next_sequence_value = None
        if sender_wallet is not None and sender_sequence is not None:
            wallet_next_sequence_value = int(sender_sequence) + 1
        record = LedgerOperationRecord(
            sequence_id=self._next_sequence_id,
            operation_id=operation_id,
            operation_type=operation_type,
            operation_version=operation_version,
            protocol_version=self.protocol_version,
            origin_type=cast(LedgerOriginType, origin_type),
            initiator_id=initiator_id,
            sender_wallet=sender_wallet,
            sender_sequence=sender_sequence,
            fee_class=cast(LedgerFeeClass, fee_class),
            fee_payer=fee_payer,
            created_at=now,
            expires_at=expires_at,
            target_epoch=target_epoch,
            payload=cast(dict, unsigned["payload"]),
            evidence_references=cast(list[str], unsigned["evidence_references"]),
            signatures=cast(list[str], unsigned["signatures"]),
            result=result,
            wallet_next_sequence=wallet_next_sequence_value,
        ).model_dump(mode="json")
        self._finalized_operation_registry.register(record)
        self._operations.append(record)
        self._operation_ids.add(operation_id)
        self._next_sequence_id += 1
        if sender_wallet is not None and wallet_next_sequence_value is not None:
            self._wallet_next_sequences[sender_wallet] = wallet_next_sequence_value
        return record

    def snapshot_operations(self) -> list[dict]:
        return list(self._operations)

    def remove_noncanonical_operations(self, operation_types: set[str]) -> list[str]:
        """Remove allow-listed local projections before validator bootstrap.

        Older validator nodes could record draft Endpoint updates as wallet
        operations even though those writes never entered consensus. Keeping
        them would advance local wallet sequences beyond the ABCI state. This
        migration is deliberately explicit and returns removed IDs for audit.
        """
        if not operation_types:
            return []
        removed = [
            operation
            for operation in self._operations
            if operation.get("operation_type") in operation_types
        ]
        if not removed:
            return []

        self._operations = [
            operation
            for operation in self._operations
            if operation.get("operation_type") not in operation_types
        ]
        self._finalized_operation_registry = FinalizedOperationRegistry.from_records(
            self._operations
        )
        self._operation_ids = self._finalized_operation_registry.operation_ids()
        self._next_sequence_id = max(
            (int(operation["sequence_id"]) for operation in self._operations),
            default=0,
        ) + 1

        for operation in removed:
            wallet_id = operation.get("sender_wallet")
            if not isinstance(wallet_id, str):
                continue
            remaining_sequences = [
                int(candidate["sender_sequence"]) + 1
                for candidate in self._operations
                if candidate.get("sender_wallet") == wallet_id
                and candidate.get("sender_sequence") is not None
            ]
            self._wallet_next_sequences[wallet_id] = max(
                remaining_sequences,
                default=1,
            )
        return [str(operation["operation_id"]) for operation in removed]

    def restore_missing_operation_records(
        self,
        operations: list[dict],
        operation_types: set[str],
    ) -> list[str]:
        """Restore allow-listed records present in the durable consensus view.

        This is used only for recovery of a partially completed validator
        migration. The records are copied from the verified ABCI projection,
        never synthesized locally.
        """
        if not operations:
            return []
        existing_by_id = {
            str(operation["operation_id"]): operation
            for operation in self._operations
        }
        missing: list[dict] = []
        for operation in operations:
            operation_type = operation.get("operation_type")
            operation_id = operation.get("operation_id")
            if operation_type not in operation_types or not isinstance(operation_id, str):
                raise ValueError("validator operation recovery contains an unauthorized record")
            existing = existing_by_id.get(operation_id)
            if existing is not None:
                if existing != operation:
                    raise ValueError("validator operation recovery found a conflicting record")
                continue
            missing.append(LedgerOperationRecord(**operation).model_dump(mode="json"))

        if not missing:
            return []
        occupied_sequence_ids = {
            int(operation["sequence_id"]) for operation in self._operations
        }
        if any(int(operation["sequence_id"]) in occupied_sequence_ids for operation in missing):
            raise ValueError("validator operation recovery found a sequence conflict")
        self._operations.extend(missing)
        self._operations.sort(key=lambda operation: int(operation["sequence_id"]))
        self._finalized_operation_registry = FinalizedOperationRegistry.from_records(
            self._operations
        )
        self._operation_ids = self._finalized_operation_registry.operation_ids()
        self._next_sequence_id = max(
            (int(operation["sequence_id"]) for operation in self._operations),
            default=0,
        ) + 1
        for operation in missing:
            wallet_id = operation.get("sender_wallet")
            sender_sequence = operation.get("sender_sequence")
            if isinstance(wallet_id, str) and sender_sequence is not None:
                self._wallet_next_sequences[wallet_id] = max(
                    self.wallet_next_sequence(wallet_id),
                    int(sender_sequence) + 1,
                )
        return [str(operation["operation_id"]) for operation in missing]

    def snapshot_wallet_sequences(self) -> dict[str, int]:
        return dict(self._wallet_next_sequences)

    def snapshot_settlement_state(self) -> dict:
        return {
            "wallet_q_atom_balances": dict(self._wallet_q_atom_balances),
            "recyclable_q_atoms": self._recyclable_q_atoms,
            "burned_q_atoms": self._burned_q_atoms,
            "stake_records": self.snapshot_stake_records(),
            "participant_suspensions": list(self.participant_suspensions().values()),
            "session_funding_accounts": [
                account.model_dump(mode="json") for account in self._session_funding_accounts.values()
            ],
            "settlement_ready_commits": [
                commitment.model_dump(mode="json") for commitment in self._settlement_ready_commits.values()
            ],
            "settlement_proposals": [
                proposal.model_dump(mode="json") for proposal in self._settlement_proposals.values()
            ],
            "settlement_acceptances": [
                acceptance.model_dump(mode="json") for acceptance in self._settlement_acceptances.values()
            ],
            "session_checkpoints": [
                checkpoint.model_dump(mode="json") for checkpoint in self._session_checkpoints.values()
            ],
            "settlement_disputes": [dispute.model_dump(mode="json") for dispute in self._settlement_disputes.values()],
            "settlement_corrections": [
                correction.model_dump(mode="json") for correction in self._settlement_corrections.values()
            ],
            "settlement_transition_hashes": dict(self._settlement_transition_hashes),
            "development_pool_allocations": list(self._development_pool_allocations.values()),
            "development_pool_carryovers": list(self._development_pool_carryovers.values()),
            "development_bounty_states": list(self._development_bounty_states.values()),
            "development_reward_reserves": list(self._development_reward_reserves.values()),
            "development_reward_payment_records": list(self._development_reward_payment_records.values()),
            "development_reward_unclaimed_records": list(self._development_reward_unclaimed_records.values()),
            "development_reward_claim_records": list(self._development_reward_claim_records.values()),
            "development_reward_expiry_records": list(self._development_reward_expiry_records.values()),
            "development_reward_finalized_commitments": list(self._development_reward_finalized_commitments.values()),
            "development_reward_adjustment_snapshots": list(self._development_reward_adjustment_snapshots.values()),
            "development_reward_cancellations": list(self._development_reward_cancellations.values()),
            "development_reward_corrections": list(self._development_reward_corrections.values()),
        }

    def restore(
        self,
        *,
        operations: list[dict],
        wallet_sequences: dict[str, int],
        wallet_q_atom_balances: dict[str, int] | None = None,
        recyclable_q_atoms: int = 0,
        burned_q_atoms: int = 0,
        stake_records: list[dict] | None = None,
        participant_suspensions: list[dict] | None = None,
        session_funding_accounts: list[dict] | None = None,
        settlement_ready_commits: list[dict] | None = None,
        settlement_proposals: list[dict] | None = None,
        settlement_acceptances: list[dict] | None = None,
        session_checkpoints: list[dict] | None = None,
        settlement_disputes: list[dict] | None = None,
        settlement_corrections: list[dict] | None = None,
        settlement_transition_hashes: dict[str, str] | None = None,
        development_pool_allocations: list[dict] | None = None,
        development_pool_carryovers: list[dict] | None = None,
        development_bounty_states: list[dict] | None = None,
        development_reward_reserves: list[dict] | None = None,
        development_reward_payment_records: list[dict] | None = None,
        development_reward_unclaimed_records: list[dict] | None = None,
        development_reward_claim_records: list[dict] | None = None,
        development_reward_expiry_records: list[dict] | None = None,
        development_reward_finalized_commitments: list[dict] | None = None,
        development_reward_adjustment_snapshots: list[dict] | None = None,
        development_reward_cancellations: list[dict] | None = None,
        development_reward_corrections: list[dict] | None = None,
        consensus_state: dict | None = None,
    ) -> None:
        self._operations = [LedgerOperationRecord(**item).model_dump(mode="json") for item in operations]
        self._finalized_operation_registry = FinalizedOperationRegistry.from_records(self._operations)
        self._operation_ids = self._finalized_operation_registry.operation_ids()
        self._wallet_next_sequences = {str(key): int(value) for key, value in wallet_sequences.items()}
        self._wallet_q_atom_balances = {str(key): int(value) for key, value in (wallet_q_atom_balances or {}).items()}
        if recyclable_q_atoms < 0 or burned_q_atoms < 0:
            raise ValueError("penalty accounting totals cannot be negative")
        self._recyclable_q_atoms = int(recyclable_q_atoms)
        self._burned_q_atoms = int(burned_q_atoms)
        restored_stakes: dict[str, dict] = {}
        for raw_stake in stake_records or []:
            if not isinstance(raw_stake, dict):
                raise ValueError("stake record is invalid")
            stake_id = raw_stake.get("stake_id")
            if not isinstance(stake_id, str) or not stake_id.strip():
                raise ValueError("stake record ID is invalid")
            if stake_id in restored_stakes:
                raise ValueError("stake record IDs are not unique")
            restored_stakes[stake_id] = dict(raw_stake)
        self._stake_records = restored_stakes
        restored_suspensions: dict[str, dict] = {}
        for raw_suspension in participant_suspensions or []:
            if not isinstance(raw_suspension, dict):
                raise ValueError("participant suspension is invalid")
            target_id = raw_suspension.get("target_id")
            if not isinstance(target_id, str) or not target_id.strip():
                raise ValueError("participant suspension target is invalid")
            if target_id in restored_suspensions:
                raise ValueError("participant suspension targets are not unique")
            restored_suspensions[target_id] = dict(raw_suspension)
        self._participant_suspensions = restored_suspensions
        self._session_funding_accounts = {
            account.session_id: account
            for account in (SessionFundingAccount.model_validate(item) for item in (session_funding_accounts or []))
        }
        self._settlement_ready_commits = {}
        for raw_commitment in settlement_ready_commits or []:
            commitment = SettlementReadyCommitment.model_validate(raw_commitment)
            if commitment.session_id in self._settlement_ready_commits:
                raise ValueError("Settlement readiness sessions are not unique")
            self._settlement_ready_commits[commitment.session_id] = commitment
        restored_session_open_records: dict[str, dict] = {}
        for operation in self._operations:
            if operation.get("operation_type") != SESSION_OPEN_OPERATION:
                continue
            payload = operation.get("payload")
            if not isinstance(payload, dict):
                continue
            session_id = payload.get("session_id")
            if not isinstance(session_id, str) or not session_id.strip():
                continue
            previous = restored_session_open_records.get(session_id)
            if previous is not None and previous != payload:
                raise ValueError("conflicting canonical Session open records")
            restored_session_open_records[session_id] = dict(payload)
        self._session_open_records = restored_session_open_records
        restored_session_accept_records: dict[str, dict] = {}
        for operation in self._operations:
            if operation.get("operation_type") != SESSION_ACCEPT_OPERATION:
                continue
            payload = operation.get("payload")
            if not isinstance(payload, dict):
                continue
            session_id = payload.get("session_id")
            if not isinstance(session_id, str) or not session_id.strip():
                continue
            previous = restored_session_accept_records.get(session_id)
            if previous is not None and previous != payload:
                raise ValueError("conflicting canonical Session acceptance records")
            restored_session_accept_records[session_id] = dict(payload)
        self._session_accept_records = restored_session_accept_records
        self._settlement_transition_hashes = {
            str(key): str(value) for key, value in (settlement_transition_hashes or {}).items()
        }
        from aidn_hypervisor.reward.development_pool import DevelopmentPoolAllocation

        self._development_pool_allocations = {}
        for raw_allocation in development_pool_allocations or []:
            allocation = DevelopmentPoolAllocation.model_validate(raw_allocation)
            if not allocation.verify_integrity():
                raise ValueError("development pool allocation hash is invalid")
            if allocation.allocation_id in self._development_pool_allocations:
                raise ValueError("development pool allocation IDs are not unique")
            self._development_pool_allocations[allocation.allocation_id] = allocation.model_dump(mode="json")
        from aidn_hypervisor.reward.development_carryover import DevelopmentPoolCarryoverRecord

        self._development_pool_carryovers = {}
        for raw_carryover in development_pool_carryovers or []:
            carryover = DevelopmentPoolCarryoverRecord.model_validate(raw_carryover)
            if not carryover.verify_integrity():
                raise ValueError("development pool carryover hash is invalid")
            if carryover.carryover_id in self._development_pool_carryovers:
                raise ValueError("development pool carryover IDs are not unique")
            source_operation = self._operation_by_id(carryover.operation_id)
            if source_operation is not None and source_operation.get("operation_type") != "DEVELOPMENT_POOL_CARRYOVER":
                raise ValueError("development pool carryover operation binding is invalid")
            self._development_pool_carryovers[carryover.carryover_id] = carryover.model_dump(mode="json")
        from aidn_hypervisor.reward.development_bounty import DevelopmentBountyState

        self._development_bounty_states = {}
        for raw_bounty_state in development_bounty_states or []:
            bounty_state = DevelopmentBountyState.model_validate(raw_bounty_state)
            if not bounty_state.verify_integrity():
                raise ValueError("development bounty state hash is invalid")
            bounty_id = bounty_state.bounty.bounty_id
            if bounty_id in self._development_bounty_states:
                raise ValueError("development bounty state IDs are not unique")
            self._development_bounty_states[bounty_id] = bounty_state.model_dump(mode="json")
        from aidn_hypervisor.reward.development_reserve import DevelopmentRewardReserve

        self._development_reward_reserves = {}
        for raw_reserve in development_reward_reserves or []:
            reserve = DevelopmentRewardReserve.model_validate(raw_reserve)
            if not reserve.verify_integrity():
                raise ValueError("development reward reserve hash is invalid")
            if reserve.reserve_id in self._development_reward_reserves:
                raise ValueError("development reward reserve IDs are not unique")
            self._development_reward_reserves[reserve.reserve_id] = reserve.model_dump(mode="json")
        reserved_by_allocation: dict[str, int] = {}
        for reserve in self._development_reward_reserves.values():
            allocation = self._development_pool_allocations.get(reserve["pool_allocation_id"])
            if allocation is None:
                raise ValueError("development reward reserve pool allocation is missing")
            calculation_operation = self._operation_by_id(reserve["calculation_operation_id"])
            if calculation_operation is None or calculation_operation.get("operation_type") != (
                "DEVELOPMENT_REWARD_CALCULATE"
            ):
                raise ValueError("development reward reserve calculation operation is missing")
            allocation_operation = self._operation_by_id(reserve["pool_allocation_operation_id"])
            if allocation_operation is None or allocation_operation.get("operation_type") != (
                "DEVELOPMENT_POOL_ALLOCATE"
            ):
                raise ValueError("development reward reserve pool allocation operation is missing")
            reserved_by_allocation[reserve["pool_allocation_id"]] = reserved_by_allocation.get(
                reserve["pool_allocation_id"], 0
            ) + int(reserve["reserved_q_atoms"])
        for allocation_id, reserved_total in reserved_by_allocation.items():
            if reserved_total > int(self._development_pool_allocations[allocation_id]["allocated_q_atoms"]):
                raise ValueError("development reward reserves exceed pool allocation")
        from aidn_hypervisor.reward.development_payment import DevelopmentRewardPaymentRecord

        self._development_reward_payment_records = {}
        for raw_payment in development_reward_payment_records or []:
            payment = DevelopmentRewardPaymentRecord.model_validate(raw_payment)
            if not payment.verify_integrity():
                raise ValueError("development reward payment record hash is invalid")
            if payment.payment_id in self._development_reward_payment_records:
                raise ValueError("development reward payment IDs are not unique")
            reserve = self._development_reward_reserves.get(payment.reserve_id)
            if reserve is None:
                raise ValueError("development reward payment reserve is missing")
            allocation = self._development_pool_allocations.get(payment.pool_allocation_id)
            if allocation is None:
                raise ValueError("development reward payment pool allocation is missing")
            if (
                reserve.get("pool_allocation_id") != payment.pool_allocation_id
                or reserve.get("pool_allocation_operation_id") != payment.pool_allocation_operation_id
                or reserve.get("calculation_operation_id") != payment.calculation_operation_id
                or reserve.get("reward_id") != payment.reward_id
            ):
                raise ValueError("development reward payment source binding is invalid")
            calculation_operation = self._operation_by_id(payment.calculation_operation_id)
            allocation_operation = self._operation_by_id(payment.pool_allocation_operation_id)
            reserve_operation = self._operation_by_id(payment.reserve_operation_id)
            if calculation_operation is None or calculation_operation.get("operation_type") != (
                "DEVELOPMENT_REWARD_CALCULATE"
            ):
                raise ValueError("development reward payment calculation operation is missing")
            if allocation_operation is None or allocation_operation.get("operation_type") != (
                "DEVELOPMENT_POOL_ALLOCATE"
            ):
                raise ValueError("development reward payment pool allocation operation is missing")
            if reserve_operation is None or reserve_operation.get("operation_type") != ("DEVELOPMENT_REWARD_RESERVE"):
                raise ValueError("development reward payment reserve operation is missing")
            self._development_reward_payment_records[payment.payment_id] = payment.model_dump(mode="json")
        paid_by_reserve: dict[str, int] = {}
        paid_by_allocation: dict[str, int] = {}
        for payment in self._development_reward_payment_records.values():
            paid_by_reserve[payment["reserve_id"]] = paid_by_reserve.get(payment["reserve_id"], 0) + int(
                payment["amount_q_atoms"]
            )
            paid_by_allocation[payment["pool_allocation_id"]] = paid_by_allocation.get(
                payment["pool_allocation_id"], 0
            ) + int(payment["amount_q_atoms"])
        for reserve_id, paid_total in paid_by_reserve.items():
            if paid_total > int(self._development_reward_reserves[reserve_id]["reserved_q_atoms"]):
                raise ValueError("development reward payments exceed reserve")
        reserved_by_allocation = {}
        for reserve in self._development_reward_reserves.values():
            allocation_id = reserve["pool_allocation_id"]
            reserved_by_allocation[allocation_id] = reserved_by_allocation.get(allocation_id, 0) + int(
                reserve["reserved_q_atoms"]
            )
        for allocation_id, reserved_total in reserved_by_allocation.items():
            paid_total = paid_by_allocation.get(allocation_id, 0)
            allocation_budget = int(self._development_pool_allocations[allocation_id]["allocated_q_atoms"])
            if reserved_total > allocation_budget or reserved_total - paid_total < 0:
                raise ValueError("development reward payment allocation balance is invalid")
        from aidn_hypervisor.reward.development_unclaimed import DevelopmentRewardUnclaimedRecord

        self._development_reward_unclaimed_records = {}
        for raw_unclaimed in development_reward_unclaimed_records or []:
            unclaimed = DevelopmentRewardUnclaimedRecord.model_validate(raw_unclaimed)
            if not unclaimed.verify_integrity():
                raise ValueError("development reward unclaimed record hash is invalid")
            if unclaimed.unclaimed_id in self._development_reward_unclaimed_records:
                raise ValueError("development reward unclaimed IDs are not unique")
            reserve = self._development_reward_reserves.get(unclaimed.reserve_id)
            allocation = self._development_pool_allocations.get(unclaimed.pool_allocation_id)
            if reserve is None or allocation is None:
                raise ValueError("development reward unclaimed source is missing")
            if (
                reserve.get("pool_allocation_id") != unclaimed.pool_allocation_id
                or reserve.get("pool_allocation_operation_id") != unclaimed.pool_allocation_operation_id
                or reserve.get("calculation_operation_id") != unclaimed.calculation_operation_id
                or reserve.get("reward_id") != unclaimed.reward_id
            ):
                raise ValueError("development reward unclaimed source binding is invalid")
            calculation_operation = self._operation_by_id(unclaimed.calculation_operation_id)
            allocation_operation = self._operation_by_id(unclaimed.pool_allocation_operation_id)
            reserve_operation = self._operation_by_id(unclaimed.reserve_operation_id)
            if calculation_operation is None or calculation_operation.get("operation_type") != (
                "DEVELOPMENT_REWARD_CALCULATE"
            ):
                raise ValueError("development reward unclaimed calculation operation is missing")
            if allocation_operation is None or allocation_operation.get("operation_type") != (
                "DEVELOPMENT_POOL_ALLOCATE"
            ):
                raise ValueError("development reward unclaimed pool allocation operation is missing")
            if reserve_operation is None or reserve_operation.get("operation_type") != ("DEVELOPMENT_REWARD_RESERVE"):
                raise ValueError("development reward unclaimed reserve operation is missing")
            self._development_reward_unclaimed_records[unclaimed.unclaimed_id] = unclaimed.model_dump(mode="json")
        unclaimed_by_reserve: dict[str, int] = {}
        for unclaimed in self._development_reward_unclaimed_records.values():
            unclaimed_by_reserve[unclaimed["reserve_id"]] = unclaimed_by_reserve.get(unclaimed["reserve_id"], 0) + int(
                unclaimed["amount_q_atoms"]
            )
        for reserve_id, unclaimed_total in unclaimed_by_reserve.items():
            paid_total = paid_by_reserve.get(reserve_id, 0)
            if paid_total + unclaimed_total > int(self._development_reward_reserves[reserve_id]["reserved_q_atoms"]):
                raise ValueError("development reward unclaimed amount exceeds reserve")
        from aidn_hypervisor.reward.development_claim import (
            DevelopmentRewardClaimRecord,
            DevelopmentRewardWalletBindingProof,
        )

        self._development_reward_claim_records = {}
        for raw_claim in development_reward_claim_records or []:
            claim = DevelopmentRewardClaimRecord.model_validate(raw_claim)
            if not claim.verify_integrity():
                raise ValueError("development reward claim record hash is invalid")
            if claim.claim_id in self._development_reward_claim_records:
                raise ValueError("development reward claim IDs are not unique")
            if any(
                item.get("unclaimed_id") == claim.unclaimed_id
                for item in self._development_reward_claim_records.values()
            ):
                raise ValueError("development reward unclaimed IDs are claimed more than once")
            unclaimed = self._development_reward_unclaimed_records.get(claim.unclaimed_id)
            reserve = self._development_reward_reserves.get(claim.reserve_id)
            allocation = self._development_pool_allocations.get(claim.pool_allocation_id)
            if unclaimed is None or reserve is None or allocation is None:
                raise ValueError("development reward claim source is missing")
            for field_name in (
                "reserve_id",
                "reserve_operation_id",
                "pool_allocation_id",
                "pool_allocation_operation_id",
                "calculation_operation_id",
                "calculation_commitment_id",
                "calculation_root",
                "reward_id",
                "contribution_id",
                "contributor_id",
                "role",
                "payment_hash",
                "payment_stage",
                "amount_q_atoms",
                "claim_expiration_epoch",
            ):
                if getattr(claim, field_name) != unclaimed[field_name]:
                    raise ValueError("development reward claim source binding is invalid")
            if claim.claim_epoch < int(unclaimed["distribution_epoch"]):
                raise ValueError("development reward claim epoch is invalid")
            if (
                claim.unclaimed_operation_id not in self._operation_ids
                or claim.claim_operation_id not in self._operation_ids
                or claim.wallet_address == ""
            ):
                raise ValueError("development reward claim source binding is invalid")
            unclaimed_operation = self._operation_by_id(claim.unclaimed_operation_id)
            claim_operation = self._operation_by_id(claim.claim_operation_id)
            if unclaimed_operation is None or unclaimed_operation.get("operation_type") != (
                "DEVELOPMENT_REWARD_MARK_UNCLAIMED"
            ):
                raise ValueError("development reward claim unclaimed operation is missing")
            if claim_operation is None or claim_operation.get("operation_type") != "DEVELOPMENT_REWARD_CLAIM":
                raise ValueError("development reward claim operation is missing")
            unclaimed_payload = unclaimed_operation.get("payload") or {}
            if (
                unclaimed_payload.get("payment_hash") != claim.payment_hash
                or unclaimed_payload.get("payment_stage") != claim.payment_stage
                or unclaimed_payload.get("reward_id") != claim.reward_id
                or unclaimed_payload.get("amount_q_atoms") != claim.amount_q_atoms
                or unclaimed_payload.get("contributor_id") != claim.contributor_id
            ):
                raise ValueError("development reward claim unclaimed operation binding is invalid")
            claim_payload = claim_operation.get("payload") or {}
            if (
                claim_payload.get("unclaimed_id") != claim.unclaimed_id
                or claim_payload.get("recipient_wallet") != claim.wallet_address
                or claim_payload.get("claim_epoch") != claim.claim_epoch
                or claim_payload.get("contribution_id") != claim.contribution_id
                or claim_payload.get("calculation_commitment_id") != claim.calculation_commitment_id
                or (claim_payload.get("wallet_binding") or {}).get("binding_id") != claim.wallet_binding_id
            ):
                raise ValueError("development reward claim operation binding is invalid")
            try:
                binding = DevelopmentRewardWalletBindingProof.model_validate(claim_payload.get("wallet_binding"))
                binding.verify_signature()
            except Exception as error:
                raise ValueError("development reward claim Wallet binding is invalid") from error
            if (
                binding.binding_id != claim.wallet_binding_id
                or binding.binding_hash != claim.wallet_binding_hash
                or binding.binding_version != claim.wallet_binding_version
                or binding.contributor_id != claim.contributor_id
                or binding.wallet_address != claim.wallet_address
            ):
                raise ValueError("development reward claim Wallet binding does not match")
            epoch_operation_id = claim_payload.get("source_epoch_transition_operation_id")
            epoch_operation = self._operation_by_id(epoch_operation_id) if isinstance(epoch_operation_id, str) else None
            if epoch_operation is None or epoch_operation.get("operation_type") != "EPOCH_TRANSITION":
                raise ValueError("development reward claim epoch transition is missing")
            if (epoch_operation.get("payload") or {}).get("opening_epoch") != claim.claim_epoch:
                raise ValueError("development reward claim epoch transition is invalid")
            self._development_reward_claim_records[claim.claim_id] = claim.model_dump(mode="json")
        claimed_by_reserve: dict[str, int] = {}
        claimed_by_allocation: dict[str, int] = {}
        for claim in self._development_reward_claim_records.values():
            claimed_by_reserve[claim["reserve_id"]] = claimed_by_reserve.get(claim["reserve_id"], 0) + int(
                claim["amount_q_atoms"]
            )
            claimed_by_allocation[claim["pool_allocation_id"]] = claimed_by_allocation.get(
                claim["pool_allocation_id"], 0
            ) + int(claim["amount_q_atoms"])
        for reserve_id, claimed_total in claimed_by_reserve.items():
            paid_total = paid_by_reserve.get(reserve_id, 0)
            unclaimed_total = unclaimed_by_reserve.get(reserve_id, 0)
            if paid_total + claimed_total > int(self._development_reward_reserves[reserve_id]["reserved_q_atoms"]):
                raise ValueError("development reward claims exceed reserve")
            active_unclaimed_total = unclaimed_total - claimed_total
            if active_unclaimed_total < 0:
                raise ValueError("development reward claimed amount exceeds unclaimed amount")
            if paid_total + claimed_total + active_unclaimed_total > int(
                self._development_reward_reserves[reserve_id]["reserved_q_atoms"]
            ):
                raise ValueError("development reward active claims exceed reserve")
        for allocation_id, claimed_total in claimed_by_allocation.items():
            paid_total = paid_by_allocation.get(allocation_id, 0)
            allocation_budget = int(self._development_pool_allocations[allocation_id]["allocated_q_atoms"])
            reserved_total = reserved_by_allocation.get(allocation_id, 0)
            if reserved_total <= 0 or reserved_total > allocation_budget or claimed_total + paid_total > reserved_total:
                raise ValueError("development reward claim allocation balance is invalid")
        from aidn_hypervisor.reward.development_expiry import DevelopmentRewardExpiryRecord

        self._development_reward_expiry_records = {}
        for raw_expiry in development_reward_expiry_records or []:
            expiry = DevelopmentRewardExpiryRecord.model_validate(raw_expiry)
            if not expiry.verify_integrity():
                raise ValueError("development reward expiry record hash is invalid")
            if expiry.expiry_id in self._development_reward_expiry_records:
                raise ValueError("development reward expiry IDs are not unique")
            if any(
                item.get("unclaimed_id") == expiry.unclaimed_id
                for item in self._development_reward_expiry_records.values()
            ):
                raise ValueError("development reward expiry unclaimed IDs are not unique")
            if any(
                item.get("unclaimed_id") == expiry.unclaimed_id
                for item in self._development_reward_claim_records.values()
            ):
                raise ValueError("development reward expiry conflicts with claim")
            unclaimed = self._development_reward_unclaimed_records.get(expiry.unclaimed_id)
            reserve = self._development_reward_reserves.get(expiry.reserve_id)
            allocation = self._development_pool_allocations.get(expiry.pool_allocation_id)
            if unclaimed is None or reserve is None or allocation is None:
                raise ValueError("development reward expiry source is missing")
            for field_name in (
                "reserve_id",
                "reserve_operation_id",
                "pool_allocation_id",
                "pool_allocation_operation_id",
                "calculation_operation_id",
                "calculation_commitment_id",
                "calculation_root",
                "reward_id",
                "contribution_id",
                "contributor_id",
                "role",
                "payment_hash",
                "payment_stage",
                "amount_q_atoms",
                "claim_expiration_epoch",
            ):
                if getattr(expiry, field_name) != unclaimed[field_name]:
                    raise ValueError("development reward expiry source binding is invalid")
            if expiry.expiry_epoch <= expiry.claim_expiration_epoch:
                raise ValueError("development reward expiry epoch is invalid")
            expiry_operation = self._operation_by_id(expiry.expiry_operation_id)
            unclaimed_operation = self._operation_by_id(expiry.unclaimed_operation_id)
            epoch_operation = self._operation_by_id(expiry.source_epoch_transition_operation_id)
            if expiry_operation is None or expiry_operation.get("operation_type") != (
                "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED"
            ):
                raise ValueError("development reward expiry operation is missing")
            if unclaimed_operation is None or unclaimed_operation.get("operation_type") != (
                "DEVELOPMENT_REWARD_MARK_UNCLAIMED"
            ):
                raise ValueError("development reward expiry unclaimed operation is missing")
            if epoch_operation is None or epoch_operation.get("operation_type") != "EPOCH_TRANSITION":
                raise ValueError("development reward expiry epoch transition is missing")
            if (epoch_operation.get("payload") or {}).get("opening_epoch") != expiry.expiry_epoch:
                raise ValueError("development reward expiry epoch transition is invalid")
            expiry_payload = expiry_operation.get("payload") or {}
            if (
                expiry_payload.get("expiry_epoch") != expiry.expiry_epoch
                or expiry_payload.get("unclaimed_id") != expiry.unclaimed_id
                or expiry_payload.get("amount_q_atoms") != expiry.amount_q_atoms
                or expiry_payload.get("return_destination") != expiry.return_destination
                or expiry_payload.get("source_epoch_transition_operation_id")
                != expiry.source_epoch_transition_operation_id
            ):
                raise ValueError("development reward expiry operation binding is invalid")
            self._development_reward_expiry_records[expiry.expiry_id] = expiry.model_dump(mode="json")
        returned_by_reserve: dict[str, int] = {}
        returned_by_allocation: dict[str, int] = {}
        for expiry in self._development_reward_expiry_records.values():
            returned_by_reserve[expiry["reserve_id"]] = returned_by_reserve.get(expiry["reserve_id"], 0) + int(
                expiry["amount_q_atoms"]
            )
            returned_by_allocation[expiry["pool_allocation_id"]] = returned_by_allocation.get(
                expiry["pool_allocation_id"], 0
            ) + int(expiry["amount_q_atoms"])
        for reserve_id, returned_total in returned_by_reserve.items():
            reserve = self._development_reward_reserves[reserve_id]
            paid_total = paid_by_reserve.get(reserve_id, 0)
            claimed_total = claimed_by_reserve.get(reserve_id, 0)
            if paid_total + claimed_total + returned_total > int(reserve["reserved_q_atoms"]):
                raise ValueError("development reward expiry exceeds reserve")
        for allocation_id, returned_total in returned_by_allocation.items():
            allocation_budget = int(self._development_pool_allocations[allocation_id]["allocated_q_atoms"])
            reserved_total = reserved_by_allocation.get(allocation_id, 0)
            paid_total = paid_by_allocation.get(allocation_id, 0)
            claimed_total = claimed_by_allocation.get(allocation_id, 0)
            if reserved_total - returned_total < 0 or reserved_total > allocation_budget:
                raise ValueError("development reward expiry allocation balance is invalid")
            if paid_total + claimed_total + returned_total > reserved_total:
                raise ValueError("development reward expiry allocation consumption is invalid")
        from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
        from aidn_hypervisor.reward.development_finalized_commitments import (
            DevelopmentRewardFinalizedCommitment,
        )

        self._development_reward_finalized_commitments = {}
        for raw_commitment in development_reward_finalized_commitments or []:
            finalized_commitment = DevelopmentRewardFinalizedCommitment.model_validate(raw_commitment)
            if not finalized_commitment.verify_integrity():
                raise ValueError("development reward finalized commitment hash is invalid")
            if finalized_commitment.finalized_commitment_id in self._development_reward_finalized_commitments:
                raise ValueError("development reward finalized commitment IDs are not unique")
            operation = self._operation_by_id(finalized_commitment.finalized_operation_id)
            if operation is None or operation.get("operation_type") != ("DEVELOPMENT_REWARD_FINALIZE_COMMITMENT"):
                raise ValueError("development reward finalized commitment operation is missing")
            try:
                validated_commitment = self.validate_consensus_development_reward_finalize_commitment(
                    LedgerOperationEnvelope.model_validate(operation),
                    finalized_operation_ids=self._operation_ids,
                )["finalized_record"]
            except ValueError as error:
                raise ValueError("development reward finalized commitment is invalid") from error
            if validated_commitment.model_dump(mode="json") != finalized_commitment.model_dump(mode="json"):
                raise ValueError("development reward finalized commitment binding is invalid")
            self._development_reward_finalized_commitments[finalized_commitment.finalized_commitment_id] = (
                finalized_commitment.model_dump(mode="json")
            )
        from aidn_hypervisor.reward.development_adjustments import DevelopmentRewardStateSnapshot
        from aidn_hypervisor.reward.development_cancellation import (
            DevelopmentRewardCancellationRecord,
            validate_cancellation_history,
        )
        from aidn_hypervisor.reward.development_correction import (
            DevelopmentRewardCorrectionRecord,
            validate_reward_correction_history,
        )

        self._development_reward_adjustment_snapshots = {}
        for raw_snapshot in development_reward_adjustment_snapshots or []:
            snapshot = DevelopmentRewardStateSnapshot.model_validate(raw_snapshot)
            if not snapshot.verify_integrity():
                raise ValueError("development reward adjustment snapshot hash is invalid")
            if snapshot.snapshot_id in self._development_reward_adjustment_snapshots:
                raise ValueError("development reward adjustment snapshot IDs are not unique")
            self._development_reward_adjustment_snapshots[snapshot.snapshot_id] = snapshot.model_dump(mode="json")
        self._development_reward_cancellations = {}
        for raw_cancellation in development_reward_cancellations or []:
            cancellation = DevelopmentRewardCancellationRecord.model_validate(raw_cancellation)
            snapshot = self._development_reward_adjustment_snapshots.get(cancellation.source_snapshot_id)
            if snapshot is None:
                raise ValueError("development reward cancellation snapshot is missing")
            source = DevelopmentRewardStateSnapshot.model_validate(snapshot)
            history = [
                DevelopmentRewardCancellationRecord.model_validate(item)
                for item in self._development_reward_cancellations.values()
                if item.get("source_snapshot_id") == source.snapshot_id
            ]
            validate_cancellation_history(source, [*history, cancellation])
            if cancellation.cancellation_id in self._development_reward_cancellations:
                raise ValueError("development reward cancellation IDs are not unique")
            self._development_reward_cancellations[cancellation.cancellation_id] = cancellation.model_dump(mode="json")
        self._development_reward_corrections = {}
        for raw_correction in development_reward_corrections or []:
            correction = DevelopmentRewardCorrectionRecord.model_validate(raw_correction)
            snapshot = self._development_reward_adjustment_snapshots.get(correction.source_snapshot_id)
            if snapshot is None:
                raise ValueError("development reward correction snapshot is missing")
            source = DevelopmentRewardStateSnapshot.model_validate(snapshot)
            history = [
                DevelopmentRewardCorrectionRecord.model_validate(item)
                for item in self._development_reward_corrections.values()
                if item.get("source_snapshot_id") == source.snapshot_id
            ]
            validate_reward_correction_history(source, [*history, correction])
            if correction.correction_id in self._development_reward_corrections:
                raise ValueError("development reward correction IDs are not unique")
            self._development_reward_corrections[correction.correction_id] = correction.model_dump(mode="json")
        self._settlement_proposals = {
            proposal.settlement_id: proposal
            for proposal in (SessionSettlementProposal.model_validate(item) for item in (settlement_proposals or []))
        }
        self._settlement_acceptances = {
            acceptance.settlement_id: acceptance
            for acceptance in (
                SessionSettlementAcceptance.model_validate(item) for item in (settlement_acceptances or [])
            )
        }
        self._session_checkpoints = {
            checkpoint.checkpoint_id: checkpoint
            for checkpoint in (SessionUsageCheckpoint.model_validate(item) for item in (session_checkpoints or []))
        }
        self._settlement_disputes = {
            dispute.settlement_id: dispute
            for dispute in (SettlementDispute.model_validate(item) for item in (settlement_disputes or []))
        }
        self._settlement_corrections = {
            correction.correction_id: correction
            for correction in (SettlementCorrection.model_validate(item) for item in (settlement_corrections or []))
        }
        self.restore_consensus_state(consensus_state)
        self._next_sequence_id = max((int(item["sequence_id"]) for item in self._operations), default=0) + 1
