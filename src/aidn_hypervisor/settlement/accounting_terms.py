"""Convert accepted Accounting Contracts into integer-q_atoms Settlement terms."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from aidn_hypervisor.accounting.models import AccountingContract, AccountingUnitContract
from aidn_hypervisor.pricing import RateCardV2
from aidn_hypervisor.settlement.models import (
    SettlementAccountingTerms,
    SettlementChargeComponent,
    TerminalChargePolicy,
)

Q_ATOMS_PER_Q = 1_000_000
_TOKEN_DIMENSIONS = {"input_tokens", "output_tokens"}
_AUDIO_SECOND_DIMENSION = "audio_input_seconds"


def _q_to_atoms(price_q: float) -> int:
    """Convert a decimal Q price without using binary floating-point arithmetic."""
    try:
        atoms = Decimal(str(price_q)) * Decimal(Q_ATOMS_PER_Q)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Accounting price is not a valid decimal Q amount") from exc
    if atoms < 0:
        raise ValueError("Accounting price cannot be negative")
    return int(atoms.to_integral_value(rounding=ROUND_HALF_EVEN))


def _rounding(unit: AccountingUnitContract) -> str:
    return unit.rounding if unit.rounding in {"DOWN", "UP", "HALF_EVEN"} else "DOWN"


def _component(unit: AccountingUnitContract, *, component_index: int) -> SettlementChargeComponent:
    if unit.mode == "fixed_price":
        return SettlementChargeComponent(
            component_id=f"{component_index}:{unit.unit}",
            fixed_amount_q_atoms=_q_to_atoms(unit.price),
        )

    # Legacy token prices are Q per one million tokens. Canonical terms retain
    # that divisor explicitly so the arithmetic remains integer q_atoms.
    if unit.unit in _TOKEN_DIMENSIONS:
        return SettlementChargeComponent(
            component_id=f"{component_index}:{unit.unit}",
            dimension_id=unit.unit,
            unit_price_q_atoms=_q_to_atoms(unit.price),
            unit_divisor=1_000_000,
            rounding=_rounding(unit),
            required_authority=unit.required_authority,
            unavailable_value_policy=unit.unavailable_value_policy
            or "REQUEST_REJECTED_BEFORE_EXECUTION",
        )

    # Provider duration is received in seconds, but Settlement normalizes it
    # to integer milliseconds before applying an integer q_atoms price.
    if unit.unit == _AUDIO_SECOND_DIMENSION:
        return SettlementChargeComponent(
            component_id=f"{component_index}:{unit.unit}",
            dimension_id=unit.unit,
            unit_price_q_atoms=_q_to_atoms(unit.price),
            unit_divisor=1_000,
            source_value_scale=1_000,
            rounding=_rounding(unit),
            required_authority=unit.required_authority,
            unavailable_value_policy=unit.unavailable_value_policy
            or "REQUEST_REJECTED_BEFORE_EXECUTION",
        )

    return SettlementChargeComponent(
        component_id=f"{component_index}:{unit.unit}",
        dimension_id=unit.unit,
        unit_price_q_atoms=_q_to_atoms(unit.price),
        rounding=_rounding(unit),
        required_authority=unit.required_authority,
        unavailable_value_policy=unit.unavailable_value_policy
        or "REQUEST_REJECTED_BEFORE_EXECUTION",
    )


def build_settlement_terms(contract: AccountingContract) -> SettlementAccountingTerms:
    """Build deterministic terms for a previously accepted Accounting Contract.

    This utility is intentionally independent of public MVP session admission.
    Public `MVP-0001` stays fixed-price until a separate variable-price profile
    binds these terms into the canonical Session contract.
    """
    modes = {item.mode for item in contract.billable_units}
    accounting_mode = contract.accounting_mode or (
        next(iter(modes)) if len(modes) == 1 else "hybrid"
    )
    return SettlementAccountingTerms(
        accounting_contract_hash=str(contract.payload_hash),
        accounting_mode=accounting_mode,
        components=[
            _component(unit, component_index=index)
            for index, unit in enumerate(contract.billable_units, start=1)
        ],
        terminal_policies={
            "COMPLETED": TerminalChargePolicy(mode="FULL_CHARGE"),
            "PARTIAL": TerminalChargePolicy(mode="ACCRUED_USAGE_ONLY"),
            "CANCELLED": TerminalChargePolicy(mode="ACCRUED_USAGE_ONLY"),
            "FAILED": TerminalChargePolicy(mode="NO_CHARGE"),
            "EXPIRED": TerminalChargePolicy(mode="NO_CHARGE"),
            "UNRECOVERABLE": TerminalChargePolicy(mode="NO_CHARGE"),
            "REJECTED": TerminalChargePolicy(mode="NO_CHARGE"),
        },
        terms_version="settlement-terms.v2",
    )


def build_rate_card_settlement_terms(
    rate_card: RateCardV2,
    *,
    accounting_contract_hash: str | None = None,
) -> SettlementAccountingTerms:
    """Bridge a Pricing V2 Rate Card directly to integer Settlement terms."""
    modes = {item.accounting_mode for item in rate_card.components}
    accounting_mode = next(iter(modes)) if len(modes) == 1 else "hybrid"
    components: list[SettlementChargeComponent] = []
    for item in rate_card.components:
        if item.kind == "fixed":
            components.append(
                SettlementChargeComponent(
                    component_id=item.component_id,
                    fixed_amount_q_atoms=item.unit_price_q_atoms,
                )
            )
            continue
        components.append(
            SettlementChargeComponent(
                component_id=item.component_id,
                dimension_id=item.dimension,
                unit_price_q_atoms=item.unit_price_q_atoms,
                unit_divisor=item.unit_divisor,
                source_value_scale=item.source_value_scale,
                rounding=item.rounding,
                required_authority=item.required_authority,
                unavailable_value_policy=item.unavailable_value_policy,
            )
        )
    return SettlementAccountingTerms(
        accounting_contract_hash=accounting_contract_hash
        or str(rate_card.rate_card_hash),
        accounting_mode=accounting_mode,
        components=components,
        minimum_charge_q_atoms=rate_card.minimum_charge_q_atoms,
        terminal_policies={
            "COMPLETED": TerminalChargePolicy(mode="FULL_CHARGE"),
            "PARTIAL": TerminalChargePolicy(mode="ACCRUED_USAGE_ONLY"),
            "CANCELLED": TerminalChargePolicy(mode="ACCRUED_USAGE_ONLY"),
            "FAILED": TerminalChargePolicy(mode="NO_CHARGE"),
            "EXPIRED": TerminalChargePolicy(mode="NO_CHARGE"),
            "UNRECOVERABLE": TerminalChargePolicy(mode="NO_CHARGE"),
            "REJECTED": TerminalChargePolicy(mode="NO_CHARGE"),
        },
        terms_version="settlement-terms.v3",
    )
