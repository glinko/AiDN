import socket
import sys
import time

from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.runtime_port_allocator import RuntimePortAllocator


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_allocator_prefers_requested_port_and_releases_it() -> None:
    requested = _free_port()
    allocator = RuntimePortAllocator(start_port=requested, end_port=requested + 2)

    first = allocator.reserve("rt-1", host="127.0.0.1", requested_port=requested)
    second = allocator.reserve("rt-2", host="127.0.0.1", requested_port=requested)

    assert first.port == requested
    assert second.port == requested + 1
    allocator.release("rt-1")
    third = allocator.reserve("rt-3", host="127.0.0.1", requested_port=requested)
    assert third.port == requested


def test_allocator_rewrites_command_and_endpoint() -> None:
    requested = _free_port()
    allocator = RuntimePortAllocator(start_port=requested, end_port=requested + 2)
    prepared = allocator.prepare_launch_spec(
        "rt-1",
        {
            "launch_mode": "managed_process",
            "command": ["llama-server", "--host", "127.0.0.1", "--port", str(requested)],
            "metadata": {"endpoint": f"http://127.0.0.1:{requested}/v1"},
        },
    )

    assert prepared["command"][-1] == str(requested)
    assert prepared["metadata"]["endpoint"] == f"http://127.0.0.1:{requested}/v1"
    assert prepared["metadata"]["port"] == str(requested)
    assert allocator.leases()[0].runtime_id == "rt-1"


def test_process_manager_releases_port_when_runtime_stops() -> None:
    requested = _free_port()
    allocator = RuntimePortAllocator(start_port=requested, end_port=requested + 2)
    manager = ProviderProcessManager(enable_subprocesses=True, port_allocator=allocator)

    spec = {
        "command": [sys.executable, "-c", "import time; time.sleep(60)", "--port", str(requested)],
        "launch_mode": "managed_process",
        "metadata": {"endpoint": f"http://127.0.0.1:{requested}"},
    }
    first = manager.start_runtime(spec)
    second = manager.start_runtime(spec)
    assert first.metadata["port"] == str(requested)
    assert second.metadata["port"] == str(requested + 1)

    manager.stop_runtime(first.runtime_id)
    third = manager.start_runtime(spec)
    assert third.metadata["port"] == str(requested)
    manager.stop_runtime(second.runtime_id)
    manager.stop_runtime(third.runtime_id)


def test_runtime_exit_includes_bounded_log_and_port_diagnostic(tmp_path) -> None:
    manager = ProviderProcessManager(
        enable_subprocesses=True,
        log_dir=tmp_path / "runtime-logs",
    )
    handle = manager.start_runtime(
        {
            "command": [
                sys.executable,
                "-c",
                "import sys; print(\"couldn't bind HTTP server socket, port 8080\", file=sys.stderr, flush=True); sys.exit(1)",
            ],
            "launch_mode": "managed_process",
        }
    )

    deadline = time.monotonic() + 2
    while handle.status != "stopped" and time.monotonic() < deadline:
        time.sleep(0.01)

    assert handle.status == "stopped"
    assert handle.readiness_code == "runtime_port_conflict"
    assert "couldn't bind HTTP server socket" in (handle.last_error or "")
    assert handle.readiness_diagnostic["log_path"].endswith("rt-1.log")
    assert len(handle.readiness_diagnostic["log_tail"]) < 4096
