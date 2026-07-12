import hashlib
import json
from datetime import datetime, timezone

from aidn_hypervisor.ledger.models import LedgerOperationRecord, LedgerOperationResult


def _canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash_dict(value: dict) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class LedgerOperationService:
    def __init__(self, *, protocol_version: str = "0.1") -> None:
        self.protocol_version = protocol_version
        self._operations: list[dict] = []
        self._operation_ids: set[str] = set()
        self._wallet_next_sequences: dict[str, int] = {}
        self._next_sequence_id = 1

    def list_operations(self, *, limit: int | None = None) -> list[dict]:
        events = list(self._operations)
        if limit is None or limit >= len(events):
            return events
        return events[-limit:]

    def export_operations(
        self,
        *,
        after_operation_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        items = list(self._operations)
        if after_operation_id is not None:
            found = next(
                (index for index, item in enumerate(items) if item["operation_id"] == after_operation_id),
                None,
            )
            if found is None:
                return {
                    "items": [],
                    "count": 0,
                    "cursor_status": "stale",
                    "watermark_sequence": items[-1]["sequence_id"] if items else 0,
                }
            items = items[found + 1 :]
        elif after_sequence is not None:
            items = [item for item in items if int(item["sequence_id"]) > int(after_sequence)]
        limit = max(0, int(limit))
        page = items[:limit]
        return {
            "items": page,
            "count": len(page),
            "cursor_status": "ok",
            "retained_from_sequence": page[0]["sequence_id"] if page else None,
            "retained_through_sequence": page[-1]["sequence_id"] if page else None,
            "watermark_sequence": self._operations[-1]["sequence_id"] if self._operations else 0,
        }

    def wallet_next_sequence(self, wallet_id: str) -> int:
        return int(self._wallet_next_sequences.get(wallet_id, 1))

    def record_operation(
        self,
        *,
        operation_type: str,
        origin_type: str,
        fee_class: str,
        initiator_id: str | None = None,
        sender_wallet: str | None = None,
        fee_payer: str | None = None,
        payload: dict | None = None,
        created_at: str | None = None,
        expires_at: str | None = None,
        target_epoch: str | None = None,
        evidence_references: list[str] | None = None,
        signatures: list[str] | None = None,
        emitted_events: list[str] | None = None,
        expected_sequence: int | None = None,
        operation_version: str = "0.1",
    ) -> dict:
        now = created_at or datetime.now(timezone.utc).isoformat()
        sender_sequence: int | None = None
        next_wallet_sequence: int | None = None
        if origin_type == "wallet":
            if sender_wallet is None:
                raise ValueError("wallet operations require sender_wallet")
            next_wallet_sequence = self.wallet_next_sequence(sender_wallet)
            sender_sequence = (
                int(expected_sequence)
                if expected_sequence is not None
                else next_wallet_sequence
            )
            if sender_sequence != next_wallet_sequence:
                raise ValueError(
                    f"invalid wallet sequence for {sender_wallet}: expected {next_wallet_sequence}, got {sender_sequence}"
                )

        unsigned = {
            "operation_type": operation_type,
            "operation_version": operation_version,
            "protocol_version": self.protocol_version,
            "origin_type": origin_type,
            "initiator_id": initiator_id,
            "sender_wallet": sender_wallet,
            "sender_sequence": sender_sequence,
            "fee_class": fee_class,
            "fee_payer": fee_payer,
            "created_at": now,
            "expires_at": expires_at,
            "target_epoch": target_epoch,
            "payload": dict(payload or {}),
            "evidence_references": list(evidence_references or []),
            "signatures": list(signatures or []),
        }
        operation_id = _hash_dict(unsigned)
        if operation_id in self._operation_ids:
            raise ValueError(f"duplicate operation id: {operation_id}")
        result = LedgerOperationResult(
            status="applied",
            state_changes_root=_hash_dict(
                {
                    "operation_id": operation_id,
                    "operation_type": operation_type,
                    "payload": unsigned["payload"],
                }
            ),
            emitted_events=list(emitted_events or []),
        )
        wallet_next_sequence_value = None
        if sender_wallet is not None and sender_sequence is not None:
            wallet_next_sequence_value = int(sender_sequence) + 1
        record = LedgerOperationRecord(
            sequence_id=self._next_sequence_id,
            operation_id=operation_id,
            operation_type=operation_type,
            operation_version=operation_version,
            protocol_version=self.protocol_version,
            origin_type=origin_type,
            initiator_id=initiator_id,
            sender_wallet=sender_wallet,
            sender_sequence=sender_sequence,
            fee_class=fee_class,
            fee_payer=fee_payer,
            created_at=now,
            expires_at=expires_at,
            target_epoch=target_epoch,
            payload=unsigned["payload"],
            evidence_references=unsigned["evidence_references"],
            signatures=unsigned["signatures"],
            result=result,
            wallet_next_sequence=wallet_next_sequence_value,
        ).model_dump(mode="json")
        self._operations.append(record)
        self._operation_ids.add(operation_id)
        self._next_sequence_id += 1
        if sender_wallet is not None and wallet_next_sequence_value is not None:
            self._wallet_next_sequences[sender_wallet] = wallet_next_sequence_value
        return record

    def snapshot_operations(self) -> list[dict]:
        return list(self._operations)

    def snapshot_wallet_sequences(self) -> dict[str, int]:
        return dict(self._wallet_next_sequences)

    def restore(
        self,
        *,
        operations: list[dict],
        wallet_sequences: dict[str, int],
    ) -> None:
        self._operations = [LedgerOperationRecord(**item).model_dump(mode="json") for item in operations]
        self._operation_ids = {item["operation_id"] for item in self._operations}
        self._wallet_next_sequences = {str(key): int(value) for key, value in wallet_sequences.items()}
        self._next_sequence_id = (
            max((int(item["sequence_id"]) for item in self._operations), default=0) + 1
        )
