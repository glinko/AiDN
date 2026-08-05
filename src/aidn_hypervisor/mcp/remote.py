"""Opt-in authenticated HTTP transport for the AiDN MCP control plane.

This is an MVP LAN/server-to-server boundary, not an Internet-facing security
profile. The transport token authenticates the already-bound Agent Control
Session; it does not create authority, expose private keys, or bypass the
Hypervisor control plane. Operator actions use a separate token and are never
available to the Agent JSON-RPC session.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import ssl
import stat
import tempfile
import threading
from argparse import ArgumentParser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from aidn_hypervisor.mcp.server import (
    McpControlPlane,
    McpDomainError,
    McpJsonRpcServer,
)
from aidn_hypervisor.secrets import (
    FileSecretManager,
    SecretManagerError,
    load_file_secret_manager_from_environment,
)

DEFAULT_MAX_BODY_BYTES = 1_048_576
MCP_SESSION_HEADER = "Mcp-Session-Id"


@dataclass(frozen=True)
class McpRemoteTlsConfig:
    """Filesystem-backed TLS inputs for the production HTTP launcher."""

    certificate_file: Path
    private_key_file: Path
    certificate_authority_file: Path

    def validate(self) -> None:
        _build_mcp_server_ssl_context(self)

    def uvicorn_options(self) -> dict[str, Any]:
        self.validate()
        return {
            "ssl_certfile": str(self.certificate_file),
            "ssl_keyfile": str(self.private_key_file),
            "ssl_ca_certs": str(self.certificate_authority_file),
            "ssl_cert_reqs": ssl.CERT_REQUIRED,
            "ssl_context_factory": _uvicorn_mcp_ssl_context_factory,
        }


@dataclass(frozen=True)
class McpRemoteTlsSecretConfig:
    """Secret Manager handles used to build one MCP TLS identity."""

    certificate_handle: str
    private_key_handle: str
    certificate_authority_handle: str

    def __post_init__(self) -> None:
        for value in (
            self.certificate_handle,
            self.private_key_handle,
            self.certificate_authority_handle,
        ):
            if not isinstance(value, str) or not value.startswith("secret://"):
                raise ValueError("MCP TLS values must be secret handles")

    @property
    def handles(self) -> tuple[str, str, str]:
        return (
            self.certificate_handle,
            self.private_key_handle,
            self.certificate_authority_handle,
        )


class McpRemoteTlsMaterializer:
    """Materialize encrypted TLS handles as short-lived mode-0600 files."""

    def __init__(
        self,
        *,
        secret_manager: FileSecretManager,
        secret_config: McpRemoteTlsSecretConfig,
    ) -> None:
        self._secret_manager = secret_manager
        self._secret_config = secret_config
        self._directory = Path(tempfile.mkdtemp(prefix="aidn-mcp-tls-"))
        os.chmod(self._directory, 0o700)
        self._generation = 0
        self._fingerprint: str | None = None
        self._current: McpRemoteTlsConfig | None = None
        self._closed = False

    def materialize(self) -> McpRemoteTlsConfig:
        """Return the current TLS files, rematerializing changed handles."""
        if self._closed:
            raise RuntimeError("MCP TLS materializer is closed")
        self._secret_manager.reload()
        fingerprint = self._secret_manager.fingerprint(self._secret_config.handles)
        if self._current is not None and fingerprint == self._fingerprint:
            return self._current

        self._generation += 1
        values = [self._secret_manager.get(handle) for handle in self._secret_config.handles]
        generation_dir = self._directory / str(self._generation)
        generation_dir.mkdir(mode=0o700)
        certificate = self._write(generation_dir / "certificate.pem", values[0])
        private_key = self._write(generation_dir / "private-key.pem", values[1])
        authority = self._write(generation_dir / "ca.pem", values[2])
        config = McpRemoteTlsConfig(
            certificate_file=certificate,
            private_key_file=private_key,
            certificate_authority_file=authority,
        )
        config.validate()
        self._fingerprint = fingerprint
        self._current = config
        return config

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        shutil.rmtree(self._directory, ignore_errors=True)

    @staticmethod
    def _write(path: Path, value: bytes) -> Path:
        path.write_bytes(value)
        os.chmod(path, 0o600)
        return path


class McpRemoteTlsRotationWatcher:
    """Request a graceful server restart when TLS handles rotate."""

    def __init__(
        self,
        *,
        secret_manager: FileSecretManager,
        secret_config: McpRemoteTlsSecretConfig,
        on_rotation: Callable[[], bool],
        interval_seconds: float = 5.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("MCP TLS rotation interval must be positive")
        self._secret_manager = secret_manager
        self._secret_config = secret_config
        self._on_rotation = on_rotation
        self._interval_seconds = interval_seconds
        self._last_fingerprint = secret_manager.fingerprint(secret_config.handles)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._rotation_detected = False
        self._error: str | None = None

    @property
    def rotation_detected(self) -> bool:
        return self._rotation_detected

    @property
    def error(self) -> str | None:
        return self._error

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("MCP TLS rotation watcher is already started")
        self._stop_event.clear()
        self._thread = threading.Thread(
            name="aidn-mcp-tls-rotation",
            target=self._run,
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._interval_seconds * 2))
            self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            try:
                self._secret_manager.reload()
                fingerprint = self._secret_manager.fingerprint(self._secret_config.handles)
            except (SecretManagerError, OSError, ValueError) as exc:
                self._error = str(exc)
                continue
            if fingerprint == self._last_fingerprint:
                continue
            try:
                accepted = self._on_rotation()
            except (SecretManagerError, OSError, ValueError) as exc:
                self._error = str(exc)
                continue
            if not accepted:
                continue
            self._last_fingerprint = fingerprint
            self._error = None
            self._rotation_detected = True
            return


def _build_mcp_server_ssl_context(config: McpRemoteTlsConfig) -> ssl.SSLContext:
    for field_name, path in (
        ("certificate", config.certificate_file),
        ("private key", config.private_key_file),
        ("certificate authority", config.certificate_authority_file),
    ):
        if not path.is_file():
            raise ValueError(f"MCP TLS {field_name} file does not exist: {path}")
    if os.name != "nt" and stat.S_IMODE(config.private_key_file.stat().st_mode) & 0o077:
        raise ValueError("MCP TLS private key must not be readable by group or other users")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(
        certfile=str(config.certificate_file),
        keyfile=str(config.private_key_file),
    )
    context.load_verify_locations(cafile=str(config.certificate_authority_file))
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _uvicorn_mcp_ssl_context_factory(config: Any, _fallback: Callable[[], ssl.SSLContext]) -> ssl.SSLContext:
    certificate_file = getattr(config, "ssl_certfile", None)
    private_key_file = getattr(config, "ssl_keyfile", None)
    certificate_authority_file = getattr(config, "ssl_ca_certs", None)
    if not certificate_file or not private_key_file or not certificate_authority_file:
        raise ValueError("MCP production transport requires certificate, key, and CA files")
    return _build_mcp_server_ssl_context(
        McpRemoteTlsConfig(
            certificate_file=Path(certificate_file),
            private_key_file=Path(private_key_file),
            certificate_authority_file=Path(certificate_authority_file),
        )
    )


def _digest_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _json_error(code: str, message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


class McpRemoteGateway:
    """Authenticated, bounded HTTP transport around one MCP Control Plane."""

    def __init__(
        self,
        control: McpControlPlane,
        *,
        agent_token: str | None,
        operator_token: str | None = None,
        require_tls: bool = False,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        max_transport_sessions: int = 128,
    ) -> None:
        if agent_token is not None and not isinstance(agent_token, str):
            raise ValueError("MCP remote agent token must be a string")
        if operator_token is not None and not isinstance(operator_token, str):
            raise ValueError("MCP operator token must be a string")
        if agent_token is not None and not agent_token.strip():
            raise ValueError("MCP remote agent token must not be empty")
        if operator_token is not None and not operator_token.strip():
            raise ValueError("MCP operator token must not be empty")
        if agent_token is not None and operator_token is not None and hmac.compare_digest(
            _digest_token(agent_token),
            _digest_token(operator_token),
        ):
            raise ValueError("MCP agent and operator tokens must be different")
        if agent_token is None and operator_token is not None:
            raise ValueError("MCP operator token requires the remote agent token")
        if max_body_bytes < 1024:
            raise ValueError("MCP remote body limit is too small")
        if max_transport_sessions < 1:
            raise ValueError("MCP remote session limit must be positive")
        self.control = control
        self._agent_token_hash = _digest_token(agent_token) if agent_token is not None else None
        self._operator_token_hash = _digest_token(operator_token) if operator_token is not None else None
        self.max_body_bytes = max_body_bytes
        self.max_transport_sessions = max_transport_sessions
        self.require_tls = require_tls
        self._sessions: dict[str, McpJsonRpcServer] = {}

    @property
    def enabled(self) -> bool:
        return self._agent_token_hash is not None

    @property
    def operator_enabled(self) -> bool:
        return self._operator_token_hash is not None

    def _authorized(self, request: Request, expected: bytes | None) -> bool:
        if expected is None:
            return False
        authorization = request.headers.get("authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            return False
        return hmac.compare_digest(_digest_token(token.strip()), expected)

    @staticmethod
    def _origin_is_rejected(request: Request) -> bool:
        # The MVP endpoint is server-to-server. Do not accidentally turn a
        # bearer-token control route into a browser-callable API.
        return bool(request.headers.get("origin"))

    def _unauthorized(self) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            content=_json_error("MCP_REMOTE_UNAUTHORIZED", "A valid bearer token is required"),
        )

    def _forbidden_origin(self) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content=_json_error("MCP_REMOTE_ORIGIN_REJECTED", "Browser-origin requests are not accepted"),
        )

    @staticmethod
    def _tls_required_response() -> JSONResponse:
        return JSONResponse(
            status_code=426,
            headers={"Upgrade": "TLS/1.2"},
            content=_json_error(
                "MCP_REMOTE_TLS_REQUIRED",
                "This MCP remote boundary requires HTTPS with a client certificate",
            ),
        )

    def _renew_control_session(self, *, source: str) -> JSONResponse | None:
        try:
            self.control.renew_control_session(source=source)
        except Exception:
            return JSONResponse(
                status_code=500,
                content=_json_error(
                    "MCP_CONTROL_SESSION_RENEW_FAILED",
                    "Control Session renewal failed safely",
                ),
            )
        return None

    async def _read_json_object(self, request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
        body = await request.body()
        if len(body) > self.max_body_bytes:
            return None, JSONResponse(
                status_code=413,
                content=_json_error("MCP_REMOTE_BODY_TOO_LARGE", "MCP request body exceeds the configured limit"),
            )
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return None, JSONResponse(
                status_code=400,
                content=_json_error("MCP_REMOTE_INVALID_JSON", "MCP request body is not valid JSON"),
            )
        if not isinstance(payload, dict):
            return None, JSONResponse(
                status_code=400,
                content=_json_error(
                    "MCP_REMOTE_BATCH_UNSUPPORTED",
                    "Only one JSON-RPC object per request is supported",
                ),
            )
        return payload, None

    @staticmethod
    def _response(
        payload: dict[str, Any] | None,
        *,
        session_id: str | None = None,
        status_code: int = 200,
    ) -> Response:
        headers = {MCP_SESSION_HEADER: session_id} if session_id is not None else None
        if payload is None:
            return Response(status_code=status_code, headers=headers)
        return JSONResponse(status_code=status_code, headers=headers, content=payload)

    def _new_transport_session(self) -> tuple[str, McpJsonRpcServer] | None:
        if len(self._sessions) >= self.max_transport_sessions:
            return None
        session_id = "mcp-" + secrets.token_urlsafe(24)
        server = McpJsonRpcServer(self.control)
        self._sessions[session_id] = server
        return session_id, server

    async def handle_agent(self, request: Request) -> Response:
        if not self.enabled:
            return JSONResponse(status_code=404, content=_json_error("MCP_REMOTE_DISABLED", "Remote MCP is disabled"))
        if self.require_tls and request.url.scheme != "https":
            return self._tls_required_response()
        if not self._authorized(request, self._agent_token_hash):
            return self._unauthorized()
        if self._origin_is_rejected(request):
            return self._forbidden_origin()
        renewal_error = self._renew_control_session(source="agent")
        if renewal_error is not None:
            return renewal_error

        session_id = request.headers.get(MCP_SESSION_HEADER)
        if request.method == "DELETE":
            if not session_id or session_id not in self._sessions:
                return JSONResponse(
                    status_code=404,
                    content=_json_error("MCP_REMOTE_SESSION_NOT_FOUND", "MCP transport session was not found"),
                )
            del self._sessions[session_id]
            return self._response(None, status_code=204)

        payload, error_response = await self._read_json_object(request)
        if error_response is not None:
            return error_response
        assert payload is not None
        method = payload.get("method")
        if method == "initialize":
            if session_id is not None:
                return JSONResponse(
                    status_code=400,
                    content=_json_error(
                        "MCP_REMOTE_SESSION_INVALID",
                        "initialize must not include an existing MCP session header",
                    ),
                )
            created = self._new_transport_session()
            if created is None:
                return JSONResponse(
                    status_code=429,
                    content=_json_error("MCP_REMOTE_SESSION_LIMIT", "MCP transport session capacity is exhausted"),
                )
            new_session_id, server = created
            response = server.handle_message(payload)
            if response is None or "error" in response:
                del self._sessions[new_session_id]
                return self._response(response, status_code=200)
            return self._response(response, session_id=new_session_id)

        if not session_id:
            return JSONResponse(
                status_code=400,
                content=_json_error("MCP_REMOTE_SESSION_REQUIRED", "Mcp-Session-Id is required after initialize"),
            )
        server = self._sessions.get(session_id)
        if server is None:
            return JSONResponse(
                status_code=404,
                content=_json_error("MCP_REMOTE_SESSION_NOT_FOUND", "MCP transport session was not found"),
            )
        response = server.handle_message(payload)
        if response is None:
            return self._response(None, session_id=session_id, status_code=202)
        return self._response(response, session_id=session_id)

    def _operator_error(self, error: McpDomainError) -> JSONResponse:
        status_code = 403 if error.code == "MCP_PERMISSION_DENIED" else 409
        return JSONResponse(status_code=status_code, content={"error": error.as_dict()})

    async def _operator_action(self, request: Request, action: str) -> Response:
        if not self.operator_enabled:
            return JSONResponse(
                status_code=404,
                content=_json_error("MCP_OPERATOR_DISABLED", "Operator API is disabled"),
            )
        if self.require_tls and request.url.scheme != "https":
            return self._tls_required_response()
        if not self._authorized(request, self._operator_token_hash):
            return self._unauthorized()
        if self._origin_is_rejected(request):
            return self._forbidden_origin()
        renewal_error = self._renew_control_session(source="operator")
        if renewal_error is not None:
            return renewal_error
        payload, error_response = await self._read_json_object(request)
        if error_response is not None:
            return error_response
        assert payload is not None
        try:
            if action == "approve":
                plan_hash = payload.get("plan_hash")
                approval_reference = payload.get("approval_reference")
                result = self.control.approve_plan(
                    plan_hash if isinstance(plan_hash, str) else "",
                    approval_reference=approval_reference if isinstance(approval_reference, str) else "",
                    approver_identity=self.control.session.operator_identity,
                )
            else:
                reason = payload.get("reason")
                reference = payload.get("reference")
                result = self.control.set_emergency_stop(
                    active=action == "emergency-stop",
                    reason=reason if isinstance(reason, str) else "",
                    reference=reference if isinstance(reference, str) else "",
                    operator_identity=self.control.session.operator_identity,
                )
        except McpDomainError as error:
            return self._operator_error(error)
        except Exception:
            return JSONResponse(
                status_code=500,
                content=_json_error("MCP_INTERNAL_ERROR", "Operator control action failed safely"),
            )
        return JSONResponse(status_code=200, content={"result": result})

    async def handle_operator_approve(self, request: Request) -> Response:
        return await self._operator_action(request, "approve")

    async def handle_operator_emergency_stop(self, request: Request) -> Response:
        return await self._operator_action(request, "emergency-stop")

    async def handle_operator_emergency_stop_clear(self, request: Request) -> Response:
        return await self._operator_action(request, "emergency-stop-clear")

    def close_all_sessions(self) -> None:
        self._sessions.clear()


def build_mcp_remote_router(gateway: McpRemoteGateway, *, prefix: str = "/mcp") -> APIRouter:
    """Build routes only for an explicitly enabled gateway."""

    normalized_prefix = "/" + prefix.strip("/")
    router = APIRouter()
    router.add_api_route(normalized_prefix, gateway.handle_agent, methods=["POST", "DELETE"])
    if gateway.operator_enabled:
        router.add_api_route(
            f"{normalized_prefix}/operator/approve",
            gateway.handle_operator_approve,
            methods=["POST"],
        )
        router.add_api_route(
            f"{normalized_prefix}/operator/emergency-stop",
            gateway.handle_operator_emergency_stop,
            methods=["POST"],
        )
        router.add_api_route(
            f"{normalized_prefix}/operator/emergency-stop/clear",
            gateway.handle_operator_emergency_stop_clear,
            methods=["POST"],
        )
    return router


def _http_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Run the AiDN MCP node-control server over mandatory mTLS HTTP")
    parser.add_argument("--host", default=os.environ.get("AIDN_MCP_REMOTE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("AIDN_MCP_REMOTE_PORT", "8766")))
    parser.add_argument("--certfile", default=os.environ.get("AIDN_MCP_TLS_CERTFILE"))
    parser.add_argument("--keyfile", default=os.environ.get("AIDN_MCP_TLS_KEYFILE"))
    parser.add_argument("--ca-file", dest="ca_file", default=os.environ.get("AIDN_MCP_TLS_CA_FILE"))
    parser.add_argument("--cert-handle", default=os.environ.get("AIDN_MCP_TLS_CERT_HANDLE"))
    parser.add_argument("--key-handle", default=os.environ.get("AIDN_MCP_TLS_KEY_HANDLE"))
    parser.add_argument("--ca-handle", default=os.environ.get("AIDN_MCP_TLS_CA_HANDLE"))
    parser.add_argument(
        "--tls-reload-seconds",
        type=float,
        default=float(os.environ.get("AIDN_MCP_TLS_RELOAD_SECONDS", "5")),
    )
    return parser


def main_http(argv: list[str] | None = None) -> None:
    """Launch the production mTLS HTTP profile with one process worker."""

    parser = _http_parser()
    args = parser.parse_args(argv)
    if os.environ.get("AIDN_MCP_REMOTE_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
        parser.error("AIDN_MCP_REMOTE_ENABLED=true is required")
    if not os.environ.get("AIDN_MCP_REMOTE_TOKEN", "").strip():
        parser.error("AIDN_MCP_REMOTE_TOKEN is required")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be in range 1..65535")

    path_values = (args.certfile, args.keyfile, args.ca_file)
    handle_values = (args.cert_handle, args.key_handle, args.ca_handle)
    has_paths = any(path_values)
    has_handles = any(handle_values)
    if has_paths and has_handles:
        parser.error("choose either TLS files or Secret Manager handles, not both")
    if has_handles and not all(handle_values):
        parser.error("Secret Manager TLS profile requires --cert-handle, --key-handle, and --ca-handle")
    if not has_paths and not has_handles:
        parser.error(
            "production mTLS requires --certfile/--keyfile/--ca-file or the three TLS secret handles"
        )
    if has_paths and not all(path_values):
        parser.error("file-backed TLS profile requires --certfile, --keyfile, and --ca-file")
    if args.tls_reload_seconds <= 0:
        parser.error("--tls-reload-seconds must be positive")

    secret_manager: FileSecretManager | None = None
    secret_config: McpRemoteTlsSecretConfig | None = None
    materializer: McpRemoteTlsMaterializer | None = None
    if has_handles:
        try:
            secret_manager = load_file_secret_manager_from_environment()
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        if secret_manager is None:
            parser.error(
                "Secret Manager TLS profile requires AIDN_SECRET_MANAGER_PATH and "
                "AIDN_SECRET_MANAGER_MASTER_KEY"
            )
        try:
            secret_config = McpRemoteTlsSecretConfig(
                certificate_handle=args.cert_handle,
                private_key_handle=args.key_handle,
                certificate_authority_handle=args.ca_handle,
            )
        except ValueError as exc:
            parser.error(str(exc))
        materializer = McpRemoteTlsMaterializer(
            secret_manager=secret_manager,
            secret_config=secret_config,
        )
        try:
            tls_config = materializer.materialize()
        except (OSError, SecretManagerError, ValueError) as exc:
            materializer.close()
            parser.error(f"Secret Manager TLS materialization failed: {exc}")
    else:
        tls_config = McpRemoteTlsConfig(
            certificate_file=Path(args.certfile),
            private_key_file=Path(args.keyfile),
            certificate_authority_file=Path(args.ca_file),
        )
        try:
            tls_config.validate()
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    os.environ["AIDN_MCP_REMOTE_TLS_REQUIRED"] = "true"

    import uvicorn

    from aidn_hypervisor.main import build_app

    try:
        while True:
            if materializer is not None:
                tls_config = materializer.materialize()
            config = uvicorn.Config(
                build_app(),
                host=args.host,
                port=args.port,
                workers=1,
                **tls_config.uvicorn_options(),
            )
            server = uvicorn.Server(config)
            watcher = None
            if secret_manager is not None and secret_config is not None:
                def request_tls_restart(server_ref=server) -> bool:
                    assert materializer is not None
                    try:
                        materializer.materialize()
                    except (OSError, SecretManagerError, ValueError):
                        return False
                    server_ref.should_exit = True
                    return True

                watcher = McpRemoteTlsRotationWatcher(
                    secret_manager=secret_manager,
                    secret_config=secret_config,
                    on_rotation=request_tls_restart,
                    interval_seconds=args.tls_reload_seconds,
                )
                watcher.start()
            try:
                server.run()
            finally:
                if watcher is not None:
                    watcher.stop()
            if watcher is None or not watcher.rotation_detected:
                break
    finally:
        if materializer is not None:
            materializer.close()


if __name__ == "__main__":
    main_http()
