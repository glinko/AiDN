"""Project Pricing V2 metadata into the runtime accounting snapshot.

The runtime protocol still signs an AccountingContract object. This projection
is not a pricing fallback: the immutable RateCard remains the source of truth
and all charge arithmetic is performed directly from it in integer q_atoms.
"""

from __future__ import annotations

from decimal import Decimal

from aidn_hypervisor.accounting.models import AccountingUnitContract
from aidn_hypervisor.pricing.models import Q_ATOMS_PER_Q, RateCardV2


def accounting_snapshot_units(
    rate_card: RateCardV2,
    *,
    default_measurement_source: str = "provider_report",
) -> list[AccountingUnitContract]:
    units: list[AccountingUnitContract] = []
    for component in rate_card.components:
        unit = "request_count" if component.kind == "fixed" else component.dimension
        price_q = Decimal(component.unit_price_q_atoms) / Decimal(Q_ATOMS_PER_Q)
        units.append(
            AccountingUnitContract(
                unit=unit,
                mode=component.accounting_mode,
                price=float(price_q),
                measurement_source=(
                    default_measurement_source
                    if component.measurement_source == "runtime_usage"
                    else component.measurement_source
                ),
                verification_method=component.verification_method,
                rounding=component.rounding,
                required_authority=component.required_authority,
                unavailable_value_policy=component.unavailable_value_policy,
            )
        )
    return units
