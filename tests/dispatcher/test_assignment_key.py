"""Tests for assignment-key signed transfer envelopes + canonical Hypervisor-key registration.

Sub-task 3.1.4: assignment-key validation on the VALIDATION channel.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aidn_hypervisor.dispatcher import (
    DispatcherError,
    NetworkDispatcher,
    NetworkMessage,
    bind_validation_route,
    canonical_payload_hash,
)
from aidn_hypervisor.dispatcher.models import canonical_payload_bytes
from aidn_hypervisor.dispatcher.routes import validation_route

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dispatcher(*, clock=None) -> NetworkDispatcher:
    return NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
        clock=clock,
    )


def _make_message(
    *,
    message_id: str = "msg-1",
    route_generation: int = 1,
    assignment_key: str | None = None,
    source_subject: dict | None = None,
    destination_subject: dict | None = None,
    expiration_delta: timedelta | None = None,
    now: datetime | None = None,
) -> NetworkMessage:
    body = {"value": "ok"}
    now = now or datetime.now(UTC)
    src = (
        source_subject
        if source_subject is not None
        else {
            "subject_type": "VALIDATOR",
            "subject_id": "validator-1",
        }
    )
    dst = (
        destination_subject
        if destination_subject is not None
        else {
            "subject_type": "VALIDATION_TARGET",
            "subject_id": "validation_handler",
        }
    )
    return NetworkMessage(
        message_id=message_id,
        message_type="VALIDATION_REPORT_TRANSFER",
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
        channel_id="validation-1",
        channel_class="VALIDATION",
        source_subject=src,
        destination_subject=dst,
        source_sequence=1,
        route_generation=route_generation,
        created_at=now.isoformat(),
        expiration=(now + (expiration_delta or timedelta(minutes=5))).isoformat(),
        payload_hash=canonical_payload_hash(body),
        payload_length=len(canonical_payload_bytes(body)),
        payload=body,
        assignment_key=assignment_key,
    )


# ---------------------------------------------------------------------------
# Canonical Hypervisor-key registration
# ---------------------------------------------------------------------------


class TestHypervisorKeyRegistration:
    """Canonical Hypervisor-key registration for the validation channel."""

    def test_validation_route_accepts_hypervisor_key(self) -> None:
        route = validation_route(
            route_generation=1,
            hypervisor_key="hv-key-abc123",
        )
        assert route.hypervisor_key == "hv-key-abc123"
        assert route.route_state == "ACTIVE"

    def test_bind_validation_route_propagates_hypervisor_key(self) -> None:
        dispatcher = _make_dispatcher()
        route = bind_validation_route(
            dispatcher,
            lambda payload: {"ok": True},
            route_generation=1,
            hypervisor_key="hv-key-xyz",
        )
        assert route.hypervisor_key == "hv-key-xyz"
        stored = dispatcher.route(
            destination_type="VALIDATION_TARGET",
            destination_id="validation_handler",
        )
        assert stored is not None
        assert stored.hypervisor_key == "hv-key-xyz"

    def test_register_hypervisor_key_on_existing_route(self) -> None:
        dispatcher = _make_dispatcher()
        bind_validation_route(
            dispatcher,
            lambda payload: {"ok": True},
            route_generation=1,
        )
        dispatcher.register_hypervisor_key(
            destination_type="VALIDATION_TARGET",
            destination_id="validation_handler",
            hypervisor_key="hv-key-post",
        )
        route = dispatcher.route(
            destination_type="VALIDATION_TARGET",
            destination_id="validation_handler",
        )
        assert route is not None
        assert route.hypervisor_key == "hv-key-post"

    def test_register_hypervisor_key_rejects_unknown_route(self) -> None:
        dispatcher = _make_dispatcher()
        with pytest.raises(ValueError, match="No route found"):
            dispatcher.register_hypervisor_key(
                destination_type="UNKNOWN",
                destination_id="nonexistent",
                hypervisor_key="hv-key",
            )

    def test_without_hypervisor_key_assignment_key_is_optional(self) -> None:
        """When no hypervisor_key is registered, assignment_key is not required."""
        dispatcher = _make_dispatcher()
        bind_validation_route(
            dispatcher,
            lambda payload: {"ok": True},
            route_generation=1,
        )
        msg = _make_message(assignment_key=None)
        record = dispatcher.submit(msg)
        assert record.delivery_state == "QUEUED"


# ---------------------------------------------------------------------------
# Assignment-key validation
# ---------------------------------------------------------------------------


class TestAssignmentKeyValidation:
    """Assignment-key signed transfer envelope validation."""

    def _setup_with_hypervisor_key(self, hv_key: str = "hv-key-abc123"):
        dispatcher = _make_dispatcher()
        bind_validation_route(
            dispatcher,
            lambda payload: {"ok": True},
            route_generation=1,
            hypervisor_key=hv_key,
        )
        return dispatcher

    def test_valid_assignment_key_accepted(self) -> None:
        dispatcher = self._setup_with_hypervisor_key()
        msg = _make_message(assignment_key="hv-key-abc123:assign-1")
        record = dispatcher.submit(msg)
        assert record.delivery_state == "QUEUED"

    def test_invalid_assignment_key_rejected(self) -> None:
        dispatcher = self._setup_with_hypervisor_key()
        msg = _make_message(assignment_key="wrong-key:assign-1")
        with pytest.raises(DispatcherError) as exc_info:
            dispatcher.submit(msg)
        assert exc_info.value.code == "ASSIGNMENT_KEY_INVALID"

    def test_missing_assignment_key_rejected(self) -> None:
        dispatcher = self._setup_with_hypervisor_key()
        msg = _make_message(assignment_key=None)
        with pytest.raises(DispatcherError) as exc_info:
            dispatcher.submit(msg)
        assert exc_info.value.code == "ASSIGNMENT_KEY_MISSING"

    def test_assignment_key_without_suffix_rejected(self) -> None:
        """``hv-key-abc123:`` with empty assignment-id suffix is invalid."""
        dispatcher = self._setup_with_hypervisor_key()
        msg = _make_message(assignment_key="hv-key-abc123:")
        with pytest.raises(DispatcherError) as exc_info:
            dispatcher.submit(msg)
        assert exc_info.value.code == "ASSIGNMENT_KEY_INVALID"

    def test_assignment_key_partial_prefix_rejected(self) -> None:
        """A key that shares a prefix but isn't the full hypervisor_key is invalid."""
        dispatcher = self._setup_with_hypervisor_key(hv_key="hv-key-abc123")
        msg = _make_message(assignment_key="hv-key:assign-1")
        with pytest.raises(DispatcherError) as exc_info:
            dispatcher.submit(msg)
        assert exc_info.value.code == "ASSIGNMENT_KEY_INVALID"

    def test_assignment_key_with_colons_in_suffix_accepted(self) -> None:
        """Assignment-id portion may contain colons."""
        dispatcher = self._setup_with_hypervisor_key()
        msg = _make_message(assignment_key="hv-key-abc123:assign-1:sub-id")
        record = dispatcher.submit(msg)
        assert record.delivery_state == "QUEUED"

    def test_assignment_key_validation_on_drain_once(self) -> None:
        """Assignment-key is re-validated at drain time."""
        dispatcher = self._setup_with_hypervisor_key()
        msg = _make_message(assignment_key="hv-key-abc123:assign-1")
        record = dispatcher.submit(msg)
        assert record.delivery_state == "QUEUED"
        # Drain succeeds with valid key
        delivery, result = dispatcher.drain_once()
        assert delivery.delivery_state == "APPLICATION_ACCEPTED"

    def test_assignment_key_validation_after_hypervisor_key_registration(self) -> None:
        """Messages queued before hypervisor_key registration are rejected on drain."""
        dispatcher = _make_dispatcher()
        bind_validation_route(
            dispatcher,
            lambda payload: {"ok": True},
            route_generation=1,
        )
        # Queue a message without assignment_key (allowed — no hv_key yet)
        msg = _make_message(assignment_key=None)
        record = dispatcher.submit(msg)
        assert record.delivery_state == "QUEUED"
        # Now register the hypervisor_key
        dispatcher.register_hypervisor_key(
            destination_type="VALIDATION_TARGET",
            destination_id="validation_handler",
            hypervisor_key="hv-key-new",
        )
        # Drain should fail because the queued message lacks an assignment_key
        with pytest.raises(DispatcherError) as exc_info:
            dispatcher.drain_once()
        assert exc_info.value.code == "ASSIGNMENT_KEY_MISSING"


