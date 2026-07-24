from __future__ import annotations


class WalletApplicationService:
    """Public wallet economics and allocation workflow facade."""

    def __init__(self, host) -> None:
        self._host = host

    def list_wallet_usage_events(self, *, limit: int | None = None) -> list[dict]:
        return self._host._wallet_economics_service.list_wallet_usage_events(limit=limit)

    def list_wallet_session_events(self, *, limit: int | None = None) -> list[dict]:
        return self._host._wallet_economics_service.list_wallet_session_events(limit=limit)

    def list_wallet_ledger_events(self, *, limit: int | None = None) -> list[dict]:
        return self._host._wallet_economics_service.list_wallet_ledger_events(limit=limit)

    def list_recyclable_removals(self) -> list[dict]:
        return self._host._wallet_economics_service.list_recyclable_removals()

    def list_faucet_claims(self) -> list[dict]:
        return self._host._wallet_economics_service.list_faucet_claims()

    def list_epoch_reward_budgets(self) -> list[dict]:
        return self._host._wallet_economics_service.list_epoch_reward_budgets()

    def get_faucet_claim_preview(self) -> dict:
        return self._host._wallet_economics_service.get_faucet_claim_preview()

    def get_wallet_economics_summary(self, *, recent_limit: int = 10) -> dict:
        return self._host._wallet_economics_service.get_wallet_economics_summary(
            recent_limit=recent_limit
        )

    def claim_faucet_share(self) -> dict:
        return self._host._wallet_economics_service.claim_faucet_share()

    def list_wallet_allocation_events(self, *, limit: int | None = None) -> list[dict]:
        return self._host._wallet_allocation_service.list_wallet_allocation_events(
            limit=limit
        )

    def list_wallet_allocation_activation_events(
        self,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        return self._host._wallet_allocation_service.list_wallet_allocation_activation_events(
            limit=limit
        )

    def list_wallet_allocation_dispute_events(
        self,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        return self._host._wallet_allocation_service.list_wallet_allocation_dispute_events(
            limit=limit
        )

    def export_wallet_usage_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._host._wallet_economics_service.export_wallet_usage_events(
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
        return self._host._wallet_economics_service.export_wallet_session_events(
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
        return self._host._wallet_economics_service.export_wallet_ledger_events(
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
        return self._host._wallet_economics_service.export_wallet_economics_events(
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_allocation_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._host._wallet_allocation_service.export_wallet_allocation_events(
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
        return self._host._wallet_allocation_service.export_wallet_allocation_activation_events(
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
        return self._host._wallet_allocation_service.export_wallet_allocation_dispute_events(
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
        return self._host._wallet_allocation_service.reopen_wallet_allocation_event(
            event_id,
            reason=reason,
        )

    def dispute_wallet_allocation_event(self, event_id: str, *, reason: str) -> dict:
        return self._host._wallet_allocation_service.dispute_wallet_allocation_event(
            event_id,
            reason=reason,
        )

    def resolve_wallet_allocation_dispute(
        self,
        event_id: str,
        *,
        resolution: str,
        reason: str | None = None,
    ) -> dict:
        return self._host._wallet_allocation_service.resolve_wallet_allocation_dispute(
            event_id,
            resolution=resolution,
            reason=reason,
        )

    def hold_wallet_allocation_event(self, event_id: str, *, reason: str) -> dict:
        return self._host._wallet_allocation_service.hold_wallet_allocation_event(
            event_id,
            reason=reason,
        )

    def release_wallet_allocation_event(
        self,
        event_id: str,
        *,
        reason: str,
        target_status: str = "closed",
    ) -> dict:
        return self._host._wallet_allocation_service.release_wallet_allocation_event(
            event_id,
            reason=reason,
            target_status=target_status,
        )

    def apply_wallet_allocation_correction(
        self,
        event_id: str,
        *,
        reason: str,
        effective_usage_total_q: float,
        annotations: dict | None = None,
        resolution_note: str | None = None,
    ) -> dict:
        return self._host._wallet_allocation_service.apply_wallet_allocation_correction(
            event_id,
            reason=reason,
            effective_usage_total_q=effective_usage_total_q,
            annotations=annotations,
            resolution_note=resolution_note,
        )

    def list_wallet_allocation_correction_events(
        self, *, limit: int | None = None
    ) -> list[dict]:
        return self._host._wallet_allocation_service.list_wallet_allocation_correction_events(
            limit=limit
        )

    def export_wallet_allocation_correction_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._host._wallet_allocation_service.export_wallet_allocation_correction_events(
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def quote_wallet_usage(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        fixed_request_count: int = 1,
    ) -> dict:
        return self._host._wallet_economics_service.quote_wallet_usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            fixed_request_count=fixed_request_count,
        )

    def record_wallet_usage(
        self,
        *,
        owner_id: str,
        bundle_id: str,
        workload_type: str,
        task_id: str | None = None,
        allocation_id: str | None = None,
        input_tokens: int,
        output_tokens: int,
        fixed_request_count: int = 1,
        measurement_kind: str = "exact",
        measurement_source: str = "manual",
        source: str = "manual",
    ) -> dict:
        return self._host._wallet_economics_service.record_wallet_usage(
            owner_id=owner_id,
            bundle_id=bundle_id,
            workload_type=workload_type,
            task_id=task_id,
            allocation_id=allocation_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            fixed_request_count=fixed_request_count,
            measurement_kind=measurement_kind,
            measurement_source=measurement_source,
            source=source,
        )
