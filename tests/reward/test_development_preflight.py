from __future__ import annotations

import base64
import json

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.reward.development_distribution import canonical_hash
from aidn_hypervisor.reward.development_preflight import (
    build_development_reward_preflight,
)
from aidn_hypervisor.reward.development_preflight_quorum import (
    build_development_reward_preflight_quorum,
    collect_development_reward_preflight,
)


def _transition_payload(*, pool_id: str = "GENERAL_DEVELOPMENT", budget: int = 50_000) -> dict:
    return {
        "closing_epoch": 12,
        "opening_epoch": 13,
        "closing_state_root": "sha256:closing-state",
        "epoch_task_result_root": "sha256:epoch-tasks",
        "eligibility_snapshot_root": "sha256:eligibility",
        "reward_calculation_root": "sha256:reward-calculation",
        "next_protocol_parameters_hash": "sha256:next-parameters",
        "pool_budgets": {pool_id: budget},
        "pool_budget_references": {pool_id: "epoch:12:GENERAL_DEVELOPMENT"},
    }


def _transition_bytes(*, budget: int = 50_000) -> bytes:
    envelope = LedgerOperationEnvelope(
        operation_type="EPOCH_TRANSITION",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="protocol",
        initiator_id="epoch-engine",
        fee_class="protocol_sponsored",
        created_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-02T00:00:00Z",
        target_epoch="12",
        payload=_transition_payload(budget=budget),
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def _preflight_value(preflight: dict) -> str:
    return base64.b64encode(
        json.dumps(preflight, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def test_abci_exposes_finalized_reward_preflight_only() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
    )

    missing = app.query(path="development/reward-preflight/GENERAL_DEVELOPMENT")
    missing_value = build_development_reward_preflight(ledger).model_dump(mode="json")
    assert missing.value == base64.b64decode(_preflight_value(missing_value))
    assert json.loads(missing.value)["status"] == "UNAVAILABLE"

    assert app.finalize_block(block_height=1, block_hash=b"A" * 32, txs=[_transition_bytes()]).code == "ok"
    response = app.query(path="development/reward-preflight/GENERAL_DEVELOPMENT")
    value = json.loads(response.value)
    assert value["status"] == "READY"
    assert value["epoch"] == 12
    assert value["opening_epoch"] == 13
    assert value["pool_budget_q_atoms"] == 50_000
    assert value["source_epoch_transition_operation_id"]
    assert value["preflight_hash"].startswith("sha256:")


def test_zero_pool_budget_is_an_explicit_no_budget_gate() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
    )
    zero_budget_tx = _transition_bytes(budget=0)

    assert app.finalize_block(block_height=1, block_hash=b"A" * 32, txs=[zero_budget_tx]).code == "ok"
    value = build_development_reward_preflight(ledger)

    assert value.status == "NO_BUDGET"
    assert value.pool_budget_q_atoms == 0
    assert value.reason_code == "DEVELOPMENT_REWARD_POOL_BUDGET_ZERO"


def test_quorum_accepts_exact_same_preflight() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
    )
    app.finalize_block(block_height=1, block_hash=b"A" * 32, txs=[_transition_bytes()])
    preflight = build_development_reward_preflight(ledger).model_dump(mode="json")

    def fetcher(_url: str, path: str, _params: dict[str, str]) -> dict:
        if path == "/status":
            return {
                "result": {
                    "node_info": {"id": "node", "network": "chain-1"},
                    "sync_info": {"latest_block_height": "1", "catching_up": False},
                }
            }
        return {"result": {"response": {"code": 0, "value": _preflight_value(preflight)}}}

    report = collect_development_reward_preflight(
        rpc_urls=["http://127.0.0.1:26657", "http://127.0.0.1:26658", "http://127.0.0.1:26659"],
        quorum=3,
        fetcher=fetcher,
    )
    assert report["status"] == "READY"
    assert report["agreement_count"] == 3
    assert report["preflight"]["pool_budget_q_atoms"] == 50_000
    quorum = build_development_reward_preflight_quorum(report)
    assert quorum.verify_integrity()
    assert quorum.preflight.pool_budget_reference == "epoch:12:GENERAL_DEVELOPMENT"


def test_quorum_blocks_on_conflicting_pool_reference() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
    )
    app.finalize_block(block_height=1, block_hash=b"A" * 32, txs=[_transition_bytes()])
    first = build_development_reward_preflight(ledger).model_dump(mode="json")
    # The altered projection is intentionally not accepted as a valid typed
    # preflight; the quorum layer must surface the disagreement as blocked.
    raw_second = {**first, "pool_budget_reference": "epoch:12:other"}
    raw_second["preflight_hash"] = canonical_hash(
        {key: value for key, value in raw_second.items() if key != "preflight_hash"}
    )

    def fetcher(url: str, path: str, _params: dict[str, str]) -> dict:
        if path == "/status":
            return {
                "result": {
                    "node_info": {"id": url, "network": "chain-1"},
                    "sync_info": {"latest_block_height": "1", "catching_up": False},
                }
            }
        value = first if url.endswith("26657") else raw_second
        return {"result": {"response": {"code": 0, "value": _preflight_value(value)}}}

    report = collect_development_reward_preflight(
        rpc_urls=["http://127.0.0.1:26657", "http://127.0.0.1:26658", "http://127.0.0.1:26659"],
        quorum=3,
        fetcher=fetcher,
    )
    assert report["status"] == "BLOCKED"
    assert report["reason_code"] == "DEVELOPMENT_REWARD_PREFLIGHT_QUORUM_UNAVAILABLE"
