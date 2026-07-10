from pathlib import Path

from aidn_hypervisor.registry_models import RegistryDiscoveryQuery


def load_dashboard_html() -> str:
    path = Path(__file__).with_name("static") / "operator_dashboard.html"
    return path.read_text(encoding="utf-8")


def build_market_payload(*, service, registry_service) -> dict:
    if registry_service is None:
        advertisement = service.node_advertisement()
        canonical_candidates = _canonical_candidates_from_node(advertisement)
        payload = {
            "nodes": [advertisement],
            "candidates": [
                _local_candidate_from_advertisement(advertisement, bundle)
                for bundle in advertisement["bundles"]
            ],
            "canonical_candidates": [
                {**candidate, "origin": "own"} for candidate in canonical_candidates
            ],
            "canonical_summary": _canonical_market_summary(
                nodes=[advertisement],
                canonical_candidates=canonical_candidates,
            ),
        }
        payload["recommended_action"] = _market_recommended_action(payload)
        return payload

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
    canonical_candidates = []
    canonical_market_nodes: dict[str, dict] = {}
    for node in registry_service.list_nodes():
        if node["status"] != "ready":
            continue
        node_candidates = _canonical_candidates_from_node(node)
        if not node_candidates:
            continue
        canonical_market_nodes[node["node_id"]] = node
        for candidate in node_candidates:
            canonical_candidates.append(
                {
                    **candidate,
                    "origin": "own" if candidate["node_id"] == service.node_id else "external",
                }
            )
    payload = {
        "query": discovery["query"],
        "nodes": discovery["nodes"],
        "candidates": candidates,
        "canonical_candidates": sorted(
            canonical_candidates,
            key=_canonical_market_candidate_sort_key,
        ),
        "canonical_summary": _canonical_market_summary(
            nodes=list(canonical_market_nodes.values()),
            canonical_candidates=canonical_candidates,
        ),
    }
    payload["recommended_action"] = _market_recommended_action(payload)
    return payload


