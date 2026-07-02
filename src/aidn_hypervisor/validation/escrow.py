from dataclasses import dataclass
from hashlib import sha256
import random
from uuid import uuid4

from aidn_hypervisor.validation.models import ValidationAuthorization


@dataclass(frozen=True)
class BondLockResult:
    escrow_reference: str
    amount_q: float


class LocalOperatorBondEscrowAdapter:
    adapter_name = "local_operator_bond"

    def lock_bond(
        self,
        owner_wallet: str,
        amount_q: float,
        purpose: dict,
    ) -> BondLockResult:
        del owner_wallet, purpose
        return BondLockResult(
            escrow_reference=f"lock-{uuid4().hex[:12]}",
            amount_q=amount_q,
        )

    def refund_bond(self, bond_id: str, amount_q: float) -> dict:
        return {"bond_id": bond_id, "refunded_q": amount_q}

    def forfeit_bond(self, bond_id: str, amount_q: float, beneficiary: str) -> dict:
        return {
            "bond_id": bond_id,
            "forfeited_q": amount_q,
            "beneficiary": beneficiary,
        }

    def close_bond(self, bond_id: str) -> dict:
        return {"bond_id": bond_id, "status": "closed"}


class LocalValidatorEscrowPoolAdapter:
    def expand_assignment_list(self, validator_entries: list) -> list[str]:
        expanded: list[str] = []
        for entry in validator_entries:
            expanded.extend([entry.validator_id] * entry.shares)
        return expanded

    def deterministic_shuffle(self, validator_ids: list[str], seed: str) -> list[str]:
        shuffled = list(validator_ids)
        rng = random.Random(seed)
        rng.shuffle(shuffled)
        return shuffled

    def issue_authorization(
        self,
        *,
        request_id: str,
        epoch_id: str,
        guarantee_q: float,
        issued_at: str,
    ) -> ValidationAuthorization:
        token = sha256(f"{epoch_id}:{request_id}:{guarantee_q}".encode("utf-8")).hexdigest()
        return ValidationAuthorization(
            authorization_id=f"auth-{uuid4().hex[:12]}",
            request_id=request_id,
            epoch_id=epoch_id,
            authorization_token=token,
            guarantee_q=guarantee_q,
            issued_at=issued_at,
            expires_at=issued_at,
            status="issued",
        )
