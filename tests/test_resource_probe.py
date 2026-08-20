import json
from pathlib import Path

from aidn_hypervisor.domain.models import NodeCapacity
from aidn_hypervisor.resource_probe import (
    ResourceProbeReport,
    load_resource_probe_from_environment,
    probe_host_resources,
    read_resource_probe_report,
    refresh_resource_probe_from_environment,
    write_resource_probe_report,
)


def test_probe_reports_cpu_ram_and_operator_configured_gpu(monkeypatch) -> None:
    monkeypatch.setattr("aidn_hypervisor.resource_probe._probe_cpu_cores", lambda: 3.5)
    monkeypatch.setattr("aidn_hypervisor.resource_probe._probe_ram_mb", lambda: 6144)
    monkeypatch.setattr(
        "aidn_hypervisor.resource_probe._configured_gpu_vram",
        lambda: {"gpu0": 24576},
    )

    report = probe_host_resources(source="test-probe")

    assert report.capacity.cpu_cores == 3.5
    assert report.capacity.ram_mb == 6144
    assert report.capacity.gpu_devices == ["gpu0"]
    assert report.capacity.vram_mb == {"gpu0": 24576}
    assert report.source == "test-probe"
    assert report.limitations == ()


def test_probe_report_round_trip_uses_restricted_json_file(tmp_path: Path) -> None:
    report = ResourceProbeReport(
        capacity=NodeCapacity(
            cpu_cores=4,
            ram_mb=8192,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 4096},
        ),
        source="operator-bootstrap",
        observed_at="2026-08-08T00:00:00+00:00",
    )
    path = tmp_path / "resource-capacity.json"

    write_resource_probe_report(report, path)
    restored = read_resource_probe_report(path)

    assert restored == report
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_probe_report_ignores_malformed_optional_measured_vram(tmp_path: Path) -> None:
    path = tmp_path / "resource-capacity.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "legacy-probe",
                "observed_at": "2026-08-08T00:00:00+00:00",
                "capacity": {
                    "cpu_cores": 4,
                    "ram_mb": 8192,
                    "gpu_devices": ["gpu0"],
                    "vram_mb": {"gpu0": 4096},
                },
                "measured_vram_mb": ["not-a-device-map"],
            }
        ),
        encoding="utf-8",
    )

    restored = read_resource_probe_report(path)

    assert restored.measured_vram_mb == {}


def test_invalid_capacity_file_falls_back_to_runtime_probe(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "resource-capacity.json"
    path.write_text("not-json", encoding="utf-8")
    fallback = ResourceProbeReport(
        capacity=NodeCapacity(cpu_cores=2, ram_mb=2048),
        source="runtime-auto-probe",
        observed_at="2026-08-08T00:00:00+00:00",
    )
    monkeypatch.setattr(
        "aidn_hypervisor.resource_probe.probe_host_resources",
        lambda **_: fallback,
    )

    report = load_resource_probe_from_environment(
        {
            "AIDN_RESOURCE_PROBE_MODE": "auto",
            "AIDN_RESOURCE_CAPACITY_PATH": str(path),
        }
    )

    assert report.capacity == fallback.capacity
    assert "configured capacity file was unavailable or invalid" in report.limitations[0]


def test_refresh_rewrites_configured_capacity_file(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "resource-capacity.json"
    refreshed = ResourceProbeReport(
        capacity=NodeCapacity(cpu_cores=6, ram_mb=12288),
        source="operator-refresh",
        observed_at="2026-08-08T00:00:00+00:00",
    )
    monkeypatch.setenv("AIDN_RESOURCE_PROBE_MODE", "auto")
    monkeypatch.setenv("AIDN_RESOURCE_CAPACITY_PATH", str(path))
    monkeypatch.setattr(
        "aidn_hypervisor.resource_probe.probe_host_resources",
        lambda **_: refreshed,
    )

    report = refresh_resource_probe_from_environment()

    assert report == refreshed
    assert read_resource_probe_report(path) == refreshed


def test_disabled_probe_keeps_unknown_capacity_distinct_from_measurement() -> None:
    report = load_resource_probe_from_environment(
        {"AIDN_RESOURCE_PROBE_MODE": "disabled"}
    )

    assert report.capacity.cpu_cores == 0
    assert report.capacity.ram_mb == 0
    assert report.source == "disabled"
