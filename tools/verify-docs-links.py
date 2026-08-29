#!/usr/bin/env python3
"""Verify local Markdown links in repository documentation."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((?P<target><[^>]+>|[^)\s]+)(?:\s+['\"][^)]*['\"])?\)")
EXTERNAL_PREFIXES = ("#", "/", "http://", "https://", "mailto:", "tel:")
DOCUMENT_ROOTS = (REPOSITORY_ROOT / "docs", REPOSITORY_ROOT / "web", REPOSITORY_ROOT / "services")
ROOT_DOCUMENTS = (
    REPOSITORY_ROOT / "README.md",
    REPOSITORY_ROOT / "00_VISION.md",
    REPOSITORY_ROOT / "01_TERMS.md",
    REPOSITORY_ROOT / "02_ARCHITECTURE.md",
    REPOSITORY_ROOT / "PRODUCT.md",
    REPOSITORY_ROOT / "DESIGN.md",
    REPOSITORY_ROOT / "ROADMAP.md",
)
LEGACY_PATHS = ("docs/superpowers/", "docs/development/executable-spec-pack/")


def markdown_documents() -> list[Path]:
    paths = set(ROOT_DOCUMENTS)
    paths.update(REPOSITORY_ROOT.glob("README.*.md"))
    for root in DOCUMENT_ROOTS:
        if root.exists():
            paths.update(root.rglob("*.md"))
    return sorted(path for path in paths if path.is_file() and "node_modules" not in path.parts)


def local_target(source: Path, raw_target: str) -> Path | None:
    target = raw_target[1:-1] if raw_target.startswith("<") and raw_target.endswith(">") else raw_target
    if not target or target.startswith(EXTERNAL_PREFIXES):
        return None
    path_part = target.split("#", 1)[0]
    if not path_part:
        return None
    candidate = (source.parent / path_part).resolve()
    try:
        return candidate.relative_to(REPOSITORY_ROOT)
    except ValueError:
        return None


def main() -> int:
    failures: list[str] = []
    for source in markdown_documents():
        relative_source = source.relative_to(REPOSITORY_ROOT)
        content = source.read_text(encoding="utf-8")
        for line_number, line in enumerate(content.splitlines(), start=1):
            for match in MARKDOWN_LINK.finditer(line):
                target = local_target(source, match.group("target"))
                if target is not None and not (REPOSITORY_ROOT / target).exists():
                    failures.append(f"{relative_source}:{line_number}: missing local target {match.group('target')}")
        for legacy_path in LEGACY_PATHS:
            if legacy_path in content:
                failures.append(f"{relative_source}: contains retired path {legacy_path}")
    if failures:
        print("Documentation link verification failed:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Verified local links in {len(markdown_documents())} Markdown documents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
