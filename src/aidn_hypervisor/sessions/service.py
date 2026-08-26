import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from aidn_hypervisor.accounting.models import (
    SessionAccountingCheckpoint,
    UsageAcknowledgement,
    UsageReport,
    VerificationStatus,
    usage_acknowledgement_hash,
    usage_report_hash,
)
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.session_failure.models import (
    FailureClass,
    RecoveryWindowConfig,
    is_terminal_status,
)
from aidn_hypervisor.session_failure.poller import SessionFailurePoller
from aidn_hypervisor.session_failure.service import SessionFailureHandler
from aidn_hypervisor.sessions.models import (
    CanonicalFundingStatus,
    EndpointSession,
    LockedDeposit,
    ProxySessionBinding,
    SessionAmendmentKind,
    SessionContractAmendment,
    SessionContractExchange,
    SessionResult,
    SessionRuntimeTerminalEvidence,
    SessionSettlementSummary,
)


def _hash_payload(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _registry_object_id(*, object_type: str, object_version: str, payload_hash: str) -> str:
    return _hash_payload(
        {
            "object_type": object_type,
            "object_version": object_version,
            "payload_hash": payload_hash,
        }
    )


def _whole_q_atoms(value: object, *, field_name: str) -> int:
    try:
        atoms = Decimal(str(value)) * 1_000_000
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name} is not a valid Q amount") from error
    if not atoms.is_finite() or atoms != atoms.to_integral_value():
        raise ValueError(f"{field_name} must map to whole q_atoms")
    return int(atoms)


