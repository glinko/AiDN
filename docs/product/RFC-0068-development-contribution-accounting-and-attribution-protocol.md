# RFC-0068 AiDN Development Contribution Accounting and Attribution Protocol

Status: `Draft`

Version: `0.1`

Depends on:

- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0046 AiDN Registry Architecture`
- `RFC-0048 Epoch Engine`
- `RFC-0058 Participant Eligibility and Sybil Resistance`
- `RFC-0059 Ledger Operation Catalog`
- `RFC-0066 Protocol Upgrade and Emergency Recovery`
- `RFC-0067 Protocol Governance and Authorization Policy`
- `ECO-0007 Development Reward Pool and Distribution Policy`

Extended by repository-specific contribution profiles, a security disclosure policy, a contributor appeal procedure, and a future semantic code-analysis specification.

## 1. Purpose

This document defines how AiDN identifies, records, evaluates, and attributes accepted project-development contributions. It specifies eligible repositories and contribution classes, forge integration, Contributor Identity and Wallet binding, merge attestation, Effective Change Units (ECU), Contribution Units (CU), review attribution, maturity, anti-gaming controls, challenges, canonical commitments, and epoch-reward inputs.

This RFC does not set the Development Reward budget, Q conversion, emission, vesting percentage, or carryover rules. Those economic parameters belong exclusively to `ECO-0007`.

## 2. Principles and Boundaries

Development rewards SHALL be based on useful accepted contribution rather than raw activity volume:

```text
Contribution proposed -> reviewed and merged -> attested -> scored ->
challenge window -> epoch distribution -> maturity distribution
```

The following identities remain distinct:

```text
Contribution Score != Q mint amount
GitHub account != Contributor Identity
Wallet in PR notes != verified Wallet binding
Commit author != canonical reward recipient
Merge actor != contribution author
```

The protocol SHALL NOT use `raw_merged_lines * fixed_q_rate`. Raw lines are manipulable through generated code, formatting, vendoring, duplication, needless abstraction, and artificial PR splitting. Size is only one bounded, sublinear input to CU.

GitHub and other source forges provide evidence only. They SHALL NOT mint or transfer Q. Canonical reward eligibility requires a protocol-recognized Contribution Attestation.

## 3. Eligible Work

Initial contribution classes are:

- `CODE`, `TESTS`, `SECURITY`, `DOCUMENTATION`, `SPECIFICATION`, `REVIEW`;
- `BUG_TRIAGE`, `RELEASE`, `INFRASTRUCTURE`, `DESIGN`, `RESEARCH`, `LOCALIZATION`, and `COMMUNITY_TOOLING`.

`CODE` includes Hypervisor, protocols, Runtimes, Provider Plugins, Registry, Ledger, consoles, CLIs, SDKs, and conformance tooling. `TESTS` may receive independent attribution. `SECURITY` includes reports, reproductions, remediation, threat modelling, and incident tooling; embargoed reports SHALL use private disclosure and attestation.

Documentation, specifications, and infrastructure are eligible when accepted into the project specification or source set. A substantive review may receive attribution only where evidence shows an accepted finding, requested change, architecture correction, security finding, or test/performance improvement. A bare approval does not qualify by itself.

## 4. Eligible Repositories and Merge Evidence

Rewards arise only from an Eligible Repository Set. Each entry SHALL bind the canonical repository and its reward policy:

```yaml
eligible_repository:
  repository_id:
  repository_name:
  canonical_url:
  organization_id:
  default_branch:
  additional_reward_branches:
  contribution_profile_id:
  attestation_policy_id:
  active_from_epoch:
  active_until_epoch:
  repository_hash:
  authorization_signature:
```

Ordinary contributions SHALL enter a protected default branch, normally `main`, or an explicitly authorized reward branch. External changes SHOULD arrive through a reviewable pull request. A direct protected-branch push is not automatically rewardable unless emergency policy permits it and a later attestation verifies that it did not bypass review merely to obtain rewards.

```yaml
contribution_merge_event:
  repository_id:
  pull_request_id:
  merge_commit_hash:
  base_branch:
  source_commit_hash:
  merged_at:
  merge_actor:
  pull_request_author:
  coauthors:
  contribution_group_id:
  reward_metadata:
  source_platform_evidence_hash:
