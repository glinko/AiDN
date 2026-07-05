from aidn_hypervisor.canonical_models import (
    CanonicalCapabilityRuntimeRecord,
    CanonicalComputeCompatibilityRecord,
    CanonicalProtocolServiceRecord,
)

_CAPABILITY_BY_WORKLOAD = {
    "llm_text": "llm.chat",
    "speech_to_text": "speech.stt",
}


def _capability_id_for_bundle(bundle) -> str:
    return _CAPABILITY_BY_WORKLOAD.get(bundle.workload_type, bundle.workload_type)


def project_protocol_services(service) -> list[CanonicalProtocolServiceRecord]:
    registry_enabled = service.registry_enabled()
    validation_enabled = service.validation_enabled()
    return [
        CanonicalProtocolServiceRecord(
            service_id="compute",
            kind="compute",
            enabled=True,
            derived_roles=["compute_provider"],
            responsibilities=[
                "provider_management",
                "endpoint_hosting",
                "session_execution",
                "marketplace_integration",
            ],
        ),
        CanonicalProtocolServiceRecord(
            service_id="registry",
            kind="registry",
            enabled=registry_enabled,
            derived_roles=["registry_operator"] if registry_enabled else [],
            responsibilities=[
                "ledger_storage",
                "snapshot_distribution",
                "historical_lookup",
            ],
        ),
        CanonicalProtocolServiceRecord(
            service_id="validation",
            kind="validation",
            enabled=validation_enabled,
            derived_roles=["validator"] if validation_enabled else [],
            responsibilities=["endpoint_validation", "validation_reporting"],
        ),
        CanonicalProtocolServiceRecord(
            service_id="consensus",
            kind="consensus",
            enabled=False,
            derived_roles=[],
            responsibilities=[
                "block_proposal",
                "block_validation",
                "ledger_finalization",
            ],
        ),
    ]


def project_capability_runtimes(service) -> list[CanonicalCapabilityRuntimeRecord]:
    runtime_by_bundle = {runtime.bundle_id: runtime for runtime in service.list_runtimes()}
    records: list[CanonicalCapabilityRuntimeRecord] = []
    for bundle in service.bundles:
        runtime = runtime_by_bundle.get(bundle.bundle_id)
        records.append(
            CanonicalCapabilityRuntimeRecord(
                runtime_id=f"runtime-{bundle.bundle_id}",
                capability_id=_capability_id_for_bundle(bundle),
                runtime_version="legacy.bundle.v1",
                protocol_version="runtime.v1",
                location_kind="local_process",
                health_status=(
                    runtime.health_status if runtime is not None else "unavailable"
                ),
                supported_features=["legacy_bundle_compatibility"],
            )
        )
    return records


def project_compute_compatibility(service) -> list[CanonicalComputeCompatibilityRecord]:
    records: list[CanonicalComputeCompatibilityRecord] = []
    for bundle in service.bundles:
        records.append(
            CanonicalComputeCompatibilityRecord(
                compatibility_id=f"bundle:{bundle.bundle_id}",
                legacy_bundle_id=bundle.bundle_id,
                legacy_plugin_id=bundle.plugin_id,
                legacy_provider_type=bundle.provider_type,
                canonical_capability_id=_capability_id_for_bundle(bundle),
                canonical_runtime_id=f"runtime-{bundle.bundle_id}",
            )
        )
    return records