# ---------------------------------------------------------------------------
# Expired authorization (dispatcher-level expiration)
# ---------------------------------------------------------------------------


class TestExpiredAuthorization:
    """Expired authorization rejected at the dispatcher level."""

    def test_expired_message_rejected_at_submit(self) -> None:
        dispatcher = _make_dispatcher()
        bind_validation_route(
            dispatcher,
            lambda payload: {"ok": True},
            route_generation=1,
        )
        msg = _make_message(
            message_id="expired-msg",
            expiration_delta=timedelta(seconds=-60),
        )
        with pytest.raises(DispatcherError) as exc_info:
            dispatcher.submit(msg)
        assert exc_info.value.code == "MESSAGE_EXPIRED"

    def test_expired_message_rejected_at_drain(self) -> None:
        """A message that expires while queued is rejected on drain."""
        current_time = datetime.now(UTC)
        dispatcher = _make_dispatcher(clock=lambda: current_time)
        bind_validation_route(
            dispatcher,
            lambda payload: {"ok": True},
            route_generation=1,
        )
        # Submit before expiration, then advance the dispatcher clock.
        msg = _make_message(
            message_id="soon-expired",
            expiration_delta=timedelta(seconds=1),
            now=current_time,
        )
        record = dispatcher.submit(msg)
        assert record.delivery_state == "QUEUED"
        current_time += timedelta(seconds=2)
        with pytest.raises(DispatcherError) as exc_info:
            dispatcher.drain_once()
        assert exc_info.value.code == "MESSAGE_EXPIRED"

    def test_expired_message_with_valid_assignment_key_still_rejected(self) -> None:
        """Even with a valid assignment_key, an expired message is rejected."""
        dispatcher = _make_dispatcher()
        bind_validation_route(
            dispatcher,
            lambda payload: {"ok": True},
            route_generation=1,
            hypervisor_key="hv-key-abc123",
        )
        msg = _make_message(
            message_id="expired-with-key",
            assignment_key="hv-key-abc123:assign-1",
            expiration_delta=timedelta(seconds=-30),
        )
        with pytest.raises(DispatcherError) as exc_info:
            dispatcher.submit(msg)
        assert exc_info.value.code == "MESSAGE_EXPIRED"
