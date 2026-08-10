"""Replaceable Faucet policy implementations.

Policies calculate an amount only. They never mutate the Ledger and never
create Q. The service persists the returned next state only after finality.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any

from aidn_faucet.models import (
    FAUCET_POLICY_VERSION,
    Q_ATOMS_PER_Q,
    PolicyDecision,
    canonical_hash,
)


class FaucetPolicyError(ValueError):
    """A deterministic policy refusal that must not create a transfer."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


class FaucetPolicy(ABC):
    policy_id: str
    policy_version: str

    @abstractmethod
    def initial_state(self, *, now: datetime) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def quota_key(self, *, wallet_id: str, state: dict[str, Any], now: datetime) -> str:
        raise NotImplementedError

    @abstractmethod
    def decide(
        self,
        *,
        wallet_id: str,
        state: dict[str, Any],
        now: datetime,
        quota_exists: bool,
    ) -> PolicyDecision:
        raise NotImplementedError


class FixedDailyPolicy(FaucetPolicy):
    """Give one controlled amount per Wallet and UTC calendar day."""

    policy_id = "fixed-daily"
    policy_version = FAUCET_POLICY_VERSION + ".fixed-daily.1"

    def __init__(self, *, amount_q: int = 50, policy_version: str | None = None) -> None:
        if amount_q <= 0:
            raise ValueError("fixed daily amount must be positive")
        self.amount_q_atoms = amount_q * Q_ATOMS_PER_Q
        if policy_version is not None:
            if not policy_version.strip():
                raise ValueError("fixed daily policy version must not be empty")
            self.policy_version = policy_version

    def initial_state(self, *, now: datetime) -> dict[str, Any]:
        return {}

    def quota_key(self, *, wallet_id: str, state: dict[str, Any], now: datetime) -> str:
        return f"{wallet_id}:{now.astimezone(UTC).date().isoformat()}"

    def decide(
        self,
        *,
        wallet_id: str,
        state: dict[str, Any],
        now: datetime,
        quota_exists: bool,
    ) -> PolicyDecision:
        quota_key = self.quota_key(wallet_id=wallet_id, state=state, now=now)
        if quota_exists:
            raise FaucetPolicyError("FAUCET_QUOTA_EXHAUSTED", "wallet has already claimed its daily allocation")
        unsigned = {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "quota_key": quota_key,
            "amount_q_atoms": self.amount_q_atoms,
            "wallet_id": wallet_id,
            "decision_at": now.astimezone(UTC).isoformat(),
        }
        return PolicyDecision(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            quota_key=quota_key,
            amount_q_atoms=self.amount_q_atoms,
            decision_hash=canonical_hash(unsigned),
            state_after_success={},
        )


class AccumulatingPoolPolicy(FaucetPolicy):
    """Accumulate a global pool and release it to one requester per cycle."""

    policy_id = "accumulating-pool"
    policy_version = FAUCET_POLICY_VERSION + ".accumulating-pool.1"

    def __init__(
        self,
        *,
        rate_q: int = 5,
        interval_seconds: int = 60,
        policy_version: str | None = None,
    ) -> None:
        if rate_q <= 0 or interval_seconds <= 0:
            raise ValueError("accumulating pool parameters must be positive")
        self.rate_q_atoms = rate_q * Q_ATOMS_PER_Q
        self.interval_seconds = interval_seconds
        if policy_version is not None:
            if not policy_version.strip():
                raise ValueError("accumulating pool policy version must not be empty")
            self.policy_version = policy_version

    def initial_state(self, *, now: datetime) -> dict[str, Any]:
        timestamp = now.astimezone(UTC).isoformat()
        return {
            "generation": 0,
            "last_drip_at": timestamp,
            "accumulated_q_atoms": 0,
        }

    def _accrued_state(self, *, state: dict[str, Any], now: datetime) -> tuple[dict[str, Any], int]:
        try:
            last_drip = datetime.fromisoformat(str(state["last_drip_at"]))
            generation = int(state["generation"])
            accumulated = int(state["accumulated_q_atoms"])
        except (KeyError, TypeError, ValueError) as error:
            raise FaucetPolicyError("FAUCET_POLICY_STATE_INVALID", "accumulating pool state is invalid") from error
        if last_drip.tzinfo is None or generation < 0 or accumulated < 0:
            raise FaucetPolicyError("FAUCET_POLICY_STATE_INVALID", "accumulating pool state is invalid")
        elapsed = max(0, int((now.astimezone(UTC) - last_drip.astimezone(UTC)).total_seconds()))
        intervals = elapsed // self.interval_seconds
        accrued = accumulated + intervals * self.rate_q_atoms
        next_drip = last_drip.astimezone(UTC)
        if intervals:
            next_drip = next_drip.replace() + timedelta(seconds=intervals * self.interval_seconds)
        return (
            {
                "generation": generation,
                "last_drip_at": next_drip.isoformat(),
                "accumulated_q_atoms": accrued,
            },
            accrued,
        )

    def quota_key(self, *, wallet_id: str, state: dict[str, Any], now: datetime) -> str:
        del wallet_id, now
        try:
            generation = int(state["generation"])
        except (KeyError, TypeError, ValueError) as error:
            raise FaucetPolicyError("FAUCET_POLICY_STATE_INVALID", "accumulating pool generation is invalid") from error
        return f"pool-generation:{generation}"

    def decide(
        self,
        *,
        wallet_id: str,
        state: dict[str, Any],
        now: datetime,
        quota_exists: bool,
    ) -> PolicyDecision:
        accrued_state, amount = self._accrued_state(state=state, now=now)
        quota_key = self.quota_key(wallet_id=wallet_id, state=accrued_state, now=now)
        if quota_exists:
            raise FaucetPolicyError("FAUCET_POOL_CLAIM_PENDING", "the current pool generation already has a claim")
        if amount <= 0:
            raise FaucetPolicyError("FAUCET_POOL_EMPTY", "the accumulation interval has not elapsed")
        next_state = {
            "generation": int(accrued_state["generation"]) + 1,
            "last_drip_at": now.astimezone(UTC).isoformat(),
            "accumulated_q_atoms": 0,
        }
        unsigned = {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "quota_key": quota_key,
            "amount_q_atoms": amount,
            "wallet_id": wallet_id,
            "state_after_success": next_state,
        }
        return PolicyDecision(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            quota_key=quota_key,
            amount_q_atoms=amount,
            decision_hash=canonical_hash(unsigned),
            state_after_success=next_state,
        )
