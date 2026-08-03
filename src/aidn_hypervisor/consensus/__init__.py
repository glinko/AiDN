# AiDN Consensus — M7 CometBFT Consensus Layer
# M7-S1: Operation Envelope + Admission

from aidn_hypervisor.consensus.abci import ABCICanonicalCommitment, AIDNABCIApplication
from aidn_hypervisor.consensus.abci_finality import ABCICommittedFinalitySource
from aidn_hypervisor.consensus.abci_socket import ABCIWireError, AIDNABCISocketServer
from aidn_hypervisor.consensus.admission import (
    AdmissionResult,
    AdmissionValidator,
)
from aidn_hypervisor.consensus.cometbft import (
    CometBftProofVerifier,
    CometBftRpcFinalitySource,
    CometBftRpcLightClientProofVerifier,
    CometBftRpcTransport,
    CometBftRpcValidatorSetProvider,
    CometBftSubmissionTransport,
    HttpCometBftRpcTransport,
    HttpCometBftSubmissionTransport,
    cometbft_transaction_hash,
)
from aidn_hypervisor.consensus.cometbft_crypto import (
    StrictCometBftEd25519Backend,
    Zip215CometBftEd25519Backend,
    cometbft_validator_set_from_rpc,
    cometbft_vote_sign_bytes,
    zip215_verify,
)
from aidn_hypervisor.consensus.cometbft_finality import (
    CometBftFinalityConfig,
    CometBftMultiRpcFinalityConfig,
    build_cometbft_finality_source,
    build_cometbft_multi_rpc_finality_source,
)
from aidn_hypervisor.consensus.cometbft_header import cometbft_header_hash
from aidn_hypervisor.consensus.cometbft_merkle import (
    verify_cometbft_transaction_inclusion,
)
from aidn_hypervisor.consensus.coverage import (
    ACTIVE_OPERATION_TYPES,
    CONSENSUS_APPLIED_OPERATION_TYPES,
    LEGACY_OPERATION_TYPES,
    operation_coverage,
    strict_operation_coverage_error,
)
from aidn_hypervisor.consensus.deployment import (
    CometBftDeploymentCheckpoint,
    CometBftDeploymentValidator,
    CometBftFinalityDeploymentConfig,
    load_cometbft_finality_deployment_config,
)
from aidn_hypervisor.consensus.finality import (
    ConsensusFinalityEvidence,
    ConsensusFinalitySource,
    QuorumConsensusFinalitySource,
    VerifiedConsensusFinalitySource,
)
from aidn_hypervisor.consensus.fixture_runner import (
    FixtureError,
    FixtureRunResult,
    run_fixture,
    run_fixture_set,
    validate_fixture_manifest,
)
from aidn_hypervisor.consensus.implementation_profile import (
    DEFAULT_IMPLEMENTATION_PROFILE_ID,
    IMPLEMENTATION_PROFILE_ACTIVATION_STATE,
    IMPLEMENTATION_PROFILE_STATUS,
    IMPLEMENTATION_PROFILE_VERSION,
    build_implementation_profile,
    canonical_json_bytes,
    operation_catalog_payload,
    sha256_digest,
    verify_implementation_profile,
)
from aidn_hypervisor.consensus.light_client import (
    CometBftCryptographicBackend,
    CometBftLightClient,
    CometBftLightClientProofVerifier,
    CometBftValidator,
    CometBftValidatorSet,
    TrustedCometBftCheckpoint,
)
from aidn_hypervisor.consensus.models import (
    LedgerFeeClass,
    LedgerOperationEnvelope,
    LedgerOriginType,
    OperationType,
)
from aidn_hypervisor.consensus.projection import (
    build_session_escrow_lock_envelope,
    build_session_escrow_lock_envelope_from_funding,
    build_session_failure_evidence_envelope,
    build_session_force_settle_envelope,
    build_session_settlement_accept_envelope,
    build_session_settlement_finalize_envelope,
    build_session_settlement_propose_envelope,
    build_session_settlement_ready_envelope,
)
from aidn_hypervisor.consensus.public_network import (
    PublicMultiValidatorAcceptanceReport,
    PublicMultiValidatorNetworkProfile,
    PublicProfileSignature,
    PublicValidatorManifest,
    assert_public_multivalidator_profile,
    build_public_multivalidator_profile,
    inspect_public_multivalidator_profile,
    public_multivalidator_profile_hash,
)
from aidn_hypervisor.consensus.replay import (
    FinalizedOperationReference,
    FinalizedOperationRegistry,
    finalized_operation_digest,
)
from aidn_hypervisor.consensus.reputation_finality import (
    FinalizedReputationProfileUpdate,
    ReputationProfileFinalityAdapter,
)
from aidn_hypervisor.consensus.session_orchestration import (
    ConsensusSessionChainResult,
    ConsensusSessionOperationOrchestrator,
)
from aidn_hypervisor.consensus.settlement_orchestration import (
    ConsensusSettlementOperationOrchestrator,
    ConsensusSettlementResult,
)
from aidn_hypervisor.consensus.state_store import (
    ABCIStateSnapshot,
    ABCIStateStore,
    ABCIStateStoreError,
)
from aidn_hypervisor.consensus.validator_duty import (
    DutyClassification,
    UnbondingReleaseDecision,
    ValidatorDutyDecision,
    ValidatorDutyEvidence,
    ValidatorDutyPolicy,
    build_participant_suspension_envelope,
    evaluate_unbonding_release,
    evaluate_validator_duty,
)
from aidn_hypervisor.consensus.validator_schedule import (
    ValidatorCandidate,
    ValidatorSchedule,
    ValidatorScheduleBuilder,
    ValidatorScheduleConfig,
    compute_eligibility_evidence_root,
    compute_participant_suspension_root,
    compute_validator_set_hash,
    derive_epoch_selection_seed,
)

