from abc import ABC, abstractmethod


class ProviderPlugin(ABC):
    plugin_id: str

    @abstractmethod
    def describe(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def validate_bundle(self, bundle_config) -> None:
        raise NotImplementedError

    @abstractmethod
    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        raise NotImplementedError

    @abstractmethod
    def build_launch_spec(self, bundle_config) -> dict:
        raise NotImplementedError

    @abstractmethod
    def health_check(self, runtime_handle) -> bool:
        raise NotImplementedError

    @abstractmethod
    def invoke(self, task, runtime_handle) -> dict:
        raise NotImplementedError

    @abstractmethod
    def stop(self, runtime_handle) -> None:
        raise NotImplementedError

    def bundle_defaults_from_install(self, *, model_id: str, target_path: str) -> dict:
        return {
            "model_id": target_path,
            "launch_mode": "managed_process",
            "device_affinity": "cpu",
        }

    def retry_policy(self) -> dict:
        return {}

    def circuit_breaker_policy(self) -> dict:
        return {}

    def supports_restart_retry(self, task, bundle_config) -> bool:
        return False

    def usage_contract(self) -> dict:
        return {
            "supports_exact": False,
            "supports_estimated": False,
            "default_measurement_source": None,
            "fallback_measurement_source": None,
            "fallback_policy": "none",
            "missing_usage_behavior": "skip",
        }
