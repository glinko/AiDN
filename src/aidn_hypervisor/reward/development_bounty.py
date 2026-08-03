"""Bounded ECO-0007 bounty lifecycle domain records.

The lifecycle is event-shaped but remains a pure domain layer.  Creation,
reservation, release and expiry return immutable Pydantic records; applying a
record produces a new immutable state.  No operation envelope, Ledger write,
Wallet transfer or Q mint is performed here.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_distribution import canonical_hash

DEVELOPMENT_BOUNTY_VERSION = "eco-0007-bounty.v1"
DEVELOPMENT_BOUNTY_RESERVATION_VERSION = "eco-0007-bounty-reservation.v1"
DEVELOPMENT_BOUNTY_RELEASE_VERSION = "eco-0007-bounty-release.v1"
DEVELOPMENT_BOUNTY_EXPIRY_VERSION = "eco-0007-bounty-expiry.v1"
DEVELOPMENT_BOUNTY_STATE_VERSION = "eco-0007-bounty-state.v1"
DEVELOPMENT_BOUNTY_REGISTRY_VERSION = "eco-0007-bounty-registry.v1"

BountyEventType = Literal["RESERVATION", "RELEASE", "EXPIRY"]
BountyState = Literal["OPEN", "RESERVED", "RELEASED", "EXPIRED"]


def development_bounty_id(
    *,
    title: str,
    acceptance_criteria_hash: str,
    eligible_repository_ids: tuple[str, ...],
    contribution_class: str,
    minimum_reward_q_atoms: int,
    maximum_reward_q_atoms: int,
    reserved_budget_q_atoms: int,
    priority_factor_millionths: int,
    reviewer_policy: str,
    opens_at_epoch: int,
    expires_at_epoch: int,
) -> str:
    """Derive a semantic bounty identity, excluding envelope metadata."""

    return canonical_hash(
        {
            "bounty_version": DEVELOPMENT_BOUNTY_VERSION,
            "title": title,
            "acceptance_criteria_hash": acceptance_criteria_hash,
            "eligible_repository_ids": list(eligible_repository_ids),
            "contribution_class": contribution_class,
            "minimum_reward_q_atoms": minimum_reward_q_atoms,
            "maximum_reward_q_atoms": maximum_reward_q_atoms,
            "reserved_budget_q_atoms": reserved_budget_q_atoms,
            "priority_factor_millionths": priority_factor_millionths,
            "reviewer_policy": reviewer_policy,
            "opens_at_epoch": opens_at_epoch,
            "expires_at_epoch": expires_at_epoch,
        }
    )


class DevelopmentBounty(BaseModel, frozen=True):
    """Immutable definition and funding ceiling of one development bounty."""

    bounty_version: str = DEVELOPMENT_BOUNTY_VERSION
    bounty_id: str = Field(min_length=1)
    create_operation_id: str = Field(min_length=1)
    created_epoch: int = Field(ge=0)
    title: str = Field(min_length=1)
    acceptance_criteria_hash: str = Field(min_length=1)
    eligible_repository_ids: tuple[str, ...] = Field(min_length=1)
    contribution_class: str = Field(min_length=1)
    minimum_reward_q_atoms: int = Field(gt=0)
    maximum_reward_q_atoms: int = Field(gt=0)
    reserved_budget_q_atoms: int = Field(gt=0)
    priority_factor_millionths: int = Field(ge=0, le=10_000_000)
    reviewer_policy: str = Field(min_length=1)
    opens_at_epoch: int = Field(ge=0)
    expires_at_epoch: int = Field(gt=0)
    state: Literal["OPEN"] = "OPEN"
    bounty_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bounty_invariants(self) -> DevelopmentBounty:
        if self.bounty_version != DEVELOPMENT_BOUNTY_VERSION:
            raise ValueError("DEVELOPMENT_BOUNTY_VERSION_INVALID")
        if tuple(sorted(set(self.eligible_repository_ids))) != self.eligible_repository_ids:
            raise ValueError("DEVELOPMENT_BOUNTY_REPOSITORIES_INVALID")
        if self.minimum_reward_q_atoms > self.maximum_reward_q_atoms:
            raise ValueError("DEVELOPMENT_BOUNTY_REWARD_RANGE_INVALID")
        if self.maximum_reward_q_atoms > self.reserved_budget_q_atoms:
            raise ValueError("DEVELOPMENT_BOUNTY_BUDGET_INVALID")
        if self.expires_at_epoch <= self.opens_at_epoch:
            raise ValueError("DEVELOPMENT_BOUNTY_EPOCH_RANGE_INVALID")
        expected_id = development_bounty_id(
            title=self.title,
            acceptance_criteria_hash=self.acceptance_criteria_hash,
            eligible_repository_ids=self.eligible_repository_ids,
            contribution_class=self.contribution_class,
            minimum_reward_q_atoms=self.minimum_reward_q_atoms,
            maximum_reward_q_atoms=self.maximum_reward_q_atoms,
            reserved_budget_q_atoms=self.reserved_budget_q_atoms,
            priority_factor_millionths=self.priority_factor_millionths,
            reviewer_policy=self.reviewer_policy,
            opens_at_epoch=self.opens_at_epoch,
            expires_at_epoch=self.expires_at_epoch,
        )
        if self.bounty_id != expected_id:
            raise ValueError("DEVELOPMENT_BOUNTY_ID_INVALID")
        if self.bounty_hash != canonical_hash(self.unsigned_payload()):
            raise ValueError("DEVELOPMENT_BOUNTY_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"bounty_hash"})

    def verify_integrity(self) -> bool:
        return self.bounty_hash == canonical_hash(self.unsigned_payload())


def build_development_bounty(
    *,
    create_operation_id: str,
    created_epoch: int,
    title: str,
    acceptance_criteria_hash: str,
    eligible_repository_ids: tuple[str, ...],
    contribution_class: str,
    minimum_reward_q_atoms: int,
    maximum_reward_q_atoms: int,
    reserved_budget_q_atoms: int,
    priority_factor_millionths: int,
    reviewer_policy: str,
    opens_at_epoch: int,
    expires_at_epoch: int,
) -> DevelopmentBounty:
    """Build a deterministic bounty definition."""

    if not create_operation_id.strip():
        raise ValueError("DEVELOPMENT_BOUNTY_OPERATION_INVALID")
    bounty_id = development_bounty_id(
        title=title,
        acceptance_criteria_hash=acceptance_criteria_hash,
        eligible_repository_ids=eligible_repository_ids,
        contribution_class=contribution_class,
        minimum_reward_q_atoms=minimum_reward_q_atoms,
        maximum_reward_q_atoms=maximum_reward_q_atoms,
        reserved_budget_q_atoms=reserved_budget_q_atoms,
        priority_factor_millionths=priority_factor_millionths,
        reviewer_policy=reviewer_policy,
        opens_at_epoch=opens_at_epoch,
        expires_at_epoch=expires_at_epoch,
    )
    payload = {
        "bounty_version": DEVELOPMENT_BOUNTY_VERSION,
        "bounty_id": bounty_id,
        "create_operation_id": create_operation_id,
        "created_epoch": created_epoch,
        "title": title,
        "acceptance_criteria_hash": acceptance_criteria_hash,
        "eligible_repository_ids": eligible_repository_ids,
        "contribution_class": contribution_class,
        "minimum_reward_q_atoms": minimum_reward_q_atoms,
        "maximum_reward_q_atoms": maximum_reward_q_atoms,
        "reserved_budget_q_atoms": reserved_budget_q_atoms,
        "priority_factor_millionths": priority_factor_millionths,
        "reviewer_policy": reviewer_policy,
        "opens_at_epoch": opens_at_epoch,
        "expires_at_epoch": expires_at_epoch,
        "state": "OPEN",
    }
    return DevelopmentBounty(**payload, bounty_hash=canonical_hash(payload))


class DevelopmentBountyReservation(BaseModel, frozen=True):
    """Immutable reservation of bounty budget from one source pool."""

    reservation_version: str = DEVELOPMENT_BOUNTY_RESERVATION_VERSION
    reservation_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    bounty_id: str = Field(min_length=1)
    source_pool_id: str = Field(min_length=1)
    source_pool_reference: str = Field(min_length=1)
    reservation_epoch: int = Field(ge=0)
    amount_q_atoms: int = Field(gt=0)
    state: Literal["RESERVED"] = "RESERVED"
    record_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_reservation_invariants(self) -> DevelopmentBountyReservation:
        if self.reservation_version != DEVELOPMENT_BOUNTY_RESERVATION_VERSION:
            raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_VERSION_INVALID")
        expected_id = development_bounty_reservation_id(
            bounty_id=self.bounty_id,
            source_pool_id=self.source_pool_id,
            source_pool_reference=self.source_pool_reference,
            reservation_epoch=self.reservation_epoch,
            amount_q_atoms=self.amount_q_atoms,
        )
        if self.reservation_id != expected_id:
            raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_ID_INVALID")
        if self.record_hash != canonical_hash(self.unsigned_payload()):
            raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"record_hash"})

    def verify_integrity(self) -> bool:
        return self.record_hash == canonical_hash(self.unsigned_payload())


def development_bounty_reservation_id(
    *,
    bounty_id: str,
    source_pool_id: str,
    source_pool_reference: str,
    reservation_epoch: int,
    amount_q_atoms: int,
) -> str:
    return canonical_hash(
        {
            "reservation_version": DEVELOPMENT_BOUNTY_RESERVATION_VERSION,
            "bounty_id": bounty_id,
            "source_pool_id": source_pool_id,
            "source_pool_reference": source_pool_reference,
            "reservation_epoch": reservation_epoch,
            "amount_q_atoms": amount_q_atoms,
        }
    )


def build_development_bounty_reservation(
    *,
    bounty_id: str,
    operation_id: str,
    source_pool_id: str,
    source_pool_reference: str,
    reservation_epoch: int,
    amount_q_atoms: int,
) -> DevelopmentBountyReservation:
    """Build a deterministic reservation event."""

    if not operation_id.strip():
        raise ValueError("DEVELOPMENT_BOUNTY_OPERATION_INVALID")
    reservation_id = development_bounty_reservation_id(
        bounty_id=bounty_id,
        source_pool_id=source_pool_id,
        source_pool_reference=source_pool_reference,
        reservation_epoch=reservation_epoch,
        amount_q_atoms=amount_q_atoms,
    )
    payload = {
        "reservation_version": DEVELOPMENT_BOUNTY_RESERVATION_VERSION,
        "reservation_id": reservation_id,
        "operation_id": operation_id,
        "bounty_id": bounty_id,
        "source_pool_id": source_pool_id,
        "source_pool_reference": source_pool_reference,
        "reservation_epoch": reservation_epoch,
        "amount_q_atoms": amount_q_atoms,
        "state": "RESERVED",
    }
    return DevelopmentBountyReservation(**payload, record_hash=canonical_hash(payload))


class DevelopmentBountyRelease(BaseModel, frozen=True):
    """Immutable successful release of one reservation."""

    release_version: str = DEVELOPMENT_BOUNTY_RELEASE_VERSION
    release_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    bounty_id: str = Field(min_length=1)
    reservation_id: str = Field(min_length=1)
    contribution_id: str = Field(min_length=1)
    release_epoch: int = Field(ge=0)
    released_q_atoms: int = Field(gt=0)
    returned_q_atoms: int = Field(ge=0)
    return_destination: Literal["CARRYOVER"] = "CARRYOVER"
    state: Literal["RELEASED"] = "RELEASED"
    record_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_release_invariants(self) -> DevelopmentBountyRelease:
        if self.release_version != DEVELOPMENT_BOUNTY_RELEASE_VERSION:
            raise ValueError("DEVELOPMENT_BOUNTY_RELEASE_VERSION_INVALID")
        expected_id = development_bounty_release_id(
            bounty_id=self.bounty_id,
            reservation_id=self.reservation_id,
            contribution_id=self.contribution_id,
            release_epoch=self.release_epoch,
            released_q_atoms=self.released_q_atoms,
            returned_q_atoms=self.returned_q_atoms,
            return_destination=self.return_destination,
        )
        if self.release_id != expected_id:
            raise ValueError("DEVELOPMENT_BOUNTY_RELEASE_ID_INVALID")
        if self.record_hash != canonical_hash(self.unsigned_payload()):
            raise ValueError("DEVELOPMENT_BOUNTY_RELEASE_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"record_hash"})

    def verify_integrity(self) -> bool:
        return self.record_hash == canonical_hash(self.unsigned_payload())


def development_bounty_release_id(
    *,
    bounty_id: str,
    reservation_id: str,
    contribution_id: str,
    release_epoch: int,
    released_q_atoms: int,
    returned_q_atoms: int,
    return_destination: str = "CARRYOVER",
) -> str:
    return canonical_hash(
        {
            "release_version": DEVELOPMENT_BOUNTY_RELEASE_VERSION,
            "bounty_id": bounty_id,
            "reservation_id": reservation_id,
            "contribution_id": contribution_id,
            "release_epoch": release_epoch,
            "released_q_atoms": released_q_atoms,
            "returned_q_atoms": returned_q_atoms,
            "return_destination": return_destination,
        }
    )


def build_development_bounty_release(
    *,
    bounty: DevelopmentBounty,
    reservation: DevelopmentBountyReservation,
    operation_id: str,
    contribution_id: str,
    release_epoch: int,
    released_q_atoms: int,
    return_destination: Literal["CARRYOVER"] = "CARRYOVER",
) -> DevelopmentBountyRelease:
    """Build a release whose returned amount closes the reservation exactly."""

    if not operation_id.strip():
        raise ValueError("DEVELOPMENT_BOUNTY_OPERATION_INVALID")
    if reservation.bounty_id != bounty.bounty_id:
        raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_BOUNTY_MISMATCH")
    if released_q_atoms <= 0 or released_q_atoms > reservation.amount_q_atoms:
        raise ValueError("DEVELOPMENT_BOUNTY_RELEASE_AMOUNT_INVALID")
    returned_q_atoms = reservation.amount_q_atoms - released_q_atoms
    release_id = development_bounty_release_id(
        bounty_id=bounty.bounty_id,
        reservation_id=reservation.reservation_id,
        contribution_id=contribution_id,
        release_epoch=release_epoch,
        released_q_atoms=released_q_atoms,
        returned_q_atoms=returned_q_atoms,
        return_destination=return_destination,
    )
    payload = {
        "release_version": DEVELOPMENT_BOUNTY_RELEASE_VERSION,
        "release_id": release_id,
        "operation_id": operation_id,
        "bounty_id": bounty.bounty_id,
        "reservation_id": reservation.reservation_id,
        "contribution_id": contribution_id,
        "release_epoch": release_epoch,
        "released_q_atoms": released_q_atoms,
        "returned_q_atoms": returned_q_atoms,
        "return_destination": return_destination,
        "state": "RELEASED",
    }
    return DevelopmentBountyRelease(**payload, record_hash=canonical_hash(payload))


class DevelopmentBountyExpiry(BaseModel, frozen=True):
    """Immutable expiry of all still-active reservations for a bounty."""

    expiry_version: str = DEVELOPMENT_BOUNTY_EXPIRY_VERSION
    expiry_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    bounty_id: str = Field(min_length=1)
    reservation_ids: tuple[str, ...] = Field(min_length=1)
    expiry_epoch: int = Field(ge=0)
    returned_q_atoms: int = Field(gt=0)
    return_destination: Literal["CARRYOVER"] = "CARRYOVER"
    state: Literal["EXPIRED"] = "EXPIRED"
    record_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_expiry_invariants(self) -> DevelopmentBountyExpiry:
        if self.expiry_version != DEVELOPMENT_BOUNTY_EXPIRY_VERSION:
            raise ValueError("DEVELOPMENT_BOUNTY_EXPIRY_VERSION_INVALID")
        if tuple(sorted(set(self.reservation_ids))) != self.reservation_ids:
            raise ValueError("DEVELOPMENT_BOUNTY_EXPIRY_RESERVATIONS_INVALID")
        expected_id = development_bounty_expiry_id(
            bounty_id=self.bounty_id,
            reservation_ids=self.reservation_ids,
            expiry_epoch=self.expiry_epoch,
            returned_q_atoms=self.returned_q_atoms,
            return_destination=self.return_destination,
        )
        if self.expiry_id != expected_id:
            raise ValueError("DEVELOPMENT_BOUNTY_EXPIRY_ID_INVALID")
        if self.record_hash != canonical_hash(self.unsigned_payload()):
            raise ValueError("DEVELOPMENT_BOUNTY_EXPIRY_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"record_hash"})

    def verify_integrity(self) -> bool:
        return self.record_hash == canonical_hash(self.unsigned_payload())


def development_bounty_expiry_id(
    *,
    bounty_id: str,
    reservation_ids: tuple[str, ...],
    expiry_epoch: int,
    returned_q_atoms: int,
    return_destination: str = "CARRYOVER",
) -> str:
    return canonical_hash(
        {
            "expiry_version": DEVELOPMENT_BOUNTY_EXPIRY_VERSION,
            "bounty_id": bounty_id,
            "reservation_ids": list(reservation_ids),
            "expiry_epoch": expiry_epoch,
            "returned_q_atoms": returned_q_atoms,
            "return_destination": return_destination,
        }
    )


def build_development_bounty_expiry(
    *,
    bounty: DevelopmentBounty,
    reservations: tuple[DevelopmentBountyReservation, ...],
    operation_id: str,
    expiry_epoch: int,
    return_destination: Literal["CARRYOVER"] = "CARRYOVER",
) -> DevelopmentBountyExpiry:
    """Build an expiry event from the reservations still held by the bounty."""

    if not operation_id.strip():
        raise ValueError("DEVELOPMENT_BOUNTY_OPERATION_INVALID")
    if not reservations:
        raise ValueError("DEVELOPMENT_BOUNTY_NO_ACTIVE_RESERVATIONS")
    if any(item.bounty_id != bounty.bounty_id for item in reservations):
        raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_BOUNTY_MISMATCH")
    reservation_ids = tuple(sorted(item.reservation_id for item in reservations))
    if len(set(reservation_ids)) != len(reservation_ids):
        raise ValueError("DEVELOPMENT_BOUNTY_EXPIRY_RESERVATIONS_INVALID")
    returned_q_atoms = sum(item.amount_q_atoms for item in reservations)
    expiry_id = development_bounty_expiry_id(
        bounty_id=bounty.bounty_id,
        reservation_ids=reservation_ids,
        expiry_epoch=expiry_epoch,
        returned_q_atoms=returned_q_atoms,
        return_destination=return_destination,
    )
    payload = {
        "expiry_version": DEVELOPMENT_BOUNTY_EXPIRY_VERSION,
        "expiry_id": expiry_id,
        "operation_id": operation_id,
        "bounty_id": bounty.bounty_id,
        "reservation_ids": reservation_ids,
        "expiry_epoch": expiry_epoch,
        "returned_q_atoms": returned_q_atoms,
        "return_destination": return_destination,
        "state": "EXPIRED",
    }
    return DevelopmentBountyExpiry(**payload, record_hash=canonical_hash(payload))


class DevelopmentBountyEventReference(BaseModel, frozen=True):
    """Compact immutable event reference retained in bounty state."""

    event_type: BountyEventType
    event_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    event_hash: str = Field(min_length=1)


class DevelopmentBountyState(BaseModel, frozen=True):
    """Immutable aggregate state derived from bounty lifecycle events."""

    state_version: str = DEVELOPMENT_BOUNTY_STATE_VERSION
    bounty: DevelopmentBounty
    reserved_q_atoms: int = Field(ge=0)
    released_q_atoms: int = Field(ge=0)
    returned_q_atoms: int = Field(ge=0)
    reservations: tuple[DevelopmentBountyReservation, ...] = ()
    resolved_reservation_ids: tuple[str, ...] = ()
    event_history: tuple[DevelopmentBountyEventReference, ...] = ()
    state: BountyState = "OPEN"
    state_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_state_invariants(self) -> DevelopmentBountyState:
        if self.state_version != DEVELOPMENT_BOUNTY_STATE_VERSION:
            raise ValueError("DEVELOPMENT_BOUNTY_STATE_VERSION_INVALID")
        if not self.bounty.verify_integrity():
            raise ValueError("DEVELOPMENT_BOUNTY_HASH_INVALID")
        reservation_ids = [item.reservation_id for item in self.reservations]
        if len(set(reservation_ids)) != len(reservation_ids):
            raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_DUPLICATE")
        source_pool_references = [item.source_pool_reference for item in self.reservations]
        if len(set(source_pool_references)) != len(source_pool_references):
            raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_CONFLICT")
        if any(item.bounty_id != self.bounty.bounty_id for item in self.reservations):
            raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_BOUNTY_MISMATCH")
        resolved = tuple(self.resolved_reservation_ids)
        if len(set(resolved)) != len(resolved) or not set(resolved).issubset(reservation_ids):
            raise ValueError("DEVELOPMENT_BOUNTY_RESOLUTION_INVALID")
        active_amount = sum(
            item.amount_q_atoms
            for item in self.reservations
            if item.reservation_id not in resolved
        )
        if self.reserved_q_atoms != active_amount:
            raise ValueError("DEVELOPMENT_BOUNTY_RESERVED_TOTAL_INVALID")
        accounted = self.reserved_q_atoms + self.released_q_atoms + self.returned_q_atoms
        if accounted > self.bounty.reserved_budget_q_atoms:
            raise ValueError("DEVELOPMENT_BOUNTY_BUDGET_EXCEEDED")
        event_ids = [item.event_id for item in self.event_history]
        operation_ids = [item.operation_id for item in self.event_history]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("DEVELOPMENT_BOUNTY_EVENT_DUPLICATE")
        if len(set(operation_ids)) != len(operation_ids):
            raise ValueError("DEVELOPMENT_BOUNTY_EVENT_OPERATION_CONFLICT")
        has_expiry = any(item.event_type == "EXPIRY" for item in self.event_history)
        active_exists = bool(active_amount)
        expected_state: BountyState = (
            "EXPIRED"
            if has_expiry
            else "RESERVED"
            if active_exists
            else "RELEASED"
            if self.event_history
            else "OPEN"
        )
        if self.state != expected_state:
            raise ValueError("DEVELOPMENT_BOUNTY_STATE_INVALID")
        if self.state_hash != canonical_hash(self.unsigned_payload()):
            raise ValueError("DEVELOPMENT_BOUNTY_STATE_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"state_hash"})

    def verify_integrity(self) -> bool:
        return self.state_hash == canonical_hash(self.unsigned_payload())

    @property
    def available_q_atoms(self) -> int:
        return self.bounty.reserved_budget_q_atoms - (
            self.reserved_q_atoms + self.released_q_atoms + self.returned_q_atoms
        )

    @property
    def active_reservations(self) -> tuple[DevelopmentBountyReservation, ...]:
        resolved = set(self.resolved_reservation_ids)
        return tuple(item for item in self.reservations if item.reservation_id not in resolved)

    def _event_replayed(self, event_id: str, operation_id: str, event_hash: str) -> bool:
        for existing in self.event_history:
            if existing.event_id == event_id or existing.operation_id == operation_id:
                if existing.event_hash == event_hash:
                    return True
                raise ValueError("DEVELOPMENT_BOUNTY_EVENT_CONFLICT")
        return False


def _build_bounty_state(
    *,
    state: DevelopmentBountyState,
    reserved_q_atoms: int,
    released_q_atoms: int,
    returned_q_atoms: int,
    reservations: tuple[DevelopmentBountyReservation, ...],
    resolved_reservation_ids: tuple[str, ...],
    event_history: tuple[DevelopmentBountyEventReference, ...],
) -> DevelopmentBountyState:
    active_exists = any(
        item.reservation_id not in set(resolved_reservation_ids) for item in reservations
    )
    has_expiry = any(item.event_type == "EXPIRY" for item in event_history)
    next_state: BountyState = (
        "EXPIRED"
        if has_expiry
        else "RESERVED"
        if active_exists
        else "RELEASED"
        if event_history
        else "OPEN"
    )
    payload = {
        "state_version": DEVELOPMENT_BOUNTY_STATE_VERSION,
        "bounty": state.bounty,
        "reserved_q_atoms": reserved_q_atoms,
        "released_q_atoms": released_q_atoms,
        "returned_q_atoms": returned_q_atoms,
        "reservations": reservations,
        "resolved_reservation_ids": resolved_reservation_ids,
        "event_history": event_history,
        "state": next_state,
    }
    hash_payload = {
        **payload,
        "bounty": state.bounty.model_dump(mode="json"),
        "reservations": [item.model_dump(mode="json") for item in reservations],
        "event_history": [item.model_dump(mode="json") for item in event_history],
    }
    return DevelopmentBountyState(**payload, state_hash=canonical_hash(hash_payload))


def build_development_bounty_state(bounty: DevelopmentBounty) -> DevelopmentBountyState:
    """Create the empty immutable state for a newly created bounty."""

    payload = {
        "state_version": DEVELOPMENT_BOUNTY_STATE_VERSION,
        "bounty": bounty,
        "reserved_q_atoms": 0,
        "released_q_atoms": 0,
        "returned_q_atoms": 0,
        "reservations": (),
        "resolved_reservation_ids": (),
        "event_history": (),
        "state": "OPEN",
    }
    hash_payload = {
        **payload,
        "bounty": bounty.model_dump(mode="json"),
        "reservations": [],
        "event_history": [],
    }
    return DevelopmentBountyState(**payload, state_hash=canonical_hash(hash_payload))


def apply_development_bounty_reservation(
    state: DevelopmentBountyState,
    reservation: DevelopmentBountyReservation,
) -> DevelopmentBountyState:
    """Apply a reservation, accepting an identical replay as a no-op."""

    if reservation.bounty_id != state.bounty.bounty_id:
        raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_BOUNTY_MISMATCH")
    if state._event_replayed(
        reservation.reservation_id,
        reservation.operation_id,
        reservation.record_hash,
    ):
        return state
    if state.state in {"RELEASED", "EXPIRED"}:
        raise ValueError("DEVELOPMENT_BOUNTY_NOT_OPEN")
    if not state.bounty.opens_at_epoch <= reservation.reservation_epoch <= state.bounty.expires_at_epoch:
        raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_EPOCH_INVALID")
    if reservation.amount_q_atoms < state.bounty.minimum_reward_q_atoms:
        raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_BELOW_MINIMUM")
    if reservation.amount_q_atoms > state.bounty.maximum_reward_q_atoms:
        raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_OVER_CAP")
    if reservation.amount_q_atoms > state.available_q_atoms:
        raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_OVER_BUDGET")
    if any(
        item.source_pool_reference == reservation.source_pool_reference
        for item in state.reservations
    ):
        raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_CONFLICT")
    history = (
        *state.event_history,
        DevelopmentBountyEventReference(
            event_type="RESERVATION",
            event_id=reservation.reservation_id,
            operation_id=reservation.operation_id,
            event_hash=reservation.record_hash,
        ),
    )
    return _build_bounty_state(
        state=state,
        reserved_q_atoms=state.reserved_q_atoms + reservation.amount_q_atoms,
        released_q_atoms=state.released_q_atoms,
        returned_q_atoms=state.returned_q_atoms,
        reservations=(*state.reservations, reservation),
        resolved_reservation_ids=state.resolved_reservation_ids,
        event_history=history,
    )


def apply_development_bounty_release(
    state: DevelopmentBountyState,
    release: DevelopmentBountyRelease,
) -> DevelopmentBountyState:
    """Release one active reservation and return its unused remainder."""

    if release.bounty_id != state.bounty.bounty_id:
        raise ValueError("DEVELOPMENT_BOUNTY_RELEASE_BOUNTY_MISMATCH")
    if state._event_replayed(release.release_id, release.operation_id, release.record_hash):
        return state
    reservation = next(
        (item for item in state.reservations if item.reservation_id == release.reservation_id),
        None,
    )
    if reservation is None:
        raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_NOT_FOUND")
    if release.reservation_id in state.resolved_reservation_ids:
        raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_ALREADY_RESOLVED")
    if not state.bounty.minimum_reward_q_atoms <= release.released_q_atoms <= state.bounty.maximum_reward_q_atoms:
        raise ValueError("DEVELOPMENT_BOUNTY_RELEASE_OVER_CAP")
    if release.released_q_atoms > reservation.amount_q_atoms:
        raise ValueError("DEVELOPMENT_BOUNTY_RELEASE_OVER_RESERVATION")
    if release.returned_q_atoms != reservation.amount_q_atoms - release.released_q_atoms:
        raise ValueError("DEVELOPMENT_BOUNTY_RELEASE_CONSERVATION_INVALID")
    if not reservation.reservation_epoch <= release.release_epoch <= state.bounty.expires_at_epoch:
        raise ValueError("DEVELOPMENT_BOUNTY_RELEASE_EPOCH_INVALID")
    history = (
        *state.event_history,
        DevelopmentBountyEventReference(
            event_type="RELEASE",
            event_id=release.release_id,
            operation_id=release.operation_id,
            event_hash=release.record_hash,
        ),
    )
    return _build_bounty_state(
        state=state,
        reserved_q_atoms=state.reserved_q_atoms - reservation.amount_q_atoms,
        released_q_atoms=state.released_q_atoms + release.released_q_atoms,
        returned_q_atoms=state.returned_q_atoms + release.returned_q_atoms,
        reservations=state.reservations,
        resolved_reservation_ids=(*state.resolved_reservation_ids, reservation.reservation_id),
        event_history=history,
    )


def apply_development_bounty_expiry(
    state: DevelopmentBountyState,
    expiry: DevelopmentBountyExpiry,
) -> DevelopmentBountyState:
    """Expire all active reservations and return them to carryover."""

    if expiry.bounty_id != state.bounty.bounty_id:
        raise ValueError("DEVELOPMENT_BOUNTY_EXPIRY_BOUNTY_MISMATCH")
    if state._event_replayed(expiry.expiry_id, expiry.operation_id, expiry.record_hash):
        return state
    if state.state == "EXPIRED":
        raise ValueError("DEVELOPMENT_BOUNTY_ALREADY_EXPIRED")
    if expiry.expiry_epoch <= state.bounty.expires_at_epoch:
        raise ValueError("DEVELOPMENT_BOUNTY_EXPIRY_NOT_REACHED")
    active = state.active_reservations
    active_ids = tuple(sorted(item.reservation_id for item in active))
    if not active:
        raise ValueError("DEVELOPMENT_BOUNTY_NO_ACTIVE_RESERVATIONS")
    if expiry.reservation_ids != active_ids:
        raise ValueError("DEVELOPMENT_BOUNTY_EXPIRY_RESERVATIONS_INCOMPLETE")
    active_amount = sum(item.amount_q_atoms for item in active)
    if expiry.returned_q_atoms != active_amount:
        raise ValueError("DEVELOPMENT_BOUNTY_EXPIRY_CONSERVATION_INVALID")
    history = (
        *state.event_history,
        DevelopmentBountyEventReference(
            event_type="EXPIRY",
            event_id=expiry.expiry_id,
            operation_id=expiry.operation_id,
            event_hash=expiry.record_hash,
        ),
    )
    return _build_bounty_state(
        state=state,
        reserved_q_atoms=0,
        released_q_atoms=state.released_q_atoms,
        returned_q_atoms=state.returned_q_atoms + expiry.returned_q_atoms,
        reservations=state.reservations,
        resolved_reservation_ids=(*state.resolved_reservation_ids, *active_ids),
        event_history=history,
    )


def _registry_payload(states: tuple[DevelopmentBountyState, ...]) -> dict[str, Any]:
    return {
        "registry_version": DEVELOPMENT_BOUNTY_REGISTRY_VERSION,
        "bounties": [item.model_dump(mode="json") for item in states],
    }


class DevelopmentBountyRegistry(BaseModel, frozen=True):
    """Immutable collection with duplicate and conflict protection."""

    registry_version: str = DEVELOPMENT_BOUNTY_REGISTRY_VERSION
    bounties: tuple[DevelopmentBountyState, ...] = ()
    registry_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_registry_invariants(self) -> DevelopmentBountyRegistry:
        if self.registry_version != DEVELOPMENT_BOUNTY_REGISTRY_VERSION:
            raise ValueError("DEVELOPMENT_BOUNTY_REGISTRY_VERSION_INVALID")
        ids = [item.bounty.bounty_id for item in self.bounties]
        if len(set(ids)) != len(ids):
            raise ValueError("DEVELOPMENT_BOUNTY_DUPLICATE")
        if any(not item.verify_integrity() for item in self.bounties):
            raise ValueError("DEVELOPMENT_BOUNTY_STATE_HASH_INVALID")
        if self.registry_hash != canonical_hash(self.unsigned_payload()):
            raise ValueError("DEVELOPMENT_BOUNTY_REGISTRY_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return _registry_payload(self.bounties)

    def verify_integrity(self) -> bool:
        return self.registry_hash == canonical_hash(self.unsigned_payload())

    def register(self, bounty: DevelopmentBounty) -> DevelopmentBountyRegistry:
        """Register a bounty; identical create replay is a no-op."""

        for existing in self.bounties:
            if existing.bounty.bounty_id == bounty.bounty_id:
                if existing.bounty.bounty_hash == bounty.bounty_hash:
                    return self
                raise ValueError("DEVELOPMENT_BOUNTY_CONFLICT")
        state = build_development_bounty_state(bounty)
        return build_development_bounty_registry((*self.bounties, state))

    def _find(self, bounty_id: str) -> DevelopmentBountyState:
        for state in self.bounties:
            if state.bounty.bounty_id == bounty_id:
                return state
        raise ValueError("DEVELOPMENT_BOUNTY_NOT_FOUND")

    def _replace(self, state: DevelopmentBountyState) -> DevelopmentBountyRegistry:
        states = tuple(
            state if item.bounty.bounty_id == state.bounty.bounty_id else item
            for item in self.bounties
        )
        return build_development_bounty_registry(states)

    def apply_reservation(
        self,
        reservation: DevelopmentBountyReservation,
    ) -> DevelopmentBountyRegistry:
        return self._replace(
            apply_development_bounty_reservation(self._find(reservation.bounty_id), reservation)
        )

    def apply_release(self, release: DevelopmentBountyRelease) -> DevelopmentBountyRegistry:
        return self._replace(
            apply_development_bounty_release(self._find(release.bounty_id), release)
        )

    def apply_expiry(self, expiry: DevelopmentBountyExpiry) -> DevelopmentBountyRegistry:
        return self._replace(
            apply_development_bounty_expiry(self._find(expiry.bounty_id), expiry)
        )


def build_development_bounty_registry(
    bounties: tuple[DevelopmentBountyState, ...] = (),
) -> DevelopmentBountyRegistry:
    """Build a validated immutable bounty registry snapshot."""

    ordered = tuple(sorted(bounties, key=lambda item: item.bounty.bounty_id))
    payload = _registry_payload(ordered)
    return DevelopmentBountyRegistry(
        bounties=ordered,
        registry_hash=canonical_hash(payload),
    )


__all__ = [
    "DEVELOPMENT_BOUNTY_EXPIRY_VERSION",
    "DEVELOPMENT_BOUNTY_REGISTRY_VERSION",
    "DEVELOPMENT_BOUNTY_RELEASE_VERSION",
    "DEVELOPMENT_BOUNTY_RESERVATION_VERSION",
    "DEVELOPMENT_BOUNTY_STATE_VERSION",
    "DEVELOPMENT_BOUNTY_VERSION",
    "DevelopmentBounty",
    "DevelopmentBountyEventReference",
    "DevelopmentBountyExpiry",
    "DevelopmentBountyRegistry",
    "DevelopmentBountyRelease",
    "DevelopmentBountyReservation",
    "DevelopmentBountyState",
    "apply_development_bounty_expiry",
    "apply_development_bounty_release",
    "apply_development_bounty_reservation",
    "build_development_bounty",
    "build_development_bounty_expiry",
    "build_development_bounty_registry",
    "build_development_bounty_release",
    "build_development_bounty_reservation",
    "build_development_bounty_state",
    "development_bounty_expiry_id",
    "development_bounty_id",
    "development_bounty_release_id",
    "development_bounty_reservation_id",
]
