"""Machine-verifiable FIX-0001 fixture loading and execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService


class FixtureError(ValueError):
    """A FIX-0001 manifest or fixture is invalid or did not pass."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FixtureError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError, FixtureError) as error:
        raise FixtureError(f"invalid fixture JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise FixtureError(f"fixture root must be an object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_hash(manifest: dict[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    return "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()


def _relative_fixture_path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise FixtureError("fixture path must be a relative path")
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise FixtureError("fixture path escapes manifest directory") from error
    return candidate


@dataclass(frozen=True)
class FixtureRunResult:
    fixture_id: str
    operation_ids: tuple[str, ...]
    result_codes: tuple[str, ...]
    post_app_hash: str | None


def validate_fixture_manifest(manifest_path: str | Path) -> list[Path]:
    """Validate manifest structure and every listed fixture file hash."""

    path = Path(manifest_path).expanduser().resolve()
    manifest = _load_json(path)
    if manifest.get("fixture_set_version") != 1:
        raise FixtureError("unsupported fixture_set_version")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise FixtureError("fixture manifest files must be non-empty")
    if manifest.get("manifest_hash") != _manifest_hash(manifest):
        raise FixtureError("fixture manifest hash mismatch")
    root = path.parent
    listed: list[Path] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise FixtureError("fixture manifest entry must be an object")
        file_path = _relative_fixture_path(root, item.get("path"))
        relative = file_path.relative_to(root).as_posix()
        if relative in seen or relative == path.name:
            raise FixtureError(f"duplicate or invalid fixture path: {relative}")
        seen.add(relative)
        expected_hash = item.get("sha256")
        if not isinstance(expected_hash, str) or expected_hash != _sha256_file(file_path):
            raise FixtureError(f"fixture hash mismatch: {relative}")
        listed.append(file_path)
    if manifest.get("fixture_count") != len(listed):
        raise FixtureError("fixture_count mismatch")
    return listed


def _operation_objects(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(fixture.get("operation"), dict):
        return [fixture["operation"]]
    operations = fixture.get("operations")
    if isinstance(operations, list) and all(isinstance(item, dict) for item in operations):
        return list(operations)
    raise FixtureError("fixture must contain operation or operations")


def _assert_expected_identity(operation: dict[str, Any], expected: dict[str, Any]) -> LedgerOperationEnvelope:
    try:
        envelope = LedgerOperationEnvelope.model_validate(operation)
    except Exception as error:
        raise FixtureError(f"operation envelope is invalid: {error}") from error
    canonical_hex = expected.get("canonical_operation_hex")
    if not isinstance(canonical_hex, str) or canonical_hex != envelope.canonical_bytes().hex():
        raise FixtureError(f"canonical operation mismatch: {envelope.operation_id}")
    if expected.get("operation_id") != envelope.operation_id:
        raise FixtureError(f"operation ID mismatch: {envelope.operation_id}")
    return envelope


def _execute_abci(
    operations: list[dict[str, Any]],
    execution: dict[str, Any],
) -> tuple[list[str], str, dict[str, Any]]:
    current_time = execution.get("current_time", "2030-01-01T00:00:00Z")
    if not isinstance(current_time, str):
        raise FixtureError("execution.current_time must be a string")
    ledger = LedgerOperationService()
    initial_balances = execution.get("initial_wallet_balances", {})
    if not isinstance(initial_balances, dict):
        raise FixtureError("execution.initial_wallet_balances must be an object")
    for wallet_id, amount in initial_balances.items():
        if not isinstance(wallet_id, str) or isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise FixtureError("execution.initial_wallet_balances is invalid")
        ledger.credit_wallet_q_atoms(wallet_id=wallet_id, amount_q_atoms=amount)
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=current_time),
        strict_operation_coverage=True,
    )
    pre_app_hash = app.prepare_snapshot()["app_hash"]
    expected_pre_hash = execution.get("pre_app_hash")
    if expected_pre_hash is not None and expected_pre_hash != pre_app_hash:
        raise FixtureError(f"pre AppHash mismatch: expected {expected_pre_hash}, got {pre_app_hash}")
    block_height = execution.get("block_height")
    block_hash_hex = execution.get("block_hash_hex")
    if isinstance(block_height, bool) or not isinstance(block_height, int) or block_height < 1:
        raise FixtureError("execution.block_height must be a positive integer")
    if not isinstance(block_hash_hex, str):
        raise FixtureError("execution.block_hash_hex is required")
    try:
        block_hash = bytes.fromhex(block_hash_hex)
    except ValueError as error:
        raise FixtureError("execution.block_hash_hex is invalid") from error
    if len(block_hash) != 32:
        raise FixtureError("execution.block_hash_hex must contain 32 bytes")
    _, tx_results = app.finalize_block_with_results(
        block_height=block_height,
        block_hash=block_hash,
        txs=[json.dumps(item, ensure_ascii=True, separators=(",", ":")).encode("utf-8") for item in operations],
    )
    result_codes = [str(item.code) for item in tx_results]
    snapshot = app.prepare_snapshot()
    assertions = execution.get("state_assertions", {})
    if not isinstance(assertions, dict):
        raise FixtureError("execution.state_assertions must be an object")
    wallet_assertions = assertions.get("wallet_balances", {})
    if not isinstance(wallet_assertions, dict):
        raise FixtureError("state_assertions.wallet_balances must be an object")
    for wallet_id, expected_balance in wallet_assertions.items():
        if ledger.wallet_q_atom_balance(wallet_id) != expected_balance:
            raise FixtureError(f"wallet assertion failed: {wallet_id}")
    return result_codes, str(snapshot["app_hash"]), snapshot


def run_fixture(path: str | Path, *, strict: bool = True) -> FixtureRunResult:
    """Validate and optionally execute one FIX-0001 fixture."""

    fixture_path = Path(path).expanduser().resolve()
    fixture = _load_json(fixture_path)
    fixture_id = fixture.get("fixture_id")
    profile_id = fixture.get("profile_id")
    if not isinstance(fixture_id, str) or not fixture_id:
        raise FixtureError("fixture_id is required")
    if not isinstance(profile_id, str) or not profile_id:
        raise FixtureError(f"profile_id is required: {fixture_id}")
    operations = _operation_objects(fixture)
    expected = fixture.get("expected")
    if not isinstance(expected, dict):
        raise FixtureError(f"expected object is required: {fixture_id}")
    if len(operations) == 1:
        envelopes = [_assert_expected_identity(operations[0], expected)]
    else:
        envelopes = []
        expected_operations = expected.get("operations")
        if not isinstance(expected_operations, list) or len(expected_operations) != len(operations):
            raise FixtureError(f"expected.operations is required for block fixture: {fixture_id}")
        for operation, operation_expected in zip(operations, expected_operations, strict=True):
            envelopes.append(_assert_expected_identity(operation, operation_expected))
    execution = fixture.get("execution")
    result_codes: list[str] = []
    post_app_hash: str | None = None
    if execution is not None:
        if not isinstance(execution, dict) or execution.get("engine") != "abci":
            raise FixtureError(f"unsupported fixture execution engine: {fixture_id}")
        result_codes, post_app_hash, _ = _execute_abci(operations, execution)
        expected_codes = expected.get("result_codes")
        if expected_codes is None and len(result_codes) == 1:
            expected_codes = [expected.get("result_code")]
        if expected_codes != result_codes:
            raise FixtureError(f"result code mismatch: {fixture_id}")
        if expected.get("post_app_hash") != post_app_hash:
            raise FixtureError(f"post AppHash mismatch: {fixture_id}")
    elif strict:
        raise FixtureError(f"strict fixture requires execution block: {fixture_id}")
    return FixtureRunResult(
        fixture_id=fixture_id,
        operation_ids=tuple(item.operation_id for item in envelopes),
        result_codes=tuple(result_codes),
        post_app_hash=post_app_hash,
    )


def run_fixture_set(manifest_path: str | Path, *, strict: bool = True) -> list[FixtureRunResult]:
    """Validate a manifest and run every listed fixture in deterministic order."""

    manifest = _load_json(Path(manifest_path).expanduser().resolve())
    manifest_profile_id = manifest.get("profile_id")
    if not isinstance(manifest_profile_id, str) or not manifest_profile_id:
        raise FixtureError("fixture manifest profile_id is required")
    results = []
    for path in validate_fixture_manifest(manifest_path):
        fixture = _load_json(path)
        if fixture.get("profile_id") != manifest_profile_id:
            raise FixtureError(f"fixture profile mismatch: {path.name}")
        results.append(run_fixture(path, strict=strict))
    return results


__all__ = [
    "FixtureError",
    "FixtureRunResult",
    "run_fixture",
    "run_fixture_set",
    "validate_fixture_manifest",
]
