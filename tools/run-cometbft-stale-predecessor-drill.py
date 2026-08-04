"""Prove that a stale Session funding predecessor is rejected by live consensus.

The drill reuses a previously committed disposable lifecycle lock from the G3
report. It submits a settlement proposal with a deliberately stale predecessor
reference and requires CometBFT/ABCI to reject it before it enters the mempool.
No new escrow is created by this probe.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.settlement.models import SessionSettlementProposal


def _rpc_get(endpoint: str, path: str, **params: str) -> dict[str, Any]:
    query = urllib_parse.urlencode(params)
    separator = "&" if "?" in path else "?"
    with urllib_request.urlopen(
        f"{endpoint.rstrip('/')}{path}{separator}{query}", timeout=10
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("error"):
        raise RuntimeError(f"CometBFT RPC request failed for {path}: {payload!r}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"CometBFT RPC result is invalid for {path}")
    return result


def _status(endpoint: str) -> dict[str, Any]:
    result = _rpc_get(endpoint, "/status")
    sync_info = result.get("sync_info")
    node_info = result.get("node_info")
    if not isinstance(sync_info, dict) or not isinstance(node_info, dict):
        raise RuntimeError("CometBFT status is incomplete")
    return {
        "height": int(sync_info.get("latest_block_height") or 0),
        "app_hash": str(sync_info.get("latest_app_hash") or "").upper(),
        "node_id": str(node_info.get("id") or ""),
        "chain_id": str(node_info.get("network") or ""),
    }


def _load_source_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load G3 source report: {error}") from error
    if not isinstance(report, dict) or report.get("status") not in {"ok", "PASS"}:
        raise ValueError("G3 source report must be a successful JSON object")
    operations = report.get("operations")
    if not isinstance(operations, list):
        raise ValueError("G3 source report does not contain operations")
    return report


def _lifecycle_lock_hash(report: dict[str, Any]) -> str:
    for item in report["operations"]:
        if isinstance(item, dict) and item.get("stage") == "lifecycle_lock":
            transaction_hash = item.get("transaction_hash")
            if isinstance(transaction_hash, str) and transaction_hash:
                return transaction_hash.upper()
    raise ValueError("G3 source report has no lifecycle_lock transaction")


def _load_committed_lock(endpoint: str, transaction_hash: str) -> dict[str, Any]:
    result = _rpc_get(endpoint, "/tx", hash=f"0x{transaction_hash}", prove="true")
    encoded = result.get("tx")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("lifecycle lock transaction does not expose its payload")
    try:
        transaction = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("lifecycle lock transaction is not valid JSON") from error
    if not isinstance(transaction, dict) or transaction.get("operation_type") != "SESSION_ESCROW_LOCK":
        raise ValueError("G3 lifecycle transaction is not SESSION_ESCROW_LOCK")
    payload = transaction.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("lifecycle lock transaction has no funding payload")
    operation_id = transaction.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        raise ValueError("lifecycle lock transaction has no operation_id")
    return {
        "operation_id": operation_id,
        "session_id": str(payload.get("session_id") or ""),
        "funding": payload,
    }


def _build_stale_proposal(lock: dict[str, Any]) -> bytes:
    now = datetime.now(UTC).replace(microsecond=0)
    funding = lock["funding"]
    session_id = lock["session_id"]
    if not session_id:
        raise ValueError("lifecycle lock funding has no session_id")
    endpoint_beneficiary = str(funding.get("endpoint_payment_beneficiary") or "")
    refund_beneficiary = str(funding.get("consumer_refund_beneficiary") or "")
    funding_state_hash = str(funding.get("funding_state_hash") or "")
    if not endpoint_beneficiary or not refund_beneficiary or not funding_state_hash:
        raise ValueError("lifecycle lock funding is missing settlement bindings")
    proposal = SessionSettlementProposal(
        settlement_id=f"settlement-stale-predecessor-{uuid.uuid4()}",
        settlement_sequence=1,
        session_id=session_id,
        settlement_input_root="sha256:stale-predecessor-input",
        request_settlement_root="sha256:stale-predecessor-requests",
        usage_chain_root="sha256:stale-predecessor-usage",
        checkpoint_root="sha256:stale-predecessor-checkpoints",
        gross_session_charge_q_atoms=0,
        capped_session_charge_q_atoms=0,
        final_endpoint_payment_q_atoms=0,
        requested_endpoint_payment_q_atoms=0,
        consumer_payment_refund_q_atoms=int(funding.get("total_locked_amount_q_atoms") or 0),
        actual_network_fees_q_atoms=0,
        consumer_fee_refund_q_atoms=int(funding.get("network_fee_reserve_q_atoms") or 0),
        disputed_amount_q_atoms=0,
        dispute_reserve_q_atoms=0,
        endpoint_absorbed_amount_q_atoms=0,
        settlement_mode="COOPERATIVE_FINAL",
        proposal_expiration=(now + timedelta(minutes=10)).isoformat(),
    )
    stale_predecessor = f"stale-predecessor:{uuid.uuid4()}"
    envelope = LedgerOperationEnvelope(
        operation_type="SESSION_SETTLEMENT_PROPOSE",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="multi_party",
        initiator_id=session_id,
        fee_payer=refund_beneficiary,
        fee_class="session",
        created_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=10)).isoformat(),
        payload={
            "session_id": session_id,
            "funding_predecessor_operation_id": stale_predecessor,
            "funding_state_reference": funding_state_hash,
            "endpoint_payment_beneficiary": endpoint_beneficiary,
            "consumer_refund_beneficiary": refund_beneficiary,
            "proposal": proposal.model_dump(mode="json"),
        },
        evidence_references=[stale_predecessor, proposal.settlement_input_root],
        signatures=["ed25519:acceptance-stale-predecessor-probe"],
    )
    return json.dumps(
        envelope.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _broadcast(endpoint: str, transaction: bytes) -> dict[str, Any]:
    result = _rpc_get(endpoint, "/broadcast_tx_sync", tx=f"0x{transaction.hex()}")
    code = int(result.get("code", -1))
    log = str(result.get("log") or "")
    expected_hash = hashlib.sha256(transaction).hexdigest().upper()
    returned_hash = str(result.get("hash") or "").upper()
    if returned_hash and returned_hash != expected_hash:
        raise RuntimeError("rejected probe hash does not match transaction bytes")
    if code == 0:
        raise RuntimeError("stale predecessor proposal was accepted")
    if "funding predecessor" not in log.lower():
        raise RuntimeError(f"unexpected stale predecessor rejection: {result!r}")
    return {
        "transaction_hash": expected_hash,
        "code": code,
        "log": log,
    }


def run_stale_predecessor_drill(
    *, endpoint: str, source_report_path: Path
) -> dict[str, Any]:
    report = _load_source_report(source_report_path)
    transaction_hash = _lifecycle_lock_hash(report)
    before = _status(endpoint)
    lock = _load_committed_lock(endpoint, transaction_hash)
    transaction = _build_stale_proposal(lock)
    rejection = _broadcast(endpoint, transaction)
    time.sleep(1)
    after = _status(endpoint)
    if before["node_id"] != after["node_id"] or before["chain_id"] != after["chain_id"]:
        raise RuntimeError("validator identity changed during stale predecessor probe")
    result = {
        "schema_version": 1,
        "status": "PASS",
        "scope": "CONTROLLED_LAN_TESTNET",
        "drill": "STALE_PREDECESSOR_REJECTED",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "rpc_url": endpoint.rstrip("/"),
        "source_report": str(source_report_path),
        "source_transaction_hash": transaction_hash,
        "session_id": lock["session_id"],
        "before": before,
        "after": after,
        "rejection": rejection,
        "checks": {
            "transaction_rejected": True,
            "funding_predecessor_error": True,
            "validator_identity_preserved": True,
        },
    }
    result["evidence_reference"] = "sha256:" + hashlib.sha256(
        json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = run_stale_predecessor_drill(
            endpoint=args.rpc_url, source_report_path=args.source_report
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}, sort_keys=True))
        return 2
    encoded = json.dumps(result, ensure_ascii=True, indent=2) + "\n"
    print(encoded, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
