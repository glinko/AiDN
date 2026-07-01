from aidn_hypervisor.endpoints.models import CreateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.remote_endpoints.models import RemoteEndpointReference


def _remote_reference() -> RemoteEndpointReference:
    return RemoteEndpointReference(
        remote_endpoint_id="remote-1",
        source_node_id="node-remote",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-remote",
        alias="Primary Remote",
        attached_at="2026-06-30T00:00:00+00:00",
        last_seen_at="2026-06-30T00:00:00+00:00",
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-06-30T00:00:00+00:00"},
    )


def test_attach_proxy_target_rotates_endpoint_configuration() -> None:
    service = EndpointService(EndpointStore())
    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )

    updated = service.attach_proxy_target(
        created.endpoint.endpoint_id,
        _remote_reference(),
    )

    assert updated.endpoint.configuration_hash != created.endpoint.configuration_hash
    assert updated.endpoint.execution_strategy == "proxy"
    assert updated.endpoint.proxy_target is not None
    assert updated.endpoint.proxy_target.remote_endpoint_id == "remote-1"
    assert len(service.list_configuration_snapshots(created.endpoint.endpoint_id)) == 2
