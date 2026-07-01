from aidn_hypervisor.remote_endpoints.models import RemoteEndpointReference


class RemoteEndpointStore:
    def __init__(self, state_store=None) -> None:
        self._state_store = state_store
        self._records: list[RemoteEndpointReference] = []
        self.restore()

    def restore(self) -> None:
        if self._state_store is None:
            return
        root = self._state_store.load()
        self._records = [self._copy_record(item) for item in root.remote_endpoints]

    def list_records(self) -> list[RemoteEndpointReference]:
        return [self._copy_record(item) for item in self._records]

    def replace_records(self, records: list[RemoteEndpointReference]) -> None:
        updated_records = [self._copy_record(record) for record in records]
        self._flush(updated_records)
        self._records = updated_records

    def _flush(self, records: list[RemoteEndpointReference]) -> None:
        if self._state_store is None:
            return
        root = self._state_store.load()
        updated = root.model_copy(
            update={
                "remote_endpoints": [self._copy_record(item) for item in records]
            }
        )
        self._state_store.save(updated)

    def _copy_record(self, record: RemoteEndpointReference) -> RemoteEndpointReference:
        return RemoteEndpointReference.model_validate(record.model_dump(mode="json"))
