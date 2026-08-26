from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from aidn_hypervisor.economics.models import (
    EpochRewardBudget,
    RecyclableRemoval,
)
from aidn_hypervisor.wallet import quote_usage_q
from aidn_hypervisor.wallet_models import WalletLedgerEvent, WalletUsageEvent


class WalletEconomicsService:
    """Wallet usage metering and epoch economics orchestration."""

    def __init__(self, host) -> None:
        self._host = host

    def list_wallet_usage_events(self, *, limit: int | None = None) -> list[dict]:
        return self._list_tail(self._host._wallet_usage_events, limit=limit)

    def list_wallet_session_events(self, *, limit: int | None = None) -> list[dict]:
        return self._list_tail(self._host._wallet_session_events, limit=limit)

    def list_wallet_ledger_events(self, *, limit: int | None = None) -> list[dict]:
        return self._list_tail(self._host._wallet_ledger_events, limit=limit)

    def list_recyclable_removals(self) -> list[dict]:
        return list(self._host._recyclable_removals)

    def list_faucet_claims(self) -> list[dict]:
        return list(self._host._faucet_claims)

    def list_epoch_reward_budgets(self) -> list[dict]:
        return list(self._host._epoch_reward_budgets)

    def get_faucet_claim_preview(self) -> dict:
        owner_wallet = self._host.owner_wallet_state()
        return {
            "eligible": False,
            "reason": "external_faucet_service_required",
            "message": "Faucet claims are handled by the external services/aidn-faucet service",
            "epoch_id": None,
            "wallet_id": owner_wallet["wallet_id"],
            "share_q": 0.0,
            "claimed": False,
            "claimed_q": 0.0,
            "remaining_q": 0.0,
            "active_local_endpoint_count": 0,
            "active_hypervisor_count": 0,
            "faucet_budget_q": 0.0,
            "claim": None,
        }

    def get_wallet_economics_summary(self, *, recent_limit: int = 10) -> dict:
        by_category: dict[str, float] = {}
        by_epoch: dict[str, float] = {}
        total_q = 0.0
        latest_removed_at: str | None = None
        for removal in self._host._recyclable_removals:
            amount_q = round(float(removal["amount_q"]), 6)
            total_q = round(total_q + amount_q, 6)
            category = str(removal["category"])
            by_category[category] = round(by_category.get(category, 0.0) + amount_q, 6)
            source_epoch_id = removal.get("source_epoch_id")
            if source_epoch_id:
                by_epoch[source_epoch_id] = round(
                    by_epoch.get(source_epoch_id, 0.0) + amount_q,
                    6,
                )
            latest_removed_at = str(removal["removed_at"])
        recent_count = max(0, int(recent_limit))
        recent_removals = (
            []
            if recent_count == 0
            else list(reversed(self._host._recyclable_removals[-recent_count:]))
        )
        latest_budget = self._latest_epoch_reward_budget()
        recycling = {
            "eligible_removed_q": float(latest_budget["eligible_removed_q"])
            if latest_budget is not None
            else 0.0,
            "recycle_backlog_q": float(latest_budget["recycle_backlog_q"])
            if latest_budget is not None
            else 0.0,
            "recyclable_amount_q": float(latest_budget["recyclable_amount_q"])
            if latest_budget is not None
            else 0.0,
        }
        faucet_preview = self.get_faucet_claim_preview()
        faucet = {
            # Faucet economics are owned by the external Treasury service.
            # Keep this legacy-shaped read model at zero so old dashboard
            # clients cannot mistake an epoch allocation for claimable funds.
            "carryover_q": 0.0,
            "budget_q": 0.0,
            "active_hypervisor_count": 0,
            "share_q": 0.0,
            "claimed": bool(faucet_preview["claimed"]),
            "claimed_q": float(faucet_preview["claimed_q"]),
            "remaining_q": float(faucet_preview["remaining_q"]),
            "claim": faucet_preview["claim"],
        }
        pools = {
            "consensus_budget_q": float(latest_budget["consensus_budget_q"])
            if latest_budget is not None
            else 0.0,
            "registry_budget_q": float(latest_budget["registry_budget_q"])
            if latest_budget is not None
            else 0.0,
            "validation_budget_q": float(latest_budget["validation_budget_q"])
            if latest_budget is not None
            else 0.0,
            "faucet_budget_q": 0.0,
        }
        latest_budget_breakdown = {
            "epoch_id": str(latest_budget["epoch_id"]) if latest_budget is not None else None,
            "total_authorized_q": float(latest_budget["total_authorized_q"])
            if latest_budget is not None
            else 0.0,
            "faucet_share_q": 0.0,
        }
        return {
            "base_emission_q": self._host.base_emission_q,
            "pool_shares": self._host.epoch_reward_pool_shares.model_dump(mode="json"),
            "removals": {
                "count": len(self._host._recyclable_removals),
                "total_q": total_q,
                "by_category": by_category,
                "by_epoch": by_epoch,
                "latest_removed_at": latest_removed_at,
            },
            "latest_budget": latest_budget,
            "recycling": recycling,
            "faucet": faucet,
            "pools": pools,
            "latest_budget_breakdown": latest_budget_breakdown,
            "recent_removals": recent_removals,
        }

    def claim_faucet_share(self) -> dict:
        raise ValueError(
            "Core Faucet claims are disabled; use the external services/aidn-faucet service"
        )

    def export_wallet_usage_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self.export_wallet_event_stream(
            self._host._wallet_usage_events,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_session_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self.export_wallet_event_stream(
            self._host._wallet_session_events,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_ledger_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self.export_wallet_event_stream(
            self._host._wallet_ledger_events,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_economics_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self.export_wallet_event_stream(
            self._host._wallet_economics_events,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def append_wallet_ledger_event(
        self,
        *,
        stream: str,
        source_event: dict,
        event_type: str,
        owner_id: str,
        task_id: str | None = None,
        allocation_id: str | None = None,
        session_id: str | None = None,
        endpoint_id: str | None = None,
        bundle_id: str | None = None,
        workload_type: str | None = None,
        status: str | None = None,
        settlement_status: str | None = None,
        amount_q: float = 0.0,
    ) -> dict:
        ledger_event = WalletLedgerEvent(
            sequence_id=self._host._next_wallet_ledger_sequence,
            event_id=str(uuid4()),
            stream=stream,
            stream_event_id=str(source_event["event_id"]),
            stream_sequence_id=int(source_event["sequence_id"]),
            event_type=event_type,
            occurred_at=str(source_event["occurred_at"]),
            owner_id=owner_id,
            node_id=self._host.node_id,
            operator_id=self._host.operator_id,
            task_id=task_id,
            allocation_id=allocation_id,
            session_id=session_id,
            endpoint_id=endpoint_id,
            bundle_id=bundle_id,
            workload_type=workload_type,
            status=status,
            settlement_status=settlement_status,
            amount_q=float(amount_q),
            payload=dict(source_event),
        ).model_dump(mode="json")
        self._host._wallet_ledger_events.append(ledger_event)
        self._host._next_wallet_ledger_sequence += 1
        return ledger_event

    def append_wallet_economics_event(
        self,
        *,
        event_type: str,
        occurred_at: str,
        owner_id: str,
        status: str | None = None,
        amount_q: float = 0.0,
        payload: dict,
    ) -> dict:
        economics_event = WalletLedgerEvent(
            sequence_id=self._host._next_wallet_economics_sequence,
            event_id=str(uuid4()),
            stream="economics",
            stream_event_id=str(
                payload.get("removal_id")
                or payload.get("claim_id")
                or payload.get("epoch_id")
                or uuid4()
            ),
            stream_sequence_id=int(payload.get("sequence_id") or 1),
            event_type=event_type,
            occurred_at=occurred_at,
            owner_id=owner_id,
            node_id=self._host.node_id,
            operator_id=self._host.operator_id,
            status=status,
            amount_q=float(amount_q),
            payload=dict(payload),
        ).model_dump(mode="json")
        self._host._wallet_economics_events.append(economics_event)
        self._host._next_wallet_economics_sequence += 1
        return economics_event

    def record_recyclable_removal(
        self,
        *,
        category: str,
        amount_q: float,
        owner_id: str,
        source_event_type: str,
        source_reference: str,
        source_epoch_id: str | None = None,
        removed_at: str | None = None,
    ) -> dict:
        removal = RecyclableRemoval(
            sequence_id=self._host._next_recyclable_removal_sequence,
            removal_id=str(uuid4()),
            category=category,
            amount_q=float(amount_q),
            owner_id=owner_id,
            removed_at=removed_at or datetime.now(UTC).isoformat(),
            source_event_type=source_event_type,
            source_reference=source_reference,
            source_epoch_id=source_epoch_id,
        ).model_dump(mode="json")
        self._host._recyclable_removals.append(removal)
        self._host._next_recyclable_removal_sequence += 1
        self.append_wallet_ledger_event(
            stream="economics",
            source_event={
                "event_id": removal["removal_id"],
                "sequence_id": removal["sequence_id"],
                "occurred_at": removal["removed_at"],
                **removal,
            },
            event_type="recyclable_removed",
            owner_id=str(removal["owner_id"]),
            status=str(removal["category"]),
            amount_q=float(removal["amount_q"]),
        )
        self.append_wallet_economics_event(
            event_type="recyclable_removed",
            occurred_at=str(removal["removed_at"]),
            owner_id=str(removal["owner_id"]),
            status=str(removal["category"]),
            amount_q=float(removal["amount_q"]),
            payload=removal,
        )
        self._host._persist_state()
        return removal

    def derive_epoch_reward_budget(
        self,
        *,
        epoch_id: str,
        source_epoch_id: str,
        recycle_backlog_q: float = 0.0,
        faucet_carryover_q: float = 0.0,
        active_hypervisor_count: int = 0,
    ) -> dict:
        eligible_removed_q = round(
            sum(
                float(item["amount_q"])
                for item in self._host._recyclable_removals
                if item.get("source_epoch_id") == source_epoch_id
            ),
            6,
        )
        budget = EpochRewardBudget(
            epoch_id=epoch_id,
            derived_at=datetime.now(UTC).isoformat(),
            base_emission_q=self._host.base_emission_q,
            eligible_removed_q=eligible_removed_q,
            recycle_backlog_q=float(recycle_backlog_q),
            faucet_carryover_q=float(faucet_carryover_q),
            active_hypervisor_count=int(active_hypervisor_count),
            pool_shares=self._host.epoch_reward_pool_shares,
        ).model_dump(mode="json")
        self._host._epoch_reward_budgets = [
            item for item in self._host._epoch_reward_budgets if item["epoch_id"] != epoch_id
        ]
        self._host._epoch_reward_budgets.append(budget)
        self.append_wallet_economics_event(
            event_type="epoch_reward_budget_derived",
            occurred_at=str(budget["derived_at"]),
            owner_id=self._host.operator_id,
            status=str(budget["epoch_id"]),
            amount_q=float(budget["total_authorized_q"]),
            payload=budget,
        )
        self._host.record_ledger_operation(
            operation_type="EPOCH_TRANSITION",
            origin_type="protocol",
            fee_class="protocol_sponsored",
            initiator_id=epoch_id,
            payload={
                "closing_epoch": source_epoch_id,
                "opening_epoch": epoch_id,
                "reward_budget_reference": epoch_id,
                "eligible_removed_q": float(budget["eligible_removed_q"]),
                "recycle_backlog_q": float(budget["recycle_backlog_q"]),
                "total_authorized_q": float(budget["total_authorized_q"]),
                "active_hypervisor_count": int(budget["active_hypervisor_count"]),
            },
            created_at=str(budget["derived_at"]),
            emitted_events=["EpochTransitionRecorded"],
        )
        self._host._persist_state()
        return budget

    def export_wallet_event_stream(
        self,
        events: list[dict],
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        items = list(events)
        retained_from_sequence = items[0]["sequence_id"] if items else None
        retained_through_sequence = items[-1]["sequence_id"] if items else None
        cursor_status = "ok"
        start_index = 0

        if after_sequence is not None:
            if retained_from_sequence is not None and after_sequence < retained_from_sequence - 1:
                cursor_status = "stale"
            else:
                start_index = len(items)
                for index, event in enumerate(items):
                    if event["sequence_id"] > after_sequence:
                        start_index = index
                        break
        elif after_event_id is not None:
            start_index = len(items)
            found = False
            for index, event in enumerate(items):
                if event["event_id"] == after_event_id:
                    start_index = index + 1
                    found = True
                    break
            if not found and items:
                cursor_status = "stale"
                start_index = 0

        page = items[start_index : start_index + limit]
        has_more = start_index + limit < len(items)
        return {
            "items": page,
            "next_after_event_id": page[-1]["event_id"] if page else after_event_id,
            "next_after_sequence": page[-1]["sequence_id"] if page else after_sequence,
            "retained_from_sequence": retained_from_sequence,
            "retained_through_sequence": retained_through_sequence,
            "watermark_sequence": retained_through_sequence,
            "has_more": has_more,
            "cursor_status": cursor_status,
        }

    def quote_wallet_usage(
        self,
        *,
        input_tokens: int | None,
        cached_input_tokens: int | None = None,
        output_tokens: int | None = None,
        fixed_request_count: int = 1,
        audio_input_seconds: float | None = None,
        audio_input_milliseconds: int | None = None,
    ) -> dict:
        return quote_usage_q(
            pricing=self._host._pricing,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            fixed_request_count=fixed_request_count,
            audio_input_seconds=audio_input_seconds,
            audio_input_milliseconds=audio_input_milliseconds,
        )

    def record_wallet_usage(
        self,
        *,
        owner_id: str,
        bundle_id: str,
        workload_type: str,
        task_id: str | None = None,
        allocation_id: str | None = None,
        input_tokens: int | None,
        cached_input_tokens: int | None = None,
        output_tokens: int | None = None,
        fixed_request_count: int = 1,
        audio_input_seconds: float | None = None,
        audio_input_milliseconds: int | None = None,
        measurement_kind: str = "exact",
        measurement_source: str = "manual",
        source: str = "manual",
    ) -> dict:
        event = WalletUsageEvent(
            sequence_id=self._host._next_wallet_usage_sequence,
            event_id=str(uuid4()),
            owner_id=owner_id,
            node_id=self._host.node_id,
            operator_id=self._host.operator_id,
            task_id=task_id,
            allocation_id=allocation_id,
            bundle_id=bundle_id,
            workload_type=workload_type,
            measurement_kind=measurement_kind,
            measurement_source=measurement_source,
            source=source,
            occurred_at=datetime.now(UTC).isoformat(),
            quote=self.quote_wallet_usage(
                input_tokens=input_tokens,
                cached_input_tokens=cached_input_tokens,
                output_tokens=output_tokens,
                fixed_request_count=fixed_request_count,
                audio_input_seconds=audio_input_seconds,
                audio_input_milliseconds=audio_input_milliseconds,
            ),
        )
        payload = event.model_dump(mode="json")
        self._host._wallet_usage_events.append(payload)
        self._host._next_wallet_usage_sequence += 1
        self.append_wallet_ledger_event(
            stream="usage",
            source_event=payload,
            event_type="usage_recorded",
            owner_id=owner_id,
            task_id=task_id,
            allocation_id=allocation_id,
            bundle_id=bundle_id,
            workload_type=workload_type,
            amount_q=float(payload["quote"]["charges"]["total_q"]),
        )
        self.prune_wallet_usage_events()
        self._host.record_event(
            event_type="wallet.usage_recorded",
            message="wallet usage event recorded",
            bundle_id=bundle_id,
            details={
                "sequence_id": payload["sequence_id"],
                "event_id": payload["event_id"],
                "owner_id": owner_id,
                "source": source,
                "measurement_kind": measurement_kind,
                "measurement_source": measurement_source,
                "task_id": task_id,
                "total_q": payload["quote"]["charges"]["total_q"],
            },
        )
        self._host._persist_state()
        return payload

    def prune_wallet_usage_events(self) -> None:
        if self._host.wallet_usage_retention_limit is None:
            return
        if len(self._host._wallet_usage_events) <= self._host.wallet_usage_retention_limit:
            return
        self._host._wallet_usage_events = self._host._wallet_usage_events[
            -self._host.wallet_usage_retention_limit :
        ]

    def _active_local_endpoint_count(self) -> int:
        endpoint_service = getattr(self._host, "endpoint_service", None)
        if endpoint_service is None:
            return 0
        return sum(
            1
            for manifest in endpoint_service.list_endpoints()
            if getattr(manifest, "status", None) == "active"
        )

    def _latest_epoch_reward_budget(self) -> dict | None:
        if not self._host._epoch_reward_budgets:
            return None
        return dict(self._host._epoch_reward_budgets[-1])

    def _latest_faucet_claim(self, epoch_id: str | None) -> dict | None:
        if epoch_id is None:
            return None
        for claim in reversed(self._host._faucet_claims):
            if claim["epoch_id"] == epoch_id:
                return dict(claim)
        return None

    @staticmethod
    def _list_tail(events: list[dict], *, limit: int | None = None) -> list[dict]:
        items = list(events)
        if limit is None or limit >= len(items):
            return items
        return items[-limit:]
