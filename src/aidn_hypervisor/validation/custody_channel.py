"""RFC-0042 VALIDATION-channel custody retrieval."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel, Field

from aidn_hypervisor.dispatcher import NetworkDispatcher, NetworkMessage, canonical_payload_hash
from aidn_hypervisor.dispatcher.models import canonical_payload_bytes
from aidn_hypervisor.dispatcher.routes import (
    bind_remote_validation_observer_route,
    bind_validation_custody_route,
    bind_validation_observer_route,
)
from aidn_hypervisor.validation.models import (
    ValidationCustodyObservationRole,
    canonical_validation_hash,
)


class ValidationReportCustodyGetRequest(BaseModel):
    """Scope-bound request body; requester identity comes from NetworkMessage."""

    custody_request_id: str = Field(min_length=1)
    report_id: str = Field(min_length=1)
    report_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    endpoint_id: str = Field(min_length=1)
    configuration_hash: str = Field(min_length=1)
    report_locator: str = Field(min_length=1)


class ValidationReportCustodyChallengeMessage(BaseModel):
    """Stable, body-free assignment sent to one authorized observer."""

    task_id: str = Field(min_length=1)
    epoch_id: str = Field(min_length=1)
    seed: str = Field(min_length=1)
    report_id: str = Field(min_length=1)
    report_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    endpoint_id: str = Field(min_length=1)
    configuration_hash: str = Field(min_length=1)
    observer_id: str = Field(min_length=1)
    independence_key: str = Field(min_length=1)
    challenge_id: str = Field(min_length=1)
    required_quorum: int = Field(ge=1)
    observation_role: ValidationCustodyObservationRole = "origin"
    scheduled_at: str = Field(min_length=1)
    task_evidence_root: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def _challenge_payload_from_task(task) -> dict:
    return ValidationReportCustodyChallengeMessage(
        task_id=task.task_id,
        epoch_id=task.epoch_id,
        seed=task.seed,
        report_id=task.report_id,
        report_hash=task.report_hash,
        endpoint_id=task.endpoint_id,
        configuration_hash=task.configuration_hash,
        observer_id=task.observer_id,
        independence_key=task.independence_key,
        challenge_id=task.challenge_id,
        required_quorum=task.required_quorum,
        observation_role=task.observation_role,
        scheduled_at=task.scheduled_at,
        task_evidence_root=task.task_evidence_root,
    ).model_dump(mode="json")


class ValidationCustodyChallengeChannel:
    """Execute one persisted custody task without transporting report content."""

    def __init__(self, validation_service, *, observer_id: str) -> None:
        if not observer_id.strip():
            raise ValueError("observer_id is required")
        self.validation_service = validation_service
        self.observer_id = observer_id

    def dispatcher_handler(self, payload: dict, message: NetworkMessage) -> dict:
        return self.handle(payload, message)

    def handle(self, payload: dict, message: NetworkMessage) -> dict:
        if message.channel_class != "VALIDATION":
            raise ValueError("custody challenge requires VALIDATION channel")
        if message.message_type != "VALIDATION_REPORT_CUSTODY_CHALLENGE":
            raise ValueError("unsupported Validation custody challenge message type")
        request = ValidationReportCustodyChallengeMessage.model_validate(payload)
        if request.observer_id != self.observer_id:
            raise ValueError("custody challenge observer scope mismatch")
        if (
            message.destination_subject.subject_type != "VALIDATION_OBSERVER"
            or message.destination_subject.subject_id != self.observer_id
        ):
            raise ValueError("custody challenge destination scope mismatch")
        task = self.validation_service.store.get_report_custody_task(request.task_id)
        expected_payload = _challenge_payload_from_task(task)
        if request.model_dump(mode="json") != expected_payload:
            raise ValueError("custody challenge task binding mismatch")
        replayed = task.status == "completed"
        completed = self.validation_service.run_scheduled_custody_challenge(
            task_id=task.task_id,
        )
        return {
            "message_id": message.message_id,
            "acknowledgment": "CUSTODY_CHALLENGE_COMPLETED",
            "task_id": completed.task_id,
            "challenge_id": completed.challenge_id,
            "report_id": completed.report_id,
            "report_hash": completed.report_hash,
            "observer_id": completed.observer_id,
            "observation_role": completed.observation_role,
            "outcome": completed.outcome,
            "challenge_evidence_root": completed.challenge_evidence_root,
            "task_evidence_root": completed.task_evidence_root,
            "replayed": replayed,
        }


class ValidationCustodyChallengeDispatcherAdapter:
    """Route a scheduled custody task through the canonical Dispatcher."""

    def __init__(
        self,
        dispatcher: NetworkDispatcher,
        validation_service,
        *,
        observer_id: str,
        route_generation: int = 1,
        authorized_source_ids: set[str] | None = None,
        hypervisor_key: str | None = None,
        remote_sender=None,
    ) -> None:
        self.dispatcher = dispatcher
        self.validation_service = validation_service
        self._observer_id = observer_id
        self._route_generation = route_generation
        self._source_subject = {
            "subject_type": "VALIDATION_AUTHORITY",
            "subject_id": "validation-authority",
        }
        self._channel = ValidationCustodyChallengeChannel(
            validation_service,
            observer_id=observer_id,
        )
        if remote_sender is None:
            bind_validation_observer_route(
                dispatcher,
                self._channel.dispatcher_handler,
                observer_id=observer_id,
                route_generation=route_generation,
                allowed_source_ids=authorized_source_ids,
                hypervisor_key=hypervisor_key,
            )
        else:
            bind_remote_validation_observer_route(
                dispatcher,
                remote_sender,
                observer_id=observer_id,
                route_generation=route_generation,
                allowed_source_ids=authorized_source_ids,
                hypervisor_key=hypervisor_key,
            )

    def submit_scheduled_task(
        self,
        *,
        task_id: str,
        source_subject: dict | None = None,
        message_id: str | None = None,
        expiration_delta: timedelta | None = None,
    ) -> dict:
        task = self.validation_service.store.get_report_custody_task(task_id)
        if task.observer_id != self._observer_id:
            raise ValueError("custody task is assigned to another observer")
        payload = _challenge_payload_from_task(task)
        source = source_subject or self._source_subject
        stable_message_id = "custody-dispatch-" + canonical_validation_hash(
            {"task_id": task_id, "observer_id": self._observer_id, "source": source}
        ).removeprefix("sha256:")
        now = datetime.now(UTC)
        message = NetworkMessage(
            message_id=message_id or stable_message_id,
            message_type="VALIDATION_REPORT_CUSTODY_CHALLENGE",
            network_id=self.dispatcher.network_id,
            chain_id=self.dispatcher.chain_id,
            network_revision=self.dispatcher.network_revision,
            channel_id="validation-custody-challenge-1",
            channel_class="VALIDATION",
            source_subject=source,
            destination_subject={
                "subject_type": "VALIDATION_OBSERVER",
                "subject_id": self._observer_id,
            },
            source_sequence=0,
            priority_class="BACKGROUND",
            route_generation=self._route_generation,
            created_at=now.isoformat(),
            expiration=(now + (expiration_delta or timedelta(minutes=5))).isoformat(),
            payload_hash=canonical_payload_hash(payload),
            payload_length=len(canonical_payload_bytes(payload)),
            payload=payload,
            authentication={"task_evidence_root": task.task_evidence_root},
        )
        return self.dispatcher.submit(message).model_dump(mode="json")

    def drain_once(self) -> tuple[dict, dict] | None:
        result = self.dispatcher.drain_once()
        if result is None:
            return None
        delivery_record, response = result
        return delivery_record.model_dump(mode="json"), response


class ValidationReportCustodyChannel:
    """Serve custody reports only after Dispatcher source authorization."""

    def __init__(self, validation_service) -> None:
        self.validation_service = validation_service
        self._responses: dict[str, tuple[str, dict]] = {}

    def dispatcher_handler(self, payload: dict, message: NetworkMessage) -> dict:
        return self.handle(payload, message)

    def handle(self, payload: dict, message: NetworkMessage) -> dict:
        if message.channel_class != "VALIDATION":
            raise ValueError("custody retrieval requires VALIDATION channel")
        if message.message_type != "VALIDATION_REPORT_CUSTODY_GET":
            raise ValueError("unsupported Validation custody message type")
        request = ValidationReportCustodyGetRequest.model_validate(payload)
        fingerprint = canonical_validation_hash(
            {
                "payload": request.model_dump(mode="json"),
                "source_subject": message.source_subject.model_dump(mode="json"),
            }
        )
        previous = self._responses.get(message.message_id)
        if previous is not None:
            previous_fingerprint, previous_response = previous
            if previous_fingerprint != fingerprint:
                raise ValueError("custody retrieval message replay conflicts with prior payload")
            replayed = dict(previous_response)
            replayed["replayed"] = True
            return replayed

        commitment = self.validation_service.store.get_report_commitment(request.report_id)
        if commitment.report_hash != request.report_hash:
            raise ValueError("custody retrieval report hash does not match commitment")
        if commitment.endpoint_id != request.endpoint_id:
            raise ValueError("custody retrieval Endpoint scope mismatch")
        if commitment.configuration_hash != request.configuration_hash:
            raise ValueError("custody retrieval configuration scope mismatch")
        if commitment.report_locator != request.report_locator:
            raise ValueError("custody retrieval locator does not match commitment")

        body = self.validation_service.get_custody_report_by_locator(
            request.report_locator,
            requester_endpoint_id=request.endpoint_id,
            configuration_hash=request.configuration_hash,
            requester_subject=message.source_subject.subject_id,
        )
        response = {
            "message_id": message.message_id,
            "custody_request_id": request.custody_request_id,
            "report_id": request.report_id,
            "report_hash": request.report_hash,
            "report_size": commitment.report_size,
            "report_locator": request.report_locator,
            "source_subject": message.source_subject.model_dump(mode="json"),
            "body": body,
            "replayed": False,
        }
        self._responses[message.message_id] = (fingerprint, response)
        return response


class ValidationCustodyDispatcherAdapter:
    """Submit authenticated custody retrieval through NetworkDispatcher."""

    def __init__(
        self,
        dispatcher: NetworkDispatcher,
        channel: ValidationReportCustodyChannel,
        *,
        route_generation: int = 1,
        destination_id: str = "validation_custody_handler",
        hypervisor_key: str | None = None,
    ) -> None:
        self.dispatcher = dispatcher
        self.channel = channel
        self._route_generation = route_generation
        self._destination_id = destination_id
        bind_validation_custody_route(
            dispatcher,
            channel.dispatcher_handler,
            destination_id=destination_id,
            route_generation=route_generation,
            hypervisor_key=hypervisor_key,
        )

    def request_report(
        self,
        *,
        report_id: str,
        report_hash: str,
        endpoint_id: str,
        configuration_hash: str,
        report_locator: str,
        source_subject: dict | None = None,
        message_id: str | None = None,
        custody_request_id: str | None = None,
        expiration_delta: timedelta | None = None,
    ) -> dict:
        payload = {
            "custody_request_id": custody_request_id or str(uuid4()),
            "report_id": report_id,
            "report_hash": report_hash,
            "endpoint_id": endpoint_id,
            "configuration_hash": configuration_hash,
            "report_locator": report_locator,
        }
        now = datetime.now(UTC)
        message = NetworkMessage(
            message_id=message_id or str(uuid4()),
            message_type="VALIDATION_REPORT_CUSTODY_GET",
            network_id=self.dispatcher.network_id,
            chain_id=self.dispatcher.chain_id,
            network_revision=self.dispatcher.network_revision,
            channel_id="validation-custody-1",
            channel_class="VALIDATION",
            source_subject=source_subject
            or {"subject_type": "VALIDATOR", "subject_id": "validator-1"},
            destination_subject={
                "subject_type": "VALIDATION_CUSTODY_TARGET",
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
        return self.dispatcher.submit(message).model_dump(mode="json")

    def drain_once(self) -> tuple[dict, dict] | None:
        result = self.dispatcher.drain_once()
        if result is None:
            return None
        delivery_record, response = result
        return delivery_record.model_dump(mode="json"), response
