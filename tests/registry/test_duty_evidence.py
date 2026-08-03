from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.registry import (
    RegistryDutyEvidence,
    RegistryDutyVerifier,
    registry_duty_signing_bytes,
)
from aidn_hypervisor.registry.proof import verify_ed25519_signature
from aidn_hypervisor.registry_service import RegistryService


class _StaticFinalitySource:
    def __init__(self, evidence: ConsensusFinalityEvidence | None) -> None:
        self.evidence = evidence

    def finality_evidence(self, operation_id: str) -> ConsensusFinalityEvidence | None:
        if self.evidence is not None and self.evidence.operation_id == operation_id:
            return self.evidence
        return None


def _public_key(private_key: Ed25519PrivateKey) -> str:
    return "ed25519:" + private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


def _finality() -> ConsensusFinalityEvidence:
    return ConsensusFinalityEvidence(
        operation_id="epoch-transition-12",
        chain_id="aidn-testnet",
        block_height=120,
        block_id="block-120",
        app_hash="app-hash-120",
        commit_hash="commit-120",
        finalized_at="2026-08-01T00:00:00Z",
        verifier_id="validator-quorum",
    )


def _build_evidence(
    *,
    manifest,
    finality: ConsensusFinalityEvidence,
    private_key: Ed25519PrivateKey,
    **overrides,
) -> RegistryDutyEvidence:
    values = {
        "registry_service_id": "registry-1",
        "epoch": 12,
        "profile_version": "registry-profile.v1",
        "profile_hash": "sha256:registry-profile",
        "inventory_manifest_id": manifest.manifest_id,
        "inventory_root": manifest.inventory_root.root_hash,
        "inventory_generation": manifest.generation,
        "completeness_manifest_hash": "sha256:completeness-12",
        "initial_sync_complete": True,
        "profile_compliant": True,
        "reachable": True,
        "mandatory_challenge_count": 10,
        "successful_mandatory_challenge_count": 10,
        "required_object_count": 100,
        "verified_required_object_count": 100,
        "availability_observation_count": 10,
        "availability_success_count": 10,
        "latency_factor_millionths": 1_000_000,
        "reliability_factor_millionths": 1_000_000,
        "health_factor_millionths": 900_000,
        "maturity_factor_millionths": 1_000_000,
        "additional_work_units_millionths": 100_000,
        "registry_work_units_millionths": 1_100_000,
        "activation_epoch": 0,
        "activation_age_epochs": 12,
        "required_activation_age_epochs": 10,
        "collateral_q_atoms": 0,
        "required_collateral_q_atoms": 0,
        "operator_wallet": "wallet:operator-1",
        "reward_beneficiary": "wallet:reward-1",
        "known_control_group_id": "kcg-1",
        "protocol_version": "1.0.0",
        "required_protocol_version": "1.0.0",
        "suspended": False,
        "unresolved_conflict_count": 0,
        "evidence_references": [manifest.manifest_id],
        "generated_at": "2026-08-01T00:00:00Z",
    }
    values.update(overrides)
    return RegistryDutyEvidence.create(
        finality_evidence=finality,
        signer=lambda payload: "ed25519:" + private_key.sign(payload).hex(),
        **values,
    )


def _verifier(
    finality: ConsensusFinalityEvidence,
    private_key: Ed25519PrivateKey,
) -> RegistryDutyVerifier:
    public_key = _public_key(private_key)
    return RegistryDutyVerifier(
        finality_source=_StaticFinalitySource(finality),
        expected_registry_service_id="registry-1",
        required_profile_version="registry-profile.v1",
        signature_verifier=lambda evidence: verify_ed25519_signature(
            public_key=public_key,
            signature=evidence.signature,
            payload=registry_duty_signing_bytes(evidence),
        ),
    )


