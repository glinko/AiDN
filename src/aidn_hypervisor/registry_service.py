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
            if query.min_rating is not None and node["rating"]["score"] < query.min_rating:
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
            if not bundles:
                continue
            node["bundles"] = bundles
            matched_nodes.append(node)

        matched_nodes.sort(
            key=lambda node: (
                {"ready": 0, "stale": 1, "offline": 2}[node["status"]],
                -node["rating"]["score"],
                node["pricing"]["input"],
                node["pricing"]["output"],
                -datetime.fromisoformat(node["heartbeat_at"]).timestamp(),
            )
        )
        return {
            "query": query.model_dump(mode="json"),
            "nodes": matched_nodes[: query.limit],
            "candidates": self._flatten_candidates(matched_nodes[: query.limit]),
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

    def _bundle_endpoint_ready(self, bundle: dict) -> bool:
        return bool(bundle.get("enabled")) and bundle.get("status") == "ready" and bool(
            bundle.get("endpoint")
        )

    def _candidate_sort_key(self, candidate: dict) -> tuple:
        return (
            {"ready": 0, "stale": 1, "offline": 2}[candidate["status"]],
            0 if candidate["endpoint_ready"] else 1,
            0 if candidate["supports_allocation"] else 1,
            0 if candidate["supports_queue"] else 1,
            -candidate["rating"]["score"],
            candidate["pricing"]["input"],
            candidate["pricing"]["output"],
            candidate["node_id"],
            candidate["bundle_id"],
        )
