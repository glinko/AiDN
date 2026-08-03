from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.registry import (
    ImmutableObjectStore,
    ProofOfRegistryEngine,
    RegistryInventoryManifest,
    RegistryObjectEnvelope,
    RegistryRepairEngine,
)
from aidn_hypervisor.registry.replicator import RegistryReplicator


def _public_key(private_key: Ed25519PrivateKey) -> str:
    return "ed25519:" + private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


def _envelope(object_id: str, value: str, *, epoch: int = 1) -> RegistryObjectEnvelope:
    return RegistryObjectEnvelope.create(
        object_id=object_id,
        object_type="advertisement",
        payload={"value": value},
        created_epoch=epoch,
    )


def _manifest(registry_id: str, objects: list[RegistryObjectEnvelope]):
    return RegistryInventoryManifest.create(
        registry_service_id=registry_id,
        generated_at_epoch=1,
        objects=objects,
        retention_policy_hash="retention-v1",
    )


def test_proof_of_registry_selects_and_verifies_a_signed_object() -> None:
    private_key = Ed25519PrivateKey.generate()
    store = ImmutableObjectStore()
    first = _envelope("object-1", "one")
    second = _envelope("object-2", "two")
    store.put(first)
    store.put(second)
    engine = ProofOfRegistryEngine(
        registry_id="registry-b",
        store=store,
        manifest_provider=lambda: _manifest("registry-b", [first, second]),
        signer=lambda payload: "ed25519:" + private_key.sign(payload).hex(),
    )
    manifest = _manifest("registry-b", [first, second])
    challenge = engine.create_challenge(
        target_registry_id="registry-b",
        inventory_root=manifest.inventory_root.root_hash,
        challenger_id="registry-a",
        target_segment_id="advertisement:all",
        challenge_nonce="challenge-1",
    )

    response = engine.answer_challenge(challenge)
    result = engine.verify_response(
        challenge=challenge,
        response=response,
        expected_inventory_manifest=manifest,
        expected_registry_public_key=_public_key(private_key),
    )

    assert result.valid is True
    assert result.reason == "verified"
    assert result.selected_object_id in {"object-1", "object-2"}


def test_proof_rejects_tampered_object_after_signature() -> None:
    private_key = Ed25519PrivateKey.generate()
    store = ImmutableObjectStore()
    source = _envelope("object-1", "one")
    store.put(source)
    manifest = _manifest("registry-b", [source])
    engine = ProofOfRegistryEngine(
        registry_id="registry-b",
        store=store,
        manifest_provider=lambda: manifest,
        signer=lambda payload: "ed25519:" + private_key.sign(payload).hex(),
    )
    challenge = engine.create_challenge(
        target_registry_id="registry-b",
        inventory_root=manifest.inventory_root.root_hash,
        challenger_id="registry-a",
        target_segment_id="advertisement:all",
        challenge_nonce="challenge-2",
    )
    response = engine.answer_challenge(challenge)
    tampered = response.model_copy(
        update={"object_hash": "0" * 64}
    )

    result = engine.verify_response(
        challenge=challenge,
        response=tampered,
        expected_inventory_manifest=manifest,
        expected_registry_public_key=_public_key(private_key),
    )

    assert result.valid is False
    assert result.reason == "registry_signature_invalid"


def test_repair_plan_and_apply_are_manifest_bound() -> None:
    source_objects = [_envelope("object-1", "one"), _envelope("object-2", "two")]
    remote_manifest = _manifest("registry-b", source_objects)
    target_store = ImmutableObjectStore()
    target_store.put(source_objects[0])
    local_manifest = _manifest("registry-a", [source_objects[0]])
    repair = RegistryRepairEngine(target_store)

    plan = repair.build_plan(
        peer_id="registry-b",
        local_manifest=local_manifest,
        remote_manifest=remote_manifest,
    )
    result = repair.apply_batch(
        plan=plan,
        remote_manifest=remote_manifest,
        envelopes=[source_objects[1]],
    )

    assert plan.missing_object_ids == ["object-2"]
    assert result.accepted_object_ids == ["object-2"]
    assert result.completed is True
    assert target_store.has("object-2") is True


def test_repair_rejects_object_not_matching_remote_manifest() -> None:
    expected = _envelope("object-1", "expected")
    wrong = _envelope("object-1", "wrong")
    remote_manifest = _manifest("registry-b", [expected])
    target_store = ImmutableObjectStore()
    repair = RegistryRepairEngine(target_store)
    plan = repair.build_plan(
        peer_id="registry-b",
        local_manifest=_manifest("registry-a", []),
        remote_manifest=remote_manifest,
    )

    result = repair.apply_batch(
        plan=plan,
        remote_manifest=remote_manifest,
        envelopes=[wrong],
    )

    assert result.accepted_object_ids == []
    assert result.rejected_reasons["object-1"] == "object_manifest_mismatch"
    assert target_store.has("object-1") is False


def test_manifest_rejects_changed_payload_free_hash_array() -> None:
    source = _envelope("object-1", "expected")
    manifest = _manifest("registry-b", [source])
    segment = manifest.segments[0].model_copy(
        update={"content_hashes": ["0" * 64]}
    )
    tampered = manifest.model_copy(update={"segments": [segment]})

    assert tampered.verify() is False


def test_replicator_inventory_catch_up_and_proof_roundtrip() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = _public_key(private_key)
    source_store = ImmutableObjectStore()
    source_store.put(_envelope("object-1", "one"))
    source = RegistryReplicator(
        node_id="registry-b",
        store=source_store,
        proof_signer=lambda payload: "ed25519:" + private_key.sign(payload).hex(),
    )
    target = RegistryReplicator(node_id="registry-a")
    target.register_peer_identity(peer_id="registry-b", public_key=public_key)

    inventory_request = target.build_inventory_request("registry-b")
    inventory_response = source.process_incoming_message(
        peer_id="registry-a",
        message=inventory_request,
    )
    object_request = target.process_incoming_message(
        peer_id="registry-b",
        message=inventory_response,
    )
    source_object_response = source.process_incoming_message(
        peer_id="registry-a",
        message=object_request,
    )
    target.process_incoming_message(
        peer_id="registry-b",
        message=source_object_response,
    )

    challenge = target.issue_proof_challenge(peer_id="registry-b")
    challenge_message = target.get_outbox()[-1]
    challenge_response = source.process_incoming_message(
        peer_id="registry-a",
        message=challenge_message,
    )
    result = target.process_incoming_message(
        peer_id="registry-b",
        message=challenge_response,
    )

    assert target.store.has("object-1") is True
    assert challenge.challenge_id == target.get_peer_state("registry-b").last_proof_challenge_id
    assert result is None
    assert target.get_peer_state("registry-b").last_proof_status == "verified"
