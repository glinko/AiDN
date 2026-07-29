import hashlib
import json
from datetime import UTC, datetime

from aidn_hypervisor.consensus.cometbft_header import cometbft_header_hash
from aidn_hypervisor.consensus.light_client import (
    CometBftLightClient,
    CometBftLightClientProofVerifier,
    CometBftValidator,
    CometBftValidatorSet,
    TrustedCometBftCheckpoint,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


class TestCryptographyBackend:
    def validator_set_hash(self, validator_set: CometBftValidatorSet) -> str:
        payload = [
            (validator.address, validator.public_key, validator.voting_power)
            for validator in validator_set.validators
        ]
        return hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()

    def verified_signer_addresses(
        self,
        *,
        signed_header: dict,
        validator_set: CometBftValidatorSet,
        chain_id: str,
        block_height: int,
        block_id: str,
    ) -> set[str]:
        return set(signed_header["commit"].get("verified_signers", []))


def _validator_set(*validators: tuple[str, int]) -> CometBftValidatorSet:
    return CometBftValidatorSet(
        tuple(
            CometBftValidator(
                address=address,
                public_key=f"ed25519:{address}",
                voting_power=power,
            )
            for address, power in validators
        )
    )


def _signed_header(
    *,
    backend: TestCryptographyBackend,
    validator_set: CometBftValidatorSet,
    next_validator_set: CometBftValidatorSet,
    height: int,
    app_hash: str,
    timestamp: str,
    verified_signers: list[str],
) -> dict:
    header = {
        "version": {"block": "11", "app": "0"},
        "chain_id": "aidn-testnet-1",
        "height": str(height),
        "time": timestamp,
        "last_block_id": {
            "hash": _hash(f"last-block-{height}"),
            "parts": {"total": "1", "hash": _hash(f"last-parts-{height}")},
        },
        "last_commit_hash": _hash(f"last-commit-{height}"),
        "data_hash": _hash(f"data-{height}"),
        "validators_hash": backend.validator_set_hash(validator_set),
        "next_validators_hash": backend.validator_set_hash(next_validator_set),
        "consensus_hash": _hash(f"consensus-{height}"),
        "app_hash": app_hash,
        "last_results_hash": _hash(f"last-results-{height}"),
        "evidence_hash": _hash(f"evidence-{height}"),
        "proposer_address": _hash(f"proposer-{height}")[:40],
    }
    block_id = cometbft_header_hash(header)
    return {
        "header": header,
        "commit": {
            "block_id": {
                "hash": block_id,
                "parts": {"total": "1", "hash": _hash(f"parts-{height}")},
            },
            "verified_signers": verified_signers,
        },
    }


def _block_id(signed_header: dict) -> str:
    return signed_header["commit"]["block_id"]["hash"]


def _client(*, now: datetime | None = None) -> tuple[CometBftLightClient, TestCryptographyBackend]:
    backend = TestCryptographyBackend()
    validators = _validator_set(("validator-a", 4), ("validator-b", 3), ("validator-c", 3))
    checkpoint = TrustedCometBftCheckpoint(
        chain_id="aidn-testnet-1",
        height=10,
        block_id="block-10",
        app_hash=_hash("app-10"),
        header_time="2030-01-01T00:00:00Z",
        validator_set=validators,
        validator_set_hash=backend.validator_set_hash(validators),
        next_validator_set_hash=backend.validator_set_hash(validators),
    )
    return (
        CometBftLightClient(
            checkpoint=checkpoint,
            cryptography=backend,
            trust_period_seconds=3600,
            now=lambda: now or datetime(2030, 1, 1, 0, 10, tzinfo=UTC),
        ),
        backend,
    )


def test_light_client_accepts_adjacent_two_thirds_commit_and_rotates_checkpoint():
    client, backend = _client()
    validators = client.trusted_checkpoint.validator_set
    next_validators = _validator_set(("validator-a", 4), ("validator-b", 3), ("validator-d", 3))
    signed_header = _signed_header(
        backend=backend,
        validator_set=validators,
        next_validator_set=next_validators,
        height=11,
        app_hash=_hash("app-11"),
        timestamp="2030-01-01T00:01:00Z",
        verified_signers=["validator-a", "validator-b"],
    )

    assert client.verify_and_trust(
        signed_header=signed_header,
        validator_set=validators,
        next_validator_set=next_validators,
        chain_id="aidn-testnet-1",
        block_height=11,
        block_id=_block_id(signed_header),
        app_hash=_hash("app-11"),
    )
    assert client.trusted_checkpoint.height == 11
    assert client.trusted_checkpoint.next_validator_set_hash == backend.validator_set_hash(
        next_validators
    )


def test_light_client_rejects_commit_without_two_thirds_voting_power():
    client, backend = _client()
    validators = client.trusted_checkpoint.validator_set
    signed_header = _signed_header(
        backend=backend,
        validator_set=validators,
        next_validator_set=validators,
        height=11,
        app_hash=_hash("app-11"),
        timestamp="2030-01-01T00:01:00Z",
        verified_signers=["validator-a"],
    )

    assert not client.verify_and_trust(
        signed_header=signed_header,
        validator_set=validators,
        next_validator_set=validators,
        chain_id="aidn-testnet-1",
        block_height=11,
        block_id=_block_id(signed_header),
        app_hash=_hash("app-11"),
    )
    assert client.trusted_checkpoint.height == 10


def test_light_client_requires_trusted_validator_overlap_for_skipped_height():
    client, backend = _client()
    replacement_validators = _validator_set(("validator-d", 7), ("validator-e", 3))
    signed_header = _signed_header(
        backend=backend,
        validator_set=replacement_validators,
        next_validator_set=replacement_validators,
        height=12,
        app_hash=_hash("app-12"),
        timestamp="2030-01-01T00:02:00Z",
        verified_signers=["validator-d"],
    )

    assert not client.verify_and_trust(
        signed_header=signed_header,
        validator_set=replacement_validators,
        next_validator_set=replacement_validators,
        chain_id="aidn-testnet-1",
        block_height=12,
        block_id=_block_id(signed_header),
        app_hash=_hash("app-12"),
    )


def test_light_client_rejects_transition_after_trusted_checkpoint_expires():
    client, backend = _client(now=datetime(2030, 1, 1, 2, 0, tzinfo=UTC))
    validators = client.trusted_checkpoint.validator_set
    signed_header = _signed_header(
        backend=backend,
        validator_set=validators,
        next_validator_set=validators,
        height=11,
        app_hash=_hash("app-11"),
        timestamp="2030-01-01T00:01:00Z",
        verified_signers=["validator-a", "validator-b"],
    )

    assert not client.verify_and_trust(
        signed_header=signed_header,
        validator_set=validators,
        next_validator_set=validators,
        chain_id="aidn-testnet-1",
        block_height=11,
        block_id=_block_id(signed_header),
        app_hash=_hash("app-11"),
    )


def test_light_client_rejects_header_tampering_after_the_block_id_was_precommitted():
    client, backend = _client()
    validators = client.trusted_checkpoint.validator_set
    signed_header = _signed_header(
        backend=backend,
        validator_set=validators,
        next_validator_set=validators,
        height=11,
        app_hash=_hash("app-11"),
        timestamp="2030-01-01T00:01:00Z",
        verified_signers=["validator-a", "validator-b"],
    )
    signed_header["header"]["data_hash"] = _hash("tampered-data")

    assert not client.verify_and_trust(
        signed_header=signed_header,
        validator_set=validators,
        next_validator_set=validators,
        chain_id="aidn-testnet-1",
        block_height=11,
        block_id=_block_id(signed_header),
        app_hash=_hash("app-11"),
    )


def test_light_client_proof_verifier_bridges_commit_and_transaction_validation():
    client, backend = _client()
    validators = client.trusted_checkpoint.validator_set
    signed_header = _signed_header(
        backend=backend,
        validator_set=validators,
        next_validator_set=validators,
        height=11,
        app_hash=_hash("app-11"),
        timestamp="2030-01-01T00:01:00Z",
        verified_signers=["validator-a", "validator-b"],
    )
    verifier = CometBftLightClientProofVerifier(
        light_client=client,
        validator_sets_for_height=lambda height: (validators, validators),
        verify_transaction_inclusion=lambda result, tx_hash, height, block_id, data_hash: (
            result["proof"] == {"ops": []}
            and tx_hash == "A" * 64
            and height == 11
            and block_id == _block_id(signed_header)
            and data_hash == "data-11"
        ),
    )

    assert verifier.verify_transaction_proof(
        transaction_result={"proof": {"ops": []}},
        transaction_hash="A" * 64,
        block_height=11,
        block_id=_block_id(signed_header),
        data_hash="data-11",
    )
    assert verifier.verify_commit(
        signed_header=signed_header,
        chain_id="aidn-testnet-1",
        block_height=11,
        block_id=_block_id(signed_header),
        app_hash=_hash("app-11"),
    )
