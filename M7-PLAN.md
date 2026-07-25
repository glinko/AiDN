# M7: CometBFT Consensus And Ledger Finality — План реализации

## Слайс 1: Operation Envelope + Admission

**Цель:** Deterministic Ledger Operation envelope + admission validation.

### S1.1: Создать пакет `consensus/`
- [ ] `src/aidn_hypervisor/consensus/__init__.py`
- [ ] `tests/consensus/__init__.py`

### S1.2: `consensus/models.py` — LedgerOperationEnvelope
- [ ] Pydantic модель `LedgerOperationEnvelope`
- [ ] Поля: `operation_id`, `operation_type`, `operation_version`, `protocol_version`, `origin_type`, `initiator_id`, `sender_wallet`, `sender_sequence`, `fee_payer`, `created_at`, `expires_at`, `target_epoch`, `payload`, `evidence_references`, `signatures`
- [ ] `OperationType` enum (WALLET_TRANSFER, SESSION_OPEN, DEPOSIT_LOCK, SESSION_SETTLE, ENDPOINT_PUBLISH, VALIDATION_REPORT, VALIDATOR_STAKE, REGISTRY_UPSERT, SNAPSHOT_COMMIT, EPOCH_TASK...)
- [ ] Deterministic serialization (`_canonical_json()`, `_operation_id()`)
- [ ] Тесты: `tests/consensus/test_models.py` (~20 тестов)

### S1.3: `consensus/admission.py` — AdmissionValidator
- [ ] `AdmissionValidator` class
- [ ] `validate_envelope()` — полная проверка
- [ ] Duplicate detection (finalized ID set)
- [ ] Sequence validation (monotonic increase per wallet)
- [ ] Expiry check
- [ ] Fee class validation
- [ ] Payload schema validation per operation_type
- [ ] Тесты: `tests/consensus/test_admission.py` (~25 тестов)

### S1.4: Интеграция с LedgerOperationService
- [ ] Добавить `submit_operation()` → admission → record
- [ ] Добавить `get_next_sequence()` / `advance_sequence()`
- [ ] Тесты: `tests/consensus/test_ledger_integration.py` (~10 тестов)

---

## Слайс 2: ABCI Application Boundary

**Цель:** AiDN ABCI application — admission, proposal, finalization, commitment.

### S2.1: `consensus/abcI.py` — ABCI интерфейс
- [ ] `ABCIResult` model (code, data, log, info, codespace, gas_used, gas_wanted)
- [ ] `ABCITag` model (key, value)
- [ ] `ABCIInfoResponse` model
- [ ] Тесты: базовые модели (~5 тестов)

### S2.2: `consensus/abcI.py` — AIDNABCIApplication (init + tx)
- [ ] `AIDNABCIApplication` class
- [ ] `info()` → app version, last_block_height
- [ ] `init_chain()` → genesis state initialization
- [ ] `process_proposal_transaction()` → admission check + mempool decision
- [ ] `reject_proposal_transaction()` → rejection reasons
- [ ] Тесты: `tests/consensus/test_abci_tx.py` (~20 тестов)

### S2.3: `consensus/abcI.py` — Block finalization
- [ ] `finalize_block()` → deterministic execution of ordered operations
- [ ] Atomicity enforcement (all-or-nothing per block)
- [ ] Event emission per operation
- [ ] State transition recording
- [ ] Тесты: `tests/consensus/test_abci_block.py` (~25 тестов)

### S2.4: `consensus/abcI.py` — Commit + Query + Snapshot
- [ ] `commit()` → state hash commitment
- [ ] `query()` → deterministic state queries
- [ ] `prepare_snapshot()` → export state
- [ ] `apply_snapshot()` → restore state
- [ ] Тесты: `tests/consensus/test_abci_lifecycle.py` (~20 тестов)

---

## Слайс 3: Consensus Service

**Цель:** Consensus Service как опциональный Hypervisor сервис.

### S3.1: `consensus/service.py` — ConsensusService (config + modes)
- [ ] `ConsensusServiceConfig` (node_id, is_validator, cometbft_endpoint, keys)
- [ ] `ConsensusService` class
- [ ] Validator mode vs non-validator mode
- [ ] Local state sync
- [ ] Тесты: `tests/consensus/test_service.py` (~15 тестов)

