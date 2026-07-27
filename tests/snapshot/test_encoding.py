"""Tests for PortableSnapshotEncoder — RFC-0062 §14-§16.

Deterministic logical snapshot encoding with namespace ordering.
"""

import hashlib
import json

import pytest

from aidn_hypervisor.snapshot.encoding import (
    STATE_NAMESPACES,
    PortableSnapshotEncoder,
)

# ── Helpers ────────────────────────────────────────────────────────

def _make_state(**kwargs):
    """Build a minimal state dict with only the requested namespace keys."""
    return {k: v for k, v in kwargs.items() if v is not None}


def _make_full_state():
    """Build a state dict covering all namespaces."""
    return {
        "wallets": {"w1": {"balance": 100}, "w2": {"balance": 200}},
        "hypervisors": {"h1": {"status": "running"}},
        "services": {"s1": {"type": "validator"}},
        "endpoints": [],
        "sessions": [],
        "stakes": [{"wallet": "w1", "amount": 50}],
        "bonds": [],
        "certifications": [],
        "reputation": {"w1": 1.0},
        "epochs": [],
        "protocol_parameters": {"max_block_size": 1000000},
        "evidence": [],
    }


# ── STATE_NAMESPACES ──────────────────────────────────────────────

class TestStateNamespaces:

    def test_all_namespaces_present(self):
        """All 12 namespaces are listed."""
        assert len(STATE_NAMESPACES) == 12

    def test_wallets_first(self):
        """wallets is the first namespace."""
        assert STATE_NAMESPACES[0] == "wallets"

    def test_evidence_last(self):
        """evidence is the last namespace."""
        assert STATE_NAMESPACES[-1] == "evidence"

    def test_no_duplicates(self):
        """No duplicate namespace names."""
        assert len(STATE_NAMESPACES) == len(set(STATE_NAMESPACES))

    def test_known_namespaces(self):
        """Expected namespaces are present."""
        expected = {
            "wallets", "hypervisors", "services", "endpoints",
            "sessions", "stakes", "bonds", "certifications",
            "reputation", "epochs", "protocol_parameters", "evidence",
        }
        assert set(STATE_NAMESPACES) == expected


# ── Encode / Decode round-trip ────────────────────────────────────

class TestEncodeDecodeRoundTrip:

    def test_empty_state(self):
        """Encoding an empty state round-trips."""
        enc = PortableSnapshotEncoder()
        data = enc.encode({})
        result = enc.decode(data)
        # All namespaces present, all empty
        for ns in STATE_NAMESPACES:
            assert ns in result

    def test_full_state_round_trip(self):
        """Full state round-trips identically."""
        enc = PortableSnapshotEncoder()
        state = _make_full_state()
        data = enc.encode(state)
        result = enc.decode(data)
        assert result == state

    def test_partial_state_round_trip(self):
        """Partial state (some namespaces missing) round-trips."""
        enc = PortableSnapshotEncoder()
        state = _make_state(wallets={"w1": {"balance": 1}})
        data = enc.encode(state)
        result = enc.decode(data)
        assert result["wallets"] == {"w1": {"balance": 1}}

    def test_nested_dict_round_trip(self):
        """Deeply nested dicts round-trip correctly."""
        enc = PortableSnapshotEncoder()
        state = {
            "wallets": {
                "w1": {
                    "nested": {"deep": {"value": [1, 2, 3]}},
                },
            },
        }
        data = enc.encode(state)
        result = enc.decode(data)
        assert result["wallets"]["w1"]["nested"]["deep"]["value"] == [1, 2, 3]


# ── Determinism ────────────────────────────────────────────────────

class TestDeterminism:

    def test_same_input_same_bytes(self):
        """Same input always produces identical bytes."""
        enc = PortableSnapshotEncoder()
        state = _make_full_state()
        a = enc.encode(state)
        b = enc.encode(state)
        assert a == b

    def test_different_encoder_same_bytes(self):
        """Different encoder instances produce identical bytes."""
        enc1 = PortableSnapshotEncoder()
        enc2 = PortableSnapshotEncoder(chunk_size=4_000_000)
        state = _make_full_state()
        assert enc1.encode(state) == enc2.encode(state)

    def test_dict_key_order_irrelevant(self):
        """Input dict key order doesn't affect output."""
        enc = PortableSnapshotEncoder()
        state1 = _make_state(wallets={"a": 1, "b": 2, "c": 3})
        state2 = _make_state(wallets={"c": 3, "a": 1, "b": 2})
        assert enc.encode(state1) == enc.encode(state2)


# ── Namespace ordering ────────────────────────────────────────────

class TestNamespaceOrdering:

    def test_namespaces_ordered_in_output(self):
        """Encoded JSON keys follow STATE_NAMESPACES order."""
        enc = PortableSnapshotEncoder()
        state = _make_full_state()
        data = enc.encode(state)
        parsed = json.loads(data)
        keys = list(parsed.keys())
        # Each namespace should appear at or before its position in STATE_NAMESPACES
        positions = {ns: i for i, ns in enumerate(STATE_NAMESPACES)}
        last_pos = -1
        for key in keys:
            assert positions[key] > last_pos
            last_pos = positions[key]

    def test_missing_namespaces_become_empty(self):
        """Namespaces not in input become empty dicts/lists."""
        enc = PortableSnapshotEncoder()
        state = _make_state(wallets={"w1": {}})
        data = enc.encode(state)
        result = enc.decode(data)
        assert "hypervisors" in result
        assert "evidence" in result


