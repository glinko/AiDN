import pytest

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.scheduler import Scheduler


def _bundle(
    bundle_id: str,
    workload_type: str,
    *,
    priority_class: int = 50,
    enabled: bool = True,
) -> BundleConfig:
    return BundleConfig(
        bundle_id=bundle_id,
        plugin_id="fake-managed",
        provider_type="fake",
        workload_type=workload_type,
        model_id=f"{bundle_id}-model",
        launch_mode="managed_process",
        device_affinity="cpu",
        resource_profile=ResourceProfile(),
        warm_policy="auto",
        priority_class=priority_class,
        enabled=enabled,
    )


def test_scheduler_manual_override_selects_requested_bundle() -> None:
    bundle = _bundle("whisper-a", "speech_to_text")
    scheduler = Scheduler()

    selected = scheduler.select_bundle(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "clip.wav"},
            mode="manual",
            bundle_override="whisper-a",
        ),
        [bundle],
    )

    assert selected.bundle_id == "whisper-a"


def test_scheduler_manual_override_fails_when_bundle_is_missing() -> None:
    scheduler = Scheduler()

    with pytest.raises(ValueError, match="missing"):
        scheduler.select_bundle(
            TaskRequest(
                task_type="audio.transcribe",
                payload={"audio_ref": "clip.wav"},
                mode="manual",
                bundle_override="missing",
            ),
            [_bundle("whisper-a", "speech_to_text")],
        )


def test_scheduler_manual_override_fails_when_bundle_is_disabled() -> None:
    scheduler = Scheduler()

    with pytest.raises(ValueError, match="disabled"):
        scheduler.select_bundle(
            TaskRequest(
                task_type="audio.transcribe",
                payload={"audio_ref": "clip.wav"},
                mode="manual",
                bundle_override="whisper-a",
            ),
            [_bundle("whisper-a", "speech_to_text", enabled=False)],
        )


def test_scheduler_manual_override_fails_when_bundle_is_incompatible() -> None:
    scheduler = Scheduler()

    with pytest.raises(ValueError, match="incompatible"):
        scheduler.select_bundle(
            TaskRequest(
                task_type="audio.transcribe",
                payload={"audio_ref": "clip.wav"},
                mode="manual",
                bundle_override="text-a",
            ),
            [_bundle("text-a", "llm_text")],
        )


def test_scheduler_automatic_mode_picks_highest_priority_compatible_enabled_bundle() -> None:
    scheduler = Scheduler()

    selected = scheduler.select_bundle(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}),
        [
            _bundle("text-a", "llm_text", priority_class=100),
            _bundle("disabled-whisper", "speech_to_text", priority_class=90, enabled=False),
            _bundle("preferred-whisper", "speech_to_text", priority_class=80),
            _bundle("fallback-whisper", "speech_to_text", priority_class=40),
        ],
    )

    assert selected.bundle_id == "preferred-whisper"


def test_scheduler_maps_text_generation_to_llm_text_bundles() -> None:
    scheduler = Scheduler()

    selected = scheduler.select_bundle(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "hello"}),
        [
            _bundle("speech-a", "speech_to_text", priority_class=100),
            _bundle("text-a", "llm_text", priority_class=80),
        ],
    )

    assert selected.bundle_id == "text-a"


def test_scheduler_automatic_mode_fails_when_no_compatible_bundle_exists() -> None:
    scheduler = Scheduler()

    with pytest.raises(ValueError, match="compatible"):
        scheduler.select_bundle(
            TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}),
            [_bundle("text-a", "llm_text", priority_class=100)],
        )
