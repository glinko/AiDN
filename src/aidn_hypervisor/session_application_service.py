from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from aidn_hypervisor.session_read_models import (
    build_session_accounting_payload,
    build_session_detail_payload,
    build_session_list_payload,
    build_session_result_payload,
    build_session_sweep_payload,
)

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
