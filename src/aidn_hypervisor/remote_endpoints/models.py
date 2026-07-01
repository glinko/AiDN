from typing import Literal

from pydantic import BaseModel, Field


RemoteEndpointRoutingMode = Literal["preferred", "standby"]


class RemoteEndpointReference(BaseModel):
    remote_endpoint_id: str
    source_node_id: str
    source_endpoint_id: str
    source_owner_wallet: str
    source_publication_id: str
    source_configuration_hash: str
    source_visibility: str
    source_model_class: str
    source_status: str
    source_base_url: str
    operator_id: str
    alias: str | None = None
    routing_mode: RemoteEndpointRoutingMode = "preferred"
    attached_at: str
    last_seen_at: str
    pricing: dict[str, str | int | float | None] = Field(default_factory=dict)
    rating: dict[str, str | int | float | None] = Field(default_factory=dict)
