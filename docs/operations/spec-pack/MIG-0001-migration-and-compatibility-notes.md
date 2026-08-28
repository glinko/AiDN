# MIG-0001 — AiDN Migration and Compatibility Notes

Status: Draft  
Version: 0.1

## 1. Purpose

Defines how AiDN upgrades consensus-visible state without creating ambiguous AppHash behavior or unsafe rollback.

## 2. Version dimensions

The implementation MUST track separately:

```text
software_version
profile_id
state_schema_version
canonical_encoding_version
app_hash_version
operation_catalog_version
snapshot_format_version
```

A software update is not automatically a protocol migration.

## 3. Compatibility matrix

Every release MUST publish:

| From | To | Read old snapshot | Join mixed validator set | Automatic migration | Rollback |
|---|---|---|---|---|---|
| profile A | profile B | explicit | explicit | explicit | explicit |

No blank cells are permitted in a production release matrix.

## 4. State-compatible update

If state schema, canonical bytes, and AppHash remain unchanged:

```text
migration_required = false
```

Mixed software versions MAY run only if the release declares consensus compatibility.

## 5. State migration

A state migration MUST define:

- activation height;
- predecessor profile;
- successor profile;
- deterministic state transform;
- expected pre-migration AppHash;
- expected post-migration AppHash semantics;
- migration fixtures.

## 6. Activation height

Consensus-visible migration MUST activate at a deterministic consensus height or governance-approved activation condition committed in state.

Wall-clock-only activation is forbidden.

## 7. Snapshot compatibility

A new node reading an old snapshot MUST either:

1. support deterministic migration; or
2. reject with `ERR_SNAPSHOT_INCOMPATIBLE`.

Silent reinterpretation is forbidden.

## 8. AppHash version changes

Changing AppHash derivation requires:

- new `app_hash_version`;
- migration fixture;
- activation rule;
- checkpoint documentation;
- explicit mixed-version prohibition unless proven safe.

## 9. Canonical encoding changes

Changing canonical JSON/hash semantics is a consensus protocol change even if logical fields are unchanged.

It requires a new encoding version and fixtures.

## 10. Operation catalog changes

Adding an operation is compatible only after activation under a profile understood by all active validators.

Unknown operation rejection means a premature submit would otherwise fail, which is preferable to accidental divergence.

## 11. Snapshot migration procedure

Recommended:

```text
load old snapshot
verify old AppHash
apply deterministic migration
derive new StateRoot
derive new AppHash under new profile
persist migrated state
emit migration evidence
```

## 12. Rollback boundary

A node MUST NOT roll back across an activated state/AppHash migration using only an older binary.

Once consensus commits blocks under the new profile, rollback requires a coordinated network recovery plan.

## 13. Safe binary rollback

Binary rollback MAY be permitted when:

- no consensus-visible schema/hash rule changed;
- old binary can read current state;
- old binary supports every operation already active;
- release matrix explicitly marks rollback safe.

## 14. Migration evidence

Migration release MUST publish:

```text
old profile commitment
new profile commitment
activation height
migration code hash
migration fixture manifest
pre-migration checkpoint
post-migration checkpoint
operator evidence
```

## 15. Required migration fixtures

At minimum:

```text
old snapshot → new state
old AppHash verification
new AppHash derivation
one post-migration block
rollback rejection where unsafe
unsupported snapshot rejection
```

## 16. Failure behavior

If migration fails before activation commit:

- old state remains active;
- node does not advertise successful upgrade.

If local state does not match expected pre-migration commitment at activation:

- validator MUST halt rather than guess.

## 17. Genesis evolution

A network genesis file is immutable for that network.

New networks use new genesis.

Existing networks evolve through state transitions/migrations, not by editing genesis.

## 18. Trust anchor compatibility

Checkpoint/trust-anchor bundles MUST identify:

```text
network_id
height
block_hash
AppHash
profile_id
app_hash_version
```

A node MUST reject a trust anchor incompatible with the requested network/profile path.

## 19. Operator upgrade note template

Every release with migration impact MUST tell operators:

```text
Can I upgrade in place?
Do I need a snapshot first?
Can I downgrade?
What height activates the change?
Can old and new validators coexist?
What exact command verifies migration?
What expected AppHash/checkpoint should I see?
```