class SessionService:
    def __init__(
        self,
        store,
        event_recorder=None,
        operation_recorder=None,
        network_fee_q: float = 0.01,
        registry_service: RegistryService | None = None,
        failure_handler: SessionFailureHandler | None = None,
        recovery_config: RecoveryWindowConfig | None = None,
        funding_amendment_verifier=None,
        record_open_operation: bool = True,
    ) -> None:
        self.store = store
        self.event_recorder = event_recorder
        self.operation_recorder = operation_recorder
        # In validator mode the economic Session-open intent is kept in the
        # local Session projection until its canonical transaction is final.
        self.record_open_operation = record_open_operation
        self.network_fee_q = max(0.0, float(network_fee_q))
        self.registry_service = registry_service or RegistryService()
        self._funding_amendment_verifier = funding_amendment_verifier

        # RFC-0060: failure handler (separate component)
        self.failure_handler = failure_handler
        if self.failure_handler is not None:
            # Wire up status change callback: when failure handler transitions
            # a session, sync the status back to SessionService's store
            self.failure_handler.set_status_change_callback(
                self._on_failure_status_change
            )
            # Restore failure tracking from the durable Session projection.
            for session in self.store.list_sessions():
                if session.status in {"queued", "active", "recovering"}:
                    self.failure_handler.register_session(
                        session.session_id,
                        session.status,
                        recovery_deadline=session.recovery_deadline_at,
                    )
        self._recovery_config = recovery_config

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

    def _record_accounting_operation(
        self,
        *,
        operation_type: str,
        session: EndpointSession,
        payload: dict,
        created_at: str | None,
        emitted_events: list[str] | None = None,
    ) -> None:
        if self.operation_recorder is None:
            return
        self.operation_recorder(
            operation_type=operation_type,
            origin_type="multi_party",
            fee_class="session",
            initiator_id=session.session_id,
            fee_payer=session.client_wallet,
            payload=dict(payload),
            created_at=created_at,
            emitted_events=list(emitted_events or []),
        )

    # ------------------------------------------------------------------
    # RFC-0060: Failure handler integration
    # ------------------------------------------------------------------

    def _on_failure_status_change(
        self, session_id: str, old_status: str, new_status: str
    ) -> None:
        """Callback when failure handler transitions a session status."""
        try:
            session = self.store.get_session(session_id)
            if is_terminal_status(session.status):
                # A stale recovery callback must not reactivate a terminal
                # Session after canonical Settlement or restart reconciliation.
                if self.failure_handler is not None:
                    self.failure_handler.unregister_session(session_id)
                return
            if session.status != old_status:
                return  # SessionService already moved it
            updated = session.model_copy(update={"status": new_status})
            self.store.save_session(updated)
            self._emit(
                event_type="session.failure_status_change",
                message="session status changed via failure handler",
                details={
                    "session_id": session_id,
                    "old_status": old_status,
                    "new_status": new_status,
                },
            )
        except Exception:
            pass  # Session may have been removed concurrently

    def sweep_failure_recovery(self) -> list[str]:
        """Run the failure poller to expire any recovery windows.

        Returns:
            List of session IDs that were transitioned to force_closing.
        """
        if self.failure_handler is None:
            return []
        poller = SessionFailurePoller(self.failure_handler)
        return poller.sweep_expired_recoveries()

    def classify_session_failure(
        self,
        *,
        session_id: str,
        failure_class: FailureClass,
        attribution=None,
        details: str = "",
    ) -> None:
        """Classify a session failure via the failure handler.

        The failure handler will transition the session status and
        emit events; the _on_failure_status_change callback will
        sync the status back to SessionService's store.
        """
        if self.failure_handler is None:
            return
        report = self.failure_handler.classify_failure(
            session_id=session_id,
            failure_class=failure_class,
            attribution=attribution,
            details=details,
        )
        current = self.store.get_session(session_id)
        self.store.save_session(
            current.model_copy(
                update={
                    "failure_class": report.failure_class.value,
                    "failure_attribution": report.details.get("attribution")
                    if hasattr(report, "details")
                    else None,
                    "recovery_deadline_at": self.failure_handler.get_recovery_deadline(
                        session_id
                    ),
                }
            )
        )

    def recover_session_from_failure(self, session_id: str) -> None:
        """Recover a session that is in the 'recovering' failure state."""
        if self.failure_handler is None:
            return
        current = self.store.get_session(session_id)
        if is_terminal_status(current.status):
            self.failure_handler.unregister_session(session_id)
            raise ValueError(
                f"Session {session_id} is already terminal: {current.status}"
            )
        self.failure_handler.recover_session(session_id)
        updated = self.store.get_session(session_id)
        self.store.save_session(updated.model_copy(update={"recovery_deadline_at": None}))

    def handle_proxy_failure(
        self,
        *,
        session_id: str,
        remote_endpoint_id: str,
        error: str = "",
    ) -> None:
        """Handle a proxy endpoint failure (RFC-0060 §90+)."""
        if self.failure_handler is None:
            return
        self.failure_handler.handle_proxy_failure(
            session_id=session_id,
            remote_endpoint_id=remote_endpoint_id,
            error=error,
        )

    def failure_evidence_root(self, session_id: str) -> str | None:
        """Return the durable RFC-0060 evidence commitment for a Session."""
        if self.failure_handler is None:
            return None
        return self.failure_handler.failure_evidence_root(session_id)

    def ensure_failure_evidence(
        self,
        *,
        session_id: str,
        failure_class: FailureClass,
        details: str = "",
    ) -> str | None:
        """Ensure a timeout-triggered force path has durable RFC-0060 evidence."""
        if self.failure_handler is None:
            return None
        current = self.store.get_session(session_id)
        return self.failure_handler.ensure_failure_evidence(
            session_id=session_id,
            failure_class=failure_class,
            previous_status=current.status,
            details=details,
        )

    def list_sessions(self) -> list[EndpointSession]:
        return self.store.list_sessions()

    def get_session(self, session_id: str) -> SessionResult:
        session = self.store.get_session(session_id)
        deposit = self.store.get_deposit_for_session(session_id)
        return SessionResult(session=session, deposit=deposit)

    def set_funding_amendment_verifier(self, verifier) -> None:
        """Attach the application-owned canonical funding proof verifier."""
        self._funding_amendment_verifier = verifier

    def get_session_amendments(
        self,
        session_id: str,
    ) -> list[SessionContractAmendment]:
        """Return and validate the immutable Session Contract version chain."""
        session = self.store.get_session(session_id)
        amendments: list[SessionContractAmendment] = []
        previous_effective_terms_hash = session.session_contract_hash
        previous_amendment_hash: str | None = None
        for expected_sequence, payload in enumerate(
            session.session_amendment_chain,
            start=1,
        ):
            try:
                amendment = SessionContractAmendment.model_validate(payload)
            except ValueError as error:
                raise ValueError(
                    f"Session amendment chain is invalid: {error}"
                ) from error
            if amendment.session_id != session_id:
                raise ValueError("Session amendment belongs to another Session")
            if amendment.sequence != expected_sequence:
                raise ValueError("Session amendment sequence is not contiguous")
            if amendment.previous_effective_terms_hash != previous_effective_terms_hash:
                raise ValueError("Session amendment predecessor terms hash mismatch")
            if amendment.previous_amendment_hash != previous_amendment_hash:
                raise ValueError("Session amendment predecessor hash mismatch")
            amendments.append(amendment)
            previous_effective_terms_hash = amendment.effective_terms_hash
            previous_amendment_hash = amendment.amendment_hash
        expected_sequence = len(amendments)
        if session.session_amendment_sequence != expected_sequence:
            raise ValueError("Session amendment sequence does not match chain length")
        if session.effective_terms_hash != previous_effective_terms_hash:
            raise ValueError("Session effective terms hash does not match chain head")
        return amendments

    def export_session_contract(self, session_id: str) -> SessionContractExchange:
        """Build a complete, immutable contract package for peer exchange."""
        session = self.store.get_session(session_id)
        if not session.session_contract_object_id or not session.session_contract_hash:
            raise ValueError("Session Contract object reference is missing")
        record = self.registry_service.get_registry_object(
            session.session_contract_object_id,
            include_payload=True,
        )
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Session Contract Registry object has no payload")
        if record.get("object_type") != "session_contract":
            raise ValueError("Session Contract Registry object type is invalid")
        if record.get("object_version") != session.session_contract_object_version:
            raise ValueError("Session Contract Registry object version is invalid")
        if record.get("namespace") != session.session_contract_namespace:
            raise ValueError("Session Contract Registry object namespace is invalid")
        if record.get("payload_hash") != session.session_contract_hash:
            raise ValueError("Session Contract Registry object hash differs from Session")
        amendments = self.get_session_amendments(session_id)
        return SessionContractExchange(
            session_id=session_id,
            session_contract_object_id=session.session_contract_object_id,
            session_contract_object_version=session.session_contract_object_version
            or "session-contract.v2",
            session_contract_namespace=session.session_contract_namespace or "session",
            session_contract_hash=session.session_contract_hash,
            session_contract=payload,
            amendments=amendments,
            amendment_sequence=session.session_amendment_sequence,
            effective_terms_hash=session.effective_terms_hash or session.session_contract_hash,
        )

    def import_session_contract_exchange(
        self,
        exchange: SessionContractExchange | dict,
    ) -> dict:
        """Stage a validated peer contract without changing local execution state.

        A local Session, when present, must already agree with the package. This
        prevents a remote peer from silently changing terms for an active local
        Session; the package is only an immutable Registry evidence transfer.
        """
        package = (
            exchange
            if isinstance(exchange, SessionContractExchange)
            else SessionContractExchange.model_validate(exchange)
        )
        try:
            local = self.store.get_session(package.session_id)
        except KeyError:
            local = None
        if local is not None:
            if local.session_contract_hash != package.session_contract_hash:
                raise ValueError("local Session Contract hash conflicts with exchange")
            local_amendments = self.get_session_amendments(package.session_id)
            if [item.amendment_hash for item in local_amendments] != [
                item.amendment_hash for item in package.amendments
            ]:
                raise ValueError("local Session amendment chain conflicts with exchange")
            if local.effective_terms_hash != package.effective_terms_hash:
                raise ValueError("local Session effective terms hash conflicts with exchange")

        base_record = {
            "object_id": package.session_contract_object_id,
            "object_type": "session_contract",
            "object_version": package.session_contract_object_version,
            "namespace": package.session_contract_namespace,
            "payload_hash": package.session_contract_hash,
            "payload_encoding": "canonical_json",
            "source_reference": package.session_id,
            "payload": package.session_contract,
        }
        amendment_records: list[dict] = [
            {
                "object_id": amendment.object_id,
                "object_type": "session_contract_amendment",
                "object_version": amendment.object_version,
                "namespace": "session",
                "payload_hash": amendment.amendment_hash,
                "payload_encoding": "canonical_json",
                "source_reference": package.session_id,
                "payload": amendment.evidence_payload(),
            }
            for amendment in package.amendments
        ]
        records: list[dict] = [base_record, *amendment_records]
        imported_count = 0
        for record in records:
            try:
                existing = self.registry_service.get_registry_object(
                    str(record["object_id"]),
                    include_payload=True,
                    include_expired=True,
                )
            except KeyError:
                imported_count += 1
                continue
            if any(existing.get(key) != record.get(key) for key in (
                "object_type",
                "object_version",
                "namespace",
                "payload_hash",
                "payload_encoding",
                "source_reference",
            )) or existing.get("payload") != record.get("payload"):
                raise ValueError(
                    f"conflicting Registry object for {record['object_id']}"
                )
        self.registry_service.ingest_registry_objects(records)
        return {
            "status": "IMPORTED" if imported_count else "DUPLICATE",
            "session_id": package.session_id,
            "exchange_hash": package.exchange_hash,
            "session_contract_object_id": package.session_contract_object_id,
            "session_contract_hash": package.session_contract_hash,
            "amendment_sequence": package.amendment_sequence,
            "effective_terms_hash": package.effective_terms_hash,
            "imported_object_count": imported_count,
            "local_session_reconciled": local is not None,
        }

    @staticmethod
    def _validate_session_amendment_changes(
        session: EndpointSession,
        *,
        amendment_kind: SessionAmendmentKind,
        changes: dict,
    ) -> dict:
        normalized = dict(changes)
        allowed_fields = {
            "EXPIRATION_EXTENSION": {"expires_at"},
            "REQUEST_LIMIT_INCREASE": {"max_requests"},
            "ARTIFACT_LIMIT_INCREASE": {"max_artifact_bytes"},
            "DEPOSIT_EXTENSION": {
                "additional_endpoint_payment_q_atoms",
                "additional_network_fee_q_atoms",
                "funding_operation_id",
                "previous_funding_state_hash",
                "next_funding_state_hash",
            },
            "MAXIMUM_SESSION_CHARGE_INCREASE": {
                "maximum_session_charge_q_atoms",
                "funding_operation_id",
                "previous_funding_state_hash",
                "next_funding_state_hash",
            },
        }[amendment_kind]
        unknown = sorted(set(normalized) - allowed_fields)
        if unknown:
            raise ValueError(
                "Session amendment contains unsupported fields: "
                + ", ".join(unknown)
            )
        if amendment_kind == "EXPIRATION_EXTENSION":
            expires_at = str(normalized.get("expires_at") or "")
            if not expires_at:
                raise ValueError("expiration amendment requires expires_at")
            try:
                next_expiration = datetime.fromisoformat(expires_at)
                current_expiration = datetime.fromisoformat(session.expires_at)
            except ValueError as error:
                raise ValueError("expiration amendment has invalid expires_at") from error
            if next_expiration <= current_expiration:
                raise ValueError("expiration amendment must extend Session expiration")
            normalized["expires_at"] = expires_at
        elif amendment_kind == "REQUEST_LIMIT_INCREASE":
            try:
                max_requests = int(normalized["max_requests"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("request limit amendment requires max_requests") from error
            current_limit = int(session.session_policy_snapshot.get("max_requests", 0) or 0)
            if max_requests <= current_limit:
                raise ValueError("request limit amendment must increase max_requests")
            normalized["max_requests"] = max_requests
        elif amendment_kind == "ARTIFACT_LIMIT_INCREASE":
            try:
                max_artifact_bytes = int(normalized["max_artifact_bytes"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    "artifact limit amendment requires max_artifact_bytes"
                ) from error
            current_limit = int(
                session.session_policy_snapshot.get("max_artifact_bytes", 0) or 0
            )
            if max_artifact_bytes <= current_limit:
                raise ValueError(
                    "artifact limit amendment must increase max_artifact_bytes"
                )
            normalized["max_artifact_bytes"] = max_artifact_bytes
        else:
            # These terms alter economic exposure.  The Ledger already has a
            # canonical escrow-extension operation, but this local API does
            # not own that operation's proof.  Refuse to record a contract
            # version that could claim more exposure than the bound funding.
            required = {
                "funding_operation_id",
                "previous_funding_state_hash",
                "next_funding_state_hash",
            }
            if not required.issubset(normalized):
                raise ValueError(
                    "economic Session amendments require canonical funding evidence"
                )
            if session.canonical_funding_state_hash != normalized["previous_funding_state_hash"]:
                raise ValueError(
                    "economic Session amendment predecessor funding hash mismatch"
                )
            if normalized["next_funding_state_hash"] == normalized["previous_funding_state_hash"]:
                raise ValueError(
                    "economic Session amendment must change funding state"
                )
            if amendment_kind == "MAXIMUM_SESSION_CHARGE_INCREASE":
                try:
                    maximum_session_charge_q_atoms = int(
                        normalized["maximum_session_charge_q_atoms"]
                    )
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError(
                        "maximum-charge amendment requires maximum_session_charge_q_atoms"
                    ) from error
                current_maximum = int(
                    session.session_policy_snapshot.get(
                        "maximum_session_charge_q_atoms", 0
                    )
                    or 0
                )
                if maximum_session_charge_q_atoms <= current_maximum:
                    raise ValueError(
                        "maximum-charge amendment must increase the Session maximum"
                    )
                normalized["maximum_session_charge_q_atoms"] = (
                    maximum_session_charge_q_atoms
                )
            for field_name in (
                "additional_endpoint_payment_q_atoms",
                "maximum_session_charge_q_atoms",
            ):
                if field_name in normalized:
                    try:
                        value = int(normalized[field_name])
                    except (TypeError, ValueError) as error:
                        raise ValueError(
                            f"economic Session amendment field is invalid: {field_name}"
                        ) from error
                    if value <= 0:
                        raise ValueError(
                            f"economic Session amendment field must be positive: {field_name}"
                        )
                    normalized[field_name] = value
            if amendment_kind == "DEPOSIT_EXTENSION":
                additional_network_fee_q_atoms = int(
                    normalized.get("additional_network_fee_q_atoms", 0)
                )
                if additional_network_fee_q_atoms < 0:
                    raise ValueError(
                        "additional_network_fee_q_atoms cannot be negative"
                    )
                normalized["additional_network_fee_q_atoms"] = (
                    additional_network_fee_q_atoms
                )
                if (
                    int(normalized.get("additional_endpoint_payment_q_atoms", 0))
                    + additional_network_fee_q_atoms
                    <= 0
                ):
                    raise ValueError("economic Session amendment must add funding")
        return normalized

    def _verify_session_amendment_signatures(
        self,
        session: EndpointSession,
        amendment: SessionContractAmendment,
    ) -> None:
        consumer_identity = self.registry_service.resolve_wallet_identity(
            session.consumer_refund_beneficiary
        )
        consumer_public_key = session.consumer_authorization_public_key or (
            consumer_identity.get("public_key") if consumer_identity else None
        )
        endpoint_identity = self.registry_service.resolve_wallet_identity(
            session.endpoint_payment_beneficiary
        )
        endpoint_public_key = (
            endpoint_identity.get("public_key") if endpoint_identity else None
        )
        require_both = session.economic_profile == "MVP-0001"
        if require_both and not amendment.accepted_at:
            raise ValueError("MVP Session amendment requires accepted_at")
        if require_both and (not consumer_public_key or not endpoint_public_key):
            raise ValueError(
                "MVP Session amendment requires registered Consumer and Endpoint identities"
            )
        for party, public_key, signature in (
            ("Consumer", consumer_public_key, amendment.consumer_signature),
            ("Endpoint", endpoint_public_key, amendment.endpoint_signature),
        ):
            if public_key is None:
                continue
            if not public_key.startswith("ed25519:") or not signature.startswith("ed25519:"):
                raise ValueError(f"{party} Session amendment signature is invalid")
            try:
                Ed25519PublicKey.from_public_bytes(
                    bytes.fromhex(public_key.removeprefix("ed25519:"))
                ).verify(
                    bytes.fromhex(signature.removeprefix("ed25519:")),
                    amendment.signing_payload(),
                )
            except (ValueError, InvalidSignature) as error:
                raise ValueError(f"{party} Session amendment signature is invalid") from error

    def accept_session_amendment(
        self,
        session_id: str,
        *,
        amendment_id: str,
        amendment_kind: SessionAmendmentKind,
        changes: dict,
        consumer_signature: str,
        endpoint_signature: str,
        accepted_at: str | None = None,
    ) -> EndpointSession:
        """Accept one signed, idempotent Session Contract amendment.

        The method updates only terms that have a local execution boundary.
        Economic amendments additionally require a predecessor and successor
        funding proof; the canonical Ledger operation remains authoritative
        for the actual escrow mutation.
        """
        current = self.store.get_session(session_id)
        amendments = self.get_session_amendments(session_id)
        existing = next(
            (item for item in amendments if item.amendment_id == amendment_id),
            None,
        )
        if existing is not None:
            if (
                existing.amendment_kind != amendment_kind
                or existing.changes != changes
                or existing.consumer_signature != consumer_signature
                or existing.endpoint_signature != endpoint_signature
            ):
                raise ValueError("Session amendment ID conflicts with existing amendment")
            return current
        amendable_statuses = {"queued", "active", "paused", "recovering"}
        if current.status not in amendable_statuses:
            raise ValueError("Session Contract cannot be amended in the current Session state")
        if not amendment_id.strip():
            raise ValueError("Session amendment ID is required")
        normalized_changes = self._validate_session_amendment_changes(
            current,
            amendment_kind=amendment_kind,
            changes=changes,
        )
        if amendment_kind in {
            "DEPOSIT_EXTENSION",
            "MAXIMUM_SESSION_CHARGE_INCREASE",
        }:
            if self._funding_amendment_verifier is None:
                raise ValueError(
                    "economic Session amendments require a canonical funding verifier"
                )
            if not self._funding_amendment_verifier(
                session=current,
                amendment_kind=amendment_kind,
                changes=normalized_changes,
            ):
                raise ValueError("canonical funding evidence was not verified")
        if not consumer_signature.strip() or not endpoint_signature.strip():
            raise ValueError("Session amendment requires Consumer and Endpoint signatures")
        if current.economic_profile == "MVP-0001" and accepted_at is None:
            raise ValueError("MVP Session amendment requires accepted_at")
        sequence = len(amendments) + 1
        previous_effective_terms_hash = current.effective_terms_hash or current.session_contract_hash
        if not previous_effective_terms_hash:
            raise ValueError("Session Contract has no effective terms hash")
        previous_amendment_hash = amendments[-1].amendment_hash if amendments else None
        effective_terms_hash = _hash_payload(
            {
                "previous_effective_terms_hash": previous_effective_terms_hash,
                "sequence": sequence,
                "amendment_kind": amendment_kind,
                "changes": normalized_changes,
            }
        )
        accepted_at_value = accepted_at or datetime.now(UTC).isoformat()
        evidence_payload = {
            "amendment_id": amendment_id,
            "session_id": session_id,
            "sequence": sequence,
            "previous_effective_terms_hash": previous_effective_terms_hash,
            "previous_amendment_hash": previous_amendment_hash,
            "amendment_kind": amendment_kind,
            "changes": normalized_changes,
            "affected_parties": ["CONSUMER", "ENDPOINT"],
            "consumer_signature": consumer_signature,
            "endpoint_signature": endpoint_signature,
            "accepted_at": accepted_at_value,
            "effective_terms_hash": effective_terms_hash,
            "object_version": "session-amendment.v1",
        }
        amendment_hash = _hash_payload(evidence_payload)
        object_id = _registry_object_id(
            object_type="session_contract_amendment",
            object_version="session-amendment.v1",
            payload_hash=amendment_hash,
        )
        amendment = SessionContractAmendment(
            **evidence_payload,
            amendment_hash=amendment_hash,
            object_id=object_id,
        )
        self._verify_session_amendment_signatures(current, amendment)
        amendment_record = {
            "object_id": object_id,
            "object_type": "session_contract_amendment",
            "object_version": "session-amendment.v1",
            "namespace": "session",
            "payload_hash": amendment_hash,
            "payload_encoding": "canonical_json",
            "source_reference": session_id,
            # The Registry payload is the signed evidence payload.  Its
            # hash is ``amendment_hash``; object_id and the hash itself are
            # envelope metadata, not recursive payload content.
            "payload": amendment.evidence_payload(),
        }
        session_policy_snapshot = dict(current.session_policy_snapshot)
        original_deposit = None
        session_updates = {
            "effective_terms_hash": amendment.effective_terms_hash,
            "session_amendment_sequence": sequence,
            "session_amendment_chain": [
                *current.session_amendment_chain,
                amendment.model_dump(mode="json"),
            ],
        }
        if amendment_kind == "EXPIRATION_EXTENSION":
            session_updates["expires_at"] = normalized_changes["expires_at"]
        elif amendment_kind == "REQUEST_LIMIT_INCREASE":
            session_policy_snapshot["max_requests"] = normalized_changes["max_requests"]
            session_updates["session_policy_snapshot"] = session_policy_snapshot
        elif amendment_kind == "ARTIFACT_LIMIT_INCREASE":
            session_policy_snapshot["max_artifact_bytes"] = normalized_changes[
                "max_artifact_bytes"
            ]
            session_updates["session_policy_snapshot"] = session_policy_snapshot
        updated = current.model_copy(update=session_updates)
        updated_deposit = None
        if amendment_kind == "DEPOSIT_EXTENSION":
            deposit = self.store.get_deposit_for_session(session_id)
            original_deposit = deposit
            additional_q_atoms = int(
                normalized_changes.get("additional_endpoint_payment_q_atoms", 0)
            ) + int(normalized_changes.get("additional_network_fee_q_atoms", 0))
            if additional_q_atoms <= 0:
                raise ValueError("economic Session amendment must add funding")
            updated_deposit = deposit.model_copy(
                update={
                    "locked_q": deposit.locked_q + additional_q_atoms / 1_000_000,
                }
            )
            session_updates["deposit_locked_q"] = updated_deposit.locked_q
            session_updates["deposit_locked_q_atoms"] = (
                int(current.deposit_locked_q_atoms or 0) + additional_q_atoms
            )
        if amendment_kind in {
            "DEPOSIT_EXTENSION",
            "MAXIMUM_SESSION_CHARGE_INCREASE",
        }:
            if amendment_kind == "MAXIMUM_SESSION_CHARGE_INCREASE":
                session_policy_snapshot["maximum_session_charge_q_atoms"] = (
                    normalized_changes["maximum_session_charge_q_atoms"]
                )
                session_updates["session_policy_snapshot"] = session_policy_snapshot
            session_updates["canonical_funding_state_hash"] = normalized_changes[
                "next_funding_state_hash"
            ]
            updated = current.model_copy(update=session_updates)
        self.store.save_session(updated)
        try:
            if updated_deposit is not None:
                self.store.save_deposit(updated_deposit)
            self._persist_session_contract_object(record=amendment_record)
        except Exception:
            self.store.save_session(current)
            if updated_deposit is not None:
                self.store.save_deposit(original_deposit)
            raise
        self._emit(
            event_type="session.contract_amended",
            message="Session Contract amendment accepted",
            details={
                "session_id": session_id,
                "amendment_id": amendment.amendment_id,
                "amendment_kind": amendment.amendment_kind,
                "sequence": amendment.sequence,
                "effective_terms_hash": amendment.effective_terms_hash,
            },
        )
        self._record_accounting_operation(
            operation_type="SESSION_AMENDMENT_ACCEPT",
            session=updated,
            payload=amendment.model_dump(mode="json"),
            created_at=amendment.accepted_at,
            emitted_events=["SessionContractAmended"],
        )
        return updated

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

    def _stored_acknowledgement_snapshot(
        self,
        acknowledgement: UsageAcknowledgement,
        *,
        accepted_charge_q: float,
    ) -> dict:
        snapshot = acknowledgement.model_dump(mode="json")
        snapshot["_accepted_charge_q"] = max(0.0, float(accepted_charge_q))
        return snapshot

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
        if session.economic_profile == "OWNER_AGENT":
            return session
        deposit = self.store.get_deposit_for_session(session_id)
        minimum_deposit_q_atoms = _whole_q_atoms(
            session.session_policy_snapshot.get("minimum_deposit", 0.0) or 0.0,
            field_name="minimum escrow deposit",
        )
        if minimum_deposit_q_atoms <= 0:
            return session
        locked_q_atoms = (
            session.deposit_locked_q_atoms
            if session.deposit_locked_q_atoms is not None
            else _whole_q_atoms(deposit.locked_q, field_name="locked deposit")
        )
        consumed_q_atoms = _whole_q_atoms(
            deposit.consumed_q,
            field_name="consumed deposit",
        )
        remaining_q_atoms = max(0, locked_q_atoms - consumed_q_atoms)
        if remaining_q_atoms < minimum_deposit_q_atoms:
            raise ValueError(
                "escrow top-up required: remaining deposit is below the "
                "Endpoint minimum deposit"
            )
        return session

    def _session_contract_payload(
        self,
        *,
        session_id: str,
        endpoint_id: str,
        client_wallet: str,
        provider_wallet: str,
        endpoint_payment_beneficiary: str,
        consumer_refund_beneficiary: str,
        consumer_authorization_public_key: str | None,
        node_id: str,
        deposit_q: float,
        advertisement_id: str | None,
        offer_id: str | None,
        pricing_policy_hash: str | None,
        endpoint_configuration_hash: str | None,
        accounting_contract_hash: str,
        accounting_contract_snapshot: dict,
        session_policy_snapshot: dict,
        accepted_at: str,
        economic_profile: str | None = None,
        deposit_q_atoms: int | None = None,
        fixed_price_q_atoms: int | None = None,
        request_charge_ceiling_q_atoms: int | None = None,
    ) -> dict:
        return {
            "session_id": session_id,
            "endpoint_id": endpoint_id,
            "client_wallet": client_wallet,
            "provider_wallet": provider_wallet,
            "endpoint_payment_beneficiary": endpoint_payment_beneficiary,
            "consumer_refund_beneficiary": consumer_refund_beneficiary,
            "consumer_authorization_public_key": consumer_authorization_public_key,
            "node_id": node_id,
            "deposit_locked_q": deposit_q,
            "economic_profile": economic_profile,
            "deposit_locked_q_atoms": deposit_q_atoms,
            "fixed_price_q_atoms": fixed_price_q_atoms,
            "request_charge_ceiling_q_atoms": request_charge_ceiling_q_atoms,
            "advertisement_id": advertisement_id,
            "offer_id": offer_id,
            "pricing_policy_hash": pricing_policy_hash,
            "endpoint_configuration_hash": endpoint_configuration_hash,
            "accounting_contract_hash": accounting_contract_hash,
            "accounting_contract_object_id": accounting_contract_snapshot.get(
                "registry_object_id"
            ),
            "accounting_contract_object_version": accounting_contract_snapshot.get(
                "registry_object_version"
            ),
            "accounting_contract_namespace": accounting_contract_snapshot.get(
                "registry_namespace"
            ),
            "session_policy_snapshot": session_policy_snapshot,
            "accepted_at": accepted_at,
            "session_contract_version": "session-contract.v2",
        }

    def _session_contract_record(
        self,
        *,
        payload: dict,
        source_reference: str,
    ) -> dict:
        payload_hash = _hash_payload(payload)
        return {
            "object_id": _registry_object_id(
                object_type="session_contract",
                object_version="session-contract.v2",
                payload_hash=payload_hash,
            ),
            "object_type": "session_contract",
            "object_version": "session-contract.v2",
            "namespace": "session",
            "payload_hash": payload_hash,
            "payload_encoding": "canonical_json",
            "source_reference": source_reference,
            "payload": payload,
        }

    def _persist_session_contract_object(self, *, record: dict) -> dict:
        return self.registry_service.upsert_registry_object(record)

    def _record_open_session_operation(
        self,
        *,
        session: EndpointSession,
        node_id: str,
        endpoint_id: str,
        deposit_q: float,
        session_policy_snapshot: dict,
        client_wallet: str,
    ) -> None:
        if self.operation_recorder is None:
            return
        session_policy_hash = hashlib.sha256(
            json.dumps(session_policy_snapshot, sort_keys=True).encode("utf-8")
        ).hexdigest()
        try:
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
                    "advertisement_id": session.advertisement_id,
                    "offer_id": session.offer_id,
                    "pricing_policy_hash": session.pricing_policy_hash,
                    "session_policy_hash": f"sha256:{session_policy_hash}",
                    "accounting_contract_hash": session.accounting_contract_hash,
                    "session_contract_hash": session.session_contract_hash,
                    "session_contract_object_id": session.session_contract_object_id,
                    "endpoint_payment_beneficiary": (
                        session.endpoint_payment_beneficiary
                    ),
                    "consumer_refund_beneficiary": (
                        session.consumer_refund_beneficiary
                    ),
                    "deposit_amount": deposit_q,
                    "open_expiration": session.expires_at,
                },
                created_at=session.created_at,
                emitted_events=["SessionOpened"],
            )
        except Exception:
            return

    def _emit_open_session_deposit_locked(
        self,
        *,
        session: EndpointSession,
        endpoint_id: str,
        client_wallet: str,
        provider_wallet: str,
        deposit_q: float,
        status: str,
    ) -> None:
        try:
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
        except Exception:
            return

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
        advertisement_id: str | None = None,
        offer_id: str | None = None,
        pricing_policy_hash: str | None = None,
        accounting_contract_hash: str | None = None,
        endpoint_configuration_hash: str | None = None,
        endpoint_payment_beneficiary: str | None = None,
        consumer_refund_beneficiary: str | None = None,
        consumer_authorization_public_key: str | None = None,
        session_id: str | None = None,
        economic_profile: str | None = None,
        deposit_q_atoms: int | None = None,
        fixed_price_q_atoms: int | None = None,
        request_charge_ceiling_q_atoms: int | None = None,
        canonical_funding_status: CanonicalFundingStatus | None = None,
        canonical_funding_operation_id: str | None = None,
        canonical_funding_submission: dict | None = None,
    ) -> SessionResult:
        session_policy_snapshot = dict(session_policy)
        session_policy_snapshot.setdefault("network_fee_q", self.network_fee_q)
        accounting_contract_snapshot = dict(accounting_contract or {})
        accepted_accounting_contract_hash = accounting_contract_hash or str(
            accounting_contract_snapshot.get("payload_hash")
            or _hash_payload(accounting_contract_snapshot)
        )
        accounting_contract_object_id = accounting_contract_snapshot.get(
            "registry_object_id"
        )
        accounting_contract_object_version = accounting_contract_snapshot.get(
            "registry_object_version"
        )
        accounting_contract_namespace = accounting_contract_snapshot.get(
            "registry_namespace"
        )
        accepted_endpoint_payment_beneficiary = (
            endpoint_payment_beneficiary or provider_wallet
        )
        accepted_consumer_refund_beneficiary = (
            consumer_refund_beneficiary or client_wallet
        )
        owner_agent_session = economic_profile == "OWNER_AGENT"
        if owner_agent_session and deposit_q != 0.0:
            raise ValueError("OWNER_AGENT sessions must not lock a deposit")
        if not owner_agent_session and deposit_q <= 0.0:
            raise ValueError("deposit must be positive outside OWNER_AGENT")
        if owner_agent_session and deposit_q_atoms not in {None, 0}:
            raise ValueError("OWNER_AGENT sessions must not lock deposit atoms")
        if not owner_agent_session and deposit_q_atoms is not None and deposit_q_atoms <= 0:
            raise ValueError("deposit atoms must be positive outside OWNER_AGENT")
        if (
            not owner_agent_session
            and request_charge_ceiling_q_atoms is not None
            and (
                deposit_q_atoms
                if deposit_q_atoms is not None
                else _whole_q_atoms(deposit_q, field_name="locked deposit")
            )
            < request_charge_ceiling_q_atoms
        ):
            raise ValueError("deposit cannot cover the authorized request ceiling")
        minimum_deposit = float(session_policy.get("minimum_deposit", 0.0) or 0.0)
        if not owner_agent_session and deposit_q < minimum_deposit:
            raise ValueError("deposit is below the minimum deposit")
        max_sessions = int(session_policy.get("max_concurrent_sessions", 1) or 1)
        queue_policy = str(session_policy.get("queue_policy", "busy") or "busy")
        now = datetime.now(UTC)
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
        session_id = session_id or f"sess-{uuid4().hex[:12]}"
        resolved_canonical_funding_status = canonical_funding_status or (
            "UNBOUND" if economic_profile == "MVP-0001" else "FINALIZED"
        )
        session_contract_payload = self._session_contract_payload(
            session_id=session_id,
            endpoint_id=endpoint_id,
            client_wallet=client_wallet,
            provider_wallet=provider_wallet,
            endpoint_payment_beneficiary=accepted_endpoint_payment_beneficiary,
            consumer_refund_beneficiary=accepted_consumer_refund_beneficiary,
            consumer_authorization_public_key=consumer_authorization_public_key,
            node_id=node_id,
            deposit_q=deposit_q,
            advertisement_id=advertisement_id,
            offer_id=offer_id,
            pricing_policy_hash=pricing_policy_hash,
            endpoint_configuration_hash=endpoint_configuration_hash,
            accounting_contract_hash=accepted_accounting_contract_hash,
            accounting_contract_snapshot=accounting_contract_snapshot,
            session_policy_snapshot=session_policy_snapshot,
            accepted_at=now.isoformat(),
            economic_profile=economic_profile,
            deposit_q_atoms=deposit_q_atoms,
            fixed_price_q_atoms=fixed_price_q_atoms,
            request_charge_ceiling_q_atoms=request_charge_ceiling_q_atoms,
        )
        session_contract_record = self._session_contract_record(
            payload=session_contract_payload,
            source_reference=session_id,
        )
        session_contract_hash = str(session_contract_record["payload_hash"])
        session = EndpointSession(
            session_id=session_id,
            endpoint_id=endpoint_id,
            client_wallet=client_wallet,
            provider_wallet=provider_wallet,
            endpoint_payment_beneficiary=accepted_endpoint_payment_beneficiary,
            consumer_refund_beneficiary=accepted_consumer_refund_beneficiary,
            consumer_authorization_public_key=consumer_authorization_public_key,
            node_id=node_id,
            status=status,
            created_at=now.isoformat(),
            started_at=started_at,
            last_activity_at=last_activity_at,
            expires_at=(now + timedelta(seconds=maximum_session_duration_seconds)).isoformat(),
            idle_deadline_at=(now + timedelta(seconds=idle_timeout_seconds)).isoformat(),
            deposit_locked_q=deposit_q,
            economic_profile=economic_profile,
            deposit_locked_q_atoms=deposit_q_atoms,
            fixed_price_q_atoms=fixed_price_q_atoms,
            request_charge_ceiling_q_atoms=request_charge_ceiling_q_atoms,
            canonical_funding_status=resolved_canonical_funding_status,
            canonical_funding_operation_id=canonical_funding_operation_id,
            canonical_funding_submission=dict(canonical_funding_submission or {}),
            reserved_slot_index=reserved_slot_index,
            queue_policy_snapshot=queue_policy,
            session_policy_snapshot=session_policy_snapshot,
            accounting_contract_snapshot=accounting_contract_snapshot,
            advertisement_id=advertisement_id,
            offer_id=offer_id,
            pricing_policy_hash=pricing_policy_hash,
            endpoint_configuration_hash=endpoint_configuration_hash,
            accounting_contract_hash=accepted_accounting_contract_hash,
            accounting_contract_object_id=(
                str(accounting_contract_object_id)
                if accounting_contract_object_id is not None
                else None
            ),
            accounting_contract_object_version=(
                str(accounting_contract_object_version)
                if accounting_contract_object_version is not None
                else None
            ),
            accounting_contract_namespace=(
                str(accounting_contract_namespace)
                if accounting_contract_namespace is not None
                else None
            ),
            session_contract_object_id=str(session_contract_record["object_id"]),
            session_contract_object_version=str(
                session_contract_record["object_version"]
            ),
            session_contract_namespace=str(session_contract_record["namespace"]),
            session_contract_hash=session_contract_hash,
            effective_terms_hash=session_contract_hash,
            session_amendment_sequence=0,
            session_amendment_chain=[],
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
        try:
            self.store.save_session(session)
            self.store.save_deposit(deposit)
            self._persist_session_contract_object(record=session_contract_record)
        except Exception:
            self.store.discard_open_session(session.session_id)
            raise
        if self.record_open_operation:
            self._record_open_session_operation(
                session=session,
                node_id=node_id,
                endpoint_id=endpoint_id,
                deposit_q=deposit_q,
                session_policy_snapshot=session_policy_snapshot,
                client_wallet=client_wallet,
            )
        self._emit_open_session_deposit_locked(
            session=session,
            endpoint_id=endpoint_id,
            client_wallet=client_wallet,
            provider_wallet=provider_wallet,
            deposit_q=deposit_q,
            status=status,
        )

        # RFC-0060: register session with failure handler
        if self.failure_handler is not None:
            self.failure_handler.register_session(session_id, status)

        return SessionResult(session=session, deposit=deposit)

    def bind_canonical_funding(
        self,
        session_id: str,
        *,
        funding_state_hash: str,
        operation_id: str | None = None,
    ) -> EndpointSession:
        current = self.store.get_session(session_id)
        if current.economic_profile != "MVP-0001":
            raise ValueError("Session is not an MVP-0001 economic Session")
        updated = current.model_copy(
            update={
                "canonical_funding_state_hash": funding_state_hash,
                "canonical_funding_status": "FINALIZED",
                "canonical_funding_operation_id": (
                    operation_id or current.canonical_funding_operation_id
                ),
            }
        )
        self.store.save_session(updated)
        return updated

    def bind_pending_canonical_funding(
        self,
        session_id: str,
        *,
        operation_id: str,
        submission: dict,
    ) -> EndpointSession:
        """Persist a canonical lock submission without applying economic state."""
        current = self.store.get_session(session_id)
        if current.economic_profile != "MVP-0001":
            raise ValueError("Session is not an MVP-0001 economic Session")
        if current.canonical_funding_status == "FINALIZED":
            if current.canonical_funding_operation_id not in {None, operation_id}:
                raise ValueError("Session canonical funding operation conflicts")
            return current
        if (
            current.canonical_funding_operation_id is not None
            and current.canonical_funding_operation_id != operation_id
        ):
            raise ValueError("Session canonical funding operation conflicts")
        updated = current.model_copy(
            update={
                "canonical_funding_status": "PENDING_FINALITY",
                "canonical_funding_operation_id": operation_id,
                "canonical_funding_submission": dict(submission),
            }
        )
        self.store.save_session(updated)
        return updated

    def close_session(self, session_id: str) -> SessionResult:
        current = self.store.get_session(session_id)
        deposit = self.store.get_deposit_for_session(session_id)
        if current.status in {"closed", "force_settled"}:
            settlement = (
                SessionSettlementSummary.model_validate(current.settlement_snapshot)
                if current.settlement_snapshot
                else None
            )
            return SessionResult(session=current, deposit=deposit, settlement=settlement)
        close_reason = current.close_reason or (
            "forced_recovery_expired"
            if current.status == "force_closing"
            else "closed_by_client"
        )
        result = self._settle_and_close_session(
            current,
            deposit,
            closed_at=datetime.now(UTC),
            close_reason=close_reason,
        )

        # RFC-0060: unregister session from failure handler
        if self.failure_handler is not None:
            self.failure_handler.unregister_session(session_id)

        self._promote_next_waiting_session(endpoint_id=current.endpoint_id)
        return result

    def mark_canonical_settlement_finalized(
        self,
        session_id: str,
        *,
        settlement_evidence_root: str,
        endpoint_payment_q_atoms: int,
        consumer_refund_q_atoms: int,
        network_fee_q_atoms: int = 0,
        failure_evidence_root: str | None = None,
        close_reason: str = "canonical_settlement_finalized",
        no_request: bool = False,
    ) -> SessionResult:
        current = self.store.get_session(session_id)
        deposit = self.store.get_deposit_for_session(session_id)
        if current.economic_profile != "MVP-0001":
            raise ValueError("Session is not an MVP-0001 economic Session")
        if current.status in {"closed", "force_settled"}:
            existing = current.settlement_snapshot
            if not existing:
                raise ValueError("Session is already finalized without settlement evidence")
            if existing.get("settlement_evidence_root") != settlement_evidence_root:
                raise ValueError("Session is already finalized with different settlement evidence")
            if (
                failure_evidence_root is not None
                and existing.get("failure_evidence_root") != failure_evidence_root
            ):
                raise ValueError(
                    "Session is already finalized with different failure evidence"
                )
            return SessionResult(
                session=current,
                deposit=deposit,
                settlement=SessionSettlementSummary.model_validate(existing),
            )
        atoms_per_q = 1_000_000
        endpoint_payment_q = round(endpoint_payment_q_atoms / atoms_per_q, 6)
        consumer_refund_q = round(consumer_refund_q_atoms / atoms_per_q, 6)
        network_fee_q = round(network_fee_q_atoms / atoms_per_q, 6)
        charged_q = round(endpoint_payment_q + network_fee_q, 6)
        settlement = SessionSettlementSummary(
            settlement_evidence_root=settlement_evidence_root,
            failure_evidence_root=failure_evidence_root,
            endpoint_payment_beneficiary=current.endpoint_payment_beneficiary,
            consumer_refund_beneficiary=current.consumer_refund_beneficiary,
            network_fee_q=network_fee_q,
            charged_q=charged_q,
            refunded_q=consumer_refund_q,
            endpoint_payment_q=endpoint_payment_q,
            payout_q=endpoint_payment_q,
            no_request=no_request,
        )
        closed = current.model_copy(
            update={
                "status": (
                    "force_settled"
                    if close_reason.startswith("forced_")
                    else "closed"
                ),
                "reserved_slot_index": None,
                "close_reason": close_reason,
                "settlement_snapshot": settlement.model_dump(mode="json"),
            }
        )
        released = deposit.model_copy(
            update={
                "status": "released",
                "consumed_q": charged_q,
                "refunded_q": consumer_refund_q,
            }
        )
        self.store.save_session(closed)
        self.store.save_deposit(released)
        if self.failure_handler is not None:
            self.failure_handler.unregister_session(session_id)
        self._emit(
            event_type="session.canonical_settled",
            message="canonical MVP Session settlement finalized",
            details={
                "session_id": session_id,
                "endpoint_id": current.endpoint_id,
                "settlement_evidence_root": settlement_evidence_root,
                "endpoint_payment_q_atoms": endpoint_payment_q_atoms,
                "consumer_refund_q_atoms": consumer_refund_q_atoms,
                "network_fee_q_atoms": network_fee_q_atoms,
            },
        )
        self._promote_next_waiting_session(endpoint_id=current.endpoint_id)
        return SessionResult(session=closed, deposit=released, settlement=settlement)

    def reconcile_canonical_settlement_projections(self, ledger_service) -> list[str]:
        """Restore Session read models from already-applied Ledger transitions.

        A restart can restore the canonical Ledger after the SessionStore
        snapshot was written, leaving an active local projection for a
        settlement that has already released escrow.  Only transitions whose
        hash is present in the restored Ledger state are eligible here; this
        method never creates an economic operation or changes wallet balances.
        """
        reconciled: list[str] = []
        for operation in ledger_service.list_operations():
            if operation.get("operation_type") not in {
                "SESSION_SETTLEMENT_FINALIZE",
                "SESSION_FORCE_SETTLE",
            }:
                continue
            payload = operation.get("payload")
            if not isinstance(payload, dict):
                continue
            # Canonical consensus records may retain the full transition or
            # the flattened finalization payload produced by the Ledger log.
            transition = payload.get("transition")
            if not isinstance(transition, dict):
                transition = payload
            session_id = transition.get("session_id") or payload.get("session_id")
            settlement_id = transition.get("settlement_id") or payload.get("settlement_id")
            transition_hash = transition.get("transition_hash") or payload.get("transition_hash")
            settlement_input_root = (
                transition.get("settlement_input_root")
                or payload.get("settlement_input_root")
            )
            if not all(
                isinstance(value, str) and value.strip()
                for value in (
                    session_id,
                    settlement_id,
                    transition_hash,
                    settlement_input_root,
                )
            ):
                continue
            try:
                current = self.store.get_session(session_id)
                self.store.get_deposit_for_session(session_id)
                funding = ledger_service.get_session_funding_account(session_id)
            except KeyError:
                # The local node may not own a remote Session projection.
                continue
            if funding.funding_state not in {"RELEASED", "REFUNDED"}:
                continue
            if ledger_service.get_settlement_transition_hash(settlement_id) != transition_hash:
                # The operation may only be admitted locally; do not project
                # it before the Ledger has applied the immutable transition.
                continue
            if (
                transition.get("endpoint_payment_beneficiary", funding.endpoint_payment_beneficiary)
                != current.endpoint_payment_beneficiary
                or transition.get("consumer_refund_beneficiary", funding.consumer_refund_beneficiary)
                != current.consumer_refund_beneficiary
            ):
                raise ValueError(
                    f"canonical Settlement beneficiary mismatch for Session {session_id}"
                )
            if current.status in {"closed", "force_settled"}:
                existing = current.settlement_snapshot or {}
                if existing.get("settlement_evidence_root") != settlement_input_root:
                    raise ValueError(
                        f"canonical Settlement evidence mismatch for Session {session_id}"
                    )
                continue
            self.mark_canonical_settlement_finalized(
                session_id,
                settlement_evidence_root=settlement_input_root,
                endpoint_payment_q_atoms=int(
                    transition.get(
                        "credit_endpoint_q_atoms",
                        payload.get("endpoint_payment_q_atoms", 0),
                    )
                ),
                consumer_refund_q_atoms=int(
                    transition.get(
                        "credit_consumer_q_atoms",
                        payload.get("consumer_refund_q_atoms", 0),
                    )
                ),
                network_fee_q_atoms=int(
                    transition.get(
                        "consume_network_fees_q_atoms",
                        payload.get("network_fees_q_atoms", 0),
                    )
                ),
                close_reason="canonical_settlement_recovered",
            )
            reconciled.append(session_id)
        return reconciled

    def touch_session(self, session_id: str) -> EndpointSession:
        current = self.store.get_session(session_id)
        if current.status != "active":
            raise ValueError(f"Session is not active: {session_id}")
        now = datetime.now(UTC)
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
        amount_q_atoms = _whole_q_atoms(amount_q, field_name="usage charge")
        return self.record_usage_charge_q_atoms(
            session_id,
            amount_q_atoms=amount_q_atoms,
            request_count=request_count,
        )

    def record_usage_charge_q_atoms(
        self,
        session_id: str,
        *,
        amount_q_atoms: int,
        request_count: int = 1,
    ) -> SessionResult:
        if isinstance(amount_q_atoms, bool) or not isinstance(amount_q_atoms, int):
            raise ValueError("usage charge q_atoms must be an integer")
        if amount_q_atoms < 0:
            raise ValueError("usage charge cannot be negative")
        if request_count < 0:
            raise ValueError("request_count cannot be negative")
        current = self.store.get_session(session_id)
        if current.status != "active":
            raise ValueError(f"Session is not active: {session_id}")
        deposit = self.store.get_deposit_for_session(session_id)
        locked_q_atoms = (
            current.deposit_locked_q_atoms
            if current.deposit_locked_q_atoms is not None
            else _whole_q_atoms(deposit.locked_q, field_name="locked deposit")
        )
        current_usage_q_atoms = current.usage_charged_q_atoms
        if current_usage_q_atoms == 0 and deposit.consumed_q > 0:
            current_usage_q_atoms = _whole_q_atoms(
                deposit.consumed_q,
                field_name="consumed deposit",
            )
        next_consumed_q_atoms = current_usage_q_atoms + amount_q_atoms
        if next_consumed_q_atoms > locked_q_atoms:
            raise ValueError(f"Session deposit exhausted: {session_id}")
        next_consumed_q = next_consumed_q_atoms / 1_000_000
        updated_deposit = deposit.model_copy(
            update={
                "consumed_q": next_consumed_q,
            }
        )
        updated_session = current.model_copy(
            update={
                "request_count": current.request_count + request_count,
                "usage_charged_q_atoms": next_consumed_q_atoms,
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
                "amount_q": amount_q_atoms / 1_000_000,
                "amount_q_atoms": amount_q_atoms,
                "consumed_q": next_consumed_q,
                "consumed_q_atoms": next_consumed_q_atoms,
                "usage_charged_q": next_consumed_q,
                "remaining_q": max(0.0, deposit.locked_q - next_consumed_q),
            },
        )
        return SessionResult(session=updated_session, deposit=updated_deposit)

    def record_runtime_terminal_evidence(
        self,
        session_id: str,
        *,
        evidence: dict,
    ) -> EndpointSession:
        """Persist the Result and Final Usage chain head bound to one Session."""
        current = self.store.get_session(session_id)
        terminal = SessionRuntimeTerminalEvidence.model_validate(evidence)
        if terminal.session_id != session_id:
            raise ValueError("runtime evidence session_id does not match target session")
        if terminal.endpoint_id != current.endpoint_id:
            raise ValueError("runtime evidence endpoint_id does not match target session")
        if terminal.endpoint_configuration_hash != current.endpoint_configuration_hash:
            raise ValueError(
                "runtime evidence Endpoint Configuration does not match target session"
            )
        if terminal.session_contract_hash != current.session_contract_hash:
            raise ValueError("runtime evidence Session Contract does not match target session")
        expected_effective_terms_hash = (
            current.effective_terms_hash or current.session_contract_hash
        )
        if current.session_amendment_sequence > 0 and terminal.effective_terms_hash is None:
            raise ValueError(
                "runtime evidence is missing the current effective terms hash"
            )
        if (
            terminal.effective_terms_hash is not None
            and terminal.effective_terms_hash != expected_effective_terms_hash
        ):
            raise ValueError(
                "runtime evidence Effective Terms hash does not match target session"
            )
        if terminal.accounting_contract_hash != current.accounting_contract_hash:
            raise ValueError("runtime evidence Accounting Contract does not match target session")
        for existing in current.runtime_terminal_evidence:
            if existing.request_id != terminal.request_id:
                continue
            if existing == terminal:
                return current
            raise ValueError("runtime terminal evidence conflicts for Request ID")
        updated = current.model_copy(
            update={
                "runtime_terminal_evidence": [
                    *current.runtime_terminal_evidence,
                    terminal,
                ]
            }
        )
        self.store.save_session(updated)
        self._emit(
            event_type="session.runtime_terminal_recorded",
            message="terminal Runtime evidence bound to Session",
            details={
                "session_id": session_id,
                "request_id": terminal.request_id,
                "runtime_id": terminal.runtime_id,
                "result_hash": terminal.result_hash,
                "final_usage_report_hash": terminal.final_usage_report_hash,
            },
        )
        self._record_accounting_operation(
            operation_type="SESSION_RUNTIME_EVIDENCE_COMMIT",
            session=updated,
            payload=terminal.model_dump(mode="json"),
            created_at=terminal.recorded_at,
            emitted_events=["SessionRuntimeEvidenceRecorded"],
        )
        return updated

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
        if (
            current.accounting_status == "mismatch"
            and current.last_usage_report_snapshot.get("sequence") == report.sequence
            and usage_report_hash(
                UsageReport.model_validate(current.last_usage_report_snapshot)
            )
            == report_hash
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
            report_created_at = datetime.now(UTC)
        report_chain = list(current.usage_report_chain or [])
        report_chain.append(report.model_dump(mode="json"))
        accounting_status = "ack_pending"
        if same_sequence_different_hash or not chain_continuity_ok:
            accounting_status = "mismatch"
            next_checkpoint.mismatch_open = True
        else:
            next_checkpoint.last_report_id = report.report_id
            next_checkpoint.last_report_sequence = report.sequence
            next_checkpoint.last_report_hash = report_hash
            next_checkpoint.accounting_contract_hash = current.accounting_contract_hash
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
        self._record_accounting_operation(
            operation_type="SESSION_USAGE_REPORT",
            session=updated,
            payload={
                "session_id": session_id,
                "endpoint_id": updated.endpoint_id,
                "sequence": report.sequence,
                "report_hash": report_hash,
                "previous_report_hash": report.previous_report_hash,
                "accounting_contract_version": report.accounting_contract_version,
                "accepted_checkpoint_sequence": updated.last_accepted_report_sequence,
                "accepted_usage_charged_q": updated.last_accepted_usage_charged_q,
            },
            created_at=report.created_at,
            emitted_events=["SessionUsageReportRecorded"],
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
        normalized_accepted_charge_q = max(0.0, float(accepted_charge_q))
        stored_acknowledgement_charge_q = current.last_usage_acknowledgement_snapshot.get(
            "_accepted_charge_q"
        )
        if (
            acknowledgement.sequence == checkpoint.last_ack_sequence
            and acknowledgement_hash == checkpoint.last_ack_hash
        ):
            comparison_charge_q = (
                stored_acknowledgement_charge_q
                if stored_acknowledgement_charge_q is not None
                else checkpoint.last_accepted_usage_charged_q
            )
            if comparison_charge_q != normalized_accepted_charge_q:
                raise ValueError(
                    "usage acknowledgement replay conflicts with accepted charge"
                )
            return current
        acknowledgement_snapshot = self._stored_acknowledgement_snapshot(
            acknowledgement,
            accepted_charge_q=normalized_accepted_charge_q,
        )
        acknowledgement_chain = list(current.usage_acknowledgement_chain or [])
        acknowledgement_chain.append(acknowledgement_snapshot)
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
            next_checkpoint.last_accepted_report_id = str(
                current.last_usage_report_snapshot.get("report_id")
            )
            next_checkpoint.last_accepted_report_sequence = acknowledgement.sequence
            next_checkpoint.last_accepted_report_hash = acknowledgement.provider_report_hash
            next_checkpoint.last_accepted_usage_charged_q = normalized_accepted_charge_q
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
        operation_created_at = (
            str(current.last_usage_report_snapshot.get("created_at"))
            if current.last_usage_report_snapshot.get("created_at") is not None
            else None
        )
        self._record_accounting_operation(
            operation_type="SESSION_USAGE_ACKNOWLEDGEMENT",
            session=updated,
            payload={
                "session_id": session_id,
                "endpoint_id": updated.endpoint_id,
                "sequence": acknowledgement.sequence,
                "report_hash": acknowledgement.provider_report_hash,
                "ack_hash": acknowledgement_hash,
                "accepted_checkpoint_sequence": updated.last_accepted_report_sequence,
                "accepted_report_id": updated.accounting_checkpoint.get(
                    "last_accepted_report_id"
                ),
                "accounting_contract_hash": updated.accounting_checkpoint.get(
                    "accounting_contract_hash"
                ),
                "accepted_usage_charged_q": updated.last_accepted_usage_charged_q,
                "verification_status": acknowledgement.verification_status,
            },
            created_at=operation_created_at,
            emitted_events=["SessionUsageAcknowledgementRecorded"],
        )
        if (
            updated.last_accepted_report_sequence != checkpoint.last_accepted_report_sequence
            or updated.accounting_checkpoint.get("last_accepted_report_hash")
            != checkpoint.last_accepted_report_hash
            or updated.last_accepted_usage_charged_q
            != checkpoint.last_accepted_usage_charged_q
        ):
            self._record_accounting_operation(
                operation_type="SESSION_CHECKPOINT_ACCEPT",
                session=updated,
                payload={
                    "session_id": session_id,
                    "endpoint_id": updated.endpoint_id,
                    "accepted_checkpoint_sequence": updated.last_accepted_report_sequence,
                    "report_hash": updated.accounting_checkpoint.get(
                        "last_accepted_report_hash"
                    ),
                    "usage_report_id": updated.accounting_checkpoint.get(
                        "last_accepted_report_id"
                    ),
                    "accounting_contract_hash": updated.accounting_checkpoint.get(
                        "accounting_contract_hash"
                    ),
                    "accepted_usage_charged_q": updated.last_accepted_usage_charged_q,
                },
                created_at=operation_created_at,
                emitted_events=["SessionCheckpointAccepted"],
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
        current_time = now or datetime.now(UTC)
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
        self._record_accounting_operation(
            operation_type="SESSION_ACCOUNTING_FORCE_SETTLE_REQUIRED",
            session=updated,
            payload={
                "session_id": session_id,
                "endpoint_id": updated.endpoint_id,
                "last_report_sequence": updated.accounting_checkpoint.get(
                    "last_report_sequence"
                ),
                "last_report_hash": updated.accounting_checkpoint.get("last_report_hash"),
                "accepted_checkpoint_sequence": updated.last_accepted_report_sequence,
                "accepted_usage_charged_q": updated.last_accepted_usage_charged_q,
            },
            created_at=checkpoint.ack_deadline_at or current_time.isoformat(),
            emitted_events=["SessionAccountingForceSettlementRequired"],
        )
        return updated

    def sweep_idle_sessions(
        self,
        *,
        now: datetime | None = None,
    ) -> list[SessionResult]:
        current_time = now or datetime.now(UTC)
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
        settlement_payload = {
            "session_id": session.session_id,
            "endpoint_id": session.endpoint_id,
            "advertisement_id": session.advertisement_id,
            "offer_id": session.offer_id,
            "session_contract_hash": session.session_contract_hash,
            "accounting_contract_hash": session.accounting_contract_hash,
            "pricing_policy_hash": session.pricing_policy_hash,
            "endpoint_payment_beneficiary": session.endpoint_payment_beneficiary,
            "consumer_refund_beneficiary": session.consumer_refund_beneficiary,
            "last_accepted_report_sequence": session.last_accepted_report_sequence,
            "last_accepted_usage_charged_q": session.last_accepted_usage_charged_q,
            "accounting_checkpoint": dict(session.accounting_checkpoint or {}),
            "usage_report_chain": list(session.usage_report_chain or []),
            "usage_acknowledgement_chain": list(
                session.usage_acknowledgement_chain or []
            ),
            "close_reason": close_reason,
            "charges": {
                "usage_charged_q": accepted_usage_charged_q,
                "idle_fee_charged_q": idle_fee_charged_q,
                "minimum_session_fee_q": minimum_session_fee_q,
                "network_fee_q": network_fee_charged_q,
                "charged_q": charged_q,
                "refunded_q": refunded_q,
                "payout_q": payout_q,
                "no_request": no_request,
            },
        }
        settlement_evidence_root = _hash_payload(settlement_payload)
        settlement = SessionSettlementSummary(
            settlement_evidence_root=settlement_evidence_root,
            endpoint_payment_beneficiary=session.endpoint_payment_beneficiary,
            consumer_refund_beneficiary=session.consumer_refund_beneficiary,
            usage_charged_q=accepted_usage_charged_q,
            idle_fee_charged_q=idle_fee_charged_q,
            minimum_session_fee_q=minimum_session_fee_q,
            network_fee_q=network_fee_charged_q,
            charged_q=charged_q,
            refunded_q=refunded_q,
            endpoint_payment_q=payout_q,
            payout_q=payout_q,
            no_request=no_request,
        )
        closed = session.model_copy(
            update={
                "status": (
                    "force_settled"
                    if session.status == "force_closing"
                    or close_reason.startswith("forced_")
                    else "closed"
                ),
                "reserved_slot_index": None,
                "close_reason": close_reason,
                "settlement_snapshot": settlement.model_dump(mode="json"),
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
                    "client_wallet": session.client_wallet,
                    "provider_wallet": session.provider_wallet,
                    "endpoint_payment_beneficiary": (
                        session.endpoint_payment_beneficiary
                    ),
                    "consumer_refund_beneficiary": (
                        session.consumer_refund_beneficiary
                    ),
                    "advertisement_id": session.advertisement_id,
                    "offer_id": session.offer_id,
                    "session_contract_hash": session.session_contract_hash,
                    "session_contract_object_id": session.session_contract_object_id,
                    "settlement_evidence_root": settlement.settlement_evidence_root,
                    "charged_q": settlement.charged_q,
                    "refunded_q": settlement.refunded_q,
                    "endpoint_payment_q": settlement.endpoint_payment_q,
                    "payout_q": settlement.payout_q,
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
                "endpoint_payment_q": settlement.endpoint_payment_q,
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
        now = datetime.now(UTC).isoformat()
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
