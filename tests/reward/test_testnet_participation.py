from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.ledger.service import (
    STANDARD_NETWORK_FEE_Q_ATOMS,
    LedgerOperationService,
)
from aidn_hypervisor.testnet_participation import (
    Q_ATOMS_PER_Q,
    TestnetParticipationCalculator,
    build_testnet_heartbeat_evidence,
    build_testnet_participation_transfer_batch,
    load_testnet_participation_program,
)
from aidn_hypervisor.testnet_participation import (
    TestnetParticipantEnrollment as ParticipantEnrollment,
)
from aidn_hypervisor.testnet_participation import (
    TestnetParticipationProgram as ParticipationProgram,
)

START = datetime(2026, 9, 1, tzinfo=UTC)


def test_example_program_toml_has_the_launch_economics() -> None:
    program = load_testnet_participation_program(
        "config/testnet-participation.example.toml"
    )

    assert program.participation_window_seconds == 600
    assert program.settlement_period_seconds == 86_400
    assert program.reward_per_eligible_window_q_atoms == Q_ATOMS_PER_Q
    assert program.windows_per_settlement == 144


def _program() -> ParticipationProgram:
    return ParticipationProgram(
        program_id="testnet-alpha-participation-1",
        network_id="aidn-testnet",
        chain_id="aidn-testnet-1",
        active_from_epoch=10,
        compatible_protocol_versions=["0.1"],
    )


def _enrollment(**overrides) -> ParticipantEnrollment:
    values = {
        "node_id": "node-1",
        "owner_wallet": "q1owner",
        "reward_wallet": "q1reward",
        "registered_at": (START - timedelta(minutes=30)).isoformat(),
        "registered_epoch": 9,
    }
    values.update(overrides)
    return ParticipantEnrollment(**values)


def _heartbeats(window: int, *, count: int = 16, node_id: str = "node-1"):
    begin = START + timedelta(minutes=10 * window)
    return [
        build_testnet_heartbeat_evidence(
            evidence_id=f"{node_id}:{window}:{index}",
            node_id=node_id,
            network_id="aidn-testnet",
            chain_id="aidn-testnet-1",
            observed_at=(begin + timedelta(seconds=30 * index)).isoformat(),
            protocol_version="0.1",
        )
        for index in range(count)
    ]


def test_one_q_is_accrued_for_one_eligible_ten_minute_window() -> None:
    settlement = TestnetParticipationCalculator().calculate(
        _program(),
        protocol_epoch=10,
        source_epoch_transition_operation_id="epoch-transition:10",
        period_start=START.isoformat(),
        enrollments=[_enrollment()],
        heartbeats=_heartbeats(0),
    )

    assert settlement.total_reward_q_atoms == Q_ATOMS_PER_Q
    assert settlement.accruals[0].eligible_window_indices == [0]
    assert settlement.accruals[0].rejected_window_count == 143
    assert settlement.funding_source == "TESTNET_INCENTIVE_TREASURY"
    assert settlement.source_epoch_transition_operation_id == "epoch-transition:10"
    assert settlement.program_policy_hash == _program().policy_hash
    assert settlement.verify_integrity()


def test_daily_maximum_is_144_q_and_calculation_is_order_independent() -> None:
    evidence = [item for window in range(144) for item in _heartbeats(window)]
    calculator = TestnetParticipationCalculator()
    first = calculator.calculate(
        _program(),
        protocol_epoch=10,
        source_epoch_transition_operation_id="epoch-transition:10",
        period_start=START.isoformat(),
        enrollments=[_enrollment()],
        heartbeats=evidence,
    )
    second = calculator.calculate(
        _program(),
        protocol_epoch=10,
        source_epoch_transition_operation_id="epoch-transition:10",
        period_start=START.isoformat(),
        enrollments=[_enrollment()],
        heartbeats=reversed(evidence),
    )

    assert first.total_reward_q_atoms == 144 * Q_ATOMS_PER_Q
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_duplicate_heartbeats_cannot_fill_presence_slots() -> None:
    repeated = _heartbeats(0, count=1)[0]
    settlement = TestnetParticipationCalculator().calculate(
        _program(),
        protocol_epoch=10,
        source_epoch_transition_operation_id="epoch-transition:10",
        period_start=START.isoformat(),
        enrollments=[_enrollment()],
        heartbeats=[repeated] * 20,
    )
    assert settlement.total_reward_q_atoms == 0


def test_unqualified_or_banned_node_receives_no_reward() -> None:
    just_registered = _enrollment(registered_at=START.isoformat())
    banned = _enrollment(node_id="node-2", reward_wallet="q2", banned=True)
    settlement = TestnetParticipationCalculator().calculate(
        _program(),
        protocol_epoch=10,
        source_epoch_transition_operation_id="epoch-transition:10",
        period_start=START.isoformat(),
        enrollments=[just_registered, banned],
        heartbeats=[*_heartbeats(0), *_heartbeats(0, node_id="node-2")],
    )
    assert settlement.total_reward_q_atoms == 0


