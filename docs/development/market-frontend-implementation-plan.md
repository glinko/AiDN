# Market Frontend Implementation Plan

Status: Planned

This document defines the frontend implementation plan for the AiDN Hypervisor
`Market` workspace. It is intentionally separate from the protocol and backend
implementation. The React work SHALL begin only after the backend read-model
and mutation contracts listed below are stable.

Related specifications:

- [UI-0001 Hypervisor Dashboard Specification](../product/UI-0001-hypervisor-dashboard-specification.md)
- [UI-0002 Hypervisor Dashboard Screen and Action Map](../product/UI-0002-hypervisor-dashboard-screen-and-action-map.md)
- [UX-0001 Hypervisor Operator Journey](../product/UX-0001-hypervisor-operator-journey.md)
- [UX-0002 Endpoint Session and Payment Flow](../product/UX-0002-endpoint-session-and-payment-flow.md)

## 1. Scope

`Market` is the operator workspace for discovering and evaluating public
Endpoint offers. It is not a second Providers page, a second Endpoints page, or
the canonical home for attached remote routes.

The ownership boundary is:

```text
Market       -> discover and evaluate public offers
Network      -> inspect nodes, peers, discovery and attached capacity
Remote       -> manage attached remote routes and dependencies
Endpoints    -> create, configure, publish and revoke local offers
Validation   -> request and inspect Endpoint validation
Providers    -> inspect local Provider execution topology
Bundles      -> manage immutable local execution revisions
Wallet       -> manage operator and consumer funding
```

The primary Market flow is:

```text
Discover offer
    -> inspect terms and evidence
    -> attach verified remote Endpoint
    -> stage local Proxy Endpoint draft
    -> review local economics and policy
    -> publish separately in Endpoints
```

Attaching an offer SHALL NOT publish a local Endpoint automatically.

## 2. Backend Preconditions

The frontend implementation is blocked until the following contracts are
available and tested.

### 2.1 Market read-model

`GET /operators/dashboard/market` SHALL return a versioned, backward-compatible
payload containing:

```yaml
schema_version: string
generated_at: timestamp
last_successful_refresh_at: timestamp|null
freshness:
  state: fresh|stale|unknown
  age_seconds: number|null
  source: registry|local|mixed|unknown
query: object
nodes: []
candidates: []
canonical_candidates: []
canonical_summary: object
recommended_action: object|null
```

The payload SHALL distinguish legacy candidates from canonical offers. The
frontend SHALL not infer a canonical offer merely because a legacy candidate is
reachable.

### 2.2 Offer fields

Each candidate SHOULD expose the following fields. Missing values remain
missing and are rendered as `Not reported`, never as zero or verified.

```yaml
offer_id: string|null
advertisement_id: string|null
endpoint_id: string|null
node_id: string
operator_id: string|null
origin: local|external
resource_type: endpoint|registry_service|validation_service|consensus_service|unknown
service_id: string|null
capability_id: string|null
runtime_id: string|null
model_class: string|null
model_id: string|null
status: ready|stale|offline|unknown
visibility: public|shared|private|unknown
published_at: timestamp|null
last_seen_at: timestamp|null
supports_queue: boolean|null
supports_allocation: boolean|null
endpoint_ready: boolean|null
pricing: object
accounting: object
limits: object
reputation: object
trust_summary: object
publication_evidence: object
route_state: unattached|attached|proxy_draft|proxy_published|blocked|unknown
```

### 2.3 Trust and evidence fields

Trust SHALL be represented as separate dimensions:

- publication state;
- publication/configuration synchronization;
- Validation state;
- Certification state;
- evidence custody state;
- Reputation;
- source freshness.

The payload SHALL not collapse these dimensions into one boolean `verified`.
For example, a reachable Endpoint with no Validation evidence is not a
verified Endpoint.

### 2.4 Mutation contracts

The following existing or planned operations must return typed result objects,
not empty `204` responses:

| Operation | Endpoint | Required result |
| --- | --- | --- |
| Attach remote Endpoint | `POST /operators/remote-endpoints/attach` | remote route ID, source identity, route state, warnings |
| Detach remote Endpoint | Remote/Network API | route state, dependency blockers, released resources |
| Stage Proxy Endpoint | Endpoint API | draft ID, source route ID, draft hash, readiness |
| Start Consumer Session | Session API | Session ID, accepted terms hash, deposit state |
| Prefer offer | Market/route API | preference ID, effective scope, expiry/version |

An operation response SHALL include a stable error code and an actionable
operator message when rejected.

## 3. Page Structure

### 3.1 Header

The page header displays:

- `Market` title and operator-facing description;
- current discovery source;
- last successful refresh time;
- freshness state;
- visible node count;
- visible offer count.

Header actions:

- `Refresh catalogue`;
- `Network status`;
- `Local Endpoints`;
- `Clear filters` when filters are active.

Refresh SHALL display progress, completion time and partial failure details. A
refresh that only repaints the page without a visible result is invalid.

### 3.2 Summary metrics

The workspace SHALL provide compact, clickable metrics:

