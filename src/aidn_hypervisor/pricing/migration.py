"""Read-time migration for endpoint pricing persisted before Pricing V2.

Pricing V2 intentionally rejects the old ``billing_unit``/``*_price`` fields
at every current API boundary.  A node that was bootstrapped before that
schema was introduced still has those fields in its durable snapshot, though.
This module is the narrow compatibility boundary for those snapshots: it
normalizes the old representation into the canonical integer-only Rate Card
shape before Pydantic validates the rest of the state.

The migration is deliberately one-way and read-only.  It does not make the
legacy fields valid for new endpoint commands or publications.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any

from aidn_hypervisor.pricing.models import Q_ATOMS_PER_Q

_LEGACY_PRICING_KEYS = frozenset(
    {
        "billing_unit",
        "input_price",
        "output_price",
        "audio_input_second_price",
        "fixed_price",
    }
)


def _q_price_to_atoms(value: Any, *, field_name: str) -> int:
    """Convert a historical decimal-Q price to integer Q atoms safely."""

    if isinstance(value, bool):
        raise ValueError(f"legacy pricing field {field_name} must be numeric")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(
            f"legacy pricing field {field_name} is not a valid decimal Q amount"
        ) from exc
    if not decimal_value.is_finite() or decimal_value < 0:
        raise ValueError(
            f"legacy pricing field {field_name} must be a finite non-negative amount"
        )
    atoms = decimal_value * Decimal(Q_ATOMS_PER_Q)
    return int(atoms.to_integral_value(rounding=ROUND_HALF_EVEN))


def normalize_legacy_pricing(value: Any) -> Any:
    """Return a Pricing V2 payload when ``value`` uses the pre-v2 shape.

    ``None`` and already-canonical payloads are returned unchanged.  Historical
    zero-valued fields are retained as zero-priced components so an explicit
    free policy remains distinguishable from an entirely unset policy.
    """

    if not isinstance(value, dict):
        return value
    if "rate_card" in value:
        return value
    if not (_LEGACY_PRICING_KEYS & value.keys()):
        return value

    components: list[dict[str, Any]] = []

    if value.get("input_price") is not None:
        components.append(
            {
                "component_id": "legacy-input-tokens",
                "dimension": "input_tokens",
                "kind": "metered",
                "unit_price_q_atoms": _q_price_to_atoms(
                    value["input_price"], field_name="input_price"
                ),
                # Historical input/output prices were Q per million tokens.
                "unit_divisor": 1_000_000,
                "accounting_mode": "provider_metered",
                "measurement_source": "provider_report",
                "verification_method": "provider_report",
            }
        )

    if value.get("output_price") is not None:
        components.append(
            {
                "component_id": "legacy-output-tokens",
                "dimension": "output_tokens",
                "kind": "metered",
                "unit_price_q_atoms": _q_price_to_atoms(
                    value["output_price"], field_name="output_price"
                ),
                "unit_divisor": 1_000_000,
                "accounting_mode": "provider_metered",
                "measurement_source": "provider_report",
                "verification_method": "provider_report",
            }
        )

    if value.get("audio_input_second_price") is not None:
        components.append(
            {
                "component_id": "legacy-audio-input-seconds",
                "dimension": "audio_input_milliseconds",
                "kind": "metered",
                "unit_price_q_atoms": _q_price_to_atoms(
                    value["audio_input_second_price"],
                    field_name="audio_input_second_price",
                ),
                # Runtime usage is integer milliseconds; the old price was Q/s.
                "unit_divisor": 1_000,
                "accounting_mode": "observable",
                "measurement_source": "provider_response.duration",
                "verification_method": "provider_response",
                "unavailable_value_policy": "ZERO_VARIABLE_COMPONENT",
            }
        )

    if value.get("fixed_price") is not None:
        components.append(
            {
                "component_id": "legacy-fixed-request",
                "dimension": "request_count",
                "kind": "fixed",
                "unit_price_q_atoms": _q_price_to_atoms(
                    value["fixed_price"], field_name="fixed_price"
                ),
                "accounting_mode": "fixed_price",
                "measurement_source": "endpoint_policy",
                "verification_method": "fixed_contract",
            }
        )

    return {
        "rate_card": {
            "schema_version": "pricing.v2",
            "currency": "Q_ATOM",
            "components": components,
        }
    }


def migrate_snapshot_pricing(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy pricing in strict endpoint collections of a snapshot."""

    for collection_name in ("endpoints", "endpoint_configuration_snapshots"):
        collection = payload.get(collection_name)
        if not isinstance(collection, list):
            continue
        for index, item in enumerate(collection):
            if not isinstance(item, dict) or "pricing" not in item:
                continue
            normalized_pricing = normalize_legacy_pricing(item["pricing"])
            if normalized_pricing is item["pricing"]:
                continue
            migrated_item = dict(item)
            migrated_item["pricing"] = normalized_pricing
            collection[index] = migrated_item
    return payload
