from pathlib import Path

from aidn_hypervisor.registry_models import RegistryDiscoveryQuery


def load_dashboard_html() -> str:
    path = Path(__file__).with_name("static") / "operator_dashboard.html"
    return path.read_text(encoding="utf-8")


def build_market_payload(*, service, registry_service) -> dict:
    if registry_service is None:
        advertisement = service.node_advertisement()
        return {
            "nodes": [advertisement],
            "candidates": [
                _local_candidate_from_advertisement(advertisement, bundle)
                for bundle in advertisement["bundles"]
            ],
        }

    discovery = registry_service.discover(RegistryDiscoveryQuery())
    nodes_by_id = {node["node_id"]: node for node in discovery["nodes"]}
    candidates = []
    for candidate in discovery["candidates"]:
        enriched = dict(candidate)
        node = nodes_by_id.get(enriched["node_id"], {})
        enriched["origin"] = (
            "own" if enriched["node_id"] == service.node_id else "external"
        )
        enriched["published_endpoint_count"] = len(node.get("published_endpoints", []))
        candidates.append(enriched)
    return {
        "query": discovery["query"],
        "nodes": discovery["nodes"],
        "candidates": candidates,
    }


def _local_candidate_from_advertisement(advertisement: dict, bundle: dict) -> dict:
    return {
        "origin": "own",
        "node_id": advertisement["node_id"],
        "operator_id": advertisement["operator_id"],
        "status": advertisement["status"],
        "base_url": advertisement["base_url"],
        "resources": advertisement["resources"]["free"],
        "can_host_custom_model": advertisement["can_host_custom_model"],
        "pricing": advertisement["pricing"],
        "rating": advertisement["rating"],
        "bundle_id": bundle["bundle_id"],
        "plugin_id": bundle["plugin_id"],
        "provider_type": bundle["provider_type"],
        "model_id": bundle["model_id"],
        "workload_type": bundle["workload_type"],
        "endpoint": bundle["endpoint"],
        "supports_allocation": bundle["supports_allocation"],
        "supports_queue": bundle["supports_queue"],
        "endpoint_ready": bool(bundle["endpoint"]) and bundle["status"] == "ready",
        "published_endpoint_count": len(advertisement.get("published_endpoints", [])),
    }
