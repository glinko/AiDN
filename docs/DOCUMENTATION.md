# AiDN Documentation System

This document defines how documentation is organized, named, linked, and
maintained in this repository.

## Purpose

Documentation must let three audiences find the right source quickly:

- an operator who needs an installation or incident procedure;
- a contributor who needs the current implementation direction; and
- a reviewer who needs the normative protocol or a verifiable historical
  record.

The generated [Documentation Catalog](INDEX.md) is the navigation entry point.
This document defines the rules behind that catalog.

## Directory taxonomy

| Location | Contents | Authority |
| --- | --- | --- |
| repository root | Vision, terms, architecture, product framing, design system, and current roadmap | Current project-level reference |
| `docs/product/` | RFC, ECO, UX, UI, WEB, MVP, and implementation-profile specifications | Normative for the named subject |
| `docs/configuration/` | Configuration references and parameter inventories | Current reference |
| `docs/operations/` | Installation, deployment, operator, and recovery guides | Current operational guidance |
| `docs/operations/spec-pack/` | Executable release, migration, and validator procedures | Current operational guidance |
| `docs/development/reference/` | Engineering notes, internal contracts, and technical reference material | Current engineering guidance |
| `docs/development/plans/` | Active implementation roadmaps and planned slices | Planning only; ROADMAP resolves priority conflicts |
| `docs/evidence/` | Dated acceptance reports, drills, simulations, and rollout evidence | Historical evidence, not instructions |
| `docs/archive/` | Superseded milestone plans, design specifications, and mockups | Historical context only |

## Identifiers and filenames

- A document identifier is globally unique. Never reuse an allocated `RFC`,
  `ECO`, `UX`, `UI`, `WEB`, `MVP`, `MCP`, `IMP`, `OPS`, `EVD`, `FIX`, `GATE`, or
  `MIG` identifier.
- The filename begins with the identifier when one exists, followed by a
  lowercase kebab-case subject: `RFC-0078-example-protocol.md`.
- The first heading starts with the same identifier and the human-readable
  title: `# RFC-0078 — Example Protocol`.
- Dated evidence uses an ISO date in the filename:
  `component-acceptance-2026-08-28.md`.
- New material must be placed in its final taxonomy directory. Do not create
  new documents under `docs/archive/` or use legacy directory names.

## Authority and lifecycle

1. Product and protocol behavior is defined by the applicable document under
   `docs/product/`, not by a plan, issue, or acceptance report.
2. The root [Roadmap](../ROADMAP.md) is the current priority and delivery
   reference. An implementation plan describes a slice; it cannot silently
   override an approved product specification.
3. Evidence records what was observed at a stated time and environment. It
   must not be edited to make it look like current guidance.
4. When a current document is superseded, retain it under `docs/archive/` and
   add a visible replacement link at the top where practical.

## Links and maintenance

- Use relative Markdown links for repository documents.
- Link to the authoritative product document before linking to a historical
  plan or acceptance record.
- After adding, moving, or retiring a document, regenerate the catalog:

  ```bash
  uv run python tools/generate-docs-index.py
  ```

- CI verifies that the checked-in catalog matches the generator.
- Before committing a documentation migration, run the documentation-link
  verifier and inspect every unresolved link rather than weakening the check.
