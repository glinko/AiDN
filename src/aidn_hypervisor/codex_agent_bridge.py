"""Run Codex as an OAuth-authenticated external AiDN MCP agent.

This module deliberately runs *outside* the Hypervisor process.  Codex owns
the ChatGPT OAuth credentials in its own ``CODEX_HOME``; AiDN receives only a
normal, revocable MCP bearer credential.  The bridge converts durable
operator-chat events into Codex turns and submits Codex's final text through
the narrow ``aidn.operator.chat.reply`` MCP tool.

It is a reference runtime for a single trusted operator machine.  It is not a
replacement for the Hypervisor's MCP gateway and never needs the dashboard
browser's session cookie or the operator-authority secret.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_PROTOCOL_VERSION = "2025-06-18"
DEFAULT_POLL_SECONDS = 2.0
DEFAULT_TURN_TIMEOUT_SECONDS = 300.0
OPERATOR_MESSAGE_EVENT = "aidn.operator.agent_message"


class BridgeError(RuntimeError):
    """A recoverable bridge operation error suitable for an operator log."""


def _json_line(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _result_text(item: Mapping[str, Any]) -> str:
    """Read the final text from a Codex app-server item notification."""

    if item.get("type") != "agentMessage":
        return ""
    text = item.get("text")
    if isinstance(text, str):
        return text.strip()
    content = item.get("content")
    if isinstance(content, list):
        values = [
            str(part.get("text", "")).strip()
            for part in content
            if isinstance(part, Mapping) and isinstance(part.get("text"), str)
        ]
        return "\n".join(value for value in values if value).strip()
    return ""


def extract_operator_messages(payload: object) -> list[dict[str, str]]:
    """Select only operator-chat events from an AiDN event inbox response."""

    source = _as_dict(payload)
    values = source.get("items")
    if not isinstance(values, list):
        return []
    messages: list[dict[str, str]] = []
    for item in values:
        record = _as_dict(item)
        if record.get("event_type") != OPERATOR_MESSAGE_EVENT:
            continue
        details = _as_dict(record.get("details"))
        text = details.get("text")
        event_id = record.get("event_id")
        if isinstance(text, str) and text.strip() and isinstance(event_id, str) and event_id:
            messages.append({"event_id": event_id, "text": text.strip()})
    return messages


class JsonLineRpcProcess:
    """Small synchronous JSON-RPC client for ``codex app-server --stdio``."""

    def __init__(self, command: list[str], *, environment: Mapping[str, str]) -> None:
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=dict(environment),
            )
        except OSError as error:
            raise BridgeError(f"Could not start Codex app-server: {error}") from error
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr: queue.Queue[str] = queue.Queue(maxsize=200)
        self._next_id = 1
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._error_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._error_reader.start()

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                self._messages.put(value)

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        for line in self._process.stderr:
            try:
                self._stderr.put_nowait(line.strip())
            except queue.Full:
                try:
                    self._stderr.get_nowait()
                except queue.Empty:
                    pass
                self._stderr.put_nowait(line.strip())

    def _write(self, payload: Mapping[str, Any]) -> None:
        if self._process.poll() is not None:
            raise BridgeError(self._exit_error())
        assert self._process.stdin is not None
        try:
            self._process.stdin.write(_json_line(payload))
            self._process.stdin.flush()
        except OSError as error:
            raise BridgeError(f"Could not write to Codex app-server: {error}") from error

    def request(self, method: str, params: Mapping[str, Any] | None = None, *, timeout: float = 30.0) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            payload["params"] = dict(params)
        self._write(payload)
        deadline = time.monotonic() + timeout
        deferred: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            try:
                message = self._messages.get(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                if self._process.poll() is not None:
                    raise BridgeError(self._exit_error()) from None
                continue
            if message.get("id") == request_id:
                for saved in deferred:
                    self._messages.put(saved)
                if "error" in message:
                    raise BridgeError(str(_as_dict(message.get("error")).get("message", "Codex request failed")))
                return _as_dict(message.get("result"))
            deferred.append(message)
        for saved in deferred:
            self._messages.put(saved)
        raise BridgeError(f"Timed out waiting for Codex {method}")

    def notification(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = dict(params)
        self._write(payload)

    def next_notification(self, *, timeout: float) -> dict[str, Any] | None:
        try:
            return self._messages.get(timeout=timeout)
        except queue.Empty:
            if self._process.poll() is not None:
                raise BridgeError(self._exit_error()) from None
            return None

    def _exit_error(self) -> str:
        logs = list(self._stderr.queue)[-3:]
        suffix = f"; stderr: {' | '.join(logs)}" if logs else ""
        return f"Codex app-server exited with status {self._process.poll()}{suffix}"

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()


class McpRemoteClient:
    """Authenticated MCP-over-HTTP client bound to one revocable credential."""

    def __init__(self, *, url: str, bearer_token: str) -> None:
        self._url = url
        self._token = bearer_token
        self._session_id: str | None = None
        self._next_id = 1

    def initialize(self) -> None:
        # A long-lived relay polls the inbox repeatedly.  MCP initialization
        # creates one transport session, so repeat calls must reuse it instead
        # of sending a second initialize request with Mcp-Session-Id attached.
        if self._session_id:
            return
        response, headers = self._post(
            "initialize",
            {
                "protocolVersion": DEFAULT_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "aidn-codex-agent", "version": "0.1"},
            },
        )
        protocol = _as_dict(response.get("result")).get("protocolVersion")
        if protocol != DEFAULT_PROTOCOL_VERSION:
            raise BridgeError("AiDN MCP returned an incompatible protocol version")
        # HTTP field names are case-insensitive.  ``urllib`` preserves the
        # spelling supplied by the remote server and Uvicorn emits this one
        # as ``mcp-session-id``; treating it as a normal case-sensitive dict
        # made the OAuth bridge reject an otherwise valid MCP initialization.
        session_id = next(
            (
                value
                for header, value in headers.items()
                if header.lower() == "mcp-session-id"
            ),
            None,
        )
        if not session_id:
            raise BridgeError("AiDN MCP did not return Mcp-Session-Id")
        self._session_id = session_id
        self._post("notifications/initialized", None, include_id=False)

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        response, _headers = self._post(
            "tools/call",
            {"name": name, "arguments": dict(arguments or {})},
        )
        result = _as_dict(response.get("result"))
        if result.get("isError"):
            content = result.get("content")
            raise BridgeError(f"AiDN MCP tool {name} failed: {content}")
        return _as_dict(result.get("structuredContent"))

    def _post(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        *,
        include_id: bool = True,
    ) -> tuple[dict[str, Any], Mapping[str, str]]:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if include_id:
            payload["id"] = self._next_id
            self._next_id += 1
        if params is not None:
            payload["params"] = dict(params)
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        request = Request(self._url, data=_json_line(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
                return _as_dict(json.loads(body) if body else {}), dict(response.headers.items())
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise BridgeError(f"AiDN MCP HTTP {error.code}: {detail[:400]}") from error
        except (URLError, TimeoutError) as error:
            raise BridgeError(f"AiDN MCP is unreachable: {error}") from error


@dataclass
class CodexThreadState:
    thread_id: str | None = None

    @classmethod
    def load(cls, path: Path) -> CodexThreadState:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        value = _as_dict(raw).get("thread_id")
        return cls(thread_id=value if isinstance(value, str) and value else None)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps({"thread_id": self.thread_id}) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)


class CodexAgentBridge:
    """Drive one persisted Codex thread from an AiDN durable event inbox."""

    def __init__(
        self,
        *,
        codex_command: str,
        codex_home: Path,
        state_file: Path,
        mcp_url: str,
        mcp_token: str,
        workspace: Path,
    ) -> None:
        self._codex_command = codex_command
        self._codex_home = codex_home
        self._state_file = state_file
        self._mcp = McpRemoteClient(url=mcp_url, bearer_token=mcp_token)
        self._workspace = workspace

    def _app_server(self) -> JsonLineRpcProcess:
        self._codex_home.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(self._codex_home)
        process = JsonLineRpcProcess([self._codex_command, "app-server", "--stdio"], environment=environment)
        process.request(
            "initialize",
            {"clientInfo": {"name": "aidn-codex-agent", "title": "AiDN Codex agent", "version": "0.1"}},
        )
        process.notification("initialized")
        return process

    def login(self, *, timeout: float = 900.0) -> dict[str, str]:
        process = self._app_server()
        try:
            result = process.request("account/login/start", {"type": "chatgptDeviceCode"})
            url = result.get("verificationUrl")
            user_code = result.get("userCode")
            login_id = result.get("loginId")
            if not all(isinstance(value, str) and value for value in (url, user_code, login_id)):
                raise BridgeError("Codex did not return a usable device-code login")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                notification = process.next_notification(timeout=min(1.0, deadline - time.monotonic()))
                if notification is None or notification.get("method") != "account/login/completed":
                    continue
                details = _as_dict(notification.get("params"))
                if details.get("loginId") != login_id:
                    continue
                if details.get("success") is not True:
                    raise BridgeError(str(details.get("error") or "Codex OAuth login was not completed"))
                return {"verification_url": url, "user_code": user_code, "status": "authenticated"}
            process.request("account/login/cancel", {"loginId": login_id})
            raise BridgeError("Timed out waiting for ChatGPT device-code login")
        finally:
            process.close()

    def relay_once(self) -> int:
        self._mcp.initialize()
        inbox = self._mcp.call_tool("aidn.event.inbox", {"limit": 100})
        messages = extract_operator_messages(inbox)
        if not messages:
            return 0
        process = self._app_server()
        state = CodexThreadState.load(self._state_file)
        try:
            thread_id = self._load_or_start_thread(process, state)
            delivered: list[str] = []
            for message in messages:
                reply = self._run_turn(process, thread_id, message["text"])
                self._mcp.call_tool("aidn.operator.chat.reply", {"text": reply})
                delivered.append(message["event_id"])
            self._mcp.call_tool("aidn.event.ack", {"event_ids": delivered})
            return len(delivered)
        finally:
            process.close()

    def _load_or_start_thread(self, process: JsonLineRpcProcess, state: CodexThreadState) -> str:
        if state.thread_id:
            try:
                result = process.request("thread/resume", {"threadId": state.thread_id, "excludeTurns": True})
                resumed = _as_dict(result.get("thread")).get("id")
                if isinstance(resumed, str) and resumed:
                    return resumed
            except BridgeError:
                state.thread_id = None
        result = process.request(
            "thread/start",
            {
                "cwd": str(self._workspace),
                "approvalPolicy": "never",
                "sandbox": "readOnly",
                "personality": "pragmatic",
                "serviceName": "aidn_codex_agent",
            },
        )
        thread_id = _as_dict(result.get("thread")).get("id")
        if not isinstance(thread_id, str) or not thread_id:
            raise BridgeError("Codex did not create an agent thread")
        state.thread_id = thread_id
        state.save(self._state_file)
        return thread_id

    def _run_turn(self, process: JsonLineRpcProcess, thread_id: str, operator_text: str) -> str:
        prompt = (
            "You are the external Codex agent for an AiDN Hypervisor operator. "
            "Answer the operator's message directly and concisely in the message language. "
            "You are connected through an audited MCP bridge: do not claim you changed a node "
            "unless the supplied facts prove it. Do not use shell commands, files, browser, or "
            "network tools; explain what you know and state what evidence is missing.\n\n"
            f"Operator message:\n{operator_text}"
        )
        result = process.request(
            "turn/start",
            {"threadId": thread_id, "input": [{"type": "text", "text": prompt}]},
        )
        turn_id = _as_dict(result.get("turn")).get("id")
        if not isinstance(turn_id, str) or not turn_id:
            raise BridgeError("Codex did not start an agent turn")
        deadline = time.monotonic() + DEFAULT_TURN_TIMEOUT_SECONDS
        final_text = ""
        while time.monotonic() < deadline:
            notification = process.next_notification(timeout=min(1.0, deadline - time.monotonic()))
            if notification is None:
                continue
            params = _as_dict(notification.get("params"))
            if params.get("turnId") != turn_id:
                continue
            if notification.get("method") == "item/completed":
                text = _result_text(_as_dict(params.get("item")))
                if text:
                    final_text = text
            if notification.get("method") == "turn/completed":
                status = _as_dict(params.get("turn")).get("status")
                if status != "completed":
                    raise BridgeError(f"Codex turn ended with status {status or 'unknown'}")
                if final_text:
                    return final_text
                raise BridgeError("Codex completed the turn without an agent message")
        try:
            process.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
        except BridgeError:
            pass
        raise BridgeError("Timed out waiting for Codex response")


def _token_from_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise BridgeError(f"Environment variable {name} must contain the AiDN MCP bearer token")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-command", default="codex")
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument("--state-file", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    login = subparsers.add_parser("login", help="start ChatGPT OAuth device-code login")
    login.add_argument("--timeout-seconds", type=float, default=900.0)
    relay = subparsers.add_parser("relay", help="deliver AiDN operator chat messages to Codex")
    relay.add_argument("--mcp-url", required=True)
    relay.add_argument("--mcp-token-env", default="AIDN_MCP_TOKEN")
    relay.add_argument("--workspace", type=Path, default=Path.cwd())
    relay.add_argument("--once", action="store_true", help="process the current inbox once and exit")
    relay.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    state_file = args.state_file or args.codex_home / "aidn-agent-thread.json"
    if args.command == "login":
        bridge = CodexAgentBridge(
            codex_command=args.codex_command,
            codex_home=args.codex_home,
            state_file=state_file,
            mcp_url="http://unused.invalid/mcp",
            mcp_token="not-used-for-login",
            workspace=Path.cwd(),
        )
        try:
            # The actual code is printed before waiting so an operator can open
            # the browser immediately.  It is not persisted or logged to AiDN.
            process = bridge._app_server()
            try:
                result = process.request("account/login/start", {"type": "chatgptDeviceCode"})
                url = str(result.get("verificationUrl", ""))
                code = str(result.get("userCode", ""))
                login_id = str(result.get("loginId", ""))
                if not url or not code or not login_id:
                    raise BridgeError("Codex did not return a usable device-code login")
                print(f"Open: {url}\nCode: {code}\nWaiting for ChatGPT authorization…", flush=True)
                deadline = time.monotonic() + args.timeout_seconds
                while time.monotonic() < deadline:
                    notification = process.next_notification(timeout=min(1.0, deadline - time.monotonic()))
                    if notification is None or notification.get("method") != "account/login/completed":
                        continue
                    details = _as_dict(notification.get("params"))
                    if details.get("loginId") != login_id:
                        continue
                    if details.get("success") is not True:
                        raise BridgeError(str(details.get("error") or "Codex OAuth login was not completed"))
                    print("Codex OAuth authenticated.", flush=True)
                    return 0
                process.request("account/login/cancel", {"loginId": login_id})
                raise BridgeError("Timed out waiting for ChatGPT device-code login")
            finally:
                process.close()
        except BridgeError as error:
            print(f"aidn-codex-agent: {error}", file=sys.stderr)
            return 1
    try:
        bridge = CodexAgentBridge(
            codex_command=args.codex_command,
            codex_home=args.codex_home,
            state_file=state_file,
            mcp_url=args.mcp_url,
            mcp_token=_token_from_environment(args.mcp_token_env),
            workspace=args.workspace.resolve(),
        )
        while True:
            delivered = bridge.relay_once()
            if delivered:
                print(f"Delivered {delivered} AiDN operator message(s) to Codex.", flush=True)
            if args.once:
                return 0
            time.sleep(max(0.25, args.poll_seconds))
    except KeyboardInterrupt:
        return 0
    except BridgeError as error:
        print(f"aidn-codex-agent: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - console entry point
    raise SystemExit(main())
