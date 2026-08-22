from importlib import import_module as I
from aidn_hypervisor.mcp.permissions_catalog_core import McpAgentPermission
R=[]
for i in range(1,8): R += I("aidn_hypervisor.mcp.permission_rows_"+str(i)).ROWS
def make(x):
 s,c,r,t,a=x; return McpAgentPermission(s,s.replace(":"," ").title(),"permission",c,r,tuple(t.split()),a)
AGENT_PERMISSION_CATALOG=tuple(make(x) for x in R)
DEFAULT_AGENT_READ_SCOPES=tuple(x.scope for x in AGENT_PERMISSION_CATALOG if x.category=="Read")
_KNOWN_AGENT_SCOPES=frozenset(x.scope for x in AGENT_PERMISSION_CATALOG)
AGENT_MUTATION_SCOPES=tuple(x.scope for x in AGENT_PERMISSION_CATALOG if x.approval_key)
FULL_AGENT_CONTROL_SCOPES=tuple(x.scope for x in AGENT_PERMISSION_CATALOG)
_APPROVAL_KEY_BY_SCOPE={x.scope:x.approval_key for x in AGENT_PERMISSION_CATALOG if x.approval_key}
def normalize_agent_scopes(scopes):
 if not scopes or any(not isinstance(s,str) or not s.strip() for s in scopes): raise ValueError("MCP agent permissions must contain at least one known scope")
 out=tuple(sorted({s.strip() for s in scopes}))
 if set(out)-_KNOWN_AGENT_SCOPES: raise ValueError("MCP agent permissions contain an unknown or non-grantable scope")
 return out
def normalize_auto_approved_scopes(scopes):
 out=tuple(sorted({s.strip() for s in scopes}))
 if any(s not in _APPROVAL_KEY_BY_SCOPE for s in out): raise ValueError("MCP agent auto-approval is only available for plan-bound actions")
 return out
def approval_policy_for_agent(base_policy, *, auto_approved_scopes):
 out=dict(base_policy); selected=set(auto_approved_scopes)
 for scope,key in _APPROVAL_KEY_BY_SCOPE.items(): out[key]="AUTO" if scope in selected else "OPERATOR_CONFIRMATION"
 return out
def permission_catalog_payload(): return [x.public() for x in AGENT_PERMISSION_CATALOG]
