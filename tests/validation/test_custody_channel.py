import pytest

from aidn_hypervisor.dispatcher import NetworkDispatcher
from aidn_hypervisor.dispatcher.service import DispatcherError
from aidn_hypervisor.validation.custody_channel import (
    ValidationCustodyChallengeDispatcherAdapter,
    ValidationCustodyDispatcherAdapter,
    ValidationReportCustodyChannel,
)
from aidn_hypervisor.validation.custody_store import ValidationReportCustodyStore
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore


def _service(tmp_path, *, access_class: str = "public", access_checker=None):
    service = ValidationService(
        ValidationStore(),
        custody_store=ValidationReportCustodyStore(tmp_path / "custody"),
        custody_access_checker=access_checker,
    )
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
        evidence_access_class=access_class,
    )
    service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {"validator_id": "val-1", "validator_label": "validator-a", "shares": 1}
        ],
        seed="seed-1",
    )
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )
    return service, outcome


def _adapter(service):
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
    )
    channel = ValidationReportCustodyChannel(service)
    adapter = ValidationCustodyDispatcherAdapter(dispatcher, channel)
    return dispatcher, adapter


def test_custody_retrieval_uses_authenticated_network_source_and_replay_guard(tmp_path) -> None:
    service, outcome = _service(tmp_path)
    dispatcher, adapter = _adapter(service)

    queued = adapter.request_report(
        report_id=outcome.report.report_id,
        report_hash=outcome.commitment.report_hash,
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        report_locator=outcome.commitment.report_locator,
        source_subject={"subject_type": "VALIDATOR", "subject_id": "validator-7"},
        message_id="custody-message-1",
        custody_request_id="custody-request-1",
    )
    assert queued["delivery_state"] == "QUEUED"

    delivered = adapter.drain_once()
    assert delivered is not None
    delivery, response = delivered
    assert delivery["delivery_state"] == "APPLICATION_ACCEPTED"
    assert response["report_hash"] == outcome.commitment.report_hash
    assert response["body"]["endpoint_id"] == "ep-1"
    assert response["source_subject"] == {
        "subject_type": "VALIDATOR",
        "subject_id": "validator-7",
    }

    duplicate = adapter.request_report(
        report_id=outcome.report.report_id,
        report_hash=outcome.commitment.report_hash,
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        report_locator=outcome.commitment.report_locator,
        source_subject={"subject_type": "VALIDATOR", "subject_id": "validator-7"},
        message_id="custody-message-1",
        custody_request_id="custody-request-1",
    )
    assert duplicate["delivery_state"] == "DUPLICATE"
    assert dispatcher.dead_letter_count() == 0


def test_custody_retrieval_rejects_unauthorized_source_and_scope_conflict(tmp_path) -> None:
    service, outcome = _service(tmp_path)
    _, adapter = _adapter(service)

    with pytest.raises(DispatcherError, match="Source subject type is not authorized"):
        adapter.request_report(
            report_id=outcome.report.report_id,
            report_hash=outcome.commitment.report_hash,
            endpoint_id="ep-1",
            configuration_hash="cfg-1",
            report_locator=outcome.commitment.report_locator,
            source_subject={"subject_type": "CONSUMER", "subject_id": "consumer-1"},
        )

    adapter.request_report(
        report_id=outcome.report.report_id,
        report_hash=outcome.commitment.report_hash,
        endpoint_id="ep-other",
        configuration_hash="cfg-1",
        report_locator=outcome.commitment.report_locator,
    )
    with pytest.raises(DispatcherError, match="Endpoint scope mismatch"):
        adapter.drain_once()


