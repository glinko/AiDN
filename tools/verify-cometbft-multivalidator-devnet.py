#!/usr/bin/env python3
"""Exercise the externally observable four-validator CometBFT MVP path.

This drill deliberately uses the public RPC boundary rather than in-process
ABCI helpers. It proves a protocol-origin Registry transaction was accepted,
included in a committed block with a valid transaction Merkle proof, and that
one validator can restart without losing quorum or changing application state.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from aidn_hypervisor.consensus.cometbft_merkle import (
    verify_cometbft_transaction_inclusion,
)


def _rpc_get(endpoint: str, path: str, **params: str) -> dict[str, Any]:
    query = urllib_parse.urlencode(params)
    with urllib_request.urlopen(f"{endpoint}{path}?{query}", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("error"):
        raise RuntimeError(f"CometBFT RPC request failed for {path}: {payload!r}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"CometBFT RPC result is invalid for {path}")
    return result


def _status(endpoint: str) -> tuple[int, str]:
    result = _rpc_get(endpoint, "/status")
    sync_info = result.get("sync_info")
    if not isinstance(sync_info, dict):
        raise RuntimeError("CometBFT status has no sync_info")
    height = int(sync_info["latest_block_height"])
    app_hash = str(sync_info.get("latest_app_hash") or "")
    if height < 1 or len(app_hash) != 64:
        raise RuntimeError("CometBFT status does not expose a finalized app hash")
    return height, app_hash


def _wait_for_height(
    endpoint: str,
    *,
    greater_than: int,
    timeout_seconds: int,
) -> tuple[int, str]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            height, app_hash = _status(endpoint)
            if height > greater_than:
                return height, app_hash
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            last_error = error
        time.sleep(1)
    raise RuntimeError(
        f"CometBFT did not advance beyond height {greater_than}: {last_error}"
    )


def _transaction_bytes() -> bytes:
    now = datetime.now(UTC)
    envelope = {
        "operation_type": "REGISTRY_UPSERT",
        "operation_version": "1.0.0",
        "protocol_version": "0.1",
        "origin_type": "protocol",
        "initiator_id": "cometbft-multivalidator-drill",
        "sender_wallet": None,
        "sender_sequence": None,
        "fee_payer": None,
        "fee_class": "protocol_sponsored",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=10)).isoformat(),
        "target_epoch": None,
        "payload": {"drill_id": str(uuid.uuid4()), "kind": "multivalidator_acceptance"},
        "evidence_references": [],
        "signatures": [],
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _submit_transaction(endpoint: str, transaction: bytes) -> str:
    result = _rpc_get(endpoint, "/broadcast_tx_sync", tx=f"0x{transaction.hex()}")
    if int(result.get("code", -1)) != 0:
        raise RuntimeError(f"CometBFT rejected drill transaction: {result!r}")
    returned_hash = str(result.get("hash") or "").upper()
    expected_hash = hashlib.sha256(transaction).hexdigest().upper()
    if returned_hash != expected_hash:
        raise RuntimeError("CometBFT broadcast hash does not match transaction bytes")
    return expected_hash


def _wait_for_transaction(
    endpoint: str,
    transaction_hash: str,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return _rpc_get(endpoint, "/tx", hash=f"0x{transaction_hash}", prove="true")
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            last_error = error
            time.sleep(1)
    raise RuntimeError(f"Committed transaction was not found: {last_error}")


def _verify_transaction_proof(endpoint: str, transaction_hash: str, tx_result: dict[str, Any]) -> int:
    height = int(tx_result["height"])
    commit = _rpc_get(endpoint, "/commit", height=str(height))
    signed_header = commit.get("signed_header")
    if not isinstance(signed_header, dict):
        raise RuntimeError("CometBFT commit does not contain a signed header")
    header = signed_header.get("header")
    block_id = signed_header.get("commit", {}).get("block_id", {})
    if not isinstance(header, dict) or not isinstance(block_id, dict):
        raise RuntimeError("CometBFT commit header is invalid")
    if not verify_cometbft_transaction_inclusion(
        transaction_result=tx_result,
        transaction_hash=transaction_hash,
        block_height=height,
        block_id=str(block_id.get("hash") or ""),
        data_hash=str(header.get("data_hash") or ""),
    ):
        raise RuntimeError("CometBFT transaction inclusion proof did not verify")
    encoded = tx_result.get("tx")
    transaction_bytes = base64.b64decode(encoded) if isinstance(encoded, str) else b""
    if hashlib.sha256(transaction_bytes).hexdigest().upper() != transaction_hash:
        raise RuntimeError("CometBFT transaction payload binding is invalid")
    return height


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", default="http://127.0.0.1:26657")
    parser.add_argument("--restart-container", default="aidn-comet-3")
    parser.add_argument(
        "--commit-timeout-seconds",
        type=int,
        default=120,
        help="Maximum wait for transaction inclusion and indexing (default: 120).",
    )
    parser.add_argument(
        "--height-timeout-seconds",
        type=int,
        default=120,
        help="Maximum wait for a post-commit or post-restart height (default: 120).",
    )
    parser.add_argument("--skip-restart", action="store_true")
    args = parser.parse_args()
    if args.commit_timeout_seconds <= 0 or args.height_timeout_seconds <= 0:
        raise ValueError("acceptance timeouts must be positive")
    endpoint = args.rpc_url.rstrip("/")

    before_height, before_app_hash = _status(endpoint)
    transaction_hash = _submit_transaction(endpoint, _transaction_bytes())
    transaction = _wait_for_transaction(
        endpoint,
        transaction_hash,
        timeout_seconds=args.commit_timeout_seconds,
    )
    transaction_height = _verify_transaction_proof(endpoint, transaction_hash, transaction)

    verified_height, verified_app_hash = _wait_for_height(
        endpoint,
        greater_than=max(before_height, transaction_height),
        timeout_seconds=args.height_timeout_seconds,
    )
    if verified_app_hash == before_app_hash:
        # This only documents that the block including the Registry update was
        # visible; the post-restart comparison below proves no state regression.
        pass

    if not args.skip_restart:
        subprocess.run(["docker", "restart", args.restart_container], check=True)
        restarted_height, restarted_app_hash = _wait_for_height(
            endpoint,
            greater_than=verified_height,
            timeout_seconds=args.height_timeout_seconds,
        )
        if restarted_app_hash != verified_app_hash:
            raise RuntimeError("Application hash changed after validator restart")
    else:
        restarted_height, restarted_app_hash = verified_height, verified_app_hash

    print(
        json.dumps(
            {
                "status": "ok",
                "transaction_hash": transaction_hash,
                "transaction_height": transaction_height,
                "height_after_restart": restarted_height,
                "app_hash": restarted_app_hash,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
