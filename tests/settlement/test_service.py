import pytest
from pydantic import ValidationError

from aidn_hypervisor.accounting.models import UsageDimensionEvidence
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.settlement import (
    RequestSettlementInput,
    SessionFundingAccount,
    SettlementAccountingTerms,
    SettlementChargeComponent,
    SettlementCorrection,
    SettlementDispute,
    SettlementEngine,
    SettlementError,
    SessionSettlementAcceptance,
    TerminalChargePolicy,
)


def _funding(
    *,
    funding_class: str = "ESCROW_PREPAID",
    payment_reserve: int = 1_000,
    fee_reserve: int = 100,
    postpaid_credit_limit: int = 0,
) -> SessionFundingAccount:
    return SessionFundingAccount(
        session_id="session-1",
        funding_class=funding_class,
        consumer_funding_account="wallet-consumer",
        endpoint_payment_beneficiary="wallet-endpoint",
        consumer_refund_beneficiary="wallet-consumer",
        total_locked_amount_q_atoms=payment_reserve + fee_reserve,
        endpoint_payment_reserve_q_atoms=payment_reserve,
        network_fee_reserve_q_atoms=fee_reserve,
        postpaid_credit_limit_q_atoms=postpaid_credit_limit,
        unsettled_payment_reserve_q_atoms=payment_reserve,
        unsettled_fee_reserve_q_atoms=fee_reserve,
    )


def _dimension(
    *,
    dimension_id: str = "input_tokens",
    value: int | None = 120,
    availability: str = "AVAILABLE",
    authority: str | None = "AUTHORITATIVE_PROVIDER",
    billing_eligible: bool = True,
) -> UsageDimensionEvidence:
    source = None
    if authority == "AUTHORITATIVE_PROVIDER":
        source = {
            "source_type": "PROVIDER_USAGE_RESPONSE",
            "source_id": "provider-receipt-1",
        }
    return UsageDimensionEvidence(
        dimension_id=dimension_id,
        unit="token",
        value=value,
        availability=availability,
        authority=authority,
        billing_eligible=billing_eligible,
        source_reference=source,
    )


def _request(
    *,
    request_id: str = "request-1",
    ceiling: int = 1_000,
    terminal_state: str = "COMPLETED",
    dimensions: list[UsageDimensionEvidence] | None = None,
    usage_chain_conflicted: bool = False,
) -> RequestSettlementInput:
    return RequestSettlementInput(
        session_id="session-1",
        request_id=request_id,
        request_charge_ceiling_q_atoms=ceiling,
        accounting_contract_hash="sha256:contract-1",
        terminal_state=terminal_state,
        result_reference="sha256:result-1",
        final_usage_report_id=f"usage-{request_id}",
        final_usage_report_hash=f"sha256:usage-{request_id}",
        usage_sequence=1,
        usage_chain_conflicted=usage_chain_conflicted,
        dimensions=dimensions if dimensions is not None else [_dimension()],
    )


def _metered_terms(**component_overrides) -> SettlementAccountingTerms:
    component = {
        "component_id": "input-token-charge",
        "dimension_id": "input_tokens",
        "unit_price_q_atoms": 2,
        "required_authority": "AUTHORITATIVE_PROVIDER",
    }
    component.update(component_overrides)
    return SettlementAccountingTerms(
        accounting_contract_hash="sha256:contract-1",
        accounting_mode="provider_metered",
        components=[SettlementChargeComponent(**component)],
    )


def test_funding_account_enforces_separate_reserve_conservation() -> None:
    with pytest.raises(ValidationError, match="payment plus fee reserves"):
        SessionFundingAccount(
            session_id="session-1",
            funding_class="ESCROW_PREPAID",
            consumer_funding_account="wallet-consumer",
            endpoint_payment_beneficiary="wallet-endpoint",
            consumer_refund_beneficiary="wallet-consumer",
            total_locked_amount_q_atoms=1_101,
            endpoint_payment_reserve_q_atoms=1_000,
            network_fee_reserve_q_atoms=100,
            unsettled_payment_reserve_q_atoms=1_000,
            unsettled_fee_reserve_q_atoms=100,
        )


