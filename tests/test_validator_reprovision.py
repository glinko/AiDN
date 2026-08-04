from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/provision-validator-replacement.sh"


def test_validator_reprovision_isolated_and_fail_closed() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "source CometBFT home" in source
    assert "node_key.json" in source
    assert "priv_validator_key.json" in source
    assert "priv_validator_state.json" in source
    assert "new-data-only-no-blockstore-copy" in source
    assert "AIDN_COMETBFT_ABCI_STATE_PATH" in source
    assert "statesync" in source
    assert "trust_height" in source
    assert "trust_hash" in source
    assert "persistent_peers" in source
    assert "replacement root already exists" in source
    assert "unsafe-reset-all" not in source
    assert "rm -rf" not in source
    assert "docker" not in source


def test_validator_reprovision_only_stops_its_own_pids() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'pid_matches "$pid" "$marker"' in source
    assert 'kill -TERM "$pid"' in source
    assert 'kill -KILL "$pid"' in source
    assert "abrupt) abrupt" in source
    assert "pkill" not in source
    assert "killall" not in source
