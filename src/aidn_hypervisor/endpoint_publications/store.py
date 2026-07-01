from aidn_hypervisor.endpoint_publications.models import PublishedEndpointConfiguration


class EndpointPublicationStore:
    def __init__(self, state_store=None) -> None:
        self._state_store = state_store
        self._records: list[PublishedEndpointConfiguration] = []
        self.restore()

    def restore(self) -> None:
        if self._state_store is None:
            return
        root = self._state_store.load()
        self._records = [self._copy_record(item) for item in root.endpoint_publications]

    def list_records(self) -> list[PublishedEndpointConfiguration]:
        return [self._copy_record(item) for item in self._records]

    def append(self, record: PublishedEndpointConfiguration) -> None:
        updated_records = [*self._records, self._copy_record(record)]
        self._flush(updated_records)
        self._records = updated_records

    def replace_records(
        self, records: list[PublishedEndpointConfiguration]
    ) -> None:
        updated_records = [self._copy_record(record) for record in records]
        self._flush(updated_records)
        self._records = updated_records

    def _flush(self, records: list[PublishedEndpointConfiguration]) -> None:
        if self._state_store is None:
            return
        root = self._state_store.load()
        updated = root.model_copy(
            update={
                "endpoint_publications": [
                    self._copy_record(item)
                    for item in records
                ]
            }
        )
        self._state_store.save(updated)

    def _copy_record(
        self, record: PublishedEndpointConfiguration
    ) -> PublishedEndpointConfiguration:
        return PublishedEndpointConfiguration.model_validate(
            record.model_dump(mode="json")
        )
