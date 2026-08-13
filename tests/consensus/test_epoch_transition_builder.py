from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.epoch_transition import (
    build_signed_epoch_transition,
    build_signed_epoch_transition_from_quorum,
    build_unsigned_epoch_transition,
    build_unsigned_epoch_transition_from_quorum,
    combine_epoch_transition_signatures,
    load_protocol_authority_private_key,
    sign_epoch_transition_signature,
)
from aidn_hypervisor.consensus.epoch_transition_inputs import (
    build_epoch_transition_input_report,
)
from aidn_hypervisor.consensus.epoch_transition_quorum import (
    collect_epoch_transition_quorum,
)
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy
from aidn_hypervisor.endpoint_publications.signing import public_key_for_private_key

PRIVATE_KEYS = tuple("ed25519:" + value * 32 for value in ("11", "22", "33"))


def _policy() -> ProtocolAuthorityPolicy:
    return ProtocolAuthorityPolicy(
        threshold=2,
        authorities=tuple(
            (f"authority-{index}", public_key_for_private_key(key))
            for index, key in enumerate(PRIVATE_KEYS, start=1)
        ),
    )


def _payload() -> dict[str, object]:
    return {
        "closing_epoch": 20,
        "opening_epoch": 21,
        "closing_state_root": "sha256:closing-state",
        "epoch_task_result_root": "sha256:epoch-tasks",
        "eligibility_snapshot_root": "sha256:eligibility",
        "reward_calculation_root": "sha256:reward-calculation",
        "next_protocol_parameters_hash": "sha256:next-parameters",
        "pool_budgets": {"GENERAL_DEVELOPMENT": 250_000},
        "pool_budget_references": {
            "GENERAL_DEVELOPMENT": "epoch:20:GENERAL_DEVELOPMENT"
        },
    }


def _keys(*indexes: int) -> dict[str, Ed25519PrivateKey]:
    return {
        f"authority-{index + 1}": Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(PRIVATE_KEYS[index].removeprefix("ed25519:"))
        )
        for index in indexes
    }


def _ready_quorum() -> dict[str, object]:
    rpc_urls = ("http://validator-1:26657", "http://validator-2:26657")
    manifest_operation_id = "manifest-operation-1"
    manifest_hash = "sha256:manifest"
    schedule_operation_id = "schedule-operation-1"
    schedule_record_digest = "sha256:schedule-record"
    report = build_epoch_transition_input_report(
        closing_epoch=20,
        opening_epoch=21,
        closing_height=100,
        closing_block_hash="sha256:block",
        closing_state_root="sha256:state",
        source_app_hash="sha256:app",
        epoch_task_result_root="sha256:tasks",
        eligibility_snapshot_root="sha256:eligibility",
        reward_calculation_root="sha256:rewards",
        next_protocol_parameters_hash="sha256:params",
        pool_budgets={"GENERAL_DEVELOPMENT": 250_000},
        pool_budget_references={"GENERAL_DEVELOPMENT": "epoch:20:GENERAL_DEVELOPMENT"},
        epoch_schedule_version="aidn.epoch-schedule.v1",
        epoch_schedule_hash="sha256:schedule",
        epoch_schedule_commit_operation_id=schedule_operation_id,
        epoch_schedule_commit_sequence_id=23,
        epoch_schedule_commit_record_digest=schedule_record_digest,
        canonical_block_time="2030-01-01T00:01:00Z",
        scheduled_end_time="2030-01-01T00:01:00Z",
        epoch_boundary_reached=True,
        epoch_result_manifest_hash=manifest_hash,
        epoch_result_manifest_operation_id=manifest_operation_id,
    ).model_dump(mode="json")

    def fetcher(url: str, path: str, params: dict[str, str]) -> dict[str, object]:
        if path == "/status":
            return {
                "result": {
                    "node_info": {"id": url, "network": "chain-1"},
                    "sync_info": {"latest_block_height": "120", "catching_up": False},
                }
            }
        query_path = json.loads(params["path"])
        if query_path == "epoch/transition-inputs":
            value = base64.b64encode(
                json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).decode("ascii")
        elif query_path == f"operation/finalized/{manifest_operation_id}":
            value = base64.b64encode(
                json.dumps(
                    {
                        "operation_id": manifest_operation_id,
                        "operation_type": "EPOCH_RESULT_MANIFEST_COMMIT",
                        "sequence_id": 7,
                        "record_digest": "sha256:record",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).decode("ascii")
        elif query_path == f"operation/finalized/{schedule_operation_id}":
            value = base64.b64encode(
                json.dumps(
                    {
                        "operation_id": schedule_operation_id,
                        "operation_type": "EPOCH_SCHEDULE_COMMIT",
                        "sequence_id": 23,
                        "record_digest": schedule_record_digest,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).decode("ascii")
        elif query_path == "epoch/schedule":
            value = base64.b64encode(
                json.dumps(
                    {
                        "operation_id": schedule_operation_id,
                        "operation_type": "EPOCH_SCHEDULE_COMMIT",
                        "sequence_id": 23,
                        "record_digest": schedule_record_digest,
                        "epoch_schedule": {
                            "schema_version": "aidn.epoch-schedule.v1",
                            "schedule_hash": "sha256:schedule",
                        },
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).decode("ascii")
        elif query_path == "epoch/result-manifest/20":
            value = base64.b64encode(
                json.dumps(
                    {
                        "operation_id": manifest_operation_id,
                        "operation_type": "EPOCH_RESULT_MANIFEST_COMMIT",
                        "sequence_id": 7,
                        "record_digest": "sha256:record",
                        "manifest_hash": manifest_hash,
                        "epoch_number": 20,
                        "closing_height": 100,
                        "closing_time": "2030-01-01T00:01:00Z",
                        "closing_block_hash": "sha256:block",
                        "closing_state_root": "sha256:state",
                        "source_app_hash": "sha256:app",
                        "epoch_schedule_version": "aidn.epoch-schedule.v1",
                        "epoch_schedule_hash": "sha256:schedule",
                        "scheduled_end_time": "2030-01-01T00:01:00Z",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).decode("ascii")
        else:
            raise AssertionError(f"unexpected query path: {query_path}")
        return {"result": {"response": {"code": 0, "height": "120", "value": value}}}

    return collect_epoch_transition_quorum(
        rpc_urls=rpc_urls,
        quorum=2,
        fetcher=fetcher,
    )


def test_builder_adds_policy_hash_and_validates_quorum() -> None:
    policy = _policy()
    envelope = build_signed_epoch_transition(
        policy=policy,
        payload=_payload(),
        signers=_keys(0, 1),
        created_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-02T00:00:00Z",
    )

    assert envelope.payload["protocol_authority_policy_hash"] == policy.policy_hash
    assert len(envelope.signatures) == 2
    policy.verify_epoch_transition(envelope)


def test_builder_rejects_insufficient_quorum() -> None:
    with pytest.raises(ValueError, match="signer quorum is not met"):
        build_signed_epoch_transition(
            policy=_policy(),
            payload=_payload(),
            signers=_keys(0),
            created_at="2030-01-01T00:00:00Z",
        )


def test_builder_rejects_key_not_bound_to_declared_authority() -> None:
    policy = _policy()
    wrong_key = {"authority-1": _keys(1)["authority-2"]}
    wrong_key["authority-2"] = _keys(0)["authority-1"]

    with pytest.raises(ValueError, match="private key does not match"):
        build_signed_epoch_transition(
            policy=policy,
            payload=_payload(),
            signers=wrong_key,
            created_at="2030-01-01T00:00:00Z",
        )


def test_builder_rejects_invalid_ledger_payload() -> None:
    payload = _payload()
    payload["opening_epoch"] = 23
    with pytest.raises(ValueError, match="opening epoch must immediately follow"):
        build_signed_epoch_transition(
            policy=_policy(),
            payload=payload,
            signers=_keys(0, 1),
            created_at="2030-01-01T00:00:00Z",
        )


def test_private_key_loader_accepts_seed_file_without_exporting_key(tmp_path: Path) -> None:
    path = tmp_path / "authority-1.seed"
    path.write_text(PRIVATE_KEYS[0].removeprefix("ed25519:"), encoding="ascii")
    key = load_protocol_authority_private_key(path)
    assert public_key_for_private_key(PRIVATE_KEYS[0]) == (
        "ed25519:" + key.public_key().public_bytes_raw().hex()
    )


def test_output_shape_is_json_serializable() -> None:
    envelope = build_signed_epoch_transition(
        policy=_policy(),
        payload=_payload(),
        signers=_keys(0, 1),
        created_at="2030-01-01T00:00:00Z",
    )
    assert json.loads(json.dumps(envelope.model_dump(mode="json")))['operation_type'] == (
        "EPOCH_TRANSITION"
    )


def test_independent_signatures_can_be_combined_without_private_keys() -> None:
    policy = _policy()
    unsigned = build_unsigned_epoch_transition(
        policy=policy,
        payload=_payload(),
        created_at="2030-01-01T00:00:00Z",
    )
    signatures = {
        authority_id: sign_epoch_transition_signature(
            unsigned,
            policy=policy,
            authority_id=authority_id,
            private_key=_keys(index)[authority_id],
        )
        for index, authority_id in enumerate(("authority-1", "authority-2"))
    }
    combined = combine_epoch_transition_signatures(
        unsigned,
        policy=policy,
        signatures=signatures,
    )
    assert combined.operation_id == unsigned.operation_id
    assert len(combined.signatures) == 2
    policy.verify_epoch_transition(combined)


def test_combiner_rejects_duplicate_authority_artifacts() -> None:
    policy = _policy()
    unsigned = build_unsigned_epoch_transition(
        policy=policy,
        payload=_payload(),
        created_at="2030-01-01T00:00:00Z",
    )
    signature = sign_epoch_transition_signature(
        unsigned,
        policy=policy,
        authority_id="authority-1",
        private_key=_keys(0)["authority-1"],
    )
    with pytest.raises(ValueError, match="SIGNATURE_REQUIRED"):
        combine_epoch_transition_signatures(
            unsigned,
            policy=policy,
            signatures={"authority-1": signature},
        )


def test_signer_and_combiner_reject_already_signed_input() -> None:
    policy = _policy()
    signed = build_signed_epoch_transition(
        policy=policy,
        payload=_payload(),
        signers=_keys(0, 1),
        created_at="2030-01-01T00:00:00Z",
    )
    with pytest.raises(ValueError, match="must be unsigned"):
        sign_epoch_transition_signature(
            signed,
            policy=policy,
            authority_id="authority-3",
            private_key=_keys(2)["authority-3"],
        )
    with pytest.raises(ValueError, match="must be unsigned"):
        combine_epoch_transition_signatures(
            signed,
            policy=policy,
            signatures={"authority-1": signed.signatures[0]},
        )


def test_signer_rejects_payload_bound_to_another_policy() -> None:
    policy = _policy()
    other_policy = ProtocolAuthorityPolicy(
        threshold=1,
        authorities=(
            ("authority-1", public_key_for_private_key(PRIVATE_KEYS[0])),
            ("authority-2", public_key_for_private_key(PRIVATE_KEYS[1])),
            ("authority-3", public_key_for_private_key(PRIVATE_KEYS[2])),
        ),
    )
    unsigned = build_unsigned_epoch_transition(
        policy=policy,
        payload=_payload(),
        created_at="2030-01-01T00:00:00Z",
    )
    tampered = unsigned.model_copy(
        update={
            "payload": {
                **unsigned.payload,
                "protocol_authority_policy_hash": other_policy.policy_hash,
            }
        }
    )
    with pytest.raises(ValueError, match="policy hash does not match"):
        sign_epoch_transition_signature(
            tampered,
            policy=policy,
            authority_id="authority-1",
            private_key=_keys(0)["authority-1"],
        )


def test_quorum_builder_derives_and_signs_exact_report_payload() -> None:
    policy = _policy()
    quorum = _ready_quorum()
    unsigned = build_unsigned_epoch_transition_from_quorum(
        policy=policy,
        quorum_report=quorum,
        created_at="2030-01-01T00:02:00Z",
        expected_chain_id="chain-1",
    )

    assert unsigned.payload["epoch_transition_quorum_hash"] == quorum["quorum_hash"]
    assert unsigned.payload["epoch_result_manifest_sequence_id"] == 7
    assert unsigned.evidence_references == sorted(
        {
            "manifest-operation-1",
            "schedule-operation-1",
            "sha256:schedule-record",
            quorum["quorum_hash"],
        }
    )

    signed = build_signed_epoch_transition_from_quorum(
        policy=policy,
        quorum_report=quorum,
        signers=_keys(0, 1),
        created_at="2030-01-01T00:02:00Z",
        expected_chain_id="chain-1",
    )
    policy.verify_epoch_transition(signed)


def test_quorum_bound_signing_requires_the_same_report() -> None:
    policy = _policy()
    quorum = _ready_quorum()
    unsigned = build_unsigned_epoch_transition_from_quorum(
        policy=policy,
        quorum_report=quorum,
        created_at="2030-01-01T00:02:00Z",
    )

    with pytest.raises(ValueError, match="quorum report is required"):
        sign_epoch_transition_signature(
            unsigned,
            policy=policy,
            authority_id="authority-1",
            private_key=_keys(0)["authority-1"],
        )


def test_manual_partial_quorum_metadata_is_rejected() -> None:
    payload = _payload()
    payload["epoch_transition_quorum_hash"] = "sha256:unverified"
    with pytest.raises(ValueError, match="quorum evidence is incomplete"):
        build_unsigned_epoch_transition(
            policy=_policy(),
            payload=payload,
            created_at="2030-01-01T00:02:00Z",
        )


def test_blocked_quorum_cannot_build_transition() -> None:
    policy = _policy()
    from aidn_hypervisor.consensus.epoch_transition_quorum import (
        EpochTransitionQuorumReport,
        epoch_transition_quorum_hash,
    )

    ready = EpochTransitionQuorumReport.model_validate(_ready_quorum())
    blocked_model = ready.model_copy(
        update={
            "status": "BLOCKED",
            "reason_code": "EPOCH_RESULT_MANIFEST_FINALITY_QUORUM_UNAVAILABLE",
            "manifest_finality_count": 1,
        }
    )
    blocked_model = blocked_model.model_copy(
        update={"quorum_hash": epoch_transition_quorum_hash(blocked_model)}
    )
    with pytest.raises(ValueError, match="not READY"):
        build_unsigned_epoch_transition_from_quorum(
            policy=policy,
            quorum_report=blocked_model,
            created_at="2030-01-01T00:02:00Z",
        )
