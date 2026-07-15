from aidn_hypervisor.providers.models import (
    ModelDeployment,
    ProviderInstallationApproval,
    ProviderInstallationJob,
    ProviderInstance,
    RuntimeBinding,
)


class InMemoryProviderInventoryStore:
    def __init__(self) -> None:
        self._provider_instances: dict[str, ProviderInstance] = {}
        self._model_deployments: dict[str, ModelDeployment] = {}
        self._runtime_bindings: dict[str, RuntimeBinding] = {}
        self._installation_approvals: dict[str, ProviderInstallationApproval] = {}
        self._installation_jobs: dict[str, ProviderInstallationJob] = {}

    def save_provider_instance(self, instance: ProviderInstance) -> None:
        current = self._provider_instances.get(instance.provider_instance_id)
        if current is not None and current.plugin_id != instance.plugin_id:
            raise ValueError("plugin_id is immutable once provider_instance_id exists")
        self._provider_instances[instance.provider_instance_id] = instance.model_copy(deep=True)

    def get_provider_instance(self, provider_instance_id: str) -> ProviderInstance:
        return self._provider_instances[provider_instance_id].model_copy(deep=True)

    def list_provider_instances(self) -> list[ProviderInstance]:
        return [item.model_copy(deep=True) for item in self._provider_instances.values()]

    def delete_provider_instance(self, provider_instance_id: str) -> None:
        removed_deployment_ids = {
            deployment.model_deployment_id
            for deployment in self._model_deployments.values()
            if deployment.provider_instance_id == provider_instance_id
        }
        self._model_deployments = {
            deployment_id: deployment
            for deployment_id, deployment in self._model_deployments.items()
            if deployment.provider_instance_id != provider_instance_id
        }
        self._runtime_bindings = {
            binding_id: binding
            for binding_id, binding in self._runtime_bindings.items()
            if binding.provider_instance_id != provider_instance_id
            and binding.model_deployment_id not in removed_deployment_ids
        }
        del self._provider_instances[provider_instance_id]

    def save_model_deployment(self, deployment: ModelDeployment) -> None:
        if deployment.provider_instance_id not in self._provider_instances:
            raise ValueError("provider_instance_id must reference an existing provider instance")
        current = self._model_deployments.get(deployment.model_deployment_id)
        if current is not None and current.provider_instance_id != deployment.provider_instance_id:
            raise ValueError("provider_instance_id is immutable once model_deployment_id exists")
        self._model_deployments[deployment.model_deployment_id] = deployment.model_copy(deep=True)

    def get_model_deployment(self, model_deployment_id: str) -> ModelDeployment:
        return self._model_deployments[model_deployment_id].model_copy(deep=True)

    def list_model_deployments(self, provider_instance_id: str | None = None) -> list[ModelDeployment]:
        items = list(self._model_deployments.values())
        if provider_instance_id is None:
            return [item.model_copy(deep=True) for item in items]
        return [
            item.model_copy(deep=True)
            for item in items
            if item.provider_instance_id == provider_instance_id
        ]

    def delete_model_deployment(self, model_deployment_id: str) -> None:
        del self._model_deployments[model_deployment_id]
        self._runtime_bindings = {
            binding_id: binding
            for binding_id, binding in self._runtime_bindings.items()
            if binding.model_deployment_id != model_deployment_id
        }

    def save_runtime_binding(self, binding: RuntimeBinding) -> None:
        current = self._runtime_bindings.get(binding.runtime_binding_id)
        if current is not None and (
            current.provider_instance_id != binding.provider_instance_id
            or current.model_deployment_id != binding.model_deployment_id
            or current.plugin_id != binding.plugin_id
        ):
            raise ValueError("runtime binding ownership fields are immutable; delete and recreate instead")
        if binding.provider_instance_id not in self._provider_instances:
            raise ValueError("provider_instance_id must reference an existing provider instance")
        provider_instance = self._provider_instances[binding.provider_instance_id]
        if binding.model_deployment_id not in self._model_deployments:
            raise ValueError("model_deployment_id must reference an existing model deployment")
        deployment = self._model_deployments[binding.model_deployment_id]
        if deployment.provider_instance_id != binding.provider_instance_id:
            raise ValueError(
                "runtime binding provider_instance_id must match the model deployment provider_instance_id"
            )
        if binding.plugin_id != provider_instance.plugin_id:
            raise ValueError("plugin_id must match the owning provider instance plugin_id")
        self._runtime_bindings[binding.runtime_binding_id] = binding.model_copy(deep=True)

    def get_runtime_binding(self, runtime_binding_id: str) -> RuntimeBinding:
        return self._runtime_bindings[runtime_binding_id].model_copy(deep=True)

    def list_runtime_bindings(self) -> list[RuntimeBinding]:
        return [item.model_copy(deep=True) for item in self._runtime_bindings.values()]

    def delete_runtime_binding(self, runtime_binding_id: str) -> None:
        del self._runtime_bindings[runtime_binding_id]

    def save_installation_approval(
        self, approval: ProviderInstallationApproval
    ) -> ProviderInstallationApproval:
        stored = approval.model_copy(deep=True)
        self._installation_approvals[approval.approval_id] = stored
        return stored.model_copy(deep=True)

    def get_installation_approval(self, approval_id: str) -> ProviderInstallationApproval:
        return self._installation_approvals[approval_id].model_copy(deep=True)

    def list_installation_approvals(self) -> list[ProviderInstallationApproval]:
        return [item.model_copy(deep=True) for item in self._installation_approvals.values()]

    def save_installation_job(self, job: ProviderInstallationJob) -> ProviderInstallationJob:
        stored = job.model_copy(deep=True)
        self._installation_jobs[job.job_id] = stored
        return stored.model_copy(deep=True)

    def get_installation_job(self, job_id: str) -> ProviderInstallationJob:
        return self._installation_jobs[job_id].model_copy(deep=True)

    def list_installation_jobs(self) -> list[ProviderInstallationJob]:
        return [item.model_copy(deep=True) for item in self._installation_jobs.values()]
