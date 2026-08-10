"""Production Faucet submission and finality adapters for CometBFT.

The adapter deliberately keeps policy and consensus separate.  It submits the
exact signed envelope, treats CheckTx admission as pending, and reports
``FINALIZED`` only after an injected AiDN finality source returns verified
operation-bound evidence.
"""

from __future__ import annotations

import base64
import json
import threading
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from aidn_faucet.models import TransferSubmission
from aidn_hypervisor.consensus.cometbft import (
    CometBftRpcTransport,
    CometBftSubmissionTransport,
    HttpCometBftRpcTransport,
    HttpCometBftSubmissionTransport,
    cometbft_transaction_hash,
)
from aidn_hypervisor.consensus.finality import ConsensusFinalitySource
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.faucet_treasury import (
    FaucetTreasuryActivationProof,
    FaucetTreasuryManifest,
)


def serialize_faucet_envelope(envelope: LedgerOperationEnvelope) -> bytes:
    """Serialize exactly as the AiDN consensus submission service does."""

    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


class FaucetTransactionHashRegistry:
    """Restart-local operation-to-transaction binding for finality proofs.

    Pending claims retain the signed envelope in SQLite.  The Faucet calls
    ``remember`` again during reconciliation, so a restart does not require
    trusting a transaction hash supplied by an HTTP caller.
    """

    def __init__(self) -> None:
        self._hashes: dict[str, str] = {}
        self._lock = threading.Lock()

    def remember(self, envelope: LedgerOperationEnvelope, transaction_bytes: bytes) -> str:
        transaction_hash = cometbft_transaction_hash(transaction_bytes)
        with self._lock:
            existing = self._hashes.get(envelope.operation_id)
            if existing is not None and existing != transaction_hash:
                raise ValueError("operation_id is already bound to another transaction")
            self._hashes[envelope.operation_id] = transaction_hash
        return transaction_hash

    def lookup(self, operation_id: str) -> str | None:
        with self._lock:
            return self._hashes.get(operation_id)


class FailoverCometBftSubmissionTransport:
    """Try configured RPC submitters while preserving the exact tx bytes."""

    def __init__(self, transports: Sequence[CometBftSubmissionTransport]) -> None:
        if not transports:
            raise ValueError("at least one CometBFT submission transport is required")
        self._transports = tuple(transports)

    def broadcast_tx_sync(self, tx_data: bytes, *, timeout_seconds: int) -> dict:
        errors: list[str] = []
        for transport in self._transports:
            try:
                return transport.broadcast_tx_sync(tx_data, timeout_seconds=timeout_seconds)
            except Exception as error:  # pragma: no cover - transport-specific failures
                errors.append(f"{type(error).__name__}: {error}")
        raise RuntimeError("all CometBFT submission endpoints failed: " + " | ".join(errors))


