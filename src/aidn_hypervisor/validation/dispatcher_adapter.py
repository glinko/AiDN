"""In-process VALIDATION_REPORT_TRANSFER routed through NetworkDispatcher core."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from aidn_hypervisor.dispatcher import (
    NetworkDispatcher,
    NetworkMessage,
    canonical_payload_hash,
)
from aidn_hypervisor.dispatcher.models import canonical_payload_bytes
from aidn_hypervisor.dispatcher.routes import bind_validation_route
from aidn_hypervisor.validation.channel import (
    ValidationReportTransferChannel,
    ValidationReportTransferMessage,
)


class ValidationDispatcherAdapter:
    """Route VALIDATION_REPORT_TRANSFER through NetworkDispatcher.submit() + drain_once().

    Replaces direct ``ValidationReportTransferChannel.handle()`` calls with the
    canonical dispatcher pipeline: submit → queue → drain_once → handler.
    """

    def __init__(
        self,
        dispatcher: NetworkDispatcher,
        channel: ValidationReportTransferChannel,
        *,
        route_generation: int = 1,
        destination_id: str = "validation_handler",
    ) -> None:
        self.dispatcher = dispatcher
        self.channel = channel
        self._route_generation = route_generation
        self._destination_id = destination_id
        # Register the channel's dispatcher_handler as the local route handler
        bind_validation_route(
            dispatcher,
            self.channel.dispatcher_handler,
            destination_id=destination_id,
            route_generation=route_generation,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit_validation_report(
        self,
        *,
        message_id: str | None = None,
        envelope: dict,
        report: dict,
        source_subject: dict | None = None,
        destination_subject: dict | None = None,
        network_revision: str | None = None,
        expiration_delta: timedelta | None = None,
    ) -> dict:
        """Submit a VALIDATION_REPORT_TRANSFER into the dispatcher queue.

        Returns the ``DeliveryRecord`` dict (QUEUED / DUPLICATE / etc.).
        """
        payload = {
            "message_id": message_id or str(uuid4()),
            "channel_class": "VALIDATION",
            "message_type": "VALIDATION_REPORT_TRANSFER",
            "envelope": envelope,
            "report": report,
        }
        now = datetime.now(UTC)
        message = NetworkMessage(
            message_id=payload["message_id"],
            message_type="VALIDATION_REPORT_TRANSFER",
            network_id=self.dispatcher.network_id,
            chain_id=self.dispatcher.chain_id,
            network_revision=network_revision or self.dispatcher.network_revision,
            channel_id="validation-1",
            channel_class="VALIDATION",
            source_subject=source_subject or {
                "subject_type": "VALIDATOR",
                "subject_id": envelope.get("validator_id", "validator-1"),
            },
            destination_subject=destination_subject or {
                "subject_type": "VALIDATION_TARGET",
                "subject_id": self._destination_id,
            },
            source_sequence=0,
            route_generation=self._route_generation,
            created_at=now.isoformat(),
            expiration=(now + (expiration_delta or timedelta(minutes=5))).isoformat(),
            payload_hash=canonical_payload_hash(payload),
            payload_length=len(canonical_payload_bytes(payload)),
            payload=payload,
        )
        record = self.dispatcher.submit(message)
        return record.model_dump()

    def drain_validation_results(self) -> tuple[dict, dict] | None:
        """Drain one message from the dispatcher queue and return (delivery_record, handler_result).

        Returns ``None`` when the queue is empty.
        """
        result = self.dispatcher.drain_once()
        if result is None:
            return None
        delivery_record, handler_result = result
        return delivery_record.model_dump(), handler_result

    def drain_all(self) -> list[tuple[dict, dict]]:
        """Drain the entire queue, returning all (record, result) pairs."""
        results: list[tuple[dict, dict]] = []
        while True:
            item = self.drain_validation_results()
            if item is None:
                break
            results.append(item)
        return results
