"""Signed, replaceable Faucet policy registry artifacts.

The Treasury manifest commits to an immutable registry root.  Individual policy
releases are public, signed records that can change only at an explicit future
boundary.  The Faucet never treats command line flags as a production policy
when a registry root is configured.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel, Field

from aidn_faucet.models import canonical_hash, canonical_json, wallet_id_for_public_key
from aidn_faucet.policy import AccumulatingPoolPolicy, FaucetPolicy, FixedDailyPolicy


def _public_key_bytes(value: str) -> bytes:
    if not isinstance(value, str) or not value.startswith("ed25519:"):
        raise ValueError("policy registry public key must use ed25519:<hex>")
    try:
        raw = bytes.fromhex(value.removeprefix("ed25519:"))
    except ValueError as error:
        raise ValueError("policy registry public key is not hexadecimal") from error
    if len(raw) != 32:
        raise ValueError("policy registry public key must contain 32 bytes")
    return raw


def _signature_bytes(value: str) -> bytes:
    if not isinstance(value, str) or not value.startswith("ed25519:"):
        raise ValueError("policy registry signature must use ed25519:<hex>")
    try:
        raw = bytes.fromhex(value.removeprefix("ed25519:"))
    except ValueError as error:
        raise ValueError("policy registry signature is not hexadecimal") from error
    if len(raw) != 64:
        raise ValueError("policy registry signature must contain 64 bytes")
    return raw


def public_key_for_private_key(private_key: Ed25519PrivateKey) -> str:
    return "ed25519:" + private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()


def load_ed25519_private_key(path: str) -> Ed25519PrivateKey:
    """Load a creator key without ever serializing it into a public artifact."""

    raw = open(path, "rb").read().strip()  # noqa: SIM115 - caller owns the secret path
    if raw.startswith(b"-----BEGIN"):
        loaded = serialization.load_pem_private_key(raw, password=None)
        if isinstance(loaded, Ed25519PrivateKey):
            return loaded
        raise ValueError("creator private key PEM is not Ed25519")
    try:
        seed = bytes.fromhex(raw.decode("ascii").removeprefix("ed25519:"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("creator private key must be a PEM key or 32-byte hex seed") from error
    if len(seed) != 32:
        raise ValueError("creator private key seed must contain exactly 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(seed)


def _parse_timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


class FaucetPolicyRegistryRoot(BaseModel, frozen=True):
    schema_version: Literal["aidn.faucet-policy-registry-root.v1"] = (
        "aidn.faucet-policy-registry-root.v1"
    )
    registry_id: str = Field(min_length=1, max_length=128)
    network_id: str = Field(min_length=1, max_length=128)
    chain_id: str = Field(min_length=1, max_length=128)
    treasury_id: str = Field(min_length=1, max_length=128)
    creator_recovery_wallet: str = Field(min_length=1, max_length=128)
    creator_public_key: str = Field(min_length=1)
    policy_schema: Literal["aidn.faucet-policy.v1"] = "aidn.faucet-policy.v1"
    update_rule: Literal["CREATOR_SIGNATURE"] = "CREATOR_SIGNATURE"
    created_at: str = Field(min_length=1)
    root_hash: str = Field(min_length=1)
    creator_signature: str = Field(min_length=1)

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "registry_id": self.registry_id,
            "network_id": self.network_id,
            "chain_id": self.chain_id,
            "treasury_id": self.treasury_id,
            "creator_recovery_wallet": self.creator_recovery_wallet,
            "creator_public_key": self.creator_public_key,
            "policy_schema": self.policy_schema,
            "update_rule": self.update_rule,
            "created_at": self.created_at,
        }

    def signing_bytes(self) -> bytes:
        return canonical_json(
            {"domain": "aidn.faucet-policy-registry-root.v1", "root": self.payload(), "root_hash": self.root_hash}
        )

    def verify(self) -> FaucetPolicyRegistryRoot:
        _parse_timestamp(self.created_at, field="registry root created_at")
        if self.root_hash != canonical_hash(self.payload()):
            raise ValueError("FAUCET_POLICY_REGISTRY_ROOT_HASH_INVALID")
        if wallet_id_for_public_key(self.creator_public_key) != self.creator_recovery_wallet:
            raise ValueError("FAUCET_POLICY_REGISTRY_CREATOR_WALLET_MISMATCH")
        try:
            Ed25519PublicKey.from_public_bytes(_public_key_bytes(self.creator_public_key)).verify(
                _signature_bytes(self.creator_signature), self.signing_bytes()
            )
        except InvalidSignature as error:
            raise ValueError("FAUCET_POLICY_REGISTRY_ROOT_SIGNATURE_INVALID") from error
        return self

    @classmethod
    def create_signed(
        cls,
        *,
        registry_id: str,
        network_id: str,
        chain_id: str,
        treasury_id: str,
        creator_recovery_wallet: str,
        creator_private_key: Ed25519PrivateKey,
        created_at: str,
    ) -> FaucetPolicyRegistryRoot:
        creator_public_key = public_key_for_private_key(creator_private_key)
        root = cls(
            registry_id=registry_id,
            network_id=network_id,
            chain_id=chain_id,
            treasury_id=treasury_id,
            creator_recovery_wallet=creator_recovery_wallet,
            creator_public_key=creator_public_key,
            created_at=created_at,
            root_hash="pending",
            creator_signature="pending",
        )
        root = root.model_copy(update={"root_hash": canonical_hash(root.payload())})
        root = root.model_copy(
            update={"creator_signature": "ed25519:" + creator_private_key.sign(root.signing_bytes()).hex()}
        )
        return root.verify()


class FaucetPolicyRelease(BaseModel, frozen=True):
    schema_version: Literal["aidn.faucet-policy-release.v1"] = "aidn.faucet-policy-release.v1"
    registry_hash: str = Field(min_length=1)
    sequence: int = Field(gt=0)
    policy_id: Literal["fixed-daily", "accumulating-pool"]
    policy_version: str = Field(min_length=1, max_length=160)
    parameters: dict[str, int] = Field(default_factory=dict)
    effective_from: str = Field(min_length=1)
    effective_until: str | None = None
    previous_policy_hash: str | None = None
    policy_hash: str = Field(min_length=1)
    creator_signature: str = Field(min_length=1)

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "registry_hash": self.registry_hash,
            "sequence": self.sequence,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "parameters": self.parameters,
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
            "previous_policy_hash": self.previous_policy_hash,
        }

    def signing_bytes(self) -> bytes:
        return canonical_json(
            {"domain": "aidn.faucet-policy-release.v1", "release": self.payload(), "policy_hash": self.policy_hash}
        )

    def verify(self, root: FaucetPolicyRegistryRoot) -> FaucetPolicyRelease:
        root.verify()
        if self.registry_hash != root.root_hash:
            raise ValueError("FAUCET_POLICY_RELEASE_REGISTRY_MISMATCH")
        if self.policy_hash != canonical_hash(self.payload()):
            raise ValueError("FAUCET_POLICY_RELEASE_HASH_INVALID")
        _validate_parameters(self.policy_id, self.parameters)
        start = _parse_timestamp(self.effective_from, field="policy effective_from")
        if self.effective_until is not None and _parse_timestamp(
            self.effective_until, field="policy effective_until"
        ) <= start:
            raise ValueError("FAUCET_POLICY_RELEASE_WINDOW_INVALID")
        try:
            Ed25519PublicKey.from_public_bytes(_public_key_bytes(root.creator_public_key)).verify(
                _signature_bytes(self.creator_signature), self.signing_bytes()
            )
        except InvalidSignature as error:
            raise ValueError("FAUCET_POLICY_RELEASE_SIGNATURE_INVALID") from error
        return self

    @classmethod
    def create_signed(
        cls,
        *,
        root: FaucetPolicyRegistryRoot,
        sequence: int,
        policy_id: Literal["fixed-daily", "accumulating-pool"],
        policy_version: str,
        parameters: dict[str, int],
        effective_from: str,
        creator_private_key: Ed25519PrivateKey,
        effective_until: str | None = None,
        previous_policy_hash: str | None = None,
    ) -> FaucetPolicyRelease:
        root.verify()
        if public_key_for_private_key(creator_private_key).lower() != root.creator_public_key.lower():
            raise ValueError("FAUCET_POLICY_RELEASE_CREATOR_KEY_MISMATCH")
        release = cls(
            registry_hash=root.root_hash,
            sequence=sequence,
            policy_id=policy_id,
            policy_version=policy_version,
            parameters=parameters,
            effective_from=effective_from,
            effective_until=effective_until,
            previous_policy_hash=previous_policy_hash,
            policy_hash="pending",
            creator_signature="pending",
        )
        release = release.model_copy(update={"policy_hash": canonical_hash(release.payload())})
        release = release.model_copy(
            update={"creator_signature": "ed25519:" + creator_private_key.sign(release.signing_bytes()).hex()}
        )
        return release.verify(root)


def _validate_parameters(policy_id: str, parameters: dict[str, int]) -> None:
    expected = {"amount_q"} if policy_id == "fixed-daily" else {"rate_q", "interval_seconds"}
    invalid_values = any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in parameters.values()
    )
    if set(parameters) != expected or invalid_values:
        raise ValueError("FAUCET_POLICY_RELEASE_PARAMETERS_INVALID")


def build_policy_from_release(
    root: FaucetPolicyRegistryRoot,
    release: FaucetPolicyRelease,
    *,
    now: datetime,
) -> FaucetPolicy:
    release.verify(root)
    active_at = now.astimezone(UTC)
    if active_at < _parse_timestamp(release.effective_from, field="policy effective_from"):
        raise ValueError("FAUCET_POLICY_RELEASE_NOT_ACTIVE")
    if release.effective_until is not None and active_at >= _parse_timestamp(
        release.effective_until, field="policy effective_until"
    ):
        raise ValueError("FAUCET_POLICY_RELEASE_EXPIRED")
    if release.policy_id == "fixed-daily":
        return FixedDailyPolicy(
            amount_q=release.parameters["amount_q"],
            policy_version=release.policy_version,
        )
    return AccumulatingPoolPolicy(
        rate_q=release.parameters["rate_q"],
        interval_seconds=release.parameters["interval_seconds"],
        policy_version=release.policy_version,
    )


def validate_registry_for_manifest(
    root: FaucetPolicyRegistryRoot,
    release: FaucetPolicyRelease,
    *,
    manifest: Any,
    now: datetime,
) -> FaucetPolicy:
    root.verify()
    if (
        root.root_hash != manifest.policy_registry_hash
        or root.network_id != manifest.network_id
        or root.chain_id != manifest.chain_id
        or root.treasury_id != manifest.treasury_id
        or root.creator_recovery_wallet != manifest.creator_recovery_wallet
    ):
        raise ValueError("FAUCET_POLICY_REGISTRY_MANIFEST_MISMATCH")
    return build_policy_from_release(root, release, now=now)
