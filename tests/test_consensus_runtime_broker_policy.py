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
