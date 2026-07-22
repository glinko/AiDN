from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.endpoint_publications.models import (
    canonical_configuration_payload,
    configuration_hash_for_publication,
)
from aidn_hypervisor.endpoints.models import CreateEndpointCommand, UpdateEndpointCommand
from aidn_hypervisor.settlement.models import SessionSettlementAcceptance
from pydantic import BaseModel, Field


class AttachProxyTargetRequest(BaseModel):
    remote_endpoint_id: str


class OpenSessionRequest(BaseModel):
    client_wallet: str
    deposit_q: float


class OpenMvpFixedPriceSessionRequest(BaseModel):
    client_wallet: str
    deposit_q_atoms: int = Field(gt=0)
    fixed_price_q_atoms: int = Field(ge=0)
    network_fee_reserve_q_atoms: int = Field(default=0, ge=0)
    consumer_authorization_public_key: str | None = None
    consumer_authorization: dict | None = None


class FinalizeMvpFixedPriceSessionRequest(BaseModel):
    request_id: str = Field(min_length=1)
    consumer_signature: str = Field(min_length=1)
    accepted_at: str | None = Field(default=None, min_length=1)
    actual_network_fees_q_atoms: int = Field(default=0, ge=0)


class PreviewMvpSettlementAcceptanceRequest(BaseModel):
    request_id: str = Field(min_length=1)
    accepted_at: str = Field(min_length=1)
    actual_network_fees_q_atoms: int = Field(default=0, ge=0)


class ForceFinalizeMvpFixedPriceSessionRequest(BaseModel):
    reason: str = Field(min_length=1)
    force_after: str = Field(min_length=1)
    request_id: str | None = Field(default=None, min_length=1)
    now: str | None = Field(default=None, min_length=1)
    actual_network_fees_q_atoms: int = Field(default=0, ge=0)


class MvpPaidSmokeRequest(BaseModel):
    client_wallet: str = Field(min_length=1)
    deposit_q_atoms: int = Field(gt=0)
    fixed_price_q_atoms: int = Field(ge=0)
    network_fee_reserve_q_atoms: int = Field(default=0, ge=0)
    task_type: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    request_id: str | None = Field(default=None, min_length=1)
    auto_finalize: bool = True
    consumer_signature: str = Field(default="mvp-smoke-consumer-signed", min_length=1)
    actual_network_fees_q_atoms: int = Field(default=0, ge=0)


