"""External Faucet policy execution and canonical transfer assembly."""

from __future__ import annotations

import hmac
import json
import os
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from aidn_faucet.cometbft_submitter import serialize_faucet_envelope
from aidn_faucet.models import (
    FaucetChallenge,
    FaucetChallengeRequest,
    FaucetClaimRequest,
    FaucetClaimResponse,
    FaucetStatus,
    PolicyDecision,
    TransferSubmission,
    canonical_hash,
    wallet_id_for_public_key,
)
from aidn_faucet.policy import FaucetPolicy, FaucetPolicyError
from aidn_faucet.store import FaucetStore
from aidn_hypervisor.consensus.cometbft import cometbft_transaction_hash
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.faucet_treasury import (
    FaucetTreasuryActivationProof,
    FaucetTreasuryManifest,
    validate_faucet_treasury_manifest,
)


class FaucetTransferSubmitter(Protocol):
    """Consensus boundary owned by the deployment, not by Faucet policy."""

    def next_sender_sequence(self, wallet_id: str) -> int:
        """Return the next canonical sequence for the Treasury Wallet."""

    def submit_transfer(self, envelope: LedgerOperationEnvelope) -> TransferSubmission:
        """Submit the exact envelope and report admission/finality separately."""

    def reconcile_transfer(self, envelope: LedgerOperationEnvelope) -> TransferSubmission:
        """Re-check the exact operation without creating a replacement envelope."""

    def treasury_activation_proof(
        self,
        manifest: FaucetTreasuryManifest,
    ) -> FaucetTreasuryActivationProof:
        """Prove that the configured Treasury is active in canonical consensus."""


class TreasurySigner:
    """Load and hold the Faucet Treasury signing key in the Faucet process only."""

    def __init__(self, private_key: Ed25519PrivateKey, *, expected_public_key: str) -> None:
        public_key = "ed25519:" + private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()
        if public_key.lower() != expected_public_key.lower():
            raise ValueError("Faucet signing key does not match Treasury manifest")
        self._private_key = private_key
        self.public_key = public_key

    @classmethod
    def from_file(cls, path: str | Path, *, expected_public_key: str) -> TreasurySigner:
        key_path = Path(path).expanduser().resolve()
        if not key_path.is_file():
            raise ValueError("Faucet signing key file does not exist")
        if os.name != "nt" and key_path.stat().st_mode & 0o077:
            raise ValueError("Faucet signing key file must not be group/world readable")
        raw = key_path.read_bytes().strip()
        if raw.startswith(b"-----BEGIN"):
            loaded = serialization.load_pem_private_key(raw, password=None)
            if not isinstance(loaded, Ed25519PrivateKey):
                raise ValueError("Faucet signing key PEM is not Ed25519")
            return cls(loaded, expected_public_key=expected_public_key)
        text = raw.decode("ascii").strip()
        if text.startswith("ed25519:"):
            text = text.removeprefix("ed25519:")
        try:
            seed = bytes.fromhex(text)
        except ValueError as error:
            raise ValueError("Faucet signing key must be raw 32-byte hex or Ed25519 PEM") from error
        if len(seed) != 32:
            raise ValueError("Faucet signing key seed must contain exactly 32 bytes")
        return cls(Ed25519PrivateKey.from_private_bytes(seed), expected_public_key=expected_public_key)

    def sign(self, payload: bytes) -> str:
        return "ed25519:" + self._private_key.sign(payload).hex()


