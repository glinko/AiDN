from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from aidn_hypervisor.session_failure.models import FailureClass
from aidn_hypervisor.settlement.models import (
    AtomicSettlementTransition,
    RequestSettlementInput,
    SessionFundingAccount,
    SessionSettlementAcceptance,
    SessionSettlementProposal,
    SettlementAccountingTerms,
    SettlementChargeComponent,
    TerminalChargePolicy,
)
from aidn_hypervisor.settlement.service import SettlementEngine

Q_ATOMS_PER_Q = 1_000_000


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _maximum_request_charge_q_atoms(
    accounting_contract: dict | None,
    *,
    fixed_price_q_atoms: int,
) -> int:
    """Return the accepted Accounting Contract request ceiling in q_atoms."""
    if accounting_contract is None:
        return fixed_price_q_atoms
    raw_value = accounting_contract.get("maximum_request_charge")
    if raw_value is None:
        return fixed_price_q_atoms
    try:
        q_value = Decimal(str(raw_value)) * Q_ATOMS_PER_Q
    except (InvalidOperation, ValueError) as error:
        raise ValueError(
            "Accounting Contract maximum request charge is invalid"
        ) from error
    if not q_value.is_finite() or q_value != q_value.to_integral_value():
        raise ValueError(
            "Accounting Contract maximum request charge must map to whole q_atoms"
        )
    maximum = int(q_value)
    if maximum == 0:
        # Older endpoint profiles used zero to mean that no explicit request
        # ceiling was published. A fixed-price Session still needs its price
        # as the effective ceiling.
        return fixed_price_q_atoms
    if maximum < fixed_price_q_atoms:
        raise ValueError(
            "Accounting Contract maximum request charge cannot be below fixed price"
        )
    return maximum