def test_canonical_ledger_locks_and_finalizes_q_atom_settlement_idempotently() -> None:
    ledger = LedgerOperationService()
    funding = _funding()
    ledger.credit_wallet_q_atoms(
        wallet_id=funding.consumer_funding_account,
        amount_q_atoms=funding.total_locked_amount_q_atoms,
    )

    locked = ledger.lock_session_funding(
        funding,
        created_at="2026-07-18T00:00:00+00:00",
    )
    assert ledger.lock_session_funding(funding) == locked
    evaluation = SettlementEngine().evaluate_session(
        funding=locked,
        session_contract_hash="sha256:session-contract",
        effective_terms_hash="sha256:effective-terms",
        request_inputs=[_request()],
        terms_by_hash={"sha256:contract-1": _metered_terms()},
        maximum_session_charge_q_atoms=1_000,
        actual_network_fees_q_atoms=20,
        session_close_reference="sha256:close",
    )

    finalized = ledger.apply_settlement_evaluation(
        evaluation,
        created_at="2026-07-18T00:01:00+00:00",
    )
    repeated = ledger.apply_settlement_evaluation(evaluation)

    assert ledger.wallet_q_atom_balance("wallet-consumer") == 840
    assert ledger.wallet_q_atom_balance("wallet-endpoint") == 240
    assert finalized == repeated
    assert finalized.released_to_endpoint_q_atoms == 240
    assert finalized.consumer_payment_refund_q_atoms == 760
    assert finalized.consumer_fee_refund_q_atoms == 80
    assert finalized.consumed_network_fees_q_atoms == 20
    assert [item["operation_type"] for item in ledger.list_operations()] == [
        "SESSION_ESCROW_LOCK",
        "SESSION_SETTLEMENT_FINALIZE",
    ]


def test_canonical_ledger_settlement_state_survives_restore() -> None:
    ledger = LedgerOperationService()
    funding = _funding(payment_reserve=100, fee_reserve=0)
    ledger.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=100)
    locked = ledger.lock_session_funding(funding)
    evaluation = SettlementEngine().evaluate_session(
        funding=locked,
        session_contract_hash="sha256:session-contract",
        effective_terms_hash="sha256:effective-terms",
        request_inputs=[_request(ceiling=100, dimensions=[_dimension(value=50)])],
        terms_by_hash={"sha256:contract-1": _metered_terms()},
        maximum_session_charge_q_atoms=100,
        actual_network_fees_q_atoms=0,
        session_close_reference="sha256:close",
    )
    ledger.apply_settlement_evaluation(evaluation)

    restored = LedgerOperationService()
    settlement_state = ledger.snapshot_settlement_state()
    restored.restore(
        operations=ledger.snapshot_operations(),
        wallet_sequences=ledger.snapshot_wallet_sequences(),
        **settlement_state,
    )

    assert restored.wallet_q_atom_balance("wallet-consumer") == 0
    assert restored.wallet_q_atom_balance("wallet-endpoint") == 100
    assert restored.get_session_funding_account("session-1").funding_state == "RELEASED"


