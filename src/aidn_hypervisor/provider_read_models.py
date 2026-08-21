from __future__ import annotations

from aidn_hypervisor.operator_onboarding import build_onboarding_payload
from aidn_hypervisor.runtime_operations_read_models import (
    build_runtime_operations_payload,
)


def _providers_empty_state() -> dict:
    return {
        "title": "No providers installed",
        "description": "Attach an existing provider or browse provider plugins.",
        "primary_action": {
            "action": "browse_provider_plugins",
            "label": "Browse provider plugins",
            "workspace": "providers",
        },
        "secondary_action": {
            "action": "attach_provider",
            "label": "Add existing provider",
            "workspace": "providers",
        },
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
        item for item in endpoint_items if item.get("bundle_id") in provider_bundle_ids
    ]
    related_bundle_ids = {
        item.get("bundle_id") for item in related if item.get("bundle_id")
    }
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


def build_operator_providers_payload(
    *,
    service,
    endpoint_items: list[dict] | None = None,
) -> dict:
    fleet = service.operator_dashboard_fleet()
    bundles = fleet["bundles"]
    installs = fleet["installs"]
    plugin_directory = service.provider_inventory.list_plugin_manifests()
    plugin_releases = service.list_provider_plugin_releases()
    installed_plugins = service.list_installed_provider_plugins()
    plugin_host_status = service.plugin_host_status()
    installation_executor = {
        "executor_id": service.provider_inventory.installation_executor.executor_id,
        "sandbox_capabilities": service.provider_inventory.executor_sandbox_capabilities(),
    }
    installation_artifacts = service.list_provider_installation_artifacts()
    model_artifacts = service.list_model_artifacts()
    model_artifact_sets = service.list_model_artifact_sets()
    artifact_materializations = service.list_model_artifact_materializations()
    installable_plugin_count = sum(
        1
        for manifest in plugin_directory
        if "CAN_INSTALL_PROVIDER" in manifest.get("plugin_capability_flags", [])
    )
    runtime_operations = build_runtime_operations_payload(service=service)
    # The live projection reattaches non-terminal broker jobs before returning.
    # Read the established, richer job records after that reconciliation so
    # legacy clients do not receive an older installation status beside the
    # fresh runtime_operations field.
    installation_jobs = service.list_provider_installation_jobs()
    applied_approval_ids = {
        job["approval_id"] for job in installation_jobs if job["status"] == "SUCCEEDED"
    }
    installation_approvals = []
    for approval in service.list_provider_installation_approvals():
        status_label = (
            "Applied with controlled executor"
            if approval["approval_id"] in applied_approval_ids
            else "Approved, ready to apply"
        )
        installation_approvals.append({**approval, "status_label": status_label})
    provider_instances = service.list_provider_instances()
    model_deployments = service.list_model_deployments()
    runtime_bindings = []
    for binding in service.list_runtime_bindings():
        try:
            endpoint_admission = service.runtime_binding_endpoint_admission(
                binding["runtime_binding_id"]
            )
        except (KeyError, ValueError) as error:
            endpoint_admission = {
                "runtime_binding_id": binding["runtime_binding_id"],
                "ready": False,
                "blockers": [
                    {
                        "code": "ENDPOINT_ADMISSION_EVALUATION_FAILED",
                        "message": str(error),
                    }
                ],
                "warnings": [],
                "dimensions": {},
            }
        runtime_bindings.append(
            {
                **binding,
                "endpoint_admission": endpoint_admission,
                "endpoint_admission_ready": endpoint_admission["ready"],
                "endpoint_admission_blocker_count": len(
                    endpoint_admission["blockers"]
                ),
                "endpoint_admission_warning_count": len(
                    endpoint_admission["warnings"]
                ),
            }
        )
    runtime_bindings_by_model: dict[str, list[dict]] = {}
    for binding in runtime_bindings:
        runtime_bindings_by_model.setdefault(binding["model_deployment_id"], []).append(
            binding
        )
    models_by_instance: dict[str, list[dict]] = {}
    for deployment in model_deployments:
        models_by_instance.setdefault(deployment["provider_instance_id"], []).append(
            deployment
        )
    enriched_model_deployments = []
    artifact_set_ids = {
        artifact_set["artifact_set_id"] for artifact_set in model_artifact_sets
    }
    materializations_by_provider_and_set: dict[tuple[str, str], list[dict]] = {}
    for materialization in artifact_materializations:
        materializations_by_provider_and_set.setdefault(
            (
                materialization["provider_instance_id"],
                materialization["artifact_set_id"],
            ),
            [],
        ).append(materialization)
    for deployment in model_deployments:
        deployment_bindings = runtime_bindings_by_model.get(
            deployment["model_deployment_id"],
            [],
        )
        artifact_set_id = deployment.get("artifact_set_id")
        artifact_set_available = (
            artifact_set_id in artifact_set_ids if artifact_set_id else False
        )
        deployment_materializations = (
            materializations_by_provider_and_set.get(
                (deployment["provider_instance_id"], artifact_set_id),
                [],
            )
            if artifact_set_id
            else []
        )
        ready_materialization = next(
            (
                item
                for item in deployment_materializations
                if item["status"] == "READY"
            ),
            None,
        )
        failed_materialization = next(
            (
                item
                for item in deployment_materializations
                if item["status"] == "FAILED"
            ),
            None,
        )
        if artifact_set_id is None:
            artifact_materialization_status = "NOT_REQUIRED"
        elif not artifact_set_available:
            artifact_materialization_status = "ARTIFACT_SET_MISSING"
        elif ready_materialization is not None:
            artifact_materialization_status = "READY"
        elif failed_materialization is not None:
            artifact_materialization_status = "FAILED"
        else:
            artifact_materialization_status = "MISSING"
        enriched_model_deployments.append(
            {
                **deployment,
                "runtime_binding_count": len(deployment_bindings),
                "runtime_binding_ready_count": sum(
                    1 for binding in deployment_bindings if binding["status"] == "ready"
                ),
                "artifact_set_available": artifact_set_available,
                "artifact_materialization_required": artifact_set_id is not None,
                "artifact_materialization_ready": ready_materialization is not None
                or artifact_set_id is None,
                "artifact_materialization_status": artifact_materialization_status,
                "artifact_materialization_id": (
                    ready_materialization or failed_materialization or {}
                ).get("materialization_id"),
                "artifact_materialization_destination": (
                    ready_materialization or failed_materialization or {}
                ).get("destination"),
            }
        )
    enriched_provider_instances = []
    for instance in provider_instances:
        instance_materializations = [
            item
            for item in artifact_materializations
            if item["provider_instance_id"] == instance["provider_instance_id"]
        ]
        instance_models = models_by_instance.get(instance["provider_instance_id"], [])
        instance_model_ids = {
            deployment["model_deployment_id"] for deployment in instance_models
        }
        instance_bindings = [
            binding
            for binding in runtime_bindings
            if binding["model_deployment_id"] in instance_model_ids
        ]
        enriched_provider_instances.append(
            {
                **instance,
                "model_count": len(instance_models),
                "runtime_binding_count": len(instance_bindings),
                "runtime_binding_ready_count": sum(
                    1 for binding in instance_bindings if binding["status"] == "ready"
                ),
                "artifact_materialization_count": len(instance_materializations),
                "artifact_materialization_ready_count": sum(
                    1 for item in instance_materializations if item["status"] == "READY"
                ),
            }
        )
    endpoint_items = endpoint_items or []
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
            "total_plugins": len(plugin_directory),
            "total_plugin_releases": len(plugin_releases),
            "total_installed_plugins": len(installed_plugins),
            "active_plugin_host_connections": plugin_host_status[
                "active_connection_count"
            ],
            "installable_plugin_count": installable_plugin_count,
            "approved_installation_count": sum(
                1 for approval in installation_approvals if approval["status"] == "APPROVED"
            ),
            "installation_job_count": len(installation_jobs),
            "total_provider_instances": len(provider_instances),
            "total_model_deployments": len(model_deployments),
            "total_model_artifact_sets": len(model_artifact_sets),
            "total_artifact_materializations": len(artifact_materializations),
            "total_runtime_bindings": len(runtime_bindings),
            "bundles": len(bundles),
            "installs": len(installs),
            "endpoint_ready_bundles": sum(
                1 for bundle in bundles if bundle["bundle_id"] not in relationships
            ),
            "recommended_action": summary_recommended_action,
        },
        "installation_executor": installation_executor,
        "installation_artifacts": installation_artifacts,
        "model_artifacts": model_artifacts,
        "model_artifact_sets": model_artifact_sets,
        "artifact_materializations": artifact_materializations,
        "empty_state": _providers_empty_state(),
        "plugin_directory": plugin_directory,
        "plugin_releases": plugin_releases,
        "installed_plugins": installed_plugins,
        "plugin_host_status": plugin_host_status,
        "installation_approvals": installation_approvals,
        "installation_jobs": installation_jobs,
        # Keep the established provider read model useful to existing MCP
        # clients while exposing the same live-reconciled projection used by
        # the dedicated dashboard widget and runtime.operations tool.
        "runtime_operations": runtime_operations,
        "provider_instances": enriched_provider_instances,
        "model_deployments": enriched_model_deployments,
        "runtime_bindings": runtime_bindings,
        "items": items,
    }
