from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.endpoints.mvp_session_read_models import (
    build_mvp_paid_smoke_payload,
    build_mvp_session_open_payload,
    build_mvp_settlement_finalize_payload,
    build_mvp_settlement_preview_payload,
)
from aidn_hypervisor.settlement.models import SessionSettlementAcceptance


class MvpPaidSmokeEvidenceMissingError(KeyError):
    """Raised when paid smoke execution completed without required runtime evidence."""


Q_ATOMS_PER_Q = Decimal("1000000")


class MvpSessionApplicationService:
    """Application-layer orchestration for MVP fixed-price Session flows."""

    def __init__(
        self,
        *,
        endpoint_service,
        hypervisor_service,
        session_service,
        public_session_publication_guard: Callable[[object], str | None] | None = None,
    ) -> None:
        self._endpoint_service = endpoint_service
        self._hypervisor_service = hypervisor_service
        self._session_service = session_service
        self._public_session_publication_guard = public_session_publication_guard

    def _get_endpoint(self, endpoint_id: str):
        return self._endpoint_service.get_endpoint(endpoint_id).endpoint

    def _accounting_contract_for_endpoint(self, endpoint):
        try:
            return self._hypervisor_service.accounting_contract_for_endpoint(endpoint)
        except KeyError:
            return None

    @staticmethod
    def _public_fixed_price_q_atoms(endpoint) -> int:
        """Return the exact atom price committed by a public MVP Endpoint."""
        fixed_price = endpoint.pricing.fixed_price
        if fixed_price is None:
            raise ValueError(
                "Public MVP Session requires an Endpoint fixed_price in the published configuration"
            )
        try:
            q_atoms = Decimal(str(fixed_price)) * Q_ATOMS_PER_Q
        except (InvalidOperation, ValueError) as error:
            raise ValueError("Endpoint fixed_price is not a valid Q amount") from error
        if q_atoms != q_atoms.to_integral_value():
            raise ValueError("Endpoint fixed_price must be expressible in whole q_atoms")
        return int(q_atoms)

    def open_fixed_price_session(
        self,
        *,
        endpoint_id: str,
        client_wallet: str,
        deposit_q_atoms: int,
        fixed_price_q_atoms: int,
        network_fee_reserve_q_atoms: int,
        consumer_authorization_public_key: str | None = None,
        consumer_authorization: dict | None = None,
        require_published_configuration: bool = False,
        require_wallet_authorization: bool = False,
    ) -> dict:
        endpoint = self._get_endpoint(endpoint_id)
        if require_published_configuration:
            guard = self._public_session_publication_guard
            if guard is None:
                raise ValueError("Endpoint publication service is not configured")
            guard_error = guard(endpoint)
            if guard_error is not None:
                raise ValueError(guard_error)
            advertised_fixed_price_q_atoms = self._public_fixed_price_q_atoms(endpoint)
            if fixed_price_q_atoms != advertised_fixed_price_q_atoms:
                raise ValueError(
                    "Public MVP Session fixed price must match the published Endpoint configuration"
                )
        accounting_contract = self._accounting_contract_for_endpoint(endpoint)
        session, deposit, funding = self._hypervisor_service.open_mvp_fixed_price_session(
            session_service=self._session_service,
            endpoint=endpoint,
            client_wallet=client_wallet,
            deposit_q_atoms=deposit_q_atoms,
            fixed_price_q_atoms=fixed_price_q_atoms,
            network_fee_reserve_q_atoms=network_fee_reserve_q_atoms,
            accounting_contract=accounting_contract,
            consumer_authorization_public_key=consumer_authorization_public_key,
            consumer_authorization=consumer_authorization,
            require_wallet_authorization=require_wallet_authorization,
        )
        return {
            "endpoint": endpoint,
            "session": session,
            "deposit": deposit,
            "funding": funding,
            "payload": build_mvp_session_open_payload(session, deposit, funding),
        }

    def run_paid_smoke(
        self,
        *,
        endpoint_id: str,
        client_wallet: str,
        deposit_q_atoms: int,
        fixed_price_q_atoms: int,
        network_fee_reserve_q_atoms: int,
        task_type: str,
        payload: dict,
        request_id: str | None = None,
        auto_finalize: bool = True,
        consumer_signature: str = "mvp-smoke-consumer-signed",
        actual_network_fees_q_atoms: int = 0,
    ) -> dict:
        opened = self.open_fixed_price_session(
            endpoint_id=endpoint_id,
            client_wallet=client_wallet,
            deposit_q_atoms=deposit_q_atoms,
            fixed_price_q_atoms=fixed_price_q_atoms,
            network_fee_reserve_q_atoms=network_fee_reserve_q_atoms,
        )
        endpoint = opened["endpoint"]
        session = opened["session"]
        deposit = opened["deposit"]
        funding = opened["funding"]

        task_constraints = {
            "endpoint_id": endpoint.endpoint_id,
            "session_id": session.session_id,
        }
        if request_id is not None:
            task_constraints["request_id"] = request_id
        task = self._hypervisor_service.submit(
            TaskRequest(
                task_type=task_type,
                payload=payload,
                constraints=task_constraints,
            )
        )
        task_after_execution = self._hypervisor_service.get_task(task.task_id)
        runtime_request_id = request_id or task.task_id
        try:
            runtime_record = self._hypervisor_service.runtime_protocol_store.requests[
                runtime_request_id
            ]
            final_usage = self._hypervisor_service.runtime_protocol_store.usage_reports[
                runtime_record.terminal_final_usage_report_id
            ]
        except KeyError as error:
            raise MvpPaidSmokeEvidenceMissingError(str(error)) from error
        settlement_evaluation = (
            self._hypervisor_service.build_mvp_fixed_price_settlement_evaluation(
                session_service=self._session_service,
                session_id=session.session_id,
                request_id=runtime_request_id,
                actual_network_fees_q_atoms=actual_network_fees_q_atoms,
            )
        )
        finalized = None
        if auto_finalize:
            finalized = self._hypervisor_service.finalize_mvp_fixed_price_session(
                session_service=self._session_service,
                session_id=session.session_id,
                request_id=runtime_request_id,
                consumer_signature=consumer_signature,
                actual_network_fees_q_atoms=actual_network_fees_q_atoms,
            )
        return {
            "payload": build_mvp_paid_smoke_payload(
                session=session,
                deposit=deposit,
                funding=funding,
                task=task_after_execution,
                bundle_id=self._hypervisor_service.selected_bundle_id(
                    task_after_execution.task_id
                ),
                result=self._hypervisor_service.task_result(task_after_execution.task_id),
                runtime_record=runtime_record,
                final_usage=final_usage,
                settlement_evaluation=settlement_evaluation,
                finalized=finalized,
            )
        }

    def preview_settlement_acceptance(
        self,
        *,
        endpoint_id: str,
        session_id: str,
        request_id: str,
        accepted_at: str,
        actual_network_fees_q_atoms: int = 0,
    ) -> dict:
        session = self._session_service.store.get_session(session_id)
        if session.endpoint_id != endpoint_id:
            raise ValueError("MVP Session does not belong to this Endpoint")
        if session.consumer_authorization_public_key is None:
            raise ValueError("MVP Session has no Consumer authorization key")
        evaluation = self._hypervisor_service.build_mvp_fixed_price_settlement_evaluation(
            session_service=self._session_service,
            session_id=session_id,
            request_id=request_id,
            actual_network_fees_q_atoms=actual_network_fees_q_atoms,
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
            consumer_signature="ed25519:" + "00" * 64,
            accepted_at=accepted_at,
        )
        return {"payload": build_mvp_settlement_preview_payload(proposal, acceptance)}

    def finalize_session(
        self,
        *,
        endpoint_id: str,
        session_id: str,
        request_id: str,
        consumer_signature: str,
        accepted_at: str | None = None,
        actual_network_fees_q_atoms: int = 0,
    ) -> dict:
        session = self._session_service.store.get_session(session_id)
        if session.endpoint_id != endpoint_id:
            raise ValueError("MVP Session does not belong to this Endpoint")
        finalized = self._hypervisor_service.finalize_mvp_fixed_price_session(
            session_service=self._session_service,
            session_id=session_id,
            request_id=request_id,
            consumer_signature=consumer_signature,
            actual_network_fees_q_atoms=actual_network_fees_q_atoms,
            accepted_at=accepted_at,
        )
        return {
            "payload": build_mvp_settlement_finalize_payload(
                finalized,
                include_acceptance=True,
            )
        }

    def force_finalize_session(
        self,
        *,
        endpoint_id: str,
        session_id: str,
        reason: str,
        force_after: str,
        request_id: str | None = None,
        now: str | None = None,
        actual_network_fees_q_atoms: int = 0,
    ) -> dict:
        session = self._session_service.store.get_session(session_id)
        if session.endpoint_id != endpoint_id:
            raise ValueError("MVP Session does not belong to this Endpoint")
        finalized = self._hypervisor_service.force_finalize_mvp_fixed_price_session(
            session_service=self._session_service,
            session_id=session_id,
            reason=reason,
            force_after=force_after,
            request_id=request_id,
            now=now,
            actual_network_fees_q_atoms=actual_network_fees_q_atoms,
        )
        return {
            "payload": build_mvp_settlement_finalize_payload(
                finalized,
                include_acceptance=False,
            )
        }
