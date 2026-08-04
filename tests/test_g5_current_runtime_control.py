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

    for action in ("status", "diagnose", "stop", "start", "graceful", "abrupt", "reboot", "recover"):
        assert action in source


def test_stop_and_start_paths_keep_the_outage_explicit() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    stop = source[source.index("  stop)"):source.index("  start)")]
    start = source[source.index("  start)"):source.index("  graceful)")]
    assert stop.index("stop_comet") < stop.index('remote sudo -n /usr/bin/docker stop "$container"')
    assert start.index("start_container") < start.index("start_comet_if_needed")


def test_diagnose_path_is_read_only_and_classifies_reprovision_boundary() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    diagnose = source[source.index("  diagnose)"):source.index("  graceful)")]
    assert "sudo -n /usr/bin/docker inspect" in diagnose
    assert "sudo -n /usr/bin/docker restart" not in diagnose
    assert "sudo -n /usr/bin/docker kill" not in diagnose
    assert "REPROVISION_REQUIRED" in diagnose
    assert "expected height .*last stored abci responses" in diagnose
