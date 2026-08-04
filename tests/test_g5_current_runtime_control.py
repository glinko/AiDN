from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/g5-current-runtime-control.sh"


def test_current_runtime_control_is_credential_free() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "sshpass" not in source
    assert "Password" not in source
    assert "sudo -S" not in source
    assert "sudo -n /usr/bin/docker restart" in source
    assert "sudo -n /usr/bin/docker kill" in source
    assert "sudo -n /usr/bin/docker stop" in source
    assert "sudo -n /usr/sbin/reboot" in source
    assert "pgrep -x cometbft" in source
    assert "pkill -TERM -x cometbft" in source
    assert "pkill -KILL -x cometbft" in source
    assert "remote_shell" not in source


def test_graceful_path_stops_comet_before_restarting_abci() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    graceful = source[source.index("  graceful)"):source.index("  abrupt)")]
    assert graceful.index("stop_comet") < graceful.index('remote sudo -n /usr/bin/docker restart "$container"')
    assert graceful.index('remote sudo -n /usr/bin/docker restart "$container"') < graceful.index(
        "start_comet_if_needed"
    )


def test_current_runtime_control_has_all_g5_actions() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for action in ("status", "graceful", "abrupt", "reboot", "recover"):
        assert action in source
