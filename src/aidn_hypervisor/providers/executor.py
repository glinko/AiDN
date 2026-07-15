from copy import deepcopy
from typing import Protocol

from aidn_hypervisor.providers.models import (
    InstallationPlan,
    ProviderInstallationApproval,
    ProviderInstallationExecutionResult,
    ProviderInstallationStepResult,
)


class ProviderInstallationExecutor(Protocol):
    executor_id: str

    def apply(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
        provider_instance_id: str,
    ) -> ProviderInstallationExecutionResult:
        ...


class RecordedProviderInstallationExecutor:
    executor_id = "recorded-declarative-v1"

    _PLAN_SECTIONS = (
        "containers",
        "processes",
        "model_downloads",
        "volumes",
        "networks",
        "environment",
        "resource_limits",
        "health_checks",
    )

    def apply(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
        provider_instance_id: str,
    ) -> ProviderInstallationExecutionResult:
        step_results = [
            ProviderInstallationStepResult(
                step_id=f"record-{section.replace('_', '-')}",
                step_type=section,
                status="RECORDED",
                summary=f"Recorded declarative {section.replace('_', ' ')} plan section",
                details={"declaration": deepcopy(value)},
            )
            for section in self._PLAN_SECTIONS
            if (value := getattr(plan, section))
        ]

        return ProviderInstallationExecutionResult(
            step_results=step_results,
            provider_instance={
                "provider_instance_id": provider_instance_id,
                "plugin_id": approval.plugin_id,
                "provider_family": self._provider_family(manifest=manifest, plan=plan),
                "display_name": self._display_name(manifest=manifest, configuration=configuration),
                "connection_mode": "managed",
                "configuration": deepcopy(configuration),
                "operational_state": "ready",
            },
        )

    def _provider_family(self, *, manifest: dict, plan: InstallationPlan) -> str:
        provider_families = manifest.get("provider_families")
        if isinstance(provider_families, list) and provider_families:
            return str(provider_families[0])
        return plan.plugin_id

    def _display_name(self, *, manifest: dict, configuration: dict) -> str:
        display_name = configuration.get("display_name") or manifest.get("display_name")
        return str(display_name or "Managed Provider")
