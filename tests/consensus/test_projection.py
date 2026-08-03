from aidn_hypervisor.consensus.projection import (
    build_session_failure_evidence_envelope,
    build_session_force_settle_envelope,
)
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.settlement.models import AtomicSettlementTransition


def test_failure_projection_uses_a_new_consensus_identity_and_preserves_local_correlation():
    ledger = LedgerOperationService()
    local = ledger.commit_session_failure_evidence(
        session_id="session-projection-1",
        failure_class="CONSUMER_DISCONNECTED",
        failure_evidence_root="sha256:failure-projection-1",
    )

    envelope = build_session_failure_evidence_envelope(
        local,
        signatures=["ed25519:operator-1"],
    )

    assert envelope.operation_id != local["operation_id"]
    assert envelope.payload["local_operation_id"] == local["operation_id"]
    assert envelope.evidence_references == ["sha256:failure-projection-1"]
    LedgerOperationService().validate_consensus_session_failure_evidence(envelope)


def test_force_projection_requires_explicit_canonical_dependencies_and_signature():
    ledger = LedgerOperationService()
    local = ledger.record_operation(
        operation_type="SESSION_FORCE_SETTLE",
        origin_type="evidence_triggered",
        fee_class="session",
        initiator_id="session-projection-2",
        fee_payer="wallet:consumer",
        payload={
            "session_id": "session-projection-2",
            "failure_class": "ENDPOINT_UNAVAILABLE",
            "failure_evidence_root": "sha256:failure-projection-2",
            "settlement_id": "settlement-projection-2",
            "requested_payment_q_atoms": 0,
            "requested_refund_q_atoms": 100,
        },
        evidence_references=["sha256:failure-projection-2"],
        signatures=["ed25519:local-record"],
        created_at="2030-01-01T00:00:00Z",
    )
    transition = AtomicSettlementTransition(
        session_id="session-projection-2",
        settlement_id="settlement-projection-2",
        endpoint_payment_beneficiary="wallet:endpoint",
        consumer_refund_beneficiary="wallet:consumer",
        previously_released_to_endpoint_q_atoms=0,
        previously_refunded_to_consumer_q_atoms=0,
        previously_consumed_network_fees_q_atoms=0,
        credit_endpoint_q_atoms=0,
        total_locked_amount_q_atoms=100,
        credit_consumer_q_atoms=100,
        consume_network_fees_q_atoms=0,
        retain_dispute_reserve_q_atoms=0,
    )

    envelope = build_session_force_settle_envelope(
        local,
        funding_lock_operation_id="consensus-lock-2",
        failure_evidence_operation_id="consensus-failure-2",
        initiator_wallet="wallet:consumer",
        initiator_signature="ed25519:consumer-force",
        observed_at="2030-01-01T02:00:00Z",
        transition=transition.model_dump(mode="json"),
        signatures=["ed25519:consumer-force"],
    )

    assert envelope.operation_id != local["operation_id"]
    assert envelope.payload["local_operation_id"] == local["operation_id"]
    assert envelope.payload["funding_lock_operation_id"] == "consensus-lock-2"
    assert envelope.payload["failure_evidence_operation_id"] == "consensus-failure-2"
    assert "consensus-lock-2" in envelope.evidence_references
    assert "consensus-failure-2" in envelope.evidence_references


def test_force_projection_rejects_missing_initiator_authorization():
    ledger = LedgerOperationService()
    local = ledger.record_operation(
        operation_type="SESSION_FORCE_SETTLE",
        origin_type="evidence_triggered",
        fee_class="session",
        initiator_id="session-projection-3",
        fee_payer="wallet:consumer",
        payload={
            "session_id": "session-projection-3",
            "failure_class": "ENDPOINT_UNAVAILABLE",
            "failure_evidence_root": "sha256:failure-projection-3",
            "settlement_id": "settlement-projection-3",
        },
        created_at="2030-01-01T00:00:00Z",
    )

    try:
        build_session_force_settle_envelope(
            local,
            funding_lock_operation_id="consensus-lock-3",
            failure_evidence_operation_id="consensus-failure-3",
            initiator_wallet="wallet:consumer",
            initiator_signature="ed25519:consumer-force",
            observed_at="2030-01-01T02:00:00Z",
            transition={
                "session_id": "session-projection-3",
                "settlement_id": "settlement-projection-3",
            },
            signatures=[],
        )
    except ValueError as error:
        assert "authorization signature" in str(error)
    else:
        raise AssertionError("unsigned projection must fail closed")


def test_force_projection_rejects_transition_for_another_session():
    ledger = LedgerOperationService()
    local = ledger.record_operation(
        operation_type="SESSION_FORCE_SETTLE",
        origin_type="evidence_triggered",
        fee_class="session",
        initiator_id="session-projection-4",
        fee_payer="wallet:consumer",
        payload={
            "session_id": "session-projection-4",
            "failure_class": "ENDPOINT_UNAVAILABLE",
            "failure_evidence_root": "sha256:failure-projection-4",
            "settlement_id": "settlement-projection-4",
        },
        created_at="2030-01-01T00:00:00Z",
    )

    try:
        build_session_force_settle_envelope(
            local,
            funding_lock_operation_id="consensus-lock-4",
            failure_evidence_operation_id="consensus-failure-4",
            initiator_wallet="wallet:consumer",
            initiator_signature="ed25519:consumer-force",
            observed_at="2030-01-01T02:00:00Z",
            transition={
                "session_id": "another-session",
                "settlement_id": "settlement-projection-4",
            },
            signatures=["ed25519:consumer-force"],
        )
    except ValueError as error:
        assert "transition session binding" in str(error)
    else:
        raise AssertionError("cross-session transition must fail closed")
