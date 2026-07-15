from pydantic import ValidationError

from aidn_hypervisor.providers.models import (
    InstallationPlan,
    InstallationRecipe,
    ModelDeployment,
    PluginPermission,
    PluginSecretRequirement,
    PluginTrustStatus,
    PluginUISchema,
    ProviderInstallationApproval,
    ProviderInstallationExecutionResult,
    ProviderInstallationJob,
    ProviderInstallationStepResult,
    ProviderInstance,
    ProviderPluginManifest,
    RuntimeBinding,
)


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
    assert manifest.required_permissions[0].permission_id == "container.manage"
    assert manifest.install_ui_schema.fields[0]["id"] == "model_storage_path"
    assert manifest.secret_requirements[0].secret_type == "API_KEY"
    assert manifest.installation_recipes[0].recipe_id == "ollama-qwen3-8b"


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
        acknowledged_secret_requirements=[
            {
                "secret_type": "API_KEY",
                "label": "Optional upstream API key",
            }
        ],
        operator_note="Approved for local install",
        created_at="2026-07-15T12:00:00Z",
    )

    assert approval.plan_id == "plan-ollama"
    assert approval.plan_hash == "sha256:plan"
    assert approval.configuration_hash == "sha256:configuration"
    assert approval.status == "APPROVED"
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
    )

    assert result.provider_instance["provider_instance_id"] == "pi-ollama"
    assert result.step_results[0].step_id == "register-provider"


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
