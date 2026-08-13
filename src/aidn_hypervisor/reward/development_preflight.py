"""Canonical read-only preflight for ECO-0007 production batches.

The preflight exposes only the finalized epoch transition and the bounded
budget reference required to construct a production batch. Contribution
evidence and contributor data remain outside the validator query surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_distribution import canonical_hash

if TYPE_CHECKING:
    from aidn_hypervisor.ledger.service import LedgerOperationService


DEVELOPMENT_REWARD_PREFLIGHT_VERSION = "eco-0007-reward-preflight.v1"


class DevelopmentRewardPreflight(BaseModel, frozen=True):
    """Compact validator projection used before a production reward batch."""

    schema_version: str = DEVELOPMENT_REWARD_PREFLIGHT_VERSION
    status: Literal["READY", "NO_BUDGET", "UNAVAILABLE"]
    pool_id: str = Field(min_length=1)
    epoch: int | None = Field(default=None, ge=0)
    opening_epoch: int | None = Field(default=None, ge=0)
    source_epoch_transition_operation_id: str | None = None
    source_epoch_transition_sequence_id: int | None = Field(default=None, ge=1)
    source_epoch_transition_record_digest: str | None = None
    pool_budget_q_atoms: int | None = Field(default=None, ge=0)
    pool_budget_reference: str | None = None
    reason_code: str | None = None
    preflight_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_preflight(self) -> DevelopmentRewardPreflight:
        if self.schema_version != DEVELOPMENT_REWARD_PREFLIGHT_VERSION:
            raise ValueError("DEVELOPMENT_PREFLIGHT_VERSION_INVALID")
        if self.status == "READY":
            required = (
                self.epoch,
                self.opening_epoch,
                self.source_epoch_transition_operation_id,
                self.source_epoch_transition_sequence_id,
                self.source_epoch_transition_record_digest,
                self.pool_budget_q_atoms,
                self.pool_budget_reference,
            )
            if any(value in {None, ""} for value in required):
                raise ValueError("DEVELOPMENT_PREFLIGHT_READY_FIELDS_MISSING")
            if self.pool_budget_q_atoms <= 0:
                raise ValueError("DEVELOPMENT_PREFLIGHT_READY_BUDGET_INVALID")
            if self.opening_epoch != self.epoch + 1:
                raise ValueError("DEVELOPMENT_PREFLIGHT_EPOCH_INVALID")
        if self.preflight_hash != development_reward_preflight_hash(self):
            raise ValueError("DEVELOPMENT_PREFLIGHT_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"preflight_hash"})

    def verify_integrity(self) -> bool:
        return self.preflight_hash == development_reward_preflight_hash(self)


def development_reward_preflight_hash(preflight: DevelopmentRewardPreflight) -> str:
    """Hash the public preflight without including its self-referential hash."""

    return canonical_hash(preflight.unsigned_payload())


def build_development_reward_preflight(
    ledger: LedgerOperationService,
    *,
    pool_id: str = "GENERAL_DEVELOPMENT",
) -> DevelopmentRewardPreflight:
    """Build a deterministic projection from finalized Ledger operations."""

    if not isinstance(pool_id, str) or not pool_id.strip() or "/" in pool_id or "\\" in pool_id:
        raise ValueError("DEVELOPMENT_PREFLIGHT_POOL_ID_INVALID")

    transition = next(
        (
            operation
            for operation in reversed(ledger.list_operations())
            if operation.get("operation_type") == "EPOCH_TRANSITION"
        ),
        None,
    )
    if transition is None:
        return _build_unavailable(
            pool_id=pool_id,
            reason_code="DEVELOPMENT_REWARD_EPOCH_TRANSITION_UNAVAILABLE",
        )

    operation_id = transition.get("operation_id")
    payload = transition.get("payload") or {}
    closing_epoch = payload.get("closing_epoch")
    opening_epoch = payload.get("opening_epoch")
    pool_budgets = payload.get("pool_budgets")
    pool_references = payload.get("pool_budget_references")
    if (
        not isinstance(operation_id, str)
        or not operation_id.strip()
        or isinstance(closing_epoch, bool)
        or not isinstance(closing_epoch, int)
        or closing_epoch < 0
        or isinstance(opening_epoch, bool)
        or not isinstance(opening_epoch, int)
        or opening_epoch != closing_epoch + 1
    ):
        return _build_unavailable(
            pool_id=pool_id,
            reason_code="DEVELOPMENT_REWARD_EPOCH_TRANSITION_INVALID",
            epoch=closing_epoch if isinstance(closing_epoch, int) and closing_epoch >= 0 else None,
            opening_epoch=opening_epoch if isinstance(opening_epoch, int) and opening_epoch >= 0 else None,
        )

    reference = ledger.finalized_operation_reference(operation_id)
    if reference is None:
        return _build_unavailable(
            pool_id=pool_id,
            reason_code="DEVELOPMENT_REWARD_EPOCH_TRANSITION_NOT_FINALIZED",
            epoch=closing_epoch,
            opening_epoch=opening_epoch,
            source_epoch_transition_operation_id=operation_id,
        )

    budget = pool_budgets.get(pool_id) if isinstance(pool_budgets, dict) else None
    pool_reference = pool_references.get(pool_id) if isinstance(pool_references, dict) else None
    if (
        isinstance(budget, bool)
        or not isinstance(budget, int)
        or budget < 0
        or not isinstance(pool_reference, str)
        or not pool_reference.strip()
    ):
        return _build_unavailable(
            pool_id=pool_id,
            reason_code="DEVELOPMENT_REWARD_POOL_BUDGET_UNAVAILABLE",
            epoch=closing_epoch,
            opening_epoch=opening_epoch,
            source_epoch_transition_operation_id=operation_id,
            source_epoch_transition_sequence_id=reference.get("sequence_id"),
            source_epoch_transition_record_digest=reference.get("record_digest"),
        )

    status: Literal["READY", "NO_BUDGET"] = "READY" if budget > 0 else "NO_BUDGET"
    return _build(
        status=status,
        pool_id=pool_id,
        epoch=closing_epoch,
        opening_epoch=opening_epoch,
        source_epoch_transition_operation_id=operation_id,
        source_epoch_transition_sequence_id=reference.get("sequence_id"),
        source_epoch_transition_record_digest=reference.get("record_digest"),
        pool_budget_q_atoms=budget,
        pool_budget_reference=pool_reference,
        reason_code=None if status == "READY" else "DEVELOPMENT_REWARD_POOL_BUDGET_ZERO",
    )


def _build_unavailable(*, pool_id: str, reason_code: str, **fields: Any) -> DevelopmentRewardPreflight:
    return _build(
        status="UNAVAILABLE",
        pool_id=pool_id,
        reason_code=reason_code,
        **fields,
    )


def _build(*, status: Literal["READY", "NO_BUDGET", "UNAVAILABLE"], **fields: Any) -> DevelopmentRewardPreflight:
    payload = {
        "schema_version": DEVELOPMENT_REWARD_PREFLIGHT_VERSION,
        "status": status,
        "pool_id": fields.get("pool_id"),
        "epoch": fields.get("epoch"),
        "opening_epoch": fields.get("opening_epoch"),
        "source_epoch_transition_operation_id": fields.get("source_epoch_transition_operation_id"),
        "source_epoch_transition_sequence_id": fields.get("source_epoch_transition_sequence_id"),
        "source_epoch_transition_record_digest": fields.get("source_epoch_transition_record_digest"),
        "pool_budget_q_atoms": fields.get("pool_budget_q_atoms"),
        "pool_budget_reference": fields.get("pool_budget_reference"),
        "reason_code": fields.get("reason_code"),
    }
    return DevelopmentRewardPreflight(
        **payload,
        preflight_hash=canonical_hash(payload),
    )
