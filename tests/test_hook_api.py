from fastapi.testclient import TestClient

from aidn_hypervisor.main import build_app
from aidn_hypervisor.service import HypervisorService
from tests.test_api import _service


def test_hook_api_lifecycle_and_delivery() -> None:
    service: HypervisorService = _service(with_runtime=False)
    client = TestClient(build_app(service=service))

    created = client.post(
        "/operators/hooks",
        json={
            "hook_id": "provider-watch",
            "owner_operator_id": "operator-local",
            "target_agent_id": "agent:local",
            "event_filter": {"event_types": ["aidn.provider.failed"]},
        },
    )
    assert created.status_code == 201
    assert created.json()["delivery_mode"] == "DURABLE_INBOX"

    foreign = client.post(
        "/operators/hooks",
        json={
            "hook_id": "foreign-watch",
            "owner_operator_id": "operator-other",
            "target_agent_id": "agent:local",
            "event_filter": {"event_types": ["aidn.provider.failed"]},
        },
    )
    assert foreign.status_code == 403

    service.record_event(
        event_type="aidn.provider.failed",
        message="provider failed",
    )
    event = service.canonical_event_journal()[-1]
    deliveries = client.get("/operators/hooks/deliveries").json()
    assert deliveries[0]["event_id"] == event.event_id
    assert deliveries[0]["status"] == "DELIVERED"

    inbox = client.get("/operators/events/inbox/agent:local").json()
    assert inbox["items"][0]["event_id"] == event.event_id
    metrics = client.get("/operators/hooks/metrics").json()
    assert metrics["events_delivered"] == 1

    deleted = client.delete("/operators/hooks/provider-watch")
    assert deleted.status_code == 200
    assert client.get("/operators/hooks").json() == []
