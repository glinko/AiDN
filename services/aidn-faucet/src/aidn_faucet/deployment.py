"""Standard production wiring for the external Faucet service."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from aidn_faucet.cometbft_submitter import (
    FaucetTransactionHashRegistry,
    build_http_cometbft_faucet_submitter,
)
from aidn_hypervisor.consensus.cometbft_finality import (
    build_cometbft_multi_rpc_finality_source,
)
from aidn_hypervisor.consensus.deployment import load_cometbft_finality_deployment_config
from aidn_hypervisor.faucet_treasury import FaucetTreasuryManifest


def build_cometbft_submitter(args: Namespace):
    """Build the default failover/quorum submitter from operator files.

    The Faucet private key is loaded by the service itself. This factory only
    binds the public Treasury manifest to an operator-approved finality
    configuration and keeps the operation-to-transaction registry shared by
    submission and reconciliation.
    """

    finality_path = getattr(args, "finality_config", None)
    if finality_path is None:
        raise ValueError("--finality-config is required for the built-in CometBFT submitter")
    manifest_path = Path(args.manifest)
    manifest = FaucetTreasuryManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    deployment = load_cometbft_finality_deployment_config(Path(finality_path))
    if deployment.chain_id != manifest.chain_id:
        raise ValueError("Faucet Treasury manifest and finality configuration use different chains")
    runtime_config = deployment.runtime_config()
    registry = FaucetTransactionHashRegistry()
    finality_source = build_cometbft_multi_rpc_finality_source(
        config=runtime_config,
        transaction_hash_for_operation=registry.lookup,
    )
    return build_http_cometbft_faucet_submitter(
        rpc_endpoints=runtime_config.rpc_endpoints,
        treasury_wallet_id=manifest.wallet_id,
        chain_id=manifest.chain_id,
        finality_source=finality_source,
        transaction_hash_registry=registry,
        sequence_quorum=runtime_config.minimum_agreement,
        timeout_seconds=runtime_config.timeout_seconds,
    )
