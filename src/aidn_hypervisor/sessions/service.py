from datetime import datetime, timedelta, timezone
from uuid import uuid4

from aidn_hypervisor.sessions.models import (
    EndpointSession,
    LockedDeposit,
    SessionResult,
    SessionSettlementSummary,
)


class SessionService:
    def __init__(self, store, event_recorder=None) -> None:
        self.store = store
        self.event_recorder = event_recorder

    def _emit(
        self,
        *,
        event_type: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        if self.event_recorder is None:
            return
        self.event_recorder(
            event_type=event_type,
            message=message,
            details=dict(details or {}),
        )

    def list_sessions(self) -> list[EndpointSession]:
        return self.store.list_sessions()

    def get_session(self, session_id: str) -> SessionResult:
        session = self.store.get_session(session_id)
        deposit = self.store.get_deposit_for_session(session_id)
        return SessionResult(session=session, deposit=deposit)

    def require_active_session(
        self,
        *,
        endpoint_id: str,
        session_id: str,
    ) -> EndpointSession:
        session = self.store.get_session(session_id)
        if session.endpoint_id != endpoint_id:
            raise ValueError(f"Session does not belong to endpoint: {session_id}")
        if session.status != "active":
            raise ValueError(f"Session is not active: {session_id}")
        return session

    def open_session(
        self,
        *,
        endpoint_id: str,
        client_wallet: str,
        provider_wallet: str,
        node_id: str,
        deposit_q: float,
        session_policy: dict,
    ) -> SessionResult:
        minimum_deposit = float(session_policy.get("minimum_deposit", 0.0) or 0.0)
        if deposit_q < minimum_deposit:
            raise ValueError("deposit is below the minimum deposit")
        max_sessions = int(session_policy.get("max_concurrent_sessions", 1) or 1)
        queue_policy = str(session_policy.get("queue_policy", "busy") or "busy")
        now = datetime.now(timezone.utc)
        active_sessions = [
            session
            for session in self.store.list_sessions()
            if session.endpoint_id == endpoint_id and session.status == "active"
        ]
        queued_sessions = [
            session
            for session in self.store.list_sessions()
            if session.endpoint_id == endpoint_id and session.status == "queued"
        ]
        slot_available = len(active_sessions) < max_sessions
        if not slot_available and queue_policy == "busy":
            raise ValueError(f"Endpoint is busy: {endpoint_id}")

        status = "active" if slot_available else "queued"
        reserved_slot_index = len(active_sessions) if slot_available else None
        started_at = now.isoformat() if slot_available else None
        last_activity_at = now.isoformat() if slot_available else None
        idle_timeout_seconds = int(session_policy.get("idle_timeout_seconds", 600) or 600)
        maximum_session_duration_seconds = int(
            session_policy.get("maximum_session_duration_seconds", 3600) or 3600
        )
        session = EndpointSession(
            session_id=f"sess-{uuid4().hex[:12]}",
            endpoint_id=endpoint_id,
            client_wallet=client_wallet,
            provider_wallet=provider_wallet,
            node_id=node_id,
            status=status,
            created_at=now.isoformat(),
            started_at=started_at,
            last_activity_at=last_activity_at,
            expires_at=(now + timedelta(seconds=maximum_session_duration_seconds)).isoformat(),
            idle_deadline_at=(now + timedelta(seconds=idle_timeout_seconds)).isoformat(),
            deposit_locked_q=deposit_q,
            reserved_slot_index=reserved_slot_index,
            queue_policy_snapshot=queue_policy,
            session_policy_snapshot=dict(session_policy),
            close_reason=("waiting_for_slot" if queued_sessions or not slot_available else None),
        )
        deposit = LockedDeposit(
            deposit_id=f"dep-{uuid4().hex[:12]}",
            session_id=session.session_id,
            wallet_id=client_wallet,
            locked_q=deposit_q,
            consumed_q=0.0,
            refunded_q=0.0,
            status="locked",
        )
        self.store.save_session(session)
        self.store.save_deposit(deposit)
        self._emit(
            event_type="session.deposit_locked",
            message="session deposit locked",
            details={
                "session_id": session.session_id,
                "endpoint_id": endpoint_id,
                "client_wallet": client_wallet,
                "provider_wallet": provider_wallet,
                "locked_q": deposit_q,
                "status": status,
            },
        )
        return SessionResult(session=session, deposit=deposit)

    def close_session(self, session_id: str) -> SessionResult:
        current = self.store.get_session(session_id)
        deposit = self.store.get_deposit_for_session(session_id)
        if current.status == "closed":
            return SessionResult(session=current, deposit=deposit)
        result = self._settle_and_close_session(
            current,
            deposit,
            closed_at=datetime.now(timezone.utc),
            close_reason=current.close_reason or "closed_by_client",
        )
        self._promote_next_waiting_session(endpoint_id=current.endpoint_id)
        return result

    def touch_session(self, session_id: str) -> EndpointSession:
        current = self.store.get_session(session_id)
        if current.status != "active":
            raise ValueError(f"Session is not active: {session_id}")
        now = datetime.now(timezone.utc)
        idle_timeout_seconds = int(
            current.session_policy_snapshot.get("idle_timeout_seconds", 600) or 600
        )
        updated = current.model_copy(
            update={
                "last_activity_at": now.isoformat(),
                "idle_deadline_at": (
                    now + timedelta(seconds=idle_timeout_seconds)
                ).isoformat(),
            }
        )
        self.store.save_session(updated)
        return updated

    def record_usage_charge(
        self,
        session_id: str,
        *,
        amount_q: float,
        request_count: int = 1,
    ) -> SessionResult:
        if amount_q < 0.0:
            raise ValueError("usage charge cannot be negative")
        if request_count < 0:
            raise ValueError("request_count cannot be negative")
        current = self.store.get_session(session_id)
        if current.status != "active":
            raise ValueError(f"Session is not active: {session_id}")
        deposit = self.store.get_deposit_for_session(session_id)
        next_consumed_q = deposit.consumed_q + amount_q
        if next_consumed_q > deposit.locked_q:
            raise ValueError(f"Session deposit exhausted: {session_id}")
        updated_deposit = deposit.model_copy(
            update={
                "consumed_q": next_consumed_q,
            }
        )
        updated_session = current.model_copy(
            update={
                "request_count": current.request_count + request_count,
            }
        )
        self.store.save_session(updated_session)
        self.store.save_deposit(updated_deposit)
        self._emit(
            event_type="session.usage_charged",
            message="session usage charge recorded",
            details={
                "session_id": session_id,
                "endpoint_id": current.endpoint_id,
                "amount_q": amount_q,
                "consumed_q": next_consumed_q,
                "usage_charged_q": next_consumed_q,
                "remaining_q": max(0.0, deposit.locked_q - next_consumed_q),
            },
        )
        return SessionResult(session=updated_session, deposit=updated_deposit)

    def sweep_idle_sessions(
        self,
        *,
        now: datetime | None = None,
    ) -> list[SessionResult]:
        current_time = now or datetime.now(timezone.utc)
        closed: list[SessionResult] = []
        for session in self.store.list_sessions():
            if session.status != "active":
                continue
            try:
                idle_deadline = datetime.fromisoformat(session.idle_deadline_at)
            except ValueError:
                idle_deadline = current_time
            if idle_deadline > current_time:
                continue
            deposit = self.store.get_deposit_for_session(session.session_id)
            self._emit(
                event_type="session.idle_timeout",
                message="session closed after idle timeout",
                details={
                    "session_id": session.session_id,
                    "endpoint_id": session.endpoint_id,
                    "idle_deadline_at": session.idle_deadline_at,
                },
            )
            result = self._settle_and_close_session(
                session,
                deposit,
                closed_at=current_time,
                close_reason="idle_timeout",
            )
            self._promote_next_waiting_session(endpoint_id=session.endpoint_id)
            closed.append(result)
        return closed

    def _settle_and_close_session(
        self,
        session: EndpointSession,
        deposit: LockedDeposit,
        *,
        closed_at: datetime,
        close_reason: str,
    ) -> SessionResult:
        minimum_session_fee = float(
            session.session_policy_snapshot.get("minimum_session_fee", 0.0) or 0.0
        )
        idle_fee_per_minute = float(
            session.session_policy_snapshot.get("idle_fee_per_minute", 0.0) or 0.0
        )
        no_request = session.request_count == 0
        idle_fee_charged_q = 0.0
        if not no_request and close_reason == "idle_timeout" and idle_fee_per_minute > 0.0:
            try:
                last_activity_at = datetime.fromisoformat(
                    session.last_activity_at or session.created_at
                )
            except ValueError:
                last_activity_at = closed_at
            idle_minutes = max(
                0.0,
                (closed_at - last_activity_at).total_seconds() / 60.0,
            )
            idle_fee_charged_q = idle_minutes * idle_fee_per_minute
        charged_q = min(
            deposit.locked_q,
            deposit.consumed_q + idle_fee_charged_q,
        )
        minimum_session_fee_q = 0.0
        if no_request and minimum_session_fee > 0.0:
            minimum_session_fee_q = min(deposit.locked_q, minimum_session_fee)
            charged_q = minimum_session_fee_q
            idle_fee_charged_q = 0.0
        refunded_q = max(0.0, deposit.locked_q - charged_q)
        settlement = SessionSettlementSummary(
            usage_charged_q=deposit.consumed_q,
            idle_fee_charged_q=idle_fee_charged_q,
            minimum_session_fee_q=minimum_session_fee_q,
            charged_q=charged_q,
            refunded_q=refunded_q,
            payout_q=charged_q,
            no_request=no_request,
        )
        closed = session.model_copy(
            update={
                "status": "closed",
                "reserved_slot_index": None,
                "close_reason": close_reason,
            }
        )
        released = deposit.model_copy(
            update={
                "status": "released",
                "consumed_q": charged_q,
                "refunded_q": refunded_q,
            }
        )
        self.store.save_session(closed)
        self.store.save_deposit(released)
        self._emit(
            event_type="session.settled",
            message="session settled and released",
            details={
                "session_id": session.session_id,
                "endpoint_id": session.endpoint_id,
                "charged_q": settlement.charged_q,
                "refunded_q": settlement.refunded_q,
                "payout_q": settlement.payout_q,
                "usage_charged_q": settlement.usage_charged_q,
                "idle_fee_charged_q": settlement.idle_fee_charged_q,
                "minimum_session_fee_q": settlement.minimum_session_fee_q,
                "no_request": settlement.no_request,
                "close_reason": close_reason,
            },
        )
        return SessionResult(session=closed, deposit=released, settlement=settlement)

    def _promote_next_waiting_session(self, *, endpoint_id: str) -> None:
        active_sessions = [
            session
            for session in self.store.list_sessions()
            if session.endpoint_id == endpoint_id and session.status == "active"
        ]
        waiting = sorted(
            [
                session
                for session in self.store.list_sessions()
                if session.endpoint_id == endpoint_id and session.status == "queued"
            ],
            key=lambda session: session.created_at,
        )
        if not waiting:
            return
        candidate = waiting[0]
        max_sessions = int(
            candidate.session_policy_snapshot.get("max_concurrent_sessions", 1) or 1
        )
        if len(active_sessions) >= max_sessions:
            return
        now = datetime.now(timezone.utc).isoformat()
        promoted = candidate.model_copy(
            update={
                "status": "active",
                "started_at": now,
                "last_activity_at": now,
                "reserved_slot_index": len(active_sessions),
                "close_reason": None,
            }
        )
        self.store.save_session(promoted)
