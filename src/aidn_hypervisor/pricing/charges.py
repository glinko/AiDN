"""Deterministic integer arithmetic for Pricing V2 request charges."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aidn_hypervisor.pricing.models import RateCardV2, RateComponent


class RateChargeComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str
    dimension: str
    measured_value: int = Field(ge=0)
    normalized_value: int = Field(ge=0)
    unit_price_q_atoms: int = Field(ge=0)
    unit_divisor: int = Field(ge=1)
    charge_q_atoms: int = Field(ge=0)


class RateCharge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate_card_hash: str
    components: list[RateChargeComponent]
    subtotal_q_atoms: int = Field(ge=0)
    total_q_atoms: int = Field(ge=0)


def _divide(value: int, divisor: int, rounding: str) -> int:
    quotient, remainder = divmod(value, divisor)
    if remainder == 0 or rounding == "DOWN":
        return quotient
    if rounding == "UP":
        return quotient + 1
    doubled = remainder * 2
    if doubled > divisor or (doubled == divisor and quotient % 2 == 1):
        return quotient + 1
    return quotient


def _component_charge(component: RateComponent, measured_value: int) -> RateChargeComponent:
    normalized = measured_value * component.source_value_scale
    charge = _divide(
        normalized * component.unit_price_q_atoms,
        component.unit_divisor,
        component.rounding,
    )
    return RateChargeComponent(
        component_id=component.component_id,
        dimension=component.dimension,
        measured_value=measured_value,
        normalized_value=normalized,
        unit_price_q_atoms=component.unit_price_q_atoms,
        unit_divisor=component.unit_divisor,
        charge_q_atoms=charge,
    )


def calculate_rate_card_charge(
    rate_card: RateCardV2,
    usage: dict[str, int | None],
) -> RateCharge:
    """Calculate one request charge and fail closed on unavailable priced Usage."""
    breakdown: list[RateChargeComponent] = []
    for component in rate_card.components:
        measured_value = 1 if component.kind == "fixed" else usage.get(component.dimension)
        if measured_value is None:
            if component.unavailable_value_policy == "ZERO_VARIABLE_COMPONENT":
                measured_value = 0
            else:
                raise ValueError(
                    f"required Usage dimension is unavailable: {component.dimension}"
                )
        if isinstance(measured_value, bool) or not isinstance(measured_value, int):
            raise ValueError(f"Usage dimension must be an integer: {component.dimension}")
        if measured_value < 0:
            raise ValueError(f"Usage dimension cannot be negative: {component.dimension}")
        breakdown.append(_component_charge(component, measured_value))

    subtotal = sum(item.charge_q_atoms for item in breakdown)
    total = max(subtotal, rate_card.minimum_charge_q_atoms)
    return RateCharge(
        rate_card_hash=str(rate_card.rate_card_hash),
        components=breakdown,
        subtotal_q_atoms=subtotal,
        total_q_atoms=total,
    )
