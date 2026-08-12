from __future__ import annotations

from typing import TYPE_CHECKING, cast

from aidn_hypervisor.ledger.service import STANDARD_NETWORK_FEE_Q_ATOMS

if TYPE_CHECKING:
    from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
    from aidn_hypervisor.service import HypervisorService


Q_ATOMS_PER_Q = 1_000_000


def _pending_wallet_transfer_payload(service: HypervisorService, wallet_id: str | None) -> list[dict]:
    if not wallet_id:
        return []
    consensus = getattr(service, "consensus_service", None)
    items: list[dict] = []
    for envelope in service.list_pending_consensus_envelopes():
        if envelope.operation_type != "WALLET_TRANSFER" or envelope.sender_wallet != wallet_id:
            continue
        submission = (
            consensus.get_submission(envelope.operation_id)
            if consensus is not None and callable(getattr(consensus, "get_submission", None))
            else None
        )
        finality = service.ledger_operation_finality(envelope.operation_id)
        payload = dict(envelope.payload)
        items.append(
            {
                "operation_id": envelope.operation_id,
                "operation_type": envelope.operation_type,
                "sender_wallet": envelope.sender_wallet,
                "sender_sequence": envelope.sender_sequence,
                "recipient_wallet": payload.get("recipient_wallet"),
                "amount_q_atoms": payload.get("amount"),
                "network_fee_q_atoms": STANDARD_NETWORK_FEE_Q_ATOMS,
                "created_at": envelope.created_at,
                "memo_hash": payload.get("memo_hash"),
                "submission_status": submission.status.value if submission is not None else None,
                "status": finality.get("status"),
                "finality": finality,
                "error": submission.error if submission is not None else None,
            }
        )
    return items


def _wallet_identity_operation_payload(
    service: HypervisorService,
    wallet_id: str | None,
) -> list[dict]:
    """Expose identity-registration lifecycle without exposing signing material."""
    if not wallet_id:
        return []
    consensus = getattr(service, "consensus_service", None)
    items: list[dict] = []
    for envelope in service.list_pending_consensus_envelopes():
        if envelope.operation_type != "WALLET_IDENTITY_REGISTER":
            continue
        payload = dict(envelope.payload)
        if envelope.sender_wallet != wallet_id and payload.get("wallet_id") != wallet_id:
            continue
        submission = (
            consensus.get_submission(envelope.operation_id)
            if consensus is not None and callable(getattr(consensus, "get_submission", None))
            else None
        )
        finality = service.ledger_operation_finality(envelope.operation_id)
        submission_status = submission.status.value if submission is not None else None
        finality_status = finality.get("status")
        if submission_status == "failed" or finality_status == "failed":
            state = "rejected"
        elif finality.get("consensus_finalized") or finality_status in {
            "consensus_finalized",
            "locally_observed_finalized",
        }:
            state = "finalized"
        else:
            state = "pending"
        items.append(
            {
                "operation_id": envelope.operation_id,
                "operation_type": envelope.operation_type,
                "wallet_id": wallet_id,
                "sender_sequence": envelope.sender_sequence,
                "created_at": envelope.created_at,
                "submission_status": submission_status,
                "status": finality_status,
                "state": state,
                "finality": finality,
                "error": submission.error if submission is not None else None,
            }
        )
    return items


