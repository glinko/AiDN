import hashlib
import json

from aidn_hypervisor.accounting.models import AccountingContract, AccountingUnitContract
from aidn_hypervisor.canonical_models import (
    CanonicalAdvertisementRecord,
    CanonicalCapabilityRecord,
    CanonicalCapabilityRuntimeRecord,
    CanonicalComputeCompatibilityRecord,
    CanonicalEndpointFeatureProfileRecord,
    CanonicalEndpointImplementationProfileRecord,
    CanonicalEndpointLimitProfileRecord,
    CanonicalProtocolServiceRecord,
    CanonicalRegistryObjectRecord,
    CanonicalWalletIdentityRecord,
)

_CAPABILITY_BY_WORKLOAD = {
    "llm_text": "llm.chat",
    "speech_to_text": "speech.stt",
}
_CAPABILITY_DEFINITION_DEFAULTS = {
    "llm.chat": {
        "capability_version": "2.0.0",
        "request_schema_seed": "request.chat.v2",
        "response_schema_seed": "response.chat.v2",
        "state_model": "session_optional",
        "streaming_model": "text_stream",
        "side_effect_model": "none",
        "input_modalities": ["text"],
        "output_modalities": ["text"],
    },
    "speech.stt": {
        "capability_version": "1.0.0",
        "request_schema_seed": "request.stt.v1",
        "response_schema_seed": "response.stt.v1",
        "state_model": "stateless",
        "streaming_model": "segment_stream",
        "side_effect_model": "none",
        "input_modalities": ["audio"],
        "output_modalities": ["text"],
    },
}
_DEFAULT_CAPABILITY_DEFINITION = {
    "capability_version": "1.0.0",
    "request_schema_seed": "request.generic.v1",
    "response_schema_seed": "response.generic.v1",
    "state_model": "stateless",
    "streaming_model": "best_effort",
    "side_effect_model": "none",
    "input_modalities": ["text"],
    "output_modalities": ["text"],
}


def _stable_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _registry_object_id(*, object_type: str, object_version: str, payload_hash: str) -> str:
    return _stable_hash(
        {
            "object_type": object_type,
            "object_version": object_version,
            "payload_hash": payload_hash,
        }
    )


def _registry_object_record(
    *,
    object_type: str,
    object_version: str,
    namespace: str,
    payload_hash: str,
    source_reference: str,
    payload: dict | None = None,
) -> CanonicalRegistryObjectRecord:
    return CanonicalRegistryObjectRecord(
        object_id=_registry_object_id(
            object_type=object_type,
            object_version=object_version,
            payload_hash=payload_hash,
        ),
        object_type=object_type,
        object_version=object_version,
        namespace=namespace,
        payload_hash=payload_hash,
        payload_encoding="canonical_json",
        source_reference=source_reference,
        payload=payload,
    )


def _capability_definition_payload(
    capability: CanonicalCapabilityRecord,
) -> dict:
    return {
        "capability_id": capability.capability_id,
        "capability_version": capability.capability_version,
        "request_schema_hash": capability.request_schema_hash,
        "response_schema_hash": capability.response_schema_hash,
        "state_model": capability.state_model,
        "streaming_model": capability.streaming_model,
        "side_effect_model": capability.side_effect_model,
        "input_modalities": list(capability.input_modalities),
        "output_modalities": list(capability.output_modalities),
    }


def _accounting_contract_payload(contract: dict) -> dict:
    return {
        "contract_version": contract["contract_version"],
        "capability_id": contract.get("capability_id"),
        "pricing_version": contract["pricing_version"],
        "pricing_policy_reference": contract.get("pricing_policy_reference"),
        "billable_units": list(contract.get("billable_units", [])),
        "checkpoint_policy": contract["checkpoint_policy"],
        "maximum_unreported_usage": contract.get("maximum_unreported_usage"),
        "maximum_request_charge": contract.get("maximum_request_charge"),
        "failure_pricing_policy": contract["failure_pricing_policy"],
    }


def _feature_profile_payload(
    feature_profile: CanonicalEndpointFeatureProfileRecord,
) -> dict:
    return {
        "endpoint_id": feature_profile.endpoint_id,
        "advertisement_id": feature_profile.advertisement_id,
        "configuration_hash": feature_profile.configuration_hash,
        "capability_id": feature_profile.capability_id,
        "supported_features": list(feature_profile.supported_features),
        "unsupported_features": list(feature_profile.unsupported_features),
    }


