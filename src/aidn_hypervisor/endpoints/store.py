from aidn_hypervisor.endpoints.models import (
    EndpointConfigurationSnapshot,
    EndpointManifest,
)
from aidn_hypervisor.endpoints.state import (
    EndpointConfigurationSnapshotRecord,
    EndpointManifestSnapshot,
)
from aidn_hypervisor.persistence import FileStateStore


class EndpointStore:
    def __init__(
        self,
        state_store: FileStateStore | None = None,
        *,
        allow_in_memory: bool = False,
    ) -> None:
        if state_store is None and not allow_in_memory:
            raise ValueError(
                "EndpointStore requires a state_store or explicit allow_in_memory=True"
            )
        self._state_store = state_store
        self._manifests: dict[str, EndpointManifest] = {}
        self._configuration_snapshots: list[EndpointConfigurationSnapshot] = []
        self.restore()

    def restore(self) -> None:
        if self._state_store is None:
            return
        snapshot = self._state_store.load()
        self._manifests = {
            manifest.endpoint_id: EndpointManifest.model_validate(
                manifest.model_dump(mode="python")
            )
            for manifest in snapshot.endpoints
        }
        self._configuration_snapshots = [
            EndpointConfigurationSnapshot.model_validate(
                configuration_snapshot.model_dump(mode="python")
            )
            for configuration_snapshot in snapshot.endpoint_configuration_snapshots
        ]

    def list_manifests(self) -> list[EndpointManifest]:
        return [manifest.model_copy(deep=True) for manifest in self._manifests.values()]

    def get_manifest(self, endpoint_id: str) -> EndpointManifest:
        return self._manifests[endpoint_id].model_copy(deep=True)

    def save_manifest(self, manifest: EndpointManifest) -> None:
        self.save_endpoint(manifest)

    def save_configuration_snapshot(
        self, snapshot: EndpointConfigurationSnapshot
    ) -> None:
        self._configuration_snapshots.append(
            EndpointConfigurationSnapshot.model_validate(
                snapshot.model_dump(mode="python")
            )
            )
        self._flush()

    def save_endpoint(
        self,
        manifest: EndpointManifest,
        snapshot: EndpointConfigurationSnapshot | None = None,
    ) -> None:
        self._manifests[manifest.endpoint_id] = EndpointManifest.model_validate(
            manifest.model_dump(mode="python")
        )
        if snapshot is not None:
            self._configuration_snapshots.append(
                EndpointConfigurationSnapshot.model_validate(
                    snapshot.model_dump(mode="python")
                )
            )
        self._flush()

    def list_configuration_snapshots(
        self, endpoint_id: str
    ) -> list[EndpointConfigurationSnapshot]:
        return [
            snapshot.model_copy(deep=True)
            for snapshot in self._configuration_snapshots
            if snapshot.endpoint_id == endpoint_id
        ]

    def _flush(self) -> None:
        if self._state_store is None:
            return
        snapshot = self._state_store.load()
        snapshot.endpoints = [
            EndpointManifestSnapshot.model_validate(manifest.model_dump(mode="python"))
            for manifest in self._manifests.values()
        ]
        snapshot.endpoint_configuration_snapshots = [
            EndpointConfigurationSnapshotRecord.model_validate(
                configuration_snapshot.model_dump(mode="python")
            )
            for configuration_snapshot in self._configuration_snapshots
        ]
        self._state_store.save(snapshot)
