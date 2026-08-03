import pytest
from pydantic import ValidationError

from aidn_hypervisor.reward.development_bounty import (
    apply_development_bounty_expiry,
    apply_development_bounty_release,
    apply_development_bounty_reservation,
    build_development_bounty,
    build_development_bounty_expiry,
    build_development_bounty_registry,
    build_development_bounty_release,
    build_development_bounty_reservation,
    build_development_bounty_state,
)
from aidn_hypervisor.reward.development_carryover import (
    build_development_carryover_ledger,
    build_development_pool_carryover,
)


def _bounty(*, create_operation_id: str = "bounty-create-1"):
    return build_development_bounty(
        create_operation_id=create_operation_id,
        created_epoch=1,
        title="Conformance audit",
        acceptance_criteria_hash="sha256:criteria",
        eligible_repository_ids=("repo-a", "repo-b"),
        contribution_class="SECURITY",
        minimum_reward_q_atoms=100,
        maximum_reward_q_atoms=800,
        reserved_budget_q_atoms=1_000,
        priority_factor_millionths=1_200_000,
        reviewer_policy="TWO_MAINTAINERS",
        opens_at_epoch=2,
        expires_at_epoch=5,
    )


def _reservation(*, operation_id: str = "bounty-reserve-1", amount: int = 600, source: str = "pool-20"):
    return build_development_bounty_reservation(
        bounty_id=_bounty().bounty_id,
        operation_id=operation_id,
        source_pool_id="GENERAL_DEVELOPMENT",
        source_pool_reference=source,
        reservation_epoch=2,
        amount_q_atoms=amount,
    )


def test_carryover_records_split_uncommitted_pool_and_are_conservative():
    record = build_development_pool_carryover(
        operation_id="carryover-1",
        source_pool_id="GENERAL_DEVELOPMENT",
        target_pool_id="GENERAL_DEVELOPMENT",
        source_epoch=20,
        target_epoch=21,
        source_pool_reference="pool-hash-20",
        target_pool_reference="pool-hash-21",
        source_pool_q_atoms=1_000,
        committed_q_atoms=300,
        uncommitted_q_atoms=700,
        carryover_limit_q_atoms=500,
        carried_q_atoms=500,
        returned_to_emission_reserve_q_atoms=200,
    )

    assert record.source_conservation_q_atoms == record.source_pool_q_atoms
    assert record.verify_integrity()
    assert record.model_config.get("frozen") is True

    ledger = build_development_carryover_ledger().append(record)
    assert ledger.append(record) == ledger
    assert ledger.verify_integrity()


def test_carryover_rejects_over_cap_and_natural_key_conflicts():
    with pytest.raises(ValueError, match="DEVELOPMENT_POOL_CARRYOVER_CAP_EXCEEDED"):
        build_development_pool_carryover(
            operation_id="carryover-over-cap",
            source_pool_id="GENERAL_DEVELOPMENT",
            target_pool_id="GENERAL_DEVELOPMENT",
            source_epoch=20,
            target_epoch=21,
            source_pool_reference="pool-hash-20",
            target_pool_reference="pool-hash-21",
            source_pool_q_atoms=1_000,
            committed_q_atoms=300,
            uncommitted_q_atoms=700,
            carryover_limit_q_atoms=499,
            carried_q_atoms=500,
            returned_to_emission_reserve_q_atoms=200,
        )

    first = build_development_pool_carryover(
        operation_id="carryover-1",
        source_pool_id="GENERAL_DEVELOPMENT",
        target_pool_id="GENERAL_DEVELOPMENT",
        source_epoch=20,
        target_epoch=21,
        source_pool_reference="pool-hash-20",
        target_pool_reference="pool-hash-21",
        source_pool_q_atoms=1_000,
        committed_q_atoms=300,
        uncommitted_q_atoms=700,
        carryover_limit_q_atoms=500,
        carried_q_atoms=500,
        returned_to_emission_reserve_q_atoms=200,
    )
    conflicting = build_development_pool_carryover(
        operation_id="carryover-2",
        source_pool_id="GENERAL_DEVELOPMENT",
        target_pool_id="GENERAL_DEVELOPMENT",
        source_epoch=20,
        target_epoch=21,
        source_pool_reference="pool-hash-20",
        target_pool_reference="pool-hash-21",
        source_pool_q_atoms=1_000,
        committed_q_atoms=300,
        uncommitted_q_atoms=700,
        carryover_limit_q_atoms=500,
        carried_q_atoms=500,
        returned_to_emission_reserve_q_atoms=200,
    )
    with pytest.raises(ValueError, match="DEVELOPMENT_POOL_CARRYOVER_CONFLICT"):
        build_development_carryover_ledger().append(first).append(conflicting)


def test_bounty_create_is_immutable_and_duplicate_create_is_idempotent():
    bounty = _bounty()
    with pytest.raises(ValidationError):
        bounty.title = "changed"

    registry = build_development_bounty_registry().register(bounty)
    assert registry.register(bounty) == registry
    assert registry.verify_integrity()

    conflicting_create = _bounty(create_operation_id="bounty-create-2")
    assert conflicting_create.bounty_id == bounty.bounty_id
    with pytest.raises(ValueError, match="DEVELOPMENT_BOUNTY_CONFLICT"):
        registry.register(conflicting_create)


