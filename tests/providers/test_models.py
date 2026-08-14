from pydantic import ValidationError

from aidn_hypervisor.providers.models import (
    ExecutorSandboxCapabilities,
    InstallationPlan,
    InstallationRecipe,
    InstalledPlugin,
    ModelArtifact,
    ModelArtifactSet,
    ModelArtifactSetFile,
    ModelDeployment,
    PluginPermission,
    PluginSandboxPolicy,
    PluginSecretRequirement,
    PluginUISchema,
    ProviderInstallationApproval,
    ProviderInstallationDiagnostics,
    ProviderInstallationExecutionResult,
    ProviderInstallationJob,
    ProviderInstallationRollbackResult,
    ProviderInstallationStepResult,
    ProviderPluginManifest,
    ProviderRuntimeBrokerResult,
    ProviderRuntimeInstallerDescriptor,
    ProviderRuntimeInvocation,
    RuntimeBinding,
    RuntimeIdentity,
    RuntimeInstance,
    plugin_permission_hash,
)


def test_installed_plugin_binds_package_permissions_and_generation() -> None:
    installed_plugin = InstalledPlugin(
        installed_plugin_id="iplg-1",
        release_id="prl-1",
        plugin_id="aidn.provider.fake",
        plugin_version="1.0.0",
        package_digest="sha256:" + "a" * 64,
        granted_permissions=["network.private", "diagnostics", "network.private"],
        installation_source="PACKAGE",
        installed_at="2026-07-18T00:00:00Z",
    )

    assert installed_plugin.granted_permissions == ["diagnostics", "network.private"]
    assert installed_plugin.granted_permission_hash == plugin_permission_hash(
        ["diagnostics", "network.private"]
    )
    assert installed_plugin.installation_generation == 1


