# WEB-0001 Website Implementation Plan

Status: `Implemented foundation; integration backlog`

Version: `0.1`

Product source: [WEB-0001 Public Website and Web Application Specification](../product/WEB-0001-public-website-and-web-application-specification.md)

Target browser contract: [WEB-0001 Website API OpenAPI](../product/WEB-0001-website-api.openapi.yaml)

## 1. Goal

Harden the existing official AiDN Public Website and bounded Web App without
coupling it to the Hypervisor Dashboard. The visual/content foundation and
demo-mode user journeys are already implemented; the remaining work is to
replace illustrative adapters with verified Network/Faucet integrations and
complete production acceptance.

This plan maps `WEB-0001` to the current repository. It is not authority to change protocol behavior or weaken the Faucet proof model.

## 2. Current repository reality

As of `2026-08-20`:

- `web/website` is the implemented standalone Vite/React public website and
  Web App foundation;
- it includes Home, How It Works, Network, Run a Node, Build, Docs, Faucet,
  Explorer and responsive dark/light navigation surfaces;
- it uses a website-owned `/api/site/v1` adapter boundary and explicitly marks
  demo/illustrative data; production freshness/provenance is still pending;
- `web/operator-dashboard` is the node-local React Dashboard and remains separate;
- the supported Ubuntu installer is `tools/aidn-operator-bootstrap-ubuntu.sh`;
- the current public installation documentation is `docs/development/operator-release-package.md`;
- the external Faucet lives in `services/aidn-faucet`;
- the Faucet exposes `/v1/status`, `/v1/challenges`, `/v1/claims`, and `/v1/claims/{request_id}/reconcile` behind an agent bearer token;
- Faucet claims require Wallet ID, public key, challenge ID, and Wallet signature;
- current Wallet IDs are `wallet-<12 hex>`, derived from `ed25519:<64 hex>` public keys;
- Registry nodes and discovery are available from Hypervisor routes such as `/registry/nodes` and `/registry/discovery`;
- local `/api/v1/endpoints` inventory is not by itself a canonical network-wide Explorer;
- no production Website Backend/indexer is connected to the public aggregate
  Network Summary contract yet.

The next website work is therefore integration and release hardening. The
browser must not call arbitrary Hypervisors or the protected Faucet directly.

## 3. Target integration layout

The current implementation lives at `web/website`. The following target
layout remains the contract for a future server/BFF split; it is not a request
to replace the working Vite/React application with Next.js:

```text
web/website/
  app/
    (public)/
      page.tsx
      how-it-works/page.tsx
      network/page.tsx
      run-a-node/page.tsx
      build/page.tsx
      agents/page.tsx
      research/page.tsx
      download/page.tsx
      docs/page.tsx
    app/
      page.tsx
      faucet/page.tsx
      explorer/page.tsx
    api/site/v1/
      network/summary/route.ts
      network/endpoints/route.ts
      network/endpoints/[endpointId]/route.ts
      faucet/status/route.ts
      faucet/challenges/route.ts
      faucet/claims/route.ts
      faucet/claims/[requestId]/reconcile/route.ts
      releases/route.ts
      status/route.ts
    error.tsx
    global-error.tsx
    not-found.tsx
    layout.tsx
    robots.ts
    sitemap.ts
  components/
    content/
    diagrams/
    explorer/
    faucet/
    layout/
    metrics/
    ui/
  content/
    pages/
    docs-index.ts
    releases.ts
  lib/
    api/
    config/
    content/
    faucet/
    network/
    telemetry/
    validation/
  public/
    brand/
    social/
  tests/
    contracts/
    e2e/
    unit/
  next.config.ts
  package.json
  tsconfig.json
```

Do not import application code from `web/operator-dashboard`. Shared visual primitives may later move into a versioned workspace package, but the first slice should avoid a premature monorepo-wide component extraction.

## 4. Frontend architecture

Reference stack for a future BFF split:

- Next.js App Router;
- React and strict TypeScript;
- Tailwind CSS;
- shadcn/ui primitives owned by the repository;
- Lucide icons;
- TanStack Query only for interactive Web App reads/mutations;
- Zod for every external response boundary;
- Recharts only for charts backed by real time-series data;
- MDX or typed content modules for public content.

Current shipped foundation: Vite, React 19, TypeScript, Lucide, Manrope and
IBM Plex Mono, with the API boundary and demo data adapter described above.

Rules:

- content-only pages are Server Components by default;
- client components are limited to navigation, theme, diagrams, Explorer filters, Faucet flow, and copy controls;
- server routes own secrets and upstream credentials;
- every upstream payload is parsed into a website-owned schema before rendering;
- no page imports raw Faucet or Hypervisor response shapes directly;
- URL query parameters own shareable Explorer filters;
- theme preference uses the platform preference and a user override without blocking first render.

## 5. Website Backend boundary

The Next.js server route layer is the MVP Website Backend/BFF. It owns:

- upstream URL selection;
- Faucet agent bearer authorization;
- public rate limiting and abuse hooks;
- response normalization;
- cache policy;
- timeout and retry bounds;
- correlation IDs;
- safe error translation;
- release feed normalization.

It must not own:

- Faucet Treasury signing;
- Wallet private keys or browser Wallet custody;
- consensus finality decisions;
- Endpoint publication;
- Hypervisor operator actions;
- inferred network metrics.

If deployment constraints require an independent backend service, preserve the exact `/api/site/v1/*` public contract and move the handlers without changing browser behavior.

## 6. Public Website API contracts

All responses use JSON and include a request correlation ID header. Errors use:

```json
{
  "error": {
    "code": "UPSTREAM_UNAVAILABLE",
    "message": "Network data is temporarily unavailable.",
    "retryable": true,
    "request_id": "site-req-..."
  }
}
```

Never pass raw upstream exception text, URLs containing credentials, signatures, challenge values, or private policy state to the browser.

### 6.1 Network summary

`GET /api/site/v1/network/summary`

```json
{
  "network_id": "chain-id",
  "observed_at": "2026-08-16T00:00:00Z",
  "freshness_seconds": 12,
  "status": "available",
  "metrics": {
    "active_hypervisors": {
      "value": 4,
      "status": "available",
      "source_count": 4,
      "observed_at": "2026-08-16T00:00:00Z",
      "note": "Registry nodes with a fresh heartbeat"
    },
    "active_endpoints": {
      "value": 7,
      "status": "available",
      "source_count": 4,
      "observed_at": "2026-08-16T00:00:00Z"
    },
    "available_gpus": {
      "value": null,
      "status": "unavailable",
      "observed_at": "2026-08-16T00:00:00Z",
      "note": "No authoritative aggregate is currently exposed"
    }
  }
}
```

The indexer computes only documented metrics. A missing value is `null`, never `0`. Partial source coverage produces `status = partial` and a bounded note.

### 6.2 Endpoint search

`GET /api/site/v1/network/endpoints`

Supported query parameters for the MVP:

- `query`;
- `capability`;
- `provider`;
- `validation_state`;
- `availability`;
- `max_price_q_atoms`;
- `cursor`;
- `limit` from 1 to 50.

Response:

```json
{
  "items": [
    {
      "endpoint_id": "ep-...",
      "publication_id": "pub-...",
      "node_id": "node-...",
      "operator_id": "operator-...",
      "display_name": "Qwen local",
      "model_class": "llm_text",
      "provider_type": "llama.cpp",
      "capabilities": ["llm.chat"],
      "context_length": 32768,
      "pricing": {
        "unit": "request",
        "fixed_price_q_atoms": 0
      },
      "validation": {
        "state": "uncertified",
        "observed_at": "2026-08-16T00:00:00Z"
      },
      "reputation": null,
      "availability": {
        "state": "reported_ready",
        "observed_at": "2026-08-16T00:00:00Z",
        "source": "registry"
      },
      "publication": {
        "published_at": "2026-08-16T00:00:00Z",
        "configuration_hash": "sha256:..."
      }
    }
  ],
  "next_cursor": null,
  "observed_at": "2026-08-16T00:00:00Z"
}
```

Fields without authoritative evidence are `null`. Do not derive latency or GPU class from free text.

`GET /api/site/v1/network/endpoints/{endpointId}` returns the same identity plus available publication, validation, reputation, limits, price, and provenance details.

