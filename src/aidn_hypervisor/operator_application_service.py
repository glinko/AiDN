from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope


class OperatorApplicationService:
    """Operator-facing wallet, onboarding, and dashboard orchestration."""

    def __init__(self, host) -> None:
        self._host = host
        self._reconciling_owner_wallet_bootstraps = False

    def owner_wallet_state(self) -> dict:
        if not self._reconciling_owner_wallet_bootstraps:
            self._reconcile_pending_owner_wallet_bootstraps()
        return self._owner_wallet_public_state()

    def _owner_wallet_public_state(self) -> dict:
        if self._host._owner_wallet is None:
            state = {
                "configured": False,
                "wallet_id": None,
                "public_key": None,
                "label": None,
                "created_at": None,
                "imported": False,
            }
        else:
            state = {
                "configured": True,
                "wallet_id": self._host._owner_wallet["wallet_id"],
                "public_key": self._host._owner_wallet["public_key"],
                "label": self._host._owner_wallet.get("label"),
                "created_at": self._host._owner_wallet["created_at"],
                "imported": bool(self._host._owner_wallet.get("imported", False)),
            }
        pending = getattr(self._host, "_pending_owner_wallet_bootstraps", [])
        if pending and not state["configured"]:
            intent = pending[0]
            proposed = dict(intent["owner_wallet"])
            proposed.pop("private_key", None)
            consensus = getattr(self._host, "consensus_service", None)
            submission = (
                consensus.get_submission(intent["operation_id"])
                if consensus is not None
                else None
            )
            state["pending_consensus"] = {
                "operation_id": intent["operation_id"],
                "wallet": proposed,
                "status": (
                    submission.status.value
                    if submission is not None
                    else "pending"
                ),
                "error": (
                    submission.error
                    if submission is not None
                    else intent.get("last_error")
                ),
            }
        return state

    def _requires_consensus_wallet_bind(self) -> bool:
        consensus = getattr(self._host, "consensus_service", None)
        return bool(consensus is not None and consensus.is_validator)

    def _prepare_wallet_material(
        self,
        *,
        mode: str,
        label: str | None,
        private_key: str | None,
    ) -> dict:
        if private_key is None:
            private_key_object = Ed25519PrivateKey.generate()
            resolved_private_key = "ed25519:" + private_key_object.private_bytes(
                Encoding.Raw,
                PrivateFormat.Raw,
                NoEncryption(),
            ).hex()
        else:
            if not private_key.startswith("ed25519:"):
                raise ValueError(
                    "Owner wallet private key must use ed25519:<32-byte hex>"
                )
            try:
                private_key_object = Ed25519PrivateKey.from_private_bytes(
                    bytes.fromhex(private_key.removeprefix("ed25519:"))
                )
            except ValueError as error:
                raise ValueError(
                    "Owner wallet private key must use ed25519:<32-byte hex>"
                ) from error
            resolved_private_key = private_key
        public_key = "ed25519:" + private_key_object.public_key().public_bytes(
            Encoding.Raw,
            PublicFormat.Raw,
        ).hex()
        digest = hashlib.sha256(public_key.encode("utf-8")).hexdigest()
        created_at = datetime.now(UTC).isoformat()
        return {
            "wallet": {
                "wallet_id": f"wallet-{digest[:12]}",
                "public_key": public_key,
                "private_key": resolved_private_key,
                "label": label,
                "created_at": created_at,
                "imported": mode == "import",
            },
            "private_key_object": private_key_object,
        }

    def _wallet_bind_envelope(self, material: dict, *, mode: str) -> LedgerOperationEnvelope:
        wallet = material["wallet"]
        payload = {
            "node_id": self._host.node_id,
            "operator_id": self._host.operator_id,
            "wallet_id": wallet["wallet_id"],
            "public_key": wallet["public_key"],
            "label": wallet["label"],
            "bootstrap_mode": mode,
            "wallet_binding_version": "1",
            "created_at": wallet["created_at"],
        }
        unsigned = LedgerOperationEnvelope(
            operation_type="OPERATOR_WALLET_BIND",
            origin_type="protocol",
            initiator_id=self._host.node_id,
            fee_class="onboarding_exempt",
            created_at=wallet["created_at"],
            payload=payload,
        )
        signature = "ed25519:" + material["private_key_object"].sign(
            unsigned.signing_bytes()
        ).hex()
        return LedgerOperationEnvelope(
            operation_type=unsigned.operation_type,
            operation_version=unsigned.operation_version,
            protocol_version=unsigned.protocol_version,
            origin_type=unsigned.origin_type,
            initiator_id=unsigned.initiator_id,
            sender_wallet=unsigned.sender_wallet,
            sender_sequence=unsigned.sender_sequence,
            fee_payer=unsigned.fee_payer,
            fee_class=unsigned.fee_class,
            created_at=unsigned.created_at,
            expires_at=unsigned.expires_at,
            target_epoch=unsigned.target_epoch,
            payload=unsigned.payload,
            evidence_references=unsigned.evidence_references,
            signatures=[signature],
            operation_id=unsigned.operation_id,
        )

    def _pending_owner_wallet_result(self, intent: dict) -> dict:
        consensus = getattr(self._host, "consensus_service", None)
        submission = (
            consensus.get_submission(intent["operation_id"])
            if consensus is not None
            else None
        )
        failed = bool(
            intent.get("last_error")
            or (submission is not None and submission.status.value == "failed")
        )
        proposed = dict(intent["owner_wallet"])
        proposed.pop("private_key", None)
        return {
            "status": "CONSENSUS_FAILED" if failed else "CONSENSUS_PENDING",
            "wallet": self._owner_wallet_public_state(),
            "proposed_wallet": proposed,
            "private_key": (
                intent["owner_wallet"]["private_key"]
                if not intent["owner_wallet"].get("imported", False)
                else None
            ),
            "consensus": {
                "operation_id": intent["operation_id"],
                "status": submission.status.value if submission is not None else "pending",
                "error": (
                    submission.error
                    if submission is not None
                    else intent.get("last_error")
                ),
            },
        }

    def _submit_pending_owner_wallet_bootstrap(self, intent: dict) -> None:
        consensus = getattr(self._host, "consensus_service", None)
        if consensus is None or not consensus.is_validator:
            raise ValueError("validator wallet bootstrap requires consensus service")
        envelope = self._host.get_pending_consensus_envelope(intent["operation_id"])
        if envelope is None:
            raise ValueError("pending wallet bootstrap envelope is missing")
        submission = consensus.submit_operation(envelope, retry_existing=True)
        if submission.status.value == "failed":
            raise ValueError(submission.error or "wallet bind consensus submission failed")

    def _owner_wallet_binding_operation(self) -> tuple[dict, LedgerOperationEnvelope] | None:
        owner = self._host._owner_wallet
        if owner is None:
            return None
        for operation in reversed(self._host.ledger_operation_service.snapshot_operations()):
            if operation.get("operation_type") != "OPERATOR_WALLET_BIND":
                continue
            payload = operation.get("payload") or {}
            if (
                payload.get("node_id") != self._host.node_id
                or payload.get("operator_id") != self._host.operator_id
                or payload.get("wallet_id") != owner.get("wallet_id")
                or payload.get("public_key") != owner.get("public_key")
            ):
                continue
            try:
                return operation, LedgerOperationEnvelope.model_validate(operation)
            except ValueError:
                return None
        return None

    def _owner_wallet_binding_is_finalized(self) -> bool:
        binding = self._owner_wallet_binding_operation()
        consensus = getattr(self._host, "consensus_service", None)
        finality_source = getattr(self._host, "consensus_finality_source", None)
        restore_submission = getattr(consensus, "restore_submission", None)
        if binding is None or consensus is None or finality_source is None or restore_submission is None:
            return False
        _, envelope = binding
        try:
            restore_submission(envelope)
            consensus.reconcile_finality(
                envelope.operation_id,
                finality_source=finality_source,
            )
        except Exception:
            return False
        return consensus.is_finalized(envelope.operation_id)

    def _stage_unfinalized_owner_wallet_recovery(self) -> bool:
        if self._host._owner_wallet is None or self._host._pending_owner_wallet_bootstraps:
            return False
        binding = self._owner_wallet_binding_operation()
        if binding is None:
            return False
        _, envelope = binding
        self._host.stage_pending_consensus_envelope(envelope)
        self._host._pending_owner_wallet_bootstraps.append(
            {
                "operation_id": envelope.operation_id,
                "payload": dict(envelope.payload),
                "owner_wallet": dict(self._host._owner_wallet),
            }
        )
        self._host._owner_wallet = None
        return True

    @staticmethod
    def _is_retryable_consensus_error(error: str | None) -> bool:
        message = (error or "").lower()
        return any(
            marker in message
            for marker in (
                "connection refused",
                "connection reset",
                "connection aborted",
                "timed out",
                "timeout",
                "urlopen error",
                "http error 5",
                "internal server error",
                "rpc error",
                "temporarily unavailable",
            )
        )

    def _discard_pending_owner_wallet_bootstrap(self, operation_id: str) -> None:
        """Remove one failed local intent so an explicit retry can start cleanly."""
        self._host._pending_owner_wallet_bootstraps = [
            item
            for item in self._host._pending_owner_wallet_bootstraps
            if item["operation_id"] != operation_id
        ]
        self._host.discard_pending_consensus_envelopes(operation_id)
        self._host.discard_pending_consensus_operations(operation_id)

    def _reconcile_pending_owner_wallet_bootstraps(self) -> None:
        if self._reconciling_owner_wallet_bootstraps:
            return
        consensus = getattr(self._host, "consensus_service", None)
        if consensus is None or not consensus.is_validator:
            return

        self._reconciling_owner_wallet_bootstraps = True
        changed = False
        try:
            if (
                self._host._owner_wallet is not None
                and not self._owner_wallet_binding_is_finalized()
            ):
                changed = self._stage_unfinalized_owner_wallet_recovery() or changed
                if self._host._owner_wallet is not None:
                    if getattr(self._host, "_pending_owner_wallet_bootstraps", []):
                        self._host._owner_wallet = None
                        changed = True
            pending = list(getattr(self._host, "_pending_owner_wallet_bootstraps", []))
            if not pending:
                if changed:
                    self._host._persist_state()
                return
            canonical_operations = {
                operation.get("operation_id"): operation
                for operation in self._host.ledger_operation_service.snapshot_operations()
            }
            pending = list(getattr(self._host, "_pending_owner_wallet_bootstraps", []))
            for intent in pending:
                operation_id = intent["operation_id"]
                submission = consensus.get_submission(operation_id)
                if submission is not None and submission.status.value == "failed":
                    error = submission.error or "consensus submission failed"
                    if self._is_retryable_consensus_error(error):
                        try:
                            self._submit_pending_owner_wallet_bootstrap(intent)
                        except ValueError as retry_error:
                            error = str(retry_error)
                        else:
                            intent.pop("last_error", None)
                            changed = True
                            continue
                    if intent.get("last_error") != error:
                        intent["last_error"] = error
                        changed = True
                    continue
                finality_source = getattr(self._host, "consensus_finality_source", None)
                if finality_source is not None:
                    consensus.reconcile_finality(
                        operation_id,
                        finality_source=finality_source,
                    )
                operation = canonical_operations.get(operation_id)
                if operation is None:
                    try:
                        self._submit_pending_owner_wallet_bootstrap(intent)
                    except ValueError as error:
                        message = str(error)
                        if intent.get("last_error") != message:
                            intent["last_error"] = message
                            changed = True
                    continue
                if operation.get("operation_type") != "OPERATOR_WALLET_BIND":
                    raise ValueError("wallet bootstrap operation type mismatch")
                if operation.get("payload") != intent["payload"]:
                    raise ValueError("wallet bootstrap consensus payload mismatch")
                submission = consensus.get_submission(operation_id)
                if submission is None or submission.status.value != "finalized":
                    try:
                        envelope = LedgerOperationEnvelope.model_validate(operation)
                        self._host.stage_pending_consensus_envelope(envelope)
                        consensus.restore_submission(envelope)
                        self._submit_pending_owner_wallet_bootstrap(intent)
                    except ValueError as error:
                        message = str(error)
                        if intent.get("last_error") != message:
                            intent["last_error"] = message
                            changed = True
                    else:
                        changed = True
                    continue
                self._host._owner_wallet = dict(intent["owner_wallet"])
                self._host._pending_owner_wallet_bootstraps = [
                    item
                    for item in self._host._pending_owner_wallet_bootstraps
                    if item["operation_id"] != operation_id
                ]
                self._host.discard_pending_consensus_envelopes(operation_id)
                self._host.discard_pending_consensus_operations(operation_id)
                self._host._operator_onboarding = None
                changed = True
            if changed:
                self.sync_operator_onboarding_state(endpoint_items=[])
                self._host._persist_state()
        finally:
            self._reconciling_owner_wallet_bootstraps = False

    def owner_wallet_private_key(self) -> str:
        if self._host._owner_wallet is None:
            raise ValueError("Owner wallet is not configured")
        return self._host._owner_wallet["private_key"]

    def node_identity(self) -> dict:
        owner = self.owner_wallet_state()
        return {
            "node_id": self._host.node_id,
            "operator_id": self._host.operator_id,
            "base_url": self._host.base_url,
            "owner_wallet_id": owner["wallet_id"],
            "ownership_configured": owner["configured"],
            "can_host_custom_model": self._host.can_host_custom_model,
        }

    def registry_enabled(self) -> bool:
        return False

    def validation_enabled(self) -> bool:
        return False

    def canonical_overlay_inventory(self) -> dict:
        return self._host._network_projection_service.canonical_overlay_inventory()

    def configure_owner_wallet(
        self,
        *,
        mode: str,
        label: str | None = None,
        private_key: str | None = None,
    ) -> dict:
        if mode not in {"create", "import"}:
            raise ValueError(f"Unsupported wallet bootstrap mode: {mode}")
        if mode == "import" and not private_key:
            raise ValueError("Private key is required for wallet import")
        if self._requires_consensus_wallet_bind():
            self._reconcile_pending_owner_wallet_bootstraps()
        material = self._prepare_wallet_material(
            mode=mode,
            label=label,
            private_key=private_key,
        )
        if self._requires_consensus_wallet_bind():
            if self._host._pending_owner_wallet_bootstraps:
                intent = self._host._pending_owner_wallet_bootstraps[0]
                existing_submission = self._host.consensus_service.get_submission(
                    intent["operation_id"]
                )
                if (
                    intent.get("last_error")
                    or (
                        existing_submission is not None
                        and existing_submission.status.value == "failed"
                    )
                ):
                    self._discard_pending_owner_wallet_bootstrap(intent["operation_id"])
                    self._host._persist_state()
                else:
                    if mode == "import" and intent["owner_wallet"]["public_key"] != material["wallet"]["public_key"]:
                        raise ValueError("another owner wallet bootstrap is already pending")
                    try:
                        self._submit_pending_owner_wallet_bootstrap(intent)
                    except ValueError as error:
                        intent["last_error"] = str(error)
                        self._host._persist_state()
                    self._reconcile_pending_owner_wallet_bootstraps()
                    return (
                        self._pending_owner_wallet_result(intent)
                        if self._host._owner_wallet is None
                        else {"wallet": self.owner_wallet_state(), "private_key": None}
                    )

            envelope = self._wallet_bind_envelope(material, mode=mode)
            intent = {
                "operation_id": envelope.operation_id,
                "payload": dict(envelope.payload),
                "owner_wallet": dict(material["wallet"]),
            }
            self._host._pending_owner_wallet_bootstraps.append(intent)
            self._host.stage_pending_consensus_envelope(envelope)
            self._host._persist_state()
            try:
                self._submit_pending_owner_wallet_bootstrap(intent)
            except ValueError as error:
                intent["last_error"] = str(error)
                self._host._persist_state()
            self._reconcile_pending_owner_wallet_bootstraps()
            if self._host._owner_wallet is None:
                return self._pending_owner_wallet_result(intent)
            return {"wallet": self.owner_wallet_state(), "private_key": None}

        self._host._owner_wallet = material["wallet"]
        self._host._operator_onboarding = None
        self.sync_operator_onboarding_state(endpoint_items=[])
        return {
            "wallet": self.owner_wallet_state(),
            "private_key": material["wallet"]["private_key"] if mode == "create" else None,
        }

    def operator_onboarding_state(self) -> dict:
        if self._host._operator_onboarding is None:
            return {
                "completed": False,
                "completed_at": None,
                "completed_via": None,
                "current_step": "configure_wallet",
                "last_workspace": "home",
                "transition_history": [],
                "steps": [],
            }
        return deepcopy(self._host._operator_onboarding)

    def sync_operator_onboarding_state(
        self,
        *,
        endpoint_items: list[dict],
        last_workspace: str | None = None,
    ) -> dict:
        onboarding = self.operator_onboarding_state()
        already_completed = bool(onboarding.get("completed"))
        if last_workspace is not None:
            onboarding["last_workspace"] = last_workspace
        if already_completed or any(
            item.get("publication_status") == "published" for item in endpoint_items
        ):
            onboarding["completed"] = True
            onboarding["completed_via"] = (
                onboarding.get("completed_via") or "first_local_endpoint_published"
            )
            if onboarding["completed_at"] is None:
                onboarding["completed_at"] = datetime.now(UTC).isoformat()
            onboarding["current_step"] = "operate"
        elif endpoint_items:
            onboarding["completed"] = False
            onboarding["completed_via"] = None
            onboarding["completed_at"] = None
            onboarding["current_step"] = "publish_endpoint"
        elif self.owner_wallet_state()["configured"]:
            onboarding["completed"] = False
            onboarding["completed_via"] = None
            onboarding["completed_at"] = None
            onboarding["current_step"] = "attach_provider"
        else:
            onboarding["completed"] = False
            onboarding["completed_via"] = None
            onboarding["completed_at"] = None
            onboarding["current_step"] = "configure_wallet"
        self._host._operator_onboarding = onboarding
        self._host._persist_state()
        return deepcopy(onboarding)

    def operator_dashboard_home(self) -> dict:
        return self._host.operator_read_models.home()

    def operator_dashboard_fleet(self) -> dict:
        return self._host.operator_read_models.fleet()

    def operator_dashboard_endpoints(self) -> dict:
        return self._host.operator_read_models.endpoints()

    def operator_requests_policy(self) -> dict[str, bool | str]:
        return dict(self._host._operator_requests_policy)

    def update_operator_requests_policy(
        self,
        *,
        allow_spillover: bool,
        dispatch_strategy: str,
        ready_endpoint_only: bool,
    ) -> dict[str, bool | str]:
        if dispatch_strategy not in {"local_first", "balanced", "market_first"}:
            raise ValueError(f"Unsupported dispatch strategy: {dispatch_strategy}")
        self._host._operator_requests_policy = {
            "allow_spillover": bool(allow_spillover),
            "dispatch_strategy": dispatch_strategy,
            "ready_endpoint_only": bool(ready_endpoint_only),
        }
        self._host._persist_state()
        return self.operator_requests_policy()

    def operator_dashboard_requests(
        self,
        *,
        market_candidates: list[dict] | None = None,
    ) -> dict:
        return self._host.operator_read_models.requests(
            market_candidates=market_candidates,
        )
