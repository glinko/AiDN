"""CometBFT RPC adapter for verified operation finality.

The RPC node is not trusted merely because it responds.  This adapter checks
the operation-to-transaction binding and delegates transaction-inclusion and
commit cryptography to a caller-supplied verifier.  It returns no evidence
when either proof cannot be validated.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from aidn_hypervisor.consensus.cometbft_crypto import cometbft_validator_set_from_rpc
from aidn_hypervisor.consensus.cometbft_merkle import (
    verify_cometbft_transaction_inclusion,
)
from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.consensus.light_client import (
    CometBftLightClient,
    CometBftLightClientProofVerifier,
    CometBftValidatorSet,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope


def cometbft_transaction_hash(transaction_bytes: bytes) -> str:
    """Return the conventional uppercase SHA-256 transaction identifier."""
    return hashlib.sha256(transaction_bytes).hexdigest().upper()


def _canonical_hash(value: dict) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalise_hash(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("CometBFT hash is invalid")
    normalized = value.removeprefix("0x").upper()
    if len(normalized) != 64 or any(char not in "0123456789ABCDEF" for char in normalized):
        raise ValueError("CometBFT hash is invalid")
    return normalized


def _normalise_app_hash(value: object) -> str:
    """Normalize a CometBFT AppHash, including the valid empty initial root."""
    if value == "":
        return ""
    return _normalise_hash(value)


def _positive_height(value: object) -> int:
    try:
        height = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("CometBFT block height is invalid") from error
    if height < 1:
        raise ValueError("CometBFT block height is invalid")
    return height


class CometBftRpcTransport(Protocol):
    """Minimal HTTP transport for the CometBFT RPC query endpoints."""

    def get(self, path: str, *, params: dict[str, str], timeout_seconds: int) -> dict:
        """Return the decoded JSON-RPC or HTTP response object."""


class CometBftSubmissionTransport(Protocol):
    """Minimal transport for submitting a transaction to CometBFT."""

    def broadcast_tx_sync(self, tx_data: bytes, *, timeout_seconds: int) -> dict:
        """Submit bytes for CheckTx/mempool admission and return the response."""


class _RejectRedirects(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class CometBftProofVerifier(Protocol):
    """Verifies cryptographic inclusion and commit proofs from a trusted anchor."""

    def verify_transaction_proof(
        self,
        *,
        transaction_result: dict,
        transaction_hash: str,
        block_height: int,
        block_id: str,
        data_hash: str,
    ) -> bool:
        """Validate the transaction inclusion proof against the committed block."""

    def verify_commit(
        self,
        *,
        signed_header: dict,
        chain_id: str,
        block_height: int,
        block_id: str,
        app_hash: str,
    ) -> bool:
        """Validate the commit signatures and validator-set trust transition."""


class HttpCometBftRpcTransport:
    """Bounded GET-only CometBFT RPC transport with a configured endpoint."""

    def __init__(self, endpoint: str, *, max_response_bytes: int = 1_000_000) -> None:
        parsed = urllib_parse.urlsplit(endpoint.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("CometBFT endpoint must be an absolute HTTP URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("CometBFT endpoint must not include credentials, query, or fragment")
        if parsed.path not in {"", "/"}:
            raise ValueError("CometBFT endpoint must not include a path")
        try:
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError("CometBFT endpoint port is invalid")
        except ValueError as error:
            raise ValueError("CometBFT endpoint port is invalid") from error
        if max_response_bytes < 1:
            raise ValueError("CometBFT max_response_bytes must be positive")
        self._endpoint = urllib_parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        self._max_response_bytes = max_response_bytes

    def get(self, path: str, *, params: dict[str, str], timeout_seconds: int) -> dict:
        if not path.startswith("/") or "?" in path or "#" in path:
            raise ValueError("CometBFT RPC path is invalid")
        if timeout_seconds < 1:
            raise ValueError("CometBFT timeout_seconds must be positive")
        query = urllib_parse.urlencode(params, safe="")
        request = urllib_request.Request(
            f"{self._endpoint}{path}?{query}",
            method="GET",
            headers={"Accept": "application/json"},
        )
        opener = urllib_request.build_opener(_RejectRedirects())
        with opener.open(request, timeout=timeout_seconds) as response:
            body = response.read(self._max_response_bytes + 1)
        if len(body) > self._max_response_bytes:
            raise ValueError("CometBFT RPC response exceeds configured limit")
        decoded = json.loads(body.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("CometBFT RPC response is invalid")
        return decoded


class HttpCometBftSubmissionTransport:
    """Bounded HTTP submission transport for CometBFT ``broadcast_tx_sync``."""

    def __init__(self, endpoint: str, *, max_response_bytes: int = 1_000_000) -> None:
        parsed = urllib_parse.urlsplit(endpoint.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("CometBFT submission endpoint must be an absolute HTTP URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "CometBFT submission endpoint must not include credentials, query, or fragment"
            )
        if parsed.path not in {"", "/"}:
            raise ValueError("CometBFT submission endpoint must not include a path")
        try:
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError("CometBFT submission endpoint port is invalid")
        except ValueError as error:
            raise ValueError("CometBFT submission endpoint port is invalid") from error
        if max_response_bytes < 1:
            raise ValueError("CometBFT submission max_response_bytes must be positive")
        self._endpoint = urllib_parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        self._max_response_bytes = max_response_bytes

    def broadcast_tx_sync(self, tx_data: bytes, *, timeout_seconds: int) -> dict:
        if not isinstance(tx_data, bytes) or not tx_data:
            raise ValueError("CometBFT transaction bytes are required")
        if timeout_seconds < 1:
            raise ValueError("CometBFT submission timeout_seconds must be positive")
        query = urllib_parse.urlencode({"tx": f"0x{tx_data.hex()}"}, safe="")
        request = urllib_request.Request(
            f"{self._endpoint}/broadcast_tx_sync?{query}",
            method="POST",
            headers={"Accept": "application/json", "Content-Length": "0"},
            data=b"",
        )
        opener = urllib_request.build_opener(_RejectRedirects())
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                body = response.read(self._max_response_bytes + 1)
        except urllib_error.HTTPError as error:
            # CometBFT may use HTTP 500 for a JSON-RPC CheckTx error.  Keep
            # the JSON body so the submission layer can distinguish a real
            # rejection from an idempotent cache admission.
            body = error.read(self._max_response_bytes + 1)
            if not body:
                raise ValueError(f"CometBFT submission HTTP error {error.code}") from error
        if len(body) > self._max_response_bytes:
            raise ValueError("CometBFT submission response exceeds configured limit")
        decoded = json.loads(body.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("CometBFT submission response is invalid")
        return decoded


class CometBftRpcValidatorSetProvider:
    """Load complete, canonically ordered CometBFT validator sets over RPC.

    A partially fetched set cannot be used for validator-hash or voting-power
    checks.  The provider therefore verifies every page's declared height and
    total before returning a typed validator set.
    """

    def __init__(
        self,
        *,
        transport: CometBftRpcTransport,
        timeout_seconds: int = 10,
        per_page: int = 100,
        maximum_validators: int = 10_000,
    ) -> None:
        if timeout_seconds < 1:
            raise ValueError("CometBFT timeout_seconds must be positive")
        if not 1 <= per_page <= 100:
            raise ValueError("CometBFT per_page must be between 1 and 100")
        if maximum_validators < per_page:
            raise ValueError("CometBFT maximum_validators is too small")
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._per_page = per_page
        self._maximum_validators = maximum_validators

    def validator_sets_for_height(
        self, height: int
    ) -> tuple[CometBftValidatorSet, CometBftValidatorSet]:
        """Return the current and next set committed by one header height."""
        if height < 1:
            raise ValueError("CometBFT validator height must be positive")
        return self.validator_set_at(height), self.validator_set_at(height + 1)

    def validator_set_at(self, height: int) -> CometBftValidatorSet:
        """Fetch every page for one exact height before constructing the set."""
        if height < 1:
            raise ValueError("CometBFT validator height must be positive")
        validators: list[dict[str, object]] = []
        expected_total: int | None = None
        page = 1
        while True:
            response = self._rpc_result(
                self._transport.get(
                    "/validators",
                    params={
                        "height": str(height),
                        "page": str(page),
                        "per_page": str(self._per_page),
                    },
                    timeout_seconds=self._timeout_seconds,
                )
            )
            if _positive_height(response.get("block_height")) != height:
                raise ValueError("CometBFT validator page height does not match")
            total = self._nonnegative_int(response.get("total"), "validator total")
            count = self._nonnegative_int(response.get("count"), "validator count")
            page_validators = response.get("validators")
            if not isinstance(page_validators, list) or len(page_validators) != count:
                raise ValueError("CometBFT validator page count is invalid")
            if total < 1 or total > self._maximum_validators:
                raise ValueError("CometBFT validator total is outside the configured limit")
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise ValueError("CometBFT validator total changed during pagination")
            if count == 0 or len(validators) + count > total:
                raise ValueError("CometBFT validator pagination is incomplete")
            if not all(isinstance(validator, dict) for validator in page_validators):
                raise ValueError("CometBFT validator page contains an invalid record")
            validators.extend(page_validators)
            if len(validators) == total:
                return cometbft_validator_set_from_rpc(validators)
            page += 1

    def _rpc_result(self, response: dict) -> dict:
        if response.get("error") not in {None, ""}:
            raise ValueError("CometBFT RPC returned an error")
        result = response.get("result", response)
        if not isinstance(result, dict):
            raise ValueError("CometBFT RPC result is invalid")
        return result

    def _nonnegative_int(self, value: object, field_name: str) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"CometBFT {field_name} is invalid") from error
        if result < 0:
            raise ValueError(f"CometBFT {field_name} is invalid")
        return result


class CometBftRpcLightClientProofVerifier(CometBftLightClientProofVerifier):
    """Production wiring for one light client and bounded RPC validator paging."""

    def __init__(
        self,
        *,
        light_client: CometBftLightClient,
        transport: CometBftRpcTransport,
        verify_transaction_inclusion: Callable[[dict, str, int, str, str], bool]
        | None = None,
        timeout_seconds: int = 10,
        per_page: int = 100,
        maximum_validators: int = 10_000,
    ) -> None:
        self.validator_set_provider = CometBftRpcValidatorSetProvider(
            transport=transport,
            timeout_seconds=timeout_seconds,
            per_page=per_page,
            maximum_validators=maximum_validators,
        )
        super().__init__(
            light_client=light_client,
            validator_sets_for_height=self.validator_set_provider.validator_sets_for_height,
            verify_transaction_inclusion=(
                verify_transaction_inclusion or verify_cometbft_transaction_inclusion
            ),
        )

class CometBftRpcFinalitySource:
    """Resolve operation finality using CometBFT ``/tx`` and ``/commit`` RPCs.

    The caller provides the exact submitted transaction hash for each operation
    and a verifier rooted in a configured trusted validator set.  A responding
    RPC endpoint alone is deliberately insufficient.
    """

    _LEGACY_SCAN_BATCH_SIZE = 64

    def __init__(
        self,
        *,
        chain_id: str,
        transaction_hash_for_operation: Callable[[str], str | None],
        proof_verifier: CometBftProofVerifier,
        transport: CometBftRpcTransport,
        verifier_id: str,
        timeout_seconds: int = 10,
        transaction_scan_window: int = 512,
    ) -> None:
        if not chain_id.strip() or not verifier_id.strip():
            raise ValueError("CometBFT chain_id and verifier_id are required")
        if timeout_seconds < 1:
            raise ValueError("CometBFT timeout_seconds must be positive")
        if transaction_scan_window < 0:
            raise ValueError("CometBFT transaction_scan_window cannot be negative")
        self._chain_id = chain_id
        self._transaction_hash_for_operation = transaction_hash_for_operation
        self._proof_verifier = proof_verifier
        self._transport = transport
        self._verifier_id = verifier_id
        self._timeout_seconds = timeout_seconds
        self._transaction_scan_window = transaction_scan_window

    def finality_evidence(self, operation_id: str) -> ConsensusFinalityEvidence | None:
        """Return evidence only after both inclusion and commit proof verification."""
        try:
            expected_tx_hash = self._transaction_hash_for_operation(operation_id)
            if expected_tx_hash is None:
                expected_tx_hash = self._recover_transaction_hash(operation_id)
                if expected_tx_hash is None:
                    return None
            transaction_hash = _normalise_hash(expected_tx_hash)
            transaction_result = self._rpc_result(
                self._transport.get(
                    "/tx",
                    params={"hash": f"0x{transaction_hash}", "prove": "true"},
                    timeout_seconds=self._timeout_seconds,
                )
            )
            block_height = _positive_height(transaction_result.get("height"))
            if _normalise_hash(transaction_result.get("hash")) != transaction_hash:
                return None
            tx_result = transaction_result.get("tx_result")
            if not isinstance(tx_result, dict) or int(tx_result.get("code", -1)) != 0:
                return None
            if not isinstance(transaction_result.get("proof"), dict):
                return None
            self._verify_operation_binding(
                operation_id=operation_id,
                expected_hash=transaction_hash,
                encoded_transaction=transaction_result.get("tx"),
            )
            commit_result = self._rpc_result(
                self._transport.get(
                    "/commit",
                    params={"height": str(block_height)},
                    timeout_seconds=self._timeout_seconds,
                )
            )
            signed_header = commit_result.get("signed_header")
            if not isinstance(signed_header, dict):
                return None
            header = signed_header.get("header")
            commit = signed_header.get("commit")
            if not isinstance(header, dict) or not isinstance(commit, dict):
                return None
            if commit_result.get("canonical") is not True:
                return None
            if header.get("chain_id") != self._chain_id:
                return None
            if _positive_height(header.get("height")) != block_height:
                return None
            block_id = self._block_id(commit)
            app_hash = _normalise_app_hash(header.get("app_hash"))
            data_hash = _normalise_hash(header.get("data_hash"))
            finalized_at = header.get("time")
            if not isinstance(finalized_at, str) or not finalized_at.strip():
                return None
            if not self._proof_verifier.verify_transaction_proof(
                transaction_result=transaction_result,
                transaction_hash=transaction_hash,
                block_height=block_height,
                block_id=block_id,
                data_hash=data_hash,
            ):
                return None
            if not self._proof_verifier.verify_commit(
                signed_header=signed_header,
                chain_id=self._chain_id,
                block_height=block_height,
                block_id=block_id,
                app_hash=app_hash,
            ):
                return None
            return ConsensusFinalityEvidence(
                operation_id=operation_id,
                chain_id=self._chain_id,
                block_height=block_height,
                block_id=block_id,
                app_hash=app_hash,
                commit_hash=_canonical_hash(signed_header),
                finalized_at=finalized_at,
                verifier_id=self._verifier_id,
            )
        except Exception:
            return None

    def _recover_transaction_hash(self, operation_id: str) -> str | None:
        """Find a committed legacy transaction when the local hash was lost.

        Older state snapshots did not persist transaction hashes and the local
        CometBFT instance may not index operation IDs when ABCI events are
        unavailable. A bounded block scan reconstructs the hash from signed
        transaction bytes; the normal proof and commit checks still run after
        discovery.
        """
        if (
            self._transaction_scan_window == 0
            or len(operation_id) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in operation_id)
        ):
            return None
        status = self._rpc_result(
            self._transport.get(
                "/status",
                params={},
                timeout_seconds=self._timeout_seconds,
            )
        )
        sync_info = status.get("sync_info")
        if not isinstance(sync_info, dict):
            return None
        latest_height = _positive_height(sync_info.get("latest_block_height"))
        first_height = max(1, latest_height - self._transaction_scan_window + 1)
        heights = range(latest_height, first_height - 1, -1)
        if self._transaction_scan_window <= 8:
            for height in heights:
                transaction_hash = self._scan_block_for_operation(height, operation_id)
                if transaction_hash is not None:
                    return transaction_hash
            return None

        # Legacy recovery is rare, but a sequential scan would block the
        # operator API for every historical block in a wide migration window.
        # Keep the search bounded while fetching independent block bodies in
        # small batches; results are consumed in descending height order.
        height_list = list(heights)
        batch_size = self._LEGACY_SCAN_BATCH_SIZE
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            for offset in range(0, len(height_list), batch_size):
                batch = height_list[offset : offset + batch_size]
                for transaction_hash in executor.map(
                    lambda height: self._scan_block_for_operation(height, operation_id),
                    batch,
                ):
                    if transaction_hash is not None:
                        return transaction_hash
        return None

    def _scan_block_for_operation(self, height: int, operation_id: str) -> str | None:
        try:
            block_result = self._rpc_result(
                self._transport.get(
                    "/block",
                    params={"height": str(height)},
                    timeout_seconds=self._timeout_seconds,
                )
            )
            block = block_result.get("block")
            if not isinstance(block, dict):
                return None
            data = block.get("data")
            if not isinstance(data, dict):
                return None
            transactions = data.get("txs") or []
            if not isinstance(transactions, list):
                return None
            for encoded_transaction in transactions:
                if not isinstance(encoded_transaction, str):
                    continue
                try:
                    transaction_bytes = base64.b64decode(encoded_transaction, validate=True)
                    envelope = LedgerOperationEnvelope.model_validate(
                        json.loads(transaction_bytes.decode("utf-8"))
                    )
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
                    continue
                if envelope.operation_id == operation_id:
                    return cometbft_transaction_hash(transaction_bytes)
        except Exception:
            return None
        return None

    def _rpc_result(self, response: dict) -> dict:
        if response.get("error") not in {None, ""}:
            raise ValueError("CometBFT RPC returned an error")
        result = response.get("result", response)
        if not isinstance(result, dict):
            raise ValueError("CometBFT RPC result is invalid")
        return result

    def _verify_operation_binding(
        self,
        *,
        operation_id: str,
        expected_hash: str,
        encoded_transaction: object,
    ) -> None:
        if not isinstance(encoded_transaction, str):
            raise ValueError("CometBFT transaction is missing")
        transaction_bytes = base64.b64decode(encoded_transaction, validate=True)
        if cometbft_transaction_hash(transaction_bytes) != expected_hash:
            raise ValueError("CometBFT transaction hash does not match submitted bytes")
        payload = json.loads(transaction_bytes.decode("utf-8"))
        envelope = LedgerOperationEnvelope.model_validate(payload)
        if envelope.operation_id != operation_id:
            raise ValueError("CometBFT transaction does not bind the requested operation")

    def _block_id(self, commit: dict) -> str:
        block_id = commit.get("block_id")
        if not isinstance(block_id, dict):
            raise ValueError("CometBFT commit block_id is invalid")
        return _normalise_hash(block_id.get("hash"))
