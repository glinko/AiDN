"""Fail-closed production wiring for CometBFT finality verification."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.abci_finality import ABCICommittedFinalitySource
from aidn_hypervisor.consensus.cometbft import (
    CometBftRpcFinalitySource,
    CometBftRpcLightClientProofVerifier,
    CometBftRpcTransport,
    HttpCometBftRpcTransport,
)
from aidn_hypervisor.consensus.cometbft_crypto import Zip215CometBftEd25519Backend
from aidn_hypervisor.consensus.light_client import (
    CometBftCryptographicBackend,
    CometBftLightClient,
    TrustedCometBftCheckpoint,
)


@dataclass(frozen=True)
class CometBftFinalityConfig:
    """Operator-approved parameters for one trusted CometBFT network."""

    rpc_endpoint: str
    chain_id: str
    verifier_id: str
    trusted_checkpoint: TrustedCometBftCheckpoint
    trust_period_seconds: int
    timeout_seconds: int = 10
    validator_page_size: int = 100
    maximum_validators: int = 10_000
    max_response_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if not self.rpc_endpoint.strip() or not self.chain_id.strip() or not self.verifier_id.strip():
            raise ValueError("CometBFT finality endpoint, chain_id, and verifier_id are required")
        if self.trusted_checkpoint.chain_id != self.chain_id:
            raise ValueError("CometBFT trusted checkpoint chain_id does not match finality config")
        if self.trust_period_seconds < 1 or self.timeout_seconds < 1:
            raise ValueError("CometBFT finality timeouts must be positive")
        if not 1 <= self.validator_page_size <= 100:
            raise ValueError("CometBFT finality validator_page_size must be between 1 and 100")
        if self.maximum_validators < self.validator_page_size:
            raise ValueError("CometBFT finality maximum_validators is too small")
        if self.max_response_bytes < 1:
            raise ValueError("CometBFT finality max_response_bytes must be positive")


def build_cometbft_finality_source(
    *,
    config: CometBftFinalityConfig,
    transaction_hash_for_operation: Callable[[str], str | None],
    abci_application: AIDNABCIApplication,
    transport: CometBftRpcTransport | None = None,
    cryptography: CometBftCryptographicBackend | None = None,
) -> ABCICommittedFinalitySource:
    """Build the only supported external-finality path for a Hypervisor.

    The trusted checkpoint is operator-provided and never bootstrapped from the
    queried RPC node.  Evidence is additionally bound to the local ABCI state
    commitment, so a verified remote commit cannot mutate unrelated local state.
    """
    backend = cryptography or Zip215CometBftEd25519Backend()
    light_client = CometBftLightClient(
        checkpoint=config.trusted_checkpoint,
        cryptography=backend,
        trust_period_seconds=config.trust_period_seconds,
    )
    rpc_transport = transport or HttpCometBftRpcTransport(
        config.rpc_endpoint,
        max_response_bytes=config.max_response_bytes,
    )
    proof_verifier = CometBftRpcLightClientProofVerifier(
        light_client=light_client,
        transport=rpc_transport,
        timeout_seconds=config.timeout_seconds,
        per_page=config.validator_page_size,
        maximum_validators=config.maximum_validators,
    )
    external_source = CometBftRpcFinalitySource(
        chain_id=config.chain_id,
        transaction_hash_for_operation=transaction_hash_for_operation,
        proof_verifier=proof_verifier,
        transport=rpc_transport,
        verifier_id=config.verifier_id,
        timeout_seconds=config.timeout_seconds,
    )
    return ABCICommittedFinalitySource(
        source=external_source,
        abci_application=abci_application,
    )
