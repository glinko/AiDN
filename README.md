# AiDN Hypervisor

<p align="center">
  <strong>Operate AI compute as a node — from local runtime to a verifiable network service.</strong>
</p>

<p align="center">
  <a href="https://github.com/glinko/AiDN/actions/workflows/ci.yml"><img src="https://github.com/glinko/AiDN/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-0f766e" alt="Apache-2.0 license"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.11%2B-3776ab" alt="Python 3.11 or newer"></a>
</p>

<p align="center"><strong>Language:</strong> English · <a href="README.ru.md">Русский</a></p>

AiDN is an operator control plane for AI resources. An **AiDN Hypervisor**
connects reviewed execution Providers, models, immutable Bundles, Endpoint
offers, Wallet-backed accounting, validation evidence, and network operations
without blurring their ownership boundaries.

It is built for the operator who needs to turn a machine into a useful AI node
and still understand exactly what is running, what is billable, and which
actions need explicit approval.

> **Project status:** active development and testnet preparation. The
> Hypervisor is safe-by-default: the supported Ubuntu bootstrap binds the API
> to loopback, does not open firewall ports, and does not publish a Wallet,
> Endpoint, or peer connection by itself.

## Contents

- [What the Hypervisor does](#what-the-hypervisor-does)
- [Dashboard](#dashboard)
- [For operators](#for-operators)
- [For developers](#for-developers)
- [Architecture](#architecture)
- [Documentation](#documentation)
- [Safety model](#safety-model)
- [Quality gates](#quality-gates)
- [License](#license)

## What the Hypervisor does

| Operator concern | AiDN boundary |
| --- | --- |
| **Compute** | Attach a reviewed Provider, materialize a model, and admit runtime work through the Resource Broker. |
| **Deployment** | Create an immutable Bundle that joins Provider, model, Runtime, configuration, and resource policy. |
| **Service** | Publish a distinct Endpoint offer only after the necessary readiness and validation gates. |
| **Settlement** | Use a Wallet and a refillable escrow deposit for explicit, metered Session accounting. |
| **Network** | Run CometBFT-aware node operations, peer discovery, replication, and validation without treating local state as global truth. |
| **Control** | Inspect node state through the Dashboard, CLI, or scoped MCP server; privileged actions remain policy- and approval-bound. |

The central idea is simple: a running process is not yet a network service. AiDN
makes each transition visible — from node identity to Provider, model, Bundle,
Endpoint, validation, discovery, and served requests.

## Dashboard

The React Dashboard is the operator's live map of that path. It works in
Basic Mode for routine setup and reveals the detailed Provider, Runtime,
Resource, validation, network, and automation surfaces in Advanced Mode.

![AiDN light-theme Dashboard overview: node journey and live prerequisites](docs/assets/dashboard-overview-light.png)

<p align="center"><sub>Current React Dashboard, captured from a locally booted development Hypervisor. It shows live development state, not a synthetic production claim.</sub></p>

The Resident Steward is deliberately a bounded local control agent, rather
than a hidden autonomous administrator. It receives safe node context,
classifies and explains observed state, and hands off actions through the
existing approval and Resource Broker boundaries.

![AiDN light-theme Agents screen: Resident Steward control boundary](docs/assets/dashboard-agents-light.png)

<p align="center"><sub>Resident Steward: explicit health, queue, and authority boundaries in the current light-theme interface.</sub></p>

## For operators

### Install on a fresh Ubuntu host

The supported path targets **Ubuntu 24.04+**. For an acceptance or production
exercise, pin a reviewed tag or commit; do not bootstrap from an unreviewed
moving reference.

```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/glinko/AiDN/<reviewed-ref>/tools/aidn-operator-bootstrap-ubuntu.sh \
  | bash -s -- --ref <reviewed-ref>
```

The interactive bootstrap provisions the checkout, persistent operator state,
an encrypted local secret store, host capacity measurement, a pinned CometBFT
process, user-level services, and the React Dashboard. It then prints a
secret-free handoff report with service URLs and next steps.

For automation with the conservative defaults:

```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/glinko/AiDN/<reviewed-ref>/tools/aidn-operator-bootstrap-ubuntu.sh \
  | bash -s -- --ref <reviewed-ref> \
      --operator-id operator-example-1 --non-interactive
```

After installation, the React Dashboard is served at:

```text
http://127.0.0.1:8766/operators/dashboard/react
```

The default listener is local-only. If a trusted-LAN dashboard is required,
make that choice explicitly in the wizard or follow the release-package guide;
never expose the unauthenticated HTTP API to the public Internet.

### First operator workflow

1. Install and open the Dashboard from the bootstrap handoff.
2. Pair the browser using the one-time code emitted by the installer, or run
   `aidn-operator pair` to issue a new ten-minute pairing code.
3. Bind or import the owner Wallet when network actions and settlement are
   needed.
4. Review and install a Provider, then select and materialize a model.
5. Create a Bundle, confirm resource admission, and start a Runtime.
6. Draft and validate an Endpoint before publishing or joining discovery.

The full procedures are in [Interactive Hypervisor installation](docs/operations/interactive-hypervisor-installation.md),
[Ubuntu Operator Release Package](docs/operations/operator-release-package.md),
and the [operator runbooks](docs/operations/).

### AI-assisted setup

The installer offers a reviewed `ai_assisted` mode for a bounded Provider and
model selection flow. It can prefetch a pinned model artifact, but it does not
silently install unreviewed software, create a Wallet, reserve compute,
publish an Endpoint, or bypass operator approval.

See the [assisted installation guide](docs/operations/interactive-hypervisor-installation.md)
for the supported catalog, resource estimates, integrity checks, and handoff
model.

## For developers

### Local setup

AiDN uses [uv](https://docs.astral.sh/uv/) for reproducible Python
environments. Python **3.11+** is required.

```bash
git clone https://github.com/glinko/AiDN.git
cd AiDN
uv sync --all-extras
uv run pytest -q
```

The checked-in `uv.lock` is the dependency resolution used by local
development and CI. After changing `pyproject.toml`, regenerate it with
`uv lock` and verify the lock with:

```bash
uv sync --all-extras --frozen
```

### Run the API locally

```bash
uv run uvicorn aidn_hypervisor.main:build_app --factory \
  --host 127.0.0.1 --port 8766
```

Open `http://127.0.0.1:8766/operators/dashboard/react` in a browser.

The React source lives in `web/operator-dashboard/`:

```bash
cd web/operator-dashboard
pnpm install
pnpm dev
```

### Useful commands

```bash
# Operator CLI
uv run aidn --help

# Static checks and the hermetic suite
uv run ruff check src tests
uv run pytest -q

# Rebuild and verify the documentation catalog
uv run python tools/generate-docs-index.py
uv run python tools/verify-docs-links.py
```

## Architecture

```text
Operator  ── Dashboard / CLI / MCP ──► Hypervisor control plane
                                            │
                         ┌──────────────────┼──────────────────┐
                         ▼                  ▼                  ▼
                    Provider          Resource Broker       Wallet
                         │                  │                  │
                         ▼                  ▼                  ▼
                    Runtime ─────────► Bundle ───────────► Endpoint
                                                               │
                                                               ▼
                                                        Session + escrow
                                                               │
                                                               ▼
                                              Validation / registry / consensus
```

- **Provider** owns how a model is executed.
- **Runtime** owns a live executable instance and its admission lease.
- **Bundle** is the immutable, reproducible deployment unit.
- **Endpoint** is the consumer-facing offer; it is not hidden inside a Bundle.
- **Session** records explicit request admission and metered settlement.
- **Ledger and consensus** determine canonical network state; a local UI never
  treats an unfinalized observation as finality.

Read the [Architecture](02_ARCHITECTURE.md) and
[Terms](01_TERMS.md) before extending these boundaries.

## Documentation

Start with the generated [documentation catalog](docs/INDEX.md). It separates
current product authority and operator procedures from implementation notes,
historical plans, and dated acceptance evidence.

| Need | Start here |
| --- | --- |
| Product direction and governance | [Vision](00_VISION.md) · [Roadmap](ROADMAP.md) |
| Protocol and product contracts | [Product & protocol authority](docs/INDEX.md#product-and-protocol-authority) |
| Node installation and operations | [Operations](docs/operations/) · [Operator release package](docs/operations/operator-release-package.md) |
| Network profile and testnet participation | [RFC-0076](docs/product/RFC-0076-network-profile-and-network-configuration.md) · [RFC-0077](docs/product/RFC-0077-testnet-participation-incentive-protocol.md) |
| Control and agent boundaries | [MCP-0001](docs/product/MCP-0001-node-control-server-implementation-profile.md) · [RFC-0075](docs/product/RFC-0075-node-intelligence-architecture.md) |
| Provider and runtime semantics | [RFC-0053](docs/product/RFC-0053-capability-runtime-specification.md) · [RFC-0055](docs/product/RFC-0055-provider-plugin-system-and-directory.md) |
| Configuration | [TOML example](config/aidn.config.example.toml) · [parameter inventory](docs/configuration/hardcoded-parameters.md) |
| API surface | [WEB-0001 OpenAPI](docs/product/WEB-0001-website-api.openapi.yaml) |
| Documentation conventions | [Documentation system](docs/DOCUMENTATION.md) |

## Safety model

AiDN treats operating an AI node as a control-plane problem, not merely a
model-launch problem.

- **Least exposure by default.** The Bootstrap uses loopback listeners and
  does not alter firewall policy.
- **Explicit authority.** Wallet, peer trust, Provider installation, resource
  reservation, Endpoint publication, and network-facing changes require their
  own reviewed paths.
- **Secrets stay local.** Private keys and encrypted secret-store material are
  never returned through the Dashboard or embedded into its configuration.
- **Policy-bound automation.** Steward, Dashboard, and MCP plans are
  allow-listed, hash-bound, idempotent where possible, and remain subject to
  operator approval.
- **Evidence before finality.** Network and accounting flows distinguish local
  observation, verified evidence, and consensus-finalized state.

## Quality gates

Every regular CI run performs four stages:

| Stage | What it verifies | Blocking |
| --- | --- | --- |
| Static checks | Ruff and generated documentation freshness | Yes |
| Tests | Hermetic test suite with coverage | Yes |
| Package | Wheel/sdist build and isolated wheel installation | Yes |
| Integration | Real Provider and network checks | Opt-in only |

The manual release-verification workflow reruns the locked suite and produces
distribution artifacts with `SHA256SUMS`. Docker-backed multi-validator
CometBFT drills are deliberately opt-in.

## License

AiDN is licensed under the [Apache License 2.0](LICENSE).
