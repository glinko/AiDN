import hashlib
import io
import zipfile

import pytest

from aidn_hypervisor.providers.package_store import FilesystemPluginPackageStore


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        for relative_path, content in entries.items():
            archive.writestr(relative_path, content)
    return buffer.getvalue()


def test_materialized_plugin_host_is_content_addressed_and_revalidated(tmp_path) -> None:
    package_bytes = _zip_bytes(
        {
            "host/main.py": b"print('plugin host')\n",
            "host/config.json": b"{}\n",
        }
    )
    package_digest = "sha256:" + hashlib.sha256(package_bytes).hexdigest()
    store = FilesystemPluginPackageStore(tmp_path / "packages")
    store.stage(package_bytes=package_bytes, expected_digest=package_digest)

    entrypoint = store.materialize_python_host(
        package_digest=package_digest,
        entrypoint_path="host/main.py",
    )
    assert entrypoint.read_bytes() == b"print('plugin host')\n"
    assert store.materialize_python_host(
        package_digest=package_digest,
        entrypoint_path="host/main.py",
    ) == entrypoint

    entrypoint.write_bytes(b"tampered\n")
    with pytest.raises(ValueError, match="does not match"):
        store.materialize_python_host(
            package_digest=package_digest,
            entrypoint_path="host/main.py",
        )


def test_materialized_plugin_host_rejects_unsafe_zip_paths(tmp_path) -> None:
    package_bytes = _zip_bytes({"../host.py": b"print('unsafe')\n"})
    package_digest = "sha256:" + hashlib.sha256(package_bytes).hexdigest()
    store = FilesystemPluginPackageStore(tmp_path / "packages")
    store.stage(package_bytes=package_bytes, expected_digest=package_digest)

    with pytest.raises(ValueError, match="unsafe archive path"):
        store.materialize_python_host(
            package_digest=package_digest,
            entrypoint_path="host.py",
        )


def test_materialized_plugin_host_requires_zip_and_declared_entrypoint(tmp_path) -> None:
    package_bytes = b"not a zip"
    package_digest = "sha256:" + hashlib.sha256(package_bytes).hexdigest()
    store = FilesystemPluginPackageStore(tmp_path / "packages")
    store.stage(package_bytes=package_bytes, expected_digest=package_digest)

    with pytest.raises(ValueError, match="must be a ZIP"):
        store.materialize_python_host(
            package_digest=package_digest,
            entrypoint_path="host.py",
        )
