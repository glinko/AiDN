from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from urllib import parse, request
from uuid import uuid4

from aidn_hypervisor.runtime_parameter_policy import normalize_runtime_parameter_policy

_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}$")


class ModelInstallService:
    """Model install orchestration extracted from HypervisorService."""

    def __init__(self, host) -> None:
        self._host = host

    def request_model_install(
        self,
        *,
        provider_type: str,
        model_id: str,
        source_url: str,
        requested_by: str,
        expected_sha256: str | None = None,
        expected_bytes: int | None = None,
        runtime_parameter_policy: dict | None = None,
        resident_adapter_requested: bool = False,
        resident_execution_profile: str | None = None,
        resident_resource_request: dict | None = None,
        resident_fallback_enabled: bool = True,
    ) -> dict:
        if self._host.model_store is None:
            raise ValueError("Model store is not configured")
        model_id = self._validate_model_id(model_id)
        source = self._normalize_source(
            provider_type=provider_type,
            model_id=model_id,
            source_url=source_url,
        )
        expected_sha256, expected_bytes = self._normalize_expected_artifact_metadata(
            expected_sha256,
            expected_bytes,
            source_kind=source.get("source_kind", "artifact"),
        )
        install_id = str(uuid4())
        target_path = str(
            self._host.model_store.reserve_target_path(provider_type, model_id)
        )
        job = {
            "install_id": install_id,
            "provider_type": provider_type,
            "model_id": model_id,
            "source_url": source["source_url"],
            "target_path": target_path,
            "requested_by": requested_by,
            "status": "queued",
            "bundle_id": None,
            "last_error": None,
        }
        # Keep the historical response shape for ordinary model installs.
        # The resident execution projection is added only for an explicitly
        # requested assisted runtime, so existing clients do not have to
        # understand optional control-plane fields.
        if resident_adapter_requested:
            job.update(
                {
                    "resident_adapter_requested": True,
                    "resident_execution_profile": resident_execution_profile,
                    "resident_resource_request": dict(resident_resource_request or {}),
                    "resident_fallback_enabled": bool(resident_fallback_enabled),
                    "resident_adapter_status": "PENDING_MODEL",
                    "resident_adapter_error": None,
                }
            )
        for key in ("source_kind", "provider_model_reference", "resolved_source_url"):
            if key in source:
                job[key] = source[key]
        if expected_sha256 is not None:
            job.update(
                {
                    "expected_sha256": expected_sha256,
                    "expected_bytes": expected_bytes,
                }
            )
        if runtime_parameter_policy:
            job["runtime_parameter_policy"] = {
                key: value.model_dump(mode="json", by_alias=True)
                for key, value in normalize_runtime_parameter_policy(
                    provider_type, runtime_parameter_policy
                ).items()
            }
        self._host._model_installs[install_id] = job
        self._host.record_event(
            event_type="model.install.requested",
            message="model install requested by operator",
            details={"install_id": install_id, "provider_type": provider_type},
        )
        self._host._persist_state()
        return dict(job)

    def list_model_installs(self) -> list[dict]:
        return [dict(job) for job in self._host._model_installs.values()]

    def process_model_installs(
        self,
        *,
        limit: int | None = None,
        install_id: str | None = None,
    ) -> list[dict]:
        if self._host.model_store is None:
            raise ValueError("Model store is not configured")
        processed: list[dict] = []
        if install_id is not None:
            normalized_install_id = str(install_id).strip()
            job = self._host._model_installs.get(normalized_install_id)
            if job is None:
                raise KeyError(f"Unknown model install job: {normalized_install_id}")
            # A targeted retry is intentionally idempotent.  A queued job is
            # materialized below; a running/terminal job is only observed by
            # the caller so a repeated Steward action cannot duplicate work.
            queued_jobs = [job] if job.get("status") == "queued" else []
        else:
            queued_jobs = [
                job
                for job in self._host._model_installs.values()
                if job["status"] == "queued"
            ]
        if limit is not None:
            queued_jobs = queued_jobs[:limit]

        for job in queued_jobs:
            prefetch_state = self._prefetch_state_for_job(job)
            if prefetch_state.get("status") == "running":
                # The installer may already be warming the selected artifact.
                # Keep the install queued so a later process pass can adopt the
                # completed file instead of starting a duplicate download.
                job["prefetch_status"] = "running"
                job["last_error"] = "waiting for background model prefetch"
                self._host._persist_state()
                continue
            job["status"] = "running"
            job["last_error"] = None
            self._host.record_event(
                event_type="model.install.started",
                message="model install started",
                details={
                    "install_id": job["install_id"],
                    "provider_type": job["provider_type"],
                },
            )
            self._host._persist_state()
            artifact_verified = False
            try:
                source_kind = job.get("source_kind", "artifact")
                if source_kind == "provider_reference":
                    # vLLM downloads a Hugging Face repository on its first
                    # managed start; Ollama can pull a named library model
                    # through its local HTTP API.  No HTML repository page is
                    # ever written into the model store.
                    if job.get("provider_type") == "ollama":
                        self._pull_ollama_model(str(job["provider_model_reference"]))
                else:
                    if prefetch_state.get("status") == "completed":
                        job["prefetched"] = True
                        job["prefetch_sha256"] = prefetch_state.get("sha256")
                    else:
                        self._host.model_store.materialize_artifact(
                            str(job.get("resolved_source_url", job["source_url"])),
                            str(job["target_path"]),
                        )
                    expected_sha256 = str(job.get("expected_sha256") or "") or None
                    expected_bytes = job.get("expected_bytes")
                    if expected_sha256 is not None:
                        job["artifact_sha256"] = self._verify_artifact(
                            Path(str(job["target_path"])),
                            expected_sha256=expected_sha256,
                            expected_bytes=expected_bytes,
                        )
                        artifact_verified = True
                    if job.get("provider_type") == "ollama":
                        self._create_ollama_model(
                            model_id=str(job["model_id"]),
                            target_path=str(job["target_path"]),
                        )
            except Exception as error:
                if not artifact_verified and job.get("expected_sha256"):
                    try:
                        Path(str(job["target_path"])).unlink(missing_ok=True)
                    except OSError:
                        pass
                job["status"] = "failed"
                job["last_error"] = str(error)
                self._host.record_event(
                    event_type="model.install.failed",
                    message="model install failed",
                    details={
                        "install_id": job["install_id"],
                        "provider_type": job["provider_type"],
                    },
                )
            else:
                job["status"] = "completed"
                job["last_error"] = None
                if job.get("resident_adapter_requested"):
                    try:
                        self._host.prepare_resident_inference_from_install(
                            str(job["install_id"]),
                            persist=False,
                        )
                    except Exception as error:
                        # A successful download remains successful even when
                        # provider preparation needs operator remediation.
                        # Keep that distinction visible to the Dashboard.
                        job["resident_adapter_status"] = "BLOCKED"
                        job["resident_adapter_error"] = str(error)[:512]
                self._host.record_event(
                    event_type="model.install.completed",
                    message="model install completed",
                    details={
                        "install_id": job["install_id"],
                        "provider_type": job["provider_type"],
                    },
                )
            self._host._persist_state()
            processed.append(dict(job))

        return processed

    @staticmethod
    def _prefetch_state_for_job(job: dict) -> dict:
        """Return a matching installer prefetch marker when it is usable.

        The marker is deliberately colocated with the final artifact.  A
        running marker is adopted only while its worker PID is alive; a stale
        marker therefore falls back to the normal model-store download path
        instead of blocking the install forever.
        """

        target = Path(str(job.get("target_path") or ""))
        if not target or not target.name:
            return {}
        marker_path = Path(f"{target}.aidn-prefetch.json")
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        if not isinstance(marker, dict):
            return {}
        if (
            str(marker.get("provider_type") or "")
            != str(job.get("provider_type") or "")
            or str(marker.get("model_id") or "")
            != str(job.get("model_id") or "")
        ):
            return {}
        if str(marker.get("source_url") or "") != str(job.get("source_url") or ""):
            return {}
        status = str(marker.get("status") or "").lower()
        if status in {"queued", "running"}:
            try:
                pid = int(marker.get("pid") or 0)
                if pid > 0:
                    os.kill(pid, 0)
                    return marker
            except (OSError, TypeError, ValueError):
                pass
            return {}
        if status == "completed" and target.is_file():
            declared_sha256 = str(marker.get("sha256") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", declared_sha256):
                return {}
            try:
                digest = hashlib.sha256()
                with target.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                actual_sha256 = digest.hexdigest()
                expected_bytes = marker.get("expected_bytes")
                target_size = target.stat().st_size
            except (OSError, TypeError, ValueError):
                return {}
            if actual_sha256 != declared_sha256:
                return {}
            if expected_bytes is not None:
                try:
                    if target_size != int(expected_bytes):
                        return {}
                except (TypeError, ValueError):
                    return {}
            expected_sha256 = str(marker.get("expected_sha256") or "").lower()
            if expected_sha256 and actual_sha256 != expected_sha256:
                return {}
            job_expected_sha256 = str(job.get("expected_sha256") or "").lower()
            if job_expected_sha256 and expected_sha256 != job_expected_sha256:
                return {}
            job_expected_bytes = job.get("expected_bytes")
            if job_expected_bytes is not None:
                try:
                    if int(marker.get("expected_bytes")) != int(job_expected_bytes):
                        return {}
                except (TypeError, ValueError):
                    return {}
            return marker
        return {}

    @staticmethod
    def _normalize_expected_artifact_metadata(
        expected_sha256: str | None,
        expected_bytes: int | None,
        *,
        source_kind: str,
    ) -> tuple[str | None, int | None]:
        normalized_sha256 = str(expected_sha256 or "").strip().lower() or None
        if normalized_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", normalized_sha256):
            raise ValueError("expected_sha256 must be a 64-character hexadecimal digest")
        normalized_bytes = expected_bytes
        if normalized_bytes is not None:
            if isinstance(normalized_bytes, bool):
                raise ValueError("expected_bytes must be a positive integer")
            try:
                normalized_bytes = int(normalized_bytes)
            except (TypeError, ValueError) as error:
                raise ValueError("expected_bytes must be a positive integer") from error
            if normalized_bytes <= 0:
                raise ValueError("expected_bytes must be a positive integer")
        if (normalized_sha256 is None) != (normalized_bytes is None):
            raise ValueError("expected_sha256 and expected_bytes must be supplied together")
        if source_kind == "provider_reference" and normalized_sha256 is not None:
            raise ValueError("artifact integrity metadata is not valid for a provider reference")
        return normalized_sha256, normalized_bytes

    @staticmethod
    def _verify_artifact(
        target: Path,
        *,
        expected_sha256: str,
        expected_bytes: int | None,
    ) -> str:
        if not target.is_file():
            raise ValueError("model artifact is missing after materialization")
        try:
            actual_bytes = target.stat().st_size
        except OSError as error:
            raise ValueError(f"model artifact metadata is unavailable: {error}") from error
        if expected_bytes is not None and actual_bytes != int(expected_bytes):
            raise ValueError(
                f"model artifact size mismatch: expected {expected_bytes} bytes, got {actual_bytes}"
            )
        digest = hashlib.sha256()
        try:
            with target.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        except OSError as error:
            raise ValueError(f"model artifact could not be hashed: {error}") from error
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"model artifact SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
            )
        return actual_sha256

    @staticmethod
    def _validate_model_id(model_id: str) -> str:
        normalized = str(model_id or "").strip()
        if not _MODEL_ID_PATTERN.fullmatch(normalized) or ".." in normalized:
            raise ValueError("model_id must be a bounded provider/model identifier")
        return normalized

    @classmethod
    def _normalize_source(
        cls,
        *,
        provider_type: str,
        model_id: str,
        source_url: str,
    ) -> dict[str, str]:
        source = str(source_url or "").strip()
        if not source:
            raise ValueError("source_url must not be empty")
        parsed = parse.urlparse(source)
        provider = provider_type.strip().lower()

        # A bare Hugging Face model id is the canonical source for vLLM and is
        # also useful for Ollama's named library flow.
        if "://" not in source and provider in {"vllm", "ollama"} and "/" in source:
            if not _MODEL_ID_PATTERN.fullmatch(source) or ".." in source:
                raise ValueError("invalid provider model identifier")
            return {
                "source_url": source,
                "source_kind": "provider_reference",
                "provider_model_reference": source,
            }

        if parsed.scheme == "hf":
            hf_parts = [part for part in [parsed.netloc, *parsed.path.strip("/").split("/")] if part]
            if len(hf_parts) < 2:
                raise ValueError("hf:// source must include a repository id")
            owner, repository_ref = hf_parts[:2]
            if "@" in owner or "@" in "/".join(hf_parts[2:]):
                raise ValueError("hf:// source must not contain credentials or an @ character outside its revision")
            repository = repository_ref
            revision = "main"
            if "@" in repository_ref:
                repository, revision = repository_ref.rsplit("@", 1)
                if not repository or not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
                    raise ValueError("hf:// source revision must be a 40-character hexadecimal commit")
            repo = f"{owner}/{repository}"
            file_path = "/".join(hf_parts[2:])
            if provider == "vllm" and not file_path:
                return {
                    "source_url": source,
                    "source_kind": "provider_reference",
                    "provider_model_reference": repo,
                }
            if not file_path:
                raise ValueError("llama.cpp and Ollama require a concrete Hugging Face model file")
            return {
                "source_url": source,
                "resolved_source_url": f"https://huggingface.co/{repo}/resolve/{revision}/{file_path}",
            }

        if parsed.netloc.lower() in {"huggingface.co", "www.huggingface.co"}:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) < 2:
                raise ValueError("Hugging Face URL does not contain a repository id")
            repo = f"{parts[0]}/{parts[1]}"
            if len(parts) >= 4 and parts[2] in {"resolve", "blob"}:
                revision = parts[3]
                file_path = "/".join(parts[4:])
                if not file_path:
                    raise ValueError("Hugging Face URL must point to a model file")
                resolved = f"https://huggingface.co/{repo}/resolve/{revision}/{file_path}"
                return {"source_url": source, "resolved_source_url": resolved}
            if provider == "vllm":
                return {
                    "source_url": source,
                    "source_kind": "provider_reference",
                    "provider_model_reference": repo,
                }
            raise ValueError(
                "for llama.cpp/Ollama paste a concrete Hugging Face file URL "
                "(/resolve/.../*.gguf), not the repository page"
            )

        if provider == "ollama" and parsed.netloc.lower() in {"ollama.com", "www.ollama.com"}:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[0] == "library":
                reference = ":".join(parts[1:])
                return {
                    "source_url": source,
                    "source_kind": "provider_reference",
                    "provider_model_reference": reference,
                }

        if parsed.scheme in {"http", "https", "file"}:
            return {"source_url": source}
        if "://" not in source:
            # Local filesystem paths remain supported for deterministic node
            # tests and air-gapped operators.
            return {"source_url": source}
        raise ValueError("source_url must be an HTTPS/HTTP/file URL or a supported provider reference")

    @staticmethod
    def _pull_ollama_model(model_id: str) -> None:
        payload = json.dumps({"name": model_id, "stream": False}).encode("utf-8")
        req = request.Request(
            "http://127.0.0.1:11434/api/pull",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=3600) as response:
            if response.status >= 400:
                raise RuntimeError(f"Ollama model pull failed with HTTP {response.status}")

    @staticmethod
    def _create_ollama_model(*, model_id: str, target_path: str) -> None:
        modelfile = f"FROM {target_path}\n"
        payload = json.dumps(
            {"name": model_id, "modelfile": modelfile, "stream": False}
        ).encode("utf-8")
        req = request.Request(
            "http://127.0.0.1:11434/api/create",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=3600) as response:
            if response.status >= 400:
                raise RuntimeError(f"Ollama model create failed with HTTP {response.status}")
