from aidn_hypervisor.providers.models import (
    ModelDeployment,
    ProviderInstance,
    RuntimeBinding,
)


class InMemoryProviderInventoryStore:
    def __init__(self) -> None:
        self._provider_instances: dict[str, ProviderInstance] = {}
        self._model_deployments: dict[str, ModelDeployment] = {}
        self._runtime_bindings: dict[str, RuntimeBinding] = {}

    def save_provider_instance(self, instance: ProviderInstance) -> None:
        self._provider_instances[instance.provider_instance_id] = instance

    def get_provider_instance(self, provider_instance_id: str) -> ProviderInstance:
        return self._provider_instances[provider_instance_id]

    def list_provider_instances(self) -> list[ProviderInstance]:
        return list(self._provider_instances.values())

    def save_model_deployment(self, deployment: ModelDeployment) -> None:
        self._model_deployments[deployment.model_deployment_id] = deployment

    def list_model_deployments(self, provider_instance_id: str | None = None) -> list[ModelDeployment]:
        items = list(self._model_deployments.values())
        if provider_instance_id is None:
            return items
        return [item for item in items if item.provider_instance_id == provider_instance_id]

    def save_runtime_binding(self, binding: RuntimeBinding) -> None:
        self._runtime_bindings[binding.runtime_binding_id] = binding

    def get_runtime_binding(self, runtime_binding_id: str) -> RuntimeBinding:
        return self._runtime_bindings[runtime_binding_id]

    def list_runtime_bindings(self) -> list[RuntimeBinding]:
        return list(self._runtime_bindings.values())
