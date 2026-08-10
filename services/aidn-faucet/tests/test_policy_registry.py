from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from aidn_faucet.policy_registry import (
    FaucetPolicyRegistryRoot,
    FaucetPolicyRelease,
    build_policy_from_release,
    public_key_for_private_key,
    validate_registry_for_manifest,
)
from aidn_faucet.service import FaucetService, TreasurySigner
from aidn_faucet.store import FaucetStore
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.faucet_treasury import FaucetTreasuryManifest, wallet_id_for_public_key


def _root(key: Ed25519PrivateKey) -> FaucetPolicyRegistryRoot:
    return FaucetPolicyRegistryRoot.create_signed(
        registry_id="faucet-policy-registry-test-v1",
        network_id="aidn-localnet-1",
        chain_id="chain-test",
        treasury_id="faucet-treasury-test-v1",
        creator_recovery_wallet=wallet_id_for_public_key(public_key_for_private_key(key)),
        creator_private_key=key,
        created_at="2030-01-01T00:00:00Z",
    )


def _release(root: FaucetPolicyRegistryRoot, key: Ed25519PrivateKey) -> FaucetPolicyRelease:
    return FaucetPolicyRelease.create_signed(
        root=root,
        sequence=1,
        policy_id="fixed-daily",
        policy_version="aidn.faucet-policy.v1.fixed-daily.lab.1",
        parameters={"amount_q": 50},
        effective_from="2030-01-01T00:00:00Z",
        creator_private_key=key,
    )


def test_signed_root_and_release_build_active_policy() -> None:
    key = Ed25519PrivateKey.generate()
    root = _root(key)
    release = _release(root, key)

    policy = build_policy_from_release(
        root,
        release,
        now=datetime(2030, 1, 1, 1, tzinfo=UTC),
    )

    assert root.verify().root_hash == root.root_hash
    assert release.verify(root).policy_hash == release.policy_hash
    assert policy.policy_id == "fixed-daily"
    assert policy.policy_version == release.policy_version
    assert policy.amount_q_atoms == 50_000_000


def test_policy_release_rejects_tampered_parameters_and_future_release() -> None:
    key = Ed25519PrivateKey.generate()
    root = _root(key)
    release = _release(root, key)
    tampered = release.model_copy(update={"parameters": {"amount_q": 500}})

    with pytest.raises(ValueError, match="HASH_INVALID"):
        tampered.verify(root)
    future_release = FaucetPolicyRelease.create_signed(
        root=root,
        sequence=2,
        policy_id="fixed-daily",
        policy_version="aidn.faucet-policy.v1.fixed-daily.lab.2",
        parameters={"amount_q": 50},
        effective_from=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
        creator_private_key=key,
    )
    with pytest.raises(ValueError, match="NOT_ACTIVE"):
        build_policy_from_release(
            root,
            future_release,
            now=datetime.now(UTC),
        )


def test_registry_must_match_treasury_manifest() -> None:
    key = Ed25519PrivateKey.generate()
    root = _root(key)
    release = _release(root, key)
    treasury_key = Ed25519PrivateKey.generate()
    treasury_public_key = public_key_for_private_key(treasury_key)
    manifest = FaucetTreasuryManifest(
        treasury_id=root.treasury_id,
        network_id=root.network_id,
        chain_id=root.chain_id,
        wallet_id=wallet_id_for_public_key(treasury_public_key),
        wallet_public_key=treasury_public_key,
        creator_recovery_wallet=root.creator_recovery_wallet,
        genesis_allocation_q_atoms=10_000_000_000_000,
        policy_registry_hash=root.root_hash,
    )

    policy = validate_registry_for_manifest(
        root,
        release,
        manifest=manifest,
        now=datetime(2030, 1, 2, tzinfo=UTC),
    )
    assert policy.policy_id == "fixed-daily"

    mismatched_values = manifest.model_dump(mode="json")
    mismatched_values.pop("manifest_hash")
    mismatched_values["network_id"] = "other-network"
    mismatched_manifest = FaucetTreasuryManifest(**mismatched_values)
    with pytest.raises(ValueError, match="MANIFEST_MISMATCH"):
        validate_registry_for_manifest(
            root,
            release,
            manifest=mismatched_manifest,
            now=datetime(2030, 1, 2, tzinfo=UTC),
        )


def test_service_rejects_stale_release_after_a_newer_release(tmp_path) -> None:
    creator_key = Ed25519PrivateKey.generate()
    root = _root(creator_key)
    release_one = _release(root, creator_key)
    release_two = FaucetPolicyRelease.create_signed(
        root=root,
        sequence=2,
        policy_id="fixed-daily",
        policy_version="aidn.faucet-policy.v1.fixed-daily.lab.2",
        parameters={"amount_q": 25},
        effective_from="2030-01-02T00:00:00Z",
        previous_policy_hash=release_one.policy_hash,
        creator_private_key=creator_key,
    )
    treasury_key = Ed25519PrivateKey.generate()
    treasury_public_key = public_key_for_private_key(treasury_key)
    manifest = FaucetTreasuryManifest(
        treasury_id=root.treasury_id,
        network_id=root.network_id,
        chain_id=root.chain_id,
        wallet_id=wallet_id_for_public_key(treasury_public_key),
        wallet_public_key=treasury_public_key,
        creator_recovery_wallet=root.creator_recovery_wallet,
        genesis_allocation_q_atoms=10_000_000_000_000,
        policy_registry_hash=root.root_hash,
    )
    store = FaucetStore(tmp_path / "faucet.sqlite")
    now = datetime(2030, 1, 3, tzinfo=UTC)
    policy_two = build_policy_from_release(root, release_two, now=now)
    FaucetService(
        manifest=manifest,
        signer=TreasurySigner(treasury_key, expected_public_key=treasury_public_key),
        policy=policy_two,
        store=store,
        submitter=object(),
        policy_registry_root=root,
        policy_release=release_two,
        now=lambda: now,
    )
    policy_one = build_policy_from_release(root, release_one, now=now)
    with pytest.raises(ValueError, match="ROLLBACK_DETECTED"):
        FaucetService(
            manifest=manifest,
            signer=TreasurySigner(treasury_key, expected_public_key=treasury_public_key),
            policy=policy_one,
            store=store,
            submitter=object(),
            policy_registry_root=root,
            policy_release=release_one,
            now=lambda: now,
        )
