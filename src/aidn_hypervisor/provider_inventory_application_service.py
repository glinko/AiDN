from __future__ import annotations

from aidn_hypervisor.bundle_hash import bundle_config_hash
from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile
from aidn_hypervisor.runtime_parameter_policy import (
    normalize_runtime_parameter_policy,
)


class ProviderInventoryApplicationService:
    """Provider inventory, wallet identity, and artifact orchestration facade."""

    def __init__(self, host) -> None:
        self._host = host

    def register_wallet_identity(
        self,
        *,
        wallet_id: str,
        public_key: str,
        registration_nonce: str,
        signature: str,
    ) -> dict:
        from aidn_hypervisor.canonical_projection import project_registry_objects
        from aidn_hypervisor.wallet_identity import verify_wallet_identity_registration

        identity = verify_wallet_identity_registration(
            wallet_id=wallet_id,
            public_key=public_key,
            registration_nonce=registration_nonce,
            signature=signature,
        )
        existing = self._host._wallet_identities.get(wallet_id)
        if existing is not None:
            if existing["public_key"] != public_key:
                raise ValueError("Wallet identity key rotation is not supported")
            if existing["registration_nonce"] != registration_nonce:
                raise ValueError("Wallet identity registration nonce was already consumed")
            return dict(existing)
        self._host._wallet_identities[wallet_id] = identity.model_dump(mode="json")
        self._host.record_ledger_operation(
            operation_type="WALLET_IDENTITY_REGISTER",
            origin_type="wallet",
            fee_class="onboarding_exempt",
            initiator_id=wallet_id,
            sender_wallet=wallet_id,
            payload={
                "wallet_id": wallet_id,
                "public_key": public_key,
                "registration_nonce": registration_nonce,
            },
            signatures=[signature],
            emitted_events=["WalletIdentityRegistered"],
        )
        registry_service = self._host.registry_service
        if registry_service is not None:
            registry_service.ingest_registry_objects(
                [
                    record.model_dump(mode="json")
                    for record in project_registry_objects(self._host, [])
                    if record.object_type == "wallet_identity"
                    and record.source_reference == wallet_id
                ]
            )
        self._host._persist_state()
        return dict(self._host._wallet_identities[wallet_id])

    def wallet_identity(self, wallet_id: str) -> dict | None:
        identity = self._host._wallet_identities.get(wallet_id)
        return dict(identity) if identity is not None else None

    def resolve_wallet_identity(self, wallet_id: str) -> dict | None:
        local_identity = self.wallet_identity(wallet_id)
        if local_identity is not None:
            return local_identity
        registry_service = self._host.registry_service
        if registry_service is None:
            return None
        return registry_service.resolve_wallet_identity(wallet_id)

    def list_wallet_identities(self) -> list[dict]:
        return [
            dict(self._host._wallet_identities[wallet_id])
            for wallet_id in sorted(self._host._wallet_identities)
        ]

    def list_provider_installation_artifacts(self) -> dict:
        return self._host.provider_inventory.installation_artifact_inventory().model_dump(
            mode="json"
        )

    def stage_provider_installation_artifact(
        self,
        *,
        relative_path: str,
        content_bytes: bytes,
    ) -> dict:
        artifact = self._host.provider_inventory.stage_local_artifact(
            relative_path=relative_path,
            content_bytes=content_bytes,
        )
        return artifact.model_dump(mode="json")

    def delete_provider_installation_artifact(self, *, relative_path: str) -> dict:
        self._host.provider_inventory.delete_local_artifact(relative_path=relative_path)
        return {"relative_path": relative_path, "deleted": True}

    def extract_provider_installation_artifact_archive(
        self,
        *,
        archive_relative_path: str,
        destination_directory: str,
    ) -> dict:
        result = self._host.provider_inventory.extract_local_artifact_archive(
            archive_relative_path=archive_relative_path,
            destination_directory=destination_directory,
        )
        return result.model_dump(mode="json")

    def list_model_artifacts(self) -> dict:
        return self._host.provider_inventory.model_artifact_inventory().model_dump(
            mode="json"
        )

    def promote_provider_installation_artifact_to_model_store(
        self,
        *,
        relative_path: str,
    ) -> dict:
        artifact = self._host.provider_inventory.promote_local_artifact_to_model_store(
            relative_path=relative_path,
        )
        return artifact.model_dump(mode="json")

    def delete_model_artifact(self, *, artifact_id: str) -> dict:
        self._host.provider_inventory.delete_model_artifact(artifact_id=artifact_id)
        return {"artifact_id": artifact_id, "deleted": True}

    def list_model_artifact_sets(self) -> list[dict]:
        return [
            item.model_dump(mode="json")
            for item in self._host.provider_inventory.list_model_artifact_sets()
        ]

    def create_model_artifact_set(self, *, display_name: str, files: list[dict]) -> dict:
        artifact_set = self._host.provider_inventory.create_model_artifact_set(
            display_name=display_name,
            files=files,
        )
        return artifact_set.model_dump(mode="json")

    def delete_model_artifact_set(self, *, artifact_set_id: str) -> dict:
        self._host.provider_inventory.delete_model_artifact_set(
            artifact_set_id=artifact_set_id
        )
        return {"artifact_set_id": artifact_set_id, "deleted": True}

    def bind_model_artifact_set(
        self,
        *,
        model_deployment_id: str,
        artifact_set_id: str,
    ) -> dict:
        deployment = self._host.provider_inventory.bind_model_artifact_set(
            model_deployment_id=model_deployment_id,
            artifact_set_id=artifact_set_id,
        )
        self._host._persist_state()
        return deployment.model_dump(mode="json")

    def collect_model_artifact_garbage(self) -> dict:
        return self._host.provider_inventory.collect_model_artifact_garbage().model_dump(
            mode="json"
        )

    def materialize_model_artifact_set(
        self,
        *,
        provider_instance_id: str,
        artifact_set_id: str,
        destination: str,
    ) -> dict:
        result = self._host.provider_inventory.materialize_model_artifact_set(
            provider_instance_id=provider_instance_id,
            artifact_set_id=artifact_set_id,
            destination=destination,
        )
        self._host._persist_state()
        return result.model_dump(mode="json")

    def list_model_artifact_materializations(self) -> list[dict]:
        return [
            item.model_dump(mode="json")
            for item in self._host.provider_inventory.list_artifact_materializations()
        ]

    def discover_provider_models(self, provider_instance_id: str) -> list[dict]:
        deployments = self._host.provider_inventory.discover_models(provider_instance_id)
        self._host._persist_state()
        return [deployment.model_dump(mode="json") for deployment in deployments]

    def probe_provider_instance(self, provider_instance_id: str) -> dict:
        result = self._host.provider_inventory.probe_provider_instance(
            provider_instance_id
        )
        self._host._persist_state()
        return result

    def create_runtime_binding(
        self,
        *,
        model_deployment_id: str,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> dict:
        binding = self._host.provider_inventory.create_runtime_binding(
            model_deployment_id=model_deployment_id,
            capability_id=capability_id,
            capability_version=capability_version,
            capability_definition_hash=capability_definition_hash,
        )
        self._host._replace_bundle(
            self._host.provider_inventory.bundle_config_for_runtime_binding(
                binding.runtime_binding_id
            )
        )
        self._host._persist_bundle_config_if_available()
        self._host._persist_state()
        return binding.model_dump(mode="json")

    def bundle_for_runtime_binding(self, runtime_binding_id: str) -> BundleConfig:
        return self._host.provider_inventory.bundle_config_for_runtime_binding(
            runtime_binding_id
        )

    def bundle_hash_for_runtime_binding(self, runtime_binding_id: str) -> str:
        return self._host.provider_inventory.bundle_hash_for_runtime_binding(
            runtime_binding_id
        )

    def runtime_binding_endpoint_admission(
        self,
        runtime_binding_id: str,
        endpoint_payload: dict | None = None,
    ) -> dict:
        return self._host.provider_inventory.runtime_binding_endpoint_admission(
            runtime_binding_id=runtime_binding_id,
            endpoint_payload=endpoint_payload,
        )

    def mark_model_install_completed(self, install_id: str) -> dict:
        job = self._host._model_installs[install_id]
        job["status"] = "completed"
        job["last_error"] = None
        self._host.record_event(
            event_type="model.install.completed",
            message="model install marked completed",
            details={"install_id": install_id},
        )
        self._host._persist_state()
        return dict(job)

    def register_bundle_from_install(
        self,
        *,
        install_id: str,
        bundle_id: str,
        workload_type: str,
        endpoint: str,
        runtime_parameter_policy: dict | None = None,
    ) -> dict:
        if any(bundle.bundle_id == bundle_id for bundle in self._host.bundles):
            raise ValueError(f"Bundle already exists: {bundle_id}")
        job = self._host._model_installs[install_id]
        if job["status"] != "completed":
            raise ValueError(f"Model install is not completed: {install_id}")

        plugin = self._host._get_plugin(job["provider_type"])
        provider_model_id = str(
            job.get("provider_model_reference") or job["model_id"]
        )
        defaults = plugin.bundle_defaults_from_install(
            model_id=provider_model_id,
            target_path=str(job["target_path"]),
        )
        selected_policy = runtime_parameter_policy
        if selected_policy is None:
            selected_policy = job.get("runtime_parameter_policy")
        normalized_policy = normalize_runtime_parameter_policy(
            str(job["provider_type"]), selected_policy
        ) if workload_type == "llm_text" else {}
        bundle = BundleConfig(
            bundle_id=bundle_id,
            plugin_id=plugin.plugin_id,
            provider_type=str(job["provider_type"]),
            workload_type=workload_type,
            model_id=str(defaults["model_id"]),
            launch_mode=str(defaults["launch_mode"]),
            endpoint=endpoint,
            device_affinity=str(defaults["device_affinity"]),
            resource_profile=ResourceProfile(),
            warm_policy="auto",
            priority_class=50,
            max_parallel_requests=1,
            enabled=True,
            runtime_parameter_policy=normalized_policy,
        )
        plugin.validate_bundle(bundle)
        bundle = bundle.model_copy(update={"bundle_hash": bundle_config_hash(bundle)})
        self._host.bundles.append(bundle)
        job["status"] = "registered"
        job["bundle_id"] = bundle_id
        self._host.record_event(
            event_type="bundle.registered_from_install",
            message="bundle registered from installed model artifact",
            bundle_id=bundle.bundle_id,
            details={"install_id": install_id, "provider_type": job["provider_type"]},
        )
        self._host._persist_bundle_config_if_available()
        self._host._persist_state()
        return bundle.model_dump(mode="json")
