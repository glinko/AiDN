"""Quorum-verified CometBFT deployment checkpoint rotation."""

from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aidn_hypervisor.consensus.cometbft import (
    CometBftRpcTransport,
    CometBftRpcValidatorSetProvider,
    HttpCometBftRpcTransport,
)
from aidn_hypervisor.consensus.cometbft_crypto import Zip215CometBftEd25519Backend
from aidn_hypervisor.consensus.cometbft_header import cometbft_header_hash
from aidn_hypervisor.consensus.deployment import (
    CometBftDeploymentCheckpoint,
    CometBftDeploymentValidator,
    CometBftFinalityDeploymentConfig,
    load_cometbft_finality_deployment_config,
)
from aidn_hypervisor.consensus.light_client import CometBftValidatorSet


def _rpc_result(response: dict[str, Any]) -> dict[str, Any]:
    error = response.get("error")
    if error not in (None, ""):
        raise ValueError("CometBFT RPC returned an error")
    result = response.get("result", response)
    if not isinstance(result, dict):
        raise ValueError("CometBFT RPC result is invalid")
    return result


def _hash(value: object, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str):
        raise ValueError("CometBFT checkpoint hash is invalid")
    normalized = value.removeprefix("0x").upper()
    if len(normalized) != 64 or any(char not in "0123456789ABCDEF" for char in normalized):
        raise ValueError("CometBFT checkpoint hash is invalid")
    return normalized


def _validators_payload(validator_set: CometBftValidatorSet) -> tuple[tuple[str, str, int], ...]:
    return tuple(
        (item.address, item.public_key, item.voting_power)
        for item in validator_set.validators
    )


