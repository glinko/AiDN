from __future__ import annotations

from datetime import datetime

from aidn_hypervisor.accounting.models import SessionAccountingCheckpoint
from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.service import HypervisorService


def build_public_usage_acknowledgement_snapshot(snapshot: dict | None) -> dict:
    return {
        key: value
        for key, value in dict(snapshot or {}).items()
        if not str(key).startswith("_")
    }


def build_public_session_payload(session) -> dict:
    payload = session.model_dump(mode="json")
    payload["last_usage_acknowledgement_snapshot"] = (
        build_public_usage_acknowledgement_snapshot(
            payload.get("last_usage_acknowledgement_snapshot")
        )
    )
    payload["usage_acknowledgement_chain"] = [
        build_public_usage_acknowledgement_snapshot(item)
        if isinstance(item, dict)
        else item
        for item in payload.get("usage_acknowledgement_chain", [])
    ]
    return payload


def build_session_result_payload(
    result,
    *,
    public_session_payload=None,
) -> dict:
    session_payload = (
        public_session_payload
        if public_session_payload is not None
        else result.session.model_dump(mode="json")
    )
    return {
        "session": session_payload,
        "deposit": result.deposit.model_dump(mode="json"),
        "settlement": (
            result.settlement.model_dump(mode="json")
            if result.settlement is not None
            else None
        ),
    }


def build_session_accounting_payload(session) -> dict:
    checkpoint_payload = dict(session.accounting_checkpoint or {})
    checkpoint = SessionAccountingCheckpoint.model_validate(
        checkpoint_payload
        or {
            "last_accepted_report_sequence": session.last_accepted_report_sequence,
            "last_accepted_usage_charged_q": session.last_accepted_usage_charged_q,
        }
    )
    acknowledgement_head = {
        key: value
        for key, value in dict(session.last_usage_acknowledgement_snapshot or {}).items()
        if not str(key).startswith("_")
    }
    return {
        "session_id": session.session_id,
        "status": session.accounting_status,
        "checkpoint": checkpoint.model_dump(mode="json"),
        "report_head": dict(session.last_usage_report_snapshot or {}),
        "acknowledgement_head": acknowledgement_head,
    }


def build_session_list_payload(session_service) -> dict:
    return {
        "items": [
            build_public_session_payload(session)
            for session in session_service.list_sessions()
        ]
    }


def build_session_detail_payload(result) -> dict:
    return build_session_result_payload(
        result,
        public_session_payload=build_public_session_payload(result.session),
    )


def build_session_sweep_payload(results) -> dict:
    return {
        "closed_count": len(results),
        "items": [build_session_result_payload(result) for result in results],
    }


