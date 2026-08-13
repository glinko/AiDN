#!/usr/bin/env python3
"""Submit one signed EPOCH_TRANSITION and wait for verified multi-RPC finality.

The command never signs an envelope and never fabricates epoch evidence. The
input envelope must already be authorized by the public policy and contain
real roots and pool budgets produced by the epoch-engine process.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.consensus.cometbft import (  # noqa: E402
    HttpCometBftRpcTransport,
    HttpCometBftSubmissionTransport,
    cometbft_transaction_hash,
)
from aidn_hypervisor.consensus.cometbft_finality import (  # noqa: E402
    build_cometbft_multi_rpc_finality_source,
)
from aidn_hypervisor.consensus.deployment import (  # noqa: E402
    load_cometbft_finality_deployment_config,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope  # noqa: E402
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy  # noqa: E402
from aidn_hypervisor.ledger.service import LedgerOperationService  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--envelope", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--finality-config", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--poll-seconds", type=float, default=3)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _rpc_result(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("error") not in (None, ""):
        return {"code": -1, "log": str(response["error"])}
    result = response.get("result", response)
    return result if isinstance(result, dict) else {"code": -1, "log": "invalid RPC result"}


def _checktx_summary(response: dict[str, Any]) -> dict[str, Any]:
    result = _rpc_result(response)
    try:
        code = int(result.get("code", -1))
    except (TypeError, ValueError):
        code = -1
    return {
        "code": code,
        "hash": result.get("hash"),
        "log": result.get("log") or result.get("info"),
    }


def _rpc_result_payload(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("error") not in (None, ""):
        raise ValueError("CometBFT RPC returned an error")
    result = response.get("result")
    if not isinstance(result, dict):
        raise ValueError("CometBFT RPC result is invalid")
    return result


def _read_authority_policy(endpoint: str, *, timeout_seconds: int) -> dict[str, Any]:
    response = HttpCometBftRpcTransport(endpoint).get(
        "/abci_query",
        params={
            "path": json.dumps("protocol/authority-policy", separators=(",", ":")),
            "prove": "false",
        },
        timeout_seconds=timeout_seconds,
    )
    query = _rpc_result_payload(response).get("response")
    if not isinstance(query, dict) or int(query.get("code", -1)) != 0:
        raise ValueError("authority policy query failed")
    encoded = query.get("value")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("authority policy is unavailable")
    try:
        value = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as error:
        raise ValueError("authority policy query is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("authority policy query is not an object")
    return value


def _assert_live_policy(
    *,
    endpoints: list[str],
    policy: ProtocolAuthorityPolicy,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    expected = {
        "configured": True,
        "policy_hash": policy.policy_hash,
        "threshold": policy.threshold,
        "authority_count": len(policy.authorities),
        "epoch_transition_mode": "THRESHOLD_AUTHORIZED",
    }
    for endpoint in endpoints:
        value = _read_authority_policy(endpoint, timeout_seconds=timeout_seconds)
        if any(value.get(key) != expected_value for key, expected_value in expected.items()):
            raise ValueError(f"validator authority policy mismatch: {endpoint}")
        observations.append({"rpc_url": endpoint, **expected})
    return observations


def _validate_input(
    envelope: LedgerOperationEnvelope,
    policy: ProtocolAuthorityPolicy,
    chain_id: str,
) -> None:
    if envelope.operation_type != "EPOCH_TRANSITION":
        raise ValueError("EPOCH_TRANSITION envelope is required")
    if envelope.origin_type != "protocol" or envelope.sender_wallet is not None:
        raise ValueError("EPOCH_TRANSITION must have protocol origin")
    if not envelope.signatures:
        raise ValueError("EPOCH_TRANSITION must already contain authority signatures")
    LedgerOperationService().validate_consensus_epoch_transition(envelope)
    policy.verify_epoch_transition(envelope)
    if not chain_id.strip():
        raise ValueError("finality config chain_id is required")


def _broadcast_all(
    envelope: LedgerOperationEnvelope,
    endpoints: list[str],
    *,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    transaction = envelope.consensus_bytes()
    expected_hash = cometbft_transaction_hash(transaction)
    observations: list[dict[str, Any]] = []
    for endpoint in endpoints:
        try:
            response = HttpCometBftSubmissionTransport(endpoint).broadcast_tx_sync(
                transaction,
                timeout_seconds=timeout_seconds,
            )
            summary = _checktx_summary(response)
            returned_hash = summary.get("hash")
            if returned_hash and str(returned_hash).removeprefix("0x").upper() != expected_hash:
                raise ValueError("CometBFT submission hash does not match envelope bytes")
            observations.append({"rpc_url": endpoint, "status": "PASS", **summary})
        except (OSError, ValueError, RuntimeError) as error:
            observations.append({"rpc_url": endpoint, "status": "FAIL", "error": str(error)})
    admitted = [item for item in observations if item.get("status") == "PASS" and int(item["code"]) == 0]
    if not admitted:
        raise RuntimeError("all configured CometBFT RPCs rejected or failed CheckTx")
    return observations


def main() -> int:
    args = _parser().parse_args()
    if args.timeout_seconds <= 0 or args.poll_seconds <= 0:
        raise ValueError("timeouts and polling interval must be positive")
    envelope = LedgerOperationEnvelope.model_validate_json(
        args.envelope.read_text(encoding="utf-8")
    )
    policy = ProtocolAuthorityPolicy.from_mapping(
        json.loads(args.policy.read_text(encoding="utf-8"))
    )
    deployment = load_cometbft_finality_deployment_config(args.finality_config)
    _validate_input(envelope, policy, deployment.chain_id)
    transaction = envelope.consensus_bytes()
    transaction_hash = cometbft_transaction_hash(transaction)
    summary: dict[str, Any] = {
        "operation_id": envelope.operation_id,
        "transaction_hash": transaction_hash,
        "chain_id": deployment.chain_id,
        "policy_hash": policy.policy_hash,
        "signature_count": len(envelope.signatures),
        "broadcast": False,
    }
    if args.dry_run:
        print(json.dumps({"status": "READY", **summary}, sort_keys=True))
        return 0

    summary["authority_policy_observations"] = _assert_live_policy(
        endpoints=list(deployment.rpc_endpoints),
        policy=policy,
        timeout_seconds=args.timeout_seconds,
    )
    submissions = _broadcast_all(
        envelope,
        deployment.rpc_endpoints,
        timeout_seconds=args.timeout_seconds,
    )
    summary["broadcast"] = True
    summary["submissions"] = submissions
    hash_by_operation = {envelope.operation_id: transaction_hash}
    finality_source = build_cometbft_multi_rpc_finality_source(
        config=deployment.runtime_config(),
        transaction_hash_for_operation=hash_by_operation.get,
    )
    deadline = time.monotonic() + args.timeout_seconds
    while time.monotonic() < deadline:
        evidence = finality_source.finality_evidence(envelope.operation_id)
        if evidence is not None:
            if evidence.operation_type != "EPOCH_TRANSITION" or evidence.chain_id != deployment.chain_id:
                raise ValueError("EPOCH_TRANSITION finality evidence does not match input")
            summary["finality"] = evidence.model_dump()
            print(json.dumps({"status": "FINALIZED", **summary}, sort_keys=True))
            return 0
        time.sleep(args.poll_seconds)
    print(json.dumps({"status": "AWAITING_VERIFIED_FINALITY", **summary}, sort_keys=True))
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        raise SystemExit(2) from error
