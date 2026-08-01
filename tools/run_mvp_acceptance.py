#!/usr/bin/env python3
"""Run the functional MVP acceptance gate.

The runner intentionally treats provider and wallet acceptance as separate
checks. A provider smoke can be run without a wallet API, but an MVP release
report is successful only when both checks pass.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


class AcceptanceError(RuntimeError):
    """Raised when a required acceptance invariant is not satisfied."""


PROVIDER_PROFILES: dict[str, dict[str, str]] = {
    "llamacpp": {
        "endpoint_env": "AIDN_LLAMACPP_ENDPOINT",
        "model_env": "AIDN_LLAMACPP_MODEL",
        "live_env": "AIDN_LLAMACPP_LIVE",
        "test_file": "tests/integration/test_llamacpp_live.py",
        "restart_test": "test_llamacpp_live_fixed_price_session_executes_and_settles_after_restart",
    },
    "vllm": {
        "endpoint_env": "AIDN_VLLM_ENDPOINT",
        "model_env": "AIDN_VLLM_MODEL",
        "test_file": "tests/integration/test_vllm_live.py",
        "restart_test": "test_live_vllm_public_paid_session_settles_after_restart",
    },
    "ollama": {
        "endpoint_env": "AIDN_OLLAMA_ENDPOINT",
        "model_env": "AIDN_OLLAMA_MODEL",
        "test_file": "tests/integration/test_ollama_live.py",
        "restart_test": "test_live_ollama_public_paid_session_settles_after_restart",
    },
}


def _trim_output(value: str, *, limit: int = 4_000) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return "..." + value[-limit:]


def _git_commit(repo_root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _junit_cases(path: Path) -> list[dict[str, Any]]:
    root = ElementTree.parse(path).getroot()
    cases: list[dict[str, Any]] = []
    for testcase in root.iter("testcase"):
        status = "passed"
        detail = ""
        if testcase.find("failure") is not None:
            status = "failed"
            detail = testcase.findtext("failure", default="")
        elif testcase.find("error") is not None:
            status = "error"
            detail = testcase.findtext("error", default="")
        elif testcase.find("skipped") is not None:
            status = "skipped"
            detail = testcase.findtext("skipped", default="")
        cases.append(
            {
                "classname": testcase.get("classname"),
                "name": testcase.get("name"),
                "status": status,
                "duration_seconds": float(testcase.get("time") or 0),
                "detail": _trim_output(detail),
            }
        )
    return cases


def _run_provider(
    *,
    repo_root: Path,
    provider: str,
    endpoint: str,
    model: str,
    evidence_dir: Path | None,
) -> dict[str, Any]:
    profile = PROVIDER_PROFILES[provider]
    environment = os.environ.copy()
    environment[profile["endpoint_env"]] = endpoint
    environment[profile["model_env"]] = model
    if live_env := profile.get("live_env"):
        environment[live_env] = "1"

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"aidn-mvp-{provider}-") as temporary:
        junit_path = Path(temporary) / f"{provider}.xml"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            profile["test_file"],
            "--no-cov",
            f"--junitxml={junit_path}",
        ]
        completed = subprocess.run(
            command,
            cwd=repo_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        cases = _junit_cases(junit_path) if junit_path.exists() else []
        restart_cases = [
            case for case in cases if case["name"] == profile["restart_test"]
        ]
        if not restart_cases:
            status = "failed"
            failure = f"Required restart/idempotency test was not collected: {profile['restart_test']}"
        elif completed.returncode != 0 or any(
            case["status"] != "passed" for case in cases
        ):
            status = "failed"
            failure = "One or more live provider conformance tests failed"
        else:
            status = "passed"
            failure = None

        if evidence_dir is not None and junit_path.exists():
            evidence_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(junit_path, evidence_dir / f"provider-{provider}.xml")

    return {
        "provider": provider,
        "endpoint": endpoint,
        "model": model,
        "test_file": profile["test_file"],
        "restart_test": profile["restart_test"],
        "status": status,
        "failure": failure,
        "return_code": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "tests": cases,
        "stdout_tail": _trim_output(completed.stdout),
        "stderr_tail": _trim_output(completed.stderr),
    }


def _fetch_json(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise AcceptanceError(f"Failed to fetch JSON from {url}") from error
    if not isinstance(payload, dict):
        raise AcceptanceError(f"Acceptance endpoint returned a non-object: {url}")
    return payload


def validate_wallet_reconciliation(
    payload: dict[str, Any],
    *,
    wallet_id: str | None = None,
    peer_base_url: str | None = None,
) -> dict[str, Any]:
    """Validate the persisted, signed-peer wallet reconciliation read model."""
    summary = payload.get("summary")
    peers = payload.get("known_peers")
    items = payload.get("items")
    if not isinstance(summary, dict) or not isinstance(peers, list) or not isinstance(items, list):
        raise AcceptanceError("Wallet reconciliation payload has an invalid shape")

    required_zeroes = ("conflict_count", "divergent_count", "peer_error_count", "peer_pending_count")
    for field in required_zeroes:
        if int(summary.get(field, -1)) != 0:
            raise AcceptanceError(f"Wallet reconciliation has non-zero {field}")
    if int(summary.get("enabled_peer_count", 0)) < 1:
        raise AcceptanceError("Wallet reconciliation has no enabled peer")
    if int(summary.get("consistent_count", 0)) < 1:
        raise AcceptanceError("Wallet reconciliation has no consistent wallet identity")

    matching_items = [item for item in items if isinstance(item, dict)]
    if wallet_id is not None:
        matching_items = [item for item in matching_items if item.get("wallet_id") == wallet_id]
        if not matching_items:
            raise AcceptanceError(f"Wallet identity is missing from reconciliation: {wallet_id}")
    elif not matching_items:
        raise AcceptanceError("Wallet reconciliation contains no wallet identities")
    if any(item.get("status") != "consistent" for item in matching_items):
        raise AcceptanceError("Wallet reconciliation contains a non-consistent identity")

    matching_peers = [peer for peer in peers if isinstance(peer, dict)]
    if peer_base_url is not None:
        matching_peers = [
            peer for peer in matching_peers if peer.get("peer_base_url") == peer_base_url
        ]
        if not matching_peers:
            raise AcceptanceError(f"Configured wallet peer is missing: {peer_base_url}")
    elif not matching_peers:
        raise AcceptanceError("Wallet reconciliation contains no configured peers")
    for peer in matching_peers:
        if peer.get("enabled") is not True:
            raise AcceptanceError("Wallet peer is not enabled")
        if peer.get("last_sync_status") != "ok":
            raise AcceptanceError("Wallet peer has not completed a successful sync")
        for field in ("expected_node_id", "expected_operator_id", "expected_owner_wallet_id"):
            if not peer.get(field):
                raise AcceptanceError(f"Wallet peer is not pinned by {field}")

    return {
        "status": "passed",
        "summary": summary,
        "wallets": matching_items,
        "peers": matching_peers,
    }


def _provider_argument(parser: argparse.ArgumentParser, provider: str) -> None:
    profile = PROVIDER_PROFILES[provider]
    parser.add_argument(
        f"--{provider}-endpoint",
        default=os.environ.get(profile["endpoint_env"], ""),
        help=f"Live {provider} endpoint (default: {profile['endpoint_env']})",
    )
    parser.add_argument(
        f"--{provider}-model",
        default=os.environ.get(profile["model_env"], ""),
        help=f"Live {provider} model (default: {profile['model_env']})",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the AiDN functional MVP acceptance gate")
    parser.add_argument(
        "--provider",
        action="append",
        choices=sorted(PROVIDER_PROFILES),
        dest="providers",
        help="Provider profile to run; repeatable, defaults to all profiles",
    )
    for provider in PROVIDER_PROFILES:
        _provider_argument(parser, provider)
    parser.add_argument("--wallet-api-url", help="Base URL exposing wallet reconciliation")
    parser.add_argument("--wallet-id")
    parser.add_argument("--wallet-peer-base-url")
    parser.add_argument("--wallet-timeout", type=float, default=15)
    parser.add_argument("--skip-wallet", action="store_true")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="Directory for the JSON report and JUnit evidence",
    )
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)

    providers = args.providers or sorted(PROVIDER_PROFILES)
    report: dict[str, Any] = {
        "profile": "MVP-0001",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(args.repo_root),
        "operator_independence_policy": {
            "status": "accepted_by_project_policy",
            "subject": "hv-node10",
            "protocol_evidence": "NOT_PROVEN_BY_PROTOCOL",
        },
        "checks": {},
    }

    provider_results: list[dict[str, Any]] = []
    for provider in providers:
        endpoint = str(getattr(args, f"{provider}_endpoint") or "").strip()
        model = str(getattr(args, f"{provider}_model") or "").strip()
        if not endpoint or not model:
            parser.error(f"{provider} requires endpoint and model")
        provider_results.append(
            _run_provider(
                repo_root=args.repo_root,
                provider=provider,
                endpoint=endpoint,
                model=model,
                evidence_dir=args.evidence_dir,
            )
        )

    provider_status = "passed" if all(item["status"] == "passed" for item in provider_results) else "failed"
    report["checks"]["real_provider_conformance"] = {
        "status": provider_status,
        "providers": provider_results,
    }
    report["checks"]["restart_recovery_idempotency"] = {
        "status": provider_status,
        "basis": "provider-specific fixed-price restart tests",
        "providers": [
            {
                "provider": item["provider"],
                "restart_test": item["restart_test"],
                "status": item["status"],
            }
            for item in provider_results
        ],
    }

    if args.skip_wallet:
        wallet_result = {"status": "skipped", "reason": "--skip-wallet"}
    elif not args.wallet_api_url:
        wallet_result = {"status": "failed", "error": "--wallet-api-url is required"}
    else:
        try:
            wallet_payload = _fetch_json(
                args.wallet_api_url.rstrip("/") + "/registry/wallet-identities/reconciliation",
                timeout_seconds=args.wallet_timeout,
            )
            wallet_result = validate_wallet_reconciliation(
                wallet_payload,
                wallet_id=args.wallet_id,
                peer_base_url=args.wallet_peer_base_url,
            )
        except AcceptanceError as error:
            wallet_result = {"status": "failed", "error": str(error)}
    report["checks"]["authoritative_wallet_identity_sync"] = wallet_result

    release_ready = (
        provider_status == "passed"
        and wallet_result.get("status") == "passed"
    )
    report["checks"]["mvp_release_readiness"] = {
        "status": "passed" if release_ready else "failed",
        "required_checks": [
            "authoritative_wallet_identity_sync",
            "real_provider_conformance",
            "restart_recovery_idempotency",
        ],
    }
    report["status"] = "passed" if release_ready else "failed"

    encoded = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.evidence_dir is not None:
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        (args.evidence_dir / "mvp-acceptance.json").write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
