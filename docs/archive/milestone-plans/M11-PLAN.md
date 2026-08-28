# M11: Rating, Validation Bond & Epoch Rewards — Execution Plan

**RFC Coverage:**
- ECO-0003: Validation Economics (Validation Bond, Reward, Maintenance Validation)
- ECO-0004: Protocol Service Reward Distribution (Pool weights, diversity, concentration caps)
- ECO-0005: Q Emission, Recycling & Epoch Reward Allocation (Base emission, recyclable Q, Faucet)
- ECO-0006: Consensus Economics & Validator Eligibility (Stake, active set, downtime, slashing)
- RFC-0035: Validation Escrow System (Bond lifecycle, custody)
- RFC-0057: Validation Report Specification (Report structure, certification)
- RFC-0058: Participant Eligibility & Sybil Resistance (Known Control Groups, eligibility states)

**Status:** `Planning`

**Depends on:** M1-M10 complete

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    M11: Rating + Bond + Rewards                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐    │
│  │  Rating      │   │  Validation  │   │  Epoch Reward    │    │
│  │  Engine      │   │  Bond        │   │  Distribution    │    │
│  │              │   │  Manager     │   │  Engine          │    │
│  │ - NodeRating │   │ - BondLock   │   │ - ServicePool    │    │
│  │ - Dimensions │   │ - Recovery   │   │ - Diversity      │    │
│  │ - Scoring    │   │ - Slash      │   │ - Concentration  │    │
│  │ - History    │   │ - Forfeit    │   │ - Mint Ops       │    │
│  └──────┬───────┘   └──────┬───────┘   └────────┬─────────┘    │
│         │                  │                     │              │
│  ┌──────┴──────────────────┴─────────────────────┴──────────┐  │
│  │              Participant Eligibility Layer                │  │
│  │  - Known Control Groups  - Activation Age  - Health      │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Epoch Transition Engine                      │  │
│  │  - Evidence Freeze  - Reward Calc  - Mint Generation     │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Existing Infrastructure (Reused)

| Component | Location | What We Use |
|---|---|---|
| Reputation Engine | `reputation_engine/` | Profile scoring, evidence ingestion, state derivation |
| ValidatorSetManager | `consensus/validator.py` | Stake management, active set selection, participation tracking |
| EpochService | `consensus/epoch.py` | Epoch lifecycle, transitions |
| Escrow Adapter | `validation/escrow.py` | Bond lock/refund/forfeit primitives |
| LedgerService | `ledger/service.py` | State transitions, operation execution |
| RegistryService | `registry_service.py` | Service registration, queries |

---

## Slice Breakdown

### S1: Rating Models + Scoring Engine

**Goal:** Implement node rating with independent dimensions (uptime, success_rate, latency, dispute_history) and Bayesian scoring.

**New Package:** `src/aidn_hypervisor/rating/`

**Files:**
- `rating/models.py` — `RatingDimension`, `NodeRating`, `RatingEvidence`, `RatingScore`
- `rating/scoring.py` — `RatingScorer`, dimension-specific scoring functions
- `rating/store.py` — `RatingStore`, persistence, history queries
- `rating/engine.py` — `RatingEngine`, event ingestion, score updates

**Key Models:**
```python
class RatingDimension(str, Enum):
    UPTIME = "uptime"
    SUCCESS_RATE = "success_rate"
    LATENCY = "latency"
    DISPUTE_HISTORY = "dispute_history"
    REPUTATION = "reputation"

class NodeRating(BaseModel, frozen=True):
    node_id: str
    dimensions: dict[RatingDimension, float]  # 0.0 - 1.0
    composite_score: float  # weighted average
    evidence_count: int
    last_updated: str
    epoch: int

class RatingEvidence(BaseModel, frozen=True):
    node_id: str
    dimension: RatingDimension
    value: float
    weight: float  # evidence confidence
    timestamp: str
    source: str  # "session_completion" | "validation_report" | "heartbeat"
```

**Test Targets:** ~80 tests

**Exit Criteria:**
- Rating dimensions independently scored
- Composite score computed from weighted dimensions
- Evidence ingestion with Bayesian update
- Rating history queryable per epoch
- Integration with existing ReputationEngine

---

### S2: Validation Bond Manager

**Goal:** Implement Validation Bond lifecycle (lock → active → recover/forfeit) with exponential decay recovery.

**New Package:** `src/aidn_hypervisor/validation_bond/`

