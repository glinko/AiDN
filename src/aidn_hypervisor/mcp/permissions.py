"""Canonical, operator-grantable MCP permissions for remote agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class McpAgentPermission:
    """One permission the Dashboard may grant to an enrolled MCP agent."""

    scope: str
    label: str
    description: str
    category: str
    risk: str
    tool_names: tuple[str, ...]
    approval_key: str | None = None

    def public(self) -> dict[str, object]:
        return asdict(self)


# This is intentionally an allow-list, not a free-form scope editor.  New
# tools must be added here deliberately so a Dashboard cannot accidentally
# grant private-key, shell, consensus, or wildcard authority.
AGENT_PERMISSION_CATALOG: tuple[McpAgentPermission, ...] = (
    McpAgentPermission(
        "CAPABILITIES:READ",
        "Capabilities",
        "Read the MCP capability and policy boundary.",
        "Read",
        "low",
        ("aidn.capabilities.get",),
    ),
    McpAgentPermission(
        "HOST:READ",
        "Host inspection",
        "Inspect sanitized host capabilities without shell access.",
        "Read",
        "low",
        ("aidn.host.inspect",),
    ),
    McpAgentPermission(
        "NODE:READ",
        "Node status",
        "Read node identity and health.",
        "Read",
        "low",
        ("aidn.node.status", "aidn.node.health"),
    ),
    McpAgentPermission(
        "NETWORK:READ",
        "Network status",
        "Read network synchronization and peer state.",
        "Read",
        "low",
        ("aidn.network.status", "aidn.network.peers"),
    ),
    McpAgentPermission(
        "PROVIDER:READ",
        "Provider inventory",
        "Read provider instances and runtime bindings.",
        "Read",
        "low",
        ("aidn.provider.list",),
    ),
    McpAgentPermission(
        "MODEL:READ",
        "Model inventory",
        "Read model deployments and installation jobs.",
        "Read",
        "low",
        ("aidn.model.list",),
    ),
    McpAgentPermission(
        "BUNDLE:READ",
        "Bundle inventory",
        "Read immutable Bundle revisions and local state.",
        "Read",
        "low",
        ("aidn.bundle.list", "aidn.bundle.get"),
    ),
    McpAgentPermission(
        "ENDPOINT:READ",
        "Endpoint inventory",
        "Read local Endpoint configurations without secrets.",
        "Read",
        "low",
        ("aidn.endpoint.list",),
    ),
    McpAgentPermission(
        "ENDPOINT:WRITE",
        "Create and publish Endpoints",
        (
            "Create Endpoint drafts and publish them through the canonical wallet path. "
            "Applying either plan requires operator confirmation unless explicitly "
            "auto-approved for this credential."
        ),
        "Actions",
        "critical",
        ("aidn.endpoint.create", "aidn.endpoint.publish"),
        "endpoint_write",
    ),
    McpAgentPermission(
        "RESOURCES:READ",
        "Resource status",
        "Read CPU, RAM, and VRAM reservation state.",
        "Read",
        "low",
        ("aidn.resources.status",),
    ),
    McpAgentPermission(
        "SCHEDULER:READ",
        "Scheduler policy",
        "Read routing and approval policy.",
        "Read",
        "low",
        ("aidn.policy.get", "aidn.scheduler.get_policy"),
    ),
    McpAgentPermission(
        "WALLET:READ",
        "Wallet summary",
        "Read public owner-wallet and accounting summary only.",
        "Read",
        "low",
        ("aidn.wallet.summary",),
    ),
    McpAgentPermission(
        "BUDGET:READ",
        "Delegated budgets",
        "Read the session's delegated budget state.",
        "Read",
        "low",
        ("aidn.budget.list", "aidn.budget.status"),
    ),
    McpAgentPermission(
        "AUDIT:READ", "Audit log", "Read the hash-linked MCP audit stream.", "Read", "low", ("aidn.audit.query",)
    ),
    McpAgentPermission(
        "PROVIDER:WRITE",
        "Attach provider",
        "Create a plan to attach a reachable Provider. Applying it still requires operator approval.",
        "Actions",
        "high",
        ("aidn.provider.attach",),
        "provider_attach",
    ),
    McpAgentPermission(
        "BUNDLE:ACTIVATE",
        "Activate Bundle",
        "Create or apply a Bundle activation plan. Runtime activation remains subject to the node approval policy.",
        "Actions",
        "high",
        ("aidn.bundle.activate",),
        "bundle_activate",
    ),
    McpAgentPermission(
        "BUNDLE:RETIRE",
        "Retire Bundle",
        "Create or apply a Bundle retirement plan. This may interrupt work and requires explicit operator approval.",
        "Actions",
        "critical",
        ("aidn.bundle.retire",),
        "bundle_retire",
    ),
)

DEFAULT_AGENT_READ_SCOPES: tuple[str, ...] = tuple(
    permission.scope for permission in AGENT_PERMISSION_CATALOG if permission.category == "Read"
)
_KNOWN_AGENT_SCOPES = frozenset(permission.scope for permission in AGENT_PERMISSION_CATALOG)
AGENT_MUTATION_SCOPES: tuple[str, ...] = tuple(
    permission.scope for permission in AGENT_PERMISSION_CATALOG if permission.approval_key is not None
)
FULL_AGENT_CONTROL_SCOPES: tuple[str, ...] = tuple(permission.scope for permission in AGENT_PERMISSION_CATALOG)
_APPROVAL_KEY_BY_SCOPE = {
    permission.scope: permission.approval_key
    for permission in AGENT_PERMISSION_CATALOG
    if permission.approval_key is not None
}


def normalize_agent_scopes(scopes: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Validate and normalize a Dashboard-selected agent scope set."""
    if not scopes or any(not isinstance(scope, str) or not scope.strip() for scope in scopes):
        raise ValueError("MCP agent permissions must contain at least one known scope")
    normalized = tuple(sorted({scope.strip() for scope in scopes}))
    unknown = sorted(set(normalized) - _KNOWN_AGENT_SCOPES)
    if unknown:
        raise ValueError("MCP agent permissions contain an unknown or non-grantable scope")
    return normalized


def normalize_auto_approved_scopes(scopes: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Validate auto-approval selections made for plan-bound agent actions."""
    if any(not isinstance(scope, str) or not scope.strip() for scope in scopes):
        raise ValueError("MCP agent auto-approval scopes must be non-empty strings")
    normalized = tuple(sorted({scope.strip() for scope in scopes}))
    if any(scope not in _APPROVAL_KEY_BY_SCOPE for scope in normalized):
        raise ValueError("MCP agent auto-approval is only available for plan-bound actions")
    return normalized


def approval_policy_for_agent(
    base_policy: dict[str, str], *, auto_approved_scopes: tuple[str, ...]
) -> dict[str, str]:
    """Derive a credential-specific approval policy from canonical operator policy.

    Agent credentials default to explicit confirmation even when the operator's
    own control session has a local automatic action.  An operator must opt in
    per credential and per mutation before a remote agent can apply it.
    """
    policy = dict(base_policy)
    auto_approved = set(auto_approved_scopes)
    for scope, approval_key in _APPROVAL_KEY_BY_SCOPE.items():
        policy[approval_key] = "AUTO" if scope in auto_approved else "OPERATOR_CONFIRMATION"
    return policy


def permission_catalog_payload() -> list[dict[str, object]]:
    return [permission.public() for permission in AGENT_PERMISSION_CATALOG]
