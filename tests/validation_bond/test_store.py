"""M11-S2: Bond Store — unit tests."""

from __future__ import annotations

import pytest

from aidn_hypervisor.validation_bond.models import (
    BondStatus,
    VALIDATION_BOND_Q_ATOMS,
    ValidationBond,
)
from aidn_hypervisor.validation_bond.store import BondStore


# ── Helpers ────────────────────────────────────────────────────────

NOW = "2026-07-26T22:00:00+00:00"


def _make_bond(
    bond_id: str,
    endpoint_id: str,
    wallet: str,
    status: BondStatus = BondStatus.LOCKED,
) -> ValidationBond:
    return ValidationBond(
        bond_id=bond_id,
        endpoint_id=endpoint_id,
        operator_wallet=wallet,
        initial_amount=VALIDATION_BOND_Q_ATOMS,
        remaining_amount=VALIDATION_BOND_Q_ATOMS,
        status=status,
        created_at=NOW,
    )


# ── CRUD ───────────────────────────────────────────────────────────

class TestBondStoreUpsert:
    def test_upsert_single(self):
        store = BondStore()
        bond = _make_bond("b1", "ep1", "w1")
        store.upsert(bond)
        assert store.count() == 1
        assert store.get("b1") is not None

    def test_upsert_multiple(self):
        store = BondStore()
        store.upsert(_make_bond("b1", "ep1", "w1"))
        store.upsert(_make_bond("b2", "ep2", "w2"))
        assert store.count() == 2

    def test_upsert_overwrite(self):
        store = BondStore()
        bond = _make_bond("b1", "ep1", "w1")
        store.upsert(bond)
        updated = bond.model_copy(update={"status": BondStatus.ACTIVE})
        store.upsert(updated)
        assert store.count() == 1
        assert store.get("b1").status == BondStatus.ACTIVE


class TestBondStoreGet:
    def test_get_existing(self):
        store = BondStore()
        bond = _make_bond("b1", "ep1", "w1")
        store.upsert(bond)
        assert store.get("b1") == bond

    def test_get_missing(self):
        store = BondStore()
        assert store.get("nonexistent") is None


class TestBondStoreEndpointQuery:
    def test_get_for_endpoint(self):
        store = BondStore()
        bond = _make_bond("b1", "ep1", "w1")
        store.upsert(bond)
        assert store.get_for_endpoint("ep1").bond_id == "b1"

    def test_get_for_endpoint_missing(self):
        store = BondStore()
        assert store.get_for_endpoint("no-ep") is None

    def test_has_endpoint_bond_true(self):
        store = BondStore()
        store.upsert(_make_bond("b1", "ep1", "w1"))
        assert store.has_endpoint_bond("ep1") is True

    def test_has_endpoint_bond_false(self):
        store = BondStore()
        store.upsert(_make_bond("b1", "ep1", "w1"))
        assert store.has_endpoint_bond("ep2") is False


class TestBondStoreWalletQuery:
    def test_get_for_wallet_single(self):
        store = BondStore()
        store.upsert(_make_bond("b1", "ep1", "w1"))
        bonds = store.get_for_wallet("w1")
        assert len(bonds) == 1
        assert bonds[0].bond_id == "b1"

    def test_get_for_wallet_multiple(self):
        store = BondStore()
        store.upsert(_make_bond("b1", "ep1", "w1"))
        store.upsert(_make_bond("b2", "ep2", "w1"))
        bonds = store.get_for_wallet("w1")
        assert len(bonds) == 2

    def test_get_for_wallet_empty(self):
        store = BondStore()
        store.upsert(_make_bond("b1", "ep1", "w1"))
        bonds = store.get_for_wallet("w2")
        assert len(bonds) == 0


class TestBondStoreStatusQuery:
    def test_get_by_status(self):
        store = BondStore()
        store.upsert(_make_bond("b1", "ep1", "w1", BondStatus.LOCKED))
        store.upsert(
            _make_bond("b2", "ep2", "w2", BondStatus.ACTIVE)
        )
        locked = store.get_by_status(BondStatus.LOCKED)
        active = store.get_by_status(BondStatus.ACTIVE)
        assert len(locked) == 1
        assert len(active) == 1

    def test_get_by_status_empty(self):
        store = BondStore()
        store.upsert(_make_bond("b1", "ep1", "w1", BondStatus.LOCKED))
        assert len(store.get_by_status(BondStatus.FORFEITED)) == 0


class TestBondStoreHas:
    def test_has_bond_true(self):
        store = BondStore()
        store.upsert(_make_bond("b1", "ep1", "w1"))
        assert store.has_bond("b1") is True

    def test_has_bond_false(self):
        store = BondStore()
        store.upsert(_make_bond("b1", "ep1", "w1"))
        assert store.has_bond("b2") is False


class TestBondStoreRemove:
    def test_remove_existing(self):
        store = BondStore()
        store.upsert(_make_bond("b1", "ep1", "w1"))
        store.remove("b1")
        assert store.count() == 0
        assert store.get("b1") is None

    def test_remove_nonexistent(self):
        store = BondStore()
        store.remove("nope")  # should not raise

    def test_remove_clears_endpoint_index(self):
        store = BondStore()
        store.upsert(_make_bond("b1", "ep1", "w1"))
        store.remove("b1")
        assert store.has_endpoint_bond("ep1") is False


class TestBondStoreGetAll:
    def test_get_all(self):
        store = BondStore()
        store.upsert(_make_bond("b1", "ep1", "w1"))
        store.upsert(_make_bond("b2", "ep2", "w2"))
        all_bonds = store.get_all()
        assert len(all_bonds) == 2

    def test_get_all_empty(self):
        store = BondStore()
        assert store.get_all() == []


class TestBondStoreReset:
    def test_reset(self):
        store = BondStore()
        store.upsert(_make_bond("b1", "ep1", "w1"))
        store.upsert(_make_bond("b2", "ep2", "w2"))
        store.reset()
        assert store.count() == 0
        assert store.get_all() == []
