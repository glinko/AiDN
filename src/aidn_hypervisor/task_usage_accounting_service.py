"""Bridge completed tasks to usage, sessions, and wallet accounting."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import ValidationError

from aidn_hypervisor.accounting.models import (
    AccountingContract,
    SessionAccountingCheckpoint,
    UsageReport,
)
from aidn_hypervisor.domain.models import BundleConfig, TaskRequest
from aidn_hypervisor.pricing import (
    Q_ATOMS_PER_Q,
    accounting_snapshot_units,
    calculate_rate_card_charge,
)
from aidn_hypervisor.wallet_models import WalletUsageMeasurement


class TaskUsageAccountingService:
    """Record task usage without changing the accepted accounting contract."""

    def __init__(self, host) -> None:
        self._host = host

    def auto_record_wallet_usage_for_task(
        self,
        *,
        task_id: str,
        bundle: BundleConfig,
        task: TaskRequest,
    ) -> None:
        owner_id, allocation_id = self.wallet_usage_attribution_for_task(task)
        result = self._host._task_results.get(task_id)
        if not isinstance(result, dict):
            return
        usage_contract = self.provider_usage_contract_for_bundle(bundle)
        usage = result.get("usage")
        if not isinstance(usage, dict):
            if owner_id is None:
                return
            if usage_contract.get("missing_usage_behavior") == "strict_accounting":
                self.mark_task_wallet_accounting_blocked(
                    task_id=task_id,
                    bundle_id=bundle.bundle_id,
                    owner_id=str(owner_id),
                    reason="missing_provider_usage",
                )
                if allocation_id is not None:
                    self._host._wallet_strict_held_allocations.add(str(allocation_id))
            return
        try:
            measurement = WalletUsageMeasurement(**usage)
        except ValidationError as error:
            if owner_id is None:
                return
            strict_accounting = usage_contract.get("missing_usage_behavior") == "strict_accounting"
            self.record_wallet_usage_skipped(
                task_id=task_id,
                bundle_id=bundle.bundle_id,
                owner_id=str(owner_id),
                source=str(usage.get("source", "task_auto")),
                reason="invalid_provider_usage_contract",
                validation_errors=error.errors(),
                strict_accounting=strict_accounting,
            )
            if strict_accounting and allocation_id is not None:
                self._host._wallet_strict_held_allocations.add(str(allocation_id))
            return

        audio_input_seconds = measurement.audio_input_seconds
        if audio_input_seconds is None and measurement.audio_input_milliseconds is not None:
            audio_input_seconds = measurement.audio_input_milliseconds / 1_000
        usage_quote = self._host.quote_wallet_usage(
            input_tokens=measurement.input_tokens,
            output_tokens=measurement.output_tokens,
            fixed_request_count=measurement.fixed_request_count,
            audio_input_seconds=audio_input_seconds,
        )
        session_charge_result = self.record_session_usage_charge_for_task(
            task_id=task_id,
            task=task,
            amount_q_atoms=self.endpoint_charge_q_atoms_for_measurement(
                task_id=task_id,
                task=task,
                measurement=measurement,
                fallback_amount_q=float(usage_quote["charges"]["total_q"]),
            ),
        )
        usage_report = self.attach_usage_report_to_task_result(
            task_id=task_id,
            task=task,
            measurement=measurement,
        )
        self.record_session_usage_acknowledgement_for_task(
            task_id=task_id,
            task=task,
            usage_report=usage_report,
            session_charge_result=session_charge_result,
        )
        if owner_id is None:
            return
        self._host.record_wallet_usage(
            owner_id=str(owner_id),
            task_id=task_id,
            allocation_id=allocation_id,
            bundle_id=bundle.bundle_id,
            workload_type=bundle.workload_type,
            input_tokens=measurement.input_tokens,
            output_tokens=measurement.output_tokens,
            fixed_request_count=measurement.fixed_request_count,
            audio_input_seconds=audio_input_seconds,
            measurement_kind=measurement.measurement_kind,
            measurement_source=measurement.measurement_source,
            source=str(usage.get("source", "task_auto")),
        )

    def record_session_usage_charge_for_task(
        self,
        *,
        task_id: str,
        task: TaskRequest,
        amount_q_atoms: int,
    ):
        session_id = task.constraints.get("session_id")
        if session_id is None:
            return None
        session_service = getattr(self._host, "session_service", None)
        if session_service is None:
            return None
        try:
            return session_service.record_usage_charge_q_atoms(
                str(session_id),
                amount_q_atoms=amount_q_atoms,
            )
        except ValueError as error:
            result = self._host._task_results.get(task_id)
            if isinstance(result, dict):
                try:
                    session = session_service.get_session(str(session_id)).session
                except Exception:
                    session = None
                if session is not None:
                    result["session_accounting"] = self.build_session_accounting_view(session)
            self._host.record_event(
                event_type="session.charge_blocked",
                message="session usage charge blocked",
                task_id=task_id,
                bundle_id=self._host.selected_bundle_id(task_id),
                details={
                    "session_id": str(session_id),
                    "charged_q": amount_q_atoms / Q_ATOMS_PER_Q,
                    "charged_q_atoms": amount_q_atoms,
                    "reason": str(error),
                },
            )
            return None

    def endpoint_charge_for_measurement(
        self,
        *,
        task_id: str | None = None,
        task: TaskRequest,
        measurement: WalletUsageMeasurement,
        fallback_amount_q: float,
    ) -> float:
        return self.endpoint_charge_q_atoms_for_measurement(
            task_id=task_id,
            task=task,
            measurement=measurement,
            fallback_amount_q=fallback_amount_q,
        ) / Q_ATOMS_PER_Q

    def endpoint_charge_q_atoms_for_measurement(
        self,
        *,
        task_id: str | None = None,
        task: TaskRequest,
        measurement: WalletUsageMeasurement,
        fallback_amount_q: float,
    ) -> int:
        """Use the Session-bound Endpoint contract rather than node telemetry pricing."""
        endpoint_id = task.constraints.get("endpoint_id")
        session_id = task.constraints.get("session_id")
        endpoint_service = getattr(self._host, "endpoint_service", None)
        if endpoint_id is None:
            if session_id is not None:
                raise ValueError("Session billing requires endpoint_id")
            return int(Decimal(str(fallback_amount_q)) * Q_ATOMS_PER_Q)
        if endpoint_service is None:
            raise RuntimeError("Endpoint billing service is unavailable")
        try:
            endpoint = endpoint_service.get_endpoint(str(endpoint_id)).endpoint
        except KeyError as error:
            raise ValueError("Endpoint billing contract does not exist") from error

        values: dict[str, int | None] = {
            "request_count": measurement.fixed_request_count,
            "input_tokens": measurement.input_tokens,
            "cached_input_tokens": measurement.cached_input_tokens,
            "output_tokens": measurement.output_tokens,
            "audio_input_milliseconds": measurement.audio_input_milliseconds,
            "audio_output_milliseconds": measurement.audio_output_milliseconds,
            "text_input_characters": measurement.text_input_characters,
        }
        charge = calculate_rate_card_charge(endpoint.pricing.rate_card, values)
        result = self._host._task_results.get(task_id) if task_id is not None else None
        if isinstance(result, dict):
            result["charge_breakdown"] = charge.model_dump(mode="json")
        return charge.total_q_atoms

    def provider_usage_contract_for_bundle(self, bundle: BundleConfig) -> dict:
        plugin = self._host.plugins.get(bundle.plugin_id)
        return plugin.usage_contract()

    def build_session_accounting_view(self, session) -> dict:
        checkpoint_payload = dict(session.accounting_checkpoint or {})
        checkpoint = SessionAccountingCheckpoint.model_validate(
            checkpoint_payload
            or {
                "last_accepted_report_sequence": session.last_accepted_report_sequence,
                "last_accepted_usage_charged_q": session.last_accepted_usage_charged_q,
            }
        )
        acknowledgement_head = {
            key: value
            for key, value in dict(session.last_usage_acknowledgement_snapshot or {}).items()
            if not str(key).startswith("_")
        }
        return {
            "session_id": session.session_id,
            "status": session.accounting_status,
            "checkpoint": checkpoint.model_dump(mode="json"),
            "report_head": dict(session.last_usage_report_snapshot or {}),
            "acknowledgement_head": acknowledgement_head,
        }

    def attach_usage_report_to_task_result(
        self,
        *,
        task_id: str,
        task: TaskRequest,
        measurement: WalletUsageMeasurement,
    ):
        session_id = task.constraints.get("session_id")
        endpoint_id = task.constraints.get("endpoint_id")
        if session_id is None or endpoint_id is None:
            return None
        endpoint_service = getattr(self._host, "endpoint_service", None)
        if endpoint_service is None:
            return None
        try:
            endpoint = endpoint_service.get_endpoint(str(endpoint_id)).endpoint
        except KeyError:
            return None

        contract = self.accounting_contract_for_endpoint(endpoint)
        cumulative_usage = {
            "fixed_request_count": measurement.fixed_request_count,
        }
        if measurement.input_tokens is not None:
            cumulative_usage["input_tokens"] = measurement.input_tokens
        if measurement.cached_input_tokens is not None:
            cumulative_usage["cached_input_tokens"] = measurement.cached_input_tokens
        if measurement.output_tokens is not None:
            cumulative_usage["output_tokens"] = measurement.output_tokens
        if measurement.audio_input_milliseconds is not None:
            cumulative_usage["audio_input_milliseconds"] = measurement.audio_input_milliseconds
        if measurement.audio_input_seconds is not None:
            cumulative_usage["audio_input_seconds"] = measurement.audio_input_seconds
        if measurement.audio_output_milliseconds is not None:
            cumulative_usage["audio_output_milliseconds"] = (
                measurement.audio_output_milliseconds
            )
        if measurement.text_input_characters is not None:
            cumulative_usage["text_input_characters"] = measurement.text_input_characters
        accounting_modes: dict[str, str] = {}
        measurement_sources: dict[str, str] = {}
        for item in contract["billable_units"]:
            unit = str(item["unit"])
            if unit in cumulative_usage:
                accounting_modes[unit] = str(item["mode"])
                measurement_sources[unit] = str(item["measurement_source"])
        for unit in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "audio_input_milliseconds",
            "audio_input_seconds",
            "audio_output_milliseconds",
            "text_input_characters",
        ):
            if unit in cumulative_usage:
                measurement_sources[unit] = measurement.measurement_source

        sequence = 1
        session_service = getattr(self._host, "session_service", None)
        if session_service is not None:
            try:
                session = session_service.get_session(str(session_id)).session
                sequence = max(1, int(session.request_count))
            except Exception:
                sequence = 1

        report_payload = {
            "session_id": str(session_id),
            "endpoint_id": str(endpoint_id),
            "task_id": task_id,
            "sequence": sequence,
            "cumulative_usage": cumulative_usage,
            "measurement_sources": measurement_sources,
        }
        report_id = (
            "usage-" + hashlib.sha256(json.dumps(report_payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        )
        report = UsageReport(
            report_id=report_id,
            report_version="0.1",
            session_id=str(session_id),
            endpoint_id=str(endpoint_id),
            capability_id=endpoint.capabilities[0] if endpoint.capabilities else None,
            pricing_version=str(contract["pricing_version"]),
            accounting_contract_version=str(contract["contract_version"]),
            accounting_modes=accounting_modes,
            sequence=sequence,
            cumulative_usage=cumulative_usage,
            request_usage=[
                {
                    "task_id": task_id,
                    "media_evidence": {
                        key: value
                        for key, value in {
                            "input_artifact_sha256": measurement.input_artifact_sha256,
                            "input_media_type": measurement.input_media_type,
                            "input_bytes": measurement.input_bytes,
                            "audio_input_milliseconds": (
                                measurement.audio_input_milliseconds
                            ),
                            "output_artifact_sha256": measurement.output_artifact_sha256,
                            "output_media_type": measurement.output_media_type,
                            "output_bytes": measurement.output_bytes,
                            "audio_output_milliseconds": (
                                measurement.audio_output_milliseconds
                            ),
                        }.items()
                        if value is not None
                    },
                }
            ],
            measurement_sources=measurement_sources,
            created_at=datetime.now(UTC).isoformat(),
            signature=f"local:{report_id}",
        )
        result = self._host._task_results.get(task_id)
        if isinstance(result, dict):
            result["usage_report"] = report.model_dump(mode="json")
        return report.model_dump(mode="json")

    def record_session_usage_acknowledgement_for_task(
        self,
        *,
        task_id: str,
        task: TaskRequest,
        usage_report: dict | None,
        session_charge_result,
    ) -> None:
        session_id = task.constraints.get("session_id")
        if session_id is None or usage_report is None or session_charge_result is None:
            return
        session_service = getattr(self._host, "session_service", None)
        if session_service is None:
            return
        updated_session = session_service.record_usage_checkpoint(
            str(session_id),
            usage_report=usage_report,
            accepted_charge_q=float(session_charge_result.deposit.consumed_q),
        )
        result = self._host._task_results.get(task_id)
        if isinstance(result, dict):
            result["usage_acknowledgement"] = {
                key: value
                for key, value in dict(updated_session.last_usage_acknowledgement_snapshot).items()
                if not str(key).startswith("_")
            }
            result["session_accounting"] = self.build_session_accounting_view(updated_session)

    def accounting_contract_for_endpoint(self, endpoint) -> dict:
        bundle = self._host._get_bundle(endpoint.bundle_id)
        usage_contract = self.provider_usage_contract_for_bundle(bundle)
        capability_id = endpoint.capabilities[0] if endpoint.capabilities else None
        measurement_source = (
            usage_contract.get("default_measurement_source")
            or usage_contract.get("fallback_measurement_source")
            or "provider_report"
        )
        rate_card = endpoint.pricing.rate_card
        pricing_version = f"{rate_card.schema_version}:{rate_card.rate_card_hash}"
        contract_version = f"acct-{endpoint.endpoint_id}-{endpoint.configuration_hash[:8]}"
        pricing_policy_reference = str(rate_card.rate_card_hash)
        billable_units = accounting_snapshot_units(
            rate_card,
            default_measurement_source=str(measurement_source),
        )
        contract = AccountingContract(
            contract_version=contract_version,
            capability_id=capability_id,
            pricing_version=pricing_version,
            pricing_policy_reference=pricing_policy_reference,
            billable_units=billable_units,
            checkpoint_policy="per_request",
            maximum_unreported_usage=float(endpoint.session.minimum_deposit),
            rate_card_hash=str(rate_card.rate_card_hash),
            maximum_unreported_usage_q_atoms=int(
                Decimal(str(endpoint.session.minimum_deposit)) * Q_ATOMS_PER_Q
            ),
            failure_pricing_policy="reject_unpriced_usage",
        )
        return contract.model_dump(mode="json")

    def accounting_compatibility_errors_for_task(
        self,
        *,
        task: TaskRequest,
        bundle: BundleConfig,
    ) -> list[str]:
        """Reject priced units the selected Provider cannot truthfully report."""
        endpoint_id = task.constraints.get("endpoint_id")
        if endpoint_id is None:
            return []
        endpoint_service = getattr(self._host, "endpoint_service", None)
        if endpoint_service is None:
            return []
        try:
            endpoint = endpoint_service.get_endpoint(str(endpoint_id)).endpoint
        except KeyError:
            return ["Endpoint does not exist"]

        contract = AccountingContract.model_validate(
            self.accounting_contract_for_endpoint(endpoint)
        )
        if all(item.mode == "fixed_price" for item in contract.billable_units):
            return []
        usage_contract = self.provider_usage_contract_for_bundle(bundle)
        declared_units = usage_contract.get("supported_billing_units")
        if declared_units is None:
            return ["Provider does not declare supported billing units"]
        supported_units = set(declared_units)
        supported_modes = set(usage_contract.get("supported_accounting_modes") or [])
        errors: list[str] = []
        for item in contract.billable_units:
            if item.mode == "fixed_price" or item.unit == "idle_milliseconds":
                continue
            if item.unit not in supported_units:
                errors.append(
                    f"Provider does not report required billing unit: {item.unit}"
                )
            if item.mode not in supported_modes:
                errors.append(
                    f"Provider does not support required accounting mode: {item.mode}"
                )
        return errors

    def mark_task_wallet_accounting_blocked(
        self,
        *,
        task_id: str,
        bundle_id: str,
        owner_id: str,
        reason: str,
        source: str = "task_auto",
        validation_errors=None,
    ) -> None:
        result = self._host._task_results.get(task_id)
        if isinstance(result, dict):
            result["wallet_accounting"] = {
                "status": "unbillable",
                "settlement_status": "blocked",
                "reason": reason,
            }
        details = {
            "owner_id": owner_id,
            "source": source,
            "billing_status": "unbillable",
            "settlement_status": "blocked",
            "reason": reason,
        }
        if validation_errors is not None:
            details["validation_errors"] = validation_errors
        self._host.record_event(
            event_type="wallet.usage_skipped",
            message="wallet usage skipped and settlement blocked by strict accounting",
            task_id=task_id,
            bundle_id=bundle_id,
            details=details,
        )

    def record_wallet_usage_skipped(
        self,
        *,
        task_id: str,
        bundle_id: str,
        owner_id: str,
        source: str,
        reason: str,
        strict_accounting: bool,
        validation_errors=None,
    ) -> None:
        if strict_accounting:
            self.mark_task_wallet_accounting_blocked(
                task_id=task_id,
                bundle_id=bundle_id,
                owner_id=owner_id,
                source=source,
                reason=reason,
                validation_errors=validation_errors,
            )
            return
        details = {
            "owner_id": owner_id,
            "source": source,
        }
        if validation_errors is not None:
            details["validation_errors"] = validation_errors
        self._host.record_event(
            event_type="wallet.usage_skipped",
            message="wallet usage skipped due to invalid provider usage contract",
            task_id=task_id,
            bundle_id=bundle_id,
            details=details,
        )

    def wallet_usage_attribution_for_task(
        self,
        task: TaskRequest,
    ) -> tuple[str | None, str | None]:
        owner_id = task.constraints.get("wallet_owner_id")
        allocation_id = str(task.constraints["allocation_id"]) if "allocation_id" in task.constraints else None
        if owner_id is not None:
            return str(owner_id), allocation_id
        if allocation_id is None:
            return None, None

        allocation = self._host._allocations.get(allocation_id)
        if allocation is None:
            return None, allocation_id

        request = allocation.get("request", {})
        derived_owner_id = request.get("owner_id")
        if derived_owner_id is None:
            return None, allocation_id
        return str(derived_owner_id), allocation_id