```

The default Contribution Epoch is the epoch containing the protected-branch merge timestamp. Payment MAY be delayed until the challenge window closes.

Pull requests MAY declare metadata such as `reward_eligible`, contribution class/group, related issues or bounties, excluded generated/vendor paths, test/documentation paths, candidate reviewers, and a Wallet address. Metadata is evidence, not authority.

## 5. Contributor Identity and Wallet Binding

Every reward recipient SHALL have a Contributor Identity:

```yaml
contributor_identity:
  contributor_id:
  source_platform_accounts:
  current_wallet_address:
  wallet_binding_version:
  known_control_group:
  identity_state:
  valid_from:
  valid_until:
  identity_hash:
  contributor_signature:
```

The Wallet binding procedure SHALL require a unique protocol challenge, a Wallet-key signature, and confirmation through the bound source-platform account:

```yaml
contributor_wallet_binding:
  contributor_id:
  source_platform_account:
  wallet_address:
  challenge_id:
  challenge_hash:
  wallet_signature:
  source_platform_confirmation_hash:
  valid_from:
  binding_version:
  binding_hash:
```

A Wallet in a PR is compared with the active binding. An unverified or mismatching address SHALL not receive immediate payment. A valid contribution without a verified Wallet enters `UNCLAIMED` and remains claimable for the configured epoch window; then it returns to the pool or reserve under `ECO-0007`. Wallet rotation applies only from its effective boundary and SHALL NOT redirect past rewards.

For a contribution that requests reward attribution, the preferred evidence is a
signed file committed in the exact merged revision:

```text
.aidn/contributor-wallet.json
```

The file SHALL use the following schema:

```yaml
schema_version: aidn.contributor-wallet.v1
contributor_id:
source_platform_account:
wallet_address:
wallet_public_key:
wallet_signature:
binding_id:
binding_hash:
claim_hash:
```

The Wallet signature covers the canonical claim payload and the claim hash
covers the complete claim object without `claim_hash`. The attestation process
MUST read the file from `merge_commit_hash`, verify the Ed25519 signature, and
match it to the active `ContributorWalletBinding`. A PR description or a file
from the working tree is not sufficient evidence.

The merged claim file is immutable evidence and SHALL NOT be overwritten after
payment. Payment, unclaimed, maturity, and correction state belongs to separate
`ECO-0007` reward records. A later Wallet rotation creates a new claim in a
later contribution and does not rewrite prior attribution.

## 6. Attestation and Attribution

Canonical attribution starts with a Contribution Attestation:

```yaml
contribution_attestation:
  contribution_id:
  repository_id:
  pull_request_id:
  merge_commit_hash:
  contribution_epoch:
  contributor_roles:
  contribution_class:
  contribution_group_id:
  effective_change_units:
  size_score:
  factor_values:
  contribution_units:
  wallet_claim:
  eligibility_state:
  exclusion_reasons:
  source_evidence_root:
  scoring_evidence_root:
  attestation_authorities:
  attestation_signatures:
  attested_at:
  attestation_hash:
```

Recommended derivation:

```text
ContributionID = HASH(RepositoryID + MergeCommitHash + ContributionGroupID)
```

Every repository SHALL declare its attestation policy. Supported policies include `SINGLE_MAINTAINER`, `MAINTAINER_THRESHOLD`, `AUTOMATION_PLUS_MAINTAINER`, and `GOVERNANCE_COMMITTEE`. The MVP default is an automated contribution report plus one authorized maintainer signature. Consensus-critical, economic, or security-sensitive work requires at least two independent authorized maintainer signatures.

Contributor roles may include `AUTHOR`, `COAUTHOR`, `ISSUE_DESIGNER`, `SPECIFICATION_AUTHOR`, `PRIMARY_REVIEWER`, `SECONDARY_REVIEWER`, `SECURITY_REVIEWER`, `TEST_AUTHOR`, and `RELEASE_INTEGRATOR`. Commit metadata alone SHALL NOT determine ownership. Role allocations use basis points and total 10,000 unless the attestation explicitly leaves a remainder unallocated.

Suggested starting allocation is 75% authors/coauthors, 15% substantive reviewers, 5% issue/specification design, and 5% test/release integration. Actual allocation SHALL reflect real work. Self-review earns no independent reviewer allocation. Known Control Groups do not count as independent reviewers for threshold decisions.

## 7. Contribution Groups and Exclusions

Related pull requests MAY share a `contribution_group_id`. They SHALL be grouped when they are sequential review slices of one deliverable, one issue/bounty, a follow-up repair within the maturity window, or changes split only for review convenience. Grouping prevents reward inflation from artificial fragmentation. Unrelated, independently useful work may remain separate.

Raw metrics such as added, deleted, modified lines, file count, and commit count are evidence fields only. The following normally have zero ECU weight:

- generated source, vendored dependencies, copied third-party source, minified or compiled output;
- binary files, lockfiles, build artifacts, generated snapshots, formatting-only and line-ending changes.

Contributors SHOULD disclose generated paths. The analysis tool SHOULD detect generated headers, package-manager output, repeated generated patterns, and move/copy operations. Undisclosed material generated code, substantial duplication, or mechanical code movement reduces ECU and may affect Quality Factor or eligibility.

## 8. Effective Change Units and Contribution Units

Each repository may publish a versioned contribution profile with path/type weights, excluded paths, generated/vendor patterns, size-score function, and automatic-size cap.

```yaml
repository_contribution_profile:
  profile_id:
  repository_id:
  source_weights:
  test_weights:
  documentation_weights:
  configuration_weights:
  deletion_weights:
  excluded_paths:
  generated_patterns:
  vendor_patterns:
  size_score_function:
  maximum_automatic_size_score:
  profile_version:
  profile_hash:
```

Default ECU calculation:

```text
ECU = SUM(EligibleChangedLines * PathWeight * ChangeTypeWeight)
SizeScore = sqrt(max(0, ECU))
ContributionUnits = SizeScore * ComplexityFactor * PriorityFactor *
                    QualityFactor * ImpactExpectationFactor * IndependenceFactor
```

Recommended initial change weights:

| Change type | Weight |
| --- | ---: |
| Added or modified source line | 1.00 |
| Deleted source line | 0.70 |
| Added or modified test line | 0.85 |
| Deleted obsolete test line | 0.50 |
| Documentation line | 0.35 |
| Configuration line | 0.40 |
| Generated, vendored, lockfile, formatting line | 0.00 |

Useful deletion has value, including removal of unsafe, dead, duplicate, obsolete, or unnecessary code. The default automatic Size Score cap is 50. Larger work requires a pre-approved bounty, explicit exceptional-contribution approval, or Governance authorization. Contribution Units SHALL use deterministic fixed-point arithmetic; the recommended precision is 1 CU = 1,000 milli-CU.

Recommended factor ranges are:

| Factor | Recommended values |
| --- | --- |
| Complexity | 0.75 trivial; 1.00 ordinary; 1.20 moderate; 1.40 high; 1.60 exceptional protocol/security |
| Priority | 0.75 unsolicited low priority; 1.00 normal; 1.20 roadmap; 1.40 critical planned; 1.75 emergency |
| Quality | 0.50 deficient; 0.80 acceptable; 1.00 good; 1.20 excellent; 1.40 exceptional |
| Impact expectation | 0.75 narrow; 1.00 ordinary; 1.20 broad; 1.40 platform-critical |
| Independence | 0.50 mechanical follow-up; 0.75 dependent; 1.00 independent; 1.15 reusable foundation |

Complexity SHALL NOT reward avoidable complication. Quality considers correctness, tests, maintainability, architecture fit, documentation, security, performance, deterministic behavior, migration safety, and conformance coverage. For the MVP, maintainers manually attest factors; automation may recommend but cannot be their sole authority.

## 9. Funding, Challenges, and Maturity

Work fully funded by employment, grants, contracts, bounties, or security rewards MAY be excluded or receive reduced Development Pool allocation; required funding disclosures prevent double funding. A pre-funded bounty defines its own milestone, reviewer, and Development Pool treatment.

Contribution states are `PENDING`, `ELIGIBLE`, `INELIGIBLE`, `CHALLENGED`, `FINALIZED`, `UNCLAIMED`, `VESTING`, `MATURED`, and `CANCELLED`. The recommended challenge window is one epoch. Challenges require evidence and may allege attribution error, hidden generated code, duplication, artificial splitting, factor manipulation, unverified Wallet, conflict of interest, plagiarism, licensing violation, malicious code, or invalid merge evidence.

```yaml
contribution_challenge:
  challenge_id:
  contribution_id:
  challenger_id:
  challenge_class:
  claimed_error:
  evidence_root:
  opened_at:
  challenge_signature:
