"""Tests for replay.py — Later-Block Replay per RFC-0062 §52-§54."""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from aidn_hypervisor.snapshot.replay import (
    BlockReplayer,
    BlockSource,
    ReplayBlock,
    ReplayConfig,
)

# ── Helpers ────────────────────────────────────────────────────────

def _hash(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


class MockBlockSource(BlockSource):
    """In-memory block source for tests."""

    def __init__(self, blocks: list[ReplayBlock], states: dict[int, dict] | None = None):
        self._blocks = {b.block_height: b for b in blocks}
        self._states = states or {}
        self._finalized_height = max((b.block_height for b in blocks), default=0)

    def get_block(self, height: int) -> ReplayBlock | None:
        return self._blocks.get(height)

    def get_finalized_height(self) -> int:
        return self._finalized_height

    def get_state_at_height(self, height: int) -> dict | None:
        return self._states.get(height)

    def execute_block(self, state: dict, block: ReplayBlock) -> dict:
        """Apply block: increment height, update hash, carry extras."""
        new_state = dict(state)
        new_state["height"] = block.block_height
        new_state["last_block_hash"] = block.block_hash
        new_state["state_hash"] = block.application_state_hash
        if block.validator_set_hash:
            new_state["validator_set_hash"] = block.validator_set_hash
        return new_state


def _make_block(height: int, state_hash: str | None = None,
                validator_hash: str | None = None) -> ReplayBlock:
    return ReplayBlock(
        block_height=height,
        block_hash=_hash(f"block-{height}"),
        application_state_hash=state_hash or _hash(f"state-{height}"),
        validator_set_hash=validator_hash,
        timestamp=f"2025-01-01T00:0{height}:00Z",
    )


def _make_state(height: int) -> dict:
    return {
        "height": height,
        "state_hash": _hash(f"state-{height}"),
        "accounts": {},
    }


# ── ReplayConfig defaults ──────────────────────────────────────────

class TestReplayConfigDefaults:
    def test_start_and_target(self):
        cfg = ReplayConfig(start_height=100, target_height=200)
        assert cfg.start_height == 100
        assert cfg.target_height == 200

    def test_max_replay_time_default(self):
        cfg = ReplayConfig(start_height=1, target_height=10)
        assert cfg.max_replay_time_seconds == 3600

    def test_verify_state_hash_default_true(self):
        cfg = ReplayConfig(start_height=1, target_height=10)
        assert cfg.verify_state_hash is True

    def test_verify_validator_set_default_true(self):
        cfg = ReplayConfig(start_height=1, target_height=10)
        assert cfg.verify_validator_set is True

    def test_custom_max_replay_time(self):
        cfg = ReplayConfig(start_height=1, target_height=10, max_replay_time_seconds=600)
        assert cfg.max_replay_time_seconds == 600

    def test_disable_state_hash_verification(self):
        cfg = ReplayConfig(start_height=1, target_height=10, verify_state_hash=False)
        assert cfg.verify_state_hash is False

    def test_disable_validator_set_verification(self):
        cfg = ReplayConfig(start_height=1, target_height=10, verify_validator_set=False)
        assert cfg.verify_validator_set is False


# ── ReplayBlock model ─────────────────────────────────────────────

class TestReplayBlock:
    def test_create_block(self):
        b = _make_block(42, "hash1", "val1")
        assert b.block_height == 42
        assert b.application_state_hash == "hash1"
        assert b.validator_set_hash == "val1"

    def test_block_is_frozen(self):
        b = _make_block(1)
        with pytest.raises(ValidationError):
            b.block_height = 2  # type: ignore

    def test_validator_set_hash_can_be_none(self):
        b = _make_block(1, validator_hash=None)
        assert b.validator_set_hash is None


# ── BlockReplayer basic replay ────────────────────────────────────

class TestBlockReplayerBasic:
    def test_replay_blocks_correctly(self):
        blocks = [_make_block(h) for h in range(101, 106)]
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=101, target_height=105)
        replayer = BlockReplayer(cfg, source)
        result = replayer.replay(_make_state(100))
        assert result.success is True
        assert result.blocks_replayed == 5
        assert result.start_height == 101
        assert result.end_height == 105

    def test_state_hash_verified_after_each_block(self):
        blocks = [_make_block(h) for h in range(101, 104)]
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=101, target_height=103, verify_state_hash=True)
        replayer = BlockReplayer(cfg, source)
        result = replayer.replay(_make_state(100))
        assert result.success is True

    def test_replay_failure_on_state_hash_mismatch(self):
        # Block at 102 has a mismatching state hash
        blocks = [
            _make_block(101),
            _make_block(102, state_hash="wrong-hash"),
            _make_block(103),
        ]
        source = MockBlockSource(blocks)

        def bad_execute(state: dict, block: ReplayBlock) -> dict:
            new = dict(state)
            new["height"] = block.block_height
            new["state_hash"] = _hash(f"state-{block.block_height}")
            return new

        class BadSource(MockBlockSource):
            def execute_block(self, state: dict, block: ReplayBlock) -> dict:
                return bad_execute(state, block)

        source2 = BadSource(blocks)
        cfg = ReplayConfig(start_height=101, target_height=103, verify_state_hash=True)
        replayer = BlockReplayer(cfg, source2)
        result = replayer.replay(_make_state(100))
        assert result.success is False
        assert any("state hash" in e.lower() or "mismatch" in e.lower() for e in result.errors)

    def test_validator_set_verified_at_end(self):
        val_hash = _hash("validator-set-final")
        blocks = [
            _make_block(101, validator_hash=val_hash),
            _make_block(102, validator_hash=val_hash),
        ]
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=101, target_height=102, verify_validator_set=True)
        replayer = BlockReplayer(cfg, source)
        result = replayer.replay(_make_state(100))
        assert result.success is True

    def test_replay_failure_on_validator_set_mismatch(self):
        blocks = [
            _make_block(101, validator_hash=_hash("v1")),
            _make_block(102, validator_hash=_hash("v2")),
        ]
        source = MockBlockSource(blocks)

        class MismatchSource(MockBlockSource):
            def execute_block(self, state: dict, block: ReplayBlock) -> dict:
                new = dict(state)
                new["height"] = block.block_height
                new["state_hash"] = block.application_state_hash
                new["validator_set_hash"] = _hash("unexpected-validator")
                return new

        source2 = MismatchSource(blocks)
        cfg = ReplayConfig(start_height=101, target_height=102, verify_validator_set=True)
        replayer = BlockReplayer(cfg, source2)
        result = replayer.replay(_make_state(100))
        assert result.success is False

    def test_replay_with_callback_reports_progress(self):
        blocks = [_make_block(h) for h in range(101, 104)]
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=101, target_height=103)
        replayer = BlockReplayer(cfg, source)
        calls: list[tuple[int, str]] = []

        def cb(height: int, state_hash: str):
            calls.append((height, state_hash))

        result = replayer.replay_with_callback(_make_state(100), cb)
        assert result.success is True
        assert len(calls) == 3  # 101, 102, 103

    def test_empty_replay_succeeds(self):
        blocks: list[ReplayBlock] = []
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=100, target_height=100)
        replayer = BlockReplayer(cfg, source)
        result = replayer.replay(_make_state(100))
        assert result.success is True
        assert result.blocks_replayed == 0

    def test_missing_block_raises_error(self):
        # Only blocks 101 and 103 exist; 102 is missing
        blocks = [_make_block(101), _make_block(103)]
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=101, target_height=103)
        replayer = BlockReplayer(cfg, source)
        result = replayer.replay(_make_state(100))
        assert result.success is False
        assert any("102" in e for e in result.errors)

    def test_replay_result_fields_populated(self):
        blocks = [_make_block(h) for h in range(101, 104)]
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=101, target_height=103)
        replayer = BlockReplayer(cfg, source)
        result = replayer.replay(_make_state(100))
        assert result.start_height == 101
        assert result.end_height == 103
        assert result.blocks_replayed == 3
        assert result.final_state_hash != ""
        assert result.duration_seconds >= 0.0

    def test_duration_tracked(self):
        blocks = [_make_block(h) for h in range(101, 104)]
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=101, target_height=103)
        replayer = BlockReplayer(cfg, source)
        result = replayer.replay(_make_state(100))
        assert result.duration_seconds > 0.0

    def test_large_replay_simulated_100_blocks(self):
        blocks = [_make_block(h) for h in range(1, 101)]
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=1, target_height=100)
        replayer = BlockReplayer(cfg, source)
        result = replayer.replay(_make_state(0))
        assert result.success is True
        assert result.blocks_replayed == 100
        assert result.end_height == 100

    def test_replay_range_calculation(self):
        blocks = [_make_block(h) for h in range(50, 60)]
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=50, target_height=59)
        replayer = BlockReplayer(cfg, source)
        start, end = replayer.get_replay_range()
        assert start == 50
        assert end == 59

    def test_replay_result_is_frozen(self):
        blocks = [_make_block(1)]
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=1, target_height=1)
        replayer = BlockReplayer(cfg, source)
        result = replayer.replay(_make_state(0))
        with pytest.raises(ValidationError):
            result.success = False  # type: ignore

    def test_replay_with_validator_hash_none_succeeds(self):
        # Blocks without validator_set_hash should still replay
        blocks = [_make_block(h, validator_hash=None) for h in range(101, 104)]
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=101, target_height=103, verify_validator_set=True)
        replayer = BlockReplayer(cfg, source)
        result = replayer.replay(_make_state(100))
        assert result.success is True

    def test_replay_skips_when_verify_state_hash_disabled(self):
        """Even with mismatched hashes, disabling verification should succeed."""
        blocks = [
            _make_block(101),
            _make_block(102, state_hash="wrong"),
        ]
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=101, target_height=102, verify_state_hash=False)
        replayer = BlockReplayer(cfg, source)
        result = replayer.replay(_make_state(100))
        assert result.success is True

    def test_replay_skips_when_verify_validator_disabled(self):
        """Disabling validator verification should not fail on mismatch."""
        blocks = [
            _make_block(101, validator_hash=_hash("v1")),
        ]
        source = MockBlockSource(blocks)

        class MismatchSource(MockBlockSource):
            def execute_block(self, state: dict, block: ReplayBlock) -> dict:
                new = dict(state)
                new["height"] = block.block_height
                new["state_hash"] = block.application_state_hash
                new["validator_set_hash"] = _hash("totally-different")
                return new

        source2 = MismatchSource(blocks)
        cfg = ReplayConfig(start_height=101, target_height=101, verify_validator_set=False)
        replayer = BlockReplayer(cfg, source2)
        result = replayer.replay(_make_state(100))
        assert result.success is True

    def test_replay_callback_receives_correct_hashes(self):
        blocks = [_make_block(h) for h in range(101, 104)]
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=101, target_height=103)
        replayer = BlockReplayer(cfg, source)
        calls: list[tuple[int, str]] = []

        def cb(height: int, state_hash: str):
            calls.append((height, state_hash))

        replayer.replay_with_callback(_make_state(100), cb)
        assert calls[0][0] == 101
        assert calls[1][0] == 102
        assert calls[2][0] == 103
        # State hashes should match expected
        assert calls[0][1] == blocks[0].application_state_hash
        assert calls[2][1] == blocks[2].application_state_hash

    def test_replay_result_end_height_matches_target(self):
        blocks = [_make_block(h) for h in range(50, 55)]
        source = MockBlockSource(blocks)
        cfg = ReplayConfig(start_height=50, target_height=54)
        replayer = BlockReplayer(cfg, source)
        result = replayer.replay(_make_state(49))
        assert result.end_height == 54

    def test_block_source_protocol_methods(self):
        blocks = [_make_block(1)]
        source = MockBlockSource(blocks)
        assert source.get_block(1) is not None
        assert source.get_block(999) is None
        assert source.get_finalized_height() == 1
        assert source.get_state_at_height(1) is None
