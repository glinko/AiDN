from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from aidn_hypervisor.settlement.models import (
    RequestSettlementInput,
    SessionFundingAccount,
    SessionSettlementAcceptance,
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
    ):
        if deposit_q_atoms <= 0:
            raise ValueError("MVP Session deposit must be positive")
        if network_fee_reserve_q_atoms < 0:
            raise ValueError("Network Fee Reserve cannot be negative")
        payment_reserve = deposit_q_atoms - network_fee_reserve_q_atoms
        if payment_reserve < fixed_price_q_atoms:
            raise ValueError("MVP Session deposit cannot cover fixed price")
        if self._host.wallet_q_atom_balance(client_wallet) < deposit_q_atoms:
            raise ValueError("insufficient q_atoms for MVP Session escrow")
        if require_wallet_authorization and consumer_authorization is None:
            raise ValueError("Public MVP Session requires Consumer wallet authorization")
        if (
            require_wallet_authorization
            and self._host.resolve_wallet_identity(endpoint.owner_wallet) is None
        ):
            raise ValueError(
                "Public MVP Endpoint Payment Beneficiary identity is not registered"
            )
        if consumer_authorization is not None:
            from aidn_hypervisor.wallet_identity import verify_session_open_authorization

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
            effective_terms_hash=terms.terms_hash,
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
            effective_terms_hash=_canonical_hash(
                {
                    "economic_profile": "MVP-0001",
                    "reason": "ENDPOINT_UNAVAILABLE",
                    "terms": "zero_endpoint_payment",
                }
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
        proposal = self._host.propose_settlement(evaluation)
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
            accepted_at=accepted_at or datetime.now(timezone.utc).isoformat(),
        )
        if session.consumer_authorization_public_key is not None:
            from aidn_hypervisor.settlement.signing import verify_settlement_acceptance

            verify_settlement_acceptance(
                acceptance,
                consumer_public_key=session.consumer_authorization_public_key,
            )
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
    ):
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
        funding = self._host.force_finalize_fixed_price_settlement(
            evaluation,
            reason=reason,
            force_after=force_after,
            now=now,
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
            close_reason=f"forced_{reason.lower()}",
            no_request=no_request,
        )
        self._host._persist_state()
        return {
            "evaluation": evaluation,
            "proposal": proposal,
            "funding": funding,
            "session_result": session_result,
        }
