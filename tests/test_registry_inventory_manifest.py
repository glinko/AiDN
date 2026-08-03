from __future__ import annotations

from aidn_hypervisor.registry import RegistryRetentionPolicy
from aidn_hypervisor.registry_service import RegistryService


def _record(
    object_id: str,
    *,
    object_type: str = "capability_definition",
    created_epoch: int = 1,
    created_block_height: int = 10,
    payload_hash: str = "sha256:payload",
    expiration_epoch: int | None = None,
) -> dict:
    record = {
        "object_id": object_id,
        "object_type": object_type,
        "object_version": "1.0",
        "namespace": "protocol",
        "payload_hash": payload_hash,
        "payload_encoding": "canonical_json",
        "source_reference": "test",
        "created_epoch": created_epoch,
        "created_block_height": created_block_height,
        "payload": {"object_id": object_id},
    }
    if expiration_epoch is not None:
        record["expiration_epoch"] = expiration_epoch
    return record


def test_registry_inventory_manifest_is_deterministic_and_payload_free():
    service = RegistryService(registry_service_id="registry-test")
    service.ingest_registry_objects(
        [
            _record("object-2", created_epoch=2, created_block_height=20),
            _record("object-1", created_epoch=1, created_block_height=10),
        ]
    )

    first = service.get_local_registry_inventory_manifest(generated_at_epoch=5)
    second = service.get_local_registry_inventory_manifest(generated_at_epoch=5)

    assert first.verify() is True
    assert first.manifest_id == second.manifest_id
    assert first.manifest_hash == second.manifest_hash
    assert first.inventory_root.inventory_id.startswith("sha256:")
    assert first.segments[0].object_ids == ["object-1", "object-2"]
    assert "payload" not in first.model_dump(mode="json")


def test_registry_retention_preview_apply_and_restart(tmp_path):
    snapshot_path = tmp_path / "registry-objects.json"
    service = RegistryService(
        snapshot_path=snapshot_path,
        retention_policy=RegistryRetentionPolicy(),
    )
    service.upsert_registry_object(
        _record("ephemeral-1", expiration_epoch=4, created_epoch=1)
    )

    preview = service.apply_registry_retention(current_epoch=4, apply=False)
    assert preview["newly_expired_count"] == 1
    assert service.list_registry_objects()  # preview does not mutate visibility

    applied = service.apply_registry_retention(current_epoch=4)
    assert applied["newly_expired_count"] == 1
    assert service.list_registry_objects() == []
    assert service.list_registry_objects({"include_expired": True})[0][
        "retention_state"
    ] == "EXPIRED"

    restarted = RegistryService(snapshot_path=snapshot_path)
    assert restarted.list_registry_objects() == []
    assert restarted.get_registry_object(
        "ephemeral-1", include_expired=True
    )["retention_state"] == "EXPIRED"
