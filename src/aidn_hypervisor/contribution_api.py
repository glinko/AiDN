"""Non-emitting HTTP API for RFC-0068 contribution evidence."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from aidn_hypervisor.contributions.models import (
    AttestationAuthority,
    ContributionClass,
    ContributionFactorValues,
    ContributionFileChange,
    ContributionRoleAllocation,
    ContributorIdentity,
    EligibleRepository,
    RepositoryContributionProfile,
)
from aidn_hypervisor.contributions.service import (
    ContributionAccountingService,
    ContributionConflictError,
    ContributionNotFoundError,
)
from aidn_hypervisor.reward.development_activation import DevelopmentRewardActivationApproval
from aidn_hypervisor.reward.development_contribution_service import (
    DevelopmentContributionRewardService,
)
from aidn_hypervisor.reward.development_distribution import (
    DevelopmentPoolInput,
    DevelopmentRewardPolicy,
)


class WalletChallengeRequest(BaseModel):
    contributor_id: str = Field(min_length=1)
    source_platform_account: str = Field(min_length=1)
    wallet_address: str = Field(min_length=1)
    expires_at: str | None = None


class WalletBindingRequest(BaseModel):
    challenge_id: str = Field(min_length=1)
    wallet_public_key: str = Field(min_length=1)
    wallet_signature: str = Field(min_length=1)
    source_platform_confirmation_hash: str = Field(min_length=1)
    valid_from: str | None = None


class MergeAttestationRequest(BaseModel):
    repository_id: str = Field(min_length=1)
    pull_request_id: str = Field(min_length=1)
    merge_commit_hash: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    source_commit_hash: str | None = None
    merged_at: str | None = None
    merge_actor: str = Field(min_length=1)
    pull_request_author: str = Field(min_length=1)
    primary_contributor_id: str = Field(min_length=1)
    contribution_epoch: int = Field(ge=0)
    contribution_class: ContributionClass
    file_changes: list[ContributionFileChange] = Field(default_factory=list)
    attestation_authorities: list[AttestationAuthority] = Field(min_length=1)
    source_platform_evidence_hash: str = Field(min_length=1)
    repository_path: str = Field(min_length=1)
    coauthors: list[str] = Field(default_factory=list)
    contribution_group_id: str | None = None
    reward_metadata: dict[str, Any] = Field(default_factory=dict)
    factor_values: ContributionFactorValues = Field(default_factory=ContributionFactorValues)
    role_allocations: list[ContributionRoleAllocation] | None = None
    logical_deliverable: str | None = None


class ChallengeRequest(BaseModel):
    contribution_id: str = Field(min_length=1)
    challenger_id: str = Field(min_length=1)
    challenge_class: str = Field(min_length=1)
    claimed_error: str = Field(min_length=1)
    evidence_root: str = Field(min_length=1)
    challenger_signature: str = Field(min_length=1)
    current_epoch: int = Field(ge=0)
    challenge_id: str | None = None


class ChallengeResolutionRequest(BaseModel):
    resolution: str = Field(min_length=1)
    resolved_by: str = Field(min_length=1)
    evidence_root: str = Field(min_length=1)
    resolver_signature: str = Field(min_length=1)
    corrected_factors: ContributionFactorValues | None = None
    corrected_role_allocations: list[ContributionRoleAllocation] | None = None


class FinalizeRequest(BaseModel):
    current_epoch: int = Field(ge=0)


class MaturityRequest(BaseModel):
    stage: int = Field(ge=1, le=2)
    current_epoch: int = Field(ge=0)
    state: str = Field(min_length=1)
    decision_by: str | None = None
    decision_reason: str | None = None
    evidence_root: str = Field(min_length=1)
    revert_classification: str | None = None


class RewardPreviewRequest(BaseModel):
    pool_input: DevelopmentPoolInput
    contribution_ids: list[str] | None = None
    policy: DevelopmentRewardPolicy | None = None


class RewardPlanRequest(RewardPreviewRequest):
    activation_approval: DevelopmentRewardActivationApproval
    current_epoch: int = Field(ge=0)
    source_epoch_transition_operation_id: str = Field(min_length=1)
    pool_budget_reference: str = Field(min_length=1)
    created_at: str = Field(min_length=1)


def _error_response(error: Exception) -> JSONResponse:
    if isinstance(error, ContributionNotFoundError):
        status_code = 404
        code = str(error.args[0]) if error.args else "CONTRIBUTION_NOT_FOUND"
    elif isinstance(error, ContributionConflictError):
        status_code = 409
        code = str(error.args[0]) if error.args else "CONTRIBUTION_CONFLICT"
    else:
        status_code = 409
        code = str(error.args[0]) if error.args else "CONTRIBUTION_INVALID"
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": str(error)}},
    )


def build_contribution_router(
    service: ContributionAccountingService,
    reward_service: DevelopmentContributionRewardService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/contributions", tags=["contributions"])
    reward_planner = reward_service or DevelopmentContributionRewardService(service)

    @router.get("/status")
    async def status() -> dict[str, object]:
        return {
            "mode": service.mode,
            "emits_q": False,
            "ledger_writes": False,
            "protocol": "RFC-0068",
            "reward_preview": True,
            "reward_execution": "ECO-0007_CONSENSUS_GATED",
        }

    @router.post("/rewards/preview", response_model=None)
    async def reward_preview(payload: RewardPreviewRequest) -> dict[str, Any] | JSONResponse:
        try:
            return reward_planner.preview(
                pool_input=payload.pool_input,
                contribution_ids=payload.contribution_ids,
                policy=payload.policy,
            ).model_dump(mode="json")
        except (ContributionNotFoundError, ValueError) as error:
            return _error_response(error)

    @router.post("/rewards/plan", response_model=None)
    async def reward_plan(payload: RewardPlanRequest) -> dict[str, Any] | JSONResponse:
        try:
            preview = reward_planner.preview(
                pool_input=payload.pool_input,
                contribution_ids=payload.contribution_ids,
                policy=payload.policy,
            )
            return reward_planner.build_consensus_plan(
                preview,
                activation_approval=payload.activation_approval,
                current_epoch=payload.current_epoch,
                source_epoch_transition_operation_id=payload.source_epoch_transition_operation_id,
                pool_budget_reference=payload.pool_budget_reference,
                created_at=payload.created_at,
            ).model_dump(mode="json")
        except (ContributionNotFoundError, ValueError) as error:
            return _error_response(error)

    @router.get("/repositories")
    async def repositories() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in service.list_repositories()]

    @router.post("/repositories", response_model=None)
    async def register_repository(payload: EligibleRepository) -> dict[str, Any] | JSONResponse:
        try:
            return service.register_repository(payload).model_dump(mode="json")
        except (ContributionNotFoundError, ContributionConflictError, ValueError) as error:
            return _error_response(error)

    @router.post("/profiles", response_model=None)
    async def register_profile(payload: RepositoryContributionProfile) -> dict[str, Any] | JSONResponse:
        try:
            return service.register_profile(payload).model_dump(mode="json")
        except (ContributionConflictError, ValueError) as error:
            return _error_response(error)

    @router.get("/contributors")
    async def contributors() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in service.list_contributors()]

    @router.post("/contributors", response_model=None)
    async def register_contributor(payload: ContributorIdentity) -> dict[str, Any] | JSONResponse:
        try:
            return service.register_contributor(payload).model_dump(mode="json")
        except (ContributionConflictError, ValueError) as error:
            return _error_response(error)

    @router.post("/wallet-challenges", response_model=None)
    async def issue_wallet_challenge(
        payload: WalletChallengeRequest,
    ) -> dict[str, Any] | JSONResponse:
        try:
            return service.issue_wallet_binding_challenge(**payload.model_dump()).model_dump(mode="json")
        except (ContributionNotFoundError, ValueError) as error:
            return _error_response(error)

    @router.post("/wallet-bindings", response_model=None)
    async def bind_wallet(payload: WalletBindingRequest) -> dict[str, Any] | JSONResponse:
        try:
            return service.bind_wallet(**payload.model_dump()).model_dump(mode="json")
        except (ContributionNotFoundError, ValueError) as error:
            return _error_response(error)

    @router.get("/attestations")
    async def attestations() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in service.list_attestations()]

    @router.get("/attestations/{contribution_id}", response_model=None)
    async def get_attestation(contribution_id: str) -> dict[str, Any] | JSONResponse:
        try:
            return service.get_attestation(contribution_id).model_dump(mode="json")
        except ContributionNotFoundError as error:
            return _error_response(error)

    @router.post("/attestations", response_model=None)
    async def attest_merge(payload: MergeAttestationRequest) -> dict[str, Any] | JSONResponse:
        try:
            return service.attest_merge(**payload.model_dump()).model_dump(mode="json")
        except (ContributionNotFoundError, ContributionConflictError, ValueError) as error:
            return _error_response(error)

    @router.post("/attestations/{contribution_id}/finalize", response_model=None)
    async def finalize_contribution(
        contribution_id: str,
        payload: FinalizeRequest,
    ) -> dict[str, Any] | JSONResponse:
        try:
            return service.finalize_contribution(
                contribution_id=contribution_id,
                current_epoch=payload.current_epoch,
            ).model_dump(mode="json")
        except (ContributionNotFoundError, ValueError) as error:
            return _error_response(error)

    @router.post("/challenges", response_model=None)
    async def open_challenge(payload: ChallengeRequest) -> dict[str, Any] | JSONResponse:
        try:
            return service.open_challenge(**payload.model_dump()).model_dump(mode="json")
        except (ContributionNotFoundError, ContributionConflictError, ValueError) as error:
            return _error_response(error)

    @router.post("/challenges/{challenge_id}/resolve", response_model=None)
    async def resolve_challenge(
        challenge_id: str,
        payload: ChallengeResolutionRequest,
    ) -> dict[str, Any] | JSONResponse:
        try:
            return service.resolve_challenge(
                challenge_id=challenge_id,
                **payload.model_dump(),
            ).model_dump(mode="json")
        except (ContributionNotFoundError, ContributionConflictError, ValueError) as error:
            return _error_response(error)

    @router.post("/attestations/{contribution_id}/maturity", response_model=None)
    async def record_maturity(
        contribution_id: str,
        payload: MaturityRequest,
    ) -> dict[str, Any] | JSONResponse:
        try:
            return service.record_maturity(
                contribution_id=contribution_id,
                **payload.model_dump(),
            ).model_dump(mode="json")
        except (ContributionNotFoundError, ContributionConflictError, ValueError) as error:
            return _error_response(error)

    @router.get("/maturity")
    async def maturity() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in service.store.list_maturity()]

    return router
