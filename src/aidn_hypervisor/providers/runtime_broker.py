"""Allowlisted adapter for reviewed Ubuntu Provider runtime scripts.

This module deliberately separates command construction from process
execution. The Hypervisor can validate and test the exact argv without ever
starting a host process; production wiring supplies the explicit Unix-socket
runner for the root-owned local broker.
"""

import json
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from aidn_hypervisor.providers.models import (
    ProviderRuntimeBrokerResult,
    ProviderRuntimeInvocation,
)


@dataclass(frozen=True)
class RuntimeCommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class ProviderRuntimeCommandRunner(Protocol):
    def run(self, *, argv: list[str], timeout_seconds: int) -> RuntimeCommandResult:
        ...


class AllowlistedProviderRuntimeBroker:
    """Build and optionally execute only the reviewed dispatcher argv."""

    _DISPATCHER_NAME = "aidn-provider-runtime-ubuntu.sh"
    _MAX_TIMEOUT_SECONDS = 3600
    _MAX_OUTPUT_BYTES = 64 * 1024

    def __init__(
        self,
        *,
        dispatcher_path: Path,
        runner: ProviderRuntimeCommandRunner,
        require_linux: bool = True,
    ) -> None:
        self.dispatcher_path = dispatcher_path.resolve()
        self.runner = runner
        self.require_linux = require_linux
        if self.dispatcher_path.name != self._DISPATCHER_NAME:
            raise ValueError("runtime broker requires the reviewed dispatcher filename")

    def build_argv(self, *, invocation: ProviderRuntimeInvocation) -> list[str]:
        if invocation.installer_id != "aidn-provider-runtime-ubuntu.v1":
            raise ValueError("runtime broker received an unsupported installer")
        arguments = dict(invocation.arguments)
        argv = [
            str(self.dispatcher_path),
            invocation.provider,
            invocation.action,
        ]
        if invocation.provider == "whisper":
            self._append_if_present(argv, arguments, "image", "--image")
            self._append_if_present(argv, arguments, "model", "--model")
            self._append_if_present(argv, arguments, "port", "--port")
            self._append_if_present(argv, arguments, "data_dir", "--data-dir")
        elif invocation.provider == "ollama":
            self._append_if_present(argv, arguments, "version", "--version")
            self._append_if_present(argv, arguments, "model", "--model")
        elif invocation.provider == "llama.cpp":
            self._append_if_present(argv, arguments, "ref", "--ref")
            self._append_if_present(argv, arguments, "backend", "--backend")
            self._append_if_present(argv, arguments, "root", "--root")
            self._append_if_present(argv, arguments, "model", "--model")
        elif invocation.provider == "vllm":
            self._append_if_present(argv, arguments, "version", "--version")
            self._append_if_present(argv, arguments, "python", "--python")
            self._append_if_present(argv, arguments, "root", "--root")
            self._append_if_present(argv, arguments, "model", "--model")
            self._append_if_present(
                argv,
                arguments,
                "served_model_name",
                "--served-model-name",
            )
        else:  # pragma: no cover - ProviderRuntimeInvocation validates this union.
            raise ValueError("runtime broker received an unsupported Provider")
        return argv

    def invoke(
        self,
        *,
        invocation: ProviderRuntimeInvocation,
        timeout_seconds: int = 3600,
    ) -> ProviderRuntimeBrokerResult:
        if self.require_linux and not sys.platform.startswith("linux"):
            return ProviderRuntimeBrokerResult(
                status="FAILED",
                summary="Ubuntu Provider runtime broker is available only on Linux.",
                details={"platform": sys.platform},
            )
        if not 1 <= timeout_seconds <= self._MAX_TIMEOUT_SECONDS:
            raise ValueError("runtime broker timeout is outside the reviewed bound")
        argv = self.build_argv(invocation=invocation)
        result = self.runner.run(argv=argv, timeout_seconds=timeout_seconds)
        stdout = result.stdout[: self._MAX_OUTPUT_BYTES]
        stderr = result.stderr[: self._MAX_OUTPUT_BYTES]
        status = "SUCCEEDED" if result.returncode == 0 else "FAILED"
        return ProviderRuntimeBrokerResult(
            status=status,
            summary=(
                "Reviewed Provider runtime action completed."
                if status == "SUCCEEDED"
                else "Reviewed Provider runtime action failed."
            ),
            details={
                "provider": invocation.provider,
                "action": invocation.action,
                "returncode": result.returncode,
                "stdout": stdout,
                "stderr": stderr,
            },
        )

    @staticmethod
    def _append_if_present(
        argv: list[str], arguments: dict[str, str], key: str, option: str
    ) -> None:
        value = arguments.get(key)
        if value is not None:
            argv.extend([option, value])


class SubprocessProviderRuntimeCommandRunner:
    """Explicit opt-in runner; it never invokes a shell or accepts an env map."""

    def run(self, *, argv: list[str], timeout_seconds: int) -> RuntimeCommandResult:
        import subprocess

        completed = subprocess.run(
            argv,
            check=False,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return RuntimeCommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class UnixSocketProviderRuntimeCommandRunner:
    """Send one reviewed argv to the root-owned local runtime broker.

    The Hypervisor process stays inside its user-systemd sandbox.  Privileged
    package, Docker, and CUDA work is performed by the separate broker service;
    this client only speaks a bounded JSON-lines protocol over a Unix socket.
    """

    _MAX_FRAME_BYTES = 128 * 1024

    def __init__(self, *, socket_path: Path | str) -> None:
        self.socket_path = str(socket_path)

    def run(self, *, argv: list[str], timeout_seconds: int) -> RuntimeCommandResult:
        request = json.dumps(
            {
                "argv": argv,
                "timeout_seconds": timeout_seconds,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        if len(request) > self._MAX_FRAME_BYTES:
            return RuntimeCommandResult(
                returncode=126,
                stderr="provider runtime broker request is too large",
            )
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(timeout_seconds + 5)
                address = (
                    "\x00" + self.socket_path[1:]
                    if self.socket_path.startswith("@")
                    else self.socket_path
                )
                client.connect(address)
                client.sendall(request)
                client.shutdown(socket.SHUT_WR)
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = client.recv(16 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self._MAX_FRAME_BYTES:
                        return RuntimeCommandResult(
                            returncode=126,
                            stderr="provider runtime broker response is too large",
                        )
                    chunks.append(chunk)
        except (OSError, TimeoutError) as error:
            return RuntimeCommandResult(
                returncode=127,
                stderr=f"provider runtime broker unavailable: {error}",
            )

        try:
            response = json.loads(b"".join(chunks).decode("utf-8"))
            returncode = response["returncode"]
            stdout = response.get("stdout", "")
            stderr = response.get("stderr", "")
            if not isinstance(returncode, int):
                raise ValueError("broker returncode must be an integer")
            if not isinstance(stdout, str) or not isinstance(stderr, str):
                raise ValueError("broker output fields must be strings")
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as error:
            return RuntimeCommandResult(
                returncode=126,
                stderr=f"invalid provider runtime broker response: {error}",
            )
        return RuntimeCommandResult(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )
