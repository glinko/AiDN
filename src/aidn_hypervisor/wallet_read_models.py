from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
    from aidn_hypervisor.service import HypervisorService


def build_operator_wallet_payload(
    service: HypervisorService,
    *,
    usage_limit: int = 100,
    allocation_limit: int = 100,
    dispute_limit: int = 100,
    economics_recent_limit: int = 8,
    economics_history_limit: int = 12,
) -> dict:
    economics_history = service.export_wallet_economics_events(
        limit=economics_history_limit
    )
    return {
        "owner_wallet": service.owner_wallet_state(),
        "node_identity": service.node_identity(),
        "usage_events": service.list_wallet_usage_events(limit=usage_limit),
        "allocation_events": service.list_wallet_allocation_events(
            limit=allocation_limit
        ),
        "dispute_events": service.list_wallet_allocation_dispute_events(
            limit=dispute_limit
        ),
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
