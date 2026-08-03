# AiDN Executable Specification Pack

Status: Draft  
Purpose: convert the existing AiDN architecture into implementation- and operator-executable specifications.

This pack contains:

1. `IMP-0001-aiDN-implementation-profile.md` — exact production-supported protocol subset.
2. `FIX-0001-consensus-transition-fixtures.md` — deterministic state-transition fixture format and required vectors.
3. `OPS-0001-public-validator-operator-runbook.md` — clean-host-to-public-validator operating procedure.
4. `GATE-0001-release-gate-checklist.md` — release acceptance gates and exact evidence requirements.
5. `MIG-0001-migration-and-compatibility-notes.md` — snapshot/state/AppHash migration and rollback rules.
6. `EVD-0001-public-evidence-bundle-format.md` — canonical public evidence bundle.

## Production-support rule

A consensus-visible feature is production-supported only when the following chain is complete:

```text
Architecture/RFC
    ↓
IMP-0001 profile entry
    ↓
FIX-0001 deterministic fixture coverage
    ↓
implementation
    ↓
GATE-0001 release evidence
```

If any link is missing, the feature MUST be treated as experimental or unsupported.

## Priority

Implementation order:

```text
IMP-0001
   ↓
FIX-0001
   ↓
OPS-0001
```

`GATE-0001`, `MIG-0001`, and `EVD-0001` SHOULD be maintained in parallel and MUST be complete before a public production release.