def build_operator_wallet_payload(
    service: HypervisorService,
    *,
    usage_limit: int = 100,
    allocation_limit: int = 100,
    dispute_limit: int = 100,
    economics_recent_limit: int = 8,
    economics_history_limit: int = 12,
) -> dict:
    owner_wallet = service.owner_wallet_state()
    wallet_id = owner_wallet.get("wallet_id")
    identity_read_model = (
        service.wallet_identity_read_model(str(wallet_id))
        if wallet_id is not None
        else {"identity": None, "source": "not_configured", "error": None}
    )
    wallet_identity = identity_read_model["identity"]
    balance_read_model = (
        service.wallet_balance_read_model(str(wallet_id))
        if wallet_id is not None
        else {"q_atoms": 0, "source": "not_configured", "error": None}
    )
    balance_q_atoms = cast(int, balance_read_model["q_atoms"])
    economics_history = service.export_wallet_economics_events(
        limit=economics_history_limit
    )
    pending_operations = _pending_wallet_transfer_payload(service, str(wallet_id) if wallet_id else None)
    identity_operations = _wallet_identity_operation_payload(
        service,
        str(wallet_id) if wallet_id else None,
    )
    latest_identity_operation = identity_operations[-1] if identity_operations else None
    if wallet_identity is not None:
        identity_registration_state = "registered"
    elif latest_identity_operation is not None:
        identity_registration_state = latest_identity_operation["state"]
    elif identity_read_model["error"] is not None:
        identity_registration_state = "unavailable"
    else:
        identity_registration_state = "not_registered"
    active_pending_operations = [
        item
        for item in pending_operations
        if item.get("status") not in {"failed", "consensus_finalized", "local_only"}
        and item.get("submission_status") != "failed"
    ]
    ledger_events = service.list_wallet_ledger_events(limit=allocation_limit)
    ledger_operations = []
    if wallet_id is not None:
        for operation in service.list_ledger_operations(limit=allocation_limit):
            payload = operation.get("payload") if isinstance(operation, dict) else None
            recipient_wallet = payload.get("recipient_wallet") if isinstance(payload, dict) else None
            if operation.get("sender_wallet") == wallet_id or recipient_wallet == wallet_id:
                ledger_operations.append(operation)
    return {
        "owner_wallet": owner_wallet,
        "wallet_state": {
            "configured": bool(owner_wallet.get("configured")),
            "wallet_id": wallet_id,
            "canonical_balance_q_atoms": balance_q_atoms,
            "canonical_balance_q": balance_q_atoms / Q_ATOMS_PER_Q,
            "balance_source": balance_read_model["source"],
            "balance_error": balance_read_model["error"],
            "identity_state": (
                "registered" if wallet_identity is not None else "not_registered"
            ),
            "identity_registration_state": identity_registration_state,
            "identity": wallet_identity,
            "identity_source": identity_read_model["source"],
            "identity_error": identity_read_model["error"],
            "identity_operation": latest_identity_operation,
            "identity_operations": identity_operations,
            "binding_state": (
                "pending"
                if owner_wallet.get("pending_consensus") is not None
                else "bound"
                if owner_wallet.get("configured")
                else "not_configured"
            ),
            "pending_operation_count": len(active_pending_operations),
            "pending_transfer_q_atoms": sum(
                int(item.get("amount_q_atoms") or 0) for item in active_pending_operations
            ),
        },
        "node_identity": service.node_identity(),
        "usage_events": service.list_wallet_usage_events(limit=usage_limit),
        "allocation_events": service.list_wallet_allocation_events(
            limit=allocation_limit
        ),
        "dispute_events": service.list_wallet_allocation_dispute_events(
            limit=dispute_limit
        ),
        "ledger_events": ledger_events,
        "ledger_operations": ledger_operations,
        "pending_operations": pending_operations,
        "economics_summary": service.get_wallet_economics_summary(
            recent_limit=economics_recent_limit
        ),
        "economics_history": economics_history.get("items", []),
        "economics_history_cursor": {
            "next_after_event_id": economics_history.get("next_after_event_id"),
            "next_after_sequence": economics_history.get("next_after_sequence"),
            "retained_from_sequence": economics_history.get("retained_from_sequence"),
            "retained_through_sequence": economics_history.get(
                "retained_through_sequence"
            ),
            "watermark_sequence": economics_history.get("watermark_sequence"),
            "cursor_status": economics_history.get("cursor_status"),
        },
        "faucet_preview": service.get_faucet_claim_preview(),
    }


def build_wallet_ledger_events_payload(
    service: HypervisorService,
    *,
    limit: int = 100,
) -> list[dict]:
    return service.list_wallet_ledger_events(limit=limit)


def build_wallet_usage_events_payload(
    service: HypervisorService,
    *,
    limit: int = 100,
) -> list[dict]:
    return service.list_wallet_usage_events(limit=limit)


def build_wallet_session_events_payload(
    service: HypervisorService,
    *,
    limit: int = 100,
) -> list[dict]:
    return service.list_wallet_session_events(limit=limit)


def build_wallet_allocation_events_payload(
    service: HypervisorService,
    *,
    limit: int = 100,
) -> list[dict]:
    return service.list_wallet_allocation_events(limit=limit)


def build_wallet_allocation_activation_events_payload(
    service: HypervisorService,
    *,
    limit: int = 100,
) -> list[dict]:
    return service.list_wallet_allocation_activation_events(limit=limit)


