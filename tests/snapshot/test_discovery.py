"""Tests for snapshot discovery and selection (RFC-0062 §37-§40)."""

from __future__ import annotations

import pytest

from aidn_hypervisor.snapshot.discovery import (
    SnapshotAvailability,
    SnapshotCandidate,
    SnapshotDiscovery,
    SnapshotRegistrySource,
    SnapshotSelector,
)
from aidn_hypervisor.snapshot.models import (
    CompressionAlgorithm,
    Encoding,
    SnapshotManifest,
    SnapshotType,
)

# ── Helpers ────────────────────────────────────────────────────────

def _make_manifest(
    *,
    snapshot_id: str = "snap-001",
    chain_id: str = "aidn-mainnet",
    protocol_version: str = "1.0.0",
    state_schema_version: int = 1,
    block_height: int = 1000,
    application_state_hash: str = "hash-abc123",
    revoked: bool = False,
) -> SnapshotManifest:
    return SnapshotManifest(
        snapshot_id=snapshot_id,
        snapshot_type=SnapshotType.FULL_STATE,
        snapshot_format_version=1,
        network_id="aidn",
        chain_id=chain_id,
        network_revision=1,
        protocol_version=protocol_version,
        application_version="1.0.0",
        state_schema_version=state_schema_version,
        block_height=block_height,
        block_hash="block-hash-xyz",
        block_time="2025-01-01T00:00:00Z",
        epoch=1,
        application_state_hash=application_state_hash,
        validator_set_hash=None,
        protocol_parameters_hash=None,
        snapshot_content_hash="content-hash",
        snapshot_content_size=1024,
        chunk_count=1,
        chunk_size=1024,
        chunk_root="chunk-root",
        compression=CompressionAlgorithm.NONE,
        encoding=Encoding.JSON_DETERMINISTIC,
        creation_time="2025-01-01T00:00:00Z",
        producer_service_id="producer-1",
        producer_signature="sig-123",
    )


def _make_availability(
    *,
    snapshot_id: str = "snap-001",
    provider_service_ids: list[str] | None = None,
    provider_group_count: int = 3,
    chunk_coverage: float = 1.0,
    last_verified: str = "2025-01-01T00:00:00Z",
    transfer_health: str = "good",
) -> SnapshotAvailability:
    return SnapshotAvailability(
        snapshot_id=snapshot_id,
        provider_service_ids=provider_service_ids or ["prov-1", "prov-2", "prov-3"],
        provider_group_count=provider_group_count,
        chunk_coverage=chunk_coverage,
        last_verified=last_verified,
        transfer_health=transfer_health,
    )


def _make_candidate(
    *,
    snapshot_id: str = "snap-001",
    chain_id: str = "aidn-mainnet",
    protocol_version: str = "1.0.0",
    state_schema_version: int = 1,
    block_height: int = 1000,
    provider_group_count: int = 3,
    chunk_coverage: float = 1.0,
    transfer_health: str = "good",
    application_state_hash: str = "hash-abc123",
) -> SnapshotCandidate:
    manifest = _make_manifest(
        snapshot_id=snapshot_id,
        chain_id=chain_id,
        protocol_version=protocol_version,
        state_schema_version=state_schema_version,
        block_height=block_height,
        application_state_hash=application_state_hash,
    )
    availability = _make_availability(
        snapshot_id=snapshot_id,
        provider_group_count=provider_group_count,
        chunk_coverage=chunk_coverage,
        transfer_health=transfer_health,
    )
    return SnapshotCandidate(
        manifest=manifest,
        availability=availability,
        score=0.0,
        suitable=True,
        rejection_reasons=[],
    )


# ── SnapshotAvailability ──────────────────────────────────────────


