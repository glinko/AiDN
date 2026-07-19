"""Install-scoped identity checks for a future isolated Provider Plugin Host."""

from collections.abc import Callable

from pydantic import BaseModel, Field

from aidn_hypervisor.providers.models import InstalledPlugin


class PluginHostAuthenticationError(ValueError):
    """Raised when a Plugin Host identity is no longer authorized locally."""


class PluginHostIdentity(BaseModel):
    installed_plugin_id: str = Field(min_length=1)
    plugin_id: str = Field(min_length=1)
    installation_generation: int = Field(ge=1)
    activation_credential_key_id: str = Field(min_length=1)


class PluginHostAuthenticator:
    """Authorize one Host identity against immutable installed-plugin state."""

    def __init__(self, installed_plugin_resolver: Callable[[str], InstalledPlugin]) -> None:
        self.installed_plugin_resolver = installed_plugin_resolver

    def authenticate(self, identity: PluginHostIdentity) -> InstalledPlugin:
        try:
            installed = self.installed_plugin_resolver(identity.installed_plugin_id)
        except KeyError as exc:
            raise PluginHostAuthenticationError("installed plugin is not known") from exc
        if installed.state not in {"INSTALLED", "ACTIVE"}:
            raise PluginHostAuthenticationError("installed plugin is not host-authorized")
        if installed.plugin_id != identity.plugin_id:
            raise PluginHostAuthenticationError("Plugin Host plugin identity does not match installation")
        if installed.installation_generation != identity.installation_generation:
            raise PluginHostAuthenticationError("Plugin Host installation generation is stale")
        if installed.activation_credential_key_id != identity.activation_credential_key_id:
            raise PluginHostAuthenticationError("Plugin Host activation credential is invalid")
        return installed
