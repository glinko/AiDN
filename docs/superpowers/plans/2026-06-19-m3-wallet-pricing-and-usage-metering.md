# M3 Wallet Pricing And Usage Metering Plan

Status: `In progress`

Last updated: `2026-06-20`

## Goal

Add the first wallet-facing pricing and usage contract so AiDN can express cost in `q`, calculate price estimates, and publish structured usage events that a later settlement layer can consume.

## What Is Already Implemented In This Branch

- node pricing is published in registry advertisements and discovery responses;
- wallet quote calculation exists for `input`, `output`, and optional `fixed_request` charges;
- operator API can estimate usage cost in `q`;
- operator API can record structured usage events;
- automatic task-side metering works when provider results publish `usage` details and task constraints include `wallet_owner_id`;
- provider `usage` payloads now carry validated `measurement_kind` (`exact` or `estimated`) and `measurement_source`;
- invalid provider `usage` payloads are skipped with a `wallet.usage_skipped` journal event instead of failing the task;
- usage events can carry `task_id` and `allocation_id` for lease-aware attribution;
- automatic metering can derive `owner_id` from the referenced allocation lease when `wallet_owner_id` is absent from task constraints;
- task submission now binds `allocation_id` to the active lease bundle at routing time and rejects inactive allocations before execution starts;
- allocation activation now emits a wallet-facing journal hook with lease metadata for both direct allocation creation and pending-allocation promotion;
- allocation activation events are now exported through a dedicated replay-safe wallet stream using the same cursor envelope as usage and settlement exports;
- allocation `release` and `expire` now emit wallet allocation finalization events with aggregated `usage_total_q` snapshots for settlement consumers;
- wallet allocation finalization events now enter `grace` first and become `closed` only after a configurable grace period;
- closed wallet allocation finalization events can now be reopened manually, attaching dispute metadata and restarting the grace window for late settlement corrections;
- allocation finalization events now expose a dispute overlay, and dispute open/resolve transitions are exported through a dedicated replay-safe dispute stream without expanding the base `grace/closed` settlement enum;
- real `ollama`, `llama.cpp`, and `whisper` adapters now publish normalized provider `usage` payloads with explicit measurement metadata;
- provider adapters now expose a declarative `usage_contract` through plugin descriptions, including exact/estimated support and fallback policy;
- provider adapters can now opt into `missing_usage_behavior=strict_accounting`, keeping tasks completed while marking results `unbillable` and settlement-blocked when usage is missing or invalid;
- wallet usage events now expose monotonic `sequence_id` ordering for replay-safe consumers;
- wallet usage export supports both compatibility `after_event_id` cursors and preferred `after_sequence` cursors;
- wallet usage export returns retention window metadata and marks stale cursors when consumers fall behind pruned history;
- wallet allocation finalization events are exported through a parallel replay-safe settlement stream;
- usage events are persisted through hypervisor state snapshot and restore.

## Remaining Work In M3

### 1. Automatic Usage Metering And Allocation Closure

- decide whether adapter-declared `usage_contract` should become an enforced runtime capability gate for production bundles.
- decide whether zero-grace nodes should remain audit-only on reopen or accepted dispute, or grow a separate late-adjustment window later.

### 2. Settlement Export Boundary

- define whether export needs signed batches or digest checkpoints before M4/M6.

### 3. Pricing Policy Hardening

- document rounding rules for fractional `q`;
- define whether fixed charges apply per request, per allocation, or per runtime startup;
- decide whether non-token workloads need parallel units now or later.

### 4. Network Integration

- expose wallet-ready usage signals where registry or routers can consume them later;
- keep pricing and usage contracts aligned with future rating and dispute workflows.

## Current Policy Defaults

### Strict Accounting Defaults

- `strict_accounting` should be the default for billable token-based inference adapters that already expose provider-backed token usage, currently `ollama` and `llama.cpp`;
- soft skip should remain the default for non-token or estimate-only workloads until AiDN defines a first-class non-token pricing unit, currently `whisper` and test/fake adapters;
- a `strict_accounting` task stays `completed`, but its result becomes `unbillable` and settlement-blocked when provider usage is missing or invalid;
- settlement consumers should treat `wallet_accounting.status=unbillable` as a hard stop for automatic settlement, even if the runtime result itself succeeded.

### Retention And Stale Cursor Recovery

- current default retention is unbounded in-memory history for wallet usage when `wallet_usage_retention_limit` is unset;
- when `wallet_usage_retention_limit` is set, pruning keeps only the newest `N` usage events and advances the retained floor exposed as `retained_from_sequence`;
- allocation finalization, activation, and dispute streams currently reuse the same cursor envelope but do not yet apply a parallel retention limit;
- settlement consumers should checkpoint `next_after_sequence` after every successful export page;
- if an export page returns `cursor_status=stale`, consumers should treat the returned page as the new retained floor, reconcile any historical gap out of band, and continue from the returned `next_after_sequence`.

### Zero-Grace And Dispute Semantics

- on non-zero-grace nodes, `accepted` dispute resolution reopens the allocation event into a fresh grace window and increments `reopen_count`;
- on zero-grace nodes, `reopen` and `accepted` dispute resolution remain audit-only actions: the event stays `closed`, `closed_at` is refreshed, and no grace window is recreated;
- `rejected` and `withdrawn` dispute outcomes always force the event back to `closed`;
- open disputes freeze automatic grace-to-closed advancement until an operator resolves them.

## Current Deliverables

- [x] `q per 1kk tokens` quote contract
- [x] operator wallet quote endpoint
- [x] operator usage event recording endpoint
- [x] usage event persistence in local state
- [x] automatic metering hook from runtime execution result metadata
- [x] validated measurement contract for provider-reported usage
- [x] provider-facing usage contract in real adapters
- [x] settlement-facing usage export contract
- [x] replay-safe export cursor and retention metadata
- [x] wallet-facing allocation activation journal hook
- [x] wallet-facing allocation activation export stream
- [x] manual reopen/dispute path for closed allocation settlement events
- [x] longer-lived dispute workflow and replay-safe dispute export stream
- [x] declarative provider usage contract in plugin descriptions
- [x] hybrid provider usage policy with default soft skip and opt-in `strict_accounting`
- [x] documented settlement-consumer policy defaults for retention, stale cursors, and zero-grace dispute handling
- [ ] policy for non-token workloads

## Next Implementation Slice

Recommended next slice:

1. decide whether adapter-declared `usage_contract` should become an enforced runtime capability gate for production bundles;
2. define the first non-token pricing unit and policy for `whisper`-class workloads;
3. expose wallet-ready accounting signals where registry or routers can consume them later.
