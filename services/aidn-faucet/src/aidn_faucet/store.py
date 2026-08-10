"""Durable, replay-safe local state for the external Faucet service."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class FaucetStore:
    """SQLite store for challenges, claims and policy state.

    The store never contains private key material. Pending claims retain the
    exact signed envelope so a timeout can be retried without changing the
    operation identity or sender sequence.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level="IMMEDIATE")
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS challenges (
                    challenge_id TEXT PRIMARY KEY,
                    wallet_id TEXT NOT NULL,
                    challenge TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS claims (
                    request_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL UNIQUE,
                    wallet_id TEXT NOT NULL,
                    quota_key TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    policy_state_key TEXT NOT NULL DEFAULT '',
                    amount_q_atoms INTEGER NOT NULL,
                    decision_json TEXT NOT NULL,
                    state_after_success_json TEXT NOT NULL,
                    envelope_json TEXT NOT NULL,
                    operation_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    detail TEXT,
                    created_at TEXT NOT NULL,
                    finalized_at TEXT
                );
                CREATE INDEX IF NOT EXISTS claims_quota_idx
                    ON claims(wallet_id, quota_key, status);
                CREATE TABLE IF NOT EXISTS policy_state (
                    policy_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS service_state (
                    state_key TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL
                );
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(claims)").fetchall()
            }
            if "policy_state_key" not in columns:
                connection.execute(
                    "ALTER TABLE claims ADD COLUMN policy_state_key TEXT NOT NULL DEFAULT ''"
                )

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def create_challenge(self, challenge: dict[str, str]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO challenges (challenge_id, wallet_id, challenge, issued_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    challenge["challenge_id"],
                    challenge["wallet_id"],
                    challenge["challenge"],
                    challenge["issued_at"],
                    challenge["expires_at"],
                ),
            )

    def get_challenge(self, challenge_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._decode(
                connection.execute(
                    "SELECT * FROM challenges WHERE challenge_id = ?",
                    (challenge_id,),
                ).fetchone()
            )

    def mark_challenge_used(self, challenge_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE challenges SET used = 1 WHERE challenge_id = ? AND used = 0",
                (challenge_id,),
            )
            return cursor.rowcount == 1

    def get_claim(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._decode(
                connection.execute(
                    "SELECT * FROM claims WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
            )

    def find_active_quota_claim(self, *, wallet_id: str, quota_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._decode(
                connection.execute(
                    """
                    SELECT * FROM claims
                    WHERE wallet_id = ? AND quota_key = ? AND status IN ('PENDING', 'REJECTED', 'FINALIZED')
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (wallet_id, quota_key),
                ).fetchone()
            )

    def find_pending_treasury_claim(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._decode(
                connection.execute(
                    """
                    SELECT * FROM claims
                    WHERE status IN ('PENDING', 'REJECTED')
                    ORDER BY created_at ASC LIMIT 1
                    """
                ).fetchone()
            )

    def create_pending_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO claims (
                    request_id, claim_id, wallet_id, quota_key, policy_id,
                    policy_version, policy_state_key, amount_q_atoms, decision_json,
                    state_after_success_json, envelope_json, operation_id,
                    status, detail, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', NULL, ?)
                """,
                (
                    claim["request_id"],
                    claim["claim_id"],
                    claim["wallet_id"],
                    claim["quota_key"],
                    claim["policy_id"],
                    claim["policy_version"],
                    claim.get("policy_state_key", claim["policy_id"]),
                    claim["amount_q_atoms"],
                    json.dumps(claim["decision"], sort_keys=True, separators=(",", ":")),
                    json.dumps(claim["state_after_success"], sort_keys=True, separators=(",", ":")),
                    json.dumps(claim["envelope"], sort_keys=True, separators=(",", ":")),
                    claim["operation_id"],
                    claim["created_at"],
                ),
            )
        result = self.get_claim(claim["request_id"])
        if result is None:
            raise RuntimeError("Faucet claim was not persisted")
        return result

    def mark_submission_unknown(self, *, request_id: str, detail: str) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE claims
                SET status = 'PENDING', detail = ?
                WHERE request_id = ? AND status IN ('PENDING', 'REJECTED')
                """,
                (detail, request_id),
            )
        result = self.get_claim(request_id)
        if result is None:
            raise RuntimeError("Faucet claim disappeared during submission")
        return result

    def mark_submission_rejected(self, *, request_id: str, detail: str) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE claims
                SET status = 'REJECTED', detail = ?
                WHERE request_id = ? AND status IN ('PENDING', 'REJECTED')
                """,
                (detail, request_id),
            )
        result = self.get_claim(request_id)
        if result is None:
            raise RuntimeError("Faucet claim disappeared during rejection recording")
        return result

    def finalize_claim(
        self,
        *,
        request_id: str,
        policy_id: str,
        state_after_success: dict[str, Any],
        finalized_at: str,
        detail: str | None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE claims
                SET status = 'FINALIZED', detail = ?, finalized_at = ?
                WHERE request_id = ? AND status IN ('PENDING', 'REJECTED')
                """,
                (detail, finalized_at, request_id),
            )
            connection.execute(
                """
                INSERT INTO policy_state (policy_id, state_json) VALUES (?, ?)
                ON CONFLICT(policy_id) DO UPDATE SET state_json = excluded.state_json
                """,
                (
                    policy_id,
                    json.dumps(state_after_success, sort_keys=True, separators=(",", ":")),
                ),
            )
        result = self.get_claim(request_id)
        if result is None or result["status"] != "FINALIZED":
            raise RuntimeError("Faucet claim finalization was not persisted")
        return result

    def get_policy_state(self, policy_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM policy_state WHERE policy_id = ?",
                (policy_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["state_json"]))

    def ensure_policy_state(self, *, policy_id: str, state: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO policy_state (policy_id, state_json) VALUES (?, ?)",
                (policy_id, json.dumps(state, sort_keys=True, separators=(",", ":"))),
            )
        result = self.get_policy_state(policy_id)
        if result is None:
            raise RuntimeError("Faucet policy state was not initialized")
        return result

    def get_service_state(self, state_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM service_state WHERE state_key = ?",
                (state_key,),
            ).fetchone()
        if row is None:
            return None
        value = json.loads(str(row["state_json"]))
        if not isinstance(value, dict):
            raise RuntimeError("Faucet service state is not an object")
        return value

    def ensure_service_state(self, *, state_key: str, state: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO service_state (state_key, state_json) VALUES (?, ?)",
                (state_key, json.dumps(state, sort_keys=True, separators=(",", ":"))),
            )
        result = self.get_service_state(state_key)
        if result is None:
            raise RuntimeError("Faucet service state was not initialized")
        return result

    def set_service_state(self, *, state_key: str, state: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO service_state (state_key, state_json) VALUES (?, ?)
                ON CONFLICT(state_key) DO UPDATE SET state_json = excluded.state_json
                """,
                (state_key, json.dumps(state, sort_keys=True, separators=(",", ":"))),
            )
        result = self.get_service_state(state_key)
        if result is None:
            raise RuntimeError("Faucet service state was not persisted")
        return result