def test_package_installed_plugin_requires_digest_and_matching_permission_hash() -> None:
    for overrides in (
        {},
        {
            "package_digest": "sha256:" + "a" * 64,
            "granted_permission_hash": "sha256:" + "b" * 64,
        },
    ):
        try:
            InstalledPlugin(
                installed_plugin_id="iplg-1",
                release_id="prl-1",
                plugin_id="aidn.provider.fake",
                plugin_version="1.0.0",
                granted_permissions=["network.private"],
                installation_source="PACKAGE",
                installed_at="2026-07-18T00:00:00Z",
                **overrides,
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("expected package or permission-hash ValidationError")


def test_provider_plugin_manifest_stores_digest_and_capability_flags() -> None:
    manifest = ProviderPluginManifest(
        plugin_id="aidn.provider.fake",
        plugin_version="0.1.0",
        display_name="Fake Provider",
        publisher="AiDN Test",
        package_digest="sha256:abc123",
        provider_families=["fake"],
        plugin_capability_flags=["CAN_ATTACH_EXISTING", "CAN_DISCOVER_MODELS"],
        required_permissions=[],
        supported_aidn_capabilities=["llm.chat"],
    )

    assert manifest.plugin_id == "aidn.provider.fake"
    assert manifest.plugin_capability_flags == [
        "CAN_ATTACH_EXISTING",
        "CAN_DISCOVER_MODELS",
    ]


def test_provider_runtime_installer_descriptor_is_an_exact_allowlist() -> None:
    descriptor = ProviderRuntimeInstallerDescriptor(
        installer_id="aidn-provider-runtime-ubuntu.v1",
        provider="ollama",
        platform="ubuntu",
        script="tools/aidn-provider-runtime-ubuntu.sh",
        pinned_version="0.32.12",
        actions=["install", "start", "status", "stop"],
    )

    assert descriptor.model_configuration_separate is True

    for override in (
        {"script": "/tmp/provider.sh"},
        {"provider": "custom-shell"},
        {"actions": ["install", "exec"]},
    ):
        payload = descriptor.model_dump()
        payload.update(override)
        try:
            ProviderRuntimeInstallerDescriptor.model_validate(payload)
        except ValidationError:
            pass
        else:
            raise AssertionError("expected allowlist ValidationError")


def test_provider_runtime_invocation_rejects_generic_command_fields() -> None:
    payload = {
        "approval_id": "pia-1",
        "plan_hash": "sha256:plan",
        "configuration_hash": "sha256:configuration",
        "installer_id": "aidn-provider-runtime-ubuntu.v1",
        "provider": "ollama",
        "action": "install",
        "pinned_version": "0.32.12",
        "arguments": {"command": "curl | sh"},
    }

    try:
        ProviderRuntimeInvocation.model_validate(payload)
    except ValidationError as exc:
        assert "unsupported arguments" in str(exc)
    else:
        raise AssertionError("expected generic command field to be rejected")

    result = ProviderRuntimeBrokerResult(status="SUCCEEDED", summary="runtime ready")
    assert result.events == []


def test_provider_plugin_manifest_normalizes_legacy_permission_strings() -> None:
    manifest = ProviderPluginManifest(
        plugin_id="aidn.provider.fake",
        plugin_version="0.1.0",
        display_name="Fake Provider",
        publisher="AiDN Test",
        package_digest="sha256:abc123",
        provider_families=["fake"],
        plugin_capability_flags=["CAN_ATTACH_EXISTING"],
        required_permissions=["network.private"],
        supported_aidn_capabilities=["llm.chat"],
    )

    permission = manifest.required_permissions[0]
    assert isinstance(permission, PluginPermission)
    assert permission.permission_id == "network.private"
    assert permission.label == "network.private"
    assert permission.risk_level == "low"
    assert permission.reason == "Legacy permission declaration"


def test_provider_plugin_manifest_rejects_blank_package_digest() -> None:
    try:
        ProviderPluginManifest(
            plugin_id="aidn.provider.fake",
            plugin_version="0.1.0",
            display_name="Fake Provider",
            publisher="AiDN Test",
            package_digest="   ",
            provider_families=["fake"],
            plugin_capability_flags=["CAN_ATTACH_EXISTING"],
            required_permissions=[],
            supported_aidn_capabilities=["llm.chat"],
        )
    except ValidationError as exc:
        assert "package_digest" in str(exc)
    else:
        raise AssertionError("expected ValidationError")


def test_provider_plugin_manifest_rejects_blank_required_strings() -> None:
    for field_name in [
        "plugin_id",
        "plugin_version",
        "display_name",
        "publisher",
        "package_digest",
    ]:
        payload = {
            "plugin_id": "aidn.provider.fake",
            "plugin_version": "0.1.0",
            "display_name": "Fake Provider",
            "publisher": "AiDN Test",
            "package_digest": "sha256:abc123",
            "provider_families": ["fake"],
            "plugin_capability_flags": ["CAN_ATTACH_EXISTING"],
            "required_permissions": [],
            "supported_aidn_capabilities": ["llm.chat"],
        }
        payload[field_name] = "   "
        try:
            ProviderPluginManifest(**payload)
        except ValidationError as exc:
            assert field_name in str(exc)
        else:
            raise AssertionError("expected ValidationError")


def test_runtime_binding_requires_primary_capability() -> None:
    for field_name, override in {
        "runtime_binding_id": "   ",
        "provider_instance_id": "",
        "model_deployment_id": "   ",
        "capability_id": "",
        "capability_version": "   ",
        "capability_definition_hash": "",
        "plugin_id": "",
        "compatibility_bundle_id": "   ",
    }.items():
        payload = {
            "runtime_binding_id": "rb-1",
            "provider_instance_id": "pi-1",
            "model_deployment_id": "md-1",
            "capability_id": "cap.primary",
            "capability_version": "1.0.0",
            "capability_definition_hash": "cap-hash",
            "plugin_id": "aidn.provider.fake",
            "compatibility_bundle_id": "bundle-rb-1",
            "status": "ready",
        }
        payload[field_name] = override
        try:
            RuntimeBinding(**payload)
        except ValidationError as exc:
            assert field_name in str(exc)
        else:
            raise AssertionError("expected ValidationError")


def test_runtime_binding_separates_configuration_identity_from_lifecycle() -> None:
    binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        runtime_id="runtime-1",
        runtime_generation=3,
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="llm.chat",
        capability_version="2.1",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.fake",
        plugin_version="1.2.0",
        adapter_id="adapter.chat",
        adapter_version="4",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )

    assert binding.runtime_configuration_hash.startswith("sha256:")
    degraded = RuntimeBinding.model_validate(
        {
            **binding.model_dump(mode="json"),
            "status": "degraded",
            "operational_state": "DEGRADED",
        }
    )
    assert degraded.binding_hash() == binding.binding_hash()
    assert binding.runtime_id != binding.runtime_binding_id


def test_runtime_identity_and_instance_are_distinct() -> None:
    identity = RuntimeIdentity(
        runtime_id="runtime-1",
        runtime_owner="operator-1",
        operator_hypervisor_id="hypervisor-1",
        implementation_class="PLUGIN_MANAGED",
        runtime_generation=2,
        capability_id="llm.chat",
        capability_major_version=2,
        runtime_configuration_hash="sha256:configuration",
    )
    instance = RuntimeInstance(
        runtime_id=identity.runtime_id,
        runtime_generation=identity.runtime_generation,
        instance_id="instance-9",
        runtime_binding_hash="sha256:binding",
        execution_host_id="host-1",
        started_at="2026-07-18T00:00:00Z",
        operational_state="STARTING",
    )

    assert instance.instance_id != identity.runtime_id
    assert instance.runtime_generation == identity.runtime_generation


def test_model_deployment_tracks_metadata_sources() -> None:
    deployment = ModelDeployment(
        model_deployment_id="md-qwen",
        provider_instance_id="pi-ollama",
        provider_model_reference="qwen3:14b",
        operator_display_name="Qwen 14B",
        declared_model_name="Qwen3 14B",
        metadata_sources={
            "declared_model_name": "OPERATOR_DECLARED",
            "context_limit": "PROVIDER_REPORTED",
        },
        capability_bindings=["llm.chat"],
        operational_state="ready",
    )

    assert deployment.metadata_sources["context_limit"] == "PROVIDER_REPORTED"


def test_model_artifact_represents_verified_immutable_bytes() -> None:
    artifact = ModelArtifact(
        artifact_id="sha256:" + "a" * 64,
        content_sha256="a" * 64,
        size_bytes=1024,
        original_filename="qwen.gguf",
        storage_relative_path="sha256/aa/" + "a" * 64 + "/payload",
        source_type="STAGED_IMPORT",
        source_reference="models/qwen.gguf",
        created_at="2026-07-18T12:00:00Z",
    )

    assert artifact.integrity_status == "VERIFIED"


def test_model_artifact_set_binds_a_versioned_multi_file_manifest() -> None:
    artifact_set = ModelArtifactSet(
        artifact_set_id="model-artifact-set:sha256:" + "b" * 64,
        display_name="Qwen GGUF package",
        files=[
            ModelArtifactSetFile(
                relative_path="weights/qwen.gguf",
                artifact_id="sha256:" + "a" * 64,
                role="WEIGHTS",
            ),
            ModelArtifactSetFile(
                relative_path="tokenizer.json",
                artifact_id="sha256:" + "c" * 64,
                role="TOKENIZER",
            ),
        ],
        manifest_hash="sha256:" + "b" * 64,
        created_at="2026-07-18T12:00:00Z",
    )

    assert artifact_set.files[0].role == "WEIGHTS"


