from __future__ import annotations

import json
import re
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

    def process_model_installs(self, *, limit: int | None = None) -> list[dict]:
        if self._host.model_store is None:
            raise ValueError("Model store is not configured")
        processed: list[dict] = []
        queued_jobs = [
            job for job in self._host._model_installs.values() if job["status"] == "queued"
        ]
        if limit is not None:
            queued_jobs = queued_jobs[:limit]

        for job in queued_jobs:
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
                    self._host.model_store.materialize_artifact(
                        str(job.get("resolved_source_url", job["source_url"])),
                        str(job["target_path"]),
                    )
                    if job.get("provider_type") == "ollama":
                        self._create_ollama_model(
                            model_id=str(job["model_id"]),
                            target_path=str(job["target_path"]),
                        )
            except Exception as error:
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
            repo = "/".join(hf_parts[:2])
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
                "resolved_source_url": f"https://huggingface.co/{repo}/resolve/main/{file_path}",
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
