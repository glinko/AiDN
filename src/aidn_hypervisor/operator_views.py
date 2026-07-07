from aidn_hypervisor.dashboard import build_market_payload
from aidn_hypervisor.endpoint_publications.models import (
    canonical_configuration_payload,
    configuration_hash_for_publication,
)
from aidn_hypervisor.operator_onboarding import ONBOARDING_STEPS, build_onboarding_payload


def _execution_payload_for_manifest(manifest) -> dict:
    if manifest.execution_strategy != "proxy" or manifest.proxy_target is None:
        return {"strategy": manifest.execution_strategy}
    return {
        "strategy": manifest.execution_strategy,
        "target_fingerprint": configuration_hash_for_publication(
            {
                "remote_endpoint_id": manifest.proxy_target.remote_endpoint_id,
                "source_publication_id": manifest.proxy_target.source_publication_id,
                "source_configuration_hash": manifest.proxy_target.source_configuration_hash,
            }
        ),
    }


def _local_publication_configuration_hash(manifest) -> str:
    payload = canonical_configuration_payload(
        bundle_hash=manifest.bundle_hash,
        model_class=manifest.model_class,
        capabilities=manifest.capabilities,
        runtime=manifest.runtime.model_dump(mode="json"),
        publication=manifest.publication.model_dump(mode="json"),
        pricing=manifest.pricing.model_dump(mode="json"),
        session=manifest.session.model_dump(mode="json"),
        execution=_execution_payload_for_manifest(manifest),
    )
    return configuration_hash_for_publication(payload)


def _publication_sync_status(
    *,
    local_configuration_hash: str | None,
    published_configuration_hash: str | None,
) -> str:
    if published_configuration_hash is None:
        return "never_published"
    if local_configuration_hash == published_configuration_hash:
        return "in_sync"
    return "local_changes_not_published"


def _validation_summary_for(
    validation_service,
    *,
    endpoint_id: str,
    configuration_hash: str | None,
) -> dict | None:
    if validation_service is None or configuration_hash is None:
        return None
    return validation_service.validation_summary(
        endpoint_id,
        configuration_hash=configuration_hash,
    )


def _snapshot_publication_configuration_hash(manifest, snapshot) -> str:
    snapshot_manifest = manifest.model_copy(
        update={
            "bundle_hash": snapshot.bundle_hash,
            "runtime": snapshot.runtime,
            "publication": snapshot.publication,
            "session": snapshot.session,
            "execution_strategy": snapshot.execution_config.get(
                "execution_strategy",
                manifest.execution_strategy,
            ),
            "proxy_target": snapshot.proxy_target,
        }
    )
    return _local_publication_configuration_hash(snapshot_manifest)


def _configuration_hash_for_publication_record(
    *,
    endpoint_service,
    manifest,
    publication_configuration_hash: str | None,
) -> str | None:
    if (
        endpoint_service is None
        or manifest is None
        or publication_configuration_hash is None
    ):
        return None
    for snapshot in reversed(
        endpoint_service.list_configuration_snapshots(manifest.endpoint_id)
    ):
        if (
            _snapshot_publication_configuration_hash(manifest, snapshot)
            == publication_configuration_hash
        ):
            return snapshot.configuration_hash
    return None


def _primary_endpoint_for_home(endpoint_items: list[dict]) -> dict | None:
    priority = {
        "local_changes_not_published": 0,
        "never_published": 1,
        "in_sync": 2,
    }
    if not endpoint_items:
        return None
    return sorted(
        endpoint_items,
        key=lambda item: (
            priority.get(item.get("publication_sync_status"), 99),
            item.get("publication_status") != "published",
            item.get("endpoint_id") or "",
        ),
    )[0]


def _home_no_endpoint_recommended_action(
    *,
    provider_count: int,
    bundle_count: int,
    first_endpoint_candidate: dict | None,
) -> dict:
    if provider_count <= 0:
        return {
            "action": "providers",
            "label": "Open Providers",
            "workspace": "providers",
        }
    if bundle_count <= 0 or first_endpoint_candidate is None:
        return {
            "action": "bundles",
            "label": "Open Bundles",
            "workspace": "bundles",
        }
    return {
        "action": "create",
        "label": "Create First Endpoint",
        "workspace": "bundles",
    }


