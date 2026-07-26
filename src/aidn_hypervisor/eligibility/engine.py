"""M11-S3: Eligibility Engine — gate checks, state derivation, snapshots."""

from __future__ import annotations

from aidn_hypervisor.eligibility.kcg import KCGManager
from aidn_hypervisor.eligibility.models import (
    ACTIVATION_AGE_EPOCHS,
    MIN_SERVICE_HEALTH,
    EligibilityGateResult,
    EligibilitySnapshot,
    EligibilityState,
    GateCheck,
    IneligibilityReason,
)


class EligibilityEngine:
    """Evaluates participant eligibility against RFC gates.

    Gates (ECO-0004 §8, ECO-0006 §8):
    1. Valid Service Identity
    2. Valid owner + Reward Beneficiary
    3. Activation age (10 epochs)
    4. Required Stake/Bond
    5. Compatible protocol version
    6. No active suspension
    7. Minimum Service Health (0.70)
    8. Required Duty Proof
    """

    def __init__(
        self,
        kcg_manager: KCGManager | None = None,
        min_stake: int = 500_000_000,
        activation_age: int = ACTIVATION_AGE_EPOCHS,
        min_health: float = MIN_SERVICE_HEALTH,
    ) -> None:
        self._kcg = kcg_manager or KCGManager()
        self._min_stake = min_stake
        self._activation_age = activation_age
        self._min_health = min_health

        # service_id → state
        self._states: dict[str, EligibilityState] = {}
        # service_id → activation epoch
        self._activation_epochs: dict[str, int] = {}
        # service_id → rating score
        self._rating_scores: dict[str, float] = {}
        # service_id → health score
        self._health_scores: dict[str, float] = {}
        # service_id → stake
        self._stakes: dict[str, int] = {}
        # service_id → has_duty_proof
        self._duty_proofs: dict[str, bool] = {}
        # service_id → suspended flag
        self._suspended: dict[str, bool] = {}
        # service_id → protocol version
        self._protocol_versions: dict[str, str] = {}

    # ── Registration ───────────────────────────────────────────

    def register_participant(
        self,
        service_id: str,
        *,
        stake: int,
        activation_epoch: int,
        protocol_version: str = "1.0.0",
        reward_beneficiary: str | None = None,
    ) -> None:
        """Register a participant for eligibility tracking."""
        self._states[service_id] = EligibilityState.PENDING
        self._activation_epochs[service_id] = activation_epoch
        self._stakes[service_id] = stake
        self._protocol_versions[service_id] = protocol_version
        self._rating_scores.setdefault(service_id, 0.5)
        self._health_scores.setdefault(service_id, 1.0)
        self._duty_proofs.setdefault(service_id, False)
        self._suspended.setdefault(service_id, False)

        if reward_beneficiary is not None:
            self._kcg.register_service(
                service_id, reward_beneficiary, stake, activation_epoch
            )

    def update_rating(self, service_id: str, score: float) -> None:
        """Update a participant's rating score."""
        self._rating_scores[service_id] = max(0.0, min(1.0, score))

    def update_health(self, service_id: str, score: float) -> None:
        """Update a participant's health score."""
        self._health_scores[service_id] = max(0.0, min(1.0, score))

    def set_duty_proof(self, service_id: str, has_proof: bool) -> None:
        """Set whether a participant has duty proof."""
        self._duty_proofs[service_id] = has_proof

    def suspend(self, service_id: str) -> None:
        """Suspend a participant."""
        self._suspended[service_id] = True
        self._states[service_id] = EligibilityState.SUSPENDED

    def unsuspend(self, service_id: str) -> None:
        """Unsuspend a participant."""
        self._suspended[service_id] = False

    def retire(self, service_id: str) -> None:
        """Retire a participant."""
        self._states[service_id] = EligibilityState.RETIRED

    # ── Gate Evaluation ────────────────────────────────────────

    def evaluate_gates(
        self,
        service_id: str,
        current_epoch: int,
        *,
        required_protocol_version: str = "1.0.0",
    ) -> EligibilityGateResult:
        """Run all eligibility gates for a participant.

        Returns:
            EligibilityGateResult with per-gate results.
        """
        checks: list[GateCheck] = []
        reasons: list[IneligibilityReason] = []

        # Gate 1: Valid Service Identity
        if service_id not in self._states:
            checks.append(
                GateCheck(
                    gate_name="valid_identity",
                    passed=False,
                    detail="Service not registered",
                )
            )
            return EligibilityGateResult(
                service_id=service_id,
                epoch=current_epoch,
                eligible=False,
                checks=checks,
                ineligibility_reasons=[],
            )

        checks.append(
            GateCheck(gate_name="valid_identity", passed=True)
        )

        # Gate 2: Activation age
        activation_epoch = self._activation_epochs.get(service_id, 0)
        age = current_epoch - activation_epoch
        age_ok = age >= self._activation_age
        checks.append(
            GateCheck(
                gate_name="activation_age",
                passed=age_ok,
                detail=f"age={age}/{self._activation_age} epochs",
            )
        )
        if not age_ok:
            reasons.append(IneligibilityReason.ACTIVATION_AGE_NOT_MET)

        # Gate 3: Required Stake
        stake = self._stakes.get(service_id, 0)
        stake_ok = stake >= self._min_stake
        checks.append(
            GateCheck(
                gate_name="required_stake",
                passed=stake_ok,
                detail=f"stake={stake}/{self._min_stake}",
            )
        )
        if not stake_ok:
            reasons.append(IneligibilityReason.INSUFFICIENT_STAKE)

        # Gate 4: Protocol version
        version = self._protocol_versions.get(service_id, "")
        version_ok = version == required_protocol_version
        checks.append(
            GateCheck(
                gate_name="protocol_version",
                passed=version_ok,
                detail=f"version={version}",
            )
        )
        if not version_ok:
            reasons.append(IneligibilityReason.PROTOCOL_VERSION_MISMATCH)

        # Gate 5: No active suspension
        is_suspended = self._suspended.get(service_id, False)
        checks.append(
            GateCheck(
                gate_name="no_suspension",
                passed=not is_suspended,
                detail="suspended" if is_suspended else "clear",
            )
        )
        if is_suspended:
            reasons.append(IneligibilityReason.SUSPENDED)

        # Gate 6: Minimum Service Health
        health = self._health_scores.get(service_id, 0.0)
        health_ok = health >= self._min_health
        checks.append(
            GateCheck(
                gate_name="minimum_health",
                passed=health_ok,
                detail=f"health={health:.2f}/{self._min_health:.2f}",
            )
        )
        if not health_ok:
            reasons.append(IneligibilityReason.HEALTH_BELOW_THRESHOLD)

        # Gate 7: Duty Proof
        has_proof = self._duty_proofs.get(service_id, False)
        checks.append(
            GateCheck(
                gate_name="duty_proof",
                passed=has_proof,
                detail="provided" if has_proof else "missing",
            )
        )
        if not has_proof:
            reasons.append(IneligibilityReason.DUTY_PROOF_MISSING)

        eligible = all(c.passed for c in checks)

        # Update state based on result
        if eligible:
            self._states[service_id] = EligibilityState.ACTIVE
        else:
            self._states[service_id] = EligibilityState.INELIGIBLE

        return EligibilityGateResult(
            service_id=service_id,
            epoch=current_epoch,
            eligible=eligible,
            checks=checks,
            ineligibility_reasons=reasons,
        )

    # ── Snapshots ──────────────────────────────────────────────

    def create_snapshot(
        self, service_id: str, current_epoch: int
    ) -> EligibilitySnapshot | None:
        """Create an eligibility snapshot for a participant."""
        if service_id not in self._states:
            return None

        activation_epoch = self._activation_epochs.get(service_id, 0)
        age = current_epoch - activation_epoch

        return EligibilitySnapshot(
            epoch=current_epoch,
            service_id=service_id,
            state=self._states[service_id],
            rating_score=self._rating_scores.get(service_id, 0.0),
            health_score=self._health_scores.get(service_id, 0.0),
            kcg_id=self._kcg.get_service_group_id(service_id),
            activation_age=age,
            has_duty_proof=self._duty_proofs.get(service_id, False),
        )

    # ── Queries ────────────────────────────────────────────────

    def get_state(self, service_id: str) -> EligibilityState | None:
        """Get the eligibility state of a participant."""
        return self._states.get(service_id)

    def get_active_participants(self) -> list[str]:
        """Get all participants in ACTIVE state."""
        return [
            sid
            for sid, state in self._states.items()
            if state == EligibilityState.ACTIVE
        ]

    @property
    def kcg_manager(self) -> KCGManager:
        """Access the KCG manager."""
        return self._kcg
