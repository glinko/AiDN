from importlib import import_module

from aidn_hypervisor.mcp.permissions_catalog_core import McpAgentPermission

_permission_rows = []
for _row_number in range(1, 8):
    module = import_module(f"aidn_hypervisor.mcp.permission_rows_{_row_number}")
    _permission_rows.extend(module.ROWS)


def _make_permission(row):
    scope, category, risk, tool_names, approval_key = row
    return McpAgentPermission(
        scope,
        scope.replace(":", " ").title(),
        "permission",
        category,
        risk,
        tuple(tool_names.split()),
        approval_key,
    )


AGENT_PERMISSION_CATALOG = tuple(_make_permission(row) for row in _permission_rows)
DEFAULT_AGENT_READ_SCOPES = tuple(
    permission.scope for permission in AGENT_PERMISSION_CATALOG if permission.category == "Read"
)
_KNOWN_AGENT_SCOPES = frozenset(permission.scope for permission in AGENT_PERMISSION_CATALOG)
AGENT_MUTATION_SCOPES = tuple(permission.scope for permission in AGENT_PERMISSION_CATALOG if permission.approval_key)
FULL_AGENT_CONTROL_SCOPES = tuple(permission.scope for permission in AGENT_PERMISSION_CATALOG)
_APPROVAL_KEY_BY_SCOPE = {
    permission.scope: permission.approval_key for permission in AGENT_PERMISSION_CATALOG if permission.approval_key
}


def normalize_agent_scopes(scopes):
    if not scopes or any(not isinstance(scope, str) or not scope.strip() for scope in scopes):
        raise ValueError("MCP agent permissions must contain at least one known scope")
    normalized = tuple(sorted({scope.strip() for scope in scopes}))
    if set(normalized) - _KNOWN_AGENT_SCOPES:
        raise ValueError("MCP agent permissions contain an unknown or non-grantable scope")
    return normalized


def normalize_auto_approved_scopes(scopes):
    normalized = tuple(sorted({scope.strip() for scope in scopes}))
    if any(scope not in _APPROVAL_KEY_BY_SCOPE for scope in normalized):
        raise ValueError("MCP agent auto-approval is only available for plan-bound actions")
    return normalized


def approval_policy_for_agent(base_policy, *, auto_approved_scopes):
    policy = dict(base_policy)
    selected_scopes = set(auto_approved_scopes)
    for scope, approval_key in _APPROVAL_KEY_BY_SCOPE.items():
        policy[approval_key] = "AUTO" if scope in selected_scopes else "OPERATOR_CONFIRMATION"
    return policy


def permission_catalog_payload():
    return [permission.public() for permission in AGENT_PERMISSION_CATALOG]