class HttpCometBftWalletSequenceProvider:
    """Read the canonical next Wallet sequence from one or more RPC nodes.

    A quorum is required when more than one endpoint is configured.  This is
    an anti-staleness check, not a replacement for verified transaction
    finality; finality remains the responsibility of ``ConsensusFinalitySource``.
    """

    def __init__(
        self,
        transports: Sequence[CometBftRpcTransport],
        *,
        quorum: int = 1,
        timeout_seconds: int = 10,
    ) -> None:
        if not transports:
            raise ValueError("at least one CometBFT RPC transport is required")
        if not 1 <= quorum <= len(transports):
            raise ValueError("sequence quorum must be within the RPC count")
        if timeout_seconds < 1:
            raise ValueError("sequence timeout must be positive")
        self._transports = tuple(transports)
        self._quorum = quorum
        self._timeout_seconds = timeout_seconds

    def __call__(self, wallet_id: str) -> int:
        if not wallet_id or "/" in wallet_id or "\\" in wallet_id:
            raise ValueError("Wallet ID is invalid for an ABCI query path")
        values: list[int] = []
        path = f"wallet/sequence/{wallet_id}"
        for transport in self._transports:
            try:
                response = transport.get(
                    "/abci_query",
                    params={"path": json.dumps(path, separators=(",", ":")), "prove": "false"},
                    timeout_seconds=self._timeout_seconds,
                )
                result = response.get("result")
                query_response = result.get("response") if isinstance(result, dict) else None
                if not isinstance(query_response, dict) or int(query_response.get("code", -1)) != 0:
                    continue
                encoded = query_response.get("value")
                if not isinstance(encoded, str) or not encoded:
                    continue
                value = int(base64.b64decode(encoded, validate=True).decode("ascii"))
                if value >= 1:
                    values.append(value)
            except (ValueError, TypeError, KeyError, UnicodeDecodeError):
                continue
        counts = Counter(values)
        if not counts:
            raise RuntimeError("canonical Wallet sequence is unavailable")
        sequence, count = counts.most_common(1)[0]
        if count < self._quorum:
            raise RuntimeError("configured RPCs disagree on the canonical Wallet sequence")
        return sequence


class HttpCometBftWalletBalanceProvider:
    """Read a Wallet's canonical Q-atom balance with the same RPC quorum."""

    def __init__(
        self,
        transports: Sequence[CometBftRpcTransport],
        *,
        quorum: int = 1,
        timeout_seconds: int = 10,
    ) -> None:
        if not transports:
            raise ValueError("at least one CometBFT RPC transport is required")
        if not 1 <= quorum <= len(transports):
            raise ValueError("balance quorum must be within the RPC count")
        if timeout_seconds < 1:
            raise ValueError("balance timeout must be positive")
        self._transports = tuple(transports)
        self._quorum = quorum
        self._timeout_seconds = timeout_seconds

    def __call__(self, wallet_id: str) -> int:
        if not wallet_id or "/" in wallet_id or "\\" in wallet_id:
            raise ValueError("Wallet ID is invalid for an ABCI query path")
        values: list[int] = []
        path = f"wallet/balance/{wallet_id}"
        for transport in self._transports:
            try:
                response = transport.get(
                    "/abci_query",
                    params={"path": json.dumps(path, separators=(",", ":")), "prove": "false"},
                    timeout_seconds=self._timeout_seconds,
                )
                result = response.get("result")
                query_response = result.get("response") if isinstance(result, dict) else None
                if not isinstance(query_response, dict) or int(query_response.get("code", -1)) != 0:
                    continue
                encoded = query_response.get("value")
                if not isinstance(encoded, str) or not encoded:
                    continue
                value = int(base64.b64decode(encoded, validate=True).decode("ascii"))
                if value >= 0:
                    values.append(value)
            except (ValueError, TypeError, KeyError, UnicodeDecodeError):
                continue
        counts = Counter(values)
        if not counts:
            raise RuntimeError("canonical Treasury balance is unavailable")
        balance, count = counts.most_common(1)[0]
        if count < self._quorum:
            raise RuntimeError("configured RPCs disagree on the canonical Treasury balance")
        return balance


