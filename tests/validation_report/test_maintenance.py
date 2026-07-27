"""M11-S6: Maintenance Validation Engine — unit tests."""

from __future__ import annotations

import random

from aidn_hypervisor.validation_report.maintenance import (
    MaintenanceValidationEngine,
)
from aidn_hypervisor.validation_report.models import (
    MaintenanceTriggerType,
)


class TestMetricTriggers:
    def test_low_reputation_triggers(self):
        engine = MaintenanceValidationEngine(reputation_threshold=0.30)
        engine.register_endpoint("ep-1", 1)
        triggers = engine.check_metrics(
            "ep-1", 5, reputation_score=0.15
        )
        assert len(triggers) == 1
        assert triggers[0].trigger_type == MaintenanceTriggerType.DECREASING_REPUTATION

    def test_high_reputation_no_trigger(self):
        engine = MaintenanceValidationEngine(reputation_threshold=0.30)
        engine.register_endpoint("ep-1", 1)
        triggers = engine.check_metrics(
            "ep-1", 5, reputation_score=0.80
        )
        assert len(triggers) == 0

    def test_low_latency_triggers(self):
        engine = MaintenanceValidationEngine(latency_threshold=0.50)
        engine.register_endpoint("ep-1", 1)
        triggers = engine.check_metrics(
            "ep-1", 5, latency_score=0.30
        )
        assert len(triggers) == 1
        assert triggers[0].trigger_type == MaintenanceTriggerType.INCREASED_LATENCY

    def test_high_error_rate_triggers(self):
        engine = MaintenanceValidationEngine(error_rate_threshold=0.40)
        engine.register_endpoint("ep-1", 1)
        triggers = engine.check_metrics(
            "ep-1", 5, error_rate=0.70
        )
        assert len(triggers) == 1
        assert triggers[0].trigger_type == MaintenanceTriggerType.INCREASED_ERROR_RATE

    def test_multiple_triggers(self):
        engine = MaintenanceValidationEngine()
        engine.register_endpoint("ep-1", 1)
        triggers = engine.check_metrics(
            "ep-1",
            5,
            reputation_score=0.10,
            latency_score=0.20,
            error_rate=0.80,
        )
        assert len(triggers) == 3


class TestPeriodicTriggers:
    def test_periodic_trigger(self):
        engine = MaintenanceValidationEngine(periodic_interval=5)
        engine.register_endpoint("ep-1", 1)
        triggers = engine.check_periodic(epoch=6, rng=random.Random(9999))
        periodic = [
            t for t in triggers
            if t.trigger_type == MaintenanceTriggerType.PERIODIC
        ]
        assert len(periodic) >= 1

    def test_no_periodic_before_interval(self):
        engine = MaintenanceValidationEngine(periodic_interval=10)
        engine.register_endpoint("ep-1", 1)
        triggers = engine.check_periodic(epoch=5, rng=random.Random(9999))
        periodic = [
            t for t in triggers
            if t.trigger_type == MaintenanceTriggerType.PERIODIC
        ]
        assert len(periodic) == 0

    def test_random_trigger(self):
        engine = MaintenanceValidationEngine(random_probability=1.0)
        engine.register_endpoint("ep-1", 1)
        triggers = engine.check_periodic(epoch=1, rng=random.Random(42))
        random_triggers = [
            t for t in triggers
            if t.trigger_type == MaintenanceTriggerType.RANDOM_EPOCH
        ]
        assert len(random_triggers) >= 1


class TestValidationResult:
    def test_update_success(self):
        engine = MaintenanceValidationEngine()
        engine.register_endpoint("ep-1", 1)
        engine.update_validation_result("ep-1", 5, True, "vr-1")
        state = engine.get_state("ep-1")
        assert state is not None
        assert state.validation_count == 1
        assert state.successful_validations == 1
        assert state.success_rate == 1.0

    def test_update_failure(self):
        engine = MaintenanceValidationEngine()
        engine.register_endpoint("ep-1", 1)
        engine.update_validation_result("ep-1", 5, False, "vr-1")
        state = engine.get_state("ep-1")
        assert state is not None
        assert state.failed_validations == 1
        assert state.success_rate == 0.0

    def test_mixed_results(self):
        engine = MaintenanceValidationEngine()
        engine.register_endpoint("ep-1", 1)
        engine.update_validation_result("ep-1", 1, True, "vr-1")
        engine.update_validation_result("ep-1", 2, True, "vr-2")
        engine.update_validation_result("ep-1", 3, False, "vr-3")
        state = engine.get_state("ep-1")
        assert state is not None
        assert state.validation_count == 3
        assert state.success_rate == 2 / 3

    def test_triggers_for_endpoint(self):
        engine = MaintenanceValidationEngine(reputation_threshold=0.30)
        engine.register_endpoint("ep-1", 1)
        engine.check_metrics("ep-1", 5, reputation_score=0.10)
        triggers = engine.get_triggers_for_endpoint("ep-1")
        assert len(triggers) >= 1

    def test_state_unknown_endpoint(self):
        engine = MaintenanceValidationEngine()
        state = engine.get_state("unknown")
        assert state is None