def _home_bootstrap_next_step(
    *,
    endpoint_pipeline: dict,
    first_endpoint_candidate: dict | None,
    fallback_next_step: str | None,
) -> str:
    state = endpoint_pipeline.get("state")
    action = endpoint_pipeline.get("recommended_action", {}).get("action")
    if state == "wallet_required":
        return "Create or import a wallet"
    if state == "no_endpoint":
        if action == "providers":
            return "Attach a provider or install a model"
        if action == "bundles":
            return "Prepare a bundle or finish model setup before creating the first endpoint"
        bundle_id = (first_endpoint_candidate or {}).get("bundle_id")
        if bundle_id:
            return f"Create your first endpoint from {bundle_id}"
        return "Create your first endpoint from a ready local bundle"
    if state == "draft_exists":
        return "Review your configured endpoint and publish it"
    if state == "published_drifted":
        return "Publish your updated endpoint configuration to sync the live endpoint"
    if state == "published_in_sync":
        return "Manage your published endpoint and request validation when ready"
    return fallback_next_step or "Attach a provider or install a model"


def _home_onboarding_steps(
    *,
    current_step: str,
    completed: bool,
    completed_at: str | None,
) -> list[dict]:
    step_index = {
        key: index for index, (key, _label, _workspace) in enumerate(ONBOARDING_STEPS)
    }
    current_index = step_index[current_step]
    steps = []
    for index, (key, label, workspace) in enumerate(ONBOARDING_STEPS):
        if key == current_step:
            status = "active"
        elif index < current_index or (completed and current_step == "operate"):
            status = "complete"
        else:
            status = "upcoming"
        steps.append(
            {
                "key": key,
                "label": label,
                "workspace": workspace,
                "status": status,
                "completed_at": completed_at if status == "complete" else None,
            }
        )
    return steps


def _canonical_endpoint_workspace_action(*, label: str, detail: str | None = None) -> dict:
    payload = {
        "action": "endpoints",
        "label": label,
        "workspace": "endpoints",
    }
    if detail is not None:
        payload["detail"] = detail
    return payload


def _normalized_home_onboarding_action(
    *,
    endpoint_pipeline: dict,
    first_endpoint_candidate: dict | None,
) -> dict:
    state = endpoint_pipeline.get("state")
    recommended = endpoint_pipeline.get("recommended_action", {})
    action = recommended.get("action")
    if state == "wallet_required":
        return {
            "label": "Create Wallet",
            "detail": "Create or import a wallet before any publish or network-facing step.",
            "type": "bootstrap",
            "action": "create-wallet",
        }
    if state == "no_endpoint":
        if action == "providers":
            return {
                "label": "Open Providers",
                "detail": "Attach a provider so the dashboard can surface a local execution path.",
                "type": "screen",
                "action": "providers",
            }
        if action == "bundles":
            return {
                "label": "Open Bundles",
                "detail": "Prepare a bundle or finish model setup before creating the first endpoint.",
                "type": "screen",
                "action": "bundles",
            }
        bundle_id = (first_endpoint_candidate or {}).get("bundle_id")
        return {
            "label": "Create First Endpoint",
            "detail": (
                f"Bundle {bundle_id} is ready to become the first endpoint."
                if bundle_id
                else "Create the first endpoint from a ready local bundle."
            ),
            "type": "endpoint",
            "action": "create",
        }
    if state == "published_drifted":
        return {
            "label": "Republish In Endpoints",
            "detail": "Open Endpoints and publish the updated configuration so the live service is back in sync.",
            "type": "screen",
            "action": "endpoints",
        }
    return {
        "label": "Manage Endpoint",
        "detail": "Open Endpoints to manage draft, publication, privacy, proxy, sessions, and validation state.",
        "type": "screen",
        "action": "endpoints",
    }


def _normalize_home_onboarding(
    *,
    onboarding: dict,
    endpoint_pipeline: dict,
    first_endpoint_candidate: dict | None,
) -> dict:
    historical_completed = bool(onboarding.get("completed"))
    normalized = {
        **onboarding,
        "recommended_action": _normalized_home_onboarding_action(
            endpoint_pipeline=endpoint_pipeline,
            first_endpoint_candidate=first_endpoint_candidate,
        ),
    }
    state = endpoint_pipeline.get("state")
    if state == "wallet_required":
        current_step = "configure_wallet"
        workspace = "home"
        completed = historical_completed
    elif state == "no_endpoint":
        action = endpoint_pipeline.get("recommended_action", {}).get("action")
        current_step = {
            "providers": "attach_provider",
            "bundles": "prepare_bundle",
            "create": "create_endpoint",
        }.get(action, "create_endpoint")
        workspace = {
            "providers": "providers",
            "bundles": "bundles",
            "create": "bundles",
        }.get(action, "bundles")
        completed = historical_completed
    elif state == "draft_exists":
        current_step = "publish_endpoint"
        workspace = "endpoints"
        completed = historical_completed
    elif state == "published_drifted":
        current_step = "publish_endpoint"
        workspace = "endpoints"
        completed = historical_completed
    else:
        current_step = normalized.get("current_step", "operate")
        workspace = normalized.get("workspace", "home")
        completed = normalized.get("completed", False)
    normalized["completed"] = completed
    normalized["current_step"] = current_step
    normalized["workspace"] = workspace
    normalized["steps"] = _home_onboarding_steps(
        current_step=current_step,
        completed=completed,
        completed_at=normalized.get("completed_at"),
    )
    return normalized