**Files:**
- `validation_bond/models.py` — `ValidationBond`, `BondStatus`, `BondRecoveryRecord`, `BondForfeitRecord`
- `validation_bond/manager.py` — `ValidationBondManager`, lock/refund/forfeit/recover
- `validation_bond/store.py` — `BondStore`, persistence

**Key Models:**
```python
class BondStatus(str, Enum):
    LOCKED = "locked"
    ACTIVE = "active"
    RECOVERING = "recovering"
    FORFEITED = "forfeited"
    RECOVERED = "recovered"

class ValidationBond(BaseModel, frozen=True):
    bond_id: str
    endpoint_id: str
    operator_wallet: str
    initial_amount: int  # q-atoms (500_000_000 = 500Q)
    remaining_amount: int
    status: BondStatus
    created_at: str
    recovery_count: int
    recovery_records: list[BondRecoveryRecord]
```

**Recovery Formula (ECO-0003 §8):**
```
Recovery(n) = remaining × 0.5  # exponential decay
Remaining(n) = remaining × 0.5
```

**Test Targets:** ~60 tests

**Exit Criteria:**
- Bond lock with minimum amount enforcement (500Q)
- Exponential decay recovery on successful maintenance validation
- Forfeit on validation failure (recyclable protocol removal)
- Bond history queryable
- Integration with LedgerService for lock/unlock ops

---

### S3: Participant Eligibility + Anti-Sybil

**Goal:** Implement Known Control Groups, activation age tracking, eligibility gates, and concentration caps.

**New Package:** `src/aidn_hypervisor/eligibility/`

**Files:**
- `eligibility/models.py` — `EligibilityState`, `KnownControlGroup`, `ActivationRecord`, `EligibilityGateResult`
- `eligibility/engine.py` — `EligibilityEngine`, gate checks, KCG aggregation
- `eligibility/kcg.py` — `KnownControlGroupManager`, group detection, concentration tracking

**Key Models:**
```python
class EligibilityState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    INELIGIBLE = "ineligible"
    SUSPENDED = "suspended"
    RETIRED = "retired"

class KnownControlGroup(BaseModel, frozen=True):
    group_id: str
    reward_beneficiary: str  # wallet address
    member_service_ids: list[str]
    total_stake: int
    aggregate_weight: float
    concentration_percentage: float
```

**Eligibility Gates (ECO-0004 §8):**
- Valid Service Identity
- Valid owner + Reward Beneficiary
- Required activation age (10 epochs)
- Required Stake/Bond
- Compatible protocol version
- No active suspension
- Minimum Service Health (0.70)
- Required Duty Proof
- Epoch eligibility snapshot inclusion

**Test Targets:** ~70 tests

**Exit Criteria:**
- Eligibility gate checks all RFC requirements
- Known Control Group detection via reward beneficiary aggregation
- Activation age enforcement
- Concentration percentage calculation
- Integration with EpochService for epoch snapshots

---

### S4: Epoch Reward Distribution Engine

**Goal:** Implement Service Pool reward calculation with diversity factors, concentration caps, and deterministic mint generation.

**New Package:** `src/aidn_hypervisor/reward/`

**Files:**
- `reward/models.py` — `ServicePool`, `RewardCalculation`, `RewardMint`, `DiversityFactor`, `PoolConfig`
- `reward/calculator.py` — `RewardCalculator`, weight computation, quality factors
- `reward/pools.py` — `ServicePoolManager`, pool budget allocation, distribution
- `reward/mint.py` — `MintGenerator`, deterministic mint operation generation

**Key Models:**
```python
class ServicePool(str, Enum):
    CONSENSUS = "consensus"
    REGISTRY = "registry"
    VALIDATION = "validation"
    FAUCET = "faucet"

class RewardCalculation(BaseModel, frozen=True):
    epoch: int
    participant_id: str
    service_pool: ServicePool
    raw_weight: float
    quality_factor: float
    maturity_factor: float
    health_factor: float
    duty_proof_factor: float
    reliability_factor: float
    final_reward: int  # q-atoms
    kcg_id: str
    kcg_share_percentage: float

class PoolConfig(BaseModel, frozen=True):
    consensus_share: float = 0.30
    registry_share: float = 0.30
    validation_share: float = 0.30
    faucet_share: float = 0.10
    target_independent_groups: dict[ServicePool, int]
    minimum_group_share_cap: float = 0.20
```

**Reward Formula (ECO-0004 §9):**
```
RawWeight(i) = WorkUnits(i) × QualityFactor(i)
QualityFactor(i) = MaturityFactor × HealthFactor × DutyProofFactor × ReliabilityFactor
```