def test_wrong_network_version_or_unfinalized_evidence_is_ignored() -> None:
    invalid = [
        build_testnet_heartbeat_evidence(
            evidence_id=f"wrong-version:{index}",
            node_id="node-1",
            network_id="aidn-testnet",
            chain_id="aidn-testnet-1",
            observed_at=(START + timedelta(seconds=30 * index)).isoformat(),
            protocol_version="2",
        )
        for index in range(16)
    ]
    settlement = TestnetParticipationCalculator().calculate(
        _program(),
        protocol_epoch=10,
        source_epoch_transition_operation_id="epoch-transition:10",
        period_start=START.isoformat(),
        enrollments=[_enrollment()],
        heartbeats=invalid,
    )
    assert settlement.total_reward_q_atoms == 0


def test_daily_settlement_builds_one_replay_stable_treasury_transfer_per_node() -> None:
    settlement = TestnetParticipationCalculator().calculate(
        _program(),
        protocol_epoch=10,
        source_epoch_transition_operation_id="epoch-transition:10",
        period_start=START.isoformat(),
        enrollments=[_enrollment()],
        heartbeats=_heartbeats(0),
    )
    signer = lambda payload: "ed25519:" + ("ab" * 64)  # noqa: E731
    first = build_testnet_participation_transfer_batch(
        settlement,
        treasury_wallet="q1testnettreasury",
        first_sender_sequence=41,
        signer=signer,
        available_treasury_q_atoms=(Q_ATOMS_PER_Q + STANDARD_NETWORK_FEE_Q_ATOMS),
    )
    second = build_testnet_participation_transfer_batch(
        settlement,
        treasury_wallet="q1testnettreasury",
        first_sender_sequence=41,
        signer=signer,
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.verify_integrity()
    assert len(first.transfers) == 1
    transfer = first.transfers[0]
    assert transfer.operation_type == "WALLET_TRANSFER"
    assert transfer.sender_sequence == 41
    assert transfer.payload["amount"] == Q_ATOMS_PER_Q
    assert transfer.payload["node_id"] == "node-1"
    assert transfer.payload["settlement_hash"] == settlement.settlement_hash
    assert transfer.payload["source_epoch_transition_operation_id"] == "epoch-transition:10"
    assert transfer.payload["program_policy_hash"] == _program().policy_hash
    assert first.total_network_fee_q_atoms == STANDARD_NETWORK_FEE_Q_ATOMS


def test_treasury_batch_fails_before_submission_when_balance_is_too_small() -> None:
    settlement = TestnetParticipationCalculator().calculate(
        _program(),
        protocol_epoch=10,
        source_epoch_transition_operation_id="epoch-transition:10",
        period_start=START.isoformat(),
        enrollments=[_enrollment()],
        heartbeats=_heartbeats(0),
    )

    try:
        build_testnet_participation_transfer_batch(
            settlement,
            treasury_wallet="q1testnettreasury",
            first_sender_sequence=1,
            signer=lambda payload: "ed25519:" + ("ab" * 64),
            available_treasury_q_atoms=Q_ATOMS_PER_Q,
        )
    except ValueError as error:
        assert str(error) == "PARTICIPATION_TREASURY_BALANCE_INSUFFICIENT"
    else:
        raise AssertionError("insufficient treasury balance must fail closed")


def test_generated_batch_uses_consensus_transfer_and_replay_protection() -> None:
    settlement = TestnetParticipationCalculator().calculate(
        _program(),
        protocol_epoch=10,
        source_epoch_transition_operation_id="epoch-transition:10",
        period_start=START.isoformat(),
        enrollments=[_enrollment()],
        heartbeats=_heartbeats(0),
    )
    batch = build_testnet_participation_transfer_batch(
        settlement,
        treasury_wallet="q1testnettreasury",
        first_sender_sequence=1,
        signer=lambda payload: "ed25519:" + ("ab" * 64),
    )
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(
        wallet_id="q1testnettreasury",
        amount_q_atoms=batch.total_treasury_debit_q_atoms,
    )
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=settlement.period_end),
        strict_operation_coverage=True,
    )
    transaction = json.dumps(
        batch.transfers[0].model_dump(mode="json")
    ).encode("utf-8")

    first, first_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"P" * 32,
        txs=[transaction],
    )
    second, second_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"Q" * 32,
        txs=[transaction],
    )

    assert first.code == "ok"
    assert first_results[0].code == "ok"
    assert ledger.wallet_q_atom_balance("q1reward") == Q_ATOMS_PER_Q
    assert ledger.wallet_q_atom_balance("q1testnettreasury") == 0
    assert second.code == "ok"
    assert second_results[0].code == "rejected"
    assert "duplicate" in second_results[0].log
