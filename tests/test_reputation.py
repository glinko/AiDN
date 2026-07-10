from aidn_hypervisor import reputation as reputation_module
from aidn_hypervisor.reputation import build_reputation_profile


def test_build_reputation_profile_returns_score_tier_components_and_evidence() -> None:
    profile = build_reputation_profile(
        node_status="ready",
        heartbeat_fresh=True,
        trust_summary={
            "total_endpoints": 4,
            "certified_count": 2,
            "certified_with_issues_count": 1,
            "validated_count": 3,
            "pending_count": 1,
            "attention_count": 0,
            "in_sync_count": 3,
            "drift_count": 1,
        },
        operational_stats={
            "total_tasks": 20,
            "successful_tasks": 18,
            "failed_tasks": 2,
        },
        baseline_rating={"score": 0.40, "tier": "C", "updated_at": "2026-07-10T00:00:00+00:00"},
        updated_at="2026-07-10T09:15:00+00:00",
    )

    assert profile["score"] > 0.0
    assert profile["tier"] in {"A", "B", "C", "D", "unrated"}
    assert profile["components"]["freshness"] > 0.0
    assert profile["components"]["publication_integrity"] > 0.0
    assert profile["components"]["validation_posture"] > 0.0
    assert profile["components"]["operational_reliability"] > 0.0
    assert profile["evidence"]["node_status"] == "ready"
    assert profile["evidence"]["published_endpoint_count"] == 4


def test_build_reputation_profile_penalizes_stale_and_drifted_nodes() -> None:
    healthy = build_reputation_profile(
        node_status="ready",
        heartbeat_fresh=True,
        trust_summary={
            "total_endpoints": 2,
            "certified_count": 1,
            "certified_with_issues_count": 0,
            "validated_count": 1,
            "pending_count": 0,
            "attention_count": 0,
            "in_sync_count": 2,
            "drift_count": 0,
        },
        operational_stats={"total_tasks": 10, "successful_tasks": 10, "failed_tasks": 0},
        baseline_rating={"score": 0.50, "tier": "C", "updated_at": "2026-07-10T00:00:00+00:00"},
        updated_at="2026-07-10T09:15:00+00:00",
    )
    degraded = build_reputation_profile(
        node_status="stale",
        heartbeat_fresh=False,
        trust_summary={
            "total_endpoints": 2,
            "certified_count": 0,
            "certified_with_issues_count": 0,
            "validated_count": 0,
            "pending_count": 1,
            "attention_count": 1,
            "in_sync_count": 0,
            "drift_count": 2,
        },
        operational_stats={"total_tasks": 10, "successful_tasks": 6, "failed_tasks": 4},
        baseline_rating={"score": 0.50, "tier": "C", "updated_at": "2026-07-10T00:00:00+00:00"},
        updated_at="2026-07-10T09:15:00+00:00",
    )

    assert healthy["score"] > degraded["score"]
    assert healthy["components"]["freshness"] > degraded["components"]["freshness"]
    assert healthy["components"]["publication_integrity"] > degraded["components"]["publication_integrity"]


def test_build_reputation_profile_uses_unrated_tier_when_no_signal_exists(monkeypatch) -> None:
    observed: dict[str, tuple] = {}

    def _spy_signal_present(*values):
        observed["values"] = values
        return False

    monkeypatch.setattr(reputation_module, "_signal_present", _spy_signal_present)

    profile = build_reputation_profile(
        node_status="offline",
        heartbeat_fresh=False,
        trust_summary={
            "total_endpoints": 0,
            "certified_count": 0,
            "certified_with_issues_count": 0,
            "validated_count": 0,
            "pending_count": 0,
            "attention_count": 0,
            "in_sync_count": 0,
            "drift_count": 0,
        },
        operational_stats={"total_tasks": 0, "successful_tasks": 0, "failed_tasks": 0},
        baseline_rating={"score": 0.87, "tier": "B", "updated_at": "2026-07-10T00:00:00+00:00"},
        updated_at="2026-07-10T09:15:00+00:00",
    )

    assert profile["score"] == 0.0
    assert profile["tier"] == "unrated"
    assert observed["values"] == (
        "offline",
        False,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )
    assert profile["components"]["freshness"] == 0.0
    assert profile["components"]["publication_integrity"] == 0.0
    assert profile["components"]["validation_posture"] == 0.0
    assert profile["components"]["operational_reliability"] == 0.0