def _implementation_profile_payload(
    implementation_profile: CanonicalEndpointImplementationProfileRecord,
) -> dict:
    return {
        "endpoint_id": implementation_profile.endpoint_id,
        "advertisement_id": implementation_profile.advertisement_id,
        "configuration_hash": implementation_profile.configuration_hash,
        "capability_id": implementation_profile.capability_id,
        "runtime_id": implementation_profile.runtime_id,
        "execution_strategy": implementation_profile.execution_strategy,
        "publication_visibility": implementation_profile.publication_visibility,
        "validation_enabled": implementation_profile.validation_enabled,
        "session_queue_policy": implementation_profile.session_queue_policy,
    }


def _wallet_identity_binding_payload(identity: dict) -> dict:
    return {
        "wallet_id": identity["wallet_id"],
        "public_key": identity["public_key"],
        "registration_nonce": identity["registration_nonce"],
    }


def _limit_profile_payload(
    limit_profile: CanonicalEndpointLimitProfileRecord,
) -> dict:
    return {
        "endpoint_id": limit_profile.endpoint_id,
        "advertisement_id": limit_profile.advertisement_id,
        "configuration_hash": limit_profile.configuration_hash,
        "capability_id": limit_profile.capability_id,
        "max_context_units": limit_profile.max_context_units,
        "max_output_units": limit_profile.max_output_units,
        "max_request_duration_seconds": limit_profile.max_request_duration_seconds,
        "max_session_duration_seconds": limit_profile.max_session_duration_seconds,
    }


def _capability_id_for_bundle(bundle) -> str:
    return _CAPABILITY_BY_WORKLOAD.get(bundle.workload_type, bundle.workload_type)


def _primary_capability_id(publication) -> str | None:
    capabilities = getattr(publication, "capabilities", []) or []
    if not capabilities:
        return None
    return capabilities[0]


def _capability_definition_for_id(capability_id: str) -> CanonicalCapabilityRecord:
    defaults = dict(_DEFAULT_CAPABILITY_DEFINITION)
    defaults.update(_CAPABILITY_DEFINITION_DEFAULTS.get(capability_id, {}))
    request_schema_hash = _stable_hash(
        {"capability_id": capability_id, "schema": defaults["request_schema_seed"]}
    )
    response_schema_hash = _stable_hash(
        {"capability_id": capability_id, "schema": defaults["response_schema_seed"]}
    )
    definition_payload = {
        "capability_id": capability_id,
        "capability_version": defaults["capability_version"],
        "request_schema_hash": request_schema_hash,
        "response_schema_hash": response_schema_hash,
        "state_model": defaults["state_model"],
        "streaming_model": defaults["streaming_model"],
        "side_effect_model": defaults["side_effect_model"],
        "input_modalities": defaults["input_modalities"],
        "output_modalities": defaults["output_modalities"],
    }
    return CanonicalCapabilityRecord(
        capability_id=capability_id,
        capability_version=defaults["capability_version"],
        capability_definition_hash=_stable_hash(definition_payload),
        request_schema_hash=request_schema_hash,
        response_schema_hash=response_schema_hash,
        state_model=defaults["state_model"],
        streaming_model=defaults["streaming_model"],
        side_effect_model=defaults["side_effect_model"],
        input_modalities=list(defaults["input_modalities"]),
        output_modalities=list(defaults["output_modalities"]),
    )