__all__ = [
    "LedgerFeeClass",
    "LedgerOperationEnvelope",
    "LedgerOriginType",
    "OperationType",
    "build_session_escrow_lock_envelope",
    "build_session_escrow_lock_envelope_from_funding",
    "build_session_failure_evidence_envelope",
    "build_session_force_settle_envelope",
    "build_session_settlement_ready_envelope",
    "build_session_settlement_propose_envelope",
    "build_session_settlement_accept_envelope",
    "build_session_settlement_finalize_envelope",
    "FinalizedOperationReference",
    "FinalizedOperationRegistry",
    "finalized_operation_digest",
    "ConsensusSessionChainResult",
    "ConsensusSessionOperationOrchestrator",
    "ConsensusSettlementOperationOrchestrator",
    "ConsensusSettlementResult",
    "AdmissionResult",
    "AdmissionValidator",
    "ABCICanonicalCommitment",
    "ABCICommittedFinalitySource",
    "ABCIWireError",
    "AIDNABCISocketServer",
    "AIDNABCIApplication",
    "ABCIStateSnapshot",
    "ABCIStateStore",
    "ABCIStateStoreError",
    "ConsensusFinalityEvidence",
    "ConsensusFinalitySource",
    "QuorumConsensusFinalitySource",
    "VerifiedConsensusFinalitySource",
    "FinalizedReputationProfileUpdate",
    "ReputationProfileFinalityAdapter",
    "CONSENSUS_APPLIED_OPERATION_TYPES",
    "ACTIVE_OPERATION_TYPES",
    "LEGACY_OPERATION_TYPES",
    "operation_coverage",
    "strict_operation_coverage_error",
    "DEFAULT_IMPLEMENTATION_PROFILE_ID",
    "IMPLEMENTATION_PROFILE_ACTIVATION_STATE",
    "IMPLEMENTATION_PROFILE_STATUS",
    "IMPLEMENTATION_PROFILE_VERSION",
    "build_implementation_profile",
    "canonical_json_bytes",
    "operation_catalog_payload",
    "sha256_digest",
    "verify_implementation_profile",
    "FixtureError",
    "FixtureRunResult",
    "run_fixture",
    "run_fixture_set",
    "validate_fixture_manifest",
    "CometBftProofVerifier",
    "CometBftSubmissionTransport",
    "CometBftRpcFinalitySource",
    "CometBftRpcLightClientProofVerifier",
    "CometBftRpcTransport",
    "CometBftRpcValidatorSetProvider",
    "HttpCometBftRpcTransport",
    "HttpCometBftSubmissionTransport",
    "cometbft_transaction_hash",
    "StrictCometBftEd25519Backend",
    "Zip215CometBftEd25519Backend",
    "cometbft_validator_set_from_rpc",
    "cometbft_vote_sign_bytes",
    "zip215_verify",
    "verify_cometbft_transaction_inclusion",
    "cometbft_header_hash",
    "CometBftFinalityConfig",
    "CometBftMultiRpcFinalityConfig",
    "build_cometbft_finality_source",
    "build_cometbft_multi_rpc_finality_source",
    "CometBftDeploymentCheckpoint",
    "CometBftDeploymentValidator",
    "CometBftFinalityDeploymentConfig",
    "load_cometbft_finality_deployment_config",
    "PublicMultiValidatorAcceptanceReport",
    "PublicMultiValidatorNetworkProfile",
    "PublicProfileSignature",
    "PublicValidatorManifest",
    "assert_public_multivalidator_profile",
    "build_public_multivalidator_profile",
    "inspect_public_multivalidator_profile",
    "public_multivalidator_profile_hash",
    "CometBftCryptographicBackend",
    "CometBftLightClient",
    "CometBftLightClientProofVerifier",
    "CometBftValidator",
    "CometBftValidatorSet",
    "TrustedCometBftCheckpoint",
    "ValidatorCandidate",
    "ValidatorSchedule",
    "ValidatorScheduleBuilder",
    "ValidatorScheduleConfig",
    "compute_eligibility_evidence_root",
    "compute_participant_suspension_root",
    "compute_validator_set_hash",
    "derive_epoch_selection_seed",
    "DutyClassification",
    "UnbondingReleaseDecision",
    "ValidatorDutyDecision",
    "ValidatorDutyEvidence",
    "ValidatorDutyPolicy",
    "build_participant_suspension_envelope",
    "evaluate_unbonding_release",
    "evaluate_validator_duty",
]