def test_restricted_custody_uses_dispatcher_source_for_access_check(tmp_path) -> None:
    observed: list[str] = []

    def access_checker(*, requester_subject: str | None, commitment) -> bool:
        observed.append(requester_subject or "")
        return requester_subject == "validator-7"

    service, outcome = _service(
        tmp_path,
        access_class="restricted",
        access_checker=access_checker,
    )
    _, adapter = _adapter(service)
    adapter.request_report(
        report_id=outcome.report.report_id,
        report_hash=outcome.commitment.report_hash,
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        report_locator=outcome.commitment.report_locator,
        source_subject={"subject_type": "VALIDATOR", "subject_id": "validator-7"},
    )

    delivered = adapter.drain_once()
    assert delivered is not None
    assert delivered[1]["body"]["endpoint_id"] == "ep-1"
    assert observed == ["validator-7"]


def test_scheduled_custody_challenge_dispatches_only_task_evidence_and_is_idempotent(
    tmp_path,
) -> None:
    service, outcome = _service(tmp_path)
    tasks = service.schedule_custody_challenges(
        epoch_id="custody-epoch-1",
        seed="custody-seed-1",
        observer_ids=["observer-1"],
        scheduled_at="2026-08-02T00:00:00+00:00",
    )
    task = tasks[0]
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
    )
    adapter = ValidationCustodyChallengeDispatcherAdapter(
        dispatcher,
        service,
        observer_id=task.observer_id,
    )

    queued = adapter.submit_scheduled_task(task_id=task.task_id)
    assert queued["delivery_state"] == "QUEUED"
    delivered = adapter.drain_once()
    assert delivered is not None
    record, response = delivered
    assert record["delivery_state"] == "APPLICATION_ACCEPTED"
    assert response["acknowledgment"] == "CUSTODY_CHALLENGE_COMPLETED"
    assert response["report_hash"] == outcome.commitment.report_hash
    assert response["observation_role"] == "origin"
    assert "body" not in response
    assert service.store.get_report_custody_task(task.task_id).status == "completed"

    replayed = adapter.submit_scheduled_task(
        task_id=task.task_id,
        message_id="custody-challenge-replay-1",
    )
    assert replayed["delivery_state"] == "QUEUED"
    replay_result = adapter.drain_once()
    assert replay_result is not None
    assert replay_result[1]["replayed"] is True


def test_scheduled_custody_challenge_route_rejects_unauthorized_source(tmp_path) -> None:
    service, _ = _service(tmp_path)
    task = service.schedule_custody_challenges(
        epoch_id="custody-epoch-1",
        seed="custody-seed-1",
        observer_ids=["observer-1"],
    )[0]
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
    )
    adapter = ValidationCustodyChallengeDispatcherAdapter(
        dispatcher,
        service,
        observer_id=task.observer_id,
    )
    with pytest.raises(DispatcherError, match="Source subject type is not authorized"):
        adapter.submit_scheduled_task(
            task_id=task.task_id,
            source_subject={"subject_type": "CONSUMER", "subject_id": "consumer-1"},
        )


def test_scheduled_custody_challenge_supports_scoped_remote_observer_route(tmp_path) -> None:
    service, _ = _service(tmp_path)
    task = service.schedule_custody_challenges(
        epoch_id="custody-epoch-1",
        seed="custody-seed-1",
        observer_ids=["remote-observer"],
    )[0]
    forwarded: list[dict] = []
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
    )
    adapter = ValidationCustodyChallengeDispatcherAdapter(
        dispatcher,
        service,
        observer_id=task.observer_id,
        remote_sender=lambda payload: forwarded.append(payload) or {"forwarded": True},
    )

    queued = adapter.submit_scheduled_task(task_id=task.task_id)
    assert queued["delivery_state"] == "QUEUED"
    delivered = adapter.drain_once()
    assert delivered is not None
    assert delivered[1] == {"forwarded": True}
    route = dispatcher.route(
        destination_type="VALIDATION_OBSERVER",
        destination_id="remote-observer",
    )
    assert route is not None
    assert route.route_type == "REMOTE_HYPERVISOR"
    assert forwarded[0]["task_id"] == task.task_id
    assert forwarded[0]["report_hash"] == task.report_hash
    assert "report_body" not in forwarded[0]
