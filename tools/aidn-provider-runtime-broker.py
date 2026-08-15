#!/usr/bin/env python3
"""Root-owned broker for the reviewed Ubuntu Provider runtime dispatcher.

The Hypervisor never receives a generic privileged command runner.  It sends a
typed, shell-free argv over a Unix socket; this service checks the peer UID and
the dispatcher/provider/action/option allowlist again before starting the
immutable dispatcher as root.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import signal
import socket
import struct
import subprocess
import sys
from pathlib import Path

MAX_FRAME_BYTES = 128 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
MAX_TIMEOUT_SECONDS = 3600
PROVIDERS = {"whisper", "ollama", "llama.cpp", "vllm"}
ACTIONS = {"install", "start", "status", "stop"}
OPTIONS = {
    "whisper": {"--image", "--model", "--port", "--data-dir"},
    "ollama": {"--version", "--model"},
    "llama.cpp": {"--ref", "--backend", "--root", "--model"},
    "vllm": {"--version", "--python", "--root", "--model", "--served-model-name"},
}


def _error_response(message: str, *, returncode: int = 126) -> dict:
    return {"returncode": returncode, "stdout": "", "stderr": message}


def _peer_uid(connection: socket.socket) -> int | None:
    if not hasattr(socket, "SO_PEERCRED"):
        return None
    credentials = connection.getsockopt(
        socket.SOL_SOCKET,
        socket.SO_PEERCRED,
        struct.calcsize("3i"),
    )
    _pid, uid, _gid = struct.unpack("3i", credentials)
    return uid


def _read_frame(connection: socket.socket) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = connection.recv(16 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FRAME_BYTES:
            raise ValueError("request exceeds the broker frame limit")
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    frame = b"".join(chunks).split(b"\n", 1)[0]
    if not frame:
        raise ValueError("request frame is empty")
    return frame


def _validate_argv(argv: object, *, dispatcher: Path) -> list[str]:
    if not isinstance(argv, list) or not argv or any(not isinstance(item, str) for item in argv):
        raise ValueError("broker request argv must be a non-empty string list")
    if argv[0] != str(dispatcher):
        raise ValueError("broker request dispatcher is not the reviewed root-owned path")
    if len(argv) < 3:
        raise ValueError("broker request must include provider and action")
    provider, action = argv[1], argv[2]
    if provider not in PROVIDERS:
        raise ValueError("broker request provider is not allowlisted")
    if action not in ACTIONS:
        raise ValueError("broker request action is not allowlisted")
    expected_options = OPTIONS[provider]
    seen: set[str] = set()
    index = 3
    while index < len(argv):
        option = argv[index]
        if option not in expected_options or option in seen:
            raise ValueError(f"broker request option is not allowlisted: {option}")
        if index + 1 >= len(argv):
            raise ValueError(f"broker request option is missing a value: {option}")
        value = argv[index + 1]
        if not value or len(value) > 512 or any(character in value for character in "\x00\r\n"):
            raise ValueError(f"broker request option value is invalid: {option}")
        seen.add(option)
        index += 2
    return argv


def _operator_identity(*, uid: int, home: Path, name: str) -> tuple[str, str]:
    account = pwd.getpwuid(uid)
    if account.pw_dir != str(home):
        raise ValueError("broker operator home does not match the allowed UID")
    if account.pw_name != name:
        raise ValueError("broker operator name does not match the allowed UID")
    if home.stat().st_uid != uid:
        raise ValueError("broker operator home is not owned by the allowed UID")
    return account.pw_name, account.pw_dir


def _run_argv(
    argv: list[str],
    *,
    timeout_seconds: object,
    operator_uid: int,
    operator_home: Path,
    operator_name: str,
) -> dict:
    try:
        timeout = int(timeout_seconds)
    except (TypeError, ValueError) as error:
        raise ValueError("broker timeout must be an integer") from error
    if not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise ValueError("broker timeout is outside the reviewed bound")

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(operator_home),
            "USER": operator_name,
            "LOGNAME": operator_name,
            "PATH": (
                f"{operator_home}/.local/bin:/usr/local/cuda/bin:"
                "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
            ),
            "XDG_RUNTIME_DIR": f"/run/user/{operator_uid}",
            "AIDN_PROVIDER_RUNTIME_OPERATOR_UID": str(operator_uid),
            "AIDN_PROVIDER_RUNTIME_OPERATOR_HOME": str(operator_home),
            "AIDN_PROVIDER_RUNTIME_OPERATOR_NAME": operator_name,
        }
    )
    try:
        completed = subprocess.run(
            argv,
            check=False,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout[:MAX_OUTPUT_BYTES],
            "stderr": completed.stderr[:MAX_OUTPUT_BYTES],
        }
    except subprocess.TimeoutExpired as error:
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        return {
            "returncode": 124,
            "stdout": "",
            "stderr": (stderr[:MAX_OUTPUT_BYTES] + "\nprovider runtime action timed out")[:MAX_OUTPUT_BYTES],
        }
    except OSError as error:
        return _error_response(f"provider runtime action could not start: {error}", returncode=127)


class ProviderRuntimeBroker:
    def __init__(
        self,
        *,
        socket_path: Path,
        dispatcher_path: Path,
        allowed_uid: int,
        allowed_gid: int,
        operator_home: Path,
        operator_name: str,
    ) -> None:
        self.socket_path = socket_path
        self.dispatcher_path = dispatcher_path.resolve()
        self.allowed_uid = allowed_uid
        self.allowed_gid = allowed_gid
        self.operator_home = operator_home.resolve()
        self.operator_name = operator_name
        _operator_identity(
            uid=allowed_uid,
            home=self.operator_home,
            name=operator_name,
        )

    def _handle(self, connection: socket.socket) -> dict:
        peer_uid = _peer_uid(connection)
        if peer_uid is not None and peer_uid != self.allowed_uid:
            return _error_response("provider runtime broker rejected the peer UID")
        try:
            request = json.loads(_read_frame(connection).decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("broker request must be a JSON object")
            argv = _validate_argv(request.get("argv"), dispatcher=self.dispatcher_path)
            return _run_argv(
                argv,
                timeout_seconds=request.get("timeout_seconds"),
                operator_uid=self.allowed_uid,
                operator_home=self.operator_home,
                operator_name=self.operator_name,
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
            return _error_response(f"provider runtime broker rejected request: {error}")

    def serve(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(self.socket_path))
            os.chown(self.socket_path, self.allowed_uid, self.allowed_gid)
            os.chmod(self.socket_path, 0o660)
            server.listen(8)
            server.settimeout(1.0)
            stopping = False

            def stop(_signum, _frame) -> None:
                nonlocal stopping
                stopping = True

            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            while not stopping:
                try:
                    connection, _address = server.accept()
                except TimeoutError:
                    continue
                with connection:
                    response = self._handle(connection)
                    try:
                        connection.sendall(
                            json.dumps(response, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
                            + b"\n"
                        )
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        # A bounded client timeout or service restart may close the
                        # connection while the reviewed action is still completing.
                        # The action result is intentionally discarded, but the
                        # long-lived root broker must remain available for the next
                        # request.
                        continue
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--dispatcher", required=True, type=Path)
    parser.add_argument("--allowed-uid", required=True, type=int)
    parser.add_argument("--allowed-gid", required=True, type=int)
    parser.add_argument("--operator-home", required=True, type=Path)
    parser.add_argument("--operator-name", required=True)
    return parser.parse_args()


def main() -> int:
    if os.geteuid() != 0:
        print("provider runtime broker must run as root", file=sys.stderr)
        return 2
    args = _parse_args()
    broker = ProviderRuntimeBroker(
        socket_path=args.socket,
        dispatcher_path=args.dispatcher,
        allowed_uid=args.allowed_uid,
        allowed_gid=args.allowed_gid,
        operator_home=args.operator_home,
        operator_name=args.operator_name,
    )
    broker.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