def _accounting_contract_for_publication(service, publication) -> dict:
    bundle = service._get_bundle(publication.bundle_id)
    usage_contract = {"default_measurement_source": "provider_report"}
    if hasattr(service.plugins, "get"):
        usage_contract = service._provider_usage_contract_for_bundle(bundle)
    capability_id = _primary_capability_id(publication)
    measurement_source = (
        usage_contract.get("default_measurement_source")
        or usage_contract.get("fallback_measurement_source")
        or "provider_report"
    )
    pricing = publication.pricing or {}
    session = publication.session or {}
    pricing_version = (
        f"pricing-{publication.endpoint_id}-{publication.configuration_hash[:8]}"
    )
    contract_version = (
        f"acct-{publication.endpoint_id}-{publication.configuration_hash[:8]}"
    )
    pricing_policy_reference = _stable_hash(
        {
            "endpoint_id": publication.endpoint_id,
            "configuration_hash": publication.configuration_hash,
            "pricing": pricing,
        }
    )
    billable_units: list[AccountingUnitContract] = []
    if pricing.get("input_price") is not None:
        billable_units.append(
            AccountingUnitContract(
                unit="input_tokens",
                mode="provider_metered",
                price=float(pricing["input_price"]),
                measurement_source=str(measurement_source),
                verification_method="provider_report",
            )
        )
    if pricing.get("output_price") is not None:
        billable_units.append(
            AccountingUnitContract(
                unit="output_tokens",
                mode="provider_metered",
                price=float(pricing["output_price"]),
                measurement_source=str(measurement_source),
                verification_method="provider_report",
            )
        )
    if pricing.get("audio_input_second_price") is not None:
        billable_units.append(
            AccountingUnitContract(
                unit="audio_input_seconds",
                mode="observable",
                price=float(pricing["audio_input_second_price"]),
                measurement_source="provider_response.duration",
                verification_method="provider_response",
                unavailable_value_policy="ZERO_VARIABLE_COMPONENT",
            )
        )
    if pricing.get("fixed_price") is not None:
        billable_units.append(
            AccountingUnitContract(
                unit="request_fee",
                mode="fixed_price",
                price=float(pricing["fixed_price"]),
                measurement_source="endpoint_policy",
                verification_method="fixed_contract",
            )
        )
    if float(session.get("idle_fee_per_minute", 0.0) or 0.0) > 0.0:
        billable_units.append(
            AccountingUnitContract(
                unit="idle_minutes",
                mode="observable",
                price=float(session["idle_fee_per_minute"]),
                measurement_source="session_activity",
                verification_method="session_timeline",
                rounding="per_minute",
            )
        )
    contract = AccountingContract(
        contract_version=contract_version,
        capability_id=capability_id,
        pricing_version=pricing_version,
        pricing_policy_reference=pricing_policy_reference,
        billable_units=billable_units,
        checkpoint_policy="per_request",
        maximum_unreported_usage=float(session.get("minimum_deposit", 0.0) or 0.0),
        maximum_request_charge=(
            float(session["recommended_deposit"])
            if session.get("recommended_deposit") is not None
            else float(session.get("minimum_deposit", 0.0) or 0.0)
        ),
        failure_pricing_policy="reject_unpriced_usage",
    )
    return contract.model_dump(mode="json")


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


def project_capability_definitions(service) -> list[CanonicalCapabilityRecord]:
    capability_ids = sorted({_capability_id_for_bundle(bundle) for bundle in service.bundles})
    return [_capability_definition_for_id(capability_id) for capability_id in capability_ids]


def project_endpoint_feature_profiles(
    publication_records,
) -> list[CanonicalEndpointFeatureProfileRecord]:
    records: list[CanonicalEndpointFeatureProfileRecord] = []
    for publication in publication_records:
        if publication.status != "published":
            continue
        capability_id = _primary_capability_id(publication)
        if capability_id is None:
            continue
        supported_features: list[str] = []
        runtime = publication.runtime or {}
        if runtime.get("streaming"):
            supported_features.append("streaming")
        if publication.publication.get("accepts_external_requests"):
            supported_features.append("external_requests")
        if publication.validation_requirement.get("enabled"):
            supported_features.append("validation")
        if publication.execution.get("strategy") == "proxy":
            supported_features.append("proxy_execution")
        if any(runtime.get(key) is not None for key in ("temperature", "top_p", "top_k")):
            supported_features.append("sampling_controls")
        feature_payload = {
            "endpoint_id": publication.endpoint_id,
            "advertisement_id": f"adv-{publication.publication_id}",
            "configuration_hash": publication.configuration_hash,
            "capability_id": capability_id,
            "supported_features": sorted(supported_features),
            "unsupported_features": [],
        }
        records.append(
            CanonicalEndpointFeatureProfileRecord(
                feature_profile_hash=_stable_hash(feature_payload),
                endpoint_id=publication.endpoint_id,
                advertisement_id=f"adv-{publication.publication_id}",
                configuration_hash=publication.configuration_hash,
                capability_id=capability_id,
                supported_features=sorted(supported_features),
                unsupported_features=[],
            )
        )
    return records


