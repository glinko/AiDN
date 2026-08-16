---
version: 1
slug: "web-website-public"
primary_target: "web/website"
related_targets:
  - "web/website/src/App.tsx"
  - "web/website/src/api.ts"
  - "web/website/src/styles.css"
  - "web/website/index.html"
---

# Public Website (WEB-0001)

## Scope

`web/website` is the shipped Vite/React public website surface. It explains
AiDN's local-first shared-compute model, gives visitors an observable network
entry point, and provides a small, bounded Faucet Web App. It is separate from
the node-local Hypervisor Operator Dashboard and must not become a second
operator console.

## Routes

- `/` is the product story: local-first compute, the use/share/build choices,
  network status, and a request topology map.
- `/how-it-works` is the Connect -> Deploy -> Publish -> Use sequence, including
  the explicit local-execution versus network-publication boundary.
- `/network` is the evidence surface: API-backed readiness metrics and a
  read-only Endpoint Explorer searchable by model, provider, and capability.
- `/run-a-node` is the reviewed Ubuntu install path, prerequisites, and the
  post-install Connect -> Provider -> Model -> Bundle -> Validate -> Publish
  sequence. The copied command is pinned to a reviewed ref.
- `/build` is the agent loop (discover -> compare -> execute -> verify) and the
  policy-bound MCP integration surface.
- `/docs` is the task-oriented documentation index, with links into operator,
  developer, and network paths plus the normative GitHub source.
- `/app/faucet` is the bounded Web App route for public Faucet status and the
  Wallet -> one-time challenge -> signed claim flow. The route parser also
  accepts the short aliases used by the app (`/how`, `/network`, `/explorer`,
  `/run`, and `/faucet`).

## User Jobs

Visitors should be able to:

- understand shared compute as a practical local-first network, then choose to
  use it, share a node, or build an agent on it;
- inspect only verified network evidence and discover an Endpoint by its model,
  capabilities, constraints, validation state, and price;
- follow a reviewed operator path from Ubuntu installation through a validated,
  publishable Endpoint;
- understand the agent/MCP control loop and its policy boundary;
- find the shortest documentation route for an operator, developer, or network
  question; and
- obtain testnet Q without exposing a private key, by proving Wallet control
  with a one-time signature.

## Direction

The thesis is **shared compute as a working network**, not an AI chat product,
token page, or decorative monitoring screen. Treat the surface as a **field
manual / network atlas**, position **6/7**, with seed **`411bfba4`**.

The world is a dark infrastructure field with a system light variant. Calm
cyan marks the current route and trusted next action; amber marks attention,
unknown, unavailable, or preview state; machine facts and provenance use a
mono treatment; and the topology map makes the request path (caller -> local
compute -> AiDN network -> Endpoint) legible. Real evidence gets weight; no
fake charts or inferred telemetry should be added.

## Content and API Boundaries

Explanatory copy and route composition live in `src/App.tsx`; the browser data
adapter in `src/api.ts` is the only website data boundary. The browser calls
only the website-owned `/api/site/v1/*` namespace (default base
`/api/site/v1`); local Vite proxying may forward it to the configured Website
Backend via `AIDN_WEBSITE_BACKEND_URL`. It must not call arbitrary Hypervisors,
Faucet credentials, or private keys from the browser.

The current contract is:

- `GET /network/summary` returns readiness plus aggregate metrics. Each metric
  carries a value, source, and observation time; a missing value renders
  **Not reported**, never a guessed zero.
- `GET /network/endpoints` returns read-only Endpoint records (model, provider,
  capabilities, context, validation, availability, operator, latency, and
  price) for client-side filtering in the Explorer.
- `GET /faucet/status` returns eligibility, amount, policy, cooldown, pause, and
  low-balance state.
- `POST /faucet/challenges` accepts a Wallet ID and public key and issues the
  expiring signing challenge in the `aidn.faucet-wallet-proof.v1` domain.
- `POST /faucet/claims` accepts the request ID, Wallet identity, challenge ID,
  and Wallet signature. Idempotency, abuse protection, budget, cooldown, and
  transaction finality remain Website Backend concerns.

The install command is informational and copy-only; it does not execute on the
visitor's machine. `VITE_AIDN_INSTALL_REF` selects the immutable reviewed
operator bootstrap ref, and production installs must not point at `main`.

## Responsive and Accessibility Constraints

- Keep interactive controls at least **44px** high, including the compact
  masthead, mobile navigation, primary/quiet actions, copy controls, form
  controls, and footer links. Preserve visible `:focus-visible` outlines.
- At a true CSS viewport of **390px**, the document must have no page-level
  horizontal overflow and the hero topology must not collide or clip its
  caller, local, network, and Endpoint nodes. Intentional wide data (the
  Endpoint table and path track) may scroll inside its own bounded region, not
  widen the page.
- The 980px and 740px responsive states collapse grids, expose the mobile
  navigation, and retain every route and action; do not hide the network
  evidence or Faucet steps on small screens.
- Keep status, validation, preview, and unavailable states explicit in text as
  well as color. Preserve semantic labels/roles for navigation, the Endpoint
  table, status/error regions, the topology illustration, and Faucet fields.
- Honor `prefers-reduced-motion`: route changes use an instant scroll and CSS
  animation/transition motion is effectively disabled.

## Demo-data Warning

`pnpm run dev:demo` (or `VITE_WEBSITE_DEMO=true`) supplies clearly labelled,
illustrative network, Endpoint, and Faucet fixtures. The preview ribbon and
`Illustrative preview` provenance are part of the contract. Demo values are
not live network state; the Faucet preview returns no network transaction. Do
not publish a demo build as a source of verified metrics. In live mode, API
errors remain visible and missing data stays **Not reported**.

## Open Next Steps

- Verify every canonical route and the Faucet three-step flow against a real
  Website Backend contract, including loading, unavailable, paused,
  low-balance, rejected, and pending-finality states.
- Run a true 390px CSS viewport audit (no page overflow, no topology-node or
  route-label collisions) and keyboard/screen-reader checks for navigation,
  table semantics, errors, and Faucet form progression.
- Confirm the production Website Backend base, CORS/proxy policy, and API
  schemas before enabling live metrics or claims; keep immutable install refs
  and the demo warning in release checks.
- Replace the temporary normative GitHub link and task-to-route placeholders
  with versioned docs once the public docs source is published.
