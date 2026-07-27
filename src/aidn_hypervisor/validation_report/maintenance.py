"""M11-S6: Maintenance Validation Engine — trigger detection, scheduling."""

from __future__ import annotations

import random

from aidn_hypervisor.validation_report.models import (
    EndpointValidationState,
    MaintenanceTrigger,
    MaintenanceTriggerType,
)


class MaintenanceValidationEngine:
    """Detects and schedules maintenance validation triggers.

    Triggers (ECO-0003 §7):
    - Decreasing reputation
    - Increased latency
    - Increased error rate
    - Suspicious behavior
    - Random epoch selection
    - Periodic scheduling
    """

    def __init__(
        self,
        reputation_threshold: float = 0.30,
        latency_threshold: float = 0.50,
        error_rate_threshold: float = 0.40,
        periodic_interval: int = 10,
        random_probability: float = 0.05,
    ) -> None:
        self._rep_threshold = reputation_threshold
        self._latency_threshold = latency_threshold
        self._error_threshold = error_rate_threshold
        self._periodic_interval = periodic_interval
        self._random_prob = random_probability

        # endpoint_id → EndpointValidationState
        self._states: dict[str, EndpointValidationState] = {}
        # Trigger history
        self._triggers: list[MaintenanceTrigger] = []

    def register_endpoint(
        self,
        endpoint_id: str,
        current_epoch: int,
    ) -> None:
        """Register an endpoint for maintenance tracking."""
        self._states[endpoint_id] = EndpointValidationState(
            endpoint_id=endpoint_id,
            certification_status="unvalidated",
            last_validation_epoch=0,
            next_scheduled_epoch=current_epoch + self._periodic_interval,
        )

    def check_metrics(
        self,
        endpoint_id: str,
        epoch: int,
        *,
        reputation_score: float | None = None,
        latency_score: float | None = None,
        error_rate: float | None = None,
    ) -> list[MaintenanceTrigger]:
        """Check metrics and generate triggers if thresholds exceeded.

        Args:
            endpoint_id: Endpoint to check.
            epoch: Current epoch.
            reputation_score: Current reputation (higher = better).
            latency_score: Latency quality (higher = better).
            error_rate: Error rate (lower = better).

        Returns:
            List of MaintenanceTrigger items generated.
        """
        triggers: list[MaintenanceTrigger] = []

        # Check reputation
        if reputation_score is not None:
            if reputation_score < self._rep_threshold:
                trigger = MaintenanceTrigger(
                    trigger_type=MaintenanceTriggerType.DECREASING_REPUTATION,
                    endpoint_id=endpoint_id,
                    epoch_detected=epoch,
                    severity=1.0 - reputation_score,
                    metric_value=reputation_score,
                    metric_threshold=self._rep_threshold,
                    description=f"Reputation {reputation_score:.2f} below {self._rep_threshold:.2f}",
                )
                triggers.append(trigger)
                self._triggers.append(trigger)

        # Check latency
        if latency_score is not None:
            if latency_score < self._latency_threshold:
                trigger = MaintenanceTrigger(
                    trigger_type=MaintenanceTriggerType.INCREASED_LATENCY,
                    endpoint_id=endpoint_id,
                    epoch_detected=epoch,
                    severity=1.0 - latency_score,
                    metric_value=latency_score,
                    metric_threshold=self._latency_threshold,
                    description=f"Latency {latency_score:.2f} below {self._latency_threshold:.2f}",
                )
                triggers.append(trigger)
                self._triggers.append(trigger)

        # Check error rate (inverted: high error rate = bad)
        if error_rate is not None:
            if error_rate > (1.0 - self._error_threshold):
                trigger = MaintenanceTrigger(
                    trigger_type=MaintenanceTriggerType.INCREASED_ERROR_RATE,
                    endpoint_id=endpoint_id,
                    epoch_detected=epoch,
                    severity=error_rate,
                    metric_value=error_rate,
                    metric_threshold=1.0 - self._error_threshold,
                    description=f"Error rate {error_rate:.2f} above threshold",
                )
                triggers.append(trigger)
                self._triggers.append(trigger)

        return triggers

    def check_periodic(
        self, epoch: int, rng: random.Random | None = None
    ) -> list[MaintenanceTrigger]:
        """Check periodic and random triggers for all endpoints.

        Args:
            epoch: Current epoch.
            rng: Optional random generator for determinism.

        Returns:
            List of MaintenanceTrigger items generated.
        """
        if rng is None:
            rng = random.Random(epoch)

        triggers: list[MaintenanceTrigger] = []

        for endpoint_id, state in self._states.items():
            # Periodic check
            next_sched = state.next_scheduled_epoch
            if epoch >= next_sched:
                trigger = MaintenanceTrigger(
                    trigger_type=MaintenanceTriggerType.PERIODIC,
                    endpoint_id=endpoint_id,
                    epoch_detected=epoch,
                    severity=0.5,
                    description=f"Periodic validation at epoch {epoch}",
                )
                triggers.append(trigger)
                self._triggers.append(trigger)

                # Update state
                self._states[endpoint_id] = state.model_copy(
                    update={
                        "last_validation_epoch": epoch,
                        "next_scheduled_epoch": epoch + self._periodic_interval,
                        "trigger_count": state.trigger_count + 1,
                    }
                )

            # Random check
            if rng.random() < self._random_prob:
                trigger = MaintenanceTrigger(
                    trigger_type=MaintenanceTriggerType.RANDOM_EPOCH,
                    endpoint_id=endpoint_id,
                    epoch_detected=epoch,
                    severity=0.3,
                    description=f"Random selection at epoch {epoch}",
                )
                triggers.append(trigger)
                self._triggers.append(trigger)

                self._states[endpoint_id] = state.model_copy(
                    update={
                        "trigger_count": state.trigger_count + 1,
                    }
                )

        return triggers

    def update_validation_result(
        self,
        endpoint_id: str,
        epoch: int,
        success: bool,
        report_id: str,
    ) -> None:
        """Update endpoint state after validation."""
        state = self._states.get(endpoint_id)
        if state is None:
            return

        new_success = state.successful_validations + (1 if success else 0)
        new_failed = state.failed_validations + (0 if success else 1)

        self._states[endpoint_id] = state.model_copy(
            update={
                "last_validation_epoch": epoch,
                "validation_count": state.validation_count + 1,
                "successful_validations": new_success,
                "failed_validations": new_failed,
                "last_report_id": report_id,
            }
        )

    def get_state(
        self, endpoint_id: str
    ) -> EndpointValidationState | None:
        """Get validation state for an endpoint."""
        return self._states.get(endpoint_id)

    def get_triggers_for_endpoint(
        self, endpoint_id: str
    ) -> list[MaintenanceTrigger]:
        """Get all triggers for an endpoint."""
        return [
            t for t in self._triggers
            if t.endpoint_id == endpoint_id
        ]