def _home_endpoint_pipeline(
    *,
    endpoint_items: list[dict],
    wallet_ready: bool,
    provider_count: int,
    bundle_count: int,
    first_endpoint_candidate: dict | None,
) -> dict:
    primary = _primary_endpoint_for_home(endpoint_items)
    if not wallet_ready:
        return {
            "state": "wallet_required",
            "primary_endpoint_id": None,
            "publication_sync_status": None,
            "recommended_action": {
                "action": "create-wallet",
                "label": "Create Wallet",
                "workspace": "home",
            },
        }
    if primary is None:
        return {
            "state": "no_endpoint",
            "primary_endpoint_id": None,
            "publication_sync_status": None,
            "recommended_action": _home_no_endpoint_recommended_action(
                provider_count=provider_count,
                bundle_count=bundle_count,
                first_endpoint_candidate=first_endpoint_candidate,
            ),
        }
    if primary["publication_sync_status"] == "local_changes_not_published":
        return {
            "state": "published_drifted",
            "primary_endpoint_id": primary["endpoint_id"],
            "publication_sync_status": primary["publication_sync_status"],
            "recommended_action": _canonical_endpoint_workspace_action(
                label="Republish In Endpoints",
                detail="Open Endpoints and publish the updated configuration so the live service is back in sync.",
            ),
        }
    if primary["publication_status"] in {"configured", "draft"}:
        return {
            "state": "draft_exists",
            "primary_endpoint_id": primary["endpoint_id"],
            "publication_sync_status": primary["publication_sync_status"],
            "recommended_action": _canonical_endpoint_workspace_action(
                label="Open Endpoints",
                detail="Open Endpoints to review the draft and publish it when ready.",
            ),
        }
    return {
        "state": "published_in_sync",
        "primary_endpoint_id": primary["endpoint_id"],
        "publication_sync_status": primary["publication_sync_status"],
        "recommended_action": _canonical_endpoint_workspace_action(
            label="Manage Endpoint",
            detail="Open Endpoints to manage draft, publication, privacy, proxy, sessions, and validation state.",
        ),
    }


def _build_operator_home_bootstrap_payload(
    *,
    service,
    endpoint_items: list[dict],
    fallback_bootstrap: dict,
) -> dict:
    configured = [
        item
        for item in endpoint_items
        if item["publication_status"] in {"configured", "draft"}
    ]
    if not service.owner_wallet_state()["configured"]:
        next_step = "Create or import a wallet"
    elif configured:
        next_step = "Review your configured endpoint and publish it"
    elif endpoint_items:
        next_step = "Manage your published endpoint and request validation when ready"
    else:
        next_step = fallback_bootstrap.get(
            "next_step"
        ) or "Attach a provider or install a model"
    return {
        "wallet_ready": service.owner_wallet_state()["configured"],
        "owner_wallet": service.owner_wallet_state(),
        "node_identity": service.node_identity(),
        "provider_count": fallback_bootstrap.get("provider_count", 0),
        "bundle_count": fallback_bootstrap.get("bundle_count", 0),
        "endpoint_count": len(endpoint_items),
        "first_endpoint_candidate": fallback_bootstrap.get("first_endpoint_candidate"),
        "items": endpoint_items,
        "next_step": next_step,
    }


def _bundle_relationships(endpoint_items: list[dict]) -> dict[str, dict]:
    relationships: dict[str, dict] = {}
    for item in endpoint_items:
        bundle_id = item.get("bundle_id")
        if not bundle_id:
            continue
        state = (
            "published_endpoint_exists"
            if item.get("publication_status") == "published"
            else "draft_endpoint_exists"
        )
        existing = relationships.get(bundle_id)
        if existing is not None and existing.get("state") == "published_endpoint_exists":
            continue
        relationships[bundle_id] = {
            "state": state,
            "endpoint_id": item.get("endpoint_id"),
            "publication_status": item.get("publication_status"),
            "publication_sync_status": item.get("publication_sync_status"),
        }
    return relationships


