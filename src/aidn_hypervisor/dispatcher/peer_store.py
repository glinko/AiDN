"""Persistent peer database for AiDN hypervisor networking.

Provides a JSON-backed peer store with health tracking,
quarantine management, and recommendation storage.

Used by DiscoveryManager (discovery.py) and RelayRouter (relay.py)
for peer state persistence.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, Field

# Import PeerRecord from discovery — avoid circular imports
# by using TYPE_CHECKING
from aidn_hypervisor.dispatcher.discovery import PeerRecord, TrustState

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Health state tracking
# ─────────────────────────────────────────────────────────────


class PeerHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNREACHABLE = "UNREACHABLE"
    SUSPECTED = "SUSPECTED"
    DEAD = "DEAD"


class PeerQuarantineReason(str, Enum):
    AUTH_FAILURE = "AUTH_FAILURE"
    PROTOCOL_VIOLATION = "PROTOCOL_VIOLATION"
    MALICIOUS_BEHAVIOR = "MALICIOUS_BEHAVIOR"
    STALE_RECORD = "STALE_RECORD"
    OPERATOR_REQUEST = "OPERATOR_REQUEST"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"


# ─────────────────────────────────────────────────────────────
# Health record
# ─────────────────────────────────────────────────────────────


@dataclass
class PeerHealthRecord:
    """Tracks connection health metrics for a peer."""

    hypervisor_id: str
    last_heartbeat: float = 0.0
    last_successful_connection: float = 0.0
    last_failed_connection: float = 0.0
    consecutive_failures: int = 0
    total_successes: int = 0
    total_failures: int = 0
    health_state: PeerHealthState = PeerHealthState.HEALTHY
    avg_response_time_ms: float = 0.0
    response_times: list[float] = field(default_factory=list)

    # Thresholds
    failure_threshold: int = 5
    recovery_threshold: int = 3
    heartbeat_timeout_seconds: float = 600.0  # 10 minutes

    @property
    def success_rate(self) -> float:
        total = self.total_successes + self.total_failures
        if total == 0:
            return 1.0  # Unknown = assume healthy
        return self.total_successes / total

    @property
    def is_alive(self) -> bool:
        """Check if the peer has been seen recently."""
        if self.last_heartbeat == 0:
            return True  # Never checked yet
        return (
            time.monotonic() - self.last_heartbeat
            < self.heartbeat_timeout_seconds
        )

    def record_success(self, response_time_ms: float = 0.0) -> None:
        """Record a successful connection."""
        self.total_successes += 1
        self.last_successful_connection = time.monotonic()
        self.consecutive_failures = 0

        if response_time_ms > 0:
            self.response_times.append(response_time_ms)
            # Keep last 100 measurements
            if len(self.response_times) > 100:
                self.response_times = self.response_times[-100:]
            self.avg_response_time_ms = (
                sum(self.response_times) / len(self.response_times)
            )

        self._update_health_state()

    def record_failure(self) -> None:
        """Record a failed connection."""
        self.total_failures += 1
        self.last_failed_connection = time.monotonic()
        self.consecutive_failures += 1
        self._update_health_state()

    def record_heartbeat(self) -> None:
        """Record a heartbeat from the peer."""
        self.last_heartbeat = time.monotonic()
        self.consecutive_failures = max(
            0, self.consecutive_failures - 1
        )
        self._update_health_state()

    def _update_health_state(self) -> None:
        """Update health state based on metrics."""
        if self.consecutive_failures >= self.failure_threshold:
            self.health_state = PeerHealthState.DEAD
        elif self.consecutive_failures >= self.failure_threshold // 2:
            self.health_state = PeerHealthState.UNREACHABLE
        elif self.consecutive_failures > 0:
            self.health_state = PeerHealthState.DEGRADED
        elif not self.is_alive:
            self.health_state = PeerHealthState.SUSPECTED
        else:
            self.health_state = PeerHealthState.HEALTHY

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypervisor_id": self.hypervisor_id,
            "last_heartbeat": self.last_heartbeat,
            "last_successful_connection": self.last_successful_connection,
            "last_failed_connection": self.last_failed_connection,
            "consecutive_failures": self.consecutive_failures,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "health_state": self.health_state.value,
            "avg_response_time_ms": self.avg_response_time_ms,
            "response_times": self.response_times,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PeerHealthRecord:
        health_state = PeerHealthState.HEALTHY
        if "health_state" in data:
            try:
                health_state = PeerHealthState(data["health_state"])
            except ValueError:
                pass
        return cls(
            hypervisor_id=data["hypervisor_id"],
            last_heartbeat=data.get("last_heartbeat", 0.0),
            last_successful_connection=data.get(
                "last_successful_connection", 0.0
            ),
            last_failed_connection=data.get("last_failed_connection", 0.0),
            consecutive_failures=data.get("consecutive_failures", 0),
            total_successes=data.get("total_successes", 0),
            total_failures=data.get("total_failures", 0),
            health_state=health_state,
            avg_response_time_ms=data.get("avg_response_time_ms", 0.0),
            response_times=data.get("response_times", []),
        )


# ─────────────────────────────────────────────────────────────
# Peer recommendation (RFC-0042 §31)
# ─────────────────────────────────────────────────────────────


@dataclass
class PeerRecommendation:
    """A peer recommendation from another hypervisor.

    RFC-0042 §31: peer exchange SHALL be source-attributed
    and non-authoritative.
    """

    recommended_peer_id: str
    recommended_by: str  # hypervisor_id of the recommender
    timestamp: float = field(default_factory=time.monotonic)
    confidence: float = Field(default=0.5)  # 0.0–1.0
    reason: str = ""
    verified: bool = False

    @property
    def is_stale(self) -> bool:
        """Recommendations older than 24 hours are stale."""
        return (time.monotonic() - self.timestamp) > 86400

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommended_peer_id": self.recommended_peer_id,
            "recommended_by": self.recommended_by,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "reason": self.reason,
            "verified": self.verified,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PeerRecommendation:
        return cls(
            recommended_peer_id=data["recommended_peer_id"],
            recommended_by=data["recommended_by"],
            timestamp=data.get("timestamp", time.monotonic()),
            confidence=data.get("confidence", 0.5),
            reason=data.get("reason", ""),
            verified=data.get("verified", False),
        )


# ─────────────────────────────────────────────────────────────
# Quarantine record
# ─────────────────────────────────────────────────────────────


@dataclass
class QuarantineRecord:
    """Tracks why and when a peer was quarantined."""

    hypervisor_id: str
    reason: str
    quarantined_at: float = field(default_factory=time.monotonic)
    quarantine_source: str = ""
    auto_release_after_seconds: float | None = None

    @property
    def can_release(self) -> bool:
        if self.auto_release_after_seconds is None:
            return False
        return (
            time.monotonic() - self.quarantined_at
            > self.auto_release_after_seconds
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypervisor_id": self.hypervisor_id,
            "reason": self.reason,
            "quarantined_at": self.quarantined_at,
            "quarantine_source": self.quarantine_source,
            "auto_release_after_seconds": self.auto_release_after_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuarantineRecord:
        return cls(
            hypervisor_id=data["hypervisor_id"],
            reason=data["reason"],
            quarantined_at=data.get("quarantined_at", time.monotonic()),
            quarantine_source=data.get("quarantine_source", ""),
            auto_release_after_seconds=data.get(
                "auto_release_after_seconds"
            ),
        )


# ─────────────────────────────────────────────────────────────
# Peer store
# ─────────────────────────────────────────────────────────────


class PeerStore:
    """Persistent peer database with health tracking.

    Backed by JSON files for MVP; can be extended to SQLite.
    """

    def __init__(
        self,
        *,
        storage_path: str | Path | None = None,
    ) -> None:
        self._storage_path = (
            Path(storage_path) if storage_path else None
        )
        self._peers: dict[str, PeerRecord] = {}
        self._health: dict[str, PeerHealthRecord] = {}
        self._recommendations: dict[str, list[PeerRecommendation]] = {}
        self._quarantined: dict[str, QuarantineRecord] = {}
        self._load()

    # ── persistence ─────────────────────────────────────────

    def _load(self) -> None:
        """Load state from disk."""
        if self._storage_path is None:
            return
        try:
            peers_file = self._storage_path / "peers.json"
            if peers_file.exists():
                data = json.loads(peers_file.read_text())
                for peer_data in data.get("peers", []):
                    try:
                        record = PeerRecord(**peer_data)
                        self._peers[record.hypervisor_id] = record
                    except Exception as exc:
                        log.warning(
                            "Failed to load peer %s: %s",
                            peer_data.get("hypervisor_id", "?"),
                            exc,
                        )

            health_file = self._storage_path / "health.json"
            if health_file.exists():
                data = json.loads(health_file.read_text())
                for h_data in data.get("health_records", []):
                    try:
                        hr = PeerHealthRecord.from_dict(h_data)
                        self._health[hr.hypervisor_id] = hr
                    except Exception:
                        pass

            rec_file = self._storage_path / "recommendations.json"
            if rec_file.exists():
                data = json.loads(rec_file.read_text())
                for peer_id, recs in data.get(
                    "recommendations", {}
                ).items():
                    self._recommendations[peer_id] = [
                        PeerRecommendation.from_dict(r)
                        for r in recs
                    ]

            q_file = self._storage_path / "quarantine.json"
            if q_file.exists():
                data = json.loads(q_file.read_text())
                for q_data in data.get("quarantine", []):
                    try:
                        qr = QuarantineRecord.from_dict(q_data)
                        self._quarantined[qr.hypervisor_id] = qr
                    except Exception:
                        pass
        except Exception as exc:
            log.error("Failed to load peer store: %s", exc)

    def save(self) -> None:
        """Persist state to disk."""
        if self._storage_path is None:
            return
        try:
            self._storage_path.mkdir(parents=True, exist_ok=True)

            (self._storage_path / "peers.json").write_text(
                json.dumps(
                    {
                        "peers": [
                            p.to_dict() for p in self._peers.values()
                        ]
                    },
                    indent=2,
                )
            )

            (self._storage_path / "health.json").write_text(
                json.dumps(
                    {
                        "health_records": [
                            h.to_dict() for h in self._health.values()
                        ]
                    },
                    indent=2,
                )
            )

            (self._storage_path / "recommendations.json").write_text(
                json.dumps(
                    {
                        "recommendations": {
                            pid: [r.to_dict() for r in recs]
                            for pid, recs in self._recommendations.items()
                        }
                    },
                    indent=2,
                )
            )

            (self._storage_path / "quarantine.json").write_text(
                json.dumps(
                    {
                        "quarantine": [
                            q.to_dict()
                            for q in self._quarantined.values()
                        ]
                    },
                    indent=2,
                )
            )
        except Exception as exc:
            log.error("Failed to save peer store: %s", exc)

    # ── peer CRUD ───────────────────────────────────────────

    def put(self, peer: PeerRecord) -> None:
        """Add or update a peer record."""
        self._peers[peer.hypervisor_id] = peer
        # Ensure health record exists
        if peer.hypervisor_id not in self._health:
            self._health[peer.hypervisor_id] = PeerHealthRecord(
                hypervisor_id=peer.hypervisor_id
            )

    def get(self, hypervisor_id: str) -> PeerRecord | None:
        """Get a peer by hypervisor_id."""
        return self._peers.get(hypervisor_id)

    def remove(self, hypervisor_id: str) -> bool:
        """Remove a peer."""
        if self._peers.pop(hypervisor_id, None) is None:
            return False
        self._health.pop(hypervisor_id, None)
        self._recommendations.pop(hypervisor_id, None)
        return True

    def has(self, hypervisor_id: str) -> bool:
        return hypervisor_id in self._peers

    def all_peers(self) -> list[PeerRecord]:
        return list(self._peers.values())

    def count(self) -> int:
        return len(self._peers)

    # ── health tracking ─────────────────────────────────────

    def get_health(self, hypervisor_id: str) -> PeerHealthRecord | None:
        return self._health.get(hypervisor_id)

    def record_connection_success(
        self,
        hypervisor_id: str,
        response_time_ms: float = 0.0,
    ) -> None:
        health = self._health.get(hypervisor_id)
        if health:
            health.record_success(response_time_ms)

    def record_connection_failure(self, hypervisor_id: str) -> None:
        health = self._health.get(hypervisor_id)
        if health:
            health.record_failure()

    def record_heartbeat(self, hypervisor_id: str) -> None:
        health = self._health.get(hypervisor_id)
        if health:
            health.record_heartbeat()

    def get_healthy_peers(self) -> list[PeerRecord]:
        """Return peers with HEALTHY or DEGRADED health state."""
        return [
            p
            for p in self._peers.values()
            if self._health.get(p.hypervisor_id)
            and self._health[p.hypervisor_id].health_state
            in (
                PeerHealthState.HEALTHY,
                PeerHealthState.DEGRADED,
            )
        ]

    # ── recommendations (RFC-0042 §31) ──────────────────────

    def add_recommendation(
        self,
        recommendation: PeerRecommendation,
    ) -> None:
        """Store a peer recommendation."""
        peer_id = recommendation.recommended_peer_id
        if peer_id not in self._recommendations:
            self._recommendations[peer_id] = []
        self._recommendations[peer_id].append(recommendation)

    def get_recommendations(
        self,
        hypervisor_id: str,
    ) -> list[PeerRecommendation]:
        """Get all recommendations for a peer."""
        return list(self._recommendations.get(hypervisor_id, []))

    def get_stale_recommendations(self) -> list[str]:
        """Return peer IDs with only stale recommendations."""
        stale: list[str] = []
        for pid, recs in self._recommendations.items():
            if all(r.is_stale for r in recs):
                stale.append(pid)
        return stale

    def cleanup_stale_recommendations(self) -> int:
        """Remove stale recommendations. Returns count removed."""
        removed = 0
        for pid in list(self._recommendations.keys()):
            before = len(self._recommendations[pid])
            self._recommendations[pid] = [
                r for r in self._recommendations[pid] if not r.is_stale
            ]
            removed += before - len(self._recommendations[pid])
        return removed

    # ── quarantine management ───────────────────────────────

    def quarantine(
        self,
        hypervisor_id: str,
        reason: str,
        *,
        auto_release_after: float | None = None,
        source: str = "",
    ) -> None:
        """Quarantine a peer."""
        record = QuarantineRecord(
            hypervisor_id=hypervisor_id,
            reason=reason,
            quarantine_source=source,
            auto_release_after_seconds=auto_release_after,
        )
        self._quarantined[hypervisor_id] = record
        # Update peer trust state
        peer = self._peers.get(hypervisor_id)
        if peer:
            peer.trust_state = TrustState.QUARANTINED

    def is_quarantined(self, hypervisor_id: str) -> bool:
        return hypervisor_id in self._quarantined

    def get_quarantine_record(
        self,
        hypervisor_id: str,
    ) -> QuarantineRecord | None:
        return self._quarantined.get(hypervisor_id)

    def release_quarantine(self, hypervisor_id: str) -> bool:
        """Release a peer from quarantine."""
        if self._quarantined.pop(hypervisor_id, None) is None:
            return False
        peer = self._peers.get(hypervisor_id)
        if peer:
            peer.trust_state = TrustState.UNVERIFIED
        return True

    def check_auto_releases(self) -> list[str]:
        """Check and auto-release expired quarantines.

        Returns list of released hypervisor_ids.
        """
        released: list[str] = []
        for hid, qr in list(self._quarantined.items()):
            if qr.can_release:
                self.release_quarantine(hid)
                released.append(hid)
        return released

    def get_quarantined_peers(self) -> list[str]:
        return list(self._quarantined.keys())

    # ── iteration ───────────────────────────────────────────

    def __iter__(self) -> Iterator[PeerRecord]:
        return iter(self._peers.values())

    def __len__(self) -> int:
        return len(self._peers)

    def __contains__(self, hypervisor_id: str) -> bool:
        return hypervisor_id in self._peers
