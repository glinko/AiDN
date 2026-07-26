"""Tests for StagingStateStore, StateRestorer — RFC-0062 §47-§48.

Staging state never overwrites active state directly.
"""

import json
import pytest

from aidn_hypervisor.snapshot.staging import (
    StagingStateStore,
    StateRestorer,
    RestorationResult,
)
from aidn_hypervisor.snapshot.encoding import (
    PortableSnapshotEncoder,
    STATE_NAMESPACES,
)


# ── Helpers ────────────────────────────────────────────────────────

def _make_sample_state():
    """Build a minimal valid state dict."""
    return {
        "wallets": {
            "w1": {"balance": 100, "locked": 10, "seq": 5},
            "w2": {"balance": 200, "locked": 0, "seq": 3},
        },
        "hypervisors": {"h1": {"status": "running", "wallet": "w1"}},
        "services": {"s1": {"type": "validator", "hypervisor": "h1"}},
        "endpoints": [],
        "sessions": [],
        "stakes": [{"wallet": "w1", "amount": 50}],
        "bonds": [],
        "certifications": [],
        "reputation": {"w1": 1.0, "w2": 0.8},
        "epochs": [],
        "protocol_parameters": {"max_block_size": 1_000_000, "version": 1},
        "evidence": [],
    }


def _encode_state(state):
    """Encode state using PortableSnapshotEncoder."""
    enc = PortableSnapshotEncoder()
    return enc.encode(state)


# ── StagingStateStore ─────────────────────────────────────────────

class TestStagingStateStoreInit:

    def test_empty_on_creation(self):
        store = StagingStateStore()
        assert store.is_empty()
        assert store.get_all_namespaces() == []

    def test_state_summary_empty(self):
        store = StagingStateStore()
        summary = store.get_state_summary()
        assert summary["namespace_count"] == 0
        assert summary["total_objects"] == 0
        assert summary["namespaces"] == {}


class TestStagingStateStoreLoadNamespace:

    def test_load_single_namespace(self):
        store = StagingStateStore()
        data = {"w1": {"balance": 100}}
        store.load_namespace("wallets", data)
        assert store.get_namespace("wallets") == data

    def test_load_multiple_namespaces(self):
        store = StagingStateStore()
        store.load_namespace("wallets", {"w1": {"balance": 100}})
        store.load_namespace("hypervisors", {"h1": {"status": "running"}})
        assert store.get_namespace("wallets") == {"w1": {"balance": 100}}
        assert store.get_namespace("hypervisors") == {"h1": {"status": "running"}}

    def test_get_missing_namespace_returns_none(self):
        store = StagingStateStore()
        assert store.get_namespace("nonexistent") is None

    def test_load_overwrites_existing(self):
        store = StagingStateStore()
        store.load_namespace("wallets", {"w1": {"balance": 100}})
        store.load_namespace("wallets", {"w1": {"balance": 200}})
        assert store.get_namespace("wallets") == {"w1": {"balance": 200}}

    def test_get_all_namespaces_after_loads(self):
        store = StagingStateStore()
        store.load_namespace("wallets", {"w1": {}})
        store.load_namespace("stakes", [])
        namespaces = store.get_all_namespaces()
        assert "wallets" in namespaces
        assert "stakes" in namespaces
        assert len(namespaces) == 2

    def test_is_empty_after_load(self):
        store = StagingStateStore()
        assert store.is_empty()
        store.load_namespace("wallets", {"w1": {}})
        assert not store.is_empty()


class TestStagingStateStoreHash:

    def test_calculate_state_hash_deterministic(self):
        store = StagingStateStore()
        store.load_namespace("wallets", {"w1": {"balance": 100}})
        hash1 = store.calculate_state_hash()
        hash2 = store.calculate_state_hash()
        assert hash1 == hash2

    def test_calculate_state_hash_empty_is_deterministic(self):
        store = StagingStateStore()
        hash1 = store.calculate_state_hash()
        store2 = StagingStateStore()
        hash2 = store2.calculate_state_hash()
        assert hash1 == hash2

    def test_calculate_state_hash_different_data_different_hash(self):
        store1 = StagingStateStore()
        store1.load_namespace("wallets", {"w1": {"balance": 100}})
        store2 = StagingStateStore()
        store2.load_namespace("wallets", {"w1": {"balance": 200}})
        assert store1.calculate_state_hash() != store2.calculate_state_hash()

    def test_calculate_state_hash_is_sha256_hex(self):
        store = StagingStateStore()
        store.load_namespace("wallets", {"w1": {}})
        h = store.calculate_state_hash()
        assert len(h) == 64
        int(h, 16)  # valid hex


class TestStagingStateStoreClear:

    def test_clear_removes_all_data(self):
        store = StagingStateStore()
        store.load_namespace("wallets", {"w1": {}})
        store.clear()
        assert store.is_empty()
        assert store.get_all_namespaces() == []
        assert store.get_namespace("wallets") is None


