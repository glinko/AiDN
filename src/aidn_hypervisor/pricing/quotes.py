"""Preflight estimates for Pricing V2."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aidn_hypervisor.pricing.charges import (
    RateChargeComponent,
    _component_charge,
    calculate_rate_card_charge,
)
from aidn_hypervisor.pricing.models import BillingDimension, RateCardV2


class RateQuoteRequest(BaseModel):
    """Optional expected Usage supplied by a Consumer before execution."""

    model_config = ConfigDict(extra="forbid")

    usage: dict[BillingDimension, int] = Field(default_factory=dict)


class RateQuote(BaseModel):
    """Immutable preflight view of one Rate Card.

    ``lower_bound_q_atoms`` is always safe to display. ``estimated_charge`` is
    present only when every metered component has an expected value. Escrow
    admission is governed by the Endpoint Session policy, not by a tariff cap.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "pricing-quote.v1"
    rate_card_hash: str
    currency: str = "Q_ATOM"
    supplied_usage: dict[BillingDimension, int]
    known_components: list[RateChargeComponent]
    missing_dimensions: list[BillingDimension]
    lower_bound_q_atoms: int = Field(ge=0)
    estimated_charge_q_atoms: int | None = Field(default=None, ge=0)


def quote_rate_card(
    rate_card: RateCardV2,
    usage: dict[BillingDimension, int] | None = None,
) -> RateQuote:
    """Build a deterministic quote without inventing unavailable Usage."""

    supplied_usage = dict(usage or {})
    known_components: list[RateChargeComponent] = []
    missing_dimensions: list[BillingDimension] = []
    for component in rate_card.components:
        if component.kind == "fixed":
            known_components.append(_component_charge(component, 1))
            continue
        measured_value = supplied_usage.get(component.dimension)
        if measured_value is None:
            missing_dimensions.append(component.dimension)
            continue
        if isinstance(measured_value, bool) or not isinstance(measured_value, int):
            raise ValueError(
                f"Quote Usage dimension must be an integer: {component.dimension}"
            )
        if measured_value < 0:
            raise ValueError(
                f"Quote Usage dimension cannot be negative: {component.dimension}"
            )
        known_components.append(_component_charge(component, measured_value))

    known_subtotal = sum(item.charge_q_atoms for item in known_components)
    lower_bound = max(known_subtotal, rate_card.minimum_charge_q_atoms)
    estimated_charge_q_atoms: int | None = None
    if not missing_dimensions:
        estimated_charge_q_atoms = calculate_rate_card_charge(
            rate_card,
            supplied_usage,
        ).total_q_atoms

    return RateQuote(
        rate_card_hash=str(rate_card.rate_card_hash),
        supplied_usage=supplied_usage,
        known_components=known_components,
        missing_dimensions=missing_dimensions,
        lower_bound_q_atoms=lower_bound,
        estimated_charge_q_atoms=estimated_charge_q_atoms,
    )
