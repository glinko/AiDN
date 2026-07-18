import hashlib
import json
from datetime import datetime, timezone

from aidn_hypervisor.ledger.models import LedgerOperationRecord, LedgerOperationResult
from aidn_hypervisor.settlement.models import (
    SessionFundingAccount,
    SettlementEvaluation,
)


def _canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash_dict(value: dict) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


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
        self._wallet_next_sequences: dict[str, int] = {}
        self._wallet_q_atom_balances: dict[str, int] = {}
        self._session_funding_accounts: dict[str, SessionFundingAccount] = {}
        self._settlement_transition_hashes: dict[str, str] = {}
        self._next_sequence_id = 1

    def wallet_q_atom_balance(self, wallet_id: str) -> int:
        return int(self._wallet_q_atom_balances.get(wallet_id, 0))

    def credit_wallet_q_atoms(self, *, wallet_id: str, amount_q_atoms: int) -> int:
        if amount_q_atoms < 0:
            raise ValueError("wallet credit must be non-negative")
        balance = self.wallet_q_atom_balance(wallet_id) + int(amount_q_atoms)
        self._wallet_q_atom_balances[wallet_id] = balance
        return balance

    def get_session_funding_account(self, session_id: str) -> SessionFundingAccount:
        return self._session_funding_accounts[session_id]

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
            payload={
                "session_id": funding.session_id,
                "funding_class": funding.funding_class,
                "funding_state_hash": locked.funding_state_hash,
                "total_locked_amount_q_atoms": funding.total_locked_amount_q_atoms,
                "endpoint_payment_reserve_q_atoms": funding.endpoint_payment_reserve_q_atoms,
                "network_fee_reserve_q_atoms": funding.network_fee_reserve_q_atoms,
                "endpoint_payment_beneficiary": funding.endpoint_payment_beneficiary,
                "consumer_refund_beneficiary": funding.consumer_refund_beneficiary,
            },
            created_at=created_at,
            emitted_events=["SessionEscrowLocked"],
        )
        if funding.funding_class == "ESCROW_PREPAID":
            self._wallet_q_atom_balances[funding.consumer_funding_account] = (
                self.wallet_q_atom_balance(funding.consumer_funding_account)
                - funding.total_locked_amount_q_atoms
            )
        self._session_funding_accounts[funding.session_id] = locked
        return locked

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
            transition.endpoint_payment_beneficiary
            != funding.endpoint_payment_beneficiary
            or transition.consumer_refund_beneficiary
            != funding.consumer_refund_beneficiary
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
                "funding_state": (
                    "DISPUTE_RESERVED" if proposal.dispute_reserve_q_atoms else "RELEASED"
                ),
            },
        )
        self._session_funding_accounts[transition.session_id] = next_funding
        self._settlement_transition_hashes[transition.settlement_id] = str(
            transition.transition_hash
        )
        return next_funding

    def list_operations(self, *, limit: int | None = None) -> list[dict]:
        events = list(self._operations)
        if limit is None or limit >= len(events):
            return events
        return events[-limit:]

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
        now = created_at or datetime.now(timezone.utc).isoformat()
        sender_sequence: int | None = None
        next_wallet_sequence: int | None = None
        if origin_type == "wallet":
            if sender_wallet is None:
                raise ValueError("wallet operations require sender_wallet")
            next_wallet_sequence = self.wallet_next_sequence(sender_wallet)
            sender_sequence = (
                int(expected_sequence)
                if expected_sequence is not None
                else next_wallet_sequence
            )
            if sender_sequence != next_wallet_sequence:
                raise ValueError(
                    f"invalid wallet sequence for {sender_wallet}: expected {next_wallet_sequence}, got {sender_sequence}"
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
        if operation_id in self._operation_ids:
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
            origin_type=origin_type,
            initiator_id=initiator_id,
            sender_wallet=sender_wallet,
            sender_sequence=sender_sequence,
            fee_class=fee_class,
            fee_payer=fee_payer,
            created_at=now,
            expires_at=expires_at,
            target_epoch=target_epoch,
            payload=unsigned["payload"],
            evidence_references=unsigned["evidence_references"],
            signatures=unsigned["signatures"],
            result=result,
            wallet_next_sequence=wallet_next_sequence_value,
        ).model_dump(mode="json")
        self._operations.append(record)
        self._operation_ids.add(operation_id)
        self._next_sequence_id += 1
        if sender_wallet is not None and wallet_next_sequence_value is not None:
            self._wallet_next_sequences[sender_wallet] = wallet_next_sequence_value
        return record

    def snapshot_operations(self) -> list[dict]:
        return list(self._operations)

    def snapshot_wallet_sequences(self) -> dict[str, int]:
        return dict(self._wallet_next_sequences)

    def snapshot_settlement_state(self) -> dict:
        return {
            "wallet_q_atom_balances": dict(self._wallet_q_atom_balances),
            "session_funding_accounts": [
                account.model_dump(mode="json")
                for account in self._session_funding_accounts.values()
            ],
            "settlement_transition_hashes": dict(self._settlement_transition_hashes),
        }

    def restore(
        self,
        *,
        operations: list[dict],
        wallet_sequences: dict[str, int],
        wallet_q_atom_balances: dict[str, int] | None = None,
        session_funding_accounts: list[dict] | None = None,
        settlement_transition_hashes: dict[str, str] | None = None,
    ) -> None:
        self._operations = [LedgerOperationRecord(**item).model_dump(mode="json") for item in operations]
        self._operation_ids = {item["operation_id"] for item in self._operations}
        self._wallet_next_sequences = {str(key): int(value) for key, value in wallet_sequences.items()}
        self._wallet_q_atom_balances = {
            str(key): int(value) for key, value in (wallet_q_atom_balances or {}).items()
        }
        self._session_funding_accounts = {
            account.session_id: account
            for account in (
                SessionFundingAccount.model_validate(item)
                for item in (session_funding_accounts or [])
            )
        }
        self._settlement_transition_hashes = {
            str(key): str(value)
            for key, value in (settlement_transition_hashes or {}).items()
        }
        self._next_sequence_id = (
            max((int(item["sequence_id"]) for item in self._operations), default=0) + 1
        )
