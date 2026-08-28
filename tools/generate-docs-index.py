#!/usr/bin/env python3
"""Generate the repository documentation catalog.

The catalog is deliberately an index, not another source of product truth.  It
lists every tracked Markdown document that belongs to the repository's product,
development, operational, or web/service documentation surfaces, and labels
the document's intended role.  Re-run this tool whenever documents are added,
renamed, or retired.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPOSITORY_ROOT / "docs" / "INDEX.md"
ROOT_DOCUMENTS = (
    "README.md",
    "00_VISION.md",
    "01_TERMS.md",
    "02_ARCHITECTURE.md",
    "PRODUCT.md",
    "DESIGN.md",
    "ROADMAP.md",
    "M7-PLAN.md",
    "M8-PLAN.md",
    "M9-PLAN.md",
    "M10-PLAN.md",
    "M11-PLAN.md",
    "design-qa.md",
)
ROOT_ROLES = {
    "README.md": ("Start here", "Repository entry point, local setup, CI, and primary links."),
    "00_VISION.md": ("Start here", "Product direction, governance principles, and path to DAO."),
    "01_TERMS.md": ("Start here", "Canonical vocabulary used across the project."),
    "02_ARCHITECTURE.md": ("Start here", "High-level canonical stack and migration boundary."),
    "PRODUCT.md": ("Start here", "Product positioning, users, principles, and constraints."),
    "DESIGN.md": ("Start here", "Dashboard visual system and interaction principles."),
    "ROADMAP.md": ("Start here", "Current delivery roadmap, gates, and milestones."),
}
ADDITIONAL_DOCUMENTS = (
    Path("docs/product/WEB-0001-website-api.openapi.yaml"),
)
DOCUMENT_TITLES = {
    "01_TERMS.md": "Terms",
    "02_ARCHITECTURE.md": "Architecture",
    "docs/product/WEB-0001-website-api.openapi.yaml": "WEB-0001 Website API OpenAPI",
}
ARCHIVE_MARKERS = ("acceptance", "evidence", "drill", "simulation", "rollout")


def title_for(path: Path) -> str:
    """Return the first Markdown heading, falling back to the filename."""

    relative = path.relative_to(REPOSITORY_ROOT).as_posix()
    if relative in DOCUMENT_TITLES:
        return DOCUMENT_TITLES[relative]
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1)
    return path.stem.replace("-", " ")


def classify(relative: Path) -> tuple[str, str]:
    """Return a stable catalog section and a concise role description."""

    normalized = relative.as_posix()
    name = relative.name.lower()
    if normalized in ROOT_ROLES:
        return ROOT_ROLES[normalized]
    if relative.parent == Path("."):
        return (
            "Historical plans",
            "Milestone plan retained as implementation history; use ROADMAP for current priority.",
        )
    if normalized.startswith("docs/product/"):
        if relative.suffix == ".yaml":
            return "Product and protocol authority", "Machine-readable API contract for a product surface."
        return "Product and protocol authority", "Normative product, economics, UX, or protocol specification."
    if normalized.startswith("docs/configuration/"):
        return "Configuration", "Configuration reference and parameter inventory."
    if normalized.startswith("docs/development/executable-spec-pack/"):
        return "Executable specifications and operator runbooks", "Executable implementation profile, release gate, migration, or operator procedure."
    if normalized.startswith("docs/development/"):
        if "repository-structure-audit" in name:
            return "Development plans", "Current repository health assessment and refactoring plan."
        if any(marker in name for marker in ARCHIVE_MARKERS) or re.search(r"20\d\d-\d\d-\d\d", name):
            return "Historical acceptance and evidence", "Dated acceptance record, rollout evidence, simulation, or operational drill."
        if "plan" in name or "roadmap" in name:
            return "Development plans", "Implementation plan or roadmap for a defined slice."
        return "Development and operations", "Engineering reference, integration guide, or operator runbook."
    if normalized.startswith("docs/superpowers/plans/"):
        return "Archived implementation plans", "Historical implementation plan retained for context and traceability."
    if normalized.startswith("docs/superpowers/specs/"):
        return "Archived design specifications", "Historical design specification retained for context and traceability."
    if normalized.startswith("web/"):
        return "Component documentation", "Setup and development guide for a web surface."
    if normalized.startswith("services/"):
        return "Component documentation", "Setup and development guide for a service."
    return "Other documentation", "Repository documentation reference."


def discovered_documents() -> list[Path]:
    documents: set[Path] = set()
    for relative in ROOT_DOCUMENTS:
        path = REPOSITORY_ROOT / relative
        if path.is_file():
            documents.add(Path(relative))
    for path in (REPOSITORY_ROOT / "docs").rglob("*.md"):
        if path != OUTPUT_PATH:
            documents.add(path.relative_to(REPOSITORY_ROOT))
    for path in (REPOSITORY_ROOT / "web").glob("*/README.md"):
        documents.add(path.relative_to(REPOSITORY_ROOT))
    for path in (REPOSITORY_ROOT / "services").glob("*/README.md"):
        documents.add(path.relative_to(REPOSITORY_ROOT))
    documents.update(path for path in ADDITIONAL_DOCUMENTS if (REPOSITORY_ROOT / path).is_file())
    return sorted(documents, key=lambda path: path.as_posix().lower())


def link_from_catalog(relative: Path) -> str:
    return Path(os.path.relpath(REPOSITORY_ROOT / relative, OUTPUT_PATH.parent)).as_posix()


def render() -> str:
    grouped: dict[str, list[tuple[Path, str, str]]] = {}
    for relative in discovered_documents():
        section, role = classify(relative)
        grouped.setdefault(section, []).append((relative, title_for(REPOSITORY_ROOT / relative), role))

    section_order = (
        "Start here",
        "Product and protocol authority",
        "Configuration",
        "Development and operations",
        "Executable specifications and operator runbooks",
        "Development plans",
        "Historical acceptance and evidence",
        "Historical plans",
        "Archived implementation plans",
        "Archived design specifications",
        "Component documentation",
        "Other documentation",
    )
    lines = [
        "<!-- Generated by tools/generate-docs-index.py; do not edit by hand. -->",
        "",
        "# AiDN Documentation Catalog",
        "",
        "This is the navigation entry point for the repository's maintained documentation. "
        "It distinguishes current authority and operator guidance from historical plans and "
        "dated evidence, without deleting the latter.",
        "",
        "## How to use this catalog",
        "",
        "- Begin with **Start here**, then follow the current [Roadmap](../ROADMAP.md).",
        "- Product and protocol documents are the normative references for behavior and policy.",
        "- Development and operations documents describe how to build, deploy, verify, and run the system.",
        "- Historical plans and evidence preserve decisions and test results; they are not current instructions unless explicitly referenced by a current document.",
        "",
        "## Catalog scope",
        "",
        "The generated catalog includes repository-root project documents, Markdown under `docs/`, "
        "the versioned product API schema, and component READMEs under `web/` and `services/`. "
        "Configuration examples remain linked from the relevant product and operator documents.",
        "",
    ]
    for section in section_order:
        entries = grouped.get(section, [])
        if not entries:
            continue
        lines.extend((f"## {section}", "", "| Document | What it is |", "| --- | --- |"))
        for relative, title, role in entries:
            safe_title = title.replace("|", "\\|")
            lines.append(f"| [{safe_title}]({link_from_catalog(relative)}) | {role} |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    OUTPUT_PATH.write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    main()
