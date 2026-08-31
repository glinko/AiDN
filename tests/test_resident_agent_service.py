from aidn_hypervisor.event_bus import InternalEventBus
from aidn_hypervisor.resident_agent_service import ResidentAgentService


def test_cpu_first_steward_uses_reference_model_without_vram() -> None:
    steward = ResidentAgentService(node_id="gpu-3090", enabled=True)
    bus = InternalEventBus(hypervisor_id="gpu-3090")
    steward.bind_event_bus(bus)

    bus.publish(
        event_type="aidn.provider.failed",
        message="provider stopped",
        details={"provider_instance_id": "provider-1"},
    )
    bus.publish(
        event_type="aidn.provider.failed",
        message="provider stopped again",
        details={"provider_instance_id": "provider-1"},
    )

    status = steward.status()
    assert status["state"] == "CONFIGURED"
    assert status["execution"]["profile"] == "CPU_RESIDENT"
    assert status["execution"]["vram_mb"] == 0
    assert status["model"]["repo"] == "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
    assert status["model"]["quantization"] == "Q4_K_M"
    assert status["model"]["license"] == "apache-2.0"
    assert status["event_ingestion"]["events_seen"] == 2
    assert status["event_ingestion"]["last_event_sequence"] == 2


def test_steward_snapshot_restores_profile_and_records_restart() -> None:
    original = ResidentAgentService(
        node_id="node-1",
        enabled=True,
        model_path="/does/not/exist/steward.gguf",
        ram_budget_mb=768,
    )
    original.heartbeat(action="observe provider failure", persist=False)
    snapshot = original.snapshot_state()

    restored = ResidentAgentService(node_id="node-1", enabled=False)
    restored.restore_state(snapshot)
    status = restored.status()

    assert status["enabled"] is True
    assert status["state"] == "DEGRADED"
    assert status["model"]["path_exists"] is False
    assert status["execution"]["ram_budget_mb"] == 768
    assert status["restart_recovery"]["restart_count"] == 1
    assert status["restart_recovery"]["last_restart_at"] is not None


def test_disabled_steward_does_not_claim_inference_health() -> None:
    steward = ResidentAgentService(node_id="node-1", enabled=False)
    status = steward.status()

    assert status["state"] == "DISABLED"
    assert status["health"] == "NOT_RUNNING"
    assert status["execution"]["inference_adapter"] == "not_started"
    assert status["execution"]["resource_lease"] == "not_requested"


def test_steward_deduplicates_replayed_event_and_keeps_causation_metadata() -> None:
    steward = ResidentAgentService(node_id="node-1", enabled=True)
    bus = InternalEventBus(hypervisor_id="node-1")
    steward.bind_event_bus(bus)

    event = bus.publish(
        event_type="aidn.provider.failed",
        message="provider stopped",
        details={"provider_instance_id": "provider-1", "credential": "never-expose"},
        correlation_id="incident-1",
        causation_id="action-1",
    )
    steward._on_event(event)

    status = steward.status()
    assert status["event_ingestion"]["events_seen"] == 1
    context = steward.context_snapshot()
    assert context["recent_events"][0]["causation_id"] == "action-1"
    assert "credential" not in context["recent_events"][0]


def test_steward_context_is_bounded_and_decision_is_non_mutating() -> None:
    steward = ResidentAgentService(
        node_id="node-1",
        enabled=True,
        context_provider=lambda: {
            "resources": {"free_vram_mb": 4096},
            "transcript": "x" * 5000,
            "nested": {"a": {"b": {"c": "d"}}},
        },
    )

    context = steward.context_snapshot()
    assert len(context["state"]["transcript"]) == 512
    assert context["omitted"]

    decision = steward.decide("Why is the provider unhealthy?", event_type="aidn.provider.failed")
    assert decision["mode"] == "LOCAL_READ_ONLY"
    assert decision["recommendation"]["tool"] == "aidn.provider.list"
    assert decision["recommendation"]["mutating"] is False
    assert decision["authority"]["can_mutate_state"] is False

    escalation = steward.decide("Install and publish a new model")
    assert escalation["mode"] == "POLICY_CONTROLLED"
    assert escalation["requires_approval"] is False

    blocked = steward.decide("Restart the provider", automation_depth=1)
    assert blocked["mode"] == "AUTOMATION_BLOCKED"


