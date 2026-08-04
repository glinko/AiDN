from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/g5-replacement-runtime-control.sh"


def test_replacement_control_has_only_explicit_safe_actions() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for action in ("status", "stop", "start", "abrupt"):
        assert action in source
    assert "sshpass" not in source
    assert "Password" not in source
    assert "sudo -S" not in source
    assert "pkill" not in source
    assert "killall" not in source
    assert "provision-validator-replacement.sh" in source


def test_replacement_control_passes_paths_and_ports_as_fixed_arguments() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '"$target" bash -s --' in source
    assert '"$action" "$root" "$repo" "$source_home" "$comet_bin"' in source
    assert 'export AIDN_REPROVISION_ROOT="$root"' in source
    assert 'export AIDN_RPC_PORT="$rpc_port"' in source
