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

Exit code `0` means that an identical `READY` report reached quorum. Exit
code `2` is expected while the Epoch Engine has not published all artifacts;
it is a release gate, not a transient RPC failure.

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

## Next implementation slice

The next slice can make the report `READY` only after adding canonical,
consensus-bound sources for:

1. epoch boundary and active parameter version;
2. frozen evidence and task-result commitments;
3. participant/service eligibility snapshot;
4. ECO-0007 reward calculation and integer pool budgets;
5. the approved next protocol parameter hash;
6. the finalized `EPOCH_RESULT_MANIFEST_COMMIT` and a subsequent
   authority-signed `EPOCH_TRANSITION`.

Only then should `prepare-authorized-epoch-transition.py` consume the report
instead of a manually authored payload.

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
- a transition referencing that manifest is accepted only in a later block;
- task, eligibility, reward and parameter roots are independently reproducible
  from the manifest's committed evidence.