def project_endpoint_limit_profiles(
    publication_records,
) -> list[CanonicalEndpointLimitProfileRecord]:
    records: list[CanonicalEndpointLimitProfileRecord] = []
    for publication in publication_records:
        if publication.status != "published":
            continue
        capability_id = _primary_capability_id(publication)
        if capability_id is None:
            continue
        runtime = publication.runtime or {}
        session = publication.session or {}
        limit_payload = {
            "endpoint_id": publication.endpoint_id,
            "advertisement_id": f"adv-{publication.publication_id}",
            "configuration_hash": publication.configuration_hash,
            "capability_id": capability_id,
            "max_context_units": runtime.get("context_length"),
            "max_output_units": runtime.get("max_tokens"),
            "max_request_duration_seconds": runtime.get("timeout"),
            "max_session_duration_seconds": session.get("maximum_session_duration_seconds"),
        }
        records.append(
            CanonicalEndpointLimitProfileRecord(
                limit_profile_hash=_stable_hash(limit_payload),
                endpoint_id=publication.endpoint_id,
                advertisement_id=f"adv-{publication.publication_id}",
                configuration_hash=publication.configuration_hash,
                capability_id=capability_id,
                max_context_units=runtime.get("context_length"),
                max_output_units=runtime.get("max_tokens"),
                max_request_duration_seconds=runtime.get("timeout"),
                max_session_duration_seconds=session.get(
                    "maximum_session_duration_seconds"
                ),
            )
        )
    return records


def project_endpoint_implementation_profiles(
    publication_records,
) -> list[CanonicalEndpointImplementationProfileRecord]:
    records: list[CanonicalEndpointImplementationProfileRecord] = []
    for publication in publication_records:
        if publication.status != "published":
            continue
        capability_id = _primary_capability_id(publication)
        if capability_id is None:
            continue
        execution = publication.execution or {}
        session = publication.session or {}
        implementation_payload = {
            "endpoint_id": publication.endpoint_id,
            "advertisement_id": f"adv-{publication.publication_id}",
            "configuration_hash": publication.configuration_hash,
            "capability_id": capability_id,
            "runtime_id": f"runtime-{publication.bundle_id}",
            "execution_strategy": execution.get("strategy", "local"),
            "publication_visibility": publication.publication.get("visibility", "private"),
            "validation_enabled": bool(publication.validation_requirement.get("enabled")),
            "session_queue_policy": session.get("queue_policy"),
        }
        records.append(
            CanonicalEndpointImplementationProfileRecord(
                implementation_profile_hash=_stable_hash(implementation_payload),
                endpoint_id=publication.endpoint_id,
                advertisement_id=f"adv-{publication.publication_id}",
                configuration_hash=publication.configuration_hash,
                capability_id=capability_id,
                runtime_id=f"runtime-{publication.bundle_id}",
                execution_strategy=execution.get("strategy", "local"),
                publication_visibility=publication.publication.get("visibility", "private"),
                validation_enabled=bool(publication.validation_requirement.get("enabled")),
                session_queue_policy=session.get("queue_policy"),
            )
        )
    return records


def project_wallet_identities(service) -> list[CanonicalWalletIdentityRecord]:
    records: list[CanonicalWalletIdentityRecord] = []
    for identity in service.list_wallet_identities():
        binding_payload = _wallet_identity_binding_payload(identity)
        records.append(
            CanonicalWalletIdentityRecord(
                identity_hash=_stable_hash(binding_payload),
                wallet_id=str(identity["wallet_id"]),
                public_key=str(identity["public_key"]),
                registration_nonce=str(identity["registration_nonce"]),
                registered_at=str(identity["registered_at"]),
            )
        )
    return records