**Maturity Formula (ECO-0004 §12):**
```
MaturityFactor(n) = 1 - 0.9^n  # n = qualifying epochs
```

**Diversity Factor (ECO-0004 §21):**
```
DiversityFactor = min(1, IndependentGroupCount / TargetIndependentGroups)
DistributablePool = NominalPoolBudget × DiversityFactor
```

**Group Share Limit (ECO-0004 §23):**
```
MaximumGroupShare = max(1 / IndependentGroupCount, MinimumGroupShareCap)
```

**Test Targets:** ~100 tests

**Exit Criteria:**
- Pool budget allocation matches ECO-0005 percentages
- Participant weight calculation with all quality factors
- Diversity factor reduces pool when few independent groups
- Group concentration caps enforced via capped proportional distribution
- Deterministic mint operation generation
- Fixed-point arithmetic (no floating point in final calculations)
- Integration with LedgerService for mint execution

---

### S5: Epoch Transition + Recycling Engine

**Goal:** Implement epoch transition automation, recyclable Q handling, Faucet allocation, and emission tracking.

**New Package:** `src/aidn_hypervisor/epoch_reward/`

**Files:**
- `epoch_reward/models.py` — `EpochRewardBudget`, `RecyclableRecord`, `FaucetAllocation`, `EmissionRecord`
- `epoch_reward/transition.py` — `EpochTransitionEngine`, evidence freeze, reward calc, mint generation
- `epoch_reward/recycling.py` — `RecyclingEngine`, recyclable Q tracking, backlog management
- `epoch_reward/faucet.py` — `FaucetEngine`, Faucet allocation, anti-Sybil constraints

**Key Models:**
```python
class EpochRewardBudget(BaseModel, frozen=True):
    epoch: int
    base_emission: int = 5_000_000_000  # 5000Q in q-atoms
    recyclable_amount: int
    total_budget: int
    consensus_pool: int
    registry_pool: int
    validation_pool: int
    faucet_pool: int
    minted_amount: int
    unused_amount: int

class RecyclableRecord(BaseModel, frozen=True):
    source: str  # "network_fee" | "validator_penalty" | "bond_forfeit" | "consensus_slash"
    amount: int
    epoch_removed: int
    epoch_recycled: int | None
    status: str  # "pending" | "recycled"
```

**Budget Calculation (ECO-0005 §8):**
```
NewEpochRewardBudget(t) = BaseEmission + RecyclableAmount(t)
RecyclableAmount(t) = EligibleRemovedQ(t-1) + RecycleBacklog(t-1)
```

**Test Targets:** ~60 tests

**Exit Criteria:**
- Epoch transition triggers evidence freeze → reward calc → mint generation
- Recyclable Q tracked from removal through recycling
- Faucet allocation with anti-Sybil constraints
- Emission records auditable
- Unused budget handling (expires for base, returns to backlog for recyclable)
- Integration with EpochService for transition hooks

---

### S6: Validation Report + Certification

**Goal:** Implement Validation Report structure, certification status derivation, and maintenance validation triggers.

**New Package:** `src/aidn_hypervisor/validation_report/`

**Files:**
- `validation_report/models.py` — `ValidationReport`, `CertificationStatus`, `MaintenanceTrigger`, `ReportEvidence`
- `validation_report/engine.py` — `ValidationReportEngine`, report creation, certification derivation
- `validation_report/maintenance.py` — `MaintenanceValidationEngine`, trigger detection, scheduling

**Key Models:**
```python
class CertificationStatus(str, Enum):
    UNVALIDATED = "unvalidated"
    VALIDATION_PENDING = "validation_pending"
    CERTIFIED = "certified"
    DE_CERTIFIED = "de_certified"
    UNDER_REVALIDATION = "under_revalidation"

class ValidationReport(BaseModel, frozen=True):
    report_id: str
    endpoint_id: str
    validator_id: str
    epoch: int
    recommendation: str  # "certify" | "de_certify" | "conditional"
    evidence: list[ReportEvidence]
    signed_at: str
    certification_status: CertificationStatus
```

**Maintenance Triggers (ECO-0003 §7):**
- Decreasing reputation
- Increased latency
- Increased error rate
- Suspicious behavior
- Random epoch selection

**Test Targets:** ~50 tests

**Exit Criteria:**
- Validation report structure matches RFC-0057
- Certification status derived from published reports
- Maintenance validation triggered by operational metrics
- Random epoch selection for maintenance validation
- Integration with RatingEngine for metric triggers

