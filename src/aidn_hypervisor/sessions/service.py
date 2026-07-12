import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from aidn_hypervisor.accounting.models import (
    SessionAccountingCheckpoint,
    UsageAcknowledgement,
    UsageReport,
    VerificationStatus,
    usage_acknowledgement_hash,
    usage_report_hash,
)
from aidn_hypervisor.sessions.models import (
    EndpointSession,
    LockedDeposit,
    ProxySessionBinding,
    SessionResult,
    SessionSettlementSummary,
)


class SessionService:
    def __init__(
        self,
        store,
        event_recorder=None,
        operation_recorder=None,
        network_fee_q: float = 0.01,
    ) -> None:
        self.store = store
        self.event_recorder = event_recorder
        self.operation_recorder = operation_recorder
        self.network_fee_q = max(0.0, float(network_fee_q))

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

    def get_proxy_session_binding(self, local_session_id: str) -> ProxySessionBinding:
        return self.store.get_proxy_session_binding(local_session_id)

    def try_get_proxy_session_binding(
        self, local_session_id: str
    ) -> ProxySessionBinding | None:
        return self.store.try_get_proxy_session_binding(local_session_id)

    def save_proxy_session_binding(
        self, binding: ProxySessionBinding
    ) -> ProxySessionBinding:
        self.store.save_proxy_session_binding(binding)
        return binding

    def _checkpoint_from_session(
        self,
        session: EndpointSession,
    ) -> SessionAccountingCheckpoint:
        checkpoint_payload = dict(session.accounting_checkpoint or {})
        if checkpoint_payload:
            return SessionAccountingCheckpoint.model_validate(checkpoint_payload)
        return SessionAccountingCheckpoint(
            last_accepted_report_sequence=session.last_accepted_report_sequence,
            last_accepted_usage_charged_q=session.last_accepted_usage_charged_q,
        )

    def _replace_accounting_state(
        self,
        current: EndpointSession,
        *,
        report_chain: list[dict] | None = None,
        acknowledgement_chain: list[dict] | None = None,
        checkpoint: SessionAccountingCheckpoint,
        accounting_status: str,
    ) -> EndpointSession:
        next_report_chain = (
            list(report_chain)
            if report_chain is not None
            else list(current.usage_report_chain or [])
        )
        next_acknowledgement_chain = (
            list(acknowledgement_chain)
            if acknowledgement_chain is not None
            else list(current.usage_acknowledgement_chain or [])
        )
        updated = current.model_copy(
            update={
                "usage_report_chain": next_report_chain,
                "usage_acknowledgement_chain": next_acknowledgement_chain,
                "last_usage_report_snapshot": (
                    next_report_chain[-1] if next_report_chain else {}
                ),
                "last_usage_acknowledgement_snapshot": (
                    next_acknowledgement_chain[-1]
                    if next_acknowledgement_chain
                    else {}
                ),
                "accounting_status": accounting_status,
                "accounting_checkpoint": checkpoint.model_dump(mode="json"),
                "last_accepted_report_sequence": checkpoint.last_accepted_report_sequence,
                "last_accepted_usage_charged_q": checkpoint.last_accepted_usage_charged_q,
            }
        )
        self.store.save_session(updated)
        return updated

    def _validate_usage_report_identity(
        self,
        *,
        current: EndpointSession,
        session_id: str,
        report: UsageReport,
    ) -> None:
        if report.session_id != session_id:
            raise ValueError("usage report session_id does not match target session")
        if report.endpoint_id != current.endpoint_id:
            raise ValueError("usage report endpoint_id does not match target session")

    def _validate_usage_acknowledgement_identity(
        self,
        *,
        session_id: str,
        acknowledgement: UsageAcknowledgement,
    ) -> None:
        if acknowledgement.session_id != session_id:
            raise ValueError(
                "usage acknowledgement session_id does not match target session"
            )

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

    def require_request_budget(
        self,
        *,
        endpoint_id: str,
        session_id: str,
    ) -> EndpointSession:
        session = self.require_active_session(
            endpoint_id=endpoint_id,
            session_id=session_id,
        )
        deposit = self.store.get_deposit_for_session(session_id)
        contract = dict(session.accounting_contract_snapshot or {})
        maximum_request_charge = contract.get("maximum_request_charge")
        if maximum_request_charge is None:
            return session
        remaining_q = max(0.0, float(deposit.locked_q) - float(deposit.consumed_q))
        if remaining_q < float(maximum_request_charge):
            raise ValueError(
                "remaining deposit is below the maximum request charge"
            )
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
        accounting_contract: dict | None = None,
    ) -> SessionResult:
        session_policy_snapshot = dict(session_policy)
        session_policy_snapshot.setdefault("network_fee_q", self.network_fee_q)
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
            session_policy_snapshot=session_policy_snapshot,
            accounting_contract_snapshot=dict(accounting_contract or {}),
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
        if self.operation_recorder is not None:
            session_policy_hash = hashlib.sha256(
                json.dumps(session_policy_snapshot, sort_keys=True).encode("utf-8")
            ).hexdigest()
            accounting_contract_hash = hashlib.sha256(
                json.dumps(dict(accounting_contract or {}), sort_keys=True).encode("utf-8")
            ).hexdigest()
            self.operation_recorder(
                operation_type="SESSION_OPEN",
                origin_type="wallet",
                fee_class="session",
                initiator_id=client_wallet,
                sender_wallet=client_wallet,
                fee_payer=client_wallet,
                payload={
                    "session_id": session.session_id,
                    "consumer_hypervisor_id": node_id,
                    "provider_hypervisor_id": node_id,
                    "endpoint_id": endpoint_id,
                    "session_policy_hash": f"sha256:{session_policy_hash}",
                    "accounting_contract_hash": f"sha256:{accounting_contract_hash}",
                    "deposit_amount": deposit_q,
                    "open_expiration": session.expires_at,
                },
                created_at=session.created_at,
                emitted_events=["SessionOpened"],
            )
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

    def record_usage_checkpoint(
        self,
        session_id: str,
        *,
        usage_report: dict,
        accepted_charge_q: float,
        verification_status: VerificationStatus = "accepted_unverified",
    ) -> EndpointSession:
        report = UsageReport.model_validate(usage_report)
        acknowledgement = UsageAcknowledgement(
            session_id=session_id,
            sequence=report.sequence,
            provider_report_hash=usage_report_hash(report),
            verification_status=verification_status,
            signature=f"local-ack:{report.report_id}",
        )
        self.record_usage_report(
            session_id,
            usage_report=report.model_dump(mode="json"),
            acknowledgement_timeout_seconds=0,
        )
        return self.record_usage_acknowledgement(
            session_id,
            usage_acknowledgement=acknowledgement.model_dump(mode="json"),
            accepted_charge_q=accepted_charge_q,
        )

    def record_usage_report(
        self,
        session_id: str,
        *,
        usage_report: dict,
        acknowledgement_timeout_seconds: int,
    ) -> EndpointSession:
        current = self.store.get_session(session_id)
        report = UsageReport.model_validate(usage_report)
        self._validate_usage_report_identity(
            current=current,
            session_id=session_id,
            report=report,
        )
        checkpoint = self._checkpoint_from_session(current)
        report_hash = usage_report_hash(report)
        if (
            report.sequence == checkpoint.last_report_sequence
            and report_hash == checkpoint.last_report_hash
        ):
            return current
        expected_sequence = (
            1
            if checkpoint.last_report_sequence is None
            else checkpoint.last_report_sequence + 1
        )
        same_sequence_different_hash = (
            report.sequence == checkpoint.last_report_sequence
            and report_hash != checkpoint.last_report_hash
        )
        chain_continuity_ok = (
            report.sequence == expected_sequence
            and (
                checkpoint.last_report_hash is None
                or report.previous_report_hash == checkpoint.last_report_hash
            )
        )
        next_checkpoint = checkpoint.model_copy(deep=True)
        try:
            report_created_at = datetime.fromisoformat(report.created_at)
        except ValueError:
            report_created_at = datetime.now(timezone.utc)
        report_chain = list(current.usage_report_chain or [])
        report_chain.append(report.model_dump(mode="json"))
        accounting_status = "ack_pending"
        if same_sequence_different_hash or not chain_continuity_ok:
            accounting_status = "mismatch"
            next_checkpoint.mismatch_open = True
        else:
            next_checkpoint.last_report_sequence = report.sequence
            next_checkpoint.last_report_hash = report_hash
            next_checkpoint.mismatch_open = False
            next_checkpoint.ack_deadline_at = (
                report_created_at
                + timedelta(seconds=max(0, acknowledgement_timeout_seconds))
            ).isoformat()
        updated = self._replace_accounting_state(
            current,
            report_chain=report_chain,
            checkpoint=next_checkpoint,
            accounting_status=accounting_status,
        )
        self._emit(
            event_type=(
                "session.accounting_mismatch"
                if accounting_status == "mismatch"
                else "session.usage_reported"
            ),
            message=(
                "session usage report chain mismatch recorded"
                if accounting_status == "mismatch"
                else "session usage report recorded"
            ),
            details={
                "session_id": session_id,
                "report_id": report.report_id,
                "sequence": report.sequence,
                "report_hash": report_hash,
                "ack_deadline_at": next_checkpoint.ack_deadline_at,
            },
        )
        return updated

    def record_usage_acknowledgement(
        self,
        session_id: str,
        *,
        usage_acknowledgement: dict,
        accepted_charge_q: float,
    ) -> EndpointSession:
        current = self.store.get_session(session_id)
        acknowledgement = UsageAcknowledgement.model_validate(usage_acknowledgement)
        self._validate_usage_acknowledgement_identity(
            session_id=session_id,
            acknowledgement=acknowledgement,
        )
        checkpoint = self._checkpoint_from_session(current)
        next_checkpoint = checkpoint.model_copy(deep=True)
        acknowledgement_hash = usage_acknowledgement_hash(acknowledgement)
        acknowledgement_chain = list(current.usage_acknowledgement_chain or [])
        acknowledgement_chain.append(acknowledgement.model_dump(mode="json"))
        next_checkpoint.last_ack_sequence = acknowledgement.sequence
        next_checkpoint.last_ack_hash = acknowledgement_hash
        valid_current_head = (
            checkpoint.last_report_sequence == acknowledgement.sequence
            and checkpoint.last_report_hash == acknowledgement.provider_report_hash
        )
        ack_eligible_head = current.accounting_status == "ack_pending" and not checkpoint.mismatch_open
        if (
            acknowledgement.verification_status == "mismatch"
            or not valid_current_head
            or not ack_eligible_head
        ):
            next_checkpoint.mismatch_open = True
            accounting_status = "mismatch"
        elif acknowledgement.verification_status in {
            "accepted_unverified",
            "verified",
            "statistically_plausible",
        }:
            next_checkpoint.last_accepted_report_sequence = acknowledgement.sequence
            next_checkpoint.last_accepted_report_hash = acknowledgement.provider_report_hash
            next_checkpoint.last_accepted_usage_charged_q = max(0.0, float(accepted_charge_q))
            next_checkpoint.mismatch_open = False
            next_checkpoint.ack_deadline_at = None
            accounting_status = "open"
        else:
            next_checkpoint.ack_deadline_at = None
            accounting_status = "open"
        updated = self._replace_accounting_state(
            current,
            acknowledgement_chain=acknowledgement_chain,
            checkpoint=next_checkpoint,
            accounting_status=accounting_status,
        )
        self._emit(
            event_type=(
                "session.accounting_mismatch"
                if accounting_status == "mismatch"
                else "session.usage_acknowledged"
            ),
            message=(
                "session accounting mismatch recorded"
                if accounting_status == "mismatch"
                else "session usage acknowledgement recorded"
            ),
            details={
                "session_id": session_id,
                "sequence": acknowledgement.sequence,
                "verification_status": acknowledgement.verification_status,
                "accepted_charge_q": updated.last_accepted_usage_charged_q,
            },
        )
        return updated

    def expire_usage_acknowledgement(
        self,
        session_id: str,
        *,
        now: datetime | None = None,
    ) -> EndpointSession:
        current = self.store.get_session(session_id)
        checkpoint = self._checkpoint_from_session(current)
        if current.accounting_status != "ack_pending" or checkpoint.ack_deadline_at is None:
            return current
        current_time = now or datetime.now(timezone.utc)
        try:
            ack_deadline = datetime.fromisoformat(checkpoint.ack_deadline_at)
        except ValueError:
            ack_deadline = current_time
        if ack_deadline > current_time:
            return current
        next_checkpoint = checkpoint.model_copy(deep=True)
        next_checkpoint.mismatch_open = True
        updated = self._replace_accounting_state(
            current,
            checkpoint=next_checkpoint,
            accounting_status="force_settle_required",
        )
        self._emit(
            event_type="session.accounting_timeout",
            message="session usage acknowledgement expired",
            details={
                "session_id": session_id,
                "ack_deadline_at": checkpoint.ack_deadline_at,
            },
        )
        return updated

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
        network_fee_q = float(
            session.session_policy_snapshot.get("network_fee_q", self.network_fee_q) or 0.0
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
        accepted_usage_charged_q = (
            session.last_accepted_usage_charged_q
            if session.last_accepted_report_sequence is not None
            else deposit.consumed_q
        )
        payout_q = round(
            min(
            deposit.locked_q,
            accepted_usage_charged_q + idle_fee_charged_q,
            ),
            6,
        )
        minimum_session_fee_q = 0.0
        if no_request and minimum_session_fee > 0.0:
            minimum_session_fee_q = min(deposit.locked_q, minimum_session_fee)
            payout_q = minimum_session_fee_q
            idle_fee_charged_q = 0.0
        network_fee_charged_q = round(
            min(
                network_fee_q,
                max(0.0, deposit.locked_q - payout_q),
            ),
            6,
        )
        charged_q = round(
            min(
                deposit.locked_q,
                payout_q + network_fee_charged_q,
            ),
            6,
        )
        refunded_q = round(max(0.0, deposit.locked_q - charged_q), 6)
        settlement = SessionSettlementSummary(
            usage_charged_q=accepted_usage_charged_q,
            idle_fee_charged_q=idle_fee_charged_q,
            minimum_session_fee_q=minimum_session_fee_q,
            network_fee_q=network_fee_charged_q,
            charged_q=charged_q,
            refunded_q=refunded_q,
            payout_q=payout_q,
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
        if self.operation_recorder is not None:
            self.operation_recorder(
                operation_type="SESSION_SETTLE",
                origin_type="multi_party",
                fee_class="session",
                initiator_id=session.session_id,
                fee_payer=session.client_wallet,
                payload={
                    "session_id": session.session_id,
                    "endpoint_id": session.endpoint_id,
                    "charged_q": settlement.charged_q,
                    "refunded_q": settlement.refunded_q,
                    "payout_q": settlement.payout_q,
                    "close_reason": close_reason,
                    "last_accepted_report_sequence": session.last_accepted_report_sequence,
                },
                created_at=closed_at.isoformat(),
                emitted_events=["SessionSettled"],
            )
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
                "network_fee_q": settlement.network_fee_q,
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