class TestStagingStateStoreSummary:

    def test_summary_populated(self):
        store = StagingStateStore()
        store.load_namespace("wallets", {"w1": {}, "w2": {}})
        store.load_namespace("stakes", [{"a": 1}, {"b": 2}])
        summary = store.get_state_summary()
        assert summary["namespace_count"] == 2
        assert summary["namespaces"]["wallets"] == 2
        assert summary["namespaces"]["stakes"] == 2
        assert summary["total_objects"] == 4


# ── StateRestorer ─────────────────────────────────────────────────

class TestStateRestorerFullRestore:

    def test_restore_from_valid_encoded_data(self):
        state = _make_sample_state()
        encoded = _encode_state(state)
        store = StagingStateStore()
        restorer = StateRestorer(store)
        result = restorer.restore(encoded)
        assert result.success
        assert result.error is None

    def test_restore_loads_all_namespaces(self):
        state = _make_sample_state()
        encoded = _encode_state(state)
        store = StagingStateStore()
        restorer = StateRestorer(store)
        result = restorer.restore(encoded)
        for ns in STATE_NAMESPACES:
            assert ns in result.namespaces_loaded

    def test_restore_calculates_correct_hash(self):
        state = _make_sample_state()
        encoded = _encode_state(state)
        store = StagingStateStore()
        restorer = StateRestorer(store)
        result = restorer.restore(encoded)
        assert result.application_state_hash == store.calculate_state_hash()

    def test_restore_counts_total_objects(self):
        state = _make_sample_state()
        encoded = _encode_state(state)
        store = StagingStateStore()
        restorer = StateRestorer(store)
        result = restorer.restore(encoded)
        assert result.total_objects > 0

    def test_restore_staging_store_populated(self):
        state = _make_sample_state()
        encoded = _encode_state(state)
        store = StagingStateStore()
        restorer = StateRestorer(store)
        result = restorer.restore(encoded)
        assert not store.is_empty()
        assert store.get_namespace("wallets") is not None

    def test_restore_clears_existing_staging_first(self):
        store = StagingStateStore()
        store.load_namespace("wallets", {"old": {}})
        state = _make_sample_state()
        encoded = _encode_state(state)
        restorer = StateRestorer(store)
        result = restorer.restore(encoded)
        # old wallet data should be replaced
        assert store.get_namespace("wallets") != {"old": {}}

    def test_restore_result_fields_populated(self):
        state = _make_sample_state()
        encoded = _encode_state(state)
        store = StagingStateStore()
        restorer = StateRestorer(store)
        result = restorer.restore(encoded)
        assert isinstance(result.success, bool)
        assert isinstance(result.namespaces_loaded, list)
        assert isinstance(result.total_objects, int)
        assert isinstance(result.application_state_hash, str)
        assert result.error is None


class TestStateRestorerInvalidData:

    def test_restore_invalid_json_raises(self):
        store = StagingStateStore()
        restorer = StateRestorer(store)
        with pytest.raises(ValueError):
            restorer.restore(b"not valid json at all")

    def test_restore_empty_bytes_raises(self):
        store = StagingStateStore()
        restorer = StateRestorer(store)
        with pytest.raises(ValueError):
            restorer.restore(b"")

    def test_restore_garbage_bytes_raises(self):
        store = StagingStateStore()
        restorer = StateRestorer(store)
        with pytest.raises(ValueError):
            restorer.restore(b"\x00\x01\x02\xff")


class TestStateRestorerPartialRestore:

    def test_partial_restore_single_namespace(self):
        store = StagingStateStore()
        restorer = StateRestorer(store)
        restorer.restore_partial("wallets", {"w1": {"balance": 100}})
        assert store.get_namespace("wallets") == {"w1": {"balance": 100}}

    def test_partial_restore_does_not_affect_other_namespaces(self):
        store = StagingStateStore()
        store.load_namespace("hypervisors", {"h1": {}})
        restorer = StateRestorer(store)
        restorer.restore_partial("wallets", {"w1": {}})
        assert store.get_namespace("hypervisors") == {"h1": {}}
        assert store.get_namespace("wallets") == {"w1": {}}


# ── RestorationResult model ───────────────────────────────────────

class TestRestorationResult:

    def test_successful_result(self):
        r = RestorationResult(
            success=True,
            namespaces_loaded=["wallets"],
            total_objects=5,
            application_state_hash="abc123",
            error=None,
        )
        assert r.success
        assert r.error is None

    def test_failed_result(self):
        r = RestorationResult(
            success=False,
            namespaces_loaded=[],
            total_objects=0,
            application_state_hash="",
            error="bad data",
        )
        assert not r.success
        assert r.error == "bad data"
