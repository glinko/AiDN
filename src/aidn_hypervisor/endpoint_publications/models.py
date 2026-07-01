import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

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
) -> dict:
    return {
        "bundle_hash": bundle_hash,
        "model_class": model_class,
        "capabilities": sorted(capabilities),
        "runtime": runtime,
        "publication": publication,
        "pricing": pricing,
        "session": session or {},
        "execution": execution or {},
    }


def configuration_hash_for_publication(payload: dict) -> str:
    encoded_payload = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded_payload).hexdigest()


class PublishedEndpointConfiguration(BaseModel):
    schema_version: str = "epcfg.v1"
    publication_id: str
    endpoint_id: str
    owner_wallet: str
    node_id: str
    configuration_hash: str
    previous_configuration_hash: str | None = None
    bundle_id: str
    bundle_hash: str
    model_class: str
    capabilities: list[str] = Field(default_factory=list)
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

    @model_validator(mode="after")
    def _validate_configuration_hash(self):
        expected_hash = configuration_hash_for_publication(
            canonical_configuration_payload(
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
        if self.configuration_hash != expected_hash:
            raise ValueError("configuration_hash does not match canonical payload")
        return self

    def signed_payload(self) -> dict:
        payload = self.model_dump(mode="json")
        payload.pop("wallet_signature", None)
        return payload
