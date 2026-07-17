from copy import deepcopy
from typing import Protocol

from aidn_hypervisor.providers.models import (
    InstallationPlan,
    ProviderInstallationApproval,
    ProviderInstallationRollbackResult,
    ProviderInstallationExecutionResult,
    ProviderInstallationStepResult,
)


class ProviderInstallationExecutor(Protocol):
    executor_id: str

    def rollback_preview(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> ProviderInstallationRollbackResult:
        ...

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

    def rollback_preview(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> ProviderInstallationRollbackResult:
        self._validate_inputs(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
        )
        return ProviderInstallationRollbackResult(
            status="NOT_REQUIRED",
            summary="Recorded executor does not mutate host state; rollback is not required.",
            details={
                "executor_id": self.executor_id,
                "host_mutation": False,
                "recorded_plan_sections": [
                    section for section in self._PLAN_SECTIONS if getattr(plan, section)
                ],
            },
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
        self._validate_inputs(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
        )
        approved_configuration = approval.configuration
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
                "display_name": self._display_name(manifest=manifest, configuration=approved_configuration),
                "connection_mode": "managed",
                "configuration": deepcopy(approved_configuration),
                "operational_state": "created",
            },
            rollback_result=self.rollback_preview(
                approval=approval,
                plan=plan,
                configuration=configuration,
                manifest=manifest,
            ),
        )

    def _validate_inputs(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> None:
        if approval.status != "APPROVED":
            raise ValueError("provider installation approval must be approved")
        if approval.plugin_id != plan.plugin_id:
            raise ValueError("provider installation approval plugin does not match plan plugin")
        if approval.plan_id != plan.plan_id:
            raise ValueError("provider installation approval plan does not match installation plan")
        manifest_plugin_id = manifest.get("plugin_id")
        if manifest_plugin_id is not None and manifest_plugin_id != approval.plugin_id:
            raise ValueError("provider installation manifest plugin does not match approval plugin")
        if configuration != approval.configuration:
            raise ValueError("provider installation configuration does not match approved configuration")

    def _provider_family(self, *, manifest: dict, plan: InstallationPlan) -> str:
        provider_families = manifest.get("provider_families")
        if isinstance(provider_families, list) and provider_families:
            return str(provider_families[0])
        return plan.plugin_id

    def _display_name(self, *, manifest: dict, configuration: dict) -> str:
        display_name = configuration.get("display_name") or manifest.get("display_name")
        return str(display_name or "Managed Provider")