def build_wallet_allocation_dispute_events_payload(
    service: HypervisorService,
    *,
    limit: int = 100,
) -> list[dict]:
    return service.list_wallet_allocation_dispute_events(limit=limit)


def build_wallet_ledger_export_payload(
    service: HypervisorService,
    *,
    after_event_id: str | None = None,
    after_sequence: int | None = None,
    limit: int = 100,
) -> dict:
    return service.export_wallet_ledger_events(
        after_event_id=after_event_id,
        after_sequence=after_sequence,
        limit=limit,
    )


def build_wallet_usage_export_payload(
    service: HypervisorService,
    *,
    after_event_id: str | None = None,
    after_sequence: int | None = None,
    limit: int = 100,
) -> dict:
    return service.export_wallet_usage_events(
        after_event_id=after_event_id,
        after_sequence=after_sequence,
        limit=limit,
    )


def build_wallet_session_export_payload(
    service: HypervisorService,
    *,
    after_event_id: str | None = None,
    after_sequence: int | None = None,
    limit: int = 100,
) -> dict:
    return service.export_wallet_session_events(
        after_event_id=after_event_id,
        after_sequence=after_sequence,
        limit=limit,
    )


def build_wallet_allocation_export_payload(
    service: HypervisorService,
    *,
    after_event_id: str | None = None,
    after_sequence: int | None = None,
    limit: int = 100,
) -> dict:
    return service.export_wallet_allocation_events(
        after_event_id=after_event_id,
        after_sequence=after_sequence,
        limit=limit,
    )


def build_wallet_allocation_activation_export_payload(
    service: HypervisorService,
    *,
    after_event_id: str | None = None,
    after_sequence: int | None = None,
    limit: int = 100,
) -> dict:
    return service.export_wallet_allocation_activation_events(
        after_event_id=after_event_id,
        after_sequence=after_sequence,
        limit=limit,
    )


def build_wallet_allocation_dispute_export_payload(
    service: HypervisorService,
    *,
    after_event_id: str | None = None,
    after_sequence: int | None = None,
    limit: int = 100,
) -> dict:
    return service.export_wallet_allocation_dispute_events(
        after_event_id=after_event_id,
        after_sequence=after_sequence,
        limit=limit,
    )


def build_ledger_operations_payload(
    service: HypervisorService,
    *,
    limit: int = 100,
) -> list[dict]:
    return service.list_ledger_operations(limit=limit)


def build_ledger_operations_export_payload(
    service: HypervisorService,
    *,
    after_operation_id: str | None = None,
    after_sequence: int | None = None,
    limit: int = 100,
) -> dict:
    return service.export_ledger_operations(
        after_operation_id=after_operation_id,
        after_sequence=after_sequence,
        limit=limit,
    )


def build_wallet_economics_summary_payload(
    service: HypervisorService,
    *,
    recent_limit: int = 10,
) -> dict:
    return service.get_wallet_economics_summary(recent_limit=recent_limit)


def build_wallet_economics_export_payload(
    service: HypervisorService,
    *,
    after_event_id: str | None = None,
    after_sequence: int | None = None,
    limit: int = 100,
) -> dict:
    return service.export_wallet_economics_events(
        after_event_id=after_event_id,
        after_sequence=after_sequence,
        limit=limit,
    )


def build_wallet_faucet_preview_payload(service: HypervisorService) -> dict:
    return service.get_faucet_claim_preview()


def build_wallet_endpoint_publications_payload(
    endpoint_publication_service: EndpointPublicationService | None,
    *,
    endpoint_id: str | None = None,
) -> dict:
    if endpoint_publication_service is None:
        return {"items": []}
    records = endpoint_publication_service.list_publications(endpoint_id=endpoint_id)
    return {"items": [record.model_dump(mode="json") for record in records]}


def build_wallet_endpoint_publications_export_payload(
    endpoint_publication_service: EndpointPublicationService | None,
    *,
    endpoint_id: str | None = None,
    limit: int = 100,
) -> dict:
    if endpoint_publication_service is None:
        return {"items": [], "count": 0}
    records = endpoint_publication_service.list_publications(endpoint_id=endpoint_id)
    items = [record.model_dump(mode="json") for record in records[: max(0, limit)]]
    return {"items": items, "count": len(items)}
