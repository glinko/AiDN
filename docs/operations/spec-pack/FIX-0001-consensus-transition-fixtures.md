# FIX-0001 — AiDN Consensus Transition Fixtures

Status: Draft  
Version: 0.1

## 1. Purpose

This document defines machine-verifiable deterministic fixtures for the AiDN state machine.

Fixtures are consensus test vectors, not examples.

A conforming implementation MUST consume the checked-in fixture set and produce exactly the expected:

- canonical bytes;
- operation ID;
- result code;
- post-state;
- state root;
- AppHash.

## 2. Repository layout

Recommended:

```text
fixtures/
├── manifest.json
├── genesis/
│   └── empty-state-v1.json
├── valid/
│   ├── development/
│   ├── session/
│   └── contribution/
├── invalid/
│   ├── predecessor/
│   ├── funds/
│   ├── state-transition/
│   └── encoding/
├── replay/
├── snapshot/
└── migration/
```

## 3. Fixture file format

Each fixture MUST contain:

```json
{
  "fixture_id": "development-carryover-001",
  "profile_id": "aidn-mainnet-candidate-1",
  "description": "...",
  "pre_height": 100,
  "pre_app_hash": "...",
  "pre_state": {},
  "operation": {},
  "expected": {
    "canonical_operation_hex": "...",
    "operation_id": "...",
    "result_code": "OK",
    "result_state": "FINALIZED",
    "post_state": {},
    "post_state_root": "...",
    "post_app_hash": "..."
  }
}
```

Invalid fixtures MUST include:

```json
"expected": {
  "result_code": "ERR_PREDECESSOR_MISMATCH",
  "state_unchanged": true,
  "post_app_hash": "<same deterministic commit outcome as defined by block fixture>"
}
```

## 4. Block fixtures

Operation fixtures verify transition semantics.

Block fixtures MUST verify ordered operation behavior:

```json
{
  "fixture_id": "block-development-epoch-101",
  "pre_height": 100,
  "operations": [
    "...",
    "...",
    "..."
  ],
  "expected_operation_results": [
    "OK",
    "OK",
    "IDEMPOTENT_REPLAY"
  ],
  "expected_post_height": 101,
  "expected_app_hash": "..."
}
```

## 5. Canonical encoding fixture

At least one fixture MUST freeze the exact canonical bytes for every operation schema/version.

Example normative input:

```json
{
  "actor_id": "wallet:q:alice",
  "network_id": "aidn-test-1",
  "nonce": "0000000000000001",
  "operation_type": "DEVELOPMENT_POOL_CARRYOVER",
  "operation_version": 1,
  "payload": {
    "amount_atoms": 250000000,
    "from_epoch": 100,
    "to_epoch": 101
  },
  "predecessor_id": "pool-state-100",
  "profile_id": "aidn-mainnet-candidate-1"
}
```

The checked-in fixture MUST contain exact expected UTF-8/hex bytes and hash.

The placeholder values in this prose document are NOT the fixture values. The generated fixture file is normative once committed.

## 5.1 Repository runner

The checked-in fixture manifest is verified and executed with:

```bash
uv run python tools/run-consensus-fixtures.py \
  --manifest fixtures/manifest.json \
  --strict
```

Strict mode requires an executable `execution` block, checks the manifest and
fixture hashes, binds every fixture to the manifest `profile_id`, validates
canonical operation bytes and IDs, and compares result codes and post-AppHash.

## 6. Required transition family: carryover

Required cases:

### CARRYOVER-001 — normal carryover

Pre-state:

```text
Epoch 100 development pool:
base allocation = 250 Q
paid = 120 Q
reserved = 30 Q
uncommitted = 100 Q
```

Operation:

```text
DEVELOPMENT_POOL_CARRYOVER
100 Q from epoch 100 → epoch 101
```

Expected:

```text
epoch 100 uncommitted = 0
epoch 100 carryover_out = 100 Q
epoch 101 carryover_in = 100 Q
pool conservation holds
```

### CARRYOVER-002 — amount exceeds uncommitted pool

Expected:

```text
ERR_INSUFFICIENT_FUNDS
state unchanged
```

### CARRYOVER-003 — duplicate replay

Same Operation ID.

Expected:

```text
IDEMPOTENT_REPLAY
no second transfer
```

### CARRYOVER-004 — wrong predecessor

Expected:

```text
ERR_PREDECESSOR_MISMATCH
```

## 7. Required transition family: bounty

### BOUNTY-001 — create

Expected state:

```text
BOUNTY_CREATED
```

### BOUNTY-002 — reserve

Expected:

```text
general available decreases
bounty reserve increases
total pool unchanged
```

### BOUNTY-003 — release after expiry/cancellation

Expected:

```text
bounty reserve decreases
general available increases
bounty = RELEASED
```

### BOUNTY-004 — release twice with new operation ID

Expected:

```text
ERR_INVALID_STATE_TRANSITION
```

### BOUNTY-005 — replay exact release

Expected:

```text
IDEMPOTENT_REPLAY
```

### BOUNTY-006 — reserve beyond available pool

Expected:

```text
ERR_INSUFFICIENT_RESERVE
```

## 8. Required transition family: reward cancellation

Scenario:

```text
Gross Reward = 100 Q
Immediate = 40 Q
Maturity Stage 1 = 30 Q
Maturity Stage 2 = 30 Q
```

Initial post-award state:

```text
Immediate paid = 40
Maturity reserve = 60
```

Operation:

```text
DEVELOPMENT_REWARD_CANCEL_UNVESTED
cancel remaining 60 Q
```

Expected:

```text
Immediate paid remains 40
Maturity reserve decreases by 60
Returned reward pool increases by 60
Reward state = CANCELLED_UNVESTED
Reward conservation holds
```

Invalid variant:

```text
attempt to cancel 70 Q
```

Expected:

```text
ERR_INSUFFICIENT_RESERVE
```

## 9. Required transition family: reward correction

Base reward:

```text
Gross = 100 Q
Role allocation:
Author 75%
Reviewer 15%
Design 5%
Testing 5%
```

Correction example:

```text
Reviewer allocation invalidated before maturity.
15 Q unpaid share is returned/reallocated according to active policy.
```

Fixture MUST explicitly define:

- predecessor reward ID;
- correction operation ID;
- old reward hash;
- new reward hash;
- exact bucket deltas;
- expected AppHash.

Required cases:

```text
CORRECTION-001 positive unpaid correction
CORRECTION-002 negative unpaid correction
CORRECTION-003 duplicate correction
CORRECTION-004 wrong predecessor reward
CORRECTION-005 correction causing negative reserve
```

## 10. Predecessor-chain fixtures

At least one object MUST be transitioned:

```text
v1 → v2 → v3
```

Then submit an operation against `v1`.

Expected:

```text
ERR_PREDECESSOR_MISMATCH
```

The fixture MUST prove that a stale signed operation cannot overwrite a newer state.

## 11. Operation ordering fixture

Given operations A and B touching the same object:

```text
A predecessor = v1
B predecessor = v2
```

Block order:

```text
A, B
```

MUST succeed.

Block order:

```text
B, A
```

MUST deterministically reject B first and produce the fixture-defined resulting state.

## 12. Insufficient-funds fixtures

Every operation that debits a pool/reserve MUST have:

```text
exact balance
one atom less than required
zero balance
maximum allowed value
```

coverage where semantically relevant.

## 13. Integer boundary fixtures

Required:

- zero;
- one atom;
- maximum profile-supported amount;
- overflow attempt;
- negative input encoding attempt.

Overflow or negative unsigned amount MUST reject before mutation.

## 14. JSON ambiguity fixtures

Fixtures MUST reject:

- duplicate keys;
- floats;
- `1.0` where integer required;
- leading-zero numeric encodings where parser permits them;
- unknown top-level field;
- missing required field;
- explicit `null` where omission is required;
- malformed UTF-8;
- alternate key order that decodes to same object but is not canonical if raw canonical submission is required.

## 15. Idempotency conflict fixture

Two operations share one client idempotency key but have different payloads.

Expected:

```text
ERR_IDEMPOTENCY_CONFLICT
```

## 16. Snapshot continuity fixture

Procedure:

1. Apply fixture block sequence through height N.
2. Export snapshot.
3. Restore a clean node from snapshot.
4. Compare restored AppHash at N.
5. Apply block N+1 to both nodes.
6. Compare AppHash at N+1.

Expected:

```text
identical
```

## 17. Full replay vs state sync fixture

Node A:

```text
genesis → replay all blocks → height H
```

Node B:

```text
state sync snapshot at H
```

Expected:

```text
AppHash_A(H) == AppHash_B(H)
StateRoot_A(H) == StateRoot_B(H)
```

The repository acceptance harness
`tools/run-consensus-snapshot-acceptance.py` executes this continuity fixture
against the current `AIDNABCIApplication`. It also verifies direct snapshot
restore, chunked State Sync, rejection of a tampered chunk, and advancement of
the restored/state-synced projections through the next block. Its report is
`CONTROLLED_LOCAL` evidence only; it does not replace live validator or
independent-operator acceptance.

## 18. Genesis fixture

The fixture set MUST freeze:

- genesis JSON canonical bytes;
- genesis hash;
- initial application state;
- initial profile commitment;
- initial validator set commitment where application-visible;
- first AppHash semantics.

## 19. Fixture manifest

`fixtures/manifest.json` MUST contain:

```json
{
  "fixture_set_version": 1,
  "profile_id": "aidn-mainnet-candidate-1",
  "fixture_count": 0,
  "files": [
    {
      "path": "...",
      "sha256": "..."
    }
  ],
  "manifest_hash": "..."
}
```

Fixture file hashes are calculated from UTF-8 text with line endings
normalized to LF. This keeps the manifest stable across Git checkouts on
Windows and Unix-like systems without weakening canonical operation checks.

## 20. Cross-implementation use

Any independent implementation MUST be able to download the fixture pack and verify conformance without running the reference implementation.

The fixture pack MUST therefore contain expected values, not only input generators.

## 21. CI gate

Recommended command:

```bash
aidn test fixtures --manifest fixtures/manifest.json --strict
```

Required exit behavior:

```text
0 = all fixtures pass
non-zero = release blocked
```

## 22. Coverage report

CI MUST emit:

```json
{
  "supported_operations": 0,
  "operations_with_happy_path_fixture": 0,
  "operations_with_replay_fixture": 0,
  "operations_with_invalid_transition_fixture": 0,
  "operations_with_hash_fixture": 0,
  "strict_coverage": true
}
```

No supported state-changing operation may have incomplete strict coverage in a release candidate.

## 23. Expected AppHash rule

Every state-changing valid fixture included in a block fixture MUST end in an explicit expected AppHash.

Do not use:

```text
"expected_app_hash": "<computed by implementation>"
```

That defeats the entire purpose, with admirable efficiency.

## 24. Golden fixture governance

Changing an expected fixture output is a protocol change.

A fixture output MUST NOT be updated merely to make failing code pass.

Any intentional fixture change requires:

- documented reason;
- compatibility analysis;
- migration impact;
- profile/version decision.
