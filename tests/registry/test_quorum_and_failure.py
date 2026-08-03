from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.registry import (
    ImmutableObjectStore,
    NonResponseConfirmationEngine,
    RegistryChallenge,
    RegistryInventoryManifest,
    RegistryObjectEnvelope,
    RegistryRepairEngine,
    RegistryReplicator,
    verify_segment_merkle_proof,
)


def _public_key(private_key: Ed25519PrivateKey) -> str:
    return "ed25519:" + private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


def _envelope(object_id: str, value: str) -> RegistryObjectEnvelope:
    return RegistryObjectEnvelope.create(
        object_id=object_id,
        object_type="advertisement",
        payload={"value": value},
        created_epoch=1,
    )


def _manifest(registry_id: str, objects: list[RegistryObjectEnvelope]) -> RegistryInventoryManifest:
    return RegistryInventoryManifest.create(
        registry_service_id=registry_id,
        generated_at_epoch=1,
        objects=objects,
        retention_policy_hash="retention-v1",
    )


def test_segment_merkle_inclusion_proof_rejects_path_tampering() -> None:
    objects = [_envelope(f"object-{index}", str(index)) for index in range(5)]
    manifest = _manifest("registry-a", objects)
    proof = manifest.segments[0].build_merkle_proof("object-3")

    assert verify_segment_merkle_proof(proof) is True
    tampered = proof.model_copy(
        update={
            "siblings": [
                proof.siblings[0].model_copy(update={"hash": "0" * 64}),
                *proof.siblings[1:],
            ]
        }
    )
    assert verify_segment_merkle_proof(tampered) is False
    assert manifest.segments[0].content_merkle_root == proof.root_hash


def test_multi_peer_repair_requires_independent_quorum_and_preserves_conflict() -> None:
    expected = _envelope("object-1", "expected")
    divergent = _envelope("object-1", "divergent")
    local_manifest = _manifest("registry-local", [])
    peer_a = _manifest("peer-a", [expected])
    peer_b = _manifest("peer-b", [expected])
    peer_c = _manifest("peer-c", [divergent])
    repair = RegistryRepairEngine(ImmutableObjectStore())

    plan = repair.build_multi_peer_plan(
        local_manifest=local_manifest,
        peer_manifests={"peer-a": peer_a, "peer-b": peer_b, "peer-c": peer_c},
        minimum_independent_sources=2,
        known_control_groups={"peer-a": "group-a", "peer-b": "group-b", "peer-c": "group-c"},
    )

    assert plan.target_object_ids == ["object-1"]
    assert plan.source_by_object["object-1"] == "peer-a"
    assert plan.conflicting_object_ids == ["object-1"]
    assert plan.conflict_evidence["object-1"]
    assert plan.evidence_root.startswith("sha256:")

    no_quorum = repair.build_multi_peer_plan(
        local_manifest=local_manifest,
        peer_manifests={"peer-a": peer_a},
        minimum_independent_sources=2,
    )
    assert no_quorum.target_object_ids == []
    assert no_quorum.quorum_missing_object_ids == ["object-1"]


def test_replicator_carries_multi_peer_plan_into_object_response() -> None:
    source_object = _envelope("object-2", "shared")
    source_a = RegistryReplicator(node_id="peer-a")
    source_b = RegistryReplicator(node_id="peer-b")
    target = RegistryReplicator(node_id="registry-target")
    source_a.store.put(source_object)
    source_b.store.put(source_object)

    for peer_id, source in (("peer-a", source_a), ("peer-b", source_b)):
        request = target.build_inventory_request(peer_id)
        response = source.process_incoming_message(
            peer_id="registry-target",
            message=request,
        )
        assert response is not None
        target.process_incoming_message(
            peer_id=peer_id,
            message=response,
        )

    plan = target.build_multi_peer_repair_plan(
        minimum_independent_sources=2,
        known_control_groups={"peer-a": "group-a", "peer-b": "group-b"},
    )
    messages = target.request_multi_peer_repair(plan=plan)
    assert len(messages) == 1
    response = source_a.process_incoming_message(
        peer_id="registry-target",
        message=messages[0],
    )
    assert response is not None
    target.process_incoming_message(peer_id="peer-a", message=response)

    assert target.store.get("object-2") == source_object


def test_non_response_report_requires_signed_independent_observations() -> None:
    challenger_key = Ed25519PrivateKey.generate()
    observer_key = Ed25519PrivateKey.generate()
    finalizer_key = Ed25519PrivateKey.generate()
    challenge = RegistryChallenge(
        challenge_id="challenge-1",
        target_registry_id="registry-target",
        target_inventory_root="root-1",
        object_selector="selector-1",
        issued_at=100.0,
        response_deadline=200.0,
        challenger_id="registry-challenger",
        challenge_nonce="nonce-1",
    )
    challenger_request = NonResponseConfirmationEngine(
        registry_id="registry-challenger",
        signer=lambda payload: "ed25519:" + challenger_key.sign(payload).hex(),
        clock=lambda: 100.0,
    )
    challenger = NonResponseConfirmationEngine(
        registry_id="registry-challenger",
        signer=lambda payload: "ed25519:" + challenger_key.sign(payload).hex(),
        clock=lambda: 201.0,
    )
    observer = NonResponseConfirmationEngine(
        registry_id="registry-observer",
        signer=lambda payload: "ed25519:" + observer_key.sign(payload).hex(),
        clock=lambda: 201.0,
    )
    finalizer = NonResponseConfirmationEngine(
        registry_id="registry-finalizer",
        signer=lambda payload: "ed25519:" + finalizer_key.sign(payload).hex(),
        clock=lambda: 202.0,
    )

    request = challenger_request.create_request_evidence(challenge=challenge)
    first = challenger.create_observation(
        request_evidence=request,
        challenge=challenge,
        observer_role="challenger",
    )
    second = observer.create_observation(
        request_evidence=request,
        challenge=challenge,
        observer_role="independent_verifier",
    )
    report = finalizer.build_failure_report(
        challenge=challenge,
        request_evidence=request,
        observations=[first, second],
    )
    result = finalizer.verify_failure_report(
        challenge=challenge,
        report=report,
        verifier_public_keys={
            "registry-challenger": _public_key(challenger_key),
            "registry-observer": _public_key(observer_key),
            "registry-finalizer": _public_key(finalizer_key),
        },
    )

    assert result.valid is True
    assert result.result == "confirmed_non_response"


def test_non_response_report_is_not_created_for_response_or_network_outage() -> None:
    challenger_key = Ed25519PrivateKey.generate()
    observer_key = Ed25519PrivateKey.generate()
    challenge = RegistryChallenge(
        challenge_id="challenge-2",
        target_registry_id="registry-target",
        target_inventory_root="root-2",
        object_selector="selector-2",
        issued_at=100.0,
        response_deadline=200.0,
        challenger_id="registry-challenger",
        challenge_nonce="nonce-2",
    )
    request_engine = NonResponseConfirmationEngine(
        registry_id="registry-challenger",
        signer=lambda payload: "ed25519:" + challenger_key.sign(payload).hex(),
        clock=lambda: 100.0,
    )
    engine = NonResponseConfirmationEngine(
        registry_id="registry-challenger",
        signer=lambda payload: "ed25519:" + challenger_key.sign(payload).hex(),
        clock=lambda: 201.0,
    )
    observer = NonResponseConfirmationEngine(
        registry_id="registry-observer",
        signer=lambda payload: "ed25519:" + observer_key.sign(payload).hex(),
        clock=lambda: 201.0,
    )
    request = request_engine.create_request_evidence(challenge=challenge)
    response_observation = engine.create_observation(
        request_evidence=request,
        challenge=challenge,
        response_received=True,
        response_hash="response-hash",
        observer_role="challenger",
    )
    second = observer.create_observation(
        request_evidence=request,
        challenge=challenge,
        observer_role="independent_verifier",
    )
    try:
        engine.build_failure_report(
            challenge=challenge,
            request_evidence=request,
            observations=[response_observation, second],
        )
    except ValueError as error:
        assert "response_received" in str(error)
    else:
        raise AssertionError("a received response must not produce a failure report")

    outage = second.model_copy(update={"network_condition": "outage"})
    try:
        engine.build_failure_report(
            challenge=challenge,
            request_evidence=request,
            observations=[
                response_observation.model_copy(update={"response_received": False, "response_hash": ""}),
                outage,
            ],
        )
    except ValueError as error:
        assert "network_condition_unreliable" in str(error)
    else:
        raise AssertionError("a network outage must make non-response inconclusive")
