"""Read-only readiness checks for a controlled multi-host CometBFT lab."""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator


class CometBftLanTestnetConfig(BaseModel, frozen=True):
    """Expected topology for a non-production, operator-controlled testnet."""

    rpc_endpoints: list[str] = Field(min_length=4, max_length=32)
    expected_validators: int = Field(default=4, ge=4, le=128)
    maximum_height_lag: int = Field(default=1, ge=0, le=100)
    allow_insecure_private_http: bool = False

    @field_validator("rpc_endpoints")
    @classmethod
    def _validate_rpc_endpoints(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise ValueError("lab CometBFT RPC endpoint must be a credential-free HTTP(S) root URL")
            normalized.append(value.rstrip("/"))
        if len(set(normalized)) != len(normalized):
            raise ValueError("lab CometBFT RPC endpoints must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_transport(self):
        if len(self.rpc_endpoints) < self.expected_validators:
            raise ValueError("lab RPC endpoint count must cover every expected validator")
        for endpoint in self.rpc_endpoints:
            parsed = urlsplit(endpoint)
            if parsed.scheme == "http":
                if not self.allow_insecure_private_http:
                    raise ValueError("insecure lab HTTP requires explicit allow_insecure_private_http")
                try:
                    address = ipaddress.ip_address(parsed.hostname or "")
                except ValueError as error:
                    raise ValueError("insecure lab HTTP requires a private IP address") from error
                if not address.is_private:
                    raise ValueError("insecure lab HTTP requires a private IP address")
        return self


class CometBftLabObservation(BaseModel, frozen=True):
    endpoint: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    chain_id: str = Field(min_length=1)
    height: int = Field(ge=1)
    app_hash: str = Field(pattern=r"^[0-9A-Fa-f]{64}$")
    catching_up: bool
    peer_count: int = Field(ge=0)


def validate_cometbft_lab_quorum(
    *,
    config: CometBftLanTestnetConfig,
    observations: Sequence[CometBftLabObservation],
) -> dict[str, object]:
    """Validate one synchronized observation of all configured lab RPC nodes.

    This is a deployment gate only.  It proves neither production transport
    security nor independent operator ownership.
    """
    expected_endpoints = set(config.rpc_endpoints)
    by_endpoint = {observation.endpoint: observation for observation in observations}
    if len(by_endpoint) != len(observations):
        raise ValueError("lab observation contains duplicate endpoints")
    if set(by_endpoint) != expected_endpoints:
        raise ValueError("lab observation does not cover exactly the configured RPC endpoints")
    if len(observations) < config.expected_validators:
        raise ValueError("lab observation does not cover every expected validator")
    if any(observation.catching_up for observation in observations):
        raise ValueError("one or more lab validators are still catching up")
    node_ids = {observation.node_id for observation in observations}
    if len(node_ids) != len(observations):
        raise ValueError("lab observations do not represent unique validator nodes")
    chain_ids = {observation.chain_id for observation in observations}
    if len(chain_ids) != 1:
        raise ValueError("lab validators disagree on chain ID")
    heights = [observation.height for observation in observations]
    if max(heights) - min(heights) > config.maximum_height_lag:
        raise ValueError("lab validator height lag exceeds the configured bound")
    required_peer_count = config.expected_validators - 1
    if any(observation.peer_count < required_peer_count for observation in observations):
        raise ValueError("one or more lab validators do not see the expected peer quorum")
    app_hashes = {observation.app_hash.upper() for observation in observations}
    if len(app_hashes) != 1:
        raise ValueError("lab validators disagree on application hash")
    return {
        "status": "ok",
        "scope": "CONTROLLED_LAN_TESTNET",
        "chain_id": next(iter(chain_ids)),
        "height_range": {"minimum": min(heights), "maximum": max(heights)},
        "app_hash": next(iter(app_hashes)),
        "validator_node_ids": sorted(node_ids),
        "rpc_endpoints": config.rpc_endpoints,
        "transport_security": (
            "PRIVATE_LAN_HTTP" if config.allow_insecure_private_http else "HTTPS_REQUIRED"
        ),
        "ownership_evidence": {
            "status": "NOT_PROVEN_BY_PROTOCOL",
            "reason": "A controlled LAN topology does not establish independent operator ownership.",
        },
    }
