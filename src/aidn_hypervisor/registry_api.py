from fastapi import APIRouter, HTTPException

from aidn_hypervisor.registry_models import RegistryDiscoveryQuery, RegistryNodeAdvertisement
from aidn_hypervisor.registry_service import RegistryService


def build_registry_router(service: RegistryService) -> APIRouter:
    router = APIRouter()

    @router.put("/registry/nodes/{node_id}")
    async def upsert_node(node_id: str, payload: RegistryNodeAdvertisement) -> dict:
        if payload.node_id != node_id:
            raise HTTPException(status_code=409, detail="node_id in path and body must match")
        return service.upsert_node(payload)

    @router.get("/registry/nodes")
    async def list_nodes() -> list[dict]:
        return service.list_nodes()

    @router.get("/registry/nodes/{node_id}")
    async def get_node(node_id: str) -> dict:
        try:
            return service.get_node(node_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown node: {node_id}") from error

    @router.get("/registry/discovery")
    async def discover(
        workload_type: str | None = None,
        provider_type: str | None = None,
        model_id: str | None = None,
        bundle_id: str | None = None,
        require_allocation_support: bool = False,
        require_queue_support: bool = False,
        ready_endpoint_only: bool = False,
        can_host_custom_model: bool | None = None,
        max_input_price_q_per_1kk: int | None = None,
        max_output_price_q_per_1kk: int | None = None,
        min_rating: float | None = None,
        include_stale: bool = False,
        limit: int = 20,
    ) -> dict:
        query = RegistryDiscoveryQuery(
            workload_type=workload_type,
            provider_type=provider_type,
            model_id=model_id,
            bundle_id=bundle_id,
            require_allocation_support=require_allocation_support,
            require_queue_support=require_queue_support,
            ready_endpoint_only=ready_endpoint_only,
            can_host_custom_model=can_host_custom_model,
            max_input_price_q_per_1kk=max_input_price_q_per_1kk,
            max_output_price_q_per_1kk=max_output_price_q_per_1kk,
            min_rating=min_rating,
            include_stale=include_stale,
            limit=limit,
        )
        return service.discover(query)

    return router
