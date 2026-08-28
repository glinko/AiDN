"""Disabled-by-default runtime for Testnet participation settlements.

The policy calculator and payout store are intentionally reusable libraries.
This module is the narrow operational boundary that decides whether a host may
only inspect a day, persist a dry-run batch, or submit the already-persisted
transfers.  It never reads a private key from TOML: callers resolve the named
secret through the host's protected secret mechanism and inject a signer.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aidn_hypervisor.testnet_participation import (
    TestnetParticipationCalculator,
    TestnetParticipationProgram,
    TestnetParticipationSettlement,
    TestnetParticipationTransferBatch,
    load_testnet_participation_program,
)
from aidn_hypervisor.testnet_participation_evidence import (
    TestnetParticipationEvidenceStore,
)
from aidn_hypervisor.testnet_participation_payout import (
    ParticipationTransferSubmitter,
    TestnetParticipationPayoutService,
    TestnetParticipationPayoutStore,
)
from aidn_hypervisor.testnet_participation_worker import TestnetParticipationWorker

TESTNET_PARTICIPATION_RUNTIME_VERSION = "aidn.testnet-participation-runtime.v1"
MAX_TESTNET_PARTICIPATION_RUNTIME_BYTES = 64 * 1024


class TestnetParticipationRuntimeConfig(BaseModel, frozen=True):
    """Host-local runtime controls; no private key material is accepted."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = TESTNET_PARTICIPATION_RUNTIME_VERSION
    enabled: bool = False
    mode: Literal["inspect", "dry_run", "submit"] = "inspect"
    active_network_id: str = Field(min_length=1)
    active_chain_id: str = Field(min_length=1)
    program_path: str | None = None
    evidence_store_path: str | None = None
    payout_store_path: str | None = None
    treasury_wallet: str | None = None
    treasury_signer_secret_ref: str | None = None

    @model_validator(mode="after")
    def validate_runtime(self) -> TestnetParticipationRuntimeConfig:
        if self.schema_version != TESTNET_PARTICIPATION_RUNTIME_VERSION:
            raise ValueError("PARTICIPATION_RUNTIME_VERSION_INVALID")
        if not self.enabled:
            if self.mode != "inspect":
                raise ValueError("PARTICIPATION_RUNTIME_DISABLED_MODE_MUST_INSPECT")
            return self
        required = {
            "program_path": self.program_path,
            "evidence_store_path": self.evidence_store_path,
        }
        if self.mode in {"dry_run", "submit"}:
            required.update(
                {
                    "payout_store_path": self.payout_store_path,
                    "treasury_wallet": self.treasury_wallet,
                    "treasury_signer_secret_ref": self.treasury_signer_secret_ref,
                }
            )
        missing = sorted(name for name, value in required.items() if not value or not value.strip())
        if missing:
            raise ValueError("PARTICIPATION_RUNTIME_REQUIRED: " + ", ".join(missing))
        if self.mode in {"dry_run", "submit"} and not str(
            self.treasury_signer_secret_ref
        ).startswith("secret://"):
            raise ValueError("PARTICIPATION_RUNTIME_TREASURY_SECRET_REF_INVALID")
        return self


def load_testnet_participation_runtime_config(
    path: str | Path,
) -> TestnetParticipationRuntimeConfig:
    """Load a bounded host-local runtime document with a single table."""

    target = Path(path).expanduser()
    try:
        if target.stat().st_size > MAX_TESTNET_PARTICIPATION_RUNTIME_BYTES:
            raise ValueError("PARTICIPATION_RUNTIME_TOO_LARGE")
        with target.open("rb") as stream:
            document = tomllib.load(stream)
    except FileNotFoundError as error:
        raise ValueError(f"participation runtime does not exist: {target}") from error
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"could not load participation runtime {target}: {error}") from error
    if set(document) != {"schema_version", "runtime"} or not isinstance(
        document.get("runtime"), dict
    ):
        raise ValueError("PARTICIPATION_RUNTIME_DOCUMENT_INVALID")
    try:
        return TestnetParticipationRuntimeConfig.model_validate(
            {"schema_version": document["schema_version"], **document["runtime"]}
        )
    except ValueError as error:
        raise ValueError(f"invalid participation runtime {target}: {error}") from error


