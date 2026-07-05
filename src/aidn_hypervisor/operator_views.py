from aidn_hypervisor.endpoint_publications.models import (
    canonical_configuration_payload,
    configuration_hash_for_publication,
)
from aidn_hypervisor.operator_onboarding import build_onboarding_payload


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


def _home_endpoint_pipeline(
    *,
    endpoint_items: list[dict],
    wallet_ready: bool,
    onboarding: dict | None = None,
) -> dict:
    primary = _primary_endpoint_for_home(endpoint_items)
    onboarding = onboarding or {}
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
            "recommended_action": {
                **onboarding.get(
                    "recommended_action",
                    {
                        "action": "open-bundles",
                        "label": "Open Bundles",
                    },
                ),
                "workspace": onboarding.get("workspace", "bundles"),
            },
        }
    if primary["publication_sync_status"] == "local_changes_not_published":
        return {
            "state": "published_drifted",
            "primary_endpoint_id": primary["endpoint_id"],
            "publication_sync_status": primary["publication_sync_status"],
            "recommended_action": {
                "action": "publish-configuration",
                "label": "Publish Configuration",
                "workspace": "endpoints",
            },
        }
    if primary["publication_status"] in {"configured", "draft"}:
        return {
            "state": "draft_exists",
            "primary_endpoint_id": primary["endpoint_id"],
            "publication_sync_status": primary["publication_sync_status"],
            "recommended_action": {
                "action": "open-endpoints",
                "label": "Open Endpoints",
                "workspace": "endpoints",
            },
        }
    return {
        "state": "published_in_sync",
        "primary_endpoint_id": primary["endpoint_id"],
        "publication_sync_status": primary["publication_sync_status"],
        "recommended_action": {
            "action": "open-endpoints",
            "label": "Open Live Endpoint",
            "workspace": "endpoints",
        },
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
        onboarding=onboarding,
    )
    return {
        "bootstrap": _build_operator_home_bootstrap_payload(
            service=service,
            endpoint_items=endpoints_payload["items"],
            fallback_bootstrap=service_payload.get("bootstrap", {}),
        ),
        "endpoint_pipeline": endpoint_pipeline,
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


def build_operator_providers_payload(*, service) -> dict:
    fleet = service.operator_dashboard_fleet()
    bundles = fleet["bundles"]
    installs = fleet["installs"]
    items = []
    for plugin in service.plugins.list():
        description = plugin.describe()
        plugin_id = description["plugin_id"]
        provider_bundles = [
            bundle for bundle in bundles if bundle["plugin_id"] == plugin_id
        ]
        provider_type_aliases = {bundle["provider_type"] for bundle in provider_bundles}
        provider_type_aliases.add(plugin_id)
        provider_installs = [
            install
            for install in installs
            if install["provider_type"] in provider_type_aliases
        ]
        items.append(
            {
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
        )
    return {
        "owner_wallet": fleet["owner_wallet"],
        "node_identity": fleet["node_identity"],
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
        },
        "items": items,
    }


def build_operator_bundles_payload(*, service) -> dict:
    fleet = service.operator_dashboard_fleet()
    bundles = fleet["bundles"]
    candidate = service.operator_dashboard_home()["bootstrap"].get(
        "first_endpoint_candidate"
    )
    candidate_id = candidate.get("bundle_id") if candidate is not None else None
    items = []
    for bundle in bundles:
        is_first_endpoint_candidate = bundle["bundle_id"] == candidate_id
        items.append(
            {
                **bundle,
                "is_first_endpoint_candidate": is_first_endpoint_candidate,
                "endpoint_action": {
                    "recommended": (
                        "create_endpoint"
                        if is_first_endpoint_candidate
                        else "inspect_bundle"
                    )
                },
            }
        )
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
        },
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


def build_operator_endpoints_payload(
    *,
    service,
    endpoint_service,
    endpoint_publication_service=None,
    validation_service=None,
) -> dict:
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
        return payload

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
        return payload

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
    return {
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
        "policy": {
            "publish_requires_validation": False,
            "validation_optional": True,
            "execution_privacy": "endpoint implementation remains private",
        },
        "items": items,
    }