def test_canonical_ledger_requires_exact_acceptance_before_cooperative_finalization() -> None:
    ledger = LedgerOperationService()
    funding = _funding(payment_reserve=100, fee_reserve=0)
    ledger.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=100)
    locked = ledger.lock_session_funding(funding)
    terms = SettlementAccountingTerms(
        accounting_contract_hash="sha256:contract-1",
        accounting_mode="fixed_price",
        components=[SettlementChargeComponent(component_id="fixed", fixed_amount_q_atoms=100)],
    )
    evaluation = SettlementEngine().evaluate_session(
        funding=locked,
        session_contract_hash="sha256:session-contract",
        effective_terms_hash="sha256:effective-terms",
        request_inputs=[_request(ceiling=100, dimensions=[])],
        terms_by_hash={"sha256:contract-1": terms},
        maximum_session_charge_q_atoms=100,
        actual_network_fees_q_atoms=0,
        session_close_reference="sha256:close",
    )

    ledger.propose_settlement(evaluation)
    with pytest.raises(ValueError, match="acceptance"):
        ledger.finalize_accepted_settlement(evaluation)
    acceptance = SessionSettlementAcceptance(
        settlement_id=evaluation.proposal.settlement_id,
        session_id="session-1",
        settlement_input_root=evaluation.proposal.settlement_input_root,
        accepted_endpoint_payment_q_atoms=100,
        accepted_consumer_refund_q_atoms=0,
        accepted_network_fees_q_atoms=0,
        consumer_signature="consumer-signature",
        accepted_at="2026-07-18T00:01:00+00:00",
    )

    ledger.accept_settlement(acceptance)
    finalized = ledger.finalize_accepted_settlement(evaluation)

    assert finalized.funding_state == "RELEASED"
    assert ledger.wallet_q_atom_balance("wallet-endpoint") == 100
    assert [item["operation_type"] for item in ledger.list_operations()] == [
        "SESSION_ESCROW_LOCK",
        "SESSION_SETTLEMENT_PROPOSE",
        "SESSION_SETTLEMENT_ACCEPT",
        "SESSION_SETTLEMENT_FINALIZE",
    ]


def test_forced_fixed_price_settlement_requires_timeout_and_completed_evidence() -> None:
    ledger = LedgerOperationService()
    funding = _funding(payment_reserve=100, fee_reserve=0)
    ledger.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=100)
    locked = ledger.lock_session_funding(funding)
    terms = SettlementAccountingTerms(
        accounting_contract_hash="sha256:contract-1",
        accounting_mode="fixed_price",
        components=[SettlementChargeComponent(component_id="fixed", fixed_amount_q_atoms=100)],
    )
    evaluation = SettlementEngine().evaluate_session(
        funding=locked,
        session_contract_hash="sha256:session-contract",
        effective_terms_hash="sha256:effective-terms",
        request_inputs=[_request(ceiling=100, dimensions=[])],
        terms_by_hash={"sha256:contract-1": terms},
        maximum_session_charge_q_atoms=100,
        actual_network_fees_q_atoms=0,
        session_close_reference="sha256:close",
    )

    with pytest.raises(ValueError, match="timeout"):
        ledger.force_finalize_fixed_price_settlement(
            evaluation,
            reason="CONSUMER_TIMEOUT_AFTER_COMPLETED_FIXED_PRICE",
            force_after="2026-07-18T00:01:00+00:00",
            now="2026-07-18T00:00:59+00:00",
        )
    finalized = ledger.force_finalize_fixed_price_settlement(
        evaluation,
        reason="CONSUMER_TIMEOUT_AFTER_COMPLETED_FIXED_PRICE",
        force_after="2026-07-18T00:01:00+00:00",
        now="2026-07-18T00:01:00+00:00",
    )

    assert finalized.funding_state == "RELEASED"
    assert ledger.wallet_q_atom_balance("wallet-endpoint") == 100
    assert [item["operation_type"] for item in ledger.list_operations()][-2:] == [
        "SESSION_FORCED_SETTLEMENT",
        "SESSION_SETTLEMENT_FINALIZE",
    ]


def test_request_charge_is_capped_and_excess_is_endpoint_absorbed() -> None:
    record = SettlementEngine().evaluate_request(
        _request(ceiling=200),
        _metered_terms(),
    )

    assert record.raw_calculated_charge_q_atoms == 240
    assert record.policy_adjusted_charge_q_atoms == 240
    assert record.capped_request_charge_q_atoms == 200
    assert record.endpoint_absorbed_amount_q_atoms == 40
    assert record.dispute_state == "NONE"


def test_fixed_fallback_handles_unavailable_provider_usage_without_invention() -> None:
    terms = _metered_terms(
        unavailable_value_policy="FIXED_FALLBACK",
        fallback_amount_q_atoms=75,
    )
    request = _request(
        dimensions=[
            _dimension(value=None, availability="UNAVAILABLE", authority=None)
        ]
    )

    record = SettlementEngine().evaluate_request(request, terms)

    assert record.capped_request_charge_q_atoms == 75
    assert record.billable_components[0].source_value is None
    assert "Usage unavailable" in record.billable_components[0].limitation


