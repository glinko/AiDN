"""Protected dashboard endpoints for local MCP agent credentials."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.dashboard_network_access import DashboardNetworkAccessService
from aidn_hypervisor.endpoint_publications.models import PublishedEndpointConfiguration
from aidn_hypervisor.endpoint_publications.signing import (
    sign_consensus_bytes,
    verify_publication_signature,
)
from aidn_hypervisor.endpoints.endpoint_application_service import EndpointApplicationService
from aidn_hypervisor.endpoints.models import (
    EndpointMarketplaceDescription,
    UpdateEndpointCommand,
)
from aidn_hypervisor.ledger.service import STANDARD_NETWORK_FEE_Q_ATOMS
from aidn_hypervisor.lifecycle_manager import LifecycleError
from aidn_hypervisor.mcp.credentials import (
    InferenceCredential,
    McpCredential,
    McpCredentialStore,
)
from aidn_hypervisor.mcp.enrollment import McpEnrollmentService
from aidn_hypervisor.mcp.permissions import (
    AGENT_MUTATION_SCOPES,
    DEFAULT_AGENT_READ_SCOPES,
    FULL_AGENT_CONTROL_SCOPES,
    normalize_agent_scopes,
    normalize_auto_approved_scopes,
    permission_catalog_payload,
)
from aidn_hypervisor.operator_access import DashboardAccessService
from aidn_hypervisor.operator_cometbft import control_managed_cometbft
from aidn_hypervisor.operator_cometbft_install import (
    apply_pending_cometbft_configuration,
    install_cometbft_from_dashboard,
    reconnect_cometbft_from_dashboard,
)
from aidn_hypervisor.resource_probe import refresh_resource_probe_from_environment
from aidn_hypervisor.wallet_identity import wallet_identity_registration_payload
from aidn_hypervisor.wallet_reconciliation import reconcile_pending_wallet_transfers

_COOKIE_NAME = "aidn_dashboard_access"
_COOKIE_PATH = "/operators/dashboard/access"
_BROWSER_KEY_HEADER = "X-AiDN-Browser-Key"
_COOKIE_MAX_AGE = {
    "ten_minutes": 10 * 60,
    "one_day": 24 * 60 * 60,
    "thirty_days": 30 * 24 * 60 * 60,
    "forever": 10 * 365 * 24 * 60 * 60,
}


class PairingRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    duration: str = Field(default="one_day", pattern="^(ten_minutes|one_day|thirty_days|forever)$")


class CredentialCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=96)
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_AGENT_READ_SCOPES), min_length=1, max_length=64)
    auto_approved_scopes: list[str] = Field(default_factory=list, max_length=64)


class CredentialScopeUpdateRequest(BaseModel):
    scopes: list[str] = Field(min_length=1, max_length=64)
    auto_approved_scopes: list[str] = Field(default_factory=list, max_length=64)


class InferenceCredentialCreateRequest(BaseModel):
    """Create an OpenAI-compatible token for one local owner endpoint."""

    label: str = Field(min_length=1, max_length=96)
    endpoint_id: str = Field(min_length=1, max_length=256)
    model_alias: str | None = Field(default=None, min_length=1, max_length=128)
    ttl_seconds: int | None = Field(default=None, ge=3600, le=31_536_000)


class EnrollmentCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=96)
    encryption_public_key: str = Field(min_length=40, max_length=128)


class ProviderAttachRequest(BaseModel):
    """Attach an already-running Provider through the paired Dashboard."""

    plugin_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    configuration: dict[str, Any] = Field(default_factory=dict)


class ProviderRuntimeInstallRequest(BaseModel):
    """Approve and apply one reviewed built-in runtime from the paired Dashboard."""

    configuration: dict[str, Any] = Field(default_factory=dict)
    operator_note: str | None = Field(default=None, max_length=500)
    upgrade_acknowledged: bool = False
    wait_for_completion: bool = True


class WalletBootstrapCreateRequest(BaseModel):
    label: str | None = Field(default=None, max_length=128)


class WalletBootstrapImportRequest(WalletBootstrapCreateRequest):
    private_key: str = Field(min_length=1, max_length=512)


class WalletTransferRequest(BaseModel):
    recipient_wallet: str = Field(min_length=1, max_length=256)
    amount_q_atoms: int = Field(gt=0)
    memo: str | None = Field(default=None, max_length=256)


class ModelInstallOperationRequest(BaseModel):
    provider_type: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=512)
    source_url: str = Field(min_length=1, max_length=2048)
    requested_by: str = Field(default="operator-dashboard", min_length=1, max_length=128)
    runtime_parameter_policy: dict[str, Any] = Field(default_factory=dict, max_length=16)
    resident_adapter_requested: bool = False
    resident_execution_profile: str | None = Field(default=None, max_length=32)
    resident_resource_request: dict[str, Any] = Field(default_factory=dict, max_length=16)
    resident_fallback_enabled: bool = True


class RegisterBundleOperationRequest(BaseModel):
    bundle_id: str = Field(min_length=1, max_length=128)
    workload_type: str = Field(min_length=1, max_length=128)
    endpoint: str = Field(min_length=1, max_length=2048)
    runtime_parameter_policy: dict[str, Any] | None = Field(default=None, max_length=16)


class MarketplaceDescriptionPreviewRequest(BaseModel):
    html: str = Field(min_length=1)


class ModelArtifactSetOperationRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=256)
    files: list[dict[str, Any]] = Field(min_length=1, max_length=512)


class BindModelArtifactSetOperationRequest(BaseModel):
    artifact_set_id: str = Field(min_length=1, max_length=128)


class MaterializeModelArtifactSetOperationRequest(BaseModel):
    artifact_set_id: str = Field(min_length=1, max_length=128)
    destination: str = Field(min_length=1, max_length=2048)


class RuntimeBindingOperationRequest(BaseModel):
    capability_id: str = Field(min_length=1, max_length=128)
    capability_version: str = Field(min_length=1, max_length=64)
    capability_definition_hash: str = Field(min_length=1, max_length=256)


class InstallationPlanApplyRequest(BaseModel):
    """Explicit browser confirmation for a persisted assisted setup plan."""

    plan_hash: str = Field(min_length=1, max_length=256)
    actor: str = Field(default="operator-dashboard", min_length=1, max_length=128)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    action: Literal[
        "prepare_review",
        "prepare_assisted_installation_review",
        "request_model_install",
    ] = "prepare_review"


class BundleRevisionOperationRequest(BaseModel):
    bundle_id: str = Field(min_length=1, max_length=128)
    overrides: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False


class DashboardNetworkAccessRequest(BaseModel):
    mode: Literal["loopback", "lan"]


class LocalAgentUseRequest(BaseModel):
    """A local-only inference permission; never part of endpoint publication."""

    enabled: bool


class LifecyclePlanRequest(BaseModel):
    """Browser-paired request for a lifecycle transition/removal plan."""

    object_type: str = Field(min_length=1, max_length=64)
    object_id: str = Field(min_length=1, max_length=256)
    action: Literal["DISABLE", "UNPUBLISH", "RETIRE"] | None = None
    cascade: bool = False
    actor: str = Field(default="operator-dashboard", min_length=1, max_length=128)


class LifecycleApplyRequest(BaseModel):
    plan_hash: str = Field(min_length=1, max_length=256)
    actor: str = Field(default="operator-dashboard", min_length=1, max_length=128)
    force: bool = False
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class RuntimeResetApplyRequest(BaseModel):
    reset_id: str = Field(min_length=1, max_length=128)
    plan_hash: str = Field(min_length=1, max_length=256)
    actor: str = Field(default="operator-dashboard", min_length=1, max_length=128)
    force: bool = False
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class ConsensusInstallRequest(BaseModel):
    """Only the reviewed, bounded CometBFT install choices reach the host."""

    mode: Literal["validator", "non_validator"] = "validator"
    chain_id: str = Field(default="aidn-localnet-1", min_length=1, max_length=96)
    version: str = Field(default="v0.38.19", pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    moniker: str | None = Field(default=None, max_length=96)
    rpc_host: Literal["127.0.0.1"] = "127.0.0.1"
    rpc_port: int = Field(default=26657, ge=1, le=65535)
    p2p_host: Literal["127.0.0.1", "0.0.0.0"] = "127.0.0.1"
    p2p_port: int = Field(default=26656, ge=1, le=65535)
    external_address: str = Field(default="", max_length=256)
    seeds: str = Field(default="", max_length=4096)
    persistent_peers: str = Field(default="", max_length=4096)
    abci_host: Literal["127.0.0.1"] = "127.0.0.1"
    abci_port: int = Field(default=26658, ge=1, le=65535)
    acknowledge_network_scope: bool = False


class ConsensusReconnectRequest(ConsensusInstallRequest):
    """Bounded request for joining an existing private CometBFT network."""

    source_rpc: str = Field(min_length=1, max_length=256)
    acknowledge_reset: bool = False


def _credential_payload(credential: McpCredential, *, reveal: bool = False) -> dict:
    payload = asdict(credential)
    if not reveal:
        payload.pop("token", None)
    return payload


def _inference_credential_payload(credential: InferenceCredential, *, reveal: bool = False) -> dict:
    payload = asdict(credential)
    if not reveal:
        payload.pop("token", None)
    return payload


def build_operator_access_router(
    *,
    access_service: DashboardAccessService | None,
    credential_store: McpCredentialStore | None,
    allow_insecure_lan: bool,
    enrollment_service: McpEnrollmentService | None = None,
    operator_fingerprint: str | None = None,
    invalidate_credential_sessions: Callable[[str], None] | None = None,
    hypervisor_service: Any | None = None,
    endpoint_service: Any | None = None,
    endpoint_publication_service: Any | None = None,
    remote_endpoint_service: Any | None = None,
    validation_service: Any | None = None,
    network_access_service: DashboardNetworkAccessService | None = None,
    session_service: Any | None = None,
) -> APIRouter:
    """Build a browser-only credential management boundary."""
    router = APIRouter(prefix="/operators/dashboard/access")
    network_access = network_access_service or DashboardNetworkAccessService()

    def session_expiry(request: Request) -> str | None:
        if access_service is None:
            return None
        return access_service.session_expiry(
            request.cookies.get(_COOKIE_NAME),
            browser_key=request.headers.get(_BROWSER_KEY_HEADER),
        )

    def require_session(request: Request) -> JSONResponse | None:
        if access_service is None or not access_service.authorize(
            request.cookies.get(_COOKIE_NAME), browser_key=request.headers.get(_BROWSER_KEY_HEADER)
        ):
            return JSONResponse(status_code=401, content={"error": {"code": "DASHBOARD_ACCESS_REQUIRED"}})
        if not allow_insecure_lan and request.url.scheme != "https":
            return JSONResponse(status_code=426, content={"error": {"code": "DASHBOARD_ACCESS_TLS_REQUIRED"}})
        return None

    def enrollment_payload(item) -> dict:
        return asdict(item)

    def operation_error(error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "DASHBOARD_OPERATION_REJECTED", "message": str(error)}},
        )

    endpoint_application_service = (
        EndpointApplicationService(
            endpoint_service=endpoint_service,
            hypervisor_service=hypervisor_service,
            endpoint_publication_service=endpoint_publication_service,
            remote_endpoint_service=remote_endpoint_service,
            validation_service=validation_service,
        )
        if endpoint_service is not None
        else None
    )

    def _reconcile_remote_endpoint_publication(endpoint_id: str) -> bool:
        """Materialize a finalized publication before a dashboard retry."""
        if endpoint_service is None or endpoint_publication_service is None:
            return False
        consensus = getattr(hypervisor_service, "consensus_service", None)
        query_publication = getattr(consensus, "query_endpoint_publication", None)
        if consensus is None or not getattr(consensus, "is_enabled", False) or not callable(
            query_publication
        ):
            return False
        payload = query_publication(endpoint_id)
        if payload is None:
            return False
        try:
            record = PublishedEndpointConfiguration.model_validate(payload)
            endpoint = endpoint_service.get_endpoint(endpoint_id).endpoint
            if record.endpoint_id != endpoint_id or record.owner_wallet != endpoint.owner_wallet:
                return False
            verify_publication_signature(
                public_key=record.owner_public_key,
                signature=record.wallet_signature,
                payload=record.signed_payload(),
            )
            current = endpoint_publication_service.current_publication(endpoint_id)
            if current is not None and current.publication_id == record.publication_id:
                return False
            endpoint_publication_service.commit_prepared_configuration(
                record,
                record_operations=False,
            )
            return True
        except (KeyError, TypeError, ValueError):
            return False

    def _publish_endpoint(endpoint_id: str) -> dict:
        if (
            hypervisor_service is None
            or endpoint_service is None
            or endpoint_publication_service is None
        ):
            raise ValueError("Endpoint publication service is not configured")
        _reconcile_remote_endpoint_publication(endpoint_id)
        wallet = hypervisor_service.owner_wallet_state()
        if not wallet.get("configured"):
            raise ValueError("Owner wallet must be configured before publishing endpoint configuration")
        record = endpoint_publication_service.prepare_configuration(
            endpoint_id=endpoint_id,
            owner_wallet=wallet["wallet_id"],
            owner_public_key=wallet.get("public_key"),
            node_id=hypervisor_service.node_id,
            wallet_private_key=hypervisor_service.owner_wallet_private_key(),
        )
        current = endpoint_publication_service.current_publication(endpoint_id)
        if current is not None and current.publication_id == record.publication_id:
            return {
                "status": "FINALIZED",
                "endpoint_id": endpoint_id,
                "publication": record.model_dump(mode="json"),
            }
        consensus = getattr(hypervisor_service, "consensus_service", None)
        if consensus is None or not getattr(consensus, "is_enabled", False):
            committed = endpoint_publication_service.commit_prepared_configuration(record)
            return {
                "status": "FINALIZED",
                "endpoint_id": endpoint_id,
                "publication": committed.model_dump(mode="json"),
            }

        # Publishing is a canonical Wallet operation.  A local projection may
        # contain an identity from a previous chain or before an external-RPC
        # reconnect, so never use it as evidence for this transaction.
        identity_read = hypervisor_service.wallet_identity_read_model(record.owner_wallet)
        identity_source = str(identity_read.get("source") or "")
        canonical_identity_provider = getattr(
            hypervisor_service, "canonical_wallet_identity_provider", None
        )

        canonical_identity_query = getattr(consensus, "query_wallet_identity", None)
        canonical_identity_required = callable(canonical_identity_provider) or callable(
            canonical_identity_query
        )
        if canonical_identity_required and identity_read.get("identity") is None:
            if identity_read.get("error"):
                raise ValueError(
                    "canonical Wallet identity is unavailable; check the configured CometBFT RPC "
                    "before publishing"
                )
            raise ValueError(
                "Owner Wallet identity is not registered on the current canonical chain; "
                "open Wallet and click Register in network before publishing"
            )
        if canonical_identity_required and identity_source in {
            "local_projection",
            "local_projection_unverified",
        }:
            raise ValueError(
                "Wallet identity is available only in a local projection; register the Wallet "
                "in the current canonical network before publishing"
            )

        local_sequence = hypervisor_service.ledger_operation_service.wallet_next_sequence(
            record.owner_wallet
        )
        sequence_provider = getattr(
            hypervisor_service, "canonical_wallet_sequence_provider", None
        )
        query_sequence = getattr(consensus, "query_wallet_next_sequence", None)
        if callable(sequence_provider):
            try:
                canonical_sequence = int(sequence_provider(record.owner_wallet))
            except (RuntimeError, OSError, ValueError, TypeError) as error:
                raise ValueError(
                    f"canonical Wallet sequence is unavailable; check the configured CometBFT RPC ({error})"
                ) from error
        elif callable(query_sequence):
            canonical_sequence = query_sequence(record.owner_wallet)
            if canonical_sequence is None:
                raise ValueError(
                    "canonical Wallet sequence is unavailable; check the configured CometBFT RPC "
                    "and try again"
                )
        else:
            canonical_sequence = local_sequence
        if canonical_sequence is not None:
            if hypervisor_service.ledger_operation_service.reconcile_wallet_sequence(
                record.owner_wallet, canonical_sequence
            ):
                hypervisor_service._persist_state()
            local_sequence = canonical_sequence

        def build_envelope(
            publication_record,
            sequence: int,
            retry_nonce: str | None = None,
        ):
            evidence = [
                publication_record.publication_id,
                publication_record.endpoint_id,
                publication_record.configuration_hash,
            ]
            if retry_nonce is not None:
                evidence.append(f"retry:{retry_nonce}")
            unsigned = LedgerOperationEnvelope(
                operation_type="ENDPOINT_PUBLISH",
                operation_version="1.0.0",
                protocol_version="0.1",
                origin_type="wallet",
                initiator_id=publication_record.endpoint_id,
                sender_wallet=publication_record.owner_wallet,
                sender_sequence=sequence,
                fee_payer=publication_record.owner_wallet,
                fee_class="standard",
                created_at=publication_record.published_at,
                payload={"publication": publication_record.model_dump(mode="json")},
                evidence_references=evidence,
                signatures=[],
            )
            signature = sign_consensus_bytes(
                private_key=hypervisor_service.owner_wallet_private_key(),
                payload=unsigned.signing_bytes(),
            )
            return unsigned.model_copy(update={"signatures": [signature]})

        candidates = [
            envelope
            for envelope in hypervisor_service.list_pending_consensus_envelopes()
            if envelope.operation_type == "ENDPOINT_PUBLISH"
            and envelope.payload.get("publication", {}).get("endpoint_id") == endpoint_id
            and envelope.payload.get("publication", {}).get("configuration_hash")
            == record.configuration_hash
        ]
        pending = next(
            (envelope for envelope in reversed(candidates) if envelope.sender_sequence == local_sequence),
            None,
        )
        if pending is None:
            pending = build_envelope(record, local_sequence)
            hypervisor_service.stage_pending_consensus_envelope(pending)
        previous_submission = consensus.get_submission(pending.operation_id)
        if previous_submission is not None and previous_submission.status.value == "failed":
            pending = build_envelope(record, local_sequence, uuid4().hex)
            hypervisor_service.stage_pending_consensus_envelope(pending)
        submission = consensus.submit_operation(pending, retry_existing=True)
        if (
            submission.status.value == "failed"
            and "configuration_hash does not match canonical payload"
            in (submission.error or "")
        ):
            compatibility_record = endpoint_publication_service.legacy_compatible_configuration(
                record,
                wallet_private_key=hypervisor_service.owner_wallet_private_key(),
            )
            if compatibility_record.configuration_hash != record.configuration_hash:
                # Keep the rejected envelope as audit evidence, then retry
                # with the same canonical sequence and a fresh operation id.
                record = compatibility_record
                pending = build_envelope(record, local_sequence, uuid4().hex)
                hypervisor_service.stage_pending_consensus_envelope(pending)
                submission = consensus.submit_operation(pending, retry_existing=True)
        finality = hypervisor_service.ledger_operation_finality(pending.operation_id)
        if finality.get("consensus_finalized"):
            committed = endpoint_publication_service.commit_prepared_configuration(
                record,
                record_operations=False,
            )
            hypervisor_service.discard_pending_consensus_envelopes(pending.operation_id)
            hypervisor_service.discard_pending_consensus_operations(pending.operation_id)
            return {
                "status": "FINALIZED",
                "endpoint_id": endpoint_id,
                "publication": committed.model_dump(mode="json"),
                "consensus": {
                    "operation_id": pending.operation_id,
                    "submission": submission.status.value,
                    "finality": finality,
                },
            }
        if submission.status.value == "failed":
            raise ValueError(submission.error or "Consensus rejected Endpoint publication")
        return {
            "status": "CONSENSUS_PENDING",
            "endpoint_id": endpoint_id,
            "operation_id": pending.operation_id,
            "submission": submission.status.value,
            "publication": record.model_dump(mode="json"),
            "finality": finality,
        }

    def validate_personal_inference_endpoint(endpoint_id: str):
        if credential_store is None:
            raise RuntimeError("Inference credential store is unavailable")
        if endpoint_service is None or hypervisor_service is None:
            raise RuntimeError("Inference gateway is unavailable")
        try:
            endpoint = endpoint_service.get_endpoint(endpoint_id).endpoint
        except (KeyError, ValueError) as error:
            raise ValueError(f"Inference endpoint was not found: {endpoint_id}") from error
        if endpoint.status == "deleted":
            raise ValueError("Inference endpoint is deleted")
        if not endpoint.local_agent_use:
            raise ValueError("Local Agent Use is not enabled for this endpoint")
        if endpoint.execution_strategy != "local":
            raise ValueError("Personal agent inference requires a local endpoint")
        # ``llm.chat`` is the canonical Provider capability for an
        # OpenAI-compatible text runtime, whereas legacy model onboarding
        # records use ``llm_text`` as their workload class.  Both are eligible
        # local text-generation endpoints for a personal inference token.
        if endpoint.model_class not in {"llm_text", "llm.chat"}:
            raise ValueError("Personal agent inference requires a local text-generation endpoint")
        if not endpoint.runtime_binding_id:
            raise ValueError("Inference endpoint has no runtime binding")
        owner = hypervisor_service.owner_wallet_state()
        if not owner.get("configured") or not owner.get("wallet_id"):
            raise ValueError("Configure the owner wallet before issuing an inference token")
        if endpoint.owner_wallet != owner["wallet_id"]:
            raise ValueError("Inference endpoint is not owned by this Hypervisor wallet")
        pricing = endpoint.pricing.model_dump(mode="json")
        for key in ("input_price", "output_price", "audio_input_second_price", "fixed_price"):
            if float(pricing.get(key) or 0.0) != 0.0:
                raise ValueError("Personal agent inference currently supports zero-priced endpoints only")
        session_policy = endpoint.session.model_dump(mode="json")
        for key in ("minimum_deposit", "minimum_session_fee", "idle_fee_per_minute"):
            if float(session_policy.get(key) or 0.0) != 0.0:
                raise ValueError("Personal agent inference requires a zero-fee session policy")
        return endpoint

    def inference_base_url(request: Request) -> str:
        configured = os.getenv("AIDN_INFERENCE_PUBLIC_BASE_URL", "").strip().rstrip("/")
        if configured:
            return configured if configured.endswith("/v1") else configured + "/v1"
        return str(request.base_url).rstrip("/") + "/v1"

    def _register_owner_wallet_identity() -> dict:
        if hypervisor_service is None:
            raise ValueError("Wallet service is not configured")
        wallet = hypervisor_service.owner_wallet_state()
        if not wallet.get("configured"):
            raise ValueError("Owner wallet must be configured before identity registration")
        wallet_id = str(wallet["wallet_id"])
        public_key = str(wallet["public_key"])
        consensus = getattr(hypervisor_service, "consensus_service", None)
        consensus_enabled = bool(consensus is not None and getattr(consensus, "is_enabled", False))
        if consensus is None or not getattr(consensus, "is_enabled", False):
            nonce = uuid4().hex
            registration_signature = sign_consensus_bytes(
                private_key=hypervisor_service.owner_wallet_private_key(),
                payload=wallet_identity_registration_payload(
                    wallet_id=wallet_id,
                    public_key=public_key,
                    registration_nonce=nonce,
                ),
            )
            identity = hypervisor_service.register_wallet_identity(
                wallet_id=wallet_id,
                public_key=public_key,
                registration_nonce=nonce,
                signature=registration_signature,
            )
            return {"status": "FINALIZED", "wallet_id": wallet_id, "identity": identity}

        identity_read = hypervisor_service.wallet_identity_read_model(wallet_id)
        identity_source = str(identity_read.get("source") or "")
        canonical_identity = identity_read.get("identity")
        if consensus_enabled and identity_source in {"local_projection", "local_projection_unverified"}:
            canonical_identity = None
        if canonical_identity is not None:
            return {
                "status": "FINALIZED",
                "wallet_id": wallet_id,
                "identity": identity_read["identity"],
            }
        if identity_read.get("error") is not None and identity_source != "consensus_rpc":
            raise ValueError("canonical Wallet identity is unavailable; registration was not submitted")

        local_sequence = hypervisor_service.ledger_operation_service.wallet_next_sequence(wallet_id)
        sequence_provider = getattr(
            hypervisor_service, "canonical_wallet_sequence_provider", None
        )
        if sequence_provider is not None:
            canonical_sequence = sequence_provider(wallet_id)
            if hypervisor_service.ledger_operation_service.synchronize_wallet_sequence(
                wallet_id, canonical_sequence
            ):
                hypervisor_service._persist_state()
            local_sequence = canonical_sequence
        else:
            query_sequence = getattr(consensus, "query_wallet_next_sequence", None)
            if callable(query_sequence):
                canonical_sequence = query_sequence(wallet_id)
                if canonical_sequence is None:
                    raise ValueError(
                        "canonical Wallet sequence is unavailable; check the configured CometBFT RPC "
                        "and try again"
                    )
                # A missing canonical identity means this Wallet has not
                # existed on the currently selected chain.  The durable local
                # projection may still contain sequences from a previous
                # chain, so replace (rather than advance-only reconcile) the
                # nonce before creating the first registration envelope.
                if hypervisor_service.ledger_operation_service.synchronize_wallet_sequence(
                    wallet_id, canonical_sequence
                ):
                    hypervisor_service._persist_state()
                local_sequence = canonical_sequence

        def build_envelope(sequence: int, retry_nonce: str | None = None) -> LedgerOperationEnvelope:
            registered_at = datetime.now(UTC).isoformat()
            nonce = uuid4().hex
            registration_signature = sign_consensus_bytes(
                private_key=hypervisor_service.owner_wallet_private_key(),
                payload=wallet_identity_registration_payload(
                    wallet_id=wallet_id,
                    public_key=public_key,
                    registration_nonce=nonce,
                ),
            )
            evidence = [wallet_id, f"identity-nonce:{nonce}"]
            if retry_nonce is not None:
                evidence.append(f"retry:{retry_nonce}")
            unsigned = LedgerOperationEnvelope(
                operation_type="WALLET_IDENTITY_REGISTER",
                operation_version="1.0.0",
                protocol_version="0.1",
                origin_type="wallet",
                initiator_id=wallet_id,
                sender_wallet=wallet_id,
                sender_sequence=sequence,
                fee_payer=wallet_id,
                fee_class="onboarding_exempt",
                created_at=registered_at,
                payload={
                    "wallet_id": wallet_id,
                    "public_key": public_key,
                    "registration_nonce": nonce,
                    "registration_signature": registration_signature,
                    "registered_at": registered_at,
                },
                evidence_references=evidence,
                signatures=[],
            )
            signature = sign_consensus_bytes(
                private_key=hypervisor_service.owner_wallet_private_key(),
                payload=unsigned.signing_bytes(),
            )
            return unsigned.model_copy(update={"signatures": [signature]})

        candidates = [
            envelope
            for envelope in hypervisor_service.list_pending_consensus_envelopes()
            if envelope.operation_type == "WALLET_IDENTITY_REGISTER"
            and envelope.payload.get("wallet_id") == wallet_id
        ]
        pending = next(
            (envelope for envelope in reversed(candidates) if envelope.sender_sequence == local_sequence),
            None,
        )
        if pending is None:
            pending = build_envelope(local_sequence)
            hypervisor_service.stage_pending_consensus_envelope(pending)
        previous_submission = consensus.get_submission(pending.operation_id)
        if previous_submission is not None and previous_submission.status.value == "failed":
            pending = build_envelope(local_sequence, uuid4().hex)
            hypervisor_service.stage_pending_consensus_envelope(pending)
        submission = consensus.submit_operation(pending, retry_existing=True)
        finality = hypervisor_service.ledger_operation_finality(pending.operation_id)
        if finality.get("consensus_finalized"):
            hypervisor_service.discard_pending_consensus_envelopes(pending.operation_id)
            hypervisor_service.discard_pending_consensus_operations(pending.operation_id)
            return {
                "status": "FINALIZED",
                "wallet_id": wallet_id,
                "operation_id": pending.operation_id,
                "finality": finality,
            }
        if submission.status.value == "failed":
            raise ValueError(submission.error or "Consensus rejected Wallet identity registration")
        return {
            "status": "CONSENSUS_PENDING",
            "wallet_id": wallet_id,
            "operation_id": pending.operation_id,
            "submission": submission.status.value,
            "finality": finality,
        }

    def _wallet_transfer(payload: WalletTransferRequest, *, preview_only: bool) -> dict:
        if hypervisor_service is None:
            raise ValueError("Wallet service is not configured")
        wallet = hypervisor_service.owner_wallet_state()
        if not wallet.get("configured"):
            raise ValueError("Owner wallet must be configured before sending a transfer")

        sender_wallet = str(wallet["wallet_id"])
        recipient_wallet = payload.recipient_wallet.strip()
        if not recipient_wallet:
            raise ValueError("recipient Wallet is required")
        if recipient_wallet == sender_wallet:
            raise ValueError("recipient Wallet must differ from the Owner Wallet")
        if isinstance(payload.amount_q_atoms, bool) or payload.amount_q_atoms <= 0:
            raise ValueError("transfer amount must be a positive integer q_atoms value")
        amount_q_atoms = int(payload.amount_q_atoms)
        memo = payload.memo.strip() if payload.memo is not None else ""
        memo_hash = (
            "sha256:" + hashlib.sha256(memo.encode("utf-8")).hexdigest()
            if memo
            else None
        )

        balance_read = hypervisor_service.wallet_balance_read_model(sender_wallet)
        available_balance_q_atoms = int(balance_read.get("q_atoms", 0))
        network_fee_q_atoms = int(STANDARD_NETWORK_FEE_Q_ATOMS)
        total_debit_q_atoms = amount_q_atoms + network_fee_q_atoms
        consensus = getattr(hypervisor_service, "consensus_service", None)
        consensus_enabled = bool(consensus is not None and getattr(consensus, "is_enabled", False))
        local_sequence = hypervisor_service.ledger_operation_service.wallet_next_sequence(sender_wallet)

        if consensus_enabled:
            sequence_provider = getattr(
                hypervisor_service, "canonical_wallet_sequence_provider", None
            )
            if callable(sequence_provider):
                canonical_sequence = sequence_provider(sender_wallet)
            else:
                query_sequence = getattr(consensus, "query_wallet_next_sequence", None)
                canonical_sequence = query_sequence(sender_wallet) if callable(query_sequence) else None
            if canonical_sequence is None:
                raise ValueError(
                    "canonical Wallet sequence is unavailable; check the configured CometBFT RPC "
                    "and try again"
                )
            local_sequence = int(canonical_sequence)
            if not preview_only and hypervisor_service.ledger_operation_service.reconcile_wallet_sequence(
                sender_wallet, local_sequence
            ):
                hypervisor_service._persist_state()

        preview = {
            "status": "PREVIEW",
            "operation_type": "WALLET_TRANSFER",
            "sender_wallet": sender_wallet,
            "recipient_wallet": recipient_wallet,
            "amount_q_atoms": amount_q_atoms,
            "network_fee_q_atoms": network_fee_q_atoms,
            "total_debit_q_atoms": total_debit_q_atoms,
            "available_balance_q_atoms": available_balance_q_atoms,
            "balance_source": balance_read.get("source"),
            "balance_error": balance_read.get("error"),
            "sufficient_balance": available_balance_q_atoms >= total_debit_q_atoms,
            "sender_sequence": local_sequence,
            "consensus_required": consensus_enabled,
            "memo_hash": memo_hash,
        }
        if preview_only:
            return preview
        if available_balance_q_atoms < total_debit_q_atoms:
            raise ValueError("insufficient q_atoms for transfer and network fee")

        def build_envelope(sequence: int, retry_nonce: str | None = None) -> LedgerOperationEnvelope:
            created_at = datetime.now(UTC).isoformat()
            evidence = [sender_wallet, recipient_wallet, f"wallet-transfer:{amount_q_atoms}"]
            if memo_hash is not None:
                evidence.append(memo_hash)
            if retry_nonce is not None:
                evidence.append(f"retry:{retry_nonce}")
            operation_payload: dict[str, Any] = {
                "recipient_wallet": recipient_wallet,
                "amount": amount_q_atoms,
            }
            if memo_hash is not None:
                operation_payload["memo_hash"] = memo_hash
            unsigned = LedgerOperationEnvelope(
                operation_type="WALLET_TRANSFER",
                operation_version="1.0.0",
                protocol_version="0.1",
                origin_type="wallet",
                initiator_id=sender_wallet,
                sender_wallet=sender_wallet,
                sender_sequence=sequence,
                fee_payer=sender_wallet,
                fee_class="standard",
                created_at=created_at,
                payload=operation_payload,
                evidence_references=evidence,
                signatures=[],
            )
            signature = sign_consensus_bytes(
                private_key=hypervisor_service.owner_wallet_private_key(),
                payload=unsigned.signing_bytes(),
            )
            return unsigned.model_copy(update={"signatures": [signature]})

        pending_candidates = [
            envelope
            for envelope in hypervisor_service.list_pending_consensus_envelopes()
            if envelope.operation_type == "WALLET_TRANSFER"
            and envelope.sender_wallet == sender_wallet
            and envelope.sender_sequence == local_sequence
        ]
        pending = None
        failed_semantic = False
        for candidate in reversed(pending_candidates):
            candidate_memo_hash = candidate.payload.get("memo_hash")
            same_intent = (
                candidate.payload.get("recipient_wallet") == recipient_wallet
                and candidate.payload.get("amount") == amount_q_atoms
                and candidate_memo_hash == memo_hash
            )
            submission = consensus.get_submission(candidate.operation_id) if consensus_enabled else None
            failed = submission is not None and submission.status.value == "failed"
            if same_intent:
                if failed:
                    failed_semantic = True
                    continue
                pending = candidate
                break
            if not failed:
                raise ValueError(
                    "another Wallet operation is already pending for this sender sequence"
                )

        if pending is None:
            pending = build_envelope(local_sequence, uuid4().hex if failed_semantic else None)

        if not consensus_enabled:
            record = hypervisor_service.ledger_operation_service.apply_consensus_wallet_transfer(pending)
            hypervisor_service._persist_state()
            return {
                **preview,
                "status": "FINALIZED",
                "operation_id": pending.operation_id,
                "record": record,
                "finality": {"status": "local_only", "consensus_finalized": False},
            }

        hypervisor_service.stage_pending_consensus_envelope(pending)
        reconciliation = reconcile_pending_wallet_transfers(
            hypervisor_service,
            operation_ids={pending.operation_id},
        )
        submission = consensus.get_submission(pending.operation_id)
        finality = hypervisor_service.ledger_operation_finality(pending.operation_id)
        reconciliation_status = reconciliation[-1].get("status") if reconciliation else None
        if finality.get("consensus_finalized") or reconciliation_status in {
            "local_projection_finalized",
            "consensus_finalized",
        }:
            return {
                **preview,
                "status": "FINALIZED",
                "operation_id": pending.operation_id,
                "submission": (
                    submission.status.value
                    if submission is not None
                    else reconciliation_status or "finalized"
                ),
                "finality": finality,
            }
        if submission is not None and submission.status.value == "failed":
            raise ValueError(submission.error or "Consensus rejected Wallet transfer")
        return {
            **preview,
            "status": "CONSENSUS_PENDING",
            "operation_id": pending.operation_id,
            "submission": (
                reconciliation[-1].get("submission_status")
                if reconciliation and reconciliation[-1].get("submission_status")
                else submission.status.value if submission is not None else "pending"
            ),
            "finality": finality,
        }

    @router.get("/status")
    async def status(request: Request) -> dict:
        active = session_expiry(request) is not None
        return {
            "enabled": access_service is not None and credential_store is not None,
            "session": {"active": active, "expires_at": session_expiry(request)},
            "transport": {"insecure_lan": allow_insecure_lan},
            "operator_authority": {
                "configured": operator_fingerprint is not None,
                "fingerprint": operator_fingerprint,
            },
            "network_access": network_access.status(),
            "credentials": (
                []
                if credential_store is None or not active
                else [_credential_payload(item) for item in credential_store.list_credentials()]
            ),
            "inference_credentials": (
                []
                if credential_store is None or not active
                else [
                    _inference_credential_payload(item)
                    for item in credential_store.list_inference_credentials()
                ]
            ),
        }

    @router.post("/operations/network")
    async def update_network_access(
        payload: DashboardNetworkAccessRequest,
        request: Request,
    ) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        try:
            result = network_access.set_mode(payload.mode)
        except (OSError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(
            status_code=202 if result.get("restart_scheduled") else 200,
            content=result,
        )

    @router.post("/operations/cometbft/install")
    async def install_cometbft(
        payload: ConsensusInstallRequest,
        request: Request,
    ) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        network_configuration_requested = bool(
            payload.p2p_host == "0.0.0.0"
            or payload.external_address.strip()
            or payload.seeds.strip()
            or payload.persistent_peers.strip()
        )
        if network_configuration_requested and not payload.acknowledge_network_scope:
            return operation_error(
                ValueError(
                    "P2P discovery configuration requires explicit network acknowledgement"
                )
            )
        try:
            result = install_cometbft_from_dashboard(
                hypervisor_service,
                payload.model_dump(exclude_none=True),
            )
        except (RuntimeError, ValueError, OSError) as error:
            return operation_error(error)
        return JSONResponse(status_code=202, content=result)

    @router.post("/operations/cometbft/apply")
    async def apply_cometbft(
        request: Request,
    ) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        try:
            result = apply_pending_cometbft_configuration(hypervisor_service)
        except (RuntimeError, ValueError, OSError) as error:
            return operation_error(error)
        return JSONResponse(status_code=202 if result.get("restart_scheduled") else 200, content=result)

    @router.post("/operations/cometbft/reconnect")
    async def reconnect_cometbft(
        payload: ConsensusReconnectRequest,
        request: Request,
    ) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        # Non-validator reconnects use the verified external-RPC profile and
        # deliberately do not open a local P2P listener.  Keep the network
        # acknowledgement gate for validator/local installs only.
        network_configuration_requested = payload.mode != "non_validator" and bool(
            payload.p2p_host == "0.0.0.0"
            or payload.external_address.strip()
            or payload.seeds.strip()
            or payload.persistent_peers.strip()
        )
        if network_configuration_requested and not payload.acknowledge_network_scope:
            return operation_error(
                ValueError(
                    "P2P discovery configuration requires explicit network acknowledgement"
                )
            )
        try:
            result = reconnect_cometbft_from_dashboard(
                hypervisor_service,
                payload.model_dump(exclude_none=True),
            )
        except (RuntimeError, ValueError, OSError) as error:
            return operation_error(error)
        return JSONResponse(status_code=202, content=result)

    @router.post("/operations/cometbft/{action}")
    async def control_cometbft(action: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        try:
            result = control_managed_cometbft(hypervisor_service, action)
        except (RuntimeError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=202, content=result)

    @router.post("/pair", status_code=200)
    async def pair(payload: PairingRequest, request: Request) -> Response:
        if access_service is None:
            return JSONResponse(status_code=404, content={"error": {"code": "DASHBOARD_ACCESS_DISABLED"}})
        if not allow_insecure_lan and request.url.scheme != "https":
            return JSONResponse(status_code=426, content={"error": {"code": "DASHBOARD_ACCESS_TLS_REQUIRED"}})
        session = access_service.exchange_pairing_code(
            payload.code,
            browser_key=request.headers.get(_BROWSER_KEY_HEADER),
            duration=payload.duration,
        )
        if session is None:
            return JSONResponse(status_code=403, content={"error": {"code": "DASHBOARD_PAIRING_INVALID"}})
        # Return a small JSON success body instead of 204.  Some iOS/WebKit
        # clients have historically been unreliable about retaining a
        # Set-Cookie header from a 204 fetch response; the dashboard pairing
        # flow must work on the phone that is normally used to operate a LAN
        # node.  The session id remains HttpOnly and is never returned in the
        # JSON body.
        paired = JSONResponse(
            status_code=200,
            content={"status": "paired", "expires_at": session.expires_at},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
        paired.set_cookie(
            _COOKIE_NAME,
            session.session_id,
            httponly=True,
            samesite="strict",
            secure=not allow_insecure_lan,
            path=_COOKIE_PATH,
            max_age=_COOKIE_MAX_AGE[payload.duration],
        )
        return paired

    @router.post("/credentials", status_code=201)
    async def create_credential(payload: CredentialCreateRequest, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        assert credential_store is not None
        try:
            scopes = normalize_agent_scopes(payload.scopes)
            auto_approved_scopes = normalize_auto_approved_scopes(payload.auto_approved_scopes)
            if not set(auto_approved_scopes).issubset(scopes):
                raise ValueError("auto approval requires the corresponding agent permission")
        except ValueError:
            return JSONResponse(status_code=422, content={"error": {"code": "MCP_CREDENTIAL_SCOPE_INVALID"}})
        issued = credential_store.create_credential(
            label=payload.label,
            scopes=scopes,
            auto_approved_scopes=auto_approved_scopes,
        )
        return JSONResponse(status_code=201, content=_credential_payload(issued, reveal=True))

    @router.get("/inference-credentials")
    async def list_inference_credentials(request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if credential_store is None:
            return JSONResponse(status_code=503, content={"error": {"code": "INFERENCE_ACCESS_UNAVAILABLE"}})
        return JSONResponse(
            status_code=200,
            content={
                "items": [
                    _inference_credential_payload(item)
                    for item in credential_store.list_inference_credentials()
                ],
                "base_url": inference_base_url(request),
            },
        )

    @router.post("/inference-credentials", status_code=201)
    async def create_inference_credential(
        payload: InferenceCredentialCreateRequest,
        request: Request,
    ) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if credential_store is None:
            return JSONResponse(status_code=503, content={"error": {"code": "INFERENCE_ACCESS_UNAVAILABLE"}})
        try:
            endpoint = validate_personal_inference_endpoint(payload.endpoint_id)
            owner = hypervisor_service.owner_wallet_state()
            issued = credential_store.create_inference_credential(
                label=payload.label,
                endpoint_id=endpoint.endpoint_id,
                owner_wallet=owner["wallet_id"],
                model_alias=payload.model_alias,
                ttl_seconds=payload.ttl_seconds,
            )
        except (RuntimeError, ValueError) as error:
            return JSONResponse(
                status_code=409,
                content={"error": {"code": "INFERENCE_CREDENTIAL_REJECTED", "message": str(error)}},
            )
        result = _inference_credential_payload(issued, reveal=True)
        result["base_url"] = inference_base_url(request)
        result["endpoint_display_name"] = endpoint.display_name
        return JSONResponse(status_code=201, content=result)

    @router.post("/inference-credentials/{credential_id}/rotate", status_code=201)
    async def rotate_inference_credential(credential_id: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if credential_store is None:
            return JSONResponse(status_code=503, content={"error": {"code": "INFERENCE_ACCESS_UNAVAILABLE"}})
        try:
            current = next(
                (
                    item
                    for item in credential_store.list_inference_credentials()
                    if item.credential_id == credential_id and item.state == "active"
                ),
                None,
            )
            if current is None:
                raise ValueError("Inference credential is not active")
            validate_personal_inference_endpoint(current.endpoint_id)
            issued = credential_store.rotate_inference_credential(credential_id)
        except (RuntimeError, ValueError):
            return JSONResponse(status_code=404, content={"error": {"code": "INFERENCE_CREDENTIAL_NOT_ACTIVE"}})
        result = _inference_credential_payload(issued, reveal=True)
        result["base_url"] = inference_base_url(request)
        return JSONResponse(status_code=201, content=result)

    @router.delete("/inference-credentials/{credential_id}", status_code=204)
    async def revoke_inference_credential(credential_id: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if credential_store is None:
            return JSONResponse(status_code=503, content={"error": {"code": "INFERENCE_ACCESS_UNAVAILABLE"}})
        current = next(
            (
                item
                for item in credential_store.list_inference_credentials()
                if item.credential_id == credential_id and item.state == "active"
            ),
            None,
        )
        if not credential_store.revoke_inference_credential(credential_id):
            return JSONResponse(status_code=404, content={"error": {"code": "INFERENCE_CREDENTIAL_NOT_ACTIVE"}})
        if current is not None and current.session_id and session_service is not None:
            try:
                session_service.close_session(current.session_id)
            except (KeyError, RuntimeError, ValueError):
                # Revocation is authoritative even if a stale/expired session
                # cannot be closed during the same request.  The normal
                # session expiry path will reclaim the slot.
                pass
        return Response(status_code=204)

    @router.get("/permission-catalog")
    async def permission_catalog(request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        return JSONResponse(
            status_code=200,
            content={
                "items": permission_catalog_payload(),
                "default_scopes": list(DEFAULT_AGENT_READ_SCOPES),
                "full_control_scopes": list(FULL_AGENT_CONTROL_SCOPES),
                "full_control_auto_approved_scopes": list(AGENT_MUTATION_SCOPES),
                "note": (
                    "Permissions control MCP tool visibility and execution. They do not bypass "
                    "operator plan approval or enable deferred tools. Automatic approval is opt-in per action."
                ),
            },
        )

    @router.put("/credentials/{credential_id}/scopes")
    async def update_credential_scopes(
        credential_id: str,
        payload: CredentialScopeUpdateRequest,
        request: Request,
    ) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        assert credential_store is not None
        try:
            scopes = normalize_agent_scopes(payload.scopes)
            auto_approved_scopes = normalize_auto_approved_scopes(payload.auto_approved_scopes)
            if not set(auto_approved_scopes).issubset(scopes):
                raise ValueError("auto approval requires the corresponding agent permission")
            updated = credential_store.update_scopes(
                credential_id,
                scopes=scopes,
                auto_approved_scopes=auto_approved_scopes,
            )
        except ValueError:
            return JSONResponse(status_code=422, content={"error": {"code": "MCP_CREDENTIAL_SCOPE_INVALID"}})
        # Scope changes are intentionally live.  The remote MCP gateway
        # re-resolves the bearer credential on every request and refreshes the
        # scoped control view, so clients do not need to restart their gateway
        # or lose the transport session just to discover a new permission.
        return JSONResponse(status_code=200, content=_credential_payload(updated))

    @router.post("/credentials/{credential_id}/rotate", status_code=201)
    async def rotate_credential(credential_id: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        assert credential_store is not None
        try:
            issued = credential_store.rotate_credential(credential_id)
        except ValueError:
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_CREDENTIAL_NOT_ACTIVE"}})
        if invalidate_credential_sessions is not None:
            invalidate_credential_sessions(credential_id)
        return JSONResponse(status_code=201, content=_credential_payload(issued, reveal=True))

    @router.delete("/credentials/{credential_id}", status_code=204)
    async def revoke_credential(credential_id: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        assert credential_store is not None
        if not credential_store.revoke_credential(credential_id):
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_CREDENTIAL_NOT_ACTIVE"}})
        if invalidate_credential_sessions is not None:
            invalidate_credential_sessions(credential_id)
        return Response(status_code=204)

    @router.post("/logout", status_code=204)
    async def logout(request: Request, response: Response) -> Response:
        if access_service is not None:
            access_service.revoke_session(
                request.cookies.get(_COOKIE_NAME),
                browser_key=request.headers.get(_BROWSER_KEY_HEADER),
            )
        response.delete_cookie(_COOKIE_NAME, path=_COOKIE_PATH)
        return Response(status_code=204, headers=dict(response.headers))

    @router.post("/operations/resources/probe")
    async def refresh_resources(request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None or hypervisor_service.resources is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_RESOURCE_PROBE_UNAVAILABLE"}})
        try:
            report = refresh_resource_probe_from_environment()
            hypervisor_service.resources.reconcile_hardware(
                report.capacity,
                probe=report.metadata(),
                observed_at=report.observed_at,
            )
            reconcile = getattr(hypervisor_service, "reconcile_scheduler", None)
            if callable(reconcile):
                reconcile(trigger="resource_probe")
        except (OSError, TypeError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "resources": hypervisor_service.resources.summary()},
        )

    @router.get("/operations/resources/status")
    async def resource_hardware_status(request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None or hypervisor_service.resources is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_RESOURCE_STATUS_UNAVAILABLE"}})
        return JSONResponse(
            status_code=200,
            content={"available": True, **hypervisor_service.resources.hardware_status()},
        )

    @router.post("/operations/wallet/create")
    async def create_wallet(payload: WalletBootstrapCreateRequest, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.configure_owner_wallet(mode="create", label=payload.label)
        except ValueError as error:
            return operation_error(error)
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/wallet/import")
    async def import_wallet(payload: WalletBootstrapImportRequest, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.configure_owner_wallet(
                mode="import",
                label=payload.label,
                private_key=payload.private_key,
            )
        except ValueError as error:
            return operation_error(error)
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/wallet/identity/register")
    async def register_owner_wallet_identity(request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        try:
            result = _register_owner_wallet_identity()
        except (ValueError, OSError) as error:
            return operation_error(error)
        return JSONResponse(
            status_code=202 if result.get("status") == "CONSENSUS_PENDING" else 200,
            content=result,
        )

    @router.post("/operations/wallet/transfer/preview")
    async def preview_wallet_transfer(payload: WalletTransferRequest, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        try:
            result = _wallet_transfer(payload, preview_only=True)
        except (ValueError, OSError) as error:
            return operation_error(error)
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/wallet/transfer")
    async def submit_wallet_transfer(payload: WalletTransferRequest, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        try:
            result = _wallet_transfer(payload, preview_only=False)
        except (ValueError, OSError) as error:
            return operation_error(error)
        return JSONResponse(
            status_code=202 if result.get("status") == "CONSENSUS_PENDING" else 200,
            content=result,
        )

    @router.post("/operations/bundles/{bundle_id}/{action}")
    async def bundle_operation(bundle_id: str, action: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            if action == "revisions":
                payload = BundleRevisionOperationRequest.model_validate(await request.json())
                result = hypervisor_service.create_bundle_revision(
                    source_bundle_id=bundle_id,
                    bundle_id=payload.bundle_id,
                    overrides=payload.overrides,
                    enabled=payload.enabled,
                )
                return JSONResponse(status_code=201, content=result)
            if action == "enable":
                result = hypervisor_service.set_bundle_enabled(bundle_id, True)
            elif action == "disable":
                result = hypervisor_service.set_bundle_enabled(bundle_id, False)
            elif action == "retry":
                result = {
                    "bundle_id": bundle_id,
                    "status": "retried",
                    "summary": hypervisor_service.retry_bundle(bundle_id),
                }
            elif action == "reset-cooldown":
                result = hypervisor_service.reset_bundle_cooldown(bundle_id)
            else:
                return JSONResponse(status_code=422, content={"error": {"code": "DASHBOARD_OPERATION_UNKNOWN"}})
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/lifecycle/transition-plan")
    async def lifecycle_transition_plan(payload: LifecyclePlanRequest, request: Request) -> Response:
        """Create a paired-browser lifecycle transition plan.

        The generic operator lifecycle API is intentionally not exposed to an
        unauthenticated LAN browser.  This wrapper keeps the same plan/hash
        contract while requiring the dashboard pairing session.
        """

        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        if payload.action is None:
            return JSONResponse(status_code=422, content={"error": {"code": "DASHBOARD_OPERATION_UNKNOWN", "message": "A transition action is required."}})
        try:
            result = hypervisor_service.lifecycle_transition_plan(
                object_type=payload.object_type,
                object_id=payload.object_id,
                action=payload.action,
                actor=payload.actor,
            )
        except LifecycleError as error:
            return JSONResponse(status_code=409, content={"error": error.as_detail()})
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/lifecycle/transition-plans/{transition_id}/apply")
    async def apply_lifecycle_transition(transition_id: str, payload: LifecycleApplyRequest, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.apply_lifecycle_transition(
                transition_id,
                plan_hash=payload.plan_hash,
                actor=payload.actor,
                idempotency_key=payload.idempotency_key,
            )
        except LifecycleError as error:
            status_code = 404 if error.code == "OBJECT_NOT_FOUND" else 409
            return JSONResponse(status_code=status_code, content={"error": error.as_detail()})
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/lifecycle/removal-plan")
    async def lifecycle_removal_plan(payload: LifecyclePlanRequest, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.lifecycle_removal_plan(
                object_type=payload.object_type,
                object_id=payload.object_id,
                cascade=payload.cascade,
                actor=payload.actor,
            )
        except LifecycleError as error:
            return JSONResponse(status_code=409, content={"error": error.as_detail()})
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/lifecycle/removal-plans/{plan_id}/apply")
    async def apply_lifecycle_removal(plan_id: str, payload: LifecycleApplyRequest, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.apply_lifecycle_removal(
                plan_id,
                plan_hash=payload.plan_hash,
                actor=payload.actor,
                force=payload.force,
                idempotency_key=payload.idempotency_key,
            )
        except LifecycleError as error:
            status_code = 404 if error.code == "OBJECT_NOT_FOUND" else 409
            return JSONResponse(status_code=status_code, content={"error": error.as_detail()})
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/lifecycle/runtime-reset/plan")
    async def runtime_reset_plan(request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.runtime_reset_plan(actor="operator-dashboard")
        except LifecycleError as error:
            return JSONResponse(status_code=409, content={"error": error.as_detail()})
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/lifecycle/runtime-reset/apply")
    async def apply_runtime_reset(payload: RuntimeResetApplyRequest, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.apply_runtime_reset(
                payload.reset_id,
                plan_hash=payload.plan_hash,
                actor=payload.actor,
                force=payload.force,
                idempotency_key=payload.idempotency_key,
            )
        except LifecycleError as error:
            status_code = 404 if error.code == "OBJECT_NOT_FOUND" else 409
            return JSONResponse(status_code=status_code, content={"error": error.as_detail()})
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/installation-plan/apply")
    async def apply_installation_plan(
        payload: InstallationPlanApplyRequest,
        request: Request,
    ) -> Response:
        """Apply one plan-bound, policy-gated assisted-installation step."""

        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}},
            )
        try:
            result = hypervisor_service.apply_installation_plan(
                plan_hash=payload.plan_hash,
                actor=payload.actor,
                idempotency_key=payload.idempotency_key,
                action=payload.action,
            )
        except ValueError as error:
            return operation_error(error)
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/providers/attach")
    async def attach_provider(payload: ProviderAttachRequest, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.attach_provider_instance(
                plugin_id=payload.plugin_id,
                display_name=payload.display_name,
                configuration=payload.configuration,
            )
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=201, content=result)

    @router.post("/operations/provider-plugins/{plugin_id}/install")
    async def install_provider_plugin(
        plugin_id: str,
        payload: ProviderRuntimeInstallRequest,
        request: Request,
    ) -> Response:
        """Run the reviewed one-click install flow through the paired Dashboard.

        The browser never supplies arbitrary permissions or commands. The
        server rebuilds the current plan, approves exactly its declared
        permission IDs, then applies the approval through the configured
        installation executor (the root-owned runtime broker on Ubuntu).
        """

        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.install_provider_runtime(
                plugin_id=plugin_id,
                configuration=payload.configuration,
                operator_note=payload.operator_note or "Paired Dashboard one-click runtime installation",
                upgrade_acknowledged=payload.upgrade_acknowledged,
                wait_for_completion=payload.wait_for_completion,
            )
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/provider-plugins/{plugin_id}/runtime/{action}")
    async def provider_runtime_action(
        plugin_id: str,
        action: str,
        payload: ProviderRuntimeInstallRequest,
        request: Request,
    ) -> Response:
        """Apply one typed lifecycle operation to a managed Provider runtime.

        The action is deliberately constrained to install/change/remove. The
        service rebuilds the reviewed plan and keeps the browser outside the
        allowlisted broker boundary.
        """

        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            if action == "install":
                result = hypervisor_service.install_provider_runtime(
                    plugin_id=plugin_id,
                    configuration=payload.configuration,
                    operator_note=payload.operator_note,
                    upgrade_acknowledged=payload.upgrade_acknowledged,
                    wait_for_completion=payload.wait_for_completion,
                )
            elif action == "change":
                result = hypervisor_service.change_provider_runtime(
                    plugin_id=plugin_id,
                    configuration=payload.configuration,
                    operator_note=payload.operator_note,
                    upgrade_acknowledged=payload.upgrade_acknowledged,
                    wait_for_completion=payload.wait_for_completion,
                )
            elif action == "remove":
                result = hypervisor_service.remove_provider_runtime(plugin_id=plugin_id)
            else:
                return JSONResponse(status_code=422, content={"error": {"code": "DASHBOARD_OPERATION_UNKNOWN"}})
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/providers/{provider_instance_id}/{action}")
    async def provider_operation(provider_instance_id: str, action: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            if action == "probe":
                result = hypervisor_service.probe_provider_instance(provider_instance_id)
            elif action == "discover-models":
                result = {"items": hypervisor_service.discover_provider_models(provider_instance_id)}
            elif action == "detach":
                result = hypervisor_service.detach_provider_instance(provider_instance_id)
            else:
                return JSONResponse(status_code=422, content={"error": {"code": "DASHBOARD_OPERATION_UNKNOWN"}})
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/models/install")
    async def request_model_install(payload: ModelInstallOperationRequest, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.request_model_install(**payload.model_dump(mode="json"))
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=202, content=result)

    @router.post("/operations/models/install/process")
    async def process_model_installs(request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.process_model_installs()
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=200, content={"items": result})

    @router.post("/operations/models/{install_id}/register-bundle")
    async def register_bundle_from_install(
        install_id: str,
        payload: RegisterBundleOperationRequest,
        request: Request,
    ) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.register_bundle_from_install(
                install_id=install_id,
                **payload.model_dump(mode="json"),
            )
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=201, content=result)

    @router.post("/operations/model-artifact-sets")
    async def create_model_artifact_set(
        payload: ModelArtifactSetOperationRequest,
        request: Request,
    ) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.create_model_artifact_set(**payload.model_dump(mode="json"))
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=201, content=result)

    @router.post("/operations/model-deployments/{model_deployment_id}/artifact-set")
    async def bind_model_artifact_set(
        model_deployment_id: str,
        payload: BindModelArtifactSetOperationRequest,
        request: Request,
    ) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.bind_model_artifact_set(
                model_deployment_id=model_deployment_id,
                artifact_set_id=payload.artifact_set_id,
            )
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/provider-instances/{provider_instance_id}/artifact-sets/materialize")
    async def materialize_model_artifact_set(
        provider_instance_id: str,
        payload: MaterializeModelArtifactSetOperationRequest,
        request: Request,
    ) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.materialize_model_artifact_set(
                provider_instance_id=provider_instance_id,
                artifact_set_id=payload.artifact_set_id,
                destination=payload.destination,
            )
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=200, content=result)

    @router.post("/operations/model-deployments/{model_deployment_id}/runtime-bindings")
    async def create_runtime_binding(
        model_deployment_id: str,
        payload: RuntimeBindingOperationRequest,
        request: Request,
    ) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if hypervisor_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_OPERATIONS_UNAVAILABLE"}})
        try:
            result = hypervisor_service.create_runtime_binding(
                model_deployment_id=model_deployment_id,
                **payload.model_dump(mode="json"),
            )
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=201, content=result)

    @router.post("/operations/endpoints")
    async def create_endpoint(payload: dict[str, Any], request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if endpoint_application_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_ENDPOINTS_UNAVAILABLE"}})
        try:
            result = endpoint_application_service.create_endpoint(payload)
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=201, content=result["payload"])

    @router.post("/operations/endpoints/marketplace-description/preview")
    async def preview_marketplace_description(
        payload: MarketplaceDescriptionPreviewRequest,
        request: Request,
    ) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        try:
            description = EndpointMarketplaceDescription(html=payload.html)
        except ValueError as error:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "MARKETPLACE_DESCRIPTION_INVALID",
                        "message": str(error),
                    }
                },
            )
        return JSONResponse(
            status_code=200,
            content={
                "description": description.model_dump(mode="json"),
                "rendered_html": description.html,
            },
        )

    @router.patch("/operations/endpoints/{endpoint_id}")
    async def update_endpoint(
        endpoint_id: str,
        payload: dict[str, Any],
        request: Request,
    ) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if endpoint_application_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_ENDPOINTS_UNAVAILABLE"}})
        try:
            result = endpoint_application_service.update_endpoint(
                endpoint_id,
                UpdateEndpointCommand.model_validate(payload),
            )
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(status_code=200, content=result["payload"])

    @router.post("/operations/endpoints/{endpoint_id}/local-agent-use")
    async def set_local_agent_use(
        endpoint_id: str,
        payload: LocalAgentUseRequest,
        request: Request,
    ) -> Response:
        """Change local agent gateway access without changing endpoint config."""
        denied = require_session(request)
        if denied is not None:
            return denied
        if endpoint_service is None:
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "DASHBOARD_ENDPOINTS_UNAVAILABLE"}},
            )
        try:
            result = endpoint_service.set_local_agent_use(
                endpoint_id,
                enabled=payload.enabled,
            )
        except (KeyError, ValueError) as error:
            return operation_error(error)

        revoked_credential_ids: list[str] = []
        closed_session_ids: list[str] = []
        if not payload.enabled and credential_store is not None:
            active_credentials = [
                item
                for item in credential_store.list_inference_credentials()
                if item.endpoint_id == endpoint_id and item.state == "active"
            ]
            for credential in active_credentials:
                if credential_store.revoke_inference_credential(credential.credential_id):
                    revoked_credential_ids.append(credential.credential_id)
                    if credential.session_id and session_service is not None:
                        try:
                            session_service.close_session(credential.session_id)
                            closed_session_ids.append(credential.session_id)
                        except (KeyError, RuntimeError, ValueError):
                            # Token revocation remains authoritative even when
                            # the linked zero-fee session has already expired.
                            pass
        return JSONResponse(
            status_code=200,
            content={
                "endpoint": result.endpoint.model_dump(mode="json"),
                "local_agent_use": result.endpoint.local_agent_use,
                "revoked_inference_credential_ids": revoked_credential_ids,
                "closed_session_ids": closed_session_ids,
            },
        )

    @router.post("/operations/endpoints/{endpoint_id}/publish")
    async def publish_endpoint(endpoint_id: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        try:
            result = _publish_endpoint(endpoint_id)
        except (KeyError, ValueError, OSError) as error:
            return operation_error(error)
        return JSONResponse(status_code=202 if result.get("status") == "CONSENSUS_PENDING" else 200, content=result)

    @router.post("/operations/endpoints/{endpoint_id}/validation")
    async def request_endpoint_validation(endpoint_id: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if endpoint_service is None or validation_service is None:
            return JSONResponse(status_code=503, content={"error": {"code": "DASHBOARD_VALIDATION_UNAVAILABLE"}})
        try:
            endpoint = endpoint_service.get_endpoint(endpoint_id).endpoint
            outcome = validation_service.request_validation(
                endpoint_id=endpoint.endpoint_id,
                owner_wallet=endpoint.owner_wallet,
                configuration_hash=endpoint.configuration_hash,
                minimum_session_deposit_q=endpoint.session.minimum_deposit,
            )
        except (KeyError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(
            status_code=201,
            content={
                "request": outcome.request.model_dump(mode="json"),
                "bond": outcome.bond.model_dump(mode="json"),
                "snapshot": outcome.snapshot.model_dump(mode="json"),
            },
        )

    @router.post("/agent-enrollment/requests", status_code=201)
    async def create_enrollment(payload: EnrollmentCreateRequest) -> Response:
        if enrollment_service is None:
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_ENROLLMENT_DISABLED"}})
        try:
            created = enrollment_service.create_request(
                label=payload.label,
                encryption_public_key=payload.encryption_public_key,
            )
        except ValueError:
            return JSONResponse(status_code=422, content={"error": {"code": "MCP_ENROLLMENT_INVALID"}})
        return JSONResponse(status_code=201, content=enrollment_payload(created))

    @router.get("/agent-enrollment/requests/{request_id}")
    async def retrieve_enrollment(request_id: str, request: Request) -> Response:
        if enrollment_service is None:
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_ENROLLMENT_NOT_FOUND"}})
        result = enrollment_service.retrieve(
            request_id=request_id,
            retrieval_secret=request.headers.get("X-AiDN-Enrollment-Secret", ""),
        )
        if result is None:
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_ENROLLMENT_NOT_FOUND"}})
        return JSONResponse(status_code=200, content=result)

    @router.get("/enrollment-requests")
    async def list_enrollments(request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if enrollment_service is None:
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_ENROLLMENT_DISABLED"}})
        return JSONResponse(
            status_code=200,
            content={"items": [enrollment_payload(item) for item in enrollment_service.list_requests()]},
        )

    @router.post("/enrollment-requests/{request_id}/approve")
    async def approve_enrollment(request_id: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if enrollment_service is None:
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_ENROLLMENT_DISABLED"}})
        try:
            approved = enrollment_service.approve(request_id)
        except ValueError:
            return JSONResponse(status_code=409, content={"error": {"code": "MCP_ENROLLMENT_NOT_PENDING"}})
        return JSONResponse(status_code=200, content=enrollment_payload(approved))

    @router.post("/enrollment-requests/{request_id}/reject")
    async def reject_enrollment(request_id: str, request: Request) -> Response:
        denied = require_session(request)
        if denied is not None:
            return denied
        if enrollment_service is None:
            return JSONResponse(status_code=404, content={"error": {"code": "MCP_ENROLLMENT_DISABLED"}})
        try:
            rejected = enrollment_service.reject(request_id)
        except ValueError:
            return JSONResponse(status_code=409, content={"error": {"code": "MCP_ENROLLMENT_NOT_PENDING"}})
        return JSONResponse(status_code=200, content=enrollment_payload(rejected))

    return router
