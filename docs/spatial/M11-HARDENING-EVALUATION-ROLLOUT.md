# M11 Hardening, Evaluation and Controlled Operator Preview

Status: implementation slice complete in the frontend contract boundary; the
Node adapters remain the authority for persistence, authorization and release
sign-off.

M11 closes the gap between a working Spatial surface and an operator preview
that can be safely disabled. The browser may render, measure and explain a
decision, but it cannot mint capability, settle a resource, or erase evidence.

## Implemented boundary

| Concern | Source of truth | Browser implementation | Evidence |
| --- | --- | --- | --- |
| Authorization/audit | Node and Primary Agent grant | `src/spatial/hardening/authorization.ts` | capability matrix for browser/Agent/MCP/Hooks/Workspace/remote/recovery/resource/Share View; allow/deny/stale/scope/revocation and idempotent redacted audit tests |
| Reliability | canonical revisions and Node recovery | `src/spatial/hardening/reliability.ts` | 15 fault classes, visible recovery, Classic fallback, invariant gate |
| Accessibility | DOM semantics and operator AT settings | `src/spatial/hardening/accessibility.ts` | keyboard flow, focus/live-region/touch/contrast/motion checks |
| Localization | catalog and protocol terminology | `src/spatial/hardening/localization.ts` | EN/RU copy, pluralization, Q integer and timezone formatting |
| Performance | device profile budgets | `src/spatial/hardening/performance.ts` | LOW/MOBILE/DESKTOP/HIGH report and Classic fallback |
| Privacy | lifecycle and evidence references | `src/spatial/hardening/privacy.ts` | explicit archive/delete/redact, reference-only export, GC guard |
| Observability | deployment telemetry policy | `src/spatial/hardening/observability.ts` | bounded, content-free metrics with correlation IDs |
| Rollout | release gates and rollback | `src/spatial/hardening/rollout.ts` | ordered stages, sign-off gates, reversible rollback |

The additive records use the stable IDs `spatial.authorization-decision.v1`,
`spatial.audit-record.v1`, `spatial.reliability-incident.v1`,
`spatial.privacy-record.v1`, `spatial.performance-report.v1`,
`spatial.observability-metric.v1`, and `spatial.rollout-stage.v1`. They are
kept in a separate hardening registry so the original M2 contract enumeration
remains compatible.

## Release gates

An operator preview is not considered ready until all of these are evidenced:

1. `SpatialAuthorizationService` denies scope mismatch, stale revisions,
   missing capabilities and propagated revocations; `SpatialAuditService`
   records actor, target, decision, result, revisions, idempotency and evidence
   refs.
2. The primary keyboard flow is operable with named DOM controls, visible
   recovery, bounded live announcements, forced-colors/reduced-motion paths and
   44px touch targets.
3. The selected device profile has a passing performance report; the current
   bundle report is 259.3 KiB gzip Classic initial JS and 363.1 KiB gzip Spatial
   lazy JS. A failed or
   unsupported profile returns to Classic without losing Node/Workspace
   control.
4. Reliability incidents cannot become green until every invariant passes;
   renderer recovery rebuilds from canonical state and never duplicates an
   action or charge.
5. Privacy export contains only canonical references, revisions, lifecycle and
   evidence references. Transcript/diagnostic redaction removes credential
   patterns, and presentation garbage collection cannot remove evidence.
6. Telemetry contains no prompts, tokens, private text or secrets; dimensions
   and cardinality are bounded and the scenario can be correlated without
   content.
7. Rollout has an explicit rollback stage, reversible/rebuildable migration,
   atomic generated-asset activation, and security/reliability/accessibility/
   performance sign-off before `DEFAULT_ON`.

## Rollout stages

`DEVELOPER → LOCAL_FIXTURE → TEST_NODE → LAN_NODES → OPT_IN_PREVIEW →
DEFAULT_ON` is the only forward path. Any gate failure returns `CLASSIC`; a
rollback writes `ROLLED_BACK`, disables `spatial_operator_preview_enabled`,
retains canonical data, and leaves the generated dashboard directory untouched.

## M11.10 Classic migration decision

Classic remains the Advanced/Recovery surface until a separate review confirms
component sharing, direct-control parity, accessibility parity, support playbook
coverage, and rollback evidence. No legacy page or generated asset is removed
as part of M11. One canonical API/control path is required after any future
replacement.
