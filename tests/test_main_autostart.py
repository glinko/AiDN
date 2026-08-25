from aidn_hypervisor.main import _autostart_resident_steward


class _ResidentStub:
    def __init__(self, status: dict):
        self.status = status
        self.prepare_calls: list[dict] = []
        self.start_calls = 0

    def resident_inference_status(self) -> dict:
        return self.status

    def prepare_resident_inference(self, **kwargs) -> dict:
        self.prepare_calls.append(kwargs)
        self.status = {"configured": True, "model_path": kwargs["model_path"], "state": "READY_TO_START"}
        return self.status

    def start_resident_inference(self) -> dict:
        self.start_calls += 1
        self.status = {**self.status, "state": "RUNNING"}
        return self.status


def test_autostart_prepares_and_starts_verified_artifact(monkeypatch, tmp_path) -> None:
    artifact = tmp_path / "steward.gguf"
    artifact.write_bytes(b"model")
    monkeypatch.setenv("AIDN_STEWARD_AUTOSTART", "true")
    monkeypatch.setenv("AIDN_STEWARD_MODEL_PATH", str(artifact))
    monkeypatch.setenv("AIDN_STEWARD_MODEL_SHA256", "a" * 64)
    service = _ResidentStub({"configured": False, "state": "NOT_CONFIGURED"})

    _autostart_resident_steward(service)

    assert len(service.prepare_calls) == 1
    assert service.prepare_calls[0]["model_path"] == str(artifact.resolve())
    assert service.prepare_calls[0]["expected_sha256"] == "a" * 64
    assert service.prepare_calls[0]["runtime_parameter_policy"]["context_length"] == {"value": 4096}
    assert service.prepare_calls[0]["runtime_parameter_policy"]["max_tokens"] == {"value": 192}
    assert service.start_calls == 1


def test_autostart_leaves_running_matching_artifact_untouched(monkeypatch, tmp_path) -> None:
    artifact = tmp_path / "steward.gguf"
    artifact.write_bytes(b"model")
    monkeypatch.setenv("AIDN_STEWARD_AUTOSTART", "true")
    monkeypatch.setenv("AIDN_STEWARD_MODEL_PATH", str(artifact))
    service = _ResidentStub(
        {"configured": True, "model_path": str(artifact.resolve()), "state": "RUNNING"}
    )

    _autostart_resident_steward(service)

    assert service.prepare_calls == []
    assert service.start_calls == 0
