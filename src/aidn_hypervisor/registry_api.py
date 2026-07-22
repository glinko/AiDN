from fastapi import APIRouter, HTTPException

from aidn_hypervisor.registry_models import RegistryDiscoveryQuery, RegistryNodeAdvertisement
from aidn_hypervisor.registry_service import RegistryService


def build_registry_router(service: RegistryService) -> APIRouter:
    router = APIRouter()

    @router.put("/registry/nodes/{node_id}")
    async def upsert_node(node_id: str, payload: RegistryNodeAdvertisement) -> dict:
        if payload.node_id != node_id:
            raise HTTPException(status_code=409, detail="node_id in path and body must match")
        try:
            return service.upsert_node(payload)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

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
        capability_id: str | None = None,
        runtime_id: str | None = None,
        advertisement_resource_type: str | None = None,
        visibility: str | None = None,
        owner_wallet: str | None = None,
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
            capability_id=capability_id,
            runtime_id=runtime_id,
            advertisement_resource_type=advertisement_resource_type,
            visibility=visibility,
            owner_wallet=owner_wallet,
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

    @router.get("/registry/conflicts")
    async def list_conflicts(
        conflict_class: str | None = None,
        object_type: str | None = None,
        logical_key: str | None = None,
        limit: int = 100,
    ) -> dict:
        return {
            "conflicts": service.list_conflicts(
                conflict_class=conflict_class,
                object_type=object_type,
                logical_key=logical_key,
                limit=limit,
            )
        }

    return router
