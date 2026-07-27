"""RFC-0047 §5 — ABCI Result/Tag/Info models."""

from typing import Literal

from pydantic import BaseModel, Field

ABCICode = Literal[
    "ok",
    "rejected",
    "invalid",
    "duplicate",
    "expired",
    "sequence",
    "internal",
]


class ABCITag(BaseModel):
    key: str
    value: str

    model_config = {"frozen": True}


class ABCIResult(BaseModel):
    """Result of processing a single transaction or block."""
    code: ABCICode = "ok"
    data: bytes = b""
    log: str = ""
    info: str = ""
    codespace: str = ""
    gas_used: int = 0
    gas_wanted: int = 0
    tags: list[ABCITag] = Field(default_factory=list)

    model_config = {"frozen": True}


class ABCIInfoResponse(BaseModel):
    """Response to info() ABCI call."""
    data: str
    version: str
    app_version: int
    last_block_height: int
    last_block_app_hash: bytes = b""

    model_config = {"frozen": True}


class ABCICommitResponse(BaseModel):
    """Response to commit() ABCI call."""
    data: bytes = b""
    version: str = ""

    model_config = {"frozen": True}


class ABCIQueryResponse(BaseModel):
    """Response to query() ABCI call."""
    key: bytes = b""
    value: bytes = b""
    proof_ops: list[dict] = Field(default_factory=list)
    height: int = 0
    index: int = -1

    model_config = {"frozen": True}