def test_fixed_price_can_settle_when_final_usage_is_missing_under_contract() -> None:
    terms = SettlementAccountingTerms(
        accounting_contract_hash="sha256:contract-1",
        accounting_mode="fixed_price",
        components=[
            SettlementChargeComponent(
                component_id="fixed-request",
                fixed_amount_q_atoms=90,
            )
        ],
    )
    request_payload = _request(dimensions=[]).model_dump(mode="json")
    request_payload.update(
        {
            "final_usage_report_id": None,
            "final_usage_report_hash": None,
        }
    )
    request = RequestSettlementInput.model_validate(request_payload)

    record = SettlementEngine().evaluate_request(request, terms)

    assert record.capped_request_charge_q_atoms == 90
    assert "Final Usage Report missing" in record.limitations


def test_diagnostic_dimension_cannot_create_consumer_liability() -> None:
    request = _request(dimensions=[_dimension(billing_eligible=False)])

    record = SettlementEngine().evaluate_request(request, _metered_terms())

    assert record.capped_request_charge_q_atoms == 0
    assert record.dispute_state == "DISPUTED"
    assert record.disputed_amount_q_atoms == request.request_charge_ceiling_q_atoms


def test_terminal_policy_is_applied_before_request_ceiling() -> None:
    terms = _metered_terms()
    terms = SettlementAccountingTerms.model_validate(
        {
            **terms.model_dump(mode="json"),
            "terminal_policies": {
                "PARTIAL": {
                    "mode": "PROPORTIONAL_BPS",
                    "proportional_basis_points": 5_000,
                }
            },
            "terms_hash": None,
        }
    )

    record = SettlementEngine().evaluate_request(
        _request(terminal_state="PARTIAL"),
        terms,
    )

    assert record.raw_calculated_charge_q_atoms == 240
    assert record.policy_adjusted_charge_q_atoms == 120
    assert record.capped_request_charge_q_atoms == 120


def test_dispute_review_does_not_release_the_disputed_terminal_charge() -> None:
    record = SettlementEngine().evaluate_request(
        _request(terminal_state="FAILED", ceiling=500),
        _metered_terms(),
    )

    assert record.raw_calculated_charge_q_atoms == 240
    assert record.capped_request_charge_q_atoms == 0
    assert record.dispute_state == "DISPUTED"
    assert record.disputed_amount_q_atoms == 500


def test_session_evaluation_is_request_first_and_atomically_conserves_funds() -> None:
    engine = SettlementEngine()
    terms = _metered_terms()
    first = _request(request_id="request-1", ceiling=200)
    second = _request(
        request_id="request-2",
        ceiling=300,
        usage_chain_conflicted=True,
    )

    evaluation = engine.evaluate_session(
        funding=_funding(),
        session_contract_hash="sha256:session-contract",
        effective_terms_hash="sha256:effective-terms",
        request_inputs=[first, second],
        terms_by_hash={terms.accounting_contract_hash: terms},
        maximum_session_charge_q_atoms=900,
        actual_network_fees_q_atoms=20,
        session_close_reference="sha256:session-close",
    )

    proposal = evaluation.proposal
    assert proposal.gross_session_charge_q_atoms == 200
    assert proposal.final_endpoint_payment_q_atoms == 200
    assert proposal.dispute_reserve_q_atoms == 300
    assert proposal.consumer_payment_refund_q_atoms == 500
    assert proposal.consumer_fee_refund_q_atoms == 80
    assert proposal.settlement_mode == "PARTIAL_UNDISPUTED"
    assert evaluation.transition.credit_endpoint_q_atoms == 200
    assert evaluation.transition.credit_consumer_q_atoms == 580
    assert evaluation.transition.retain_dispute_reserve_q_atoms == 300


