import hashlib
import json
import threading
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.registry import (
    ManifestObjectEntry,
    RegistryDutyEvidence,
    RegistryDutyVerifier,
    RegistryInventoryManifest,
    RegistryRetentionPolicy,
)
from aidn_hypervisor.registry.object_envelope import (
    LedgerCommitmentClass,
    RegistryObjectEnvelope,
)
from aidn_hypervisor.registry.peer import PeerAuthenticator
from aidn_hypervisor.registry_models import (
    RegistryCompletenessIntegrity,
    RegistryCompletenessIssue,
    RegistryCompletenessTotals,
    RegistryConflictEvidence,
    RegistryDiscoveryQuery,
    RegistryLocalCompletenessSummary,
    RegistryNodeAdvertisement,
    RegistryObjectQuery,
    RegistryReplicationPeerConfig,
    RegistryWalletIdentityGovernancePolicy,
    RegistryWalletIdentityPeerConfig,
)

if TYPE_CHECKING:
    from aidn_hypervisor.consensus.finality import ConsensusFinalitySource
    from aidn_hypervisor.ledger.service import LedgerOperationService

_REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION = "registry-object-store.v1"
_LOCAL_REGISTRY_COMPLETENESS_SUMMARY_VERSION = (
    "registry-local-completeness-summary.v1"
)
_REQUIRED_REGISTRY_OBJECT_FIELDS = (
    "object_id",
    "object_type",
    "object_version",
    "namespace",
    "payload_hash",
    "payload_encoding",
    "source_reference",
)


