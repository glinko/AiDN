import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.endpoints.models import EndpointMarketplaceDescription

PublicationStatus = Literal["published", "superseded", "revoked"]


def canonical_configuration_payload(
    *,
    bundle_hash: str,
    model_class: str,
    capabilities: list[str],
    runtime: dict,
    publication: dict,
    pricing: dict,
    session: dict | None = None,
    execution: dict | None = None,
    profile: dict | None = None,
    local_agent_use: bool | None = None,
) -> dict:
    payload = {
        "bundle_hash": bundle_hash,
        "model_class": model_class,
        "capabilities": sorted(capabilities),
        "runtime": runtime,
        "publication": publication,
        "pricing": pricing,
        "session": session or {},
        "execution": execution or {},
    }
    marketplace_description = (profile or {}).get("marketplace_description")
    if marketplace_description is not None:
        payload["marketplace_description"] = marketplace_description
    # False is the backwards-compatible default.  Commit the opt-in only
    # when it is enabled so pre-feature publication hashes remain valid.
    if local_agent_use:
        payload["local_agent_use"] = True
    return payload


def configuration_hash_for_publication(payload: dict) -> str:
    encoded_payload = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded_payload).hexdigest()


def legacy_canonical_configuration_payload(
    *,
    bundle_hash: str,
    model_class: str,
    capabilities: list[str],
    runtime: dict,
    publication: dict,
    pricing: dict,
    session: dict | None = None,
    execution: dict | None = None,
) -> dict:
    """Build the pre-marketplace-description publication payload.

    Nodes upgraded before marketplace HTML became part of the endpoint
    commitment still validate this payload shape.  Keeping the compatibility
    helper explicit lets a publisher retry against such a node without
    silently changing the current canonical format.
    """
    return canonical_configuration_payload(
        bundle_hash=bundle_hash,
        model_class=model_class,
        capabilities=capabilities,
        runtime=runtime,
        publication=publication,
        pricing=pricing,
        session=session,
        execution=execution,
    )


def legacy_configuration_hash_for_publication(
    *,
    bundle_hash: str,
    model_class: str,
    capabilities: list[str],
    runtime: dict,
    publication: dict,
    pricing: dict,
    session: dict | None = None,
    execution: dict | None = None,
) -> str:
    """Return the compatibility hash accepted by pre-marketplace nodes."""
    return configuration_hash_for_publication(
        legacy_canonical_configuration_payload(
            bundle_hash=bundle_hash,
            model_class=model_class,
            capabilities=capabilities,
            runtime=runtime,
            publication=publication,
            pricing=pricing,
            session=session,
            execution=execution,
        )
    )


class PublishedEndpointConfiguration(BaseModel):
    schema_version: str = "epcfg.v1"
    publication_id: str
    endpoint_id: str
    owner_wallet: str
    owner_public_key: str | None = None
    node_id: str
    configuration_hash: str
    previous_configuration_hash: str | None = None
    bundle_id: str
    bundle_hash: str
    model_class: str
    capabilities: list[str] = Field(default_factory=list)
    # ``None`` preserves the signed payload shape of publications created
    # before Local Agent Use existed.  A true value is the explicit opt-in.
    local_agent_use: bool | None = None
    profile: dict = Field(default_factory=dict)
    runtime: dict = Field(default_factory=dict)
    publication: dict = Field(default_factory=dict)
    pricing: dict = Field(default_factory=dict)
    session: dict = Field(default_factory=dict)
    execution: dict = Field(default_factory=dict)
    validation_requirement: dict = Field(default_factory=dict)
    published_at: str
    sequence: int = Field(ge=1)
    status: PublicationStatus = "published"
    wallet_signature: str

    @model_validator(mode="before")
    @classmethod
    def _sanitize_marketplace_description(cls, value):
        if not isinstance(value, dict):
            return value
        profile = value.get("profile")
        if not isinstance(profile, dict):
            return value
        marketplace_description = profile.get("marketplace_description")
        if marketplace_description is None:
            return value
        normalized_profile = dict(profile)
        normalized_profile["marketplace_description"] = (
            EndpointMarketplaceDescription.model_validate(marketplace_description)
            .model_dump(mode="json")
        )
        normalized = dict(value)
        normalized["profile"] = normalized_profile
        return normalized

    @model_validator(mode="after")
    def _validate_configuration_hash(self):
        expected_hashes = {
            configuration_hash_for_publication(
                canonical_configuration_payload(
                    bundle_hash=self.bundle_hash,
                    model_class=self.model_class,
                    capabilities=self.capabilities,
                    runtime=self.runtime,
                    publication=self.publication,
                    pricing=self.pricing,
                    session=self.session,
                    execution=self.execution,
                    profile=self.profile,
                    local_agent_use=self.local_agent_use,
                )
            )
        }
        # A rolling upgrade may submit a marketplace description to a
        # validator that predates the field.  Accept the old commitment while
        # the network converges; the payload remains fully signed and the
        # description is still retained in the publication record.
        if self.profile.get("marketplace_description") is not None:
            expected_hashes.add(
                legacy_configuration_hash_for_publication(
                    bundle_hash=self.bundle_hash,
                    model_class=self.model_class,
                    capabilities=self.capabilities,
                    runtime=self.runtime,
                    publication=self.publication,
                    pricing=self.pricing,
                    session=self.session,
                    execution=self.execution,
                )
            )
        if self.configuration_hash not in expected_hashes:
            raise ValueError("configuration_hash does not match canonical payload")
        return self

    def signed_payload(self) -> dict:
        payload = self.model_dump(mode="json")
        payload.pop("wallet_signature", None)
        # Do not add a null/false field to legacy signatures.  New opt-in
        # publications carry ``true`` and therefore remain cryptographically
        # bound to the capability.
        if not self.local_agent_use:
            payload.pop("local_agent_use", None)
        return payload