# ── Unknown namespace validation ──────────────────────────────────

class TestUnknownNamespace:

    def test_unknown_namespace_raises(self):
        """State with an unknown namespace key raises ValueError."""
        enc = PortableSnapshotEncoder()
        state = {"unknown_ns": {"data": 1}}
        with pytest.raises(ValueError, match="unknown"):
            enc.encode(state)

    def test_unknown_namespace_case_sensitive(self):
        """Namespace names are case-sensitive."""
        enc = PortableSnapshotEncoder()
        state = {"Wallets": {"w1": {}}}
        with pytest.raises(ValueError, match="(?i)unknown"):
            enc.encode(state)

    def test_multiple_unknown_namespaces(self):
        """Multiple unknown namespaces still raise."""
        enc = PortableSnapshotEncoder()
        state = {"foo": 1, "bar": 2}
        with pytest.raises(ValueError):
            enc.encode(state)


# ── Content hash ──────────────────────────────────────────────────

class TestContentHash:

    def test_hash_is_sha256_hex(self):
        """Content hash is a 64-char hex string."""
        enc = PortableSnapshotEncoder()
        state = _make_full_state()
        h = enc.compute_content_hash(state)
        assert len(h) == 64
        int(h, 16)  # valid hex

    def test_hash_deterministic(self):
        """Same state always produces the same hash."""
        enc = PortableSnapshotEncoder()
        state = _make_full_state()
        assert enc.compute_content_hash(state) == enc.compute_content_hash(state)

    def test_hash_matches_manual_sha256(self):
        """Hash is SHA-256 of encoded bytes."""
        enc = PortableSnapshotEncoder()
        state = _make_full_state()
        encoded = enc.encode(state)
        expected = hashlib.sha256(encoded).hexdigest()
        assert enc.compute_content_hash(state) == expected

    def test_different_states_different_hashes(self):
        """Different states produce different hashes."""
        enc = PortableSnapshotEncoder()
        s1 = _make_state(wallets={"w1": {"balance": 1}})
        s2 = _make_state(wallets={"w1": {"balance": 2}})
        assert enc.compute_content_hash(s1) != enc.compute_content_hash(s2)

    def test_empty_state_hash(self):
        """Empty state still produces a valid hash."""
        enc = PortableSnapshotEncoder()
        h = enc.compute_content_hash({})
        assert len(h) == 64


# ── Content size ──────────────────────────────────────────────────

class TestContentSize:

    def test_size_matches_encoded_length(self):
        """Content size equals len(encoded bytes)."""
        enc = PortableSnapshotEncoder()
        state = _make_full_state()
        assert enc.compute_content_size(state) == len(enc.encode(state))

    def test_empty_state_has_size(self):
        """Empty state has non-zero size (namespace wrappers)."""
        enc = PortableSnapshotEncoder()
        assert enc.compute_content_size({}) > 0

    def test_larger_state_larger_size(self):
        """Larger state produces larger encoded size."""
        enc = PortableSnapshotEncoder()
        s1 = _make_state(wallets={"w1": {}})
        s2 = _make_full_state()
        assert enc.compute_content_size(s2) > enc.compute_content_size(s1)


# ── Large state ───────────────────────────────────────────────────

class TestLargeState:

    def test_many_wallets(self):
        """Encoding a state with many entries works."""
        enc = PortableSnapshotEncoder()
        wallets = {f"w{i}": {"balance": i} for i in range(1000)}
        state = _make_state(wallets=wallets)
        data = enc.encode(state)
        result = enc.decode(data)
        assert len(result["wallets"]) == 1000

    def test_large_state_deterministic(self):
        """Large state still deterministic."""
        enc = PortableSnapshotEncoder()
        wallets = {f"w{i}": {"balance": i} for i in range(500)}
        stakes = [{"wallet": f"w{i}", "amount": i * 10} for i in range(200)]
        state = _make_state(wallets=wallets, stakes=stakes)
        a = enc.encode(state)
        b = enc.encode(state)
        assert a == b

    def test_large_state_round_trip(self):
        """Large state round-trips correctly."""
        enc = PortableSnapshotEncoder()
        services = {f"s{i}": {"type": f"type{i % 5}"} for i in range(300)}
        state = _make_state(services=services)
        data = enc.encode(state)
        result = enc.decode(data)
        assert len(result["services"]) == 300


# ── Nested dict ordering ──────────────────────────────────────────

class TestNestedDictOrdering:

    def test_nested_keys_sorted(self):
        """Nested dict keys are sorted in canonical JSON."""
        enc = PortableSnapshotEncoder()
        state = _make_state(wallets={"w1": {"z_field": 1, "a_field": 2}})
        data = enc.encode(state)
        parsed = json.loads(data)
        wallet_keys = list(parsed["wallets"]["w1"].keys())
        assert wallet_keys == sorted(wallet_keys)

    def test_deeply_nested_sorted(self):
        """Deeply nested dicts have sorted keys."""
        enc = PortableSnapshotEncoder()
        state = _make_state(
            protocol_parameters={
                "z_max": 100,
                "a_min": 1,
                "m_mid": 50,
            }
        )
        data = enc.encode(state)
        parsed = json.loads(data)
        keys = list(parsed["protocol_parameters"].keys())
        assert keys == sorted(keys)
