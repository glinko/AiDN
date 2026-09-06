#!/usr/bin/env python3
"""Verify the minimum traceability contract for the Spatial UI roadmap."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COVERAGE_PATH = REPOSITORY_ROOT / "docs" / "spatial" / "IMPLEMENTATION-COVERAGE.md"
ADR_IDS = tuple(f"ADR-{index:03d}" for index in range(1, 15))
REQUIRED_SECTIONS = (
    "## ADR coverage matrix",
    "## M0 acceptance coverage",
    "## M1.1 acceptance coverage",
    "## M1.2 acceptance coverage",
    "## M1.3 acceptance coverage",
    "## M1.4 acceptance coverage",
    "## M1.5 acceptance coverage",
    "## M1.6 acceptance coverage",
    "## M1.7 acceptance coverage",
    "## M1.8 acceptance coverage",
    "## M2.1 acceptance coverage",
    "## M2.2 acceptance coverage",
    "## M2.3 acceptance coverage",
    "## M2.4 acceptance coverage",
    "## M2.5 acceptance coverage",
    "## M2.6 acceptance coverage",
    "## M2.7 acceptance coverage",
    "## M3.1 acceptance coverage",
    "## M3.2 acceptance coverage",
    "## M3.3 acceptance coverage",
    "## M3.4 acceptance coverage",
    "## M3.5 acceptance coverage",
    "## M3.6 acceptance coverage",
    "## M4.1 acceptance coverage",
    "## M4.2 acceptance coverage",
    "## M4.3 acceptance coverage",
    "## M4.4 acceptance coverage",
    "## M4.5 acceptance coverage",
    "## M4.6 acceptance coverage",
    "## M4.7 acceptance coverage",
    "## M4.8 acceptance coverage",
    "## M4.9 acceptance coverage",
    "## M4.10 acceptance coverage",
    "## M5.1 acceptance coverage",
    "## M5.2 acceptance coverage",
    "## M5.3 acceptance coverage",
    "## M5.4 acceptance coverage",
    "## M5.5 acceptance coverage",
    "## M5.6 acceptance coverage",
    "## M5.7 acceptance coverage",
    "## M5.8 acceptance coverage",
    "## M5.9 acceptance coverage",
    "## M5.10 acceptance coverage",
    "## M6.1 acceptance coverage",
    "## M6.2 acceptance coverage",
    "## M6.3 acceptance coverage",
    "## M6.4 acceptance coverage",
    "## M6.5 acceptance coverage",
    "## M6.6 acceptance coverage",
    "## M6.7 acceptance coverage",
    "## M7.1 acceptance coverage",
    "## M7.2 acceptance coverage",
    "## M7.3 acceptance coverage",
    "## M7.4 acceptance coverage",
    "## M7.5 acceptance coverage",
    "## M7.6 acceptance coverage",
    "## M7.7 acceptance coverage",
    "## M8.1 acceptance coverage",
    "## M8.2 acceptance coverage",
    "## M8.3 acceptance coverage",
    "## M8.4 acceptance coverage",
    "## M8.5 acceptance coverage",
    "## M8.6 acceptance coverage",
    "## M8.7 acceptance coverage",
    "## M8.8 acceptance coverage",
    "## M9.1 acceptance coverage",
    "## M9.2 acceptance coverage",
    "## M9.3 acceptance coverage",
    "## M9.4 acceptance coverage",
    "## M9.5 acceptance coverage",
    "## M9.6 acceptance coverage",
    "## M9.7 acceptance coverage",
    "## M10.1 acceptance coverage",
    "## M10.2 acceptance coverage",
    "## M10.3 acceptance coverage",
    "## M10.4 acceptance coverage",
    "## M10.5 acceptance coverage",
    "## M10.6 acceptance coverage",
    "## M10.7 acceptance coverage",
    "## M10.8 acceptance coverage",
    "## M10.9 acceptance coverage",
    "## M11.1 acceptance coverage",
    "## M11.2 acceptance coverage",
    "## M11.3 acceptance coverage",
    "## M11.4 acceptance coverage",
    "## M11.5 acceptance coverage",
    "## M11.6 acceptance coverage",
    "## M11.7 acceptance coverage",
    "## M11.8 acceptance coverage",
    "## M11.9 acceptance coverage",
    "## M11.10 acceptance coverage",
    "## Stable contract IDs",
    "## Stable event type IDs",
    "## Feature flags",
    "## Canonical terminology",
    "## Classic and Spatial boundary",
    "## Change control",
)
VERSIONED_ID = re.compile(r"`spatial\.[a-z0-9.-]+\.v[1-9][0-9]*`")
M0_ACCEPTANCE_IDS = {
    f"M{milestone}.{criterion}-AC-{index:03d}"
    for milestone, criterion, index in (
        (0, 1, 1),
        (0, 1, 2),
        (0, 1, 3),
    )
}
M0_ACCEPTANCE_IDS.update(
    {
        f"M0.{milestone}-AC-{index:03d}"
        for milestone, index in (
            (2, 1), (2, 2), (2, 3), (2, 4),
            (3, 1), (3, 2), (3, 3), (3, 4),
            (4, 1), (4, 2), (4, 3), (4, 4), (4, 5),
            (5, 1), (5, 2), (5, 3), (5, 4), (5, 5),
        )
    }
)
M1_1_ACCEPTANCE_IDS = {f"M1.1-AC-{index:03d}" for index in range(1, 5)}
M1_2_ACCEPTANCE_IDS = {f"M1.2-AC-{index:03d}" for index in range(1, 6)}
M1_3_ACCEPTANCE_IDS = {f"M1.3-AC-{index:03d}" for index in range(1, 6)}
M1_4_ACCEPTANCE_IDS = {f"M1.4-AC-{index:03d}" for index in range(1, 5)}
M1_5_ACCEPTANCE_IDS = {f"M1.5-AC-{index:03d}" for index in range(1, 6)}
M1_6_ACCEPTANCE_IDS = {f"M1.6-AC-{index:03d}" for index in range(1, 6)}
M1_7_ACCEPTANCE_IDS = {f"M1.7-AC-{index:03d}" for index in range(1, 6)}
M1_8_ACCEPTANCE_IDS = {f"M1.8-AC-{index:03d}" for index in range(1, 7)}
M2_1_ACCEPTANCE_IDS = {f"M2.1-AC-{index:03d}" for index in range(1, 6)}
M2_2_ACCEPTANCE_IDS = {f"M2.2-AC-{index:03d}" for index in range(1, 6)}
M2_3_ACCEPTANCE_IDS = {f"M2.3-AC-{index:03d}" for index in range(1, 6)}
M2_4_ACCEPTANCE_IDS = {f"M2.4-AC-{index:03d}" for index in range(1, 6)}
M2_5_ACCEPTANCE_IDS = {f"M2.5-AC-{index:03d}" for index in range(1, 6)}
M2_6_ACCEPTANCE_IDS = {f"M2.6-AC-{index:03d}" for index in range(1, 7)}
M2_7_ACCEPTANCE_IDS = {f"M2.7-AC-{index:03d}" for index in range(1, 7)}
M3_1_ACCEPTANCE_IDS = {f"M3.1-AC-{index:03d}" for index in range(1, 7)}
M3_2_ACCEPTANCE_IDS = {f"M3.2-AC-{index:03d}" for index in range(1, 7)}
M3_3_ACCEPTANCE_IDS = {f"M3.3-AC-{index:03d}" for index in range(1, 7)}
M3_4_ACCEPTANCE_IDS = {f"M3.4-AC-{index:03d}" for index in range(1, 7)}
M3_5_ACCEPTANCE_IDS = {f"M3.5-AC-{index:03d}" for index in range(1, 7)}
M3_6_ACCEPTANCE_IDS = {f"M3.6-AC-{index:03d}" for index in range(1, 7)}
M4_1_ACCEPTANCE_IDS = {f"M4.1-AC-{index:03d}" for index in range(1, 7)}
M4_2_ACCEPTANCE_IDS = {f"M4.2-AC-{index:03d}" for index in range(1, 7)}
M4_3_ACCEPTANCE_IDS = {f"M4.3-AC-{index:03d}" for index in range(1, 7)}
M4_4_ACCEPTANCE_IDS = {f"M4.4-AC-{index:03d}" for index in range(1, 7)}
M4_5_ACCEPTANCE_IDS = {f"M4.5-AC-{index:03d}" for index in range(1, 7)}
M4_6_ACCEPTANCE_IDS = {f"M4.6-AC-{index:03d}" for index in range(1, 7)}
M4_7_ACCEPTANCE_IDS = {f"M4.7-AC-{index:03d}" for index in range(1, 7)}
M4_8_ACCEPTANCE_IDS = {f"M4.8-AC-{index:03d}" for index in range(1, 7)}
M4_9_ACCEPTANCE_IDS = {f"M4.9-AC-{index:03d}" for index in range(1, 7)}
M4_10_ACCEPTANCE_IDS = {f"M4.10-AC-{index:03d}" for index in range(1, 7)}
M5_1_ACCEPTANCE_IDS = {f"M5.1-AC-{index:03d}" for index in range(1, 7)}
M5_2_ACCEPTANCE_IDS = {f"M5.2-AC-{index:03d}" for index in range(1, 7)}
M5_3_ACCEPTANCE_IDS = {f"M5.3-AC-{index:03d}" for index in range(1, 7)}
M5_4_ACCEPTANCE_IDS = {f"M5.4-AC-{index:03d}" for index in range(1, 7)}
M5_5_ACCEPTANCE_IDS = {f"M5.5-AC-{index:03d}" for index in range(1, 7)}
M5_6_ACCEPTANCE_IDS = {f"M5.6-AC-{index:03d}" for index in range(1, 7)}
M5_7_ACCEPTANCE_IDS = {f"M5.7-AC-{index:03d}" for index in range(1, 7)}
M5_8_ACCEPTANCE_IDS = {f"M5.8-AC-{index:03d}" for index in range(1, 7)}
M5_9_ACCEPTANCE_IDS = {f"M5.9-AC-{index:03d}" for index in range(1, 7)}
M5_10_ACCEPTANCE_IDS = {f"M5.10-AC-{index:03d}" for index in range(1, 7)}
M6_1_ACCEPTANCE_IDS = {f"M6.1-AC-{index:03d}" for index in range(1, 7)}
M6_2_ACCEPTANCE_IDS = {f"M6.2-AC-{index:03d}" for index in range(1, 7)}
M6_3_ACCEPTANCE_IDS = {f"M6.3-AC-{index:03d}" for index in range(1, 7)}
M6_4_ACCEPTANCE_IDS = {f"M6.4-AC-{index:03d}" for index in range(1, 7)}
M6_5_ACCEPTANCE_IDS = {f"M6.5-AC-{index:03d}" for index in range(1, 7)}
M6_6_ACCEPTANCE_IDS = {f"M6.6-AC-{index:03d}" for index in range(1, 7)}
M6_7_ACCEPTANCE_IDS = {f"M6.7-AC-{index:03d}" for index in range(1, 7)}
M7_1_ACCEPTANCE_IDS = {f"M7.1-AC-{index:03d}" for index in range(1, 7)}
M7_2_ACCEPTANCE_IDS = {f"M7.2-AC-{index:03d}" for index in range(1, 7)}
M7_3_ACCEPTANCE_IDS = {f"M7.3-AC-{index:03d}" for index in range(1, 7)}
M7_4_ACCEPTANCE_IDS = {f"M7.4-AC-{index:03d}" for index in range(1, 7)}
M7_5_ACCEPTANCE_IDS = {f"M7.5-AC-{index:03d}" for index in range(1, 7)}
M7_6_ACCEPTANCE_IDS = {f"M7.6-AC-{index:03d}" for index in range(1, 7)}
M7_7_ACCEPTANCE_IDS = {f"M7.7-AC-{index:03d}" for index in range(1, 7)}
M8_1_ACCEPTANCE_IDS = {f"M8.1-AC-{index:03d}" for index in range(1, 7)}
M8_2_ACCEPTANCE_IDS = {f"M8.2-AC-{index:03d}" for index in range(1, 7)}
M8_3_ACCEPTANCE_IDS = {f"M8.3-AC-{index:03d}" for index in range(1, 7)}
M8_4_ACCEPTANCE_IDS = {f"M8.4-AC-{index:03d}" for index in range(1, 7)}
M8_5_ACCEPTANCE_IDS = {f"M8.5-AC-{index:03d}" for index in range(1, 7)}
M8_6_ACCEPTANCE_IDS = {f"M8.6-AC-{index:03d}" for index in range(1, 7)}
M8_7_ACCEPTANCE_IDS = {f"M8.7-AC-{index:03d}" for index in range(1, 7)}
M8_8_ACCEPTANCE_IDS = {f"M8.8-AC-{index:03d}" for index in range(1, 7)}
M9_1_ACCEPTANCE_IDS = {f"M9.1-AC-{index:03d}" for index in range(1, 7)}
M9_2_ACCEPTANCE_IDS = {f"M9.2-AC-{index:03d}" for index in range(1, 7)}
M9_3_ACCEPTANCE_IDS = {f"M9.3-AC-{index:03d}" for index in range(1, 7)}
M9_4_ACCEPTANCE_IDS = {f"M9.4-AC-{index:03d}" for index in range(1, 7)}
M9_5_ACCEPTANCE_IDS = {f"M9.5-AC-{index:03d}" for index in range(1, 7)}
M9_6_ACCEPTANCE_IDS = {f"M9.6-AC-{index:03d}" for index in range(1, 7)}
M9_7_ACCEPTANCE_IDS = {f"M9.7-AC-{index:03d}" for index in range(1, 7)}
M10_1_ACCEPTANCE_IDS = {f"M10.1-AC-{index:03d}" for index in range(1, 7)}
M10_2_ACCEPTANCE_IDS = {f"M10.2-AC-{index:03d}" for index in range(1, 7)}
M10_3_ACCEPTANCE_IDS = {f"M10.3-AC-{index:03d}" for index in range(1, 7)}
M10_4_ACCEPTANCE_IDS = {f"M10.4-AC-{index:03d}" for index in range(1, 7)}
M10_5_ACCEPTANCE_IDS = {f"M10.5-AC-{index:03d}" for index in range(1, 7)}
M10_6_ACCEPTANCE_IDS = {f"M10.6-AC-{index:03d}" for index in range(1, 7)}
M10_7_ACCEPTANCE_IDS = {f"M10.7-AC-{index:03d}" for index in range(1, 7)}
M10_8_ACCEPTANCE_IDS = {f"M10.8-AC-{index:03d}" for index in range(1, 7)}
M10_9_ACCEPTANCE_IDS = {f"M10.9-AC-{index:03d}" for index in range(1, 7)}
M11_1_ACCEPTANCE_IDS = {f"M11.1-AC-{index:03d}" for index in range(1, 7)}
M11_2_ACCEPTANCE_IDS = {f"M11.2-AC-{index:03d}" for index in range(1, 7)}
M11_3_ACCEPTANCE_IDS = {f"M11.3-AC-{index:03d}" for index in range(1, 7)}
M11_4_ACCEPTANCE_IDS = {f"M11.4-AC-{index:03d}" for index in range(1, 7)}
M11_5_ACCEPTANCE_IDS = {f"M11.5-AC-{index:03d}" for index in range(1, 7)}
M11_6_ACCEPTANCE_IDS = {f"M11.6-AC-{index:03d}" for index in range(1, 7)}
M11_7_ACCEPTANCE_IDS = {f"M11.7-AC-{index:03d}" for index in range(1, 7)}
M11_8_ACCEPTANCE_IDS = {f"M11.8-AC-{index:03d}" for index in range(1, 7)}
M11_9_ACCEPTANCE_IDS = {f"M11.9-AC-{index:03d}" for index in range(1, 7)}
M11_10_ACCEPTANCE_IDS = {f"M11.10-AC-{index:03d}" for index in range(1, 7)}


def fail(message: str) -> None:
    print(f"Spatial coverage verification failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def table_rows(content: str, heading: str) -> list[str]:
    section = content.split(heading, 1)[1].split("\n## ", 1)[0]
    return [line for line in section.splitlines() if line.startswith("|")][2:]


def main() -> int:
    if not COVERAGE_PATH.is_file():
        fail(f"missing {COVERAGE_PATH.relative_to(REPOSITORY_ROOT)}")

    content = COVERAGE_PATH.read_text(encoding="utf-8")
    for heading in REQUIRED_SECTIONS:
        if heading not in content:
            fail(f"missing section {heading}")

    coverage_rows = table_rows(content, "## ADR coverage matrix")
    for adr_id in ADR_IDS:
        matches = [row for row in coverage_rows if adr_id in row]
        if len(matches) != 1:
            fail(f"{adr_id} must have exactly one coverage row; found {len(matches)}")
        cells = [cell.strip() for cell in matches[0].strip("|").split("|")]
        if len(cells) != 6 or not cells[1] or not cells[2] or not cells[3] or not cells[4]:
            fail(f"{adr_id} row must name owner, slice, validation, and status")

    def validate_acceptance_table(heading: str, expected_ids: set[str]) -> int:
        rows = table_rows(content, heading)
        if not rows:
            fail(f"{heading} registry is empty")
        identifiers: set[str] = set()
        for row in rows:
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            if len(cells) != 5:
                fail(f"malformed acceptance row: {row}")
            acceptance_id, _, validation, status, deferred_reason = cells
            if not acceptance_id or not validation or not status:
                fail(f"acceptance row lacks ID, validation, or status: {row}")
            if status == "deferred" and deferred_reason in {"", "None"}:
                fail(f"deferred acceptance row lacks a reason: {acceptance_id}")
            identifiers.add(acceptance_id.strip("`").strip())
        missing = expected_ids - identifiers
        if missing:
            fail(f"{heading} is missing acceptance IDs: {', '.join(sorted(missing))}")
        return len(rows)

    m0_acceptance_count = validate_acceptance_table(
        "## M0 acceptance coverage",
        M0_ACCEPTANCE_IDS,
    )
    m1_1_acceptance_count = validate_acceptance_table(
        "## M1.1 acceptance coverage",
        M1_1_ACCEPTANCE_IDS,
    )
    m1_2_acceptance_count = validate_acceptance_table(
        "## M1.2 acceptance coverage",
        M1_2_ACCEPTANCE_IDS,
    )
    m1_3_acceptance_count = validate_acceptance_table(
        "## M1.3 acceptance coverage",
        M1_3_ACCEPTANCE_IDS,
    )
    m1_4_acceptance_count = validate_acceptance_table(
        "## M1.4 acceptance coverage",
        M1_4_ACCEPTANCE_IDS,
    )
    m1_5_acceptance_count = validate_acceptance_table(
        "## M1.5 acceptance coverage",
        M1_5_ACCEPTANCE_IDS,
    )
    m1_6_acceptance_count = validate_acceptance_table(
        "## M1.6 acceptance coverage",
        M1_6_ACCEPTANCE_IDS,
    )
    m1_7_acceptance_count = validate_acceptance_table(
        "## M1.7 acceptance coverage",
        M1_7_ACCEPTANCE_IDS,
    )
    m1_8_acceptance_count = validate_acceptance_table(
        "## M1.8 acceptance coverage",
        M1_8_ACCEPTANCE_IDS,
    )
    m2_1_acceptance_count = validate_acceptance_table(
        "## M2.1 acceptance coverage",
        M2_1_ACCEPTANCE_IDS,
    )
    m2_2_acceptance_count = validate_acceptance_table(
        "## M2.2 acceptance coverage",
        M2_2_ACCEPTANCE_IDS,
    )
    m2_3_acceptance_count = validate_acceptance_table(
        "## M2.3 acceptance coverage",
        M2_3_ACCEPTANCE_IDS,
    )
    m2_4_acceptance_count = validate_acceptance_table(
        "## M2.4 acceptance coverage",
        M2_4_ACCEPTANCE_IDS,
    )
    m2_5_acceptance_count = validate_acceptance_table(
        "## M2.5 acceptance coverage",
        M2_5_ACCEPTANCE_IDS,
    )
    m2_6_acceptance_count = validate_acceptance_table(
        "## M2.6 acceptance coverage",
        M2_6_ACCEPTANCE_IDS,
    )
    m2_7_acceptance_count = validate_acceptance_table(
        "## M2.7 acceptance coverage",
        M2_7_ACCEPTANCE_IDS,
    )
    m3_1_acceptance_count = validate_acceptance_table(
        "## M3.1 acceptance coverage",
        M3_1_ACCEPTANCE_IDS,
    )
    m3_2_acceptance_count = validate_acceptance_table(
        "## M3.2 acceptance coverage",
        M3_2_ACCEPTANCE_IDS,
    )
    m3_3_acceptance_count = validate_acceptance_table(
        "## M3.3 acceptance coverage",
        M3_3_ACCEPTANCE_IDS,
    )
    m3_4_acceptance_count = validate_acceptance_table(
        "## M3.4 acceptance coverage",
        M3_4_ACCEPTANCE_IDS,
    )
    m3_5_acceptance_count = validate_acceptance_table(
        "## M3.5 acceptance coverage",
        M3_5_ACCEPTANCE_IDS,
    )
    m3_6_acceptance_count = validate_acceptance_table(
        "## M3.6 acceptance coverage",
        M3_6_ACCEPTANCE_IDS,
    )
    m4_1_acceptance_count = validate_acceptance_table("## M4.1 acceptance coverage", M4_1_ACCEPTANCE_IDS)
    m4_2_acceptance_count = validate_acceptance_table("## M4.2 acceptance coverage", M4_2_ACCEPTANCE_IDS)
    m4_3_acceptance_count = validate_acceptance_table("## M4.3 acceptance coverage", M4_3_ACCEPTANCE_IDS)
    m4_4_acceptance_count = validate_acceptance_table("## M4.4 acceptance coverage", M4_4_ACCEPTANCE_IDS)
    m4_5_acceptance_count = validate_acceptance_table("## M4.5 acceptance coverage", M4_5_ACCEPTANCE_IDS)
    m4_6_acceptance_count = validate_acceptance_table("## M4.6 acceptance coverage", M4_6_ACCEPTANCE_IDS)
    m4_7_acceptance_count = validate_acceptance_table("## M4.7 acceptance coverage", M4_7_ACCEPTANCE_IDS)
    m4_8_acceptance_count = validate_acceptance_table("## M4.8 acceptance coverage", M4_8_ACCEPTANCE_IDS)
    m4_9_acceptance_count = validate_acceptance_table("## M4.9 acceptance coverage", M4_9_ACCEPTANCE_IDS)
    m4_10_acceptance_count = validate_acceptance_table("## M4.10 acceptance coverage", M4_10_ACCEPTANCE_IDS)
    m5_1_acceptance_count = validate_acceptance_table("## M5.1 acceptance coverage", M5_1_ACCEPTANCE_IDS)
    m5_2_acceptance_count = validate_acceptance_table("## M5.2 acceptance coverage", M5_2_ACCEPTANCE_IDS)
    m5_3_acceptance_count = validate_acceptance_table("## M5.3 acceptance coverage", M5_3_ACCEPTANCE_IDS)
    m5_4_acceptance_count = validate_acceptance_table("## M5.4 acceptance coverage", M5_4_ACCEPTANCE_IDS)
    m5_5_acceptance_count = validate_acceptance_table("## M5.5 acceptance coverage", M5_5_ACCEPTANCE_IDS)
    m5_6_acceptance_count = validate_acceptance_table("## M5.6 acceptance coverage", M5_6_ACCEPTANCE_IDS)
    m5_7_acceptance_count = validate_acceptance_table("## M5.7 acceptance coverage", M5_7_ACCEPTANCE_IDS)
    m5_8_acceptance_count = validate_acceptance_table("## M5.8 acceptance coverage", M5_8_ACCEPTANCE_IDS)
    m5_9_acceptance_count = validate_acceptance_table("## M5.9 acceptance coverage", M5_9_ACCEPTANCE_IDS)
    m5_10_acceptance_count = validate_acceptance_table("## M5.10 acceptance coverage", M5_10_ACCEPTANCE_IDS)
    m6_1_acceptance_count = validate_acceptance_table("## M6.1 acceptance coverage", M6_1_ACCEPTANCE_IDS)
    m6_2_acceptance_count = validate_acceptance_table("## M6.2 acceptance coverage", M6_2_ACCEPTANCE_IDS)
    m6_3_acceptance_count = validate_acceptance_table("## M6.3 acceptance coverage", M6_3_ACCEPTANCE_IDS)
    m6_4_acceptance_count = validate_acceptance_table("## M6.4 acceptance coverage", M6_4_ACCEPTANCE_IDS)
    m6_5_acceptance_count = validate_acceptance_table("## M6.5 acceptance coverage", M6_5_ACCEPTANCE_IDS)
    m6_6_acceptance_count = validate_acceptance_table("## M6.6 acceptance coverage", M6_6_ACCEPTANCE_IDS)
    m6_7_acceptance_count = validate_acceptance_table("## M6.7 acceptance coverage", M6_7_ACCEPTANCE_IDS)
    m7_1_acceptance_count = validate_acceptance_table("## M7.1 acceptance coverage", M7_1_ACCEPTANCE_IDS)
    m7_2_acceptance_count = validate_acceptance_table("## M7.2 acceptance coverage", M7_2_ACCEPTANCE_IDS)
    m7_3_acceptance_count = validate_acceptance_table("## M7.3 acceptance coverage", M7_3_ACCEPTANCE_IDS)
    m7_4_acceptance_count = validate_acceptance_table("## M7.4 acceptance coverage", M7_4_ACCEPTANCE_IDS)
    m7_5_acceptance_count = validate_acceptance_table("## M7.5 acceptance coverage", M7_5_ACCEPTANCE_IDS)
    m7_6_acceptance_count = validate_acceptance_table("## M7.6 acceptance coverage", M7_6_ACCEPTANCE_IDS)
    m7_7_acceptance_count = validate_acceptance_table("## M7.7 acceptance coverage", M7_7_ACCEPTANCE_IDS)
    m8_1_acceptance_count = validate_acceptance_table("## M8.1 acceptance coverage", M8_1_ACCEPTANCE_IDS)
    m8_2_acceptance_count = validate_acceptance_table("## M8.2 acceptance coverage", M8_2_ACCEPTANCE_IDS)
    m8_3_acceptance_count = validate_acceptance_table("## M8.3 acceptance coverage", M8_3_ACCEPTANCE_IDS)
    m8_4_acceptance_count = validate_acceptance_table("## M8.4 acceptance coverage", M8_4_ACCEPTANCE_IDS)
    m8_5_acceptance_count = validate_acceptance_table("## M8.5 acceptance coverage", M8_5_ACCEPTANCE_IDS)
    m8_6_acceptance_count = validate_acceptance_table("## M8.6 acceptance coverage", M8_6_ACCEPTANCE_IDS)
    m8_7_acceptance_count = validate_acceptance_table("## M8.7 acceptance coverage", M8_7_ACCEPTANCE_IDS)
    m8_8_acceptance_count = validate_acceptance_table("## M8.8 acceptance coverage", M8_8_ACCEPTANCE_IDS)
    m9_1_acceptance_count = validate_acceptance_table("## M9.1 acceptance coverage", M9_1_ACCEPTANCE_IDS)
    m9_2_acceptance_count = validate_acceptance_table("## M9.2 acceptance coverage", M9_2_ACCEPTANCE_IDS)
    m9_3_acceptance_count = validate_acceptance_table("## M9.3 acceptance coverage", M9_3_ACCEPTANCE_IDS)
    m9_4_acceptance_count = validate_acceptance_table("## M9.4 acceptance coverage", M9_4_ACCEPTANCE_IDS)
    m9_5_acceptance_count = validate_acceptance_table("## M9.5 acceptance coverage", M9_5_ACCEPTANCE_IDS)
    m9_6_acceptance_count = validate_acceptance_table("## M9.6 acceptance coverage", M9_6_ACCEPTANCE_IDS)
    m9_7_acceptance_count = validate_acceptance_table("## M9.7 acceptance coverage", M9_7_ACCEPTANCE_IDS)
    m10_1_acceptance_count = validate_acceptance_table("## M10.1 acceptance coverage", M10_1_ACCEPTANCE_IDS)
    m10_2_acceptance_count = validate_acceptance_table("## M10.2 acceptance coverage", M10_2_ACCEPTANCE_IDS)
    m10_3_acceptance_count = validate_acceptance_table("## M10.3 acceptance coverage", M10_3_ACCEPTANCE_IDS)
    m10_4_acceptance_count = validate_acceptance_table("## M10.4 acceptance coverage", M10_4_ACCEPTANCE_IDS)
    m10_5_acceptance_count = validate_acceptance_table("## M10.5 acceptance coverage", M10_5_ACCEPTANCE_IDS)
    m10_6_acceptance_count = validate_acceptance_table("## M10.6 acceptance coverage", M10_6_ACCEPTANCE_IDS)
    m10_7_acceptance_count = validate_acceptance_table("## M10.7 acceptance coverage", M10_7_ACCEPTANCE_IDS)
    m10_8_acceptance_count = validate_acceptance_table("## M10.8 acceptance coverage", M10_8_ACCEPTANCE_IDS)
    m10_9_acceptance_count = validate_acceptance_table("## M10.9 acceptance coverage", M10_9_ACCEPTANCE_IDS)
    m11_1_acceptance_count = validate_acceptance_table("## M11.1 acceptance coverage", M11_1_ACCEPTANCE_IDS)
    m11_2_acceptance_count = validate_acceptance_table("## M11.2 acceptance coverage", M11_2_ACCEPTANCE_IDS)
    m11_3_acceptance_count = validate_acceptance_table("## M11.3 acceptance coverage", M11_3_ACCEPTANCE_IDS)
    m11_4_acceptance_count = validate_acceptance_table("## M11.4 acceptance coverage", M11_4_ACCEPTANCE_IDS)
    m11_5_acceptance_count = validate_acceptance_table("## M11.5 acceptance coverage", M11_5_ACCEPTANCE_IDS)
    m11_6_acceptance_count = validate_acceptance_table("## M11.6 acceptance coverage", M11_6_ACCEPTANCE_IDS)
    m11_7_acceptance_count = validate_acceptance_table("## M11.7 acceptance coverage", M11_7_ACCEPTANCE_IDS)
    m11_8_acceptance_count = validate_acceptance_table("## M11.8 acceptance coverage", M11_8_ACCEPTANCE_IDS)
    m11_9_acceptance_count = validate_acceptance_table("## M11.9 acceptance coverage", M11_9_ACCEPTANCE_IDS)
    m11_10_acceptance_count = validate_acceptance_table("## M11.10 acceptance coverage", M11_10_ACCEPTANCE_IDS)

    if not VERSIONED_ID.search(content):
        fail("stable contract and event registries contain no versioned IDs")
    contract_rows = table_rows(content, "## Stable contract IDs")
    event_rows = table_rows(content, "## Stable event type IDs")
    for label, rows in (("contract", contract_rows), ("event", event_rows)):
        identifiers = [row.split("|", 2)[1].strip() for row in rows]
        if len(identifiers) != len(set(identifiers)):
            fail(f"duplicate stable {label} ID")

    if "`spatial_ui_enabled`" not in content:
        fail("missing required spatial_ui_enabled feature flag")
    if "`spatial_interaction_enabled`" not in content:
        fail("missing required spatial_interaction_enabled feature flag")
    if "`spatial_topology_enabled`" not in content:
        fail("missing required spatial_topology_enabled feature flag")
    if "`spatial_status_enabled`" not in content:
        fail("missing required spatial_status_enabled feature flag")
    if "`spatial_remote_mediation_enabled`" not in content:
        fail("missing required spatial_remote_mediation_enabled feature flag")
    if "`spatial_memory_enabled`" not in content:
        fail("missing required spatial_memory_enabled feature flag")
    if "`spatial_multi_device_sync_enabled`" not in content:
        fail("missing required spatial_multi_device_sync_enabled feature flag")
    if "`spatial_change_intent_enabled`" not in content:
        fail("missing required spatial_change_intent_enabled feature flag")
    if "`spatial_operator_preview_enabled`" not in content:
        fail("missing required spatial_operator_preview_enabled feature flag")

    print(
        f"Verified {len(coverage_rows)} ADR rows, {m0_acceptance_count} M0 acceptance rows, "
        f"{m1_1_acceptance_count} M1.1 acceptance rows, {m1_2_acceptance_count} M1.2 acceptance rows, "
        f"{m1_3_acceptance_count} M1.3, {m1_4_acceptance_count} M1.4, {m1_5_acceptance_count} M1.5, "
        f"{m1_6_acceptance_count} M1.6, {m1_7_acceptance_count} M1.7, and {m1_8_acceptance_count} M1.8 acceptance rows."
        f" M2.1: {m2_1_acceptance_count}, M2.2: {m2_2_acceptance_count}, M2.3: {m2_3_acceptance_count},"
        f" M2.4: {m2_4_acceptance_count}, M2.5: {m2_5_acceptance_count}, M2.6: {m2_6_acceptance_count},"
        f" M2.7: {m2_7_acceptance_count}, M3.1: {m3_1_acceptance_count},"
        f" M3.2: {m3_2_acceptance_count}, M3.3: {m3_3_acceptance_count},"
        f" M3.4: {m3_4_acceptance_count}, M3.5: {m3_5_acceptance_count},"
        f" and M3.6: {m3_6_acceptance_count} acceptance rows."
        f" M4.1: {m4_1_acceptance_count}, M4.2: {m4_2_acceptance_count}, M4.3: {m4_3_acceptance_count},"
        f" M4.4: {m4_4_acceptance_count}, M4.5: {m4_5_acceptance_count}, M4.6: {m4_6_acceptance_count},"
        f" M4.7: {m4_7_acceptance_count}, M4.8: {m4_8_acceptance_count}, M4.9: {m4_9_acceptance_count},"
        f" and M4.10: {m4_10_acceptance_count} acceptance rows."
        f" M5.1: {m5_1_acceptance_count}, M5.2: {m5_2_acceptance_count}, M5.3: {m5_3_acceptance_count},"
        f" M5.4: {m5_4_acceptance_count}, M5.5: {m5_5_acceptance_count}, M5.6: {m5_6_acceptance_count},"
        f" M5.7: {m5_7_acceptance_count}, M5.8: {m5_8_acceptance_count}, M5.9: {m5_9_acceptance_count},"
        f" M5.10: {m5_10_acceptance_count}, M6.1: {m6_1_acceptance_count}, M6.2: {m6_2_acceptance_count},"
        f" M6.3: {m6_3_acceptance_count}, M6.4: {m6_4_acceptance_count}, M6.5: {m6_5_acceptance_count},"
        f" M6.6: {m6_6_acceptance_count}, M6.7: {m6_7_acceptance_count}, M7.1: {m7_1_acceptance_count},"
        f" M7.2: {m7_2_acceptance_count}, M7.3: {m7_3_acceptance_count}, M7.4: {m7_4_acceptance_count},"
        f" M7.5: {m7_5_acceptance_count}, M7.6: {m7_6_acceptance_count}, M7.7: {m7_7_acceptance_count},"
        f" M8.1: {m8_1_acceptance_count}, M8.2: {m8_2_acceptance_count}, M8.3: {m8_3_acceptance_count},"
        f" M8.4: {m8_4_acceptance_count}, M8.5: {m8_5_acceptance_count}, M8.6: {m8_6_acceptance_count},"
        f" M8.7: {m8_7_acceptance_count}, M8.8: {m8_8_acceptance_count}, M9.1: {m9_1_acceptance_count},"
        f" M9.2: {m9_2_acceptance_count}, M9.3: {m9_3_acceptance_count}, M9.4: {m9_4_acceptance_count},"
        f" M9.5: {m9_5_acceptance_count}, M9.6: {m9_6_acceptance_count}, M9.7: {m9_7_acceptance_count},"
        f" M10.1: {m10_1_acceptance_count}, M10.2: {m10_2_acceptance_count}, M10.3: {m10_3_acceptance_count},"
        f" M10.4: {m10_4_acceptance_count}, M10.5: {m10_5_acceptance_count}, M10.6: {m10_6_acceptance_count},"
        f" M10.7: {m10_7_acceptance_count}, M10.8: {m10_8_acceptance_count}, M10.9: {m10_9_acceptance_count},"
        f" M11.1: {m11_1_acceptance_count}, M11.2: {m11_2_acceptance_count}, M11.3: {m11_3_acceptance_count},"
        f" M11.4: {m11_4_acceptance_count}, M11.5: {m11_5_acceptance_count}, M11.6: {m11_6_acceptance_count},"
        f" M11.7: {m11_7_acceptance_count}, M11.8: {m11_8_acceptance_count}, M11.9: {m11_9_acceptance_count},"
        f" and M11.10: {m11_10_acceptance_count} acceptance rows."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
