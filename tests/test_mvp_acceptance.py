from __future__ import annotations

import pytest

from tools.run_mvp_acceptance import AcceptanceError, _junit_cases, validate_wallet_reconciliation


def test_junit_cases_capture_restart_test_status(tmp_path) -> None:
    report = tmp_path / "results.xml"
    report.write_text(
        """<testsuites><testsuite name='live'>
        <testcase classname='live' name='test_restart' time='1.25'/>
        <testcase classname='live' name='test_failure' time='0.1'><failure>boom</failure></testcase>
        </testsuite></testsuites>""",
        encoding="utf-8",
    )

    assert _junit_cases(report) == [
        {
            "classname": "live",
            "name": "test_restart",
            "status": "passed",
            "duration_seconds": 1.25,
            "detail": "",
        },
        {
            "classname": "live",
            "name": "test_failure",
            "status": "failed",
            "duration_seconds": 0.1,
            "detail": "boom",
        },
    ]


def _wallet_reconciliation() -> dict:
    return {
        "summary": {
            "wallet_count": 1,
            "consistent_count": 1,
            "conflict_count": 0,
            "resolved_count": 0,
            "divergent_count": 0,
            "enabled_peer_count": 1,
            "peer_error_count": 0,
            "peer_pending_count": 0,
        },
        "known_peers": [
            {
                "peer_base_url": "http://peer.example:8000",
                "enabled": True,
                "last_sync_status": "ok",
                "expected_node_id": "node-peer",
                "expected_operator_id": "operator-peer",
                "expected_owner_wallet_id": "wallet-peer",
            }
        ],
        "items": [{"wallet_id": "wallet-peer", "status": "consistent"}],
    }


def test_wallet_reconciliation_requires_pinned_successful_peer() -> None:
    result = validate_wallet_reconciliation(
        _wallet_reconciliation(),
        wallet_id="wallet-peer",
        peer_base_url="http://peer.example:8000",
    )

    assert result["status"] == "passed"
    assert result["peers"][0]["expected_node_id"] == "node-peer"


@pytest.mark.parametrize(
    "field,value",
    [
        ("conflict_count", 1),
        ("peer_error_count", 1),
        ("peer_pending_count", 1),
        ("consistent_count", 0),
    ],
)
def test_wallet_reconciliation_fails_closed(field: str, value: int) -> None:
    payload = _wallet_reconciliation()
    payload["summary"][field] = value

    with pytest.raises(AcceptanceError):
        validate_wallet_reconciliation(payload)


@pytest.mark.parametrize("collection", ["items", "known_peers"])
def test_wallet_reconciliation_fails_closed_when_summary_has_no_records(collection: str) -> None:
    payload = _wallet_reconciliation()
    payload[collection] = []

    with pytest.raises(AcceptanceError):
        validate_wallet_reconciliation(payload)


def test_wallet_reconciliation_rejects_disabled_peer() -> None:
    payload = _wallet_reconciliation()
    payload["known_peers"][0]["enabled"] = False

    with pytest.raises(AcceptanceError):
        validate_wallet_reconciliation(payload)