### S3.2: `consensus/service.py` — Transaction submission
- [ ] `submit_signed_operation()` → serialize → send to CometBFT
- [ ] Submission tracking (pending, admitted, included, finalized)
- [ ] Resubmission logic for non-finalized
- [ ] Inclusion monitoring
- [ ] Тесты: `tests/consensus/test_submission.py` (~20 тестов)

### S3.3: Интеграция с HypervisorService
- [ ] Wire `ConsensusService` into HypervisorService
- [ ] Optional enable/disable
- [ ] Graceful degradation when consensus unavailable
- [ ] Тесты: `tests/consensus/test_hypervisor_integration.py` (~10 тестов)

---

## Слайс 4: Block Execution Engine

**Цель:** Deterministic operation execution with state machine transitions.

### S4.1: `consensus/execution.py` — ExecutionEngine
- [ ] `ExecutionEngine` class
- [ ] `execute_operation()` → apply state transitions
- [ ] Per-operation-type handlers (dispatch table)
- [ ] State change tracking
- [ ] Тесты: `tests/consensus/test_execution.py` (~20 тестов)

### S4.2: `consensus/execution.py` — Event emission + atomicity
- [ ] Event emission per operation
- [ ] Atomicity: rollback on failure within block
- [ ] State root calculation
- [ ] Тесты: `tests/consensus/test_atomicity.py` (~15 тестов)

### S4.3: Integration with LedgerOperationService
- [ ] ExecutionEngine uses LedgerOperationService as state backend
- [ ] Post-execution recording
- [ ] Тесты: `tests/consensus/test_execution_integration.py` (~10 тестов)

---

## Слайс 5: Validator Set + Stake (ECO-0006)

**Цель:** Validator registration, stake, active set selection, participation tracking.

### S5.1: `consensus/validator.py` — Validator models
- [ ] `ConsensusValidator` model (node_id, operator_id, stake, status, voting_power)
- [ ] `ValidatorStatus` enum (CANDIDATE, ACTIVE, DOWNTIME, SUSPENDED, UNBONDING)
- [ ] `StakeRecord` model (amount, locked_at, unlock_at)
- [ ] Тесты: `tests/consensus/test_validator_models.py` (~15 тестов)

### S5.2: `consensus/validator.py` — ValidatorSetManager
- [ ] `ValidatorSetManager` class
- [ ] Candidate registration
- [ ] Stake lock/unlock
- [ ] Active set selection (equal voting power, target size)
- [ ] Epoch-based rotation
- [ ] Тесты: `tests/consensus/test_validator_set.py` (~25 тестов)

### S5.3: `consensus/validator.py` — Participation + Downtime
- [ ] Participation tracking (block sign, proposal)
- [ ] Downtime classification (ordinary, persistent, abandonment)
- [ ] Consequence application (warning, suspension, unbonding)
- [ ] Reward eligibility calculation
- [ ] Тесты: `tests/consensus/test_participation.py` (~20 тестов)

---

## Слайс 6: Epoch + Snapshots + Finalized State

**Цель:** Epoch boundaries, finalized state commitment, snapshot sync.

### S6.1: `consensus/epoch.py` — Epoch management
- [ ] `EpochConfig` (block_interval, blocks_per_epoch)
- [ ] `EpochState` (current_epoch, start_block, end_block, status)
- [ ] `EpochService` (transition, task scheduling)
- [ ] Тесты: `tests/consensus/test_epoch.py` (~15 тестов)

### S6.2: `consensus/commitment.py` — State commitment
- [ ] `StateCommitmentService`
- [ ] State hash calculation
- [ ] Finalized state verification
- [ ] Commitment record
- [ ] Тесты: `tests/consensus/test_commitment.py` (~15 тестов)

### S6.3: `consensus/snapshot.py` — Snapshot sync
- [ ] `SnapshotProducer` (create, export)
- [ ] `SnapshotConsumer` (validate, restore)
- [ ] Integration with ABCI snapshot hooks
- [ ] Тесты: `tests/consensus/test_snapshot.py` (~15 тестов)

---

## Общие метрики

- **Итого тестов:** ~250+
- **Новых файлов:** ~12
- **Новых пакетов:** `consensus/`
- **TDD:** тесты перед каждым компонентом
