import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread

from aidn_hypervisor.runtime_port_allocator import RuntimePortAllocator


@dataclass
class RuntimeHandle:
    runtime_id: str
    command: list[str]
    status: str
    bundle_id: str | None = None
    health_status: str = "unknown"
    last_error: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    # Readiness is deliberately separate from process and provider health.
    # A runtime can have a live PID while its HTTP/API surface is still
    # warming up, or can be stopped after a provider probe failed.
    readiness_status: str = "UNKNOWN"
    readiness_code: str | None = None
    readiness_message: str | None = None
    readiness_checked_at: str | None = None
    readiness_diagnostic: dict = field(default_factory=dict)
    # RFC-0073 Runtime Instance projection.  ``status`` remains the low-level
    # process state for backwards compatibility; these fields describe the
    # schedulable lifecycle state and warm-retention metadata.
    lifecycle_state: str = "STARTING"
    last_activity_at: str | None = None
    pinned_warm: bool = False


class ProviderProcessManager:
    def __init__(
        self,
        *,
        enable_subprocesses: bool = False,
        on_runtime_state_change: Callable[[RuntimeHandle], None] | None = None,
        log_dir: str | Path | None = None,
        port_allocator: RuntimePortAllocator | None = None,
    ) -> None:
        self.enable_subprocesses = enable_subprocesses
        self._on_runtime_state_change = on_runtime_state_change
        self._log_dir = Path(log_dir).expanduser() if log_dir is not None else None
        self._runtime_logs: dict[str, object] = {}
        self.port_allocator = port_allocator or RuntimePortAllocator()
        self._runtimes: dict[str, RuntimeHandle] = {}
        self._processes: dict[str, subprocess.Popen] = {}
        self._cleanup_paths: dict[str, tuple[Path, ...]] = {}
        self._pending_state_notifications: set[str] = set()
        self._next_runtime_index = 1

    def set_runtime_state_change_callback(
        self,
        callback: Callable[[RuntimeHandle], None] | None,
    ) -> None:
        """Attach the durable-state callback owned by ``HypervisorService``.

        A managed process can exit without an API request ever touching the
        runtime.  The process manager therefore needs a narrow callback so
        the owning service can persist the transition instead of leaving the
        old ``starting``/``running`` snapshot on disk indefinitely.
        """

        self._on_runtime_state_change = callback

    def start_runtime(self, launch_spec: dict) -> RuntimeHandle:
        runtime_id = f"rt-{self._next_runtime_index}"
        self._next_runtime_index += 1
        # A dry-run/test manager does not own a listener.  Keep its historical
        # metadata untouched; allocation is enforced for real managed child
        # processes where a bind collision can actually occur.
        prepared_spec = (
            self.port_allocator.prepare_launch_spec(runtime_id, dict(launch_spec))
            if self._should_spawn_subprocess(launch_spec)
            else dict(launch_spec)
        )
        command = list(prepared_spec["command"])
        metadata = dict(prepared_spec.get("metadata", {}))
        handle = RuntimeHandle(
            runtime_id=runtime_id,
            command=command,
            status="starting",
            bundle_id=prepared_spec.get("bundle_id"),
            health_status="unknown",
            metadata=metadata,
        )
        cleanup_paths = tuple(Path(path) for path in prepared_spec.get("cleanup_paths", ()))
        process: subprocess.Popen | None = None
        log_handle = None
        try:
            if self._should_spawn_subprocess(prepared_spec):
                stdout = subprocess.DEVNULL
                stderr = subprocess.DEVNULL
                if self._log_dir is not None:
                    self._log_dir.mkdir(parents=True, exist_ok=True)
                    log_path = self._log_dir / f"{runtime_id}.log"
                    log_handle = log_path.open("ab")
                    try:
                        os.chmod(log_path, 0o600)
                    except OSError:
                        pass
                    stdout = log_handle
                    stderr = subprocess.STDOUT
                    metadata["log_path"] = str(log_path)
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    env={**os.environ, **prepared_spec.get("environment", {})},
                    cwd=prepared_spec.get("working_directory"),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            elif cleanup_paths:
                self._cleanup_runtime_paths(cleanup_paths)
        except Exception:
            if log_handle is not None:
                log_handle.close()
            self.port_allocator.release(runtime_id)
            self._cleanup_runtime_paths(cleanup_paths)
            raise
        if process is not None:
            self._runtime_logs[runtime_id] = log_handle
            self._processes[runtime_id] = process
            self._cleanup_paths[runtime_id] = cleanup_paths
            handle.metadata["pid"] = str(process.pid)
        # Register the handle before starting the watcher.  A process that
        # exits immediately must still be observable by the watcher.
        self._runtimes[runtime_id] = handle
        if process is not None:
            Thread(
                target=self._wait_for_process_cleanup,
                args=(runtime_id, process),
                daemon=True,
            ).start()
        return handle

    def list_runtimes(self) -> list[RuntimeHandle]:
        return list(self._runtimes.values())

    def restore_runtime(self, runtime_handle: RuntimeHandle) -> RuntimeHandle:
        self._runtimes[runtime_handle.runtime_id] = runtime_handle
        self._restore_port_lease(runtime_handle)
        self._sync_next_runtime_index(runtime_handle.runtime_id)
        return runtime_handle

    def replace_runtimes(self, runtimes: list[RuntimeHandle]) -> None:
        self._runtimes = {runtime.runtime_id: runtime for runtime in runtimes}
        self._processes = {}
        self._pending_state_notifications.clear()
        self._next_runtime_index = 1
        for runtime in runtimes:
            self._restore_port_lease(runtime)
            self._sync_next_runtime_index(runtime.runtime_id)

    def stop_runtime(self, runtime_id: str) -> RuntimeHandle:
        handle = self._runtimes.pop(runtime_id)
        handle.lifecycle_state = "STOPPING"
        process = self._processes.pop(runtime_id, None)
        self._pending_state_notifications.discard(runtime_id)
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        finally:
            self._close_runtime_log(runtime_id)
            self.port_allocator.release(runtime_id)
            self._cleanup_runtime_paths(self._cleanup_paths.pop(runtime_id, ()))
        handle.status = "stopped"
        handle.lifecycle_state = "STOPPED"
        handle.readiness_status = "STOPPED"
        handle.readiness_code = "operator_stopped"
        handle.readiness_message = "runtime stopped by operator"
        handle.readiness_checked_at = (
            datetime.now(UTC).isoformat().replace("+00:00", "Z")
        )
        handle.readiness_diagnostic = {
            "healthy": False,
            "code": handle.readiness_code,
            "message": handle.readiness_message,
        }
        return handle

    def _wait_for_process_cleanup(self, runtime_id: str, process: subprocess.Popen) -> None:
        process.wait()
        self.sync_process_state()
        self._cleanup_runtime_paths(self._cleanup_paths.pop(runtime_id, ()))

    def sync_process_state(self) -> bool:
        """Project managed child-process exits onto runtime handles.

        ``start_runtime`` intentionally returns ``starting`` before a plugin
        health probe can complete.  Previously the watcher only removed
        temporary files, so a dead process could remain ``starting`` forever.
        This method is cheap and idempotent; read models call it before
        exposing runtime state and the watcher calls it on process exit.
        """

        changed = False
        for runtime_id, process in list(self._processes.items()):
            returncode = process.poll()
            if returncode is None:
                continue
            handle = self._runtimes.get(runtime_id)
            if handle is None:
                self._processes.pop(runtime_id, None)
                continue
            if handle.status != "stopped":
                self._close_runtime_log(runtime_id)
                log_tail = self._read_runtime_log_tail(handle)
                handle.status = "stopped"
                handle.lifecycle_state = "FAILED" if returncode else "STOPPED"
                handle.health_status = "unhealthy"
                base_error = f"managed runtime exited with code {returncode}"
                handle.last_error = f"{base_error}: {log_tail}" if log_tail else base_error
                handle.readiness_status = "FAILED"
                handle.readiness_code = (
                    "runtime_port_conflict"
                    if _is_port_conflict(log_tail)
                    else "managed_runtime_exited"
                )
                handle.readiness_message = handle.last_error
                handle.readiness_checked_at = (
                    datetime.now(UTC).isoformat().replace("+00:00", "Z")
                )
                handle.readiness_diagnostic = {
                    "healthy": False,
                    "code": handle.readiness_code,
                    "message": handle.readiness_message,
                }
                if log_tail:
                    handle.readiness_diagnostic["log_tail"] = log_tail
                if handle.metadata.get("log_path"):
                    handle.readiness_diagnostic["log_path"] = handle.metadata["log_path"]
                self.port_allocator.release(runtime_id)
                changed = True
                self._notify_runtime_state_change(handle)
            elif runtime_id in self._pending_state_notifications:
                changed = self._notify_runtime_state_change(handle) or changed
            if runtime_id not in self._pending_state_notifications:
                # The process object is no longer useful after wait(); retain
                # it only while a failed persistence callback needs retrying.
                self._processes.pop(runtime_id, None)
        return changed

    def _notify_runtime_state_change(self, handle: RuntimeHandle) -> bool:
        callback = self._on_runtime_state_change
        if callback is None:
            return True
        try:
            callback(handle)
        except Exception:
            # A persistence failure must never turn the process watcher into an
            # unhandled background exception.  The next read will reconcile
            # and retry the durable projection.
            self._pending_state_notifications.add(handle.runtime_id)
            return False
        self._pending_state_notifications.discard(handle.runtime_id)
        return True

    @staticmethod
    def _cleanup_runtime_paths(paths: tuple[Path, ...]) -> None:
        for path in paths:
            try:
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink(missing_ok=True)
            except OSError:
                # Cleanup runs from a best-effort process watcher. It must not
                # turn an already-exited Host into an unhandled background error.
                pass

    def _should_spawn_subprocess(self, launch_spec: dict) -> bool:
        return self.enable_subprocesses and launch_spec.get("launch_mode") == "managed_process"

    def _restore_port_lease(self, runtime: RuntimeHandle) -> None:
        if runtime.status == "stopped":
            return
        endpoint = runtime.metadata.get("endpoint")
        port = runtime.metadata.get("port")
        if not endpoint or not port:
            return
        try:
            from urllib.parse import urlsplit

            parsed = urlsplit(endpoint)
            if parsed.hostname is None:
                return
            self.port_allocator.restore(
                runtime.runtime_id,
                host=parsed.hostname,
                port=int(port),
            )
        except (TypeError, ValueError):
            return

    def _close_runtime_log(self, runtime_id: str) -> None:
        log_handle = self._runtime_logs.pop(runtime_id, None)
        if log_handle is None:
            return
        try:
            log_handle.close()
        except Exception:
            pass

    @staticmethod
    def _read_runtime_log_tail(handle: RuntimeHandle, *, limit: int = 4096) -> str:
        log_path = handle.metadata.get("log_path")
        if not log_path:
            return ""
        try:
            data = Path(log_path).read_bytes()[-limit:]
        except OSError:
            return ""
        return data.decode("utf-8", errors="replace").strip()

    def _sync_next_runtime_index(self, runtime_id: str) -> None:
        prefix = "rt-"
        if not runtime_id.startswith(prefix):
            return
        suffix = runtime_id[len(prefix) :]
        if not suffix.isdigit():
            return
        self._next_runtime_index = max(self._next_runtime_index, int(suffix) + 1)


def _is_port_conflict(log_tail: str) -> bool:
    if not log_tail:
        return False
    normalized = log_tail.lower()
    return bool(
        "couldn't bind http server socket" in normalized
        or "address already in use" in normalized
        or re.search(r"\bport\s+\d+.*(?:already\s+)?in use", normalized)
    )
