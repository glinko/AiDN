"""Safe, operator-approved software updates for a bootstrapped Hypervisor.

The Dashboard never supplies a command, checkout path, repository URL, or
revision.  Those values come from the reviewed bootstrap wrapper.  This
service only exposes a small check/apply state machine and runs a fixed Git /
uv / dashboard-build sequence against the current checkout.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_UPDATE_REPOSITORY = "https://github.com/glinko/AiDN.git"
DEFAULT_UPDATE_REF = "main"
UPDATE_STATE_FILENAME = "software-update.json"
GENERATED_DASHBOARD_PATH = "src/aidn_hypervisor/static/react-dashboard"
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_COMMIT = re.compile(r"^[0-9a-fA-F]{40}$")
_MAX_OUTPUT = 64 * 1024


class OperatorUpdateError(ValueError):
    """Raised when a software update cannot be safely checked or applied."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _short_error(error: str) -> str:
    return error.strip()[:2_000] or "software update failed"


class OperatorUpdateService:
    """Plan and apply one reviewed checkout update at a time.

    ``restart_callback`` is deliberately supplied by the host wiring.  The
    normal bootstrap callback terminates the current process after the update
    state is durably written; systemd then starts the newly checked-out code.
    """

    def __init__(
        self,
        *,
        repository_path: str | Path | None = None,
        state_path: str | Path | None = None,
        repository_url: str | None = None,
        ref: str | None = None,
        node_root: str | Path | None = None,
        tooling_dir: str | Path | None = None,
        uv_path: str | Path | None = None,
        restart_callback: Callable[[], bool | None] | None = None,
        run_tooling: bool = True,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        inferred_repo = Path(__file__).resolve().parents[2]
        self._repository_path = Path(
            repository_path or os.getenv("AIDN_UPDATE_REPOSITORY_PATH") or inferred_repo
        ).expanduser().resolve()
        if state_path is None:
            configured_state = os.getenv("AIDN_HYPERVISOR_STATE_PATH")
            state_path = (
                Path(configured_state).expanduser().with_name(UPDATE_STATE_FILENAME)
                if configured_state
                else self._repository_path / ".aidn" / UPDATE_STATE_FILENAME
            )
        self._state_path = Path(state_path).expanduser()
        self._repository_url = (
            repository_url
            or os.getenv("AIDN_UPDATE_REPOSITORY_URL")
            or DEFAULT_UPDATE_REPOSITORY
        ).strip()
        self._ref = (ref or os.getenv("AIDN_UPDATE_REF") or DEFAULT_UPDATE_REF).strip()
        self._node_root = Path(
            node_root
            or os.getenv("AIDN_UPDATE_NODE_ROOT")
            or self._state_path.parent / "tooling" / "node"
        ).expanduser()
        self._tooling_dir = Path(
            tooling_dir
            or os.getenv("AIDN_UPDATE_TOOLING_DIR")
            or self._state_path.parent / "tooling"
        ).expanduser()
        self._uv_path = str(uv_path or os.getenv("AIDN_UV_BIN") or shutil.which("uv") or "")
        self._restart_callback = restart_callback
        self._run_tooling = run_tooling
        self._command_runner = command_runner or subprocess.run
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

        if not self._ref or not _SAFE_REF.fullmatch(self._ref):
            raise OperatorUpdateError("configured update ref contains unsupported characters")
        if ".." in self._ref.split("/"):
            raise OperatorUpdateError("configured update ref contains an unsupported path segment")
        if not self._repository_url.startswith("https://"):
            raise OperatorUpdateError("software updates require an HTTPS repository")

    @property
    def state_path(self) -> Path:
        return self._state_path

    def _default_payload(self) -> dict[str, Any]:
        return {
            "status": "idle",
            "repository_url": self._repository_url,
            "target_ref": self._ref,
            "current_commit": None,
            "available_commit": None,
            "started_at": None,
            "checked_at": None,
            "finished_at": None,
            "restart_scheduled": False,
            "restart_required": False,
            "step": None,
            "message": None,
            "error": None,
        }

    def _read_state(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._default_payload()
        except (OSError, json.JSONDecodeError):
            return self._default_payload()
        if not isinstance(payload, dict):
            return self._default_payload()
        result = self._default_payload()
        result.update(payload)
        return result

    def _write_state(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(dict(payload), ensure_ascii=True, sort_keys=True, indent=2) + "\n"
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self._state_path.name}-",
            dir=self._state_path.parent,
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._state_path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        return dict(payload)

    def _run(self, command: Sequence[str], *, timeout: int = 120) -> str:
        try:
            result = self._command_runner(
                list(command),
                cwd=str(self._repository_path),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise OperatorUpdateError(f"could not run {command[0]}: {error}") from error
        stdout = (result.stdout or "")[:_MAX_OUTPUT]
        stderr = (result.stderr or "")[:_MAX_OUTPUT]
        if result.returncode != 0:
            detail = stderr.strip() or stdout.strip() or f"exit code {result.returncode}"
            raise OperatorUpdateError(f"{command[0]} failed: {_short_error(detail)}")
        return stdout.strip()

    def _git(self, *arguments: str, timeout: int = 120) -> str:
        return self._run(("git", *arguments), timeout=timeout)

    def _validate_checkout(self) -> None:
        if not (self._repository_path / ".git").exists():
            raise OperatorUpdateError("the configured AiDN checkout is unavailable")
        remote = self._git("remote", "get-url", "origin")
        if remote.rstrip("/") != self._repository_url.rstrip("/"):
            raise OperatorUpdateError(
                "the checkout origin does not match the reviewed AiDN repository"
            )

    def _current_commit(self) -> str:
        self._validate_checkout()
        commit = self._git("rev-parse", "HEAD")
        if not _COMMIT.fullmatch(commit):
            raise OperatorUpdateError("the checkout did not report a valid commit")
        return commit.lower()

    def _fetch_target(self) -> str:
        self._validate_checkout()
        self._git("fetch", "--depth", "1", "origin", self._ref, timeout=180)
        target = self._git("rev-parse", "FETCH_HEAD")
        if not _COMMIT.fullmatch(target):
            raise OperatorUpdateError("the remote ref did not resolve to a commit")
        return target.lower()

    def _status_after_restart(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("status") != "restart_scheduled":
            return payload
        try:
            current = self._current_commit()
        except OperatorUpdateError:
            return payload
        target = str(payload.get("available_commit") or "").lower()
        if target and current == target:
            payload.update(
                {
                    "status": "updated",
                    "current_commit": current,
                    "restart_scheduled": False,
                    "restart_required": False,
                    "step": "ready",
                    "message": "Update installed and the Hypervisor restarted successfully.",
                    "error": None,
                }
            )
            return self._write_state(payload)
        return payload

    def read_payload(self) -> dict[str, Any]:
        with self._lock:
            return self._status_after_restart(self._read_state())

    def check(self) -> dict[str, Any]:
        with self._lock:
            current_payload = self._read_state()
            if current_payload.get("status") == "updating":
                return current_payload
            try:
                current = self._current_commit()
                target = self._fetch_target()
                status = "up_to_date" if current == target else "available"
                payload = {
                    **current_payload,
                    "status": status,
                    "current_commit": current,
                    "available_commit": target,
                    "checked_at": _now(),
                    "finished_at": _now(),
                    "restart_scheduled": False,
                    "restart_required": False,
                    "step": "ready",
                    "message": (
                        "The node is already on the latest reviewed commit."
                        if status == "up_to_date"
                        else "A reviewed software update is ready to install."
                    ),
                    "error": None,
                }
            except OperatorUpdateError as error:
                payload = {
                    **current_payload,
                    "status": "error",
                    "checked_at": _now(),
                    "finished_at": _now(),
                    "step": "check",
                    "message": None,
                    "error": str(error),
                }
            return self._write_state(payload)

    def apply(self, *, expected_commit: str) -> dict[str, Any]:
        expected = expected_commit.strip().lower()
        if not _COMMIT.fullmatch(expected):
            raise OperatorUpdateError("expected update commit is invalid")
        with self._lock:
            current_payload = self._read_state()
            if current_payload.get("status") == "updating":
                return current_payload
            current = self._current_commit()
            target = self._fetch_target()
            if target != expected:
                raise OperatorUpdateError(
                    "the available update changed; check for updates again before applying"
                )
            if current == target:
                payload = {
                    **current_payload,
                    "status": "up_to_date",
                    "current_commit": current,
                    "available_commit": target,
                    "checked_at": _now(),
                    "finished_at": _now(),
                    "step": "ready",
                    "message": "The node is already on the selected commit.",
                    "error": None,
                }
                return self._write_state(payload)
            payload = {
                **current_payload,
                "status": "updating",
                "current_commit": current,
                "available_commit": target,
                "started_at": _now(),
                "finished_at": None,
                "restart_scheduled": False,
                "restart_required": False,
                "step": "queued",
                "message": "Update queued. The Dashboard will reconnect after the Hypervisor restarts.",
                "error": None,
            }
            self._write_state(payload)
            self._worker = threading.Thread(
                target=self._run_update,
                args=(current, target),
                name="aidn-software-update",
                daemon=True,
            )
            self._worker.start()
            return payload

    def _set_progress(self, payload: dict[str, Any], *, step: str, message: str | None = None) -> None:
        payload["step"] = step
        if message is not None:
            payload["message"] = message
        self._write_state(payload)

    def _clean_generated_dashboard(self) -> None:
        status = self._git("status", "--porcelain=v1", "--untracked-files=all")
        dirty: list[str] = []
        for line in status.splitlines():
            path = line[3:].replace("\\", "/") if len(line) >= 4 else ""
            if path == GENERATED_DASHBOARD_PATH or path.startswith(f"{GENERATED_DASHBOARD_PATH}/"):
                continue
            dirty.append(line)
        if dirty:
            raise OperatorUpdateError(
                "local checkout changes are present; run the reviewed installer first "
                "so they can be preserved safely"
            )
        self._git("restore", "--source=HEAD", "--staged", "--worktree", "--", GENERATED_DASHBOARD_PATH)
        self._git("clean", "-fd", "--", GENERATED_DASHBOARD_PATH)

    def _run_update(self, previous: str, target: str) -> None:
        payload = self._read_state()
        try:
            self._set_progress(payload, step="preflight", message="Checking the checkout and update source.")
            self._clean_generated_dashboard()
            fetched = self._fetch_target()
            if fetched != target:
                raise OperatorUpdateError(
                    "the remote ref changed while the update was starting; no files were changed"
                )
            self._set_progress(payload, step="checkout", message="Activating the reviewed commit.")
            self._git("checkout", "--detach", target, timeout=120)
            if self._run_tooling:
                if not self._uv_path:
                    raise OperatorUpdateError("uv is not available on this node; run the installer once to provision it")
                self._set_progress(payload, step="dependencies", message="Synchronizing the Python environment.")
                self._run((self._uv_path, "--directory", str(self._repository_path), "sync", "--all-extras", "--frozen"), timeout=600)
                dashboard_script = self._repository_path / "tools" / "build-operator-dashboard.sh"
                node_binary = self._node_root / "bin" / "node"
                if not dashboard_script.is_file() or not node_binary.is_file():
                    raise OperatorUpdateError(
                        "dashboard build tooling is unavailable; run the reviewed installer once before updating from the UI"
                    )
                self._set_progress(payload, step="dashboard", message="Building the new Dashboard assets.")
                self._run(("bash", str(dashboard_script), "--project-root", str(self._repository_path), "--node-root", str(self._node_root), "--tooling-dir", str(self._tooling_dir)), timeout=900)
            current = self._current_commit()
            if current != target:
                raise OperatorUpdateError("the checkout did not finish on the requested commit")
            # Persist the successful checkout before asking the supervisor to
            # terminate this process. The normal callback uses a short timer,
            # so the replacement process can read this state after restart.
            restart_scheduled = self._restart_callback is not None
            payload.update(
                {
                    "status": "restart_scheduled" if restart_scheduled else "updated",
                    "current_commit": current,
                    "step": "restart" if restart_scheduled else "ready",
                    "message": (
                        "Update installed. The Hypervisor is restarting; reconnect the Dashboard when it returns."
                        if restart_scheduled
                        else "Update installed. Restart the Hypervisor service to load the new code."
                    ),
                    "finished_at": _now(),
                    "restart_scheduled": restart_scheduled,
                    "restart_required": not restart_scheduled,
                    "error": None,
                }
            )
            self._write_state(payload)
            if self._restart_callback:
                callback_result = self._restart_callback()
                if callback_result is False:
                    payload.update(
                        {
                            "status": "updated",
                            "step": "ready",
                            "message": "Update installed. Restart the Hypervisor service to load the new code.",
                            "restart_scheduled": False,
                            "restart_required": True,
                        }
                    )
                    self._write_state(payload)
        except Exception as error:
            try:
                if self._repository_path.exists():
                    self._git("checkout", "--detach", previous, timeout=120)
            except Exception:
                # Keep the original failure visible; a host supervisor can
                # still recover the checkout using the reviewed installer.
                pass
            payload.update(
                {
                    "status": "error",
                    "step": "failed",
                    "finished_at": _now(),
                    "restart_scheduled": False,
                    "restart_required": False,
                    "message": None,
                    "error": _short_error(str(error)),
                }
            )
            self._write_state(payload)


__all__ = ["OperatorUpdateError", "OperatorUpdateService"]
