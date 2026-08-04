"""Run a host-local acceptance test for the production MCP TLS profile."""

from __future__ import annotations

import argparse
import base64
import http.client
import ipaddress
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from aidn_hypervisor.secrets import FileSecretManager

CERTIFICATE_HANDLE = "secret://mcp/tls/certificate"
PRIVATE_KEY_HANDLE = "secret://mcp/tls/private-key"
AUTHORITY_HANDLE = "secret://mcp/tls/ca"
AGENT_TOKEN = "mcp-tls-acceptance-agent-token"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a real local MCP mTLS certificate-rotation acceptance test"
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="AiDN repository used to launch the MCP server",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="Maximum time for each server or rotation wait",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the acceptance workspace and server log after success",
    )
    return parser


def _write_private_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    os.chmod(path, 0o600)


def _issue_ca(workspace: Path) -> tuple[rsa.RSAPrivateKey, x509.Certificate, Path]:
    key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AiDN MCP acceptance CA")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .sign(key, hashes.SHA256())
    )
    path = workspace / "ca.pem"
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    os.chmod(path, 0o600)
    return key, certificate, path


def _issue_server(
    workspace: Path,
    *,
    ca_key: rsa.RSAPrivateKey,
    ca_certificate: x509.Certificate,
    label: str,
) -> tuple[Path, Path, int]:
    key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"AiDN MCP server {label}")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(ca_certificate.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    certificate_path = workspace / f"server-{label}.pem"
    key_path = workspace / f"server-{label}-key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    _write_private_key(key_path, key)
    return certificate_path, key_path, certificate.serial_number


def _issue_client(
    workspace: Path,
    *,
    ca_key: rsa.RSAPrivateKey,
    ca_certificate: x509.Certificate,
) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AiDN MCP acceptance client")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(ca_certificate.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    certificate_path = workspace / "client.pem"
    key_path = workspace / "client-key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    _write_private_key(key_path, key)
    return certificate_path, key_path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _tls_serial(port: int, *, ca_file: Path, client_certificate: Path, client_key: Path) -> int:
    context = ssl.create_default_context(cafile=str(ca_file))
    context.load_cert_chain(certfile=str(client_certificate), keyfile=str(client_key))
    with socket.create_connection(("127.0.0.1", port), timeout=2) as raw_socket, context.wrap_socket(
        raw_socket,
        server_hostname="localhost",
    ) as tls_socket:
        encoded = tls_socket.getpeercert(binary_form=True)
    if not encoded:
        raise RuntimeError("MCP server did not present a TLS certificate")
    return x509.load_der_x509_certificate(encoded).serial_number


class _McpHttpsClient:
    def __init__(
        self,
        port: int,
        *,
        ca_file: Path,
        client_certificate: Path,
        client_key: Path,
    ) -> None:
        self._port = port
        self._ca_file = ca_file
        self._client_certificate = client_certificate
        self._client_key = client_key

    def __enter__(self) -> _McpHttpsClient:
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        return None

    def post_json(
        self,
        path: str,
        payload: dict[str, object],
        *,
        session_id: str | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        context = ssl.create_default_context(cafile=str(self._ca_file))
        context.load_cert_chain(
            certfile=str(self._client_certificate),
            keyfile=str(self._client_key),
        )
        headers = {
            "Authorization": f"Bearer {AGENT_TOKEN}",
            "Content-Type": "application/json",
            "Connection": "close",
        }
        if session_id is not None:
            headers["Mcp-Session-Id"] = session_id
        connection = http.client.HTTPSConnection(
            "127.0.0.1",
            self._port,
            context=context,
            timeout=2,
        )
        try:
            connection.request(
                "POST",
                path,
                body=json.dumps(payload).encode("utf-8"),
                headers=headers,
            )
            response = connection.getresponse()
            return (
                response.status,
                {key.lower(): value for key, value in response.getheaders()},
                response.read(),
            )
        finally:
            connection.close()


def _client(
    port: int,
    *,
    ca_file: Path,
    client_certificate: Path,
    client_key: Path,
) -> _McpHttpsClient:
    return _McpHttpsClient(
        port,
        ca_file=ca_file,
        client_certificate=client_certificate,
        client_key=client_key,
    )


def _initialize(client: _McpHttpsClient) -> str:
    status, headers, body = client.post_json(
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "mcp-tls-acceptance", "version": "1"},
            },
        },
    )
    if status != 200:
        raise RuntimeError(f"MCP initialize failed: HTTP {status} {body.decode('utf-8', errors='replace')}")
    try:
        return headers["mcp-session-id"]
    except KeyError as exc:
        raise RuntimeError("MCP initialize response did not contain Mcp-Session-Id") from exc


