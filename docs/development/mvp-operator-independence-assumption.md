# MVP Operator Independence Assumption

Status: Accepted for MVP controlled testnet

Effective date: 2026-08-01

## Decision

For the functional MVP acceptance gate, the project accepts `hv-node10`
(`192.168.88.126`) as an independent AiDN operator by explicit out-of-band
project declaration. Tests requiring a second organizationally independent
operator are therefore waived for the MVP controlled testnet.

This decision is an administrative acceptance assumption. It does not change
the Registry protocol, the mTLS or Ed25519 verification rules, the Ledger
finality rules, or the semantics of any verifier report.

## Scope

The assumption is sufficient to close the MVP acceptance gate for:

- authenticated Registry peer transport;
- persistent inventory exchange;
- immutable object replication;
- reconnect and restart recovery;
- the current controlled-testnet Hypervisor profile.

It is not a claim that the protocol has cryptographically proven separate
ownership, separate legal entities, or absence of operator coordination.

## Evidence Boundary

The live technical evidence remains the evidence recorded in
[Independent Operator Onboarding and Acceptance](./independent-operator-onboarding-and-acceptance.md):
mutual peer approval, authenticated transport, inventory convergence, and
restart/re-authentication without loss of replicated objects.

The technical verifier SHALL continue to report
`ownership_evidence: NOT_PROVEN_BY_PROTOCOL`. The MVP policy layer may accept
the declared operator status without rewriting that field.

This waiver does not authorize public directory trust, public multi-validator
finality claims, or production economic deployment. Those claims require their
own evidence and Governance decisions.

## Revisit Conditions

The assumption must be revisited if:

- the project withdraws the operator declaration;
- ownership or control evidence conflicts with the declaration;
- the controlled-testnet profile is promoted to a public network claim;
- a protocol or Governance policy requires independently verified operators.

Until then, implementation may proceed without blocking the functional MVP on
additional external-operator testing.
