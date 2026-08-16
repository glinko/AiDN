"""Bounded CometBFT installation flow for the paired operator dashboard.

The dashboard is deliberately not a shell.  It may select one of the reviewed
consensus profiles and a few bounded identity/network values, while the
Hypervisor derives every filesystem path and unit name locally.  Installation
is staged in a pending JSON document; applying that document is a separate,
explicit step which schedules the Hypervisor restart required to load the new
ConsensusService configuration.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import signal
import tempfile
import threading
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

DEFAULT_VERSION = "v0.38.19"
DEFAULT_CHAIN_ID = "aidn-localnet-1"
LOOPBACK = "127.0.0.1"
LAN = "0.0.0.0"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_VERSION = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
_VALID_MODES = frozenset({"validator", "non_validator"})
_MAX_OUTPUT = 64 * 1024
_MAX_PEERS = 32
_MAX_PEER_TEXT = 4096
_MAX_REMOTE_GENESIS_BYTES = 4 * 1024 * 1024
_REMOTE_RPC_TIMEOUT_SECONDS = 8
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")
_IPV6 = re.compile(r"^[0-9A-Fa-f:]{2,45}$")


class ConsensusRuntimeExecutor(Protocol):
    def invoke(self, *, argv: list[str], timeout_seconds: int) -> Any:
        ...


class UnixSocketConsensusRuntimeExecutor:
    """Small adapter around the existing root-owned runtime broker client."""

    def __init__(self, runner: Any) -> None:
        self.runner = runner

    def invoke(self, *, argv: list[str], timeout_seconds: int) -> Any:
        return self.runner.run(argv=argv, timeout_seconds=timeout_seconds)


@dataclass(frozen=True)
class CometBftInstallPlan:
    mode: str
    version: str
    chain_id: str
    moniker: str
    node_id: str
    rpc_host: str
    rpc_port: int
    p2p_host: str
    p2p_port: int
    external_address: str
    seeds: str
    persistent_peers: str
    abci_host: str
    abci_port: int
    home: str
    binary_path: str
    service_name: str

    @property
    def use_abci(self) -> bool:
        return self.mode == "validator"

    def as_config(self) -> dict[str, Any]:
        return {
            "profile": "operator-cometbft-install-v1",
            "mode": self.mode,
            "version": self.version,
            "chain_id": self.chain_id,
            "moniker": self.moniker,
            "node_id": self.node_id,
            "cometbft_endpoint": f"tcp://{self.rpc_host}:{self.rpc_port}",
            "rpc_host": self.rpc_host,
            "rpc_port": self.rpc_port,
            "p2p_host": self.p2p_host,
            "p2p_port": self.p2p_port,
            "external_address": self.external_address,
            "seeds": self.seeds,
            "persistent_peers": self.persistent_peers,
            "pex": True,
            "abci_host": self.abci_host,
            "abci_port": self.abci_port,
            "abci_state_path": f"{self.home}/../abci-state" if self.use_abci else None,
            "home": self.home,
            "binary_path": self.binary_path,
            "service_name": self.service_name,
            "managed_service_name": self.service_name,
        }


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _data_root(service: Any | None = None) -> Path | None:
    configured = os.getenv("AIDN_HYPERVISOR_STATE_PATH", "").strip()
    state_store = getattr(service, "state_store", None)
    state_path = getattr(state_store, "path", None)
    raw = configured or str(state_path or "")
    if not raw:
        return None
    return Path(raw).expanduser().resolve().parent


def _config_path(service: Any | None = None) -> Path | None:
    configured = os.getenv("AIDN_COMETBFT_CONFIG_PATH", "").strip()
    return Path(configured).expanduser() if configured else (
        _data_root(service) / "consensus-config.json" if _data_root(service) else None
    )


def _pending_path(service: Any | None = None) -> Path | None:
    active = _config_path(service)
    return active.with_name(f"{active.stem}.pending{active.suffix}") if active else None


def _read_object(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"CometBFT configuration could not be read: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("CometBFT configuration must contain a JSON object")
    return raw


def load_active_cometbft_configuration(service: Any | None = None) -> dict[str, Any] | None:
    """Load the staged-and-applied dashboard configuration, if present."""

    return _read_object(_config_path(service))


def _bounded_text(value: object, *, name: str, default: str, pattern: re.Pattern[str]) -> str:
    text = str(value if value is not None else default).strip()
    if not pattern.fullmatch(text):
        raise ValueError(f"{name} contains unsupported characters")
    return text


def _value_or_active(
    values: Mapping[str, object],
    active: Mapping[str, Any],
    name: str,
    default: object = "",
) -> object:
    """Use an explicit request value, including an explicit empty value."""

    return values[name] if name in values else active.get(name, default)


def _split_host_port(value: str, *, name: str) -> tuple[str, int]:
    """Validate a CometBFT host:port endpoint without resolving it."""

    text = value.strip()
    if not text or any(character.isspace() for character in text):
        raise ValueError(f"{name} must be a host:port endpoint")
    if text.startswith("["):
        closing = text.find("]")
        if closing < 2 or closing + 1 >= len(text) or text[closing + 1] != ":":
            raise ValueError(f"{name} must be a host:port endpoint")
        host = text[1:closing]
        port_text = text[closing + 2 :]
        if not _IPV6.fullmatch(host):
            raise ValueError(f"{name} contains an invalid IPv6 host")
    else:
        host, separator, port_text = text.rpartition(":")
        if not separator or not _HOST.fullmatch(host):
            raise ValueError(f"{name} must be a host:port endpoint")
    try:
        port = int(port_text)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} port must be an integer from 1 to 65535") from error
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} port must be an integer from 1 to 65535")
    return host, port


def _endpoint(value: object, *, name: str, default: str = "") -> str:
    text = str(default if value is None else value).strip()
    if not text:
        return ""
    _split_host_port(text, name=name)
    return text


def _peer_list(value: object, *, name: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) > _MAX_PEER_TEXT:
        raise ValueError(f"{name} is too long")
    entries: list[str] = []
    for candidate in re.split(r"[,\n\r]+", raw):
        peer = candidate.strip()
        if not peer:
            continue
        if "@" in peer:
            peer_id, endpoint = peer.rsplit("@", 1)
            if not _IDENTIFIER.fullmatch(peer_id):
                raise ValueError(f"{name} contains an invalid peer ID")
        else:
            endpoint = peer
        _split_host_port(endpoint, name=name)
        if peer not in entries:
            entries.append(peer)
    if len(entries) > _MAX_PEERS:
        raise ValueError(f"{name} may contain at most {_MAX_PEERS} peers")
    return ",".join(entries)


def _port(value: object, *, name: str, default: int) -> int:
    candidate = default if value is None or value == "" else value
    if isinstance(candidate, bool):
        raise ValueError(f"{name} must be an integer from 1 to 65535")
    try:
        result = int(candidate)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer from 1 to 65535") from error
    if not 1 <= result <= 65535:
        raise ValueError(f"{name} must be an integer from 1 to 65535")
    return result


def _safe_operator_id(service: Any) -> str:
    candidate = str(getattr(service, "operator_id", "") or getattr(service, "node_id", "") or "operator-local")
    return re.sub(r"[^A-Za-z0-9._-]+", "-", candidate)[:80] or "operator-local"


def build_cometbft_install_plan(service: Any, values: Mapping[str, object] | None = None) -> CometBftInstallPlan:
    values = values or {}
    active = load_active_cometbft_configuration(service) or {}
    consensus = getattr(service, "consensus_service", None)
    consensus_config = getattr(consensus, "config", None)
    operator_id = _safe_operator_id(service)
    node_id = re.sub(
        r"[^A-Za-z0-9._-]+",
        "-",
        str(getattr(service, "node_id", "") or operator_id),
    )[:80] or operator_id

    mode = str(
        values.get("mode")
        or active.get("mode")
        or getattr(getattr(consensus_config, "mode", None), "value", "")
        or "validator"
    )
    if mode not in _VALID_MODES:
        raise ValueError("CometBFT mode must be validator or non_validator")
    version = _bounded_text(
        values.get("version"),
        name="CometBFT version",
        default=str(active.get("version") or DEFAULT_VERSION),
        pattern=_VERSION,
    )
    if version != DEFAULT_VERSION:
        raise ValueError(f"CometBFT version {version} is not in the reviewed install catalog")
    chain_id = _bounded_text(
        values.get("chain_id"),
        name="CometBFT chain ID",
        default=str(
            active.get("chain_id")
            or getattr(consensus_config, "chain_id", "")
            or os.getenv("AIDN_COMETBFT_CHAIN_ID")
            or DEFAULT_CHAIN_ID
        ),
        pattern=_IDENTIFIER,
    )
    moniker = _bounded_text(
        values.get("moniker"),
        name="CometBFT moniker",
        default=str(active.get("moniker") or operator_id),
        pattern=_IDENTIFIER,
    )

    rpc_host = str(values.get("rpc_host") or LOOPBACK).strip()
    abci_host = str(values.get("abci_host") or LOOPBACK).strip()
    p2p_host = str(values.get("p2p_host") or active.get("p2p_host") or LOOPBACK).strip()
    if rpc_host != LOOPBACK or abci_host != LOOPBACK:
        raise ValueError("CometBFT RPC and ABCI must remain on loopback")
    if p2p_host not in {LOOPBACK, LAN}:
        raise ValueError("CometBFT P2P host must be 127.0.0.1 or 0.0.0.0")
    rpc_port = _port(values.get("rpc_port"), name="RPC port", default=int(active.get("rpc_port") or 26657))
    p2p_port = _port(values.get("p2p_port"), name="P2P port", default=int(active.get("p2p_port") or 26656))
    abci_port = _port(values.get("abci_port"), name="ABCI port", default=int(active.get("abci_port") or 26658))
    if len({rpc_port, p2p_port, abci_port}) != 3:
        raise ValueError("RPC, P2P and ABCI ports must be distinct")
    external_address = _endpoint(
        _value_or_active(values, active, "external_address"),
        name="CometBFT external address",
    )
    seeds = _peer_list(
        _value_or_active(values, active, "seeds"),
        name="CometBFT seeds",
    )
    persistent_peers = _peer_list(
        _value_or_active(values, active, "persistent_peers"),
        name="CometBFT persistent peers",
    )
    if external_address and p2p_host == LOOPBACK:
        raise ValueError("CometBFT external address requires a non-loopback P2P bind")

    root = _data_root(service)
    if root is None:
        raise ValueError("Persistent Hypervisor state is required for CometBFT installation")
    home = root / "consensus" / "cometbft"
    binary_path = root / "consensus" / "bin" / "cometbft"
    service_name = f"aidn-cometbft-{operator_id}.service"
    return CometBftInstallPlan(
        mode=mode,
        version=version,
        chain_id=chain_id,
        moniker=moniker,
        node_id=node_id,
        rpc_host=rpc_host,
        rpc_port=rpc_port,
        p2p_host=p2p_host,
        p2p_port=p2p_port,
        external_address=external_address,
        seeds=seeds,
        persistent_peers=persistent_peers,
        abci_host=abci_host,
        abci_port=abci_port,
        home=str(home),
        binary_path=str(binary_path),
        service_name=service_name,
    )


def _dispatcher_path() -> str:
    return os.getenv(
        "AIDN_PROVIDER_RUNTIME_DISPATCHER",
        "/usr/libexec/aidn-provider-runtime/aidn-provider-runtime-ubuntu.sh",
    )


def build_cometbft_install_argv(
    service: Any,
    values: Mapping[str, object] | None = None,
) -> tuple[CometBftInstallPlan, list[str]]:
    plan = build_cometbft_install_plan(service, values)
    argv = [
        _dispatcher_path(),
        "consensus",
        "install",
        "--version", plan.version,
        "--home", plan.home,
        "--binary-path", plan.binary_path,
        "--service-name", plan.service_name,
        "--chain-id", plan.chain_id,
        "--moniker", plan.moniker,
        "--rpc-host", plan.rpc_host,
        "--rpc-port", str(plan.rpc_port),
        "--p2p-host", plan.p2p_host,
        "--p2p-port", str(plan.p2p_port),
        "--abci-host", plan.abci_host,
        "--abci-port", str(plan.abci_port),
    ]
    # These are optional shell arguments.  Do not send an empty value: the
    # root-owned broker deliberately rejects empty option values before the
    # reviewed installer gets a chance to apply its defaults.
    if plan.external_address:
        argv.extend(["--external-address", plan.external_address])
    if plan.seeds:
        argv.extend(["--seeds", plan.seeds])
    if plan.persistent_peers:
        argv.extend(["--persistent-peers", plan.persistent_peers])
    if not plan.use_abci:
        argv.append("--no-abci")
    return plan, argv


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _result_detail(result: Any) -> tuple[int, str, str]:
    return (
        int(getattr(result, "returncode", 1)),
        str(getattr(result, "stdout", "") or "")[:_MAX_OUTPUT],
        str(getattr(result, "stderr", "") or "")[:_MAX_OUTPUT],
    )


def _executor(service: Any) -> ConsensusRuntimeExecutor:
    candidate = getattr(service, "consensus_installation_executor", None)
    if candidate is None or not callable(getattr(candidate, "invoke", None)):
        raise ValueError("CometBFT installation broker is not configured on this node")
    return candidate


def build_operator_cometbft_install_payload(service: Any) -> dict[str, Any]:
    try:
        plan = build_cometbft_install_plan(service)
    except ValueError as error:
        return {
            "profile": "operator-cometbft-install-v1",
            "available": False,
            "reason": str(error),
            "broker": {"configured": False},
            "defaults": {"version": DEFAULT_VERSION, "mode": "validator", "chain_id": DEFAULT_CHAIN_ID},
            "current": load_active_cometbft_configuration(service),
            "pending": _read_object(_pending_path(service)),
            "paths": {},
        }
    executor_available = getattr(service, "consensus_installation_executor", None) is not None
    pending = _read_object(_pending_path(service))
    active = load_active_cometbft_configuration(service)
    return {
        "profile": "operator-cometbft-install-v1",
        "available": executor_available,
        "reason": None if executor_available else "Root-owned runtime broker is not configured",
        "broker": {
            "configured": executor_available,
            "dispatcher": _dispatcher_path() if executor_available else None,
            "socket_configured": bool(os.getenv("AIDN_PROVIDER_RUNTIME_BROKER_SOCKET")),
        },
        "defaults": {
            "mode": plan.mode,
            "version": plan.version,
            "chain_id": plan.chain_id,
            "moniker": plan.moniker,
            "rpc_host": plan.rpc_host,
            "rpc_port": plan.rpc_port,
            "p2p_host": plan.p2p_host,
            "p2p_port": plan.p2p_port,
            "external_address": plan.external_address,
            "seeds": plan.seeds,
            "persistent_peers": plan.persistent_peers,
            "pex": True,
            "abci_host": plan.abci_host,
            "abci_port": plan.abci_port,
        },
        "current": active,
        "pending": pending,
        "paths": {"home": plan.home, "binary": plan.binary_path, "service": plan.service_name},
        "steps": [
            {"id": "preflight", "label": "Review bounded settings", "status": "ready"},
            {"id": "install", "label": "Install CometBFT runtime", "status": "pending"},
            {
                "id": "apply",
                "label": "Apply and restart Hypervisor",
                "status": "pending" if pending is None else "ready",
            },
        ],
    }


def install_cometbft_from_dashboard(service: Any, values: Mapping[str, object]) -> dict[str, Any]:
    plan, argv = build_cometbft_install_argv(service, values)
    result = _executor(service).invoke(argv=argv, timeout_seconds=3600)
    returncode, stdout, stderr = _result_detail(result)
    if returncode != 0:
        detail = stderr.splitlines()[0][:512] if stderr.strip() else "installer returned a non-zero status"
        raise RuntimeError(f"CometBFT installation failed: {detail}")
    pending_path = _pending_path(service)
    if pending_path is None:
        raise ValueError("Persistent Hypervisor state is required for CometBFT configuration")
    pending = plan.as_config()
    _atomic_write(pending_path, pending)
    return {
        "status": "installed_pending_apply",
        "pending": pending,
        "installer": {"returncode": returncode, "stdout": stdout, "stderr": stderr},
        "next_action": "apply",
    }


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise urllib.error.HTTPError(
            request.full_url,
            code,
            "redirects are not allowed for a consensus source",
            headers,
            fp,
        )


def _validated_source_rpc(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("A source RPC endpoint is required to join an existing network")
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port or 26657
    except ValueError as error:
        raise ValueError("Source RPC endpoint is invalid") from error
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise ValueError("Source RPC must be an unauthenticated HTTP(S) endpoint")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Source RPC must not contain a path, query or fragment")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError("Source RPC must use a private or loopback IP address") from error
    if not (address.is_private or address.is_loopback or address.is_link_local):
        raise ValueError("Source RPC must use a private or loopback IP address")
    if not 1 <= port <= 65535:
        raise ValueError("Source RPC port must be an integer from 1 to 65535")
    authority = f"[{host}]" if address.version == 6 else host
    return urlunsplit((parsed.scheme, f"{authority}:{port}", "", "", ""))


def _fetch_source_json(source_rpc: str, path: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{source_rpc}{path}",
        headers={"Accept": "application/json", "User-Agent": "AiDN-Hypervisor/1"},
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=_REMOTE_RPC_TIMEOUT_SECONDS) as response:
            payload = response.read(_MAX_REMOTE_GENESIS_BYTES + 1)
    except (OSError, urllib.error.URLError) as error:
        raise ValueError(f"Source RPC {source_rpc} could not be reached") from error
    if len(payload) > _MAX_REMOTE_GENESIS_BYTES:
        raise ValueError("Source genesis response exceeds the reviewed size limit")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Source RPC returned invalid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("Source RPC response must be a JSON object")
    return value


def _fetch_source_genesis(source_rpc: object, expected_chain_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    endpoint = _validated_source_rpc(source_rpc)
    status_payload = _fetch_source_json(endpoint, "/status")
    status_result = status_payload.get("result")
    if not isinstance(status_result, Mapping):
        raise ValueError("Source RPC status response is missing result")
    node_info = status_result.get("node_info")
    sync_info = status_result.get("sync_info")
    if not isinstance(node_info, Mapping):
        raise ValueError("Source RPC status response is missing node information")
    source_chain_id = str(node_info.get("network") or "").strip()
    if source_chain_id != expected_chain_id:
        raise ValueError(
            f"Source RPC belongs to chain {source_chain_id!r}, not {expected_chain_id!r}"
        )
    genesis_payload = _fetch_source_json(endpoint, "/genesis")
    genesis_result = genesis_payload.get("result")
    if not isinstance(genesis_result, Mapping):
        raise ValueError("Source RPC genesis response is missing result")
    genesis = genesis_result.get("genesis")
    if not isinstance(genesis, dict):
        raise ValueError("Source RPC did not return a CometBFT genesis object")
    if str(genesis.get("chain_id") or "").strip() != expected_chain_id:
        raise ValueError("Source genesis Chain ID does not match the requested network")
    sync_info = sync_info if isinstance(sync_info, Mapping) else {}
    canonical_genesis = json.dumps(genesis, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return genesis, {
        "rpc": endpoint,
        "node_id": str(node_info.get("id") or ""),
        "moniker": str(node_info.get("moniker") or ""),
        "chain_id": expected_chain_id,
        "height": str(sync_info.get("latest_block_height") or ""),
        "genesis_sha256": hashlib.sha256(canonical_genesis).hexdigest(),
    }


def _reset_cometbft_data(home: Path, genesis: Mapping[str, Any]) -> None:
    home = home.expanduser().resolve()
    config = home / "config"
    data = home / "data"
    genesis_path = config / "genesis.json"
    if not config.is_dir() or not genesis_path.is_file():
        raise ValueError("CometBFT home is not initialized; use the normal install flow first")
    if data.is_symlink() or config.is_symlink():
        raise ValueError("CometBFT home cannot contain symlinked state directories")
    if data.exists():
        shutil.rmtree(data)
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    # CometBFT requires this file even for a non-validator node.  A reconnect
    # intentionally discards the old signing history, so start from the
    # canonical empty state instead of letting user-systemd restart-loop on a
    # missing file.
    _atomic_write(
        data / "priv_validator_state.json",
        {"height": "0", "round": -1, "step": 0},
    )
    addrbook = config / "addrbook.json"
    if addrbook.exists() or addrbook.is_symlink():
        addrbook.unlink()
    _atomic_write(genesis_path, genesis)


def reconnect_cometbft_from_dashboard(service: Any, values: Mapping[str, object]) -> dict[str, Any]:
    """Join an existing private network by replacing only local CometBFT state.

    The existing local genesis and blockstore are intentionally discarded after
    the operator has acknowledged the reset. Hypervisor state, models and
    provider data remain outside the reset boundary. Reconnect currently uses a
    non-validator profile so a fresh host cannot accidentally claim validator
    power that is not present in the source genesis.
    """

    if str(values.get("mode") or "").strip() != "non_validator":
        raise ValueError("Reconnect to an existing network currently requires non_validator mode")
    if values.get("acknowledge_reset") is not True:
        raise ValueError("Reconnect requires explicit acknowledgement of the local consensus reset")
    if _read_object(_pending_path(service)) is not None:
        raise ValueError("Apply or finish the pending CometBFT configuration before reconnecting")
    plan, _ = build_cometbft_install_argv(service, values)
    genesis, source = _fetch_source_genesis(values.get("source_rpc"), plan.chain_id)
    from aidn_hypervisor.operator_cometbft import control_managed_cometbft

    control_managed_cometbft(service, "stop")
    _reset_cometbft_data(Path(plan.home), genesis)
    installed = install_cometbft_from_dashboard(service, values)
    applied = apply_pending_cometbft_configuration(service)
    return {
        "status": "reconnected",
        "source": source,
        "reset": {
            "scope": "cometbft_data_and_genesis",
            "home": plan.home,
            "hypervisor_state_preserved": True,
            "models_preserved": True,
        },
        "installation": installed,
        "applied": applied,
        "next_action": "refresh",
    }


def _schedule_restart() -> bool:
    if not _env_bool("AIDN_HYPERVISOR_RESTART_ON_BIND_CHANGE"):
        return False

    def terminate_after_response() -> None:
        os.kill(os.getpid(), signal.SIGTERM)

    timer = threading.Timer(0.35, terminate_after_response)
    timer.daemon = True
    timer.start()
    return True


def _restart_managed_cometbft(service: Any) -> bool:
    """Restart the configured CometBFT unit when applying a live update.

    The Hypervisor process may not yet have loaded the newly written active
    configuration, but it still owns the allowlisted service identity.  A
    direct user-systemd restart makes peer changes effective immediately while
    keeping the existing Hypervisor restart scheduling semantics intact.
    """

    consensus = getattr(service, "consensus_service", None)
    if consensus is None or not getattr(getattr(consensus, "config", None), "managed_service_name", None):
        return False
    try:
        from aidn_hypervisor.operator_cometbft import control_managed_cometbft

        control_managed_cometbft(service, "restart")
    except (RuntimeError, ValueError):
        return False
    return True


def apply_pending_cometbft_configuration(service: Any) -> dict[str, Any]:
    pending_path = _pending_path(service)
    active_path = _config_path(service)
    pending = _read_object(pending_path)
    if pending is None or active_path is None:
        raise ValueError("No pending CometBFT installation is available")
    # Re-validate before making the active file visible. This also keeps a
    # hand-edited pending file from becoming a ConsensusService config.
    plan = build_cometbft_install_plan(service, pending)
    active = plan.as_config()
    _atomic_write(active_path, active)
    try:
        pending_path.unlink()
    except FileNotFoundError:
        pass
    cometbft_restarted = _restart_managed_cometbft(service)
    restart_scheduled = _schedule_restart()
    return {
        "status": "applied",
        "active": active,
        "restart_required": True,
        "cometbft_restarted": cometbft_restarted,
        "restart_scheduled": restart_scheduled,
        "next_action": (
            "refresh"
            if restart_scheduled
            else "refresh_consensus"
            if cometbft_restarted
            else "restart_hypervisor_manually"
        ),
    }
