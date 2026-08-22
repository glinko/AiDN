"""Canonical Node Journey read model.

The dashboard deliberately consumes one graph instead of rebuilding readiness
rules in several React screens.  This module is read-only: it derives a
stable, explainable projection from the Hypervisor's existing read models and
never changes operational state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping, Sequence


JourneyState = str


_REQUIRED_NODE_IDS = (
    "hypervisor",
    "wallet",
    "provider",
    "model",
    "bundle",
    "endpoint",
    "validation",
    "discovery",
    "serve_requests",
    "earnings",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized(value: Any) -> str:
    return _text(value).lower().replace("-", "_").replace(" ", "_")


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _as_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _is_ready_state(value: Any) -> bool:
    return _normalized(value) in {"ready", "healthy", "published", "connected", "online", "valid"}


def _is_terminal_bad(value: Any) -> bool:
    return _normalized(value) in {"failed", "error", "unavailable", "degraded"}


class JourneyStateService:
    """Build the canonical operator journey graph from live Hypervisor state."""

    def __init__(self, service: Any, *, endpoint_items: Sequence[Mapping[str, Any]] | None = None) -> None:
        self.service = service
        self.endpoint_items = [dict(item) for item in _as_list(endpoint_items)]

    def _safe_call(self, name: str, default: Any) -> Any:
        method = getattr(self.service, name, None)
        if not callable(method):
            return default
        try:
            return method()
        except (KeyError, OSError, RuntimeError, TypeError, ValueError):
            return default

    def _facts(self) -> dict[str, Any]:
        home = self._safe_call("operator_dashboard_home", {})
        fleet = self._safe_call("operator_dashboard_fleet", {})
        wallet = self._safe_call("owner_wallet_state", {})
        providers = self._safe_call("list_provider_instances", [])
        deployments = self._safe_call("list_model_deployments", [])
        bindings = self._safe_call("list_runtime_bindings", [])
        installed_plugins = self._safe_call("list_installed_provider_plugins", [])
        hooks = self._safe_call("list_hooks", [])
        resources = self._safe_call("resource_summary", None)
        if not isinstance(resources, Mapping):
            resource_manager = getattr(self.service, "resources", None)
            summary = getattr(resource_manager, "summary", None)
            try:
                resources = summary() if callable(summary) else {}
            except (OSError, RuntimeError, TypeError, ValueError):
                resources = {}
        if not isinstance(home, Mapping):
            home = {}
        if not isinstance(fleet, Mapping):
            fleet = {}
        bootstrap = home.get("bootstrap") if isinstance(home.get("bootstrap"), Mapping) else {}
        node = fleet.get("node") if isinstance(fleet.get("node"), Mapping) else bootstrap.get("node_identity")
        if not isinstance(node, Mapping):
            node = {}
        bundles = _as_list(fleet.get("bundles"))
        if not bundles:
            bundles = _as_list(bootstrap.get("bundles"))
        return {
            "home": home,
            "fleet": fleet,
            "wallet": dict(wallet) if isinstance(wallet, Mapping) else {},
            "node": dict(node),
            "providers": _as_list(providers),
            "deployments": _as_list(deployments),
            "bindings": _as_list(bindings),
            "installed_plugins": _as_list(installed_plugins),
            "hooks": _as_list(hooks),
            "resources": dict(resources) if isinstance(resources, Mapping) else {},
            "bundles": bundles,
        }

    @staticmethod
    def _node(
        *,
        node_id: str,
        title: str,
        description: str,
        state: JourneyState,
        required: bool,
        dependencies: Sequence[str],
        route: str | None,
        action_label: str,
        reason: str,
        category: str,
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        action = None
        if route:
            action = {"label": action_label, "route": route, "screen": route}
        return {
            "id": node_id,
            "type": node_id,
            "category": category,
            "title": title,
            "description": description,
            "state": state,
            "required": required,
            "dependencies": list(dependencies),
            "action": action,
            "reason": reason,
            "details": dict(details or {}),
        }

    def build(self) -> dict[str, Any]:
        facts = self._facts()
        wallet = facts["wallet"]
        node = facts["node"]
        providers = facts["providers"]
        deployments = facts["deployments"]
        bindings = facts["bindings"]
        bundles = facts["bundles"]
        endpoints = self.endpoint_items
        resources = facts["resources"]
        queue = facts["fleet"].get("queue") if isinstance(facts["fleet"].get("queue"), Mapping) else {}

        hypervisor_ready = bool(_text(node.get("node_id")) or _text(getattr(self.service, "node_id", "")))
        wallet_ready = bool(wallet.get("configured"))
        enabled_bundles = [item for item in bundles if bool(item.get("enabled"))]
        managed_bundles = [
            item for item in enabled_bundles
            if _normalized(item.get("launch_mode")) == "managed_process" and _text(item.get("model_id"))
        ]
        provider_ready = bool(providers or managed_bundles or facts["installed_plugins"])
        provider_in_progress = bool(not provider_ready and (facts["installed_plugins"] or bindings))
        model_ready = bool(deployments or managed_bundles or any(_text(item.get("model_id")) for item in bundles))
        model_in_progress = bool(not model_ready and bindings)
        bundle_ready = bool(enabled_bundles or bundles)
        configured_endpoints = [item for item in endpoints if _text(item.get("endpoint_id"))]
        published_endpoints = [
            item for item in configured_endpoints
            if _normalized(item.get("publication_status")) in {"published", "active", "online"}
        ]
        endpoint_ready = bool(published_endpoints)
        endpoint_in_progress = bool(configured_endpoints and not endpoint_ready)

        validation_items = []
        for endpoint in published_endpoints:
            validation = endpoint.get("validation_summary") or endpoint.get("validation")
            if isinstance(validation, Mapping):
                validation_items.append(validation)
        valid_count = sum(
            1
            for item in validation_items
            if _normalized(item.get("status") or item.get("state") or item.get("result"))
            in {"valid", "verified", "passed", "certified"}
        )
        pending_validation = any(
            _normalized(item.get("status") or item.get("state")) in {"pending", "requested", "running", "in_progress"}
            for item in validation_items
        )
        validation_ready = bool(published_endpoints and valid_count == len(published_endpoints))
        consensus = getattr(self.service, "consensus_service", None)
        consensus_status: Mapping[str, Any] = {}
        status_method = getattr(consensus, "status", None)
        if callable(status_method):
            try:
                raw_status = status_method()
                if isinstance(raw_status, Mapping):
                    consensus_status = raw_status
            except (OSError, RuntimeError, TypeError, ValueError):
                consensus_status = {}
        network_ready = bool(
            _is_ready_state(consensus_status.get("status"))
            or _is_ready_state(consensus_status.get("state"))
            or consensus_status.get("rpc_available") is True
            or consensus_status.get("available") is True
        )
        registry_ready = False
        registry_method = getattr(self.service, "registry_enabled", None)
        if callable(registry_method):
            try:
                registry_ready = bool(registry_method())
            except (OSError, RuntimeError, TypeError, ValueError):
                registry_ready = False
        if not network_ready and not consensus_status and hypervisor_ready:
            # A local-only node can still complete setup without a consensus backend.
            network_ready = registry_ready
        runtime_ready = any(
            _normalized(item.get("runtime_status") or item.get("runtime_health_status")) in {"ready", "healthy", "running"}
            for item in bundles
        )
        resources_total = resources.get("total") if isinstance(resources.get("total"), Mapping) else {}
        resources_free = resources.get("free") if isinstance(resources.get("free"), Mapping) else {}
        resource_reported = any(_number(resources_total.get(key)) > 0 for key in ("cpu", "ram_mb", "vram_mb"))
        resource_warning = resource_reported and any(
            _number(resources_free.get(key)) <= 0
            for key in ("ram_mb", "vram_mb")
            if _number(resources_total.get(key)) > 0
        )

        nodes = [
            self._node(node_id="hypervisor", title="Your AiDN Node", description="The local Hypervisor is initialized and reporting its identity.", state="ready" if hypervisor_ready else "in_progress", required=True, dependencies=[], route="settings", action_label="Node settings", reason="Node identity is available." if hypervisor_ready else "The Hypervisor has not reported a node identity yet.", category="identity", details={"node_id": node.get("node_id")}),
            self._node(node_id="wallet", title="Wallet", description="Bind ownership for network actions and settlement.", state="ready" if wallet_ready else "not_started", required=True, dependencies=["hypervisor"], route="wallet", action_label="Manage wallet", reason="Owner wallet is configured." if wallet_ready else "Create or connect an owner wallet before network-facing actions.", category="identity", details={"wallet_id": wallet.get("wallet_id")}),
            self._node(node_id="provider", title="Providers", description="Install and configure a model execution provider.", state="ready" if provider_ready else "in_progress" if provider_in_progress else "not_started", required=True, dependencies=["hypervisor"], route="providers", action_label="Manage providers", reason="A provider path is available." if provider_ready else "Install a Provider Plugin or attach a Provider Instance.", category="compute", details={"instances": len(providers), "installed_plugins": len(facts["installed_plugins"])}),
            self._node(node_id="model", title="Models", description="Deploy a model that a Provider can serve.", state="ready" if model_ready else "in_progress" if model_in_progress else "blocked", required=True, dependencies=["provider"], route="models", action_label="Manage models", reason="A model deployment or managed Bundle is present." if model_ready else "A Provider is required before a model can be deployed.", category="compute", details={"deployments": len(deployments), "bundles_with_models": len([item for item in bundles if _text(item.get("model_id"))])}),
            self._node(node_id="bundle", title="Bundles", description="Create an immutable, reproducible service configuration.", state="ready" if bundle_ready else "blocked", required=True, dependencies=["model"], route="bundles", action_label="Open bundles", reason="At least one Bundle is configured." if bundle_ready else "Create a Bundle after a model is available.", category="compute", details={"total": len(bundles), "enabled": len(enabled_bundles)}),
            self._node(node_id="endpoint", title="Endpoints", description="Publish a model-backed offer for requests and agents.", state="ready" if endpoint_ready else "in_progress" if endpoint_in_progress else "blocked", required=True, dependencies=["bundle"], route="endpoints", action_label="Open endpoints", reason="A published Endpoint is discoverable." if endpoint_ready else "Configure and publish an Endpoint from a Bundle.", category="network", details={"configured": len(configured_endpoints), "published": len(published_endpoints)}),
            self._node(node_id="validation", title="Validation", description="Validate the public service and preserve proof of readiness.", state="ready" if validation_ready else "in_progress" if pending_validation else "blocked", required=True, dependencies=["endpoint"], route="validation", action_label="Review validation", reason="Published Endpoints have validation evidence." if validation_ready else "A published Endpoint must be validated before it is trusted.", category="network", details={"valid": valid_count, "published": len(published_endpoints)}),
            self._node(node_id="discovery", title="Discovery", description="Make the validated service visible to the network.", state="ready" if endpoint_ready and network_ready else "warning" if endpoint_ready else "blocked", required=True, dependencies=["endpoint", "validation"], route="network", action_label="Open network", reason="Network evidence and a published Endpoint are available." if endpoint_ready and network_ready else "Network connectivity and a published Endpoint are required for discovery.", category="network", details={"network_ready": network_ready}),
            self._node(node_id="serve_requests", title="Serve requests", description="Keep a healthy runtime available for local or remote work.", state="ready" if endpoint_ready and runtime_ready else "warning" if endpoint_ready else "blocked", required=True, dependencies=["endpoint", "resources"], route="agents", action_label="Open agents", reason="A published Endpoint has a healthy runtime." if endpoint_ready and runtime_ready else "Activate a healthy runtime and keep enough resources available.", category="operations", details={"runtime_ready": runtime_ready, "active": queue.get("active", 0)}),
            self._node(node_id="earnings", title="Earnings", description="Track Q earned from useful shared compute.", state="ready" if endpoint_ready and wallet_ready else "blocked", required=True, dependencies=["endpoint", "wallet"], route="wallet", action_label="Open wallet", reason="Wallet and a published Endpoint are ready for settlement evidence." if endpoint_ready and wallet_ready else "A configured wallet and published Endpoint are required.", category="economics", details={"wallet_configured": wallet_ready}),
            self._node(node_id="resources", title="Resources", description="Monitor CPU, RAM, GPU and VRAM admission capacity.", state="warning" if resource_warning else "ready" if resource_reported else "not_started", required=False, dependencies=["hypervisor"], route="settings", action_label="Inspect resources", reason="Live resource capacity is reported." if resource_reported else "Run a resource probe to establish capacity truth.", category="operations", details={"total": resources_total, "free": resources_free}),
            self._node(node_id="policies", title="Policies", description="Set access, pricing and local-priority rules.", state="ready" if callable(getattr(self.service, "operator_requests_policy", None)) else "not_started", required=False, dependencies=["hypervisor"], route="settings", action_label="Open settings", reason="Operator policy controls are available." if callable(getattr(self.service, "operator_requests_policy", None)) else "No policy read model is available.", category="operations"),
            self._node(node_id="security", title="Security", description="Protect identity, credentials and control sessions.", state="ready" if hypervisor_ready else "blocked", required=False, dependencies=["hypervisor"], route="settings", action_label="Review security", reason="Node identity is present; secrets remain in the control boundary." if hypervisor_ready else "Initialize the node before reviewing security controls.", category="operations"),
            self._node(node_id="monitoring", title="Monitoring", description="Observe event history, hooks and operational evidence.", state="ready" if facts["hooks"] or hypervisor_ready else "not_started", required=False, dependencies=["hypervisor"], route="hooks", action_label="Open automation", reason="Operational event controls are available." if facts["hooks"] or hypervisor_ready else "Enable operational monitoring after initialization.", category="operations", details={"hooks": len(facts["hooks"])}),
            self._node(node_id="plugins", title="Plugins", description="Extend the node with reviewed provider and protocol plugins.", state="ready" if facts["installed_plugins"] else "not_started", required=False, dependencies=["provider"], route="catalog", action_label="Explore catalog", reason="Reviewed plugins are installed." if facts["installed_plugins"] else "Optional: explore the reviewed plugin catalog.", category="extensions", details={"installed": len(facts["installed_plugins"])}),
            self._node(node_id="backups", title="Backups", description="Keep recovery snapshots for operational state.", state="not_started", required=False, dependencies=["hypervisor"], route="settings", action_label="Open maintenance", reason="No backup read model is exposed yet.", category="extensions"),
            self._node(node_id="analytics", title="Analytics", description="Review usage and performance over time.", state="ready" if queue else "not_started", required=False, dependencies=["serve_requests"], route="agents", action_label="Review activity", reason="Queue and activity evidence is available." if queue else "Usage evidence will appear after requests are served.", category="extensions"),
        ]

        edges: list[dict[str, Any]] = []
        for item in nodes:
            for dependency in item["dependencies"]:
                edges.append({"from": dependency, "to": item["id"], "type": "required" if item["required"] else "optional"})

        required_nodes = [item for item in nodes if item["required"]]
        ready_required = sum(1 for item in required_nodes if item["state"] == "ready")
        optional_nodes = [item for item in nodes if not item["required"]]
        ready_optional = sum(1 for item in optional_nodes if item["state"] == "ready")
        recommended = next((item for item in required_nodes if item["state"] in {"not_started", "blocked", "in_progress", "warning", "error"}), None)
        progress_total = len(required_nodes)
        progress = {
            "required_ready": ready_required,
            "required_total": progress_total,
            "percent": round((ready_required / progress_total) * 100) if progress_total else 0,
            "optional_ready": ready_optional,
            "optional_total": len(optional_nodes),
        }
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "hypervisor": {
                "node_id": node.get("node_id") or getattr(self.service, "node_id", None),
                "version": _text(getattr(self.service, "version", "")) or None,
                "role": "provider",
                "state": "ready" if hypervisor_ready else "in_progress",
                "network_ready": network_ready,
                "resource_reported": resource_reported,
            },
            "progress": progress,
            "nodes": nodes,
            "edges": edges,
            "recommended_action": (
                {
                    "node_id": recommended["id"],
                    "title": recommended["title"],
                    "description": recommended["reason"],
                    "label": recommended["action"]["label"] if recommended.get("action") else "Continue",
                    "route": recommended["action"]["route"] if recommended.get("action") else None,
                    "screen": recommended["action"]["screen"] if recommended.get("action") else None,
                }
                if recommended is not None
                else {"node_id": None, "title": "Node is operational", "description": "Required setup stages are ready.", "label": "Review dashboard", "route": "overview", "screen": "overview"}
            ),
            "role": "provider",
        }


def build_journey_payload(service: Any, *, endpoint_items: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    return JourneyStateService(service, endpoint_items=endpoint_items).build()
