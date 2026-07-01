from aidn_hypervisor.endpoints.models import EndpointConfigurationSnapshot, EndpointManifest
from aidn_hypervisor.endpoints.state import (
    EndpointConfigurationSnapshotRecord,
    EndpointManifestSnapshot,
)


class EndpointStore:
    def __init__(self, state_store=None) -> None:
        self._state_store = state_store
        self._manifests: dict[str, EndpointManifest] = {}
        self._snapshots: list[EndpointConfigurationSnapshot] = []
        self.restore()

    def restore(self) -> None:
        if self._state_store is None:
            return
        root = self._state_store.load()
        self._manifests = {
            item.endpoint_id: EndpointManifest.model_validate(item.model_dump(mode="json"))
            for item in root.endpoints
        }
        self._snapshots = [
            EndpointConfigurationSnapshot.model_validate(item.model_dump(mode="json"))
            for item in root.endpoint_configuration_snapshots
        ]

    def list_manifests(self) -> list[EndpointManifest]:
        return list(self._manifests.values())

    def get_manifest(self, endpoint_id: str) -> EndpointManifest:
        return self._manifests[endpoint_id]

    def save_manifest(self, manifest: EndpointManifest) -> None:
        self._manifests[manifest.endpoint_id] = manifest
        self._flush()

    def save_configuration_snapshot(self, snapshot: EndpointConfigurationSnapshot) -> None:
        self._snapshots.append(snapshot)
        self._flush()

    def list_configuration_snapshots(
        self, endpoint_id: str
    ) -> list[EndpointConfigurationSnapshot]:
        return [item for item in self._snapshots if item.endpoint_id == endpoint_id]

    def _flush(self) -> None:
        if self._state_store is None:
            return
        root = self._state_store.load()
        updated = root.model_copy(
            update={
                "endpoints": [
                    EndpointManifestSnapshot.model_validate(item.model_dump(mode="json"))
                    for item in self._manifests.values()
                ],
                "endpoint_configuration_snapshots": [
                    EndpointConfigurationSnapshotRecord.model_validate(
                        item.model_dump(mode="json")
                    )
                    for item in self._snapshots
                ],
            }
        )
        self._state_store.save(updated)