class TestnetParticipationRuntimeResult(BaseModel, frozen=True):
    """One explicit runtime invocation, safe to publish as read-only status."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["disabled", "inspect", "dry_run", "submit"]
    settlement: TestnetParticipationSettlement | None = None
    batch: TestnetParticipationTransferBatch | None = None
    batch_status: str | None = None
    processed_operation_id: str | None = None
    detail: str | None = None


class TestnetParticipationManagedRuntime:
    """Execute only the reviewed operation allowed by one runtime profile."""

    def __init__(
        self,
        *,
        config: TestnetParticipationRuntimeConfig,
        signer: Callable[[bytes], str] | None = None,
        submitter: ParticipationTransferSubmitter | None = None,
        calculator: TestnetParticipationCalculator | None = None,
    ) -> None:
        self.config = config
        self.calculator = calculator or TestnetParticipationCalculator()
        self.program: TestnetParticipationProgram | None = None
        self.evidence_store: TestnetParticipationEvidenceStore | None = None
        self.payout_service: TestnetParticipationPayoutService | None = None

        if not config.enabled:
            return
        self.program = load_testnet_participation_program(str(config.program_path))
        if (
            self.program.network_id != config.active_network_id
            or self.program.chain_id != config.active_chain_id
        ):
            raise ValueError("PARTICIPATION_RUNTIME_NETWORK_PROFILE_MISMATCH")
        self.evidence_store = TestnetParticipationEvidenceStore(str(config.evidence_store_path))
        if config.mode in {"dry_run", "submit"}:
            if signer is None or submitter is None:
                raise ValueError("PARTICIPATION_RUNTIME_TREASURY_INTEGRATION_REQUIRED")
            self.payout_service = TestnetParticipationPayoutService(
                treasury_wallet=str(config.treasury_wallet),
                signer=signer,
                store=TestnetParticipationPayoutStore(str(config.payout_store_path)),
                submitter=submitter,
            )

    def process_finalized_epoch(
        self,
        *,
        protocol_epoch: int,
        source_epoch_transition_operation_id: str,
        period_start: str,
        reconcile: bool = False,
    ) -> TestnetParticipationRuntimeResult:
        """Run the one mode selected by the protected runtime profile."""

        if not self.config.enabled:
            return TestnetParticipationRuntimeResult(
                mode="disabled",
                detail="PARTICIPATION_RUNTIME_DISABLED",
            )
        if self.program is None or self.evidence_store is None:
            raise RuntimeError("participation runtime was not initialized")
        enrollments, heartbeats = self.evidence_store.settlement_inputs(
            self.program, period_start=period_start
        )
        settlement = self.calculator.calculate(
            self.program,
            protocol_epoch=protocol_epoch,
            source_epoch_transition_operation_id=source_epoch_transition_operation_id,
            period_start=period_start,
            enrollments=enrollments,
            heartbeats=heartbeats,
        )
        if self.config.mode == "inspect":
            return TestnetParticipationRuntimeResult(mode="inspect", settlement=settlement)
        if self.payout_service is None:
            raise RuntimeError("participation payout service was not initialized")
        if self.config.mode == "dry_run":
            batch = self.payout_service.schedule(settlement)
            record = self.payout_service.store.get_batch(settlement.settlement_id)
            return TestnetParticipationRuntimeResult(
                mode="dry_run",
                settlement=settlement,
                batch=batch,
                batch_status=str(record["status"]) if record is not None else None,
                detail="PARTICIPATION_PAYOUT_DRY_RUN_NOT_SUBMITTED",
            )

        result = TestnetParticipationWorker(
            program=self.program,
            active_network_id=self.config.active_network_id,
            active_chain_id=self.config.active_chain_id,
            evidence_store=self.evidence_store,
            payout_service=self.payout_service,
            calculator=self.calculator,
        ).process_finalized_epoch(
            protocol_epoch=protocol_epoch,
            source_epoch_transition_operation_id=source_epoch_transition_operation_id,
            period_start=period_start,
            reconcile=reconcile,
        )
        return TestnetParticipationRuntimeResult(
            mode="submit",
            settlement=result.settlement,
            batch=result.batch,
            batch_status=result.batch_status,
            processed_operation_id=result.processed_operation_id,
        )


__all__ = [
    "TESTNET_PARTICIPATION_RUNTIME_VERSION",
    "TestnetParticipationManagedRuntime",
    "TestnetParticipationRuntimeConfig",
    "TestnetParticipationRuntimeResult",
    "load_testnet_participation_runtime_config",
]