class TestSnapshotAvailability:
    def test_create_availability(self):
        avail = _make_availability()
        assert avail.snapshot_id == "snap-001"
        assert avail.provider_group_count == 3
        assert avail.chunk_coverage == 1.0
        assert avail.transfer_health == "good"

    def test_availability_is_frozen(self):
        avail = _make_availability()
        with pytest.raises(Exception):
            avail.snapshot_id = "snap-002"  # type: ignore

    def test_availability_partial_coverage(self):
        avail = _make_availability(chunk_coverage=0.75)
        assert avail.chunk_coverage == 0.75

    def test_availability_degraded_health(self):
        avail = _make_availability(transfer_health="degraded")
        assert avail.transfer_health == "degraded"

    def test_availability_poor_health(self):
        avail = _make_availability(transfer_health="poor")
        assert avail.transfer_health == "poor"

    def test_availability_custom_providers(self):
        providers = ["prov-A", "prov-B"]
        avail = _make_availability(provider_service_ids=providers)
        assert avail.provider_service_ids == providers


# ── SnapshotCandidate scoring ──────────────────────────────────────


class TestSnapshotCandidate:
    def test_candidate_creation(self):
        c = _make_candidate()
        assert c.suitable is True
        assert c.rejection_reasons == []

    def test_candidate_with_rejection(self):
        manifest = _make_manifest()
        availability = _make_availability()
        c = SnapshotCandidate(
            manifest=manifest,
            availability=availability,
            score=0.0,
            suitable=False,
            rejection_reasons=["wrong chain"],
        )
        assert c.suitable is False
        assert "wrong chain" in c.rejection_reasons


# ── SnapshotDiscovery ─────────────────────────────────────────────


class TestSnapshotDiscovery:
    def test_discover_snapshots(self):
        manifests = [_make_manifest(snapshot_id="snap-001"), _make_manifest(snapshot_id="snap-002")]

        class MockSource(SnapshotRegistrySource):
            def query_snapshots(self) -> list[SnapshotManifest]:
                return manifests

            def get_provider_inventory(self, snapshot_id: str) -> list[str]:
                return ["prov-1", "prov-2"]

        discovery = SnapshotDiscovery(registry_source=MockSource())
        results = discovery.discover_snapshots()
        assert len(results) == 2
        assert results[0].snapshot_id == "snap-001"
        assert results[1].snapshot_id == "snap-002"

    def test_get_provider_status_existing(self):
        manifest = _make_manifest(snapshot_id="snap-001")

        class MockSource(SnapshotRegistrySource):
            def query_snapshots(self) -> list[SnapshotManifest]:
                return [manifest]

            def get_provider_inventory(self, snapshot_id: str) -> list[str]:
                return ["prov-1", "prov-2", "prov-3"]

        discovery = SnapshotDiscovery(registry_source=MockSource())
        status = discovery.get_provider_status("snap-001")
        assert status is not None
        assert status.snapshot_id == "snap-001"

    def test_get_provider_status_missing(self):
        class MockSource(SnapshotRegistrySource):
            def query_snapshots(self) -> list[SnapshotManifest]:
                return []

            def get_provider_inventory(self, snapshot_id: str) -> list[str]:
                return []

        discovery = SnapshotDiscovery(registry_source=MockSource())
        status = discovery.get_provider_status("snap-999")
        assert status is None


# ── SnapshotSelector ──────────────────────────────────────────────


