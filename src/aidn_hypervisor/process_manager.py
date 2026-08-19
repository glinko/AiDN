import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Thread


@dataclass
class RuntimeHandle:
    runtime_id: str
    command: list[str]
    status: str
    bundle_id: str | None = None
    health_status: str = "unknown"
    last_error: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


class ProviderProcessManager:
    def __init__(
        self,
        *,
        enable_subprocesses: bool = False,
        on_runtime_state_change: Callable[[RuntimeHandle], None] | None = None,
    ) -> None:
        self.enable_subprocesses = enable_subprocesses
        self._on_runtime_state_change = on_runtime_state_change
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
        metadata = dict(launch_spec.get("metadata", {}))
        handle = RuntimeHandle(
            runtime_id=runtime_id,
            command=launch_spec["command"],
            status="starting",
            bundle_id=launch_spec.get("bundle_id"),
            health_status="unknown",
            metadata=metadata,
        )
        cleanup_paths = tuple(Path(path) for path in launch_spec.get("cleanup_paths", ()))
        process: subprocess.Popen | None = None
        if self._should_spawn_subprocess(launch_spec):
            try:
                process = subprocess.Popen(
                    launch_spec["command"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env={**os.environ, **launch_spec.get("environment", {})},
                    cwd=launch_spec.get("working_directory"),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                self._cleanup_runtime_paths(cleanup_paths)
                raise
            self._processes[runtime_id] = process
            self._cleanup_paths[runtime_id] = cleanup_paths
            handle.metadata["pid"] = str(process.pid)
        elif cleanup_paths:
            self._cleanup_runtime_paths(cleanup_paths)
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
        self._sync_next_runtime_index(runtime_handle.runtime_id)
        return runtime_handle

    def replace_runtimes(self, runtimes: list[RuntimeHandle]) -> None:
        self._runtimes = {runtime.runtime_id: runtime for runtime in runtimes}
        self._processes = {}
        self._pending_state_notifications.clear()
        self._next_runtime_index = 1
        for runtime in runtimes:
            self._sync_next_runtime_index(runtime.runtime_id)

    def stop_runtime(self, runtime_id: str) -> RuntimeHandle:
        handle = self._runtimes.pop(runtime_id)
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
            self._cleanup_runtime_paths(self._cleanup_paths.pop(runtime_id, ()))
        handle.status = "stopped"
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
                handle.status = "stopped"
                handle.health_status = "unhealthy"
                handle.last_error = f"managed runtime exited with code {returncode}"
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

    def _sync_next_runtime_index(self, runtime_id: str) -> None:
        prefix = "rt-"
        if not runtime_id.startswith(prefix):
            return
        suffix = runtime_id[len(prefix) :]
        if not suffix.isdigit():
            return
        self._next_runtime_index = max(self._next_runtime_index, int(suffix) + 1)