def test_provider_plugin_manifest_exposes_directory_install_metadata() -> None:
    manifest = ProviderPluginManifest(
        plugin_id="aidn.provider.ollama",
        plugin_version="1.0.0",
        display_name="Ollama Provider",
        publisher="AiDN Community",
        package_digest="sha256:abc123",
        provider_families=["ollama"],
        plugin_capability_flags=["CAN_INSTALL_PROVIDER", "CAN_DISCOVER_MODELS"],
        required_permissions=[
            PluginPermission(
                permission_id="container.manage",
                label="Container management",
                risk_level="medium",
                reason="Run the Ollama provider container",
            )
        ],
        supported_aidn_capabilities=["llm.chat"],
        trust_status="COMMUNITY_REVIEWED",
        source_repository="https://github.com/aidn/provider-ollama",
        supported_platforms=["linux"],
        supported_accelerators=["nvidia"],
        install_ui_schema=PluginUISchema(
            schema_id="ollama.install.v1",
            fields=[
                {
                    "id": "model_storage_path",
                    "type": "directory",
                    "required": True,
                }
            ],
        ),
        secret_requirements=[
            PluginSecretRequirement(
                secret_type="API_KEY",
                label="Optional upstream API key",
                required=False,
                allowed_usage=["provider_api"],
            )
        ],
        installation_recipes=[
            InstallationRecipe(
                recipe_id="ollama-qwen3-8b",
                display_name="Ollama + Qwen3 8B",
                description="Install Ollama and pull qwen3:8b",
                provider_configuration={"deployment_mode": "managed_container"},
                model_configuration={"provider_model_reference": "qwen3:8b"},
                endpoint_defaults={"capability_id": "llm.chat"},
            )
        ],
    )

    assert manifest.trust_status == "COMMUNITY_REVIEWED"
    assert manifest.sandbox_policy.execution_mode == "RECORDED_ONLY"
    assert manifest.required_permissions[0].permission_id == "container.manage"
    assert manifest.install_ui_schema.fields[0]["id"] == "model_storage_path"
    assert manifest.secret_requirements[0].secret_type == "API_KEY"
    assert manifest.installation_recipes[0].recipe_id == "ollama-qwen3-8b"


def test_executor_sandbox_capabilities_capture_supported_boundary() -> None:
    capabilities = ExecutorSandboxCapabilities(
        supported_execution_modes=["RECORDED_ONLY", "SANDBOX_REQUIRED"],
        supported_filesystem_scopes=["NONE", "CONTROLLED_PATHS"],
        supported_network_scopes=["NONE", "DECLARED_EGRESS"],
        supported_secret_scopes=["DECLARED_HANDLES_ONLY"],
        host_mutation=True,
        notes="Sandboxed executor with controlled host mutation.",
    )

    assert capabilities.supported_execution_modes == [
        "RECORDED_ONLY",
        "SANDBOX_REQUIRED",
    ]
    assert capabilities.host_mutation is True


def test_installation_plan_accepts_default_unsupported_actions() -> None:
    plan = InstallationPlan(
        plan_id="plan-ollama",
        plugin_id="aidn.provider.ollama",
        plan_version="1.0.0",
        summary="Install Ollama",
    )

    assert plan.unsupported_actions == []


def test_installation_plan_is_declarative_and_rejects_script_execution() -> None:
    try:
        InstallationPlan(
            plan_id="plan-ollama",
            plugin_id="aidn.provider.ollama",
            plan_version="1.0.0",
            summary="Install Ollama",
            containers=[],
            processes=[],
            model_downloads=[],
            volumes=[],
            networks=[],
            environment={},
            resource_limits={},
            health_checks=[],
            required_permissions=[],
            secret_references=[],
            unsupported_actions=["RUN_SHELL_SCRIPT"],
        )
    except ValidationError as exc:
        assert "unsupported_actions" in str(exc)
    else:
        raise AssertionError("expected ValidationError")


