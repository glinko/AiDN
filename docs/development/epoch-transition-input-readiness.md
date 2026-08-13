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

The ABCI source can currently expose the closing chain state. It deliberately
does not infer the following from unrelated data:

- closing/opening epoch boundary;
- epoch task result root;
- participant eligibility snapshot root;
- deterministic reward calculation root;
- approved next-protocol-parameters hash;
- pool budgets and their ECO-0007 source references.

These values must be produced by the live Epoch Engine from finalized evidence
and governance-approved parameters. A local UI balance, a wallet operation or
the legacy floating-point reward simulator is not an acceptable substitute.

## Next implementation slice

The next slice can make the report `READY` only after adding canonical,
consensus-bound sources for:

1. epoch boundary and active parameter version;
2. frozen evidence and task-result commitments;
3. participant/service eligibility snapshot;
4. ECO-0007 reward calculation and integer pool budgets;
5. the approved next protocol parameter hash.

Only then should `prepare-authorized-epoch-transition.py` consume the report
instead of a manually authored payload.
