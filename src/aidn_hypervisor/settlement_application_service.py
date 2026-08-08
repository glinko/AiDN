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
        consensus = getattr(self._host, "consensus_service", None)
        if consensus is not None and consensus.is_validator:
            raise ValueError(
                "validator cooperative Settlement requires a canonical consensus transaction"
            )
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

    def submit_consensus_cooperative_settlement(
        self,
        evaluation,
        acceptance,
        *,
        created_at: str | None = None,
        signatures: list[str] | None = None,
    ) -> dict:
        """Submit cooperative Settlement through canonical consensus only."""
        from aidn_hypervisor.consensus.settlement_orchestration import (
            ConsensusSettlementOperationOrchestrator,
        )

        consensus = getattr(self._host, "consensus_service", None)
        if consensus is None or not consensus.is_enabled:
            raise ValueError("consensus service is not enabled")
        result = ConsensusSettlementOperationOrchestrator(
            consensus,
            self._host._ledger_operation_service,
            finality_source=self._host.consensus_finality_source,
            pending_envelope_store=self._host,
        ).submit_cooperative_settlement(
            evaluation=evaluation,
            acceptance=acceptance,
            created_at=created_at,
            signatures=signatures,
        )
        if result["status"] == "failed":
            blocked_on = result.get("blocked_on") or "operation"
            details = result.get("submissions", {}).get(blocked_on, {}).get("error")
            raise ValueError(
                f"canonical cooperative Settlement failed at {blocked_on}"
                + (f": {details}" if details else "")
            )
        self._host._persist_state()
        try:
            funding = self._host.get_session_funding_account(
                evaluation.proposal.session_id
            )
        except KeyError:
            funding = None
        return {
            "status": "FINALIZED"
            if result["status"] == "finalized"
            else "CONSENSUS_PENDING",
            "evaluation": evaluation,
            "proposal": evaluation.proposal,
            "acceptance": acceptance,
            "funding": funding,
            "consensus": result,
            "session_result": None,
        }

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

    def prepare_force_settlement_operation(self, evaluation, **kwargs):
        """Prepare a local Forced Settlement without changing canonical state."""
        consensus = getattr(self._host, "consensus_service", None)
        stage_only = bool(consensus is not None and consensus.is_validator)
        if stage_only:
            existing = self._host.find_pending_consensus_operation(
                operation_type="SESSION_FORCE_SETTLE",
                payload_fields={"settlement_id": evaluation.proposal.settlement_id},
            )
            if existing is not None:
                payload = existing.get("payload")
                expected = {
                    "session_id": evaluation.proposal.session_id,
                    "failure_class": kwargs.get("failure_class"),
                    "settlement_input_root": evaluation.proposal.settlement_input_root,
                    "requested_payment_q_atoms": (
                        evaluation.proposal.requested_endpoint_payment_q_atoms
                    ),
                    "requested_refund_q_atoms": (
                        evaluation.proposal.consumer_payment_refund_q_atoms
                        + evaluation.proposal.consumer_fee_refund_q_atoms
                    ),
                }
                if not isinstance(payload, dict) or any(
                    payload.get(key) != value for key, value in expected.items()
                ):
                    raise ValueError("conflicting pending Forced Settlement projection")
                return {
                    "funding": self._host.get_session_funding_account(
                        evaluation.proposal.session_id
                    ),
                    "operation": existing,
                }
        kwargs["stage_only"] = stage_only
        prepared = self._host._ledger_operation_service.prepare_force_settlement_operation(
            evaluation,
            **kwargs,
        )
        if stage_only:
            prepared["operation"] = self._host.stage_consensus_operation(
                prepared["operation"]
            )
        else:
            self._host._persist_state()
        return prepared

    def apply_prepared_force_settlement(
        self,
        evaluation,
        *,
        force_operation_id: str,
        created_at: str | None = None,
    ):
        funding = self._host._ledger_operation_service.apply_prepared_force_settlement(
            evaluation,
            force_operation_id=force_operation_id,
            created_at=created_at,
        )
        self._host._persist_state()
        return funding

    def commit_session_failure_evidence(self, **kwargs):
        consensus = getattr(self._host, "consensus_service", None)
        stage_only = bool(consensus is not None and consensus.is_validator)
        existing = None
        if stage_only:
            existing = self._host.find_pending_consensus_operation(
                operation_type="SESSION_FAILURE_EVIDENCE",
                payload_fields={
                    "session_id": kwargs["session_id"],
                    "failure_class": kwargs["failure_class"],
                    "failure_evidence_root": kwargs["failure_evidence_root"],
                },
            )
        if existing is not None:
            payload = existing.get("payload")
            if not isinstance(payload, dict) or payload.get("details") != kwargs.get("details"):
                raise ValueError("conflicting pending Session failure evidence")
            return existing
        operation = self._host._ledger_operation_service.commit_session_failure_evidence(
            **kwargs,
            stage_only=stage_only,
        )
        if stage_only:
            operation = self._host.stage_consensus_operation(operation)
        else:
            self._host._persist_state()
        return operation

    def submit_consensus_session_failure_chain(self, **kwargs):
        """Submit local Session failure records through canonical consensus.

        The local operation IDs are lookup keys only.  The orchestration layer
        projects fresh network envelopes and gates every dependent submission
        on verified finality of its predecessor.
        """
        from aidn_hypervisor.consensus.session_orchestration import (
            ConsensusSessionOperationOrchestrator,
        )

        consensus = self._host.consensus_service
        if consensus is None:
            raise ValueError("consensus service is not configured")
        operation_keys = {
            "local_lock_operation": "local_lock_operation_id",
            "local_failure_operation": "local_failure_operation_id",
            "local_force_operation": "local_force_operation_id",
        }
        operations = {}
        for argument_name, key_name in operation_keys.items():
            operation_id = kwargs.pop(key_name, None)
            if not isinstance(operation_id, str) or not operation_id.strip():
                raise ValueError(f"{key_name} is required")
            operation = self._host.get_local_consensus_operation(operation_id)
            if operation is None:
                raise ValueError(f"local operation was not found: {operation_id}")
            operations[argument_name] = operation
        lock_payload = operations["local_lock_operation"].get("payload")
        if not isinstance(lock_payload, dict):
            raise ValueError("local escrow lock payload is invalid")
        from aidn_hypervisor.settlement.models import SessionFundingAccount

        try:
            funding = SessionFundingAccount.model_validate(lock_payload)
        except ValueError as error:
            raise ValueError(f"local escrow lock funding is invalid: {error}") from error
        supplied_funding = kwargs.pop("funding", None)
        if supplied_funding is not None:
            supplied_payload = (
                supplied_funding.model_dump(mode="json")
                if hasattr(supplied_funding, "model_dump")
                else supplied_funding
            )
            if supplied_payload != funding.model_dump(mode="json"):
                raise ValueError("consensus escrow funding does not match local lock")
        canonical_lock_envelope = None
        session_service = getattr(self._host, "session_service", None)
        if session_service is not None:
            try:
                session = session_service.store.get_session(funding.session_id)
            except (KeyError, AttributeError):
                session = None
            if session is not None:
                submission = session.canonical_funding_submission
                if isinstance(submission, dict) and submission:
                    envelope_payload = submission.get("envelope")
                    if isinstance(envelope_payload, dict):
                        from aidn_hypervisor.consensus.models import LedgerOperationEnvelope

                        candidate = LedgerOperationEnvelope.model_validate(envelope_payload)
                        if (
                            candidate.operation_type == "SESSION_ESCROW_LOCK"
                            and candidate.operation_id == session.canonical_funding_operation_id
                        ):
                            canonical_lock_envelope = candidate
        return ConsensusSessionOperationOrchestrator(
            consensus,
            finality_source=self._host.consensus_finality_source,
        ).submit_failure_chain(
            **operations,
            funding=funding,
            canonical_lock_envelope=canonical_lock_envelope,
            **kwargs,
        )

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
