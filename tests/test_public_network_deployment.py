from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/verify-public-network-deployment.py"
SPEC = importlib.util.spec_from_file_location("public_network_deployment", TOOL)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _fetch(url: str, path: str, timeout: float) -> dict:
    suffix = "a" if "rpc-a" in url else "b"
    if path == "/status":
        return {
            "result": {
                "node_info": {"id": f"node-{suffix}", "network": "aidn-public"},
                "sync_info": {"latest_block_height": "42"},
            }
        }
    return {
        "result": {
            "listening": True,
            "n_peers": "2",
            "peers": [
                {
                    "node_info": {"id": "peer-1"},
                    "remote_ip": "203.0.113.1",
                },
                {
                    "node_info": {"id": "peer-2"},
                    "remote_ip": "203.0.113.2",
                },
            ],
        }
    }


def test_public_deployment_collector_emits_hash_bound_pass_checks() -> None:
    report = MODULE.collect_report(
        rpc_urls=["https://rpc-a.example", "https://rpc-b.example"],
        fetcher=_fetch,
    )

    assert report["status"] == "ok"
    assert report["scope"] == "PUBLIC_NETWORK_DEPLOYMENT"
    assert all(item["status"] == "PASS" for item in report["checks"].values())
    assert all(
        item["evidence_reference"].startswith("sha256:")
        for item in report["checks"].values()
    )
    assert report["peer_summary"] == {
        "distinct_peer_ids": 2,
        "distinct_remote_hosts": 2,
    }


def test_public_deployment_collector_fails_diversity_check_without_enough_hosts() -> None:
    def fetch_same_host(url: str, path: str, timeout: float) -> dict:
        response = _fetch(url, path, timeout)
        if path == "/net_info":
            for peer in response["result"]["peers"]:
                peer["remote_ip"] = "203.0.113.1"
        return response

    report = MODULE.collect_report(
        rpc_urls=["https://rpc-a.example", "https://rpc-b.example"],
        minimum_bootstrap_hosts=2,
        fetcher=fetch_same_host,
    )

    assert report["checks"]["public_p2p_acceptance"]["status"] == "PASS"
    assert report["checks"]["bootstrap_diversity"]["status"] == "FAIL"
    assert report["checks"]["tls_validated"]["status"] == "PASS"


def test_public_deployment_collector_rejects_non_https_or_duplicate_endpoints() -> None:
    with pytest.raises(ValueError, match="credential-free HTTPS"):
        MODULE.collect_report(
            rpc_urls=["http://rpc-a.example", "https://rpc-b.example"],
            fetcher=_fetch,
        )

    with pytest.raises(ValueError, match="unique"):
        MODULE.collect_report(
            rpc_urls=["https://rpc-a.example", "https://rpc-a.example"],
            fetcher=_fetch,
        )