def build_operator_sessions_payload(
    *,
    service: HypervisorService,
    endpoint_service=None,
    session_service=None,
) -> dict:
    current_time = datetime.now().astimezone()
    session_tasks: dict[str, list[dict]] = {}
    session_activity: dict[str, list[dict]] = {}

    def _task_input_preview(task_request: TaskRequest) -> str | None:
        payload = task_request.payload if isinstance(task_request.payload, dict) else {}
        if "prompt" in payload:
            return str(payload["prompt"])
        if "audio_ref" in payload:
            return str(payload["audio_ref"])
        if payload:
            first_key = next(iter(payload))
            return str(payload[first_key])
        return None

    def _settlement_preview(session, deposit) -> dict:
        minimum_session_fee = float(
            session.session_policy_snapshot.get("minimum_session_fee", 0.0) or 0.0
        )
        network_fee_q = float(
            session.session_policy_snapshot.get("network_fee_q", 0.01) or 0.0
        )
        idle_fee_per_minute = float(
            session.session_policy_snapshot.get("idle_fee_per_minute", 0.0) or 0.0
        )
        usage_charged_q = float(deposit.consumed_q)
        minimum_session_fee_q = (
            min(float(deposit.locked_q), minimum_session_fee)
            if int(session.request_count or 0) == 0
            else 0.0
        )
        idle_elapsed_seconds = 0
        idle_exposure_q = 0.0
        if (
            session.status == "active"
            and int(session.request_count or 0) > 0
            and idle_fee_per_minute > 0.0
            and session.last_activity_at
        ):
            try:
                last_activity_at = datetime.fromisoformat(session.last_activity_at)
                idle_elapsed_seconds = max(
                    0,
                    int((current_time - last_activity_at).total_seconds()),
                )
            except ValueError:
                idle_elapsed_seconds = 0
            idle_exposure_q = min(
                max(0.0, float(deposit.locked_q) - usage_charged_q),
                (idle_elapsed_seconds / 60.0) * idle_fee_per_minute,
            )
        projected_payout_q = max(
            minimum_session_fee_q,
            usage_charged_q + idle_exposure_q,
        )
        projected_network_fee_q = min(
            network_fee_q,
            max(0.0, float(deposit.locked_q) - projected_payout_q),
        )
        projected_charged_q = min(
            float(deposit.locked_q),
            projected_payout_q + projected_network_fee_q,
        )
        projected_refundable_q = max(
            0.0,
            float(deposit.locked_q) - projected_charged_q,
        )
        seconds_until_idle_timeout = 0
        if session.idle_deadline_at:
            try:
                idle_deadline_at = datetime.fromisoformat(session.idle_deadline_at)
                seconds_until_idle_timeout = max(
                    0,
                    int((idle_deadline_at - current_time).total_seconds()),
                )
            except ValueError:
                seconds_until_idle_timeout = 0
        return {
            "usage_charged_q": usage_charged_q,
            "minimum_session_fee_q": minimum_session_fee_q,
            "network_fee_q": projected_network_fee_q,
            "idle_exposure_q": idle_exposure_q,
            "projected_charged_q": projected_charged_q,
            "projected_refundable_q": projected_refundable_q,
            "idle_elapsed_seconds": idle_elapsed_seconds,
            "seconds_until_idle_timeout": seconds_until_idle_timeout,
        }

    for task in service.queue.snapshot():
        session_id = task.request.constraints.get("session_id")
        if session_id is None:
            continue
        task_id = str(task.task_id)
        task_result = service.task_result(task_id)
        serialized = {
            "task_id": task_id,
            "created_at": task.created_at,
            "status": task.status,
            "task_type": task.request.task_type,
            "bundle_id": service.selected_bundle_id(task_id),
            "session_id": str(session_id),
            "endpoint_id": task.request.constraints.get("endpoint_id"),
            "input_preview": _task_input_preview(task.request),
            "usage": (
                task_result.get("usage") if isinstance(task_result, dict) else None
            ),
            "session_accounting": (
                task_result.get("session_accounting")
                if isinstance(task_result, dict)
                else None
            ),
        }
        session_tasks.setdefault(str(session_id), []).append(serialized)
        history = [
            {
                "timestamp": event.timestamp,
                "event_type": event.event_type,
                "message": event.message,
                "task_id": event.task_id,
                "details": dict(event.details or {}),
            }
            for event in service.task_history(task_id)
        ]
        session_activity.setdefault(str(session_id), []).extend(history)

    for event in service.event_journal():
        event_session_id = event.details.get("session_id")
        if event_session_id is None:
            continue
        session_activity.setdefault(str(event_session_id), []).append(
            {
                "timestamp": event.timestamp,
                "event_type": event.event_type,
                "message": event.message,
                "task_id": event.task_id,
                "details": dict(event.details or {}),
            }
        )

    for session_id in session_tasks:
        session_tasks[session_id] = sorted(
            session_tasks[session_id],
            key=lambda item: item["created_at"],
            reverse=True,
        )[:8]
    for session_id in session_activity:
        session_activity[session_id] = sorted(
            session_activity[session_id],
            key=lambda item: item["timestamp"],
            reverse=True,
        )[:12]

    if session_service is None:
        return {
            "owner_wallet": service.owner_wallet_state(),
            "node_identity": service.node_identity(),
            "summary": {"total": 0, "active": 0, "queued": 0, "closed": 0},
            "items": [],
        }

    endpoint_names: dict[str, str] = {}
    if endpoint_service is not None:
        for manifest in endpoint_service.list_endpoints():
            endpoint_names[manifest.endpoint_id] = manifest.display_name

    items = []
    for session in sorted(
        session_service.list_sessions(),
        key=lambda item: (
            item.status != "active",
            item.status != "queued",
            item.created_at,
        ),
    ):
        result = session_service.get_session(session.session_id)
        binding = session_service.try_get_proxy_session_binding(session.session_id)
        items.append(
            {
                **build_session_result_payload(result),
                "display_name": endpoint_names.get(
                    session.endpoint_id,
                    session.endpoint_id,
                ),
                "proxy_session": (
                    binding.model_dump(mode="json") if binding is not None else None
                ),
                "remaining_q": max(
                    0.0,
                    result.deposit.locked_q - result.deposit.consumed_q,
                ),
                "settlement_preview": _settlement_preview(
                    result.session,
                    result.deposit,
                ),
                "related_tasks": session_tasks.get(session.session_id, []),
                "activity": session_activity.get(session.session_id, []),
            }
        )

    return {
        "owner_wallet": service.owner_wallet_state(),
        "node_identity": service.node_identity(),
        "summary": {
            "total": len(items),
            "active": sum(
                1 for item in items if item["session"]["status"] == "active"
            ),
            "queued": sum(
                1 for item in items if item["session"]["status"] == "queued"
            ),
            "closed": sum(
                1 for item in items if item["session"]["status"] == "closed"
            ),
        },
        "items": items,
    }
