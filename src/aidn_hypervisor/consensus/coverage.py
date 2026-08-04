"""Consensus operation coverage matrix and production fail-closed policy."""

from __future__ import annotations

from typing import Literal

from aidn_hypervisor.consensus.models import KNOWN_OPERATION_TYPES

OperationCoverage = Literal["IMPLEMENTED", "DECLARED_UNIMPLEMENTED", "EXTENSION"]

# The current implementation profile has one consensus operation schema
# version.  Keeping this at the consensus boundary prevents a permissive
# envelope model from silently accepting a version that execution cannot
# interpret.
SUPPORTED_OPERATION_VERSIONS = frozenset({"1.0.0"})

# These names remain in the historical RFC-0059 catalog so old clients can
# receive a deterministic rejection. They are not active operations in the
# current implementation profile and must not be implemented as aliases for
# the newer typed transitions.
LEGACY_OPERATION_TYPES = frozenset(
    {
        "DEPOSIT_LOCK",
        "ENDPOINT_PUBLISH",
        "EPOCH_TASK",
        "REGISTRY_UPSERT",
        "SESSION_SETTLE",
        "SETTLEMENT_ACCEPT",
        "SETTLEMENT_PROPOSE",
        "VALIDATION_REPORT",
        "VALIDATION_REQUEST",
        "VALIDATOR_STAKE",
        "VALIDATOR_UNSTAKE",
    }
)

VALIDATION_EVIDENCE_OPERATION_TYPES = frozenset(
    {
        "VALIDATION_REPORT_COMMIT",
        "VALIDATION_REPORT_STORAGE_RECEIPT",
        "VALIDATION_REPORT_STORAGE_FAILURE",
        "VALIDATION_REPORT_AVAILABILITY_COMMIT",
        "VALIDATION_REPORT_CUSTODY_RELEASE",
    }
)

# Keep this set beside the ABCI and deterministic execution dispatchers. A
# missing entry is intentionally visible in review and in the coverage test.
CONSENSUS_APPLIED_OPERATION_TYPES = frozenset(
    {
        "EPOCH_TRANSITION",
        "WALLET_TRANSFER",
        "SERVICE_VERIFICATION_COMMIT",
        "REPUTATION_PROFILE_UPDATE",
        *VALIDATION_EVIDENCE_OPERATION_TYPES,
        "SNAPSHOT_COMMIT",
        "SESSION_FAILURE_EVIDENCE",
        "CONSENSUS_VALIDATOR_SET_UPDATE",
        "REWARD_MINT",
        "DEVELOPMENT_REWARD_CALCULATE",
        "DEVELOPMENT_POOL_ALLOCATE",
        "DEVELOPMENT_POOL_CARRYOVER",
        "DEVELOPMENT_BOUNTY_CREATE",
        "DEVELOPMENT_BOUNTY_RESERVE",
        "DEVELOPMENT_BOUNTY_RELEASE",
        "DEVELOPMENT_BOUNTY_EXPIRE",
        "DEVELOPMENT_REWARD_RESERVE",
        "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
        "DEVELOPMENT_REWARD_PAY_MATURITY",
        "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
        "DEVELOPMENT_REWARD_CLAIM",
        "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED",
        "DEVELOPMENT_REWARD_FINALIZE_COMMITMENT",
        "DEVELOPMENT_REWARD_CANCEL_UNVESTED",
        "DEVELOPMENT_REWARD_CORRECT",
        "PENALTY_APPLY",
        "SESSION_ESCROW_LOCK",
        "SESSION_OPEN",
        "SESSION_ACCEPT",
        "SESSION_ESCROW_EXTEND",
        "SESSION_ESCROW_RELEASE",
        "SESSION_CHECKPOINT_COMMIT",
        "SESSION_SETTLEMENT_READY_COMMIT",
        "SESSION_SETTLEMENT_PROPOSE",
        "SESSION_SETTLEMENT_ACCEPT",
        "SESSION_SETTLEMENT_DISPUTE",
        "SESSION_SETTLEMENT_PARTIAL_FINALIZE",
        "SESSION_SETTLEMENT_CORRECT",
        "SESSION_SETTLEMENT_FINALIZE",
        "SESSION_FORCE_SETTLE",
        "STAKE_LOCK",
        "UNSTAKE_REQUEST",
        "STAKE_RELEASE",
        "PARTICIPANT_SUSPEND",
        "PARTICIPANT_REINSTATE",
    }
)

ACTIVE_OPERATION_TYPES = frozenset(KNOWN_OPERATION_TYPES - LEGACY_OPERATION_TYPES)

if not LEGACY_OPERATION_TYPES <= KNOWN_OPERATION_TYPES:
    raise RuntimeError("legacy operation types must be present in the protocol catalog")
if CONSENSUS_APPLIED_OPERATION_TYPES & LEGACY_OPERATION_TYPES:
    raise RuntimeError("legacy operation types cannot be consensus-applied")


def operation_coverage(operation_type: str) -> OperationCoverage:
    """Classify an operation for consensus execution."""
    if operation_type in CONSENSUS_APPLIED_OPERATION_TYPES:
        return "IMPLEMENTED"
    if operation_type in KNOWN_OPERATION_TYPES:
        return "DECLARED_UNIMPLEMENTED"
    return "EXTENSION"


def strict_operation_coverage_error(
    operation_type: str,
    *,
    has_custom_handler: bool = False,
) -> str | None:
    """Return a stable error when strict consensus coverage is not met."""
    if operation_type in CONSENSUS_APPLIED_OPERATION_TYPES or has_custom_handler:
        return None
    coverage = operation_coverage(operation_type)
    if coverage == "DECLARED_UNIMPLEMENTED":
        return f"consensus operation transition is not implemented: {operation_type}"
    return f"consensus operation type is not registered: {operation_type}"


def strict_operation_version_error(
    operation_type: str,
    operation_version: str,
) -> str | None:
    """Return a stable error for an unsupported consensus schema version."""

    if operation_version in SUPPORTED_OPERATION_VERSIONS:
        return None
    return f"unsupported operation version: {operation_type}:{operation_version}"
