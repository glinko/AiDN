from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta

from aidn_hypervisor.domain.models import BundleConfig, TaskRequest
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.queue import QueuedTask
from aidn_hypervisor.runtime_parameter_policy import apply_runtime_parameter_policy
from aidn_hypervisor.runtime_protocol.approved_dispatch import (
    ApprovedRuntimeDispatcher,
)
from aidn_hypervisor.runtime_protocol.models import (
    RuntimeExecuteRequest,
    RuntimeRequestRecord,
    RuntimeUsageReport,
)
from aidn_hypervisor.sessions.models import ProxySessionBinding

Q_ATOMS_PER_Q = 1_000_000


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class RuntimeExecutionService:
    """Runtime/session execution orchestration extracted from HypervisorService."""

    def __init__(self, host) -> None:
        self._host = host

    def endpoint_manifest_for_request(self, request: TaskRequest):
        endpoint_id = request.constraints.get("endpoint_id")
        if endpoint_id is None:
            return None
        endpoint_service = getattr(self._host, "endpoint_service", None)
        if endpoint_service is None:
            return None
        return endpoint_service.get_endpoint(str(endpoint_id)).endpoint

    def uses_approved_runtime(self, endpoint_manifest) -> bool:
        if endpoint_manifest is None or endpoint_manifest.runtime_binding_id is None:
            return False
        try:
            binding = self._host.provider_inventory.store.get_runtime_binding(
                endpoint_manifest.runtime_binding_id
            )
        except KeyError:
            return False
        return binding.adapter_id in {
            "llamacpp-openai",
            "ollama-generate",
            "proxy-openai",
            "vllm-openai",
            "whisper-http",
        }

    def uses_approved_llamacpp_runtime(self, endpoint_manifest) -> bool:
        """Compatibility alias for callers not yet migrated to generic dispatch."""
        return self.uses_approved_runtime(endpoint_manifest)

    def touch_task_session(self, request: TaskRequest) -> None:
        session_id = request.constraints.get("session_id")
        if session_id is None:
            return
        session_service = getattr(self._host, "session_service", None)
        if session_service is None:
            raise RuntimeError("Session service is not configured")
        try:
            session_service.touch_session(str(session_id))
        except KeyError as error:
            raise RuntimeError(f"Unknown session: {session_id}") from error

    def record_mvp_runtime_evidence_for_completed_task(
        self,
        *,
        task_id: str,
        bundle: BundleConfig,
        task: TaskRequest,
        runtime: RuntimeHandle | None,
    ) -> RuntimeRequestRecord | None:
        session_id = task.constraints.get("session_id")
        endpoint_id = task.constraints.get("endpoint_id")
        if session_id is None or endpoint_id is None:
            return None
        session_service = getattr(self._host, "session_service", None)
        endpoint_service = getattr(self._host, "endpoint_service", None)
        if session_service is None or endpoint_service is None:
            return None
        try:
            session = session_service.store.get_session(str(session_id))
            endpoint = endpoint_service.get_endpoint(str(endpoint_id)).endpoint
        except KeyError:
            return None
        if session.economic_profile != "MVP-0001":
            return None
        if session.session_contract_hash is None:
            raise RuntimeError("MVP Session is missing session_contract_hash")
        if session.accounting_contract_hash is None:
            raise RuntimeError("MVP Session is missing accounting_contract_hash")
        if session.request_charge_ceiling_q_atoms is None:
            raise RuntimeError("MVP Session is missing request_charge_ceiling_q_atoms")

        request_id = str(task.constraints.get("request_id") or task_id)
        runtime_id = (
            runtime.runtime_id if runtime is not None else f"proxy:{bundle.bundle_id}"
        )
        runtime_configuration_hash = _canonical_hash(
            {
                "bridge": "MVP-0001_TASK_RUNTIME_COMPAT",
                "bundle_id": bundle.bundle_id,
                "bundle_model_id": bundle.model_id,
                "endpoint_configuration_hash": endpoint.configuration_hash,
            }
        )
        payload = {
            "task_id": task_id,
            "task_type": task.task_type,
            "payload": task.payload,
        }
        request_deadline = str(
            task.constraints.get("request_deadline")
            or (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        )
        request = RuntimeExecuteRequest(
            runtime_id=runtime_id,
            runtime_generation=1,
            runtime_configuration_hash=runtime_configuration_hash,
            route_generation=1,
            endpoint_id=endpoint.endpoint_id,
            endpoint_configuration_hash=endpoint.configuration_hash,
            session_id=session.session_id,
            session_contract_hash=session.session_contract_hash,
            effective_terms_hash=(
                session.effective_terms_hash or session.session_contract_hash
            ),
            request_id=request_id,
            capability_id=(
                endpoint.capabilities[0]
                if endpoint.capabilities
                else endpoint.model_class
            ),
            capability_version="1.0",
            capability_definition_hash=_canonical_hash(
                {
                    "endpoint_id": endpoint.endpoint_id,
                    "model_class": endpoint.model_class,
                    "capabilities": endpoint.capabilities,
                }
            ),
            request_payload_hash=_canonical_hash(payload),
            request_payload=payload,
            request_charge_ceiling=(
                session.request_charge_ceiling_q_atoms / Q_ATOMS_PER_Q
            ),
            accounting_contract_hash=session.accounting_contract_hash,
            idempotency_key=f"task:{task_id}",
            request_deadline=request_deadline,
            trace_context={
                "task_id": task_id,
                "bundle_id": bundle.bundle_id,
                "bridge": "MVP-0001_TASK_RUNTIME_COMPAT",
            },
        )
        existing = self._host.runtime_protocol_store.requests.get(request_id)
        request_hash = request.semantic_hash()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise RuntimeError("MVP Runtime Request ID conflicts with task evidence")
            if existing.terminal_result_hash is not None:
                return existing

        now = datetime.now(UTC).isoformat()
        result = self._host._task_results.get(task_id)
        result_payload = result if isinstance(result, dict) else {"result": result}
        final_usage = RuntimeUsageReport(
            usage_report_id=f"usage-final-{request_id}",
            runtime_id=request.runtime_id,
            runtime_generation=request.runtime_generation,
            runtime_configuration_hash=request.runtime_configuration_hash,
            endpoint_id=request.endpoint_id,
            endpoint_configuration_hash=request.endpoint_configuration_hash,
            session_id=request.session_id,
            request_id=request.request_id,
            effective_terms_hash=request.effective_terms_hash,
            accounting_contract_hash=request.accounting_contract_hash,
            report_type="FINAL",
            usage_sequence=1,
            request_state="COMPLETED",
            provider_attempt_count=1,
            terminal=True,
            observed_from=now,
            observed_to=now,
            limitations=[
                "MVP-0001 fixed-price bridge records execution envelope only; "
                "token dimensions are not inferred."
            ],
            created_at=now,
            runtime_signature="hypervisor-mvp-bridge",
        )
        self._host.runtime_protocol_store.requests[request_id] = RuntimeRequestRecord(
            request_id=request_id,
            runtime_id=request.runtime_id,
            runtime_generation=request.runtime_generation,
            route_generation=request.route_generation,
            request_hash=request_hash,
            request=request,
            request_state="COMPLETED",
            admission_state="ACCEPTED",
            runtime_request_handle=f"task:{task_id}",
            accepted_at=now,
            terminal_result_hash=_canonical_hash(result_payload),
            terminal_final_usage_report_id=final_usage.usage_report_id,
            updated_at=now,
        )
        self._host.runtime_protocol_store.usage_reports[final_usage.usage_report_id] = (
            final_usage
        )
        self._host.runtime_protocol_store.flush()
        self._host.record_event(
            event_type="runtime.mvp_evidence_recorded",
            message="MVP Runtime evidence recorded from completed task",
            task_id=task_id,
            bundle_id=bundle.bundle_id,
            runtime_id=runtime_id,
            details={
                "session_id": session.session_id,
                "request_id": request_id,
                "usage_report_id": final_usage.usage_report_id,
            },
        )
        return self._host.runtime_protocol_store.requests[request_id]

    def attempt_approved_runtime_task(
        self,
        task_id: str,
        task: QueuedTask,
        bundle: BundleConfig,
        endpoint_manifest,
    ) -> bool:
        session_id = task.request.constraints.get("session_id")
        if session_id is None:
            raise RuntimeError("Approved Runtime execution requires an active Session")
        session_service = getattr(self._host, "session_service", None)
        if session_service is None:
            raise RuntimeError("Session service is not configured")
        self._host.queue.transition_status(task_id, "admitted")
        try:
            effective_request = apply_runtime_parameter_policy(
                task.request,
                bundle,
                getattr(endpoint_manifest, "runtime_parameter_policy", None),
            )
            self._host.queue.transition_status(task_id, "running")
            self.touch_task_session(task.request)
            session = session_service.store.get_session(str(session_id))
            result = ApprovedRuntimeDispatcher(
                provider_inventory=self._host.provider_inventory,
                runtime_protocol_store=self._host.runtime_protocol_store,
                hypervisor_id=self._host.node_id,
            ).execute(
                endpoint=endpoint_manifest,
                session=session,
                request_id=str(task.request.constraints.get("request_id") or task_id),
                request_payload=effective_request.payload,
                request_deadline=task.request.constraints.get("request_deadline"),
                streaming=bool(task.request.constraints.get("streaming", False)),
            )
            if result.terminal_state != "COMPLETED":
                raise RuntimeError(
                    f"Approved Runtime execution failed: {result.terminal_state}"
                )
            self.record_session_runtime_terminal_evidence(
                session_service=session_service,
                session=session,
                endpoint_manifest=endpoint_manifest,
                result=result,
            )
            result_payload = result.result_payload or {}
            task_result = {
                "ok": True,
                "task_type": task.request.task_type,
                "output_text": result_payload.get("text", ""),
                "model_id": result_payload.get("model"),
                "runtime_protocol": {
                    "runtime_id": result.runtime_id,
                    "request_id": result.request_id,
                    "final_usage_report_id": result.final_usage_report_id,
                },
            }
            if isinstance(result_payload.get("tool_calls"), list):
                task_result["tool_calls"] = result_payload["tool_calls"]
            self._host._task_results[task_id] = task_result
            self._host.queue.transition_status(task_id, "completed")
            self._host.record_event(
                event_type="task.completed",
                message="task completed through approved Runtime Adapter",
                task_id=task_id,
                bundle_id=bundle.bundle_id,
                runtime_id=result.runtime_id,
                details={
                    "runtime_request_id": result.request_id,
                    "adapter": self._host.provider_inventory.store.get_runtime_binding(
                        endpoint_manifest.runtime_binding_id
                    ).adapter_id,
                },
            )
            self._host._auto_record_wallet_usage_for_task(
                task_id=task_id,
                bundle=bundle,
                task=task.request,
            )
            return True
        except Exception as error:
            self._host.queue.transition_status(task_id, "failed")
            self._host.record_event(
                event_type="task.failed",
                message=str(error),
                task_id=task_id,
                bundle_id=bundle.bundle_id,
            )
            raise

    def record_session_runtime_terminal_evidence(
        self,
        *,
        session_service,
        session,
        endpoint_manifest,
        result,
    ) -> None:
        record = self._host.runtime_protocol_store.requests.get(result.request_id)
        final_usage = self._host.runtime_protocol_store.usage_reports.get(
            result.final_usage_report_id
        )
        if record is None or final_usage is None:
            raise RuntimeError("terminal Runtime evidence is not durable")
        if not final_usage.terminal or final_usage.report_type != "FINAL":
            raise RuntimeError("terminal Runtime evidence requires Final Usage")
        binding_id = endpoint_manifest.runtime_binding_id
        if binding_id is None:
            raise RuntimeError("approved Runtime Endpoint has no Runtime Binding")
        session_service.record_runtime_terminal_evidence(
            session.session_id,
            evidence={
                "request_id": result.request_id,
                "runtime_binding_id": binding_id,
                "runtime_id": result.runtime_id,
                "runtime_generation": result.runtime_generation,
                "runtime_configuration_hash": result.runtime_configuration_hash,
                "route_generation": result.route_generation,
                "endpoint_id": result.endpoint_id,
                "endpoint_configuration_hash": result.endpoint_configuration_hash,
                "session_id": result.session_id,
                "session_contract_hash": record.request.session_contract_hash,
                "effective_terms_hash": record.request.effective_terms_hash,
                "accounting_contract_hash": record.request.accounting_contract_hash,
                "terminal_state": result.terminal_state,
                "result_hash": result.result_hash,
                "final_usage_report_id": final_usage.usage_report_id,
                "final_usage_report_hash": final_usage.report_hash,
                "recorded_at": result.completed_at,
            },
        )

    def close_endpoint_session(self, session_id: str):
        session_service = getattr(self._host, "session_service", None)
        if session_service is None:
            raise RuntimeError("Session service is not configured")
        result = session_service.close_session(session_id)
        self.propagate_proxy_session_close(session_id)
        return result

    def propagate_proxy_session_close(self, session_id: str) -> None:
        session_service = getattr(self._host, "session_service", None)
        if session_service is None:
            raise RuntimeError("Session service is not configured")
        binding = session_service.try_get_proxy_session_binding(session_id)
        if binding is None or not binding.remote_session_id:
            return
        self.close_remote_proxy_session_binding(session_service, binding)

    def close_remote_proxy_session_binding(
        self,
        session_service,
        binding: ProxySessionBinding,
    ) -> None:
        if binding.status == "closed" and binding.close_status == "closed":
            return
        try:
            self._host._remote_request_json(
                "POST",
                f"{binding.source_base_url.rstrip('/')}/api/v1/sessions/{binding.remote_session_id}/close",
            )
            session_service.save_proxy_session_binding(
                binding.model_copy(
                    update={
                        "status": "closed",
                        "close_status": "closed",
                        "last_error": None,
                    }
                )
            )
        except Exception as error:
            session_service.save_proxy_session_binding(
                binding.model_copy(
                    update={
                        "status": "close_pending",
                        "close_status": "pending_reconcile",
                        "last_error": str(error),
                    }
                )
            )

    def proxy_target_requires_remote_session(self, endpoint_manifest) -> bool:
        proxy_target = endpoint_manifest.proxy_target
        if proxy_target is None:
            return False
        remote_endpoint_service = getattr(self._host, "remote_endpoint_service", None)
        if remote_endpoint_service is None:
            return False
        try:
            remote_endpoint = remote_endpoint_service.get_remote_endpoint(
                proxy_target.remote_endpoint_id
            )
        except KeyError:
            return False
        session_policy = remote_endpoint.session_policy or {}
        return any(
            (
                float(session_policy.get("minimum_deposit", 0.0) or 0.0) > 0.0,
                float(session_policy.get("minimum_session_fee", 0.0) or 0.0) > 0.0,
                float(session_policy.get("idle_fee_per_minute", 0.0) or 0.0) > 0.0,
            )
        )

    def ensure_proxy_session_binding(
        self,
        endpoint_manifest,
        task_request: TaskRequest,
    ) -> ProxySessionBinding:
        session_id = task_request.constraints.get("session_id")
        if session_id is None:
            raise RuntimeError("Local session is required for proxy session brokering")
        session_service = getattr(self._host, "session_service", None)
        if session_service is None:
            raise RuntimeError("Session service is not configured")
        existing = session_service.try_get_proxy_session_binding(str(session_id))
        if (
            existing is not None
            and existing.status == "active"
            and existing.remote_session_id
        ):
            return existing
        session_result = session_service.get_session(str(session_id))
        proxy_target = endpoint_manifest.proxy_target
        if proxy_target is None:
            raise RuntimeError(
                f"Proxy endpoint has no target: {endpoint_manifest.endpoint_id}"
            )
        remote_endpoint = self._host.remote_endpoint_service.get_remote_endpoint(
            proxy_target.remote_endpoint_id
        )
        remote_policy = remote_endpoint.session_policy or {}
        deposit_q = float(
            remote_policy.get("recommended_deposit")
            or remote_policy.get("minimum_deposit")
            or session_result.deposit.locked_q
        )
        open_url = (
            f"{proxy_target.source_base_url.rstrip('/')}/api/v1/endpoints/"
            f"{proxy_target.source_endpoint_id}/sessions"
        )
        try:
            opened = self._host._remote_request_json(
                "POST",
                open_url,
                {
                    "client_wallet": session_result.session.client_wallet,
                    "deposit_q": deposit_q,
                },
            )
        except Exception as error:
            session_service.save_proxy_session_binding(
                ProxySessionBinding(
                    local_session_id=str(session_id),
                    remote_endpoint_id=proxy_target.source_endpoint_id,
                    remote_session_id="",
                    remote_node_id=proxy_target.source_node_id,
                    source_base_url=proxy_target.source_base_url,
                    status="degraded",
                    opened_at=datetime.now(UTC).isoformat(),
                    last_error=str(error),
                    close_status="not_requested",
                )
            )
            raise RuntimeError(str(error)) from error
        remote_session = dict(opened.get("session") or {})
        return session_service.save_proxy_session_binding(
            ProxySessionBinding(
                local_session_id=str(session_id),
                remote_endpoint_id=proxy_target.source_endpoint_id,
                remote_session_id=str(remote_session["session_id"]),
                remote_node_id=proxy_target.source_node_id,
                source_base_url=proxy_target.source_base_url,
                status="active",
                opened_at=str(
                    remote_session.get("opened_at")
                    or datetime.now(UTC).isoformat()
                ),
                last_error=None,
                close_status="not_requested",
            )
        )

    def attempt_proxy_task(
        self,
        task_id: str,
        task: QueuedTask,
        bundle: BundleConfig,
        endpoint_manifest,
    ) -> bool:
        self._host.queue.transition_status(task_id, "admitted")
        self._host.record_event(
            event_type="task.proxy_dispatched",
            message="task dispatched through proxy endpoint",
            task_id=task_id,
            bundle_id=bundle.bundle_id,
            details={
                "endpoint_id": endpoint_manifest.endpoint_id,
                "remote_endpoint_id": endpoint_manifest.proxy_target.source_endpoint_id,
                "remote_node_id": endpoint_manifest.proxy_target.source_node_id,
                "source_base_url": endpoint_manifest.proxy_target.source_base_url,
            },
        )
        try:
            effective_request = apply_runtime_parameter_policy(
                task.request,
                bundle,
                getattr(endpoint_manifest, "runtime_parameter_policy", None),
            )
            self._host.queue.transition_status(task_id, "running")
            self.touch_task_session(task.request)
            self._host._task_results[task_id] = self.invoke_proxy_endpoint(
                endpoint_manifest,
                effective_request,
            )
            self._host.queue.transition_status(task_id, "completed")
            self._host.record_event(
                event_type="task.completed",
                message="task completed successfully",
                task_id=task_id,
                bundle_id=bundle.bundle_id,
            )
            self.record_mvp_runtime_evidence_for_completed_task(
                task_id=task_id,
                bundle=bundle,
                task=task.request,
                runtime=None,
            )
            self._host._auto_record_wallet_usage_for_task(
                task_id=task_id,
                bundle=bundle,
                task=task.request,
            )
            return True
        except Exception as error:
            self._host.queue.transition_status(task_id, "failed")
            self._host.record_event(
                event_type="task.failed",
                message=str(error),
                task_id=task_id,
                bundle_id=bundle.bundle_id,
            )
            raise

    def invoke_proxy_endpoint(self, endpoint_manifest, task_request: TaskRequest) -> dict:
        proxy_target = endpoint_manifest.proxy_target
        if proxy_target is None:
            raise RuntimeError(
                f"Proxy endpoint has no target: {endpoint_manifest.endpoint_id}"
            )
        remote_constraints = {
            key: value
            for key, value in task_request.constraints.items()
            if key not in {"endpoint_id", "allocation_id", "session_id"}
        }
        if self.proxy_target_requires_remote_session(endpoint_manifest):
            binding = self.ensure_proxy_session_binding(endpoint_manifest, task_request)
            remote_constraints["session_id"] = binding.remote_session_id
        remote_constraints["endpoint_id"] = proxy_target.source_endpoint_id
        remote_request = task_request.model_copy(
            update={
                "mode": "auto",
                "bundle_override": None,
                "constraints": remote_constraints,
            }
        )
        submit_response = self._host._remote_request_json(
            "POST",
            f"{proxy_target.source_base_url.rstrip('/')}/tasks",
            remote_request.model_dump(mode="json"),
        )
        remote_task_id = str(submit_response["task_id"])
        attempts = max(1, int(getattr(self._host, "proxy_poll_attempts", 5)))
        interval_seconds = max(
            0.0,
            float(getattr(self._host, "proxy_poll_interval_seconds", 0.0)),
        )
        for attempt in range(attempts):
            detail = self._host._remote_request_json(
                "GET",
                f"{proxy_target.source_base_url.rstrip('/')}/tasks/{remote_task_id}",
            )
            if detail.get("status") == "completed":
                result = dict(detail.get("result") or {})
                result["proxy"] = {
                    "remote_task_id": remote_task_id,
                    "remote_endpoint_id": proxy_target.source_endpoint_id,
                    "remote_node_id": proxy_target.source_node_id,
                    "source_base_url": proxy_target.source_base_url,
                }
                return result
            if detail.get("status") == "failed":
                raise RuntimeError(
                    str(
                        (detail.get("result") or {}).get("error")
                        or f"Remote proxy task failed: {remote_task_id}"
                    )
                )
            if attempt < attempts - 1 and interval_seconds > 0.0:
                time.sleep(interval_seconds)
        raise RuntimeError(
            f"Remote proxy task did not complete within {attempts} poll attempts: "
            f"{remote_task_id}"
        )