def project_registry_objects(
    service,
    publication_records,
) -> list[CanonicalRegistryObjectRecord]:
    records: list[CanonicalRegistryObjectRecord] = []
    for identity in project_wallet_identities(service):
        payload = {
            "wallet_id": identity.wallet_id,
            "public_key": identity.public_key,
            "registration_nonce": identity.registration_nonce,
        }
        records.append(
            _registry_object_record(
                object_type="wallet_identity",
                object_version="wallet-identity.v1",
                namespace="identity",
                payload_hash=identity.identity_hash,
                source_reference=identity.wallet_id,
                payload=payload,
            )
        )
    for capability in project_capability_definitions(service):
        records.append(
            _registry_object_record(
                object_type="capability_definition",
                object_version="capdef.v1",
                namespace="protocol",
                payload_hash=capability.capability_definition_hash,
                source_reference=capability.capability_id,
                payload=_capability_definition_payload(capability),
            )
        )
    for publication in publication_records:
        if publication.status != "published":
            continue
        contract = _accounting_contract_for_publication(service, publication)
        records.append(
            CanonicalRegistryObjectRecord(
                object_id=str(contract["registry_object_id"]),
                object_type="accounting_contract",
                object_version=str(contract["registry_object_version"]),
                namespace=str(contract["registry_namespace"]),
                payload_hash=str(contract["payload_hash"]),
                payload_encoding=str(contract["payload_encoding"]),
                source_reference=publication.endpoint_id,
                payload=_accounting_contract_payload(contract),
            )
        )
    for feature_profile in project_endpoint_feature_profiles(publication_records):
        records.append(
            _registry_object_record(
                object_type="endpoint_feature_profile",
                object_version="feature-profile.v1",
                namespace="marketplace",
                payload_hash=feature_profile.feature_profile_hash,
                source_reference=feature_profile.advertisement_id,
                payload=_feature_profile_payload(feature_profile),
            )
        )
    for implementation_profile in project_endpoint_implementation_profiles(
        publication_records
    ):
        records.append(
            _registry_object_record(
                object_type="endpoint_implementation_profile",
                object_version="implementation-profile.v1",
                namespace="marketplace",
                payload_hash=implementation_profile.implementation_profile_hash,
                source_reference=implementation_profile.advertisement_id,
                payload=_implementation_profile_payload(implementation_profile),
            )
        )
    for limit_profile in project_endpoint_limit_profiles(publication_records):
        records.append(
            _registry_object_record(
                object_type="endpoint_limit_profile",
                object_version="limit-profile.v1",
                namespace="marketplace",
                payload_hash=limit_profile.limit_profile_hash,
                source_reference=limit_profile.advertisement_id,
                payload=_limit_profile_payload(limit_profile),
            )
        )
    return records


def project_canonical_advertisements(
    publication_records,
) -> list[CanonicalAdvertisementRecord]:
    feature_profile_by_advertisement = {
        item.advertisement_id: item
        for item in project_endpoint_feature_profiles(publication_records)
    }
    limit_profile_by_advertisement = {
        item.advertisement_id: item for item in project_endpoint_limit_profiles(publication_records)
    }
    implementation_profile_by_advertisement = {
        item.advertisement_id: item
        for item in project_endpoint_implementation_profiles(publication_records)
    }
    records: list[CanonicalAdvertisementRecord] = []
    for publication in publication_records:
        if publication.status != "published":
            continue
        advertisement_id = f"adv-{publication.publication_id}"
        capability_id = _primary_capability_id(publication)
        capability_definition = (
            _capability_definition_for_id(capability_id) if capability_id is not None else None
        )
        feature_profile = feature_profile_by_advertisement.get(advertisement_id)
        limit_profile = limit_profile_by_advertisement.get(advertisement_id)
        implementation_profile = implementation_profile_by_advertisement.get(advertisement_id)
        records.append(
            CanonicalAdvertisementRecord(
                advertisement_id=advertisement_id,
                offer_id=f"offer-{publication.publication_id}",
                resource_type="endpoint",
                owner_wallet=publication.owner_wallet,
                hypervisor_id=publication.node_id,
                capability_id=capability_id,
                capability_version=(
                    capability_definition.capability_version
                    if capability_definition is not None
                    else None
                ),
                capability_definition_hash=(
                    capability_definition.capability_definition_hash
                    if capability_definition is not None
                    else None
                ),
                feature_profile_hash=(
                    feature_profile.feature_profile_hash
                    if feature_profile is not None
                    else None
                ),
                limit_profile_hash=(
                    limit_profile.limit_profile_hash if limit_profile is not None else None
                ),
                implementation_profile_hash=(
                    implementation_profile.implementation_profile_hash
                    if implementation_profile is not None
                    else None
                ),
                visibility=publication.publication.get("visibility", "private"),
                signature_scope="configuration_publication",
            )
        )
    return records
