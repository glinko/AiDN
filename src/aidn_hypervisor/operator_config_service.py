"""Safe operator-profile editing for the paired Dashboard.

The TOML profile is intentionally a narrow projection of the process
environment.  It is useful for ports, feature switches, provider URLs, and
other operator-owned settings, while credentials remain in Secret Manager and
host identity paths remain controlled by the bootstrap wrapper.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from aidn_hypervisor.config import (
    CONFIG_FILE_ENV,
    MAX_CONFIG_BYTES,
    OperatorConfigError,
    config_sha256,
    is_read_only_config_key,
    is_secret_config_key,
    read_operator_config_values,
    render_operator_config,
    resolve_operator_config_path,
    write_operator_config,
)


class OperatorConfigConflict(OperatorConfigError):
    """The browser edited a revision that is no longer current."""


class OperatorConfigService:
    """Read, validate, and atomically apply one operator TOML profile."""

    def __init__(
        self,
        *,
        path: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
        restart_callback: Callable[[], bool | None] | None = None,
        apply_callback: Callable[[Mapping[str, str]], None] | None = None,
        restart_supported: bool | None = None,
    ) -> None:
        self._environment = dict(os.environ if environ is None else environ)
        self._path = resolve_operator_config_path(path, environ=self._environment)
        self._restart_callback = restart_callback
        self._apply_callback = apply_callback
        self._restart_supported = (
            bool(restart_callback)
            if restart_supported is None
            else restart_supported
        )

    @property
    def path(self) -> Path | None:
        return self._path

    def _environment_values(self) -> dict[str, str]:
        return {
            key: str(value)
            for key, value in self._environment.items()
            if key.startswith("AIDN_")
            and key != CONFIG_FILE_ENV
        }

    def _current_values(self) -> dict[str, str]:
        if self._path is not None and self._path.is_file():
            return read_operator_config_values(self._path)
        return self._environment_values()

    def _public_values(self, values: Mapping[str, str]) -> dict[str, str]:
        return {
            key: value
            for key, value in values.items()
            if key.startswith("AIDN_") and not is_secret_config_key(key)
        }

    def _hidden_keys(self, values: Mapping[str, str]) -> list[str]:
        return sorted(key for key in values if is_secret_config_key(key))

    def _read_hash(self) -> str | None:
        return config_sha256(self._path) if self._path is not None else None

    def read_payload(self) -> dict[str, object]:
        if self._path is None:
            return {
                "status": "unavailable",
                "path": None,
                "format": "toml",
                "text": "",
                "sha256": None,
                "hidden_keys": [],
                "read_only_keys": [],
                "restart_supported": False,
                "restart_scheduled": False,
                "last_modified": None,
            }
        current = self._current_values()
        public = self._public_values(current)
        modified = None
        if self._path.is_file():
            modified = datetime.fromtimestamp(
                self._path.stat().st_mtime,
                tz=UTC,
            ).isoformat()
        return {
            "status": "configured" if self._path.is_file() else "missing",
            "path": str(self._path),
            "format": "toml",
            "text": render_operator_config(public),
            "sha256": self._read_hash(),
            "hidden_keys": self._hidden_keys(current),
            "read_only_keys": sorted(
                key for key in public if is_read_only_config_key(key)
            ),
            "restart_supported": self._restart_supported,
            "restart_scheduled": False,
            "last_modified": modified,
        }

    def _validation(self, text: str) -> dict[str, object]:
        errors: list[str] = []
        warnings: list[str] = []
        try:
            if len(text.encode("utf-8")) > MAX_CONFIG_BYTES:
                raise OperatorConfigError(
                    f"configuration text exceeds {MAX_CONFIG_BYTES} bytes"
                )
            # Importing this private parser keeps the loader and Dashboard on
            # one TOML/schema implementation without exposing it publicly.
            from aidn_hypervisor.config import _parse_text

            candidate = _parse_text(text, dashboard=True)
            current = self._current_values()
            for key in candidate:
                if is_secret_config_key(key):
                    raise OperatorConfigError(
                        f"{key} is managed by Secret Manager and cannot be edited here"
                    )
                if is_read_only_config_key(key) and key in current and candidate[key] != current[key]:
                    raise OperatorConfigError(f"{key} is protected by the operator bootstrap")
            changed = sorted(
                key
                for key in set(candidate) | set(self._public_values(current))
                if not is_secret_config_key(key)
                and candidate.get(key) != self._public_values(current).get(key)
            )
            if changed:
                warnings.append("Applying a changed profile restarts the Hypervisor service.")
            hidden = self._hidden_keys(current)
            if hidden:
                warnings.append("Secret values remain hidden in Secret Manager and are not changed by this editor.")
            return {
                "valid": True,
                "errors": errors,
                "warnings": warnings,
                "changed_keys": changed,
                "restart_required": bool(changed),
                "read_only_keys": sorted(
                    key for key in set(candidate) | set(current) if is_read_only_config_key(key)
                ),
            }
        except OperatorConfigError as error:
            errors.append(str(error))
            return {
                "valid": False,
                "errors": errors,
                "warnings": warnings,
                "changed_keys": [],
                "restart_required": False,
                "read_only_keys": sorted(key for key in self._current_values() if is_read_only_config_key(key)),
            }

    def validate(self, text: str) -> dict[str, object]:
        return self._validation(text)

    def save(
        self,
        text: str,
        *,
        expected_sha256: str | None = None,
        apply: bool = False,
    ) -> dict[str, object]:
        if self._path is None:
            raise OperatorConfigError("operator configuration is unavailable for this process")
        validation = self._validation(text)
        if not validation["valid"]:
            raise OperatorConfigError(str(validation["errors"][0]))
        current_hash = self._read_hash()
        if expected_sha256 is not None and expected_sha256 != current_hash:
            raise OperatorConfigConflict(
                "the operator configuration changed since it was loaded; reload it before saving"
            )
        from aidn_hypervisor.config import _parse_text

        candidate = _parse_text(text, dashboard=True)
        current = self._current_values()
        # Protected paths and hidden credentials are carried forward even when
        # the browser receives a redacted document that cannot contain them.
        merged = dict(candidate)
        for key, value in current.items():
            if (
                not key.startswith("AIDN_")
                or is_secret_config_key(key)
                or is_read_only_config_key(key)
            ):
                merged.setdefault(key, value)
        write_operator_config(self._path, merged)
        restart_scheduled = False
        if apply and self._apply_callback is not None:
            self._apply_callback(merged)
        if apply and self._restart_callback is not None:
            restart_scheduled = bool(self._restart_callback())
        payload = self.read_payload()
        payload.update(
            {
                "status": "accepted",
                "changed_keys": validation["changed_keys"],
                "restart_required": bool(validation["restart_required"]),
                "restart_scheduled": restart_scheduled,
                "warnings": validation["warnings"],
            }
        )
        return payload


__all__ = ["OperatorConfigConflict", "OperatorConfigService"]
