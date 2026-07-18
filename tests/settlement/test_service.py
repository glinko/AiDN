import pytest
from pydantic import ValidationError

from aidn_hypervisor.accounting.models import UsageDimensionEvidence
from aidn_hypervisor.settlement import (
    RequestSettlementInput,
    SessionFundingAccount,
    SettlementAccountingTerms,
    SettlementChargeComponent,
    SettlementCorrection,
    SettlementDispute,
    SettlementEngine,
    SettlementError,
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
