from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from aidn_hypervisor.wallet_models import (
    WalletAllocationActivationEvent,
    WalletAllocationDisputeEvent,
    WalletAllocationEvent,
)


class WalletAllocationService:
    """Allocation wallet lifecycle, grace windows, and dispute handling."""

    def __init__(self, host) -> None:
        self._host = host

    def list_wallet_allocation_events(self, *, limit: int | None = None) -> list[dict]:
        self.reconcile_wallet_allocation_events()
        return self._list_tail(self._host._wallet_allocation_events, limit=limit)

    def list_wallet_allocation_activation_events(
        self,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        return self._list_tail(self._host._wallet_allocation_activation_events, limit=limit)

    def list_wallet_allocation_dispute_events(
        self,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        return self._list_tail(self._host._wallet_allocation_dispute_events, limit=limit)

    def export_wallet_allocation_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        self.reconcile_wallet_allocation_events()
        return self._host._export_wallet_event_stream(
            self._host._wallet_allocation_events,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_allocation_activation_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._host._export_wallet_event_stream(
            self._host._wallet_allocation_activation_events,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_allocation_dispute_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._host._export_wallet_event_stream(
            self._host._wallet_allocation_dispute_events,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def reopen_wallet_allocation_event(
        self,
        event_id: str,
        *,
        reason: str | None = None,
    ) -> dict:
        self.reconcile_wallet_allocation_events()
        event = self._find_allocation_event(event_id)
        if event.get("settlement_status") != "closed":
            raise ValueError(f"Wallet allocation event is not closed: {event_id}")
        if event.get("dispute_status") == "open":
            raise ValueError(f"Wallet allocation event is disputed: {event_id}")

        current_time = self._host._wallet_allocation_now()
        timestamp = datetime.fromtimestamp(current_time, timezone.utc).isoformat()
        normalized_reason = reason.strip() if isinstance(reason, str) else None
        closed_immediately = self._host.wallet_allocation_grace_period_seconds == 0
        event["settlement_status"] = "closed" if closed_immediately else "grace"
        event["grace_expires_at"] = (
            None
            if closed_immediately
            else datetime.fromtimestamp(
                current_time + self._host.wallet_allocation_grace_period_seconds,
                timezone.utc,
            ).isoformat()
        )
        event["closed_at"] = timestamp if closed_immediately else None
        event["reopened_at"] = timestamp
        event["reopen_reason"] = normalized_reason or None
        event["reopen_count"] = int(event.get("reopen_count", 0)) + 1
        self._host.record_event(
            event_type="wallet.allocation_reopened",
            message="wallet allocation settlement reopened",
            bundle_id=event["bundle_id"],
            details={
                "event_id": event["event_id"],
                "sequence_id": event["sequence_id"],
                "allocation_id": event["allocation_id"],
                "owner_id": event["owner_id"],
                "reopen_count": event["reopen_count"],
                "reopen_reason": event["reopen_reason"],
                "settlement_status": event["settlement_status"],
            },
        )
        self._host._persist_state()
        return dict(event)

    def dispute_wallet_allocation_event(self, event_id: str, *, reason: str) -> dict:
        self.reconcile_wallet_allocation_events()
        event = self._find_allocation_event(event_id)
        if event.get("dispute_status") == "open":
            raise ValueError(f"Wallet allocation event is already disputed: {event_id}")

        timestamp = datetime.fromtimestamp(
            self._host._wallet_allocation_now(), timezone.utc
        ).isoformat()
        dispute_id = str(uuid4())
        event["dispute_id"] = dispute_id
        event["dispute_opened_at"] = timestamp
        event["dispute_reason"] = reason
        event["dispute_status"] = "open"
        event["dispute_opened_by"] = self._host.operator_id
        event["dispute_resolved_at"] = None
        event["dispute_resolution"] = None
        event["dispute_resolution_reason"] = None
        dispute_payload = WalletAllocationDisputeEvent(
            sequence_id=self._host._next_wallet_allocation_dispute_sequence,
            event_id=str(uuid4()),
            dispute_id=dispute_id,
            allocation_event_id=event["event_id"],
            allocation_id=event["allocation_id"],
            owner_id=event["owner_id"],
            node_id=self._host.node_id,
            operator_id=self._host.operator_id,
            bundle_id=event["bundle_id"],
            workload_type=event["workload_type"],
            event_type="opened",
            occurred_at=timestamp,
            reason=reason,
            opened_by=self._host.operator_id,
        ).model_dump(mode="json")
        self._host._wallet_allocation_dispute_events.append(dispute_payload)
        self._host._next_wallet_allocation_dispute_sequence += 1
        self._host._append_wallet_ledger_event(
            stream="allocation_dispute",
            source_event=dispute_payload,
            event_type="opened",
            owner_id=str(dispute_payload["owner_id"]),
            allocation_id=str(dispute_payload["allocation_id"]),
            bundle_id=str(dispute_payload["bundle_id"]),
            workload_type=str(dispute_payload["workload_type"]),
            amount_q=0.0,
        )
        self._host.record_event(
            event_type="wallet.allocation_disputed",
            message="wallet allocation settlement disputed",
            bundle_id=event["bundle_id"],
            details={
                "event_id": event["event_id"],
                "sequence_id": event["sequence_id"],
                "dispute_id": dispute_id,
                "allocation_id": event["allocation_id"],
                "owner_id": event["owner_id"],
                "dispute_reason": event["dispute_reason"],
                "settlement_status": event["settlement_status"],
                "dispute_status": event["dispute_status"],
            },
        )
        self._host._persist_state()
        return dict(event)

    def resolve_wallet_allocation_dispute(
        self,
        event_id: str,
        *,
        resolution: str,
        reason: str | None = None,
    ) -> dict:
        self.reconcile_wallet_allocation_events()
        event = self._find_allocation_event(event_id)
        if event.get("dispute_status") != "open":
            raise ValueError(f"Wallet allocation event is not disputed: {event_id}")

        current_time = self._host._wallet_allocation_now()
        timestamp = datetime.fromtimestamp(current_time, timezone.utc).isoformat()
        normalized_reason = reason.strip() if isinstance(reason, str) else None
        event["dispute_status"] = "resolved"
        event["dispute_resolved_at"] = timestamp
        event["dispute_resolution"] = resolution
        event["dispute_resolution_reason"] = normalized_reason or None
        if resolution == "accepted":
            closed_immediately = self._host.wallet_allocation_grace_period_seconds == 0
            event["settlement_status"] = "closed" if closed_immediately else "grace"
            event["grace_expires_at"] = (
                None
                if closed_immediately
                else datetime.fromtimestamp(
                    current_time + self._host.wallet_allocation_grace_period_seconds,
                    timezone.utc,
                ).isoformat()
            )
            event["closed_at"] = timestamp if closed_immediately else None
            event["reopened_at"] = timestamp
            event["reopen_reason"] = normalized_reason or event.get("dispute_reason")
            event["reopen_count"] = int(event.get("reopen_count", 0)) + 1
        elif resolution in {"rejected", "withdrawn"}:
            event["settlement_status"] = "closed"
            event["grace_expires_at"] = None
            event["closed_at"] = timestamp
        else:
            raise ValueError(f"Unsupported dispute resolution: {resolution}")
        dispute_payload = WalletAllocationDisputeEvent(
            sequence_id=self._host._next_wallet_allocation_dispute_sequence,
            event_id=str(uuid4()),
            dispute_id=str(event["dispute_id"]),
            allocation_event_id=event["event_id"],
            allocation_id=event["allocation_id"],
            owner_id=event["owner_id"],
            node_id=self._host.node_id,
            operator_id=self._host.operator_id,
            bundle_id=event["bundle_id"],
            workload_type=event["workload_type"],
            event_type="resolved",
            occurred_at=timestamp,
            resolution=resolution,
            resolution_reason=normalized_reason or None,
        ).model_dump(mode="json")
        self._host._wallet_allocation_dispute_events.append(dispute_payload)
        self._host._next_wallet_allocation_dispute_sequence += 1
        self._host._append_wallet_ledger_event(
            stream="allocation_dispute",
            source_event=dispute_payload,
            event_type="resolved",
            owner_id=str(dispute_payload["owner_id"]),
            allocation_id=str(dispute_payload["allocation_id"]),
            bundle_id=str(dispute_payload["bundle_id"]),
            workload_type=str(dispute_payload["workload_type"]),
            amount_q=0.0,
        )
        self._host.record_event(
            event_type="wallet.allocation_dispute_resolved",
            message="wallet allocation dispute resolved",
            bundle_id=event["bundle_id"],
            details={
                "event_id": event["event_id"],
                "sequence_id": event["sequence_id"],
                "dispute_id": event["dispute_id"],
                "allocation_id": event["allocation_id"],
                "owner_id": event["owner_id"],
                "dispute_resolution": event["dispute_resolution"],
                "dispute_resolution_reason": event["dispute_resolution_reason"],
                "settlement_status": event["settlement_status"],
            },
        )
        self._host._persist_state()
        return dict(event)

    def record_wallet_allocation_event(self, allocation: dict, *, status: str) -> dict:
        request = allocation["request"]
        matching_usage_events = [
            event
            for event in self._host._wallet_usage_events
            if event.get("allocation_id") == allocation["allocation_id"]
        ]
        closed_immediately = self._host.wallet_allocation_grace_period_seconds == 0
        current_time = self._host._wallet_allocation_now()
        event = WalletAllocationEvent(
            sequence_id=self._host._next_wallet_allocation_sequence,
            event_id=str(uuid4()),
            allocation_id=str(allocation["allocation_id"]),
            owner_id=str(request["owner_id"]),
            node_id=self._host.node_id,
            operator_id=self._host.operator_id,
            bundle_id=str(allocation["bundle_id"]),
            workload_type=str(allocation["workload_type"]),
            status=status,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            settlement_status="closed" if closed_immediately else "grace",
            grace_expires_at=(
                None
                if closed_immediately
                else datetime.fromtimestamp(
                    current_time + self._host.wallet_allocation_grace_period_seconds,
                    timezone.utc,
                ).isoformat()
            ),
            closed_at=(
                datetime.fromtimestamp(current_time, timezone.utc).isoformat()
                if closed_immediately
                else None
            ),
            reopened_at=None,
            reopen_reason=None,
            reopen_count=0,
            dispute_id=None,
            dispute_opened_at=None,
            dispute_reason=None,
            dispute_status="none",
            dispute_opened_by=None,
            dispute_resolved_at=None,
            dispute_resolution=None,
            dispute_resolution_reason=None,
            usage_event_count=len(matching_usage_events),
            usage_total_q=sum(
                float(item["quote"]["charges"]["total_q"])
                for item in matching_usage_events
            ),
        )
        payload = event.model_dump(mode="json")
        self._host._wallet_allocation_events.append(payload)
        self._host._next_wallet_allocation_sequence += 1
        self._host._append_wallet_ledger_event(
            stream="allocation",
            source_event=payload,
            event_type=str(payload["status"]),
            owner_id=str(payload["owner_id"]),
            allocation_id=str(payload["allocation_id"]),
            bundle_id=str(payload["bundle_id"]),
            workload_type=str(payload["workload_type"]),
            status=str(payload["status"]),
            settlement_status=str(payload["settlement_status"]),
            amount_q=float(payload["usage_total_q"]),
        )
        self._host.record_event(
            event_type="wallet.allocation_finalized",
            message="wallet allocation finalization recorded",
            bundle_id=str(allocation["bundle_id"]),
            runtime_id=allocation.get("runtime_id"),
            details={
                "event_id": payload["event_id"],
                "sequence_id": payload["sequence_id"],
                "allocation_id": payload["allocation_id"],
                "owner_id": payload["owner_id"],
                "status": payload["status"],
                "settlement_status": payload["settlement_status"],
                "usage_event_count": payload["usage_event_count"],
                "usage_total_q": payload["usage_total_q"],
            },
        )
        return payload

    def record_wallet_allocation_activation_hook(
        self,
        allocation: dict,
        *,
        activation_source: str,
    ) -> None:
        request = allocation["request"]
        event = WalletAllocationActivationEvent(
            sequence_id=self._host._next_wallet_allocation_activation_sequence,
            event_id=str(uuid4()),
            allocation_id=allocation["allocation_id"],
            owner_id=request["owner_id"],
            node_id=self._host.node_id,
            operator_id=self._host.operator_id,
            bundle_id=allocation["bundle_id"],
            workload_type=allocation["workload_type"],
            runtime_id=allocation.get("runtime_id"),
            endpoint=allocation.get("endpoint"),
            activation_source=activation_source,
            lease_seconds=request["lease_seconds"],
            occurred_at=datetime.now(timezone.utc).isoformat(),
        )
        payload = event.model_dump(mode="json")
        self._host._wallet_allocation_activation_events.append(payload)
        self._host._next_wallet_allocation_activation_sequence += 1
        self._host._append_wallet_ledger_event(
            stream="allocation_activation",
            source_event=payload,
            event_type="activated",
            owner_id=str(payload["owner_id"]),
            allocation_id=str(payload["allocation_id"]),
            bundle_id=str(payload["bundle_id"]),
            workload_type=str(payload["workload_type"]),
            amount_q=0.0,
        )
        self._host.record_event(
            event_type="wallet.allocation_activated",
            message="wallet allocation activation recorded",
            bundle_id=allocation["bundle_id"],
            runtime_id=allocation.get("runtime_id"),
            details={
                "sequence_id": payload["sequence_id"],
                "event_id": payload["event_id"],
                "activation_source": payload["activation_source"],
                "allocation_id": payload["allocation_id"],
                "owner_id": payload["owner_id"],
                "bundle_id": payload["bundle_id"],
                "workload_type": payload["workload_type"],
                "runtime_id": payload["runtime_id"],
                "endpoint": payload["endpoint"],
                "lease_seconds": payload["lease_seconds"],
            },
        )

    def reconcile_wallet_allocation_events(self) -> None:
        changed = False
        current_time = self._host._wallet_allocation_now()
        for event in self._host._wallet_allocation_events:
            dispute_open = event.get("dispute_status") == "open"
            if event.get("settlement_status") == "closed" and not dispute_open:
                continue

            matching_usage_events = [
                usage_event
                for usage_event in self._host._wallet_usage_events
                if usage_event.get("allocation_id") == event["allocation_id"]
            ]
            next_usage_event_count = len(matching_usage_events)
            next_usage_total_q = sum(
                float(item["quote"]["charges"]["total_q"])
                for item in matching_usage_events
            )
            if event["usage_event_count"] != next_usage_event_count:
                event["usage_event_count"] = next_usage_event_count
                changed = True
            if event["usage_total_q"] != next_usage_total_q:
                event["usage_total_q"] = next_usage_total_q
                changed = True

            if dispute_open:
                continue

            grace_expires_at = event.get("grace_expires_at")
            if grace_expires_at is None:
                continue
            try:
                expires_at_ts = datetime.fromisoformat(grace_expires_at).timestamp()
            except ValueError:
                expires_at_ts = current_time
            if expires_at_ts > current_time:
                continue
            event["settlement_status"] = "closed"
            event["closed_at"] = datetime.fromtimestamp(
                current_time, timezone.utc
            ).isoformat()
            changed = True

        if changed:
            self._host._persist_state()

    def _find_allocation_event(self, event_id: str) -> dict:
        event = next(
            (
                item
                for item in self._host._wallet_allocation_events
                if item["event_id"] == event_id
            ),
            None,
        )
        if event is None:
            raise KeyError(event_id)
        return event

    @staticmethod
    def _list_tail(events: list[dict], *, limit: int | None = None) -> list[dict]:
        items = list(events)
        if limit is None or limit >= len(items):
            return items
        return items[-limit:]