def _initialize_with_retry(
    port: int,
    *,
    ca_file: Path,
    client_certificate: Path,
    client_key: Path,
    timeout_seconds: float,
) -> str:
    def attempt() -> str:
        with _client(
            port,
            ca_file=ca_file,
            client_certificate=client_certificate,
            client_key=client_key,
        ) as client:
            return _initialize(client)

    return _wait_for(
        attempt,
        timeout_seconds=timeout_seconds,
        description="MCP initialize over mTLS",
    )


def _tools_list(client: _McpHttpsClient, session_id: str) -> None:
    status, _headers, body = client.post_json(
        "/mcp",
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        session_id=session_id,
    )
    if status != 200:
        raise RuntimeError(f"MCP tools/list failed: HTTP {status} {body.decode('utf-8', errors='replace')}")


def _wait_for(predicate, *, timeout_seconds: float, description: str):
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except (ConnectionError, OSError, RuntimeError, http.client.HTTPException, ssl.SSLError) as exc:
            last_error = exc
        time.sleep(0.1)
    suffix = f": {last_error}" if last_error is not None else ""
    raise RuntimeError(f"timed out waiting for {description}{suffix}")


def _log_tail(path: Path) -> str:
    if not path.exists():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:])


def run_acceptance(*, repo: Path, timeout_seconds: float, keep: bool) -> dict[str, object]:
    if not (repo / ".git").exists():
        raise ValueError(f"repository is invalid: {repo}")
    workspace = Path(tempfile.mkdtemp(prefix="aidn-mcp-tls-acceptance-"))
    server_process: subprocess.Popen | None = None
    log_path = workspace / "server.log"
    completed = False
    try:
        ca_key, ca_certificate, ca_file = _issue_ca(workspace)
        first_certificate, first_key, first_serial = _issue_server(
            workspace,
            ca_key=ca_key,
            ca_certificate=ca_certificate,
            label="v1",
        )
        second_certificate, second_key, second_serial = _issue_server(
            workspace,
            ca_key=ca_key,
            ca_certificate=ca_certificate,
            label="v2",
        )
        client_certificate, client_key = _issue_client(
            workspace,
            ca_key=ca_key,
            ca_certificate=ca_certificate,
        )
        master_key = base64.b64encode(os.urandom(32)).decode("ascii")
        raw_master_key = base64.b64decode(master_key)
        secret_manager = FileSecretManager(
            path=workspace / "secrets.json",
            master_key=raw_master_key,
        )
        secret_manager.put_many(
            {
                CERTIFICATE_HANDLE: first_certificate.read_bytes(),
                PRIVATE_KEY_HANDLE: first_key.read_bytes(),
                AUTHORITY_HANDLE: ca_file.read_bytes(),
            }
        )
        port = _free_port()
        state_path = workspace / "hypervisor-state.json"
        environment = os.environ.copy()
        environment.update(
            {
                "AIDN_SECRET_MANAGER_PATH": str(workspace / "secrets.json"),
                "AIDN_SECRET_MANAGER_MASTER_KEY": master_key,
                "AIDN_HYPERVISOR_STATE_PATH": str(state_path),
                "AIDN_HYPERVISOR_BUNDLES_PATH": str(workspace / "bundles.json"),
                "AIDN_MCP_REMOTE_ENABLED": "true",
                "AIDN_MCP_REMOTE_TOKEN": AGENT_TOKEN,
                "AIDN_MCP_TLS_RELOAD_SECONDS": "0.1",
                "PYTHONUNBUFFERED": "1",
            }
        )
        command = [
            sys.executable,
            "-m",
            "aidn_hypervisor.mcp.remote",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--cert-handle",
            CERTIFICATE_HANDLE,
            "--key-handle",
            PRIVATE_KEY_HANDLE,
            "--ca-handle",
            AUTHORITY_HANDLE,
            "--tls-reload-seconds",
            "0.1",
        ]
        with log_path.open("w", encoding="utf-8") as log:
            server_process = subprocess.Popen(
                command,
                cwd=repo,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        old_session_id = _initialize_with_retry(
            port,
            ca_file=ca_file,
            client_certificate=client_certificate,
            client_key=client_key,
            timeout_seconds=timeout_seconds,
        )
        observed_first_serial = _wait_for(
            lambda: _tls_serial(
                port,
                ca_file=ca_file,
                client_certificate=client_certificate,
                client_key=client_key,
            ),
            timeout_seconds=timeout_seconds,
            description="initial MCP mTLS listener",
        )
        if observed_first_serial != first_serial:
            raise RuntimeError("initial MCP server certificate serial does not match Secret Manager material")

        with _client(
            port,
            ca_file=ca_file,
            client_certificate=client_certificate,
            client_key=client_key,
        ) as client:
            _tools_list(client, old_session_id)

        secret_manager.put_many(
            {
                CERTIFICATE_HANDLE: second_certificate.read_bytes(),
                PRIVATE_KEY_HANDLE: second_key.read_bytes(),
                AUTHORITY_HANDLE: ca_file.read_bytes(),
            }
        )
        observed_second_serial = _wait_for(
            lambda: (
                serial
                if (serial := _tls_serial(
                    port,
                    ca_file=ca_file,
                    client_certificate=client_certificate,
                    client_key=client_key,
                ))
                == second_serial
                else None
            ),
            timeout_seconds=timeout_seconds,
            description="rotated MCP mTLS certificate",
        )
        if observed_second_serial != second_serial:
            raise RuntimeError("rotated MCP server certificate serial does not match new Secret Manager material")

        new_session_id = _initialize_with_retry(
            port,
            ca_file=ca_file,
            client_certificate=client_certificate,
            client_key=client_key,
            timeout_seconds=timeout_seconds,
        )
        with _client(
            port,
            ca_file=ca_file,
            client_certificate=client_certificate,
            client_key=client_key,
        ) as client:
            stale_status, _stale_headers, _stale_body = client.post_json(
                "/mcp",
                {"jsonrpc": "2.0", "id": 3, "method": "ping"},
                session_id=old_session_id,
            )
            if stale_status != 404:
                raise RuntimeError(
                    "old MCP transport session survived rotation: "
                    f"HTTP {stale_status}"
                )
            _tools_list(client, new_session_id)

        if server_process.poll() is not None:
            raise RuntimeError(f"MCP server exited after rotation with code {server_process.returncode}")
        completed = True
        return {
            "status": "ok",
            "checks": [
                "real_mtls_client_certificate",
                "secret_manager_tls_handles",
                "certificate_serial_rotation",
                "graceful_server_restart",
                "stale_transport_session_rejected",
                "new_transport_session_accepted",
                "mcp_tools_list_after_reconnect",
            ],
            "initial_certificate_serial": observed_first_serial,
            "rotated_certificate_serial": observed_second_serial,
            "old_session_rejected": True,
            "workspace": str(workspace) if keep else None,
        }
    except Exception as exc:
        raise RuntimeError(
            f"{exc}; acceptance workspace: {workspace}; server log: {log_path}"
        ) from exc
    finally:
        if server_process is not None and server_process.poll() is None:
            server_process.terminate()
            try:
                server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_process.kill()
                server_process.wait(timeout=5)
        if not keep and completed:
            shutil.rmtree(workspace, ignore_errors=True)


def main() -> int:
    args = _parser().parse_args()
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    try:
        report = run_acceptance(
            repo=args.repo.resolve(),
            timeout_seconds=args.timeout_seconds,
            keep=args.keep,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
