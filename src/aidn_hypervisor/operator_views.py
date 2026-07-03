from aidn_hypervisor.endpoint_publications.models import (
    canonical_configuration_payload,
    configuration_hash_for_publication,
)


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
    endpoints_payload = build_operator_endpoints_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
    )
    return {
        **service_payload,
        "bootstrap": _build_operator_home_bootstrap_payload(
            service=service,
            endpoint_items=endpoints_payload["items"],
            fallback_bootstrap=service_payload.get("bootstrap", {}),
        ),
        "market_preview": {
            "candidate_count": len(market_candidates or []),
        },
    }


def build_operator_endpoints_payload(
    *,
    service,
    endpoint_service,
    endpoint_publication_service=None,
    validation_service=None,
) -> dict:
    if endpoint_service is None:
        return service.operator_dashboard_endpoints()

    manifests = list(endpoint_service.list_endpoints())
    if not manifests:
        return service.operator_dashboard_endpoints()

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
        "summary": summary,
        "policy": {
            "publish_requires_validation": False,
            "validation_optional": True,
            "execution_privacy": "endpoint implementation remains private",
        },
        "items": items,
    }
