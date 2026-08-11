"""Hash-bound Faucet Treasury manifest primitives.

The manifest is a Genesis/accounting input only. It does not implement Faucet
policy, sign transfers, or expose a Ledger credit path.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

FAUCET_TREASURY_SCHEMA = "aidn.faucet-treasury.v1"
FAUCET_TREASURY_ACTIVATION_PROOF_SCHEMA = "aidn.faucet-treasury-activation-proof.v1"
FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS = 10_000_000_000_000
FAUCET_TREASURY_FUNDING_DOMAIN = "aidn.faucet-treasury-funding.v1"
FAUCET_TREASURY_MANIFEST_BINDING_DOMAIN = "aidn.faucet-treasury-manifest-bind.v1"
_PUBLIC_KEY_RE = re.compile(r"^ed25519:[0-9a-fA-F]{64}$")
_HASH_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
_OPERATION_ID_RE = re.compile(r"^[0-9a-fA-F]{64}$")

_FUNDING_AUTHORIZATION_FIELDS = (
    "funding_id",
    "treasury_id",
    "network_id",
    "chain_id",
    "treasury_wallet_id",
    "treasury_public_key",
    "creator_recovery_wallet",
    "creator_recovery_public_key",
    "amount",
    "treasury_manifest_hash",
    "funding_mode",
    "authorization_reference",
)

_MANIFEST_BINDING_AUTHORIZATION_FIELDS = (
    "treasury_manifest",
    "creator_recovery_public_key",
    "authorization_reference",
)


def _canonical_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _hash_payload(value: dict) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def wallet_id_for_public_key(public_key: str) -> str:
    """Derive the protocol Wallet ID used by the Treasury manifest."""

    if not _PUBLIC_KEY_RE.fullmatch(public_key):
        raise ValueError("public key must use ed25519:<64 hex characters>")
    return "wallet-" + hashlib.sha256(public_key.encode("utf-8")).hexdigest()[:12]


def faucet_treasury_funding_authorization_bytes(payload: dict) -> bytes:
    """Return the canonical creator authorization preimage for TREASURY_FUND."""

    authorization_payload = {
        field_name: payload.get(field_name)
        for field_name in _FUNDING_AUTHORIZATION_FIELDS
    }
    return _canonical_json(
        {
            "domain": FAUCET_TREASURY_FUNDING_DOMAIN,
            "payload": authorization_payload,
        }
    )


def faucet_treasury_manifest_binding_authorization_bytes(payload: dict) -> bytes:
    """Return the canonical creator authorization preimage for a manifest bind.

    The manifest itself is signed before the first funding transition.  This
    makes a post-genesis Treasury declaration a replicated consensus fact,
    rather than a per-node environment setting.
    """

    authorization_payload = {
        field_name: payload.get(field_name)
        for field_name in _MANIFEST_BINDING_AUTHORIZATION_FIELDS
    }
    return _canonical_json(
        {
            "domain": FAUCET_TREASURY_MANIFEST_BINDING_DOMAIN,
            "payload": authorization_payload,
        }
    )


class FaucetTreasuryManifest(BaseModel):
    """Public, secret-free initial Treasury declaration."""

    schema_version: Literal[FAUCET_TREASURY_SCHEMA] = FAUCET_TREASURY_SCHEMA
    treasury_id: str = Field(min_length=1)
    network_id: str = Field(min_length=1)
    chain_id: str = Field(min_length=1)
    wallet_id: str = Field(min_length=1)
    wallet_public_key: str = Field(min_length=1)
    creator_recovery_wallet: str = Field(min_length=1)
    genesis_allocation_q_atoms: int = Field(gt=0)
    funding_mode: Literal["GENESIS", "CONSENSUS"] = "GENESIS"
    funding_id: str | None = None
    # The consensus envelope ID is unknown when the pre-funding manifest is
    # created. It is post-finalization metadata and is excluded from the
    # manifest hash so the canonical declaration remains stable.
    funding_operation_id: str | None = None
    policy_registry_hash: str = Field(min_length=1)
    object_version: int = Field(default=1, ge=1)
    manifest_hash: str = ""

    model_config = {"extra": "forbid", "frozen": True}

    def _hash_payload(self) -> dict:
        payload = self.model_dump(mode="json")
        payload.pop("manifest_hash", None)
        payload.pop("funding_operation_id", None)
        if self.funding_mode == "GENESIS":
            # Preserve the v1 Genesis hash for manifests created before the
            # consensus funding metadata was introduced.
            payload.pop("funding_id", None)
        return payload

    def expected_manifest_hash(self) -> str:
        return _hash_payload(self._hash_payload())

    def model_post_init(self, __context) -> None:
        if not _PUBLIC_KEY_RE.fullmatch(self.wallet_public_key):
            raise ValueError("faucet Treasury public key must be ed25519:<64 hex characters>")
        expected_wallet_id = wallet_id_for_public_key(self.wallet_public_key)
        if self.wallet_id != expected_wallet_id:
            raise ValueError("faucet Treasury wallet_id does not match wallet_public_key")
        if self.creator_recovery_wallet == self.wallet_id:
            raise ValueError("creator recovery Wallet must differ from Faucet Treasury Wallet")
        if self.genesis_allocation_q_atoms != FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS:
            raise ValueError("initial Faucet Treasury allocation must be exactly 10,000,000 Q")
        if not _HASH_RE.fullmatch(self.policy_registry_hash):
            raise ValueError("policy_registry_hash must be sha256:<64 hex characters>")
        if self.funding_mode == "GENESIS" and (
            self.funding_id is not None or self.funding_operation_id is not None
        ):
            raise ValueError("Genesis Treasury funding cannot contain funding metadata")
        if self.funding_mode == "CONSENSUS" and not self.funding_id:
            raise ValueError("consensus Treasury funding requires funding_id")
        if self.funding_operation_id is not None and not _OPERATION_ID_RE.fullmatch(
            self.funding_operation_id
        ):
            raise ValueError("funding_operation_id must be a 64-character operation ID")
        expected_hash = self.expected_manifest_hash()
        if self.manifest_hash and self.manifest_hash != expected_hash:
            raise ValueError("faucet Treasury manifest_hash does not match the manifest")
        object.__setattr__(self, "manifest_hash", expected_hash)

    def genesis_accounts(self) -> dict[str, int]:
        """Return the account projection used by the application Genesis loader."""

        if self.funding_mode != "GENESIS":
            raise ValueError("consensus-funded Treasury has no Genesis account projection")
        return {self.wallet_id: self.genesis_allocation_q_atoms}


class FaucetTreasuryActivationProof(BaseModel):
    """Canonical evidence that a Treasury is the active network Treasury.

    A public manifest is only a declaration. This object is produced after
    querying the active consensus boundary and binds that declaration to the
    canonical funding event (or Genesis state) and the observed balance.
    """

    schema_version: Literal[FAUCET_TREASURY_ACTIVATION_PROOF_SCHEMA] = (
        FAUCET_TREASURY_ACTIVATION_PROOF_SCHEMA
    )
    state: Literal["ACTIVE", "UNVERIFIED", "DEGRADED"]
    treasury_id: str = Field(min_length=1)
    network_id: str = Field(min_length=1)
    chain_id: str = Field(min_length=1)
    wallet_id: str = Field(min_length=1)
    manifest_hash: str = Field(min_length=1)
    funding_mode: Literal["GENESIS", "CONSENSUS"]
    funding_id: str | None = None
    funding_operation_id: str | None = None
    funded_amount_q_atoms: int = Field(ge=0)
    observed_balance_q_atoms: int | None = Field(default=None, ge=0)
    evidence_type: Literal["GENESIS_STATE", "CONSENSUS_FUNDING"] | None = None
    canonical_evidence: dict[str, Any] | None = None
    quorum: int | None = Field(default=None, ge=1)
    source_count: int | None = Field(default=None, ge=1)
    reason: str | None = None
    proof_hash: str = ""

    model_config = {"extra": "forbid", "frozen": True}

    def _hash_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload.pop("proof_hash", None)
        return payload

    def expected_proof_hash(self) -> str:
        return _hash_payload(self._hash_payload())

    def model_post_init(self, __context: Any) -> None:
        if not _HASH_RE.fullmatch(self.manifest_hash):
            raise ValueError("Treasury activation proof manifest_hash is invalid")
        if self.state == "ACTIVE" and self.funding_mode == "CONSENSUS":
            if not self.funding_id:
                raise ValueError("consensus Treasury activation proof requires funding_id")
            if not self.funding_operation_id:
                raise ValueError("consensus Treasury activation proof requires funding_operation_id")
        if self.state == "ACTIVE":
            if self.funded_amount_q_atoms != FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS:
                raise ValueError("active Treasury activation proof has an invalid funded amount")
            if self.observed_balance_q_atoms is None:
                raise ValueError("active Treasury activation proof requires an observed balance")
            if self.evidence_type is None or self.canonical_evidence is None:
                raise ValueError("active Treasury activation proof requires canonical evidence")
            if self.quorum is None or self.source_count is None or self.quorum > self.source_count:
                raise ValueError("active Treasury activation proof has invalid quorum evidence")
            evidence = self.canonical_evidence
            if evidence.get("manifest_hash") != self.manifest_hash:
                raise ValueError("Treasury activation evidence does not bind the manifest")
            if evidence.get("chain_id") != self.chain_id:
                raise ValueError("Treasury activation evidence does not bind the chain")
            if self.funding_mode == "CONSENSUS":
                if self.evidence_type != "CONSENSUS_FUNDING":
                    raise ValueError("consensus Treasury activation requires funding evidence")
                if evidence.get("funding_id") != self.funding_id:
                    raise ValueError("Treasury activation evidence does not bind funding ID")
                if evidence.get("operation_id") != self.funding_operation_id:
                    raise ValueError("Treasury activation evidence does not bind funding operation")
                if evidence.get("operation_type") != "TREASURY_FUND":
                    raise ValueError("Treasury activation evidence has the wrong operation type")
            elif self.evidence_type != "GENESIS_STATE":
                raise ValueError("Genesis Treasury activation requires Genesis state evidence")
        expected_hash = self.expected_proof_hash()
        if self.proof_hash and self.proof_hash != expected_hash:
            raise ValueError("Treasury activation proof_hash does not match the proof")
        object.__setattr__(self, "proof_hash", expected_hash)

    @classmethod
    def unavailable(
        cls,
        manifest: FaucetTreasuryManifest,
        *,
        reason: str,
        observed_balance_q_atoms: int | None = None,
    ) -> FaucetTreasuryActivationProof:
        """Build a hash-bound non-active proof for diagnostics and status APIs."""

        return cls(
            state="UNVERIFIED",
            treasury_id=manifest.treasury_id,
            network_id=manifest.network_id,
            chain_id=manifest.chain_id,
            wallet_id=manifest.wallet_id,
            manifest_hash=manifest.manifest_hash,
            funding_mode=manifest.funding_mode,
            funding_id=manifest.funding_id,
            funding_operation_id=manifest.funding_operation_id,
            funded_amount_q_atoms=0,
            observed_balance_q_atoms=observed_balance_q_atoms,
            reason=reason,
        )


def validate_faucet_treasury_manifest(
    manifest: FaucetTreasuryManifest,
    *,
    expected_network_id: str | None = None,
    expected_chain_id: str | None = None,
) -> FaucetTreasuryManifest:
    """Fail closed when a manifest is for another network or chain."""

    if expected_network_id is not None and manifest.network_id != expected_network_id:
        raise ValueError("faucet Treasury network_id does not match the active network")
    if expected_chain_id is not None and manifest.chain_id != expected_chain_id:
        raise ValueError("faucet Treasury chain_id does not match the active chain")
    return manifest