def test_provider_installation_approval_captures_plan_binding_without_secret_value() -> None:
    approval = ProviderInstallationApproval(
        approval_id="approval-ollama",
        plugin_id="aidn.provider.ollama",
        plan_id="plan-ollama",
        plan_hash="sha256:plan",
        configuration_hash="sha256:configuration",
        configuration={"model": "qwen3:8b"},
        approved_permissions=["container.manage"],
        upgrade_review={
            "status": "INITIAL_APPROVAL",
            "requires_acknowledgement": False,
            "current_sandbox_policy": {
                "execution_mode": "RECORDED_ONLY",
            },
            "summary": "No previous installation approval exists for this plugin.",
        },
        upgrade_acknowledged=False,
        acknowledged_sandbox_policy=PluginSandboxPolicy(
            execution_mode="RECORDED_ONLY",
            filesystem_scope="NONE",
            network_scope="NONE",
            secret_scope="DECLARED_HANDLES_ONLY",
        ).model_dump(mode="json"),
        acknowledged_secret_requirements=[
            {
                "requirement_key": "API_KEY:Optional upstream API key",
                "secret_type": "API_KEY",
                "label": "Optional upstream API key",
                "required": False,
                "allowed_usage": ["provider.connect"],
            }
        ],
        selected_secret_handles=[
            {
                "requirement_key": "API_KEY:Optional upstream API key",
                "secret_type": "API_KEY",
                "label": "Optional upstream API key",
                "secret_handle": "secret://provider/upstream-api-key",
                "allowed_usage": ["provider.connect"],
            }
        ],
        operator_note="Approved for local install",
        created_at="2026-07-15T12:00:00Z",
    )

    assert approval.plan_id == "plan-ollama"
    assert approval.plan_hash == "sha256:plan"
    assert approval.configuration_hash == "sha256:configuration"
    assert approval.status == "APPROVED"
    assert approval.upgrade_review["status"] == "INITIAL_APPROVAL"
    assert approval.upgrade_acknowledged is False
    assert approval.acknowledged_sandbox_policy["execution_mode"] == "RECORDED_ONLY"
    assert approval.selected_secret_handles[0].secret_handle == "secret://provider/upstream-api-key"
    assert "secret_value" not in str(approval.model_dump())


def test_provider_installation_approval_rejects_unknown_status() -> None:
    try:
        ProviderInstallationApproval(
            approval_id="approval-ollama",
            plugin_id="aidn.provider.ollama",
            plan_id="plan-ollama",
            plan_hash="sha256:plan",
            configuration_hash="sha256:configuration",
            status="PENDING",
            created_at="2026-07-15T12:00:00Z",
        )
    except ValidationError as exc:
        assert "status" in str(exc)
    else:
        raise AssertionError("expected ValidationError")


def test_provider_installation_job_records_apply_result() -> None:
    step_result = ProviderInstallationStepResult(
        step_id="create-container",
        step_type="container",
        status="RECORDED",
        summary="Created provider container",
        details={"container_id": "container-1"},
    )

    job = ProviderInstallationJob(
        job_id="job-ollama",
        approval_id="approval-ollama",
        plugin_id="aidn.provider.ollama",
        plan_id="plan-ollama",
        plan_hash="sha256:plan",
        configuration_hash="sha256:configuration",
        status="SUCCEEDED",
        executor_id="executor-local",
        step_results=[step_result],
        provider_instance_id="pi-ollama",
        created_at="2026-07-15T12:00:00Z",
        started_at="2026-07-15T12:00:01Z",
        completed_at="2026-07-15T12:00:05Z",
    )

    assert job.step_results[0].status == "RECORDED"
    assert job.step_results[0].details["container_id"] == "container-1"
    assert job.provider_instance_id == "pi-ollama"
    assert job.status == "SUCCEEDED"


def test_provider_installation_diagnostics_capture_readiness_and_rollback_preview() -> None:
    diagnostics = ProviderInstallationDiagnostics(
        diagnostics_id="diag-ollama",
        plugin_id="aidn.provider.ollama",
        plan_id="plan-ollama",
        plan_hash="sha256:plan",
        configuration_hash="sha256:configuration",
        executor_id="recorded-declarative-v1",
        readiness_status="ACTION_REQUIRED",
        checks=[
            {
                "check_id": "secret_handles",
                "status": "WARN",
                "summary": "Optional secret handles are still unassigned.",
            }
        ],
        rollback_result=ProviderInstallationRollbackResult(
            status="NOT_REQUIRED",
            summary="Recorded executor does not mutate host state; rollback is not required.",
        ),
        created_at="2026-07-17T12:00:00Z",
    )

    assert diagnostics.readiness_status == "ACTION_REQUIRED"
    assert diagnostics.checks[0].status == "WARN"
    assert diagnostics.rollback_result.status == "NOT_REQUIRED"


def test_provider_installation_execution_result_contains_provider_instance_payload() -> None:
    result = ProviderInstallationExecutionResult(
        step_results=[
            ProviderInstallationStepResult(
                step_id="register-provider",
                step_type="provider_instance",
                status="RECORDED",
                summary="Registered provider instance",
            )
        ],
        provider_instance={
            "provider_instance_id": "pi-ollama",
            "plugin_id": "aidn.provider.ollama",
            "provider_family": "ollama",
            "display_name": "Local Ollama",
            "connection_mode": "managed",
            "operational_state": "ready",
        },
        rollback_result=ProviderInstallationRollbackResult(
            status="NOT_REQUIRED",
            summary="Recorded executor does not mutate host state; rollback is not required.",
        ),
    )

    assert result.provider_instance["provider_instance_id"] == "pi-ollama"
    assert result.step_results[0].step_id == "register-provider"
    assert result.rollback_result.status == "NOT_REQUIRED"


def test_provider_installation_execution_result_rejects_invalid_provider_instance_payload() -> None:
    try:
        ProviderInstallationExecutionResult(
            provider_instance={
                "provider_instance_id": "pi-ollama",
                "plugin_id": "aidn.provider.ollama",
                "provider_family": "ollama",
                "display_name": "Local Ollama",
                "connection_mode": "managed",
            },
        )
    except ValidationError as exc:
        assert "operational_state" in str(exc)
    else:
        raise AssertionError("expected ValidationError")


def test_provider_installation_rollback_result_tracks_step_results() -> None:
    rollback = ProviderInstallationRollbackResult(
        status="COMPLETED",
        summary="Rollback finished.",
        details={"executor_id": "recorded-declarative-v1"},
        step_results=[
            ProviderInstallationStepResult(
                step_id="rollback-delete-local-provider-instance",
                step_type="rollback_local_inventory_delete",
                status="RECORDED",
                summary="Removed local provider inventory state.",
                details={"provider_instance_id": "pi-1"},
            )
        ],
    )

    assert rollback.step_results[0].step_type == "rollback_local_inventory_delete"
    assert rollback.step_results[0].details["provider_instance_id"] == "pi-1"


def test_provider_installation_job_tracks_rollback_execution_metadata() -> None:
    job = ProviderInstallationJob(
        job_id="job-rollback",
        approval_id="approval-rollback",
        plugin_id="aidn.provider.fake",
        plan_id="plan-rollback",
        plan_hash="sha256:plan",
        configuration_hash="sha256:configuration",
        status="FAILED",
        executor_id="recorded-declarative-v1",
        rollback_status="COMPLETED",
        rollback_summary="Rollback finished.",
        rollback_started_at="2026-07-17T12:00:00Z",
        rollback_completed_at="2026-07-17T12:00:01Z",
        rollback_step_results=[
            ProviderInstallationStepResult(
                step_id="rollback-delete-local-provider-instance",
                step_type="rollback_local_inventory_delete",
                status="RECORDED",
                summary="Removed local provider inventory state.",
                details={"provider_instance_id": "pi-1"},
            )
        ],
        created_at="2026-07-17T11:59:00Z",
    )

    assert job.rollback_status == "COMPLETED"
    assert job.rollback_started_at == "2026-07-17T12:00:00Z"
    assert job.rollback_completed_at == "2026-07-17T12:00:01Z"
    assert job.rollback_step_results[0].step_id == "rollback-delete-local-provider-instance"
