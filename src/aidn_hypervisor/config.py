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

import os
import tomllib
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE_ENV = "AIDN_CONFIG_FILE"
_ALLOWED_PREFIXES = ("AIDN_", "VITE_")


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


def _read_values(path: Path) -> dict[str, str]:
    try:
        with path.open("rb") as stream:
            document = tomllib.load(stream)
    except OSError as exc:
        raise OperatorConfigError(f"could not read AIDN_CONFIG_FILE {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise OperatorConfigError(f"invalid TOML in AIDN_CONFIG_FILE {path}: {exc}") from exc

    raw_values = document.get("env")
    if not isinstance(raw_values, dict):
        raise OperatorConfigError("AIDN_CONFIG_FILE must contain an [env] table")

    values: dict[str, str] = {}
    for key, value in raw_values.items():
        if not isinstance(key, str) or not key.startswith(_ALLOWED_PREFIXES):
            raise OperatorConfigError(
                f"unsupported configuration key {key!r}; use an AIDN_* or VITE_* key"
            )
        if key == CONFIG_FILE_ENV:
            raise OperatorConfigError("AIDN_CONFIG_FILE cannot be set inside the config file")
        values[key] = _format_value(value, key=key)
    return values


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
    if configured_path is None or not str(configured_path).strip():
        return OperatorConfigLoadResult(path=None)

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
    "OperatorConfigError",
    "OperatorConfigLoadResult",
    "load_operator_config",
    "redact_environment",
]
