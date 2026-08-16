from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from aidn_hypervisor.endpoint_publications.models import (
    canonical_configuration_payload,
    configuration_hash_for_publication,
)
from aidn_hypervisor.endpoint_publications.signing import verify_publication_signature
from aidn_hypervisor.endpoints.endpoint_application_service import (
    EndpointApplicationService,
    RemoteEndpointNotFoundError,
)
from aidn_hypervisor.endpoints.models import (
    EndpointMarketplaceDescription,
    UpdateEndpointCommand,
)
from aidn_hypervisor.endpoints.mvp_session_application_service import (
    MvpPaidSmokeEvidenceMissingError,
    MvpSessionApplicationService,
)
from aidn_hypervisor.endpoints.service import EndpointStateError
from aidn_hypervisor.session_application_service import SessionApplicationService


class AttachProxyTargetRequest(BaseModel):
    remote_endpoint_id: str


class OpenSessionRequest(BaseModel):
    client_wallet: str
    deposit_q: float


class OpenMvpFixedPriceSessionRequest(BaseModel):
    client_wallet: str
    session_id: str | None = Field(default=None, min_length=1)
    deposit_q_atoms: int = Field(gt=0)
    fixed_price_q_atoms: int = Field(ge=0)
    network_fee_reserve_q_atoms: int = Field(default=0, ge=0)
    consumer_authorization_public_key: str | None = None
    consumer_authorization: dict | None = None
    consensus_sender_sequence: int | None = Field(default=None, ge=1)
    consensus_lock_signatures: list[str] | None = None


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
    consensus_sender_sequence: int | None = Field(default=None, ge=1)
    consensus_lock_signatures: list[str] | None = None
    consensus_failure_signatures: list[str] | None = None
    consensus_initiator_wallet: str | None = Field(default=None, min_length=1)
    consensus_initiator_signature: str | None = Field(default=None, min_length=1)
    consensus_observed_at: str | None = Field(default=None, min_length=1)
    consensus_force_signatures: list[str] | None = None


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


