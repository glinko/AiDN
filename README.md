# AiDN Hypervisor

Autonomous Intelligence Dispatch Network — a hypervisor for managing AI agent lifecycles, provider integrations, and paid session orchestration.

[![CI](https://github.com/glinko/AiDN/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/glinko/AiDN/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-70%25%2B-green)](https://github.com/glinko/AiDN/actions/workflows/ci.yml)

## Quick Start

```bash
uv sync --all-extras
uv run pytest -q
```

The checked-in `uv.lock` is the reproducible dependency resolution used by
local development and CI. After changing `pyproject.toml`, regenerate it with
`uv lock` and verify the result with `uv sync --all-extras --frozen`.

## CI Pipeline

The regular pipeline also has a blocking package gate after static checks and
tests.

Four-stage pipeline: **static checks** → **tests** → **package** → **opt-in integration**.

| Stage | Jobs | Blocking |
|-------|------|----------|
| Static checks | Ruff and the generated documentation catalog | yes |
| Tests | hermetic non-integration suite with coverage | yes |
| Package | build wheel/sdist and verify isolated wheel installation | yes |
| Integration | real provider and network checks via manual dispatch | configured environment only |

## Release Verification

The regular CI build includes a distribution gate: it builds both wheel and
source archives, installs the wheel outside the checkout, and uploads
`SHA256SUMS` with the artifacts. The manual `Release verification` workflow
reruns the locked hermetic suite before producing those artifacts. Its optional
four-validator CometBFT drill is Docker-backed and intentionally opt-in.

## Docs

- [Documentation catalog](docs/INDEX.md) — complete classified navigation for current specifications, operator material, plans, and historical evidence
- [Vision](00_VISION.md)
- [Terms](01_TERMS.md)
- [Architecture](02_ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
- [WEB-0001 Public Website and Web Application Specification](docs/product/WEB-0001-public-website-and-web-application-specification.md)
- [WEB-0001 Website Implementation Plan](docs/development/plans/web-0001-implementation-plan.md)
- [WEB-0001 Website API OpenAPI](docs/product/WEB-0001-website-api.openapi.yaml)
- [WEB-0001 public website implementation](web/website/README.md)
- [RFC-0072 Hypervisor Event and Agent Hook Protocol](docs/product/RFC-0072-hypervisor-event-and-agent-hook-protocol.md)
- [RFC-0073 Resource Broker, Admission Control and Runtime Scheduler](docs/product/RFC-0073-resource-broker-admission-control-and-runtime-scheduler.md)
- [RFC-0074 Object Lifecycle, Decommissioning and Node Reset](docs/product/RFC-0074-object-lifecycle-deletion-decommissioning-and-node-reset.md)
- [IMP-0002 Deletion, Decommissioning and Reset Implementation Profile](docs/product/IMP-0002-deletion-decommissioning-and-reset-implementation-profile.md)
- [RFC-0075 Node Intelligence Architecture](docs/product/RFC-0075-node-intelligence-architecture.md)
- [Local agent MCP runbook for node 127](docs/operations/local-agent-node127-mcp-runbook.md)
- [Four-validator CometBFT acceptance drill](docs/evidence/cometbft-multivalidator-acceptance-drill.md)
- [Executable implementation and operator specification pack](docs/operations/spec-pack/README.md)
- [Configuration templates](config/aidn.env.example), [TOML operator profile](config/aidn.config.example.toml), and [hardcoded-parameter inventory](docs/configuration/hardcoded-parameters.md)
