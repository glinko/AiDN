"""Lease-gated inference adapter for the resident Node Steward.

The resident agent is intentionally a control-plane component.  This module
is the narrow execution boundary it may use when an operator has explicitly
prepared a local model.  It never downloads artifacts and it never starts a
provider before the Resource Broker grants an atomic lease.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.resident_model_manager import ResidentModelError, ResidentModelManager
from aidn_hypervisor.resources import (
    ResourceAdmissionError,
    ResourceReconciliationRequiredError,
)
from aidn_hypervisor.runtime_parameter_policy import (
    normalize_runtime_parameter_policy,
    policy_json,
)


class ResidentInferenceError(ValueError):
    """Stable, operator-safe error from the resident inference boundary."""

    code = "INFERENCE_ADAPTER_ERROR"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


class ResidentInferenceResourceWait(ResidentInferenceError):
    code = "INFERENCE_RESOURCE_WAIT"


@dataclass(frozen=True)
class InferenceResourceRequest:
    """Resource commitment for a resident runtime and one request."""

    cpu: float = 0.25
    ram_mb: int = 1024
    vram_mb: int = 0
    request_cpu: float = 0.05
    request_ram_mb: int = 64
    request_vram_mb: int = 0
    lease_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.cpu < 0 or self.request_cpu < 0:
            raise ValueError("resident CPU resource values must be non-negative")
        for name in ("ram_mb", "vram_mb", "request_ram_mb", "request_vram_mb"):
            value = getattr(self, name)
            if isinstance(value, bool) or int(value) < 0:
                raise ValueError(f"resident {name} must be non-negative")
        if self.lease_seconds is not None and (
            isinstance(self.lease_seconds, bool) or int(self.lease_seconds) <= 0
        ):
            raise ValueError("resident lease_seconds must be positive")

    def as_payload(self) -> dict[str, Any]:
        return {
            "cpu": self.cpu,
            "ram_mb": self.ram_mb,
            "vram_mb": self.vram_mb,
            "request_cpu": self.request_cpu,
            "request_ram_mb": self.request_ram_mb,
            "request_vram_mb": self.request_vram_mb,
            "lease_seconds": self.lease_seconds,
        }


_PROFILES = {"CPU_RESIDENT", "IGPU_RESIDENT", "GPU_RESIDENT", "GPU_BURST"}
_GPU_PROFILES = {"GPU_RESIDENT", "GPU_BURST"}
_CPU_PROFILES = {"CPU_RESIDENT", "IGPU_RESIDENT"}


def _apply_profile_residency_policy(
    provider_type: str,
    profile: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Make the execution profile authoritative for accelerator residency.

    The generic llama.cpp policy intentionally defaults to ``gpu_layers=99``
    for operator-managed GPU endpoints.  That default must not leak into a
    CPU/iGPU Resident Steward profile: those profiles reserve no VRAM, so a
    non-zero layer setting would make the launch command contradict the
    Resource Broker lease and could still make llama.cpp probe or allocate a
    GPU.  Keep the override operator-owned and apply it both when preparing a
    config and again at start for restored legacy snapshots.
    """

    effective = dict(policy or {})
    if (
        str(provider_type).strip().lower() == "llama.cpp"
        and str(profile).strip().upper() in _CPU_PROFILES
    ):
        current = effective.get("gpu_layers")
        if hasattr(current, "model_copy"):
            # Keep the normalized Pydantic representation used during
            # preparation; the persisted start path receives JSON mappings.
            effective["gpu_layers"] = current.model_copy(
                update={"value": 0, "consumer_editable": False}
            )
        else:
            effective["gpu_layers"] = {
                "value": 0,
                "consumer_editable": False,
                "min": 0,
                "max": 999,
            }
    return effective


def _bounded_path(value: str) -> Path:
    raw = str(value or "").strip()
    if not raw or len(raw) > 2048:
        raise ResidentInferenceError(
            "a local model path is required",
            details={"code": "INFERENCE_MODEL_NOT_FOUND"},
        )
    path = Path(os.path.expanduser(raw))
    if not path.is_file():
        raise ResidentInferenceError(
            "the prepared model artifact does not exist",
            details={"code": "INFERENCE_MODEL_NOT_FOUND", "model_path": str(path)},
        )
    return path.resolve()


