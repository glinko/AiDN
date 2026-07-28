from __future__ import annotations


class SettlementApplicationService:
    """Ledger, funding, and MVP settlement application facade."""

    def __init__(self, host) -> None:
        self._host = host

    def list_ledger_operations(self, *, limit: int | None = None) -> list[dict]:
        return [
            {
                **operation,
                "finality": self._host.ledger_operation_finality(
                    operation["operation_id"]
                ),
            }
            for operation in self._host._ledger_operation_service.list_operations(
                limit=limit
            )
        ]

    def export_ledger_operations(
        self,
        *,
        after_operation_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        payload = self._host._ledger_operation_service.export_operations(
            after_operation_id=after_operation_id,
            after_sequence=after_sequence,
            limit=limit,
        )
        payload["items"] = [
            {
                **operation,
                "finality": self._host.ledger_operation_finality(
                    operation["operation_id"]
                ),
            }
            for operation in payload["items"]
        ]
        return payload

    def wallet_next_operation_sequence(self, wallet_id: str) -> int:
        return self._host._ledger_operation_service.wallet_next_sequence(wallet_id)

    def wallet_q_atom_balance(self, wallet_id: str) -> int:
        return self._host._ledger_operation_service.wallet_q_atom_balance(wallet_id)

    def get_session_funding_account(self, session_id: str):
        return self._host._ledger_operation_service.get_session_funding_account(
            session_id
        )

    def credit_wallet_q_atoms(self, *, wallet_id: str, amount_q_atoms: int) -> int:
        balance = self._host._ledger_operation_service.credit_wallet_q_atoms(
            wallet_id=wallet_id,
            amount_q_atoms=amount_q_atoms,
        )
        self._host._persist_state()
        return balance

    def lock_session_funding(self, funding, *, created_at: str | None = None):
        locked = self._host._ledger_operation_service.lock_session_funding(
            funding,
            created_at=created_at,
        )
        self._host._persist_state()
        return locked

    def apply_settlement_evaluation(self, evaluation, *, created_at: str | None = None):
        funding = self._host._ledger_operation_service.apply_settlement_evaluation(
            evaluation,
            created_at=created_at,
        )
        self._host._persist_state()
        return funding

    def propose_settlement(self, evaluation, *, created_at: str | None = None):
        proposal = self._host._ledger_operation_service.propose_settlement(
            evaluation,
            created_at=created_at,
        )
        self._host._persist_state()
        return proposal

    def accept_settlement(self, acceptance, *, created_at: str | None = None):
        accepted = self._host._ledger_operation_service.accept_settlement(
            acceptance,
            created_at=created_at,
        )
        self._host._persist_state()
        return accepted

    def finalize_accepted_settlement(
        self,
        evaluation,
        *,
        created_at: str | None = None,
    ):
        funding = self._host._ledger_operation_service.finalize_accepted_settlement(
            evaluation,
            created_at=created_at,
        )
        self._host._persist_state()
        return funding

    def force_finalize_fixed_price_settlement(self, evaluation, **kwargs):
        funding = self._host._ledger_operation_service.force_finalize_fixed_price_settlement(
            evaluation,
            **kwargs,
        )
        self._host._persist_state()
        return funding

    def open_mvp_fixed_price_session(self, **kwargs):
        return self._host._mvp_session_economics_service.open_mvp_fixed_price_session(
            **kwargs
        )

    def build_mvp_fixed_price_settlement_evaluation(self, **kwargs):
        return self._host._mvp_session_economics_service.build_mvp_fixed_price_settlement_evaluation(
            **kwargs
        )

    def build_mvp_endpoint_unavailable_refund_evaluation(self, **kwargs):
        return self._host._mvp_session_economics_service.build_mvp_endpoint_unavailable_refund_evaluation(
            **kwargs
        )

    def finalize_mvp_fixed_price_session(self, **kwargs):
        return self._host._mvp_session_economics_service.finalize_mvp_fixed_price_session(
            **kwargs
        )

    def force_finalize_mvp_fixed_price_session(self, **kwargs):
        return self._host._mvp_session_economics_service.force_finalize_mvp_fixed_price_session(
            **kwargs
        )

    def record_ledger_operation(
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
        operation = self._host._ledger_operation_service.record_operation(
            operation_type=operation_type,
            origin_type=origin_type,
            fee_class=fee_class,
            initiator_id=initiator_id,
            sender_wallet=sender_wallet,
            fee_payer=fee_payer,
            payload=payload,
            created_at=created_at,
            expires_at=expires_at,
            target_epoch=target_epoch,
            evidence_references=evidence_references,
            signatures=signatures,
            emitted_events=emitted_events,
            expected_sequence=expected_sequence,
            operation_version=operation_version,
        )
        self._host._persist_state()
        return operation