```

Resolution outcomes are `ATTESTATION_CONFIRMED`, `ATTRIBUTION_CORRECTED`, `SCORE_CORRECTED`, `CONTRIBUTION_GROUPED`, `CONTRIBUTION_EXCLUDED`, `WALLET_BINDING_REQUIRED`, or `SECURITY_REVIEW_REQUIRED`. Appeals are bounded and evidence-based. A style preference, popularity, later requirement change, or the existence of another possible implementation is not sufficient challenge ground.

Recommended maturity stages are 4 and 12 epochs after merge. A contribution remains maturity-eligible when it was not reverted for contributor defect, does not cause unresolved critical regression, receives needed security remediation, has valid licensing/attribution, and remains useful or functionally replaced.

Reverts are classified as `REQUIREMENT_CHANGE`, `SUPERSEDED`, `ORDINARY_DEFECT`, `CRITICAL_DEFECT`, `SECURITY_DEFECT`, `INTENTIONAL_GAMING`, or `MALICIOUS`. Requirement changes and useful supersession do not automatically penalize the contributor. Ordinary defects may reduce unpaid maturity rewards, especially where the contributor does not remediate. Critical/security defects may cancel unpaid maturity rewards and affect reliability. Intentional gaming may cancel unvested rewards and cause separate penalty proceedings. This RFC SHALL NOT automatically claw back finalized Q.

## 10. Evidence, Privacy, and Security

The protocol retains merge evidence, attestations, scoring evidence, challenges, maturity decisions, reward references, and the historical Wallet binding. Platform metadata can change or disappear, so attestations SHOULD commit immutable evidence: merge commit, protected-branch reachability, PR diff root, review evidence root, issue evidence root, source-platform event hash, and repository identity.

A PR diff root SHOULD cover changed paths, old/new file hashes, normalized classifications, and exclusions. Review evidence may commit review comments, requested changes, accepted suggestions, and review-state transitions. Private security evidence may be access controlled. Full forge data remains off-ledger in project archives, Registry objects, mirrors, or restricted security storage.

The design SHALL account for maintainer compromise, fake forge identities, Wallet substitution, fabricated merge events, inflation, hidden generated code, review collusion, splitting, plagiarism, malicious scoring, repository takeover, rewritten history, and forge outage. High-value work SHOULD require threshold attestation. An emergency process may suspend an authority, require re-attestation, or delay rewards.

AI-assisted work MAY be eligible; the responsible human remains accountable for licensing, correctness, security, review, maintenance, and truthful attribution. Bots require an authorized identity, responsible human or organization, and explicit reward-policy permission.

## 11. Canonical Commitments and Operations

The Ledger or Registry MAY store compact commitments:

```yaml
canonical_contribution_commitment:
  contribution_id:
  repository_id:
  merge_commit_hash:
  contribution_epoch:
  contribution_class:
  contribution_group_id:
  contributor_allocation_root:
  contribution_units:
  challenge_state:
  maturity_state:
  attestation_hash:
  finalized_at:
```

`RFC-0059` SHOULD define equivalent operations:

- `CONTRIBUTOR_IDENTITY_REGISTER`, `CONTRIBUTOR_WALLET_BIND`, and `CONTRIBUTOR_WALLET_ROTATE`;
- `ELIGIBLE_REPOSITORY_REGISTER` and `ELIGIBLE_REPOSITORY_UPDATE`;
- `CONTRIBUTION_ATTEST`, `CONTRIBUTION_CHALLENGE`, `CONTRIBUTION_CHALLENGE_RESOLVE`, and `CONTRIBUTION_FINALIZE`;
- `CONTRIBUTION_MATURITY_CONFIRM`, `CONTRIBUTION_MATURITY_REDUCE`, and `CONTRIBUTION_REWARD_CANCEL_UNVESTED`.

Repository registration, Wallet binding, attestation, identical challenge submission, resolution, finalization, and maturity confirmation SHALL be idempotent. Q distribution operations and all economic values are defined by `ECO-0007`.

## 12. MVP, Deferred Work, and Invariants

The post-MVP implementation baseline SHALL include an Eligible Repository Set, protected-branch merge verification, Contributor Identity, signed Wallet binding, PR metadata, attestation, ECU, sublinear Size Score, bounded factors, contribution groups, author/reviewer allocation, excluded generated/vendor/lockfile changes, challenge windows, maturity/revert classification, compact commitments, and stable errors.

Deferred capabilities include AST semantic scoring, automated complexity/plagiarism adjudication, decentralized reviewer markets, cross-forge federation, zero-knowledge contributor identity, automatic long-term impact scoring, automatic reliability penalties, and quality-oracle integration.

Required error codes include:

```text
CONTRIBUTOR_NOT_REGISTERED
CONTRIBUTOR_WALLET_NOT_BOUND
CONTRIBUTOR_WALLET_MISMATCH
CONTRIBUTOR_IDENTITY_CONFLICT
REPOSITORY_NOT_ELIGIBLE
REPOSITORY_ATTESTATION_AUTHORITY_INVALID
CONTRIBUTION_NOT_FOUND
CONTRIBUTION_ALREADY_ATTESTED
CONTRIBUTION_MERGE_NOT_VERIFIED
CONTRIBUTION_BRANCH_NOT_ELIGIBLE
CONTRIBUTION_NOT_REWARD_ELIGIBLE
CONTRIBUTION_DIFF_INVALID
CONTRIBUTION_GENERATED_CODE_UNDECLARED
CONTRIBUTION_DUPLICATE_CODE
CONTRIBUTION_GROUP_REQUIRED
CONTRIBUTION_GROUP_CONFLICT
CONTRIBUTION_SCORE_INVALID
CONTRIBUTION_FACTOR_OUT_OF_RANGE
CONTRIBUTION_ALLOCATION_INVALID
CONTRIBUTION_CHALLENGE_INVALID
CONTRIBUTION_CHALLENGE_EXPIRED
CONTRIBUTION_APPEAL_INVALID
CONTRIBUTION_MATURITY_NOT_REACHED
CONTRIBUTION_MATURITY_REDUCED
CONTRIBUTION_REWARD_UNCLAIMED
CONTRIBUTION_GAMING_DETECTED
CONTRIBUTION_LICENSE_VIOLATION
```

The following are invariant:

- raw line count never directly determines Q; excluded mechanical changes receive no ordinary size credit;
- size is sublinear and bounded; useful deletion can be valuable; factors are bounded and auditable;
- attribution, review evidence, Wallet binding, and Known Control Groups are explicit;
- related work may be grouped; self-review is not independent review; Wallet changes are not retroactive;
- immediate merge does not prove maturity; revert reason is classified; finalized Q requires a separate authorized recovery process;
- forge evidence does not control emission; technical scoring remains separate from Development Pool policy;
- AI assistance does not remove human accountability, and neither the AI nor a line counter is the project economist.

## 13. Open Parameters

The following parameters require governance approval with `ECO-0007` and repository profiles:

```text
ContributionChallengeWindow
ContributionClaimWindow
MaturityStageOneEpochs
MaturityStageTwoEpochs
MaximumAutomaticSizeScore
MaximumOrdinaryContributionUnits
DefaultSourceLineWeight
DefaultDeletionWeight
DefaultTestWeight
DefaultDocumentationWeight
MinimumIndependentReviewers
SensitiveContributionReviewerThreshold
ContributorAppealWindow
ContributionEvidenceRetention
```
