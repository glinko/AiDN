ONBOARDING_STEPS = [
    ("configure_wallet", "Configure Wallet", "home"),
    ("attach_provider", "Attach Provider", "providers"),
    ("prepare_bundle", "Prepare Bundle", "bundles"),
    ("create_endpoint", "Create Endpoint", "bundles"),
    ("publish_endpoint", "Publish Endpoint", "endpoints"),
    ("operate", "Operate Hypervisor", "home"),
]

_WORKSPACE_BY_STEP = {
    key: workspace for key, _label, workspace in ONBOARDING_STEPS
}
_INDEX_BY_STEP = {key: index for index, (key, _label, _workspace) in enumerate(ONBOARDING_STEPS)}


def onboarding_recommended_action(
    *,
    current_step: str,
    first_endpoint_candidate: dict | None,
) -> dict:
    candidate = first_endpoint_candidate or {}
    bundle_id = candidate.get("bundle_id")
    if current_step == "configure_wallet":
        return {
            "label": "Create Wallet",
            "detail": "Create or import a wallet before any publish or network-facing step.",
            "type": "bootstrap",
            "action": "create-wallet",
        }
    if current_step == "attach_provider":
        return {
            "label": "Open Providers",
            "detail": "Attach a provider so the dashboard can surface a local execution path.",
            "type": "screen",
            "action": "providers",
        }
    if current_step == "prepare_bundle":
        return {
            "label": "Open Bundles",
            "detail": "Prepare a bundle or finish model setup before creating the first endpoint.",
            "type": "screen",
            "action": "bundles",
        }
    if current_step == "create_endpoint":
        return {
            "label": "Create First Endpoint",
            "detail": (
                f"Bundle {bundle_id} is ready to become the first endpoint."
                if bundle_id
                else "Create the first endpoint from a ready local bundle."
            ),
            "type": "endpoint",
            "action": "create-endpoint",
        }
    if current_step == "publish_endpoint":
        return {
            "label": "Open Endpoints",
            "detail": "Review the endpoint draft and publish the first local endpoint to complete onboarding.",
            "type": "screen",
            "action": "endpoints",
        }
    return {
        "label": "Open Home",
        "detail": "Onboarding is complete. Return to Home for the normal operator dashboard.",
        "type": "screen",
        "action": "open-home",
    }


def build_onboarding_payload(
    *,
    wallet_ready: bool,
    provider_count: int,
    bundle_count: int,
    endpoint_items: list[dict],
    first_endpoint_candidate: dict | None,
    persisted: dict | None,
) -> dict:
    persisted = persisted or {}
    has_published_endpoint = any(
        item.get("publication_status") == "published" for item in endpoint_items
    )
    completed = bool(persisted.get("completed")) or has_published_endpoint
    completed_at = persisted.get("completed_at")
    completed_via = persisted.get("completed_via")
    if has_published_endpoint:
        # The endpoint publication projection is authoritative for the live
        # state. Older persisted onboarding records may predate the finality
        # callback and therefore lack completion metadata even though the
        # endpoint is already published.
        completed_via = completed_via or "first_local_endpoint_published"
        if completed_at is None:
            published_at = sorted(
                item.get("published_at")
                for item in endpoint_items
                if item.get("publication_status") == "published"
                and isinstance(item.get("published_at"), str)
            )
            completed_at = published_at[0] if published_at else None

    if completed:
        current_step = "operate"
    elif not wallet_ready:
        current_step = "configure_wallet"
    elif provider_count <= 0:
        current_step = "attach_provider"
    elif bundle_count <= 0 or first_endpoint_candidate is None:
        current_step = "prepare_bundle"
    elif not endpoint_items:
        current_step = "create_endpoint"
    else:
        current_step = "publish_endpoint"

    current_index = _INDEX_BY_STEP[current_step]
    steps = []
    for index, (key, label, workspace) in enumerate(ONBOARDING_STEPS):
        if key == current_step:
            status = "active"
        elif index < current_index:
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

    return {
        "completed": completed,
        "completed_at": completed_at,
        "completed_via": completed_via,
        "current_step": current_step,
        "workspace": _WORKSPACE_BY_STEP[current_step],
        "last_workspace": persisted.get("last_workspace", "home"),
        "transition_history": list(persisted.get("transition_history", [])),
        "steps": steps,
        "recommended_action": onboarding_recommended_action(
            current_step=current_step,
            first_endpoint_candidate=first_endpoint_candidate,
        ),
    }