class FaucetService:
    """Apply a replaceable Faucet policy without owning Ledger state."""

    def __init__(
        self,
        *,
        manifest: FaucetTreasuryManifest | dict[str, Any],
        signer: TreasurySigner,
        policy: FaucetPolicy,
        store: FaucetStore,
        submitter: FaucetTransferSubmitter,
        service_id: str = "aidn-faucet",
        agent_token: str | None = None,
        creator_token: str | None = None,
        treasury_balance_provider: Callable[[str], int | None] | None = None,
        require_treasury_activation: bool = True,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        parsed_manifest = (
            manifest
            if isinstance(manifest, FaucetTreasuryManifest)
            else FaucetTreasuryManifest.model_validate(manifest)
        )
        self.manifest = validate_faucet_treasury_manifest(parsed_manifest)
        if signer.public_key.lower() != self.manifest.wallet_public_key.lower():
            raise ValueError("Faucet signer does not match Treasury Wallet")
        self.signer = signer
        self.policy = policy
        self.store = store
        self.submitter = submitter
        self.service_id = service_id
        self.agent_token = agent_token
        self.creator_token = creator_token
        self.require_treasury_activation = require_treasury_activation
        self._treasury_balance_provider = treasury_balance_provider or getattr(
            submitter,
            "treasury_balance_q_atoms",
            None,
        )
        self._now_fn = now or (lambda: datetime.now(UTC))
        self._treasury_activation_cache: tuple[datetime, FaucetTreasuryActivationProof] | None = None
        self.store.ensure_service_state(
            state_key="controls",
            state={
                "paused": False,
                "pause_reason": None,
                "low_balance_watermark_q_atoms": 0,
            },
        )
        self.store.ensure_policy_state(
            policy_id=self.policy.policy_id,
            state=self.policy.initial_state(now=self._now()),
        )

    def _now(self) -> datetime:
        value = self._now_fn()
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def authorize_agent(self, token: str | None) -> None:
        if self.agent_token is None:
            return
        if token is None or not hmac.compare_digest(token, self.agent_token):
            raise PermissionError("FAUCET_AGENT_UNAUTHORIZED")

    def authorize_creator(self, token: str | None) -> None:
        if self.creator_token is None:
            raise PermissionError("FAUCET_CREATOR_CONTROLS_DISABLED")
        if token is None or not hmac.compare_digest(token, self.creator_token):
            raise PermissionError("FAUCET_CREATOR_UNAUTHORIZED")

    def creator_status(self) -> dict[str, Any]:
        controls = self._control_state()
        return {
            **controls,
            "service": self.status().model_dump(mode="json"),
        }

    def claim_status(self, request_id: str) -> dict[str, Any]:
        """Return sanitized operational state without exposing the envelope."""

        record = self.store.get_claim(request_id)
        if record is None:
            raise ValueError("FAUCET_CLAIM_NOT_FOUND")
        response = self._response_from_record(record).model_dump(mode="json")
        response.update(
            {
                "created_at": record["created_at"],
                "finalized_at": record["finalized_at"],
            }
        )
        return response

    def reconcile_as_creator(self, request_id: str) -> dict[str, Any]:
        """Reconcile a stored claim for the creator without changing its identity."""

        return self.reconcile(request_id).model_dump(mode="json")

    def pause(self, *, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("FAUCET_PAUSE_REASON_REQUIRED")
        state = self._control_state()
        state.update({"paused": True, "pause_reason": reason.strip()})
        return self.store.set_service_state(state_key="controls", state=state)

    def resume(self) -> dict[str, Any]:
        state = self._control_state()
        state.update({"paused": False, "pause_reason": None})
        return self.store.set_service_state(state_key="controls", state=state)

    def set_low_balance_watermark(self, *, watermark_q_atoms: int) -> dict[str, Any]:
        if isinstance(watermark_q_atoms, bool) or watermark_q_atoms < 0:
            raise ValueError("FAUCET_LOW_BALANCE_WATERMARK_INVALID")
        state = self._control_state()
        state["low_balance_watermark_q_atoms"] = watermark_q_atoms
        return self.store.set_service_state(state_key="controls", state=state)

    def status(self) -> FaucetStatus:
        controls = self._control_state()
        balance = self._treasury_balance()
        watermark = int(controls["low_balance_watermark_q_atoms"])
        activation = self._treasury_activation()
        return FaucetStatus(
            service_id=self.service_id,
            treasury_id=self.manifest.treasury_id,
            treasury_wallet_id=self.manifest.wallet_id,
            policy_id=self.policy.policy_id,
            policy_version=self.policy.policy_version,
            agent_auth_required=self.agent_token is not None,
            paused=bool(controls["paused"]),
            pause_reason=controls.get("pause_reason"),
            low_balance_watermark_q_atoms=watermark,
            low_balance_blocked=watermark > 0 and (balance is None or balance < watermark),
            treasury_balance_q_atoms=balance,
            treasury_activation_state=(
                activation.state if activation is not None else "DISABLED"
            ),
            treasury_activation_reason=(
                activation.reason
                if activation is not None
                else "Treasury activation verification is disabled"
            ),
            treasury_activation_proof=activation,
        )

    def _treasury_activation(self) -> FaucetTreasuryActivationProof | None:
        if not self.require_treasury_activation:
            return None
        now = self._now()
        cached = self._treasury_activation_cache
        if cached is not None and now < cached[0] + timedelta(seconds=15):
            return cached[1]
        verifier = getattr(self.submitter, "treasury_activation_proof", None)
        if not callable(verifier):
            proof = FaucetTreasuryActivationProof.unavailable(
                self.manifest,
                reason="FAUCET_TREASURY_ACTIVATION_VERIFIER_UNAVAILABLE",
            )
        else:
            try:
                proof = verifier(self.manifest)
            except Exception as error:  # pragma: no cover - adapter-specific boundary
                proof = FaucetTreasuryActivationProof.unavailable(
                    self.manifest,
                    reason=f"FAUCET_TREASURY_ACTIVATION_VERIFIER_FAILED: {error}",
                )
            if not isinstance(proof, FaucetTreasuryActivationProof):
                proof = FaucetTreasuryActivationProof.unavailable(
                    self.manifest,
                    reason="FAUCET_TREASURY_ACTIVATION_PROOF_INVALID",
                )
        if (
            proof.treasury_id != self.manifest.treasury_id
            or proof.network_id != self.manifest.network_id
            or proof.chain_id != self.manifest.chain_id
            or proof.wallet_id != self.manifest.wallet_id
            or proof.manifest_hash != self.manifest.manifest_hash
            or proof.funding_mode != self.manifest.funding_mode
            or proof.funding_operation_id != self.manifest.funding_operation_id
        ):
            proof = FaucetTreasuryActivationProof.unavailable(
                self.manifest,
                reason="FAUCET_TREASURY_ACTIVATION_PROOF_MISMATCH",
            )
        self._treasury_activation_cache = (now, proof)
        return proof

    def issue_challenge(self, request: FaucetChallengeRequest) -> FaucetChallenge:
        expected_wallet_id = wallet_id_for_public_key(request.wallet_public_key)
        if expected_wallet_id != request.wallet_id:
            raise ValueError("FAUCET_WALLET_ID_MISMATCH")
        now = self._now()
        challenge = FaucetChallenge(
            challenge_id="faucet-challenge-" + secrets.token_urlsafe(18),
            wallet_id=request.wallet_id,
            challenge=secrets.token_urlsafe(32),
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=10)).isoformat(),
        )
        self.store.create_challenge(challenge.model_dump(mode="json"))
        return challenge

    def claim(self, request: FaucetClaimRequest) -> FaucetClaimResponse:
        existing = self.store.get_claim(request.request_id)
        if existing is not None:
            if existing["wallet_id"] != request.wallet_id:
                raise ValueError("FAUCET_REQUEST_ID_REUSED_FOR_ANOTHER_WALLET")
            return self._response_from_record(existing)

        self._ensure_claims_enabled()
        now = self._now()
        self._verify_wallet_proof(request)
        if self.store.find_pending_treasury_claim() is not None:
            raise ValueError("FAUCET_TREASURY_TRANSFER_PENDING")
        state = self.store.get_policy_state(self.policy.policy_id)
        if state is None:
            raise ValueError("FAUCET_POLICY_STATE_MISSING")
        quota_key = self.policy.quota_key(wallet_id=request.wallet_id, state=state, now=now)
        active_claim = self.store.find_active_quota_claim(
            wallet_id=request.wallet_id,
            quota_key=quota_key,
        )
        try:
            decision = self.policy.decide(
                wallet_id=request.wallet_id,
                state=state,
                now=now,
                quota_exists=active_claim is not None,
            )
        except FaucetPolicyError as error:
            if error.code == "FAUCET_QUOTA_EXHAUSTED":
                return FaucetClaimResponse(
                    request_id=request.request_id,
                    status="QUOTA_EXHAUSTED",
                    policy_id=self.policy.policy_id,
                    policy_version=self.policy.policy_version,
                    detail=str(error),
                )
            if error.code == "FAUCET_POOL_EMPTY":
                return FaucetClaimResponse(
                    request_id=request.request_id,
                    status="POOL_EMPTY",
                    policy_id=self.policy.policy_id,
                    policy_version=self.policy.policy_version,
                    detail=str(error),
                )
            if active_claim is not None:
                return self._response_from_record(active_claim)
            raise

        if decision.quota_key != quota_key:
            raise ValueError("FAUCET_POLICY_QUOTA_KEY_CHANGED")
        claim_id = "faucet-claim-" + canonical_hash(
            {"service_id": self.service_id, "request_id": request.request_id}
        ).removeprefix("sha256:")[:32]
        envelope = self._build_transfer_envelope(
            claim_id=claim_id,
            recipient_wallet=request.wallet_id,
            decision=decision,
            created_at=now,
        )
        self._consume_challenge(request, now=now)
        record = self.store.create_pending_claim(
            {
                "request_id": request.request_id,
                "claim_id": claim_id,
                "wallet_id": request.wallet_id,
                "quota_key": decision.quota_key,
                "policy_id": decision.policy_id,
                "policy_version": decision.policy_version,
                "amount_q_atoms": decision.amount_q_atoms,
                "decision": decision.model_dump(mode="json"),
                "state_after_success": decision.state_after_success,
                "envelope": envelope.model_dump(mode="json"),
                "operation_id": envelope.operation_id,
                "created_at": now.isoformat(),
            }
        )
        return self._submit_or_recover(record, envelope)

    def reconcile(self, request_id: str) -> FaucetClaimResponse:
        record = self.store.get_claim(request_id)
        if record is None:
            raise ValueError("FAUCET_CLAIM_NOT_FOUND")
        if record["status"] == "FINALIZED":
            return self._response_from_record(record)
        envelope = LedgerOperationEnvelope.model_validate(json_loads(record["envelope_json"]))
        return self._submit_or_recover(
            record,
            envelope,
            reconcile_only=record["status"] != "REJECTED",
        )

    def _submit_or_recover(
        self,
        record: dict[str, Any],
        envelope: LedgerOperationEnvelope,
        *,
        reconcile_only: bool = False,
    ) -> FaucetClaimResponse:
        try:
            result = (
                self.submitter.reconcile_transfer(envelope)
                if reconcile_only
                else self.submitter.submit_transfer(envelope)
            )
        except Exception as error:
            updated = self.store.mark_submission_unknown(
                request_id=record["request_id"],
                detail=f"SUBMISSION_UNKNOWN: {error}",
            )
            return self._response_from_record(updated)
        if result.operation_id != envelope.operation_id:
            raise ValueError("FAUCET_SUBMITTER_OPERATION_MISMATCH")
        if result.status == "FINALIZED":
            state_after_success = json_loads(record["state_after_success_json"])
            updated = self.store.finalize_claim(
                request_id=record["request_id"],
                policy_id=record["policy_id"],
                state_after_success=state_after_success,
                finalized_at=self._now().isoformat(),
                detail=result.detail,
            )
            return self._response_from_record(updated)
        if result.status == "ADMITTED":
            updated = self.store.mark_submission_unknown(
                request_id=record["request_id"],
                detail=f"PENDING_FINALITY: {result.detail or 'consensus admission accepted'}",
            )
            return self._response_from_record(updated)
        if result.status == "REJECTED":
            updated = self.store.mark_submission_rejected(
                request_id=record["request_id"],
                detail=f"SUBMISSION_REJECTED: {result.detail or 'consensus rejected the envelope'}",
            )
            return self._response_from_record(updated)
        updated = self.store.mark_submission_unknown(
            request_id=record["request_id"],
            detail=f"SUBMISSION_UNKNOWN: {result.detail or result.status}",
        )
        return self._response_from_record(updated)

    def _build_transfer_envelope(
        self,
        *,
        claim_id: str,
        recipient_wallet: str,
        decision: PolicyDecision,
        created_at: datetime,
    ) -> LedgerOperationEnvelope:
        try:
            sender_sequence = self.submitter.next_sender_sequence(self.manifest.wallet_id)
        except Exception as error:
            raise ValueError(f"FAUCET_SEQUENCE_UNAVAILABLE: {error}") from error
        unsigned = LedgerOperationEnvelope(
            operation_type="WALLET_TRANSFER",
            operation_version="1.0.0",
            protocol_version="0.1",
            origin_type="wallet",
            initiator_id=f"faucet:{self.manifest.treasury_id}",
            sender_wallet=self.manifest.wallet_id,
            sender_sequence=sender_sequence,
            fee_payer=self.manifest.wallet_id,
            fee_class="standard",
            created_at=created_at.isoformat(),
            expires_at=(created_at + timedelta(minutes=15)).isoformat(),
            payload={
                "recipient_wallet": recipient_wallet,
                "amount": decision.amount_q_atoms,
                "source": "FAUCET_TREASURY",
                "treasury_id": self.manifest.treasury_id,
                "claim_id": claim_id,
                "policy_id": decision.policy_id,
                "policy_version": decision.policy_version,
                "quota_key": decision.quota_key,
                "policy_decision_hash": decision.decision_hash,
            },
            evidence_references=[decision.decision_hash],
            signatures=[],
        )
        return unsigned.model_copy(update={"signatures": [self.signer.sign(unsigned.signing_bytes())]})

    def _verify_wallet_proof(self, request: FaucetClaimRequest) -> None:
        expected_wallet_id = wallet_id_for_public_key(request.wallet_public_key)
        if expected_wallet_id != request.wallet_id:
            raise ValueError("FAUCET_WALLET_ID_MISMATCH")
        challenge = self.store.get_challenge(request.challenge_id)
        if challenge is None or challenge["wallet_id"] != request.wallet_id:
            raise ValueError("FAUCET_CHALLENGE_INVALID")
        if bool(challenge["used"]):
            raise ValueError("FAUCET_CHALLENGE_USED")
        if self._now() >= datetime.fromisoformat(str(challenge["expires_at"])):
            raise ValueError("FAUCET_CHALLENGE_EXPIRED")
        typed = FaucetChallenge(**challenge)
        try:
            signature = bytes.fromhex(request.wallet_signature.removeprefix("ed25519:"))
            public_key = bytes.fromhex(request.wallet_public_key.removeprefix("ed25519:"))
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, typed.signing_bytes())
        except (ValueError, InvalidSignature) as error:
            raise ValueError("FAUCET_WALLET_PROOF_INVALID") from error

    def _consume_challenge(self, request: FaucetClaimRequest, *, now: datetime) -> None:
        del now
        if not self.store.mark_challenge_used(request.challenge_id):
            raise ValueError("FAUCET_CHALLENGE_USED")

    def _response_from_record(self, record: dict[str, Any]) -> FaucetClaimResponse:
        detail = record.get("detail")
        envelope = json_loads(record["envelope_json"])
        transaction_hash = cometbft_transaction_hash(
            serialize_faucet_envelope(LedgerOperationEnvelope.model_validate(envelope))
        )
        if record["status"] == "FINALIZED":
            status = "APPROVED"
        elif record["status"] == "REJECTED":
            status = "SUBMISSION_REJECTED"
        elif isinstance(detail, str) and detail.startswith("PENDING_FINALITY"):
            status = "PENDING_FINALITY"
        else:
            status = "SUBMISSION_UNKNOWN"
        return FaucetClaimResponse(
            request_id=record["request_id"],
            claim_id=record["claim_id"],
            status=status,
            amount_q_atoms=int(record["amount_q_atoms"]),
            operation_id=record["operation_id"],
            transaction_hash=transaction_hash,
            policy_id=record["policy_id"],
            policy_version=record["policy_version"],
            detail=detail,
        )

    def _control_state(self) -> dict[str, Any]:
        state = self.store.get_service_state("controls")
        if state is None:
            raise RuntimeError("FAUCET_CONTROL_STATE_MISSING")
        return state

    def _treasury_balance(self) -> int | None:
        if self._treasury_balance_provider is None:
            return None
        try:
            value = self._treasury_balance_provider(self.manifest.wallet_id)
        except Exception:
            return None
        if value is None or isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    def _ensure_claims_enabled(self) -> None:
        activation = self._treasury_activation()
        if self.require_treasury_activation and (
            activation is None or activation.state != "ACTIVE"
        ):
            reason = activation.reason if activation is not None else "verification disabled"
            raise ValueError(f"FAUCET_TREASURY_NOT_ACTIVE: {reason}")
        controls = self._control_state()
        if bool(controls["paused"]):
            raise ValueError("FAUCET_PAUSED")
        watermark = int(controls["low_balance_watermark_q_atoms"])
        if watermark <= 0:
            return
        balance = self._treasury_balance()
        if balance is None:
            raise ValueError("FAUCET_TREASURY_BALANCE_UNAVAILABLE")
        if balance < watermark:
            raise ValueError("FAUCET_LOW_BALANCE_PAUSED")


def json_loads(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Faucet persisted JSON object is invalid")
    return parsed
