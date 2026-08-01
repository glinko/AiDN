"""Regression coverage for the secret-free independent operator workspace."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_operator_kit_initialization_writes_templates_without_key_material(tmp_path: Path) -> None:
    workspace = tmp_path / "operator-kit"
    result = subprocess.run(
        [
            sys.executable,
            "tools/prepare-independent-operator-kit.py",
            "init",
            "--output",
            str(workspace),
            "--peer-id",
            "independent-operator-1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout)["status"] == "ok"
    registry_template = json.loads(
        (workspace / "registry-replication.json.template").read_text(encoding="utf-8")
    )
    assert registry_template["local_peer_id"] == "independent-operator-1"
    assert registry_template["signing_key_handle"].startswith("secret://")
    assert "private_key" not in registry_template
    assert not list(workspace.glob("*secret*"))
    assert (workspace / "external-cometbft-acceptance.json.template").is_file()
    assert (workspace / "operator-attestation.template.json").is_file()
