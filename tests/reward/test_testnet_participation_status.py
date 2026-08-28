from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from aidn_hypervisor.main import build_app
from aidn_hypervisor.testnet_participation_monitor import TestnetParticipationMonitorStatus
from aidn_hypervisor.testnet_participation_runtime import (
    TestnetParticipationManagedRuntime,
    TestnetParticipationRuntimeConfig,
)
from aidn_hypervisor.testnet_participation_status import (
    build_testnet_participation_status_payload,
)


def test_status_is_unavailable_when_the_runtime_monitor_is_not_installed() -> None:
    assert build_testnet_participation_status_payload(None) == {
        "available": False,
        "runtime": {"enabled": False, "mode": "disabled"},
        "program": None,
        "monitor": {"scan_count": 0, "transition_count": 0, "processed_count": 0},
        "last_settlement": None,
        "last_error_code": None,
    }


def test_status_redacts_treasury_details_from_monitor_errors() -> None:
    runtime = TestnetParticipationManagedRuntime(
        config=TestnetParticipationRuntimeConfig(
            active_network_id="aidn-testnet",
            active_chain_id="aidn-testnet-1",
        )
    )
    monitor = SimpleNamespace(
        dispatcher=SimpleNamespace(runtime=runtime),
        status=lambda: TestnetParticipationMonitorStatus(
            scan_count=3,
            transition_count=2,
            processed_count=1,
            last_error=(
                "ValueError: PARTICIPATION_RUNTIME_TREASURY_SECRET_REF_INVALID "
                "secret://testnet/treasury"
            ),
        ),
    )

    payload = build_testnet_participation_status_payload(monitor)
    rendered = json.dumps(payload)

    assert payload["available"] is True
    assert payload["runtime"] == {"enabled": False, "mode": "inspect"}
    assert payload["last_error_code"] == "PARTICIPATION_RUNTIME_TREASURY_SECRET_REF_INVALID"
    assert "secret://" not in rendered
    assert "treasury_wallet" not in rendered
    assert "treasury_signer_secret_ref" not in rendered


def test_dashboard_status_endpoint_is_safe_when_the_runtime_is_not_configured() -> None:
    response = TestClient(build_app()).get("/operators/dashboard/testnet-participation")

    assert response.status_code == 200
    assert response.json()["available"] is False
