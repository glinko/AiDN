from pathlib import Path

import pytest

from aidn_hypervisor.providers.models import ProviderRuntimeInvocation
from aidn_hypervisor.providers.runtime_broker import (
    AllowlistedProviderRuntimeBroker,
    RuntimeCommandResult,
)


class _Runner:
    def __init__(self, result: RuntimeCommandResult) -> None:
        self.result = result
        self.calls: list[tuple[list[str], int]] = []

    def run(self, *, argv: list[str], timeout_seconds: int) -> RuntimeCommandResult:
        self.calls.append((argv, timeout_seconds))
        return self.result


def _invocation(**overrides) -> ProviderRuntimeInvocation:
    payload = {
        "approval_id": "pia-1",
        "plan_hash": "sha256:plan",
        "configuration_hash": "sha256:configuration",
        "installer_id": "aidn-provider-runtime-ubuntu.v1",
        "provider": "ollama",
        "action": "install",
        "pinned_version": "0.32.12",
        "arguments": {"version": "0.32.12"},
    }
    payload.update(overrides)
    return ProviderRuntimeInvocation.model_validate(payload)


def test_runtime_broker_builds_exact_argv_without_shell_fields() -> None:
    runner = _Runner(RuntimeCommandResult(returncode=0, stdout="ready"))
    broker = AllowlistedProviderRuntimeBroker(
        dispatcher_path=Path("tools/aidn-provider-runtime-ubuntu.sh").resolve(),
        runner=runner,
        require_linux=False,
    )

    result = broker.invoke(invocation=_invocation(), timeout_seconds=30)

    assert result.status == "SUCCEEDED"
    assert runner.calls == [
        (
            [
                str(Path("tools/aidn-provider-runtime-ubuntu.sh").resolve()),
                "ollama",
                "install",
                "--version",
                "0.32.12",
            ],
            30,
        )
    ]
    assert "shell" not in result.details
    assert "command" not in result.details


def test_runtime_broker_preserves_reviewed_argument_order_for_llamacpp() -> None:
    runner = _Runner(RuntimeCommandResult(returncode=0))
    broker = AllowlistedProviderRuntimeBroker(
        dispatcher_path=Path("tools/aidn-provider-runtime-ubuntu.sh").resolve(),
        runner=runner,
        require_linux=False,
    )
    invocation = _invocation(
        provider="llama.cpp",
        pinned_version="b10433",
        arguments={"ref": "b10433", "backend": "cuda", "model": "/models/qwen.gguf"},
    )

    broker.invoke(invocation=invocation)

    assert runner.calls[0][0][-6:] == [
        "--ref",
        "b10433",
        "--backend",
        "cuda",
        "--model",
        "/models/qwen.gguf",
    ]


def test_runtime_broker_rejects_unreviewed_dispatcher_filename() -> None:
    with pytest.raises(ValueError, match="reviewed dispatcher"):
        AllowlistedProviderRuntimeBroker(
            dispatcher_path=Path("tools/arbitrary.sh").resolve(),
            runner=_Runner(RuntimeCommandResult(returncode=0)),
            require_linux=False,
        )


def test_runtime_broker_bounds_timeout_and_output() -> None:
    runner = _Runner(RuntimeCommandResult(returncode=1, stdout="x" * 100_000, stderr="y" * 100_000))
    broker = AllowlistedProviderRuntimeBroker(
        dispatcher_path=Path("tools/aidn-provider-runtime-ubuntu.sh").resolve(),
        runner=runner,
        require_linux=False,
    )

    with pytest.raises(ValueError, match="timeout"):
        broker.invoke(invocation=_invocation(), timeout_seconds=0)

    result = broker.invoke(invocation=_invocation(), timeout_seconds=30)
    assert result.status == "FAILED"
    assert len(result.details["stdout"]) == 64 * 1024
    assert len(result.details["stderr"]) == 64 * 1024