- visible nodes;
- canonical offers;
- external offers;
- local offers;
- ready offers;
- stale/offline offers;
- attached routes;
- verified/certified offers.

Clicking a metric applies the corresponding filter or navigates to the owning
workspace. Metrics SHALL not display data that is unavailable from the
read-model.

### 3.3 Filter toolbar

The toolbar SHALL support:

- free-text search;
- origin: `All`, `Local`, `External`;
- availability: `All`, `Ready`, `Stale`, `Offline`, `Unknown`;
- service kind;
- capability;
- Validation/Certification state;
- Reputation tier or score range;
- Accounting Mode;
- route state: unattached, attached, proxy draft, proxy published;
- visibility;
- price range;
- source node.

Filtering is local to the loaded read-model. It must preserve the unfiltered
result count and show `Showing N of M offers`.

Search SHALL cover at least:

- display name;
- Endpoint ID;
- Advertisement ID;
- node and operator IDs;
- capability and service IDs;
- model class/model ID;
- legacy Bundle ID where present.

### 3.4 Offer list

Desktop uses a dense table. Mobile uses vertically stacked offer cards. The
desktop list SHALL expose:

- offer identity and origin;
- source node and freshness;
- capability/service/model;
- availability;
- economics;
- trust evidence;
- route state;
- primary action.

The list SHALL be sortable by availability, price, Reputation, freshness and
capability. Sorting SHALL be deterministic and stable for equal values.

## 4. Offer Inspector

Selecting an offer opens a right-side inspector on desktop and a bottom sheet
on mobile. The inspector is read-only except for explicitly labelled actions.

### 4.1 Identity section

Display:

- Advertisement ID;
- Endpoint ID;
- offer ID;
- node ID;
- operator ID;
- origin;
- resource type;
- visibility;
- Registry source;
- publication timestamp;
- last-seen timestamp;
- configuration/content hash when public.

IDs SHALL be copyable. The inspector SHALL never display private Provider
configuration or credentials.

### 4.2 Service section

Display:

- service ID;
- capability ID;
- model class;
- public runtime class;
- declared limits;
- queue/allocation support;
- custom-model policy;
- public resource information.

Provider topology remains hidden unless explicitly part of the public
Advertisement.

### 4.3 Economics section

Display:

- Accounting Mode;
- fixed price or variable dimensions;
- input/output price where available;
- minimum deposit;
- maximum Session charge;
- timeout policy;
- Network Fee treatment;
- pricing source;
- metering/reproducibility limits.

The UI SHALL explicitly state:

```text
Displayed economics come from the published Endpoint advertisement.
They are not inferred from local Provider costs.
```

### 4.4 Trust section

Display each trust dimension separately:

- publication status;
- configuration synchronization;
- Validation status;
- Certification status;
- evidence root/reference;
- custody status;
- Reputation score/tier;
- last update;
- unresolved warnings.

Examples:

```text
Published / In sync / Certified
Published / Configuration drifted / Validation pending
Reachable / Not validated
Stale publication / Evidence unavailable
```

### 4.5 Route section

Display:

- attached/unattached state;
- local remote route ID;
- local alias;
- routing mode;
- upstream dependency;
- proxy draft state;
- proxy publication state;
- detach/publish blockers.

## 5. Operator Actions

### 5.1 Inspect offer

Opens the inspector and changes no state.

### 5.2 Refresh catalogue

Runs Market and Remote Endpoint read-model refresh, then reports:

- success or failure;
- refresh timestamp;
- updated source count;
- partial failures;
- stale-data fallback.

### 5.3 Attach remote Endpoint

The action is available only for an external offer with a valid Endpoint ID and
policy-compliant publication evidence. It SHALL be blocked for stale, offline,
unverified or conflicting offers when the active policy requires stronger
evidence.

Before submission, show:

```text
Attach remote Endpoint?

Source node: <node>
Endpoint: <endpoint>
Routing mode: preferred
The local Hypervisor will retain a dependency on this remote source.
```

After submission, show the returned route ID and provide actions to open the
route or stage a Proxy Endpoint draft.

### 5.4 Stage Proxy Endpoint

This action continues into `Endpoints` with a prefilled draft containing:

- source node;
- remote Endpoint;
- routing mode;
- local display name;
- local accounting mode;
- local price;
- consumer-facing limits;
- visibility;
- Validation policy.

Staging SHALL not publish the Endpoint.

### 5.5 Open local offer

For a local offer, navigate to `Endpoints` with the exact `endpoint_id` selected.
Opening a generic Endpoint list without preserving selection is insufficient.

### 5.6 Compare offers

The operator MAY select two or more offers and compare:

- capability/service;
- availability/freshness;
- price/accounting mode;
- deposit and Session limits;
- Reputation;
- Validation/Certification;
- route state;
- source node.

Comparison is read-only.

### 5.7 Open Network or Validation

Navigation SHALL preserve the selected node, offer ID and Endpoint ID as route
context. If no Validation evidence exists, the UI must say so rather than
presenting a request action unsupported by the backend.

