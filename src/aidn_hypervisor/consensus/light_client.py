"""Checkpoint-bound CometBFT light-client verification state machine.

CometBFT signs protobuf SignBytes, so signature and validator-set hashing are
delegated to a compatible cryptographic backend.  This module owns the protocol
logic around that backend: trusted-period expiry, validator voting power,
adjacent transitions, non-adjacent trust overlap and checkpoint rotation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol


@dataclass(frozen=True)
class CometBftValidator:
    """One consensus validator and its voting power at a specific height."""

    address: str
    public_key: str
    voting_power: int

    def __post_init__(self) -> None:
        if not self.address.strip() or not self.public_key.strip():
            raise ValueError("CometBFT validator identity is required")
        if self.voting_power < 1:
            raise ValueError("CometBFT validator voting_power must be positive")


@dataclass(frozen=True)
class CometBftValidatorSet:
    """Validator set returned for one height, with no duplicate addresses."""

    validators: tuple[CometBftValidator, ...]

    def __post_init__(self) -> None:
        if not self.validators:
            raise ValueError("CometBFT validator set must not be empty")
        addresses = [validator.address for validator in self.validators]
        if len(addresses) != len(set(addresses)):
            raise ValueError("CometBFT validator set has duplicate addresses")

    @property
    def total_voting_power(self) -> int:
        return sum(validator.voting_power for validator in self.validators)

    def voting_power_of(self, addresses: set[str]) -> int:
        return sum(
            validator.voting_power
            for validator in self.validators
            if validator.address in addresses
        )


@dataclass(frozen=True)
class TrustedCometBftCheckpoint:
    """Trusted light-client state imported from a verified checkpoint."""

    chain_id: str
    height: int
    block_id: str
    app_hash: str
    header_time: str
    validator_set: CometBftValidatorSet
    validator_set_hash: str
    next_validator_set_hash: str

    def __post_init__(self) -> None:
        required_fields = (
            self.chain_id,
            self.block_id,
            self.app_hash,
            self.header_time,
            self.validator_set_hash,
            self.next_validator_set_hash,
        )
        if any(not field.strip() for field in required_fields):
            raise ValueError("Trusted CometBFT checkpoint has an empty required field")
        if self.height < 1:
            raise ValueError("Trusted CometBFT checkpoint height must be positive")


class CometBftCryptographicBackend(Protocol):
    """Comet-compatible hashing and protobuf SignBytes verification backend."""

    def validator_set_hash(self, validator_set: CometBftValidatorSet) -> str:
        """Return the exact CometBFT validator-set hash."""

    def verified_signer_addresses(
        self,
        *,
        signed_header: dict,
        validator_set: CometBftValidatorSet,
        chain_id: str,
        block_height: int,
        block_id: str,
    ) -> set[str]:
        """Return only validators with valid precommit signatures for this block."""


class CometBftLightClient:
    """Advance trusted CometBFT state only through valid verifier transitions."""

    def __init__(
        self,
        *,
        checkpoint: TrustedCometBftCheckpoint,
        cryptography: CometBftCryptographicBackend,
        trust_period_seconds: int,
        trust_level_numerator: int = 1,
        trust_level_denominator: int = 3,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if trust_period_seconds < 1:
            raise ValueError("CometBFT trust_period_seconds must be positive")
        if trust_level_numerator < 1 or trust_level_denominator < 3:
            raise ValueError("CometBFT trust level is invalid")
        if 3 * trust_level_numerator < trust_level_denominator:
            raise ValueError("CometBFT trust level must be at least one third")
        if 3 * trust_level_numerator >= 2 * trust_level_denominator:
            raise ValueError("CometBFT trust level must be below two thirds")
        if cryptography.validator_set_hash(checkpoint.validator_set) != checkpoint.validator_set_hash:
            raise ValueError("Trusted CometBFT checkpoint validator set hash is invalid")
        self._cryptography = cryptography
        self._trust_period_seconds = trust_period_seconds
        self._trust_level_numerator = trust_level_numerator
        self._trust_level_denominator = trust_level_denominator
        self._now = now or (lambda: datetime.now(UTC))
        self._trusted = checkpoint

    @property
    def trusted_checkpoint(self) -> TrustedCometBftCheckpoint:
        return self._trusted

    def verify_and_trust(
        self,
        *,
        signed_header: dict,
        validator_set: CometBftValidatorSet,
        next_validator_set: CometBftValidatorSet,
        chain_id: str,
        block_height: int,
        block_id: str,
        app_hash: str,
    ) -> bool:
        """Verify one signed header and atomically promote it to trusted state."""
        try:
            candidate = self._checkpoint_from_signed_header(
                signed_header=signed_header,
                validator_set=validator_set,
                next_validator_set=next_validator_set,
                chain_id=chain_id,
                block_height=block_height,
                block_id=block_id,
                app_hash=app_hash,
            )
            if candidate.height == self._trusted.height:
                return (
                    candidate.block_id == self._trusted.block_id
                    and candidate.app_hash == self._trusted.app_hash
                    and candidate.validator_set_hash == self._trusted.validator_set_hash
                )
            if candidate.height < self._trusted.height or not self._trusted_is_current():
                return False
            if self._parse_time(candidate.header_time) <= self._parse_time(self._trusted.header_time):
                return False
            signer_addresses = self._cryptography.verified_signer_addresses(
                signed_header=signed_header,
                validator_set=validator_set,
                chain_id=chain_id,
                block_height=block_height,
                block_id=block_id,
            )
            if not signer_addresses:
                return False
            if not self._has_two_thirds(validator_set, signer_addresses):
                return False
            if candidate.height == self._trusted.height + 1:
                if self._trusted.next_validator_set_hash != candidate.validator_set_hash:
                    return False
            elif not self._has_trusted_overlap(signer_addresses):
                return False
            self._trusted = candidate
            return True
        except (KeyError, TypeError, ValueError):
            return False

    def _checkpoint_from_signed_header(
        self,
        *,
        signed_header: dict,
        validator_set: CometBftValidatorSet,
        next_validator_set: CometBftValidatorSet,
        chain_id: str,
        block_height: int,
        block_id: str,
        app_hash: str,
    ) -> TrustedCometBftCheckpoint:
        header = signed_header.get("header")
        commit = signed_header.get("commit")
        if not isinstance(header, dict) or not isinstance(commit, dict):
            raise ValueError("CometBFT signed header is invalid")
        if header.get("chain_id") != chain_id or int(header.get("height")) != block_height:
            raise ValueError("CometBFT signed header identity is invalid")
        if header.get("app_hash") != app_hash:
            raise ValueError("CometBFT signed header app hash is invalid")
        commit_block_id = commit.get("block_id")
        if not isinstance(commit_block_id, dict) or commit_block_id.get("hash") != block_id:
            raise ValueError("CometBFT commit block binding is invalid")
        validator_hash = self._cryptography.validator_set_hash(validator_set)
        next_validator_hash = self._cryptography.validator_set_hash(next_validator_set)
        if header.get("validators_hash") != validator_hash:
            raise ValueError("CometBFT validator set does not match header")
        if header.get("next_validators_hash") != next_validator_hash:
            raise ValueError("CometBFT next validator set does not match header")
        return TrustedCometBftCheckpoint(
            chain_id=chain_id,
            height=block_height,
            block_id=block_id,
            app_hash=app_hash,
            header_time=str(header.get("time") or ""),
            validator_set=validator_set,
            validator_set_hash=validator_hash,
            next_validator_set_hash=next_validator_hash,
        )

    def _trusted_is_current(self) -> bool:
        trusted_time = self._parse_time(self._trusted.header_time)
        return self._now() <= trusted_time + timedelta(seconds=self._trust_period_seconds)

    def _has_two_thirds(
        self,
        validator_set: CometBftValidatorSet,
        signer_addresses: set[str],
    ) -> bool:
        return 3 * validator_set.voting_power_of(signer_addresses) > 2 * validator_set.total_voting_power

    def _has_trusted_overlap(self, signer_addresses: set[str]) -> bool:
        trusted_power = self._trusted.validator_set.total_voting_power
        signer_power = self._trusted.validator_set.voting_power_of(signer_addresses)
        return (
            signer_power * self._trust_level_denominator
            > trusted_power * self._trust_level_numerator
        )

    def _parse_time(self, value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class CometBftLightClientProofVerifier:
    """Bridge a trusted light-client state machine into the RPC finality source."""

    def __init__(
        self,
        *,
        light_client: CometBftLightClient,
        validator_sets_for_height: Callable[[int], tuple[CometBftValidatorSet, CometBftValidatorSet]],
        verify_transaction_inclusion: Callable[[dict, str, int, str, str], bool],
    ) -> None:
        self._light_client = light_client
        self._validator_sets_for_height = validator_sets_for_height
        self._verify_transaction_inclusion = verify_transaction_inclusion

    def verify_transaction_proof(
        self,
        *,
        transaction_result: dict,
        transaction_hash: str,
        block_height: int,
        block_id: str,
        data_hash: str,
    ) -> bool:
        try:
            return bool(
                self._verify_transaction_inclusion(
                    transaction_result,
                    transaction_hash,
                    block_height,
                    block_id,
                    data_hash,
                )
            )
        except Exception:
            return False

    def verify_commit(
        self,
        *,
        signed_header: dict,
        chain_id: str,
        block_height: int,
        block_id: str,
        app_hash: str,
    ) -> bool:
        try:
            validator_set, next_validator_set = self._validator_sets_for_height(block_height)
            return self._light_client.verify_and_trust(
                signed_header=signed_header,
                validator_set=validator_set,
                next_validator_set=next_validator_set,
                chain_id=chain_id,
                block_height=block_height,
                block_id=block_id,
                app_hash=app_hash,
            )
        except Exception:
            return False
