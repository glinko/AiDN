import copy

import pytest

from aidn_hypervisor.consensus.cometbft_header import cometbft_header_hash


def _header() -> dict:
    return {
        "version": {"block": "11", "app": "0"},
        "chain_id": "aidn-testnet-1",
        "height": "11",
        "time": "2030-01-01T00:01:00.123456789Z",
        "last_block_id": {
            "hash": "11" * 32,
            "parts": {"total": "1", "hash": "22" * 32},
        },
        "last_commit_hash": "33" * 32,
        "data_hash": "44" * 32,
        "validators_hash": "55" * 32,
        "next_validators_hash": "66" * 32,
        "consensus_hash": "77" * 32,
        "app_hash": "88" * 32,
        "last_results_hash": "99" * 32,
        "evidence_hash": "AA" * 32,
        "proposer_address": "BB" * 20,
    }


def test_cometbft_header_hash_matches_v038_canonical_field_merkle_vector():
    assert cometbft_header_hash(_header()) == "863FCECB84185D31CEBC5D5DE0C0BA7B7778337ABF78D857EA461D68196EA0E4"


def test_cometbft_header_hash_defaults_omitted_zero_app_version():
    header = _header()
    header["version"].pop("app")

    assert cometbft_header_hash(header) == cometbft_header_hash(_header())


@pytest.mark.parametrize(
    "field,value",
    [
        ("data_hash", "00" * 32),
        ("app_hash", "00" * 32),
        ("proposer_address", "CC" * 20),
        ("time", "2030-01-01T00:01:01.123456789Z"),
    ],
)
def test_cometbft_header_hash_changes_for_every_committed_header_field(field: str, value: str):
    header = _header()
    expected_hash = cometbft_header_hash(header)
    header[field] = value

    assert cometbft_header_hash(header) != expected_hash


def test_cometbft_header_hash_rejects_ambiguous_or_incomplete_block_id():
    ambiguous = _header()
    ambiguous["last_block_id"]["part_set_header"] = copy.deepcopy(
        ambiguous["last_block_id"]["parts"]
    )
    incomplete = _header()
    incomplete["last_block_id"]["parts"]["hash"] = ""

    with pytest.raises(ValueError, match="ambiguous"):
        cometbft_header_hash(ambiguous)
    with pytest.raises(ValueError, match="incomplete"):
        cometbft_header_hash(incomplete)
