from fastapi import APIRouter, HTTPException

from aidn_hypervisor.registry_models import (
    RegistryDiscoveryQuery,
    RegistryNodeAdvertisement,
    RegistryWalletIdentityPeerConfig,
    RegistryWalletIdentityPeerDiscoveryRequest,
    RegistryWalletIdentityPeerRepairRequest,
    RegistryWalletIdentityResolutionRequest,
    RegistryWalletIdentityPeerSyncRequest,
    RegistryWalletIdentitySyncImportRequest,
)
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

    @router.get("/registry/wallet-identities/sync-state")
    async def wallet_identity_sync_state(limit: int = 500) -> dict:
        return service.export_wallet_identity_sync_state(limit=limit)

    @router.get("/registry/wallet-identities/peers")
    async def list_wallet_identity_peers() -> dict:
        return {"peers": service.list_wallet_identity_peers()}

    @router.put("/registry/wallet-identities/peers")
    async def upsert_wallet_identity_peer(
        request: RegistryWalletIdentityPeerConfig,
    ) -> dict:
        try:
            return service.upsert_wallet_identity_peer(
                peer_base_url=request.peer_base_url,
                enabled=request.enabled,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/registry/wallet-identities/discover-peers")
    async def discover_wallet_identity_peers(
        request: RegistryWalletIdentityPeerDiscoveryRequest,
    ) -> dict:
        if request.repair_after_discovery:
            return service.discover_and_repair_wallet_identity_peers(
                self_node_id=request.self_node_id,
                include_stale=request.include_stale,
                limit=request.limit,
            )
        return service.discover_wallet_identity_peers_from_nodes(
            self_node_id=request.self_node_id,
            include_stale=request.include_stale,
            auto_register=request.auto_register,
        )

    @router.get("/registry/wallet-identities/reconciliation")
    async def wallet_identity_reconciliation(limit: int = 500) -> dict:
        return service.wallet_identity_reconciliation_report(limit=limit)

    @router.post("/registry/wallet-identities/resolve-conflict")
    async def resolve_wallet_identity_conflict(
        request: RegistryWalletIdentityResolutionRequest,
    ) -> dict:
        try:
            return service.resolve_wallet_identity_conflict(
                wallet_id=request.wallet_id,
                chosen_object_id=request.chosen_object_id,
                chosen_payload_hash=request.chosen_payload_hash,
                operator_note=request.operator_note,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown wallet identity: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/registry/wallet-identities/import")
    async def import_wallet_identity_sync_state(
        request: RegistryWalletIdentitySyncImportRequest,
    ) -> dict:
        return service.import_wallet_identity_sync_state(
            objects=request.objects,
            conflicts=request.conflicts,
        )

    @router.post("/registry/wallet-identities/sync-from-peer")
    async def sync_wallet_identity_from_peer(
        request: RegistryWalletIdentityPeerSyncRequest,
    ) -> dict:
        try:
            return service.sync_wallet_identity_from_peer(
                peer_base_url=request.peer_base_url,
                limit=request.limit,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/registry/wallet-identities/repair")
    async def repair_wallet_identity_peers(
        request: RegistryWalletIdentityPeerRepairRequest,
    ) -> dict:
        return service.repair_wallet_identity_peers(limit=request.limit)

    return router
