"""Fail-closed production wiring for CometBFT finality verification."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.abci_finality import ABCICommittedFinalitySource
from aidn_hypervisor.consensus.cometbft import (
    CometBftRpcFinalitySource,
    CometBftRpcLightClientProofVerifier,
    CometBftRpcTransport,
    HttpCometBftRpcTransport,
)
from aidn_hypervisor.consensus.cometbft_crypto import Zip215CometBftEd25519Backend
from aidn_hypervisor.consensus.finality import (
    ConsensusFinalitySource,
    QuorumConsensusFinalitySource,
)
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
    transaction_scan_window: int = 0
    legacy_transaction_hashes: Mapping[str, str] = field(default_factory=dict)

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
        if self.transaction_scan_window < 0:
            raise ValueError("CometBFT transaction_scan_window cannot be negative")


@dataclass(frozen=True)
class CometBftMultiRpcFinalityConfig:
    """Operator-approved multi-RPC finality parameters for one network."""

    rpc_endpoints: tuple[str, ...]
    minimum_agreement: int
    chain_id: str
    verifier_id: str
    trusted_checkpoint: TrustedCometBftCheckpoint
    trust_period_seconds: int
    timeout_seconds: int = 10
    validator_page_size: int = 100
    maximum_validators: int = 10_000
    max_response_bytes: int = 1_000_000
    transaction_scan_window: int = 0
    legacy_transaction_hashes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.rpc_endpoints) < 2:
            raise ValueError("multi-RPC finality requires at least two endpoints")
        if len(set(self.rpc_endpoints)) != len(self.rpc_endpoints):
            raise ValueError("multi-RPC finality endpoints must be unique")
        if any(not endpoint.strip() for endpoint in self.rpc_endpoints):
            raise ValueError("multi-RPC finality endpoints must be non-empty")
        if not 2 <= self.minimum_agreement <= len(self.rpc_endpoints):
            raise ValueError("minimum_agreement must be within the endpoint count")
        if not self.chain_id.strip() or not self.verifier_id.strip():
            raise ValueError("multi-RPC finality chain_id and verifier_id are required")
        if self.trusted_checkpoint.chain_id != self.chain_id:
            raise ValueError("trusted checkpoint chain_id does not match finality config")
        if self.trust_period_seconds < 1 or self.timeout_seconds < 1:
            raise ValueError("multi-RPC finality timeouts must be positive")
        if not 1 <= self.validator_page_size <= 100:
            raise ValueError("multi-RPC finality validator_page_size must be between 1 and 100")
        if self.maximum_validators < self.validator_page_size:
            raise ValueError("multi-RPC finality maximum_validators is too small")
        if self.max_response_bytes < 1:
            raise ValueError("multi-RPC finality max_response_bytes must be positive")
        if self.transaction_scan_window < 0:
            raise ValueError("CometBFT transaction_scan_window cannot be negative")


def build_cometbft_finality_source(
    *,
    config: CometBftFinalityConfig,
    transaction_hash_for_operation: Callable[[str], str | None],
    abci_application: AIDNABCIApplication | None = None,
    transport: CometBftRpcTransport | None = None,
    cryptography: CometBftCryptographicBackend | None = None,
) -> ConsensusFinalitySource:
    """Build the only supported external-finality path for a Hypervisor.

    The trusted checkpoint is operator-provided and never bootstrapped from the
    queried RPC node. When a local ABCI application is supplied, evidence is
    additionally bound to its state commitment. A non-validator may omit that
    local binding and rely on the verified operation-bound remote proof.
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
    recovered_transaction_hashes: dict[str, str] = {}
    external_source = CometBftRpcFinalitySource(
        chain_id=config.chain_id,
        transaction_hash_for_operation=transaction_hash_for_operation,
        proof_verifier=proof_verifier,
        transport=rpc_transport,
        verifier_id=config.verifier_id,
        timeout_seconds=config.timeout_seconds,
        transaction_scan_window=config.transaction_scan_window,
        legacy_transaction_hashes=config.legacy_transaction_hashes,
        recovered_transaction_hashes=recovered_transaction_hashes,
    )
    if abci_application is None:
        return external_source
    return ABCICommittedFinalitySource(source=external_source, abci_application=abci_application)


def build_cometbft_multi_rpc_finality_source(
    *,
    config: CometBftMultiRpcFinalityConfig,
    transaction_hash_for_operation: Callable[[str], str | None],
    abci_application: AIDNABCIApplication | None = None,
    transports: Sequence[CometBftRpcTransport] | None = None,
    cryptography: CometBftCryptographicBackend | None = None,
) -> ConsensusFinalitySource:
    """Build a quorum source with optional local-ABCI commitment binding."""
    if transports is not None and len(transports) != len(config.rpc_endpoints):
        raise ValueError("multi-RPC transports must match endpoint count")
    backend = cryptography or Zip215CometBftEd25519Backend()
    recovered_transaction_hashes: dict[str, str] = {}
    sources = []
    source_ids = []
    for index, endpoint in enumerate(config.rpc_endpoints):
        transport = (
            transports[index]
            if transports is not None
            else HttpCometBftRpcTransport(
                endpoint,
                max_response_bytes=config.max_response_bytes,
            )
        )
        light_client = CometBftLightClient(
            checkpoint=config.trusted_checkpoint,
            cryptography=backend,
            trust_period_seconds=config.trust_period_seconds,
        )
        proof_verifier = CometBftRpcLightClientProofVerifier(
            light_client=light_client,
            transport=transport,
            timeout_seconds=config.timeout_seconds,
            per_page=config.validator_page_size,
            maximum_validators=config.maximum_validators,
        )
        sources.append(
            CometBftRpcFinalitySource(
                chain_id=config.chain_id,
                transaction_hash_for_operation=transaction_hash_for_operation,
                proof_verifier=proof_verifier,
                transport=transport,
                verifier_id=f"{config.verifier_id}:{index}",
                timeout_seconds=config.timeout_seconds,
                transaction_scan_window=config.transaction_scan_window,
                legacy_transaction_hashes=config.legacy_transaction_hashes,
                recovered_transaction_hashes=recovered_transaction_hashes,
            )
        )
        source_ids.append(endpoint)
    quorum_source = QuorumConsensusFinalitySource(
        sources=sources,
        quorum=config.minimum_agreement,
        source_ids=source_ids,
    )
    if abci_application is None:
        return quorum_source
    return ABCICommittedFinalitySource(source=quorum_source, abci_application=abci_application)