class HttpCometBftTreasuryManifestProvider:
    """Read the Treasury manifest from the canonical ABCI query path.

    A local JSON file is not enough to establish Treasury ownership.  This
    provider requires the same configured RPC quorum to return one identical
    hash-bound manifest.
    """

    def __init__(
        self,
        transports: Sequence[CometBftRpcTransport],
        *,
        quorum: int = 1,
        timeout_seconds: int = 10,
    ) -> None:
        if not transports:
            raise ValueError("at least one CometBFT RPC transport is required")
        if not 1 <= quorum <= len(transports):
            raise ValueError("manifest quorum must be within the RPC count")
        if timeout_seconds < 1:
            raise ValueError("manifest timeout must be positive")
        self._transports = tuple(transports)
        self._quorum = quorum
        self._timeout_seconds = timeout_seconds

    @property
    def quorum(self) -> int:
        return self._quorum

    @property
    def source_count(self) -> int:
        return len(self._transports)

    def __call__(self) -> FaucetTreasuryManifest | None:
        manifests: dict[str, list[FaucetTreasuryManifest]] = {}
        for transport in self._transports:
            try:
                response = transport.get(
                    "/abci_query",
                    params={
                        "path": json.dumps(
                            "faucet/treasury-manifest",
                            separators=(",", ":"),
                        ),
                        "prove": "false",
                    },
                    timeout_seconds=self._timeout_seconds,
                )
                result = response.get("result")
                query_response = result.get("response") if isinstance(result, dict) else None
                if not isinstance(query_response, dict) or int(query_response.get("code", -1)) != 0:
                    continue
                encoded = query_response.get("value")
                if not isinstance(encoded, str) or not encoded:
                    continue
                manifest = FaucetTreasuryManifest.model_validate(
                    json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
                )
            except (ValueError, TypeError, KeyError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            manifests.setdefault(manifest.manifest_hash, []).append(manifest)

        winning = [group for group in manifests.values() if len(group) >= self._quorum]
        if len(winning) != 1:
            return None
        return winning[0][0]


class CometBftFaucetTransferSubmitter:
    """Submit Faucet transfers and reconcile them against verified finality."""

    def __init__(
        self,
        *,
        treasury_wallet_id: str,
        chain_id: str,
        sequence_provider: Callable[[str], int],
        submission_transport: CometBftSubmissionTransport,
        finality_source: ConsensusFinalitySource,
        transaction_hash_registry: FaucetTransactionHashRegistry | None = None,
        balance_provider: Callable[[str], int | None] | None = None,
        manifest_provider: Callable[[], FaucetTreasuryManifest | None] | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        if not treasury_wallet_id.strip() or not chain_id.strip():
            raise ValueError("Treasury Wallet and chain ID are required")
        if timeout_seconds < 1:
            raise ValueError("CometBFT submission timeout must be positive")
        self.treasury_wallet_id = treasury_wallet_id
        self.chain_id = chain_id
        self._sequence_provider = sequence_provider
        self._submission_transport = submission_transport
        self._finality_source = finality_source
        self._hash_registry = transaction_hash_registry or FaucetTransactionHashRegistry()
        self._balance_provider = balance_provider
        self._manifest_provider = manifest_provider
        self._timeout_seconds = timeout_seconds

    def next_sender_sequence(self, wallet_id: str) -> int:
        if wallet_id != self.treasury_wallet_id:
            raise ValueError("Faucet sender Wallet does not match the configured Treasury")
        sequence = self._sequence_provider(wallet_id)
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("canonical Treasury Wallet sequence is invalid")
        return sequence

    def treasury_balance_q_atoms(self, wallet_id: str) -> int | None:
        if wallet_id != self.treasury_wallet_id:
            raise ValueError("Faucet balance query Wallet does not match the configured Treasury")
        if self._balance_provider is None:
            return None
        value = self._balance_provider(wallet_id)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ValueError("Treasury balance provider returned an invalid value")
        return value

    def treasury_activation_proof(
        self,
        manifest: FaucetTreasuryManifest,
    ) -> FaucetTreasuryActivationProof:
        """Verify that the configured Treasury is recognized by consensus."""

        if manifest.chain_id != self.chain_id:
            return FaucetTreasuryActivationProof.unavailable(
                manifest,
                reason="FAUCET_TREASURY_CHAIN_MISMATCH",
            )
        if manifest.wallet_id != self.treasury_wallet_id:
            return FaucetTreasuryActivationProof.unavailable(
                manifest,
                reason="FAUCET_TREASURY_WALLET_MISMATCH",
            )

        if manifest.funding_mode == "CONSENSUS":
            if not manifest.funding_operation_id:
                return FaucetTreasuryActivationProof.unavailable(
                    manifest,
                    reason="FAUCET_TREASURY_FUNDING_NOT_FINALIZED",
                )
            try:
                evidence = self._finality_source.finality_evidence(manifest.funding_operation_id)
            except Exception as error:  # pragma: no cover - transport-specific boundary
                return FaucetTreasuryActivationProof.unavailable(
                    manifest,
                    reason=f"FAUCET_TREASURY_FINALITY_UNAVAILABLE: {error}",
                )
            if evidence is None:
                return FaucetTreasuryActivationProof.unavailable(
                    manifest,
                    reason="FAUCET_TREASURY_FUNDING_NOT_FINALIZED",
                )
            if (
                evidence.operation_id != manifest.funding_operation_id
                or evidence.chain_id != manifest.chain_id
                or evidence.operation_type != "TREASURY_FUND"
            ):
                return FaucetTreasuryActivationProof.unavailable(
                    manifest,
                    reason="FAUCET_TREASURY_FUNDING_EVIDENCE_MISMATCH",
                )
            balance = self.treasury_balance_q_atoms(manifest.wallet_id)
            if balance is None:
                return FaucetTreasuryActivationProof.unavailable(
                    manifest,
                    reason="FAUCET_TREASURY_BALANCE_UNAVAILABLE",
                )
            quorum = int(getattr(self._finality_source, "quorum", 1))
            source_count = int(getattr(self._finality_source, "source_count", 1))
            return FaucetTreasuryActivationProof(
                state="ACTIVE",
                treasury_id=manifest.treasury_id,
                network_id=manifest.network_id,
                chain_id=manifest.chain_id,
                wallet_id=manifest.wallet_id,
                manifest_hash=manifest.manifest_hash,
                funding_mode=manifest.funding_mode,
                funding_id=manifest.funding_id,
                funding_operation_id=manifest.funding_operation_id,
                funded_amount_q_atoms=manifest.genesis_allocation_q_atoms,
                observed_balance_q_atoms=balance,
                evidence_type="CONSENSUS_FUNDING",
                canonical_evidence={
                    "operation_id": evidence.operation_id,
                    "operation_type": evidence.operation_type,
                    "funding_id": manifest.funding_id,
                    "chain_id": evidence.chain_id,
                    "manifest_hash": manifest.manifest_hash,
                    "block_height": evidence.block_height,
                    "block_id": evidence.block_id,
                    "app_hash": evidence.app_hash,
                    "commit_hash": evidence.commit_hash,
                    "proof_version": evidence.proof_version,
                },
                quorum=quorum,
                source_count=source_count,
            )

        if self._manifest_provider is None:
            return FaucetTreasuryActivationProof.unavailable(
                manifest,
                reason="FAUCET_TREASURY_GENESIS_QUERY_UNAVAILABLE",
            )
        try:
            canonical_manifest = self._manifest_provider()
        except Exception as error:  # pragma: no cover - transport-specific boundary
            return FaucetTreasuryActivationProof.unavailable(
                manifest,
                reason=f"FAUCET_TREASURY_GENESIS_QUERY_FAILED: {error}",
            )
        if canonical_manifest is None or canonical_manifest.manifest_hash != manifest.manifest_hash:
            return FaucetTreasuryActivationProof.unavailable(
                manifest,
                reason="FAUCET_TREASURY_GENESIS_MANIFEST_MISMATCH",
            )
        balance = self.treasury_balance_q_atoms(manifest.wallet_id)
        if balance is None:
            return FaucetTreasuryActivationProof.unavailable(
                manifest,
                reason="FAUCET_TREASURY_BALANCE_UNAVAILABLE",
            )
        quorum = int(getattr(self._manifest_provider, "quorum", 1))
        source_count = int(getattr(self._manifest_provider, "source_count", 1))
        return FaucetTreasuryActivationProof(
            state="ACTIVE",
            treasury_id=manifest.treasury_id,
            network_id=manifest.network_id,
            chain_id=manifest.chain_id,
            wallet_id=manifest.wallet_id,
            manifest_hash=manifest.manifest_hash,
            funding_mode=manifest.funding_mode,
            funding_id=manifest.funding_id,
            funding_operation_id=None,
            funded_amount_q_atoms=manifest.genesis_allocation_q_atoms,
            observed_balance_q_atoms=balance,
            evidence_type="GENESIS_STATE",
            canonical_evidence={
                "manifest_hash": canonical_manifest.manifest_hash,
                "chain_id": canonical_manifest.chain_id,
                "wallet_id": canonical_manifest.wallet_id,
                "balance_q_atoms": balance,
            },
            quorum=quorum,
            source_count=source_count,
        )

    def submit_transfer(self, envelope: LedgerOperationEnvelope) -> TransferSubmission:
        self._validate_envelope(envelope)
        transaction_bytes = serialize_faucet_envelope(envelope)
        transaction_hash = self._hash_registry.remember(envelope, transaction_bytes)
        try:
            response = self._submission_transport.broadcast_tx_sync(
                transaction_bytes,
                timeout_seconds=self._timeout_seconds,
            )
            if self._is_cached_response(response):
                return TransferSubmission(
                    operation_id=envelope.operation_id,
                    status="ADMITTED",
                    transaction_hash=transaction_hash,
                    detail="CometBFT reported an idempotently cached exact envelope",
                )
            result = self._rpc_result(response)
            code = int(result.get("code", -1))
            if code != 0:
                return TransferSubmission(
                    operation_id=envelope.operation_id,
                    status="REJECTED",
                    transaction_hash=transaction_hash,
                    detail=str(result.get("log") or result.get("info") or f"CheckTx code {code}"),
                )
            response_hash = result.get("hash")
            if response_hash is not None and self._normalise_hash(response_hash) != transaction_hash:
                return TransferSubmission(
                    operation_id=envelope.operation_id,
                    status="REJECTED",
                    transaction_hash=transaction_hash,
                    detail="CometBFT admission hash does not match the signed envelope",
                )
            return TransferSubmission(
                operation_id=envelope.operation_id,
                status="ADMITTED",
                transaction_hash=transaction_hash,
                detail="CometBFT CheckTx admitted the exact envelope; finality is pending",
            )
        except Exception as error:
            return TransferSubmission(
                operation_id=envelope.operation_id,
                status="UNKNOWN",
                transaction_hash=transaction_hash,
                detail=f"CometBFT submission unavailable: {error}",
            )

    def reconcile_transfer(self, envelope: LedgerOperationEnvelope) -> TransferSubmission:
        self._validate_envelope(envelope)
        transaction_bytes = serialize_faucet_envelope(envelope)
        transaction_hash = self._hash_registry.remember(envelope, transaction_bytes)
        try:
            evidence = self._finality_source.finality_evidence(envelope.operation_id)
        except Exception as error:  # pragma: no cover - defensive verifier boundary
            return TransferSubmission(
                operation_id=envelope.operation_id,
                status="UNKNOWN",
                transaction_hash=transaction_hash,
                detail=f"consensus finality unavailable: {error}",
            )
        if evidence is None:
            return TransferSubmission(
                operation_id=envelope.operation_id,
                status="ADMITTED",
                transaction_hash=transaction_hash,
                detail="No verified finality evidence is available yet",
            )
        if evidence.operation_id != envelope.operation_id or evidence.chain_id != self.chain_id:
            return TransferSubmission(
                operation_id=envelope.operation_id,
                status="UNKNOWN",
                transaction_hash=transaction_hash,
                detail="Finality evidence is not bound to the requested operation and chain",
            )
        return TransferSubmission(
            operation_id=envelope.operation_id,
            status="FINALIZED",
            transaction_hash=transaction_hash,
            detail=(
                f"Finalized at height {evidence.block_height} by {evidence.verifier_id}"
            ),
        )

    def transaction_hash_for_operation(self, operation_id: str) -> str | None:
        return self._hash_registry.lookup(operation_id)

    def _validate_envelope(self, envelope: LedgerOperationEnvelope) -> None:
        if envelope.operation_type != "WALLET_TRANSFER":
            raise ValueError("Faucet submitter accepts only WALLET_TRANSFER")
        if envelope.sender_wallet != self.treasury_wallet_id:
            raise ValueError("Faucet envelope sender is not the configured Treasury")
        if envelope.fee_payer != self.treasury_wallet_id:
            raise ValueError("Faucet envelope fee payer is not the configured Treasury")
        if envelope.sender_sequence is None:
            raise ValueError("Faucet envelope sender sequence is required")

    @staticmethod
    def _rpc_result(response: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(response, dict) or response.get("error") not in {None, ""}:
            raise ValueError("CometBFT submission returned an RPC error")
        result = response.get("result", response)
        if not isinstance(result, dict):
            raise ValueError("CometBFT submission result is invalid")
        return result

    @staticmethod
    def _is_cached_response(response: object) -> bool:
        if not isinstance(response, dict):
            return False
        fragments: list[str] = []
        error = response.get("error")
        if isinstance(error, dict):
            fragments.extend(str(error.get(key, "")) for key in ("message", "data"))
        result = response.get("result")
        if isinstance(result, dict):
            fragments.extend(str(result.get(key, "")) for key in ("log", "info"))
        return "tx already exists in cache" in " ".join(fragments).lower()

    @staticmethod
    def _normalise_hash(value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("CometBFT transaction hash is invalid")
        normalized = value.removeprefix("0x").upper()
        if len(normalized) != 64 or any(char not in "0123456789ABCDEF" for char in normalized):
            raise ValueError("CometBFT transaction hash is invalid")
        return normalized


def build_http_cometbft_faucet_submitter(
    *,
    rpc_endpoints: Sequence[str],
    treasury_wallet_id: str,
    chain_id: str,
    finality_source: ConsensusFinalitySource,
    transaction_hash_registry: FaucetTransactionHashRegistry | None = None,
    sequence_quorum: int | None = None,
    balance_provider: Callable[[str], int | None] | None = None,
    timeout_seconds: int = 10,
) -> CometBftFaucetTransferSubmitter:
    """Build a failover HTTP adapter around a preconfigured finality source."""

    if not rpc_endpoints:
        raise ValueError("at least one CometBFT RPC endpoint is required")
    rpc_transports = tuple(HttpCometBftRpcTransport(endpoint) for endpoint in rpc_endpoints)
    submission_transports = tuple(
        HttpCometBftSubmissionTransport(endpoint) for endpoint in rpc_endpoints
    )
    sequence_provider = HttpCometBftWalletSequenceProvider(
        rpc_transports,
        quorum=sequence_quorum or len(rpc_transports),
        timeout_seconds=timeout_seconds,
    )
    return CometBftFaucetTransferSubmitter(
        treasury_wallet_id=treasury_wallet_id,
        chain_id=chain_id,
        sequence_provider=sequence_provider,
        submission_transport=FailoverCometBftSubmissionTransport(submission_transports),
        finality_source=finality_source,
        transaction_hash_registry=transaction_hash_registry,
        balance_provider=(
            balance_provider
            or HttpCometBftWalletBalanceProvider(
                rpc_transports,
                quorum=sequence_quorum or len(rpc_transports),
                timeout_seconds=timeout_seconds,
            )
        ),
        manifest_provider=HttpCometBftTreasuryManifestProvider(
            rpc_transports,
            quorum=sequence_quorum or len(rpc_transports),
            timeout_seconds=timeout_seconds,
        ),
        timeout_seconds=timeout_seconds,
    )