class MvpSessionEconomicsService:
    """Economic orchestration for MVP fixed-price Sessions."""

    def __init__(self, host) -> None:
        self._host = host

    def open_mvp_fixed_price_session(
        self,
        *,
        session_service,
        endpoint,
        client_wallet: str,
        deposit_q_atoms: int,
        fixed_price_q_atoms: int,
        network_fee_reserve_q_atoms: int = 0,
        accounting_contract: dict | None = None,
        consumer_authorization_public_key: str | None = None,
        consumer_authorization: dict | None = None,
        require_wallet_authorization: bool = False,
        session_id: str | None = None,
        consensus_sender_sequence: int | None = None,
        consensus_lock_signatures: list[str] | None = None,
    ):
        consensus_service = getattr(self._host, "consensus_service", None)
        validator_consensus = bool(
            consensus_service is not None
            and getattr(consensus_service, "is_validator", False)
        )
        resumable_session = None
        if validator_consensus and session_id is not None:
            try:
                candidate = session_service.store.get_session(session_id)
            except KeyError:
                candidate = None
            if (
                candidate is not None
                and candidate.endpoint_id == endpoint.endpoint_id
                and candidate.client_wallet == client_wallet
                and candidate.economic_profile == "MVP-0001"
            ):
                resumable_session = candidate
        if deposit_q_atoms <= 0:
            raise ValueError("MVP Session deposit must be positive")
        if network_fee_reserve_q_atoms < 0:
            raise ValueError("Network Fee Reserve cannot be negative")
        payment_reserve = deposit_q_atoms - network_fee_reserve_q_atoms
        if payment_reserve < fixed_price_q_atoms:
            raise ValueError("MVP Session deposit cannot cover fixed price")
        maximum_request_charge_q_atoms = _maximum_request_charge_q_atoms(
            accounting_contract,
            fixed_price_q_atoms=fixed_price_q_atoms,
        )
        if resumable_session is None and payment_reserve < maximum_request_charge_q_atoms:
            raise ValueError(
                "MVP Session deposit cannot cover Accounting Contract maximum request charge"
            )
        if (
            resumable_session is None
            and self._host.wallet_q_atom_balance(client_wallet) < deposit_q_atoms
        ):
            raise ValueError("insufficient q_atoms for MVP Session escrow")
        if (
            require_wallet_authorization
            and consumer_authorization is None
            and resumable_session is None
        ):
            raise ValueError("Public MVP Session requires Consumer wallet authorization")
        if (
            require_wallet_authorization
            and self._host.resolve_wallet_identity(endpoint.owner_wallet) is None
        ):
            raise ValueError(
                "Public MVP Endpoint Payment Beneficiary identity is not registered"
            )
        if consumer_authorization is not None:
            from aidn_hypervisor.wallet_identity import (
                verify_session_open_authorization,
            )

            identity = self._host.resolve_wallet_identity(client_wallet)
            if identity is None:
                raise ValueError("Consumer wallet identity is not registered")
            nonce = str(consumer_authorization.get("nonce") or "")
            if not nonce or nonce in self._host._consumed_wallet_authorization_nonces:
                raise ValueError("Session-open authorization nonce was already consumed")
            verify_session_open_authorization(
                public_key=identity["public_key"],
                signature=str(consumer_authorization.get("signature") or ""),
                wallet_id=client_wallet,
                endpoint_id=endpoint.endpoint_id,
                endpoint_configuration_hash=endpoint.configuration_hash,
                deposit_q_atoms=deposit_q_atoms,
                fixed_price_q_atoms=fixed_price_q_atoms,
                network_fee_reserve_q_atoms=network_fee_reserve_q_atoms,
                nonce=nonce,
                expires_at=str(consumer_authorization.get("expires_at") or ""),
            )
            consumer_authorization_public_key = identity["public_key"]

        if validator_consensus:
            return self._open_validator_consensus_session(
                session_service=session_service,
                endpoint=endpoint,
                client_wallet=client_wallet,
                deposit_q_atoms=deposit_q_atoms,
                fixed_price_q_atoms=fixed_price_q_atoms,
                network_fee_reserve_q_atoms=network_fee_reserve_q_atoms,
                payment_reserve=payment_reserve,
                accounting_contract=accounting_contract,
                consumer_authorization_public_key=consumer_authorization_public_key,
                consumer_authorization=consumer_authorization,
                session_id=session_id,
                consensus_sender_sequence=consensus_sender_sequence,
                consensus_lock_signatures=consensus_lock_signatures,
            )

        result = session_service.open_session(
            endpoint_id=endpoint.endpoint_id,
            client_wallet=client_wallet,
            provider_wallet=endpoint.owner_wallet,
            endpoint_payment_beneficiary=endpoint.owner_wallet,
            consumer_refund_beneficiary=client_wallet,
            node_id=self._host.node_id,
            deposit_q=deposit_q_atoms / Q_ATOMS_PER_Q,
            deposit_q_atoms=deposit_q_atoms,
            fixed_price_q_atoms=fixed_price_q_atoms,
            request_charge_ceiling_q_atoms=fixed_price_q_atoms,
            economic_profile="MVP-0001",
            session_policy=endpoint.session.model_dump(mode="json"),
            accounting_contract=accounting_contract,
            endpoint_configuration_hash=endpoint.configuration_hash,
            consumer_authorization_public_key=consumer_authorization_public_key,
            session_id=session_id,
        )
        funding = SessionFundingAccount(
            session_id=result.session.session_id,
            session_contract_hash=result.session.session_contract_hash,
            funding_class="ESCROW_PREPAID",
            consumer_funding_account=client_wallet,
            endpoint_payment_beneficiary=result.session.endpoint_payment_beneficiary,
            consumer_refund_beneficiary=result.session.consumer_refund_beneficiary,
            total_locked_amount_q_atoms=deposit_q_atoms,
            endpoint_payment_reserve_q_atoms=payment_reserve,
            network_fee_reserve_q_atoms=network_fee_reserve_q_atoms,
            unsettled_payment_reserve_q_atoms=payment_reserve,
            unsettled_fee_reserve_q_atoms=network_fee_reserve_q_atoms,
        )
        try:
            locked = self._host.lock_session_funding(funding)
        except Exception:
            session_service.store.discard_open_session(result.session.session_id)
            raise
        if consumer_authorization is not None:
            self._host._consumed_wallet_authorization_nonces.add(
                str(consumer_authorization["nonce"])
            )
        session = session_service.bind_canonical_funding(
            result.session.session_id,
            funding_state_hash=str(locked.funding_state_hash),
        )
        return session, result.deposit, locked

    def _open_validator_consensus_session(
        self,
        *,
        session_service,
        endpoint,
        client_wallet: str,
        deposit_q_atoms: int,
        fixed_price_q_atoms: int,
        network_fee_reserve_q_atoms: int,
        payment_reserve: int,
        accounting_contract: dict | None,
        consumer_authorization_public_key: str | None,
        consumer_authorization: dict | None,
        session_id: str | None,
        consensus_sender_sequence: int | None,
        consensus_lock_signatures: list[str] | None,
    ):
        """Open or resume a validator Session without a local lock mutation."""
        if session_id is not None:
            try:
                current = session_service.store.get_session(session_id)
            except KeyError as error:
                raise ValueError("pending canonical Session was not found") from error
            if current.endpoint_id != endpoint.endpoint_id:
                raise ValueError("pending canonical Session Endpoint does not match")
            if current.client_wallet != client_wallet:
                raise ValueError("pending canonical Session Consumer does not match")
            if current.economic_profile != "MVP-0001":
                raise ValueError("Session is not an MVP-0001 economic Session")
            if current.deposit_locked_q_atoms != deposit_q_atoms:
                raise ValueError("pending canonical Session deposit does not match")
            if current.fixed_price_q_atoms != fixed_price_q_atoms:
                raise ValueError("pending canonical Session fixed price does not match")
            if current.request_charge_ceiling_q_atoms != fixed_price_q_atoms:
                raise ValueError(
                    "pending canonical Session charge ceiling does not match"
                )
            if current.canonical_funding_status == "FINALIZED":
                funding = self._host.get_session_funding_account(session_id)
                return current, session_service.store.get_deposit_for_session(session_id), funding
            if current.canonical_funding_status != "PENDING_FINALITY":
                raise ValueError("Session does not have a pending canonical funding lock")
            return self._reconcile_validator_consensus_session(
                session_service=session_service,
                session_id=session_id,
            )

        if consensus_sender_sequence is None:
            raise ValueError("validator Session open requires canonical sender sequence")
        if not consensus_lock_signatures:
            raise ValueError("validator Session open requires canonical lock signatures")

        result = session_service.open_session(
            endpoint_id=endpoint.endpoint_id,
            client_wallet=client_wallet,
            provider_wallet=endpoint.owner_wallet,
            endpoint_payment_beneficiary=endpoint.owner_wallet,
            consumer_refund_beneficiary=client_wallet,
            node_id=self._host.node_id,
            deposit_q=deposit_q_atoms / Q_ATOMS_PER_Q,
            deposit_q_atoms=deposit_q_atoms,
            fixed_price_q_atoms=fixed_price_q_atoms,
            request_charge_ceiling_q_atoms=fixed_price_q_atoms,
            economic_profile="MVP-0001",
            session_policy=endpoint.session.model_dump(mode="json"),
            accounting_contract=accounting_contract,
            endpoint_configuration_hash=endpoint.configuration_hash,
            consumer_authorization_public_key=consumer_authorization_public_key,
            session_id=session_id,
            canonical_funding_status="PENDING_FINALITY",
        )
        pending_funding = SessionFundingAccount(
            session_id=result.session.session_id,
            session_contract_hash=result.session.session_contract_hash,
            funding_class="ESCROW_PREPAID",
            consumer_funding_account=client_wallet,
            endpoint_payment_beneficiary=result.session.endpoint_payment_beneficiary,
            consumer_refund_beneficiary=result.session.consumer_refund_beneficiary,
            total_locked_amount_q_atoms=deposit_q_atoms,
            endpoint_payment_reserve_q_atoms=payment_reserve,
            network_fee_reserve_q_atoms=network_fee_reserve_q_atoms,
            unsettled_payment_reserve_q_atoms=payment_reserve,
            unsettled_fee_reserve_q_atoms=network_fee_reserve_q_atoms,
            funding_state="LOCK_PENDING",
        )
        from aidn_hypervisor.consensus.projection import (
            build_session_escrow_lock_envelope_from_funding,
        )

        envelope = build_session_escrow_lock_envelope_from_funding(
            pending_funding,
            sender_sequence=consensus_sender_sequence,
            signatures=consensus_lock_signatures,
            created_at=datetime.now(UTC).isoformat(),
        )
        consensus = self._host.consensus_service
        try:
            submission = consensus.submit_operation(envelope)
            if submission.status.value == "failed":
                raise ValueError(submission.error or "canonical Session lock was rejected")
            session = session_service.bind_pending_canonical_funding(
                result.session.session_id,
                operation_id=envelope.operation_id,
                submission={
                    **self._consensus_submission_payload(submission),
                    "envelope": envelope.model_dump(mode="json"),
                },
            )
            if consumer_authorization is not None:
                self._host._consumed_wallet_authorization_nonces.add(
                    str(consumer_authorization["nonce"])
                )
        except Exception:
            session_service.store.discard_open_session(result.session.session_id)
            raise

        return self._reconcile_validator_consensus_session(
            session_service=session_service,
            session_id=session.session_id,
        )

    def _reconcile_validator_consensus_session(self, *, session_service, session_id: str):
        from aidn_hypervisor.consensus.models import LedgerOperationEnvelope

        session = session_service.store.get_session(session_id)
        submission_payload = session.canonical_funding_submission
        if not isinstance(submission_payload, dict) or not submission_payload:
            raise ValueError("pending canonical Session lock submission is missing")
        envelope_payload = submission_payload.get("envelope", submission_payload)
        if not isinstance(envelope_payload, dict):
            raise ValueError("pending canonical Session lock envelope is invalid")
        envelope = LedgerOperationEnvelope.model_validate(envelope_payload)
        if session.canonical_funding_operation_id != envelope.operation_id:
            raise ValueError("pending canonical Session lock identity is inconsistent")
        consensus = self._host.consensus_service
        submission = consensus.get_submission(envelope.operation_id)
        if submission is None:
            # A restart can discard the in-memory submission index even though
            # CometBFT already finalized the exact transaction. Restore its
            # identity first so finality verification can inspect the existing
            # transaction before any rebroadcast. Rebroadcasting first can
            # produce a misleading sender-sequence rejection.
            submission = consensus.restore_submission(envelope)
        if submission.status.value == "failed":
            raise ValueError(submission.error or "canonical Session lock was rejected")
        finality_source = getattr(self._host, "consensus_finality_source", None)
        if finality_source is not None:
            reconciled = consensus.reconcile_finality(
                envelope.operation_id,
                finality_source=finality_source,
            )
            if reconciled is not None:
                submission = reconciled
        if submission.status.value not in {"finalized", "included"}:
            submission = consensus.submit_operation(envelope, retry_existing=True)
            if finality_source is not None:
                reconciled = consensus.reconcile_finality(
                    envelope.operation_id,
                    finality_source=finality_source,
                )
                if reconciled is not None:
                    submission = reconciled
        if submission.status.value != "finalized":
            return (
                session,
                session_service.store.get_deposit_for_session(session_id),
                self._pending_funding_from_envelope(envelope),
            )

        try:
            funding = self._host.get_session_funding_account(session_id)
        except KeyError:
            # Finality evidence without a local canonical projection is not
            # enough to activate execution on this validator.
            return (
                session,
                session_service.store.get_deposit_for_session(session_id),
                self._pending_funding_from_envelope(envelope),
            )
        expected_funding = self._pending_funding_from_envelope(envelope)
        if funding.model_dump(mode="json") != expected_funding.model_dump(mode="json"):
            raise ValueError("canonical Session funding projection does not match lock envelope")
        session = session_service.bind_canonical_funding(
            session_id,
            funding_state_hash=funding.funding_state_hash or "",
            operation_id=envelope.operation_id,
        )
        return session, session_service.store.get_deposit_for_session(session_id), funding

    @staticmethod
    def _pending_funding_from_envelope(envelope):
        return SessionFundingAccount.model_validate(envelope.payload)

    @staticmethod
    def _consensus_submission_payload(submission) -> dict:
        return {
            "operation_id": submission.operation_id,
            "status": submission.status.value,
            "submitted_at": submission.submitted_at,
            "admitted_at": submission.admitted_at,
            "included_at": submission.included_at,
            "finalized_at": submission.finalized_at,
            "block_height": submission.block_height,
            "transaction_hash": submission.transaction_hash,
            "retry_count": submission.retry_count,
            "error": submission.error,
        }

    def build_mvp_fixed_price_settlement_evaluation(
        self,
        *,
        session_service,
        session_id: str,
        request_id: str,
        actual_network_fees_q_atoms: int = 0,
        settlement_sequence: int = 1,
        proposal_expiration: str | None = None,
    ):
        session = session_service.store.get_session(session_id)
        if session.economic_profile != "MVP-0001":
            raise ValueError("Session is not an MVP-0001 economic Session")
        if session.fixed_price_q_atoms is None:
            raise ValueError("MVP Session is missing fixed_price_q_atoms")
        if session.request_charge_ceiling_q_atoms is None:
            raise ValueError("MVP Session is missing request_charge_ceiling_q_atoms")
        if session.accounting_contract_hash is None:
            raise ValueError("MVP Session is missing accounting_contract_hash")
        if session.session_contract_hash is None:
            raise ValueError("MVP Session is missing session_contract_hash")
        if session.canonical_funding_state_hash is None:
            raise ValueError("MVP Session is not bound to canonical funding")

        matching_requests = [
            item
            for item in self._host.runtime_protocol_store.requests.values()
            if item.request.session_id == session_id
        ]
        if len(matching_requests) != 1 or matching_requests[0].request_id != request_id:
            raise ValueError("MVP-0001 supports exactly one Runtime Request per Session")
        record = matching_requests[0]
        if record.request.endpoint_id != session.endpoint_id:
            raise ValueError("Runtime Request Endpoint does not match Session")
        if (
            record.request.endpoint_configuration_hash
            != session.endpoint_configuration_hash
        ):
            raise ValueError(
                "Runtime Request Endpoint Configuration does not match Session"
            )
        if record.request.session_contract_hash != session.session_contract_hash:
            raise ValueError("Runtime Request Session Contract does not match Session")
        if record.request.accounting_contract_hash != session.accounting_contract_hash:
            raise ValueError("Runtime Request Accounting Contract does not match Session")
        if (
            record.terminal_result_hash is None
            or record.terminal_final_usage_report_id is None
        ):
            raise ValueError("Runtime Request is not terminal with Final Usage")

        final_usage = self._host.runtime_protocol_store.usage_reports.get(
            record.terminal_final_usage_report_id
        )
        if final_usage is None:
            raise ValueError("Final Usage Report is missing from Runtime store")
        endpoint_service = getattr(self._host, "endpoint_service", None)
        if endpoint_service is not None:
            endpoint = endpoint_service.get_endpoint(session.endpoint_id).endpoint
            if endpoint.runtime_binding_id is not None:
                matching_terminal_evidence = [
                    item
                    for item in session.runtime_terminal_evidence
                    if item.request_id == request_id
                ]
                if len(matching_terminal_evidence) != 1:
                    raise ValueError(
                        "Runtime-bound MVP Session requires exactly one terminal Runtime evidence record"
                    )
                terminal_evidence = matching_terminal_evidence[0]
                if terminal_evidence.runtime_binding_id != endpoint.runtime_binding_id:
                    raise ValueError("Session Runtime Binding does not match Endpoint")
                if terminal_evidence.runtime_id != record.request.runtime_id:
                    raise ValueError("Session Runtime ID does not match Runtime Request")
                if (
                    terminal_evidence.runtime_generation
                    != record.request.runtime_generation
                ):
                    raise ValueError(
                        "Session Runtime Generation does not match Runtime Request"
                    )
                if (
                    terminal_evidence.runtime_configuration_hash
                    != record.request.runtime_configuration_hash
                ):
                    raise ValueError(
                        "Session Runtime Configuration does not match Runtime Request"
                    )
                if terminal_evidence.route_generation != record.request.route_generation:
                    raise ValueError(
                        "Session Route Generation does not match Runtime Request"
                    )
                if (
                    record.request.effective_terms_hash is not None
                    and terminal_evidence.effective_terms_hash
                    != record.request.effective_terms_hash
                ):
                    raise ValueError(
                        "Session Effective Terms hash does not match Runtime Request"
                    )
                if (
                    session.session_amendment_sequence > 0
                    and terminal_evidence.effective_terms_hash is None
                ):
                    raise ValueError(
                        "Session Effective Terms hash is required after amendment"
                    )
                if terminal_evidence.terminal_state != record.request_state:
                    raise ValueError(
                        "Session terminal state does not match Runtime Request"
                    )
                if terminal_evidence.result_hash != record.terminal_result_hash:
                    raise ValueError("Session Result hash does not match Runtime Request")
                if (
                    terminal_evidence.final_usage_report_id
                    != final_usage.usage_report_id
                ):
                    raise ValueError(
                        "Session Final Usage ID does not match Runtime store"
                    )
                if (
                    terminal_evidence.final_usage_report_hash
                    != final_usage.report_hash
                ):
                    raise ValueError(
                        "Session Final Usage hash does not match Runtime store"
                    )
        request_reports = sorted(
            (
                item
                for item in self._host.runtime_protocol_store.usage_reports.values()
                if item.request_id == request_id
            ),
            key=lambda item: item.usage_sequence,
        )
        if (
            not request_reports
            or request_reports[-1].usage_report_id != final_usage.usage_report_id
        ):
            raise ValueError("Final Usage Report is not the current Usage chain head")

        usage_conflicted = any(
            item.request_id == request_id
            for item in self._host.runtime_protocol_store.usage_conflicts.values()
        )
        request_input = RequestSettlementInput(
            session_id=session_id,
            request_id=request_id,
            request_charge_ceiling_q_atoms=session.request_charge_ceiling_q_atoms,
            effective_terms_hash=(
                session.effective_terms_hash or session.session_contract_hash
            ),
            accounting_contract_hash=session.accounting_contract_hash,
            terminal_state=record.request_state,
            result_reference=record.terminal_result_hash,
            final_usage_report_id=final_usage.usage_report_id,
            final_usage_report_hash=final_usage.report_hash,
            usage_sequence=final_usage.usage_sequence,
            usage_chain_valid=not usage_conflicted,
            usage_chain_conflicted=usage_conflicted,
            dimensions=[
                dimension.model_copy(deep=True) for dimension in final_usage.dimensions
            ],
        )
        terms = SettlementAccountingTerms(
            accounting_contract_hash=session.accounting_contract_hash,
            accounting_mode="fixed_price",
            components=[
                SettlementChargeComponent(
                    component_id="mvp_fixed_request_price",
                    fixed_amount_q_atoms=session.fixed_price_q_atoms,
                )
            ],
            terminal_policies={
                "COMPLETED": TerminalChargePolicy(mode="FULL_CHARGE"),
                "PARTIAL": TerminalChargePolicy(mode="NO_CHARGE"),
                "CANCELLED": TerminalChargePolicy(mode="NO_CHARGE"),
                "FAILED": TerminalChargePolicy(mode="NO_CHARGE"),
                "EXPIRED": TerminalChargePolicy(mode="NO_CHARGE"),
                "UNRECOVERABLE": TerminalChargePolicy(mode="NO_CHARGE"),
                "REJECTED": TerminalChargePolicy(mode="NO_CHARGE"),
            },
        )
        funding = self._host.get_session_funding_account(session_id)
        if funding.funding_state in {"RELEASED", "REFUNDED"}:
            raise ValueError("MVP Session funding is already finalized")
        if funding.funding_state_hash != session.canonical_funding_state_hash:
            raise ValueError("Session funding hash no longer matches Session")
        close_reference = _canonical_hash(
            {
                "economic_profile": "MVP-0001",
                "session_id": session_id,
                "request_id": request_id,
                "terminal_result_hash": record.terminal_result_hash,
                "final_usage_report_hash": final_usage.report_hash,
                "settlement_sequence": settlement_sequence,
            }
        )
        return SettlementEngine().evaluate_session(
            funding=funding,
            session_contract_hash=session.session_contract_hash,
            effective_terms_hash=(
                session.effective_terms_hash or session.session_contract_hash
            ),
            request_inputs=[request_input],
            terms_by_hash={session.accounting_contract_hash: terms},
            maximum_session_charge_q_atoms=session.request_charge_ceiling_q_atoms,
            actual_network_fees_q_atoms=actual_network_fees_q_atoms,
            session_close_reference=close_reference,
            settlement_sequence=settlement_sequence,
            proposal_expiration=proposal_expiration,
        )

    def build_mvp_endpoint_unavailable_refund_evaluation(
        self,
        *,
        session_service,
        session_id: str,
        actual_network_fees_q_atoms: int = 0,
        settlement_sequence: int = 1,
        proposal_expiration: str | None = None,
    ):
        session = session_service.store.get_session(session_id)
        if session.economic_profile != "MVP-0001":
            raise ValueError("Session is not an MVP-0001 economic Session")
        if session.request_charge_ceiling_q_atoms is None:
            raise ValueError("MVP Session is missing request_charge_ceiling_q_atoms")
        if session.session_contract_hash is None:
            raise ValueError("MVP Session is missing session_contract_hash")
        if session.canonical_funding_state_hash is None:
            raise ValueError("MVP Session is not bound to canonical funding")
        matching_requests = [
            item
            for item in self._host.runtime_protocol_store.requests.values()
            if item.request.session_id == session_id
        ]
        if matching_requests:
            raise ValueError("Endpoint-unavailable refund requires no accepted Runtime work")
        funding = self._host.get_session_funding_account(session_id)
        if funding.funding_state in {"RELEASED", "REFUNDED"}:
            raise ValueError("MVP Session funding is already finalized")
        if funding.funding_state_hash != session.canonical_funding_state_hash:
            raise ValueError("Session funding hash no longer matches Session")
        close_reference = _canonical_hash(
            {
                "economic_profile": "MVP-0001",
                "session_id": session_id,
                "reason": "ENDPOINT_UNAVAILABLE",
                "settlement_sequence": settlement_sequence,
            }
        )
        return SettlementEngine().evaluate_session(
            funding=funding,
            session_contract_hash=session.session_contract_hash,
            effective_terms_hash=(
                session.effective_terms_hash or session.session_contract_hash
            ),
            request_inputs=[],
            terms_by_hash={},
            maximum_session_charge_q_atoms=session.request_charge_ceiling_q_atoms,
            actual_network_fees_q_atoms=actual_network_fees_q_atoms,
            session_close_reference=close_reference,
            settlement_sequence=settlement_sequence,
            settlement_mode="FORCED",
            proposal_expiration=proposal_expiration,
        )

    def finalize_mvp_fixed_price_session(
        self,
        *,
        session_service,
        session_id: str,
        request_id: str,
        consumer_signature: str,
        actual_network_fees_q_atoms: int = 0,
        settlement_sequence: int = 1,
        proposal_expiration: str | None = None,
        accepted_at: str | None = None,
    ):
        recovered = self._reconcile_canonical_cooperative_settlement(
            session_service=session_service,
            session_id=session_id,
        )
        if recovered is not None:
            return recovered
        session = session_service.store.get_session(session_id)
        evaluation = self.build_mvp_fixed_price_settlement_evaluation(
            session_service=session_service,
            session_id=session_id,
            request_id=request_id,
            actual_network_fees_q_atoms=actual_network_fees_q_atoms,
            settlement_sequence=settlement_sequence,
            proposal_expiration=proposal_expiration,
        )
        if evaluation.proposal.dispute_reserve_q_atoms or any(
            record.dispute_state != "NONE"
            for record in evaluation.input_set.request_settlement_records
        ):
            raise ValueError(
                "MVP cooperative Settlement requires undisputed Runtime evidence"
            )
        proposal = evaluation.proposal
        acceptance = SessionSettlementAcceptance(
            settlement_id=proposal.settlement_id,
            session_id=session_id,
            settlement_input_root=proposal.settlement_input_root,
            accepted_endpoint_payment_q_atoms=proposal.final_endpoint_payment_q_atoms,
            accepted_consumer_refund_q_atoms=(
                proposal.consumer_payment_refund_q_atoms
                + proposal.consumer_fee_refund_q_atoms
            ),
            accepted_network_fees_q_atoms=proposal.actual_network_fees_q_atoms,
            consumer_signature=consumer_signature,
            accepted_at=accepted_at or datetime.now(UTC).isoformat(),
        )
        if session.consumer_authorization_public_key is not None:
            from aidn_hypervisor.settlement.signing import verify_settlement_acceptance

            verify_settlement_acceptance(
                acceptance,
                consumer_public_key=session.consumer_authorization_public_key,
            )
        consensus = getattr(self._host, "consensus_service", None)
        consensus_result = None
        if consensus is not None and consensus.is_enabled:
            canonical = self._host.submit_consensus_cooperative_settlement(
                evaluation,
                acceptance,
                created_at=acceptance.accepted_at,
                signatures=[consumer_signature],
            )
            consensus_result = canonical["consensus"]
            if canonical["status"] != "FINALIZED":
                return {
                    "status": "CONSENSUS_PENDING",
                    "evaluation": evaluation,
                    "proposal": proposal,
                    "acceptance": acceptance,
                    "funding": canonical["funding"],
                    "consensus": consensus_result,
                    "session_result": None,
                }
            funding = canonical["funding"]
        else:
            proposal = self._host.propose_settlement(evaluation)
            self._host.accept_settlement(acceptance)
            funding = self._host.finalize_accepted_settlement(evaluation)
        session_result = session_service.mark_canonical_settlement_finalized(
            session_id,
            settlement_evidence_root=evaluation.input_set.settlement_input_root,
            endpoint_payment_q_atoms=proposal.final_endpoint_payment_q_atoms,
            consumer_refund_q_atoms=(
                proposal.consumer_payment_refund_q_atoms
                + proposal.consumer_fee_refund_q_atoms
            ),
            network_fee_q_atoms=proposal.actual_network_fees_q_atoms,
        )
        self._host._persist_state()
        return {
            "evaluation": evaluation,
            "proposal": proposal,
            "acceptance": acceptance,
            "funding": funding,
            "session_result": session_result,
            **({"status": "FINALIZED", "consensus": consensus_result} if consensus_result is not None else {}),
        }

    def _reconcile_canonical_cooperative_settlement(
        self,
        *,
        session_service,
        session_id: str,
    ) -> dict | None:
        """Finish a cooperative Settlement committed while the request was pending.

        Consensus may apply the atomic funding transition after the HTTP
        request has already returned ``CONSENSUS_PENDING``.  ABCI owns the
        canonical funding transition, while ``SessionService`` owns the local
        Session and Deposit projection.  Reconcile only an applied,
        Session-bound finalization with verified finality; never infer a
        settlement from ``RELEASED`` funding alone.
        """
        try:
            session = session_service.store.get_session(session_id)
            funding = self._host.get_session_funding_account(session_id)
        except KeyError:
            return None
        if session.status in {"closed", "force_settled"}:
            return None
        if funding.funding_state not in {"RELEASED", "REFUNDED"}:
            return None

        ledger = self._host._ledger_operation_service
        finalize_operation = None
        for operation in reversed(ledger.list_operations()):
            if operation.get("operation_type") != "SESSION_SETTLEMENT_FINALIZE":
                continue
            payload = operation.get("payload")
            result = operation.get("result")
            if not isinstance(payload, dict) or not isinstance(result, dict):
                continue
            if (
                payload.get("session_id") == session_id
                and result.get("status") == "applied"
            ):
                finalize_operation = operation
                break
        if finalize_operation is None:
            return None

        payload = finalize_operation["payload"]
        transition_payload = payload.get("transition")
        if not isinstance(transition_payload, dict):
            raise ValueError("canonical cooperative Settlement transition is incomplete")
        try:
            transition = AtomicSettlementTransition.model_validate(transition_payload)
        except ValueError as error:
            raise ValueError(
                "canonical cooperative Settlement transition is invalid"
            ) from error

        if transition.session_id != session_id:
            raise ValueError("canonical cooperative Settlement session binding is invalid")
        if payload.get("session_id") != session_id:
            raise ValueError("canonical cooperative Settlement payload session is invalid")
        if not isinstance(payload.get("settlement_input_root"), str):
            raise ValueError("canonical cooperative Settlement input root is missing")

        try:
            proposal = ledger.get_settlement_proposal(transition.settlement_id)
            acceptance = ledger.get_settlement_acceptance(transition.settlement_id)
        except KeyError as error:
            raise ValueError(
                "canonical cooperative Settlement proposal or acceptance is missing"
            ) from error
        if (
            proposal.session_id != session_id
            or proposal.settlement_id != transition.settlement_id
            or proposal.settlement_input_root != payload.get("settlement_input_root")
            or acceptance.session_id != session_id
            or acceptance.settlement_id != proposal.settlement_id
            or acceptance.settlement_input_root != proposal.settlement_input_root
            or payload.get("acceptance_hash") != acceptance.acceptance_hash
        ):
            raise ValueError("canonical cooperative Settlement binding is invalid")
        if (
            acceptance.accepted_endpoint_payment_q_atoms
            != proposal.final_endpoint_payment_q_atoms
            or acceptance.accepted_consumer_refund_q_atoms
            != proposal.consumer_payment_refund_q_atoms
            + proposal.consumer_fee_refund_q_atoms
            or acceptance.accepted_network_fees_q_atoms
            != proposal.actual_network_fees_q_atoms
        ):
            raise ValueError("canonical cooperative Settlement acceptance is invalid")
        if proposal.dispute_reserve_q_atoms != 0:
            raise ValueError(
                "canonical cooperative Settlement cannot retain a dispute reserve"
            )
        if ledger.get_settlement_transition_hash(proposal.settlement_id) != transition.transition_hash:
            raise ValueError("canonical cooperative Settlement transition hash is invalid")
        if (
            funding.released_to_endpoint_q_atoms
            != proposal.final_endpoint_payment_q_atoms
            or funding.consumer_payment_refund_q_atoms
            != proposal.consumer_payment_refund_q_atoms
            or funding.consumer_fee_refund_q_atoms != proposal.consumer_fee_refund_q_atoms
            or funding.consumed_network_fees_q_atoms
            != proposal.actual_network_fees_q_atoms
            or funding.active_dispute_reserve_q_atoms != 0
        ):
            raise ValueError("canonical cooperative Settlement funding is inconsistent")

        consensus = getattr(self._host, "consensus_service", None)
        consensus_enabled = bool(
            consensus is not None and getattr(consensus, "is_enabled", False)
        )
        finality = self._host.ledger_operation_finality(
            finalize_operation["operation_id"]
        )
        consensus_finalized = (
            not consensus_enabled or finality.get("consensus_finalized") is True
        )
        consensus_payload = {
            "status": "finalized" if consensus_finalized else "awaiting_verified_finality",
            "blocked_on": None if consensus_finalized else "finalize",
            "canonical_operation_ids": {
                "finalize": finalize_operation["operation_id"],
            },
            "finality": finality,
        }
        if not consensus_finalized:
            return {
                "status": "CONSENSUS_PENDING",
                "proposal": proposal,
                "acceptance": acceptance,
                "funding": funding,
                "consensus": consensus_payload,
                "session_result": None,
            }

        session_result = session_service.mark_canonical_settlement_finalized(
            session_id,
            settlement_evidence_root=proposal.settlement_input_root,
            endpoint_payment_q_atoms=proposal.final_endpoint_payment_q_atoms,
            consumer_refund_q_atoms=(
                proposal.consumer_payment_refund_q_atoms
                + proposal.consumer_fee_refund_q_atoms
            ),
            network_fee_q_atoms=proposal.actual_network_fees_q_atoms,
        )
        self._host._persist_state()
        return {
            "status": "FINALIZED",
            "proposal": proposal,
            "acceptance": acceptance,
            "funding": funding,
            "consensus": consensus_payload,
            "session_result": session_result,
        }

    def force_finalize_mvp_fixed_price_session(
        self,
        *,
        session_service,
        session_id: str,
        reason: str,
        force_after: str,
        request_id: str | None = None,
        now: str | None = None,
        actual_network_fees_q_atoms: int = 0,
        settlement_sequence: int = 1,
        consensus_sender_sequence: int | None = None,
        consensus_lock_signatures: list[str] | None = None,
        consensus_failure_signatures: list[str] | None = None,
        consensus_initiator_wallet: str | None = None,
        consensus_initiator_signature: str | None = None,
        consensus_observed_at: str | None = None,
        consensus_force_signatures: list[str] | None = None,
    ):
        recovered = self._reconcile_canonical_force_settlement(
            session_service=session_service,
            session_id=session_id,
            reason=reason,
        )
        if recovered is not None:
            return recovered
        if reason == "ENDPOINT_UNAVAILABLE":
            evaluation = self.build_mvp_endpoint_unavailable_refund_evaluation(
                session_service=session_service,
                session_id=session_id,
                actual_network_fees_q_atoms=actual_network_fees_q_atoms,
                settlement_sequence=settlement_sequence,
            )
            no_request = True
        elif reason == "CONSUMER_TIMEOUT_AFTER_COMPLETED_FIXED_PRICE":
            if request_id is None:
                raise ValueError(
                    "forced completed fixed-price payment requires request_id"
                )
            evaluation = self.build_mvp_fixed_price_settlement_evaluation(
                session_service=session_service,
                session_id=session_id,
                request_id=request_id,
                actual_network_fees_q_atoms=actual_network_fees_q_atoms,
                settlement_sequence=settlement_sequence,
            )
            no_request = False
        else:
            raise ValueError("unsupported forced Settlement reason")
        failure_evidence_root = session_service.failure_evidence_root(session_id)
        if failure_evidence_root is None and session_service.failure_handler is not None:
            failure_evidence_root = session_service.ensure_failure_evidence(
                session_id=session_id,
                failure_class=(
                    FailureClass.ENDPOINT_FAILURE
                    if reason == "ENDPOINT_UNAVAILABLE"
                    else FailureClass.CONSUMER_DISCONNECTED
                ),
                details=f"MVP forced Settlement reason: {reason}",
            )
        if session_service.failure_handler is not None and failure_evidence_root is None:
            raise ValueError("forced Settlement requires persisted failure evidence")
        failure_evidence_operation_id = None
        if failure_evidence_root is not None:
            failure_evidence_class = (
                FailureClass.ENDPOINT_FAILURE.value
                if reason == "ENDPOINT_UNAVAILABLE"
                else FailureClass.CONSUMER_DISCONNECTED.value
            )
            evidence_operation = self._host.commit_session_failure_evidence(
                session_id=session_id,
                failure_class=failure_evidence_class,
                failure_evidence_root=failure_evidence_root,
                details=f"MVP forced Settlement reason: {reason}",
            )
            failure_evidence_operation_id = evidence_operation["operation_id"]

        consensus = getattr(self._host, "consensus_service", None)
        consensus_enabled = bool(
            consensus is not None and getattr(consensus, "is_enabled", False)
        )
        proposal = evaluation.proposal
        if consensus_enabled:
            if failure_evidence_operation_id is None:
                raise ValueError(
                    "consensus Forced Settlement requires local failure evidence"
                )
            ledger = self._host._ledger_operation_service
            lock_operation = next(
                (
                    operation
                    for operation in reversed(ledger.list_operations())
                    if operation.get("operation_type") == "SESSION_ESCROW_LOCK"
                    and isinstance(operation.get("payload"), dict)
                    and operation["payload"].get("session_id") == session_id
                ),
                None,
            )
            if lock_operation is None:
                raise ValueError(
                    "consensus Forced Settlement requires a local escrow lock"
                )
            if consensus_sender_sequence is None:
                raise ValueError(
                    "consensus_sender_sequence is required for consensus escrow lock"
                )
            if not consensus_lock_signatures:
                raise ValueError(
                    "consensus_lock_signatures are required for consensus escrow lock"
                )
            if not consensus_failure_signatures:
                raise ValueError(
                    "consensus_failure_signatures are required for failure evidence"
                )
            if not consensus_initiator_wallet:
                raise ValueError(
                    "consensus_initiator_wallet is required for Forced Settlement"
                )
            if not consensus_initiator_signature:
                raise ValueError(
                    "consensus_initiator_signature is required for Forced Settlement"
                )
            observed_at = consensus_observed_at or now
            if not observed_at:
                raise ValueError(
                    "consensus_observed_at or now is required for Forced Settlement"
                )
            if consensus_force_signatures is None:
                consensus_force_signatures = [consensus_initiator_signature]

            prepared = self._host.prepare_force_settlement_operation(
                evaluation,
                failure_class=reason,
                force_after=force_after,
                now=now,
                failure_evidence_root=failure_evidence_root,
                failure_evidence_operation_id=failure_evidence_operation_id,
                failure_evidence_operation=evidence_operation,
                initiator_signature=consensus_initiator_signature,
                require_completed_fixed_price=(
                    reason == "CONSUMER_TIMEOUT_AFTER_COMPLETED_FIXED_PRICE"
                ),
            )
            force_operation = prepared["operation"]
            consensus_result = self._host.submit_consensus_session_failure_chain(
                local_lock_operation_id=str(lock_operation["operation_id"]),
                local_failure_operation_id=failure_evidence_operation_id,
                local_force_operation_id=str(force_operation["operation_id"]),
                funding=prepared["funding"],
                sender_sequence=consensus_sender_sequence,
                lock_signatures=consensus_lock_signatures,
                failure_signatures=consensus_failure_signatures,
                initiator_wallet=consensus_initiator_wallet,
                initiator_signature=consensus_initiator_signature,
                observed_at=observed_at,
                transition=evaluation.transition.model_dump(mode="json"),
                force_signatures=consensus_force_signatures,
            )
            if consensus_result["status"] != "finalized":
                return {
                    "status": "CONSENSUS_PENDING",
                    "evaluation": evaluation,
                    "proposal": proposal,
                    "funding": self._host.get_session_funding_account(session_id),
                    "consensus": consensus_result,
                    "session_result": None,
                }
            canonical_force_operation_id = str(
                consensus_result["canonical_operation_ids"]["force"]
            )
            consensus_force_operation_id = (
                canonical_force_operation_id
                if getattr(consensus, "is_validator", False)
                else str(force_operation["operation_id"])
            )
            funding = self._host.apply_prepared_force_settlement(
                evaluation,
                force_operation_id=consensus_force_operation_id,
                created_at=now,
            )
            self._host.discard_pending_consensus_operations(
                failure_evidence_operation_id,
                str(force_operation["operation_id"]),
            )
        else:
            funding = self._host.force_finalize_fixed_price_settlement(
                evaluation,
                reason=reason,
                force_after=force_after,
                now=now,
                failure_evidence_root=failure_evidence_root,
                failure_evidence_operation_id=failure_evidence_operation_id,
            )
        proposal = evaluation.proposal
        session_result = session_service.mark_canonical_settlement_finalized(
            session_id,
            settlement_evidence_root=evaluation.input_set.settlement_input_root,
            endpoint_payment_q_atoms=proposal.final_endpoint_payment_q_atoms,
            consumer_refund_q_atoms=(
                proposal.consumer_payment_refund_q_atoms
                + proposal.consumer_fee_refund_q_atoms
            ),
            network_fee_q_atoms=proposal.actual_network_fees_q_atoms,
            failure_evidence_root=failure_evidence_root,
            close_reason=f"forced_{reason.lower()}",
            no_request=no_request,
        )
        self._host._persist_state()
        return {
            "status": "FINALIZED",
            "evaluation": evaluation,
            "proposal": proposal,
            "funding": funding,
            **({"consensus": consensus_result} if consensus_enabled else {}),
            "session_result": session_result,
        }

    def _reconcile_canonical_force_settlement(
        self,
        *,
        session_service,
        session_id: str,
        reason: str,
    ) -> dict | None:
        """Finish a force Settlement committed while the request was pending.

        A validator may commit the canonical force transaction after the HTTP
        request has already returned ``CONSENSUS_PENDING``.  The ABCI Ledger
        then has the final Funding Account, but the application Session still
        needs its local terminal projection.  Reconcile only an applied,
        Session-bound force operation and never infer closure from Funding
        state alone.
        """
        try:
            session = session_service.store.get_session(session_id)
            funding = self._host.get_session_funding_account(session_id)
        except KeyError:
            return None
        if funding.funding_state not in {"RELEASED", "REFUNDED"}:
            return None

        force_operation = None
        for operation in reversed(self._host._ledger_operation_service.list_operations()):
            if operation.get("operation_type") != "SESSION_FORCE_SETTLE":
                continue
            payload = operation.get("payload")
            result = operation.get("result")
            if not isinstance(payload, dict) or not isinstance(result, dict):
                continue
            if (
                payload.get("session_id") == session_id
                and result.get("status") == "applied"
            ):
                force_operation = operation
                break
        if force_operation is None:
            return None

        payload = force_operation["payload"]
        failure_class = payload.get("failure_class")
        allowed_failure_classes = (
            {"ENDPOINT_UNAVAILABLE", "ENDPOINT_FAILURE"}
            if reason == "ENDPOINT_UNAVAILABLE"
            else {reason}
        )
        if failure_class not in allowed_failure_classes:
            return None
        settlement_id = payload.get("settlement_id")
        settlement_input_root = payload.get("settlement_input_root")
        request_settlement_root = payload.get("request_settlement_root")
        usage_chain_root = payload.get("usage_chain_root")
        checkpoint_root = payload.get("checkpoint_root")
        failure_evidence_root = payload.get("failure_evidence_root")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                settlement_id,
                settlement_input_root,
                request_settlement_root,
                usage_chain_root,
                checkpoint_root,
                failure_evidence_root,
            )
        ):
            raise ValueError("canonical Forced Settlement evidence is incomplete")

        requested_payment = payload.get("requested_payment_q_atoms")
        requested_refund = payload.get("requested_refund_q_atoms")
        if (
            isinstance(requested_payment, bool)
            or not isinstance(requested_payment, int)
            or requested_payment < 0
            or isinstance(requested_refund, bool)
            or not isinstance(requested_refund, int)
            or requested_refund < 0
        ):
            raise ValueError("canonical Forced Settlement amounts are invalid")

        consumer_payment_refund = funding.consumer_payment_refund_q_atoms
        consumer_fee_refund = funding.consumer_fee_refund_q_atoms
        if requested_refund != consumer_payment_refund + consumer_fee_refund:
            raise ValueError("canonical Forced Settlement refund does not match Funding")
        actual_network_fees = funding.consumed_network_fees_q_atoms
        final_endpoint_payment = funding.released_to_endpoint_q_atoms
        proposal = SessionSettlementProposal(
            settlement_id=settlement_id,
            settlement_sequence=1,
            session_id=session_id,
            settlement_input_root=settlement_input_root,
            request_settlement_root=request_settlement_root,
            usage_chain_root=usage_chain_root,
            checkpoint_root=checkpoint_root,
            gross_session_charge_q_atoms=final_endpoint_payment + actual_network_fees,
            capped_session_charge_q_atoms=final_endpoint_payment + actual_network_fees,
            final_endpoint_payment_q_atoms=final_endpoint_payment,
            requested_endpoint_payment_q_atoms=requested_payment,
            consumer_payment_refund_q_atoms=consumer_payment_refund,
            actual_network_fees_q_atoms=actual_network_fees,
            consumer_fee_refund_q_atoms=consumer_fee_refund,
            disputed_amount_q_atoms=funding.active_dispute_reserve_q_atoms,
            dispute_reserve_q_atoms=funding.active_dispute_reserve_q_atoms,
            endpoint_absorbed_amount_q_atoms=0,
            settlement_mode="FORCED",
            proposal_expiration=None,
        )

        consensus = getattr(self._host, "consensus_service", None)
        consensus_enabled = bool(consensus is not None and consensus.is_enabled)
        finality = self._host.ledger_operation_finality(force_operation["operation_id"])
        consensus_finalized = (
            not consensus_enabled
            or finality.get("consensus_finalized") is True
        )
        consensus_payload = {
            "status": "finalized" if consensus_finalized else "awaiting_verified_finality",
            "blocked_on": None if consensus_finalized else "force",
            "canonical_operation_ids": {
                "force": force_operation["operation_id"],
            },
            "finality": finality,
        }
        if session.canonical_funding_operation_id:
            consensus_payload["canonical_operation_ids"]["lock"] = (
                session.canonical_funding_operation_id
            )

        if not consensus_finalized:
            return {
                "status": "CONSENSUS_PENDING",
                "proposal": proposal,
                "funding": funding,
                "consensus": consensus_payload,
                "session_result": None,
            }

        session_result = session_service.mark_canonical_settlement_finalized(
            session_id,
            settlement_evidence_root=settlement_input_root,
            endpoint_payment_q_atoms=final_endpoint_payment,
            consumer_refund_q_atoms=consumer_payment_refund + consumer_fee_refund,
            network_fee_q_atoms=actual_network_fees,
            failure_evidence_root=failure_evidence_root,
            close_reason=f"forced_{reason.lower()}",
            no_request=reason == "ENDPOINT_UNAVAILABLE",
        )
        self._host._persist_state()
        return {
            "status": "FINALIZED",
            "proposal": proposal,
            "funding": funding,
            "consensus": consensus_payload,
            "session_result": session_result,
        }
