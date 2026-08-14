from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.contributions.wallet_profile import (
    load_verified_contributor_wallet_key,
    public_key_for_private_key,
)


def test_external_wallet_key_is_verified_against_public_identity(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public_key = public_key_for_private_key(private_key)
    key_path = tmp_path / "wallet.seed"
    key_path.write_text(bytes(range(32)).hex() + "\n", encoding="utf-8")

    loaded, loaded_public_key = load_verified_contributor_wallet_key(
        key_path,
        wallet_address="wallet-controlled-localnet",
        expected_public_key=public_key,
    )

    assert loaded.public_key().public_bytes_raw() == private_key.public_key().public_bytes_raw()
    assert loaded_public_key == public_key


def test_external_wallet_key_mismatch_fails_closed(tmp_path: Path) -> None:
    key_path = tmp_path / "wallet.seed"
    key_path.write_text(bytes(range(32)).hex() + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="CONTRIBUTOR_WALLET_KEY_MISMATCH"):
        load_verified_contributor_wallet_key(
            key_path,
            wallet_address="wallet-controlled-localnet",
            expected_public_key="ed25519:" + "00" * 32,
        )
