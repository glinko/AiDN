from datetime import datetime
import time

from aidn_hypervisor.registry_models import RegistryDiscoveryQuery, RegistryNodeAdvertisement


class RegistryService:
    def __init__(self, *, stale_grace_seconds: int = 30) -> None:
        self.stale_grace_seconds = stale_grace_seconds
        self._nodes: dict[str, dict] = {}

    def upsert_node(self, payload: RegistryNodeAdvertisement) -> dict:
        self._nodes[payload.node_id] = payload.model_dump(mode="json")
        return self.get_node(payload.node_id)

    def list_nodes(self) -> list[dict]:
        return [self.get_node(node_id) for node_id in sorted(self._nodes)]

    def get_node(self, node_id: str) -> dict:
        record = dict(self._nodes[node_id])
        record["status"] = self._status_for(record)
        return record

    def discover(self, query: RegistryDiscoveryQuery) -> dict:
        matched_nodes: list[dict] = []
        canonical_candidates_by_node: dict[str, list[dict]] = {}
        use_legacy_filters = self._uses_legacy_filters(query)
        use_canonical_filters = self._uses_canonical_filters(query)
        for node_id in self._nodes:
            node = self.get_node(node_id)
            if node["status"] == "offline":
                continue
            if node["status"] == "stale" and not query.include_stale:
                continue
            if (
                query.can_host_custom_model is not None
                and node["can_host_custom_model"] != query.can_host_custom_model
            ):
                continue
            if query.min_rating is not None and self._node_rating_score(node) < query.min_rating:
                continue
            if (
                query.max_input_price_q_per_1kk is not None
                and node["pricing"]["input"] > query.max_input_price_q_per_1kk
            ):
                continue
            if (
                query.max_output_price_q_per_1kk is not None
                and node["pricing"]["output"] > query.max_output_price_q_per_1kk
            ):
                continue

            bundles = [
                bundle for bundle in node["bundles"] if self._bundle_matches(bundle, query)
            ]
            canonical_candidates = self._flatten_canonical_candidates_for_node(node)
            if use_canonical_filters:
                canonical_candidates = [
                    candidate
                    for candidate in canonical_candidates
                    if self._canonical_candidate_matches(candidate=candidate, query=query)
                ]

            has_legacy_matches = bool(bundles)
            has_canonical_matches = bool(canonical_candidates)
            if use_legacy_filters and use_canonical_filters:
                if not has_legacy_matches or not has_canonical_matches:
                    continue
            elif use_canonical_filters:
                if not has_canonical_matches:
                    continue
            elif not has_legacy_matches:
                continue
            node["bundles"] = bundles
            matched_nodes.append(node)
            canonical_candidates_by_node[node["node_id"]] = canonical_candidates

        matched_nodes.sort(
            key=lambda node: (
                {"ready": 0, "stale": 1, "offline": 2}[node["status"]],
                -self._node_rating_score(node),
                node["pricing"]["input"],
                node["pricing"]["output"],
                -datetime.fromisoformat(node["heartbeat_at"]).timestamp(),
            )
        )
        nodes = matched_nodes[: query.limit]
        canonical_candidates: list[dict] = []
        for node in nodes:
            canonical_candidates.extend(canonical_candidates_by_node.get(node["node_id"], []))
        canonical_candidates.sort(key=self._canonical_candidate_sort_key)
        return {
            "query": query.model_dump(mode="json"),
            "nodes": nodes,
            "candidates": self._flatten_candidates(nodes),
            "canonical_candidates": canonical_candidates,
        }

    def _flatten_candidates(self, nodes: list[dict]) -> list[dict]:
        candidates: list[dict] = []
        for node in nodes:
            for bundle in node["bundles"]:
                candidates.append(
                    {
                        "node_id": node["node_id"],
                        "operator_id": node["operator_id"],
                        "status": node["status"],
                        "base_url": node["base_url"],
                        "resources": node["resources"],
                        "can_host_custom_model": node["can_host_custom_model"],
                        "pricing": node["pricing"],
                        "rating": node["rating"],
                        "reputation": node.get("reputation"),
                        "bundle_id": bundle["bundle_id"],
                        "plugin_id": bundle["plugin_id"],
                        "provider_type": bundle["provider_type"],
                        "model_id": bundle["model_id"],
                        "workload_type": bundle["workload_type"],
                        "endpoint": bundle["endpoint"],
                        "endpoint_ready": self._bundle_endpoint_ready(bundle),
                        "supports_allocation": bundle["supports_allocation"],
                        "supports_queue": bundle["supports_queue"],
                    }
                )
        candidates.sort(key=self._candidate_sort_key)
        return candidates

    def _status_for(self, record: dict) -> str:
        heartbeat = datetime.fromisoformat(record["heartbeat_at"]).timestamp()
        ttl = int(record["heartbeat_ttl_seconds"])
        age = time.time() - heartbeat
        if age <= ttl:
            return "ready"
        if age <= ttl + self.stale_grace_seconds:
            return "stale"
        return "offline"

    def _bundle_matches(self, bundle: dict, query: RegistryDiscoveryQuery) -> bool:
        if query.workload_type is not None and bundle["workload_type"] != query.workload_type:
            return False
        if query.provider_type is not None and bundle["provider_type"] != query.provider_type:
            return False
        if query.bundle_id is not None and bundle["bundle_id"] != query.bundle_id:
            return False
        if query.model_id is not None and query.model_id.lower() not in bundle["model_id"].lower():
            return False
        if query.require_allocation_support and not bundle["supports_allocation"]:
            return False
        if query.require_queue_support and not bundle["supports_queue"]:
            return False
        if query.ready_endpoint_only and not self._bundle_endpoint_ready(bundle):
            return False
        return True

    def _uses_canonical_filters(self, query: RegistryDiscoveryQuery) -> bool:
        return any(
            value is not None
            for value in (
                query.capability_id,
                query.runtime_id,
                query.advertisement_resource_type,
                query.visibility,
                query.owner_wallet,
            )
        )

    def _uses_legacy_filters(self, query: RegistryDiscoveryQuery) -> bool:
        return any(
            value is not None
            for value in (
                query.workload_type,
                query.provider_type,
                query.model_id,
                query.bundle_id,
            )
        ) or query.require_allocation_support or query.require_queue_support or query.ready_endpoint_only

    def _bundle_endpoint_ready(self, bundle: dict) -> bool:
        return bool(bundle.get("enabled")) and bundle.get("status") == "ready" and bool(
            bundle.get("endpoint")
        )

    def _flatten_canonical_candidates_for_node(self, node: dict) -> list[dict]:
        candidates: list[dict] = []
        runtimes_by_id = {}
        runtimes_by_capability: dict[str, list[dict]] = {}
        for runtime in node.get("canonical_capability_runtimes", []):
            runtimes_by_id[runtime["runtime_id"]] = runtime
            runtimes_by_capability.setdefault(runtime["capability_id"], []).append(runtime)
        compatibility_by_capability: dict[str, list[dict]] = {}
        compatibility_by_runtime_id: dict[str, list[dict]] = {}
        for item in node.get("canonical_compute_compatibility", []):
            compatibility_by_capability.setdefault(item["canonical_capability_id"], []).append(item)
            compatibility_by_runtime_id.setdefault(item["canonical_runtime_id"], []).append(item)
        for advertisement in node.get("canonical_advertisements", []):
            service_id = self._service_id_for_advertisement(advertisement=advertisement)
            capability_id = advertisement.get("capability_id")
            runtime_rows = (
                runtimes_by_capability.get(capability_id, [])
                if capability_id is not None
                else []
            )
            emitted = False
            for runtime in runtime_rows:
                compatibility_rows = compatibility_by_runtime_id.get(runtime["runtime_id"]) or [None]
                for compatibility in compatibility_rows:
                    candidates.append(
                        self._canonical_candidate_row(
                            node=node,
                            advertisement=advertisement,
                            service_id=service_id,
                            capability_id=capability_id,
                            runtime=runtime,
                            compatibility=compatibility,
                        )
                    )
                emitted = True

            if emitted:
                continue

            compatibility_rows = (
                compatibility_by_capability.get(capability_id, [])
                if capability_id is not None
                else []
            )
            for compatibility in compatibility_rows:
                candidates.append(
                    self._canonical_candidate_row(
                        node=node,
                        advertisement=advertisement,
                        service_id=service_id,
                        capability_id=capability_id,
                        runtime=runtimes_by_id.get(compatibility.get("canonical_runtime_id"), {}),
                        compatibility=compatibility,
                    )
                )
                emitted = True

            if not emitted:
                candidates.append(
                    self._canonical_candidate_row(
                        node=node,
                        advertisement=advertisement,
                        service_id=service_id,
                        capability_id=capability_id,
                        runtime={},
                        compatibility=None,
                    )
                )
        return candidates

    def _canonical_candidate_row(
        self,
        *,
        node: dict,
        advertisement: dict,
        service_id: str,
        capability_id: str | None,
        runtime: dict,
        compatibility: dict | None,
    ) -> dict:
        runtime_id = runtime.get("runtime_id")
        if runtime_id is None and compatibility is not None:
            runtime_id = compatibility.get("canonical_runtime_id")
        return {
            "node_id": node["node_id"],
            "operator_id": node["operator_id"],
            "base_url": node["base_url"],
            "status": node["status"],
            "service_id": service_id,
            "capability_id": capability_id,
            "runtime_id": runtime_id,
            "advertisement_id": advertisement["advertisement_id"],
            "resource_type": advertisement["resource_type"],
            "visibility": advertisement["visibility"],
            "owner_wallet": advertisement.get("owner_wallet"),
            "pricing": node["pricing"],
            "rating": node["rating"],
            "reputation": node.get("reputation"),
            "can_host_custom_model": node["can_host_custom_model"],
            "published_endpoint_count": len(node.get("published_endpoints", [])),
            "trust_summary": self._canonical_trust_summary(node),
            "legacy_bundle_id": (
                compatibility.get("legacy_bundle_id") if compatibility is not None else None
            ),
            "legacy_plugin_id": (
                compatibility.get("legacy_plugin_id") if compatibility is not None else None
            ),
            "legacy_provider_type": (
                compatibility.get("legacy_provider_type")
                if compatibility is not None
                else None
            ),
        }

    def _service_id_for_advertisement(self, *, advertisement: dict) -> str:
        resource_type = advertisement.get("resource_type")
        if resource_type == "registry_service":
            return "registry"
        if resource_type == "validation_service":
            return "validation"
        if resource_type == "consensus_service":
            return "consensus"
        return "compute"

    def _canonical_candidate_matches(
        self,
        *,
        candidate: dict,
        query: RegistryDiscoveryQuery,
    ) -> bool:
        if query.capability_id is not None and candidate.get("capability_id") != query.capability_id:
            return False
        if (
            query.advertisement_resource_type is not None
            and candidate.get("resource_type") != query.advertisement_resource_type
        ):
            return False
        if query.visibility is not None and candidate.get("visibility") != query.visibility:
            return False
        if (
            query.owner_wallet is not None
            and candidate.get("owner_wallet") != query.owner_wallet
        ):
            return False
        if query.runtime_id is not None and candidate.get("runtime_id") != query.runtime_id:
            return False
        return True

    def _canonical_trust_summary(self, node: dict) -> dict:
        published_endpoints = node.get("published_endpoints", [])
        validation_by_status: dict[str, int] = {}
        publication_by_status: dict[str, int] = {}
        certified_count = 0
        certified_with_issues_count = 0
        validated_count = 0
        pending_count = 0
        attention_count = 0
        in_sync_count = 0
        drift_count = 0

        for item in published_endpoints:
            validation_summary = item.get("published_validation_summary", {}) or {}
            certification_status = validation_summary.get("certification_status")
            validation_status = validation_summary.get("validation_status", "unknown")
            publication_status = item.get("publication_sync_status") or "unknown"
            validation_by_status[validation_status] = (
                validation_by_status.get(validation_status, 0) + 1
            )
            publication_by_status[publication_status] = (
                publication_by_status.get(publication_status, 0) + 1
            )

            if certification_status == "certified":
                certified_count += 1
            elif certification_status == "certified_with_issues":
                certified_with_issues_count += 1
            elif certification_status in {
                "pending_initial",
                "maintenance_in_progress",
                "maintenance_due",
                "uncertified",
            }:
                pending_count += 1
            elif certification_status not in {None, "superseded"}:
                attention_count += 1
            elif validation_status == "validated":
                validated_count += 1
            elif validation_status in {"pending_initial", "pending_maintenance", "unvalidated"}:
                pending_count += 1
            elif validation_status not in {"unknown"}:
                attention_count += 1

            if publication_status == "in_sync":
                in_sync_count += 1
            elif publication_status in {
                "local_changes_not_published",
                "published_configuration_not_served",
            }:
                drift_count += 1

        return {
            "total_endpoints": len(published_endpoints),
            "certified_count": certified_count,
            "certified_with_issues_count": certified_with_issues_count,
            "validated_count": certified_count + certified_with_issues_count + validated_count,
            "pending_count": pending_count,
            "attention_count": attention_count,
            "in_sync_count": in_sync_count,
            "drift_count": drift_count,
            "validation_by_status": validation_by_status,
            "publication_by_status": publication_by_status,
        }

    def _candidate_sort_key(self, candidate: dict) -> tuple:
        return (
            {"ready": 0, "stale": 1, "offline": 2}[candidate["status"]],
            0 if candidate["endpoint_ready"] else 1,
            0 if candidate["supports_allocation"] else 1,
            0 if candidate["supports_queue"] else 1,
            -self._node_rating_score(candidate),
            candidate["pricing"]["input"],
            candidate["pricing"]["output"],
            candidate["node_id"],
            candidate["bundle_id"],
        )

    def _canonical_candidate_sort_key(self, candidate: dict) -> tuple:
        return (
            {"ready": 0, "stale": 1, "offline": 2}[candidate["status"]],
            -self._node_rating_score(candidate),
            candidate["pricing"]["input"],
            candidate["pricing"]["output"],
            candidate["node_id"],
            candidate["advertisement_id"],
        )

    def _node_rating_score(self, item: dict) -> float:
        reputation = item.get("reputation") or {}
        if reputation.get("score") is not None:
            return float(reputation.get("score") or 0)
        rating = item.get("rating") or {}
        return float(rating.get("score") or 0)
