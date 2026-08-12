"""Creator-side submission helper for an already signed ``TREASURY_FUND``."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from aidn_faucet.cometbft_submitter import serialize_faucet_envelope
from aidn_hypervisor.consensus.cometbft import cometbft_transaction_hash
from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence, ConsensusFinalitySource
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.faucet_treasury import FaucetTreasuryManifest


class TreasuryFundingSubmissionTransport(Protocol):
    def broadcast_tx_sync(self, tx_data: bytes, *, timeout_seconds: int) -> dict:
        """Submit the exact creator-signed envelope bytes."""


_HEX_64 = re.compile(r"^[0-9A-Fa-f]{64}$")


def persist_finality_transaction_hash(
    finality_config: Path,
    *,
    operation_id: str,
    transaction_hash: str,
) -> bool:
    """Persist a finalized operation hash for restart-safe finality verification.

    The in-process submission registry is intentionally ephemeral. A Faucet
    must nevertheless re-verify its Treasury funding after a restart, so the
    creator-side funding command records the already verified transaction hash
    in the operator-owned finality configuration. Existing mappings are
    immutable: a conflicting replacement is rejected.
    """

    normalized_hash = transaction_hash.removeprefix("0x").upper()
    if not _HEX_64.fullmatch(operation_id) or not _HEX_64.fullmatch(normalized_hash):
        raise ValueError("FAUCET_TREASURY_FINALITY_TRANSACTION_HASH_INVALID")

    try:
        payload = json.loads(finality_config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("FAUCET_TREASURY_FINALITY_CONFIG_UNREADABLE") from error
    if not isinstance(payload, dict):
        raise ValueError("FAUCET_TREASURY_FINALITY_CONFIG_INVALID")
    mappings = payload.get("legacy_transaction_hashes", {})
    if not isinstance(mappings, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in mappings.items()
    ):
        raise ValueError("FAUCET_TREASURY_FINALITY_TRANSACTION_REGISTRY_INVALID")

    existing = mappings.get(operation_id)
    if existing is not None:
        if existing.removeprefix("0x").upper() != normalized_hash:
            raise ValueError("FAUCET_TREASURY_FINALITY_TRANSACTION_HASH_CONFLICT")
        return False

    source_stat = finality_config.stat()
    payload["legacy_transaction_hashes"] = {**mappings, operation_id: normalized_hash}
    descriptor, temporary_name = tempfile.mkstemp(
        dir=finality_config.parent,
        prefix=f".{finality_config.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, stat.S_IMODE(source_stat.st_mode))
        if getattr(os, "geteuid", lambda: -1)() == 0:
            os.chown(temporary_path, source_stat.st_uid, source_stat.st_gid)
        os.replace(temporary_path, finality_config)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return True


def validate_treasury_funding_envelope(
    manifest: FaucetTreasuryManifest,
    envelope: LedgerOperationEnvelope,
) -> None:
    if manifest.funding_mode != "CONSENSUS" or not manifest.funding_id:
        raise ValueError("FAUCET_TREASURY_FUNDING_MANIFEST_INVALID")
    if manifest.funding_operation_id:
        raise ValueError("FAUCET_TREASURY_ALREADY_FINALIZED")
    if envelope.operation_type != "TREASURY_FUND":
        raise ValueError("FAUCET_TREASURY_FUNDING_OPERATION_TYPE_INVALID")
    payload = envelope.payload
    expected = {
        "funding_id": manifest.funding_id,
        "treasury_id": manifest.treasury_id,
        "network_id": manifest.network_id,
        "chain_id": manifest.chain_id,
        "treasury_wallet_id": manifest.wallet_id,
        "treasury_public_key": manifest.wallet_public_key,
        "creator_recovery_wallet": manifest.creator_recovery_wallet,
        "treasury_manifest_hash": manifest.manifest_hash,
        "funding_mode": "CONSENSUS",
    }
    if any(payload.get(field) != value for field, value in expected.items()):
        raise ValueError("FAUCET_TREASURY_FUNDING_ENVELOPE_MANIFEST_MISMATCH")
    if not envelope.signatures:
        raise ValueError("FAUCET_TREASURY_FUNDING_SIGNATURE_MISSING")


def _rpc_result(response: object) -> dict[str, Any]:
    if not isinstance(response, dict) or response.get("error") not in (None, ""):
        raise ValueError("CometBFT submission returned an RPC error")
    result = response.get("result", response)
    if not isinstance(result, dict):
        raise ValueError("CometBFT submission result is invalid")
    return result


def submit_and_wait_for_treasury_funding(
    *,
    manifest: FaucetTreasuryManifest,
    envelope: LedgerOperationEnvelope,
    transport: TreasuryFundingSubmissionTransport,
    finality_source: ConsensusFinalitySource,
    timeout_seconds: int = 180,
    poll_seconds: float = 2,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[str, ConsensusFinalityEvidence]:
    """Submit once, then wait only for operation-bound verified finality."""

    validate_treasury_funding_envelope(manifest, envelope)
    if timeout_seconds < 1 or poll_seconds <= 0:
        raise ValueError("FAUCET_TREASURY_FUNDING_WAIT_INVALID")
    transaction = serialize_faucet_envelope(envelope)
    transaction_hash = cometbft_transaction_hash(transaction)
    result = _rpc_result(transport.broadcast_tx_sync(transaction, timeout_seconds=timeout_seconds))
    if int(result.get("code", -1)) != 0:
        detail = result.get("log") or result.get("info") or f"CheckTx code {result.get('code')}"
        raise ValueError(f"FAUCET_TREASURY_FUNDING_REJECTED: {detail}")
    response_hash = result.get("hash")
    if isinstance(response_hash, str) and response_hash.removeprefix("0x").upper() != transaction_hash:
        raise ValueError("FAUCET_TREASURY_FUNDING_TRANSACTION_HASH_MISMATCH")

    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        evidence = finality_source.finality_evidence(envelope.operation_id)
        if evidence is not None:
            if (
                evidence.operation_id != envelope.operation_id
                or evidence.chain_id != manifest.chain_id
                or evidence.operation_type != "TREASURY_FUND"
            ):
                raise ValueError("FAUCET_TREASURY_FUNDING_FINALITY_MISMATCH")
            return transaction_hash, evidence
        sleep(poll_seconds)
    raise TimeoutError("FAUCET_TREASURY_FUNDING_FINALITY_TIMEOUT")
