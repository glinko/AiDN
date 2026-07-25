from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from aidn_hypervisor.state import JournalEvent
from aidn_hypervisor.wallet_models import WalletSessionEvent


class EventProjectionService:
    """Journal recording and wallet-facing event projections."""

    def __init__(self, host) -> None:
        self._host = host

    def record_event(
        self,
        *,
        event_type: str,
        message: str,
        task_id: str | None = None,
        bundle_id: str | None = None,
        runtime_id: str | None = None,
        details: dict | None = None,
    ) -> JournalEvent:
        event = JournalEvent(
            timestamp=datetime.now(UTC).isoformat(),
            event_type=event_type,
            message=message,
            task_id=task_id,
            bundle_id=bundle_id,
            runtime_id=runtime_id,
            details=dict(details or {}),
        )
        self._host._events.append(event)
        if (
            self.record_wallet_session_event_from_journal(event)
            or self.record_wallet_validation_event_from_journal(event)
        ):
            self._host._persist_state()
        return event

    def record_wallet_session_event_from_journal(self, event: JournalEvent) -> bool:
        event_type_map = {
            "session.deposit_locked": "deposit_locked",
            "session.usage_charged": "usage_charged",
            "session.settled": "settled",
        }
        normalized_type = event_type_map.get(event.event_type)
        if normalized_type is None:
            return False
        session_id = event.details.get("session_id")
        endpoint_id = event.details.get("endpoint_id")
        if session_id is None or endpoint_id is None:
            return False
        session_result = None
        session_service = getattr(self._host, "session_service", None)
        if session_service is not None:
            try:
                session_result = session_service.get_session(str(session_id))
            except KeyError:
                session_result = None
        session = session_result.session if session_result is not None else None
        deposit = session_result.deposit if session_result is not None else None
        locked_q = float(
            event.details.get(
                "locked_q",
                deposit.locked_q if deposit is not None else 0.0,
            )
        )
        usage_charged_q = float(
            event.details.get(
                "usage_charged_q",
                deposit.consumed_q if deposit is not None else 0.0,
            )
        )
        charged_q = float(
            event.details.get(
                "charged_q",
                event.details.get(
                    "amount_q",
                    deposit.consumed_q if deposit is not None else 0.0,
                ),
            )
        )
        refunded_q = float(
            event.details.get(
                "refunded_q",
                deposit.refunded_q if deposit is not None else 0.0,
            )
        )
        network_fee_q = float(event.details.get("network_fee_q", 0.0) or 0.0)
        remaining_q = float(
            event.details.get(
                "remaining_q",
                max(
                    0.0,
                    locked_q - (deposit.consumed_q if deposit is not None else charged_q),
                ),
            )
        )
        session_event = WalletSessionEvent(
            sequence_id=self._host._next_wallet_session_sequence,
            event_id=str(uuid4()),
            session_id=str(session_id),
            endpoint_id=str(endpoint_id),
            owner_id=str(
                event.details.get(
                    "client_wallet",
                    session.client_wallet if session is not None else "",
                )
            ),
            provider_wallet=str(
                event.details.get(
                    "provider_wallet",
                    session.provider_wallet if session is not None else "",
                )
            ),
            node_id=self._host.node_id,
            operator_id=self._host.operator_id,
            event_type=normalized_type,
            occurred_at=event.timestamp,
            task_id=event.task_id,
            status=str(
                event.details.get(
                    "status",
                    session.status if session is not None else "unknown",
                )
            ),
            settlement_status="closed" if normalized_type == "settled" else "open",
            locked_q=locked_q,
            charged_q=charged_q,
            refunded_q=refunded_q,
            remaining_q=remaining_q,
            usage_charged_q=usage_charged_q,
            idle_fee_charged_q=float(event.details.get("idle_fee_charged_q", 0.0)),
            minimum_session_fee_q=float(
                event.details.get("minimum_session_fee_q", 0.0)
            ),
            network_fee_q=network_fee_q,
            close_reason=(
                str(event.details["close_reason"])
                if event.details.get("close_reason") is not None
                else None
            ),
        ).model_dump(mode="json")
        self._host._wallet_session_events.append(session_event)
        self._host._next_wallet_session_sequence += 1
        session_amount_q = (
            float(session_event["locked_q"])
            if normalized_type == "deposit_locked"
            else float(session_event["charged_q"])
        )
        self._host._append_wallet_ledger_event(
            stream="session",
            source_event=session_event,
            event_type=normalized_type,
            owner_id=str(session_event["owner_id"]),
            task_id=(
                str(session_event["task_id"])
                if session_event.get("task_id") is not None
                else None
            ),
            session_id=str(session_event["session_id"]),
            endpoint_id=str(session_event["endpoint_id"]),
            status=str(session_event["status"]),
            settlement_status=str(session_event["settlement_status"]),
            amount_q=session_amount_q,
        )
        if normalized_type == "settled" and network_fee_q > 0.0:
            self._host.record_recyclable_removal(
                category="network_fee",
                amount_q=network_fee_q,
                owner_id=str(session_event["owner_id"]),
                source_event_type="session_network_fee_charged",
                source_reference=str(session_event["session_id"]),
                removed_at=str(session_event["occurred_at"]),
            )
        return True

    def record_wallet_validation_event_from_journal(self, event: JournalEvent) -> bool:
        validation_event_types = {
            "validation_bond_locked",
            "validation_bond_refunded",
            "validation_bond_forfeited",
            "validation_request_passed",
            "validation_request_failed",
            "maintenance_validation_passed",
            "maintenance_validation_failed",
        }
        if event.event_type not in validation_event_types:
            return False
        owner_id = event.details.get("owner_wallet") or event.details.get("owner_id")
        endpoint_id = event.details.get("endpoint_id")
        if owner_id is None or endpoint_id is None:
            return False
        source_event = {
            "event_id": str(uuid4()),
            "sequence_id": len(self._host._wallet_ledger_events) + 1,
            "occurred_at": event.timestamp,
            "journal_event_type": event.event_type,
            "details": dict(event.details),
        }
        self._host._append_wallet_ledger_event(
            stream="validation",
            source_event=source_event,
            event_type=event.event_type,
            owner_id=str(owner_id),
            endpoint_id=str(endpoint_id),
            status=str(
                event.details.get("outcome") or event.details.get("status") or "recorded"
            ),
            amount_q=float(event.details.get("amount_q", 0.0) or 0.0),
        )
        if event.event_type == "validation_bond_forfeited":
            amount_q = float(event.details.get("amount_q", 0.0) or 0.0)
            if amount_q > 0.0:
                self._host.record_recyclable_removal(
                    category="validation_bond_forfeiture",
                    amount_q=amount_q,
                    owner_id=str(owner_id),
                    source_event_type=event.event_type,
                    source_reference=str(event.details.get("bond_id") or endpoint_id),
                    source_epoch_id=(
                        str(event.details["source_epoch_id"])
                        if event.details.get("source_epoch_id") is not None
                        else None
                    ),
                    removed_at=event.timestamp,
                )
        return True