def _provider_endpoint_readiness(
    *,
    provider: dict,
    provider_bundle_ids: set[str],
    endpoint_items: list[dict],
) -> dict:
    if not provider.get("plugin_id"):
        return {
            "state": "not_attached",
            "recommended_action": {
                "action": "providers",
                "label": "Open Providers",
                "workspace": "providers",
            },
        }
    if int(provider.get("bundle_count", 0) or 0) <= 0:
        return {
            "state": "attached_no_usable_supply",
            "recommended_action": {
                "action": "providers",
                "label": "Inspect Provider",
                "workspace": "providers",
            },
        }
    related = [
        item
        for item in endpoint_items
        if item.get("bundle_id") in provider_bundle_ids
    ]
    related_bundle_ids = {item.get("bundle_id") for item in related if item.get("bundle_id")}
    unclaimed_bundle_ids = provider_bundle_ids - related_bundle_ids
    if related and unclaimed_bundle_ids:
        return {
            "state": "mixed_endpoint_supply",
            "recommended_action": {
                "action": "create_endpoint",
                "label": "Create Endpoint",
                "workspace": "endpoints",
                "bundle_id": sorted(unclaimed_bundle_ids)[0],
            },
        }
    if related:
        return {
            "state": "already_backing_endpoint_supply",
            "recommended_action": {
                "action": "open_endpoint",
                "label": "Open Endpoint",
                "workspace": "endpoints",
                "endpoint_id": related[0].get("endpoint_id"),
            },
        }
    return {
        "state": "ready_for_endpoint_creation",
        "recommended_action": {
            "action": "create_endpoint",
            "label": "Create Endpoint",
            "workspace": "endpoints",
        },
    }


def _bundle_endpoint_relationship(*, bundle: dict, relationship: dict | None) -> dict:
    if relationship is None:
        return {
            "state": "no_endpoint",
            "recommended_action": {
                "action": "create_endpoint",
                "label": "Create Endpoint",
                "workspace": "endpoints",
                "bundle_id": bundle.get("bundle_id"),
            },
        }
    publication_sync_status = relationship.get("publication_sync_status")
    endpoint_id = relationship.get("endpoint_id")
    if publication_sync_status == "local_changes_not_published":
        return {
            "state": "published_drifted",
            "recommended_action": {
                "action": "open_endpoint",
                "label": "Republish In Endpoints",
                "workspace": "endpoints",
                "endpoint_id": endpoint_id,
            },
        }
    if relationship.get("publication_status") == "published":
        state = "published_endpoint"
    else:
        state = "draft_endpoint"
    return {
        "state": state,
        "recommended_action": {
            "action": "open_endpoint",
            "label": "Open Endpoint",
            "workspace": "endpoints",
            "endpoint_id": endpoint_id,
        },
    }


def build_operator_home_payload(
    *,
    service,
    endpoint_service,
    endpoint_publication_service=None,
    validation_service=None,
    market_candidates=None,
) -> dict:
    service_payload = service.operator_dashboard_home()
    service_summary = service_payload.get("summary", {})
    bootstrap_facts = service_payload.get("bootstrap", {})
    wallet_ready = service.owner_wallet_state()["configured"]
    endpoints_payload = build_operator_endpoints_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
    )
    onboarding = build_onboarding_payload(
        wallet_ready=wallet_ready,
        provider_count=service_payload.get("bootstrap", {}).get("provider_count", 0),
        bundle_count=service_payload.get("bootstrap", {}).get("bundle_count", 0),
        endpoint_items=endpoints_payload["items"],
        first_endpoint_candidate=service_payload.get("bootstrap", {}).get(
            "first_endpoint_candidate"
        ),
        persisted=service.operator_onboarding_state(),
    )
    endpoint_pipeline = _home_endpoint_pipeline(
        endpoint_items=endpoints_payload["items"],
        wallet_ready=wallet_ready,
        provider_count=bootstrap_facts.get("provider_count", 0),
        bundle_count=bootstrap_facts.get("bundle_count", 0),
        first_endpoint_candidate=bootstrap_facts.get("first_endpoint_candidate"),
    )
    onboarding = _normalize_home_onboarding(
        onboarding=onboarding,
        endpoint_pipeline=endpoint_pipeline,
        first_endpoint_candidate=bootstrap_facts.get("first_endpoint_candidate"),
    )
    bootstrap = _build_operator_home_bootstrap_payload(
        service=service,
        endpoint_items=endpoints_payload["items"],
        fallback_bootstrap=bootstrap_facts,
    )
    bootstrap["next_step"] = _home_bootstrap_next_step(
        endpoint_pipeline=endpoint_pipeline,
        first_endpoint_candidate=bootstrap_facts.get("first_endpoint_candidate"),
        fallback_next_step=bootstrap.get("next_step"),
    )
    return {
        "bootstrap": bootstrap,
        "endpoint_pipeline": endpoint_pipeline,
        "canonical_overlay": service.canonical_overlay_inventory(),
        "onboarding": onboarding,
        "publish": {
            "draft_offer_count": service_summary.get("bundle_total", 0),
            "install_pending_count": service_summary.get("pending_install_total", 0),
            "live_offer_count": service_summary.get("enabled_bundle_total", 0),
        },
        "market_visibility": {
            "local_offer_count": service_summary.get("bundle_total", 0),
            "live_offer_count": service_summary.get("enabled_bundle_total", 0),
        },
        "fleet_capacity": {
            "node_count": 1,
            "queued": service_summary.get("queue", {}).get("queued", 0),
            "active": service_summary.get("queue", {}).get("active", 0),
            "free": service_summary.get("free_resources", {}),
        },
        "operator_controls": {
            "actions": [
                "Create Wallet",
                "Install Model",
                "Create Endpoint",
                "Publish Offer",
                "Attach Endpoint",
                "Pause Queue",
                "Raise Limits",
                "Connect Remote Node",
            ]
        },
        "market_preview": {
            "candidate_count": len(market_candidates or []),
        },
    }


