import sys

from aidn_hypervisor.process_manager import ProviderProcessManager


def test_start_runtime_returns_handle() -> None:
    manager = ProviderProcessManager()

    handle = manager.start_runtime({"command": ["python", "-c", "print('ready')"]})

    assert handle.command == ["python", "-c", "print('ready')"]
    assert handle.runtime_id == "rt-1"
    assert handle.status == "starting"
    assert handle.health_status == "unknown"
    assert manager._runtimes["rt-1"] is handle


def test_start_runtime_generates_sequential_runtime_ids() -> None:
    manager = ProviderProcessManager()

    first = manager.start_runtime({"command": ["python", "-c", "print('ready')"]})
    second = manager.start_runtime({"command": ["python", "-c", "print('ready again')"]})

    assert first.runtime_id == "rt-1"
    assert second.runtime_id == "rt-2"


def test_start_runtime_keeps_runtime_ids_monotonic_after_stop() -> None:
    manager = ProviderProcessManager()

    first = manager.start_runtime({"command": ["python", "-c", "print('ready')"]})
    second = manager.start_runtime({"command": ["python", "-c", "print('ready again')"]})
    manager.stop_runtime(first.runtime_id)
    third = manager.start_runtime({"command": ["python", "-c", "print('ready third')"]})

    assert second.runtime_id == "rt-2"
    assert third.runtime_id == "rt-3"


def test_start_runtime_preserves_launch_metadata() -> None:
    manager = ProviderProcessManager()

    handle = manager.start_runtime(
        {
            "command": ["ollama", "serve"],
            "metadata": {
                "endpoint": "http://127.0.0.1:11434",
                "model_id": "phi4",
            },
        }
    )

    assert handle.metadata == {
        "endpoint": "http://127.0.0.1:11434",
        "model_id": "phi4",
    }


def test_start_runtime_with_subprocesses_enabled_records_pid_and_stops_process() -> None:
    manager = ProviderProcessManager(enable_subprocesses=True)

    handle = manager.start_runtime(
        {
            "command": [
                sys.executable,
                "-c",
                "import time; time.sleep(60)",
            ],
            "launch_mode": "managed_process",
        }
    )
    process = manager._processes[handle.runtime_id]

    assert handle.metadata["pid"] == str(process.pid)
    assert process.poll() is None

    stopped = manager.stop_runtime(handle.runtime_id)

    assert stopped is handle
    assert process.poll() is not None


def test_start_runtime_with_subprocesses_enabled_does_not_spawn_attached_service() -> None:
    manager = ProviderProcessManager(enable_subprocesses=True)

    handle = manager.start_runtime(
        {
            "command": ["ollama", "serve"],
            "launch_mode": "attached_service",
            "metadata": {"endpoint": "http://127.0.0.1:11434"},
        }
    )

    assert "pid" not in handle.metadata
    assert handle.runtime_id not in manager._processes
