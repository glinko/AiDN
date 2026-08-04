from __future__ import annotations

from pathlib import Path


def test_multivalidator_script_builds_from_its_repository_root() -> None:
    script = (
        Path(__file__).parents[1]
        / "tools"
        / "run-cometbft-multivalidator-devnet.sh"
    ).read_text(encoding="utf-8")

    assert 'REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"' in script
    assert 'docker build -t "$APP_IMAGE" -f "$ROOT/Dockerfile" "$REPO_ROOT"' in script
    assert 'docker build -t "$APP_IMAGE" -f "$ROOT/Dockerfile" "$(pwd)"' not in script