def build_operator_providers_payload(
    *,
    service,
    endpoint_service=None,
    endpoint_publication_service=None,
    validation_service=None,
) -> dict:
    fleet = service.operator_dashboard_fleet()
    bundles = fleet["bundles"]
    installs = fleet["installs"]
    endpoint_items = []
    if endpoint_service is not None:
        endpoint_items = build_operator_endpoints_payload(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=endpoint_publication_service,
            validation_service=validation_service,
        )["items"]
    relationships = _bundle_relationships(endpoint_items)
    items = []
    for plugin in service.plugins.list():
        description = plugin.describe()
        plugin_id = description["plugin_id"]
        provider_bundles = [
            bundle for bundle in bundles if bundle["plugin_id"] == plugin_id
        ]
        provider_bundle_ids = {
            bundle["bundle_id"] for bundle in provider_bundles if bundle.get("bundle_id")
        }
        provider_type_aliases = {bundle["provider_type"] for bundle in provider_bundles}
        provider_type_aliases.add(plugin_id)
        provider_installs = [
            install
            for install in installs
            if install["provider_type"] in provider_type_aliases
        ]
        provider_item = {
            **description,
            "bundle_count": len(provider_bundles),
            "active_bundle_count": sum(
                1 for bundle in provider_bundles if bundle["enabled"]
            ),
            "install_count": len(provider_installs),
            "pending_install_count": sum(
                1
                for install in provider_installs
                if install["install_status"] in {"pending", "running"}
            ),
        }
        provider_item["endpoint_readiness"] = _provider_endpoint_readiness(
            provider=provider_item,
            provider_bundle_ids=provider_bundle_ids,
            endpoint_items=endpoint_items,
        )
        items.append(provider_item)
    summary_recommended_action = {
        "action": "providers",
        "label": "Attach Provider",
        "workspace": "providers",
    }
    endpoint_ready_provider = next(
        (
            item
            for item in items
            if item["endpoint_readiness"]["state"]
            in {
                "mixed_endpoint_supply",
                "ready_for_endpoint_creation",
                "already_backing_endpoint_supply",
            }
        ),
        None,
    )
    if endpoint_ready_provider is not None:
        summary_recommended_action = endpoint_ready_provider["endpoint_readiness"][
            "recommended_action"
        ]
    return {
        "owner_wallet": fleet["owner_wallet"],
        "node_identity": fleet["node_identity"],
        "recommended_action": summary_recommended_action,
        "onboarding": build_onboarding_payload(
            wallet_ready=fleet["owner_wallet"]["configured"],
            provider_count=len(items),
            bundle_count=len(bundles),
            endpoint_items=[],
            first_endpoint_candidate=service.operator_dashboard_home()["bootstrap"].get(
                "first_endpoint_candidate"
            ),
            persisted=service.operator_onboarding_state(),
        ),
        "summary": {
            "total": len(items),
            "bundles": len(bundles),
            "installs": len(installs),
            "endpoint_ready_bundles": sum(
                1 for bundle in bundles if bundle["bundle_id"] not in relationships
            ),
            "recommended_action": summary_recommended_action,
        },
        "items": items,
    }