def _market_recommended_action(payload: dict) -> dict:
    nodes = payload.get("nodes", [])
    candidates = payload.get("candidates", [])
    canonical_candidates = payload.get("canonical_candidates", [])
    own_published = sum(
        len(node.get("published_endpoints", []))
        for node in nodes
        if node.get("origin") == "own" or len(nodes) == 1
    )
    has_external_supply = any(
        candidate.get("origin") == "external"
        and (
            candidate.get("published_endpoint_count", 0)
            or candidate.get("resource_type") == "endpoint"
        )
        for candidate in [*candidates, *canonical_candidates]
    )
    if own_published <= 0:
        return {
            "action": "publish_local_endpoint",
            "label": "Open Endpoints",
            "workspace": "endpoints",
            "detail": "Publish a local endpoint before routing marketplace demand through remote supply.",
        }
    if has_external_supply:
        return {
            "action": "configure_remote_route",
            "label": "Open Remote Endpoints",
            "workspace": "remote",
            "detail": "Attach a remote endpoint and stage a proxy route from the endpoint workspace.",
        }
    return {
        "action": "review_market_supply",
        "label": "Review Market Supply",
        "workspace": "market",
        "detail": "Compare local and remote supply before changing endpoint routing.",
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


def _canonical_candidates_from_node(advertisement: dict) -> list[dict]:
    candidates: list[dict] = []
    runtimes_by_id: dict[str, dict] = {}
    runtimes_by_capability: dict[str, list[dict]] = {}
    for runtime in advertisement.get("canonical_capability_runtimes", []):
        runtimes_by_id[runtime["runtime_id"]] = runtime
        runtimes_by_capability.setdefault(runtime["capability_id"], []).append(runtime)
    compatibility_by_capability: dict[str, list[dict]] = {}
    compatibility_by_runtime_id: dict[str, list[dict]] = {}
    for item in advertisement.get("canonical_compute_compatibility", []):
        compatibility_by_capability.setdefault(item["canonical_capability_id"], []).append(item)
        compatibility_by_runtime_id.setdefault(item["canonical_runtime_id"], []).append(item)

    for item in advertisement.get("canonical_advertisements", []):
        service_id = _service_id_for_resource_type(item.get("resource_type"))
        capability_id = item.get("capability_id")
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
                    _canonical_candidate_row(
                        advertisement=advertisement,
                        candidate_advertisement=item,
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
                _canonical_candidate_row(
                    advertisement=advertisement,
                    candidate_advertisement=item,
                    service_id=service_id,
                    capability_id=capability_id,
                    runtime=runtimes_by_id.get(compatibility.get("canonical_runtime_id"), {}),
                    compatibility=compatibility,
                )
            )
            emitted = True

        if not emitted:
            candidates.append(
                _canonical_candidate_row(
                    advertisement=advertisement,
                    candidate_advertisement=item,
                    service_id=service_id,
                    capability_id=capability_id,
                    runtime={},
                    compatibility=None,
                )
            )
    return candidates


def _canonical_candidate_row(
    *,
    advertisement: dict,
    candidate_advertisement: dict,
    service_id: str,
    capability_id: str | None,
    runtime: dict,
    compatibility: dict | None,
) -> dict:
    runtime_id = runtime.get("runtime_id")
    if runtime_id is None and compatibility is not None:
        runtime_id = compatibility.get("canonical_runtime_id")
    return {
        "node_id": advertisement["node_id"],
        "operator_id": advertisement["operator_id"],
        "base_url": advertisement["base_url"],
        "status": advertisement["status"],
        "service_id": service_id,
        "capability_id": capability_id,
        "runtime_id": runtime_id,
        "advertisement_id": candidate_advertisement["advertisement_id"],
        "resource_type": candidate_advertisement["resource_type"],
        "visibility": candidate_advertisement["visibility"],
        "owner_wallet": candidate_advertisement.get("owner_wallet"),
        "pricing": advertisement["pricing"],
        "rating": advertisement["rating"],
        "can_host_custom_model": advertisement["can_host_custom_model"],
        "published_endpoint_count": len(advertisement.get("published_endpoints", [])),
        "trust_summary": _aggregate_market_trust(
            advertisement.get("published_endpoints", [])
        ),
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


def _service_id_for_resource_type(resource_type: str | None) -> str:
    if resource_type == "registry_service":
        return "registry"
    if resource_type == "validation_service":
        return "validation"
    if resource_type == "consensus_service":
        return "consensus"
    return "compute"


def _canonical_market_summary(*, nodes: list[dict], canonical_candidates: list[dict]) -> dict:
    enabled_service_kinds = sorted(
        {
            service["kind"]
            for node in nodes
            for service in node.get("canonical_services", [])
            if service.get("enabled")
        }
    )
    capability_ids = sorted(
        {
            capability_id
            for capability_id in (
                *[
                    runtime.get("capability_id")
                    for node in nodes
                    for runtime in node.get("canonical_capability_runtimes", [])
                ],
                *[
                    candidate.get("capability_id")
                    for candidate in canonical_candidates
                ],
            )
            if capability_id
        }
    )
    runtime_ids = {
        runtime.get("runtime_id")
        for node in nodes
        for runtime in node.get("canonical_capability_runtimes", [])
        if runtime.get("runtime_id")
    }
    runtime_ids.update(
        {
            candidate.get("runtime_id")
            for candidate in canonical_candidates
            if candidate.get("runtime_id")
        }
    )
    endpoint_advertisement_count = sum(
        1
        for node in nodes
        for item in node.get("canonical_advertisements", [])
        if item.get("resource_type") == "endpoint"
    )
    if endpoint_advertisement_count == 0:
        endpoint_advertisement_count = sum(
            1
            for candidate in canonical_candidates
            if candidate.get("resource_type") == "endpoint"
        )
    return {
        "service_kinds": enabled_service_kinds,
        "capability_ids": capability_ids,
        "runtime_count": len(runtime_ids),
        "endpoint_advertisement_count": endpoint_advertisement_count,
    }


def _canonical_market_candidate_sort_key(candidate: dict) -> tuple:
    return (
        {"ready": 0, "stale": 1, "offline": 2}[candidate["status"]],
        -candidate["rating"]["score"],
        candidate["pricing"]["input"],
        candidate["pricing"]["output"],
        candidate["node_id"],
        candidate["advertisement_id"],
        candidate.get("runtime_id") or "",
        candidate.get("legacy_bundle_id") or "",
    )
