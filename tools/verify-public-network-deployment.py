#!/usr/bin/env python3
"""Collect read-only public CometBFT deployment evidence for G4.

The collector never submits transactions or changes validator state. HTTPS
certificate validation is delegated to the platform trust store used by
``urllib``; the resulting observations are committed through per-check hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import ssl
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 15.0


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _evidence_reference(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _normalize_rpc_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("RPC endpoint must be credential-free HTTPS without path/query/fragment")
    return f"https://{parsed.netloc}"


def _fetch_json(url: str, path: str, timeout_seconds: float) -> dict[str, Any]:
    request = Request(
        url.rstrip("/") + path,
        headers={
            "Accept": "application/json",
            "User-Agent": "aidn-g4-deployment-verifier/1",
        },
    )
    context = ssl.create_default_context()
    try:
        with urlopen(request, timeout=timeout_seconds, context=context) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise ValueError(f"public RPC request failed for {path}: {error}") from error
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError(f"public RPC response exceeds {MAX_RESPONSE_BYTES} bytes: {path}")
    try:
        value = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"public RPC response is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"public RPC response must be an object: {path}")
    return value


Fetcher = Callable[[str, str, float], dict[str, Any]]


def _result(payload: dict[str, Any], *, path: str) -> dict[str, Any]:
    value = payload.get("result")
    if not isinstance(value, dict):
        raise ValueError(f"public RPC {path} response lacks result object")
    return value


def _integer(value: object, *, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"public RPC field is not an integer: {field}") from error
    if number < 0:
        raise ValueError(f"public RPC field cannot be negative: {field}")
    return number


def _endpoint_observation(
    url: str,
    *,
    timeout_seconds: float,
    fetcher: Fetcher,
) -> dict[str, Any]:
    status_payload = fetcher(url, "/status", timeout_seconds)
    net_info_payload = fetcher(url, "/net_info", timeout_seconds)
    status = _result(status_payload, path="/status")
    net_info = _result(net_info_payload, path="/net_info")
    node_info = status.get("node_info")
    if not isinstance(node_info, dict):
        raise ValueError("public RPC /status response lacks node_info")
    network = node_info.get("network")
    if not isinstance(network, str) or not network:
        raise ValueError("public RPC /status response lacks node_info.network")
    latest_block = status.get("sync_info")
    if not isinstance(latest_block, dict):
        raise ValueError("public RPC /status response lacks sync_info")
    peers = net_info.get("peers")
    if not isinstance(peers, list):
        raise ValueError("public RPC /net_info response lacks peers list")
    peer_summaries: list[dict[str, str]] = []
    for peer in peers:
        if not isinstance(peer, dict):
            continue
        peer_node_info = peer.get("node_info")
        if not isinstance(peer_node_info, dict):
            continue
        peer_id = peer_node_info.get("id")
        remote_ip = peer.get("remote_ip")
        if isinstance(peer_id, str) and peer_id and isinstance(remote_ip, str) and remote_ip:
            peer_summaries.append({"peer_id": peer_id, "remote_ip": remote_ip})
    observation = {
        "rpc_url": url,
        "network": network,
        "node_id": node_info.get("id"),
        "latest_block_height": latest_block.get("latest_block_height"),
        "listening": net_info.get("listening"),
        "n_peers": _integer(net_info.get("n_peers"), field="n_peers"),
        "peers": sorted(peer_summaries, key=lambda item: (item["peer_id"], item["remote_ip"])),
    }
    if not isinstance(observation["node_id"], str) or not observation["node_id"]:
        raise ValueError("public RPC /status response lacks node_info.id")
    if not isinstance(observation["latest_block_height"], str) or not observation["latest_block_height"]:
        raise ValueError("public RPC /status response lacks latest_block_height")
    if not isinstance(observation["listening"], bool):
        raise ValueError("public RPC /net_info response lacks boolean listening")
    return observation


def collect_report(
    *,
    rpc_urls: list[str],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    minimum_peers: int = 1,
    minimum_bootstrap_peers: int = 2,
    minimum_bootstrap_hosts: int = 2,
    fetcher: Fetcher = _fetch_json,
) -> dict[str, Any]:
    if not rpc_urls:
        raise ValueError("at least two RPC endpoints are required")
    normalized_urls = [_normalize_rpc_url(value) for value in rpc_urls]
    if len(normalized_urls) < 2:
        raise ValueError("at least two RPC endpoints are required")
    if len(set(normalized_urls)) != len(normalized_urls):
        raise ValueError("RPC endpoints must be unique")
    if timeout_seconds <= 0 or minimum_peers < 0 or minimum_bootstrap_peers < 1 or minimum_bootstrap_hosts < 1:
        raise ValueError("deployment thresholds and timeout must be positive")

    observations: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for url in normalized_urls:
        try:
            observation = _endpoint_observation(
                url,
                timeout_seconds=timeout_seconds,
                fetcher=fetcher,
            )
        except ValueError as error:
            failure = {"rpc_url": url, "error": str(error)}
            failures.append(failure)
            observations.append({"rpc_url": url, "status": "FAIL", "error": str(error)})
        else:
            observations.append({"status": "PASS", **observation})

    passed_observations = [item for item in observations if item.get("status") == "PASS"]
    all_responses_passed = len(passed_observations) == len(normalized_urls)
    network_ids = {str(item["network"]) for item in passed_observations}
    network_consistent = len(network_ids) == 1
    peer_entries = [peer for item in passed_observations for peer in item.get("peers", [])]
    distinct_peer_ids = {str(peer["peer_id"]) for peer in peer_entries}
    distinct_remote_hosts = {str(peer["remote_ip"]) for peer in peer_entries}
    p2p_ready = all_responses_passed and network_consistent and all(
        item.get("listening") is True and int(item.get("n_peers", -1)) >= minimum_peers
        for item in passed_observations
    )
    bootstrap_ready = (
        all_responses_passed
        and network_consistent
        and len(distinct_peer_ids) >= minimum_bootstrap_peers
        and len(distinct_remote_hosts) >= minimum_bootstrap_hosts
    )
    reference_payload = {
        "observations": observations,
        "failures": failures,
        "thresholds": {
            "minimum_peers": minimum_peers,
            "minimum_bootstrap_peers": minimum_bootstrap_peers,
            "minimum_bootstrap_hosts": minimum_bootstrap_hosts,
        },
    }
    checks = {
        "public_p2p_acceptance": {
            "status": "PASS" if p2p_ready else "FAIL",
            "evidence_reference": _evidence_reference(reference_payload),
        },
        "bootstrap_diversity": {
            "status": "PASS" if bootstrap_ready else "FAIL",
            "evidence_reference": _evidence_reference(reference_payload),
        },
        "tls_validated": {
            "status": "PASS" if all_responses_passed else "FAIL",
            "evidence_reference": _evidence_reference(
                {"rpc_urls": normalized_urls, "transport": "HTTPS_CERTIFICATE_VALIDATED"}
            ),
        },
    }
    return {
        "schema_version": 1,
        "status": "ok",
        "scope": "PUBLIC_NETWORK_DEPLOYMENT",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "rpc_endpoints": normalized_urls,
        "network_ids": sorted(network_ids),
        "observations": observations,
        "failures": failures,
        "peer_summary": {
            "distinct_peer_ids": len(distinct_peer_ids),
            "distinct_remote_hosts": len(distinct_remote_hosts),
        },
        "checks": checks,
        "limitations": [
            "RPC peer observations do not prove independent operator ownership",
            "bootstrap diversity is based on observed peer IDs and remote hosts",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", action="append", required=True, help="credential-free HTTPS RPC endpoint; repeat")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--minimum-peers", type=int, default=1)
    parser.add_argument("--minimum-bootstrap-peers", type=int, default=2)
    parser.add_argument("--minimum-bootstrap-hosts", type=int, default=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = collect_report(
            rpc_urls=args.rpc_url,
            timeout_seconds=args.timeout_seconds,
            minimum_peers=args.minimum_peers,
            minimum_bootstrap_peers=args.minimum_bootstrap_peers,
            minimum_bootstrap_hosts=args.minimum_bootstrap_hosts,
        )
    except (OSError, ValueError, TypeError) as error:
        payload = {"status": "FAIL", "reason": str(error)}
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        return 2
    encoded = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    print(encoded, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    return 0 if all(item["status"] == "PASS" for item in report["checks"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
