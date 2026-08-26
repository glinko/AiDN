"""Load the optional, operator-owned AiDN configuration file.

The service historically accepted ``AIDN_*`` values directly from the process
environment.  That remains the deployment contract.  This module adds an
optional TOML file selected by ``AIDN_CONFIG_FILE`` and fills only variables
that are not already present in the environment.  Existing systemd wrappers,
CLI flags, and dashboard-applied state therefore keep their precedence.

The file deliberately contains an ``[env]`` table instead of a second nested
configuration model.  Every key maps to the same environment variable used by
the running service, which keeps the file auditable and avoids two competing
configuration schemas.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import tomllib
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

CONFIG_FILE_ENV = "AIDN_CONFIG_FILE"
DEFAULT_CONFIG_FILENAME = "operator-config.toml"
MAX_CONFIG_BYTES = 128 * 1024
_ALLOWED_PREFIXES = ("AIDN_", "VITE_")
_DASHBOARD_ALLOWED_PREFIX = "AIDN_"
_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+$")
_SECRET_MARKERS = (
    "TOKEN",
    "PRIVATE_KEY",
    "MASTER_KEY",
    "PASSWORD",
    "CREDENTIAL",
    "SIGNING_KEY",
    "API_KEY",
)
_READ_ONLY_KEYS = frozenset(
    {
        CONFIG_FILE_ENV,
        "AIDN_HYPERVISOR_STATE_PATH",
        "AIDN_HYPERVISOR_BUNDLES_PATH",
        "AIDN_HYPERVISOR_MODEL_STORE_PATH",
        "AIDN_HYPERVISOR_BIND_HOST_PATH",
        "AIDN_SECRET_MANAGER_PATH",
        "AIDN_PROVIDER_RUNTIME_DISPATCHER",
        "AIDN_PROVIDER_RUNTIME_BROKER_SOCKET",
        "AIDN_REGISTRY_REPLICATION_CONFIG",
        "AIDN_REMOTE_TRUST_ANCHOR_CONFIG",
        "AIDN_COMETBFT_FINALITY_CONFIG",
        "AIDN_PROTOCOL_AUTHORITY_POLICY_PATH",
        "AIDN_NETWORK_PROFILE_PATH",
        "AIDN_NETWORK_PROFILE_SIGNERS_PATH",
        "AIDN_TESTNET_PARTICIPATION_PROGRAM_PATH",
        # The software updater is deliberately bound to the reviewed
        # bootstrap checkout and tooling. These values are not operator
        # editable from the TOML editor.
        "AIDN_UPDATE_REPOSITORY_URL",
        "AIDN_UPDATE_REF",
        "AIDN_UPDATE_NODE_ROOT",
        "AIDN_UPDATE_TOOLING_DIR",
        "AIDN_UV_BIN",
    }
)


class OperatorConfigError(ValueError):
    """Raised when an operator configuration file cannot be loaded safely."""


@dataclass(frozen=True)
class OperatorConfigLoadResult:
    """Describe one configuration-file load without exposing secret values."""

    path: Path | None
    applied: tuple[str, ...] = ()
    preserved: tuple[str, ...] = ()


def _format_value(value: object, *, key: str) -> str:
    """Convert a TOML scalar to the string representation expected by env vars."""

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        # Useful for comma-separated scope lists while keeping TOML readable.
        return ",".join(value)
    raise OperatorConfigError(
        f"{key} must be a TOML string, number, boolean, or list of strings"
    )


def is_secret_config_key(key: str) -> bool:
    """Return whether a configuration key may contain a credential.

    Secret material belongs in the encrypted Secret Manager.  A path to that
    manager is safe to show, so it is deliberately not classified as secret.
    The predicate is intentionally conservative for values that may be copied
    into logs or a browser response.
    """

    if key == "AIDN_SECRET_MANAGER_PATH" or key.endswith("_PATH"):
        return False
    upper = key.upper()
    return any(marker in upper for marker in _SECRET_MARKERS) or "SECRET" in upper


def is_read_only_config_key(key: str) -> bool:
    return key in _READ_ONLY_KEYS


def resolve_operator_config_path(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """Resolve the canonical profile path without creating it."""

    values = os.environ if environ is None else environ
    configured = path if path is not None else values.get(CONFIG_FILE_ENV)
    if configured is not None and str(configured).strip():
        return Path(str(configured)).expanduser()
    state_path = values.get("AIDN_HYPERVISOR_STATE_PATH")
    if state_path and str(state_path).strip():
        return Path(str(state_path)).expanduser().with_name(DEFAULT_CONFIG_FILENAME)
    return None


def _validate_scalar_text(key: str, value: str) -> None:
    if "\x00" in value or any(ord(character) < 32 and character not in "\t\r\n" for character in value):
        raise OperatorConfigError(f"{key} contains a control character")
    if "\t" in value or "\n" in value or "\r" in value:
        raise OperatorConfigError(f"{key} must be a single-line value")
    if key.endswith("_PORT") or key in {"AIDN_HYPERVISOR_API_PORT", "AIDN_MCP_REMOTE_PORT"}:
        try:
            port = int(value)
        except ValueError as exc:
            raise OperatorConfigError(f"{key} must be an integer port") from exc
        if not 1 <= port <= 65535:
            raise OperatorConfigError(f"{key} must be between 1 and 65535")
    if "URL" in key or key.endswith("_ENDPOINT"):
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https", "tcp", "unix"} or not parsed.netloc and parsed.scheme != "unix":
            raise OperatorConfigError(f"{key} must be an http, https, tcp, or unix URL")
        if parsed.username or parsed.password:
            raise OperatorConfigError(f"{key} must not contain embedded credentials")
    if key == "AIDN_HYPERVISOR_API_HOST" and value not in {"127.0.0.1", "0.0.0.0"}:
        raise OperatorConfigError("AIDN_HYPERVISOR_API_HOST must be 127.0.0.1 or 0.0.0.0")


def _parse_document(document: object, *, dashboard: bool) -> dict[str, str]:
    if not isinstance(document, dict):
        raise OperatorConfigError("configuration document must be a TOML table")
    raw_values = document.get("env")
    if not isinstance(raw_values, dict):
        raise OperatorConfigError("AIDN_CONFIG_FILE must contain an [env] table")

    values: dict[str, str] = {}
    for key, value in raw_values.items():
        if not isinstance(key, str) or not _KEY_PATTERN.fullmatch(key):
            raise OperatorConfigError(f"unsupported configuration key {key!r}")
        if dashboard and not key.startswith(_DASHBOARD_ALLOWED_PREFIX):
            raise OperatorConfigError(f"{key} is not an editable AIDN_* setting")
        if not key.startswith(_ALLOWED_PREFIXES):
            raise OperatorConfigError(
                f"unsupported configuration key {key!r}; use an AIDN_* or VITE_* key"
            )
        if key == CONFIG_FILE_ENV:
            raise OperatorConfigError("AIDN_CONFIG_FILE cannot be set inside the config file")
        rendered = _format_value(value, key=key)
        _validate_scalar_text(key, rendered)
        values[key] = rendered
    return values


def _parse_text(text: str, *, dashboard: bool = False) -> dict[str, str]:
    if not isinstance(text, str):
        raise OperatorConfigError("configuration text must be a string")
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_CONFIG_BYTES:
        raise OperatorConfigError(f"configuration text exceeds {MAX_CONFIG_BYTES} bytes")
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise OperatorConfigError(f"invalid TOML: {exc}") from exc
    return _parse_document(document, dashboard=dashboard)


def render_operator_config(values: Mapping[str, str], *, include_header: bool = True) -> str:
    """Render a deterministic, shell-safe TOML profile.

    Values are quoted as JSON strings.  TOML accepts JSON string escapes, and
    keeping one representation avoids accidentally changing environment
    semantics when a list-valued setting is edited in the Dashboard.
    """

    lines = []
    if include_header:
        lines.extend(
            [
                "# AiDN operator configuration profile",
                "# Generated by the Dashboard. Secrets stay in Secret Manager.",
                "# Edit only AIDN_* values; changes to protected paths are rejected.",
                "",
            ]
        )
    lines.append("[env]")
    for key in sorted(values):
        if not _KEY_PATTERN.fullmatch(key) or not key.startswith(_ALLOWED_PREFIXES):
            raise OperatorConfigError(f"unsupported configuration key {key!r}")
        _validate_scalar_text(key, str(values[key]))
        lines.append(f"{key} = {json.dumps(str(values[key]), ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def config_sha256(path: str | Path) -> str | None:
    target = Path(path)
    try:
        digest = hashlib.sha256()
        with target.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except FileNotFoundError:
        return None


def write_operator_config(path: str | Path, values: Mapping[str, str]) -> Path:
    """Atomically write a host-only profile and retain the previous revision."""

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    content = render_operator_config(values)
    temporary: str | None = None
    try:
        if target.exists():
            backup = target.with_name(f"{target.name}.bak")
            backup.write_bytes(target.read_bytes())
            os.chmod(backup, 0o600)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}-", dir=target.parent)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        return target
    except BaseException:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        raise


def write_operator_config_from_environment(
    path: str | Path,
    environ: Mapping[str, str] | None = None,
) -> Path:
    environment = os.environ if environ is None else environ
    values = {
        key: str(value)
        for key, value in environment.items()
        if key.startswith("AIDN_")
        and key != CONFIG_FILE_ENV
        and not is_secret_config_key(key)
    }
    return write_operator_config(path, values)


def _read_values(path: Path) -> dict[str, str]:
    try:
        with path.open("rb") as stream:
            document = tomllib.load(stream)
    except OSError as exc:
        raise OperatorConfigError(f"could not read AIDN_CONFIG_FILE {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise OperatorConfigError(f"invalid TOML in AIDN_CONFIG_FILE {path}: {exc}") from exc

    return _parse_document(document, dashboard=False)


def read_operator_config_values(path: str | Path) -> dict[str, str]:
    return _read_values(Path(path).expanduser())


def load_operator_config(
    path: str | Path | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> OperatorConfigLoadResult:
    """Load an optional TOML profile into ``environ``.

    Environment values always win.  A missing path is an error when the
    operator explicitly selected it; no file is loaded when neither ``path``
    nor ``AIDN_CONFIG_FILE`` is set.  The function is idempotent and safe to
    call at every process entry point.
    """

    target_environment = os.environ if environ is None else environ
    configured_path = path if path is not None else target_environment.get(CONFIG_FILE_ENV)
    config_path: Path | None = None
    values: dict[str, str] = {}
    if configured_path is not None and str(configured_path).strip():
        config_path = Path(str(configured_path)).expanduser()
        if not config_path.is_file():
            raise OperatorConfigError(f"AIDN_CONFIG_FILE does not exist: {config_path}")
        values = _read_values(config_path)
    applied: list[str] = []
    preserved: list[str] = []
    for key, value in values.items():
        if key in target_environment:
            preserved.append(key)
        else:
            target_environment[key] = value
            applied.append(key)
    network_profile_path = target_environment.get("AIDN_NETWORK_PROFILE_PATH")
    if network_profile_path:
        from aidn_hypervisor.network_profile import (
            apply_network_profile_environment,
            load_network_profile,
            load_network_profile_signers,
            verify_network_profile,
        )

        trusted_signers = load_network_profile_signers(
            target_environment.get("AIDN_NETWORK_PROFILE_SIGNERS_PATH")
        )
        verification = verify_network_profile(
            network_profile_path,
            trusted_profile_signers=trusted_signers,
        )
        if not verification.valid:
            raise OperatorConfigError(
                "AIDN_NETWORK_PROFILE_PATH verification failed: "
                + ",".join(verification.errors)
            )
        applied.extend(
            apply_network_profile_environment(
                load_network_profile(network_profile_path),
                environ=target_environment,
            )
        )
    return OperatorConfigLoadResult(
        path=config_path,
        applied=tuple(sorted(applied)),
        preserved=tuple(sorted(preserved)),
    )


def redact_environment(values: Mapping[str, str]) -> dict[str, str]:
    """Return a diagnostic environment with secret-looking values redacted."""

    redacted: dict[str, str] = {}
    for key, value in values.items():
        if any(marker in key.upper() for marker in ("TOKEN", "SECRET", "PRIVATE_KEY", "PASSWORD")):
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value
    return redacted


__all__ = [
    "CONFIG_FILE_ENV",
    "DEFAULT_CONFIG_FILENAME",
    "MAX_CONFIG_BYTES",
    "OperatorConfigError",
    "OperatorConfigLoadResult",
    "config_sha256",
    "is_read_only_config_key",
    "is_secret_config_key",
    "load_operator_config",
    "read_operator_config_values",
    "redact_environment",
    "render_operator_config",
    "resolve_operator_config_path",
    "write_operator_config",
    "write_operator_config_from_environment",
]