def build_operator_bundles_payload(
    *,
    service,
    endpoint_service=None,
    endpoint_publication_service=None,
    validation_service=None,
) -> dict:
    fleet = service.operator_dashboard_fleet()
    bundles = fleet["bundles"]
    candidate = service.operator_dashboard_home()["bootstrap"].get(
        "first_endpoint_candidate"
    )
    candidate_id = candidate.get("bundle_id") if candidate is not None else None
    endpoint_items = []
    if endpoint_service is not None:
        endpoint_items = build_operator_endpoints_payload(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=endpoint_publication_service,
            validation_service=validation_service,
        )["items"]
    relationships = _bundle_relationships(endpoint_items)
    items = []
    for bundle in bundles:
        is_first_endpoint_candidate = bundle["bundle_id"] == candidate_id
        relationship = relationships.get(bundle["bundle_id"])
        endpoint_relationship = _bundle_endpoint_relationship(
            bundle=bundle,
            relationship=relationship,
        )
        relationship_action = endpoint_relationship["recommended_action"]
        items.append(
            {
                **bundle,
                "is_first_endpoint_candidate": is_first_endpoint_candidate,
                "endpoint_relationship": endpoint_relationship,
                "endpoint_action": {
                    "recommended": relationship_action["action"]
                },
            }
        )
    bundles_recommended_action = {
        "action": "create_endpoint",
        "label": "Create Endpoint",
        "workspace": "endpoints",
    }
    first_endpoint_action = next(
        (
            item["endpoint_relationship"]["recommended_action"]
            for item in items
            if item["is_first_endpoint_candidate"]
        ),
        None,
    )
    if first_endpoint_action is not None:
        bundles_recommended_action = first_endpoint_action
    elif items:
        bundles_recommended_action = items[0]["endpoint_relationship"][
            "recommended_action"
        ]
    return {
        "owner_wallet": fleet["owner_wallet"],
        "node_identity": fleet["node_identity"],
        "onboarding": build_onboarding_payload(
            wallet_ready=fleet["owner_wallet"]["configured"],
            provider_count=len(service.plugins.list()),
            bundle_count=len(items),
            endpoint_items=[],
            first_endpoint_candidate=candidate,
            persisted=service.operator_onboarding_state(),
        ),
        "summary": {
            "total": len(items),
            "enabled": sum(1 for item in items if item["enabled"]),
            "ready_to_publish": sum(
                1 for item in items if item["publish_status"] == "ready_to_publish"
            ),
            "first_endpoint_candidates": sum(
                1 for item in items if item["is_first_endpoint_candidate"]
            ),
            "recommended_action": bundles_recommended_action,
        },
        "recommended_action": bundles_recommended_action,
        "items": items,
    }


def build_operator_installs_payload(*, service) -> dict:
    fleet = service.operator_dashboard_fleet()
    raw_installs = {job["install_id"]: job for job in service.list_model_installs()}
    items = []
    for install in fleet["installs"]:
        raw_install = raw_installs.get(install["install_id"], {})
        can_register_bundle = (
            install["install_status"] == "completed" and install["bundle_id"] is None
        )
        if can_register_bundle:
            next_action = "register_bundle"
        elif install["install_status"] in {"pending", "running"}:
            next_action = "monitor_install"
        elif install["install_status"] == "failed":
            next_action = "review_error"
        else:
            next_action = "none"
        items.append(
            {
                **install,
                "target_path": raw_install.get("target_path"),
                "can_register_bundle": can_register_bundle,
                "next_action": next_action,
            }
        )
    return {
        "owner_wallet": fleet["owner_wallet"],
        "node_identity": fleet["node_identity"],
        "summary": {
            "total": len(items),
            "pending": sum(
                1 for item in items if item["install_status"] == "pending"
            ),
            "running": sum(
                1 for item in items if item["install_status"] == "running"
            ),
            "completed": sum(
                1 for item in items if item["install_status"] == "completed"
            ),
            "failed": sum(1 for item in items if item["install_status"] == "failed"),
            "ready_to_register": sum(
                1 for item in items if item["can_register_bundle"]
            ),
        },
        "items": items,
    }


def build_operator_market_payload(*, service, registry_service) -> dict:
    return build_market_payload(service=service, registry_service=registry_service)


