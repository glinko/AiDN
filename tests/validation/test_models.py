import pytest
from pydantic import ValidationError

from aidn_hypervisor.validation.models import (
    ValidationBond,
    ValidationStatusSnapshot,
)


def test_validation_bond_preserves_balanced_totals() -> None:
    bond = ValidationBond(
        bond_id="bond-1",
        owner_wallet="wallet-1",
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        amount_q=500.0,
        remaining_locked_q=500.0,
        released_q=0.0,
        forfeited_q=0.0,
        escrow_adapter="adapter-1",
        escrow_reference="escrow-1",
        status="locked",
    )

    assert bond.amount_q == 500.0
    assert bond.remaining_locked_q == 500.0
    assert bond.released_q == 0.0
    assert bond.forfeited_q == 0.0


def test_validation_status_snapshot_requires_request_for_validated_status() -> None:
    with pytest.raises(ValidationError):
        ValidationStatusSnapshot(
            endpoint_id="ep-1",
            configuration_hash="cfg-1",
            status="validated",
            latest_request_id=None,
            latest_report_id="report-1",
        )
