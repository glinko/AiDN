import os
import subprocess
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
    def __init__(self, *, enable_subprocesses: bool = False) -> None:
        self.enable_subprocesses = enable_subprocesses
        self._runtimes: dict[str, RuntimeHandle] = {}
        self._processes: dict[str, subprocess.Popen] = {}
        self._cleanup_paths: dict[str, tuple[Path, ...]] = {}
        self._next_runtime_index = 1

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
            Thread(
                target=self._wait_for_process_cleanup,
                args=(runtime_id, process),
                daemon=True,
            ).start()
        elif cleanup_paths:
            self._cleanup_runtime_paths(cleanup_paths)
        self._runtimes[runtime_id] = handle
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
        self._next_runtime_index = 1
        for runtime in runtimes:
            self._sync_next_runtime_index(runtime.runtime_id)

    def stop_runtime(self, runtime_id: str) -> RuntimeHandle:
        handle = self._runtimes.pop(runtime_id)
        process = self._processes.pop(runtime_id, None)
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
        self._cleanup_runtime_paths(self._cleanup_paths.pop(runtime_id, ()))

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
