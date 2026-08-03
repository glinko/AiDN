#!/usr/bin/env python3
"""Exercise the externally observable four-validator CometBFT MVP path.

This drill deliberately uses the public RPC boundary rather than in-process
ABCI helpers. It proves a canonical RFC-0060 failure chain and a Session
lock/open/accept lifecycle chain were accepted and executed in dependency
order, included in committed blocks with valid transaction Merkle proofs, and
that one validator can restart without losing quorum or changing application
state.
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
from pathlib import Path
from typing import Any
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from aidn_hypervisor.consensus.cometbft_merkle import (
    verify_cometbft_transaction_inclusion,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.settlement.models import (
    AtomicSettlementTransition,
    SessionFundingAccount,
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
    return height, app_hash.upper()


def _converged_status(
    statuses: list[dict[str, Any]], *, greater_than: int
) -> tuple[int, str] | None:
    if not statuses:
        return None
    heights = {item.get("height") for item in statuses}
    app_hashes = {item.get("app_hash") for item in statuses}
    if len(heights) != 1 or len(app_hashes) != 1:
        return None
    height = statuses[0].get("height")
    app_hash = statuses[0].get("app_hash")
    if not isinstance(height, int) or not isinstance(app_hash, str):
        return None
    if height <= greater_than:
        return None
    return height, app_hash


def _wait_for_network_convergence(
    endpoints: list[str],
    *,
    greater_than: int,
    timeout_seconds: int,
) -> tuple[int, str, list[dict[str, Any]]]:
    """Wait until every configured validator exposes one committed state."""
    if not endpoints:
        raise ValueError("at least one validator RPC endpoint is required")
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            statuses = []
            for endpoint in endpoints:
                height, app_hash = _status(endpoint)
                statuses.append(
                    {
                        "rpc_url": endpoint,
                        "height": height,
                        "app_hash": app_hash,
                    }
                )
            convergence = _converged_status(statuses, greater_than=greater_than)
            if convergence is not None:
                height, app_hash = convergence
                return height, app_hash, statuses
            last_error = RuntimeError(
                "validator RPC views have not converged: "
                + json.dumps(statuses, sort_keys=True)
            )
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            last_error = error
        time.sleep(1)
    raise RuntimeError(
        "validator RPC views did not converge beyond height "
        f"{greater_than}: {last_error}"
    )


def _failure_chain_transactions() -> list[tuple[str, str, bytes]]:
    """Create one disposable canonical RFC-0060 failure chain."""
    now = datetime.now(UTC).replace(microsecond=0)
    session_id = f"session-cometbft-drill-{uuid.uuid4()}"
    failure_root = f"sha256:cometbft-failure-{uuid.uuid4()}"
    settlement_id = f"settlement-cometbft-drill-{uuid.uuid4()}"
    expires_at = (now + timedelta(minutes=10)).isoformat()
    funding = SessionFundingAccount(
        session_id=session_id,
        session_contract_hash="sha256:cometbft-drill-session-contract",
        funding_class="ESCROW_PREPAID",
        consumer_funding_account="wallet:acceptance-consumer",
        endpoint_payment_beneficiary="wallet:acceptance-endpoint",
        consumer_refund_beneficiary="wallet:acceptance-consumer",
        total_locked_amount_q_atoms=1_100,
        endpoint_payment_reserve_q_atoms=1_000,
        network_fee_reserve_q_atoms=100,
        unsettled_payment_reserve_q_atoms=1_000,
        unsettled_fee_reserve_q_atoms=100,
    )
    lock = LedgerOperationEnvelope(
        operation_type="SESSION_ESCROW_LOCK",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="wallet",
        initiator_id=session_id,
        sender_wallet=funding.consumer_funding_account,
        sender_sequence=1,
        fee_payer=funding.consumer_funding_account,
        fee_class="session",
        created_at=now.isoformat(),
        expires_at=expires_at,
        payload=funding.model_dump(mode="json"),
        signatures=["ed25519:acceptance-consumer-lock"],
    )
    failure = LedgerOperationEnvelope(
        operation_type="SESSION_FAILURE_EVIDENCE",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="evidence_triggered",
        initiator_id=session_id,
        fee_class="session",
        created_at=now.isoformat(),
        expires_at=expires_at,
        payload={
            "session_id": session_id,
            "failure_class": "ENDPOINT_FAILURE",
            "failure_evidence_root": failure_root,
        },
        evidence_references=[failure_root],
        signatures=["ed25519:acceptance-operator"],
    )
    transition = AtomicSettlementTransition(
        session_id=session_id,
        settlement_id=settlement_id,
        endpoint_payment_beneficiary=funding.endpoint_payment_beneficiary,
        consumer_refund_beneficiary=funding.consumer_refund_beneficiary,
        previously_released_to_endpoint_q_atoms=0,
        previously_refunded_to_consumer_q_atoms=0,
        previously_consumed_network_fees_q_atoms=0,
        credit_endpoint_q_atoms=0,
        credit_consumer_q_atoms=1_100,
        consume_network_fees_q_atoms=0,
        retain_dispute_reserve_q_atoms=0,
        total_locked_amount_q_atoms=1_100,
    )
    force = LedgerOperationEnvelope(
        operation_type="SESSION_FORCE_SETTLE",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="evidence_triggered",
        initiator_id=session_id,
        fee_payer=funding.consumer_funding_account,
        fee_class="session",
        created_at=now.isoformat(),
        expires_at=expires_at,
        payload={
            "session_id": session_id,
            "failure_class": "ENDPOINT_UNAVAILABLE",
            "requested_at": (now - timedelta(minutes=2)).isoformat(),
            "force_after": (now - timedelta(minutes=1)).isoformat(),
            "observed_at": now.isoformat(),
            "failure_evidence_root": failure_root,
            "failure_evidence_operation_id": failure.operation_id,
            "funding_lock_operation_id": lock.operation_id,
            "requested_payment_q_atoms": 0,
            "requested_refund_q_atoms": 1_100,
            "request_settlement_root": "sha256:cometbft-empty-requests",
            "usage_chain_root": "sha256:cometbft-empty-usage",
            "checkpoint_root": "sha256:cometbft-empty-checkpoints",
            "initiator_wallet": funding.consumer_funding_account,
            "initiator_signature": "ed25519:acceptance-consumer-force",
            "transition": transition.model_dump(mode="json"),
        },
        evidence_references=[
            lock.operation_id,
            failure.operation_id,
            failure_root,
            settlement_id,
        ],
        signatures=["ed25519:acceptance-consumer-force"],
    )
    return [
        ("lock", session_id, _serialize(lock)),
        ("failure", session_id, _serialize(failure)),
        ("force", session_id, _serialize(force)),
    ]


def _session_lifecycle_transactions() -> list[tuple[str, str, bytes]]:
    """Create a disposable lock -> open -> accept lifecycle chain."""
    now = datetime.now(UTC).replace(microsecond=0)
    session_id = f"session-cometbft-lifecycle-{uuid.uuid4()}"
    expires_at = (now + timedelta(minutes=10)).isoformat()
    funding = SessionFundingAccount(
        session_id=session_id,
        session_contract_hash="sha256:cometbft-lifecycle-session-contract",
        funding_class="ESCROW_PREPAID",
        consumer_funding_account="wallet:acceptance-consumer",
        endpoint_payment_beneficiary="wallet:acceptance-endpoint",
        consumer_refund_beneficiary="wallet:acceptance-consumer",
        total_locked_amount_q_atoms=300,
        endpoint_payment_reserve_q_atoms=250,
        network_fee_reserve_q_atoms=50,
        unsettled_payment_reserve_q_atoms=250,
        unsettled_fee_reserve_q_atoms=50,
    )
    lock = LedgerOperationEnvelope(
        operation_type="SESSION_ESCROW_LOCK",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="wallet",
        initiator_id=session_id,
        sender_wallet=funding.consumer_funding_account,
        sender_sequence=2,
        fee_payer=funding.consumer_funding_account,
        fee_class="session",
        created_at=now.isoformat(),
        expires_at=expires_at,
        payload=funding.model_dump(mode="json"),
        signatures=["ed25519:acceptance-consumer-lifecycle-lock"],
    )
    open_payload = {
        "session_id": session_id,
        "consumer_hypervisor_id": "hv-acceptance-consumer",
        "provider_hypervisor_id": "hv-acceptance-endpoint",
        "endpoint_id": "endpoint:cometbft-lifecycle",
        "endpoint_version": "1.0.0",
        "endpoint_configuration_hash": "sha256:cometbft-lifecycle-endpoint",
        "pricing_policy_hash": "sha256:cometbft-lifecycle-pricing",
        "accounting_contract_hash": "sha256:cometbft-lifecycle-accounting",
        "session_policy_hash": "sha256:cometbft-lifecycle-policy",
        "session_contract_hash": funding.session_contract_hash,
        "effective_terms_hash": "sha256:cometbft-lifecycle-terms",
        "endpoint_payment_beneficiary": funding.endpoint_payment_beneficiary,
        "consumer_refund_beneficiary": funding.consumer_refund_beneficiary,
        "deposit_amount_q_atoms": funding.total_locked_amount_q_atoms,
        "funding_lock_operation_id": lock.operation_id,
        "funding_state_reference": funding.funding_state_hash,
        "open_expiration": expires_at,
    }
    open_operation = LedgerOperationEnvelope(
        operation_type="SESSION_OPEN",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="wallet",
        initiator_id=session_id,
        sender_wallet=funding.consumer_funding_account,
        sender_sequence=3,
        fee_payer=funding.consumer_funding_account,
        fee_class="session",
        created_at=now.isoformat(),
        expires_at=expires_at,
        payload=open_payload,
        evidence_references=[lock.operation_id, funding.funding_state_hash],
        signatures=["ed25519:acceptance-consumer-lifecycle-open"],
    )
    accept = LedgerOperationEnvelope(
        operation_type="SESSION_ACCEPT",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="wallet",
        initiator_id="hv-acceptance-endpoint",
        sender_wallet=funding.endpoint_payment_beneficiary,
        sender_sequence=1,
        fee_payer=funding.endpoint_payment_beneficiary,
        fee_class="session",
        created_at=now.isoformat(),
        expires_at=expires_at,
        payload={
            "session_id": session_id,
            "session_open_operation_id": open_operation.operation_id,
            "session_contract_hash": funding.session_contract_hash,
            "effective_terms_hash": open_payload["effective_terms_hash"],
            "endpoint_id": open_payload["endpoint_id"],
            "endpoint_configuration_hash": open_payload["endpoint_configuration_hash"],
            "provider_hypervisor_id": open_payload["provider_hypervisor_id"],
            "accepted_by": funding.endpoint_payment_beneficiary,
            "accepted_at": now.isoformat(),
        },
        evidence_references=[open_operation.operation_id],
        signatures=["ed25519:acceptance-endpoint-lifecycle-accept"],
    )
    return [
        ("lifecycle_lock", session_id, _serialize(lock)),
        ("lifecycle_open", session_id, _serialize(open_operation)),
        ("lifecycle_accept", session_id, _serialize(accept)),
    ]


def _reputation_profile_transactions() -> list[tuple[str, str, bytes]]:
    """Create a finalized evidence -> Reputation root chain."""
    now = datetime.now(UTC).replace(microsecond=0)
    endpoint_id = f"endpoint:cometbft-reputation-{uuid.uuid4()}"
    verification_report_id = f"verification-cometbft-{uuid.uuid4()}"
    verification = LedgerOperationEnvelope(
        operation_type="SERVICE_VERIFICATION_COMMIT",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="protocol",
        initiator_id=endpoint_id,
        fee_class="protocol_sponsored",
        target_epoch="7",
        created_at=now.isoformat(),
        payload={
            "verification_report_id": verification_report_id,
            "service_id": endpoint_id,
            "service_type": "ENDPOINT",
            "report_hash": "sha256:cometbft-verification-report",
            "evidence_root": "sha256:cometbft-verification-evidence",
            "verification_epoch": 7,
            "result_summary": {"eligible": True, "status": "verified"},
            "registry_reference": {"object_id": "registry:cometbft-reputation"},
        },
        evidence_references=["sha256:cometbft-verification-source"],
        signatures=["ed25519:acceptance-verification-authority"],
    )
    new_profile_hash = "sha256:" + hashlib.sha256(
        verification.operation_id.encode("utf-8")
    ).hexdigest()
    profile = LedgerOperationEnvelope(
        operation_type="REPUTATION_PROFILE_UPDATE",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="protocol",
        initiator_id="reputation-scheduler",
        fee_class="protocol_sponsored",
        target_epoch="7",
        created_at=now.isoformat(),
        payload={
            "object_id": endpoint_id,
            "object_type": "reputation_profile",
            "previous_profile_hash": "sha256:" + "0" * 64,
            "new_profile_hash": new_profile_hash,
            "metric_deltas": {
                "VALIDATION_REPORT_AVAILABILITY": {
                    "positive_mass_milli": 300,
                    "negative_mass_milli": 0,
                    "event_count": 1,
                }
            },
            "evidence_root": "sha256:" + hashlib.sha256(
                verification.operation_id.encode("utf-8")
            ).hexdigest(),
            "effective_epoch": 7,
            "formula_version": "reputation.v1",
        },
        evidence_references=[verification.operation_id],
        signatures=["ed25519:acceptance-reputation-scheduler"],
    )
    return [
        ("service_verification", endpoint_id, _serialize(verification)),
        ("reputation_profile_update", endpoint_id, _serialize(profile)),
    ]


def _serialize(envelope: LedgerOperationEnvelope) -> bytes:
    return json.dumps(
        envelope.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _unsupported_operation_transaction() -> bytes:
    """Create a valid-envelope probe for the strict validator profile."""
    envelope = LedgerOperationEnvelope(
        operation_type="REGISTRY_UPSERT",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="protocol",
        created_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        payload={},
    )
    return _serialize(envelope)


def _submit_expected_rejection(endpoint: str, transaction: bytes) -> dict[str, Any]:
    result = _rpc_get(endpoint, "/broadcast_tx_sync", tx=f"0x{transaction.hex()}")
    if int(result.get("code", 0)) == 0:
        raise RuntimeError(
            "strict validator accepted an operation without a consensus transition"
        )
    log = str(result.get("log") or "")
    expected = "consensus operation transition is not implemented: REGISTRY_UPSERT"
    if expected not in log:
        raise RuntimeError(
            "strict validator returned an unexpected unsupported-operation error: "
            f"{result!r}"
        )
    return {
        "operation_type": "REGISTRY_UPSERT",
        "code": int(result["code"]),
        "log": log,
    }


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
    execution_result = tx_result.get("tx_result")
    if not isinstance(execution_result, dict) or int(execution_result.get("code", -1)) != 0:
        raise RuntimeError(f"CometBFT transaction execution failed: {tx_result!r}")
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
    parser.add_argument(
        "--validator-rpc-url",
        action="append",
        dest="validator_rpc_urls",
        help=(
            "Additional validator RPC endpoint. Repeat once per validator; "
            "the primary --rpc-url is included automatically."
        ),
    )
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
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the successful machine-readable evidence report to this path.",
    )
    args = parser.parse_args()
    if args.commit_timeout_seconds <= 0 or args.height_timeout_seconds <= 0:
        raise ValueError("acceptance timeouts must be positive")
    endpoint = args.rpc_url.rstrip("/")
    validator_endpoints = [endpoint]
    for validator_endpoint in args.validator_rpc_urls or []:
        normalized_endpoint = validator_endpoint.rstrip("/")
        if normalized_endpoint not in validator_endpoints:
            validator_endpoints.append(normalized_endpoint)

    before_height, before_app_hash, before_statuses = _wait_for_network_convergence(
        validator_endpoints,
        greater_than=0,
        timeout_seconds=args.height_timeout_seconds,
    )
    coverage_probe = _submit_expected_rejection(
        endpoint,
        _unsupported_operation_transaction(),
    )
    transaction_records = []
    for stage, session_id, transaction_bytes in [
        *_failure_chain_transactions(),
        *_session_lifecycle_transactions(),
        *_reputation_profile_transactions(),
    ]:
        transaction_hash = _submit_transaction(endpoint, transaction_bytes)
        transaction = _wait_for_transaction(
            endpoint,
            transaction_hash,
            timeout_seconds=args.commit_timeout_seconds,
        )
        transaction_height = _verify_transaction_proof(
            endpoint,
            transaction_hash,
            transaction,
        )
        transaction_records.append(
            {
                "stage": stage,
                "session_id": session_id,
                "transaction_hash": transaction_hash,
                "transaction_height": transaction_height,
            }
        )

    verified_height, verified_app_hash, verified_statuses = _wait_for_network_convergence(
        validator_endpoints,
        greater_than=max(
            before_height,
            *(item["transaction_height"] for item in transaction_records),
        ),
        timeout_seconds=args.height_timeout_seconds,
    )
    if verified_app_hash == before_app_hash:
        raise RuntimeError("accepted operations did not change the application hash")

    if not args.skip_restart:
        subprocess.run(["docker", "restart", args.restart_container], check=True)
        restarted_height, restarted_app_hash, restarted_statuses = _wait_for_network_convergence(
            validator_endpoints,
            greater_than=verified_height,
            timeout_seconds=args.height_timeout_seconds,
        )
        if restarted_app_hash != verified_app_hash:
            raise RuntimeError("Application hash changed after validator restart")
    else:
        restarted_height, restarted_app_hash, restarted_statuses = (
            verified_height,
            verified_app_hash,
            verified_statuses,
        )

    report = {
        "status": "ok",
        "strict_operation_coverage_probe": coverage_probe,
        "validator_rpc_urls": validator_endpoints,
        "validator_status_before": before_statuses,
        "operations": transaction_records,
        "validator_status_after_transactions": verified_statuses,
        "validator_status_after_restart": restarted_statuses,
        "height_after_restart": restarted_height,
        "app_hash": restarted_app_hash,
    }
    serialized_report = json.dumps(report, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized_report + "\n", encoding="utf-8")
    print(serialized_report)


if __name__ == "__main__":
    main()
