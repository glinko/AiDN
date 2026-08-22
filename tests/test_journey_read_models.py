from aidn_hypervisor.journey_read_models import build_journey_payload


class _Resources:
    def summary(self):
        return {
            "total": {"cpu": 8, "ram_mb": 32768, "vram_mb": 24576},
            "free": {"cpu": 8, "ram_mb": 24000, "vram_mb": 18000},
        }


class _Service:
    node_id = "node-test"
    resources = _Resources()

    def operator_dashboard_home(self):
        return {"bootstrap": {"node_identity": {"node_id": self.node_id}}}

    def operator_dashboard_fleet(self):
        return {
            "node": {"node_id": self.node_id},
            "bundles": [
                {
                    "bundle_id": "bundle-test",
                    "enabled": True,
                    "launch_mode": "managed_process",
                    "model_id": "model-test",
                    "runtime_status": "running",
                }
            ],
            "queue": {"active": 1, "queued": 0},
        }

    def owner_wallet_state(self):
        return {"configured": True, "wallet_id": "wallet-test"}

    def list_provider_instances(self):
        return [{"provider_instance_id": "provider-test", "operational_state": "healthy"}]

    def list_model_deployments(self):
        return [{"model_deployment_id": "model-test", "operational_state": "ready"}]

    def list_runtime_bindings(self):
        return [{"runtime_binding_id": "binding-test", "status": "ready"}]

    def list_installed_provider_plugins(self):
        return [{"plugin_id": "llama.cpp"}]

    def list_hooks(self):
        return []

    def registry_enabled(self):
        return True

    class _Consensus:
        def status(self):
            return {"status": "ready"}

    consensus_service = _Consensus()


def test_journey_graph_is_canonical_and_progress_is_live():
    graph = build_journey_payload(
        _Service(),
        endpoint_items=[
            {
                "endpoint_id": "endpoint-test",
                "publication_status": "published",
                "validation_summary": {"status": "valid"},
            }
        ],
    )

    by_id = {item["id"]: item for item in graph["nodes"]}
    assert graph["hypervisor"]["node_id"] == "node-test"
    assert by_id["endpoint"]["state"] == "ready"
    assert by_id["validation"]["state"] == "ready"
    assert by_id["serve_requests"]["state"] == "ready"
    assert graph["progress"]["percent"] == 100
    assert graph["recommended_action"]["node_id"] is None
    assert {"from": "bundle", "to": "endpoint", "type": "required"} in graph["edges"]


def test_journey_marks_downstream_work_blocked_when_provider_is_missing():
    service = _Service()
    service.list_provider_instances = lambda: []
    service.list_installed_provider_plugins = lambda: []
    service.list_model_deployments = lambda: []
    service.list_runtime_bindings = lambda: []
    service.operator_dashboard_fleet = lambda: {"node": {"node_id": service.node_id}, "bundles": [], "queue": {}}

    graph = build_journey_payload(service, endpoint_items=[])
    by_id = {item["id"]: item for item in graph["nodes"]}
    assert by_id["provider"]["state"] == "not_started"
    assert by_id["model"]["state"] == "blocked"
    assert by_id["bundle"]["state"] == "blocked"
    assert by_id["endpoint"]["state"] == "blocked"
    assert graph["recommended_action"]["node_id"] == "provider"