def test_registry_duty_evidence_is_deterministic_and_produces_fixed_point_reward_input() -> None:
    service = RegistryService(registry_service_id="registry-1")
    manifest = service.get_local_registry_inventory_manifest(generated_at_epoch=12)
    private_key = Ed25519PrivateKey.generate()
    first = _build_evidence(
        manifest=manifest,
        finality=_finality(),
        private_key=private_key,
    )
    second = _build_evidence(
        manifest=manifest,
        finality=_finality(),
        private_key=private_key,
    )

    assert first.evidence_id == second.evidence_id
    assert first.evidence_hash == second.evidence_hash
    assert first.verify_integrity() is True

    verifier = _verifier(_finality(), private_key)
    result = verifier.evaluate(first, expected_inventory_manifest=manifest)
    reward_input = verifier.build_reward_input(first, result)

    assert result.valid is True
    assert result.eligible is True
    assert result.raw_weight_millionths == 990_000
    assert reward_input.raw_weight_millionths == 990_000
    snapshot = verifier.build_eligibility_snapshot(first, result)
    assert snapshot.state == "eligible"
    assert snapshot.evidence_hash == first.evidence_hash
    assert reward_input.eligibility_snapshot_id == snapshot.snapshot_id
    assert isinstance(reward_input.raw_weight_millionths, int)


def test_registry_duty_evidence_fails_closed_without_consensus_finality() -> None:
    service = RegistryService(registry_service_id="registry-1")
    manifest = service.get_local_registry_inventory_manifest(generated_at_epoch=12)
    private_key = Ed25519PrivateKey.generate()
    evidence = _build_evidence(
        manifest=manifest,
        finality=_finality(),
        private_key=private_key,
    )
    verifier = RegistryDutyVerifier(
        finality_source=_StaticFinalitySource(None),
        expected_registry_service_id="registry-1",
        required_profile_version="registry-profile.v1",
        signature_verifier=lambda _: True,
    )

    result = verifier.evaluate(evidence, expected_inventory_manifest=manifest)

    assert result.valid is False
    assert result.eligible is False
    assert "consensus_finality_missing" in result.reasons


def test_valid_finality_can_still_be_ineligible_without_creating_reward_input() -> None:
    service = RegistryService(registry_service_id="registry-1")
    manifest = service.get_local_registry_inventory_manifest(generated_at_epoch=12)
    private_key = Ed25519PrivateKey.generate()
    evidence = _build_evidence(
        manifest=manifest,
        finality=_finality(),
        private_key=private_key,
        successful_mandatory_challenge_count=8,
        unresolved_conflict_count=1,
    )
    verifier = _verifier(_finality(), private_key)
    result = verifier.evaluate(evidence, expected_inventory_manifest=manifest)

    assert result.valid is True
    assert result.eligible is False
    assert "proof_success_below_threshold" in result.reasons
    assert "unresolved_registry_conflicts" in result.reasons

    try:
        verifier.build_reward_input(evidence, result)
    except ValueError as error:
        assert "ineligible" in str(error)
    else:
        raise AssertionError("ineligible Registry must not produce reward input")


def test_registry_service_commits_verification_idempotently_without_minting() -> None:
    finality = _finality()
    private_key = Ed25519PrivateKey.generate()
    ledger = LedgerOperationService()
    service = RegistryService(
        registry_service_id="registry-1",
        ledger_operation_service=ledger,
        consensus_finality_source=_StaticFinalitySource(finality),
    )
    manifest = service.get_local_registry_inventory_manifest(generated_at_epoch=12)
    evidence = _build_evidence(
        manifest=manifest,
        finality=finality,
        private_key=private_key,
    )

    committed = service.commit_registry_duty_evidence(
        evidence,
        expected_inventory_manifest=manifest,
        verifier=_verifier(finality, private_key),
    )
    repeated = service.commit_registry_duty_evidence(
        evidence,
        expected_inventory_manifest=manifest,
        verifier=_verifier(finality, private_key),
    )

    operations = ledger.snapshot_operations()
    assert committed["eligibility"]["eligible"] is True
    assert committed["reward_input"]["raw_weight_millionths"] == 990_000
    assert committed["eligibility_snapshot"]["state"] == "eligible"
    assert repeated["ledger_commitment"] == committed["ledger_commitment"]
    assert [item["operation_type"] for item in operations] == [
        "SERVICE_VERIFICATION_COMMIT"
    ]
    assert not any(item["operation_type"] == "REWARD_MINT" for item in operations)
    assert ledger.wallet_q_atom_balance("wallet:reward-1") == 0
