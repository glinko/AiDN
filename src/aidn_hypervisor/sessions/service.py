from datetime import datetime, timedelta, timezone
from uuid import uuid4

from aidn_hypervisor.sessions.models import EndpointSession, LockedDeposit, SessionResult


class SessionService:
    def __init__(self, store) -> None:
        self.store = store

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
        return SessionResult(session=session, deposit=deposit)

    def close_session(self, session_id: str) -> SessionResult:
        current = self.store.get_session(session_id)
        deposit = self.store.get_deposit_for_session(session_id)
        if current.status == "closed":
            return SessionResult(session=current, deposit=deposit)
        closed = current.model_copy(
            update={
                "status": "closed",
                "reserved_slot_index": None,
                "close_reason": current.close_reason or "closed_by_client",
            }
        )
        released = deposit.model_copy(
            update={
                "status": "released",
                "refunded_q": max(0.0, deposit.locked_q - deposit.consumed_q),
            }
        )
        self.store.save_session(closed)
        self.store.save_deposit(released)
        self._promote_next_waiting_session(endpoint_id=current.endpoint_id)
        return SessionResult(session=closed, deposit=released)

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
