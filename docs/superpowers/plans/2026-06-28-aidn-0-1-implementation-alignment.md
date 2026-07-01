# AiDN_0.1 Implementation Alignment Audit

Status: `Draft`

Last updated: `2026-06-28`

## Goal

Document how the implementation currently published in `glinko/AiDN_0.1` aligns
with the newer documentation that now lives in `glinko/AiDN`.

This note is meant to answer one practical question:

`What can we lift directly from AiDN_0.1, and what remains only documented in AiDN?`

## Repository Baseline

At the time of this audit:

- `AiDN` HEAD is `a4b36ec`, which is a docs-only continuation on top of the
  implementation merge commit `4203298`;
- `AiDN_0.1` HEAD is `4203298`.

That means:

- `AiDN_0.1` is the implementation baseline;
- `AiDN` is the newer documentation baseline;
- `src/` and `tests/` are effectively the same codebase between the two repos
  at this point;
- the meaningful delta currently lives in `AiDN/docs/`.

## What Can Be Reused Directly From AiDN_0.1

These areas are already implemented and match the documented architecture well
enough to reuse as-is:

- local hypervisor runtime foundation:
  - `queue.py`
  - `resources.py`
  - `scheduler.py`
  - `process_manager.py`
  - `service.py`
- bundle and plugin model:
  - `domain/models.py`
  - `plugins/base.py`
  - `plugins/registry.py`
  - `plugins/ollama.py`
  - `plugins/llamacpp.py`
  - `plugins/whisper.py`
- node discovery and registry layer:
  - `registry_models.py`
  - `registry_service.py`
  - `registry_api.py`
- wallet and pricing foundation:
  - `wallet.py`
  - `wallet_models.py`
- persistence and snapshot layer:
  - `state.py`
  - `persistence.py`
  - `bundle_registry.py`
  - `model_store.py`
- operator API and dashboard shell:
  - `api.py`
  - `dashboard.py`
  - `static/operator_dashboard.html`
- regression coverage:
  - `tests/test_service.py`
  - `tests/test_api.py`
  - `tests/test_wallet.py`
  - `tests/test_registry_service.py`
  - `tests/test_registry_api.py`

## What AiDN_0.1 Already Covers Relative To The Current Docs

`AiDN_0.1` already implements the documented slices up through the
pre-hardening M3 baseline:

- M1 local hypervisor MVP;
- M2 centralized registry and discovery;
- operator dashboard terminal redesign;
- requests workspace with spillover preview policy;
- wallet usage recording and export;
- allocation activation export;
- grace-window allocation settlement;
- settlement reopen;
- dispute open/resolve workflow;
- dispute export stream;
- strict-accounting blocked settlement markers.

## What Is Documented In AiDN But Not Implemented In AiDN_0.1

The newer `AiDN` docs add settlement lifecycle hardening beyond the
`grace / reopen / dispute / closed` model. That slice is not present in
`AiDN_0.1`.

Missing relative to:

- `docs/superpowers/specs/2026-06-21-m3-settlement-lifecycle-hardening-design.md`
- `docs/superpowers/plans/2026-06-21-m3-settlement-lifecycle-hardening.md`

Not yet implemented in `AiDN_0.1`:

- explicit settlement `hold` state;
- operator hold and release endpoints for settlement events;
- append-only correction journal;
- replay-safe correction export stream;
- `base_usage_total_q` versus `effective_usage_total_q`;
- `correction_count`;
- strict-accounting auto-hold behavior on settlement events;
- dispute-aware release guards for held events;
- richer reconciliation rules that preserve immutable usage history while
  changing settlement-facing totals.

## Practical Conclusion

Yes, we can reuse `AiDN_0.1`, but only as the implementation substrate.

The correct framing is:

- do **not** treat `AiDN_0.1` as newer than the `AiDN` docs;
- do treat `AiDN_0.1` as the last working code snapshot that already satisfies
  the older roadmap checkpoints;
- implement new work against `AiDN` documentation by applying focused deltas on
  top of the `AiDN_0.1` baseline.

## Recommended Application Strategy

### Phase 1: Adopt AiDN_0.1 As The Execution Baseline

Use `AiDN_0.1` as the starting codebase for:

- runtime orchestration;
- provider lifecycle;
- discovery and registry APIs;
- dashboard shell;
- wallet/export primitives.

### Phase 2: Port The Doc-Only Delta From AiDN Into Code

Implement, in order:

1. settlement hold/release/correction lifecycle from the `2026-06-21` spec;
2. state snapshot support for correction history;
3. correction export and API coverage;
4. roadmap/doc sync after each landed slice.

### Phase 3: Resume Forward Work From The New Docs

Once the hardening slice is landed, continue with the next documented gaps:

1. non-token pricing policy for `whisper`-class workloads;
2. runtime enforcement boundary for `usage_contract`;
3. rating publication contract;
4. custom model onboarding publication.

## Non-Recommendation

Do not copy code blindly from `AiDN_0.1` into `AiDN` file-by-file while
assuming it satisfies the latest docs. It does not.

The safe path is:

- keep `AiDN` docs as the source of truth;
- use `AiDN_0.1` as the implementation baseline;
- land only the missing deltas required by the newer spec set.
