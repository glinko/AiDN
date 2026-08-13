from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).parents[2] / "tools" / "rollout-protocol-authority-policy.py"
    spec = importlib.util.spec_from_file_location("rollout_protocol_authority_policy", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Remote:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def run(self, command: str, **_: object) -> str:
        self.commands.append(command)
        return ""


def test_policy_install_keeps_redirection_inside_privileged_shell() -> None:
    module = _module()
    remote = _Remote()

    module._install_policy(
        remote,
        host_path="/root/state/protocol-authority.json",
        policy_bytes=b"{}\n",
        content_sha256="0" * 64,
    )

    assert len(remote.commands) == 1
    command = remote.commands[0]
    assert command.startswith("sh -c '")
    assert " > /root/state/protocol-authority.json.tmp-" in command
    assert "mv -f /root/state/protocol-authority.json.tmp-" in command


def test_epoch_submitters_serialize_dataclass_finality_evidence() -> None:
    root = Path(__file__).parents[2] / "tools"
    for name in ("submit-authorized-epoch-schedule.py", "submit-authorized-epoch-transition.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "evidence.model_dump()" in source
        assert 'evidence.model_dump(mode="json")' not in source
