"""Operator read model and bounded local controls for CometBFT.

The dashboard may inspect consensus state and control only the user-systemd
unit explicitly configured by the Hypervisor.  It never accepts a binary path,
home path, unit name, or arbitrary shell command from the browser.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from aidn_hypervisor.operator_cometbft_install import load_active_cometbft_configuration

_ALLOWED_ACTIONS = frozenset({"start", "stop", "restart"})
_SERVICE_NAME = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")


def _safe_endpoint(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https", "tcp", "tcp4", "tcp6"} or not parsed.netloc:
        return ""
    if parsed.username or parsed.password:
        return ""
    try:
        # Accessing .port validates malformed numeric ports without exposing
        # the original value in an operator read model.
        _ = parsed.port
    except ValueError:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _service_name(consensus: object) -> str | None:
    config = getattr(consensus, "config", None)
    value = str(getattr(config, "managed_service_name", "") or "").strip()
    return value if _SERVICE_NAME.fullmatch(value) else None


def _peer_items(value: object) -> list[str]:
    raw = str(value or "")
    items: list[str] = []
    for candidate in re.split(r"[,\n\r]+", raw):
        item = candidate.strip()
        if item and item not in items:
            items.append(item)
    return items[:32]


def _network_payload(service: object) -> dict[str, object]:
    active = load_active_cometbft_configuration(service) or {}
    seeds = _peer_items(active.get("seeds"))
    persistent_peers = _peer_items(active.get("persistent_peers"))
    return {
        "p2p_host": str(active.get("p2p_host") or "127.0.0.1"),
        "p2p_port": active.get("p2p_port") or 26656,
        "external_address": str(active.get("external_address") or ""),
        "pex": active.get("pex") is not False,
        "seeds": seeds,
        "persistent_peers": persistent_peers,
        "configured_sources": [
            source
            for source, configured in (
                ("persistent_peers", bool(persistent_peers)),
                ("seeds", bool(seeds)),
                ("pex", active.get("pex") is not False),
            )
            if configured
        ],
    }


def build_operator_cometbft_payload(service) -> dict:
    """Return a non-secret CometBFT control/readiness projection."""

    consensus = getattr(service, "consensus_service", None)
    if consensus is None:
        return {
            "profile": "operator-cometbft-v1",
            "configured": False,
            "enabled": False,
            "mode": "disabled",
            "node_id": None,
            "chain_id": None,
            "rpc_endpoint": "",
            "rpc": {"available": False, "reason": "consensus_service_unavailable"},
            "network": _network_payload(service),
            "management": {"managed": False, "service": None, "control_supported": False},
            "metrics": {},
            "protocol_authority": {},
        }

    config = getattr(consensus, "config", None)
    try:
        status = consensus.status()
    except Exception as error:  # pragma: no cover - defensive control-plane boundary
        status = {
            "enabled": bool(getattr(consensus, "is_enabled", False)),
            "mode": str(getattr(getattr(config, "mode", None), "value", "unknown")),
            "node_id": getattr(config, "node_id", None),
            "chain_id": getattr(config, "chain_id", None),
            "rpc": {"available": False, "error_type": type(error).__name__},
            "management": {},
            "metrics": {},
            "protocol_authority": {},
        }

    service_name = _service_name(consensus)
    management_payload = {
        "managed": service_name is not None,
        "service": service_name,
        "control_supported": service_name is not None,
    }
    rpc = status.get("rpc") if isinstance(status, Mapping) else {}
    metrics = status.get("metrics") if isinstance(status, Mapping) else {}
    authority = status.get("protocol_authority") if isinstance(status, Mapping) else {}
    return {
        "profile": "operator-cometbft-v1",
        "configured": True,
        "enabled": bool(status.get("enabled", False)) if isinstance(status, Mapping) else False,
        "mode": str(status.get("mode") or getattr(getattr(config, "mode", None), "value", "unknown"))
        if isinstance(status, Mapping)
        else "unknown",
        "node_id": status.get("node_id") if isinstance(status, Mapping) else getattr(config, "node_id", None),
        "chain_id": status.get("chain_id") if isinstance(status, Mapping) else getattr(config, "chain_id", None),
        "rpc_endpoint": _safe_endpoint(getattr(config, "cometbft_endpoint", "")),
        "rpc": dict(rpc) if isinstance(rpc, Mapping) else {"available": False},
        "network": _network_payload(service),
        "management": management_payload,
        "metrics": dict(metrics) if isinstance(metrics, Mapping) else {},
        "protocol_authority": dict(authority) if isinstance(authority, Mapping) else {},
    }


def control_managed_cometbft(
    service,
    action: str,
    *,
    runner=None,
    timeout_seconds: int = 20,
) -> dict:
    """Run one allowlisted systemd action against the configured unit."""

    normalized_action = str(action or "").strip().lower()
    if normalized_action not in _ALLOWED_ACTIONS:
        raise ValueError("CometBFT action must be start, stop or restart")
    consensus = getattr(service, "consensus_service", None)
    service_name = _service_name(consensus) if consensus is not None else None
    if service_name is None:
        raise ValueError("CometBFT is not managed by a configured user-systemd unit")
    if timeout_seconds < 1:
        raise ValueError("CometBFT control timeout must be positive")

    execute = runner or subprocess.run
    environment = os.environ.copy()
    runtime_dir = environment.get("XDG_RUNTIME_DIR", "").strip()
    if runtime_dir and "DBUS_SESSION_BUS_ADDRESS" not in environment:
        environment["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime_dir}/bus"
    try:
        completed = execute(
            ["systemctl", "--user", normalized_action, service_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"CometBFT {normalized_action} could not be controlled") from error
    if int(getattr(completed, "returncode", 1)) != 0:
        detail = str(getattr(completed, "stderr", "") or "").strip().splitlines()
        suffix = f": {detail[0][:240]}" if detail else ""
        raise RuntimeError(f"CometBFT {normalized_action} failed{suffix}")
    return {
        "status": "ok",
        "action": normalized_action,
        "service": service_name,
    }


def allowed_cometbft_actions() -> Sequence[str]:
    """Expose the action names without exposing mutable module state."""

    return tuple(sorted(_ALLOWED_ACTIONS))