### 5.8 Start Consumer Session

This is a separate future flow. It SHALL show and confirm:

- accepted Endpoint terms;
- Accounting Contract;
- deposit;
- maximum charge;
- timeout;
- refund policy;
- Network Fees;
- Consumer Wallet;
- signature/approval requirement.

The flow is:

```text
Review terms -> Sign request -> Lock deposit -> Open Session
```

### 5.9 Prefer/bookmark offer

This is API-dependent. It may store a local routing preference, but must not
republish, reprice or increase trust for the remote offer.

## 6. Action Ownership Rules

The following actions SHALL remain outside Market:

| Action | Canonical workspace |
| --- | --- |
| Detach remote route | Network/Remote Endpoints |
| Configure Proxy Endpoint | Endpoints |
| Publish or revoke local Endpoint | Endpoints |
| Request Validation | Validation |
| Inspect Provider internals | Providers |
| Create Bundle | Bundles |
| Configure Wallet | Wallet |
| Configure agent access | Settings |

Market may link to these workspaces with the selected object context.

## 7. State and Error Handling

### Offer states

```text
Local published
External ready
External attached
Stale
Unverified
Drifted
Offline
```

State rules:

- `Ready` means current availability evidence exists, not that quality is
  guaranteed.
- `Stale` and `Offline` are inspect-only until fresh evidence is available.
- `Unverified` cannot be attached when the active policy requires verified
  publication.
- `Drifted` requires inspection of the publication evidence.
- `Attached` exposes route actions, not a second attach operation.

### Empty states

No offers:

```text
No market offers discovered.
Publish a local Endpoint or restore Registry replication to populate the catalogue.
```

No external offers:

```text
No external capacity is currently visible.
Your local published Endpoints are still available.
```

Buttons should link to `Refresh`, `Network`, `Endpoints`, or `Market` as
appropriate.

### Failure states

The page SHALL preserve the last successful catalogue when refresh fails and
show:

- stale banner;
- failed source;
- error code;
- retry action;
- next safe action.

Attach failures SHALL keep the selected offer open and show the backend error
code, human-readable reason and owning workspace.

## 8. Mobile Layout

Mobile order:

1. Summary metrics.
2. Search.
3. Filter drawer or horizontal filter strip.
4. Offer cards.
5. Inspector bottom sheet.

The primary action remains visible at the bottom of the inspector. Secondary
actions move into `More`. The offer card must show at least:

```text
Offer name
Capability/model
Source node
Availability
Price
Trust
Route
Primary action
```

The basic attach/inspect decision SHALL not require horizontal table scrolling.

## 9. React Components

The planned component tree is:

```text
MarketWorkspace
├── MarketHeader
├── MarketFreshnessBanner
├── MarketSummaryGrid
├── MarketFilterBar
├── MarketOfferTable
│   └── MarketOfferRow
├── MarketOfferCard
├── MarketOfferInspector
│   ├── OfferIdentityPanel
│   ├── OfferServicePanel
│   ├── OfferEconomicsPanel
│   ├── OfferTrustPanel
│   └── OfferRoutePanel
├── MarketComparePanel
└── MarketEmpty/ErrorState
```

The component layer SHALL consume typed `MarketDashboard` data and SHALL not
reconstruct protocol state from unrelated endpoints.

## 10. Client State

TanStack Query owns server state:

- Market read-model;
- Remote Endpoint read-model;
- Network/readiness context where needed.

Local UI state owns only:

- search query;
- filters and sort;
- selected offer IDs;
- inspector open state;
- comparison selection;
- current mutation progress;
- operation notice.

After a successful mutation, invalidate/refetch Market and Remote Endpoint
queries. Do not optimistically mark a route attached before the backend result
is accepted.

## 11. Acceptance Criteria

The Market frontend slice is complete when:

- all visible fields come from the versioned Market/Remote read-model;
- missing values are visible as unknown/not reported rather than guessed;
- search, filters and sorting work on desktop and mobile;
- clicking an offer opens an inspector with exact object identity;
- trust dimensions are displayed separately;
- Refresh shows progress, completion or partial failure;
- Attach has a confirmation step, real result and actionable errors;
- attached offers cannot be attached a second time;
- Stage Proxy Endpoint preserves source context and does not publish;
- local offers open the exact Endpoint;
- Network/Validation navigation preserves selected object context;
- comparison is read-only and deterministic;
- no Market action duplicates ownership of Network, Endpoints, Providers,
  Bundles, Validation or Wallet;
- keyboard focus, mobile scrolling, empty states and stale-data states are
  covered by UI tests;
- backend mutation errors are rendered with stable codes and clear next steps.

## 12. Deferred Features

The following remain deferred until their backend contracts are complete:

- local offer bookmarking/preference persistence;
- Consumer Session start from Market;
- multi-offer route planning;
- automatic proxy pricing recommendations;
- market-wide reputation sorting based on non-finalized evidence;
- cross-node negotiation or reservation;
- decentralized offer ranking.

The frontend SHALL not simulate these capabilities with local-only state.
