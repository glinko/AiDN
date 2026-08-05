from __future__ import annotations

from aidn_hypervisor.operator_readiness import build_operator_readiness_payload


class _Resources:
    def __init__(self, summary: dict) -> None:
        self._summary = summary

    def summary(self) -> dict:
        return self._summary


class _Service:
    def __init__(
        self,
        *,
        wallet: dict,
        resources: dict,
        providers: list[dict],
        models: list[dict],
        bindings: list[dict],
        bundles: list[dict],
    ) -> None:
        self.resources = _Resources(resources)
        self._wallet = wallet
        self._providers = providers
        self._models = models
        self._bindings = bindings
        self._bundles = bundles

    def owner_wallet_state(self) -> dict:
        return self._wallet

    def list_provider_instances(self) -> list[dict]:
        return self._providers

    def list_model_deployments(self) -> list[dict]:
        return self._models

    def list_runtime_bindings(self) -> list[dict]:
        return self._bindings

    def operator_dashboard_fleet(self) -> dict:
        return {"bundles": self._bundles}


def _empty_service() -> _Service:
    return _Service(
        wallet={"configured": False, "wallet_id": None, "label": None},
        resources={
            "total": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
            "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
            "free": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
        },
        providers=[],
        models=[],
        bindings=[],
        bundles=[],
    )


def test_readiness_reports_real_prerequisite_blockers() -> None:
    payload = build_operator_readiness_payload(
        service=_empty_service(),
        consensus_status={"enabled": True, "rpc": {"available": False}},
    )

    assert payload["overall_state"] == "blocked"
    assert payload["execution_ready"] is False
    assert payload["network_ready"] is False
    assert payload["next_action"]["label"] == "Fix CometBFT"
    assert {step["key"] for step in payload["steps"] if step["blocking"]} == {
        "consensus",
        "wallet",
        "resources",
        "provider",
        "model_deployment",
        "runtime_binding",
        "bundle",
        "endpoint",
    }


def test_readiness_exposes_provider_model_discovery_as_next_safe_action() -> None:
    service = _Service(
        wallet={"configured": True, "wallet_id": "wallet-operator", "label": "Operator"},
        resources={
            "total": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 24576},
            "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
            "free": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 24576},
        },
        providers=[
            {
                "provider_instance_id": "pi-ollama",
                "operational_state": "ready",
            }
        ],
        models=[],
        bindings=[],
        bundles=[],
    )

    payload = build_operator_readiness_payload(
        service=service,
        consensus_status={"enabled": True, "rpc": {"available": True}},
    )

    model_step = next(step for step in payload["steps"] if step["key"] == "model_deployment")
    assert model_step["action"] == {
        "kind": "discover-provider",
        "label": "Discover models",
        "detail": "Run model discovery against the ready provider, then choose the deployment for Runtime Binding.",
        "provider_instance_id": "pi-ollama",
    }


def test_readiness_reaches_ready_only_after_runtime_and_publication_chain_exists() -> None:
    service = _Service(
        wallet={"configured": True, "wallet_id": "wallet-operator", "label": "Operator"},
        resources={
            "total": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 24576},
            "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
            "free": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 24576},
        },
        providers=[
            {
                "provider_instance_id": "pi-ollama",
                "operational_state": "ready",
            }
        ],
        models=[
            {
                "model_deployment_id": "md-qwen",
                "operational_state": "ready",
            }
        ],
        bindings=[{"runtime_binding_id": "rb-qwen", "status": "ready"}],
        bundles=[{"bundle_id": "bundle-qwen", "enabled": True}],
    )

    payload = build_operator_readiness_payload(
        service=service,
        endpoint_items=[
            {"endpoint_id": "endpoint-qwen", "publication_status": "published"}
        ],
        consensus_status={"enabled": True, "rpc": {"available": True}},
    )

    assert payload["overall_state"] == "ready"
    assert payload["execution_ready"] is True
    assert payload["network_ready"] is True
    assert payload["progress"] == {"ready": 8, "total": 8, "percent": 100}