### 6.3 Faucet status facade

`GET /api/site/v1/faucet/status`

The Website Backend calls the protected Faucet `/v1/status` with the server-only agent token and returns a reduced response:

```json
{
  "enabled": true,
  "state": "ready",
  "policy_id": "fixed-daily",
  "policy_version": "...",
  "treasury_activation_state": "ACTIVE",
  "treasury_balance_q_atoms": 500000000,
  "low_balance_blocked": false,
  "paused": false,
  "pause_reason": null
}
```

Do not claim a fixed payout amount or cooldown unless the active policy exposes those values through a stable public projection. `remaining_budget` means Treasury balance only when explicitly labeled; it is not the user's remaining quota.

### 6.4 Faucet challenge facade

`POST /api/site/v1/faucet/challenges`

Request:

```json
{
  "wallet_id": "wallet-0123456789ab",
  "wallet_public_key": "ed25519:<64 lowercase hex>"
}
```

The Website Backend validates shape and deterministic Wallet/public-key relationship, applies public rate limits, then forwards to Faucet `/v1/challenges`.

Response mirrors only:

```json
{
  "challenge_id": "faucet-challenge-...",
  "wallet_id": "wallet-0123456789ab",
  "challenge": "...",
  "issued_at": "...",
  "expires_at": "...",
  "signing_domain": "aidn.faucet-wallet-proof.v1"
}
```

The challenge is public proof material but must not enter analytics or application logs.

### 6.5 Faucet claim facade

`POST /api/site/v1/faucet/claims`

Request:

```json
{
  "request_id": "web-claim-<client generated uuid>",
  "wallet_id": "wallet-0123456789ab",
  "wallet_public_key": "ed25519:<64 lowercase hex>",
  "challenge_id": "faucet-challenge-...",
  "wallet_signature": "ed25519:<signature>"
}
```

The backend uses `request_id` as an idempotency key and forwards the proof to Faucet `/v1/claims`. The normalized response contains:

- `request_id`;
- `claim_id` when available;
- normalized status;
- `amount_q_atoms`;
- `operation_id`;
- `transaction_hash`;
- policy ID/version;
- safe detail.

`POST /api/site/v1/faucet/claims/{requestId}/reconcile` always reconciles the exact original request. It must never create a new claim or new semantic transfer.

## 7. Network Indexer slice

Implement the Network read model before displaying aggregate metrics.

MVP responsibilities:

1. poll at least two operator-approved Registry/Hypervisor read sources where available;
2. validate chain/network identity;
3. ingest Registry node advertisements and current published Endpoint summaries;
4. retain source, observation time, heartbeat TTL, and conflict state;
5. deduplicate by canonical node/publication identity;
6. exclude stale records from active totals by default;
7. expose metric coverage and disagreement;
8. fail closed on chain mismatch;
9. never treat a browser-supplied Hypervisor URL as an upstream.

Storage may begin as a small PostgreSQL schema or another durable indexed store approved for deployment. Do not compute the production summary by fanning out from a browser request to every node.

Minimum indexed entities:

- `network_sources`;
- `registry_nodes`;
- `endpoint_publications`;
- `endpoint_observations`;
- `validation_observations`;
- `network_metric_snapshots`;
- `ingestion_runs`.

## 8. Faucet security implementation

The Website Backend adds an Internet-facing boundary in front of a service currently designed for protected access. Before public exposure, implement:

- IP and Wallet rate limiting;
- global request limit;
- wallet-proof verification remains authoritative in Faucet;
- bounded body size;
- strict JSON content type;
- origin/CSRF policy for mutations;
- request ID idempotency;
- timeout and retry policy that never duplicates a claim;
- server-only Faucet agent token;
- logs that hash or omit Wallet and proof material;
- emergency disable propagation;
- separate security audit log;
- configurable CAPTCHA/proof-of-human hook, disabled only by explicit environment policy;
- response headers preventing caching of proof and claim responses.

The Website Backend must never receive or store the Wallet private key. The initial MVP may provide copyable signing bytes and CLI/Hypervisor instructions. A future Wallet connector can replace manual signature entry without changing the Faucet service contract.

## 9. Content implementation

Create typed content entries for:

- Home sections;
- audience routes;
- How It Works stages;
- Provider examples and maturity;
- research topics and maturity;
- documentation taxonomy;
- footer links;
- platform support matrix.

Installation commands and release facts come from a single release data adapter. Do not duplicate an install command in Home, Run a Node, Download, and Docs.

Every factual capability claim includes a source link in content metadata. The source may be hidden from the normal visual surface but must be available to maintainers and tests.

## 10. Page-by-page build order

### Phase 0 — foundation (`complete`)

- standalone `web/website` scaffold and package scripts;
- strict TypeScript, production build and source lint/typecheck entry points;
- tokens, dark/light theme, typography, layout, navigation, footer, metadata,
  error/empty states and reduced-motion behavior;
- demo-mode warning and bounded API adapter boundary.

Exit gate: satisfied for the current foundation; production hosting and full
browser automation remain release-hardening work.

### Phase 1 — truthful public content (`complete`)

- Home;
- How It Works;
- Run a Node;
- Build;
- Agents;
- Research maturity list;
- Docs entry;
- Download/release adapter.

Exit gate: satisfied in the shipped demo foundation; release metadata and
production links still require the integration adapter.

### Phase 2 — Network summary and status (`in progress`)

- implement indexer ingestion and provenance;
- implement `/api/site/v1/network/summary`;
- build Network metric states: loading, partial, stale, unavailable, and ready;
- implement `/status` dependency display.

Exit gate: every rendered metric has source/freshness metadata and missing metrics render `Not reported`.

### Phase 3 — read-only Explorer (`foundation shipped; integration in progress`)

- implement indexed Endpoint search and details;
- implement URL-owned filters and pagination;
- render availability, publication, validation, reputation, and pricing as separate evidence groups;
- add empty and partial-data states.

Exit gate: no result field is inferred from display text and no write action exists.

### Phase 4 — Faucet (`foundation shipped; production integration in progress`)

- implement server-only Faucet facade and credential handling;
- implement Wallet/public-key validation;
- build challenge/signature/claim/reconcile state machine;
- add public and global rate limits;
- add security logging without proof leakage;
- add CAPTCHA/proof-of-human adapter point;
- add end-to-end tests against a disposable Faucet instance.

Exit gate: one exact request can move through challenge, proof, claim, pending finality, and reconciliation without duplicate transfer creation.

### Phase 5 — release hardening (`open`)

- SEO and social assets;
- Web Vitals budgets;
- dependency degradation drills;
- security header review;
- accessibility audit;
- content claim review;
- production configuration and rollback documentation.

## 11. Environment contract

Server-only variables:

```text
AIDN_SITE_NETWORK_SOURCES
AIDN_SITE_NETWORK_ID
AIDN_SITE_FAUCET_URL
AIDN_SITE_FAUCET_AGENT_TOKEN
AIDN_SITE_RELEASE_REPOSITORY
AIDN_SITE_RELEASE_CHANNEL
AIDN_SITE_RATE_LIMIT_STORE_URL
AIDN_SITE_DATABASE_URL
AIDN_SITE_ANALYTICS_ENDPOINT
AIDN_SITE_ANALYTICS_TOKEN
AIDN_SITE_CAPTCHA_PROVIDER
AIDN_SITE_CAPTCHA_SECRET
```

Browser-safe variables must use a separate explicit allowlist. Never expose upstream tokens, internal source URLs, database credentials, or CAPTCHA secrets through a public prefix.

Preview deployments use non-production Faucet credentials or disable Faucet mutations entirely. They must not point at the production Treasury.

## 12. Cache and freshness policy

| Data | Cache policy |
| --- | --- |
| Public content | static generation; invalidate on deploy/content update |
| Release feed | server cache, 5 minutes; show last successful refresh |
| Network summary | server cache, 10–30 seconds; preserve observed time |
| Explorer search | server cache, up to 15 seconds by normalized query |
| Faucet status | no shared cache or at most 5 seconds with no token leakage |
| Faucet challenge/claim/reconcile | `no-store` |
| Error responses containing request state | `no-store` |

Client retries are allowed only for safe GET requests. Faucet mutations require explicit state-aware retry/reconcile behavior.

## 13. Test strategy

### Unit

- Wallet/public-key relationship validation;
- q_atoms formatting;
- maturity labels;
- metric null/partial/stale rendering;
- Faucet state reducer;
- release command selection;
- content source metadata.

### Contract

- Zod fixtures for all `/api/site/v1/*` responses;
- current Faucet `/v1/*` adapter fixtures;
- Registry node/discovery adapter fixtures;
- chain mismatch and stale-heartbeat rejection;
- absent fields remain null rather than inferred.

### Integration

- indexer ingests two sources and deduplicates canonical records;
- one source disagreement produces partial/degraded status;
- Faucet facade never exposes its bearer token;
- repeated claim request ID is idempotent;
- reconciliation reuses the original request;
- upstream timeout maps to a safe bounded error.

### End-to-end

- role CTA journeys from Home;
- immutable install ref visible on Run a Node and Download;
- Network unavailable while public content remains usable;
- Explorer filters persist in URL and work with keyboard navigation;
- Faucet happy path with a disposable Wallet;
- Faucet challenge expiry and restart;
- pending finality reconciliation;
- quota exhausted, paused, low balance, rejected, and unknown states;
- dark/light theme;
- mobile navigation;
- reduced motion;
- `404`, route error, and dependency status pages.

### Security

- secret scan of browser bundles and rendered HTML;
- request body and header redaction tests;
- CSRF/origin tests for Faucet mutations;
- rate-limit tests by IP and Wallet identity;
- no caching of challenge or claim responses;
- no open proxy through Network source parameters;
- dependency URLs cannot be supplied by a visitor.

## 14. CI and release gates

Add blocking jobs for:

- dependency install from lockfile;
- typecheck;
- lint;
- unit and contract tests;
- production build;
- Playwright critical journeys;
- accessibility smoke tests;
- secret scan of generated assets;
- dead-link check for required routes;
- install command/ref validation;
- bundle-size and Web Vitals budgets.

Deployment promotion requires:

- reviewed content diff;
- immutable Hypervisor release ref;
- Network source allowlist;
- Faucet mutation disabled or fully configured;
- dependency health check;
- rollback artifact;
- post-deploy smoke test.

## 15. Definition of done per route

A route is done only when it has:

- final approved purpose and copy intent from `WEB-0001`;
- responsive dark/light rendering;
- loading, empty, error, stale, and partial states where applicable;
- keyboard and screen-reader behavior;
- route metadata and canonical URL;
- analytics events without sensitive payloads;
- unit/contract coverage;
- at least one end-to-end happy path;
- source/provenance for factual claims;
- no placeholders presented as real links, metrics, or supported platforms.

## 16. Initial implementation tickets

1. ~~Scaffold `web/website` and CI.~~ Complete in the current foundation.
2. ~~Implement design tokens, layout, themes, navigation, footer, and route metadata.~~ Complete.
3. ~~Add typed content system and Home.~~ Complete in the current content module.
4. ~~Add How It Works, Build, Agents, Research, and Docs entry.~~ Complete in the current route foundation.
5. ~~Add immutable release adapter, Run a Node, and Download.~~ Foundation complete; verified release feed remains open.
6. Define and test Website Network schemas.
7. Implement Network indexer storage and ingestion.
8. Implement Network summary and status pages.
9. Implement read-only Explorer and Endpoint details.
10. Implement server-only Faucet adapter.
11. Implement Wallet proof and Faucet state machine.
12. Add abuse controls, security tests, and Faucet E2E.
13. Complete accessibility, performance, SEO, content, and degradation gates.

Tickets 1–5 may proceed while the Network Indexer and public Faucet deployment are being prepared. Tickets 8–12 cannot be marked complete with hardcoded fixtures in production code.

## 17. Required external inputs

Implementation can use explicit placeholders in development for:

- brand assets;
- canonical production domain;
- public Network source allowlist;
- final release feed/signature location;
- Faucet public deployment and server credential;
- CAPTCHA or alternative abuse-control provider;
- analytics destination;
- privacy and terms URLs.

Each placeholder must be represented by typed configuration and a launch blocker, not by a hidden TODO in a component.
