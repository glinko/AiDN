#!/usr/bin/env python3
"""Root-owned broker for the reviewed Ubuntu Provider runtime dispatcher.

The Hypervisor never receives a generic privileged command runner.  It sends a
typed, shell-free argv over a Unix socket; this service checks the peer UID and
the dispatcher/provider/action/option allowlist again before starting the
immutable dispatcher as root.  Synchronous requests remain supported for
compatibility; asynchronous clients use durable ``submit``, ``status`` and
``cancel`` operations with idempotent client job IDs and replayable offsets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import signal
import socket
import struct
import subprocess
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

MAX_FRAME_BYTES = 128 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
MAX_TIMEOUT_SECONDS = 3600
MAX_JOB_EVENTS = 64
MAX_EVENT_OFFSET = 1_000_000_000
PROVIDERS = {"whisper", "ollama", "llama.cpp", "vllm", "consensus"}
ACTIONS = {"install", "start", "status", "stop", "remove"}
JOB_TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED"}
OPTIONS = {
    "whisper": {"--image", "--model", "--port", "--data-dir"},
    "ollama": {"--version", "--model"},
    "llama.cpp": {"--ref", "--backend", "--root", "--model"},
    "vllm": {"--version", "--python", "--root", "--model", "--served-model-name"},
    "consensus": {
        "--version", "--home", "--binary-path", "--service-name", "--chain-id",
        "--moniker", "--rpc-host", "--rpc-port", "--p2p-host", "--p2p-port",
        "--external-address", "--seeds", "--persistent-peers",
        "--abci-host", "--abci-port", "--no-abci",
    },
}
FLAGS = {"consensus": {"--no-abci"}}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _bounded_identifier(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError(f"broker {label} must be bounded non-empty text")
    if any(character in value for character in "\x00\r\n"):
        raise ValueError(f"broker {label} contains control characters")
    return value


def _request_hash(*, argv: list[str], timeout_seconds: int) -> str:
    payload = json.dumps(
        {"argv": argv, "timeout_seconds": timeout_seconds},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


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
        if option in FLAGS.get(provider, set()):
            seen.add(option)
            index += 1
            continue
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
            "AIDN_PROVIDER_RUNTIME_OPERATOR_GID": str(operator_home.stat().st_gid),
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


class _BrokerJobStore:
    """Small root-owned durable store for broker job state and event offsets."""

    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self._lock = RLock()
        self._jobs: dict[str, dict] = {}
        self._load_and_reconcile()

    def _load_and_reconcile(self) -> None:
        changed = False
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            jobs = payload.get("jobs", {}) if isinstance(payload, dict) else {}
            if isinstance(jobs, dict):
                valid_jobs: dict[str, dict] = {}
                for job_id, job in jobs.items():
                    if not isinstance(job, dict):
                        changed = True
                        continue
                    normalized_id = str(job_id)
                    if job.get("broker_job_id") != normalized_id:
                        changed = True
                        continue
                    if job.get("status") not in {
                        "QUEUED",
                        "RUNNING",
                        "SUCCEEDED",
                        "FAILED",
                        "CANCELLED",
                    }:
                        changed = True
                        continue
                    try:
                        event_offset = int(job.get("event_offset", 0))
                    except (TypeError, ValueError):
                        changed = True
                        continue
                    if event_offset < 0 or not isinstance(job.get("events", []), list):
                        changed = True
                        continue
                    valid_jobs[normalized_id] = dict(job)
                self._jobs = valid_jobs
            else:
                self._jobs = {}
                changed = True
        except FileNotFoundError:
            self._jobs = {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            # A corrupt root-owned state file must not make the broker accept
            # unknown requests.  Preserve it for forensics and start empty.
            try:
                corrupt = self.state_path.with_suffix(".corrupt")
                self.state_path.replace(corrupt)
            except OSError:
                pass
            self._jobs = {}

        with self._lock:
            for job in self._jobs.values():
                if job.get("status") in JOB_TERMINAL_STATUSES:
                    continue
                self._append_event_locked(
                    job,
                    status="FAILED",
                    progress_percent=100,
                    message="Broker restarted before the action reached a terminal state.",
                )
                job["status"] = "FAILED"
                job["progress_percent"] = 100
                job["updated_at"] = _now_iso()
                job["result"] = {
                    "status": "FAILED",
                    "summary": "Provider runtime broker restarted during the action.",
                    "details": {"code": "broker_restarted"},
                    "events": [],
                }
                changed = True
            if changed:
                self._persist_locked()

    def _persist_locked(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "jobs": self._jobs}, ensure_ascii=True, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(self.state_path)

    def _append_event_locked(
        self,
        job: dict,
        *,
        status: str,
        progress_percent: int,
        message: str,
    ) -> dict:
        offset = int(job.get("event_offset", 0)) + 1
        event = {
            "offset": offset,
            "event_id": f"{job['broker_job_id']}:{offset}",
            "status": status,
            "progress_percent": max(0, min(100, int(progress_percent))),
            "message": str(message)[:512],
            "timestamp": _now_iso(),
        }
        events = [item for item in job.get("events", []) if isinstance(item, dict)]
        events.append(event)
        if len(events) > MAX_JOB_EVENTS:
            events = events[-MAX_JOB_EVENTS:]
            job["events_truncated_before"] = events[0]["offset"]
        job["events"] = events
        job["event_offset"] = offset
        job["progress_percent"] = event["progress_percent"]
        job["updated_at"] = event["timestamp"]
        return event

    def create_or_get(
        self,
        *,
        client_job_id: str,
        request_hash: str,
        timeout_seconds: int,
    ) -> tuple[dict, bool]:
        with self._lock:
            for job in self._jobs.values():
                if job.get("client_job_id") != client_job_id:
                    continue
                if job.get("request_hash") != request_hash:
                    raise ValueError("broker client job ID was reused with a different request")
                return json.loads(json.dumps(job)), False

            now = _now_iso()
            job = {
                "broker_job_id": f"brj-{uuid4().hex[:16]}",
                "client_job_id": client_job_id,
                "request_hash": request_hash,
                "status": "QUEUED",
                "progress_percent": 0,
                "event_offset": 0,
                "events": [],
                "events_truncated_before": 0,
                "result": None,
                "cancel_requested": False,
                "timeout_seconds": timeout_seconds,
                "created_at": now,
                "updated_at": now,
            }
            self._append_event_locked(
                job,
                status="QUEUED",
                progress_percent=0,
                message="Broker job accepted and queued.",
            )
            self._jobs[job["broker_job_id"]] = job
            self._persist_locked()
            return json.loads(json.dumps(job)), True

    def get(self, broker_job_id: str, *, after_offset: int = 0) -> dict:
        with self._lock:
            job = self._jobs.get(broker_job_id)
            if job is None:
                raise KeyError(broker_job_id)
            result = json.loads(json.dumps(job))
            result["events"] = [
                event
                for event in result.get("events", [])
                if int(event.get("offset", 0)) > after_offset
            ]
            return result

    def update(
        self,
        broker_job_id: str,
        *,
        status: str,
        progress_percent: int,
        message: str,
        result: dict | None = None,
        cancel_requested: bool | None = None,
    ) -> dict:
        with self._lock:
            job = self._jobs.get(broker_job_id)
            if job is None:
                raise KeyError(broker_job_id)
            self._append_event_locked(
                job,
                status=status,
                progress_percent=progress_percent,
                message=message,
            )
            job["status"] = status
            if result is not None:
                job["result"] = result
            if cancel_requested is not None:
                job["cancel_requested"] = bool(cancel_requested)
            self._persist_locked()
            return json.loads(json.dumps(job))

    def request_cancel(self, broker_job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(broker_job_id)
            if job is None:
                raise KeyError(broker_job_id)
            if job.get("status") in JOB_TERMINAL_STATUSES:
                return json.loads(json.dumps(job))
            job["cancel_requested"] = True
            self._append_event_locked(
                job,
                status=str(job.get("status", "RUNNING")),
                progress_percent=int(job.get("progress_percent", 0)),
                message="Cancellation requested; the active action will finish cooperatively.",
            )
            self._persist_locked()
            return json.loads(json.dumps(job))


class ProviderRuntimeBroker:
    def __init__(
        self,
        *,
        socket_path: str,
        dispatcher_path: Path,
        allowed_uid: int,
        allowed_gid: int,
        operator_home: Path,
        operator_name: str,
        state_path: Path | None = None,
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
        self.state_path = (
            state_path.resolve()
            if state_path is not None
            else Path("/var/lib/aidn-provider-runtime") / f"jobs-{allowed_uid}.json"
        )
        self._jobs = _BrokerJobStore(self.state_path)
        self._futures: dict[str, Future] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="aidn-provider-runtime-broker",
        )

    @staticmethod
    def _control_error(message: str, *, code: str = "BROKER_REQUEST_INVALID") -> dict:
        return {"error": message[:512], "code": code}

    def _job_response(self, broker_job_id: str, *, after_offset: int = 0) -> dict:
        job = self._jobs.get(broker_job_id, after_offset=after_offset)
        return {
            "job": job,
            "events": job.get("events", []),
            "next_offset": int(job.get("event_offset", 0)) + 1,
        }

    def _submit_job(self, request: dict) -> dict:
        argv = _validate_argv(request.get("argv"), dispatcher=self.dispatcher_path)
        try:
            timeout = int(request.get("timeout_seconds", MAX_TIMEOUT_SECONDS))
        except (TypeError, ValueError) as error:
            raise ValueError("broker timeout must be an integer") from error
        if not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
            raise ValueError("broker timeout is outside the reviewed bound")
        client_job_id = _bounded_identifier(
            request.get("client_job_id"), label="client job ID"
        )
        request_hash = _request_hash(argv=argv, timeout_seconds=timeout)
        job, created = self._jobs.create_or_get(
            client_job_id=client_job_id,
            request_hash=request_hash,
            timeout_seconds=timeout,
        )
        if created:
            broker_job_id = job["broker_job_id"]
            self._futures[broker_job_id] = self._executor.submit(
                self._execute_job,
                broker_job_id,
                argv,
                timeout,
            )
        return self._job_response(job["broker_job_id"])

    def _execute_job(self, broker_job_id: str, argv: list[str], timeout_seconds: int) -> None:
        try:
            self._jobs.update(
                broker_job_id,
                status="RUNNING",
                progress_percent=10,
                message="Provider runtime action started by the broker.",
            )
            result = _run_argv(
                argv,
                timeout_seconds=timeout_seconds,
                operator_uid=self.allowed_uid,
                operator_home=self.operator_home,
                operator_name=self.operator_name,
            )
            succeeded = result.get("returncode") == 0
            self._jobs.update(
                broker_job_id,
                status="SUCCEEDED" if succeeded else "FAILED",
                progress_percent=100,
                message=(
                    "Provider runtime action completed successfully."
                    if succeeded
                    else "Provider runtime action failed."
                ),
                result={
                    "status": "SUCCEEDED" if succeeded else "FAILED",
                    "summary": (
                        "Reviewed Provider runtime action completed."
                        if succeeded
                        else "Reviewed Provider runtime action failed."
                    ),
                    "details": {
                        "provider": argv[1],
                        "action": argv[2],
                        **result,
                    },
                    "events": [],
                },
            )
        except Exception as error:  # pragma: no cover - defensive daemon boundary
            try:
                self._jobs.update(
                    broker_job_id,
                    status="FAILED",
                    progress_percent=100,
                    message="Provider runtime broker failed before the action completed.",
                    result={
                        "status": "FAILED",
                        "summary": "Provider runtime broker failed before the action completed.",
                        "details": {"code": "broker_internal_error", "error": str(error)[:512]},
                        "events": [],
                    },
                )
            except KeyError:
                pass
        finally:
            self._futures.pop(broker_job_id, None)

    def _control(self, request: dict) -> dict:
        operation = request.get("operation")
        if operation == "submit":
            return self._submit_job(request)
        if operation == "status":
            broker_job_id = _bounded_identifier(
                request.get("broker_job_id"), label="job ID"
            )
            try:
                after_offset = int(request.get("after_offset", 0))
            except (TypeError, ValueError) as error:
                raise ValueError("broker event offset must be an integer") from error
            if after_offset < 0:
                raise ValueError("broker event offset cannot be negative")
            if after_offset > MAX_EVENT_OFFSET:
                raise ValueError("broker event offset is outside the reviewed bound")
            return self._job_response(broker_job_id, after_offset=after_offset)
        if operation == "cancel":
            broker_job_id = _bounded_identifier(
                request.get("broker_job_id"), label="job ID"
            )
            job = self._jobs.request_cancel(broker_job_id)
            future = self._futures.get(broker_job_id)
            if job.get("status") == "QUEUED" and future is not None and future.cancel():
                self._jobs.update(
                    broker_job_id,
                    status="CANCELLED",
                    progress_percent=100,
                    message="Provider runtime action was cancelled before dispatch.",
                    result={
                        "status": "CANCELLED",
                        "summary": "Provider runtime action was cancelled before dispatch.",
                        "details": {"code": "cancelled_before_dispatch"},
                        "events": [],
                    },
                )
                self._futures.pop(broker_job_id, None)
            return self._job_response(broker_job_id)
        raise ValueError("broker operation must be submit, status, or cancel")

    def _handle(self, connection: socket.socket) -> dict:
        peer_uid = _peer_uid(connection)
        if peer_uid is not None and peer_uid != self.allowed_uid:
            return _error_response("provider runtime broker rejected the peer UID")
        try:
            request = json.loads(_read_frame(connection).decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("broker request must be a JSON object")
            if request.get("operation") is not None:
                try:
                    return self._control(request)
                except KeyError as error:
                    return self._control_error(
                        f"provider runtime broker job was not found: {error.args[0]}",
                        code="BROKER_JOB_NOT_FOUND",
                    )
                except (ValueError, TypeError, json.JSONDecodeError) as error:
                    return self._control_error(f"provider runtime broker rejected request: {error}")
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
        abstract_socket = self.socket_path.startswith("@")
        filesystem_socket = None if abstract_socket else Path(self.socket_path)
        if filesystem_socket is not None:
            filesystem_socket.parent.mkdir(parents=True, exist_ok=True)
            try:
                filesystem_socket.unlink()
            except FileNotFoundError:
                pass
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            address = "\x00" + self.socket_path[1:] if abstract_socket else self.socket_path
            server.bind(address)
            if filesystem_socket is not None:
                os.chown(filesystem_socket, self.allowed_uid, self.allowed_gid)
                os.chmod(filesystem_socket, 0o660)
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
        if filesystem_socket is not None:
            try:
                filesystem_socket.unlink()
            except FileNotFoundError:
                pass
        self._executor.shutdown(wait=False, cancel_futures=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--dispatcher", required=True, type=Path)
    parser.add_argument("--allowed-uid", required=True, type=int)
    parser.add_argument("--allowed-gid", required=True, type=int)
    parser.add_argument("--operator-home", required=True, type=Path)
    parser.add_argument("--operator-name", required=True)
    parser.add_argument("--state-path", type=Path)
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
        state_path=args.state_path,
    )
    broker.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