@dataclass(frozen=True)
class CometBftCheckpointCandidate:
    endpoint: str
    checkpoint: CometBftDeploymentCheckpoint
    next_validator_set: CometBftValidatorSet

    @property
    def fingerprint(self) -> tuple[object, ...]:
        return (
            json.dumps(
                self.checkpoint.model_dump(mode="json"),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
            _validators_payload(self.next_validator_set),
        )


def collect_checkpoint_candidate(
    *,
    endpoint: str,
    transport: CometBftRpcTransport,
    config: CometBftFinalityDeploymentConfig,
    height: int,
) -> CometBftCheckpointCandidate:
    if height <= config.trusted_checkpoint.height:
        raise ValueError("CHECKPOINT_ROTATION_HEIGHT_NOT_FORWARD")
    commit_result = _rpc_result(
        transport.get(
            "/commit",
            params={"height": str(height)},
            timeout_seconds=config.timeout_seconds,
        )
    )
    if commit_result.get("canonical") is not True:
        raise ValueError("CHECKPOINT_ROTATION_COMMIT_NOT_CANONICAL")
    signed_header = commit_result.get("signed_header")
    if not isinstance(signed_header, dict):
        raise ValueError("CHECKPOINT_ROTATION_SIGNED_HEADER_INVALID")
    header = signed_header.get("header")
    commit = signed_header.get("commit")
    if not isinstance(header, dict) or not isinstance(commit, dict):
        raise ValueError("CHECKPOINT_ROTATION_COMMIT_INVALID")
    if header.get("chain_id") != config.chain_id:
        raise ValueError("CHECKPOINT_ROTATION_CHAIN_ID_MISMATCH")
    try:
        observed_height = int(header.get("height"))
    except (TypeError, ValueError) as error:
        raise ValueError("CHECKPOINT_ROTATION_HEIGHT_INVALID") from error
    if observed_height != height:
        raise ValueError("CHECKPOINT_ROTATION_HEIGHT_MISMATCH")
    block_id = commit.get("block_id")
    if not isinstance(block_id, dict):
        raise ValueError("CHECKPOINT_ROTATION_BLOCK_ID_INVALID")
    block_hash = _hash(block_id.get("hash"))
    if cometbft_header_hash(header) != block_hash:
        raise ValueError("CHECKPOINT_ROTATION_HEADER_HASH_MISMATCH")
    header_time = header.get("time")
    if not isinstance(header_time, str) or not header_time.strip():
        raise ValueError("CHECKPOINT_ROTATION_HEADER_TIME_INVALID")

    provider = CometBftRpcValidatorSetProvider(
        transport=transport,
        timeout_seconds=config.timeout_seconds,
        per_page=config.validator_page_size,
        maximum_validators=config.maximum_validators,
    )
    validator_set, next_validator_set = provider.validator_sets_for_height(height)
    backend = Zip215CometBftEd25519Backend()
    validator_set_hash = backend.validator_set_hash(validator_set)
    next_validator_set_hash = backend.validator_set_hash(next_validator_set)
    if header.get("validators_hash") != validator_set_hash:
        raise ValueError("CHECKPOINT_ROTATION_VALIDATOR_SET_HASH_MISMATCH")
    if header.get("next_validators_hash") != next_validator_set_hash:
        raise ValueError("CHECKPOINT_ROTATION_NEXT_VALIDATOR_SET_HASH_MISMATCH")

    checkpoint = CometBftDeploymentCheckpoint(
        height=height,
        block_id=block_hash,
        app_hash=_hash(header.get("app_hash"), allow_empty=True),
        header_time=header_time,
        validator_set_hash=validator_set_hash,
        next_validator_set_hash=next_validator_set_hash,
        validators=[
            CometBftDeploymentValidator(
                address=item.address,
                public_key=item.public_key,
                voting_power=item.voting_power,
            )
            for item in validator_set.validators
        ],
    )
    return CometBftCheckpointCandidate(
        endpoint=endpoint,
        checkpoint=checkpoint,
        next_validator_set=next_validator_set,
    )


def rotate_checkpoint(
    *,
    config: CometBftFinalityDeploymentConfig,
    height: int,
    transports: Sequence[CometBftRpcTransport],
) -> tuple[CometBftDeploymentCheckpoint, int, list[dict[str, str]]]:
    if len(transports) != len(config.rpc_endpoints):
        raise ValueError("CHECKPOINT_ROTATION_TRANSPORT_COUNT_MISMATCH")
    candidates: list[CometBftCheckpointCandidate] = []
    failures: list[dict[str, str]] = []

    def collect(item: tuple[str, CometBftRpcTransport]) -> CometBftCheckpointCandidate:
        endpoint, transport = item
        return collect_checkpoint_candidate(
            endpoint=endpoint,
            transport=transport,
            config=config,
            height=height,
        )

    with ThreadPoolExecutor(max_workers=len(transports)) as executor:
        futures = [
            executor.submit(collect, item)
            for item in zip(config.rpc_endpoints, transports, strict=True)
        ]
        for endpoint, future in zip(config.rpc_endpoints, futures, strict=True):
            try:
                candidates.append(future.result())
            except Exception as error:  # operational report; no secret material is included
                failures.append({"endpoint": endpoint, "error": str(error)})

    groups: dict[tuple[object, ...], list[CometBftCheckpointCandidate]] = defaultdict(list)
    for candidate in candidates:
        groups[candidate.fingerprint].append(candidate)
    winning_count = max((len(group) for group in groups.values()), default=0)
    winning_groups = [group for group in groups.values() if len(group) == winning_count]
    if winning_count < config.minimum_agreement or len(winning_groups) != 1:
        raise ValueError(
            "CHECKPOINT_ROTATION_QUORUM_NOT_REACHED: "
            f"agreement={winning_count}, required={config.minimum_agreement}, "
            f"candidates={len(candidates)}, failures={len(failures)}"
        )
    return winning_groups[0][0].checkpoint, winning_count, failures


def rotate_checkpoint_file(
    *,
    path: Path,
    height: int,
    output: Path | None = None,
) -> dict[str, object]:
    config = load_cometbft_finality_deployment_config(path)
    transports = [
        HttpCometBftRpcTransport(
            endpoint,
            max_response_bytes=config.max_response_bytes,
        )
        for endpoint in config.rpc_endpoints
    ]
    checkpoint, agreement, failures = rotate_checkpoint(
        config=config,
        height=height,
        transports=transports,
    )
    updated = config.model_copy(update={"trusted_checkpoint": checkpoint})
    destination = output or path
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(updated.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return {
        "status": "PASS",
        "config": str(destination),
        "chain_id": updated.chain_id,
        "height": checkpoint.height,
        "block_id": checkpoint.block_id,
        "app_hash": checkpoint.app_hash,
        "observed_agreement": agreement,
        "minimum_agreement": updated.minimum_agreement,
        "preserved_legacy_transaction_hashes": len(updated.legacy_transaction_hashes),
        "rpc_failures": failures,
    }


__all__ = [
    "CometBftCheckpointCandidate",
    "collect_checkpoint_candidate",
    "rotate_checkpoint",
    "rotate_checkpoint_file",
]