---

### S7: Integration + E2E Tests

**Goal:** Full pipeline tests: bond → validation → rating → reward → epoch transition.

**Test Files:**
- `tests/m11/test_rating_integration.py`
- `tests/m11/test_bond_lifecycle_integration.py`
- `tests/m11/test_reward_distribution_integration.py`
- `tests/m11/test_epoch_transition_integration.py`
- `tests/m11/test_full_pipeline.py`

**E2E Scenarios:**
1. Node registers → earns rating → becomes eligible → receives reward
2. Endpoint publishes → locks bond → passes validation → recovers bond
3. Validator participates → earns consensus reward → diversity factor applied
4. Bond forfeited → becomes recyclable → recycled into next epoch budget
5. Known Control Group detected → concentration cap applied → reward redistributed
6. Epoch transition → evidence freeze → reward calc → mint generation → state update
7. Maturity advances → quality factor improves → reward increases
8. Downtime detected → health factor decreases → reward reduced

**Test Targets:** ~80 tests

**Exit Criteria:**
- All E2E scenarios pass
- No floating point drift in reward calculations
- Deterministic results across runs
- Integration with all existing components (EpochService, ValidatorSetManager, ReputationEngine, LedgerService)

---

## Execution Order

```
S1: Rating Models + Scoring Engine          → ~80 tests
        ↓
S2: Validation Bond Manager                 → ~60 tests
        ↓
S3: Participant Eligibility + Anti-Sybil    → ~70 tests
        ↓
S4: Epoch Reward Distribution Engine        → ~100 tests
        ↓
S5: Epoch Transition + Recycling Engine     → ~60 tests
        ↓
S6: Validation Report + Certification       → ~50 tests
        ↓
S7: Integration + E2E Tests                → ~80 tests
```

**Total:** ~500 tests, ~7000 lines of code + tests

---

## Key Constants (ECO Alignment)

| Parameter | Value | Source |
|---|---|---|
| Base Emission per Epoch | 5000Q | ECO-0005 §3 |
| Consensus Pool Share | 30% | ECO-0005 §12 |
| Registry Pool Share | 30% | ECO-0005 §12 |
| Validation Pool Share | 30% | ECO-0005 §12 |
| Faucet Pool Share | 10% | ECO-0005 §12 |
| Validation Bond | 500Q | ECO-0003 §3 |
| Validator Stake | 500Q | ECO-0006 §10 |
| Minimum Health | 0.70 | ECO-0004 §15 |
| Minimum Group Share Cap | 20% | ECO-0004 §23 |
| Target Consensus Groups | 5 | ECO-0004 §21 |
| Target Registry Groups | 5 | ECO-0004 §21 |
| Target Validation Groups | 3 | ECO-0004 §21 |
| Activation Age | 10 epochs | ECO-0006 §8 |
| Minimum Reward | 0.01Q | ECO-0004 §26 |
| Epoch Duration | 24 hours | ECO-0005 §2 |

---

## Design Principles

1. **Fixed-point arithmetic** — no floating point in final reward calculations
2. **Deterministic** — same inputs always produce same outputs
3. **Evidence-backed** — no reward without Duty Proof
4. **Budget-first** — individual claims never increase pool size
5. **Anti-Sybil** — Known Control Groups aggregate for concentration limits
6. **Recyclable** — protocol removals feed back into reward budget
7. **Transparent** — all calculations auditable via Ledger records
8. **Compatible** — builds on existing M1-M10 infrastructure

---

## Related RFCs

- [ECO-0003 Validation Economics](../../product/ECO-0003-validation-economics.md)
- [ECO-0004 Protocol Service Reward Distribution](../../product/ECO-0004-protocol-service-reward-distribution.md)
- [ECO-0005 Q Emission, Recycling & Epoch Reward Allocation](../../product/ECO-0005-q-emission-recycling-and-epoch-reward-allocation.md)
- [ECO-0006 Consensus Economics & Validator Eligibility](../../product/ECO-0006-consensus-economics-and-validator-eligibility.md)
- [RFC-0035 Validation Escrow System](../../product/RFC-0035-validation-escrow-system.md)
- [RFC-0057 Validation Report Specification](../../product/RFC-0057-validation-report-specification.md)
- [RFC-0058 Participant Eligibility & Sybil Resistance](../../product/RFC-0058-participant-eligibility-and-sybil-resistance.md)