def test_validation_zero_refunds_payment_reserve_and_keeps_network_fee_separate() -> None:
    terms = _metered_terms()
    evaluation = SettlementEngine().evaluate_session(
        funding=_funding(funding_class="VALIDATION"),
        session_contract_hash="sha256:session-contract",
        effective_terms_hash="sha256:effective-terms",
        request_inputs=[_request()],
        terms_by_hash={terms.accounting_contract_hash: terms},
        maximum_session_charge_q_atoms=1_000,
        actual_network_fees_q_atoms=20,
        session_close_reference="sha256:validation-close",
    )

    assert evaluation.proposal.settlement_mode == "VALIDATION_ZERO"
    assert evaluation.proposal.final_endpoint_payment_q_atoms == 0
    assert evaluation.proposal.consumer_payment_refund_q_atoms == 1_000
    assert evaluation.proposal.actual_network_fees_q_atoms == 20
    assert evaluation.transition.credit_consumer_q_atoms == 1_080


def test_postpaid_evaluation_creates_obligation_without_fabricating_escrow() -> None:
    terms = _metered_terms()
    funding = _funding(
        funding_class="TRUSTED_POSTPAID",
        payment_reserve=0,
        fee_reserve=0,
        postpaid_credit_limit=500,
    )

    evaluation = SettlementEngine().evaluate_session(
        funding=funding,
        session_contract_hash="sha256:session-contract",
        effective_terms_hash="sha256:effective-terms",
        request_inputs=[_request(ceiling=500)],
        terms_by_hash={terms.accounting_contract_hash: terms},
        maximum_session_charge_q_atoms=500,
        actual_network_fees_q_atoms=0,
        session_close_reference="sha256:postpaid-close",
    )

    assert evaluation.proposal.settlement_mode == "POSTPAID_OBLIGATION"
    assert evaluation.proposal.final_endpoint_payment_q_atoms == 240
    assert evaluation.transition.credit_endpoint_q_atoms == 0
    assert evaluation.transition.postpaid_obligation_q_atoms == 240


def test_session_maximum_charge_cannot_exceed_reserved_or_postpaid_limit() -> None:
    with pytest.raises(SettlementError) as error:
        SettlementEngine().evaluate_session(
            funding=_funding(payment_reserve=100),
            session_contract_hash="sha256:session-contract",
            effective_terms_hash="sha256:effective-terms",
            request_inputs=[],
            terms_by_hash={},
            maximum_session_charge_q_atoms=101,
            actual_network_fees_q_atoms=0,
            session_close_reference="sha256:session-close",
        )

    assert error.value.code == "SETTLEMENT_MAXIMUM_CHARGE_EXCEEDED"


def test_dispute_amount_is_bounded_by_claimed_payment_difference() -> None:
    with pytest.raises(ValidationError, match="claimed payment difference"):
        SettlementDispute(
            dispute_id="dispute-1",
            settlement_id="settlement-1",
            session_id="session-1",
            dispute_class="USAGE_VALUE",
            claimed_endpoint_payment_q_atoms=300,
            accepted_endpoint_payment_q_atoms=200,
            disputed_amount_q_atoms=101,
            evidence_root="sha256:evidence",
            opened_at="2026-07-18T00:00:00+00:00",
            claimant_signature="consumer-signature",
        )


def test_correction_record_must_conserve_q_and_preserve_prior_result() -> None:
    correction = SettlementCorrection(
        correction_id="correction-1",
        settlement_id="settlement-1",
        correction_reason="duplicate endpoint credit",
        prior_result_hash="sha256:prior-result",
        endpoint_payment_delta_q_atoms=-10,
        consumer_refund_delta_q_atoms=10,
        network_fee_delta_q_atoms=0,
        authorization_reference="governance:resolution-1",
        evidence_root="sha256:evidence",
        created_at="2026-07-18T00:00:00+00:00",
        correction_signature="authority-signature",
    )

    assert correction.correction_hash.startswith("sha256:")

    with pytest.raises(ValidationError, match="conserve Q"):
        SettlementCorrection.model_validate(
            {
                **correction.model_dump(mode="json"),
                "consumer_refund_delta_q_atoms": 9,
                "correction_hash": None,
            }
        )
