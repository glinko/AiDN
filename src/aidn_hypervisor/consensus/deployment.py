"""Operator-controlled deployment configuration for CometBFT finality."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aidn_hypervisor.consensus.cometbft_finality import CometBftMultiRpcFinalityConfig
from aidn_hypervisor.consensus.light_client import (
    CometBftValidator,
    CometBftValidatorSet,
    TrustedCometBftCheckpoint,
)


class CometBftDeploymentValidator(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    address: str = Field(min_length=1)
    public_key: str = Field(min_length=1)
    voting_power: int = Field(gt=0)


class CometBftDeploymentCheckpoint(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    height: int = Field(gt=0)
    block_id: str = Field(min_length=1)
    app_hash: str
    header_time: str = Field(min_length=1)
    validator_set_hash: str = Field(min_length=1)
    next_validator_set_hash: str = Field(min_length=1)
    validators: list[CometBftDeploymentValidator] = Field(min_length=1)


class CometBftFinalityDeploymentConfig(BaseModel, frozen=True):
    """Persistable inputs required to activate a verified finality source."""

    model_config = ConfigDict(extra="forbid")

    rpc_endpoints: list[str] = Field(min_length=2, max_length=16)
    minimum_agreement: int = Field(ge=2)
    chain_id: str = Field(min_length=1)
    verifier_id: str = Field(min_length=1)
    trusted_checkpoint: CometBftDeploymentCheckpoint
    trust_period_seconds: int = Field(gt=0)
    timeout_seconds: int = Field(default=10, gt=0, le=120)
    validator_page_size: int = Field(default=100, ge=1, le=100)
    maximum_validators: int = Field(default=10_000, ge=1, le=100_000)
    max_response_bytes: int = Field(default=1_000_000, gt=0, le=10_000_000)
    transaction_scan_window: int = Field(default=512, ge=0, le=10_000)

    @field_validator("rpc_endpoints")
    @classmethod
    def _http_endpoints(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            parsed = urlsplit(value.strip())
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise ValueError(
                    "CometBFT finality RPC endpoints must be credential-free HTTP URLs"
                )
            normalized.append(value.rstrip("/"))
        if len(set(normalized)) != len(normalized):
            raise ValueError("CometBFT finality RPC endpoints must be unique")
        return normalized

    @model_validator(mode="after")
    def _bounds(self) -> CometBftFinalityDeploymentConfig:
        if self.minimum_agreement > len(self.rpc_endpoints):
            raise ValueError("minimum_agreement must not exceed RPC endpoint count")
        if self.maximum_validators < self.validator_page_size:
            raise ValueError("maximum_validators must not be below validator_page_size")
        return self

    def runtime_config(self) -> CometBftMultiRpcFinalityConfig:
        checkpoint = TrustedCometBftCheckpoint(
            chain_id=self.chain_id,
            height=self.trusted_checkpoint.height,
            block_id=self.trusted_checkpoint.block_id,
            app_hash=self.trusted_checkpoint.app_hash,
            header_time=self.trusted_checkpoint.header_time,
            validator_set=CometBftValidatorSet(
                tuple(
                    CometBftValidator(
                        address=validator.address,
                        public_key=validator.public_key,
                        voting_power=validator.voting_power,
                    )
                    for validator in self.trusted_checkpoint.validators
                )
            ),
            validator_set_hash=self.trusted_checkpoint.validator_set_hash,
            next_validator_set_hash=self.trusted_checkpoint.next_validator_set_hash,
        )
        return CometBftMultiRpcFinalityConfig(
            rpc_endpoints=tuple(self.rpc_endpoints),
            minimum_agreement=self.minimum_agreement,
            chain_id=self.chain_id,
            verifier_id=self.verifier_id,
            trusted_checkpoint=checkpoint,
            trust_period_seconds=self.trust_period_seconds,
            timeout_seconds=self.timeout_seconds,
            validator_page_size=self.validator_page_size,
            maximum_validators=self.maximum_validators,
            max_response_bytes=self.max_response_bytes,
            transaction_scan_window=self.transaction_scan_window,
        )


def load_cometbft_finality_deployment_config(
    path: Path,
) -> CometBftFinalityDeploymentConfig:
    try:
        return CometBftFinalityDeploymentConfig.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("CometBFT finality deployment configuration cannot be loaded") from error
