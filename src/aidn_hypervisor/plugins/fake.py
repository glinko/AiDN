from aidn_hypervisor.plugins.base import ProviderPlugin


class FakeManagedPlugin(ProviderPlugin):
    plugin_id = "fake-managed"

    def describe(self) -> dict:
        return {
            "plugin_id": self.plugin_id,
            "workload_types": ["llm_text", "speech_to_text"],
            "usage_contract": self.usage_contract(),
        }

    def validate_bundle(self, bundle_config) -> None:
        return None

    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        profile = bundle_config.resource_profile
        startup_transient = {}
        runtime_resident = {
            "cpu": profile.steady_cpu,
            "ram_mb": profile.steady_ram_mb,
            "vram_mb": profile.steady_vram_mb,
        }
        if runtime_state is None:
            startup_transient = {
                "cpu": profile.cold_start_cpu,
                "ram_mb": profile.cold_start_ram_mb,
                "vram_mb": profile.cold_start_vram_mb,
            }

        return {
            "startup_transient": startup_transient,
            "runtime_resident": runtime_resident,
            "request_active": {
                "cpu": profile.per_request_cpu,
                "ram_mb": profile.per_request_ram_mb,
                "vram_mb": profile.per_request_vram_mb,
            },
        }

    def build_launch_spec(self, bundle_config) -> dict:
        return {"command": ["python", "-m", "http.server", "0"]}

    def health_check(self, runtime_handle) -> bool:
        return True

    def invoke(self, task, runtime_handle) -> dict:
        return {"ok": True, "task_type": task.task_type}

    def stop(self, runtime_handle) -> None:
        return None