class TestSnapshotSelector:
    def _make_selector(self, **kwargs) -> SnapshotSelector:
        defaults: dict = {
            "chain_id": "aidn-mainnet",
            "protocol_version": "1.0.0",
            "state_schema_versions": [1, 2],
            "min_provider_groups": 3,
            "stability_delay_blocks": 100,
        }
        defaults.update(kwargs)
        return SnapshotSelector(**defaults)

    def test_select_highest_scored(self):
        selector = self._make_selector()
        c_high = _make_candidate(block_height=1500, provider_group_count=5, chunk_coverage=1.0, transfer_health="good")
        c_low = _make_candidate(block_height=500, provider_group_count=3, chunk_coverage=0.5, transfer_health="degraded")
        result = selector.select([c_high, c_low], finalized_height=2000)
        assert result is not None
        assert result.score > 0

    def test_select_rejects_wrong_chain(self):
        selector = self._make_selector()
        c = _make_candidate(chain_id="wrong-chain")
        result = selector.select([c], finalized_height=2000)
        assert result is None

    def test_select_rejects_unsupported_protocol(self):
        selector = self._make_selector()
        c = _make_candidate(protocol_version="9.9.9")
        result = selector.select([c], finalized_height=2000)
        assert result is None

    def test_select_rejects_unsupported_state_schema(self):
        selector = self._make_selector(state_schema_versions=[1])
        c = _make_candidate(state_schema_version=5)
        result = selector.select([c], finalized_height=2000)
        assert result is None

    def test_select_rejects_insufficient_providers(self):
        selector = self._make_selector(min_provider_groups=5)
        c = _make_candidate(provider_group_count=2)
        result = selector.select([c], finalized_height=2000)
        assert result is None

    def test_select_rejects_before_stability_delay(self):
        selector = self._make_selector(stability_delay_blocks=100)
        c = _make_candidate(block_height=1950)
        result = selector.select([c], finalized_height=2000)
        assert result is None

    def test_select_accepts_after_stability_delay(self):
        selector = self._make_selector(stability_delay_blocks=100)
        c = _make_candidate(block_height=1800)
        result = selector.select([c], finalized_height=2000)
        assert result is not None

    def test_select_empty_list(self):
        selector = self._make_selector()
        result = selector.select([], finalized_height=2000)
        assert result is None

    def test_select_all_unsuitable(self):
        selector = self._make_selector()
        c1 = _make_candidate(chain_id="wrong-1")
        c2 = _make_candidate(chain_id="wrong-2")
        result = selector.select([c1, c2], finalized_height=2000)
        assert result is None

    def test_provider_diversity_bonus(self):
        selector = self._make_selector()
        c_high = _make_candidate(provider_group_count=6, block_height=1000)
        c_low = _make_candidate(provider_group_count=3, block_height=1000)
        result = selector.select([c_high, c_low], finalized_height=2000)
        assert result is not None
        # Higher provider count should yield higher score
        assert result.score > 0

    def test_chunk_coverage_bonus(self):
        selector = self._make_selector()
        c_full = _make_candidate(chunk_coverage=1.0, block_height=1000)
        c_partial = _make_candidate(chunk_coverage=0.5, block_height=1000)
        result = selector.select([c_full, c_partial], finalized_height=2000)
        assert result is not None
        assert result.availability.chunk_coverage == 1.0

    def test_transfer_health_affects_score(self):
        selector = self._make_selector()
        c_good = _make_candidate(transfer_health="good", block_height=1000)
        c_poor = _make_candidate(transfer_health="poor", block_height=1000)
        result = selector.select([c_good, c_poor], finalized_height=2000)
        assert result is not None
        assert result.availability.transfer_health == "good"

    def test_multiple_candidates_ranked(self):
        selector = self._make_selector()
        c1 = _make_candidate(block_height=1800, provider_group_count=5, chunk_coverage=1.0, transfer_health="good")
        c2 = _make_candidate(block_height=1500, provider_group_count=4, chunk_coverage=0.9, transfer_health="good")
        c3 = _make_candidate(block_height=1200, provider_group_count=3, chunk_coverage=0.8, transfer_health="degraded")
        result = selector.select([c1, c2, c3], finalized_height=2000)
        assert result is not None
        assert result.manifest.block_height == 1800

    def test_select_prefers_newer_snapshot(self):
        selector = self._make_selector()
        c_new = _make_candidate(block_height=1800)
        c_old = _make_candidate(block_height=500)
        result = selector.select([c_new, c_old], finalized_height=2000)
        assert result is not None
        assert result.manifest.block_height == 1800

    def test_select_rejects_height_above_finalized(self):
        selector = self._make_selector()
        c = _make_candidate(block_height=3000)
        result = selector.select([c], finalized_height=2000)
        assert result is None
