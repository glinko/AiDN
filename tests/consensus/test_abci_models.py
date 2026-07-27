"""Tests for ABCI models — abci_models.py."""

import pytest
from pydantic_core import ValidationError as PydanticCoreValidationError

from aidn_hypervisor.consensus.abci_models import (
    ABCICommitResponse,
    ABCIInfoResponse,
    ABCIQueryResponse,
    ABCIResult,
    ABCITag,
)


def test_abci_result_ok():
    result = ABCIResult()
    assert result.code == "ok"
    assert result.data == b""
    assert result.log == ""
    assert result.info == ""
    assert result.codespace == ""
    assert result.gas_used == 0
    assert result.gas_wanted == 0
    assert result.tags == []


def test_abci_result_rejected_with_log():
    result = ABCIResult(code="rejected", log="expired operation")
    assert result.code == "rejected"
    assert result.log == "expired operation"


def test_abci_result_with_tags():
    tags = [ABCITag(key="op_id", value="abc123"), ABCITag(key="type", value="transfer")]
    result = ABCIResult(code="ok", tags=tags)
    assert len(result.tags) == 2
    assert result.tags[0].key == "op_id"
    assert result.tags[0].value == "abc123"
    assert result.tags[1].key == "type"
    assert result.tags[1].value == "transfer"


def test_abci_result_frozen():
    result = ABCIResult(code="ok", log="test")
    with pytest.raises(PydanticCoreValidationError):
        result.code = "rejected"  # type: ignore


def test_abci_info_response():
    resp = ABCIInfoResponse(
        data="AiDN",
        version="0.1:1",
        app_version=1,
        last_block_height=42,
    )
    assert resp.data == "AiDN"
    assert resp.version == "0.1:1"
    assert resp.app_version == 1
    assert resp.last_block_height == 42
    assert resp.last_block_app_hash == b""


def test_abci_commit_response():
    resp = ABCICommitResponse(data=b"\x01\x02", version="5")
    assert resp.data == b"\x01\x02"
    assert resp.version == "5"


def test_abci_query_response():
    resp = ABCIQueryResponse(
        key=b"test_key",
        value=b"test_value",
        height=10,
    )
    assert resp.key == b"test_key"
    assert resp.value == b"test_value"
    assert resp.height == 10
    assert resp.index == -1
    assert resp.proof_ops == []


def test_all_abci_codes():
    """Every ABCICode literal is accepted."""
    codes = ["ok", "rejected", "invalid", "duplicate", "expired", "sequence", "internal"]
    for code in codes:
        result = ABCIResult(code=code)  # type: ignore
        assert result.code == code
