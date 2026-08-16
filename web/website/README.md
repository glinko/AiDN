# AiDN public website

This is the first WEB-0001 implementation slice: the public website and the
small, bounded Web App surface are kept separate from the node-local Operator
Dashboard.

## Run locally

```bash
pnpm install
pnpm run dev:demo
```

The demo mode uses clearly labelled illustrative network, Endpoint, and
Faucet data. It is safe for visual review and must not be presented as live
network state.

To connect the UI to the Website Backend instead:

```bash
VITE_WEBSITE_API_BASE=/api/site/v1 AIDN_WEBSITE_BACKEND_URL=http://127.0.0.1:8000 pnpm run dev
```

The browser only calls the website-owned `/api/site/v1/*` boundary. The Vite
proxy forwards that path to the configured Website Backend; it does not expose
Faucet credentials or call arbitrary Hypervisors from the browser.

## Routes

- `/` — product story and local-first network model
- `/how-it-works` — connect, deploy, publish, use
- `/network` — verified summary metrics and read-only Endpoint Explorer
- `/run-a-node` — reviewed Ubuntu install path and operator sequence
- `/build` — agent loop and policy-bound MCP surface
- `/docs` — task-oriented documentation entry points
- `/app/faucet` — Wallet proof, one-time challenge, and claim flow

## Verification

```bash
pnpm run build
pnpm run typecheck
pnpm exec oxlint src
```

The network page intentionally renders “Not reported” when a metric is not
returned by the Website API. The Faucet never asks the browser for a private
key; it submits a Wallet ID, public key, one-time challenge proof, and an
idempotency request ID.
