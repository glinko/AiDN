from typing import Literal

from pydantic import BaseModel, Field, model_validator


SessionStatus = Literal["queued", "active", "closed"]
DepositStatus = Literal["locked", "released"]


class EndpointSession(BaseModel):
    session_id: str
    endpoint_id: str
    client_wallet: str
    provider_wallet: str
    node_id: str
    status: SessionStatus
    created_at: str
    started_at: str | None = None
    last_activity_at: str | None = None
    expires_at: str
    idle_deadline_at: str
    deposit_locked_q: float = Field(gt=0.0)
    reserved_slot_index: int | None = Field(default=None, ge=0)
    queue_policy_snapshot: str
    session_policy_snapshot: dict = Field(default_factory=dict)
    close_reason: str | None = None


class LockedDeposit(BaseModel):
    deposit_id: str
    session_id: str
    wallet_id: str
    locked_q: float = Field(gt=0.0)
    consumed_q: float = Field(default=0.0, ge=0.0)
    refunded_q: float = Field(default=0.0, ge=0.0)
    status: DepositStatus = "locked"

    @model_validator(mode="after")
    def _validate_balances(self):
        if self.consumed_q > self.locked_q:
            raise ValueError("consumed_q cannot exceed locked_q")
        if self.refunded_q > self.locked_q:
            raise ValueError("refunded_q cannot exceed locked_q")
        if self.consumed_q + self.refunded_q > self.locked_q:
            raise ValueError("consumed_q plus refunded_q cannot exceed locked_q")
        return self


class SessionResult(BaseModel):
    session: EndpointSession
    deposit: LockedDeposit
