from datetime import datetime, timezone


def reputation_tier_for(score: float) -> str:
    if score <= 0.0:
        return "unrated"
    if score >= 0.9:
        return "A"
    if score >= 0.75:
        return "B"
    if score >= 0.5:
        return "C"
    return "D"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 6)))


def _signal_present(*values: int | float | bool | str) -> bool:
    for value in values:
        if isinstance(value, bool):
            if value:
                return True
        elif isinstance(value, str):
            if value and value not in {"offline", "unknown"}:
                return True
        elif float(value) > 0.0:
            return True
    return False


def build_reputation_profile(
    *,
    node_status: str,
    heartbeat_fresh: bool,
    trust_summary: dict,
    operational_stats: dict,
    baseline_rating: dict,
    updated_at: str | None = None,
) -> dict:
    total_endpoints = int(trust_summary.get("total_endpoints", 0) or 0)
    certified_count = int(trust_summary.get("certified_count", 0) or 0)
    certified_with_issues_count = int(trust_summary.get("certified_with_issues_count", 0) or 0)
    validated_count = int(trust_summary.get("validated_count", 0) or 0)
    pending_count = int(trust_summary.get("pending_count", 0) or 0)
    attention_count = int(trust_summary.get("attention_count", 0) or 0)
    in_sync_count = int(trust_summary.get("in_sync_count", 0) or 0)
    drift_count = int(trust_summary.get("drift_count", 0) or 0)

    total_tasks = int(operational_stats.get("total_tasks", 0) or 0)
    successful_tasks = int(operational_stats.get("successful_tasks", 0) or 0)
    failed_tasks = int(operational_stats.get("failed_tasks", 0) or 0)

    has_signal = _signal_present(
        node_status,
        heartbeat_fresh,
        total_endpoints,
        certified_count,
        certified_with_issues_count,
        validated_count,
        pending_count,
        attention_count,
        in_sync_count,
        drift_count,
        total_tasks,
        successful_tasks,
        failed_tasks,
    )
    if not has_signal:
        return {
            "score": 0.0,
            "tier": "unrated",
            "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
            "components": {
                "freshness": 0.0,
                "publication_integrity": 0.0,
                "validation_posture": 0.0,
                "operational_reliability": 0.0,
            },
            "evidence": {
                "node_status": node_status,
                "published_endpoint_count": total_endpoints,
                "in_sync_count": in_sync_count,
                "drift_count": drift_count,
                "certified_count": certified_count,
                "certified_with_issues_count": certified_with_issues_count,
                "validated_count": validated_count,
                "pending_count": pending_count,
                "attention_count": attention_count,
                "total_tasks": total_tasks,
                "successful_tasks": successful_tasks,
                "failed_tasks": failed_tasks,
            },
        }

    freshness = 1.0 if node_status == "ready" and heartbeat_fresh else 0.55 if node_status == "stale" else 0.0

    if total_endpoints <= 0:
        publication_integrity = 0.0
    else:
        publication_integrity = _clamp((in_sync_count - drift_count) / max(total_endpoints, 1) + 0.5)

    if certified_count == 0 and certified_with_issues_count == 0 and validated_count == 0 and pending_count == 0 and attention_count == 0:
        validation_posture = 0.0
    else:
        validation_posture = _clamp(
            0.45
            + certified_count * 0.15
            + certified_with_issues_count * 0.08
            + validated_count * 0.1
            - attention_count * 0.15
            - pending_count * 0.05
        )

    if total_tasks <= 0:
        operational_reliability = 0.0
    else:
        operational_reliability = _clamp((successful_tasks - failed_tasks) / max(total_tasks, 1) + 0.5)

    score = _clamp(
        freshness * 0.25
        + publication_integrity * 0.30
        + validation_posture * 0.25
        + operational_reliability * 0.20
    )
    if score == 0.0:
        tier = "unrated"
    else:
        tier = reputation_tier_for(score)

    return {
        "score": score,
        "tier": tier,
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
        "components": {
            "freshness": freshness,
            "publication_integrity": publication_integrity,
            "validation_posture": validation_posture,
            "operational_reliability": operational_reliability,
        },
        "evidence": {
            "node_status": node_status,
            "published_endpoint_count": total_endpoints,
            "in_sync_count": in_sync_count,
            "drift_count": drift_count,
            "certified_count": certified_count,
            "certified_with_issues_count": certified_with_issues_count,
            "validated_count": validated_count,
            "pending_count": pending_count,
            "attention_count": attention_count,
            "total_tasks": total_tasks,
            "successful_tasks": successful_tasks,
            "failed_tasks": failed_tasks,
        },
    }
