#!/usr/bin/env python3
"""Broadcast a signed Treasury manifest bind and wait for verified finality."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "aidn-faucet" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from aidn_faucet.cometbft_submitter import (  # noqa: E402
    FailoverCometBftSubmissionTransport,
    FaucetTransactionHashRegistry,
    serialize_faucet_envelope,
)

from aidn_hypervisor.consensus.cometbft import (  # noqa: E402
    HttpCometBftSubmissionTransport,
)
from aidn_hypervisor.consensus.cometbft_finality import (  # noqa: E402
    build_cometbft_multi_rpc_finality_source,
)
from aidn_hypervisor.consensus.deployment import (  # noqa: E402
    load_cometbft_finality_deployment_config,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope  # noqa: E402
from aidn_hypervisor.faucet_treasury import FaucetTreasuryManifest  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--envelope", type=Path, required=True)
    parser.add_argument("--finality-config", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--poll-seconds", type=float, default=2)
    return parser


def main() -> int:
    args = _parser().parse_args()
    manifest = FaucetTreasuryManifest.model_validate_json(args.manifest.read_text(encoding="utf-8"))
    envelope = LedgerOperationEnvelope.model_validate_json(args.envelope.read_text(encoding="utf-8"))
    if envelope.operation_type != "TREASURY_MANIFEST_BIND":
        raise ValueError("manifest bind envelope has the wrong operation type")
    if envelope.payload.get("treasury_manifest", {}).get("manifest_hash") != manifest.manifest_hash:
        raise ValueError("manifest bind envelope does not match Treasury manifest")
    deployment = load_cometbft_finality_deployment_config(args.finality_config)
    if deployment.chain_id != manifest.chain_id:
        raise ValueError("finality config chain does not match Treasury manifest")
    registry = FaucetTransactionHashRegistry()
    transaction = serialize_faucet_envelope(envelope)
    transaction_hash = registry.remember(envelope, transaction)
    transport = FailoverCometBftSubmissionTransport(
        [HttpCometBftSubmissionTransport(endpoint) for endpoint in deployment.rpc_endpoints]
    )
    result = transport.broadcast_tx_sync(transaction, timeout_seconds=args.timeout_seconds)
    rpc_result = result.get("result", result) if isinstance(result, dict) else {}
    if not isinstance(rpc_result, dict) or int(rpc_result.get("code", -1)) != 0:
        raise ValueError(f"TREASURY_MANIFEST_BIND_REJECTED: {rpc_result.get('log', rpc_result)}")
    finality_source = build_cometbft_multi_rpc_finality_source(
        config=deployment.runtime_config(), transaction_hash_for_operation=registry.lookup
    )
    deadline = time.monotonic() + args.timeout_seconds
    while time.monotonic() < deadline:
        evidence = finality_source.finality_evidence(envelope.operation_id)
        if evidence is not None:
            if evidence.operation_type != "TREASURY_MANIFEST_BIND" or evidence.chain_id != manifest.chain_id:
                raise ValueError("TREASURY_MANIFEST_BIND_FINALITY_MISMATCH")
            print(
                json.dumps(
                    {
                        "operation_id": envelope.operation_id,
                        "transaction_hash": transaction_hash,
                        "finality": evidence.model_dump(),
                    },
                    sort_keys=True,
                )
            )
            return 0
        time.sleep(args.poll_seconds)
    raise TimeoutError("TREASURY_MANIFEST_BIND_FINALITY_TIMEOUT")


if __name__ == "__main__":
    raise SystemExit(main())
