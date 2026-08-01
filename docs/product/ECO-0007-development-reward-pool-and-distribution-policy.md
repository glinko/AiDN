# ECO-0007 Development Reward Pool and Distribution Policy

Status: `Planned`

Version: `0.1-placeholder`

Depends on:

- `ECO-0000 Economic Principles`
- `ECO-0005 Q Emission, Recycling and Epoch Reward Allocation`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0048 Epoch Engine`
- `RFC-0058 Participant Eligibility and Sybil Resistance`
- `RFC-0059 Ledger Operation Catalog`
- `RFC-0067 Protocol Governance and Authorization Policy`
- `RFC-0068 AiDN Development Contribution Accounting and Attribution Protocol`

## 1. Status and Purpose

This is a reserved post-MVP policy document. It creates a stable roadmap location for the Development Reward Pool without assigning economic parameters before Governance and tokenomics review.

`RFC-0068` determines accepted contribution evidence, attribution, and relative Contribution Units. This document will determine only the economic conversion and distribution of eligible contribution. It SHALL NOT redefine code-review, ECU, CU, Wallet-binding, or contribution-attestation rules.

## 2. Required Future Decisions

The approved version of this document SHALL define:

- Development Reward Pool funding source, epoch budget, maximum allocation, and carryover;
- conversion from eligible Contribution Units to Q while preserving the epoch budget;
- immediate, vesting, and maturity reward portions;
- treatment of unclaimed, cancelled-unvested, reverted, and expired rewards;
- pre-funded bounty, employment, grant, contract, and security-reward interaction;
- reward-recipient, reviewer, and repository caps;
- rounding, deterministic calculation, commitments, and Ledger operations;
- Governance authorization, upgrade, emergency pause, audit, and appeal boundaries.

## 3. Non-Normative Placeholder Boundary

Until an approved version exists:

- no Development Pool Q emission, minting, or transfer SHALL be implemented from this placeholder;
- `RFC-0068` contribution records MAY be collected as evidence but SHALL NOT imply a payout;
- current MVP economics, Endpoint Settlement, Validator economics, and ordinary Q accounting remain unchanged;
- no repository, maintainer, contributor, or Wallet receives an implied entitlement from this document.

## 4. Post-MVP Delivery Order

1. Implement `RFC-0068` evidence, attribution, and attestation in an isolated non-emitting mode.
2. Publish and approve the economic parameters and safety caps in a normative `ECO-0007` revision.
3. Add the corresponding `RFC-0059` Ledger operations and deterministic epoch calculation.
4. Enable a limited, auditable reward-pool rollout only after independent review and Governance authorization.
