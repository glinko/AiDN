#!/usr/bin/env python3
"""Broadcast one creator-signed TREASURY_FUND and wait for quorum finality.

This command has no private-key option.  Sign with
``create-faucet-treasury-funding.py`` on the creator host first.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "aidn-faucet" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from aidn_faucet.cometbft_submitter import (  # noqa: E402
    FailoverCometBftSubmissionTransport,
    FaucetTransactionHashRegistry,
    serialize_faucet_envelope,
)
from aidn_faucet.treasury_funding import submit_and_wait_for_treasury_funding  # noqa: E402

from aidn_hypervisor.consensus.cometbft import HttpCometBftSubmissionTransport  # noqa: E402
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
    parser.add_argument("--manifest", type=Path, required=True, help="pre-finality CONSENSUS manifest")
    parser.add_argument("--envelope", type=Path, required=True, help="creator-signed TREASURY_FUND JSON")
    parser.add_argument("--finality-config", type=Path, required=True)
    parser.add_argument("--final-manifest", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--poll-seconds", type=float, default=2)
    return parser


def main() -> int:
    args = _parser().parse_args()
    manifest = FaucetTreasuryManifest.model_validate_json(args.manifest.read_text(encoding="utf-8"))
    envelope = LedgerOperationEnvelope.model_validate_json(args.envelope.read_text(encoding="utf-8"))
    deployment = load_cometbft_finality_deployment_config(args.finality_config)
    if deployment.chain_id != manifest.chain_id:
        raise ValueError("finality config chain does not match Treasury manifest")
    registry = FaucetTransactionHashRegistry()
    registry.remember(envelope, serialize_faucet_envelope(envelope))
    finality_source = build_cometbft_multi_rpc_finality_source(
        config=deployment.runtime_config(),
        transaction_hash_for_operation=registry.lookup,
    )
    transport = FailoverCometBftSubmissionTransport(
        [HttpCometBftSubmissionTransport(endpoint) for endpoint in deployment.rpc_endpoints]
    )
    transaction_hash, evidence = submit_and_wait_for_treasury_funding(
        manifest=manifest,
        envelope=envelope,
        transport=transport,
        finality_source=finality_source,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )
    final_manifest = manifest.model_copy(update={"funding_operation_id": envelope.operation_id})
    args.final_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.final_manifest.write_text(
        json.dumps(final_manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "operation_id": envelope.operation_id,
                "transaction_hash": transaction_hash,
                "final_manifest": str(args.final_manifest),
                "finality": evidence.model_dump(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
