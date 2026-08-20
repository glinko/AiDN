from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


def _broker_module():
    path = Path(__file__).parents[1] / "tools" / "aidn-provider-runtime-broker.py"
    spec = importlib.util.spec_from_file_location("aidn_provider_runtime_broker_policy", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_root_broker_accepts_only_consensus_install_flags() -> None:
    if os.name == "nt":
        pytest.skip("the production broker uses POSIX pwd/socket APIs")
    broker = _broker_module()
    dispatcher = (Path(__file__).parents[1] / "tools" / "aidn-provider-runtime-ubuntu.sh").resolve()
    argv = [
        str(dispatcher),
        "consensus",
        "install",
        "--version", "v0.38.19",
        "--home", "/home/user/.local/share/aidn/consensus/cometbft",
        "--binary-path", "/home/user/.local/share/aidn/consensus/bin/cometbft",
        "--service-name", "aidn-cometbft-node.service",
        "--chain-id", "aidn-localnet-1",
        "--moniker", "node",
        "--rpc-host", "127.0.0.1",
        "--rpc-port", "26657",
        "--p2p-host", "127.0.0.1",
        "--p2p-port", "26656",
        "--abci-host", "127.0.0.1",
        "--abci-port", "26658",
        "--no-abci",
    ]

    assert broker._validate_argv(argv, dispatcher=dispatcher) == argv
    with pytest.raises(ValueError, match="not allowlisted"):
        broker._validate_argv(argv + ["--command", "rm"], dispatcher=dispatcher)


def test_root_broker_job_store_deduplicates_and_replays_offsets(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("the production broker uses POSIX pwd/socket APIs")
    broker = _broker_module()
    store = broker._BrokerJobStore(tmp_path / "jobs.json")

    first, created = store.create_or_get(
        client_job_id="aidn:pij-1",
        request_hash="sha256:request",
        timeout_seconds=30,
    )
    duplicate, duplicate_created = store.create_or_get(
        client_job_id="aidn:pij-1",
        request_hash="sha256:request",
        timeout_seconds=30,
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate["broker_job_id"] == first["broker_job_id"]
    with pytest.raises(ValueError, match="reused"):
        store.create_or_get(
            client_job_id="aidn:pij-1",
            request_hash="sha256:different",
            timeout_seconds=30,
        )

    store.update(
        first["broker_job_id"],
        status="RUNNING",
        progress_percent=10,
        message="started",
    )
    replay = store.get(first["broker_job_id"], after_offset=1)
    assert [event["offset"] for event in replay["events"]] == [2]
    assert replay["event_offset"] + 1 == 3


def test_root_broker_job_store_marks_inflight_jobs_failed_after_restart(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("the production broker uses POSIX pwd/socket APIs")
    broker = _broker_module()
    state_path = tmp_path / "jobs.json"
    store = broker._BrokerJobStore(state_path)
    job, _created = store.create_or_get(
        client_job_id="aidn:pij-2",
        request_hash="sha256:request",
        timeout_seconds=30,
    )
    store.update(
        job["broker_job_id"],
        status="RUNNING",
        progress_percent=10,
        message="started",
    )

    restarted = broker._BrokerJobStore(state_path)
    recovered = restarted.get(job["broker_job_id"])

    assert recovered["status"] == "FAILED"
    assert recovered["result"]["details"]["code"] == "broker_restarted"
    assert recovered["events"][-1]["status"] == "FAILED"
