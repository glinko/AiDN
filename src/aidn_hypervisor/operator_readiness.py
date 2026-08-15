"""Operator-facing readiness projection for the Hypervisor dashboard.

The projection deliberately reports observed state and bounded next actions. It
does not execute host commands, create credentials, or infer that a provider is
ready merely because its process is reachable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _action(
    *,
    kind: str,
    label: str,
    detail: str,
    screen: str | None = None,
    provider_instance_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": kind,
        "label": label,
        "detail": detail,
    }
    if screen is not None:
        result["screen"] = screen
    if provider_instance_id is not None:
        result["provider_instance_id"] = provider_instance_id
    return result


def _step(
    *,
    key: str,
    title: str,
    status: str,
    summary: str,
    detail: str,
    blocking: bool,
    action: dict[str, Any],
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "summary": summary,
        "detail": detail,
        "blocking": blocking,
        "action": action,
        "evidence": dict(evidence or {}),
    }


def _consensus_step(consensus_status: Mapping[str, Any] | None) -> dict[str, Any]:
    if consensus_status is None:
        return _step(
            key="consensus",
            title="Consensus RPC",
            status="manual",
            summary="Consensus status is not exposed by this process.",
            detail=(
                "The dashboard cannot verify network finality. Check the node's "
                "CometBFT service before treating it as a production network participant."
            ),
            blocking=True,
            action=_action(
                kind="manual",
                label="Run operator bootstrap",
                detail=(
                    "This node does not expose consensus management metadata. On a fresh Ubuntu host, "
                    "run the reviewed operator bootstrap; it installs CometBFT, creates a fixed user-systemd "
                    "unit, starts it after the Hypervisor ABCI listener, and then refresh this wizard."
                ),
            ),
            evidence={"available": False, "reason": "status_unavailable"},
        )

    rpc = consensus_status.get("rpc") or {}
    management = consensus_status.get("management") or {}
    managed_service = management.get("service")
    if not consensus_status.get("enabled", False):
        return _step(
            key="consensus",
            title="Consensus RPC",
            status="attention",
            summary="Consensus is disabled; this node is local-only.",
            detail=(
                "Local execution can continue, but this node cannot be considered "
                "ready for network-finalized operations until consensus mode is enabled."
            ),
            blocking=True,
            action=_action(
                kind="manual",
                label="Enable consensus",
                detail=(
                    "Re-run the operator bootstrap with --consensus-mode validator or "
                    "--consensus-mode non_validator. The installer provisions CometBFT "
                    "automatically; use --consensus-mode disabled only for local-only work."
                ),
            ),
            evidence={"enabled": False, "rpc": dict(rpc), "management": dict(management)},
        )
    if rpc.get("available"):
        return _step(
            key="consensus",
            title="Consensus RPC",
            status="ready",
            summary="CometBFT RPC is reachable.",
            detail=(
                "The node exposes a live consensus status and can be checked against "
                "the active chain configuration."
            ),
            blocking=False,
            action=_action(
                kind="refresh",
                label="Recheck status",
                detail="Refresh the readiness report.",
            ),
            evidence={"enabled": True, "rpc": dict(rpc), "management": dict(management)},
        )
    if managed_service:
        action_label = "Restart CometBFT"
        action_detail = (
            f"This node is managed by user-systemd unit {managed_service}. Run "
            f"systemctl --user restart {managed_service}, then press Recheck status."
        )
    else:
        action_label = "Install CometBFT"
        action_detail = (
            "This legacy node has no managed consensus unit. Open Advanced → CometBFT to run the "
            "paired dashboard installation wizard, apply the staged configuration, and start the unit."
        )
    return _step(
        key="consensus",
        title="Consensus RPC",
        status="blocked",
        summary="CometBFT is configured but its RPC is unavailable.",
        detail=(
            "Network-facing settlement and validator operations must not be treated "
            "as ready while the configured RPC cannot be reached."
        ),
        blocking=True,
        action=_action(
            kind="manual",
            label=action_label,
            detail=action_detail,
        ),
        evidence={"enabled": True, "rpc": dict(rpc), "management": dict(management)},
    )


def _is_ready_managed_bundle(bundle: Mapping[str, Any]) -> bool:
    """Return whether a Bundle can execute without provider inventory records.

    A model installed through the operator's managed-process path is already the
    executable deployment boundary.  It intentionally does not need a separate
    Provider Instance, Model Deployment, or Runtime Binding record.  Keep the
    check narrow so legacy/attached-service Bundles continue to require their
    explicit inventory chain.
    """

    return (
        bool(bundle.get("enabled", False))
        and str(bundle.get("launch_mode") or "").strip().lower() == "managed_process"
        and bool(str(bundle.get("model_id") or "").strip())
        and bool(str(bundle.get("endpoint") or "").strip())
    )


def build_operator_readiness_payload(
    *,
    service,
    endpoint_items: Sequence[Mapping[str, Any]] | None = None,
    consensus_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical readiness projection consumed by UI and tooling."""

    wallet = service.owner_wallet_state()
    resources = service.resources.summary() if service.resources is not None else {}
    totals = resources.get("total", {})
    probe = resources.get("probe", {})
    reported_resources = any(_number(totals.get(key)) > 0 for key in ("cpu", "ram_mb", "vram_mb"))
    provider_instances = list(service.list_provider_instances())
    model_deployments = list(service.list_model_deployments())
    runtime_bindings = list(service.list_runtime_bindings())
    fleet = service.operator_dashboard_fleet()
    bundles = list(fleet.get("bundles", []))
    endpoints = list(endpoint_items or [])
    ready_provider = next(
        (item for item in provider_instances if str(item.get("operational_state", "")).lower() in {"ready", "healthy"}),
        None,
    )
    ready_provider_count = sum(
        1
        for item in provider_instances
        if str(item.get("operational_state", "")).lower() in {"ready", "healthy"}
    )
    ready_models = [
        item for item in model_deployments if str(item.get("operational_state", "")).lower() in {"ready", "healthy"}
    ]
    ready_bindings = [item for item in runtime_bindings if str(item.get("status", "")).lower() == "ready"]
    enabled_bundles = [item for item in bundles if item.get("enabled", False)]
    managed_bundles = [item for item in enabled_bundles if _is_ready_managed_bundle(item)]
    managed_bundle_count = len(managed_bundles)
    managed_path_ready = managed_bundle_count > 0
    published_endpoints = [item for item in endpoints if item.get("publication_status") == "published"]
    provider_path_ready = ready_provider is not None or managed_path_ready

    steps: list[dict[str, Any]] = [_consensus_step(consensus_status)]
    steps.append(
        _step(
            key="wallet",
            title="Operator Wallet",
            status="ready" if wallet.get("configured") else "blocked",
            summary=(
                f"{wallet.get('label') or wallet.get('wallet_id') or 'Owner wallet'} is configured."
                if wallet.get("configured")
                else "No owner wallet is configured."
            ),
            detail=(
                "The wallet binds operator ownership and signs network-facing "
                "management and publication actions. Private key material is never "
                "included in this projection."
            ),
            blocking=not wallet.get("configured"),
            action=(
                _action(
                    kind="refresh",
                    label="Recheck wallet",
                    detail="Refresh the readiness report.",
                )
                if wallet.get("configured")
                else _action(
                    kind="wallet",
                    label="Configure wallet",
                    detail="Create a new wallet or import an existing owner wallet in the Wallet console.",
                )
            ),
            evidence={
                "configured": bool(wallet.get("configured")),
                "wallet_id": wallet.get("wallet_id"),
            },
        )
    )
    steps.append(
        _step(
            key="resources",
            title="Host Capacity",
            status="ready" if reported_resources else "blocked",
            summary=(
                (
                    f"Detected {_number(totals.get('cpu')):g} CPU cores and "
                    f"{int(_number(totals.get('ram_mb')))} MB RAM."
                )
                if reported_resources
                else "Automatic host capacity detection did not return CPU or RAM."
            ),
            detail=(
                "Capacity is measured during operator bootstrap and loaded at every "
                "Hypervisor start. GPU VRAM is reported only when the host exposes "
                "nvidia-smi or an explicit operator override."
            ),
            blocking=not reported_resources,
            action=(
                _action(
                    kind="refresh",
                    label="Recheck capacity",
                    detail="Refresh after configuring the host resource probe.",
                )
                if reported_resources
                else _action(
                    kind="resource-probe",
                    label="Run automatic probe",
                    detail=(
                        "Measure CPU, RAM and visible GPU VRAM now. If detection still "
                        "fails, re-run the reviewed operator bootstrap to restore the "
                        "capacity report and host permissions."
                    ),
                )
            ),
            evidence={
                "reported": reported_resources,
                "resources": dict(resources),
                "probe": dict(probe) if isinstance(probe, Mapping) else {},
            },
        )
    )
    steps.append(
        _step(
            key="provider",
            title="Provider Instance",
            status="ready" if provider_path_ready else ("attention" if provider_instances else "blocked"),
            summary=(
                f"{len(provider_instances)} provider instance(s) registered; at least one is ready."
                if ready_provider is not None
                else f"{managed_bundle_count} managed Bundle(s) provide the execution runtime; an attached Provider Instance is not required."
                if managed_path_ready
                else f"{len(provider_instances)} provider instance(s) registered, but none is ready."
                if provider_instances
                else "No provider instance is registered."
            ),
            detail=(
                "A reachable upstream provider is only the first half of the execution "
                "chain. Models and Runtime Bindings must still be created explicitly."
                if ready_provider is not None
                else "Managed process Bundles start their pinned runtime directly. Provider discovery is only required for attached-service Bundles."
                if managed_path_ready
                else "Attach a provider and wait for a healthy state before discovering an upstream model."
            ),
            blocking=not provider_path_ready,
            action=(
                _action(
                    kind="refresh",
                    label="Recheck provider",
                    detail="Refresh after the provider health state changes.",
                )
                if ready_provider is not None
                else _action(
                    kind="refresh",
                    label="Recheck managed Bundle",
                    detail="Refresh after the managed model or Bundle changes.",
                )
                if managed_path_ready
                else _action(
                    kind="screen",
                    label="Open providers",
                    detail="Inspect provider instances, attach an existing provider, or open the provider catalog.",
                    screen="providers",
                )
            ),
            evidence={
                "count": len(provider_instances),
                "ready_count": ready_provider_count,
                "provider_instance_id": ready_provider.get("provider_instance_id") if ready_provider else None,
                "managed_bundle_count": managed_bundle_count,
            },
        )
    )
    provider_id = ready_provider.get("provider_instance_id") if ready_provider else None
    model_path_ready = bool(ready_models) or managed_path_ready
    steps.append(
        _step(
            key="model_deployment",
            title="Model Deployment",
            status="ready" if model_path_ready else "blocked",
            summary=(
                f"{len(ready_models)} ready model deployment(s) discovered."
                if ready_models
                else "Managed Bundle includes a materialized model; external Model Deployment is not required."
                if managed_path_ready
                else "The upstream model is not registered in Hypervisor inventory yet."
            ),
            detail=(
                "A model visible in Ollama, vLLM or another upstream API is not "
                "automatically a Hypervisor Model Deployment. Discover or register it "
                "before binding a Runtime."
                if ready_models
                else "This model was installed and registered directly in a managed Bundle. Model Deployment discovery applies to attached-service providers."
                if managed_path_ready
                else "Register or discover a model before creating a Runtime Binding."
            ),
            blocking=not model_path_ready,
            action=(
                _action(
                    kind="refresh",
                    label="Recheck models",
                    detail="Refresh after model discovery or registration.",
                )
                if ready_models
                else _action(
                    kind="refresh",
                    label="Recheck managed model",
                    detail="Refresh after model materialization or Bundle changes.",
                )
                if managed_path_ready
                else _action(
                    kind="discover-provider" if provider_id else "screen",
                    label="Discover models" if provider_id else "Open providers",
                    detail=(
                        "Run model discovery against the ready provider, then choose "
                        "the deployment for Runtime Binding."
                    )
                    if provider_id
                    else "Register a provider before discovering models.",
                    screen=None if provider_id else "providers",
                    provider_instance_id=provider_id,
                )
            ),
            evidence={
                "count": len(model_deployments),
                "ready_count": len(ready_models),
                "provider_instance_id": provider_id,
                "managed_bundle_count": managed_bundle_count,
            },
        )
    )
    binding_path_ready = bool(ready_bindings) or managed_path_ready
    steps.append(
        _step(
            key="runtime_binding",
            title="Runtime Binding",
            status="ready" if binding_path_ready else "blocked",
            summary=(
                f"{len(ready_bindings)} Runtime Binding(s) are ready."
                if ready_bindings
                else "Managed Bundle runs without a separate Runtime Binding."
                if managed_path_ready
                else "No ready Runtime Binding connects a Model Deployment to a capability runtime."
            ),
            detail=(
                "This is the boundary that turns discovered model inventory into an "
                "executable RFC-0054 Runtime path. It is not implied by Provider "
                "readiness."
                if ready_bindings
                else "The managed process Bundle is already the executable runtime boundary; a separate Runtime Binding is only required for attached-service providers."
                if managed_path_ready
                else "Create a Runtime Binding after the model deployment is ready."
            ),
            blocking=not binding_path_ready,
            action=(
                _action(
                    kind="refresh",
                    label="Recheck runtime path",
                    detail="Refresh after the managed Bundle or runtime state changes.",
                )
                if managed_path_ready
                else _action(
                    kind="screen",
                    label="Open runtime setup",
                    detail=(
                        "Open Providers, inspect the Model Deployment, create a Runtime "
                        "Binding, and resolve any artifact or admission blockers."
                    ),
                    screen="providers",
                )
            ),
            evidence={
                "count": len(runtime_bindings),
                "ready_count": len(ready_bindings),
                "managed_bundle_count": managed_bundle_count,
            },
        )
    )
    bundle_path_ready = bool(enabled_bundles) and (bool(ready_bindings) or managed_path_ready)
    steps.append(
        _step(
            key="bundle",
            title="Bundle",
            status="ready" if bundle_path_ready else "blocked",
            summary=(
                f"{len(enabled_bundles)} enabled Bundle(s) are present."
                if enabled_bundles and ready_bindings
                else f"{managed_bundle_count} enabled managed Bundle(s) expose a local runtime endpoint."
                if managed_path_ready
                else "A Bundle cannot be considered executable until a ready Runtime Binding exists."
            ),
            detail=(
                "Bundle is the operator's canonical deployment object. It must reference "
                "the actual Runtime path; an old or declarative Bundle is not enough for "
                "production readiness."
                if enabled_bundles and ready_bindings
                else "Managed process Bundles are executable without a separate Runtime Binding; the runtime starts on demand from the registered model path."
                if managed_path_ready
                else "Enable a Bundle after its Runtime Binding is ready and points at the actual runtime path."
            ),
            blocking=not bundle_path_ready,
            action=_action(
                kind="screen",
                label="Open Bundles",
                detail=(
                    "Inspect the enabled managed Bundle and its registered model path."
                    if managed_path_ready
                    else "Create or inspect an immutable Bundle revision after Runtime Binding is ready."
                ),
                screen="bundles",
            ),
            evidence={
                "count": len(bundles),
                "enabled_count": len(enabled_bundles),
                "managed_count": managed_bundle_count,
            },
        )
    )
    steps.append(
        _step(
            key="endpoint",
            title="Endpoint Offer",
            status="ready" if published_endpoints else ("attention" if endpoints else "blocked"),
            summary=(
                f"{len(published_endpoints)} published Endpoint offer(s) are visible."
                if published_endpoints
                else f"{len(endpoints)} Endpoint draft(s) exist but none is published."
                if endpoints
                else "No Endpoint offer has been created."
            ),
            detail=(
                "Publication is the final network-facing step. It requires the configured "
                "owner wallet and a valid managed Bundle or Bundle/Runtime chain; validation "
                "remains a separate decision."
            ),
            blocking=not published_endpoints,
            action=_action(
                kind="screen",
                label="Open Endpoints",
                detail="Create, review or publish the Endpoint offer after the Bundle chain is ready.",
                screen="endpoints",
            ),
            evidence={"count": len(endpoints), "published_count": len(published_endpoints)},
        )
    )

    blocking_steps = [step for step in steps if step["blocking"]]
    attention_steps = [step for step in steps if step["status"] in {"attention", "manual"}]
    ready_count = sum(1 for step in steps if step["status"] == "ready")
    if blocking_steps:
        overall_state = "blocked"
    elif attention_steps:
        overall_state = "attention"
    else:
        overall_state = "ready"
    execution_keys = {"provider", "model_deployment", "runtime_binding", "bundle"}
    network_keys = {"consensus", "wallet", "endpoint"}
    execution_ready = all(step["status"] == "ready" for step in steps if step["key"] in execution_keys)
    network_ready = all(step["status"] == "ready" for step in steps if step["key"] in network_keys)
    return {
        "profile": "operator-readiness-v1",
        "overall_state": overall_state,
        "execution_ready": execution_ready,
        "network_ready": network_ready,
        "progress": {
            "ready": ready_count,
            "total": len(steps),
            "percent": round(ready_count / len(steps) * 100) if steps else 0,
        },
        "next_action": (blocking_steps or attention_steps or steps)[0]["action"] if steps else None,
        "steps": steps,
        "observed": {
            "provider_instances": len(provider_instances),
            "model_deployments": len(model_deployments),
            "runtime_bindings": len(runtime_bindings),
            "bundles": len(bundles),
            "endpoint_drafts": len(endpoints),
            "published_endpoints": len(published_endpoints),
        },
    }