class ResidentInferenceAdapter:
    """Lease-gated adapter around the existing ProviderPlugin contract.

    ``prepare`` is deliberately side-effect free.  ``start`` is the only
    operation that can reserve residency and launch a provider process, and
    it cannot do so until the broker admits the requested resources.
    """

    SNAPSHOT_VERSION = 1
    RUNTIME_BUNDLE_PREFIX = "resident-steward"

    def __init__(
        self,
        *,
        node_id: str,
        resources,
        runtimes,
        plugin_resolver: Callable[[str], object],
        on_change: Callable[[], None] | None = None,
        on_event: Callable[[str, str, dict[str, Any]], None] | None = None,
        on_resource_change: Callable[[str], None] | None = None,
        model_manager: ResidentModelManager | None = None,
    ) -> None:
        self._lock = RLock()
        self.node_id = str(node_id or "node-local")
        self.resources = resources
        self.runtimes = runtimes
        self._plugin_resolver = plugin_resolver
        self._on_change = on_change
        self._on_event = on_event
        self._on_resource_change = on_resource_change
        self.model_manager = model_manager or ResidentModelManager()
        self._config: dict[str, Any] | None = None
        self._state = "NOT_CONFIGURED"
        self._runtime_id: str | None = None
        self._runtime: RuntimeHandle | None = None
        self._lease_id: str | None = None
        self._effective_profile: str | None = None
        self._last_error: str | None = None
        self._fallback_reason: str | None = None

    @property
    def configured(self) -> bool:
        with self._lock:
            return self._config is not None

    def prepare(
        self,
        *,
        model_path: str,
        provider_type: str = "llama.cpp",
        plugin_id: str | None = None,
        profile: str = "CPU_RESIDENT",
        cpu: float = 0.25,
        ram_mb: int = 1024,
        vram_mb: int = 0,
        request_cpu: float = 0.05,
        request_ram_mb: int = 64,
        request_vram_mb: int = 0,
        lease_seconds: int | None = None,
        fallback_enabled: bool = True,
        runtime_parameter_policy: dict[str, Any] | None = None,
        source_url: str | None = None,
        expected_sha256: str | None = None,
        download: bool = False,
        max_download_bytes: int | None = None,
        readiness_timeout_seconds: float = 60.0,
        persist: bool = True,
    ) -> dict[str, Any]:
        normalized_profile = str(profile or "CPU_RESIDENT").strip().upper()
        if normalized_profile not in _PROFILES:
            raise ResidentInferenceError(
                "unsupported resident execution profile",
                details={"code": "INFERENCE_PROFILE_INVALID", "profile": normalized_profile},
            )
        if normalized_profile in _GPU_PROFILES and int(vram_mb) <= 0:
            raise ResidentInferenceError(
                "GPU resident profiles require a positive VRAM commitment",
                details={"code": "INFERENCE_RESOURCE_PROFILE_INVALID"},
            )
        try:
            if download or source_url:
                if not source_url:
                    raise ResidentModelError(
                        "source_url is required when download is enabled",
                        details={"code": "INFERENCE_MODEL_SOURCE_REQUIRED"},
                    )
                artifact = self.model_manager.download(
                    source_url,
                    model_path,
                    expected_sha256=expected_sha256,
                    max_bytes=max_download_bytes,
                )
                path = Path(str(artifact["model_path"]))
            else:
                path = _bounded_path(model_path)
                artifact = self.model_manager.verify(
                    str(path), expected_sha256=expected_sha256
                ) if expected_sha256 else {
                    "model_path": str(path),
                    "size_bytes": path.stat().st_size,
                    "sha256": None,
                    "verified": False,
                }
        except ResidentModelError:
            raise
        except OSError as error:
            raise ResidentInferenceError(
                "unable to inspect resident model artifact",
                details={"code": "INFERENCE_MODEL_NOT_FOUND", "message": str(error)},
            ) from error
        provider = str(provider_type or "").strip()
        if not provider or len(provider) > 128:
            raise ResidentInferenceError("provider_type is required")
        resolved_plugin_id = str(plugin_id or provider).strip()
        try:
            plugin = self._plugin_resolver(resolved_plugin_id)
        except (KeyError, ValueError) as error:
            raise ResidentInferenceError(
                "resident inference provider plugin is not installed",
                details={
                    "code": "INFERENCE_PROVIDER_NOT_FOUND",
                    "plugin_id": resolved_plugin_id,
                },
            ) from error
        policy = _apply_profile_residency_policy(
            provider,
            normalized_profile,
            normalize_runtime_parameter_policy(provider, runtime_parameter_policy),
        )
        resource_request = InferenceResourceRequest(
            cpu=float(cpu),
            ram_mb=int(ram_mb),
            vram_mb=int(vram_mb) if normalized_profile in _GPU_PROFILES else 0,
            request_cpu=float(request_cpu),
            request_ram_mb=int(request_ram_mb),
            request_vram_mb=(int(request_vram_mb) if normalized_profile in _GPU_PROFILES else 0),
            lease_seconds=lease_seconds,
        )
        bundle = self._bundle_for(
            model_path=path,
            provider_type=provider,
            plugin_id=resolved_plugin_id,
            profile=normalized_profile,
            resources=resource_request,
            runtime_parameter_policy=policy,
        )
        try:
            plugin.validate_bundle(bundle)
            # Building the launch spec during preparation catches invalid
            # provider configuration without spawning a process.
            plugin.build_launch_spec(bundle)
        except Exception as error:
            raise ResidentInferenceError(
                "resident provider rejected the prepared runtime",
                details={"code": "INFERENCE_CONFIGURATION_INVALID", "message": str(error)},
            ) from error
        config = {
            "model_path": str(path),
            "provider_type": provider,
            "plugin_id": resolved_plugin_id,
            "profile": normalized_profile,
            "fallback_enabled": bool(fallback_enabled),
            "resources": resource_request.as_payload(),
            "runtime_parameter_policy": policy_json(policy),
            "artifact": artifact,
            "source_url": str(source_url).strip() if source_url else None,
            "expected_sha256": expected_sha256,
            "readiness_timeout_seconds": max(0.0, min(600.0, float(readiness_timeout_seconds))),
        }
        with self._lock:
            if self._runtime is not None:
                raise ResidentInferenceError(
                    "stop the active resident runtime before preparing a new model",
                    details={"code": "INFERENCE_RUNTIME_ACTIVE"},
                )
            self._config = config
            self._state = "READY_TO_START"
            self._effective_profile = None
            self._last_error = None
            self._fallback_reason = None
            payload = self._status_unlocked()
        self._changed(persist=persist)
        self._emit("aidn.steward.inference_prepared", "resident inference prepared", payload)
        return payload

    def start(self, *, persist: bool = True) -> dict[str, Any]:
        with self._lock:
            if self._config is None:
                raise ResidentInferenceError(
                    "resident inference has not been prepared",
                    details={"code": "INFERENCE_NOT_CONFIGURED"},
                )
            if self._runtime is not None and self._state in {"STARTING", "RUNNING"}:
                return self._status_unlocked()
            config = dict(self._config)
        if self.resources is None or not hasattr(self.resources, "acquire_lease"):
            raise ResidentInferenceError(
                "Resource Broker is not configured",
                details={"code": "INFERENCE_NOT_CONFIGURED"},
            )
        request = dict(config["resources"])
        profile = str(config["profile"])
        lease_id = f"steward:{self.node_id}:inference"
        gpu_lease_seconds = request.get("lease_seconds")
        if profile == "GPU_BURST" and gpu_lease_seconds is None:
            # A burst is deliberately bounded.  CPU fallback remains
            # resident after the temporary GPU lease expires.
            gpu_lease_seconds = 300
        metadata = {
            "kind": "resident_inference",
            "profile": profile,
            "fallback_enabled": str(bool(config.get("fallback_enabled", True))).lower(),
        }
        effective_profile = profile
        fallback_reason = None
        runtime = None
        try:
            lease = self.resources.acquire_lease(
                lease_id,
                cpu=float(request["cpu"]),
                ram_mb=int(request["ram_mb"]),
                vram_mb=int(request["vram_mb"]),
                owner_id="NODE_STEWARD",
                lease_seconds=gpu_lease_seconds,
                metadata=metadata,
            )
            self._resource_changed("inference_lease_granted")
        except (ResourceAdmissionError, ResourceReconciliationRequiredError) as error:
            if profile != "GPU_BURST" or not bool(config.get("fallback_enabled", True)):
                self._mark_resource_wait(error, persist=persist)
                raise ResidentInferenceResourceWait(
                    "resident runtime is waiting for broker capacity",
                    details={
                        "code": "INFERENCE_RESOURCE_WAIT",
                        "profile": profile,
                        "broker": getattr(error, "details", {}),
                    },
                ) from error
            effective_profile = "CPU_RESIDENT"
            fallback_reason = self._resource_error_message(error)
            try:
                lease = self.resources.acquire_lease(
                    lease_id,
                    cpu=float(request["cpu"]),
                    ram_mb=int(request["ram_mb"]),
                    vram_mb=0,
                    owner_id="NODE_STEWARD",
                    lease_seconds=None,
                    metadata={**metadata, "profile": effective_profile, "fallback_from": profile},
                )
                self._resource_changed("inference_cpu_fallback_lease_granted")
            except (ResourceAdmissionError, ResourceReconciliationRequiredError) as fallback_error:
                self._mark_resource_wait(fallback_error, persist=persist, fallback_reason=fallback_reason)
                raise ResidentInferenceResourceWait(
                    "resident runtime and CPU fallback are waiting for broker capacity",
                    details={
                        "code": "INFERENCE_RESOURCE_WAIT",
                        "profile": profile,
                        "fallback_profile": effective_profile,
                        "broker": getattr(fallback_error, "details", {}),
                    },
                ) from fallback_error
        try:
            plugin = self._plugin_resolver(str(config["plugin_id"]))
            policy = _apply_profile_residency_policy(
                str(config["provider_type"]),
                effective_profile,
                dict(config.get("runtime_parameter_policy") or {}),
            )
            bundle = self._bundle_for(
                model_path=Path(str(config["model_path"])),
                provider_type=str(config["provider_type"]),
                plugin_id=str(config["plugin_id"]),
                profile=effective_profile,
                resources=InferenceResourceRequest(**{
                    **request,
                    "vram_mb": int(request["vram_mb"]) if effective_profile in _GPU_PROFILES else 0,
                    "request_vram_mb": int(request["request_vram_mb"]) if effective_profile in _GPU_PROFILES else 0,
                }),
                runtime_parameter_policy=normalize_runtime_parameter_policy(
                    str(config["provider_type"]), policy
                ),
            )
            launch_spec = dict(plugin.build_launch_spec(bundle))
            launch_spec["bundle_id"] = bundle.bundle_id
            launch_spec["launch_mode"] = "managed_process"
            launch_metadata = dict(launch_spec.get("metadata") or {})
            launch_metadata.update(
                {
                    "resident_adapter": "true",
                    "resident_profile": effective_profile,
                    "resource_lease_id": lease.lease_id,
                    "model_path": str(config["model_path"]),
                }
            )
            launch_spec["metadata"] = launch_metadata
            runtime = self.runtimes.start_runtime(launch_spec)
            self._await_readiness(
                plugin,
                runtime,
                timeout_seconds=float(config.get("readiness_timeout_seconds", 60.0)),
            )
        except Exception as error:
            if runtime is not None:
                try:
                    self.runtimes.stop_runtime(runtime.runtime_id)
                except Exception:
                    pass
            self.resources.release_lease(lease_id)
            self._resource_changed("inference_start_failed_lease_released")
            with self._lock:
                self._last_error = str(error)[:512]
                self._state = "FAILED"
                self._effective_profile = effective_profile
                self._fallback_reason = fallback_reason
            self._changed(persist=persist)
            self._emit(
                "aidn.steward.inference_failed",
                "resident inference runtime failed to start",
                {"error": str(error)[:512], "profile": effective_profile},
            )
            error_details = getattr(error, "details", {})
            error_code = error_details.get("code") if isinstance(error_details, dict) else None
            raise ResidentInferenceError(
                "resident inference runtime failed to start",
                details={"code": str(error_code or "INFERENCE_RUNTIME_FAILED"), "message": str(error), **(error_details if isinstance(error_details, dict) else {})},
            ) from error
        with self._lock:
            self._lease_id = lease.lease_id
            self._runtime = runtime
            self._runtime_id = runtime.runtime_id
            self._effective_profile = effective_profile
            self._fallback_reason = fallback_reason
            self._last_error = None
            self._state = "STARTING"
            payload = self._status_unlocked()
        self._changed(persist=persist)
        self._emit(
            "aidn.steward.inference_started",
            "resident inference runtime started",
            {"runtime_id": runtime.runtime_id, "profile": effective_profile},
        )
        return payload

    def stop(self, *, persist: bool = True) -> dict[str, Any]:
        with self._lock:
            runtime = self._runtime
            runtime_id = self._runtime_id
            lease_id = self._lease_id
            plugin_id = str(self._config.get("plugin_id")) if self._config else None
        error_message = None
        if runtime is not None and plugin_id:
            try:
                self._plugin_resolver(plugin_id).stop(runtime)
            except Exception as error:  # pragma: no cover - provider boundary
                error_message = str(error)[:512]
        if runtime_id is not None:
            try:
                self.runtimes.stop_runtime(runtime_id)
            except KeyError:
                pass
        if lease_id and self.resources is not None:
            self.resources.release_lease(lease_id)
            self._resource_changed("inference_lease_released")
        with self._lock:
            self._runtime = None
            self._runtime_id = None
            self._lease_id = None
            self._effective_profile = None
            self._state = "FAILED" if error_message else ("READY_TO_START" if self._config else "NOT_CONFIGURED")
            self._last_error = error_message
            payload = self._status_unlocked()
        self._changed(persist=persist)
        self._emit("aidn.steward.inference_stopped", "resident inference runtime stopped", payload)
        return payload

    def refresh(self, *, persist: bool = True) -> dict[str, Any]:
        sync = getattr(self.runtimes, "sync_process_state", None)
        if callable(sync):
            try:
                sync()
            except Exception:
                pass
        expire_leases = getattr(self.resources, "expire_leases", None)
        if callable(expire_leases):
            try:
                expire_leases()
            except Exception:
                pass
        with self._lock:
            runtime_id = self._runtime_id
            runtime = self._runtime
            lease_id = self._lease_id
        if runtime_id is not None:
            current = next(
                (item for item in getattr(self.runtimes, "list_runtimes", lambda: [])() if item.runtime_id == runtime_id),
                None,
            )
            runtime = current or runtime
        if runtime is not None and runtime.status == "stopped":
            if lease_id and self.resources is not None:
                self.resources.release_lease(lease_id)
                self._resource_changed("inference_runtime_exit_lease_released")
            with self._lock:
                self._runtime = None
                self._runtime_id = None
                self._lease_id = None
                self._state = "FAILED"
                self._last_error = runtime.last_error or "resident runtime exited"
            self._changed(persist=persist)
        elif runtime is not None:
            missing_lease = bool(lease_id and self.resources is not None and not self.resources.has_active_lease(lease_id))
            if missing_lease:
                # Never leave a live process consuming resources after the
                # broker revoked/expired its lease.
                with self._lock:
                    config = dict(self._config or {})
                requested_profile = str(config.get("profile") or "")
                can_fallback = requested_profile == "GPU_BURST" and bool(
                    config.get("fallback_enabled", True)
                )
                self.stop(persist=False)
                if can_fallback:
                    try:
                        # Re-enter normal admission.  If VRAM is still
                        # unavailable, ``start`` acquires the CPU lease and
                        # keeps the Steward alive without GPU state.
                        self.start(persist=persist)
                        with self._lock:
                            self._fallback_reason = (
                                "GPU lease was reclaimed; resident runtime was re-admitted"
                            )
                        self._changed(persist=persist)
                        self._emit(
                            "aidn.steward.inference_fallback",
                            "resident inference fell back after GPU lease reclamation",
                            {"profile": requested_profile},
                        )
                    except ResidentInferenceResourceWait as error:
                        with self._lock:
                            self._state = "RESOURCE_WAIT"
                            self._last_error = str(error)
                        self._changed(persist=persist)
                else:
                    with self._lock:
                        self._state = "RESOURCE_REVOKED"
                        self._last_error = "resident runtime lease is no longer active"
                    self._changed(persist=persist)
            else:
                with self._lock:
                    self._runtime = runtime
                    if runtime.status == "running":
                        self._state = "RUNNING"
        return self.status()

    def infer(
        self,
        prompt: str,
        *,
        persist: bool = True,
        timeout_seconds: float | None = None,
        stream: bool = False,
        **parameters: Any,
    ) -> dict[str, Any]:
        bounded_prompt = str(prompt or "")
        if not bounded_prompt or len(bounded_prompt) > 131072:
            raise ResidentInferenceError("prompt must contain 1..131072 characters")
        self.refresh(persist=persist)
        with self._lock:
            runtime = self._runtime
            config = dict(self._config or {})
            profile = self._effective_profile or config.get("profile")
        if runtime is None or not config:
            raise ResidentInferenceError(
                "resident inference runtime is not running",
                details={"code": "INFERENCE_RUNTIME_NOT_RUNNING"},
            )
        if self.resources is None:
            raise ResidentInferenceError("Resource Broker is not configured")
        request_id = f"steward:{self.node_id}:inference-request:{uuid4().hex}"
        request_values = config.get("resources") or {}
        try:
            self.resources.acquire_lease(
                request_id,
                cpu=float(request_values.get("request_cpu", 0.0)),
                ram_mb=int(request_values.get("request_ram_mb", 0)),
                vram_mb=(
                    int(request_values.get("request_vram_mb", 0))
                    if profile in _GPU_PROFILES
                    else 0
                ),
                owner_id="NODE_STEWARD",
                lease_seconds=300,
                metadata={"kind": "resident_inference_request", "runtime_id": runtime.runtime_id},
            )
            self._resource_changed("inference_request_lease_granted")
        except (ResourceAdmissionError, ResourceReconciliationRequiredError) as error:
            raise ResidentInferenceResourceWait(
                "resident inference request is waiting for broker capacity",
                details={"code": "INFERENCE_RESOURCE_WAIT", "broker": getattr(error, "details", {})},
            ) from error
        try:
            plugin = self._plugin_resolver(str(config["plugin_id"]))
            payload = {"prompt": bounded_prompt, "stream": bool(stream)}
            payload.update({str(key): value for key, value in parameters.items() if str(key)[:64] == str(key)})
            result = self._invoke_with_timeout(
                plugin,
                TaskRequest(task_type="llm_text.generate", payload=payload),
                runtime,
                timeout_seconds=timeout_seconds,
            )
            with self._lock:
                self._state = "RUNNING"
            return result
        finally:
            self.resources.release_lease(request_id)
            self._resource_changed("inference_request_lease_released")
            self._changed(persist=persist)

    def prepare_model(
        self,
        *,
        source_url: str,
        target_path: str,
        expected_sha256: str | None = None,
        max_download_bytes: int | None = None,
    ) -> dict[str, Any]:
        """Download and verify an artifact without preparing or starting it."""

        try:
            return self.model_manager.download(
                source_url,
                target_path,
                expected_sha256=expected_sha256,
                max_bytes=max_download_bytes,
            )
        except ResidentModelError as error:
            raise ResidentInferenceError(str(error), details=error.details) from error

    def verify_model(self, model_path: str, *, expected_sha256: str | None = None) -> dict[str, Any]:
        try:
            return self.model_manager.verify(model_path, expected_sha256=expected_sha256)
        except ResidentModelError as error:
            raise ResidentInferenceError(str(error), details=error.details) from error

    def snapshot_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": self.SNAPSHOT_VERSION,
                "config": dict(self._config) if self._config else None,
                "state": self._state,
                "effective_profile": self._effective_profile,
                "last_error": self._last_error,
                "fallback_reason": self._fallback_reason,
            }

    def restore_state(self, snapshot: dict[str, Any] | None) -> None:
        if not isinstance(snapshot, dict):
            return
        with self._lock:
            config = snapshot.get("config")
            self._config = dict(config) if isinstance(config, dict) else None
            self._runtime = None
            self._runtime_id = None
            self._lease_id = None
            self._effective_profile = None
            self._last_error = snapshot.get("last_error")
            self._fallback_reason = snapshot.get("fallback_reason")
            self._state = "READY_TO_START" if self._config else "NOT_CONFIGURED"

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_unlocked()

    def _status_unlocked(self) -> dict[str, Any]:
        config = dict(self._config or {})
        runtime = self._runtime
        execution = {
            "profile": config.get("profile"),
            "effective_profile": self._effective_profile,
            "state": self._state,
            "inference_adapter": self._state.lower(),
            "fallback_profile": "CPU_RESIDENT",
            "fallback_reason": self._fallback_reason,
            "vram_mb": (config.get("resources") or {}).get("vram_mb", 0)
            if self._effective_profile != "CPU_RESIDENT"
            else 0,
            "ram_budget_mb": (config.get("resources") or {}).get("ram_mb", 0),
            "resource_lease": self._lease_id or "not_requested",
            "resource_lease_status": (
                self._lease_status(self._lease_id) if self._lease_id else "not_requested"
            ),
            "requested_resources": dict(config.get("resources") or {}),
        }
        return {
            "adapter_id": f"resident-inference:{self.node_id}",
            "configured": bool(config),
            "state": self._state,
            "provider_type": config.get("provider_type"),
            "plugin_id": config.get("plugin_id"),
            "model_path": config.get("model_path"),
            "execution": execution,
            "runtime": {
                "runtime_id": runtime.runtime_id if runtime else None,
                "status": runtime.status if runtime else "stopped",
                "health_status": runtime.health_status if runtime else "unknown",
                "readiness_status": runtime.readiness_status if runtime else "UNKNOWN",
                "endpoint": (runtime.metadata.get("endpoint") if runtime else None),
                "last_error": runtime.last_error if runtime else self._last_error,
            },
            "last_error": self._last_error,
            "artifact": dict(config.get("artifact") or {}),
            "readiness_timeout_seconds": config.get("readiness_timeout_seconds", 60.0),
            "streaming": {"supported": bool(config.get("plugin_id")), "mode": "provider_plugin"},
        }

    def _await_readiness(self, plugin: object, runtime: RuntimeHandle, *, timeout_seconds: float) -> None:
        """Promote the runtime only after a bounded provider health probe."""

        timeout = max(0.0, min(600.0, float(timeout_seconds)))
        probe = getattr(plugin, "health_check_diagnostic", None)
        if not callable(probe):
            probe = getattr(plugin, "health_check", None)
        if not callable(probe):
            runtime.readiness_status = "READY"
            runtime.readiness_code = "provider_probe_unavailable"
            runtime.readiness_message = "provider does not expose a health probe"
            return
        deadline = monotonic() + timeout
        diagnostic: dict[str, Any] = {}
        while True:
            try:
                raw = probe(runtime)
                diagnostic = raw if isinstance(raw, dict) else {"healthy": bool(raw)}
            except Exception as error:
                diagnostic = {"healthy": False, "code": "provider_probe_failed", "message": str(error)[:256]}
            if bool(diagnostic.get("healthy")):
                runtime.health_status = "healthy"
                runtime.readiness_status = "READY"
                runtime.readiness_code = str(diagnostic.get("code") or "provider_ready")
                runtime.readiness_message = str(diagnostic.get("message") or "provider is ready")
                runtime.readiness_diagnostic = dict(diagnostic)
                return
            if monotonic() >= deadline:
                runtime.health_status = "unhealthy"
                runtime.readiness_status = "FAILED"
                runtime.readiness_code = str(diagnostic.get("code") or "provider_not_ready")
                runtime.readiness_message = str(diagnostic.get("message") or "provider did not become ready before timeout")
                runtime.readiness_diagnostic = dict(diagnostic)
                raise ResidentInferenceError(
                    "resident provider did not become ready",
                    details={"code": "INFERENCE_RUNTIME_NOT_READY", "readiness": diagnostic},
                )
            sleep(min(0.25, max(0.01, deadline - monotonic())))

    @staticmethod
    def _invoke_with_timeout(plugin: object, task: TaskRequest, runtime: RuntimeHandle, *, timeout_seconds: float | None) -> dict[str, Any]:
        invoke = getattr(plugin, "invoke", None)
        if not callable(invoke):
            raise ResidentInferenceError("resident provider cannot invoke inference", details={"code": "INFERENCE_PROVIDER_INVOKE_UNSUPPORTED"})
        timeout = None if timeout_seconds is None else max(0.1, min(3600.0, float(timeout_seconds)))
        if timeout is None:
            return invoke(task, runtime)
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aidn-steward-infer")
        future = executor.submit(invoke, task, runtime)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as error:
            future.cancel()
            raise ResidentInferenceError(
                "resident inference request timed out",
                details={"code": "INFERENCE_REQUEST_TIMEOUT", "timeout_seconds": timeout},
            ) from error
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _lease_status(self, lease_id: str | None) -> str:
        if not lease_id or self.resources is None:
            return "not_requested"
        records = getattr(self.resources, "lease_details", lambda **_: [])(include_inactive=True)
        for item in records:
            if str(item.get("lease_id")) == lease_id:
                return str(item.get("status") or "UNKNOWN")
        return "MISSING"

    def _bundle_for(
        self,
        *,
        model_path: Path,
        provider_type: str,
        plugin_id: str,
        profile: str,
        resources: InferenceResourceRequest,
        runtime_parameter_policy: dict[str, Any],
    ) -> BundleConfig:
        device = "cuda" if profile in _GPU_PROFILES else "cpu"
        policy_payload: dict[str, Any] | None = runtime_parameter_policy
        if runtime_parameter_policy and all(
            hasattr(value, "model_dump")
            for value in runtime_parameter_policy.values()
        ):
            policy_payload = policy_json(runtime_parameter_policy)
        return BundleConfig(
            bundle_id=f"{self.RUNTIME_BUNDLE_PREFIX}:{self.node_id}",
            plugin_id=plugin_id,
            provider_type=provider_type,
            workload_type="llm_text",
            model_id=str(model_path),
            launch_mode="managed_process",
            endpoint="http://127.0.0.1:8080",
            provider_api_format="openai-compatible",
            device_affinity=device,
            resource_profile=ResourceProfile(
                steady_cpu=resources.cpu,
                steady_ram_mb=resources.ram_mb,
                steady_vram_mb=resources.vram_mb,
                per_request_cpu=resources.request_cpu,
                per_request_ram_mb=resources.request_ram_mb,
                per_request_vram_mb=resources.request_vram_mb,
            ),
            warm_policy="always",
            priority_class=0,
            max_parallel_requests=1,
            runtime_parameter_policy=normalize_runtime_parameter_policy(
                provider_type, policy_payload
            ),
        )

    def _mark_resource_wait(
        self,
        error: Exception,
        *,
        persist: bool,
        fallback_reason: str | None = None,
    ) -> None:
        with self._lock:
            self._state = "RESOURCE_WAIT"
            self._last_error = self._resource_error_message(error)
            self._fallback_reason = fallback_reason
            payload = self._status_unlocked()
        self._changed(persist=persist)
        self._emit("aidn.steward.inference_resource_wait", "resident inference is waiting for resources", payload)

    @staticmethod
    def _resource_error_message(error: Exception) -> str:
        details = getattr(error, "details", {})
        if isinstance(details, dict):
            reason = details.get("reason")
            if reason:
                return str(reason)[:512]
        return str(error)[:512]

    def _changed(self, *, persist: bool) -> None:
        if persist and self._on_change is not None:
            self._on_change()

    def _emit(self, event_type: str, message: str, payload: dict[str, Any]) -> None:
        if self._on_event is not None:
            try:
                self._on_event(event_type, message, payload)
            except Exception:
                # Observability must never turn a successful provider launch
                # into an inference failure.
                return

    def _resource_changed(self, trigger: str) -> None:
        if self._on_resource_change is None:
            return
        try:
            self._on_resource_change(trigger)
        except Exception:
            # Admission and cleanup remain authoritative even when the
            # optional scheduler notification cannot be delivered.
            pass