def build_operator_remote_endpoints_payload(
    *,
    service,
    registry_service=None,
    remote_endpoint_service=None,
) -> dict:
    attached = (
        [
            record.model_dump(mode="json")
            for record in remote_endpoint_service.list_remote_endpoints()
        ]
        if remote_endpoint_service is not None
        else []
    )
    attached_keys = {
        (item["source_node_id"], item["source_endpoint_id"]) for item in attached
    }
    discovered: list[dict] = []
    if registry_service is not None:
        for node in registry_service.list_nodes():
            if node["node_id"] == service.node_id:
                continue
            for endpoint in node.get("published_endpoints", []):
                discovered.append(
                    {
                        "node_id": node["node_id"],
                        "operator_id": node["operator_id"],
                        "base_url": node["base_url"],
                        "status": node["status"],
                        "pricing": node["pricing"],
                        "rating": node["rating"],
                        "can_host_custom_model": node["can_host_custom_model"],
                        "endpoint_id": endpoint["endpoint_id"],
                        "owner_wallet": endpoint["owner_wallet"],
                        "publication_id": endpoint["current_publication_id"],
                        "configuration_hash": endpoint["current_configuration_hash"],
                        "published_at": endpoint["published_at"],
                        "visibility": endpoint["visibility"],
                        "model_class": endpoint["model_class"],
                        "publication_sync_status": endpoint.get(
                            "publication_sync_status"
                        ),
                        "published_validation_summary": endpoint.get(
                            "published_validation_summary"
                        ),
                        "live_validation_summary": endpoint.get(
                            "live_validation_summary"
                        ),
                        "already_attached": (
                            (node["node_id"], endpoint["endpoint_id"]) in attached_keys
                        ),
                    }
                )
    discovered.sort(
        key=lambda item: (
            -float(item["rating"].get("score", 0.0)),
            float(item["pricing"].get("input", 0)),
            item["node_id"],
            item["endpoint_id"],
        )
    )
    payload = {
        "owner_wallet": service.owner_wallet_state(),
        "node_identity": service.node_identity(),
        "summary": {
            "attached": len(attached),
            "discovered": len(discovered),
            "remote_nodes": len({item["node_id"] for item in discovered}),
            "model_classes": len({item["model_class"] for item in discovered}),
        },
        "policy": {
            "local_catalogue": True,
            "proxy_ready": True,
            "execution_privacy": "underlying execution topology remains private",
        },
        "attached": attached,
        "discovered": discovered,
    }
    payload["recommended_action"] = _remote_endpoints_recommended_action(payload)
    return payload


def _remote_endpoints_recommended_action(payload: dict) -> dict:
    summary = payload.get("summary", {})
    if summary.get("attached", 0):
        return {
            "action": "stage_proxy_route",
            "label": "Open Endpoints",
            "workspace": "endpoints",
            "detail": "Use attached remote capacity to stage a proxy endpoint route.",
        }
    if summary.get("discovered", 0):
        return {
            "action": "attach_remote_endpoint",
            "label": "Attach Remote Endpoint",
            "workspace": "remote",
            "detail": "Add a discovered remote endpoint to the local catalogue before routing through it.",
        }
    return {
        "action": "review_market_supply",
        "label": "Open Market",
        "workspace": "market",
        "detail": "Browse remote supply in the market before attaching or proxying endpoints.",
    }