def build_endpoint_router(
    service,
    hypervisor_service=None,
    endpoint_publication_service=None,
    remote_endpoint_service=None,
    session_service=None,
    validation_service=None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/endpoints")

    def _ok(data: dict, *, status_code: int = 200) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "data": data,
                "error": None,
                "correlation_id": str(uuid4()),
            },
        )

    def _error(
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict | None = None,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "data": None,
                "error": {
                    "code": code,
                    "message": message,
                    **({"details": details} if details is not None else {}),
                },
                "correlation_id": str(uuid4()),
            },
        )

    def _local_publication_configuration_hash(endpoint) -> str:
        payload = canonical_configuration_payload(
            bundle_hash=endpoint.bundle_hash,
            model_class=endpoint.model_class,
            capabilities=endpoint.capabilities,
            runtime=endpoint.runtime.model_dump(mode="json"),
            publication=endpoint.publication.model_dump(mode="json"),
            pricing=endpoint.pricing.model_dump(mode="json"),
            session=endpoint.session.model_dump(mode="json"),
            execution={
                "strategy": endpoint.execution_strategy,
                "runtime_binding_id": endpoint.runtime_binding_id,
            },
        )
        return configuration_hash_for_publication(payload)

    def _public_session_publication_guard(endpoint) -> str | None:
        if endpoint_publication_service is None:
            return "Endpoint publication service is not configured"
        current_publication = endpoint_publication_service.current_publication(
            endpoint.endpoint_id
        )
        if current_publication is None:
            return "Public MVP Session requires a currently published Endpoint configuration"
        local_publication_configuration_hash = _local_publication_configuration_hash(
            endpoint
        )
        if local_publication_configuration_hash != current_publication.configuration_hash:
            return (
                "Public MVP Session requires the live Endpoint configuration to match "
                "the current published configuration"
            )
        if not (
            current_publication.publication.get("accepts_external_requests", False)
            or current_publication.publication.get("visibility") == "public"
        ):
            return (
                "Public MVP Session requires a published Endpoint configuration that "
                "accepts external requests"
            )
        return None

    @router.get("")
    async def list_endpoints() -> JSONResponse:
        items = [item.model_dump(mode="json") for item in service.list_endpoints()]
        return _ok({"items": items})

    @router.post("", status_code=201)
    async def create_endpoint(payload: dict) -> JSONResponse:
        command_data = dict(payload)
        runtime_binding_id = command_data.get("runtime_binding_id")
        if runtime_binding_id and hypervisor_service is not None:
            try:
                admission = hypervisor_service.runtime_binding_endpoint_admission(
                    str(runtime_binding_id),
                    endpoint_payload=command_data,
                )
            except KeyError:
                return _error(
                    404,
                    "runtime_binding_not_found",
                    f"Unknown runtime binding: {runtime_binding_id}",
                )
            if not admission["ready"]:
                return _error(
                    409,
                    "endpoint_admission_blocked",
                    "Endpoint draft cannot be created from this Runtime Binding yet.",
                    details=admission,
                )
            try:
                compatibility_bundle = hypervisor_service.bundle_for_runtime_binding(
                    str(runtime_binding_id)
                )
            except KeyError:
                return _error(
                    404,
                    "runtime_binding_not_found",
                    f"Unknown runtime binding: {runtime_binding_id}",
                )
            command_data["bundle_id"] = compatibility_bundle.bundle_id
            command_data["bundle_hash"] = command_data.get("bundle_hash") or (
                hypervisor_service.bundle_hash_for_runtime_binding(
                    str(runtime_binding_id)
                )
            )
        command = CreateEndpointCommand(**command_data)
        created = service.create_endpoint(command)
        onboarding = None
        if hypervisor_service is not None:
            onboarding = hypervisor_service.sync_operator_onboarding_state(
                endpoint_items=[
                    {
                        "endpoint_id": created.endpoint.endpoint_id,
                        "bundle_id": created.endpoint.bundle_id,
                        "publication_status": "configured",
                        "visibility": created.endpoint.publication.visibility,
                    }
                ]
            )
        return _ok(
            {
                "endpoint": created.endpoint.model_dump(mode="json"),
                "snapshot": created.snapshot.model_dump(mode="json"),
                "onboarding": onboarding,
            },
            status_code=201,
        )

    @router.get("/{endpoint_id}")
    async def get_endpoint(endpoint_id: str) -> JSONResponse:
        try:
            result = service.get_endpoint(endpoint_id)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        return _ok({"endpoint": result.endpoint.model_dump(mode="json")})

    @router.patch("/{endpoint_id}")
    async def update_endpoint(
        endpoint_id: str,
        command: UpdateEndpointCommand,
    ) -> JSONResponse:
        if command.endpoint_id != endpoint_id:
            command = command.model_copy(update={"endpoint_id": endpoint_id})
        try:
            current = service.get_endpoint(endpoint_id).endpoint
            updated = service.update_endpoint(command)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        if (
            validation_service is not None
            and updated.snapshot is not None
            and current.configuration_hash != updated.endpoint.configuration_hash
        ):
            validation_service.supersede_configuration(
                endpoint_id=endpoint_id,
                previous_configuration_hash=current.configuration_hash,
                replacement_configuration_hash=updated.endpoint.configuration_hash,
                superseded_at=updated.snapshot.created_at,
            )
        return _ok(
            {
                "endpoint": updated.endpoint.model_dump(mode="json"),
                "snapshot": (
                    updated.snapshot.model_dump(mode="json")
                    if updated.snapshot is not None
                    else None
                ),
            }
        )

    @router.post("/{endpoint_id}/proxy-target")
    async def attach_proxy_target(
        endpoint_id: str,
        request: AttachProxyTargetRequest,
    ) -> JSONResponse:
        if remote_endpoint_service is None:
            return _error(
                503,
                "remote_endpoint_unavailable",
                "Remote endpoint service is not configured",
            )
        try:
            remote_endpoint = remote_endpoint_service.get_remote_endpoint(
                request.remote_endpoint_id
            )
        except KeyError:
            return _error(
                404,
                "remote_endpoint_not_found",
                f"Unknown remote endpoint: {request.remote_endpoint_id}",
            )
        try:
            current = service.get_endpoint(endpoint_id).endpoint
            updated = service.attach_proxy_target(endpoint_id, remote_endpoint)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        if (
            validation_service is not None
            and updated.snapshot is not None
            and current.configuration_hash != updated.endpoint.configuration_hash
        ):
            validation_service.supersede_configuration(
                endpoint_id=endpoint_id,
                previous_configuration_hash=current.configuration_hash,
                replacement_configuration_hash=updated.endpoint.configuration_hash,
                superseded_at=updated.snapshot.created_at,
            )
        return _ok(
            {
                "endpoint": updated.endpoint.model_dump(mode="json"),
                "snapshot": (
                    updated.snapshot.model_dump(mode="json")
                    if updated.snapshot is not None
                    else None
                ),
            }
        )

    @router.delete("/{endpoint_id}/proxy-target")
    async def detach_proxy_target(endpoint_id: str) -> JSONResponse:
        try:
            current = service.get_endpoint(endpoint_id).endpoint
            updated = service.detach_proxy_target(endpoint_id)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        if (
            validation_service is not None
            and updated.snapshot is not None
            and current.configuration_hash != updated.endpoint.configuration_hash
        ):
            validation_service.supersede_configuration(
                endpoint_id=endpoint_id,
                previous_configuration_hash=current.configuration_hash,
                replacement_configuration_hash=updated.endpoint.configuration_hash,
                superseded_at=updated.snapshot.created_at,
            )
        return _ok(
            {
                "endpoint": updated.endpoint.model_dump(mode="json"),
                "snapshot": (
                    updated.snapshot.model_dump(mode="json")
                    if updated.snapshot is not None
                    else None
                ),
            }
        )

    @router.post("/{endpoint_id}/sessions", status_code=201)
    async def open_session(
        endpoint_id: str,
        request: OpenSessionRequest,
    ) -> JSONResponse:
        if session_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        try:
            endpoint = service.get_endpoint(endpoint_id).endpoint
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        try:
            accounting_contract = None
            if hypervisor_service is not None:
                try:
                    accounting_contract = hypervisor_service.accounting_contract_for_endpoint(
                        endpoint
                    )
                except KeyError:
                    accounting_contract = None
            result = session_service.open_session(
                endpoint_id=endpoint_id,
                client_wallet=request.client_wallet,
                provider_wallet=endpoint.owner_wallet,
                node_id="node-local",
                deposit_q=request.deposit_q,
                session_policy=endpoint.session.model_dump(mode="json"),
                accounting_contract=accounting_contract,
                endpoint_configuration_hash=endpoint.configuration_hash,
            )
        except ValueError as error:
            return _error(409, "session_open_rejected", str(error))
        return _ok(
            {
                "session": result.session.model_dump(mode="json"),
                "deposit": result.deposit.model_dump(mode="json"),
            },
            status_code=201,
        )

    @router.post("/{endpoint_id}/mvp-sessions", status_code=201)
    async def open_mvp_fixed_price_session(
        endpoint_id: str,
        request: OpenMvpFixedPriceSessionRequest,
    ) -> JSONResponse:
        if session_service is None or hypervisor_service is None:
            return _error(
                503,
                "mvp_session_unavailable",
                "MVP economic Session service is not configured",
            )
        try:
            endpoint = service.get_endpoint(endpoint_id).endpoint
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        try:
            accounting_contract = hypervisor_service.accounting_contract_for_endpoint(
                endpoint
            )
        except KeyError:
            accounting_contract = None
        try:
            session, deposit, funding = hypervisor_service.open_mvp_fixed_price_session(
                session_service=session_service,
                endpoint=endpoint,
                client_wallet=request.client_wallet,
                deposit_q_atoms=request.deposit_q_atoms,
                fixed_price_q_atoms=request.fixed_price_q_atoms,
                network_fee_reserve_q_atoms=request.network_fee_reserve_q_atoms,
                accounting_contract=accounting_contract,
                consumer_authorization_public_key=request.consumer_authorization_public_key,
                consumer_authorization=request.consumer_authorization,
            )
        except ValueError as error:
            return _error(409, "mvp_session_open_rejected", str(error))
        return _ok(
            {
                "session": session.model_dump(mode="json"),
                "deposit": deposit.model_dump(mode="json"),
                "funding": funding.model_dump(mode="json"),
            },
            status_code=201,
        )

    @router.post("/{endpoint_id}/public-mvp-sessions", status_code=201)
    async def open_public_mvp_fixed_price_session(
        endpoint_id: str,
        request: OpenMvpFixedPriceSessionRequest,
    ) -> JSONResponse:
        if session_service is None or hypervisor_service is None:
            return _error(
                503,
                "mvp_session_unavailable",
                "MVP economic Session service is not configured",
            )
        try:
            endpoint = service.get_endpoint(endpoint_id).endpoint
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        publication_guard_error = _public_session_publication_guard(endpoint)
        if publication_guard_error is not None:
            return _error(
                409,
                "public_mvp_session_open_rejected",
                publication_guard_error,
            )
        try:
            accounting_contract = hypervisor_service.accounting_contract_for_endpoint(
                endpoint
            )
        except KeyError:
            accounting_contract = None
        try:
            session, deposit, funding = hypervisor_service.open_mvp_fixed_price_session(
                session_service=session_service,
                endpoint=endpoint,
                client_wallet=request.client_wallet,
                deposit_q_atoms=request.deposit_q_atoms,
                fixed_price_q_atoms=request.fixed_price_q_atoms,
                network_fee_reserve_q_atoms=request.network_fee_reserve_q_atoms,
                accounting_contract=accounting_contract,
                consumer_authorization=request.consumer_authorization,
                require_wallet_authorization=True,
            )
        except ValueError as error:
            return _error(409, "public_mvp_session_open_rejected", str(error))
        return _ok(
            {
                "session": session.model_dump(mode="json"),
                "deposit": deposit.model_dump(mode="json"),
                "funding": funding.model_dump(mode="json"),
            },
            status_code=201,
        )

    @router.post("/{endpoint_id}/mvp-paid-smoke")
    async def run_mvp_paid_smoke(
        endpoint_id: str,
        request: MvpPaidSmokeRequest,
    ) -> JSONResponse:
        if session_service is None or hypervisor_service is None:
            return _error(
                503,
                "mvp_session_unavailable",
                "MVP economic Session service is not configured",
            )
        try:
            endpoint = service.get_endpoint(endpoint_id).endpoint
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        try:
            accounting_contract = hypervisor_service.accounting_contract_for_endpoint(
                endpoint
            )
        except KeyError:
            accounting_contract = None
        try:
            session, deposit, funding = hypervisor_service.open_mvp_fixed_price_session(
                session_service=session_service,
                endpoint=endpoint,
                client_wallet=request.client_wallet,
                deposit_q_atoms=request.deposit_q_atoms,
                fixed_price_q_atoms=request.fixed_price_q_atoms,
                network_fee_reserve_q_atoms=request.network_fee_reserve_q_atoms,
                accounting_contract=accounting_contract,
            )
            task_constraints = {
                "endpoint_id": endpoint.endpoint_id,
                "session_id": session.session_id,
            }
            if request.request_id is not None:
                task_constraints["request_id"] = request.request_id
            task = hypervisor_service.submit(
                TaskRequest(
                    task_type=request.task_type,
                    payload=request.payload,
                    constraints=task_constraints,
                )
            )
            task_after_execution = hypervisor_service.get_task(task.task_id)
            runtime_request_id = request.request_id or task.task_id
            runtime_record = hypervisor_service.runtime_protocol_store.requests[
                runtime_request_id
            ]
            final_usage = hypervisor_service.runtime_protocol_store.usage_reports[
                runtime_record.terminal_final_usage_report_id
            ]
            settlement_evaluation = (
                hypervisor_service.build_mvp_fixed_price_settlement_evaluation(
                    session_service=session_service,
                    session_id=session.session_id,
                    request_id=runtime_request_id,
                    actual_network_fees_q_atoms=request.actual_network_fees_q_atoms,
                )
            )
            finalized = None
            if request.auto_finalize:
                finalized = hypervisor_service.finalize_mvp_fixed_price_session(
                    session_service=session_service,
                    session_id=session.session_id,
                    request_id=runtime_request_id,
                    consumer_signature=request.consumer_signature,
                    actual_network_fees_q_atoms=request.actual_network_fees_q_atoms,
                )
        except ValueError as error:
            return _error(409, "mvp_paid_smoke_rejected", str(error))
        except KeyError as error:
            return _error(
                409,
                "mvp_paid_smoke_evidence_missing",
                f"MVP paid smoke evidence is missing: {error}",
            )
        data = {
            "session": session.model_dump(mode="json"),
            "deposit": deposit.model_dump(mode="json"),
            "funding": funding.model_dump(mode="json"),
            "task": {
                "task_id": task_after_execution.task_id,
                "status": task_after_execution.status,
                "task_type": task_after_execution.request.task_type,
                "bundle_id": hypervisor_service.selected_bundle_id(
                    task_after_execution.task_id
                ),
                "result": hypervisor_service.task_result(task_after_execution.task_id),
            },
            "runtime_evidence": {
                "request": runtime_record.model_dump(mode="json"),
                "final_usage": final_usage.model_dump(mode="json"),
            },
            "settlement_readiness": {
                "ready": True,
                "proposal": settlement_evaluation.proposal.model_dump(mode="json"),
                "input_root": settlement_evaluation.input_set.settlement_input_root,
                "request_settlement_root": (
                    settlement_evaluation.input_set.request_settlement_root
                ),
                "usage_chain_root": settlement_evaluation.input_set.usage_chain_root,
            },
            "finalized": None,
        }
        if finalized is not None:
            data["finalized"] = {
                "proposal": finalized["proposal"].model_dump(mode="json"),
                "acceptance": finalized["acceptance"].model_dump(mode="json"),
                "funding": finalized["funding"].model_dump(mode="json"),
                "session": finalized["session_result"].session.model_dump(mode="json"),
                "deposit": finalized["session_result"].deposit.model_dump(mode="json"),
                "settlement": (
                    finalized["session_result"].settlement.model_dump(mode="json")
                    if finalized["session_result"].settlement is not None
                    else None
                ),
            }
        return _ok(data, status_code=201)

    @router.post("/{endpoint_id}/mvp-sessions/{session_id}/settlement-preview")
    async def preview_mvp_settlement_acceptance(
        endpoint_id: str,
        session_id: str,
        request: PreviewMvpSettlementAcceptanceRequest,
    ) -> JSONResponse:
        if session_service is None or hypervisor_service is None:
            return _error(503, "mvp_session_unavailable", "MVP economic Session service is not configured")
        try:
            session = session_service.store.get_session(session_id)
            if session.endpoint_id != endpoint_id:
                raise ValueError("MVP Session does not belong to this Endpoint")
            if session.consumer_authorization_public_key is None:
                raise ValueError("MVP Session has no Consumer authorization key")
            evaluation = hypervisor_service.build_mvp_fixed_price_settlement_evaluation(
                session_service=session_service,
                session_id=session_id,
                request_id=request.request_id,
                actual_network_fees_q_atoms=request.actual_network_fees_q_atoms,
            )
            proposal = evaluation.proposal
            acceptance = SessionSettlementAcceptance(
                settlement_id=proposal.settlement_id,
                session_id=session_id,
                settlement_input_root=proposal.settlement_input_root,
                accepted_endpoint_payment_q_atoms=proposal.final_endpoint_payment_q_atoms,
                accepted_consumer_refund_q_atoms=(proposal.consumer_payment_refund_q_atoms + proposal.consumer_fee_refund_q_atoms),
                accepted_network_fees_q_atoms=proposal.actual_network_fees_q_atoms,
                consumer_signature="ed25519:" + "00" * 64,
                accepted_at=request.accepted_at,
            )
        except (KeyError, ValueError) as error:
            return _error(409, "mvp_settlement_preview_rejected", str(error))
        return _ok({
            "proposal": proposal.model_dump(mode="json"),
            "acceptance_payload": acceptance.model_dump(
                mode="json", exclude={"consumer_signature", "acceptance_hash"}
            ),
        })

    @router.post("/{endpoint_id}/mvp-sessions/{session_id}/finalize")
    async def finalize_mvp_fixed_price_session(
        endpoint_id: str,
        session_id: str,
        request: FinalizeMvpFixedPriceSessionRequest,
    ) -> JSONResponse:
        if session_service is None or hypervisor_service is None:
            return _error(
                503,
                "mvp_session_unavailable",
                "MVP economic Session service is not configured",
            )
        try:
            session = session_service.store.get_session(session_id)
        except KeyError:
            return _error(404, "session_not_found", f"Unknown session: {session_id}")
        if session.endpoint_id != endpoint_id:
            return _error(
                409,
                "mvp_session_endpoint_mismatch",
                "MVP Session does not belong to this Endpoint",
            )
        try:
            finalized = hypervisor_service.finalize_mvp_fixed_price_session(
                session_service=session_service,
                session_id=session_id,
                request_id=request.request_id,
                consumer_signature=request.consumer_signature,
                actual_network_fees_q_atoms=request.actual_network_fees_q_atoms,
                accepted_at=request.accepted_at,
            )
        except ValueError as error:
            return _error(409, "mvp_session_finalize_rejected", str(error))
        return _ok(
            {
                "proposal": finalized["proposal"].model_dump(mode="json"),
                "acceptance": finalized["acceptance"].model_dump(mode="json"),
                "funding": finalized["funding"].model_dump(mode="json"),
                "session": finalized["session_result"].session.model_dump(mode="json"),
                "deposit": finalized["session_result"].deposit.model_dump(mode="json"),
                "settlement": (
                    finalized["session_result"].settlement.model_dump(mode="json")
                    if finalized["session_result"].settlement is not None
                    else None
                ),
            }
        )

    @router.post("/{endpoint_id}/mvp-sessions/{session_id}/force-finalize")
    async def force_finalize_mvp_fixed_price_session(
        endpoint_id: str,
        session_id: str,
        request: ForceFinalizeMvpFixedPriceSessionRequest,
    ) -> JSONResponse:
        if session_service is None or hypervisor_service is None:
            return _error(
                503,
                "mvp_session_unavailable",
                "MVP economic Session service is not configured",
            )
        try:
            session = session_service.store.get_session(session_id)
        except KeyError:
            return _error(404, "session_not_found", f"Unknown session: {session_id}")
        if session.endpoint_id != endpoint_id:
            return _error(
                409,
                "mvp_session_endpoint_mismatch",
                "MVP Session does not belong to this Endpoint",
            )
        try:
            finalized = hypervisor_service.force_finalize_mvp_fixed_price_session(
                session_service=session_service,
                session_id=session_id,
                reason=request.reason,
                force_after=request.force_after,
                request_id=request.request_id,
                now=request.now,
                actual_network_fees_q_atoms=request.actual_network_fees_q_atoms,
            )
        except ValueError as error:
            return _error(409, "mvp_session_force_finalize_rejected", str(error))
        return _ok(
            {
                "proposal": finalized["proposal"].model_dump(mode="json"),
                "funding": finalized["funding"].model_dump(mode="json"),
                "session": finalized["session_result"].session.model_dump(mode="json"),
                "deposit": finalized["session_result"].deposit.model_dump(mode="json"),
                "settlement": (
                    finalized["session_result"].settlement.model_dump(mode="json")
                    if finalized["session_result"].settlement is not None
                    else None
                ),
            }
        )

    return router
