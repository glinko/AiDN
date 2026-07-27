# AiDN Hypervisor

Autonomous Intelligence Dispatch Network — a hypervisor for managing AI agent lifecycles, provider integrations, and paid session orchestration.

[![CI](https://github.com/glinko/AiDN/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/glinko/AiDN/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-70%25%2B-green)](https://github.com/glinko/AiDN/actions/workflows/ci.yml)

## Quick Start

```bash
pip install -e ".[dev]"
pytest
```

## CI Pipeline

Three-stage pipeline: **quality baseline** → **tests** → **opt-in integration**.

| Stage | Jobs | Blocking |
|-------|------|----------|
| Quality baseline | formatting and legacy Ruff findings are reported | non-blocking baseline |
| Tests | hermetic non-integration suite with coverage | yes |
| Integration | real provider and network checks via manual dispatch | configured environment only |

## Docs

- [Vision](00_VISION.md)
- [Terms](01_TERMS.md)
- [Architecture](02_ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
