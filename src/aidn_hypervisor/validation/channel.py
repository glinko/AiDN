from pydantic import BaseModel, Field

from aidn_hypervisor.validation.models import (
    ValidationReport,
    ValidationReportTransferEnvelope,
    canonical_validation_hash,
)


class ValidationReportTransferMessage(BaseModel):
    """Transport-neutral RFC-0042 VALIDATION-channel message profile."""

    message_id: str = Field(min_length=1)
    channel_class: str = "VALIDATION"
    message_type: str = "VALIDATION_REPORT_TRANSFER"
    envelope: ValidationReportTransferEnvelope
    report: ValidationReport


class ValidationReportTransferChannel:
    """Idempotent adapter to be called by a future Hypervisor network dispatcher."""

    def __init__(self, validation_service) -> None:
        self.validation_service = validation_service
        self._processed_messages: dict[str, str] = {}

    def handle(self, message: ValidationReportTransferMessage) -> dict:
        if message.channel_class != "VALIDATION":
            raise ValueError("validation report transfer requires VALIDATION channel")
        if message.message_type != "VALIDATION_REPORT_TRANSFER":
            raise ValueError("unsupported validation channel message type")
        fingerprint = canonical_validation_hash(message.model_dump(mode="json"))
        existing = self._processed_messages.get(message.message_id)
        if existing is not None:
            if existing != fingerprint:
                raise ValueError("validation channel message replay conflicts with prior payload")
            return {
                "message_id": message.message_id,
                "acknowledgment": "PROCESSED",
                "replayed": True,
                "report_hash": message.envelope.report_hash,
            }
        custody_object = self.validation_service.accept_report_transfer(
            envelope=message.envelope,
            report=message.report,
        )
        self._processed_messages[message.message_id] = fingerprint
        return {
            "message_id": message.message_id,
            "acknowledgment": "PROCESSED",
            "replayed": False,
            "report_hash": custody_object.report_hash,
        }
