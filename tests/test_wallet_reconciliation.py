from types import SimpleNamespace

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.wallet_reconciliation import reconcile_pending_wallet_transfers


def _envelope() -> LedgerOperationEnvelope:
    return LedgerOperationEnvelope(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        sender_wallet="wallet-sender",
        sender_sequence=4,
        fee_payer="wallet-sender",
        payload={"recipient_wallet": "wallet-recipient", "amount": 1_000_000},
        created_at="2026-08-12T20:11:16Z",
        signatures=["ed25519:test"],
    )


class _Ledger:
    def __init__(self, finalized: bool = False) -> None:
        self.finalized = finalized
        self.applied: list[str] = []
        self.projected: list[str] = []

    def get_operation(self, operation_id: str):
        return {"operation_id": operation_id} if self.finalized else None

    def apply_consensus_wallet_transfer(self, envelope):
        self.applied.append(envelope.operation_id)
        return {"operation_id": envelope.operation_id, "status": "applied"}

    def record_consensus_wallet_transfer_projection(self, envelope):
        self.projected.append(envelope.operation_id)
        return {"operation_id": envelope.operation_id, "status": "projected"}


class _Consensus:
    is_enabled = True
    is_validator = False

    def __init__(self) -> None:
        self.submissions: dict[str, SimpleNamespace] = {}
        self.restored: list[str] = []
        self.rebroadcast: list[str] = []

    def restore_submission(self, envelope):
        self.restored.append(envelope.operation_id)
        self.submissions.setdefault(
            envelope.operation_id,
            SimpleNamespace(status=SimpleNamespace(value="pending"), error=None),
        )
        return self.submissions[envelope.operation_id]

    def get_submission(self, operation_id: str):
        return self.submissions.get(operation_id)

    def submit_operation(self, envelope, *, retry_existing: bool):
        assert retry_existing is True
        self.rebroadcast.append(envelope.operation_id)
        self.submissions[envelope.operation_id].status.value = "admitted"
        return self.submissions[envelope.operation_id]


class _Service:
    def __init__(self, *, finalized: bool = False) -> None:
        self.consensus_service = _Consensus()
        self.ledger_operation_service = _Ledger(finalized=finalized)
        self.pending = [_envelope()]
        self.discarded: list[str] = []
        self.persisted = 0

    def list_pending_consensus_envelopes(self):
        return list(self.pending)

    def ledger_operation_finality(self, operation_id: str):
        if self.ledger_operation_service.finalized:
            return {
                "status": "consensus_finalized",
                "consensus_finalized": True,
                "finality_evidence": {"operation_id": operation_id},
            }
        submission = self.consensus_service.get_submission(operation_id)
        return {
            "status": submission.status.value if submission else "not_submitted",
            "consensus_finalized": False,
            "finality_evidence": None,
        }

    def discard_pending_consensus_envelopes(self, operation_id: str):
        self.discarded.append(operation_id)
        self.pending = [item for item in self.pending if item.operation_id != operation_id]

    def discard_pending_consensus_operations(self, operation_id: str):
        self.discarded.append(operation_id)

    def _persist_state(self):
        self.persisted += 1


def test_restart_recovery_rebroadcasts_exact_pending_transfer_once() -> None:
    service = _Service()
    envelope = service.pending[0]

    reports = reconcile_pending_wallet_transfers(service)

    assert reports[0]["status"] == "admitted"
    assert service.consensus_service.restored == [envelope.operation_id]
    assert service.consensus_service.rebroadcast == [envelope.operation_id]
    assert service.pending[0].operation_id == envelope.operation_id
    assert service.ledger_operation_service.applied == []

    second_reports = reconcile_pending_wallet_transfers(service)

    assert second_reports[0]["status"] == "admitted"
    assert service.consensus_service.rebroadcast == [envelope.operation_id]


def test_finalized_transfer_is_materialized_and_envelope_is_removed() -> None:
    service = _Service(finalized=True)
    envelope = service.pending[0]
    service.consensus_service.is_validator = True

    reports = reconcile_pending_wallet_transfers(service)

    assert reports[0]["status"] == "local_projection_finalized"
    assert service.ledger_operation_service.applied == []
    assert service.discarded == [envelope.operation_id, envelope.operation_id]
    assert service.pending == []


def test_consensus_finality_materializes_transfer() -> None:
    service = _Service()
    envelope = service.pending[0]
    service.consensus_service.is_validator = True
    original_finality = service.ledger_operation_finality

    def finalized_after_submission(operation_id: str):
        if service.consensus_service.get_submission(operation_id).status.value == "admitted":
            service.ledger_operation_service.finalized = True
        return original_finality(operation_id)

    service.ledger_operation_finality = finalized_after_submission
    reports = reconcile_pending_wallet_transfers(service)

    assert reports[0]["status"] == "consensus_finalized"
    assert service.ledger_operation_service.applied == [envelope.operation_id]
    assert service.ledger_operation_service.projected == []
    assert service.pending == []
    assert service.persisted == 1


def test_remote_projection_does_not_require_local_genesis_balance() -> None:
    ledger = LedgerOperationService()
    envelope = _envelope()

    record = ledger.record_consensus_wallet_transfer_projection(envelope)

    assert record["operation_id"] == envelope.operation_id
    assert ledger.wallet_q_atom_balance("wallet-sender") == 0
    assert ledger.wallet_next_sequence("wallet-sender") == 5
