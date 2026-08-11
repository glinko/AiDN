#!/usr/bin/env python3
"""Run a secret-safe live acceptance check against an AiDN Faucet service.

The runner creates an ephemeral recipient Wallet in process memory, proves
control through the normal challenge flow, and verifies the fixed-daily
idempotency and quota boundaries. It never writes a private key, bearer token,
or signed transfer envelope to the evidence report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class AcceptanceError(RuntimeError):
    """Raised when the live Faucet boundary does not meet its contract."""


FINAL_CLAIM_STATES = frozenset({"APPROVED", "ALREADY_CLAIMED"})
RETRYABLE_CLAIM_STATES = frozenset({"PENDING_FINALITY", "SUBMISSION_UNKNOWN"})


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def wallet_public_key(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return "ed25519:" + raw.hex()


def wallet_id_for_public_key(public_key: str) -> str:
    return "wallet-" + hashlib.sha256(public_key.encode("utf-8")).hexdigest()[:12]


def challenge_signing_bytes(challenge: dict[str, Any]) -> bytes:
    required = ("challenge_id", "wallet_id", "challenge")
    if any(not isinstance(challenge.get(field), str) or not challenge[field] for field in required):
        raise AcceptanceError("Faucet challenge has an invalid shape")
    return canonical_json(
        {
            "domain": "aidn.faucet-wallet-proof.v1",
            "challenge_id": challenge["challenge_id"],
            "wallet_id": challenge["wallet_id"],
            "challenge": challenge["challenge"],
        }
    )


def _json_request(
    *,
    url: str,
    method: str,
    token: str | None,
    payload: dict[str, Any] | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    body = None if payload is None else canonical_json(payload)
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        raise AcceptanceError(f"HTTP {error.code} from {url}: {detail}") from error
    except (OSError, urllib.error.URLError) as error:
        raise AcceptanceError(f"Request failed for {url}: {error}") from error
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AcceptanceError(f"Response from {url} is not JSON") from error
    if not isinstance(decoded, dict):
        raise AcceptanceError(f"Response from {url} is not a JSON object")
    return decoded


def _claim_request(
    *,
    base_url: str,
    token: str,
    private_key: Ed25519PrivateKey,
    wallet_id: str,
    public_key: str,
    request_id: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    challenge = _json_request(
        url=f"{base_url}/v1/challenges",
        method="POST",
        token=token,
        payload={"wallet_id": wallet_id, "wallet_public_key": public_key},
        timeout_seconds=timeout_seconds,
    )
    signature = "ed25519:" + private_key.sign(challenge_signing_bytes(challenge)).hex()
    return _json_request(
        url=f"{base_url}/v1/claims",
        method="POST",
        token=token,
        payload={
            "request_id": request_id,
            "wallet_id": wallet_id,
            "wallet_public_key": public_key,
            "challenge_id": challenge["challenge_id"],
            "wallet_signature": signature,
        },
        timeout_seconds=timeout_seconds,
    )


def _reconcile_until_final(
    *,
    base_url: str,
    token: str,
    response: dict[str, Any],
    timeout_seconds: float,
    finality_timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + finality_timeout_seconds
    while response.get("status") in RETRYABLE_CLAIM_STATES:
        if time.monotonic() >= deadline:
            raise AcceptanceError(
                "Faucet claim did not reach finality before the acceptance timeout: "
                f"{response.get('status')}"
            )
        time.sleep(poll_interval_seconds)
        request_id = response.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise AcceptanceError("Retryable Faucet claim does not include request_id")
        response = _json_request(
            url=f"{base_url}/v1/claims/{request_id}/reconcile",
            method="POST",
            token=token,
            payload={},
            timeout_seconds=timeout_seconds,
        )
    return response


def _redacted_claim(response: dict[str, Any]) -> dict[str, Any]:
    return {
        field: response.get(field)
        for field in (
            "request_id",
            "claim_id",
            "status",
            "amount_q_atoms",
            "operation_id",
            "transaction_hash",
            "policy_id",
            "policy_version",
            "detail",
        )
    }


def run_acceptance(
    *,
    base_url: str,
    agent_token: str,
    timeout_seconds: float,
    finality_timeout_seconds: float,
    poll_interval_seconds: float,
    expected_amount_q_atoms: int | None,
    assert_quota: bool,
) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    health = _json_request(
        url=f"{base_url}/health",
        method="GET",
        token=None,
        payload=None,
        timeout_seconds=timeout_seconds,
    )
    if health.get("status") != "ok" or health.get("service") != "aidn-faucet":
        raise AcceptanceError("Faucet health endpoint does not identify an active aidn-faucet service")
    status = _json_request(
        url=f"{base_url}/v1/status",
        method="GET",
        token=agent_token,
        payload=None,
        timeout_seconds=timeout_seconds,
    )
    if status.get("treasury_activation_state") != "ACTIVE":
        raise AcceptanceError(
            "Faucet Treasury is not canonically active: "
            f"{status.get('treasury_activation_state')} ({status.get('treasury_activation_reason')})"
        )
    if status.get("paused") is True or status.get("low_balance_blocked") is True:
        raise AcceptanceError("Faucet claims are disabled by creator controls")

    private_key = Ed25519PrivateKey.generate()
    public_key = wallet_public_key(private_key)
    wallet_id = wallet_id_for_public_key(public_key)
    nonce = secrets.token_hex(8)
    request_id = f"live-acceptance-{nonce}"
    first = _reconcile_until_final(
        base_url=base_url,
        token=agent_token,
        response=_claim_request(
            base_url=base_url,
            token=agent_token,
            private_key=private_key,
            wallet_id=wallet_id,
            public_key=public_key,
            request_id=request_id,
            timeout_seconds=timeout_seconds,
        ),
        timeout_seconds=timeout_seconds,
        finality_timeout_seconds=finality_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    if first.get("status") not in FINAL_CLAIM_STATES:
        raise AcceptanceError(f"Faucet claim was not finalized: {first.get('status')}")
    if expected_amount_q_atoms is not None and first.get("amount_q_atoms") != expected_amount_q_atoms:
        raise AcceptanceError(
            "Faucet claim amount does not match the selected policy: "
            f"{first.get('amount_q_atoms')} != {expected_amount_q_atoms}"
        )

    replay = _json_request(
        url=f"{base_url}/v1/claims/{request_id}/reconcile",
        method="POST",
        token=agent_token,
        payload={},
        timeout_seconds=timeout_seconds,
    )
    if replay.get("operation_id") != first.get("operation_id") or replay.get("status") not in FINAL_CLAIM_STATES:
        raise AcceptanceError("Faucet reconciliation did not retain the exact finalized claim")

    quota_result: dict[str, Any] | None = None
    if assert_quota:
        quota_result = _claim_request(
            base_url=base_url,
            token=agent_token,
            private_key=private_key,
            wallet_id=wallet_id,
            public_key=public_key,
            request_id=f"{request_id}-quota",
            timeout_seconds=timeout_seconds,
        )
        if quota_result.get("status") != "QUOTA_EXHAUSTED":
            raise AcceptanceError(
                "Fixed-daily Faucet policy did not reject a second same-Wallet claim: "
                f"{quota_result.get('status')}"
            )

    return {
        "schema_version": 1,
        "profile": "aidn-faucet-live-acceptance.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS",
        "faucet_url": base_url,
        "ephemeral_recipient_wallet": wallet_id,
        "faucet_status": {
            key: status.get(key)
            for key in (
                "treasury_id",
                "treasury_wallet_id",
                "policy_id",
                "policy_version",
                "policy_registry_hash",
                "treasury_activation_state",
                "treasury_balance_q_atoms",
            )
        },
        "claim": _redacted_claim(first),
        "idempotent_reconcile": _redacted_claim(replay),
        "quota_check": _redacted_claim(quota_result) if quota_result is not None else None,
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    serialized = canonical_json(report)
    report = dict(report)
    report["report_hash"] = "sha256:" + hashlib.sha256(serialized).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_json(report) + b"\n")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the AiDN Faucet live acceptance check")
    parser.add_argument("--faucet-url", default=os.environ.get("AIDN_FAUCET_URL", ""))
    parser.add_argument("--agent-token", default=os.environ.get("AIDN_FAUCET_AGENT_TOKEN", ""))
    parser.add_argument("--timeout-seconds", type=float, default=15)
    parser.add_argument("--finality-timeout-seconds", type=float, default=120)
    parser.add_argument("--poll-interval-seconds", type=float, default=2)
    parser.add_argument("--expected-amount-q-atoms", type=int, default=50_000_000)
    parser.add_argument(
        "--skip-quota-check",
        action="store_true",
        help="Use only for a policy that intentionally permits repeated claims.",
    )
    parser.add_argument("--output", type=Path, help="Write a secret-free JSON evidence report")
    args = parser.parse_args(argv)
    if not args.faucet_url:
        parser.error("--faucet-url or AIDN_FAUCET_URL is required")
    if not args.agent_token:
        parser.error("--agent-token or AIDN_FAUCET_AGENT_TOKEN is required")
    if args.timeout_seconds <= 0 or args.finality_timeout_seconds <= 0 or args.poll_interval_seconds <= 0:
        parser.error("timeout values must be positive")
    if args.expected_amount_q_atoms <= 0:
        parser.error("--expected-amount-q-atoms must be positive")

    try:
        report = run_acceptance(
            base_url=args.faucet_url,
            agent_token=args.agent_token,
            timeout_seconds=args.timeout_seconds,
            finality_timeout_seconds=args.finality_timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            expected_amount_q_atoms=args.expected_amount_q_atoms,
            assert_quota=not args.skip_quota_check,
        )
    except AcceptanceError as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 1
    if args.output is not None:
        _write_report(args.output, report)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
