# AiDN Hypervisor

Autonomous Intelligence Dispatch Network — a hypervisor for managing AI agent lifecycles, provider integrations, and paid session orchestration.

[![CI](https://github.com/glinko/AiDN/actions/workflows/ci.yml/badge.svg?branch=p0-infrastructure-overhaul)](https://github.com/glinko/AiDN/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-70%25%2B-green)](https://github.com/glinko/AiDN/actions/workflows/ci.yml)

## Quick Start

```bash
pip install -e ".[dev]"
pytest
```

## CI Pipeline

Three-stage pipeline: **quality** → **tests** → **integration**

| Stage | Jobs | Blocking |
|-------|------|----------|
| Quality | `ruff`, `mypy` (warn-only) | ruff blocks, mypy warns |
| Tests | `coverage`, `smoke`, `service-contracts` | yes |
| Integration | `providers-plugins`, `dispatcher-runtime`, `endpoint-session-paid-flow` | yes |

## Docs

- [Vision](00_VISION.md)
- [Terms](01_TERMS.md)
- [Architecture](02_ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