def _normalize_peer_base_url(peer_base_url: str) -> str:
    parsed = urllib_parse.urlsplit(peer_base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("peer_base_url must be an absolute HTTP URL")
    if parsed.username or parsed.password:
        raise ValueError("peer_base_url must not include credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("peer_base_url must not include a path, query, or fragment")
    try:
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("peer_base_url port is invalid")
    except ValueError as error:
        raise ValueError("peer_base_url port is invalid") from error
    return urllib_parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
_WALLET_IDENTITY_NETWORK_OBJECT_TYPES = {
    "wallet_identity",
    "wallet_identity_resolution_proposal",
    "wallet_identity_resolution_approval",
    "wallet_identity_resolution",
    "wallet_identity_governance_certificate",
    "wallet_identity_governance_revocation",
}
_ALLOWED_WALLET_IDENTITY_VOTER_STATUSES = {"ready", "stale"}


class _RejectPeerRedirects(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class WalletIdentityPeerTransport:
    """Fetch wallet identity sync state without following peer redirects."""

    def fetch(self, request, *, timeout_seconds: int):
        return urllib_request.build_opener(_RejectPeerRedirects()).open(
            request, timeout=timeout_seconds
        )


class RegistryService:
    def __init__(
        self,
        *,
        stale_grace_seconds: int = 30,
        snapshot_path: str | Path | None = None,
        registry_service_id: str = "local-registry",
        registry_generation: int = 1,
        retention_policy: RegistryRetentionPolicy | None = None,
        ledger_operation_service: "LedgerOperationService | None" = None,
        consensus_finality_source: "ConsensusFinalitySource | None" = None,
        wallet_identity_peer_transport: WalletIdentityPeerTransport | None = None,
    ) -> None:
        self.stale_grace_seconds = stale_grace_seconds
        self.registry_service_id = registry_service_id
        self.registry_generation = int(registry_generation)
        self.retention_policy = retention_policy or RegistryRetentionPolicy()
        self._nodes: dict[str, dict] = {}
        self._registry_objects: dict[str, dict] = {}
        self._expired_registry_objects: set[str] = set()
        self._conflicts: dict[str, dict] = {}
        self._wallet_identity_peers: dict[str, dict] = {}
        self._replication_peers: dict[str, dict] = {}
        self._wallet_identity_resolutions: dict[str, dict] = {}
        self._wallet_identity_resolution_proposals: dict[str, dict] = {}
        self._wallet_identity_governance_revocations: dict[str, dict] = {}
        self._wallet_identity_governance_policy = (
            RegistryWalletIdentityGovernancePolicy().model_dump(mode="json")
        )
        self._ledger_operation_service = ledger_operation_service
        self._consensus_finality_source = consensus_finality_source
        self._wallet_identity_peer_transport = (
            wallet_identity_peer_transport or WalletIdentityPeerTransport()
        )
        self._snapshot_path = Path(snapshot_path) if snapshot_path is not None else None
        self._snapshot_lock = threading.RLock()
        self._loading_registry_object_snapshot = True
        try:
            self._load_registry_object_snapshot()
        finally:
            self._loading_registry_object_snapshot = False

    def bind_ledger_operation_service(
        self,
        ledger_operation_service: "LedgerOperationService",
    ) -> None:
        """Attach the local canonical ledger used for strict governance policy."""
        if self._ledger_operation_service not in {None, ledger_operation_service}:
            raise ValueError("Registry already has a different Ledger operation service")
        self._ledger_operation_service = ledger_operation_service
        self._rebuild_wallet_identity_resolution_state()

    def bind_consensus_finality_source(
        self,
        consensus_finality_source: "ConsensusFinalitySource",
    ) -> None:
        """Attach the verified network finality source used by Registry reports."""
        if (
            self._consensus_finality_source is not None
            and self._consensus_finality_source is not consensus_finality_source
        ):
            raise ValueError("Registry already has a different consensus finality source")
        self._consensus_finality_source = consensus_finality_source

    def reputation_profile_finality(
        self,
        object_id: str,
        *,
        effective_epoch: int | None = None,
    ) -> dict:
        """Return a read-only, finality-aware Reputation profile projection.

        Local Registry data and local Reputation scores are not sufficient to
        claim canonical Reputation.  This read model therefore returns the
        committed operation identity while finality is pending, but withholds
        the profile-root payload until the operation-bound finality adapter
        verifies it.
        """
        normalized_object_id = str(object_id).strip()
        if not normalized_object_id:
            raise ValueError("Reputation profile object_id is required")

        base = {
            "object_id": normalized_object_id,
            "consensus_finalized": False,
            "profile_update": None,
        }
        if self._ledger_operation_service is None:
            return {**base, "status": "unavailable"}

        commitment = self._ledger_operation_service.reputation_profile_update_commitment(
            normalized_object_id,
            effective_epoch=effective_epoch,
        )
        if commitment is None:
            return {**base, "status": "not_found"}

        operation_id = commitment.get("operation_id")
        payload = commitment.get("payload")
        pending = {
            **base,
            "status": "pending_finality",
        }
        if isinstance(operation_id, str) and operation_id.strip():
            pending["operation_id"] = operation_id
        if isinstance(payload, dict) and isinstance(payload.get("effective_epoch"), int):
            pending["effective_epoch"] = payload["effective_epoch"]

        from aidn_hypervisor.consensus.reputation_finality import (
            ReputationProfileFinalityAdapter,
        )

        projection = ReputationProfileFinalityAdapter(
            ledger_service=self._ledger_operation_service,
            finality_source=self._consensus_finality_source,
        ).resolve(
            object_id=normalized_object_id,
            effective_epoch=effective_epoch,
        )
        if projection is None:
            return pending

        return {
            "status": "consensus_finalized",
            "consensus_finalized": True,
            "object_id": projection.object_id,
            "effective_epoch": projection.effective_epoch,
            "operation_id": projection.operation_id,
            "profile_update": projection.model_dump(),
        }

    def upsert_node(self, payload: RegistryNodeAdvertisement) -> dict:
        self._validate_wallet_identity_objects(
            payload.model_dump(mode="json").get("canonical_registry_objects", []),
            exclude_node_id=payload.node_id,
        )
        self._nodes[payload.node_id] = payload.model_dump(mode="json")
        return self.get_node(payload.node_id)

    def list_nodes(self) -> list[dict]:
        return [self.get_node(node_id) for node_id in sorted(self._nodes)]

    def list_conflicts(
        self,
        *,
        conflict_class: str | None = None,
        object_type: str | None = None,
        logical_key: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        items = []
        for conflict_id in sorted(self._conflicts):
            item = deepcopy(self._conflicts[conflict_id])
            if conflict_class is not None and item.get("conflict_class") != conflict_class:
                continue
            if object_type is not None and item.get("object_type") != object_type:
                continue
            if logical_key is not None and item.get("logical_key") != logical_key:
                continue
            items.append(item)
        return items[:limit]

    def list_wallet_identity_objects(self, *, limit: int = 500) -> list[dict]:
        return self.list_registry_objects(
            {
                "object_type": "wallet_identity",
                "namespace": "identity",
                "include_payload": True,
                "limit": limit,
            }
        )

    def list_wallet_identity_network_objects(self, *, limit: int = 500) -> list[dict]:
        objects = self.list_registry_objects(
            {
                "namespace": "identity",
                "include_payload": True,
                "limit": min(max(limit * 4, limit), 500),
            }
        )
        filtered = [
            item
            for item in objects
            if item.get("object_type") in _WALLET_IDENTITY_NETWORK_OBJECT_TYPES
        ]
        return filtered[:limit]

    def upsert_wallet_identity_peer(
        self,
        *,
        peer_base_url: str,
        enabled: bool = True,
        expected_node_id: str | None = None,
        expected_operator_id: str | None = None,
        expected_owner_wallet_id: str | None = None,
    ) -> dict:
        normalized_base_url = _normalize_peer_base_url(peer_base_url)
        existing = deepcopy(self._wallet_identity_peers.get(normalized_base_url) or {})
        now = datetime.now(UTC).isoformat()
        record = {
            "peer_base_url": normalized_base_url,
            "enabled": bool(enabled),
            "added_at": existing.get("added_at") or now,
            "last_sync_at": existing.get("last_sync_at"),
            "last_sync_status": existing.get("last_sync_status"),
            "last_sync_error": existing.get("last_sync_error"),
            "last_import_result": deepcopy(existing.get("last_import_result")),
        }
        for field, requested_value in {
            "expected_node_id": expected_node_id,
            "expected_operator_id": expected_operator_id,
            "expected_owner_wallet_id": expected_owner_wallet_id,
        }.items():
            resolved_value = requested_value or existing.get(field)
            if resolved_value is not None:
                record[field] = resolved_value
        self._wallet_identity_peers[normalized_base_url] = record
        self._persist_registry_object_snapshot()
        return deepcopy(record)

    def list_wallet_identity_peers(self) -> list[dict]:
        return [
            deepcopy(self._wallet_identity_peers[peer_base_url])
            for peer_base_url in sorted(self._wallet_identity_peers)
        ]

    def upsert_replication_peer(
        self,
        *,
        peer_id: str,
        public_key: str,
        enabled: bool = True,
    ) -> dict:
        """Locally approve one Registry replication identity.

        Discovery data is intentionally not accepted here: a peer must be
        configured by the operator before strict replication can authenticate it.
        """
        normalized_peer_id = str(peer_id).strip()
        if not normalized_peer_id:
            raise ValueError("peer_id is required")
        normalized_public_key = str(public_key).strip()
        PeerAuthenticator().register_key(normalized_peer_id, normalized_public_key)

        existing = deepcopy(self._replication_peers.get(normalized_peer_id) or {})
        now = datetime.now(UTC).isoformat()
        key_changed = existing.get("public_key") not in {None, normalized_public_key}
        record = {
            "peer_id": normalized_peer_id,
            "public_key": normalized_public_key,
            "enabled": bool(enabled),
            "added_at": existing.get("added_at") or now,
            "updated_at": now,
            "last_authenticated_at": None
            if key_changed or not enabled
            else existing.get("last_authenticated_at"),
            "last_authentication_error": None
            if key_changed or not enabled
            else existing.get("last_authentication_error"),
        }
        with self._snapshot_lock:
            self._replication_peers[normalized_peer_id] = record
            self._persist_registry_object_snapshot()
        return deepcopy(record)

    def list_replication_peers(self) -> list[dict]:
        """Return operator-managed Registry replication peer identities."""
        return [
            deepcopy(self._replication_peers[peer_id])
            for peer_id in sorted(self._replication_peers)
        ]

    def record_replication_peer_authentication(
        self,
        *,
        peer_id: str,
        authenticated: bool,
        error: str | None = None,
    ) -> dict:
        """Persist handshake outcome without ever accepting a new peer key."""
        record = self._replication_peers.get(peer_id)
        if record is None:
            raise ValueError("Registry replication peer is not configured")
        updated = deepcopy(record)
        if authenticated:
            updated["last_authenticated_at"] = datetime.now(UTC).isoformat()
            updated["last_authentication_error"] = None
        else:
            updated["last_authentication_error"] = error or "authentication_failed"
        with self._snapshot_lock:
            self._replication_peers[peer_id] = updated
            self._persist_registry_object_snapshot()
        return deepcopy(updated)

    def list_wallet_identity_resolutions(self) -> list[dict]:
        return [
            deepcopy(self._wallet_identity_resolutions[wallet_id])
            for wallet_id in sorted(self._wallet_identity_resolutions)
        ]

    def list_wallet_identity_resolution_proposals(self) -> list[dict]:
        return [
            deepcopy(self._wallet_identity_resolution_proposals[resolution_id])
            for resolution_id in sorted(self._wallet_identity_resolution_proposals)
        ]

    def list_wallet_identity_governance_certificates(self, *, limit: int = 500) -> list[dict]:
        """Return portable authority evidence for finalized wallet resolutions."""
        return self.list_registry_objects(
            {
                "object_type": "wallet_identity_governance_certificate",
                "namespace": "identity",
                "include_payload": True,
                "limit": limit,
            }
        )

    def list_wallet_identity_governance_revocations(self, *, limit: int = 500) -> list[dict]:
        return self.list_registry_objects(
            {
                "object_type": "wallet_identity_governance_revocation",
                "namespace": "identity",
                "include_payload": True,
                "limit": limit,
            }
        )

    def wallet_identity_governance_certificate_ledger_proof(
        self,
        certificate_id: str,
    ) -> dict | None:
        if self._ledger_operation_service is None:
            return None
        operation = self._ledger_operation_service.wallet_identity_governance_certificate_commitment(
            certificate_id
        )
        if operation is None:
            return None
        return self._ledger_operation_service.governance_commitment_proof(operation)

    def wallet_identity_governance_revocation_ledger_proof(
        self,
        certificate_id: str,
    ) -> dict | None:
        if self._ledger_operation_service is None:
            return None
        operation = self._ledger_operation_service.wallet_identity_governance_certificate_revocation(
            certificate_id
        )
        if operation is None:
            return None
        return self._ledger_operation_service.governance_commitment_proof(operation)

    def wallet_identity_governance_certificate_peer_proof_report(
        self,
        certificate_id: str,
        *,
        timeout_seconds: int = 10,
    ) -> dict:
        return self._wallet_identity_governance_peer_proof_report(
            certificate_id=certificate_id,
            local_proof=self.wallet_identity_governance_certificate_ledger_proof(certificate_id),
            expected_operation_type="GOVERNANCE_AUTHORIZATION_COMMIT",
            peer_path=(
                "/registry/wallet-identities/governance-certificates/"
                f"{urllib_parse.quote(certificate_id, safe='')}/ledger-proof"
            ),
            timeout_seconds=timeout_seconds,
        )

    def wallet_identity_governance_revocation_peer_proof_report(
        self,
        certificate_id: str,
        *,
        timeout_seconds: int = 10,
    ) -> dict:
        return self._wallet_identity_governance_peer_proof_report(
            certificate_id=certificate_id,
            local_proof=self.wallet_identity_governance_revocation_ledger_proof(certificate_id),
            expected_operation_type="GOVERNANCE_AUTHORIZATION_REVOKE",
            peer_path=(
                "/registry/wallet-identities/governance-revocations/"
                f"{urllib_parse.quote(certificate_id, safe='')}/ledger-proof"
            ),
            timeout_seconds=timeout_seconds,
        )

    def _wallet_identity_governance_peer_proof_report(
        self,
        *,
        certificate_id: str,
        local_proof: dict | None,
        expected_operation_type: str,
        peer_path: str,
        timeout_seconds: int,
    ) -> dict:
        """Compare verified local evidence with peer records without claiming finality."""
        if self._ledger_operation_service is None:
            raise ValueError("Wallet-identity governance Ledger is unavailable")
        if local_proof is None:
            raise KeyError(certificate_id)
        local_summary = self._ledger_operation_service.verify_governance_commitment_proof(
            local_proof,
            certificate_id=certificate_id,
            expected_operation_type=expected_operation_type,
        )
        peer_results: list[dict] = []
        for peer_base_url in sorted(self._wallet_identity_peers):
            peer = self._wallet_identity_peers[peer_base_url]
            if not peer.get("enabled", True):
                continue
            request = urllib_request.Request(
                (
                    f"{peer_base_url}{peer_path}"
                ),
                method="GET",
            )
            try:
                with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
                    peer_proof = json.loads(response.read().decode("utf-8"))
                if not isinstance(peer_proof, dict):
                    raise ValueError("peer response is not an object")
                peer_summary = self._ledger_operation_service.verify_governance_commitment_proof(
                    peer_proof,
                    certificate_id=certificate_id,
                    expected_operation_type=expected_operation_type,
                )
            except (urllib_error.URLError, TimeoutError, json.JSONDecodeError) as error:
                peer_results.append(
                    {
                        "peer_base_url": peer_base_url,
                        "status": "unavailable",
                        "error": str(error),
                    }
                )
                continue
            except (TypeError, ValueError) as error:
                peer_results.append(
                    {
                        "peer_base_url": peer_base_url,
                        "status": "invalid",
                        "error": str(error),
                    }
                )
                continue
            peer_results.append(
                {
                    "peer_base_url": peer_base_url,
                    "status": (
                        "matching"
                        if peer_summary["commitment_subject_hash"]
                        == local_summary["commitment_subject_hash"]
                        else "mismatched"
                    ),
                    "operation_id": peer_summary["operation_id"],
                    "commitment_subject_hash": peer_summary["commitment_subject_hash"],
                }
            )
        matching_peer_count = sum(
            1 for item in peer_results if item["status"] == "matching"
        )
        finality = self._consensus_finality_summary(local_summary["operation_id"])
        return {
            "report_version": "wallet-identity-governance-peer-proof-report.v1",
            "certificate_id": certificate_id,
            "local_proof": local_proof,
            "enabled_peer_count": len(peer_results),
            "matching_peer_count": matching_peer_count,
            "mismatched_peer_count": sum(
                1 for item in peer_results if item["status"] == "mismatched"
            ),
            "invalid_peer_count": sum(
                1 for item in peer_results if item["status"] == "invalid"
            ),
            "unavailable_peer_count": sum(
                1 for item in peer_results if item["status"] == "unavailable"
            ),
            "peer_results": peer_results,
            **finality,
        }

    def _consensus_finality_summary(self, operation_id: str) -> dict:
        """Return only independently verified network finality, never local state."""
        if self._consensus_finality_source is None:
            return {
                "consensus_finality": False,
                "finality_evidence": None,
                "finality_note": (
                    "Peer agreement verifies matching local Ledger evidence only; "
                    "no verified network finality source is configured."
                ),
            }
        try:
            evidence = self._consensus_finality_source.finality_evidence(operation_id)
        except Exception:
            evidence = None
        if (
            not isinstance(evidence, ConsensusFinalityEvidence)
            or evidence.operation_id != operation_id
        ):
            return {
                "consensus_finality": False,
                "finality_evidence": None,
                "finality_note": (
                    "No verified network finality evidence is available for this operation."
                ),
            }
        return {
            "consensus_finality": True,
            "finality_evidence": evidence.model_dump(),
            "finality_note": "Verified network finality evidence is available.",
        }

    def commit_registry_duty_evidence(
        self,
        evidence: RegistryDutyEvidence,
        *,
        expected_inventory_manifest: RegistryInventoryManifest | None = None,
        verifier: RegistryDutyVerifier | None = None,
        created_at: str | None = None,
    ) -> dict:
        """Commit finality-bound Registry evidence without minting rewards.

        The local Ledger receives only ``SERVICE_VERIFICATION_COMMIT``.  A
        later epoch task must consume the returned eligibility/reward input and
        produce any canonical reward calculation or ``REWARD_MINT`` operation.
        """
        if evidence.registry_service_id != self.registry_service_id:
            raise ValueError("Registry Duty evidence belongs to another Registry")
        if expected_inventory_manifest is None:
            expected_inventory_manifest = self.get_local_registry_inventory_manifest(
                generated_at_epoch=evidence.epoch,
            )
        effective_verifier = verifier or RegistryDutyVerifier(
            finality_source=self._consensus_finality_source,
            expected_registry_service_id=self.registry_service_id,
            required_profile_version=evidence.profile_version,
            required_protocol_version=evidence.required_protocol_version,
        )
        decision = effective_verifier.evaluate(
            evidence,
            expected_epoch=evidence.epoch,
            expected_inventory_manifest=expected_inventory_manifest,
        )
        if not decision.valid:
            reasons = ",".join(decision.reasons) or "invalid_evidence"
            raise ValueError(f"Registry Duty evidence is not finality-valid: {reasons}")
        if self._ledger_operation_service is None:
            raise ValueError("Registry Duty evidence requires an attached Ledger")
        eligibility_snapshot = effective_verifier.build_eligibility_snapshot(
            evidence,
            decision,
        )

        registry_reference = {
            "inventory_manifest_id": evidence.inventory_manifest_id,
            "inventory_root": evidence.inventory_root,
            "finalized_operation_id": evidence.finalized_operation_id,
            "profile_version": evidence.profile_version,
            "profile_hash": evidence.profile_hash,
        }
        result_summary = {
            "eligible": decision.eligible,
            "reasons": list(decision.reasons),
            "decision_hash": decision.decision_hash,
            "eligibility_snapshot_id": eligibility_snapshot.snapshot_id,
            "raw_weight_millionths": decision.raw_weight_millionths,
            "proof_success_millionths": decision.proof_success_millionths,
            "completeness_millionths": decision.completeness_millionths,
            "availability_millionths": decision.availability_millionths,
            "reward_beneficiary": evidence.reward_beneficiary,
            "known_control_group_id": evidence.known_control_group_id,
        }
        record = self._ledger_operation_service.commit_service_verification(
            verification_report_id=evidence.evidence_id,
            service_id=evidence.registry_service_id,
            service_type=evidence.service_type,
            report_hash=evidence.evidence_hash,
            evidence_root=evidence.evidence_hash,
            verification_epoch=evidence.epoch,
            result_summary=result_summary,
            registry_reference=registry_reference,
            evidence_references=[
                evidence.evidence_id,
                evidence.inventory_manifest_id,
                evidence.inventory_root,
                evidence.finalized_operation_id,
            ],
            signatures=[evidence.signature] if evidence.signature else [],
            created_at=created_at,
        )

        payload = {
            "evidence": evidence.model_dump(mode="json"),
            "eligibility": decision.model_dump(mode="json"),
            "eligibility_snapshot": eligibility_snapshot.model_dump(mode="json"),
            "ledger_operation_id": record["operation_id"],
        }
        registry_object = RegistryObjectEnvelope.create(
            object_id=evidence.evidence_id,
            object_type="registry_duty_evidence",
            namespace="verification",
            payload=payload,
            created_epoch=evidence.epoch,
            created_block_height=int(evidence.finality_evidence["block_height"]),
            ledger_commitment=LedgerCommitmentClass.LEDGER_OPERATION,
            parent_references=[evidence.finalized_operation_id],
            producer_signature=evidence.signature or None,
        )
        stored_object = self.upsert_registry_object(
            registry_object.model_dump(mode="json")
        )
        reward_input = None
        if decision.eligible:
            reward_input = effective_verifier.build_reward_input(evidence, decision)
        return {
            "evidence": evidence.model_dump(mode="json"),
            "eligibility": decision.model_dump(mode="json"),
            "eligibility_snapshot": eligibility_snapshot.model_dump(mode="json"),
            "reward_input": (
                reward_input.model_dump(mode="json") if reward_input is not None else None
            ),
            "ledger_commitment": {
                "operation_id": record["operation_id"],
                "operation_type": record["operation_type"],
                "verification_epoch": evidence.epoch,
            },
            "registry_object": stored_object,
        }

    def revoke_wallet_identity_governance_certificate(
        self,
        *,
        certificate_id: str,
        reason: str,
        approvals: list[dict],
    ) -> dict:
        existing = self._wallet_identity_governance_revocations.get(certificate_id)
        if existing is not None:
            if existing.get("reason") != reason:
                raise ValueError("Wallet-identity governance certificate has conflicting revocations")
            return deepcopy(existing)
        certificate = self._wallet_identity_governance_certificate_payload(certificate_id)
        if certificate is None:
            raise KeyError(certificate_id)
        self._verify_wallet_identity_governance_certificate(certificate)
        from aidn_hypervisor.wallet_identity import wallet_identity_governance_revocation_id

        eligible_voter_node_ids = list(certificate["eligible_voter_node_ids"])
        revocation = {
            "revocation_version": "wallet-identity-governance-revocation.v1",
            "certificate_id": certificate_id,
            "reason": reason,
            "eligible_voter_node_ids": eligible_voter_node_ids,
            "voter_authorities": deepcopy(certificate["voter_authorities"]),
            "quorum_threshold": int(certificate["quorum_threshold"]),
            "approvals": sorted(
                [deepcopy(item) for item in approvals],
                key=lambda item: str(item.get("approver_node_id") or ""),
            ),
        }
        revocation["revocation_id"] = wallet_identity_governance_revocation_id(
            certificate_id=certificate_id,
            reason=reason,
            eligible_voter_node_ids=eligible_voter_node_ids,
            quorum_threshold=revocation["quorum_threshold"],
        )
        self._verify_wallet_identity_governance_revocation(
            revocation,
            require_ledger=False,
        )
        if self._ledger_operation_service is None:
            if self._wallet_identity_governance_policy.get("ledger_authorization_required"):
                raise ValueError("Wallet-identity governance policy requires an available Ledger")
        else:
            record = self._ledger_operation_service.commit_wallet_identity_governance_revocation(revocation)
            revocation["ledger_commitment"] = {
                "operation_id": record["operation_id"],
                "sequence_id": record["sequence_id"],
                "certificate_id": certificate_id,
                "operation_type": record["operation_type"],
            }
        revocation["revoked_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self.upsert_registry_object(
            self._wallet_identity_governance_revocation_registry_object(revocation)
        )
        return deepcopy(revocation)

    def wallet_identity_governance_policy(self) -> dict:
        return deepcopy(self._wallet_identity_governance_policy)

    def update_wallet_identity_governance_policy(
        self,
        *,
        authorized_voter_statuses: list[str] | None = None,
        threshold_mode: str | None = None,
        minimum_eligible_voter_count: int | None = None,
        minimum_quorum_threshold: int | None = None,
        quorum_resolution_required: bool | None = None,
        ledger_authorization_required: bool | None = None,
    ) -> dict:
        policy = deepcopy(self._wallet_identity_governance_policy)
        if authorized_voter_statuses is not None:
            normalized_statuses = sorted(
                {
                    str(item).strip()
                    for item in authorized_voter_statuses
                    if str(item).strip()
                }
            )
            if not normalized_statuses:
                raise ValueError(
                    "authorized_voter_statuses must contain at least one status"
                )
            invalid_statuses = sorted(
                set(normalized_statuses) - _ALLOWED_WALLET_IDENTITY_VOTER_STATUSES
            )
            if invalid_statuses:
                raise ValueError(
                    "authorized_voter_statuses contains unsupported values: "
                    + ", ".join(invalid_statuses)
                )
            policy["authorized_voter_statuses"] = normalized_statuses
        if threshold_mode is not None:
            normalized_threshold_mode = str(threshold_mode).strip()
            if normalized_threshold_mode != "majority":
                raise ValueError(
                    "threshold_mode must currently be 'majority' for wallet identity governance"
                )
            policy["threshold_mode"] = normalized_threshold_mode
        if minimum_eligible_voter_count is not None:
            if minimum_eligible_voter_count < 1:
                raise ValueError("minimum_eligible_voter_count must be at least 1")
            policy["minimum_eligible_voter_count"] = int(minimum_eligible_voter_count)
        if minimum_quorum_threshold is not None:
            if minimum_quorum_threshold < 1:
                raise ValueError("minimum_quorum_threshold must be at least 1")
            policy["minimum_quorum_threshold"] = int(minimum_quorum_threshold)
        if quorum_resolution_required is not None:
            policy["quorum_resolution_required"] = bool(quorum_resolution_required)
        if ledger_authorization_required is not None:
            policy["ledger_authorization_required"] = bool(ledger_authorization_required)
        if policy["ledger_authorization_required"] and not policy["quorum_resolution_required"]:
            raise ValueError("ledger_authorization_required requires quorum_resolution_required")
        policy["updated_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        model = RegistryWalletIdentityGovernancePolicy.model_validate(policy)
        self._wallet_identity_governance_policy = model.model_dump(mode="json")
        self._persist_registry_object_snapshot()
        return self.wallet_identity_governance_policy()

    def propose_wallet_identity_quorum_resolution(
        self,
        *,
        wallet_id: str,
        chosen_object_id: str | None = None,
        chosen_payload_hash: str | None = None,
        proposer_node_id: str,
        proposer_signature: str | None = None,
        eligible_voter_node_ids: list[str] | None = None,
        quorum_threshold: int | None = None,
        operator_note: str | None = None,
    ) -> dict:
        selected = self._select_wallet_identity_resolution_candidate(
            wallet_id=wallet_id,
            chosen_object_id=chosen_object_id,
            chosen_payload_hash=chosen_payload_hash,
        )
        requested_voters = self._normalize_requested_wallet_identity_voters(
            eligible_voter_node_ids=eligible_voter_node_ids,
        )
        authoritative_voters = self._authoritative_wallet_identity_voters(
            wallet_id=wallet_id,
            chosen_object_id=str(selected["object_id"]),
            chosen_payload_hash=str(selected["payload_hash"]),
        )
        if proposer_node_id not in authoritative_voters:
            raise ValueError(
                f"Proposer {proposer_node_id} is not authoritative for wallet identity resolution {wallet_id}"
            )
        if requested_voters and requested_voters != authoritative_voters:
            raise ValueError(
                "Requested eligible voters do not match the authoritative wallet identity voter set"
            )
        threshold = self._wallet_identity_quorum_threshold(
            eligible_voter_node_ids=authoritative_voters,
            quorum_threshold=quorum_threshold,
        )
        self._verify_wallet_identity_quorum_proposal_signature(
            wallet_id=wallet_id,
            chosen_object_id=str(selected["object_id"]),
            chosen_payload_hash=str(selected["payload_hash"]),
            proposer_node_id=proposer_node_id,
            proposer_signature=proposer_signature,
            eligible_voter_node_ids=authoritative_voters,
            quorum_threshold=threshold,
            operator_note=operator_note,
        )
        payload = {
            "wallet_id": wallet_id,
            "chosen_object_id": str(selected["object_id"]),
            "chosen_payload_hash": str(selected["payload_hash"]),
            "eligible_voter_node_ids": authoritative_voters,
            "quorum_threshold": threshold,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        resolution_id = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        existing = self._wallet_identity_resolution_proposals.get(resolution_id)
        if existing is None:
            proposal = {
                "resolution_id": resolution_id,
                "wallet_id": wallet_id,
                "chosen_object_id": str(selected["object_id"]),
                "chosen_payload_hash": str(selected["payload_hash"]),
                "public_key": selected.get("payload", {}).get("public_key"),
                "registration_nonce": selected.get("payload", {}).get(
                    "registration_nonce"
                ),
                "requested_voter_node_ids": requested_voters,
                "eligible_voter_node_ids": authoritative_voters,
                "voter_policy": "wallet_identity_source_nodes_with_owner_wallet_link.v1",
                "quorum_threshold": threshold,
                "governance_policy_snapshot": self.wallet_identity_governance_policy(),
                "status": "pending",
                "operator_note": operator_note,
                "proposed_at": now,
                "approvals": [],
                "final_resolution": None,
            }
        else:
            proposal = deepcopy(existing)
            if (
                proposal.get("chosen_object_id") != str(selected["object_id"])
                or proposal.get("chosen_payload_hash") != str(selected["payload_hash"])
            ):
                raise ValueError(
                    f"Resolution proposal {resolution_id} conflicts with existing candidate"
                )
        proposal = self._record_wallet_identity_resolution_approval(
            proposal=proposal,
            approver_node_id=proposer_node_id,
            approval_signature=proposer_signature,
            approval_note=operator_note,
            approved_at=now,
            approval_kind="proposal",
        )
        self._wallet_identity_resolution_proposals[resolution_id] = proposal
        self.upsert_registry_object(
            self._wallet_identity_quorum_proposal_registry_object(proposal)
        )
        self.upsert_registry_object(
            self._wallet_identity_quorum_approval_registry_object(
                resolution_id=resolution_id,
                wallet_id=wallet_id,
                approval=proposal["approvals"][-1],
            )
        )
        self._finalize_wallet_identity_resolution_proposal(resolution_id)
        self._persist_registry_object_snapshot()
        return deepcopy(self._wallet_identity_resolution_proposals[resolution_id])

    def approve_wallet_identity_quorum_resolution(
        self,
        *,
        resolution_id: str,
        approver_node_id: str,
        approval_signature: str | None = None,
        approval_note: str | None = None,
    ) -> dict:
        proposal = deepcopy(self._wallet_identity_resolution_proposals.get(resolution_id))
        if proposal is None:
            raise KeyError(resolution_id)
        if proposal.get("status") == "finalized":
            return proposal
        eligible_voters = list(proposal.get("eligible_voter_node_ids") or [])
        if eligible_voters and approver_node_id not in eligible_voters:
            raise ValueError(
                f"Approver {approver_node_id} is not eligible for resolution {resolution_id}"
            )
        self._verify_wallet_identity_quorum_approval_signature(
            resolution_id=resolution_id,
            approver_node_id=approver_node_id,
            approval_signature=approval_signature,
            approval_note=approval_note,
        )
        proposal = self._record_wallet_identity_resolution_approval(
            proposal=proposal,
            approver_node_id=approver_node_id,
            approval_signature=approval_signature,
            approval_note=approval_note,
            approved_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            approval_kind="approval",
        )
        self._wallet_identity_resolution_proposals[resolution_id] = proposal
        self.upsert_registry_object(
            self._wallet_identity_quorum_approval_registry_object(
                resolution_id=resolution_id,
                wallet_id=str(proposal["wallet_id"]),
                approval=proposal["approvals"][-1],
            )
        )
        self._finalize_wallet_identity_resolution_proposal(resolution_id)
        self._persist_registry_object_snapshot()
        return deepcopy(self._wallet_identity_resolution_proposals[resolution_id])

    def resolve_wallet_identity_conflict(
        self,
        *,
        wallet_id: str,
        chosen_object_id: str | None = None,
        chosen_payload_hash: str | None = None,
        operator_note: str | None = None,
        governance_certificate: dict | None = None,
    ) -> dict:
        if (
            self._wallet_identity_governance_policy.get("quorum_resolution_required")
            and governance_certificate is None
        ):
            raise ValueError("Wallet-identity resolution requires a quorum governance certificate")
        matches = self._wallet_identity_matches(wallet_id)
        selected = self._select_wallet_identity_resolution_candidate(
            wallet_id=wallet_id,
            chosen_object_id=chosen_object_id,
            chosen_payload_hash=chosen_payload_hash,
        )
        selected_record = deepcopy(selected)
        selected_record.pop("_source", None)
        self.upsert_registry_object(selected_record)
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        payload = deepcopy(selected_record.get("payload") or {})
        resolution = {
            "wallet_id": wallet_id,
            "chosen_object_id": str(selected_record["object_id"]),
            "chosen_payload_hash": str(selected_record["payload_hash"]),
            "public_key": payload.get("public_key"),
            "registration_nonce": payload.get("registration_nonce"),
            "resolved_at": now,
            "operator_note": operator_note,
            "source_nodes": sorted(
                {
                    str(item.get("_source", {}).get("node_id"))
                    for item in matches
                    if item.get("_source", {}).get("node_id") is not None
                    and item.get("object_id") == selected_record["object_id"]
                    and item.get("payload_hash") == selected_record["payload_hash"]
                }
            ),
        }
        if governance_certificate is not None:
            self._verify_wallet_identity_governance_certificate(governance_certificate)
            resolution["governance_certificate"] = deepcopy(governance_certificate)
        self._wallet_identity_resolutions[wallet_id] = resolution
        self.upsert_registry_object(
            self._wallet_identity_resolution_registry_object(resolution=resolution)
        )
        for conflict_id in sorted(self._conflicts):
            conflict = self._conflicts[conflict_id]
            if (
                conflict.get("conflict_class") == "wallet_identity_binding"
                and conflict.get("object_type") == "wallet_identity"
                and conflict.get("logical_key") == wallet_id
            ):
                conflict["status"] = "resolved"
                conflict["resolved_at"] = now
                conflict["resolution_note"] = operator_note
                conflict["resolution_payload"] = {
                    "wallet_id": wallet_id,
                    "chosen_object_id": resolution["chosen_object_id"],
                    "chosen_payload_hash": resolution["chosen_payload_hash"],
                }
        self._persist_registry_object_snapshot()
        return deepcopy(resolution)

    def discover_wallet_identity_peers_from_nodes(
        self,
        *,
        self_node_id: str | None = None,
        include_stale: bool = False,
        auto_register: bool = True,
    ) -> dict:
        candidates: list[dict] = []
        discovered_urls: set[str] = set()
        registered_count = 0

        for node_id in sorted(self._nodes):
            node = self.get_node(node_id)
            if self_node_id is not None and node.get("node_id") == self_node_id:
                continue
            if node.get("status") == "offline":
                continue
            if node.get("status") == "stale" and not include_stale:
                continue
            base_url = str(node.get("base_url") or "").rstrip("/")
            if not base_url or base_url in discovered_urls:
                continue
            discovered_urls.add(base_url)
            existing_peer = deepcopy(self._wallet_identity_peers.get(base_url) or {})
            candidate = {
                "peer_base_url": base_url,
                "node_id": node.get("node_id"),
                "operator_id": node.get("operator_id"),
                "owner_wallet_id": node.get("owner_wallet_id"),
                "status": node.get("status"),
                "already_registered": bool(existing_peer),
                "enabled": existing_peer.get("enabled", True),
                "last_sync_at": existing_peer.get("last_sync_at"),
                "last_sync_status": existing_peer.get("last_sync_status"),
            }
            candidates.append(candidate)
            if auto_register and not existing_peer:
                peer_identity_pins = {}
                if node.get("owner_wallet_id"):
                    peer_identity_pins = {
                        "expected_node_id": node.get("node_id"),
                        "expected_operator_id": node.get("operator_id"),
                        "expected_owner_wallet_id": node.get("owner_wallet_id"),
                    }
                self.upsert_wallet_identity_peer(
                    peer_base_url=base_url,
                    enabled=True,
                    **peer_identity_pins,
                )
                registered_count += 1

        return {
            "candidate_count": len(candidates),
            "registered_count": registered_count,
            "candidates": candidates,
        }

    def export_wallet_identity_sync_state(self, *, limit: int = 500) -> dict:
        return {
            "objects": self.list_wallet_identity_network_objects(limit=limit),
            "conflicts": self.list_conflicts(
                conflict_class="wallet_identity_binding",
                object_type="wallet_identity",
                limit=limit,
            ),
        }

    def ingest_conflict_evidence(self, conflicts: list[dict]) -> list[dict]:
        accepted: list[dict] = []
        changed = False
        for item in conflicts:
            model = RegistryConflictEvidence.model_validate(item)
            if model.conflict_id in self._conflicts:
                continue
            self._conflicts[model.conflict_id] = model.model_dump(mode="json")
            accepted.append(deepcopy(self._conflicts[model.conflict_id]))
            changed = True
        if changed:
            self._persist_registry_object_snapshot()
        return accepted

    def import_wallet_identity_sync_state(
        self,
        *,
        objects: list[dict],
        conflicts: list[dict],
    ) -> dict:
        imported_objects = 0
        rejected_objects: list[dict] = []
        for item in objects:
            try:
                self.upsert_registry_object(item)
                imported_objects += 1
            except ValueError as error:
                rejected_objects.append(
                    {
                        "source_reference": item.get("source_reference"),
                        "object_id": item.get("object_id"),
                        "reason": str(error),
                    }
                )
        accepted_conflicts = self.ingest_conflict_evidence(conflicts)
        return {
            "imported_object_count": imported_objects,
            "rejected_objects": rejected_objects,
            "accepted_conflict_count": len(accepted_conflicts),
            "conflict_count": len(
                self.list_conflicts(
                    conflict_class="wallet_identity_binding",
                    object_type="wallet_identity",
                )
            ),
        }

    def sync_wallet_identity_from_peer(
        self,
        *,
        peer_base_url: str,
        limit: int = 500,
        timeout_seconds: int = 10,
        expected_node_id: str | None = None,
        expected_operator_id: str | None = None,
        expected_owner_wallet_id: str | None = None,
    ) -> dict:
        normalized_base_url = _normalize_peer_base_url(peer_base_url)
        request = urllib_request.Request(
            f"{normalized_base_url}/registry/wallet-identities/sync-state?limit={int(limit)}",
            method="GET",
        )
        try:
            with self._wallet_identity_peer_transport.fetch(
                request, timeout_seconds=timeout_seconds
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib_error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ValueError(
                f"Failed to sync wallet identities from peer {peer_base_url}"
            ) from error
        if not isinstance(payload, dict):
            raise ValueError(
                f"Peer wallet identity sync response from {peer_base_url} is invalid"
            )
        if expected_node_id is not None:
            payload = self._verified_wallet_identity_peer_sync_envelope(
                payload=payload,
                expected_node_id=expected_node_id,
                expected_operator_id=expected_operator_id,
                expected_owner_wallet_id=expected_owner_wallet_id,
            )
        result = self.import_wallet_identity_sync_state(
            objects=list(payload.get("objects") or []),
            conflicts=list(payload.get("conflicts") or []),
        )
        result["peer_base_url"] = normalized_base_url
        return result

    @staticmethod
    def _verified_wallet_identity_peer_sync_envelope(
        *,
        payload: dict,
        expected_node_id: str,
        expected_operator_id: str | None,
        expected_owner_wallet_id: str | None,
    ) -> dict:
        from aidn_hypervisor.wallet_identity import verify_wallet_identity_sync_envelope

        sync_state = payload.get("sync_state")
        source = payload.get("source")
        signature = payload.get("signature")
        if not isinstance(sync_state, dict) or not isinstance(source, dict):
            raise ValueError("Peer wallet identity sync envelope is required")
        required_source = {
            "node_id": expected_node_id,
            "operator_id": expected_operator_id,
            "owner_wallet_id": expected_owner_wallet_id,
        }
        for field, expected_value in required_source.items():
            if expected_value is not None and source.get(field) != expected_value:
                raise ValueError(f"Peer wallet identity sync {field} does not match")
        state_hash = "sha256:" + hashlib.sha256(
            json.dumps(
                sync_state,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if source.get("state_hash") != state_hash:
            raise ValueError("Peer wallet identity sync state hash does not match")
        source_identity_present = any(
            item.get("object_type") == "wallet_identity"
            and isinstance(item.get("payload"), dict)
            and item["payload"].get("wallet_id") == source.get("owner_wallet_id")
            and item["payload"].get("public_key") == source.get("public_key")
            for item in list(sync_state.get("objects") or [])
            if isinstance(item, dict)
        )
        if not source_identity_present:
            raise ValueError(
                "Peer wallet identity sync source owner identity is missing or mismatched"
            )
        try:
            verify_wallet_identity_sync_envelope(
                node_id=source["node_id"],
                operator_id=source["operator_id"],
                owner_wallet_id=source["owner_wallet_id"],
                public_key=source["public_key"],
                state_hash=source["state_hash"],
                signature=signature,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Peer wallet identity sync signature is invalid") from error
        return sync_state

    def repair_wallet_identity_peers(
        self,
        *,
        limit: int = 500,
        timeout_seconds: int = 10,
    ) -> dict:
        results: list[dict] = []
        for peer_base_url in sorted(self._wallet_identity_peers):
            peer = self._wallet_identity_peers[peer_base_url]
            if not peer.get("enabled", True):
                continue
            try:
                import_result = self.sync_wallet_identity_from_peer(
                    peer_base_url=peer_base_url,
                    limit=limit,
                    timeout_seconds=timeout_seconds,
                    expected_node_id=peer.get("expected_node_id"),
                    expected_operator_id=peer.get("expected_operator_id"),
                    expected_owner_wallet_id=peer.get("expected_owner_wallet_id"),
                )
            except ValueError as error:
                peer["last_sync_at"] = datetime.now(UTC).isoformat()
                peer["last_sync_status"] = "error"
                peer["last_sync_error"] = str(error)
                peer["last_import_result"] = None
                results.append(
                    {
                        "peer_base_url": peer_base_url,
                        "status": "error",
                        "error": str(error),
                    }
                )
                continue

            peer["last_sync_at"] = datetime.now(UTC).isoformat()
            peer["last_sync_status"] = "ok"
            peer["last_sync_error"] = None
            peer["last_import_result"] = deepcopy(import_result)
            results.append(
                {
                    "peer_base_url": peer_base_url,
                    "status": "ok",
                    "import_result": deepcopy(import_result),
                }
            )

        if results or self._wallet_identity_peers:
            self._persist_registry_object_snapshot()

        success_count = sum(1 for item in results if item["status"] == "ok")
        error_count = sum(1 for item in results if item["status"] == "error")
        enabled_peer_count = sum(
            1
            for item in self._wallet_identity_peers.values()
            if item.get("enabled", True)
        )
        return {
            "enabled_peer_count": enabled_peer_count,
            "attempted_peer_count": len(results),
            "success_count": success_count,
            "error_count": error_count,
            "results": results,
        }

    def discover_and_repair_wallet_identity_peers(
        self,
        *,
        self_node_id: str | None = None,
        include_stale: bool = False,
        limit: int = 500,
        timeout_seconds: int = 10,
    ) -> dict:
        discovery = self.discover_wallet_identity_peers_from_nodes(
            self_node_id=self_node_id,
            include_stale=include_stale,
            auto_register=True,
        )
        repair = self.repair_wallet_identity_peers(
            limit=limit,
            timeout_seconds=timeout_seconds,
        )
        return {
            "discovery": discovery,
            "repair": repair,
        }

    def wallet_identity_reconciliation_report(self, *, limit: int = 500) -> dict:
        objects = self.list_wallet_identity_objects(limit=limit)
        conflicts = self.list_conflicts(
            conflict_class="wallet_identity_binding",
            object_type="wallet_identity",
            limit=limit,
        )
        conflicts_by_wallet: dict[str, list[dict]] = {}
        for item in conflicts:
            wallet_id = str(item.get("logical_key") or "")
            conflicts_by_wallet.setdefault(wallet_id, []).append(deepcopy(item))

        grouped: dict[str, list[dict]] = {}
        for item in objects:
            wallet_id = str(item.get("source_reference") or "")
            grouped.setdefault(wallet_id, []).append(deepcopy(item))

        items: list[dict] = []
        all_wallet_ids = sorted(set(grouped) | set(conflicts_by_wallet))
        peer_items = self.list_wallet_identity_peers()
        resolution_items = self.list_wallet_identity_resolutions()
        resolutions_by_wallet = {
            str(item["wallet_id"]): item for item in resolution_items
        }
        enabled_peer_count = sum(1 for item in peer_items if item.get("enabled", True))
        peer_error_count = sum(
            1 for item in peer_items if item.get("enabled", True) and item.get("last_sync_status") == "error"
        )
        peer_pending_count = sum(
            1
            for item in peer_items
            if item.get("enabled", True) and item.get("last_sync_status") in {None, "pending"}
        )

        for wallet_id in all_wallet_ids[:limit]:
            wallet_objects = grouped.get(wallet_id, [])
            wallet_conflicts = conflicts_by_wallet.get(wallet_id, [])
            payload_hashes = sorted(
                {str(item.get("payload_hash")) for item in wallet_objects if item.get("payload_hash")}
            )
            object_ids = sorted(
                {str(item.get("object_id")) for item in wallet_objects if item.get("object_id")}
            )
            source_nodes = sorted(
                {
                    str(source.get("node_id"))
                    for item in wallet_objects
                    for source in item.get("sources", [])
                    if source.get("node_id") is not None
                }
            )
            resolution = resolutions_by_wallet.get(wallet_id)
            has_conflict = bool(wallet_conflicts)
            if has_conflict and resolution is not None:
                status = "resolved"
            elif has_conflict:
                status = "conflict"
            elif len(payload_hashes) <= 1:
                status = "consistent"
            else:
                status = "divergent"
            items.append(
                {
                    "wallet_id": wallet_id,
                    "status": status,
                    "object_count": len(wallet_objects),
                    "payload_variant_count": len(payload_hashes),
                    "object_ids": object_ids,
                    "payload_hashes": payload_hashes,
                    "source_nodes": source_nodes,
                    "conflict_count": len(wallet_conflicts),
                    "conflicts": wallet_conflicts,
                    "resolution": deepcopy(resolution),
                }
            )

        summary = {
            "wallet_count": len(all_wallet_ids[:limit]),
            "consistent_count": sum(1 for item in items if item["status"] == "consistent"),
            "conflict_count": sum(1 for item in items if item["status"] == "conflict"),
            "resolved_count": sum(1 for item in items if item["status"] == "resolved"),
            "divergent_count": sum(1 for item in items if item["status"] == "divergent"),
            "enabled_peer_count": enabled_peer_count,
            "peer_error_count": peer_error_count,
            "peer_pending_count": peer_pending_count,
        }
        return {
            "summary": summary,
            "known_peers": peer_items,
            "resolutions": resolution_items,
            "resolution_proposals": self.list_wallet_identity_resolution_proposals(),
            "items": items,
        }

    def get_node(self, node_id: str) -> dict:
        record = deepcopy(self._nodes[node_id])
        if record.get("reputation") is None:
            record.pop("reputation", None)
        record["status"] = self._status_for(record)
        return record

    def upsert_registry_object(self, record: dict, *, persist: bool = True) -> dict:
        """Store one immutable object while serializing snapshot mutation."""
        with self._snapshot_lock:
            return self._upsert_registry_object(record, persist=persist)

    def _upsert_registry_object(self, record: dict, *, persist: bool = True) -> dict:
        object_id = str(record["object_id"])
        normalized = deepcopy(record)
        self._validate_wallet_identity_objects([normalized])
        existing = self._registry_objects.get(object_id)
        if existing is not None and existing != normalized:
            raise ValueError(f"Conflicting registry object for {object_id}")
        was_expired = object_id in self._expired_registry_objects
        self._registry_objects[object_id] = normalized
        self._expired_registry_objects.discard(object_id)
        try:
            self._apply_registry_object_state(record=normalized)
        except Exception:
            if existing is None:
                self._registry_objects.pop(object_id, None)
            else:
                self._registry_objects[object_id] = existing
            if was_expired:
                self._expired_registry_objects.add(object_id)
            self._rebuild_wallet_identity_resolution_state()
            raise
        if persist:
            try:
                self._persist_registry_object_snapshot()
            except Exception:
                if existing is None:
                    self._registry_objects.pop(object_id, None)
                else:
                    self._registry_objects[object_id] = existing
                if was_expired:
                    self._expired_registry_objects.add(object_id)
                self._rebuild_wallet_identity_resolution_state()
                raise
        return deepcopy(self._registry_objects[object_id])

    def ingest_registry_objects(self, records: list[dict]) -> list[dict]:
        previous_registry_objects = deepcopy(self._registry_objects)
        stored: list[dict] = []
        try:
            for record in records:
                stored.append(self.upsert_registry_object(record, persist=False))
            if stored:
                self._persist_registry_object_snapshot()
        except Exception:
            self._registry_objects = previous_registry_objects
            raise
        return stored

    def list_registry_objects(
        self, query: RegistryObjectQuery | dict | None = None
    ) -> list[dict]:
        if query is None:
            query_model = RegistryObjectQuery()
        elif isinstance(query, RegistryObjectQuery):
            query_model = query
        else:
            query_model = RegistryObjectQuery(**query)

        objects_by_id: dict[str, dict] = {}
        store_backed_object_ids: set[str] = set()
        node_backed_records: dict[str, dict] = {}
        for object_id in sorted(self._registry_objects):
            item = self._registry_objects[object_id]
            if (
                object_id in self._expired_registry_objects
                and not query_model.include_expired
            ):
                continue
            source = self._registry_object_source(item)
            if (
                query_model.node_id is not None
                and source.get("node_id") != query_model.node_id
            ):
                continue
            if (
                query_model.object_type is not None
                and item.get("object_type") != query_model.object_type
            ):
                continue
            if (
                query_model.namespace is not None
                and item.get("namespace") != query_model.namespace
            ):
                continue
            if (
                query_model.source_reference is not None
                and item.get("source_reference") != query_model.source_reference
            ):
                continue
            objects_by_id[object_id] = self._registry_object_row(
                item=item,
                include_payload=query_model.include_payload,
                source=source,
            )
            store_backed_object_ids.add(object_id)

        for node_id in self._nodes:
            node = self.get_node(node_id)
            if node["status"] == "offline":
                continue
            if node["status"] == "stale" and not query_model.include_stale:
                continue
            if query_model.node_id is not None and node["node_id"] != query_model.node_id:
                continue
            for item in node.get("canonical_registry_objects", []):
                if (
                    query_model.object_type is not None
                    and item.get("object_type") != query_model.object_type
                ):
                    continue
                if (
                    query_model.namespace is not None
                    and item.get("namespace") != query_model.namespace
                ):
                    continue
                if (
                    query_model.source_reference is not None
                    and item.get("source_reference") != query_model.source_reference
                ):
                    continue
                object_id = str(item["object_id"])
                if object_id in store_backed_object_ids:
                    if self._registry_object_records_conflict(
                        self._registry_objects[object_id],
                        item,
                    ):
                        raise ValueError(f"Conflicting registry object for {object_id}")
                    continue
                existing_item = node_backed_records.get(object_id)
                if existing_item is None:
                    node_backed_records[object_id] = deepcopy(item)
                elif self._registry_object_records_conflict(existing_item, item):
                    raise ValueError(f"Conflicting registry object for {object_id}")
                row = objects_by_id.get(object_id)
                source = {
                    "node_id": node["node_id"],
                    "operator_id": node["operator_id"],
                    "status": node["status"],
                }
                if row is None:
                    row = self._registry_object_row(
                        item=item,
                        include_payload=query_model.include_payload,
                        source=source,
                    )
                    objects_by_id[object_id] = row
                    continue
                if (
                    query_model.include_payload
                    and "payload" not in row
                    and item.get("payload") is not None
                ):
                    row["payload"] = deepcopy(item["payload"])
                if source not in row["sources"]:
                    row["sources"].append(source)
                    row["source_count"] = len(row["sources"])

        objects = sorted(
            objects_by_id.values(),
            key=lambda item: (
                item["object_type"],
                item["namespace"],
                item["source_reference"],
                item["object_id"],
            ),
        )
        return objects[: query_model.limit]

    def get_registry_object(
        self,
        object_id: str,
        *,
        include_payload: bool = False,
        include_expired: bool = False,
    ) -> dict:
        stored = self._registry_objects.get(object_id)
        if (
            stored is not None
            and object_id in self._expired_registry_objects
            and not include_expired
        ):
            raise KeyError(object_id)
        item: dict | None = None
        if stored is not None:
            item = self._registry_object_row(
                item=stored,
                include_payload=include_payload,
                source=self._registry_object_source(stored),
            )
        else:
            for candidate in self.list_registry_objects(
                query={
                    "limit": RegistryObjectQuery.model_fields["limit"].default,
                    "include_payload": include_payload,
                    "include_expired": include_expired,
                }
            ):
                if candidate["object_id"] == object_id:
                    item = candidate
                    break
        if item is not None and stored is None:
            return item

        # Scan node-backed compatibility objects directly so lookups are not limited by list pagination.
        for node_id in self._nodes:
            node = self.get_node(node_id)
            if node["status"] == "offline":
                continue
            if node["status"] == "stale":
                continue
            for candidate in node.get("canonical_registry_objects", []):
                if str(candidate["object_id"]) != object_id:
                    continue
                if stored is not None:
                    if self._registry_object_records_conflict(stored, candidate):
                        raise ValueError(f"Conflicting registry object for {object_id}")
                    continue
                source = {
                    "node_id": node["node_id"],
                    "operator_id": node["operator_id"],
                    "status": node["status"],
                }
                if item is None:
                    item = self._registry_object_row(
                        item=candidate,
                        include_payload=include_payload,
                        source=source,
                    )
                    continue
                if self._registry_object_records_conflict(
                    self._registry_object_record_from_row(item),
                    candidate,
                ):
                    raise ValueError(f"Conflicting registry object for {object_id}")
                if include_payload and "payload" not in item and candidate.get("payload") is not None:
                    item["payload"] = deepcopy(candidate["payload"])
                if source not in item["sources"]:
                    item["sources"].append(source)
                    item["source_count"] = len(item["sources"])
        if item is not None:
            return item
        raise KeyError(object_id)

    def resolve_wallet_identity(self, wallet_id: str) -> dict | None:
        matches = self._wallet_identity_matches(wallet_id)
        if not matches:
            return None
        resolution = self._wallet_identity_resolutions.get(wallet_id)
        if resolution is not None:
            certificate = resolution.get("governance_certificate")
            if certificate is not None:
                if not isinstance(certificate, dict):
                    raise ValueError("Wallet-identity resolution has an invalid governance certificate")
                self._verify_wallet_identity_governance_certificate(certificate)
            for item in matches:
                if (
                    item.get("object_id") == resolution.get("chosen_object_id")
                    and item.get("payload_hash") == resolution.get("chosen_payload_hash")
                ):
                    payload = item.get("payload")
                    if not isinstance(payload, dict):
                        raise ValueError(
                            f"Canonical wallet identity object for {wallet_id} has no payload"
                        )
                    registry_sources: list[dict] = []
                    for candidate in sorted(
                        matches,
                        key=lambda candidate: (
                            str(candidate.get("_source", {}).get("node_id") or ""),
                            str(candidate.get("_source", {}).get("operator_id") or ""),
                        ),
                    ):
                        if (
                            candidate.get("object_id") != item.get("object_id")
                            or candidate.get("payload_hash") != item.get("payload_hash")
                        ):
                            continue
                        source = {
                            "node_id": candidate.get("_source", {}).get("node_id"),
                            "operator_id": candidate.get("_source", {}).get("operator_id"),
                            "status": candidate.get("_source", {}).get("status") or "stored",
                        }
                        if source not in registry_sources:
                            registry_sources.append(source)
                    return {
                        "wallet_id": str(payload["wallet_id"]),
                        "public_key": str(payload["public_key"]),
                        "registration_nonce": str(payload["registration_nonce"]),
                        "registered_at": None,
                        "identity_source": "registry_resolution",
                        "registry_object_id": str(item["object_id"]),
                        "registry_sources": registry_sources,
                        "resolution": deepcopy(resolution),
                    }
        unique_records = {
            (
                str(item["object_id"]),
                str(item["payload_hash"]),
            ): item
            for item in matches
        }
        if len(unique_records) > 1:
            raise ValueError(
                f"Conflicting wallet identity objects found for {wallet_id}"
            )
        record = next(iter(unique_records.values()))
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError(
                f"Canonical wallet identity object for {wallet_id} has no payload"
            )
        registry_sources: list[dict] = []
        for item in sorted(
            matches,
            key=lambda candidate: (
                str(candidate.get("_source", {}).get("node_id") or ""),
                str(candidate.get("_source", {}).get("operator_id") or ""),
            ),
        ):
            source = {
                "node_id": item.get("_source", {}).get("node_id"),
                "operator_id": item.get("_source", {}).get("operator_id"),
                "status": item.get("_source", {}).get("status") or "stored",
            }
            if source not in registry_sources:
                registry_sources.append(source)
        return {
            "wallet_id": str(payload["wallet_id"]),
            "public_key": str(payload["public_key"]),
            "registration_nonce": str(payload["registration_nonce"]),
            "registered_at": None,
            "identity_source": "registry_object",
            "registry_object_id": str(record["object_id"]),
            "registry_sources": registry_sources,
        }

    def discover(self, query: RegistryDiscoveryQuery) -> dict:
        matched_nodes: list[dict] = []
        canonical_candidates_by_node: dict[str, list[dict]] = {}
        use_legacy_filters = self._uses_legacy_filters(query)
        use_canonical_filters = self._uses_canonical_filters(query)
        for node_id in self._nodes:
            node = self.get_node(node_id)
            if node["status"] == "offline":
                continue
            if node["status"] == "stale" and not query.include_stale:
                continue
            if (
                query.can_host_custom_model is not None
                and node["can_host_custom_model"] != query.can_host_custom_model
            ):
                continue
            if query.min_rating is not None and self._node_rating_score(node) < query.min_rating:
                continue
            if (
                query.max_input_price_q_per_1kk is not None
                and node["pricing"]["input"] > query.max_input_price_q_per_1kk
            ):
                continue
            if (
                query.max_output_price_q_per_1kk is not None
                and node["pricing"]["output"] > query.max_output_price_q_per_1kk
            ):
                continue

            bundles = [
                bundle for bundle in node["bundles"] if self._bundle_matches(bundle, query)
            ]
            canonical_candidates = self._flatten_canonical_candidates_for_node(node)
            if use_canonical_filters:
                canonical_candidates = [
                    candidate
                    for candidate in canonical_candidates
                    if self._canonical_candidate_matches(candidate=candidate, query=query)
                ]

            has_legacy_matches = bool(bundles)
            has_canonical_matches = bool(canonical_candidates)
            if use_legacy_filters and use_canonical_filters:
                if not has_legacy_matches or not has_canonical_matches:
                    continue
            elif use_canonical_filters:
                if not has_canonical_matches:
                    continue
            elif not has_legacy_matches:
                continue
            node["bundles"] = bundles
            matched_nodes.append(node)
            canonical_candidates_by_node[node["node_id"]] = canonical_candidates

        matched_nodes.sort(
            key=lambda node: (
                {"ready": 0, "stale": 1, "offline": 2}[node["status"]],
                -self._node_rating_score(node),
                node["pricing"]["input"],
                node["pricing"]["output"],
                -datetime.fromisoformat(node["heartbeat_at"]).timestamp(),
            )
        )
        nodes = matched_nodes[: query.limit]
        canonical_candidates: list[dict] = []
        for node in nodes:
            canonical_candidates.extend(canonical_candidates_by_node.get(node["node_id"], []))
        canonical_candidates.sort(key=self._canonical_candidate_sort_key)
        return {
            "query": query.model_dump(mode="json"),
            "nodes": nodes,
            "candidates": self._flatten_candidates(nodes),
            "canonical_candidates": canonical_candidates,
        }

    def get_local_registry_completeness_summary(self) -> RegistryLocalCompletenessSummary:
        by_namespace: dict[str, int] = {}
        by_object_type: dict[str, int] = {}
        payload_object_count = 0
        payload_bytes_total = 0
        payload_hash_coverage_count = 0
        issues: list[RegistryCompletenessIssue] = []

        for object_id in sorted(self._registry_objects):
            record = self._registry_objects[object_id]
            if not isinstance(record, dict):
                raise ValueError(
                    f"Registry object store contains non-object record for {object_id}"
                )

            issues.extend(
                self._registry_object_summary_issues(object_id=object_id, record=record)
            )

            namespace = record.get("namespace")
            if isinstance(namespace, str) and namespace:
                by_namespace[namespace] = by_namespace.get(namespace, 0) + 1

            object_type = record.get("object_type")
            if isinstance(object_type, str) and object_type:
                by_object_type[object_type] = by_object_type.get(object_type, 0) + 1

            payload_hash = record.get("payload_hash")
            if isinstance(payload_hash, str) and payload_hash:
                payload_hash_coverage_count += 1

            if record.get("payload") is not None:
                payload_object_count += 1
                payload_bytes_total += self._payload_size_bytes(record["payload"])

        return RegistryLocalCompletenessSummary(
            summary_version=_LOCAL_REGISTRY_COMPLETENESS_SUMMARY_VERSION,
            generated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            snapshot_schema_version=_REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION,
            store_totals=RegistryCompletenessTotals(
                total_object_count=len(self._registry_objects),
                payload_object_count=payload_object_count,
                payload_bytes_total=payload_bytes_total,
            ),
            by_namespace=by_namespace,
            by_object_type=by_object_type,
            integrity=RegistryCompletenessIntegrity(
                object_count_matches_store=True,
                all_object_ids_unique=True,
                all_required_fields_present=not any(
                    issue.code == "missing_required_field" for issue in issues
                ),
                payload_hash_coverage_count=payload_hash_coverage_count,
                issues=issues,
            ),
        )

    def apply_registry_retention(
        self,
        *,
        current_epoch: int,
        apply: bool = True,
        limit: int | None = None,
    ) -> dict:
        """Preview or enforce versioned Registry retention without deleting objects."""
        with self._snapshot_lock:
            decisions: list[tuple[str, int | None]] = []
            for object_id in sorted(self._registry_objects):
                record = self._registry_objects[object_id]
                if not isinstance(record, dict):
                    raise ValueError(
                        f"Registry object store contains non-object record for {object_id}"
                    )
                retention_class = record.get("retention_class")
                expiration_epoch = self.retention_policy.expiration_epoch_for(
                    created_epoch=record.get("created_epoch"),
                    namespace=record.get("namespace"),
                    object_type=record.get("object_type"),
                    retention_class=retention_class,
                    explicit_expiration_epoch=record.get("expiration_epoch"),
                )
                if self.retention_policy.is_expired(
                    current_epoch=current_epoch,
                    expiration_epoch=expiration_epoch,
                ):
                    decisions.append((object_id, expiration_epoch))

            if limit is not None:
                decisions = decisions[: max(0, int(limit))]
            expired_ids = [object_id for object_id, _ in decisions]
            newly_expired = [
                object_id
                for object_id in expired_ids
                if object_id not in self._expired_registry_objects
            ]
            if apply and newly_expired:
                self._expired_registry_objects.update(newly_expired)
                self._persist_registry_object_snapshot()
            return {
                "current_epoch": int(current_epoch),
                "policy_version": self.retention_policy.policy_version,
                "policy_hash": self.retention_policy.policy_hash,
                "applied": bool(apply),
                "expired_count": len(expired_ids),
                "newly_expired_count": len(newly_expired),
                "expired_ids": expired_ids,
                "expiration_epochs": {
                    object_id: expiration_epoch
                    for object_id, expiration_epoch in decisions
                },
            }

    def get_local_registry_inventory_manifest(
        self,
        *,
        generated_at_epoch: int | None = None,
        generated_at_height: int | None = None,
        include_expired: bool = False,
    ) -> RegistryInventoryManifest:
        """Build a payload-free deterministic commitment for local Registry state."""
        entries: list[ManifestObjectEntry] = []
        for object_id in sorted(self._registry_objects):
            if object_id in self._expired_registry_objects and not include_expired:
                continue
            record = self._registry_objects[object_id]
            if not isinstance(record, dict):
                raise ValueError(
                    f"Registry object store contains non-object record for {object_id}"
                )
            entries.append(ManifestObjectEntry.from_object(record))

        observed_epochs = [
            entry.created_epoch
            for entry in entries
            if entry.created_epoch is not None
        ]
        resolved_epoch = (
            int(generated_at_epoch)
            if generated_at_epoch is not None
            else max(observed_epochs, default=0)
        )
        return RegistryInventoryManifest.create(
            registry_service_id=self.registry_service_id,
            generated_at_epoch=resolved_epoch,
            generated_at_height=generated_at_height,
            generation=self.registry_generation,
            retention_policy_hash=self.retention_policy.policy_hash,
            objects=entries,
        )

    def _registry_object_summary_issues(
        self,
        *,
        object_id: str,
        record: dict,
    ) -> list[RegistryCompletenessIssue]:
        issues: list[RegistryCompletenessIssue] = []
        for field in _REQUIRED_REGISTRY_OBJECT_FIELDS:
            value = record.get(field)
            if value is None or (isinstance(value, str) and not value):
                issues.append(
                    RegistryCompletenessIssue(
                        code="missing_required_field",
                        object_id=object_id,
                        field=field,
                        detail=f"Stored record is missing required field {field}",
                    )
                )
        return issues

    def _payload_size_bytes(self, payload: object) -> int:
        return len(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )

    def _flatten_candidates(self, nodes: list[dict]) -> list[dict]:
        candidates: list[dict] = []
        for node in nodes:
            for bundle in node["bundles"]:
                candidates.append(
                    {
                        "node_id": node["node_id"],
                        "operator_id": node["operator_id"],
                        "status": node["status"],
                        "base_url": node["base_url"],
                        "resources": node["resources"],
                        "can_host_custom_model": node["can_host_custom_model"],
                        "pricing": node["pricing"],
                        "rating": node["rating"],
                        "bundle_id": bundle["bundle_id"],
                        "plugin_id": bundle["plugin_id"],
                        "provider_type": bundle["provider_type"],
                        "model_id": bundle["model_id"],
                        "workload_type": bundle["workload_type"],
                        "endpoint": bundle["endpoint"],
                        "endpoint_ready": self._bundle_endpoint_ready(bundle),
                        "supports_allocation": bundle["supports_allocation"],
                        "supports_queue": bundle["supports_queue"],
                    }
                )
                if node.get("reputation") is not None:
                    candidates[-1]["reputation"] = node["reputation"]
        candidates.sort(key=self._candidate_sort_key)
        return candidates

    def _registry_object_row(self, *, item: dict, include_payload: bool, source: dict) -> dict:
        row = {
            "object_id": str(item["object_id"]),
            "object_type": item["object_type"],
            "object_version": item["object_version"],
            "namespace": item["namespace"],
            "payload_hash": item["payload_hash"],
            "payload_encoding": item["payload_encoding"],
            "source_reference": item["source_reference"],
            "source_count": 1,
            "sources": [deepcopy(source)],
        }
        for field in (
            "retention_class",
            "access_class",
            "expiration_epoch",
            "created_at",
        ):
            if field in item:
                row[field] = deepcopy(item[field])
        if str(item.get("object_id")) in self._expired_registry_objects:
            row["retention_state"] = "EXPIRED"
        if include_payload and item.get("payload") is not None:
            row["payload"] = deepcopy(item["payload"])
        return row

    def _registry_object_source(self, item: dict) -> dict:
        source = item.get("_source")
        if isinstance(source, dict):
            return {
                "node_id": source.get("node_id"),
                "operator_id": source.get("operator_id"),
                "status": source.get("status") or "stored",
            }
        return {"node_id": None, "operator_id": None, "status": "stored"}

    def _registry_object_record_from_row(self, row: dict) -> dict:
        record = {
            "object_id": row["object_id"],
            "object_type": row["object_type"],
            "object_version": row["object_version"],
            "namespace": row["namespace"],
            "payload_hash": row["payload_hash"],
            "payload_encoding": row["payload_encoding"],
            "source_reference": row["source_reference"],
        }
        for field in (
            "retention_class",
            "access_class",
            "expiration_epoch",
            "created_at",
        ):
            if field in row:
                record[field] = deepcopy(row[field])
        if "payload" in row:
            record["payload"] = deepcopy(row["payload"])
        return record

    def _registry_object_records_conflict(self, left: dict, right: dict) -> bool:
        for field in (
            "object_type",
            "object_version",
            "namespace",
            "payload_hash",
            "payload_encoding",
            "source_reference",
            "retention_class",
            "access_class",
            "expiration_epoch",
            "created_at",
        ):
            if left.get(field) != right.get(field):
                return True
        return bool("payload" in left and "payload" in right and left.get("payload") != right.get("payload"))

    def _record_conflict_evidence(
        self,
        *,
        conflict_class: str,
        object_type: str,
        namespace: str,
        logical_key: str,
        existing_record: dict,
        conflicting_record: dict,
    ) -> None:
        conflict_payload = {
            "conflict_class": conflict_class,
            "object_type": object_type,
            "namespace": namespace,
            "logical_key": logical_key,
            "existing_object_id": existing_record.get("object_id"),
            "existing_payload_hash": existing_record.get("payload_hash"),
            "conflicting_object_id": conflicting_record.get("object_id"),
            "conflicting_payload_hash": conflicting_record.get("payload_hash"),
        }
        encoded = json.dumps(
            conflict_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        conflict_id = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
        if conflict_id in self._conflicts:
            return
        self._conflicts[conflict_id] = RegistryConflictEvidence(
            conflict_id=conflict_id,
            conflict_class=conflict_class,
            object_type=object_type,
            namespace=namespace,
            logical_key=logical_key,
            existing_record=deepcopy(existing_record),
            conflicting_record=deepcopy(conflicting_record),
            observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        ).model_dump(mode="json")
        self._persist_registry_object_snapshot()

    def _select_wallet_identity_resolution_candidate(
        self,
        *,
        wallet_id: str,
        chosen_object_id: str | None,
        chosen_payload_hash: str | None,
    ) -> dict:
        if chosen_object_id is None and chosen_payload_hash is None:
            raise ValueError(
                "chosen_object_id or chosen_payload_hash must be provided"
            )
        matches = self._wallet_identity_matches(wallet_id)
        if not matches:
            raise KeyError(wallet_id)
        candidates = []
        for item in matches:
            if chosen_object_id is not None and item.get("object_id") != chosen_object_id:
                continue
            if (
                chosen_payload_hash is not None
                and item.get("payload_hash") != chosen_payload_hash
            ):
                continue
            candidates.append(deepcopy(item))
        unique_candidates = {
            (str(item.get("object_id")), str(item.get("payload_hash"))): item
            for item in candidates
        }
        if not unique_candidates:
            raise ValueError(
                f"No wallet identity candidate matched resolution for {wallet_id}"
            )
        if len(unique_candidates) > 1:
            raise ValueError(
                f"Resolution for {wallet_id} matched multiple wallet identity candidates"
            )
        return next(iter(unique_candidates.values()))

    def _normalize_requested_wallet_identity_voters(
        self,
        *,
        eligible_voter_node_ids: list[str] | None,
    ) -> list[str]:
        if eligible_voter_node_ids:
            voters = {
                str(item).strip()
                for item in eligible_voter_node_ids
                if str(item).strip()
            }
        else:
            voters = set()
        return sorted(voters)

    def _authoritative_wallet_identity_voters(
        self,
        *,
        wallet_id: str,
        chosen_object_id: str,
        chosen_payload_hash: str,
    ) -> list[str]:
        voters: set[str] = set()
        allowed_statuses = set(
            self._wallet_identity_governance_policy.get(
                "authorized_voter_statuses", ["ready", "stale"]
            )
        )
        for item in self._wallet_identity_matches(wallet_id):
            if item.get("object_id") != chosen_object_id:
                continue
            if item.get("payload_hash") != chosen_payload_hash:
                continue
            source = item.get("_source", {})
            node_id = str(source.get("node_id") or "").strip()
            if not node_id:
                continue
            if source.get("status") not in allowed_statuses:
                continue
            try:
                self._wallet_identity_operator_identity_for_node(node_id=node_id)
            except ValueError:
                continue
            voters.add(node_id)
        if not voters:
            raise ValueError(
                f"Wallet identity resolution for {wallet_id} has no authoritative voter nodes"
            )
        minimum_voter_count = int(
            self._wallet_identity_governance_policy.get(
                "minimum_eligible_voter_count", 1
            )
            or 1
        )
        if len(voters) < minimum_voter_count:
            raise ValueError(
                f"Wallet identity resolution for {wallet_id} has only {len(voters)} "
                f"authoritative voter node(s); policy requires at least {minimum_voter_count}"
            )
        return sorted(voters)

    def _wallet_identity_quorum_threshold(
        self,
        *,
        eligible_voter_node_ids: list[str],
        quorum_threshold: int | None,
    ) -> int:
        voter_count = len(eligible_voter_node_ids)
        if voter_count == 0:
            raise ValueError("Wallet identity resolution requires at least one eligible voter")
        if quorum_threshold is None:
            threshold_mode = str(
                self._wallet_identity_governance_policy.get("threshold_mode")
                or "majority"
            )
            if threshold_mode != "majority":
                raise ValueError(
                    f"Unsupported wallet identity quorum threshold policy: {threshold_mode}"
                )
            resolved_threshold = (voter_count // 2) + 1
        else:
            resolved_threshold = int(quorum_threshold)
        if resolved_threshold < 1 or resolved_threshold > voter_count:
            raise ValueError(
                "quorum_threshold must be between 1 and the number of eligible voters"
            )
        minimum_quorum_threshold = int(
            self._wallet_identity_governance_policy.get("minimum_quorum_threshold", 1)
            or 1
        )
        if resolved_threshold < minimum_quorum_threshold:
            raise ValueError(
                "quorum_threshold does not satisfy the active wallet identity governance policy"
            )
        return resolved_threshold

    def _wallet_identity_operator_identity_for_node(self, *, node_id: str) -> dict:
        node = deepcopy(self._nodes.get(node_id))
        if node is None:
            raise ValueError(f"Node {node_id} is not registered for wallet identity quorum")
        operator_wallet_id = str(node.get("operator_id") or "").strip()
        if not operator_wallet_id:
            raise ValueError(
                f"Node {node_id} does not advertise an operator wallet identity binding"
            )
        owner_wallet_id = str(node.get("owner_wallet_id") or "").strip()
        if not owner_wallet_id:
            raise ValueError(
                f"Node {node_id} does not advertise owner wallet control for wallet identity quorum"
            )
        operator_identity = self.resolve_wallet_identity(operator_wallet_id)
        if operator_identity is None:
            raise ValueError(
                f"Node {node_id} operator wallet identity {operator_wallet_id} is not registered"
            )
        owner_wallet_identity = self.resolve_wallet_identity(owner_wallet_id)
        if owner_wallet_identity is None:
            raise ValueError(
                f"Node {node_id} owner wallet identity {owner_wallet_id} is not registered"
            )
        if operator_identity.get("public_key") != owner_wallet_identity.get("public_key"):
            raise ValueError(
                f"Node {node_id} operator identity {operator_wallet_id} is not linked to owner wallet {owner_wallet_id}"
            )
        return {
            "operator_wallet_id": operator_wallet_id,
            "operator_identity": operator_identity,
            "owner_wallet_id": owner_wallet_id,
            "owner_wallet_identity": owner_wallet_identity,
        }

    def _verify_wallet_identity_quorum_proposal_signature(
        self,
        *,
        wallet_id: str,
        chosen_object_id: str,
        chosen_payload_hash: str,
        proposer_node_id: str,
        proposer_signature: str | None,
        eligible_voter_node_ids: list[str],
        quorum_threshold: int,
        operator_note: str | None,
    ) -> None:
        from aidn_hypervisor.wallet_identity import (
            verify_wallet_identity_quorum_proposal,
        )

        if not proposer_signature:
            raise ValueError(
                f"Wallet identity quorum proposal for {wallet_id} requires proposer_signature"
            )
        authority = self._wallet_identity_operator_identity_for_node(
            node_id=proposer_node_id
        )
        verify_wallet_identity_quorum_proposal(
            public_key=str(authority["operator_identity"]["public_key"]),
            signature=proposer_signature,
            wallet_id=wallet_id,
            chosen_object_id=chosen_object_id,
            chosen_payload_hash=chosen_payload_hash,
            proposer_node_id=proposer_node_id,
            eligible_voter_node_ids=eligible_voter_node_ids,
            quorum_threshold=quorum_threshold,
            operator_note=operator_note,
        )

    def _verify_wallet_identity_quorum_approval_signature(
        self,
        *,
        resolution_id: str,
        approver_node_id: str,
        approval_signature: str | None,
        approval_note: str | None,
    ) -> None:
        from aidn_hypervisor.wallet_identity import (
            verify_wallet_identity_quorum_approval,
        )

        if not approval_signature:
            raise ValueError(
                f"Wallet identity quorum approval for {resolution_id} requires approval_signature"
            )
        authority = self._wallet_identity_operator_identity_for_node(
            node_id=approver_node_id
        )
        verify_wallet_identity_quorum_approval(
            public_key=str(authority["operator_identity"]["public_key"]),
            signature=approval_signature,
            resolution_id=resolution_id,
            approver_node_id=approver_node_id,
            approval_note=approval_note,
        )

    def _record_wallet_identity_resolution_approval(
        self,
        *,
        proposal: dict,
        approver_node_id: str,
        approval_signature: str | None,
        approval_note: str | None,
        approved_at: str,
        approval_kind: str = "approval",
    ) -> dict:
        approvals = list(proposal.get("approvals") or [])
        for existing in approvals:
            if existing.get("approver_node_id") != approver_node_id:
                continue
            if existing.get("approval_signature") != approval_signature:
                raise ValueError(
                    f"Approver {approver_node_id} submitted conflicting approval for "
                    f"{proposal.get('resolution_id')}"
                )
            return proposal
        approvals.append(
            {
                "approver_node_id": approver_node_id,
                "approval_signature": approval_signature,
                "approval_note": approval_note,
                "approved_at": approved_at,
                "approval_kind": approval_kind,
            }
        )
        proposal["approvals"] = approvals
        return proposal

    def _finalize_wallet_identity_resolution_proposal(self, resolution_id: str) -> None:
        proposal = self._wallet_identity_resolution_proposals[resolution_id]
        if proposal.get("status") == "finalized":
            return
        threshold = int(proposal.get("quorum_threshold") or 0)
        approvals = list(proposal.get("approvals") or [])
        if len(approvals) < threshold:
            return
        certificate = self._wallet_identity_governance_certificate(proposal=proposal)
        ledger_commitment = self._commit_wallet_identity_governance_certificate(certificate)
        if ledger_commitment is not None:
            certificate["ledger_commitment"] = ledger_commitment
        self.upsert_registry_object(
            self._wallet_identity_governance_certificate_registry_object(certificate)
        )
        final_resolution = self.resolve_wallet_identity_conflict(
            wallet_id=str(proposal["wallet_id"]),
            chosen_object_id=str(proposal["chosen_object_id"]),
            chosen_payload_hash=str(proposal["chosen_payload_hash"]),
            operator_note=str(proposal.get("operator_note") or "quorum-approved"),
            governance_certificate=certificate,
        )
        proposal["status"] = "finalized"
        proposal["finalized_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        proposal["final_resolution"] = final_resolution
        proposal["governance_certificate"] = certificate
        self._wallet_identity_resolution_proposals[resolution_id] = proposal

    def _wallet_identity_governance_certificate(self, *, proposal: dict) -> dict:
        """Derive portable evidence from the exact signed quorum state."""
        from aidn_hypervisor.wallet_identity import wallet_identity_governance_certificate_payload

        authorities = []
        for node_id in sorted(proposal.get("eligible_voter_node_ids") or []):
            authority = self._wallet_identity_operator_identity_for_node(node_id=node_id)
            authorities.append(
                {
                    "node_id": node_id,
                    "operator_wallet_id": str(authority["operator_wallet_id"]),
                    "owner_wallet_id": str(authority["owner_wallet_id"]),
                    "public_key": str(authority["operator_identity"]["public_key"]),
                }
            )
        approvals = sorted(
            [deepcopy(item) for item in proposal.get("approvals") or []],
            key=lambda item: str(item.get("approver_node_id") or ""),
        )
        policy_snapshot = deepcopy(proposal.get("governance_policy_snapshot") or {})
        policy_hash = "sha256:" + hashlib.sha256(
            json.dumps(policy_snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        certificate_fields = {
            "resolution_id": str(proposal["resolution_id"]),
            "wallet_id": str(proposal["wallet_id"]),
            "chosen_object_id": str(proposal["chosen_object_id"]),
            "chosen_payload_hash": str(proposal["chosen_payload_hash"]),
            "governance_policy_hash": policy_hash,
            "eligible_voter_node_ids": sorted(proposal.get("eligible_voter_node_ids") or []),
            "voter_authorities": authorities,
            "quorum_threshold": int(proposal["quorum_threshold"]),
            "approvals": approvals,
        }
        certificate_id = "sha256:" + hashlib.sha256(
            wallet_identity_governance_certificate_payload(certificate_id="", **certificate_fields)
        ).hexdigest()
        return {
            "certificate_version": "wallet-identity-governance-certificate.v1",
            "certificate_id": certificate_id,
            **certificate_fields,
            "governance_policy_snapshot": policy_snapshot,
            "issued_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

    def _verify_wallet_identity_governance_certificate(self, certificate: dict) -> None:
        from aidn_hypervisor.wallet_identity import verify_wallet_identity_governance_certificate

        try:
            verify_wallet_identity_governance_certificate(
                certificate_id=str(certificate["certificate_id"]),
                resolution_id=str(certificate["resolution_id"]),
                wallet_id=str(certificate["wallet_id"]),
                chosen_object_id=str(certificate["chosen_object_id"]),
                chosen_payload_hash=str(certificate["chosen_payload_hash"]),
                governance_policy_hash=str(certificate["governance_policy_hash"]),
                eligible_voter_node_ids=list(certificate["eligible_voter_node_ids"]),
                voter_authorities=list(certificate["voter_authorities"]),
                quorum_threshold=int(certificate["quorum_threshold"]),
                approvals=list(certificate["approvals"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Wallet-identity governance certificate is invalid") from exc
        if str(certificate["certificate_id"]) in self._wallet_identity_governance_revocations:
            raise ValueError("Wallet-identity governance certificate is revoked")
        commitment = certificate.get("ledger_commitment")
        requires_ledger = bool(
            self._wallet_identity_governance_policy.get("ledger_authorization_required")
        )
        if commitment is None:
            if requires_ledger:
                raise ValueError("Wallet-identity governance certificate requires Ledger commitment")
            return
        if not isinstance(commitment, dict):
            raise ValueError("Wallet-identity governance certificate Ledger commitment is invalid")
        expected_certificate_id = str(certificate["certificate_id"])
        if commitment.get("certificate_id") != expected_certificate_id:
            raise ValueError("Wallet-identity governance certificate Ledger commitment is mismatched")
        if self._ledger_operation_service is None:
            if requires_ledger:
                if self._loading_registry_object_snapshot:
                    return
                raise ValueError("Wallet-identity governance certificate Ledger is unavailable")
            return
        record = self._ledger_operation_service.wallet_identity_governance_certificate_commitment(
            expected_certificate_id
        )
        if record is None or record.get("operation_id") != commitment.get("operation_id"):
            raise ValueError("Wallet-identity governance certificate Ledger commitment is unknown")

    def _verify_wallet_identity_governance_revocation(
        self,
        revocation: dict,
        *,
        require_ledger: bool = True,
    ) -> None:
        from aidn_hypervisor.wallet_identity import verify_wallet_identity_governance_revocation

        try:
            verify_wallet_identity_governance_revocation(
                certificate_id=str(revocation["certificate_id"]),
                revocation_id=str(revocation["revocation_id"]),
                reason=str(revocation["reason"]),
                eligible_voter_node_ids=list(revocation["eligible_voter_node_ids"]),
                voter_authorities=list(revocation["voter_authorities"]),
                quorum_threshold=int(revocation["quorum_threshold"]),
                approvals=list(revocation["approvals"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Wallet-identity governance revocation is invalid") from exc
        commitment = revocation.get("ledger_commitment")
        requires_ledger = bool(
            self._wallet_identity_governance_policy.get("ledger_authorization_required")
        )
        if commitment is None:
            if requires_ledger and require_ledger:
                raise ValueError("Wallet-identity governance revocation requires Ledger commitment")
            return
        if not isinstance(commitment, dict) or commitment.get("certificate_id") != revocation.get("certificate_id"):
            raise ValueError("Wallet-identity governance revocation Ledger commitment is invalid")
        if self._ledger_operation_service is None:
            if requires_ledger and not self._loading_registry_object_snapshot:
                raise ValueError("Wallet-identity governance revocation Ledger is unavailable")
            return
        record = self._ledger_operation_service.wallet_identity_governance_certificate_revocation(
            str(revocation["certificate_id"])
        )
        if record is None or record.get("operation_id") != commitment.get("operation_id"):
            raise ValueError("Wallet-identity governance revocation Ledger commitment is unknown")

    def _wallet_identity_governance_certificate_payload(self, certificate_id: str) -> dict | None:
        for item in self.list_wallet_identity_governance_certificates():
            payload = item.get("payload")
            if isinstance(payload, dict) and payload.get("certificate_id") == certificate_id:
                return deepcopy(payload)
        return None

    def _commit_wallet_identity_governance_certificate(self, certificate: dict) -> dict | None:
        if self._ledger_operation_service is None:
            if self._wallet_identity_governance_policy.get("ledger_authorization_required"):
                raise ValueError("Wallet-identity governance policy requires an available Ledger")
            return None
        record = self._ledger_operation_service.commit_wallet_identity_governance_certificate(certificate)
        return {
            "operation_id": record["operation_id"],
            "sequence_id": record["sequence_id"],
            "certificate_id": certificate["certificate_id"],
            "operation_type": record["operation_type"],
        }

    def _wallet_identity_registry_object(
        self,
        *,
        object_type: str,
        object_version: str,
        source_reference: str,
        payload: dict,
    ) -> dict:
        encoded_payload = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        payload_hash = f"sha256:{hashlib.sha256(encoded_payload).hexdigest()}"
        identity_payload = {
            "object_type": object_type,
            "object_version": object_version,
            "payload_hash": payload_hash,
        }
        canonical = json.dumps(identity_payload, sort_keys=True, separators=(',', ':'))
        object_id = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
        return {
            "object_id": object_id,
            "object_type": object_type,
            "object_version": object_version,
            "namespace": "identity",
            "payload_hash": payload_hash,
            "payload_encoding": "canonical_json",
            "source_reference": source_reference,
            "payload": deepcopy(payload),
        }

    def _wallet_identity_quorum_proposal_registry_object(self, proposal: dict) -> dict:
        payload = {
            "resolution_id": proposal["resolution_id"],
            "wallet_id": proposal["wallet_id"],
            "chosen_object_id": proposal["chosen_object_id"],
            "chosen_payload_hash": proposal["chosen_payload_hash"],
            "public_key": proposal.get("public_key"),
            "registration_nonce": proposal.get("registration_nonce"),
            "requested_voter_node_ids": list(proposal.get("requested_voter_node_ids") or []),
            "eligible_voter_node_ids": list(proposal.get("eligible_voter_node_ids") or []),
            "voter_policy": proposal.get("voter_policy"),
            "quorum_threshold": proposal.get("quorum_threshold"),
            "governance_policy_snapshot": deepcopy(
                proposal.get("governance_policy_snapshot") or {}
            ),
            "status": proposal.get("status"),
            "operator_note": proposal.get("operator_note"),
            "proposed_at": proposal.get("proposed_at"),
        }
        return self._wallet_identity_registry_object(
            object_type="wallet_identity_resolution_proposal",
            object_version="wallet-identity-resolution-proposal.v1",
            source_reference=str(proposal["resolution_id"]),
            payload=payload,
        )

    def _wallet_identity_quorum_approval_registry_object(
        self,
        *,
        resolution_id: str,
        wallet_id: str,
        approval: dict,
    ) -> dict:
        payload = {
            "resolution_id": resolution_id,
            "wallet_id": wallet_id,
            "approver_node_id": approval.get("approver_node_id"),
            "approval_signature": approval.get("approval_signature"),
            "approval_note": approval.get("approval_note"),
            "approved_at": approval.get("approved_at"),
            "approval_kind": approval.get("approval_kind") or "approval",
        }
        return self._wallet_identity_registry_object(
            object_type="wallet_identity_resolution_approval",
            object_version="wallet-identity-resolution-approval.v1",
            source_reference=f"{resolution_id}:{approval.get('approver_node_id')}",
            payload=payload,
        )

    def _wallet_identity_resolution_registry_object(self, *, resolution: dict) -> dict:
        payload = deepcopy(resolution)
        return self._wallet_identity_registry_object(
            object_type="wallet_identity_resolution",
            object_version="wallet-identity-resolution.v1",
            source_reference=str(resolution["wallet_id"]),
            payload=payload,
        )

    def _wallet_identity_governance_certificate_registry_object(self, certificate: dict) -> dict:
        return self._wallet_identity_registry_object(
            object_type="wallet_identity_governance_certificate",
            object_version="wallet-identity-governance-certificate.v1",
            source_reference=str(certificate["certificate_id"]),
            payload=deepcopy(certificate),
        )

    def _wallet_identity_governance_revocation_registry_object(self, revocation: dict) -> dict:
        return self._wallet_identity_registry_object(
            object_type="wallet_identity_governance_revocation",
            object_version="wallet-identity-governance-revocation.v1",
            source_reference=str(revocation["revocation_id"]),
            payload=deepcopy(revocation),
        )

    def _apply_registry_object_state(self, *, record: dict) -> None:
        if record.get("namespace") != "identity":
            return
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return
        object_type = record.get("object_type")
        if object_type == "wallet_identity_resolution_proposal":
            self._apply_wallet_identity_resolution_proposal_record(payload)
        elif object_type == "wallet_identity_resolution_approval":
            self._apply_wallet_identity_resolution_approval_record(payload)
        elif object_type == "wallet_identity_resolution":
            self._apply_wallet_identity_resolution_record(payload)
        elif object_type == "wallet_identity_governance_revocation":
            self._apply_wallet_identity_governance_revocation_record(payload)

    def _apply_wallet_identity_governance_revocation_record(self, payload: dict) -> None:
        certificate_id = str(payload["certificate_id"])
        existing = self._wallet_identity_governance_revocations.get(certificate_id)
        if existing is not None:
            if existing.get("revocation_id") != payload.get("revocation_id"):
                raise ValueError("Wallet-identity governance certificate has conflicting revocations")
            return
        certificate = self._wallet_identity_governance_certificate_payload(certificate_id)
        if certificate is None:
            raise ValueError("Wallet-identity governance revocation references an unknown certificate")
        self._verify_wallet_identity_governance_certificate(certificate)
        authority_fields = (
            "eligible_voter_node_ids",
            "voter_authorities",
            "quorum_threshold",
        )
        if any(payload.get(field) != certificate.get(field) for field in authority_fields):
            raise ValueError(
                "Wallet-identity governance revocation authority does not match its certificate"
            )
        self._verify_wallet_identity_governance_revocation(payload)
        self._wallet_identity_governance_revocations[certificate_id] = deepcopy(payload)
        for wallet_id, resolution in list(self._wallet_identity_resolutions.items()):
            certificate = resolution.get("governance_certificate")
            if isinstance(certificate, dict) and certificate.get("certificate_id") == certificate_id:
                self._wallet_identity_resolutions.pop(wallet_id, None)

    def _apply_wallet_identity_resolution_proposal_record(self, payload: dict) -> None:
        resolution_id = str(payload.get("resolution_id") or "").strip()
        if not resolution_id:
            return
        existing = deepcopy(self._wallet_identity_resolution_proposals.get(resolution_id) or {})
        approvals = list(existing.get("approvals") or [])
        final_resolution = deepcopy(existing.get("final_resolution"))
        finalized_at = existing.get("finalized_at")
        self._wallet_identity_resolution_proposals[resolution_id] = {
            "resolution_id": resolution_id,
            "wallet_id": str(payload.get("wallet_id") or ""),
            "chosen_object_id": payload.get("chosen_object_id"),
            "chosen_payload_hash": payload.get("chosen_payload_hash"),
            "public_key": payload.get("public_key"),
            "registration_nonce": payload.get("registration_nonce"),
            "requested_voter_node_ids": list(payload.get("requested_voter_node_ids") or []),
            "eligible_voter_node_ids": list(payload.get("eligible_voter_node_ids") or []),
            "voter_policy": payload.get("voter_policy"),
            "quorum_threshold": payload.get("quorum_threshold"),
            "governance_policy_snapshot": deepcopy(
                payload.get("governance_policy_snapshot") or {}
            ),
            "status": payload.get("status") or existing.get("status") or "pending",
            "operator_note": payload.get("operator_note"),
            "proposed_at": payload.get("proposed_at"),
            "approvals": approvals,
            "final_resolution": final_resolution,
            **({"finalized_at": finalized_at} if finalized_at is not None else {}),
        }

    def _apply_wallet_identity_resolution_approval_record(self, payload: dict) -> None:
        resolution_id = str(payload.get("resolution_id") or "").strip()
        if not resolution_id:
            return
        proposal = deepcopy(self._wallet_identity_resolution_proposals.get(resolution_id) or {})
        proposal.setdefault("resolution_id", resolution_id)
        proposal.setdefault("wallet_id", str(payload.get("wallet_id") or ""))
        proposal.setdefault("eligible_voter_node_ids", [])
        proposal.setdefault("quorum_threshold", None)
        proposal.setdefault("status", "pending")
        proposal.setdefault("operator_note", None)
        proposal.setdefault("proposed_at", None)
        proposal.setdefault("approvals", [])
        proposal.setdefault("final_resolution", None)
        proposal = self._record_wallet_identity_resolution_approval(
            proposal=proposal,
            approver_node_id=str(payload.get("approver_node_id") or ""),
            approval_signature=payload.get("approval_signature"),
            approval_note=payload.get("approval_note"),
            approved_at=str(payload.get("approved_at") or ""),
            approval_kind=str(payload.get("approval_kind") or "approval"),
        )
        self._wallet_identity_resolution_proposals[resolution_id] = proposal

    def _apply_wallet_identity_resolution_record(self, payload: dict) -> None:
        wallet_id = str(payload.get("wallet_id") or "").strip()
        if not wallet_id:
            return
        resolution = deepcopy(payload)
        certificate = resolution.get("governance_certificate")
        if certificate is not None:
            if not isinstance(certificate, dict):
                raise ValueError("Wallet-identity resolution has an invalid governance certificate")
            if str(certificate.get("certificate_id") or "") in self._wallet_identity_governance_revocations:
                return
            self._verify_wallet_identity_governance_certificate(certificate)
            if (
                certificate.get("wallet_id") != wallet_id
                or certificate.get("chosen_object_id") != resolution.get("chosen_object_id")
                or certificate.get("chosen_payload_hash") != resolution.get("chosen_payload_hash")
            ):
                raise ValueError("Wallet-identity resolution certificate does not bind its selected identity")
        self._wallet_identity_resolutions[wallet_id] = resolution
        for conflict_id in sorted(self._conflicts):
            conflict = self._conflicts[conflict_id]
            if (
                conflict.get("conflict_class") == "wallet_identity_binding"
                and conflict.get("object_type") == "wallet_identity"
                and conflict.get("logical_key") == wallet_id
            ):
                conflict["status"] = "resolved"
                conflict["resolved_at"] = resolution.get("resolved_at")
                conflict["resolution_note"] = resolution.get("operator_note")
                conflict["resolution_payload"] = {
                    "wallet_id": wallet_id,
                    "chosen_object_id": resolution.get("chosen_object_id"),
                    "chosen_payload_hash": resolution.get("chosen_payload_hash"),
                }

    def _rebuild_wallet_identity_resolution_state(self) -> None:
        self._wallet_identity_resolutions = {}
        self._wallet_identity_resolution_proposals = {}
        self._wallet_identity_governance_revocations = {}
        for object_id in sorted(self._registry_objects):
            record = self._registry_objects[object_id]
            if record.get("object_type") == "wallet_identity_governance_revocation":
                self._apply_registry_object_state(record=record)
        for object_id in sorted(self._registry_objects):
            record = self._registry_objects[object_id]
            if record.get("object_type") != "wallet_identity_governance_revocation":
                self._apply_registry_object_state(record=record)

    def _wallet_identity_matches(self, wallet_id: str) -> list[dict]:
        matches: list[dict] = []
        for object_id in sorted(self._registry_objects):
            record = self._registry_objects[object_id]
            if self._wallet_identity_record_key(record) != wallet_id:
                continue
            matches.append(deepcopy(record))
        for node_id in sorted(self._nodes):
            node = self._nodes[node_id]
            for record in node.get("canonical_registry_objects", []):
                if self._wallet_identity_record_key(record) != wallet_id:
                    continue
                candidate = deepcopy(record)
                candidate["_source"] = {
                    "node_id": node.get("node_id"),
                    "operator_id": node.get("operator_id"),
                    "status": self._status_for(node),
                }
                matches.append(candidate)
        return matches

    def _wallet_identity_record_key(self, record: dict) -> str | None:
        if record.get("object_type") != "wallet_identity":
            return None
        if record.get("namespace") != "identity":
            return None
        source_reference = record.get("source_reference")
        if not isinstance(source_reference, str) or not source_reference:
            return None
        return source_reference

    def _validate_wallet_identity_objects(
        self,
        records: list[dict],
        *,
        exclude_node_id: str | None = None,
    ) -> None:
        seen_by_wallet: dict[str, dict] = {}
        for record in records:
            wallet_id = self._wallet_identity_record_key(record)
            if wallet_id is None:
                continue
            candidate = deepcopy(record)
            if exclude_node_id is not None:
                candidate["_source"] = {
                    "node_id": exclude_node_id,
                    "operator_id": None,
                    "status": "pending",
                }
            existing_seen = seen_by_wallet.get(wallet_id)
            if existing_seen is not None:
                if (
                    existing_seen.get("payload_hash") != candidate.get("payload_hash")
                    or existing_seen.get("object_id") != candidate.get("object_id")
                ):
                    self._record_conflict_evidence(
                        conflict_class="wallet_identity_binding",
                        object_type="wallet_identity",
                        namespace="identity",
                        logical_key=wallet_id,
                        existing_record=existing_seen,
                        conflicting_record=candidate,
                    )
                    raise ValueError(
                        f"Conflicting wallet identity objects found for {wallet_id}"
                    )
            else:
                seen_by_wallet[wallet_id] = candidate
            payload_hash = record.get("payload_hash")
            object_id = record.get("object_id")
            for existing in self._wallet_identity_matches(wallet_id):
                source_node_id = existing.get("_source", {}).get("node_id")
                if exclude_node_id is not None and source_node_id == exclude_node_id:
                    continue
                if (
                    existing.get("payload_hash") != payload_hash
                    or existing.get("object_id") != object_id
                ):
                    self._record_conflict_evidence(
                        conflict_class="wallet_identity_binding",
                        object_type="wallet_identity",
                        namespace="identity",
                        logical_key=wallet_id,
                        existing_record=existing,
                        conflicting_record=candidate,
                    )
                    raise ValueError(
                        f"Conflicting wallet identity objects found for {wallet_id}"
                    )

    def _load_registry_object_snapshot(self) -> None:
        if self._snapshot_path is None or not self._snapshot_path.exists():
            return
        try:
            snapshot = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Malformed registry object snapshot: {self._snapshot_path}"
            ) from exc
        if not isinstance(snapshot, dict):
            raise ValueError("Registry object snapshot must be a JSON object")

        schema_version = snapshot.get("schema_version")
        if schema_version != _REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported registry object snapshot schema version: {schema_version}"
            )

        objects = snapshot.get("objects")
        if not isinstance(objects, list):
            raise ValueError("Registry object snapshot must contain an objects list")

        conflicts = snapshot.get("conflicts", [])
        if not isinstance(conflicts, list):
            raise ValueError("Registry object snapshot conflicts must be a list")
        wallet_identity_peers = snapshot.get("wallet_identity_peers", [])
        if not isinstance(wallet_identity_peers, list):
            raise ValueError("Registry object snapshot wallet_identity_peers must be a list")
        replication_peers = snapshot.get("replication_peers", [])
        if not isinstance(replication_peers, list):
            raise ValueError("Registry object snapshot replication_peers must be a list")
        wallet_identity_resolutions = snapshot.get("wallet_identity_resolutions", [])
        if not isinstance(wallet_identity_resolutions, list):
            raise ValueError(
                "Registry object snapshot wallet_identity_resolutions must be a list"
            )
        wallet_identity_resolution_proposals = snapshot.get(
            "wallet_identity_resolution_proposals", []
        )
        if not isinstance(wallet_identity_resolution_proposals, list):
            raise ValueError(
                "Registry object snapshot wallet_identity_resolution_proposals must be a list"
            )
        wallet_identity_governance_policy = snapshot.get(
            "wallet_identity_governance_policy"
        )
        if (
            wallet_identity_governance_policy is not None
            and not isinstance(wallet_identity_governance_policy, dict)
        ):
            raise ValueError(
                "Registry object snapshot wallet_identity_governance_policy must be an object"
            )
        expired_registry_objects = snapshot.get("expired_registry_objects", [])
        if not isinstance(expired_registry_objects, list) or not all(
            isinstance(object_id, str) and object_id for object_id in expired_registry_objects
        ):
            raise ValueError(
                "Registry object snapshot expired_registry_objects must be a list of ids"
            )
        retention_policy = snapshot.get("retention_policy")
        if retention_policy is not None:
            if not isinstance(retention_policy, dict):
                raise ValueError(
                    "Registry object snapshot retention_policy must be an object"
                )
            self.retention_policy = RegistryRetentionPolicy.model_validate(
                retention_policy
            )
        if snapshot.get("registry_service_id") is not None:
            self.registry_service_id = str(snapshot["registry_service_id"])
        if snapshot.get("registry_generation") is not None:
            self.registry_generation = int(snapshot["registry_generation"])

        identity_dependency_order = {
            "wallet_identity_governance_certificate": 0,
            "wallet_identity_governance_revocation": 1,
            "wallet_identity_resolution": 2,
        }
        ordered_objects = sorted(
            enumerate(objects),
            key=lambda item: (
                identity_dependency_order.get(item[1].get("object_type"), 0)
                if isinstance(item[1], dict)
                else 0,
                item[0],
            ),
        )
        for index, record in ordered_objects:
            if not isinstance(record, dict):
                raise ValueError(
                    f"Registry object snapshot contains invalid object entry at index {index}"
                )
            try:
                self.upsert_registry_object(record, persist=False)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Registry object snapshot contains invalid object entry at index {index}"
                ) from exc
        self._expired_registry_objects = {
            object_id
            for object_id in expired_registry_objects
            if object_id in self._registry_objects
        }
        for index, conflict in enumerate(conflicts):
            if not isinstance(conflict, dict):
                raise ValueError(
                    f"Registry object snapshot contains invalid conflict entry at index {index}"
                )
            model = RegistryConflictEvidence.model_validate(conflict)
            self._conflicts[model.conflict_id] = model.model_dump(mode="json")
        for index, peer in enumerate(wallet_identity_peers):
            if not isinstance(peer, dict):
                raise ValueError(
                    "Registry object snapshot contains invalid wallet identity peer entry "
                    f"at index {index}"
                )
            model = RegistryWalletIdentityPeerConfig.model_validate(peer)
            record = model.model_dump(mode="json")
            for field in (
                "expected_node_id",
                "expected_operator_id",
                "expected_owner_wallet_id",
            ):
                if record[field] is None:
                    record.pop(field)
            self._wallet_identity_peers[model.peer_base_url.rstrip("/")] = record
        for index, peer in enumerate(replication_peers):
            if not isinstance(peer, dict):
                raise ValueError(
                    "Registry object snapshot contains invalid replication peer entry "
                    f"at index {index}"
                )
            model = RegistryReplicationPeerConfig.model_validate(peer)
            try:
                PeerAuthenticator().register_key(model.peer_id, model.public_key)
            except ValueError as exc:
                raise ValueError(
                    "Registry object snapshot contains invalid replication peer entry "
                    f"at index {index}"
                ) from exc
            self._replication_peers[model.peer_id] = model.model_dump(mode="json")
        for index, resolution in enumerate(wallet_identity_resolutions):
            if not isinstance(resolution, dict):
                raise ValueError(
                    "Registry object snapshot contains invalid wallet identity resolution entry "
                    f"at index {index}"
                )
            wallet_id = str(resolution.get("wallet_id") or "").strip()
            if not wallet_id:
                raise ValueError(
                    "Registry object snapshot contains wallet identity resolution without wallet_id "
                    f"at index {index}"
                )
            self._wallet_identity_resolutions[wallet_id] = deepcopy(resolution)
        for index, proposal in enumerate(wallet_identity_resolution_proposals):
            if not isinstance(proposal, dict):
                raise ValueError(
                    "Registry object snapshot contains invalid wallet identity resolution proposal entry "
                    f"at index {index}"
                )
            resolution_id = str(proposal.get("resolution_id") or "").strip()
            if not resolution_id:
                raise ValueError(
                    "Registry object snapshot contains wallet identity resolution proposal without resolution_id "
                    f"at index {index}"
                )
            self._wallet_identity_resolution_proposals[resolution_id] = deepcopy(
                proposal
            )
        if wallet_identity_governance_policy is not None:
            model = RegistryWalletIdentityGovernancePolicy.model_validate(
                wallet_identity_governance_policy
            )
            self._wallet_identity_governance_policy = model.model_dump(mode="json")

    def _persist_registry_object_snapshot(self) -> None:
        """Atomically persist one snapshot without colliding writer threads."""
        with self._snapshot_lock:
            self._write_registry_object_snapshot()

    def _write_registry_object_snapshot(self) -> None:
        if self._snapshot_path is None:
            return
        self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "schema_version": _REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION,
            "registry_service_id": self.registry_service_id,
            "registry_generation": self.registry_generation,
            "retention_policy": self.retention_policy.model_dump(mode="json"),
            "expired_registry_objects": sorted(self._expired_registry_objects),
            "objects": [
                deepcopy(self._registry_objects[object_id])
                for object_id in sorted(self._registry_objects)
            ],
            "conflicts": [
                deepcopy(self._conflicts[conflict_id])
                for conflict_id in sorted(self._conflicts)
            ],
            "wallet_identity_peers": [
                deepcopy(self._wallet_identity_peers[peer_base_url])
                for peer_base_url in sorted(self._wallet_identity_peers)
            ],
            "replication_peers": [
                deepcopy(self._replication_peers[peer_id])
                for peer_id in sorted(self._replication_peers)
            ],
            "wallet_identity_resolutions": [
                deepcopy(self._wallet_identity_resolutions[wallet_id])
                for wallet_id in sorted(self._wallet_identity_resolutions)
            ],
            "wallet_identity_resolution_proposals": [
                deepcopy(self._wallet_identity_resolution_proposals[resolution_id])
                for resolution_id in sorted(self._wallet_identity_resolution_proposals)
            ],
            "wallet_identity_governance_policy": deepcopy(
                self._wallet_identity_governance_policy
            ),
        }
        temp_path = self._snapshot_path.with_suffix(self._snapshot_path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temp_path.replace(self._snapshot_path)

    def _status_for(self, record: dict) -> str:
        heartbeat = datetime.fromisoformat(record["heartbeat_at"]).timestamp()
        ttl = int(record["heartbeat_ttl_seconds"])
        age = time.time() - heartbeat
        if age <= ttl:
            return "ready"
        if age <= ttl + self.stale_grace_seconds:
            return "stale"
        return "offline"

    def _bundle_matches(self, bundle: dict, query: RegistryDiscoveryQuery) -> bool:
        if query.workload_type is not None and bundle["workload_type"] != query.workload_type:
            return False
        if query.provider_type is not None and bundle["provider_type"] != query.provider_type:
            return False
        if query.bundle_id is not None and bundle["bundle_id"] != query.bundle_id:
            return False
        if query.model_id is not None and query.model_id.lower() not in bundle["model_id"].lower():
            return False
        if query.require_allocation_support and not bundle["supports_allocation"]:
            return False
        if query.require_queue_support and not bundle["supports_queue"]:
            return False
        return not (query.ready_endpoint_only and not self._bundle_endpoint_ready(bundle))

    def _uses_canonical_filters(self, query: RegistryDiscoveryQuery) -> bool:
        return any(
            value is not None
            for value in (
                query.capability_id,
                query.runtime_id,
                query.advertisement_resource_type,
                query.visibility,
                query.owner_wallet,
            )
        )

    def _uses_legacy_filters(self, query: RegistryDiscoveryQuery) -> bool:
        return any(
            value is not None
            for value in (
                query.workload_type,
                query.provider_type,
                query.model_id,
                query.bundle_id,
            )
        ) or query.require_allocation_support or query.require_queue_support or query.ready_endpoint_only

    def _bundle_endpoint_ready(self, bundle: dict) -> bool:
        return bool(bundle.get("enabled")) and bundle.get("status") == "ready" and bool(
            bundle.get("endpoint")
        )

    def _flatten_canonical_candidates_for_node(self, node: dict) -> list[dict]:
        candidates: list[dict] = []
        runtimes_by_id = {}
        runtimes_by_capability: dict[str, list[dict]] = {}
        for runtime in node.get("canonical_capability_runtimes", []):
            runtimes_by_id[runtime["runtime_id"]] = runtime
            runtimes_by_capability.setdefault(runtime["capability_id"], []).append(runtime)
        compatibility_by_capability: dict[str, list[dict]] = {}
        compatibility_by_runtime_id: dict[str, list[dict]] = {}
        for item in node.get("canonical_compute_compatibility", []):
            compatibility_by_capability.setdefault(item["canonical_capability_id"], []).append(item)
            compatibility_by_runtime_id.setdefault(item["canonical_runtime_id"], []).append(item)
        for advertisement in node.get("canonical_advertisements", []):
            service_id = self._service_id_for_advertisement(advertisement=advertisement)
            capability_id = advertisement.get("capability_id")
            runtime_rows = (
                runtimes_by_capability.get(capability_id, [])
                if capability_id is not None
                else []
            )
            emitted = False
            for runtime in runtime_rows:
                compatibility_rows = compatibility_by_runtime_id.get(runtime["runtime_id"]) or [None]
                for compatibility in compatibility_rows:
                    candidates.append(
                        self._canonical_candidate_row(
                            node=node,
                            advertisement=advertisement,
                            service_id=service_id,
                            capability_id=capability_id,
                            runtime=runtime,
                            compatibility=compatibility,
                        )
                    )
                emitted = True

            if emitted:
                continue

            compatibility_rows = (
                compatibility_by_capability.get(capability_id, [])
                if capability_id is not None
                else []
            )
            for compatibility in compatibility_rows:
                candidates.append(
                    self._canonical_candidate_row(
                        node=node,
                        advertisement=advertisement,
                        service_id=service_id,
                        capability_id=capability_id,
                        runtime=runtimes_by_id.get(compatibility.get("canonical_runtime_id"), {}),
                        compatibility=compatibility,
                    )
                )
                emitted = True

            if not emitted:
                candidates.append(
                    self._canonical_candidate_row(
                        node=node,
                        advertisement=advertisement,
                        service_id=service_id,
                        capability_id=capability_id,
                        runtime={},
                        compatibility=None,
                    )
                )
        return candidates

    def _canonical_candidate_row(
        self,
        *,
        node: dict,
        advertisement: dict,
        service_id: str,
        capability_id: str | None,
        runtime: dict,
        compatibility: dict | None,
    ) -> dict:
        runtime_id = runtime.get("runtime_id")
        if runtime_id is None and compatibility is not None:
            runtime_id = compatibility.get("canonical_runtime_id")
        row = {
            "node_id": node["node_id"],
            "operator_id": node["operator_id"],
            "base_url": node["base_url"],
            "status": node["status"],
            "service_id": service_id,
            "capability_id": capability_id,
            "capability_version": advertisement.get("capability_version"),
            "runtime_id": runtime_id,
            "advertisement_id": advertisement["advertisement_id"],
            "offer_id": advertisement.get("offer_id"),
            "capability_definition_hash": advertisement.get("capability_definition_hash"),
            "feature_profile_hash": advertisement.get("feature_profile_hash"),
            "limit_profile_hash": advertisement.get("limit_profile_hash"),
            "implementation_profile_hash": advertisement.get(
                "implementation_profile_hash"
            ),
            "resource_type": advertisement["resource_type"],
            "visibility": advertisement["visibility"],
            "owner_wallet": advertisement.get("owner_wallet"),
            "pricing": node["pricing"],
            "rating": node["rating"],
            "can_host_custom_model": node["can_host_custom_model"],
            "published_endpoint_count": len(node.get("published_endpoints", [])),
            "trust_summary": self._canonical_trust_summary(node),
            "legacy_bundle_id": (
                compatibility.get("legacy_bundle_id") if compatibility is not None else None
            ),
            "legacy_plugin_id": (
                compatibility.get("legacy_plugin_id") if compatibility is not None else None
            ),
            "legacy_provider_type": (
                compatibility.get("legacy_provider_type")
                if compatibility is not None
                else None
            ),
        }
        if node.get("reputation") is not None:
            row["reputation"] = node["reputation"]
        return row

    def _service_id_for_advertisement(self, *, advertisement: dict) -> str:
        resource_type = advertisement.get("resource_type")
        if resource_type == "registry_service":
            return "registry"
        if resource_type == "validation_service":
            return "validation"
        if resource_type == "consensus_service":
            return "consensus"
        return "compute"

    def _canonical_candidate_matches(
        self,
        *,
        candidate: dict,
        query: RegistryDiscoveryQuery,
    ) -> bool:
        if query.capability_id is not None and candidate.get("capability_id") != query.capability_id:
            return False
        if (
            query.advertisement_resource_type is not None
            and candidate.get("resource_type") != query.advertisement_resource_type
        ):
            return False
        if query.visibility is not None and candidate.get("visibility") != query.visibility:
            return False
        if (
            query.owner_wallet is not None
            and candidate.get("owner_wallet") != query.owner_wallet
        ):
            return False
        return not (query.runtime_id is not None and candidate.get("runtime_id") != query.runtime_id)

    def _canonical_trust_summary(self, node: dict) -> dict:
        published_endpoints = node.get("published_endpoints", [])
        validation_by_status: dict[str, int] = {}
        publication_by_status: dict[str, int] = {}
        custody_by_status: dict[str, int] = {}
        certified_count = 0
        certified_with_issues_count = 0
        validated_count = 0
        pending_count = 0
        attention_count = 0
        in_sync_count = 0
        drift_count = 0
        custody_available_count = 0
        custody_attention_count = 0
        custody_unverified_count = 0

        for item in published_endpoints:
            validation_summary = item.get("published_validation_summary", {}) or {}
            certification_status = validation_summary.get("certification_status")
            validation_status = validation_summary.get("validation_status", "unknown")
            publication_status = item.get("publication_sync_status") or "unknown"
            custody_status = (item.get("published_custody_summary") or {}).get(
                "custody_status", "unknown"
            )
            validation_by_status[validation_status] = (
                validation_by_status.get(validation_status, 0) + 1
            )
            publication_by_status[publication_status] = (
                publication_by_status.get(publication_status, 0) + 1
            )
            custody_by_status[custody_status] = (
                custody_by_status.get(custody_status, 0) + 1
            )

            if certification_status == "certified":
                certified_count += 1
            elif certification_status == "certified_with_issues":
                certified_with_issues_count += 1
            elif certification_status in {
                "pending_initial",
                "maintenance_in_progress",
                "maintenance_due",
                "uncertified",
            }:
                pending_count += 1
            elif certification_status not in {None, "superseded"}:
                attention_count += 1
            elif validation_status == "validated":
                validated_count += 1
            elif validation_status in {"pending_initial", "pending_maintenance", "unvalidated"}:
                pending_count += 1
            elif validation_status not in {"unknown"}:
                attention_count += 1

            if publication_status == "in_sync":
                in_sync_count += 1
            elif publication_status in {
                "local_changes_not_published",
                "published_configuration_not_served",
            }:
                drift_count += 1

            if custody_status == "available":
                custody_available_count += 1
            elif custody_status in {"attention_required", "partially_checked"}:
                custody_attention_count += 1
            elif custody_status in {"not_reported", "not_checked", "unknown"}:
                custody_unverified_count += 1

        return {
            "total_endpoints": len(published_endpoints),
            "certified_count": certified_count,
            "certified_with_issues_count": certified_with_issues_count,
            "validated_count": certified_count + certified_with_issues_count + validated_count,
            "pending_count": pending_count,
            "attention_count": attention_count,
            "in_sync_count": in_sync_count,
            "drift_count": drift_count,
            "custody_available_count": custody_available_count,
            "custody_attention_count": custody_attention_count,
            "custody_unverified_count": custody_unverified_count,
            "validation_by_status": validation_by_status,
            "publication_by_status": publication_by_status,
            "custody_by_status": custody_by_status,
        }

    def _candidate_sort_key(self, candidate: dict) -> tuple:
        return (
            {"ready": 0, "stale": 1, "offline": 2}[candidate["status"]],
            0 if candidate["endpoint_ready"] else 1,
            0 if candidate["supports_allocation"] else 1,
            0 if candidate["supports_queue"] else 1,
            -self._node_rating_score(candidate),
            candidate["pricing"]["input"],
            candidate["pricing"]["output"],
            candidate["node_id"],
            candidate["bundle_id"],
        )

    def _canonical_candidate_sort_key(self, candidate: dict) -> tuple:
        return (
            {"ready": 0, "stale": 1, "offline": 2}[candidate["status"]],
            -self._node_rating_score(candidate),
            candidate["pricing"]["input"],
            candidate["pricing"]["output"],
            candidate["node_id"],
            candidate["advertisement_id"],
        )

    def _node_rating_score(self, item: dict) -> float:
        reputation = item.get("reputation") or {}
        if reputation.get("score") is not None:
            return float(reputation.get("score") or 0)
        rating = item.get("rating") or {}
        return float(rating.get("score") or 0)
