from __future__ import annotations

import json

import pytest

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.recovery import (
    ValidatorRecoveryError,
    apply_validator_recovery_plan,
    build_validator_recovery_plan,
)
from aidn_hypervisor.consensus.state_store import ABCIStateStore
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.state import HypervisorStateSnapshot


def _operation(ledger: LedgerOperationService, *, wallet: str | None = None) -> dict:
    return ledger.record_operation(
        operation_type="REGISTRY_UPSERT",
        origin_type="wallet" if wallet else "protocol",
        fee_class="onboarding_exempt" if wallet else "protocol_sponsored",
        initiator_id=wallet or "recovery-test",
        sender_wallet=wallet,
        payload={"kind": "recovery-test"},
    )


def _write_fixture(tmp_path):
    abci_store = ABCIStateStore(tmp_path / "abci")
    canonical_ledger = LedgerOperationService()
    first = _operation(canonical_ledger)
    app = AIDNABCIApplication(ledger_service=canonical_ledger, state_store=abci_store)
    app.finalize_block(block_height=1, block_hash=b"a" * 32, txs=[])

    extra = _operation(canonical_ledger, wallet="wallet-extra")
    local = HypervisorStateSnapshot(
        ledger_operations=[first, extra],
        wallet_operation_sequences={"wallet-extra": 2},
    )
    hypervisor_path = tmp_path / "hypervisor.json"
    FileStateStore(hypervisor_path).save(local)
    return hypervisor_path, abci_store, extra["operation_id"]


def test_recovery_requires_explicit_discard_and_preserves_nonconsensus_state(tmp_path) -> None:
    hypervisor_path, abci_store, extra_id = _write_fixture(tmp_path)

    with pytest.raises(ValidatorRecoveryError, match="explicit discard list"):
        build_validator_recovery_plan(
            hypervisor_state_path=hypervisor_path,
            abci_state_path=abci_store.root,
            discard_operation_ids=[],
        )

    plan = build_validator_recovery_plan(
        hypervisor_state_path=hypervisor_path,
        abci_state_path=abci_store.root,
        discard_operation_ids=[extra_id],
    )

    assert plan.discarded_operation_ids == (extra_id,)
    assert [item.operation_id for item in plan.projected_state.ledger_operations] == [
        plan.projected_state.ledger_operations[0].operation_id
    ]
    assert plan.projected_state.wallet_operation_sequences == {}

    before = json.loads(hypervisor_path.read_text(encoding="utf-8"))
    backup = apply_validator_recovery_plan(
        plan=plan,
        hypervisor_state_path=hypervisor_path,
    )
    after = json.loads(hypervisor_path.read_text(encoding="utf-8"))

    assert backup.is_file()
    assert before["ledger_operations"][-1]["operation_id"] == extra_id
    assert after["ledger_operations"][-1]["operation_id"] != extra_id
    assert after["wallet_operation_sequences"] == {}


def test_recovery_rejects_unknown_discard_operation(tmp_path) -> None:
    hypervisor_path, abci_store, _extra_id = _write_fixture(tmp_path)

    with pytest.raises(ValidatorRecoveryError, match="explicit discard list"):
        build_validator_recovery_plan(
            hypervisor_state_path=hypervisor_path,
            abci_state_path=abci_store.root,
            discard_operation_ids=["not-present"],
        )
