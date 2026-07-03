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
        enriched["trust_summary"] = _aggregate_market_trust(
            node.get("published_endpoints", [])
        )
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
        "trust_summary": _aggregate_market_trust(
            advertisement.get("published_endpoints", [])
        ),
    }


def _aggregate_market_trust(published_endpoints: list[dict]) -> dict:
    validation_by_status: dict[str, int] = {}
    publication_by_status: dict[str, int] = {}
    validated_count = 0
    pending_count = 0
    attention_count = 0
    in_sync_count = 0
    drift_count = 0

    for item in published_endpoints:
        validation_status = (
            item.get("published_validation_summary", {}) or {}
        ).get("validation_status", "unknown")
        publication_status = item.get("publication_sync_status") or "unknown"
        validation_by_status[validation_status] = (
            validation_by_status.get(validation_status, 0) + 1
        )
        publication_by_status[publication_status] = (
            publication_by_status.get(publication_status, 0) + 1
        )

        if validation_status == "validated":
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
        "validated_count": validated_count,
        "pending_count": pending_count,
        "attention_count": attention_count,
        "in_sync_count": in_sync_count,
        "drift_count": drift_count,
        "validation_by_status": validation_by_status,
        "publication_by_status": publication_by_status,
    }
