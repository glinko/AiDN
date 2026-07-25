"""Tests for registry/protocol — Protocol Negotiation + Registry Status (RFC-0061 §§18-19)."""

from __future__ import annotations

import pytest

from aidn_hypervisor.registry import (
    NegotiationResult,
    ProtocolNegotiator,
    ProtocolVersion,
    RegistryStatus,
)


# ---------------------------------------------------------------------------
# ProtocolVersion
# ---------------------------------------------------------------------------

def test_protocol_version_str():
    v = ProtocolVersion(major=1, minor=2, patch=3)
    assert str(v) == "1.2.3"


def test_protocol_version_frozen():
    v = ProtocolVersion(major=1, minor=0, patch=0)
    with pytest.raises(Exception):
        v.major = 2  # type: ignore


# ---------------------------------------------------------------------------
# RegistryStatus
# ---------------------------------------------------------------------------

def test_registry_status_creation():
    status = RegistryStatus(peer_id="peer-1")
    assert status.peer_id == "peer-1"
    assert status.protocol_version == "1.0.0"
    assert status.registry_class == "full"
    assert status.finalized_height == 0
    assert status.current_epoch == 0
    assert status.profile_version == 1
    assert status.object_count == 0
    assert status.earliest_epoch == 0
    assert status.latest_epoch == 0
    assert status.supported_compression == []
    assert status.supported_formats == []
    assert status.max_object_size == 10 * 1024 * 1024
    assert status.max_chunk_size == 1024 * 1024
    assert status.inventory_summary == {}


def test_registry_status_fields():
    status = RegistryStatus(
        peer_id="peer-1",
        protocol_version="2.0.0",
        registry_class="archive",
        finalized_height=1000,
        current_epoch=5,
        profile_version=2,
        object_count=500,
        earliest_epoch=1,
        latest_epoch=5,
        supported_compression=["gzip", "lz4"],
        supported_formats=["json", "protobuf"],
        max_object_size=20 * 1024 * 1024,
        max_chunk_size=2 * 1024 * 1024,
        inventory_summary={"total": 500},
    )
    assert status.protocol_version == "2.0.0"
    assert status.registry_class == "archive"
    assert status.finalized_height == 1000
    assert status.current_epoch == 5
    assert status.profile_version == 2
    assert status.object_count == 500
    assert status.earliest_epoch == 1
    assert status.latest_epoch == 5
    assert status.supported_compression == ["gzip", "lz4"]
    assert status.supported_formats == ["json", "protobuf"]
    assert status.max_object_size == 20 * 1024 * 1024
    assert status.max_chunk_size == 2 * 1024 * 1024
    assert status.inventory_summary == {"total": 500}


# ---------------------------------------------------------------------------
# ProtocolNegotiator — defaults
# ---------------------------------------------------------------------------

def test_negotiator_defaults():
    neg = ProtocolNegotiator()
    assert str(neg.local_version) == "1.0.0"
    assert neg.local_status is None
    assert neg.supported_compression == ["gzip", "none"]
    assert neg.supported_formats == ["json", "protobuf"]


# ---------------------------------------------------------------------------
# ProtocolNegotiator — negotiate compatible
# ---------------------------------------------------------------------------

def test_negotiate_compatible():
    neg = ProtocolNegotiator()
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="1.1.0",
        supported_compression=["gzip"],
        supported_formats=["json"],
    )
    result = neg.negotiate(peer_id="remote-1", remote_status=remote)
    assert result.compatible is True
    assert result.peer_id == "remote-1"
    assert "gzip" in result.agreed_compression
    assert "json" in result.agreed_formats


# ---------------------------------------------------------------------------
# ProtocolNegotiator — negotiate incompatible major
# ---------------------------------------------------------------------------

def test_negotiate_incompatible_major():
    neg = ProtocolNegotiator()
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="2.0.0",
    )
    result = neg.negotiate(peer_id="remote-1", remote_status=remote)
    assert result.compatible is False


def test_major_version_mismatch():
    neg = ProtocolNegotiator(
        local_version=ProtocolVersion(major=1, minor=0, patch=0),
    )
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="3.0.0",
    )
    result = neg.negotiate(peer_id="remote-1", remote_status=remote)
    assert result.compatible is False


# ---------------------------------------------------------------------------
# ProtocolNegotiator — minor version compat
# ---------------------------------------------------------------------------

def test_minor_version_compat():
    neg = ProtocolNegotiator(
        local_version=ProtocolVersion(major=1, minor=0, patch=0),
    )
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="1.5.3",
    )
    result = neg.negotiate(peer_id="remote-1", remote_status=remote)
    assert result.compatible is True


# ---------------------------------------------------------------------------
# ProtocolNegotiator — compression negotiation
# ---------------------------------------------------------------------------

def test_negotiate_compression():
    neg = ProtocolNegotiator(
        supported_compression=["gzip", "lz4", "none"],
    )
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="1.0.0",
        supported_compression=["lz4", "zstd"],
    )
    result = neg.negotiate(peer_id="remote-1", remote_status=remote)
    assert "lz4" in result.agreed_compression
    assert "gzip" not in result.agreed_compression
    assert "zstd" not in result.agreed_compression


def test_negotiate_no_common_compression():
    neg = ProtocolNegotiator(
        supported_compression=["zstd"],
    )
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="1.0.0",
        supported_compression=["lz4"],
    )
    result = neg.negotiate(peer_id="remote-1", remote_status=remote)
    assert result.agreed_compression == ["none"]


