from pathlib import Path

import pytest

from aidn_hypervisor.resident_model_manager import ResidentModelError, ResidentModelManager


def test_local_file_prepare_is_atomic_and_verifiable(tmp_path: Path) -> None:
    source = tmp_path / "source.gguf"
    target = tmp_path / "models" / "steward.gguf"
    source.write_bytes(b"resident-model")
    manager = ResidentModelManager(max_bytes=1024)

    source_digest = manager.inspect(str(source))["sha256"]
    result = manager.download(source.as_uri(), str(target), expected_sha256=source_digest)

    assert target.read_bytes() == b"resident-model"
    assert result["verified"] is True
    assert manager.verify(str(target), expected_sha256=source_digest)["size_bytes"] == len(b"resident-model")
    assert list(target.parent.glob("*.part")) == []


def test_checksum_mismatch_never_replaces_target(tmp_path: Path) -> None:
    source = tmp_path / "source.gguf"
    target = tmp_path / "steward.gguf"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    manager = ResidentModelManager(max_bytes=1024)

    with pytest.raises(ResidentModelError) as error:
        manager.download(source.as_uri(), str(target), expected_sha256="0" * 64)

    assert error.value.details["code"] == "INFERENCE_MODEL_CHECKSUM_MISMATCH"
    assert target.read_bytes() == b"old"


def test_remote_source_is_allow_listed_and_bounded(tmp_path: Path) -> None:
    manager = ResidentModelManager(max_bytes=4)

    with pytest.raises(ResidentModelError) as denied:
        manager.download("https://example.invalid/model.gguf", str(tmp_path / "model.gguf"))
    assert denied.value.details["code"] == "INFERENCE_MODEL_SOURCE_HOST_DENIED"

    source = tmp_path / "large.gguf"
    source.write_bytes(b"12345")
    with pytest.raises(ResidentModelError) as oversized:
        manager.download(source.as_uri(), str(tmp_path / "copy.gguf"))
    assert oversized.value.details["code"] == "INFERENCE_MODEL_TOO_LARGE"
