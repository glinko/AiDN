from __future__ import annotations

from uuid import uuid4


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
    ) -> dict:
        if self._host.model_store is None:
            raise ValueError("Model store is not configured")
        install_id = str(uuid4())
        target_path = str(
            self._host.model_store.reserve_target_path(provider_type, model_id)
        )
        job = {
            "install_id": install_id,
            "provider_type": provider_type,
            "model_id": model_id,
            "source_url": source_url,
            "target_path": target_path,
            "requested_by": requested_by,
            "status": "queued",
            "bundle_id": None,
            "last_error": None,
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
                self._host.model_store.materialize_artifact(
                    str(job["source_url"]),
                    str(job["target_path"]),
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
