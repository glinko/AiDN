"""M11-S2: Bond Store — in-memory persistence for validation bonds."""

from __future__ import annotations

from aidn_hypervisor.validation_bond.models import (
    BondStatus,
    ValidationBond,
)


class BondStore:
    """In-memory bond store with query support."""

    def __init__(self) -> None:
        self._bonds: dict[str, ValidationBond] = {}
        self._by_endpoint: dict[str, str] = {}
        self._by_wallet: dict[str, list[str]] = {}

    # ── CRUD ─────────────────────────────────────────────────────

    def upsert(self, bond: ValidationBond) -> None:
        """Store or update a bond."""
        existing = self._bonds.get(bond.bond_id)
        self._bonds[bond.bond_id] = bond

        # Index by endpoint
        if existing and existing.endpoint_id != bond.endpoint_id:
            self._by_endpoint.pop(bond.endpoint_id, None)
        self._by_endpoint[bond.endpoint_id] = bond.bond_id

        # Index by wallet
        if existing is None:
            self._by_wallet.setdefault(bond.operator_wallet, [])
            if bond.bond_id not in self._by_wallet[bond.operator_wallet]:
                self._by_wallet[bond.operator_wallet].append(bond.bond_id)

    def get(self, bond_id: str) -> ValidationBond | None:
        """Get a bond by ID."""
        return self._bonds.get(bond_id)

    def get_for_endpoint(self, endpoint_id: str) -> ValidationBond | None:
        """Get the bond for a given endpoint."""
        bid = self._by_endpoint.get(endpoint_id)
        if bid is None:
            return None
        return self._bonds.get(bid)

    def get_for_wallet(self, wallet: str) -> list[ValidationBond]:
        """Get all bonds for a wallet."""
        bids = self._by_wallet.get(wallet, [])
        return [b for bid in bids if (b := self._bonds.get(bid)) is not None]

    def get_all(self) -> list[ValidationBond]:
        """Get all bonds."""
        return list(self._bonds.values())

    def get_by_status(self, status: BondStatus) -> list[ValidationBond]:
        """Get all bonds with a given status."""
        return [b for b in self._bonds.values() if b.status == status]

    def has_bond(self, bond_id: str) -> bool:
        """Check if a bond exists."""
        return bond_id in self._bonds

    def has_endpoint_bond(self, endpoint_id: str) -> bool:
        """Check if an endpoint has a bond."""
        return endpoint_id in self._by_endpoint

    def remove(self, bond_id: str) -> None:
        """Remove a bond."""
        bond = self._bonds.pop(bond_id, None)
        if bond is None:
            return
        self._by_endpoint.pop(bond.endpoint_id, None)
        self._by_wallet.get(bond.operator_wallet, []).remove(bond_id)

    def count(self) -> int:
        """Total bond count."""
        return len(self._bonds)

    def reset(self) -> None:
        """Clear all bonds."""
        self._bonds.clear()
        self._by_endpoint.clear()
        self._by_wallet.clear()
