from __future__ import annotations


class HypervisorIntegrationService:
    """External service wiring for validation, endpoint publication, and sessions."""

    def __init__(self, host) -> None:
        self._host = host

    def bind_validation_service(self, validation_service) -> None:
        self._host.validation_service = validation_service
        validation_service.event_recorder = self._host.record_event
        validation_service.operation_recorder = self._host.record_ledger_operation

    def bind_external_services(
        self,
        *,
        registry_service=None,
        endpoint_service=None,
        endpoint_publication_service=None,
        remote_endpoint_service=None,
        session_service=None,
        validation_service=None,
    ) -> None:
        self._host.registry_service = registry_service
        self._host.endpoint_service = endpoint_service
        self._host.endpoint_publication_service = endpoint_publication_service
        self._host.remote_endpoint_service = remote_endpoint_service
        self._host.session_service = session_service
        if validation_service is not None:
            self.bind_validation_service(validation_service)
        if endpoint_service is not None:
            endpoint_service.operation_recorder = self._host.record_ledger_operation
        if endpoint_publication_service is not None:
            endpoint_publication_service.operation_recorder = (
                self._host.record_ledger_operation
            )
        if session_service is not None:
            session_service.registry_service = registry_service
            session_service.event_recorder = self._host.record_event
            session_service.operation_recorder = self._host.record_ledger_operation
