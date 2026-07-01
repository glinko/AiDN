from aidn_hypervisor.remote_endpoints.service import RemoteEndpointService
from aidn_hypervisor.remote_endpoints.store import RemoteEndpointStore


def test_attach_remote_endpoint_creates_catalog_entry() -> None:
    service = RemoteEndpointService(RemoteEndpointStore())

    attached = service.attach_remote_endpoint(
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
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-06-30T00:00:00+00:00"},
        alias="Primary Remote",
    )

    assert attached.remote_endpoint_id
    assert attached.source_node_id == "node-remote"
    assert attached.source_endpoint_id == "ep-remote"
    assert attached.alias == "Primary Remote"
    assert service.list_remote_endpoints() == [attached]


def test_attach_remote_endpoint_refreshes_existing_entry_without_duplication() -> None:
    service = RemoteEndpointService(RemoteEndpointStore())
    first = service.attach_remote_endpoint(
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
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-06-30T00:00:00+00:00"},
    )

    refreshed = service.attach_remote_endpoint(
        source_node_id="node-remote",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote-2",
        source_configuration_hash="cfg-remote-2",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote-v2.example",
        operator_id="operator-remote",
        pricing={"unit": "q_per_1kk_tokens", "input": 7, "output": 11},
        rating={"score": 0.97, "tier": "A", "updated_at": "2026-06-30T01:00:00+00:00"},
        alias="Refreshed Remote",
    )

    listed = service.list_remote_endpoints()

    assert refreshed.remote_endpoint_id == first.remote_endpoint_id
    assert len(listed) == 1
    assert listed[0].source_publication_id == "pub-remote-2"
    assert listed[0].source_configuration_hash == "cfg-remote-2"
    assert listed[0].source_base_url == "https://remote-v2.example"
    assert listed[0].alias == "Refreshed Remote"
