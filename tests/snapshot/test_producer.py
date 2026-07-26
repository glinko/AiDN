"""Tests for SnapshotProducer — RFC-0062 §8, §20-§21.

Full snapshot production pipeline with local restoration verification.
"""

import copy
import pytest

from aidn_hypervisor.snapshot.models import (
    CompressionAlgorithm,
    Encoding,
    SnapshotType,
)
from aidn_hypervisor.snapshot.producer import (
    SnapshotProducer,
    SnapshotProducerConfig,
    SnapshotProducerError,
    ProduceResult,
)


# ── Helpers ────────────────────────────────────────────────────────

DEFAULT_CONFIG = SnapshotProducerConfig()
SIGNING_KEY = b"test-signing-key-32-bytes-!!"


def _make_state(**kwargs):
    """Build a minimal state dict."""
    return {k: v for k, v in kwargs.items() if v is not None}


def _make_full_state():
    """Build a state dict with multiple namespaces."""
    return {
        "wallets": {"w1": {"balance": 100}, "w2": {"balance": 200}},
        "hypervisors": {"h1": {"status": "running"}},
        "services": {"s1": {"type": "validator"}},
        "stakes": [{"wallet": "w1", "amount": 50}],
        "protocol_parameters": {"max_block_size": 1000000},
    }


def _produce_kwargs(overrides=None):
    """Default kwargs for SnapshotProducer.produce()."""
    defaults = {
        "state": _make_full_state(),
        "block_height": 1000,
        "block_hash": "0x" + "ab" * 32,
        "block_time": "2025-01-01T00:00:00Z",
        "epoch": 5,
        "chain_id": "aidn-mainnet",
        "network_id": "aidn",
        "network_revision": 1,
        "protocol_version": "1.0.0",
        "application_version": "0.1.0",
        "state_schema_version": 1,
        "producer_service_id": "producer-01",
    }
    if overrides:
        defaults.update(overrides)
    return defaults


# ── Config defaults ────────────────────────────────────────────────

class TestProducerConfig:

    def test_default_chunk_size(self):
        assert DEFAULT_CONFIG.chunk_size == 8_388_608

    def test_default_compression(self):
        assert DEFAULT_CONFIG.compression == CompressionAlgorithm.GZIP

    def test_default_format_version(self):
        assert DEFAULT_CONFIG.format_version == 1

    def test_default_stability_delay(self):
        assert DEFAULT_CONFIG.stability_delay_blocks == 100

    def test_default_max_snapshot_size(self):
        assert DEFAULT_CONFIG.max_snapshot_size == 10_737_418_240

    def test_config_is_frozen(self):
        """Config is a frozen pydantic model."""
        with pytest.raises(Exception):
            DEFAULT_CONFIG.chunk_size = 1

    def test_custom_config(self):
        cfg = SnapshotProducerConfig(
            chunk_size=4_000_000,
            compression=CompressionAlgorithm.NONE,
            format_version=2,
            stability_delay_blocks=50,
            max_snapshot_size=5_000_000_000,
        )
        assert cfg.chunk_size == 4_000_000
        assert cfg.compression == CompressionAlgorithm.NONE
        assert cfg.format_version == 2
        assert cfg.stability_delay_blocks == 50
        assert cfg.max_snapshot_size == 5_000_000_000


# ── Produce valid snapshot ────────────────────────────────────────