def test_bounty_reservation_release_preserves_budget_and_replays_safely():
    bounty = _bounty()
    state = build_development_bounty_state(bounty)
    reservation = _reservation()
    state = apply_development_bounty_reservation(state, reservation)

    assert state.state == "RESERVED"
    assert state.reserved_q_atoms == 600
    assert state.available_q_atoms == 400
    assert apply_development_bounty_reservation(state, reservation) == state

    release = build_development_bounty_release(
        bounty=bounty,
        reservation=reservation,
        operation_id="bounty-release-1",
        contribution_id="contribution-1",
        release_epoch=3,
        released_q_atoms=500,
    )
    state = apply_development_bounty_release(state, release)
    assert state.state == "RELEASED"
    assert state.reserved_q_atoms == 0
    assert state.released_q_atoms == 500
    assert state.returned_q_atoms == 100
    assert state.available_q_atoms == 400
    assert state.bounty.reserved_budget_q_atoms == (
        state.available_q_atoms
        + state.reserved_q_atoms
        + state.released_q_atoms
        + state.returned_q_atoms
    )
    assert apply_development_bounty_release(state, release) == state


def test_bounty_rejects_over_cap_duplicate_conflict_and_closed_reservation():
    bounty = _bounty()
    state = build_development_bounty_state(bounty)
    reservation = _reservation()

    too_large = _reservation(operation_id="bounty-reserve-large", amount=801)
    with pytest.raises(ValueError, match="DEVELOPMENT_BOUNTY_RESERVATION_OVER_CAP"):
        apply_development_bounty_reservation(state, too_large)

    state = apply_development_bounty_reservation(state, reservation)
    conflicting = _reservation(operation_id="bounty-reserve-2")
    with pytest.raises(ValueError, match="DEVELOPMENT_BOUNTY_EVENT_CONFLICT"):
        apply_development_bounty_reservation(state, conflicting)

    release = build_development_bounty_release(
        bounty=bounty,
        reservation=reservation,
        operation_id="bounty-release-1",
        contribution_id="contribution-1",
        release_epoch=3,
        released_q_atoms=500,
    )
    state = apply_development_bounty_release(state, release)
    second_reservation = build_development_bounty_reservation(
        bounty_id=bounty.bounty_id,
        operation_id="bounty-reserve-3",
        source_pool_id="GENERAL_DEVELOPMENT",
        source_pool_reference="pool-21",
        reservation_epoch=4,
        amount_q_atoms=200,
    )
    with pytest.raises(ValueError, match="DEVELOPMENT_BOUNTY_NOT_OPEN"):
        apply_development_bounty_reservation(state, second_reservation)


def test_bounty_expiry_returns_all_active_reservations_and_is_idempotent():
    bounty = _bounty()
    state = build_development_bounty_state(bounty)
    first = _reservation(operation_id="bounty-reserve-1", amount=400, source="pool-20")
    second = _reservation(operation_id="bounty-reserve-2", amount=300, source="pool-21")
    state = apply_development_bounty_reservation(state, first)
    state = apply_development_bounty_reservation(state, second)

    expiry = build_development_bounty_expiry(
        bounty=bounty,
        reservations=(first, second),
        operation_id="bounty-expiry-1",
        expiry_epoch=6,
    )
    state = apply_development_bounty_expiry(state, expiry)
    assert state.state == "EXPIRED"
    assert state.reserved_q_atoms == 0
    assert state.released_q_atoms == 0
    assert state.returned_q_atoms == 700
    assert state.available_q_atoms == 300
    assert apply_development_bounty_expiry(state, expiry) == state


def test_bounty_expiry_requires_expiry_boundary_and_all_active_reservations():
    bounty = _bounty()
    state = build_development_bounty_state(bounty)
    reservation = _reservation()
    state = apply_development_bounty_reservation(state, reservation)

    before_expiry = build_development_bounty_expiry(
        bounty=bounty,
        reservations=(reservation,),
        operation_id="bounty-expiry-early",
        expiry_epoch=5,
    )
    with pytest.raises(ValueError, match="DEVELOPMENT_BOUNTY_EXPIRY_NOT_REACHED"):
        apply_development_bounty_expiry(state, before_expiry)

    second = _reservation(
        operation_id="bounty-reserve-2",
        amount=200,
        source="pool-21",
    )
    state = apply_development_bounty_reservation(state, second)
    incomplete = build_development_bounty_expiry(
        bounty=bounty,
        reservations=(reservation,),
        operation_id="bounty-expiry-incomplete",
        expiry_epoch=6,
    )
    with pytest.raises(ValueError, match="DEVELOPMENT_BOUNTY_EXPIRY_RESERVATIONS_INCOMPLETE"):
        apply_development_bounty_expiry(state, incomplete)
