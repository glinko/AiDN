from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, Decimal, InvalidOperation

from aidn_hypervisor.settlement.models import (
    AtomicSettlementTransition,
    BillableComponentResult,
    RequestSettlementInput,
    RequestSettlementRecord,
    SessionFundingAccount,
    SessionSettlementProposal,
    SettlementAccountingTerms,
    SettlementEvaluation,
    SettlementInputSet,
    TerminalChargePolicy,
    canonical_hash,
)


class SettlementError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _round_ratio(numerator: int, denominator: int, mode: str) -> int:
    quotient, remainder = divmod(numerator, denominator)
    if mode == "DOWN" or remainder == 0:
        return quotient
    if mode == "UP":
        return quotient + 1
    doubled = remainder * 2
    if doubled < denominator:
        return quotient
    if doubled > denominator:
        return quotient + 1
    return quotient if quotient % 2 == 0 else quotient + 1


class SettlementEngine:
    def evaluate_request(
        self,
        request: RequestSettlementInput,
        terms: SettlementAccountingTerms,
        *,
        effective_terms_hash: str | None = None,
    ) -> RequestSettlementRecord:
        if request.accounting_contract_hash != terms.accounting_contract_hash:
            raise SettlementError(
                "SETTLEMENT_ACCOUNTING_CONTRACT_MISMATCH",
                "Request and Settlement Accounting Contract hashes differ",
            )
        if request.usage_chain_conflicted or (
            not request.usage_chain_valid
            and request.final_usage_report_hash is not None
        ):
            limitation = (
                "Usage chain conflict"
                if request.usage_chain_conflicted
                else "Usage chain is invalid"
            )
            return self._disputed_record(request, limitation)

        dimensions = {item.dimension_id: item for item in request.dimensions}
        component_results: list[BillableComponentResult] = []
        limitations = list(request.limitations)
        raw_charge = 0
        disputed = False

        for component in terms.components:
            if component.dimension_id is None:
                charge = int(component.fixed_amount_q_atoms or 0)
                component_results.append(
                    BillableComponentResult(
                        component_id=component.component_id,
                        charge_q_atoms=charge,
                    )
                )
                raw_charge += charge
                continue

            dimension = dimensions.get(component.dimension_id)
            charge, source_value, limitation, is_disputed = self._evaluate_component(
                component=component,
                dimension=dimension,
                dimensions=dimensions,
            )
            component_results.append(
                BillableComponentResult(
                    component_id=component.component_id,
                    dimension_id=component.dimension_id,
                    source_value=source_value,
                    charge_q_atoms=charge,
                    disputed=is_disputed,
                    limitation=limitation,
                )
            )
            raw_charge += charge
            disputed = disputed or is_disputed
            if limitation:
                limitations.append(limitation)

        policy = self._terminal_policy(request, terms)
        policy_adjusted, policy_disputed = self._apply_terminal_policy(
            raw_charge,
            policy,
        )
        disputed = disputed or policy_disputed
        if (
            request.minimum_charge_eligible
            and policy_adjusted > 0
            and not policy_disputed
        ):
            policy_adjusted = max(policy_adjusted, terms.minimum_charge_q_atoms)
        capped_charge = min(
            policy_adjusted,
            request.request_charge_ceiling_q_atoms,
        )
        absorbed = max(0, policy_adjusted - request.request_charge_ceiling_q_atoms)
        disputed_amount = (
            max(0, request.request_charge_ceiling_q_atoms - capped_charge)
            if disputed
            else 0
        )
        billable_ids = {
            item.dimension_id for item in terms.components if item.dimension_id is not None
        }
        nonbillable = sorted(set(dimensions) - billable_ids)
        return RequestSettlementRecord(
            session_id=request.session_id,
            request_id=request.request_id,
            request_charge_ceiling_q_atoms=request.request_charge_ceiling_q_atoms,
            effective_terms_hash=effective_terms_hash or request.effective_terms_hash,
            accounting_contract_hash=request.accounting_contract_hash,
            terminal_state=request.terminal_state,
            result_reference=request.result_reference,
            final_usage_report_id=request.final_usage_report_id,
            final_usage_report_hash=request.final_usage_report_hash,
            raw_calculated_charge_q_atoms=raw_charge,
            policy_adjusted_charge_q_atoms=policy_adjusted,
            capped_request_charge_q_atoms=capped_charge,
            endpoint_absorbed_amount_q_atoms=absorbed,
            disputed_amount_q_atoms=disputed_amount,
            billable_components=component_results,
            nonbillable_components=nonbillable,
            limitations=limitations,
            dispute_state="DISPUTED" if disputed else "NONE",
        )

    def evaluate_session(
        self,
        *,
        funding: SessionFundingAccount,
        session_contract_hash: str,
        effective_terms_hash: str,
        request_inputs: list[RequestSettlementInput],
        terms_by_hash: dict[str, SettlementAccountingTerms],
        maximum_session_charge_q_atoms: int,
        actual_network_fees_q_atoms: int,
        session_close_reference: str,
        settlement_sequence: int = 1,
        accepted_checkpoint_references: list[str] | None = None,
        dispute_references: list[str] | None = None,
        failure_references: list[str] | None = None,
        artifact_commitments: list[str] | None = None,
        settlement_mode: str | None = None,
        proposal_expiration: str | None = None,
    ) -> SettlementEvaluation:
        payment_limit = (
            funding.postpaid_credit_limit_q_atoms
            if funding.funding_class == "TRUSTED_POSTPAID"
            else funding.endpoint_payment_reserve_q_atoms
        )
        if maximum_session_charge_q_atoms > payment_limit:
            raise SettlementError(
                "SETTLEMENT_MAXIMUM_CHARGE_EXCEEDED",
                "Maximum Session Charge exceeds Endpoint Payment Reserve",
            )
        if actual_network_fees_q_atoms > funding.network_fee_reserve_q_atoms:
            raise SettlementError(
                "SETTLEMENT_NETWORK_FEE_INVALID",
                "Network Fees exceed Network Fee Reserve",
            )
        records: list[RequestSettlementRecord] = []
        for request in request_inputs:
            if request.session_id != funding.session_id:
                raise SettlementError(
                    "SETTLEMENT_REQUEST_RECORD_INVALID",
                    "Request belongs to another Session",
                )
            if (
                request.effective_terms_hash is not None
                and request.effective_terms_hash != effective_terms_hash
            ):
                raise SettlementError(
                    "SETTLEMENT_EFFECTIVE_TERMS_MISMATCH",
                    "Request and Settlement Effective Terms hashes differ",
                )
            try:
                terms = terms_by_hash[request.accounting_contract_hash]
            except KeyError as exc:
                raise SettlementError(
                    "SETTLEMENT_ACCOUNTING_CONTRACT_MISMATCH",
                    "Settlement terms are unavailable",
                ) from exc
            records.append(
                self.evaluate_request(
                    request,
                    terms,
                    effective_terms_hash=effective_terms_hash,
                )
            )

        input_set = SettlementInputSet(
            session_id=funding.session_id,
            session_contract_hash=session_contract_hash,
            effective_terms_hash=effective_terms_hash,
            endpoint_payment_beneficiary=funding.endpoint_payment_beneficiary,
            consumer_refund_beneficiary=funding.consumer_refund_beneficiary,
            funding_state_reference=funding.funding_state_hash,
            request_settlement_records=records,
            final_usage_chain_heads={
                item.request_id: item.final_usage_report_hash
                for item in records
                if item.final_usage_report_hash is not None
            },
            accepted_checkpoint_references=accepted_checkpoint_references or [],
            dispute_references=dispute_references or [],
            failure_references=failure_references or [],
            artifact_commitments=artifact_commitments or [],
            session_close_reference=session_close_reference,
        )
        gross_charge = sum(item.capped_request_charge_q_atoms for item in records)
        capped_session_charge = min(gross_charge, maximum_session_charge_q_atoms)
        session_absorbed = sum(
            item.endpoint_absorbed_amount_q_atoms for item in records
        ) + max(0, gross_charge - maximum_session_charge_q_atoms)

        validation_zero = funding.funding_class == "VALIDATION"
        free_zero = funding.funding_class == "FREE"
        postpaid = funding.funding_class == "TRUSTED_POSTPAID"
        final_endpoint_payment = 0 if validation_zero or free_zero else capped_session_charge
        if final_endpoint_payment < funding.released_to_endpoint_q_atoms:
            raise SettlementError(
                "SETTLEMENT_DOUBLE_PAYMENT",
                "Previously released Endpoint Payment exceeds final charge",
            )
        requested_endpoint_payment = 0 if postpaid else (
            final_endpoint_payment - funding.released_to_endpoint_q_atoms
        )
        requested_dispute = 0 if validation_zero or free_zero else sum(
            item.disputed_amount_q_atoms for item in records
        )
        available_dispute_reserve = max(
            0,
            funding.endpoint_payment_reserve_q_atoms
            - final_endpoint_payment
            - funding.consumer_payment_refund_q_atoms,
        )
        dispute_reserve = min(requested_dispute, available_dispute_reserve)
        consumer_payment_refund = max(
            0,
            funding.endpoint_payment_reserve_q_atoms
            - final_endpoint_payment
            - dispute_reserve,
        )
        consumer_fee_refund = (
            funding.network_fee_reserve_q_atoms - actual_network_fees_q_atoms
        )
        additional_consumer_refund = (
            consumer_payment_refund
            + consumer_fee_refund
            - funding.consumer_payment_refund_q_atoms
            - funding.consumer_fee_refund_q_atoms
        )
        if additional_consumer_refund < 0:
            raise SettlementError(
                "SETTLEMENT_REFUND_INVALID",
                "Previously refunded amount exceeds final Consumer refund",
            )
        additional_network_fees = (
            actual_network_fees_q_atoms - funding.consumed_network_fees_q_atoms
        )
        if additional_network_fees < 0:
            raise SettlementError(
                "SETTLEMENT_NETWORK_FEE_INVALID",
                "Previously consumed Network Fees exceed final fees",
            )

        if settlement_mode is None:
            if validation_zero:
                settlement_mode = "VALIDATION_ZERO"
            elif free_zero or (final_endpoint_payment == 0 and dispute_reserve == 0):
                settlement_mode = "COOPERATIVE_ZERO"
            elif dispute_reserve > 0:
                settlement_mode = "PARTIAL_UNDISPUTED"
            elif funding.funding_class == "TRUSTED_POSTPAID":
                settlement_mode = "POSTPAID_OBLIGATION"
            else:
                settlement_mode = "COOPERATIVE_FINAL"

        settlement_id = canonical_hash(
            {
                "session_id": funding.session_id,
                "settlement_sequence": settlement_sequence,
                "settlement_input_root": input_set.settlement_input_root,
            }
        )
        proposal = SessionSettlementProposal(
            settlement_id=settlement_id,
            settlement_sequence=settlement_sequence,
            session_id=funding.session_id,
            settlement_input_root=input_set.settlement_input_root,
            request_settlement_root=input_set.request_settlement_root,
            usage_chain_root=input_set.usage_chain_root,
            checkpoint_root=input_set.checkpoint_root,
            gross_session_charge_q_atoms=gross_charge,
            capped_session_charge_q_atoms=capped_session_charge,
            final_endpoint_payment_q_atoms=final_endpoint_payment,
            requested_endpoint_payment_q_atoms=requested_endpoint_payment,
            consumer_payment_refund_q_atoms=consumer_payment_refund,
            actual_network_fees_q_atoms=actual_network_fees_q_atoms,
            consumer_fee_refund_q_atoms=consumer_fee_refund,
            disputed_amount_q_atoms=requested_dispute,
            dispute_reserve_q_atoms=dispute_reserve,
            endpoint_absorbed_amount_q_atoms=session_absorbed,
            settlement_mode=settlement_mode,
            proposal_expiration=proposal_expiration,
        )
        transition = AtomicSettlementTransition(
            session_id=funding.session_id,
            settlement_id=settlement_id,
            endpoint_payment_beneficiary=funding.endpoint_payment_beneficiary,
            consumer_refund_beneficiary=funding.consumer_refund_beneficiary,
            previously_released_to_endpoint_q_atoms=(
                funding.released_to_endpoint_q_atoms
            ),
            previously_refunded_to_consumer_q_atoms=(
                funding.consumer_payment_refund_q_atoms
                + funding.consumer_fee_refund_q_atoms
            ),
            previously_consumed_network_fees_q_atoms=(
                funding.consumed_network_fees_q_atoms
            ),
            credit_endpoint_q_atoms=requested_endpoint_payment,
            credit_consumer_q_atoms=additional_consumer_refund,
            consume_network_fees_q_atoms=additional_network_fees,
            retain_dispute_reserve_q_atoms=dispute_reserve,
            postpaid_obligation_q_atoms=(final_endpoint_payment if postpaid else 0),
            total_locked_amount_q_atoms=funding.total_locked_amount_q_atoms,
        )
        return SettlementEvaluation(
            input_set=input_set,
            proposal=proposal,
            transition=transition,
        )

    def _evaluate_component(self, *, component, dimension, dimensions):
        if dimension is None or dimension.availability in {
            "UNAVAILABLE",
            "NOT_APPLICABLE",
        }:
            return self._fallback_component(component, dimensions, "Usage unavailable")
        if not dimension.billing_eligible:
            return 0, None, "Dimension is diagnostic-only", True
        if (
            component.required_authority is not None
            and dimension.authority != component.required_authority
        ):
            return self._fallback_component(component, dimensions, "Usage authority mismatch")
        if dimension.availability == "PARTIAL" and (
            component.unavailable_value_policy != "PARTIAL_CHARGE"
        ):
            return self._fallback_component(component, dimensions, "Usage is partial")
        value = self._scaled_integer_value(
            dimension.value,
            component.dimension_id,
            scale=component.source_value_scale,
            rounding=component.rounding,
        )
        charge = _round_ratio(
            value * component.unit_price_q_atoms,
            component.unit_divisor,
            component.rounding,
        )
        return charge, value, None, False

    def _fallback_component(self, component, dimensions, reason):
        policy = component.unavailable_value_policy
        if policy == "ZERO_VARIABLE_COMPONENT":
            return 0, None, reason, False
        if policy == "FIXED_FALLBACK":
            return int(component.fallback_amount_q_atoms or 0), None, reason, False
        if policy == "OBSERVABLE_FALLBACK":
            fallback = dimensions.get(component.fallback_dimension_id)
            if (
                fallback is not None
                and fallback.availability in {"AVAILABLE", "PARTIAL"}
                and fallback.authority in {"DETERMINISTIC_LOCAL", "OBSERVABLE_LOCAL"}
                and fallback.billing_eligible
            ):
                value = self._scaled_integer_value(
                    fallback.value,
                    component.fallback_dimension_id,
                    scale=component.source_value_scale,
                    rounding=component.rounding,
                )
                charge = _round_ratio(
                    value * component.unit_price_q_atoms,
                    component.unit_divisor,
                    component.rounding,
                )
                return charge, value, f"{reason}; observable fallback applied", False
        if policy == "PARTIAL_CHARGE":
            return 0, None, f"{reason}; no partial value available", True
        return 0, None, reason, True

    def _scaled_integer_value(self, value, dimension_id, *, scale: int, rounding: str):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SettlementError(
                "SETTLEMENT_ACCOUNTING_FORMULA_INVALID",
                f"Billable dimension must be numeric: {dimension_id}",
            )
        try:
            scaled = Decimal(str(value)) * Decimal(scale)
        except (InvalidOperation, ValueError) as exc:
            raise SettlementError(
                "SETTLEMENT_ACCOUNTING_FORMULA_INVALID",
                f"Billable dimension is invalid: {dimension_id}",
            ) from exc
        if scaled < 0:
            raise SettlementError(
                "SETTLEMENT_ACCOUNTING_FORMULA_INVALID",
                f"Billable dimension must be non-negative: {dimension_id}",
            )
        decimal_rounding = {
            "DOWN": ROUND_DOWN,
            "UP": ROUND_UP,
            "HALF_EVEN": ROUND_HALF_EVEN,
        }[rounding]
        return int(scaled.to_integral_value(rounding=decimal_rounding))

    def _terminal_policy(self, request, terms):
        policy = terms.terminal_policies.get(request.terminal_state)
        if policy is not None:
            return policy
        if request.terminal_state == "COMPLETED":
            return TerminalChargePolicy(mode="FULL_CHARGE")
        if request.terminal_state == "REJECTED":
            return TerminalChargePolicy(mode="NO_CHARGE")
        return TerminalChargePolicy(mode="DISPUTE_REVIEW")

    def _apply_terminal_policy(self, raw_charge, policy):
        if policy.mode == "NO_CHARGE":
            return 0, False
        if policy.mode in {"ACCRUED_USAGE_ONLY", "FULL_CHARGE"}:
            return raw_charge, False
        if policy.mode == "FIXED_CHARGE":
            return int(policy.fixed_charge_q_atoms or 0), False
        if policy.mode == "PROPORTIONAL_BPS":
            return _round_ratio(
                raw_charge * int(policy.proportional_basis_points or 0),
                10_000,
                "HALF_EVEN",
            ), False
        return 0, True

    def _disputed_record(self, request, limitation):
        return RequestSettlementRecord(
            session_id=request.session_id,
            request_id=request.request_id,
            request_charge_ceiling_q_atoms=request.request_charge_ceiling_q_atoms,
            effective_terms_hash=request.effective_terms_hash,
            accounting_contract_hash=request.accounting_contract_hash,
            terminal_state=request.terminal_state,
            result_reference=request.result_reference,
            final_usage_report_id=request.final_usage_report_id,
            final_usage_report_hash=request.final_usage_report_hash,
            raw_calculated_charge_q_atoms=0,
            policy_adjusted_charge_q_atoms=0,
            capped_request_charge_q_atoms=0,
            endpoint_absorbed_amount_q_atoms=0,
            disputed_amount_q_atoms=request.request_charge_ceiling_q_atoms,
            limitations=[*request.limitations, limitation],
            dispute_state="DISPUTED",
        )