class MarketplaceDescriptionPreviewRequest(BaseModel):
    html: str = Field(min_length=1)


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

    def _publication_execution_payload(endpoint) -> dict:
        execution = {
            "strategy": endpoint.execution_strategy,
            "runtime_binding_id": endpoint.runtime_binding_id,
        }
        if endpoint.execution_strategy != "proxy" or endpoint.proxy_target is None:
            return execution
        execution["target_fingerprint"] = configuration_hash_for_publication(
            {
                "remote_endpoint_id": endpoint.proxy_target.remote_endpoint_id,
                "source_publication_id": endpoint.proxy_target.source_publication_id,
                "source_configuration_hash": endpoint.proxy_target.source_configuration_hash,
            }
        )
        return execution

    def _local_publication_configuration_hash(endpoint) -> str:
        payload = canonical_configuration_payload(
            bundle_hash=endpoint.bundle_hash,
            model_class=endpoint.model_class,
            capabilities=endpoint.capabilities,
            runtime=endpoint.runtime.model_dump(mode="json"),
            publication=endpoint.publication.model_dump(mode="json"),
            pricing=endpoint.pricing.model_dump(mode="json"),
            session=endpoint.session.model_dump(mode="json"),
            execution=_publication_execution_payload(endpoint),
            profile=endpoint.profile.model_dump(mode="json"),
            local_agent_use=endpoint.local_agent_use,
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
        if not current_publication.owner_public_key:
            return (
                "Public MVP Session requires a cryptographically signed Endpoint "
                "configuration"
            )
        owner_identity = hypervisor_service.resolve_wallet_identity(
            current_publication.owner_wallet
        )
        if owner_identity is None:
            return "Public MVP Session requires a registered Endpoint owner wallet identity"
        if owner_identity["public_key"] != current_publication.owner_public_key:
            return (
                "Public MVP Session rejects an Endpoint publication whose signing key "
                "does not match the owner wallet identity"
            )
        try:
            verify_publication_signature(
                public_key=current_publication.owner_public_key,
                signature=current_publication.wallet_signature,
                payload=current_publication.signed_payload(),
            )
        except ValueError:
            return "Public MVP Session rejects an invalid Endpoint publication signature"
        if (
            endpoint.execution_strategy == "proxy"
            and endpoint.proxy_target is not None
            and (
                endpoint.proxy_target.publication_verification != "VERIFIED"
                or not endpoint.proxy_target.source_owner_public_key
                or not endpoint.proxy_target.source_wallet_signature
            )
        ):
            return (
                "Public MVP Session requires a verified remote Endpoint publication "
                "for proxy execution"
            )
        if endpoint.execution_strategy == "proxy" and endpoint.proxy_target is not None:
            if remote_endpoint_service is None:
                return (
                    "Public MVP Session requires the remote Endpoint catalog "
                    "for proxy binding verification"
                )
            try:
                remote_reference = remote_endpoint_service.get_remote_endpoint(
                    endpoint.proxy_target.remote_endpoint_id
                )
            except KeyError:
                return (
                    "Public MVP Session rejects a proxy target missing from the "
                    "remote Endpoint catalog"
                )
            target = endpoint.proxy_target
            if any(
                (
                    target.source_node_id != remote_reference.source_node_id,
                    target.source_endpoint_id != remote_reference.source_endpoint_id,
                    target.source_publication_id != remote_reference.source_publication_id,
                    target.source_configuration_hash
                    != remote_reference.source_configuration_hash,
                    target.source_owner_public_key
                    != remote_reference.source_owner_public_key,
                    target.source_wallet_signature
                    != remote_reference.source_wallet_signature,
                    target.publication_verification
                    != remote_reference.publication_verification,
                )
            ):
                return (
                    "Public MVP Session rejects a stale proxy target whose remote "
                    "publication proof no longer matches the catalog"
                )
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

    mvp_session_application_service = (
        MvpSessionApplicationService(
            endpoint_service=service,
            hypervisor_service=hypervisor_service,
            session_service=session_service,
            public_session_publication_guard=_public_session_publication_guard,
        )
        if session_service is not None and hypervisor_service is not None
        else None
    )
    endpoint_application_service = EndpointApplicationService(
        endpoint_service=service,
        hypervisor_service=hypervisor_service,
        endpoint_publication_service=endpoint_publication_service,
        remote_endpoint_service=remote_endpoint_service,
        validation_service=validation_service,
    )
    session_application_service = (
        SessionApplicationService(
            hypervisor_service=hypervisor_service,
            session_service=session_service,
            endpoint_service=service,
        )
        if session_service is not None
        else None
    )

    @router.get("")
    async def list_endpoints() -> JSONResponse:
        items = [item.model_dump(mode="json") for item in service.list_endpoints()]
        return _ok({"items": items})

    @router.post("/marketplace-description/preview")
    async def preview_marketplace_description(
        request: MarketplaceDescriptionPreviewRequest,
    ) -> JSONResponse:
        try:
            description = EndpointMarketplaceDescription(html=request.html)
        except ValueError as error:
            return _error(
                422,
                "marketplace_description_invalid",
                str(error),
            )
        return _ok(
            {
                "description": description.model_dump(mode="json"),
                "rendered_html": description.html,
            }
        )

    @router.post("", status_code=201)
    async def create_endpoint(payload: dict) -> JSONResponse:
        runtime_binding_id = payload.get("runtime_binding_id")
        try:
            result = endpoint_application_service.create_endpoint(payload)
        except KeyError:
            return _error(
                404,
                "runtime_binding_not_found",
                f"Unknown runtime binding: {runtime_binding_id}",
            )
        except ValueError as error:
            if str(error) == "endpoint_admission_blocked":
                admission = hypervisor_service.runtime_binding_endpoint_admission(
                    str(runtime_binding_id),
                    endpoint_payload=dict(payload),
                )
                return _error(
                    409,
                    "endpoint_admission_blocked",
                    "Endpoint draft cannot be created from this Runtime Binding yet.",
                    details=admission,
                )
            raise
        open_status = (
            202 if result["payload"].get("status") == "CONSENSUS_PENDING" else 201
        )
        return _ok(result["payload"], status_code=open_status)

    @router.get("/{endpoint_id}")
    async def get_endpoint(endpoint_id: str) -> JSONResponse:
        try:
            result = service.get_endpoint(endpoint_id)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        return _ok({"endpoint": result.endpoint.model_dump(mode="json")})

    @router.delete("/{endpoint_id}")
    async def delete_endpoint(endpoint_id: str) -> JSONResponse:
        try:
            result = endpoint_application_service.delete_endpoint(endpoint_id)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        except EndpointStateError as error:
            return _error(409, "endpoint_state_conflict", str(error))
        return _ok(result["payload"])

    @router.patch("/{endpoint_id}")
    async def update_endpoint(
        endpoint_id: str,
        command: UpdateEndpointCommand,
    ) -> JSONResponse:
        try:
            result = endpoint_application_service.update_endpoint(endpoint_id, command)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        except ValueError as error:
            return _error(409, "endpoint_update_requires_consensus", str(error))
        return _ok(result["payload"])

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
            result = endpoint_application_service.attach_proxy_target(
                endpoint_id,
                request.remote_endpoint_id,
            )
        except RemoteEndpointNotFoundError:
            return _error(
                404,
                "remote_endpoint_not_found",
                f"Unknown remote endpoint: {request.remote_endpoint_id}",
            )
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        return _ok(result["payload"])

    @router.delete("/{endpoint_id}/proxy-target")
    async def detach_proxy_target(endpoint_id: str) -> JSONResponse:
        try:
            result = endpoint_application_service.detach_proxy_target(endpoint_id)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        return _ok(result["payload"])

    @router.post("/{endpoint_id}/sessions", status_code=201)
    async def open_session(
        endpoint_id: str,
        request: OpenSessionRequest,
    ) -> JSONResponse:
        if session_application_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        try:
            result = session_application_service.open_session(
                endpoint_id=endpoint_id,
                client_wallet=request.client_wallet,
                deposit_q=request.deposit_q,
            )
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        except ValueError as error:
            return _error(409, "session_open_rejected", str(error))
        open_status = (
            202 if result["payload"].get("status") == "CONSENSUS_PENDING" else 201
        )
        return _ok(result["payload"], status_code=open_status)

    @router.post("/{endpoint_id}/mvp-sessions", status_code=201)
    async def open_mvp_fixed_price_session(
        endpoint_id: str,
        request: OpenMvpFixedPriceSessionRequest,
    ) -> JSONResponse:
        if mvp_session_application_service is None:
            return _error(
                503,
                "mvp_session_unavailable",
                "MVP economic Session service is not configured",
            )
        try:
            result = mvp_session_application_service.open_fixed_price_session(
                endpoint_id=endpoint_id,
                client_wallet=request.client_wallet,
                session_id=request.session_id,
                deposit_q_atoms=request.deposit_q_atoms,
                fixed_price_q_atoms=request.fixed_price_q_atoms,
                network_fee_reserve_q_atoms=request.network_fee_reserve_q_atoms,
                consumer_authorization_public_key=request.consumer_authorization_public_key,
                consumer_authorization=request.consumer_authorization,
                consensus_sender_sequence=request.consensus_sender_sequence,
                consensus_lock_signatures=request.consensus_lock_signatures,
            )
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        except ValueError as error:
            return _error(409, "mvp_session_open_rejected", str(error))
        open_status = (
            202 if result["payload"].get("status") == "CONSENSUS_PENDING" else 201
        )
        return _ok(result["payload"], status_code=open_status)

    @router.post("/{endpoint_id}/public-mvp-sessions", status_code=201)
    async def open_public_mvp_fixed_price_session(
        endpoint_id: str,
        request: OpenMvpFixedPriceSessionRequest,
    ) -> JSONResponse:
        if mvp_session_application_service is None:
            return _error(
                503,
                "mvp_session_unavailable",
                "MVP economic Session service is not configured",
            )
        try:
            result = mvp_session_application_service.open_fixed_price_session(
                endpoint_id=endpoint_id,
                client_wallet=request.client_wallet,
                session_id=request.session_id,
                deposit_q_atoms=request.deposit_q_atoms,
                fixed_price_q_atoms=request.fixed_price_q_atoms,
                network_fee_reserve_q_atoms=request.network_fee_reserve_q_atoms,
                consumer_authorization=request.consumer_authorization,
                consensus_sender_sequence=request.consensus_sender_sequence,
                consensus_lock_signatures=request.consensus_lock_signatures,
                require_published_configuration=True,
                require_wallet_authorization=True,
            )
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        except ValueError as error:
            return _error(409, "public_mvp_session_open_rejected", str(error))
        open_status = (
            202 if result["payload"].get("status") == "CONSENSUS_PENDING" else 201
        )
        return _ok(result["payload"], status_code=open_status)

    @router.post("/{endpoint_id}/mvp-paid-smoke")
    async def run_mvp_paid_smoke(
        endpoint_id: str,
        request: MvpPaidSmokeRequest,
    ) -> JSONResponse:
        if mvp_session_application_service is None:
            return _error(
                503,
                "mvp_session_unavailable",
                "MVP economic Session service is not configured",
            )
        try:
            result = mvp_session_application_service.run_paid_smoke(
                endpoint_id=endpoint_id,
                client_wallet=request.client_wallet,
                deposit_q_atoms=request.deposit_q_atoms,
                fixed_price_q_atoms=request.fixed_price_q_atoms,
                network_fee_reserve_q_atoms=request.network_fee_reserve_q_atoms,
                task_type=request.task_type,
                payload=request.payload,
                request_id=request.request_id,
                auto_finalize=request.auto_finalize,
                consumer_signature=request.consumer_signature,
                actual_network_fees_q_atoms=request.actual_network_fees_q_atoms,
            )
        except MvpPaidSmokeEvidenceMissingError as error:
            return _error(
                409,
                "mvp_paid_smoke_evidence_missing",
                f"MVP paid smoke evidence is missing: {error}",
            )
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        except ValueError as error:
            return _error(409, "mvp_paid_smoke_rejected", str(error))
        return _ok(result["payload"], status_code=201)

    @router.post("/{endpoint_id}/mvp-sessions/{session_id}/settlement-preview")
    async def preview_mvp_settlement_acceptance(
        endpoint_id: str,
        session_id: str,
        request: PreviewMvpSettlementAcceptanceRequest,
    ) -> JSONResponse:
        if mvp_session_application_service is None:
            return _error(
                503,
                "mvp_session_unavailable",
                "MVP economic Session service is not configured",
            )
        try:
            result = mvp_session_application_service.preview_settlement_acceptance(
                endpoint_id=endpoint_id,
                session_id=session_id,
                request_id=request.request_id,
                accepted_at=request.accepted_at,
                actual_network_fees_q_atoms=request.actual_network_fees_q_atoms,
            )
        except (KeyError, ValueError) as error:
            return _error(409, "mvp_settlement_preview_rejected", str(error))
        return _ok(result["payload"])

    @router.post("/{endpoint_id}/mvp-sessions/{session_id}/finalize")
    async def finalize_mvp_fixed_price_session(
        endpoint_id: str,
        session_id: str,
        request: FinalizeMvpFixedPriceSessionRequest,
    ) -> JSONResponse:
        if mvp_session_application_service is None:
            return _error(
                503,
                "mvp_session_unavailable",
                "MVP economic Session service is not configured",
            )
        try:
            result = mvp_session_application_service.finalize_session(
                endpoint_id=endpoint_id,
                session_id=session_id,
                request_id=request.request_id,
                consumer_signature=request.consumer_signature,
                accepted_at=request.accepted_at,
                actual_network_fees_q_atoms=request.actual_network_fees_q_atoms,
            )
        except KeyError:
            return _error(404, "session_not_found", f"Unknown session: {session_id}")
        except ValueError as error:
            code = (
                "mvp_session_endpoint_mismatch"
                if str(error) == "MVP Session does not belong to this Endpoint"
                else "mvp_session_finalize_rejected"
            )
            return _error(409, code, str(error))
        return _ok(result["payload"])

    @router.post("/{endpoint_id}/mvp-sessions/{session_id}/force-finalize")
    async def force_finalize_mvp_fixed_price_session(
        endpoint_id: str,
        session_id: str,
        request: ForceFinalizeMvpFixedPriceSessionRequest,
    ) -> JSONResponse:
        if mvp_session_application_service is None:
            return _error(
                503,
                "mvp_session_unavailable",
                "MVP economic Session service is not configured",
            )
        try:
            result = mvp_session_application_service.force_finalize_session(
                endpoint_id=endpoint_id,
                session_id=session_id,
                reason=request.reason,
                force_after=request.force_after,
                request_id=request.request_id,
                now=request.now,
                actual_network_fees_q_atoms=request.actual_network_fees_q_atoms,
                consensus_sender_sequence=request.consensus_sender_sequence,
                consensus_lock_signatures=request.consensus_lock_signatures,
                consensus_failure_signatures=request.consensus_failure_signatures,
                consensus_initiator_wallet=request.consensus_initiator_wallet,
                consensus_initiator_signature=request.consensus_initiator_signature,
                consensus_observed_at=request.consensus_observed_at,
                consensus_force_signatures=request.consensus_force_signatures,
            )
        except KeyError:
            return _error(404, "session_not_found", f"Unknown session: {session_id}")
        except ValueError as error:
            code = (
                "mvp_session_endpoint_mismatch"
                if str(error) == "MVP Session does not belong to this Endpoint"
                else "mvp_session_force_finalize_rejected"
            )
            return _error(409, code, str(error))
        payload = result["payload"]
        return _ok(
            payload,
            status_code=(202 if payload.get("status") == "CONSENSUS_PENDING" else 200),
        )

    return router
