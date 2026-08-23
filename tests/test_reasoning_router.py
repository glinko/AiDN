from aidn_hypervisor.reasoning_router import (
    ReasoningProvider,
    ReasoningProviderRegistry,
    ReasoningRouter,
    ReasoningRouteRequest,
)


def provider(provider_id: str, **overrides):
    values = {
        "provider_id": provider_id,
        "kind": "LOCAL_MODEL",
        "model_id": provider_id,
        "capabilities": ("general", "diagnostic"),
        "context_limit": 131072,
        "allowed_data_classes": ("PUBLIC", "OPERATOR"),
        "latency_ms": 50,
        "cost_q_atoms": 0,
        "available": True,
        "enabled": True,
        "trusted": True,
        "priority": 0,
    }
    values.update(overrides)
    return ReasoningProvider(**values)


def test_router_is_local_first_and_deterministic():
    registry = ReasoningProviderRegistry(
        [
            provider("remote", kind="AIDN_ENDPOINT", priority=100, cost_q_atoms=5),
            provider("local-b", priority=1),
            provider("local-a", priority=1),
        ]
    )
    router = ReasoningRouter(registry)
    request = ReasoningRouteRequest(capability="diagnostic")

    first = router.route(request)
    second = router.route(request)

    assert first["status"] == "ROUTED"
    assert first["selected_provider"]["provider_id"] == "local-a"
    assert first["decision_id"] == second["decision_id"]
    assert first["execution"] == {"started": False, "side_effects": False}


def test_router_rejects_privacy_context_budget_and_external_constraints():
    registry = ReasoningProviderRegistry(
        [
            provider(
                "external",
                kind="EXTERNAL_API",
                allowed_data_classes=("PUBLIC",),
                context_limit=4096,
                cost_q_atoms=50,
            )
        ]
    )
    router = ReasoningRouter(registry)
    result = router.route(
        ReasoningRouteRequest(
            data_class="SENSITIVE",
            minimum_context=8192,
            max_cost_q_atoms=10,
            budget_remaining_q_atoms=5,
            allow_external=False,
        )
    )

    assert result["status"] == "NO_ELIGIBLE_PROVIDER"
    assert result["reason_code"] == "ROUTE_UNAVAILABLE"
    assert result["selected_provider"] is None
    assert result["rejected"][0]["code"] == "CONTEXT_TOO_SMALL"


def test_router_uses_resource_broker_and_fails_closed_when_unavailable():
    registry = ReasoningProviderRegistry([provider("gpu", required_vram_mb=2048)])
    denied = ReasoningRouter(registry, resource_admission=lambda **_kwargs: {"allowed": False, "reason": "full"})
    result = denied.route(ReasoningRouteRequest(required_vram_mb=1024))
    assert result["status"] == "NO_ELIGIBLE_PROVIDER"
    assert result["rejected"][0]["code"] == "RESOURCE_ADMISSION_DENIED"

    no_broker = ReasoningRouter(registry)
    result = no_broker.route(ReasoningRouteRequest(required_vram_mb=1024))
    assert result["rejected"][0]["code"] == "RESOURCE_ADMISSION_UNAVAILABLE"


def test_registry_rejects_secret_metadata_and_round_trips_snapshot():
    registry = ReasoningProviderRegistry()
    try:
        registry.register(provider("bad", metadata={"api_token": "do-not-store"}))
    except ValueError as error:
        assert "secret" in str(error)
    else:
        raise AssertionError("secret metadata must be rejected")

    registry.register(provider("good", required_vram_mb=2048, metadata={"source": "operator"}))
    restored = ReasoningProviderRegistry()
    restored.restore_state(registry.snapshot_state())
    assert restored.get("good").metadata == {"source": "operator"}
    assert restored.get("good").required_vram_mb == 2048
    assert restored.as_payload()["count"] == 1
