"""Protected dashboard endpoints for local MCP agent credentials."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.endpoint_publications.signing import sign_consensus_bytes
from aidn_hypervisor.endpoints.endpoint_application_service import EndpointApplicationService
from aidn_hypervisor.endpoints.models import (
    EndpointMarketplaceDescription,
    UpdateEndpointCommand,
)
from aidn_hypervisor.ledger.service import STANDARD_NETWORK_FEE_Q_ATOMS
from aidn_hypervisor.mcp.credentials import McpCredential, McpCredentialStore
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
from aidn_hypervisor.dashboard_network_access import DashboardNetworkAccessService
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


class BundleRevisionOperationRequest(BaseModel):
    bundle_id: str = Field(min_length=1, max_length=128)
    overrides: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False


class DashboardNetworkAccessRequest(BaseModel):
    mode: Literal["loopback", "lan"]


def _credential_payload(credential: McpCredential, *, reveal: bool = False) -> dict:
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

    def _publish_endpoint(endpoint_id: str) -> dict:
        if (
            hypervisor_service is None
            or endpoint_service is None
            or endpoint_publication_service is None
        ):
            raise ValueError("Endpoint publication service is not configured")
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

        local_sequence = hypervisor_service.ledger_operation_service.wallet_next_sequence(
            record.owner_wallet
        )
        query_sequence = getattr(consensus, "query_wallet_next_sequence", None)
        if callable(query_sequence):
            canonical_sequence = query_sequence(record.owner_wallet)
            if canonical_sequence is None:
                raise ValueError("canonical wallet sequence is unavailable")
            if hypervisor_service.ledger_operation_service.reconcile_wallet_sequence(
                record.owner_wallet, canonical_sequence
            ):
                hypervisor_service._persist_state()
            local_sequence = canonical_sequence

        def build_envelope(sequence: int, retry_nonce: str | None = None):
            evidence = [record.publication_id, record.endpoint_id, record.configuration_hash]
            if retry_nonce is not None:
                evidence.append(f"retry:{retry_nonce}")
            unsigned = LedgerOperationEnvelope(
                operation_type="ENDPOINT_PUBLISH",
                operation_version="1.0.0",
                protocol_version="0.1",
                origin_type="wallet",
                initiator_id=record.endpoint_id,
                sender_wallet=record.owner_wallet,
                sender_sequence=sequence,
                fee_payer=record.owner_wallet,
                fee_class="standard",
                created_at=record.published_at,
                payload={"publication": record.model_dump(mode="json")},
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
            pending = build_envelope(local_sequence)
            hypervisor_service.stage_pending_consensus_envelope(pending)
        previous_submission = consensus.get_submission(pending.operation_id)
        if previous_submission is not None and previous_submission.status.value == "failed":
            pending = build_envelope(local_sequence, uuid4().hex)
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

    def _register_owner_wallet_identity() -> dict:
        if hypervisor_service is None:
            raise ValueError("Wallet service is not configured")
        wallet = hypervisor_service.owner_wallet_state()
        if not wallet.get("configured"):
            raise ValueError("Owner wallet must be configured before identity registration")
        wallet_id = str(wallet["wallet_id"])
        public_key = str(wallet["public_key"])
        consensus = getattr(hypervisor_service, "consensus_service", None)
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
        if identity_read.get("identity") is not None:
            return {
                "status": "FINALIZED",
                "wallet_id": wallet_id,
                "identity": identity_read["identity"],
            }
        if identity_read.get("error") is not None:
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
                    raise ValueError("canonical wallet sequence is unavailable")
                if hypervisor_service.ledger_operation_service.reconcile_wallet_sequence(
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
                raise ValueError("canonical wallet sequence is unavailable")
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

    @router.post("/pair", status_code=204)
    async def pair(payload: PairingRequest, request: Request, response: Response) -> Response:
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
        response.set_cookie(
            _COOKIE_NAME,
            session.session_id,
            httponly=True,
            samesite="strict",
            secure=not allow_insecure_lan,
            path=_COOKIE_PATH,
            max_age=_COOKIE_MAX_AGE[payload.duration],
        )
        return Response(status_code=204, headers=dict(response.headers))

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
        if invalidate_credential_sessions is not None:
            invalidate_credential_sessions(credential_id)
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
            hypervisor_service.resources.replace_capacity(report.capacity, probe=report.metadata())
        except (OSError, TypeError, ValueError) as error:
            return operation_error(error)
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "resources": hypervisor_service.resources.summary()},
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
            plan = hypervisor_service.build_provider_installation_plan(
                plugin_id=plugin_id,
                configuration=payload.configuration,
            )
            required_permissions = plan.get("required_permissions", [])
            if not isinstance(required_permissions, list):
                raise ValueError("installation plan contains an invalid permission declaration")
            approved_permissions = [
                item["permission_id"]
                for item in required_permissions
                if isinstance(item, dict) and isinstance(item.get("permission_id"), str)
            ]
            if len(approved_permissions) != len(required_permissions):
                raise ValueError("installation plan contains an invalid permission declaration")
            approval = hypervisor_service.approve_provider_installation_plan(
                plugin_id=plugin_id,
                configuration=payload.configuration,
                approved_permissions=approved_permissions,
                upgrade_acknowledged=False,
                selected_secret_handles=[],
                operator_note=payload.operator_note or "Paired Dashboard one-click runtime installation",
            )
            result = hypervisor_service.apply_provider_installation_approval(
                approval["approval_id"]
            )
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
