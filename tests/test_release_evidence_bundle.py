from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "build-release-evidence-bundle.py"
SPEC = importlib.util.spec_from_file_location("build_release_evidence_bundle", TOOL)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _run_tool(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, str(TOOL), *extra],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _required_args(tmp_path: Path) -> list[str]:
    artifact = tmp_path / "release.json"
    artifact.write_text('{"release":"test"}\n', encoding="utf-8")
    private_key = tmp_path / "operator.key"
    private_key.write_bytes(bytes(range(1, 33)))
    return [
        "--output",
        str(tmp_path / "bundle"),
        "--network-id",
        "testnet",
        "--release-version",
        "0.1.0-test",
        "--g0-report",
        str(tmp_path / "g0.json"),
        "--g1-report",
        str(tmp_path / "g1.json"),
        "--g2-report",
        str(tmp_path / "g2.json"),
        "--g3-report",
        str(tmp_path / "g3.json"),
        "--g4-report",
        str(tmp_path / "g4.json"),
        "--g5-report",
        str(tmp_path / "g5.json"),
        "--g6-evidence-dir",
        str(tmp_path / "operator-a"),
        "--g6-evidence-dir",
        str(tmp_path / "operator-b"),
        "--operator-id",
        "operator-test",
        "--control-group-id",
        "group-test",
        "--private-key",
        str(private_key),
        "--artifact",
        f"{artifact}=release/input.json",
    ]


def test_release_bundle_refuses_incomplete_pre_bundle_gates(tmp_path: Path) -> None:
    result = _run_tool(tmp_path, *_required_args(tmp_path))

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "INCOMPLETE"
    assert "G0=" in payload["reason"]
    assert not (tmp_path / "bundle").exists()


def test_release_bundle_rejects_signing_key_inside_output(tmp_path: Path) -> None:
    args = _required_args(tmp_path)
    output_index = args.index("--output") + 1
    output = Path(args[output_index])
    key_index = args.index("--private-key") + 1
    key = output / "operator.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(bytes(range(1, 33)))
    args[key_index] = str(key)

    result = _run_tool(tmp_path, *args)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "INCOMPLETE"
    assert "inside the output bundle" in payload["reason"]


def test_release_bundle_rejects_g6_context_mismatch(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "operator-a"
    evidence_dir.mkdir()
    (evidence_dir / "manifest.json").write_text(
        json.dumps(
            {
                "network_id": "old-network",
                "release_version": "0.1.0-old",
                "profile_id": "old-profile",
            }
        ),
        encoding="utf-8",
    )

    try:
        MODULE._validate_g6_context(
            [evidence_dir],
            network_id="new-network",
            release_version="0.1.0-new",
            profile_id="new-profile",
        )
    except ValueError as error:
        assert "context does not match" in str(error)
    else:
        raise AssertionError("stale G6 context was accepted")
