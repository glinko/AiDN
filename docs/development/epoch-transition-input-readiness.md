# Epoch Transition Input Readiness

This document defines the read-only preflight surface used before the first
canonical `EPOCH_TRANSITION` for ECO-0007.

## Why this exists

An epoch transition is not an operator-authored budget JSON. RFC-0048 requires
the transition to commit finalized epoch evidence, eligibility, reward
calculation and approved next parameters. Until those sources exist, the
network must fail closed and explain the missing inputs.

The ABCI application exposes:

```text
epoch/transition-inputs
```

The response is a hash-bound `aidn.epoch-transition-inputs.v1` report with:

- the current finalized height, block hash, state root and AppHash when they
  are observable;
- the Epoch Engine roots and pool budget references when they are available;
- `READY` or `BLOCKED` status;
- an exact `missing_inputs` list;
- a deterministic `report_hash` for cross-validator comparison.

The report is derived from canonical state. It is not a Ledger operation and
cannot modify AppHash or unlock the development pool.

## Quorum preflight

Query all validators from an operator or evidence host:

```text
uv run python tools/query-epoch-transition-inputs.py \\
  --rpc-url http://192.168.88.128:26657 \\
  --rpc-url http://192.168.88.129:26657 \\
  --rpc-url http://192.168.88.130:26657
```

The command is a fail-closed quorum gate, not a single-RPC health check. For a
`READY` report it also queries, on every validator:

- `operation/finalized/<epoch_result_manifest_operation_id>`;
- `epoch/result-manifest/<closing_epoch>`.

These queries prove that the manifest operation is finalized and that its
public projection matches the transition report's historical closing height,
block hash, state root, source AppHash, schedule and manifest hash. The gate
counts only one identical report/reference pair on one chain and excludes
catching-up validators. Exit code `0` means that this complete evidence reached
the requested quorum. Exit code `2` is expected while the Epoch Engine has not
published or finalized all artifacts; it is a release gate, not a transient
RPC failure.

## Current implementation boundary

The ABCI source can currently expose the closing chain state. When an
explicit `AIDN_EPOCH_*` schedule is configured, it also reports whether the
canonical last block time has reached the active epoch boundary:

- `AIDN_EPOCH_START_TIME` anchors the genesis epoch;
- `AIDN_EPOCH_DURATION_SECONDS` defines the versioned duration;
- `AIDN_EPOCH_PARAMETER_VERSION`, `AIDN_EPOCH_TASK_SET_VERSION` and
  `AIDN_EPOCH_PROTOCOL_VERSION` bind the schedule metadata.

The schedule is included in durable ABCI snapshots and is hash-bound. It does
not by itself authorize a transition or create an emission budget. For a
validator deployment, the same schedule hash must be installed on every
validator. A mismatch fails closed; the nodes must not choose a majority
schedule. The last CometBFT block timestamp is the only accepted time source;
host wall clocks are not used to close an epoch.

The Epoch Engine now publishes these inputs through an immutable,
consensus-bound `EPOCH_RESULT_MANIFEST_COMMIT`. The manifest is an
evidence-only object: it does not mint Q, spend a pool, activate parameters or
replace protocol-authority signatures. It aggregates the exact RFC-0048 roots
and ECO-0007 pool budget references consumed by a later transition.

New manifests use `aidn.epoch-result-manifest.v2`, which adds historical
closing block, state-root and source-AppHash commitments. Nodes can replay the
older `v1` schema for state compatibility, but the quorum gate keeps a v1
manifest blocked because it cannot prove the historical closing chain state.

The ABCI query `epoch/result-manifest/<epoch>` is deliberately a public
identity projection. It contains operation identity, finality reference,
manifest hash and historical closing-chain fields, but not the manifest
payload or signatures. Full evidence remains behind the normal consensus and
operator evidence paths.

The following remain unavailable until a finalized manifest for the closing
Epoch exists:

- epoch result manifest;
- epoch task result root and participant/service eligibility snapshot roots;
- deterministic reward calculation root;
- approved next-protocol-parameters hash;
- pool budgets and their ECO-0007 source references.

These values must be produced by the live Epoch Engine from finalized evidence
and governance-approved parameters. A local UI balance, a wallet operation or
the legacy floating-point reward simulator is not an acceptable substitute.
The manifest must be finalized before the dependent `EPOCH_TRANSITION` block;
same-block manifest-plus-transition construction is rejected.

## Quorum-bound transition artifact

The report can now feed the offline authority path directly. Use
`--quorum-report` with `prepare-authorized-epoch-transition.py` or
`build-authorized-epoch-transition.py`; do not copy roots into a separate
payload file. The resulting envelope carries:

- the exact typed transition payload from the `READY` report;
- the quorum schema version and `quorum_hash`;
- the finalized manifest `sequence_id` and `record_digest`;
- evidence references for the manifest operation and quorum report.

Independent signers and the signature combiner must receive the same report.
They reject a quorum-bound envelope without it or with a mismatching report.
This is still an offline evidence boundary: the receiving ABCI application
must independently find the manifest in its own finalized operation registry,
verify its hash and all historical bindings, and reject a same-block
manifest-plus-transition attempt.

## Next implementation slice

The next slice can make the report `READY` only after adding canonical,
consensus-bound sources for:

1. epoch boundary and active parameter version;
2. frozen evidence and task-result commitments;
3. participant/service eligibility snapshot;
4. ECO-0007 reward calculation and integer pool budgets;
5. the approved next protocol parameter hash;
6. the finalized `EPOCH_RESULT_MANIFEST_COMMIT` and a subsequent
   authority-signed `EPOCH_TRANSITION`;
7. canonical consensus submission and multi-RPC finality evidence for the
   first live transition.

## Acceptance checks

The boundary slice is complete when:

- every validator returns the same `epoch_schedule_hash`;
- the report contains the same canonical block time and current state roots;
- the report changes from `epoch_boundary` blocked to a concrete
  `closing_epoch/opening_epoch` pair only at or after scheduled end;
- a durable restart restores the schedule and last block time;
- a schedule mismatch fails closed;
- a finalized manifest exposes the same roots, schedule bindings and pool
  budget references on every validator;
- `operation/finalized/<operation_id>` and
  `epoch/result-manifest/<closing_epoch>` agree on operation identity and
  historical closing-chain fields;
- the quorum gate blocks when the finalized manifest reference is missing,
  stale, conflicting or below the configured threshold;
- a transition referencing that manifest is accepted only in a later block;
- task, eligibility, reward and parameter roots are independently reproducible
  from the manifest's committed evidence.