def test_steward_action_guard_links_lineage_and_enforces_cooldown() -> None:
    steward = ResidentAgentService(node_id="node-1", enabled=True)

    first = steward.guard_action(
        "runtime.restart",
        target_id="runtime-1",
        event_id="evt-1",
        event_type="aidn.provider.failed",
        correlation_id="incident-1",
        cooldown_seconds=60,
        persist=False,
    )
    assert first["allowed"] is True
    assert first["code"] == "ACTION_GUARDED"
    assert first["lineage"] == {
        "event_id": "evt-1",
        "event_type": "aidn.provider.failed",
        "correlation_id": "incident-1",
        "causation_id": "evt-1",
    }
    assert first["claim_only"] is True

    second = steward.guard_action(
        "runtime.restart",
        target_id="runtime-1",
        event_id="evt-2",
        event_type="aidn.provider.failed",
        correlation_id="incident-2",
        cooldown_seconds=60,
        persist=False,
    )
    assert second["allowed"] is False
    assert second["code"] == "ACTION_COOLDOWN_ACTIVE"
    assert second["blocked_by_action_id"] == first["action_id"]
    assert steward.status()["automation"]["active_cooldowns"] == 1


def test_steward_action_guard_blocks_depth_and_restores_cooldown() -> None:
    original = ResidentAgentService(node_id="node-1", enabled=True)
    blocked = original.guard_action(
        "runtime.restart",
        target_id="runtime-1",
        event_id="evt-1",
        automation_depth=1,
        persist=False,
    )
    assert blocked["allowed"] is False
    assert blocked["code"] == "AUTOMATION_DEPTH_EXCEEDED"
    assert original.status()["automation"]["active_cooldowns"] == 0

    allowed = original.guard_action(
        "runtime.restart",
        target_id="runtime-1",
        event_id="evt-2",
        cooldown_seconds=120,
        persist=False,
    )
    restored = ResidentAgentService(node_id="node-1", enabled=True)
    restored.restore_state(original.snapshot_state())
    replay = restored.guard_action(
        "runtime.restart",
        target_id="runtime-1",
        event_id="evt-3",
        cooldown_seconds=120,
        persist=False,
    )
    assert allowed["allowed"] is True
    assert replay["allowed"] is False
    assert replay["code"] == "ACTION_COOLDOWN_ACTIVE"


def test_unrestricted_test_mode_makes_all_available_actions_automatic() -> None:
    steward = ResidentAgentService(node_id="node-1", enabled=True)

    policy = steward.configure_action_policy(test_unrestricted=True, persist=False)
    guarded = steward.guard_action(
        "runtime.restart",
        target_id="runtime-1",
        automation_depth=99,
        cooldown_seconds=3600,
        persist=False,
    )
    repeated = steward.guard_action(
        "runtime.restart",
        target_id="runtime-1",
        automation_depth=99,
        cooldown_seconds=3600,
        persist=False,
    )

    assert policy["test_unrestricted"] is True
    assert {item["policy"] for item in policy["catalog"]} == {"AUTO"}
    assert guarded["allowed"] is True
    assert guarded["code"] == "TEST_UNRESTRICTED"
    assert repeated["allowed"] is True
    assert steward.decide("Restart the provider", automation_depth=99)["mode"] == "TEST_UNRESTRICTED"


def test_steward_decision_derives_event_lineage() -> None:
    steward = ResidentAgentService(node_id="node-1", enabled=True)
    bus = InternalEventBus(hypervisor_id="node-1")
    steward.bind_event_bus(bus)
    event = bus.publish(
        event_type="aidn.provider.failed",
        message="provider stopped",
        correlation_id="incident-7",
        causation_id="action-7",
    )

    decision = steward.decide(
        "Why is the provider unhealthy?",
        event_id=event.event_id,
        event_type=event.event_type,
    )
    assert decision["lineage"]["correlation_id"] == "incident-7"
    assert decision["lineage"]["causation_id"] == "action-7"
