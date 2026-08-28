from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from aidn_hypervisor.pricing import Q_ATOMS_PER_Q, quote_rate_card
from aidn_hypervisor.session_read_models import (
    build_session_accounting_payload,
    build_session_detail_payload,
    build_session_list_payload,
    build_session_result_payload,
    build_session_sweep_payload,
)
from aidn_hypervisor.sessions.models import SessionAmendmentKind

if TYPE_CHECKING:
    from aidn_hypervisor.endpoints.service import EndpointService
    from aidn_hypervisor.service import HypervisorService
    from aidn_hypervisor.sessions.service import SessionService


class SessionApplicationService:
    """Application-layer orchestration for Session accounting and lifecycle actions."""

    def __init__(
        self,
        *,
        hypervisor_service: HypervisorService | None,
        session_service: SessionService,
        endpoint_service: EndpointService | None = None,
    ) -> None:
        self._hypervisor_service = hypervisor_service
        self._session_service = session_service
        self._endpoint_service = endpoint_service
        if hypervisor_service is not None:
            session_service.set_funding_amendment_verifier(
                self._verify_funding_amendment
            )

    def _verify_funding_amendment(
        self,
        *,
        session,
        amendment_kind: str,
        changes: dict,
    ) -> bool:
        if self._hypervisor_service is None:
            return False
        try:
            funding = self._hypervisor_service.get_session_funding_account(
                session.session_id
            )
        except KeyError:
            return False
        if funding.session_contract_hash != session.session_contract_hash:
            return False
        if funding.funding_state_hash != changes.get("next_funding_state_hash"):
            return False
        operation_id = changes.get("funding_operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            return False
        operations = self._hypervisor_service.ledger_operation_service.list_operations()
        operation = next(
            (
                item
                for item in operations
                if item.get("operation_id") == operation_id
                and item.get("operation_type") == "SESSION_ESCROW_EXTEND"
            ),
            None,
        )
        if operation is None:
            return False
        payload = operation.get("payload")
        if not isinstance(payload, dict):
            return False
        if payload.get("session_id") != session.session_id:
            return False
        if payload.get("funding_state_reference") != changes.get(
            "previous_funding_state_hash"
        ):
            return False
        next_funding = payload.get("funding")
        if not isinstance(next_funding, dict):
            return False
        if next_funding.get("funding_state_hash") != funding.funding_state_hash:
            return False
        if amendment_kind == "DEPOSIT_EXTENSION":
            return (
                int(payload.get("added_endpoint_payment_reserve_q_atoms", 0))
                == int(changes.get("additional_endpoint_payment_q_atoms", 0))
                and int(payload.get("added_network_fee_reserve_q_atoms", 0))
                == int(changes.get("additional_network_fee_q_atoms", 0))
            )
        return int(changes.get("maximum_session_charge_q_atoms", 0)) > 0

    def open_session(
        self,
        *,
        endpoint_id: str,
        client_wallet: str,
        deposit_q: float,
    ) -> dict:
        if self._endpoint_service is None:
            raise RuntimeError("Endpoint service is not configured")
        endpoint = self._endpoint_service.get_endpoint(endpoint_id).endpoint
        quote = quote_rate_card(endpoint.pricing.rate_card)
        try:
            deposit_atoms_value = Decimal(str(deposit_q)) * Q_ATOMS_PER_Q
        except (InvalidOperation, ValueError) as error:
            raise ValueError("Session deposit is not a valid Q amount") from error
        if (
            not deposit_atoms_value.is_finite()
            or deposit_atoms_value != deposit_atoms_value.to_integral_value()
        ):
            raise ValueError("Session deposit must map to whole q_atoms")
        deposit_q_atoms = int(deposit_atoms_value)
        accounting_contract = None
        if self._hypervisor_service is not None:
            try:
                accounting_contract = (
                    self._hypervisor_service.accounting_contract_for_endpoint(endpoint)
                )
            except KeyError:
                accounting_contract = None
        result = self._session_service.open_session(
            endpoint_id=endpoint_id,
            client_wallet=client_wallet,
            provider_wallet=endpoint.owner_wallet,
            node_id=(
                self._hypervisor_service.node_id
                if self._hypervisor_service is not None
                else "node-local"
            ),
            deposit_q=deposit_q,
            deposit_q_atoms=deposit_q_atoms,
            fixed_price_q_atoms=(
                quote.estimated_charge_q_atoms
                if not quote.missing_dimensions
                else None
            ),
            # The Consumer authorizes only the funds locked in escrow. The
            # operator does not publish a second per-request maximum.
            request_charge_ceiling_q_atoms=deposit_q_atoms,
            session_policy=endpoint.session.model_dump(mode="json"),
            accounting_contract=accounting_contract,
            endpoint_configuration_hash=endpoint.configuration_hash,
        )
        return {
            "session": result.session,
            "deposit": result.deposit,
            "payload": {
                "session": result.session.model_dump(mode="json"),
                "deposit": result.deposit.model_dump(mode="json"),
            },
        }

    def close_session(self, session_id: str):
        if self._hypervisor_service is None:
            raise RuntimeError("Hypervisor service is not configured")
        result = self._hypervisor_service.close_endpoint_session(session_id)
        return {
            "result": result,
            "payload": build_session_result_payload(result),
        }

    def sweep_idle_sessions(self, *, now: datetime | None = None):
        results = self._session_service.sweep_idle_sessions(now=now)
        if self._hypervisor_service is None:
            return {
                "results": results,
                "payload": build_session_sweep_payload(results),
            }
        for result in results:
            self._hypervisor_service.propagate_proxy_session_close(
                result.session.session_id
            )
        return {
            "results": results,
            "payload": build_session_sweep_payload(results),
        }

    def list_sessions(self) -> dict:
        return build_session_list_payload(self._session_service)

    def get_session_detail(self, *, session_id: str) -> dict:
        result = self._session_service.get_session(session_id)
        return {
            "result": result,
            "payload": build_session_detail_payload(result),
        }

    def record_usage_report(
        self,
        *,
        session_id: str,
        usage_report: dict,
        acknowledgement_timeout_seconds: int,
    ) -> dict:
        updated_session = self._session_service.record_usage_report(
            session_id,
            usage_report=usage_report,
            acknowledgement_timeout_seconds=acknowledgement_timeout_seconds,
        )
        session_accounting = build_session_accounting_payload(updated_session)
        return {
            "session": updated_session,
            "session_accounting": session_accounting,
            "conflicted": updated_session.accounting_status == "mismatch",
        }

    def record_usage_acknowledgement(
        self,
        *,
        session_id: str,
        usage_acknowledgement: dict,
        accepted_charge_q: float,
    ) -> dict:
        updated_session = self._session_service.record_usage_acknowledgement(
            session_id,
            usage_acknowledgement=usage_acknowledgement,
            accepted_charge_q=accepted_charge_q,
        )
        session_accounting = build_session_accounting_payload(updated_session)
        return {
            "session": updated_session,
            "session_accounting": session_accounting,
            "conflicted": updated_session.accounting_status == "mismatch",
        }

    def get_session_accounting(self, *, session_id: str) -> dict:
        result = self._session_service.get_session(session_id)
        return build_session_accounting_payload(result.session)

    def list_session_amendments(self, *, session_id: str) -> dict:
        session = self._session_service.get_session(session_id).session
        amendments = self._session_service.get_session_amendments(session_id)
        return {
            "session_id": session_id,
            "session_contract_hash": session.session_contract_hash,
            "effective_terms_hash": session.effective_terms_hash,
            "amendment_sequence": session.session_amendment_sequence,
            "items": [item.model_dump(mode="json") for item in amendments],
        }

    def export_session_contract(self, *, session_id: str) -> dict:
        exchange = self._session_service.export_session_contract(session_id)
        return exchange.model_dump(mode="json")

    def import_session_contract_exchange(self, *, exchange: dict) -> dict:
        return self._session_service.import_session_contract_exchange(exchange)

    def accept_session_amendment(
        self,
        *,
        session_id: str,
        amendment_id: str,
        amendment_kind: SessionAmendmentKind,
        changes: dict,
        consumer_signature: str,
        endpoint_signature: str,
        accepted_at: str | None = None,
    ) -> dict:
        session = self._session_service.accept_session_amendment(
            session_id,
            amendment_id=amendment_id,
            amendment_kind=amendment_kind,
            changes=changes,
            consumer_signature=consumer_signature,
            endpoint_signature=endpoint_signature,
            accepted_at=accepted_at,
        )
        amendments = self._session_service.get_session_amendments(session_id)
        amendment = next(
            item for item in amendments if item.amendment_id == amendment_id
        )
        result = self._session_service.get_session(session_id)
        return {
            "amendment": amendment.model_dump(mode="json"),
            "effective_terms_hash": session.effective_terms_hash,
            "payload": build_session_detail_payload(result),
        }
