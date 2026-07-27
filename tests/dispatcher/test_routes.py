import pytest
from pydantic import ValidationError

from aidn_hypervisor.dispatcher.routes import (
    VALIDATION_MESSAGE_TYPES,
    bind_validation_route,
    validation_route,
)
from aidn_hypervisor.dispatcher.service import NetworkDispatcher


def _make_dispatcher() -> NetworkDispatcher:
    return NetworkDispatcher(
        network_id="test-net",
        chain_id="test-chain",
        network_revision="1",
    )


# ---------------------------------------------------------------------------
# validation_route factory
# ---------------------------------------------------------------------------

class TestValidationRoute:
    def test_returns_active_route(self) -> None:
        route = validation_route(route_generation=1)
        assert route.route_state == "ACTIVE"
        assert route.route_generation == 1

    def test_destination_type_and_id(self) -> None:
        route = validation_route(route_generation=1)
        assert route.destination_type == "VALIDATION_TARGET"
        assert route.destination_id == "validation_handler"

    def test_custom_destination_id(self) -> None:
        route = validation_route(destination_id="custom-validator", route_generation=1)
        assert route.destination_id == "custom-validator"

    def test_route_type_is_local_protocol_handler(self) -> None:
        route = validation_route(route_generation=1)
        assert route.route_type == "LOCAL_PROTOCOL_HANDLER"

    def test_allowed_source_types(self) -> None:
        route = validation_route(route_generation=1)
        assert route.allowed_source_types == {"VALIDATOR"}

    def test_allowed_channel_classes(self) -> None:
        route = validation_route(route_generation=1)
        assert route.allowed_channel_classes == {"VALIDATION"}

    def test_allowed_message_types(self) -> None:
        route = validation_route(route_generation=1)
        assert route.allowed_message_types == VALIDATION_MESSAGE_TYPES

    def test_created_at_is_set(self) -> None:
        route = validation_route(route_generation=1)
        assert route.created_at is not None
        assert isinstance(route.created_at, str)

    def test_no_runtime_binding_hash(self) -> None:
        route = validation_route(route_generation=1)
        assert route.runtime_binding_hash is None

    def test_no_configuration_hash(self) -> None:
        route = validation_route(route_generation=1)
        assert route.configuration_hash is None

    def test_generation_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            validation_route(route_generation=0)


# ---------------------------------------------------------------------------
# bind_validation_route
# ---------------------------------------------------------------------------

class TestBindValidationRoute:
    def test_registers_local_route_and_returns_route(self) -> None:
        dispatcher = _make_dispatcher()
        handler_called = []

        def handler(msg: dict) -> None:
            handler_called.append(msg)

        route = bind_validation_route(
            dispatcher, handler, route_generation=1
        )

        assert route is not None
        assert route.destination_type == "VALIDATION_TARGET"
        assert route.allowed_source_types == {"VALIDATOR"}
        assert route.allowed_channel_classes == {"VALIDATION"}

    def test_custom_destination_id_propagates(self) -> None:
        dispatcher = _make_dispatcher()

        route = bind_validation_route(
            dispatcher, lambda m: None,
            destination_id="my-validator",
            route_generation=1,
        )
        assert route.destination_id == "my-validator"

    def test_handler_is_bound_for_resolution(self) -> None:
        dispatcher = _make_dispatcher()

        def handler(msg: dict) -> dict:
            return {"status": "ok"}

        bind_validation_route(dispatcher, handler, route_generation=1)
        key = ("VALIDATION_TARGET", "validation_handler")
        assert key in dispatcher._handlers

    def test_increments_route_generation_on_rebind(self) -> None:
        dispatcher = _make_dispatcher()

        r1 = bind_validation_route(dispatcher, lambda m: None, route_generation=1)
        r2 = bind_validation_route(dispatcher, lambda m: None, route_generation=2)

        assert r1.route_generation == 1
        assert r2.route_generation == 2
