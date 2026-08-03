"""Read-only acceptance verification for an externally operated CometBFT network."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from .cometbft import (
    CometBftRpcFinalitySource,
    CometBftRpcLightClientProofVerifier,
    HttpCometBftRpcTransport,
)
from .cometbft_crypto import Zip215CometBftEd25519Backend
from .finality import ConsensusFinalityEvidence
from .light_client import CometBftLightClient, CometBftValidator, CometBftValidatorSet, TrustedCometBftCheckpoint


class ExternalCometBftValidatorConfig(BaseModel, frozen=True):
    address: str = Field(min_length=1)
    public_key: str = Field(min_length=1)
    voting_power: int = Field(gt=0)


class ExternalCometBftCheckpointConfig(BaseModel, frozen=True):
    height: int = Field(gt=0)
    block_id: str = Field(min_length=1)
    app_hash: str
    header_time: str = Field(min_length=1)
    validator_set_hash: str = Field(min_length=1)
    next_validator_set_hash: str = Field(min_length=1)
    validators: list[ExternalCometBftValidatorConfig] = Field(min_length=1)


class ExternalCometBftAcceptanceConfig(BaseModel, frozen=True):
    """Operator-supplied immutable inputs for a read-only testnet check."""

    rpc_endpoints: list[str] = Field(min_length=2, max_length=16)
    chain_id: str = Field(min_length=1)
    verifier_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    transaction_hash: str = Field(pattern=r"^[0-9A-Fa-f]{64}$")
    trusted_checkpoint: ExternalCometBftCheckpointConfig
    trust_period_seconds: int = Field(gt=0)
    timeout_seconds: int = Field(default=10, gt=0, le=120)
    validator_page_size: int = Field(default=100, ge=1, le=100)
    maximum_validators: int = Field(default=10_000, ge=1, le=100_000)

    @field_validator("rpc_endpoints")
    @classmethod
    def _https_endpoints(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise ValueError("external CometBFT RPC endpoint must be credential-free HTTPS")
            normalized.append(value.rstrip("/"))
        if len(set(normalized)) != len(normalized):
            raise ValueError("external CometBFT RPC endpoints must be unique")
        return normalized

    @model_validator(mode="after")
    def _validator_bound(self):
        if self.maximum_validators < self.validator_page_size:
            raise ValueError("maximum_validators must not be below validator_page_size")
        return self

    def trusted_checkpoint_model(self) -> TrustedCometBftCheckpoint:
        validator_set = CometBftValidatorSet(
            tuple(
                CometBftValidator(
                    address=validator.address,
                    public_key=validator.public_key,
                    voting_power=validator.voting_power,
                )
                for validator in self.trusted_checkpoint.validators
            )
        )
        return TrustedCometBftCheckpoint(
            chain_id=self.chain_id,
            height=self.trusted_checkpoint.height,
            block_id=self.trusted_checkpoint.block_id,
            app_hash=self.trusted_checkpoint.app_hash,
            header_time=self.trusted_checkpoint.header_time,
            validator_set=validator_set,
            validator_set_hash=self.trusted_checkpoint.validator_set_hash,
            next_validator_set_hash=self.trusted_checkpoint.next_validator_set_hash,
        )


def verify_external_cometbft_acceptance(
    *,
    config: ExternalCometBftAcceptanceConfig,
    evidence_loader: Callable[[str], ConsensusFinalityEvidence | None] | None = None,
) -> dict[str, Any]:
    """Verify one already-finalized operation from multiple independent RPC views.

    This function never submits transactions and never controls validators. It
    proves cryptographic finality relative to the supplied trusted checkpoint
    and rejects divergent RPC views. Endpoint ownership remains out of band.
    """
    loader = evidence_loader or _default_evidence_loader(config)
    evidence_by_endpoint: list[tuple[str, ConsensusFinalityEvidence]] = []
    for endpoint in config.rpc_endpoints:
        evidence = loader(endpoint)
        if evidence is None:
            raise ValueError(f"external CometBFT endpoint did not verify finality: {endpoint}")
        if not isinstance(evidence, ConsensusFinalityEvidence):
            raise ValueError("external CometBFT evidence type is invalid")
        if evidence.operation_id != config.operation_id or evidence.chain_id != config.chain_id:
            raise ValueError("external CometBFT evidence identity does not match acceptance config")
        evidence_by_endpoint.append((endpoint, evidence))
    expected = evidence_by_endpoint[0][1]
    expected_fingerprint = _evidence_fingerprint(expected)
    for _, evidence in evidence_by_endpoint[1:]:
        if _evidence_fingerprint(evidence) != expected_fingerprint:
            raise ValueError("external CometBFT RPC endpoints disagree on finalized evidence")
    return {
        "status": "ok",
        "finality_evidence": expected.model_dump(),
        "rpc_endpoints": [endpoint for endpoint, _ in evidence_by_endpoint],
        "ownership_evidence": {
            "status": "NOT_PROVEN_BY_PROTOCOL",
            "reason": "Multiple RPC endpoints can agree while remaining under one operator control.",
        },
    }


def _evidence_fingerprint(evidence: ConsensusFinalityEvidence) -> tuple[object, ...]:
    """Compare all canonical finality fields while ignoring verifier identity."""
    return (
        evidence.operation_id,
        evidence.chain_id,
        evidence.block_height,
        evidence.block_id,
        evidence.app_hash,
        evidence.commit_hash,
        evidence.finalized_at,
        evidence.proof_version,
    )


def _default_evidence_loader(
    config: ExternalCometBftAcceptanceConfig,
) -> Callable[[str], ConsensusFinalityEvidence | None]:
    checkpoint = config.trusted_checkpoint_model()

    def load(endpoint: str) -> ConsensusFinalityEvidence | None:
        light_client = CometBftLightClient(
            checkpoint=checkpoint,
            cryptography=Zip215CometBftEd25519Backend(),
            trust_period_seconds=config.trust_period_seconds,
        )
        transport = HttpCometBftRpcTransport(endpoint)
        verifier = CometBftRpcLightClientProofVerifier(
            light_client=light_client,
            transport=transport,
            timeout_seconds=config.timeout_seconds,
            per_page=config.validator_page_size,
            maximum_validators=config.maximum_validators,
        )
        source = CometBftRpcFinalitySource(
            chain_id=config.chain_id,
            transaction_hash_for_operation=lambda _: config.transaction_hash.upper(),
            proof_verifier=verifier,
            transport=transport,
            verifier_id=config.verifier_id,
            timeout_seconds=config.timeout_seconds,
        )
        return source.finality_evidence(config.operation_id)

    return load