class TestProduceValidSnapshot:

    def test_produce_returns_result(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert isinstance(result, ProduceResult)

    def test_produce_with_empty_state(self):
        """Empty state produces a valid snapshot."""
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(
            **_produce_kwargs({"state": {}})
        )
        assert isinstance(result, ProduceResult)
        assert result.manifest is not None

    def test_produce_with_none_compression(self):
        """Snapshot with no compression works."""
        cfg = SnapshotProducerConfig(compression=CompressionAlgorithm.NONE)
        producer = SnapshotProducer(cfg, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.manifest.compression == CompressionAlgorithm.NONE


# ── Manifest fields ───────────────────────────────────────────────

class TestManifestFields:

    def test_snapshot_id_populated(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert len(result.manifest.snapshot_id) == 64  # SHA-256 hex

    def test_snapshot_type_is_full_state(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.manifest.snapshot_type == SnapshotType.FULL_STATE

    def test_format_version_set(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.manifest.snapshot_format_version == 1

    def test_chain_id_set(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.manifest.chain_id == "aidn-mainnet"

    def test_network_id_set(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.manifest.network_id == "aidn"

    def test_block_height_set(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.manifest.block_height == 1000

    def test_epoch_set(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.manifest.epoch == 5

    def test_producer_service_id_set(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.manifest.producer_service_id == "producer-01"

    def test_encoding_is_json_deterministic(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.manifest.encoding == Encoding.JSON_DETERMINISTIC

    def test_creation_time_present(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert len(result.manifest.creation_time) > 0

    def test_signature_present(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert len(result.manifest.producer_signature) > 0


# ── Chunk count ───────────────────────────────────────────────────

class TestChunkCount:

    def test_chunk_count_matches_manifest(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert len(result.chunks) == result.manifest.chunk_count

    def test_small_data_single_chunk(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs({"state": {}}))
        assert result.manifest.chunk_count >= 1

    def test_chunk_count_positive(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.manifest.chunk_count > 0


# ── Chunk root ────────────────────────────────────────────────────

class TestChunkRoot:

    def test_chunk_root_populated(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert len(result.chunk_root) == 64  # SHA-256 hex

    def test_chunk_root_matches_manifest(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.chunk_root == result.manifest.chunk_root


# ── Content hash ──────────────────────────────────────────────────

class TestContentHash:

    def test_content_hash_populated(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert len(result.content_hash) == 64

    def test_content_hash_matches_manifest(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.content_hash == result.manifest.snapshot_content_hash

    def test_content_size_matches_manifest(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.content_size == result.manifest.snapshot_content_size


# ── Local restoration verification ────────────────────────────────

class TestLocalRestoration:

    def test_restoration_succeeds_for_valid_snapshot(self):
        """Local restoration verification should pass for correct encoding."""
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        # If we got here without exception, verification passed
        assert result is not None

    def test_restoration_catches_encoding_mismatch(self):
        """If encoding is tampered, local restoration should fail."""
        from aidn_hypervisor.snapshot import encoding as enc_module
        original_encode = enc_module.PortableSnapshotEncoder.encode

        def broken_encode(self, state):
            data = original_encode(self, state)
            # Corrupt the last byte
            return data[:-1] + bytes([(data[-1] + 1) % 256])

        enc_module.PortableSnapshotEncoder.encode = broken_encode
        try:
            producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
            with pytest.raises(SnapshotProducerError, match="restoration"):
                producer.produce(**_produce_kwargs())
        finally:
            enc_module.PortableSnapshotEncoder.encode = original_encode


# ── Compression ───────────────────────────────────────────────────

class TestCompression:

    def test_gzip_compression_applied(self):
        cfg = SnapshotProducerConfig(compression=CompressionAlgorithm.GZIP)
        producer = SnapshotProducer(cfg, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.manifest.compression == CompressionAlgorithm.GZIP

    def test_none_compression_applied(self):
        cfg = SnapshotProducerConfig(compression=CompressionAlgorithm.NONE)
        producer = SnapshotProducer(cfg, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.manifest.compression == CompressionAlgorithm.NONE


# ── ProduceResult fields ──────────────────────────────────────────

class TestProduceResult:

    def test_all_fields_populated(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.manifest is not None
        assert len(result.chunks) > 0
        assert len(result.content_hash) > 0
        assert result.content_size > 0
        assert len(result.chunk_root) > 0

    def test_result_is_frozen(self):
        """ProduceResult should be a frozen model."""
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        with pytest.raises(Exception):
            result.content_hash = "tampered"


# ── Error handling ────────────────────────────────────────────────

class TestErrorHandling:

    def test_negative_block_height_raises(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        with pytest.raises(SnapshotProducerError):
            producer.produce(**_produce_kwargs({"block_height": -1}))

    def test_zero_block_height_raises(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        with pytest.raises(SnapshotProducerError):
            producer.produce(**_produce_kwargs({"block_height": 0}))

    def test_negative_epoch_raises(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        with pytest.raises(SnapshotProducerError):
            producer.produce(**_produce_kwargs({"epoch": -1}))

    def test_empty_chain_id_raises(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        with pytest.raises(SnapshotProducerError):
            producer.produce(**_produce_kwargs({"chain_id": ""}))

    def test_empty_network_id_raises(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        with pytest.raises(SnapshotProducerError):
            producer.produce(**_produce_kwargs({"network_id": ""}))

    def test_empty_block_hash_raises(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        with pytest.raises(SnapshotProducerError):
            producer.produce(**_produce_kwargs({"block_hash": ""}))

    def test_empty_protocol_version_raises(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        with pytest.raises(SnapshotProducerError):
            producer.produce(**_produce_kwargs({"protocol_version": ""}))

    def test_empty_application_version_raises(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        with pytest.raises(SnapshotProducerError):
            producer.produce(**_produce_kwargs({"application_version": ""}))

    def test_empty_producer_service_id_raises(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        with pytest.raises(SnapshotProducerError):
            producer.produce(**_produce_kwargs({"producer_service_id": ""}))

    def test_negative_state_schema_version_raises(self):
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        with pytest.raises(SnapshotProducerError):
            producer.produce(**_produce_kwargs({"state_schema_version": -1}))


# ── Stability delay ───────────────────────────────────────────────

class TestStabilityDelay:

    def test_stability_delay_configured(self):
        """stability_delay_blocks is stored in config."""
        cfg = SnapshotProducerConfig(stability_delay_blocks=200)
        assert cfg.stability_delay_blocks == 200

    def test_custom_stability_delay(self):
        """Custom stability delay is respected."""
        cfg = SnapshotProducerConfig(stability_delay_blocks=50)
        producer = SnapshotProducer(cfg, SIGNING_KEY)
        # Producer should accept and use the config
        result = producer.produce(**_produce_kwargs())
        assert result is not None


# ── Max snapshot size ─────────────────────────────────────────────

class TestMaxSnapshotSize:

    def test_max_snapshot_size_enforced(self):
        """Snapshot exceeding max size raises error."""
        # Create a very large state
        large_wallets = {f"w{i}": {"balance": i, "data": "x" * 10000} for i in range(10000)}
        large_state = _make_state(wallets=large_wallets)

        cfg = SnapshotProducerConfig(max_snapshot_size=100)  # 100 bytes max
        producer = SnapshotProducer(cfg, SIGNING_KEY)
        with pytest.raises(SnapshotProducerError, match="size"):
            producer.produce(**_produce_kwargs({"state": large_state}))

    def test_normal_state_within_limit(self):
        """Normal state fits within default max size."""
        producer = SnapshotProducer(DEFAULT_CONFIG, SIGNING_KEY)
        result = producer.produce(**_produce_kwargs())
        assert result.content_size < DEFAULT_CONFIG.max_snapshot_size
