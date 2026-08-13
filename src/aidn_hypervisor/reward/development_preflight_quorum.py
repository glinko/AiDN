"""Read-only quorum collection for the ECO-0007 production preflight."""

from __future__ import annotations

import base64
import binascii
import json
from collections import Counter
from collections.abc import Callable
from typing import Any, Literal
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_distribution import canonical_hash
from aidn_hypervisor.reward.development_preflight import (
    DevelopmentRewardPreflight,
)

Fetcher = Callable[[str, str, dict[str, str]], dict[str, Any]]
DEVELOPMENT_REWARD_PREFLIGHT_QUORUM_VERSION = "eco-0007-reward-preflight-quorum.v1"


class DevelopmentRewardPreflightQuorum(BaseModel, frozen=True):
    """Hash-bound quorum observation accepted as a production batch input."""

    schema_version: str = DEVELOPMENT_REWARD_PREFLIGHT_QUORUM_VERSION
    status: Literal["READY"] = "READY"
    pool_id: str = Field(min_length=1)
    chain_id: str = Field(min_length=1)
    required_quorum: int = Field(ge=1)
    agreement_count: int = Field(ge=1)
    chain_agreement_count: int = Field(ge=1)
    preflight: DevelopmentRewardPreflight
    observations_hash: str = Field(min_length=1)
    quorum_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_quorum(self) -> DevelopmentRewardPreflightQuorum:
        if self.schema_version != DEVELOPMENT_REWARD_PREFLIGHT_QUORUM_VERSION:
            raise ValueError("DEVELOPMENT_PREFLIGHT_QUORUM_VERSION_INVALID")
        if self.preflight.status != "READY":
            raise ValueError("DEVELOPMENT_PREFLIGHT_QUORUM_PREFLIGHT_NOT_READY")
        if self.preflight.pool_id != self.pool_id:
            raise ValueError("DEVELOPMENT_PREFLIGHT_QUORUM_POOL_MISMATCH")
        if self.agreement_count < self.required_quorum or self.chain_agreement_count < self.required_quorum:
            raise ValueError("DEVELOPMENT_PREFLIGHT_QUORUM_INSUFFICIENT")
        if self.quorum_hash != development_reward_preflight_quorum_hash(self):
            raise ValueError("DEVELOPMENT_PREFLIGHT_QUORUM_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"quorum_hash"})

    def verify_integrity(self) -> bool:
        return self.quorum_hash == development_reward_preflight_quorum_hash(self)


def development_reward_preflight_quorum_hash(
    quorum: DevelopmentRewardPreflightQuorum,
) -> str:
    return canonical_hash(quorum.unsigned_payload())


def build_development_reward_preflight_quorum(
    report: dict[str, Any],
) -> DevelopmentRewardPreflightQuorum:
    """Validate a collector report and bind its observations to a hash."""

    if report.get("status") != "READY":
        raise ValueError("DEVELOPMENT_PREFLIGHT_QUORUM_REPORT_NOT_READY")
    preflight = DevelopmentRewardPreflight.model_validate(report.get("preflight"))
    payload = {
        "schema_version": DEVELOPMENT_REWARD_PREFLIGHT_QUORUM_VERSION,
        "status": "READY",
        "pool_id": report.get("pool_id"),
        "chain_id": report.get("chain_id"),
        "required_quorum": report.get("required_quorum"),
        "agreement_count": report.get("agreement_count"),
        "chain_agreement_count": report.get("chain_agreement_count"),
        "preflight": preflight.model_dump(mode="json"),
        "observations_hash": canonical_hash(report.get("observations", [])),
    }
    return DevelopmentRewardPreflightQuorum(
        **payload,
        quorum_hash=canonical_hash(payload),
    )


def _fetch_json(endpoint: str, path: str, params: dict[str, str]) -> dict[str, Any]:
    query = urllib_parse.urlencode(params)
    with urllib_request.urlopen(f"{endpoint.rstrip('/')}{path}?{query}", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("CometBFT RPC response is invalid")
    return payload


def collect_development_reward_preflight(
    *,
    rpc_urls: list[str],
    pool_id: str = "GENERAL_DEVELOPMENT",
    quorum: int | None = None,
    fetcher: Fetcher = _fetch_json,
) -> dict[str, Any]:
    """Require one exact preflight projection from the configured RPC quorum."""

    if len(rpc_urls) < 2 or len(set(rpc_urls)) != len(rpc_urls):
        raise ValueError("at least two unique RPC endpoints are required")
    if not pool_id or "/" in pool_id or "\\" in pool_id:
        raise ValueError("pool ID is invalid")
    required_quorum = (2 * len(rpc_urls) + 2) // 3 if quorum is None else quorum
    if not 1 <= required_quorum <= len(rpc_urls):
        raise ValueError("preflight quorum is outside RPC count")

    observations: list[dict[str, Any]] = []
    for rpc_url in rpc_urls:
        try:
            status_payload = fetcher(rpc_url, "/status", {})
            status = _rpc_result(status_payload, "/status")
            node_info = status.get("node_info")
            sync_info = status.get("sync_info")
            if not isinstance(node_info, dict) or not isinstance(sync_info, dict):
                raise ValueError("CometBFT status is incomplete")
            chain_id = node_info.get("network")
            node_id = node_info.get("id")
            height = int(sync_info.get("latest_block_height"))
            if not isinstance(chain_id, str) or not chain_id or not isinstance(node_id, str) or not node_id:
                raise ValueError("CometBFT status identity is incomplete")
            query_payload = fetcher(
                rpc_url,
                "/abci_query",
                {
                    "path": json.dumps(f"development/reward-preflight/{pool_id}", separators=(",", ":")),
                    "prove": "false",
                },
            )
            query = _rpc_result(query_payload, "/abci_query").get("response")
            if not isinstance(query, dict) or int(query.get("code", -1)) != 0:
                raise ValueError("development reward preflight query failed")
            encoded = query.get("value")
            if not isinstance(encoded, str) or not encoded:
                raise ValueError("development reward preflight is unavailable")
            preflight = DevelopmentRewardPreflight.model_validate(
                json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
            )
            observations.append(
                {
                    "rpc_url": rpc_url,
                    "status": "PASS",
                    "node_id": node_id,
                    "chain_id": chain_id,
                    "height": height,
                    "catching_up": bool(sync_info.get("catching_up")),
                    "preflight": preflight.model_dump(mode="json"),
                }
            )
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            binascii.Error,
        ) as error:
            observations.append({"rpc_url": rpc_url, "status": "FAIL", "error": str(error)})

    passed = [item for item in observations if item.get("status") == "PASS"]
    chain_counts = Counter(str(item["chain_id"]) for item in passed)
    chain_id, chain_count = chain_counts.most_common(1)[0] if chain_counts else (None, 0)
    eligible = [item for item in passed if item.get("chain_id") == chain_id and item.get("catching_up") is False]
    summary_counts = Counter(
        json.dumps(item["preflight"], sort_keys=True, separators=(",", ":")) for item in eligible
    )
    winning_summary_json, winning_count = summary_counts.most_common(1)[0] if summary_counts else (None, 0)
    winning_summary = json.loads(winning_summary_json) if winning_summary_json is not None else None
    ready = (
        chain_count >= required_quorum
        and winning_count >= required_quorum
        and isinstance(winning_summary, dict)
        and winning_summary.get("status") == "READY"
    )
    report = {
        "schema_version": 1,
        "status": "READY" if ready else "BLOCKED",
        "pool_id": pool_id,
        "chain_id": chain_id,
        "required_quorum": required_quorum,
        "agreement_count": winning_count,
        "chain_agreement_count": chain_count,
        "preflight": winning_summary,
        "observations": observations,
        "reason_code": None
        if ready
        else (
            "DEVELOPMENT_REWARD_PREFLIGHT_NOT_READY"
            if winning_summary is None
            else winning_summary.get("reason_code") or "DEVELOPMENT_REWARD_PREFLIGHT_QUORUM_UNAVAILABLE"
        ),
    }
    if ready:
        report["observations_hash"] = canonical_hash(observations)
        report["quorum_hash"] = canonical_hash(
            {
                "schema_version": DEVELOPMENT_REWARD_PREFLIGHT_QUORUM_VERSION,
                "status": "READY",
                "pool_id": pool_id,
                "chain_id": chain_id,
                "required_quorum": required_quorum,
                "agreement_count": winning_count,
                "chain_agreement_count": chain_count,
                "preflight": winning_summary,
                "observations_hash": report["observations_hash"],
            }
        )
    return report


def _rpc_result(payload: dict[str, Any], path: str) -> dict[str, Any]:
    if payload.get("error") not in {None, ""}:
        raise ValueError(f"CometBFT RPC returned an error for {path}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError(f"CometBFT RPC result is invalid for {path}")
    return result
