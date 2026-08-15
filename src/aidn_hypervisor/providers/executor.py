import hashlib
import ipaddress
import json
import os
import shutil
import stat
import tarfile
import zipfile
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from aidn_hypervisor.providers.models import (
    ExecutorSandboxCapabilities,
    InstallationPlan,
    ModelArtifact,
    ModelArtifactGarbageCollectionResult,
    ModelArtifactInventory,
    ModelArtifactSet,
    ModelArtifactSetFile,
    ProviderArtifactMaterialization,
    ProviderInstallationApproval,
    ProviderInstallationArchiveExtractionResult,
    ProviderInstallationArtifact,
    ProviderInstallationArtifactInventory,
    ProviderInstallationDiagnosticCheck,
    ProviderInstallationExecutionResult,
    ProviderInstallationRollbackResult,
    ProviderInstallationStepResult,
    ProviderRuntimeBrokerResult,
    ProviderRuntimeInstallerDescriptor,
    ProviderRuntimeInvocation,
)


class ProviderRuntimeBroker(Protocol):
    """Narrow local boundary for an allowlisted Ubuntu runtime action."""

    def invoke(self, *, invocation: ProviderRuntimeInvocation) -> ProviderRuntimeBrokerResult:
        ...


class ProviderInstallationExecutor(Protocol):
    executor_id: str

    def sandbox_capabilities(self) -> ExecutorSandboxCapabilities:
        ...

    def installation_artifact_inventory(self) -> ProviderInstallationArtifactInventory:
        ...

    def stage_local_artifact(
        self,
        *,
        relative_path: str,
        content_bytes: bytes,
    ) -> ProviderInstallationArtifact:
        ...

    def delete_local_artifact(self, *, relative_path: str) -> None:
        ...

    def extract_local_artifact_archive(
        self,
        *,
        archive_relative_path: str,
        destination_directory: str,
    ) -> ProviderInstallationArchiveExtractionResult:
        ...

    def model_artifact_inventory(self) -> ModelArtifactInventory:
        ...

    def promote_local_artifact_to_model_store(
        self,
        *,
        relative_path: str,
    ) -> ModelArtifact:
        ...

    def delete_model_artifact(self, *, artifact_id: str) -> None:
        ...

    def create_model_artifact_set(
        self,
        *,
        display_name: str,
        files: list[dict],
    ) -> ModelArtifactSet:
        ...

    def list_model_artifact_sets(self) -> list[ModelArtifactSet]:
        ...

    def get_model_artifact_set(self, artifact_set_id: str) -> ModelArtifactSet:
        ...

    def delete_model_artifact_set(self, *, artifact_set_id: str) -> None:
        ...

    def collect_model_artifact_garbage(self) -> ModelArtifactGarbageCollectionResult:
        ...

    def materialize_model_artifact_set(
        self, *, provider_instance_id: str, artifact_set_id: str, destination: str
    ) -> ProviderArtifactMaterialization:
        ...

    def diagnostic_checks(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> list[ProviderInstallationDiagnosticCheck]:
        ...

    def rollback_preview(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> ProviderInstallationRollbackResult:
        ...

    def rollback(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
        provider_instance_id: str | None,
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

    def sandbox_capabilities(self) -> ExecutorSandboxCapabilities:
        return ExecutorSandboxCapabilities(
            supported_execution_modes=["RECORDED_ONLY"],
            supported_filesystem_scopes=["NONE"],
            supported_network_scopes=["NONE"],
            supported_secret_scopes=["DECLARED_HANDLES_ONLY"],
            host_mutation=False,
            notes=(
                "Recorded executor accepts preview-only plans and records declarative "
                "state without mutating the host."
            ),
        )

    def diagnostic_checks(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> list[ProviderInstallationDiagnosticCheck]:
        self._validate_inputs(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
        )
        return []

    def installation_artifact_inventory(self) -> ProviderInstallationArtifactInventory:
        return ProviderInstallationArtifactInventory(supported=False)

    def stage_local_artifact(
        self,
        *,
        relative_path: str,
        content_bytes: bytes,
    ) -> ProviderInstallationArtifact:
        raise ValueError(
            "current installation executor does not support local artifact staging"
        )

    def delete_local_artifact(self, *, relative_path: str) -> None:
        raise ValueError(
            "current installation executor does not support local artifact deletion"
        )

    def extract_local_artifact_archive(
        self,
        *,
        archive_relative_path: str,
        destination_directory: str,
    ) -> ProviderInstallationArchiveExtractionResult:
        raise ValueError(
            "current installation executor does not support local artifact archive extraction"
        )

    def model_artifact_inventory(self) -> ModelArtifactInventory:
        return ModelArtifactInventory(supported=False)

    def promote_local_artifact_to_model_store(
        self,
        *,
        relative_path: str,
    ) -> ModelArtifact:
        raise ValueError(
            "current installation executor does not support model artifact storage"
        )

    def delete_model_artifact(self, *, artifact_id: str) -> None:
        raise ValueError(
            "current installation executor does not support model artifact storage"
        )

    def create_model_artifact_set(
        self,
        *,
        display_name: str,
        files: list[dict],
    ) -> ModelArtifactSet:
        raise ValueError(
            "current installation executor does not support model artifact storage"
        )

    def list_model_artifact_sets(self) -> list[ModelArtifactSet]:
        return []

    def get_model_artifact_set(self, artifact_set_id: str) -> ModelArtifactSet:
        raise KeyError(artifact_set_id)

    def delete_model_artifact_set(self, *, artifact_set_id: str) -> None:
        raise ValueError(
            "current installation executor does not support model artifact storage"
        )

    def collect_model_artifact_garbage(self) -> ModelArtifactGarbageCollectionResult:
        raise ValueError(
            "current installation executor does not support model artifact storage"
        )

    def materialize_model_artifact_set(
        self, *, provider_instance_id: str, artifact_set_id: str, destination: str
    ) -> ProviderArtifactMaterialization:
        raise ValueError(
            "current installation executor does not support model artifact materialization"
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

    def rollback(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
        provider_instance_id: str | None,
    ) -> ProviderInstallationRollbackResult:
        preview = self.rollback_preview(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
        )
        if provider_instance_id is None:
            return preview.model_copy(
                update={
                    "status": "NOT_NEEDED",
                    "summary": (
                        "Recorded executor has no host mutation to revert and no local "
                        "provider inventory cleanup was required."
                    ),
                    "details": {
                        **deepcopy(preview.details),
                        "provider_instance_id": None,
                    },
                }
            )
        return preview.model_copy(
            update={
                "status": "COMPLETED",
                "summary": (
                    "Recorded executor confirmed no host mutation and prepared local "
                    "provider inventory cleanup."
                ),
                "details": {
                    **deepcopy(preview.details),
                    "provider_instance_id": provider_instance_id,
                },
                "step_results": [
                    ProviderInstallationStepResult(
                        step_id="rollback-recorded-local-inventory",
                        step_type="rollback_local_inventory",
                        status="RECORDED",
                        summary=(
                            "Recorded executor prepared local provider inventory cleanup."
                        ),
                        details={
                            "provider_instance_id": provider_instance_id,
                            "host_mutation": False,
                        },
                    )
                ],
            }
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


class AllowlistedProviderRuntimeInstallationExecutor(RecordedProviderInstallationExecutor):
    """Validate and dispatch reviewed runtime actions through an injected broker.

    The class intentionally has no default broker. Constructing it requires an
    implementation of the narrow local broker boundary, so the normal service
    path cannot accidentally gain subprocess or shell execution.
    """

    executor_id = "allowlisted-provider-runtime-v1"

    def __init__(self, broker: ProviderRuntimeBroker) -> None:
        self._broker = broker

    def sandbox_capabilities(self) -> ExecutorSandboxCapabilities:
        return ExecutorSandboxCapabilities(
            supported_execution_modes=["RECORDED_ONLY", "UNSANDBOXED_HOST"],
            supported_filesystem_scopes=["NONE", "CONTROLLED_PATHS"],
            supported_network_scopes=["NONE", "PRIVATE_ONLY", "DECLARED_EGRESS"],
            supported_secret_scopes=["NONE", "DECLARED_HANDLES_ONLY"],
            host_mutation=True,
            notes=(
                "Runtime actions are accepted only through a typed allowlist and an "
                "injected local broker; no generic command runner is exposed."
            ),
        )

    def diagnostic_checks(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> list[ProviderInstallationDiagnosticCheck]:
        invocation = self.build_invocation(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
            action="install",
        )
        return [
            ProviderInstallationDiagnosticCheck(
                check_id="runtime_invocation",
                status="PASS",
                summary="Reviewed runtime invocation is accepted by the allowlist.",
                details={"invocation": invocation.model_dump(mode="json")},
            )
        ]

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
        invocation = self.build_invocation(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
            action="stop",
        )
        return ProviderInstallationRollbackResult(
            status="PENDING",
            summary=(
                "Runtime rollback requires an explicit broker cleanup policy; "
                "installation removal is not inferred from stop."
            ),
            details={"invocation": invocation.model_dump(mode="json")},
        )

    def rollback(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
        provider_instance_id: str | None,
    ) -> ProviderInstallationRollbackResult:
        preview = self.rollback_preview(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
        )
        return preview.model_copy(
            update={
                "details": {
                    **deepcopy(preview.details),
                    "provider_instance_id": provider_instance_id,
                }
            }
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
        invocation = self.build_invocation(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
            action="install",
        )
        broker_result = self._broker.invoke(invocation=invocation)
        if broker_result.status != "SUCCEEDED":
            broker_details = broker_result.details if isinstance(broker_result.details, dict) else {}
            returncode = broker_details.get("returncode")
            stderr = broker_details.get("stderr")
            diagnostic = ""
            if returncode is not None or stderr:
                diagnostic = f" (returncode={returncode!r}"
                if stderr:
                    diagnostic += f"; stderr={str(stderr)[:1024]}"
                diagnostic += ")"
            raise ValueError(
                "Provider runtime broker did not complete installation: "
                f"{broker_result.summary}{diagnostic}"
            )
        result = super().apply(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
            provider_instance_id=provider_instance_id,
        )
        runtime_step = ProviderInstallationStepResult(
            step_id="runtime-broker-install",
            step_type="provider_runtime_install",
            status="RECORDED",
            summary=broker_result.summary,
            details={
                "invocation": invocation.model_dump(mode="json"),
                "broker": broker_result.model_dump(mode="json"),
            },
        )
        return result.model_copy(update={"step_results": [runtime_step, *result.step_results]})

    def run_runtime_action(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
        action: str,
    ) -> ProviderRuntimeBrokerResult:
        """Run one reviewed lifecycle action through the typed broker.

        Installations use ``apply`` because they also materialize local
        inventory.  Change/remove operations need the same reviewed broker
        boundary without creating a second ProviderInstance.
        """

        invocation = self.build_invocation(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
            action=action,
        )
        broker_result = self._broker.invoke(invocation=invocation)
        if broker_result.status != "SUCCEEDED":
            broker_details = broker_result.details if isinstance(broker_result.details, dict) else {}
            returncode = broker_details.get("returncode")
            stderr = broker_details.get("stderr")
            diagnostic = f" (returncode={returncode!r}"
            if stderr:
                diagnostic += f"; stderr={str(stderr)[:1024]}"
            diagnostic += ")" if returncode is not None or stderr else ""
            raise ValueError(
                f"Provider runtime {action} failed: {broker_result.summary}{diagnostic}"
            )
        return broker_result

    def build_invocation(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
        action: str,
    ) -> ProviderRuntimeInvocation:
        self._validate_inputs(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
        )
        if action not in {"install", "start", "status", "stop", "remove"}:
            raise ValueError("unsupported Provider runtime action")
        descriptors = manifest.get("runtime_installers")
        if not isinstance(descriptors, list):
            raise ValueError("Provider manifest does not declare runtime installers")
        descriptor = next(
            (
                item
                for item in descriptors
                if isinstance(item, dict)
                and item.get("installer_id") == "aidn-provider-runtime-ubuntu.v1"
                and item.get("provider") == approval.plugin_id
            ),
            None,
        )
        if descriptor is None:
            raise ValueError("Provider manifest has no matching reviewed runtime installer")
        runtime = ProviderRuntimeInstallerDescriptor.model_validate(descriptor)
        if action not in runtime.actions:
            raise ValueError(f"runtime installer does not support action: {action}")

        arguments: dict[str, str] = {}
        if action == "install":
            if runtime.provider == "whisper":
                arguments["image"] = runtime.pinned_version
            elif runtime.provider == "ollama":
                arguments["version"] = runtime.pinned_version
            elif runtime.provider == "llama.cpp":
                arguments["ref"] = runtime.pinned_version
                arguments["backend"] = str(configuration.get("backend") or "cpu")
                if arguments["backend"] not in {"cpu", "cuda"}:
                    raise ValueError("llama.cpp runtime backend is not reviewed")
            elif runtime.provider == "vllm":
                arguments["version"] = runtime.pinned_version
                arguments["python"] = str(configuration.get("python_version") or "3.12")
                if arguments["python"] != "3.12":
                    raise ValueError("vLLM Python version is not reviewed")
                if str(configuration.get("backend") or "cuda") != "cuda":
                    raise ValueError("managed vLLM runtime requires the reviewed CUDA backend")

        configured_version = configuration.get("runtime_version") or configuration.get("runtime_ref")
        if configured_version is not None and str(configured_version) != runtime.pinned_version:
            raise ValueError("Provider configuration runtime version does not match reviewed pin")
        return ProviderRuntimeInvocation(
            approval_id=approval.approval_id,
            plan_hash=approval.plan_hash,
            configuration_hash=approval.configuration_hash,
            installer_id=runtime.installer_id,
            provider=runtime.provider,
            action=action,
            pinned_version=runtime.pinned_version,
            arguments=arguments,
        )


class SandboxEnforcedProviderInstallationExecutor(RecordedProviderInstallationExecutor):
    executor_id = "sandbox-enforced-declarative-v1"

    _DISALLOWED_NON_EMPTY_SECTIONS = (
        "containers",
        "processes",
        "model_downloads",
        "volumes",
        "environment",
    )
    _MAX_NETWORK_DECLARATIONS = 4
    _MAX_HEALTH_CHECKS = 4
    _MAX_RESOURCE_LIMIT_KEYS = 16
    _ALLOWED_NETWORK_SCOPES = {"local", "private"}
    _ALLOWED_NETWORK_KEYS = {"name", "scope", "notes"}
    _ALLOWED_HEALTH_CHECK_TYPES = {"http"}
    _ALLOWED_HEALTH_CHECK_METHODS = {"GET", "HEAD"}
    _ALLOWED_HEALTH_CHECK_KEYS = {
        "type",
        "url",
        "timeout_seconds",
        "interval_seconds",
        "method",
        "expected_status",
    }
    _MAX_HEALTH_CHECK_TIMEOUT_SECONDS = 30

    def sandbox_capabilities(self) -> ExecutorSandboxCapabilities:
        return ExecutorSandboxCapabilities(
            supported_execution_modes=["RECORDED_ONLY", "SANDBOX_REQUIRED"],
            supported_filesystem_scopes=["NONE", "CONTROLLED_PATHS"],
            supported_network_scopes=["NONE", "PRIVATE_ONLY", "DECLARED_EGRESS"],
            supported_secret_scopes=["DECLARED_HANDLES_ONLY"],
            host_mutation=False,
            notes=(
                "Sandbox-enforced executor validates declarative plans against a "
                "bounded non-host-mutating execution surface before recording state."
            ),
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
        enforcement_details = self._enforce_plan_boundary(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
        )
        result = super().apply(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
            provider_instance_id=provider_instance_id,
        )
        return result.model_copy(
            update={
                "step_results": [
                    ProviderInstallationStepResult(
                        step_id="sandbox-enforce-boundary",
                        step_type="sandbox_boundary",
                        status="RECORDED",
                        summary=(
                            "Validated declarative plan against sandbox executor boundary."
                        ),
                        details=enforcement_details,
                    ),
                    *result.step_results,
                ]
            }
        )

    def _enforce_plan_boundary(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> dict:
        self._validate_inputs(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
        )
        for section in self._DISALLOWED_NON_EMPTY_SECTIONS:
            if getattr(plan, section):
                raise ValueError(
                    "sandbox executor does not permit non-empty declarative section: "
                    f"{section}"
                )
        if len(plan.networks) > self._MAX_NETWORK_DECLARATIONS:
            raise ValueError(
                "sandbox executor does not permit more than "
                f"{self._MAX_NETWORK_DECLARATIONS} network declarations"
            )
        invalid_network_scopes = [
            network.get("scope")
            for network in plan.networks
            if str(network.get("scope") or "").strip() not in self._ALLOWED_NETWORK_SCOPES
        ]
        if invalid_network_scopes:
            raise ValueError(
                "sandbox executor does not permit network scope: "
                f"{invalid_network_scopes[0]}"
            )
        validated_network_names: list[str] = []
        for network in plan.networks:
            unexpected_network_keys = sorted(
                key for key in network if key not in self._ALLOWED_NETWORK_KEYS
            )
            if unexpected_network_keys:
                raise ValueError(
                    "sandbox executor does not permit network declaration keys outside "
                    f"the bounded subset: {unexpected_network_keys[0]}"
                )
            network_name = str(network.get("name") or "").strip()
            if not network_name:
                raise ValueError(
                    "sandbox executor requires every network declaration to have a name"
                )
            validated_network_names.append(network_name)

        approved_base_host = self._host_from_url(configuration.get("base_url"))
        validated_health_hosts: list[str] = []
        if len(plan.health_checks) > self._MAX_HEALTH_CHECKS:
            raise ValueError(
                "sandbox executor does not permit more than "
                f"{self._MAX_HEALTH_CHECKS} health checks"
            )
        for check in plan.health_checks:
            unexpected_health_check_keys = sorted(
                key for key in check if key not in self._ALLOWED_HEALTH_CHECK_KEYS
            )
            if unexpected_health_check_keys:
                raise ValueError(
                    "sandbox executor does not permit health check keys outside the "
                    f"bounded subset: {unexpected_health_check_keys[0]}"
                )
            check_type = str(check.get("type") or "").strip().lower()
            if check_type not in self._ALLOWED_HEALTH_CHECK_TYPES:
                raise ValueError(
                    "sandbox executor does not permit health check type: "
                    f"{check_type or 'unknown'}"
                )
            url = str(check.get("url") or "").strip()
            parsed_url = urlparse(url)
            if parsed_url.scheme.lower() != "http":
                raise ValueError(
                    "sandbox executor does not permit health check URL scheme outside "
                    "the bounded subset: "
                    f"{parsed_url.scheme or 'unknown'}"
                )
            if parsed_url.username or parsed_url.password:
                raise ValueError(
                    "sandbox executor does not permit embedded health check credentials"
                )
            if parsed_url.query or parsed_url.fragment:
                raise ValueError(
                    "sandbox executor does not permit health check query or fragment parameters"
                )
            method = str(check.get("method") or "GET").strip().upper()
            if method not in self._ALLOWED_HEALTH_CHECK_METHODS:
                raise ValueError(
                    "sandbox executor does not permit health check method outside the "
                    f"bounded subset: {method}"
                )
            expected_status = check.get("expected_status")
            if (
                expected_status is not None
                and (not isinstance(expected_status, int) or not (200 <= expected_status <= 399))
            ):
                    raise ValueError(
                        "sandbox executor requires expected health check status to be an integer "
                        "between 200 and 399"
                    )
            interval_seconds = check.get("interval_seconds")
            if interval_seconds is not None and float(interval_seconds) <= 0:
                raise ValueError(
                    "sandbox executor requires positive health check interval seconds"
                )
            host = parsed_url.hostname
            if not host:
                raise ValueError("sandbox executor requires health check URLs with a host")
            if not self._is_allowed_health_host(host, approved_base_host):
                raise ValueError(
                    "sandbox executor does not permit health check host outside the "
                    f"approved boundary: {host}"
                )
            timeout_seconds = check.get("timeout_seconds")
            if timeout_seconds is not None and float(timeout_seconds) > self._MAX_HEALTH_CHECK_TIMEOUT_SECONDS:
                raise ValueError(
                    "sandbox executor does not permit health check timeout above "
                    f"{self._MAX_HEALTH_CHECK_TIMEOUT_SECONDS} seconds"
                )
            if timeout_seconds is not None and float(timeout_seconds) <= 0:
                raise ValueError(
                    "sandbox executor requires positive health check timeout seconds"
                )
            validated_health_hosts.append(host)

        if len(plan.resource_limits) > self._MAX_RESOURCE_LIMIT_KEYS:
            raise ValueError(
                "sandbox executor does not permit more than "
                f"{self._MAX_RESOURCE_LIMIT_KEYS} resource limit keys"
            )
        for key, value in plan.resource_limits.items():
            normalized_key = str(key).strip()
            if not normalized_key:
                raise ValueError("sandbox executor requires non-empty resource limit keys")
            if not isinstance(value, (str, int, float, bool)):
                raise ValueError(
                    "sandbox executor requires flat scalar resource limits: "
                    f"{key}"
                )
            if isinstance(value, str) and not value.strip():
                raise ValueError(
                    "sandbox executor requires non-empty scalar resource limit values: "
                    f"{key}"
                )
            if isinstance(value, (int, float)) and value < 0:
                raise ValueError(
                    "sandbox executor does not permit negative resource limits: "
                    f"{key}"
                )

        return {
            "executor_id": self.executor_id,
            "host_mutation": False,
            "validated_network_names": validated_network_names,
            "validated_network_scopes": [network.get("scope") for network in plan.networks],
            "validated_health_hosts": validated_health_hosts,
            "validated_resource_limit_keys": sorted(plan.resource_limits.keys()),
            "approved_base_host": approved_base_host,
        }

    def _host_from_url(self, value) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        parsed = urlparse(text)
        return parsed.hostname

    def _is_allowed_health_host(self, host: str, approved_base_host: str | None) -> bool:
        normalized_host = host.strip().lower()
        if approved_base_host and normalized_host == approved_base_host.lower():
            return True
        if normalized_host in {"localhost", "::1"}:
            return True
        try:
            address = ipaddress.ip_address(normalized_host)
        except ValueError:
            return False
        return address.is_loopback or address.is_private


class ControlledFilesystemProviderInstallationExecutor(
    SandboxEnforcedProviderInstallationExecutor
):
    executor_id = "controlled-filesystem-v1"
    _STATE_FILENAME = "provider-installation-state.json"
    _MAX_VOLUME_DECLARATIONS = 8
    _MAX_MODEL_DOWNLOAD_DECLARATIONS = 8
    _MAX_LOCAL_ARTIFACT_BYTES = 64 * 1024 * 1024
    _MAX_EXTRACTED_FILES = 256
    _MAX_EXTRACTED_BYTES = 512 * 1024 * 1024
    _MAX_EXTRACTED_MEMBER_BYTES = 128 * 1024 * 1024
    _SUPPORTED_ARCHIVE_FORMATS = ("zip", "tar", "tar.gz", "tgz")
    _MODEL_ARTIFACT_STORE_DIR = "model-artifacts"
    _MODEL_ARTIFACT_MATERIALIZATION_MODES = ("COPY", "HARDLINK_IF_READONLY")
    _ALLOWED_VOLUME_KEYS = {"name", "mount_path", "notes"}
    _ALLOWED_MODEL_DOWNLOAD_KEYS = {"model", "source", "destination", "notes"}

    def __init__(
        self,
        root_path: str | Path,
        *,
        model_artifact_gc_grace_seconds: int = 7 * 24 * 60 * 60,
        model_artifact_materialization_mode: str = "COPY",
    ) -> None:
        self.root_path = Path(root_path).resolve()
        self.model_artifact_gc_grace_seconds = max(
            0,
            int(model_artifact_gc_grace_seconds),
        )
        normalized_mode = str(model_artifact_materialization_mode or "").strip().upper()
        if normalized_mode not in self._MODEL_ARTIFACT_MATERIALIZATION_MODES:
            raise ValueError(
                "controlled filesystem executor requires a supported model artifact materialization mode"
            )
        self.model_artifact_materialization_mode = normalized_mode

    def sandbox_capabilities(self) -> ExecutorSandboxCapabilities:
        return ExecutorSandboxCapabilities(
            supported_execution_modes=["SANDBOX_REQUIRED"],
            supported_filesystem_scopes=["CONTROLLED_PATHS"],
            supported_network_scopes=["NONE", "PRIVATE_ONLY", "DECLARED_EGRESS"],
            supported_secret_scopes=["DECLARED_HANDLES_ONLY"],
            host_mutation=True,
            notes=(
                "Controlled filesystem executor writes and removes provider "
                "installation state only inside one configured root path."
            ),
        )

    def rollback_preview(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> ProviderInstallationRollbackResult:
        enforcement_details = self._enforce_controlled_filesystem_boundary(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
        )
        return ProviderInstallationRollbackResult(
            status="PENDING",
            summary=(
                "Controlled filesystem executor can remove installation state from "
                "the configured root path during rollback."
            ),
            details={
                **enforcement_details,
                "executor_id": self.executor_id,
                "host_mutation": True,
                "state_root": str(self.root_path),
            },
        )

    def diagnostic_checks(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> list[ProviderInstallationDiagnosticCheck]:
        self._enforce_controlled_filesystem_boundary(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
        )
        local_imports: list[dict] = []
        model_artifacts: list[dict] = []
        imports_root = self._imports_root().resolve()
        for download in plan.model_downloads:
            source = str(download.get("source") or "")
            if self._is_local_import_source(source):
                import_relative_path = self._local_import_relative_path(source)
                source_path = (imports_root / import_relative_path).resolve()
                destination_path = self._resolve_volume_destination(
                    volumes=plan.volumes,
                    destination=str(download.get("destination") or ""),
                    imported_filename=import_relative_path.name,
                )
                source_exists = source_path.exists() and source_path.is_file()
                local_imports.append(
                    {
                        "model": download.get("model"),
                        "source": source,
                        "source_relative_path": import_relative_path.as_posix(),
                        "source_path": str(source_path),
                        "destination": str(download.get("destination") or ""),
                        "resolved_destination": destination_path.as_posix(),
                        "exists": source_exists,
                        "size_bytes": source_path.stat().st_size if source_exists else None,
                    }
                )
                continue
            if not self._is_model_artifact_source(source):
                continue
            artifact_id = self._model_artifact_id_from_source(source)
            try:
                _, source_path = self._verified_model_artifact(artifact_id)
                source_exists = True
            except (KeyError, ValueError):
                source_path = self._model_artifact_payload_path(artifact_id)
                source_exists = False
            destination_path = self._resolve_volume_destination(
                volumes=plan.volumes,
                destination=str(download.get("destination") or ""),
                imported_filename=artifact_id.removeprefix("sha256:"),
            )
            model_artifacts.append(
                {
                    "model": download.get("model"),
                    "source": source,
                    "artifact_id": artifact_id,
                    "source_path": str(source_path),
                    "destination": str(download.get("destination") or ""),
                    "resolved_destination": destination_path.as_posix(),
                    "exists": source_exists,
                    "size_bytes": source_path.stat().st_size if source_exists else None,
                }
            )
        checks: list[ProviderInstallationDiagnosticCheck] = []
        if local_imports:
            missing_imports = [item for item in local_imports if not item["exists"]]
            if missing_imports:
                summary = (
                    "One or more required local-import artifacts are missing from the "
                    "controlled imports root."
                )
                status = "FAIL"
            else:
                summary = (
                    "All required local-import artifacts are staged inside the controlled "
                    "imports root."
                )
                status = "PASS"
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="local_import_artifacts",
                    status=status,
                    summary=summary,
                    details={
                        "imports_root": str(imports_root),
                        "required_local_import_count": len(local_imports),
                        "ready_local_import_count": len(local_imports) - len(missing_imports),
                        "missing_local_import_count": len(missing_imports),
                        "local_imports": local_imports,
                    },
                )
            )
        if model_artifacts:
            missing_artifacts = [item for item in model_artifacts if not item["exists"]]
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="model_artifact_store",
                    status="FAIL" if missing_artifacts else "PASS",
                    summary=(
                        "One or more requested model artifacts are missing from the "
                        "shared Model Artifact Store."
                        if missing_artifacts
                        else "All requested model artifacts are verified in the shared Model Artifact Store."
                    ),
                    details={
                        "store_root": str(self._model_artifacts_root().resolve()),
                        "required_model_artifact_count": len(model_artifacts),
                        "ready_model_artifact_count": len(model_artifacts) - len(missing_artifacts),
                        "missing_model_artifact_count": len(missing_artifacts),
                        "model_artifacts": model_artifacts,
                    },
                )
            )
        if not checks:
            return []
        return checks

    def installation_artifact_inventory(self) -> ProviderInstallationArtifactInventory:
        imports_root = self._imports_root().resolve()
        items: list[ProviderInstallationArtifact] = []
        if imports_root.exists():
            for path in sorted(
                candidate for candidate in imports_root.rglob("*") if candidate.is_file()
            ):
                items.append(self._artifact_metadata(path))
        return ProviderInstallationArtifactInventory(
            supported=True,
            imports_root=str(imports_root),
            max_artifact_bytes=self._MAX_LOCAL_ARTIFACT_BYTES,
            archive_extract_supported=True,
            supported_archive_formats=list(self._SUPPORTED_ARCHIVE_FORMATS),
            max_extracted_bytes=self._MAX_EXTRACTED_BYTES,
            max_extracted_files=self._MAX_EXTRACTED_FILES,
            items=items,
        )

    def stage_local_artifact(
        self,
        *,
        relative_path: str,
        content_bytes: bytes,
    ) -> ProviderInstallationArtifact:
        normalized_relative_path = self._validated_import_relative_path(relative_path)
        if len(content_bytes) > self._MAX_LOCAL_ARTIFACT_BYTES:
            raise ValueError(
                "controlled filesystem executor artifact exceeds the maximum allowed size"
            )
        target_path = (self._imports_root() / normalized_relative_path).resolve()
        try:
            target_path.relative_to(self._imports_root().resolve())
        except ValueError as exc:
            raise ValueError(
                "controlled filesystem executor resolved artifact path outside the imports root"
            ) from exc
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_suffix(f"{target_path.suffix}.tmp")
        temp_path.write_bytes(content_bytes)
        temp_path.replace(target_path)
        return self._artifact_metadata(target_path)

    def delete_local_artifact(self, *, relative_path: str) -> None:
        normalized_relative_path = self._validated_import_relative_path(relative_path)
        target_path = (self._imports_root() / normalized_relative_path).resolve()
        try:
            target_path.relative_to(self._imports_root().resolve())
        except ValueError as exc:
            raise ValueError(
                "controlled filesystem executor resolved artifact path outside the imports root"
            ) from exc
        if not target_path.exists() or not target_path.is_file():
            raise KeyError(relative_path)
        target_path.unlink()
        current = target_path.parent
        imports_root = self._imports_root().resolve()
        while current != imports_root and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    def extract_local_artifact_archive(
        self,
        *,
        archive_relative_path: str,
        destination_directory: str,
    ) -> ProviderInstallationArchiveExtractionResult:
        archive_relative = self._validated_import_relative_path(archive_relative_path)
        destination_relative = self._validated_import_directory_path(
            destination_directory
        )
        imports_root = self._imports_root().resolve()
        archive_path = (imports_root / archive_relative).resolve()
        try:
            archive_path.relative_to(imports_root)
        except ValueError as exc:
            raise ValueError(
                "controlled filesystem executor resolved archive path outside the imports root"
            ) from exc
        if not archive_path.exists() or not archive_path.is_file():
            raise KeyError(archive_relative.as_posix())
        archive_format = self._archive_format_for_path(archive_relative)
        if archive_format is None:
            raise ValueError(
                "controlled filesystem executor only supports zip, tar, tar.gz, and tgz archives"
            )
        destination_root = (imports_root / destination_relative).resolve()
        try:
            destination_root.relative_to(imports_root)
        except ValueError as exc:
            raise ValueError(
                "controlled filesystem executor resolved extraction target outside the imports root"
            ) from exc
        destination_root.mkdir(parents=True, exist_ok=True)
        extracted = self._extract_archive_members(
            archive_path=archive_path,
            archive_format=archive_format,
            destination_root=destination_root,
            imports_root=imports_root,
        )
        return ProviderInstallationArchiveExtractionResult(
            archive_relative_path=archive_relative.as_posix(),
            destination_directory=destination_relative.as_posix(),
            extracted_file_count=len(extracted),
            extracted_total_bytes=sum(item["size_bytes"] for item in extracted),
            extracted_relative_paths=[item["relative_path"] for item in extracted],
        )

    def model_artifact_inventory(self) -> ModelArtifactInventory:
        """Return verified immutable artifacts without exposing arbitrary host paths."""
        store_root = self._model_artifacts_root().resolve()
        items: list[ModelArtifact] = []
        reference_counts = self._artifact_set_reference_counts()
        manifests_root = self._model_artifact_manifests_root()
        if manifests_root.exists():
            for path in sorted(manifests_root.glob("*.json")):
                try:
                    item = ModelArtifact.model_validate_json(path.read_text(encoding="utf-8"))
                    self._verified_model_artifact(item.artifact_id)
                    reference_count = reference_counts.get(item.artifact_id, 0)
                    gc_record = (
                        None
                        if reference_count
                        else self._model_artifact_gc_record(item.artifact_id)
                    )
                    unreferenced_since = gc_record.get("unreferenced_since") if gc_record else None
                    eligible_at = self._gc_eligible_at(unreferenced_since)
                    items.append(
                        item.model_copy(
                            update={
                                "reference_count": reference_count,
                                "unreferenced_since": unreferenced_since,
                                "garbage_collection_eligible_at": eligible_at,
                            }
                        )
                    )
                except (OSError, ValueError):
                    # A malformed local manifest is never offered as a usable artifact.
                    continue
        return ModelArtifactInventory(
            supported=True,
            store_root=str(store_root),
            max_artifact_bytes=self._MAX_LOCAL_ARTIFACT_BYTES,
            garbage_collection_grace_seconds=self.model_artifact_gc_grace_seconds,
            items=items,
        )

    def promote_local_artifact_to_model_store(
        self,
        *,
        relative_path: str,
    ) -> ModelArtifact:
        """Copy a staged file into immutable content-addressed model storage."""
        staged_relative_path = self._validated_import_relative_path(relative_path)
        imports_root = self._imports_root().resolve()
        source_path = (imports_root / staged_relative_path).resolve()
        try:
            source_path.relative_to(imports_root)
        except ValueError as exc:
            raise ValueError(
                "controlled filesystem executor resolved staged artifact outside the imports root"
            ) from exc
        if not source_path.exists() or not source_path.is_file():
            raise KeyError(staged_relative_path.as_posix())
        size_bytes, digest = self._sha256_file(source_path)
        if size_bytes > self._MAX_LOCAL_ARTIFACT_BYTES:
            raise ValueError(
                "controlled filesystem executor artifact exceeds the maximum allowed size"
            )
        artifact_id = f"sha256:{digest}"
        payload_path = self._model_artifact_payload_path(artifact_id)
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        if payload_path.exists():
            existing_size, existing_digest = self._sha256_file(payload_path)
            if existing_size != size_bytes or existing_digest != digest:
                raise ValueError(
                    "controlled filesystem executor found conflicting content for model artifact id"
                )
        else:
            temporary_path = payload_path.with_suffix(".tmp")
            try:
                shutil.copyfile(source_path, temporary_path)
                copied_size, copied_digest = self._sha256_file(temporary_path)
                if copied_size != size_bytes or copied_digest != digest:
                    raise ValueError(
                        "controlled filesystem executor could not verify promoted model artifact"
                    )
                temporary_path.replace(payload_path)
                payload_path.chmod(stat.S_IREAD)
            finally:
                if temporary_path.exists():
                    temporary_path.unlink()
        artifact = ModelArtifact(
            artifact_id=artifact_id,
            content_sha256=digest,
            size_bytes=size_bytes,
            original_filename=source_path.name,
            storage_relative_path=payload_path.relative_to(
                self._model_artifacts_root()
            ).as_posix(),
            source_type="STAGED_IMPORT",
            source_reference=staged_relative_path.as_posix(),
            created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
        manifest_path = self._model_artifact_manifest_path(artifact_id)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        if not manifest_path.exists():
            temporary_manifest_path = manifest_path.with_suffix(".tmp")
            temporary_manifest_path.write_text(
                artifact.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
            )
            temporary_manifest_path.replace(manifest_path)
        else:
            artifact = ModelArtifact.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        return artifact

    def delete_model_artifact(self, *, artifact_id: str) -> None:
        normalized_artifact_id = self._validated_model_artifact_id(artifact_id)
        if self._has_unreadable_model_artifact_set_manifest():
            raise ValueError(
                "controlled filesystem executor cannot delete model artifacts "
                "while an artifact set manifest is unreadable"
            )
        referencing_sets = self._artifact_set_ids_referencing(normalized_artifact_id)
        if referencing_sets:
            raise ValueError(
                "controlled filesystem executor cannot delete a model artifact referenced "
                f"by artifact set: {referencing_sets[0]}"
            )
        payload_path = self._model_artifact_payload_path(normalized_artifact_id)
        manifest_path = self._model_artifact_manifest_path(normalized_artifact_id)
        if not payload_path.exists():
            raise KeyError(normalized_artifact_id)
        payload_path.chmod(stat.S_IREAD | stat.S_IWRITE)
        payload_path.unlink()
        if manifest_path.exists():
            manifest_path.unlink()
        gc_record_path = self._model_artifact_gc_record_path(normalized_artifact_id)
        if gc_record_path.exists():
            gc_record_path.unlink()
        self._remove_empty_parent_directories(
            payload_path.parent,
            stop_at=self._model_artifacts_root().resolve(),
        )

    def create_model_artifact_set(
        self,
        *,
        display_name: str,
        files: list[dict],
    ) -> ModelArtifactSet:
        normalized_display_name = str(display_name or "").strip()
        if not normalized_display_name:
            raise ValueError(
                "controlled filesystem executor requires a non-empty model artifact set display name"
            )
        normalized_files = [ModelArtifactSetFile.model_validate(item) for item in files]
        if not normalized_files:
            raise ValueError(
                "controlled filesystem executor requires at least one model artifact set file"
            )
        seen_paths: set[str] = set()
        canonical_files: list[ModelArtifactSetFile] = []
        for item in normalized_files:
            relative_path = self._validated_artifact_set_relative_path(item.relative_path)
            if relative_path in seen_paths:
                raise ValueError(
                    "controlled filesystem executor requires unique model artifact set file paths"
                )
            seen_paths.add(relative_path)
            artifact_id = self._validated_model_artifact_id(item.artifact_id)
            self._verified_model_artifact(artifact_id)
            canonical_files.append(
                item.model_copy(
                    update={"relative_path": relative_path, "artifact_id": artifact_id}
                )
            )
        canonical_files.sort(key=lambda item: item.relative_path)
        manifest_payload = {
            "display_name": normalized_display_name,
            "files": [item.model_dump(mode="json") for item in canonical_files],
        }
        manifest_digest = hashlib.sha256(
            json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        artifact_set_id = f"model-artifact-set:sha256:{manifest_digest}"
        artifact_set = ModelArtifactSet(
            artifact_set_id=artifact_set_id,
            display_name=normalized_display_name,
            files=canonical_files,
            manifest_hash=f"sha256:{manifest_digest}",
            created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
        manifest_path = self._model_artifact_set_manifest_path(artifact_set_id)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        if manifest_path.exists():
            return ModelArtifactSet.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        temporary_path = manifest_path.with_suffix(".tmp")
        temporary_path.write_text(
            artifact_set.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(manifest_path)
        return artifact_set

    def list_model_artifact_sets(self) -> list[ModelArtifactSet]:
        sets_root = self._model_artifact_sets_root()
        items: list[ModelArtifactSet] = []
        if not sets_root.exists():
            return items
        for path in sorted(sets_root.glob("*.json")):
            try:
                artifact_set = ModelArtifactSet.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                for item in artifact_set.files:
                    self._verified_model_artifact(item.artifact_id)
                items.append(artifact_set)
            except (OSError, ValueError, KeyError):
                continue
        return items

    def get_model_artifact_set(self, artifact_set_id: str) -> ModelArtifactSet:
        normalized_artifact_set_id = self._validated_artifact_set_id(artifact_set_id)
        manifest_path = self._model_artifact_set_manifest_path(normalized_artifact_set_id)
        if not manifest_path.exists():
            raise KeyError(normalized_artifact_set_id)
        artifact_set = ModelArtifactSet.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        for item in artifact_set.files:
            self._verified_model_artifact(item.artifact_id)
        return artifact_set

    def delete_model_artifact_set(self, *, artifact_set_id: str) -> None:
        normalized_artifact_set_id = self._validated_artifact_set_id(artifact_set_id)
        manifest_path = self._model_artifact_set_manifest_path(normalized_artifact_set_id)
        if not manifest_path.exists():
            raise KeyError(normalized_artifact_set_id)
        manifest_path.unlink()

    def collect_model_artifact_garbage(self) -> ModelArtifactGarbageCollectionResult:
        now = datetime.now(UTC)
        retained_artifact_ids: list[str] = []
        pending_artifact_ids: list[str] = []
        collected_artifact_ids: list[str] = []
        if self._has_unreadable_model_artifact_set_manifest():
            return ModelArtifactGarbageCollectionResult(
                evaluated_at=now.isoformat().replace("+00:00", "Z"),
                grace_seconds=self.model_artifact_gc_grace_seconds,
                retained_artifact_ids=[
                    item.artifact_id for item in self.model_artifact_inventory().items
                ],
            )
        for artifact in self.model_artifact_inventory().items:
            gc_record_path = self._model_artifact_gc_record_path(artifact.artifact_id)
            if artifact.reference_count:
                if gc_record_path.exists():
                    gc_record_path.unlink()
                retained_artifact_ids.append(artifact.artifact_id)
                continue
            if artifact.unreferenced_since is None:
                self._write_model_artifact_gc_record(
                    artifact.artifact_id,
                    unreferenced_since=now,
                )
                pending_artifact_ids.append(artifact.artifact_id)
                continue
            eligible_at = self._parse_timestamp(artifact.unreferenced_since) + timedelta(
                seconds=self.model_artifact_gc_grace_seconds
            )
            if now < eligible_at:
                pending_artifact_ids.append(artifact.artifact_id)
                continue
            self.delete_model_artifact(artifact_id=artifact.artifact_id)
            collected_artifact_ids.append(artifact.artifact_id)
        return ModelArtifactGarbageCollectionResult(
            evaluated_at=now.isoformat().replace("+00:00", "Z"),
            grace_seconds=self.model_artifact_gc_grace_seconds,
            retained_artifact_ids=retained_artifact_ids,
            pending_artifact_ids=pending_artifact_ids,
            collected_artifact_ids=collected_artifact_ids,
        )

    def materialize_model_artifact_set(
        self,
        *,
        provider_instance_id: str,
        artifact_set_id: str,
        destination: str,
    ) -> ProviderArtifactMaterialization:
        artifact_set = self.get_model_artifact_set(artifact_set_id)
        relative_destination = Path(
            self._validated_artifact_set_relative_path(f"{destination}/placeholder")
        ).parent
        target_root = (
            self._provider_root(provider_instance_id) / "artifact-sets" / relative_destination
        ).resolve()
        try:
            target_root.relative_to(self._provider_root(provider_instance_id).resolve())
        except ValueError as exc:
            raise ValueError("model artifact set destination escaped provider root") from exc
        target_root.mkdir(parents=True, exist_ok=True)
        files: list[dict] = []
        for item in artifact_set.files:
            _, source_path = self._verified_model_artifact(item.artifact_id)
            target_path = (target_root / item.relative_path).resolve()
            try:
                target_path.relative_to(target_root)
            except ValueError as exc:
                raise ValueError("model artifact set file escaped materialization root") from exc
            target_path.parent.mkdir(parents=True, exist_ok=True)
            method = self._materialize_shared_model_artifact(
                source_path=source_path,
                destination_path=target_path,
            )
            files.append(
                {
                    "artifact_id": item.artifact_id,
                    "relative_path": item.relative_path,
                    "role": item.role,
                    "destination_path": str(target_path),
                    "materialization_method": method,
                }
            )
        digest = hashlib.sha256(
            f"{provider_instance_id}|{artifact_set.artifact_set_id}|{target_root}".encode()
        ).hexdigest()[:16]
        return ProviderArtifactMaterialization(
            materialization_id=f"pam-{digest}",
            provider_instance_id=provider_instance_id,
            artifact_set_id=artifact_set.artifact_set_id,
            destination=relative_destination.as_posix(),
            status="READY",
            files=files,
            created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
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
        enforcement_details = self._enforce_controlled_filesystem_boundary(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
        )
        result = RecordedProviderInstallationExecutor.apply(
            self,
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
            provider_instance_id=provider_instance_id,
        )
        provider_root = self._provider_root(provider_instance_id)
        state_path = self._state_path(provider_instance_id)
        provider_root.mkdir(parents=True, exist_ok=True)
        volume_steps = self._prepare_volume_directories(
            provider_root=provider_root,
            plan=plan,
        )
        download_steps = self._stage_model_download_manifests(
            provider_root=provider_root,
            plan=plan,
        )
        import_steps = self._import_local_artifacts(
            provider_root=provider_root,
            plan=plan,
        )
        payload = self._state_payload(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
            provider_instance_id=provider_instance_id,
        )
        temp_path = state_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(state_path)
        return result.model_copy(
            update={
                "rollback_result": self.rollback_preview(
                    approval=approval,
                    plan=plan,
                    configuration=configuration,
                    manifest=manifest,
                ),
                "step_results": [
                    ProviderInstallationStepResult(
                        step_id="sandbox-enforce-boundary",
                        step_type="sandbox_boundary",
                        status="RECORDED",
                        summary=(
                            "Validated declarative plan against controlled filesystem "
                            "executor boundary."
                        ),
                        details=enforcement_details,
                    ),
                    *result.step_results,
                    *volume_steps,
                    *download_steps,
                    *import_steps,
                    ProviderInstallationStepResult(
                        step_id="filesystem-write-installation-state",
                        step_type="filesystem_state_write",
                        status="RECORDED",
                        summary=(
                            "Wrote managed installation state inside the controlled "
                            "filesystem root."
                        ),
                        details={
                            "state_root": str(self.root_path),
                            "provider_root": str(provider_root),
                            "state_path": str(state_path),
                        },
                    ),
                ]
            }
        )

    def rollback(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
        provider_instance_id: str | None,
    ) -> ProviderInstallationRollbackResult:
        self._validate_inputs(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
        )
        if provider_instance_id is None:
            return ProviderInstallationRollbackResult(
                status="NOT_NEEDED",
                summary=(
                    "No provider instance id was assigned, so no controlled "
                    "filesystem state needed rollback."
                ),
                details={
                    "executor_id": self.executor_id,
                    "host_mutation": True,
                    "state_root": str(self.root_path),
                    "provider_instance_id": None,
                },
            )

        provider_root = self._provider_root(provider_instance_id)
        if not provider_root.exists():
            return ProviderInstallationRollbackResult(
                status="NOT_NEEDED",
                summary=(
                    "Controlled filesystem state was already absent before rollback."
                ),
                details={
                    "executor_id": self.executor_id,
                    "host_mutation": True,
                    "state_root": str(self.root_path),
                    "provider_root": str(provider_root),
                    "provider_instance_id": provider_instance_id,
                },
            )

        shutil.rmtree(provider_root)
        return ProviderInstallationRollbackResult(
            status="COMPLETED",
            summary=(
                "Removed managed installation state and prepared host artifacts from "
                "the controlled filesystem root."
            ),
            details={
                "executor_id": self.executor_id,
                "host_mutation": True,
                "state_root": str(self.root_path),
                "provider_root": str(provider_root),
                "provider_instance_id": provider_instance_id,
            },
            step_results=[
                ProviderInstallationStepResult(
                    step_id="filesystem-remove-installation-state",
                    step_type="filesystem_state_remove",
                    status="RECORDED",
                    summary=(
                        "Removed managed installation state and prepared host "
                        "artifacts from the controlled filesystem root."
                    ),
                    details={
                        "state_root": str(self.root_path),
                        "provider_root": str(provider_root),
                        "provider_instance_id": provider_instance_id,
                    },
                )
            ],
        )

    def _provider_root(self, provider_instance_id: str) -> Path:
        return self.root_path / "providers" / provider_instance_id

    def _state_path(self, provider_instance_id: str) -> Path:
        return self._provider_root(provider_instance_id) / self._STATE_FILENAME

    def _volumes_root(self, provider_root: Path) -> Path:
        return provider_root / "volumes"

    def _downloads_root(self, provider_root: Path) -> Path:
        return provider_root / "downloads"

    def _imports_root(self) -> Path:
        return self.root_path / "imports"

    def _model_artifacts_root(self) -> Path:
        return self.root_path / self._MODEL_ARTIFACT_STORE_DIR

    def _model_artifact_manifests_root(self) -> Path:
        return self._model_artifacts_root() / "manifests"

    def _model_artifact_sets_root(self) -> Path:
        return self._model_artifacts_root() / "sets"

    def _model_artifact_gc_root(self) -> Path:
        return self._model_artifacts_root() / "gc"

    def _model_artifact_payload_path(self, artifact_id: str) -> Path:
        normalized_artifact_id = self._validated_model_artifact_id(artifact_id)
        digest = normalized_artifact_id.removeprefix("sha256:")
        return self._model_artifacts_root() / "sha256" / digest[:2] / digest / "payload"

    def _model_artifact_manifest_path(self, artifact_id: str) -> Path:
        normalized_artifact_id = self._validated_model_artifact_id(artifact_id)
        digest = normalized_artifact_id.removeprefix("sha256:")
        return self._model_artifact_manifests_root() / f"{digest}.json"

    def _model_artifact_set_manifest_path(self, artifact_set_id: str) -> Path:
        normalized_artifact_set_id = self._validated_artifact_set_id(artifact_set_id)
        digest = normalized_artifact_set_id.removeprefix("model-artifact-set:sha256:")
        return self._model_artifact_sets_root() / f"{digest}.json"

    def _model_artifact_gc_record_path(self, artifact_id: str) -> Path:
        normalized_artifact_id = self._validated_model_artifact_id(artifact_id)
        digest = normalized_artifact_id.removeprefix("sha256:")
        return self._model_artifact_gc_root() / f"{digest}.json"

    def _verified_model_artifact(self, artifact_id: str) -> tuple[ModelArtifact, Path]:
        normalized_artifact_id = self._validated_model_artifact_id(artifact_id)
        manifest_path = self._model_artifact_manifest_path(normalized_artifact_id)
        payload_path = self._model_artifact_payload_path(normalized_artifact_id)
        if not manifest_path.exists() or not payload_path.exists() or not payload_path.is_file():
            raise KeyError(normalized_artifact_id)
        artifact = ModelArtifact.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        if artifact.artifact_id != normalized_artifact_id:
            raise ValueError(
                "controlled filesystem executor found mismatched model artifact manifest"
            )
        size_bytes, digest = self._sha256_file(payload_path)
        if size_bytes != artifact.size_bytes or digest != artifact.content_sha256:
            raise ValueError(
                "controlled filesystem executor detected corrupt model artifact content"
            )
        return artifact, payload_path

    def _artifact_set_ids_referencing(self, artifact_id: str) -> list[str]:
        return [
            artifact_set_id
            for artifact_set_id, count in self._artifact_set_reference_counts().items()
            if artifact_set_id == artifact_id and count
        ]

    def _artifact_set_reference_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        sets_root = self._model_artifact_sets_root()
        if not sets_root.exists():
            return counts
        for path in sets_root.glob("*.json"):
            try:
                artifact_set = ModelArtifactSet.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                for item in artifact_set.files:
                    counts[item.artifact_id] = counts.get(item.artifact_id, 0) + 1
            except (OSError, ValueError):
                # Preserve bytes when a set manifest is unreadable rather than risk collection.
                continue
        return counts

    def _has_unreadable_model_artifact_set_manifest(self) -> bool:
        sets_root = self._model_artifact_sets_root()
        if not sets_root.exists():
            return False
        for path in sets_root.glob("*.json"):
            try:
                ModelArtifactSet.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return True
        return False

    def _model_artifact_gc_record(self, artifact_id: str) -> dict | None:
        path = self._model_artifact_gc_record_path(artifact_id)
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            timestamp = record.get("unreferenced_since")
            if not isinstance(timestamp, str):
                return None
            self._parse_timestamp(timestamp)
            return {"unreferenced_since": timestamp}
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _write_model_artifact_gc_record(
        self,
        artifact_id: str,
        *,
        unreferenced_since: datetime,
    ) -> None:
        path = self._model_artifact_gc_record_path(artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(
                {
                    "artifact_id": artifact_id,
                    "unreferenced_since": unreferenced_since.isoformat().replace(
                        "+00:00", "Z"
                    ),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)

    def _gc_eligible_at(self, unreferenced_since: str | None) -> str | None:
        if unreferenced_since is None:
            return None
        return (
            self._parse_timestamp(unreferenced_since)
            + timedelta(seconds=self.model_artifact_gc_grace_seconds)
        ).isoformat().replace("+00:00", "Z")

    def _parse_timestamp(self, value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _state_payload(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
        provider_instance_id: str,
    ) -> dict:
        return {
            "executor_id": self.executor_id,
            "approval_id": approval.approval_id,
            "plugin_id": approval.plugin_id,
            "plan_id": plan.plan_id,
            "plan_hash": approval.plan_hash,
            "configuration_hash": approval.configuration_hash,
            "provider_instance_id": provider_instance_id,
            "display_name": configuration.get("display_name"),
            "base_url": configuration.get("base_url"),
            "manifest_plugin_version": manifest.get("plugin_version"),
            "recorded_sections": [
                section
                for section in self._PLAN_SECTIONS
                if getattr(plan, section)
            ],
            "prepared_volumes": [volume.get("name") for volume in plan.volumes],
            "staged_model_downloads": [
                download.get("model") for download in plan.model_downloads
            ],
            "imported_local_artifacts": [
                download.get("model")
                for download in plan.model_downloads
                if self._is_local_import_source(download.get("source"))
            ],
            "materialized_model_artifacts": [
                self._model_artifact_id_from_source(str(download.get("source") or ""))
                for download in plan.model_downloads
                if self._is_model_artifact_source(download.get("source"))
            ],
        }

    def _enforce_controlled_filesystem_boundary(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> dict:
        self._validate_inputs(
            approval=approval,
            plan=plan,
            configuration=configuration,
            manifest=manifest,
        )
        for section in ("containers", "processes", "environment"):
            if getattr(plan, section):
                raise ValueError(
                    "controlled filesystem executor does not permit non-empty declarative "
                    f"section: {section}"
                )
        enforcement_details = SandboxEnforcedProviderInstallationExecutor._enforce_plan_boundary(
            self,
            approval=approval,
            plan=plan.model_copy(
                update={
                    "model_downloads": [],
                    "volumes": [],
                }
            ),
            configuration=configuration,
            manifest=manifest,
        )
        validated_volume_names: list[str] = []
        if len(plan.volumes) > self._MAX_VOLUME_DECLARATIONS:
            raise ValueError(
                "controlled filesystem executor does not permit more than "
                f"{self._MAX_VOLUME_DECLARATIONS} volume declarations"
            )
        for volume in plan.volumes:
            unexpected_volume_keys = sorted(
                key for key in volume if key not in self._ALLOWED_VOLUME_KEYS
            )
            if unexpected_volume_keys:
                raise ValueError(
                    "controlled filesystem executor does not permit volume declaration "
                    f"keys outside the bounded subset: {unexpected_volume_keys[0]}"
                )
            volume_name = str(volume.get("name") or "").strip()
            if not volume_name:
                raise ValueError(
                    "controlled filesystem executor requires every volume declaration to have a name"
                )
            mount_path = str(volume.get("mount_path") or "").strip()
            if not mount_path:
                raise ValueError(
                    "controlled filesystem executor requires every volume declaration to have a mount_path"
                )
            validated_volume_names.append(volume_name)

        validated_model_downloads: list[str] = []
        local_import_models: list[str] = []
        model_artifact_models: list[str] = []
        if len(plan.model_downloads) > self._MAX_MODEL_DOWNLOAD_DECLARATIONS:
            raise ValueError(
                "controlled filesystem executor does not permit more than "
                f"{self._MAX_MODEL_DOWNLOAD_DECLARATIONS} model download declarations"
            )
        for download in plan.model_downloads:
            unexpected_download_keys = sorted(
                key
                for key in download
                if key not in self._ALLOWED_MODEL_DOWNLOAD_KEYS
            )
            if unexpected_download_keys:
                raise ValueError(
                    "controlled filesystem executor does not permit model download "
                    "declaration keys outside the bounded subset: "
                    f"{unexpected_download_keys[0]}"
                )
            model_name = str(download.get("model") or "").strip()
            if not model_name:
                raise ValueError(
                    "controlled filesystem executor requires every model download declaration to have a model"
                )
            validated_model_downloads.append(model_name)
            if self._is_local_import_source(download.get("source")):
                self._local_import_relative_path(str(download.get("source")))
                self._resolve_volume_destination(
                    volumes=plan.volumes,
                    destination=str(download.get("destination") or ""),
                    imported_filename=self._local_import_relative_path(
                        str(download.get("source"))
                    ).name,
                )
                local_import_models.append(model_name)
            if self._is_model_artifact_source(download.get("source")):
                artifact_id = self._model_artifact_id_from_source(
                    str(download.get("source"))
                )
                self._resolve_volume_destination(
                    volumes=plan.volumes,
                    destination=str(download.get("destination") or ""),
                    imported_filename=artifact_id.removeprefix("sha256:"),
                )
                model_artifact_models.append(model_name)

        return {
            **enforcement_details,
            "executor_id": self.executor_id,
            "host_mutation": True,
            "state_root": str(self.root_path),
            "validated_volume_names": validated_volume_names,
            "validated_model_downloads": validated_model_downloads,
            "validated_local_import_models": local_import_models,
            "validated_model_artifact_models": model_artifact_models,
        }

    def _prepare_volume_directories(
        self,
        *,
        provider_root: Path,
        plan: InstallationPlan,
    ) -> list[ProviderInstallationStepResult]:
        if not plan.volumes:
            return []
        volumes_root = self._volumes_root(provider_root)
        volumes_root.mkdir(parents=True, exist_ok=True)
        steps: list[ProviderInstallationStepResult] = []
        for volume in plan.volumes:
            volume_name = self._safe_name(str(volume["name"]))
            volume_path = volumes_root / volume_name
            volume_path.mkdir(parents=True, exist_ok=True)
            steps.append(
                ProviderInstallationStepResult(
                    step_id=f"filesystem-prepare-volume-{volume_name}",
                    step_type="filesystem_prepare_volume",
                    status="RECORDED",
                    summary="Prepared controlled volume directory inside the executor root.",
                    details={
                        "volume_name": volume["name"],
                        "mount_path": volume.get("mount_path"),
                        "volume_path": str(volume_path),
                    },
                )
            )
        return steps

    def _stage_model_download_manifests(
        self,
        *,
        provider_root: Path,
        plan: InstallationPlan,
    ) -> list[ProviderInstallationStepResult]:
        if not plan.model_downloads:
            return []
        downloads_root = self._downloads_root(provider_root)
        downloads_root.mkdir(parents=True, exist_ok=True)
        steps: list[ProviderInstallationStepResult] = []
        for index, download in enumerate(plan.model_downloads, start=1):
            model_name = self._safe_name(str(download["model"]))
            manifest_path = downloads_root / f"{index:02d}-{model_name}.json"
            manifest_payload = {
                "model": download.get("model"),
                "source": download.get("source"),
                "destination": download.get("destination"),
                "notes": download.get("notes"),
            }
            manifest_path.write_text(
                json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            steps.append(
                ProviderInstallationStepResult(
                    step_id=f"filesystem-stage-model-download-{index}",
                    step_type="filesystem_stage_model_download",
                    status="RECORDED",
                    summary="Staged model download manifest inside the executor root.",
                    details={
                        "model": download.get("model"),
                        "manifest_path": str(manifest_path),
                    },
                )
            )
        return steps

    def _import_local_artifacts(
        self,
        *,
        provider_root: Path,
        plan: InstallationPlan,
    ) -> list[ProviderInstallationStepResult]:
        steps: list[ProviderInstallationStepResult] = []
        for index, download in enumerate(plan.model_downloads, start=1):
            source = str(download.get("source") or "")
            if not (
                self._is_local_import_source(source)
                or self._is_model_artifact_source(source)
            ):
                continue
            if self._is_local_import_source(source):
                import_relative_path = self._local_import_relative_path(source)
                source_path = (self._imports_root() / import_relative_path).resolve()
                try:
                    source_path.relative_to(self._imports_root().resolve())
                except ValueError as exc:
                    raise ValueError(
                        "controlled filesystem executor resolved local import source outside the imports root"
                    ) from exc
                imported_filename = import_relative_path.name
                step_type = "filesystem_import_local_artifact"
                summary = "Imported a staged local artifact into the controlled provider volume path."
            else:
                artifact_id = self._model_artifact_id_from_source(source)
                _, source_path = self._verified_model_artifact(artifact_id)
                imported_filename = artifact_id.removeprefix("sha256:")
                step_type = "filesystem_materialize_model_artifact"
                summary = "Materialized a shared Model Artifact Store entry into the controlled provider volume path."
            if not source_path.exists() or not source_path.is_file():
                raise ValueError(
                    "controlled filesystem executor could not find model artifact source: "
                    f"{source}"
                )
            destination_path = self._resolve_volume_destination(
                volumes=plan.volumes,
                destination=str(download.get("destination") or ""),
                imported_filename=imported_filename,
                provider_root=provider_root,
            )
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            materialization_method = "COPY"
            if self._is_model_artifact_source(source):
                materialization_method = self._materialize_shared_model_artifact(
                    source_path=source_path,
                    destination_path=destination_path,
                )
            else:
                shutil.copy2(source_path, destination_path)
            steps.append(
                ProviderInstallationStepResult(
                    step_id=f"filesystem-materialize-model-artifact-{index}",
                    step_type=step_type,
                    status="RECORDED",
                    summary=summary,
                    details={
                        "model": download.get("model"),
                        "source": source,
                        "source_path": str(source_path),
                        "destination_path": str(destination_path),
                        "materialization_method": materialization_method,
                    },
                )
            )
        return steps

    def _materialize_shared_model_artifact(
        self,
        *,
        source_path: Path,
        destination_path: Path,
    ) -> str:
        if destination_path.exists():
            destination_path.unlink()
        if (
            self.model_artifact_materialization_mode == "HARDLINK_IF_READONLY"
            and not (source_path.stat().st_mode & stat.S_IWUSR)
        ):
            try:
                os.link(source_path, destination_path)
                destination_path.chmod(stat.S_IREAD)
                return "HARDLINK"
            except OSError:
                pass
        shutil.copy2(source_path, destination_path)
        return "COPY"

    def _safe_name(self, value: str) -> str:
        sanitized = "".join(
            character if character.isalnum() or character in {"-", "_", "."} else "-"
            for character in value.strip()
        ).strip("-.")
        return sanitized or "item"

    def _is_local_import_source(self, value) -> bool:
        return str(value or "").startswith("local-import://")

    def _is_model_artifact_source(self, value) -> bool:
        return str(value or "").startswith("model-artifact://")

    def _local_import_relative_path(self, source: str) -> Path:
        prefix = "local-import://"
        if not source.startswith(prefix):
            raise ValueError("controlled filesystem executor requires a local-import source")
        remainder = source[len(prefix) :].strip()
        if not remainder:
            raise ValueError(
                "controlled filesystem executor requires non-empty local-import source paths"
            )
        return self._validated_import_relative_path(remainder)

    def _model_artifact_id_from_source(self, source: str) -> str:
        prefix = "model-artifact://"
        if not source.startswith(prefix):
            raise ValueError(
                "controlled filesystem executor requires a model-artifact source"
            )
        return self._validated_model_artifact_id(source[len(prefix) :].strip())

    def _validated_model_artifact_id(self, artifact_id: str) -> str:
        candidate = str(artifact_id or "").strip().lower()
        prefix = "sha256:"
        digest = candidate.removeprefix(prefix)
        if not candidate.startswith(prefix) or len(digest) != 64:
            raise ValueError(
                "controlled filesystem executor requires model artifact ids in sha256:<64-hex> form"
            )
        if any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(
                "controlled filesystem executor requires model artifact ids in sha256:<64-hex> form"
            )
        return candidate

    def _validated_artifact_set_id(self, artifact_set_id: str) -> str:
        candidate = str(artifact_set_id or "").strip().lower()
        prefix = "model-artifact-set:sha256:"
        digest = candidate.removeprefix(prefix)
        if not candidate.startswith(prefix) or len(digest) != 64:
            raise ValueError(
                "controlled filesystem executor requires model artifact set ids "
                "in model-artifact-set:sha256:<64-hex> form"
            )
        if any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(
                "controlled filesystem executor requires model artifact set ids "
                "in model-artifact-set:sha256:<64-hex> form"
            )
        return candidate

    def _validated_artifact_set_relative_path(self, relative_path: str) -> str:
        candidate = Path(str(relative_path or "").strip())
        if not str(candidate).strip() or candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(
                "controlled filesystem executor requires model artifact set paths relative to the provider model root"
            )
        if candidate.name in {"", ".", ".."}:
            raise ValueError(
                "controlled filesystem executor requires model artifact set paths to target files"
            )
        return candidate.as_posix()

    def _sha256_file(self, path: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        size_bytes = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                size_bytes += len(chunk)
                digest.update(chunk)
        return size_bytes, digest.hexdigest()

    def _remove_empty_parent_directories(self, path: Path, *, stop_at: Path) -> None:
        current = path
        while current != stop_at and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    def _validated_import_relative_path(self, relative_path: str) -> Path:
        candidate = Path(str(relative_path or "").strip())
        if not str(candidate).strip():
            raise ValueError(
                "controlled filesystem executor requires non-empty local import artifact paths"
            )
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(
                "controlled filesystem executor does not permit local-import paths outside the imports root"
            )
        if candidate.name in {"", ".", ".."}:
            raise ValueError(
                "controlled filesystem executor requires artifact paths to target a file"
            )
        return candidate

    def _validated_import_directory_path(self, relative_path: str) -> Path:
        candidate = Path(str(relative_path or "").strip())
        if not str(candidate).strip():
            raise ValueError(
                "controlled filesystem executor requires non-empty extraction target directories"
            )
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(
                "controlled filesystem executor does not permit extraction targets outside the imports root"
            )
        if candidate.name in {"", ".", ".."} and len(candidate.parts) <= 1:
            raise ValueError(
                "controlled filesystem executor requires extraction to target a named directory"
            )
        return candidate

    def _archive_format_for_path(self, relative_path: Path) -> str | None:
        name = relative_path.as_posix().lower()
        if name.endswith(".tar.gz"):
            return "tar.gz"
        if name.endswith(".tgz"):
            return "tgz"
        if name.endswith(".tar"):
            return "tar"
        if name.endswith(".zip"):
            return "zip"
        return None

    def _extract_archive_members(
        self,
        *,
        archive_path: Path,
        archive_format: str,
        destination_root: Path,
        imports_root: Path,
    ) -> list[dict]:
        if archive_format == "zip":
            return self._extract_zip_archive(
                archive_path=archive_path,
                destination_root=destination_root,
                imports_root=imports_root,
            )
        return self._extract_tar_archive(
            archive_path=archive_path,
            destination_root=destination_root,
            imports_root=imports_root,
        )

    def _extract_zip_archive(
        self,
        *,
        archive_path: Path,
        destination_root: Path,
        imports_root: Path,
    ) -> list[dict]:
        extracted: list[dict] = []
        total_bytes = 0
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                relative_member = self._validated_archive_member_path(info.filename)
                if info.file_size > self._MAX_EXTRACTED_MEMBER_BYTES:
                    raise ValueError(
                        "controlled filesystem executor archive member exceeds the maximum allowed size"
                    )
                total_bytes += info.file_size
                if len(extracted) + 1 > self._MAX_EXTRACTED_FILES:
                    raise ValueError(
                        "controlled filesystem executor archive exceeds the maximum allowed file count"
                    )
                if total_bytes > self._MAX_EXTRACTED_BYTES:
                    raise ValueError(
                        "controlled filesystem executor archive exceeds the maximum allowed extracted size"
                    )
                destination_path = self._validated_archive_destination_path(
                    destination_root=destination_root,
                    imports_root=imports_root,
                    relative_member=relative_member,
                )
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination_path.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                extracted.append(
                    {
                        "relative_path": destination_path.relative_to(imports_root).as_posix(),
                        "size_bytes": info.file_size,
                    }
                )
        return extracted

    def _extract_tar_archive(
        self,
        *,
        archive_path: Path,
        destination_root: Path,
        imports_root: Path,
    ) -> list[dict]:
        extracted: list[dict] = []
        total_bytes = 0
        with tarfile.open(archive_path, mode="r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                relative_member = self._validated_archive_member_path(member.name)
                if member.size > self._MAX_EXTRACTED_MEMBER_BYTES:
                    raise ValueError(
                        "controlled filesystem executor archive member exceeds the maximum allowed size"
                    )
                total_bytes += member.size
                if len(extracted) + 1 > self._MAX_EXTRACTED_FILES:
                    raise ValueError(
                        "controlled filesystem executor archive exceeds the maximum allowed file count"
                    )
                if total_bytes > self._MAX_EXTRACTED_BYTES:
                    raise ValueError(
                        "controlled filesystem executor archive exceeds the maximum allowed extracted size"
                    )
                destination_path = self._validated_archive_destination_path(
                    destination_root=destination_root,
                    imports_root=imports_root,
                    relative_member=relative_member,
                )
                extracted_stream = archive.extractfile(member)
                if extracted_stream is None:
                    raise ValueError(
                        "controlled filesystem executor could not read an archive member"
                    )
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                with extracted_stream as source, destination_path.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                extracted.append(
                    {
                        "relative_path": destination_path.relative_to(imports_root).as_posix(),
                        "size_bytes": member.size,
                    }
                )
        return extracted

    def _validated_archive_member_path(self, archive_member: str) -> Path:
        candidate = Path(str(archive_member or "").strip())
        if not str(candidate).strip():
            raise ValueError(
                "controlled filesystem executor requires archive members to have non-empty paths"
            )
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(
                "controlled filesystem executor does not permit archive members outside the extraction target"
            )
        if candidate.name in {"", ".", ".."}:
            raise ValueError(
                "controlled filesystem executor requires archive members to target files"
            )
        return candidate

    def _validated_archive_destination_path(
        self,
        *,
        destination_root: Path,
        imports_root: Path,
        relative_member: Path,
    ) -> Path:
        destination_path = (destination_root / relative_member).resolve()
        try:
            destination_path.relative_to(destination_root)
            destination_path.relative_to(imports_root)
        except ValueError as exc:
            raise ValueError(
                "controlled filesystem executor resolved extracted content outside the imports root"
            ) from exc
        return destination_path

    def _resolve_volume_destination(
        self,
        *,
        volumes: list[dict],
        destination: str,
        imported_filename: str,
        provider_root: Path | None = None,
    ) -> Path:
        text = destination.strip()
        if not text:
            raise ValueError(
                "controlled filesystem executor requires destination for local-import artifacts"
            )
        relative_destination = Path(text)
        if relative_destination.is_absolute() or ".." in relative_destination.parts:
            raise ValueError(
                "controlled filesystem executor does not permit local-import destinations outside provider volumes"
            )
        parts = list(relative_destination.parts)
        if not parts:
            raise ValueError(
                "controlled filesystem executor requires destination for local-import artifacts"
            )
        volume_name = parts[0]
        matching_volume = next(
            (volume for volume in volumes if str(volume.get("name") or "").strip() == volume_name),
            None,
        )
        if matching_volume is None:
            raise ValueError(
                "controlled filesystem executor requires local-import destinations to target a declared volume"
            )
        resolved_parts = [self._safe_name(part) for part in parts[1:]]
        final_name = resolved_parts[-1] if resolved_parts else self._safe_name(imported_filename)
        parent_parts = resolved_parts[:-1] if resolved_parts else []
        if provider_root is None:
            return Path(
                self._safe_name(volume_name),
                *parent_parts,
                final_name,
            )
        return self._volumes_root(provider_root) / self._safe_name(volume_name) / Path(
            *parent_parts,
            final_name,
        )

    def _artifact_metadata(self, path: Path) -> ProviderInstallationArtifact:
        relative_path = path.resolve().relative_to(self._imports_root().resolve())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        updated_at = datetime.fromtimestamp(
            path.stat().st_mtime,
            tz=UTC,
        ).isoformat().replace("+00:00", "Z")
        return ProviderInstallationArtifact(
            relative_path=relative_path.as_posix(),
            size_bytes=path.stat().st_size,
            sha256=f"sha256:{digest}",
            updated_at=updated_at,
        )