# ---------------------------------------------------------------------------
# ProtocolNegotiator — format negotiation
# ---------------------------------------------------------------------------

def test_negotiate_formats():
    neg = ProtocolNegotiator(
        supported_formats=["json", "protobuf", "msgpack"],
    )
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="1.0.0",
        supported_formats=["json", "cbor"],
    )
    result = neg.negotiate(peer_id="remote-1", remote_status=remote)
    assert "json" in result.agreed_formats
    assert "protobuf" not in result.agreed_formats
    assert "cbor" not in result.agreed_formats


def test_negotiate_no_common_formats():
    neg = ProtocolNegotiator(
        supported_formats=["msgpack"],
    )
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="1.0.0",
        supported_formats=["cbor"],
    )
    result = neg.negotiate(peer_id="remote-1", remote_status=remote)
    assert result.agreed_formats == ["json"]


# ---------------------------------------------------------------------------
# ProtocolNegotiator — limits negotiation
# ---------------------------------------------------------------------------

def test_negotiate_limits():
    local_status = RegistryStatus(
        peer_id="local",
        max_object_size=20 * 1024 * 1024,
        max_chunk_size=2 * 1024 * 1024,
    )
    neg = ProtocolNegotiator(local_status=local_status)
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="1.0.0",
        max_object_size=10 * 1024 * 1024,
        max_chunk_size=512 * 1024,
    )
    result = neg.negotiate(peer_id="remote-1", remote_status=remote)
    assert result.max_object_size == 10 * 1024 * 1024  # min of both
    assert result.max_chunk_size == 512 * 1024


def test_negotiate_max_sizes():
    local_status = RegistryStatus(
        peer_id="local",
        max_object_size=5 * 1024 * 1024,
        max_chunk_size=256 * 1024,
    )
    neg = ProtocolNegotiator(local_status=local_status)
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="1.0.0",
        max_object_size=100 * 1024 * 1024,
        max_chunk_size=10 * 1024 * 1024,
    )
    result = neg.negotiate(peer_id="remote-1", remote_status=remote)
    assert result.max_object_size == 5 * 1024 * 1024
    assert result.max_chunk_size == 256 * 1024


# ---------------------------------------------------------------------------
# ProtocolNegotiator — with/without local status
# ---------------------------------------------------------------------------

def test_negotiate_with_local_status():
    local_status = RegistryStatus(
        peer_id="local",
        max_object_size=5 * 1024 * 1024,
        max_chunk_size=256 * 1024,
    )
    neg = ProtocolNegotiator(local_status=local_status)
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="1.0.0",
        max_object_size=10 * 1024 * 1024,
        max_chunk_size=1024 * 1024,
    )
    result = neg.negotiate(peer_id="remote-1", remote_status=remote)
    assert result.max_object_size == 5 * 1024 * 1024
    assert result.max_chunk_size == 256 * 1024


def test_negotiate_without_local_status():
    neg = ProtocolNegotiator()
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="1.0.0",
        max_object_size=5 * 1024 * 1024,
        max_chunk_size=256 * 1024,
    )
    result = neg.negotiate(peer_id="remote-1", remote_status=remote)
    # Defaults: local 10MB / 1MB vs remote 5MB / 256KB → min wins
    assert result.max_object_size == 5 * 1024 * 1024
    assert result.max_chunk_size == 256 * 1024


# ---------------------------------------------------------------------------
# ProtocolNegotiator — get_negotiated / is_compatible
# ---------------------------------------------------------------------------

def test_get_negotiated():
    neg = ProtocolNegotiator()
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="1.0.0",
    )
    neg.negotiate(peer_id="remote-1", remote_status=remote)
    got = neg.get_negotiated("remote-1")
    assert got is not None
    assert got.peer_id == "remote-1"
    assert neg.get_negotiated("nonexistent") is None


def test_is_compatible():
    neg = ProtocolNegotiator()
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="1.0.0",
    )
    neg.negotiate(peer_id="remote-1", remote_status=remote)
    assert neg.is_compatible("remote-1") is True
    assert neg.is_compatible("nonexistent") is False


def test_negotiated_result_stored():
    neg = ProtocolNegotiator()
    remote = RegistryStatus(
        peer_id="remote-1",
        protocol_version="1.0.0",
    )
    result = neg.negotiate(peer_id="remote-1", remote_status=remote)
    stored = neg.get_negotiated("remote-1")
    assert stored is result


# ---------------------------------------------------------------------------
# NegotiationResult model
# ---------------------------------------------------------------------------

def test_negotiation_result_model():
    r = NegotiationResult(
        peer_id="p1",
        compatible=True,
        agreed_compression=["gzip"],
        agreed_formats=["json"],
        max_object_size=10 * 1024 * 1024,
        max_chunk_size=1024 * 1024,
    )
    assert r.peer_id == "p1"
    assert r.compatible is True
    assert r.agreed_compression == ["gzip"]
    assert r.agreed_formats == ["json"]
    assert r.max_object_size == 10 * 1024 * 1024
    assert r.max_chunk_size == 1024 * 1024


# ---------------------------------------------------------------------------
# Multiple peers negotiation
# ---------------------------------------------------------------------------

def test_multiple_peers_negotiation():
    neg = ProtocolNegotiator()
    for i in range(3):
        remote = RegistryStatus(
            peer_id=f"remote-{i}",
            protocol_version="1.0.0",
        )
        neg.negotiate(peer_id=f"remote-{i}", remote_status=remote)

    for i in range(3):
        assert neg.is_compatible(f"remote-{i}") is True
        assert neg.get_negotiated(f"remote-{i}") is not None