def build_operator_endpoints_payload(
    *,
    service,
    endpoint_service,
    endpoint_publication_service=None,
    validation_service=None,
) -> dict:
    def _with_endpoint_workspace_defaults(payload: dict) -> dict:
        summary = payload.get("summary", {})
        payload["workspace_role"] = "primary_control_plane"
        payload["recommended_action"] = {
            "action": "select_endpoint" if summary.get("total", 0) else "create_endpoint",
            "label": "Open Endpoint Controls" if summary.get("total", 0) else "Create Endpoint",
            "workspace": "endpoints",
        }
        payload["policy"] = {
            "publish_requires_validation": False,
            "validation_optional": True,
            "execution_privacy": "endpoint implementation remains private",
        }
        return payload

    if endpoint_service is None:
        payload = service.operator_dashboard_endpoints()
        payload["onboarding"] = build_onboarding_payload(
            wallet_ready=service.owner_wallet_state()["configured"],
            provider_count=service.operator_dashboard_home()["bootstrap"].get(
                "provider_count", 0
            ),
            bundle_count=service.operator_dashboard_home()["bootstrap"].get(
                "bundle_count", 0
            ),
            endpoint_items=payload["items"],
            first_endpoint_candidate=service.operator_dashboard_home()["bootstrap"].get(
                "first_endpoint_candidate"
            ),
            persisted=service.operator_onboarding_state(),
        )
        return _with_endpoint_workspace_defaults(payload)

    manifests = list(endpoint_service.list_endpoints())
    if not manifests:
        payload = service.operator_dashboard_endpoints()
        payload["onboarding"] = build_onboarding_payload(
            wallet_ready=service.owner_wallet_state()["configured"],
            provider_count=service.operator_dashboard_home()["bootstrap"].get(
                "provider_count", 0
            ),
            bundle_count=service.operator_dashboard_home()["bootstrap"].get(
                "bundle_count", 0
            ),
            endpoint_items=payload["items"],
            first_endpoint_candidate=service.operator_dashboard_home()["bootstrap"].get(
                "first_endpoint_candidate"
            ),
            persisted=service.operator_onboarding_state(),
        )
        return _with_endpoint_workspace_defaults(payload)

    items = []
    for manifest in manifests:
        local_configuration_hash = _local_publication_configuration_hash(manifest)
        current_publication = (
            endpoint_publication_service.current_publication(manifest.endpoint_id)
            if endpoint_publication_service is not None
            else None
        )
        publication_history = (
            endpoint_publication_service.list_publications(
                endpoint_id=manifest.endpoint_id
            )
            if endpoint_publication_service is not None
            else []
        )
        configuration_snapshots = [
            snapshot.model_dump(mode="json")
            for snapshot in endpoint_service.list_configuration_snapshots(
                manifest.endpoint_id
            )
        ]
        published = current_publication is not None
        validation_requested = bool(
            manifest.validation.enabled
            or manifest.publication.validation == "enabled"
        )
        published_endpoint_configuration_hash = _configuration_hash_for_publication_record(
            endpoint_service=endpoint_service,
            manifest=manifest,
            publication_configuration_hash=(
                current_publication.configuration_hash
                if current_publication is not None
                else None
            ),
        )
        validation_summary = (
            validation_service.validation_summary(
                manifest.endpoint_id,
                configuration_hash=manifest.configuration_hash,
            )
            if validation_service is not None
            else None
        )
        published_validation_summary = (
            _validation_summary_for(
                validation_service,
                endpoint_id=manifest.endpoint_id,
                configuration_hash=published_endpoint_configuration_hash,
            )
            if current_publication is not None
            else None
        )
        items.append(
            {
                "endpoint_id": manifest.endpoint_id,
                "display_name": manifest.display_name,
                "bundle_id": manifest.bundle_id,
                "configuration_hash": manifest.configuration_hash,
                "local_configuration_hash": local_configuration_hash,
                "published_configuration_hash": (
                    current_publication.configuration_hash
                    if current_publication is not None
                    else None
                ),
                "publication_sync_status": _publication_sync_status(
                    local_configuration_hash=local_configuration_hash,
                    published_configuration_hash=(
                        current_publication.configuration_hash
                        if current_publication is not None
                        else None
                    ),
                ),
                "model_class": manifest.model_class,
                "capabilities": list(manifest.capabilities),
                "profile": manifest.profile.model_dump(mode="json"),
                "runtime": manifest.runtime.model_dump(mode="json"),
                "session": manifest.session.model_dump(mode="json"),
                "execution_strategy": manifest.execution_strategy,
                "proxy_target": (
                    manifest.proxy_target.model_dump(mode="json")
                    if manifest.proxy_target is not None
                    else None
                ),
                "visibility": manifest.publication.visibility,
                "publication_status": "published" if published else "configured",
                "validation_mode": "requested" if validation_requested else "disabled",
                "runtime_status": manifest.status,
                "publication": manifest.publication.model_dump(mode="json"),
                "validation": manifest.validation.model_dump(mode="json"),
                "validation_summary": validation_summary,
                "published_validation_summary": published_validation_summary,
                "current_publication": (
                    current_publication.model_dump(mode="json")
                    if current_publication is not None
                    else None
                ),
                "publication_history": [
                    record.model_dump(mode="json")
                    for record in publication_history
                ],
                "shared_with_wallet_ids": list(
                    manifest.publication.shared_with_wallet_ids
                ),
                "configuration_snapshots": configuration_snapshots,
                "endpoint_url": None,
                "created_at": manifest.created_at,
                "published_at": (
                    current_publication.published_at
                    if current_publication is not None
                    else None
                ),
            }
        )

    summary = {
        "total": len(items),
        "published": sum(
            1 for item in items if item["publication_status"] == "published"
        ),
        "configured": sum(
            1 for item in items if item["publication_status"] == "configured"
        ),
        "validation_requested": sum(
            1 for item in items if item["validation_mode"] == "requested"
        ),
        "private": sum(1 for item in items if item["visibility"] == "private"),
        "shared": sum(1 for item in items if item["visibility"] == "shared"),
        "public": sum(1 for item in items if item["visibility"] == "public"),
    }
    return _with_endpoint_workspace_defaults({
        "owner_wallet": service.owner_wallet_state(),
        "node_identity": service.node_identity(),
        "onboarding": build_onboarding_payload(
            wallet_ready=service.owner_wallet_state()["configured"],
            provider_count=service.operator_dashboard_home()["bootstrap"].get(
                "provider_count", 0
            ),
            bundle_count=service.operator_dashboard_home()["bootstrap"].get(
                "bundle_count", 0
            ),
            endpoint_items=items,
            first_endpoint_candidate=service.operator_dashboard_home()["bootstrap"].get(
                "first_endpoint_candidate"
            ),
            persisted=service.operator_onboarding_state(),
        ),
        "summary": summary,
        "items": items,
    })
