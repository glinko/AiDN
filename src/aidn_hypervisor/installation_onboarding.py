"""Shared validation and persistence contract for the Ubuntu installer wizard.

The shell bootstrap owns the interactive terminal experience, but the data it
collects is deliberately represented by a small, testable Python contract.  A
later Resident Steward or Dashboard flow can resume the same plan without
guessing what the operator already approved.  The plan is advisory: it never
grants permission to install a plugin, download an artifact, publish an
Endpoint, or mutate the node by itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

SETUP_MODES = {"manual", "ai_assisted"}
PROVIDER_CHOICES = {"skip", "ollama", "llama.cpp", "vllm"}
ENDPOINT_ACTIONS = {"skip", "draft", "start"}
HANDOFF_ACTIONS = {"continue", "dashboard"}
PLAN_MAX_BYTES = 128 * 1024


def _set_owner_only_permissions(fd: int) -> None:
    """Apply POSIX owner-only permissions when the platform supports them.

    The installation target is Ubuntu, where the plan is deliberately written
    as ``0600``.  Windows does not expose ``os.fchmod`` and enforces access
    through ACLs instead; skipping the POSIX mode change there keeps plan
    creation portable without weakening the supported-host guarantee.
    """

    fchmod = getattr(os, "fchmod", None)
    if fchmod is not None:
        fchmod(fd, 0o600)
MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}$")


def _clean(value: object) -> str:
    return str(value or "").strip()


def validate_model_id(value: str) -> str:
    """Validate a bounded provider/model identifier without filesystem paths."""

    normalized = _clean(value)
    if normalized.lower() == "skip":
        return "skip"
    if not MODEL_ID_PATTERN.fullmatch(normalized) or ".." in normalized:
        raise ValueError("setup model id must be a bounded provider/model identifier")
    return normalized


def validate_model_source(value: str, *, provider: str) -> str:
    """Accept reviewed HTTPS/HF sources while rejecting embedded credentials."""

    source = _clean(value)
    if not source:
        raise ValueError("setup model source is required when a model is selected")
    if len(source) > 2048 or any(char in source for char in ("@", "?", "#")):
        raise ValueError("setup model source must be a bounded URL without credentials or query data")
    if source.startswith("hf://"):
        parts = [part for part in source[5:].strip("/").split("/") if part]
        if len(parts) < 2:
            raise ValueError("hf:// source must include an owner and repository")
        return source
    parsed = urlparse(source)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("setup model source must be an HTTPS URL or hf:// reference")
    if parsed.username or parsed.password:
        raise ValueError("setup model source must not contain credentials")
    # Hugging Face is the reviewed default source, while allowing a trusted
    # operator-owned HTTPS mirror keeps the CLI useful on private networks.
    if provider == "llama.cpp" and parsed.path.rstrip("/") == "":
        raise ValueError("llama.cpp setup source must identify a concrete model artifact")
    return source


@dataclass(frozen=True)
class InstallationOnboardingPlan:
    """Serializable, resumable choices collected by the installer."""

    setup_mode: str = "manual"
    provider: str = "skip"
    model_id: str = "skip"
    model_source: str | None = None
    endpoint_action: str = "skip"
    handoff: str = "dashboard"
    schema_version: int = 1

    def __post_init__(self) -> None:
        mode = _clean(self.setup_mode).lower()
        provider = _clean(self.provider).lower()
        endpoint_action = _clean(self.endpoint_action).lower()
        handoff = _clean(self.handoff).lower()
        if mode == "ai":
            mode = "ai_assisted"
        if mode not in SETUP_MODES:
            raise ValueError("setup mode must be manual or ai_assisted")
        if provider not in PROVIDER_CHOICES:
            raise ValueError("setup provider must be skip, ollama, llama.cpp, or vllm")
        if endpoint_action not in ENDPOINT_ACTIONS:
            raise ValueError("setup endpoint action must be skip, draft, or start")
        if handoff not in HANDOFF_ACTIONS:
            raise ValueError("setup handoff must be continue or dashboard")
        model_id = validate_model_id(self.model_id)
        model_source = _clean(self.model_source) or None
        if provider == "skip":
            if model_id != "skip" or model_source is not None:
                raise ValueError("a model cannot be selected without a provider")
            if endpoint_action != "skip":
                raise ValueError("an endpoint action requires a provider and model")
        elif model_id == "skip":
            if model_source is not None or endpoint_action != "skip":
                raise ValueError("a model must be selected before endpoint setup")
        else:
            if model_source is not None:
                model_source = validate_model_source(model_source, provider=provider)
            if endpoint_action != "skip" and model_source is None:
                raise ValueError("endpoint setup requires a model source")
        object.__setattr__(self, "setup_mode", mode)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_source", model_source)
        object.__setattr__(self, "endpoint_action", endpoint_action)
        object.__setattr__(self, "handoff", handoff)

    @property
    def ai_assisted(self) -> bool:
        return self.setup_mode == "ai_assisted"

    def to_dict(self, *, plan_path: str | None = None) -> dict[str, object]:
        next_action = "manual_dashboard_setup"
        if self.ai_assisted:
            if self.provider == "skip":
                next_action = "open_dashboard_provider_setup"
            elif self.model_id == "skip":
                next_action = "choose_model_in_dashboard"
            elif self.endpoint_action == "skip":
                next_action = "review_bundle_and_endpoint_in_dashboard"
            elif self.handoff == "dashboard":
                next_action = "review_ai_plan_in_dashboard"
            else:
                next_action = "resident_steward_review"
        return {
            "schema_version": self.schema_version,
            "created_at": datetime.now(UTC).isoformat(),
            "mode": self.setup_mode,
            "ai_assisted": self.ai_assisted,
            "provider": self.provider,
            "model": {
                "id": self.model_id,
                "source": self.model_source,
            },
            "endpoint": {"requested_action": self.endpoint_action},
            "handoff": self.handoff,
            "status": "READY_FOR_REVIEW" if self.ai_assisted else "MANUAL",
            "next_action": next_action,
            "plan_path": plan_path,
            "authority": {
                "installs": "explicit_operator_review_required",
                "downloads": "explicit_operator_review_required",
                "publication": "validation_and_operator_policy_required",
                "secrets": "never_in_plan",
            },
        }


def write_installation_plan(path: str | os.PathLike[str], plan: InstallationOnboardingPlan) -> dict[str, object]:
    """Atomically write a mode/plan file with owner-only permissions."""

    destination = Path(path).expanduser()
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = plan.to_dict(plan_path=str(destination))
    payload["plan_hash"] = installation_plan_hash(payload)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        _set_owner_only_permissions(fd)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return payload


def installation_plan_hash(payload: dict[str, object]) -> str:
    """Return a stable hash for the operator-approved plan contents.

    ``plan_hash`` itself is excluded so callers can persist the hash beside the
    canonical JSON without creating a self-referential value.
    """

    canonical = dict(payload)
    canonical.pop("plan_hash", None)
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def installation_plan_path(path: str | os.PathLike[str] | None = None) -> Path | None:
    """Resolve the plan path without inventing a plan on an unconfigured node."""

    candidate = path if path is not None else os.getenv("AIDN_INSTALLATION_PLAN_PATH")
    if not candidate:
        return None
    return Path(candidate).expanduser()


def read_installation_plan(
    path: str | os.PathLike[str] | None = None,
    *,
    max_bytes: int = PLAN_MAX_BYTES,
) -> dict[str, object]:
    """Load and validate the persisted plan as a bounded, secret-free projection."""

    resolved = installation_plan_path(path)
    if resolved is None:
        return {
            "available": False,
            "status": "NOT_CONFIGURED",
            "reason": "No installation plan path is configured for this node.",
            "plan_path": None,
        }
    projection: dict[str, object] = {
        "available": False,
        "status": "NOT_CONFIGURED",
        "plan_path": str(resolved),
    }
    try:
        metadata = resolved.stat()
        if os.name != "nt" and metadata.st_mode & 0o077:
            raise ValueError("installation plan permissions must be owner-only")
        size = metadata.st_size
        if size > max_bytes:
            raise ValueError("installation plan exceeds the configured size limit")
        if size <= 0:
            raise ValueError("installation plan is empty")
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError:
        projection.update(
            available=False,
            status="NOT_FOUND",
            reason="The installer has not written an installation plan yet.",
        )
        return projection
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        projection.update(
            available=False,
            status="INVALID",
            reason=f"Installation plan could not be read: {error}",
        )
        return projection
    if not isinstance(payload, dict):
        projection.update(available=False, status="INVALID", reason="Installation plan must be a JSON object.")
        return projection
    try:
        model = payload.get("model") if isinstance(payload.get("model"), dict) else {}
        plan = InstallationOnboardingPlan(
            setup_mode=str(payload.get("mode") or "manual"),
            provider=str(payload.get("provider") or "skip"),
            model_id=str(model.get("id") or "skip"),
            model_source=model.get("source"),
            endpoint_action=str(
                (payload.get("endpoint") or {}).get("requested_action")
                if isinstance(payload.get("endpoint"), dict)
                else "skip"
            ),
            handoff=str(payload.get("handoff") or "dashboard"),
            schema_version=int(payload.get("schema_version") or 1),
        )
        normalized = plan.to_dict(plan_path=str(resolved))
    except (TypeError, ValueError, AttributeError) as error:
        projection.update(available=False, status="INVALID", reason=f"Installation plan is invalid: {error}")
        return projection

    expected_hash = installation_plan_hash(payload)
    stored_hash = str(payload.get("plan_hash") or "")
    if not stored_hash:
        integrity = "legacy_unhashed"
    elif stored_hash == expected_hash:
        integrity = "verified"
    else:
        integrity = "mismatch"
    persisted_status = str(payload.get("status") or normalized["status"])
    projection = {
        **normalized,
        **{
            "available": True,
            "status": persisted_status,
            "plan_hash": expected_hash,
            "stored_plan_hash": stored_hash or None,
            "integrity": integrity,
            "created_at": payload.get("created_at") or normalized["created_at"],
            "updated_at": payload.get("updated_at"),
            "applied_at": payload.get("applied_at"),
            "application": payload.get("application"),
            "next_action": payload.get("next_action") or normalized["next_action"],
            "plan_path": str(resolved),
        },
    }
    if integrity == "legacy_unhashed":
        projection["status"] = "LEGACY_REVIEW_REQUIRED"
        projection["reason"] = "This plan predates plan-hash binding; regenerate or review it before applying."
    elif integrity == "mismatch":
        projection["status"] = "STALE"
        projection["reason"] = "The persisted plan changed after it was written; regenerate it before applying."
    return projection


def update_installation_plan(
    path: str | os.PathLike[str] | None,
    *,
    expected_hash: str,
    status: str,
    application: dict[str, object] | None = None,
    next_action: str | None = None,
) -> dict[str, object]:
    """Atomically update only review metadata and re-bind the plan hash."""

    resolved = installation_plan_path(path)
    if resolved is None:
        raise ValueError("installation plan path is not configured")
    current = read_installation_plan(resolved)
    if not current.get("available"):
        raise ValueError(str(current.get("reason") or "installation plan is unavailable"))
    if current.get("integrity") != "verified":
        raise ValueError(str(current.get("reason") or "installation plan integrity is not verified"))
    if str(current.get("plan_hash")) != str(expected_hash):
        raise ValueError("installation plan changed; refresh before applying")
    raw = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("installation plan must be a JSON object")
    raw["status"] = status
    raw["updated_at"] = datetime.now(UTC).isoformat()
    if application is not None:
        raw["application"] = application
    if next_action is not None:
        raw["next_action"] = next_action
    raw.pop("plan_hash", None)
    raw["plan_hash"] = installation_plan_hash(raw)
    destination = Path(resolved)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        _set_owner_only_permissions(fd)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(raw, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return read_installation_plan(destination)


def prepare_assisted_installation_review(
    path: str | os.PathLike[str] | None,
    *,
    expected_hash: str,
    actor: str,
    idempotency_key: str | None = None,
    provider_plan_builder,
) -> dict[str, object]:
    """Advance one assistant-created plan to an explicit provider review.

    This is intentionally *not* a shortcut around the Provider lifecycle:
    it materializes the reviewed provider installation plan and records the
    model/Endpoint work still waiting behind it.  The operator must still use
    the existing plan/approval/apply flow for the provider and the normal
    model/Bundle/Endpoint lifecycle thereafter.
    """

    current = read_installation_plan(path)
    if not current.get("available"):
        raise ValueError(str(current.get("reason") or "installation plan is unavailable"))
    if current.get("integrity") != "verified":
        raise ValueError(str(current.get("reason") or "installation plan integrity is not verified"))
    if current.get("mode") != "ai_assisted":
        raise ValueError("only an AI-assisted installation plan can be prepared")
    if str(current.get("plan_hash")) != str(expected_hash):
        raise ValueError("installation plan changed; refresh before applying")

    existing = current.get("application")
    if (
        idempotency_key
        and isinstance(existing, dict)
        and existing.get("idempotency_key") == idempotency_key
    ):
        current["operation_id"] = existing.get("operation_id")
        current["review"] = existing
        return current

    provider = str(current.get("provider") or "skip")
    model = current.get("model") if isinstance(current.get("model"), dict) else {}
    endpoint = current.get("endpoint") if isinstance(current.get("endpoint"), dict) else {}
    operation_id = f"install-review-{uuid4().hex}"
    application: dict[str, object] = {
        "operation_id": operation_id,
        "actor": str(actor or "operator"),
        "idempotency_key": idempotency_key,
        "prepared_at": datetime.now(UTC).isoformat(),
        "provider": {"status": "SKIPPED"},
        "model": {
            "id": model.get("id", "skip"),
            "source": model.get("source"),
            "status": "NOT_REQUESTED" if model.get("id", "skip") == "skip" else "PENDING_PROVIDER",
        },
        "endpoint": {
            "requested_action": endpoint.get("requested_action", "skip"),
            "status": "NOT_REQUESTED" if endpoint.get("requested_action", "skip") == "skip" else "PENDING_MODEL",
        },
        "authority": {
            "provider_install": "provider_plan_approval_required",
            "model_download": "explicit_model_install_required",
            "endpoint": "bundle_and_endpoint_lifecycle_required",
        },
    }

    if provider == "skip":
        status = "COMPLETED"
        next_action = "open_dashboard_provider_setup"
    else:
        provider_plan = dict(provider_plan_builder(provider, {}))
        application["provider"] = {
            "plugin_id": provider,
            "configuration": {},
            "status": "REVIEW_REQUIRED",
            # Only share the reviewed declarative fields. This plan must never
            # turn into a vehicle for secret-bearing provider configuration.
            "installation_plan": {
                key: provider_plan.get(key)
                for key in ("plan_id", "plan_version", "summary", "required_permissions", "health_checks")
            },
        }
        status = "PROVIDER_REVIEW_REQUIRED"
        next_action = "approve_provider_installation"

    updated = update_installation_plan(
        path,
        expected_hash=expected_hash,
        status=status,
        application=application,
        next_action=next_action,
    )
    updated["operation_id"] = operation_id
    updated["review"] = application
    return updated


__all__ = [
    "ENDPOINT_ACTIONS",
    "HANDOFF_ACTIONS",
    "InstallationOnboardingPlan",
    "PLAN_MAX_BYTES",
    "PROVIDER_CHOICES",
    "SETUP_MODES",
    "validate_model_id",
    "validate_model_source",
    "installation_plan_hash",
    "installation_plan_path",
    "read_installation_plan",
    "prepare_assisted_installation_review",
    "update_installation_plan",
    "write_installation_plan",
]
