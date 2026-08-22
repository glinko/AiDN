"""Permission model."""
from dataclasses import asdict, dataclass
@dataclass(frozen=True)
class McpAgentPermission:
    scope: str
    label: str
    description: str
    category: str
    risk: str
    tool_names: tuple[str, ...]
    approval_key: str | None = None
    def public(self):
        return asdict(self)
