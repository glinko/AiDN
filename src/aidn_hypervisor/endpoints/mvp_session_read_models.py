from __future__ import annotations


def build_mvp_session_open_payload(session, deposit, funding) -> dict:
    return {
        "session": session.model_dump(mode="json"),
        "deposit": deposit.model_dump(mode="json"),
        "funding": funding.model_dump(mode="json"),
    }


def build_mvp_session_result_payload(session_result) -> dict:
    return {
        "session": session_result.session.model_dump(mode="json"),
        "deposit": session_result.deposit.model_dump(mode="json"),
        "settlement": (
            session_result.settlement.model_dump(mode="json")
            if session_result.settlement is not None
            else None
        ),
    }


def build_mvp_settlement_preview_payload(proposal, acceptance) -> dict:
    return {
        "proposal": proposal.model_dump(mode="json"),
        "acceptance_payload": acceptance.model_dump(
            mode="json",
            exclude={"consumer_signature", "acceptance_hash"},
        ),
    }


def build_mvp_settlement_finalize_payload(
    finalized: dict,
    *,
    include_acceptance: bool,
) -> dict:
    payload = {
        "proposal": finalized["proposal"].model_dump(mode="json"),
        "funding": finalized["funding"].model_dump(mode="json"),
    }
    if include_acceptance:
        payload["acceptance"] = finalized["acceptance"].model_dump(mode="json")
    payload.update(build_mvp_session_result_payload(finalized["session_result"]))
    return payload


def build_mvp_settlement_readiness_payload(evaluation) -> dict:
    return {
        "ready": True,
        "proposal": evaluation.proposal.model_dump(mode="json"),
        "input_root": evaluation.input_set.settlement_input_root,
        "request_settlement_root": evaluation.input_set.request_settlement_root,
        "usage_chain_root": evaluation.input_set.usage_chain_root,
    }


def build_mvp_runtime_evidence_payload(
    *,
    task,
    bundle_id: str | None,
    result: dict | None,
    runtime_record,
    final_usage,
) -> dict:
    return {
        "task": {
            "task_id": task.task_id,
            "status": task.status,
            "task_type": task.request.task_type,
            "bundle_id": bundle_id,
            "result": result,
        },
        "runtime_evidence": {
            "request": runtime_record.model_dump(mode="json"),
            "final_usage": final_usage.model_dump(mode="json"),
        },
    }


def build_mvp_paid_smoke_payload(
    *,
    session,
    deposit,
    funding,
    task,
    bundle_id: str | None,
    result: dict | None,
    runtime_record,
    final_usage,
    settlement_evaluation,
    finalized: dict | None,
) -> dict:
    payload = build_mvp_session_open_payload(session, deposit, funding)
    payload.update(
        build_mvp_runtime_evidence_payload(
            task=task,
            bundle_id=bundle_id,
            result=result,
            runtime_record=runtime_record,
            final_usage=final_usage,
        )
    )
    payload["settlement_readiness"] = build_mvp_settlement_readiness_payload(
        settlement_evaluation
    )
    payload["finalized"] = (
        build_mvp_settlement_finalize_payload(finalized, include_acceptance=True)
        if finalized is not None
        else None
    )
    return payload
