from __future__ import annotations

from datetime import UTC, datetime

from aidn_hypervisor.canonical_projection import (
    project_canonical_advertisements,
    project_capability_definitions,
    project_capability_runtimes,
    project_compute_compatibility,
    project_endpoint_feature_profiles,
    project_endpoint_implementation_profiles,
    project_endpoint_limit_profiles,
    project_protocol_services,
    project_registry_objects,
    project_wallet_identities,
)
from aidn_hypervisor.registry_models import (
    RegistryBundleAdvertisement,
    RegistryNodeAdvertisement,
    RegistryPublishedEndpointSummary,
    RegistryReputation,
)
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.reputation import build_reputation_profile


def _empty_resource_summary() -> dict[str, dict[str, float | int]]:
    zeroes = {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0}
    return {
        "total": dict(zeroes),
        "reserved": dict(zeroes),
        "free": dict(zeroes),
    }


class NetworkProjectionService:
    """Read-only network and registry-facing projections for a Hypervisor node."""

    def __init__(self, host) -> None:
        self._host = host

    def node_advertisement(self, *, heartbeat_at: str | None = None) -> dict:
        timestamp = heartbeat_at or datetime.now(UTC).isoformat()
        resources = (
            self._host.resources.summary()
            if self._host.resources is not None
            else _empty_resource_summary()
        )
        canonical_overlay = self.canonical_overlay_inventory()
        current_publication_records = self._current_publication_records()
        published_endpoints = [
            RegistryPublishedEndpointSummary(
                endpoint_id=record.endpoint_id,
                owner_wallet=record.owner_wallet,
                node_id=record.node_id,
                current_publication_id=record.publication_id,
                current_configuration_hash=record.configuration_hash,
                published_at=record.published_at,
                status=record.status,
                visibility=record.publication.get("visibility", "private"),
                model_class=record.model_class,
                signed_publication=record.model_dump(mode="json"),
                publication_sync_status=self.publication_sync_status(
                    local_configuration_hash=record.configuration_hash,
                    published_configuration_hash=record.configuration_hash,
                ),
                published_validation_summary=self.validation_summary_for(
                    endpoint_id=record.endpoint_id,
                    configuration_hash=record.configuration_hash,
                ),
                live_validation_summary=self.validation_summary_for(
                    endpoint_id=record.endpoint_id,
                    configuration_hash=record.configuration_hash,
                ),
                published_custody_summary=self.custody_summary_for(
                    endpoint_id=record.endpoint_id,
                    configuration_hash=record.configuration_hash,
                ),
                live_custody_summary=self.custody_summary_for(
                    endpoint_id=record.endpoint_id,
                    configuration_hash=record.configuration_hash,
                ),
            )
            for record in current_publication_records
        ]
        trust_summary = RegistryService()._canonical_trust_summary(
            {
                "published_endpoints": [
                    item.model_dump(mode="json") for item in published_endpoints
                ]
            }
        )
        node_status = self.node_advertisement_status(
            heartbeat_at=timestamp,
            heartbeat_ttl_seconds=self._host.heartbeat_ttl_seconds,
        )
        reputation = RegistryReputation(
            **build_reputation_profile(
                node_status=node_status,
                heartbeat_fresh=node_status == "ready",
                trust_summary=trust_summary,
                operational_stats=self.operational_reputation_stats(),
                baseline_rating=self._host.rating,
                updated_at=timestamp,
            )
        )
        advertisement = RegistryNodeAdvertisement(
            node_id=self._host.node_id,
            operator_id=self._host.operator_id,
            owner_wallet_id=(
                self._host._owner_wallet["wallet_id"]
                if self._host._owner_wallet is not None
                else None
            ),
            base_url=self._host.base_url,
            heartbeat_at=timestamp,
            heartbeat_ttl_seconds=self._host.heartbeat_ttl_seconds,
            status=node_status,
            resources=resources,
            providers=sorted({bundle.provider_type for bundle in self._host.bundles}),
            can_host_custom_model=self._host.can_host_custom_model,
            pricing=self._host._pricing,
            rating=self._host._rating,
            reputation=reputation,
            bundles=[
                RegistryBundleAdvertisement(
                    bundle_id=bundle.bundle_id,
                    plugin_id=bundle.plugin_id,
                    workload_type=bundle.workload_type,
                    provider_type=bundle.provider_type,
                    model_id=bundle.model_id,
                    endpoint=bundle.endpoint,
                    enabled=bundle.enabled,
                    status=self._host._bundle_registry_status(bundle),
                    launch_mode=bundle.launch_mode,
                    device_affinity=bundle.device_affinity,
                    max_parallel_requests=bundle.max_parallel_requests,
                    supports_allocation=True,
                    supports_queue=True,
                )
                for bundle in self._host.bundles
            ],
            published_endpoints=published_endpoints,
            canonical_services=canonical_overlay.get("services", []),
            canonical_capabilities=canonical_overlay.get("capabilities", []),
            canonical_capability_runtimes=canonical_overlay.get("runtimes", []),
            canonical_compute_compatibility=canonical_overlay.get(
                "compatibility", []
            ),
            canonical_feature_profiles=canonical_overlay.get("feature_profiles", []),
            canonical_limit_profiles=canonical_overlay.get("limit_profiles", []),
            canonical_implementation_profiles=canonical_overlay.get(
                "implementation_profiles", []
            ),
            canonical_registry_objects=project_registry_objects(
                self._host, current_publication_records
            ),
            canonical_advertisements=project_canonical_advertisements(
                current_publication_records
            ),
        )
        return advertisement.model_dump(mode="json")

    def node_advertisement_status(
        self,
        *,
        heartbeat_at: str,
        heartbeat_ttl_seconds: int,
    ) -> str:
        heartbeat = datetime.fromisoformat(heartbeat_at).timestamp()
        age = self._host._current_time_seconds() - heartbeat
        if age <= heartbeat_ttl_seconds:
            return "ready"
        if age <= heartbeat_ttl_seconds + RegistryService().stale_grace_seconds:
            return "stale"
        return "offline"

    def publication_sync_status(
        self,
        *,
        local_configuration_hash: str | None,
        published_configuration_hash: str | None,
    ) -> str:
        if published_configuration_hash is None:
            return "never_published"
        if local_configuration_hash == published_configuration_hash:
            return "in_sync"
        return "local_changes_not_published"

    def validation_summary_for(
        self,
        *,
        endpoint_id: str,
        configuration_hash: str | None,
    ) -> dict | None:
        validation_service = getattr(self._host, "validation_service", None)
        if validation_service is None:
            return None
        if configuration_hash is None:
            return validation_service.validation_summary(endpoint_id)
        summary = validation_service.validation_summary(
            endpoint_id,
            configuration_hash=configuration_hash,
        )
        if (
            summary.get("validation_status") == "unvalidated"
            and summary.get("certification_status") == "uncertified"
        ):
            fallback = validation_service.validation_summary(endpoint_id)
            if fallback.get("validation_status") != "unvalidated" or fallback.get(
                "certification_status"
            ) != "uncertified":
                return fallback
        return summary

    def custody_summary_for(
        self,
        *,
        endpoint_id: str,
        configuration_hash: str | None,
    ) -> dict | None:
        validation_service = getattr(self._host, "validation_service", None)
        if validation_service is None or configuration_hash is None:
            return None
        return validation_service.custody_summary(
            endpoint_id,
            configuration_hash=configuration_hash,
        )

    def operational_reputation_stats(self) -> dict[str, int]:
        successful_tasks = 0
        failed_tasks = 0
        for task in self._host.queue.snapshot():
            if task.status == "completed":
                successful_tasks += 1
                continue
            if task.status == "failed":
                failed_tasks += 1
        total_tasks = successful_tasks + failed_tasks
        return {
            "total_tasks": total_tasks,
            "successful_tasks": successful_tasks,
            "failed_tasks": failed_tasks,
        }

    def capability_catalog(
        self,
        *,
        owner_id: str,
        workload_type: str | None = None,
        bundle_id: str | None = None,
        include_disabled: bool = False,
    ) -> dict:
        self._host._cleanup_expired_allocations()
        self._host._reconcile_pending_allocations()
        bundles = self._host._filtered_catalog_bundles(
            workload_type=workload_type,
            bundle_id=bundle_id,
            include_disabled=include_disabled,
        )
        return {
            "node": {
                "node_id": self._host.node_id,
                "operator_id": self._host.operator_id,
                "can_host_custom_model": self._host.can_host_custom_model,
                "pricing": self._host.pricing,
            },
            "resources": (
                self._host.resources.summary()
                if self._host.resources is not None
                else _empty_resource_summary()
            ),
            "bundles": [
                self._host._catalog_entry(bundle, owner_id=owner_id) for bundle in bundles
            ],
        }

    def canonical_overlay_inventory(self) -> dict:
        current_publication_records = self._current_publication_records()
        capabilities = project_capability_definitions(self._host)
        runtimes = project_capability_runtimes(self._host)
        compatibility = project_compute_compatibility(self._host)
        return {
            "services": [
                record.model_dump(mode="json")
                for record in project_protocol_services(self._host)
            ],
            "capabilities": [record.model_dump(mode="json") for record in capabilities],
            "runtimes": [record.model_dump(mode="json") for record in runtimes],
            "compatibility": [
                record.model_dump(mode="json") for record in compatibility
            ],
            "feature_profiles": [
                record.model_dump(mode="json")
                for record in project_endpoint_feature_profiles(current_publication_records)
            ],
            "limit_profiles": [
                record.model_dump(mode="json")
                for record in project_endpoint_limit_profiles(current_publication_records)
            ],
            "implementation_profiles": [
                record.model_dump(mode="json")
                for record in project_endpoint_implementation_profiles(
                    current_publication_records
                )
            ],
            "wallet_identities": [
                record.model_dump(mode="json")
                for record in project_wallet_identities(self._host)
            ],
            "registry_objects": [
                record.model_dump(mode="json")
                for record in project_registry_objects(
                    self._host, current_publication_records
                )
            ],
        }

    def _current_publication_records(self) -> list:
        publication_service = getattr(self._host, "endpoint_publication_service", None)
        if publication_service is None:
            return []
        return [
            record
            for record in publication_service.list_publications()
            if record.status == "published"
        ]
