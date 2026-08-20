"""Host capacity discovery used by operator bootstrap and runtime recovery."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aidn_hypervisor.domain.models import NodeCapacity

RESOURCE_PROBE_SCHEMA_VERSION = 1


def _read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _cpu_affinity_count() -> float:
    get_affinity = getattr(os, "sched_getaffinity", None)
    if callable(get_affinity):
        try:
            return float(len(get_affinity(0)))
        except OSError:
            pass
    return float(os.cpu_count() or 0)


def _cpu_quota() -> float | None:
    cpu_max = _read_text("/sys/fs/cgroup/cpu.max")
    if cpu_max:
        parts = cpu_max.split()
        if len(parts) == 2 and parts[0] != "max":
            try:
                quota, period = float(parts[0]), float(parts[1])
                if quota > 0 and period > 0:
                    return quota / period
            except ValueError:
                pass

    raw_quota = _read_text("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    raw_period = _read_text("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    if raw_quota and raw_period:
        try:
            quota, period = float(raw_quota), float(raw_period)
            if quota > 0 and period > 0:
                return quota / period
        except ValueError:
            pass
    return None


def _probe_cpu_cores() -> float:
    affinity = _cpu_affinity_count()
    quota = _cpu_quota()
    if quota is not None and affinity > 0:
        return round(min(affinity, quota), 3)
    return round(affinity, 3)


def _physical_ram_mb() -> int:
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, TypeError, ValueError):
        return 0
    return max(0, pages * page_size // (1024 * 1024))


def _cgroup_ram_limit_mb() -> int | None:
    for path in (
        "/sys/fs/cgroup/memory.max",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",
    ):
        raw = _read_text(path)
        if not raw or raw == "max":
            continue
        try:
            limit_bytes = int(raw)
        except ValueError:
            continue
        # cgroup v1 represents unlimited memory using a very large sentinel.
        if 0 < limit_bytes < (1 << 60):
            return limit_bytes // (1024 * 1024)
    return None


def _probe_ram_mb() -> int:
    physical = _physical_ram_mb()
    cgroup_limit = _cgroup_ram_limit_mb()
    if cgroup_limit is not None and physical > 0:
        return min(physical, cgroup_limit)
    return cgroup_limit or physical


def _configured_gpu_vram() -> dict[str, int] | None:
    raw = os.getenv("AIDN_RESOURCE_GPU_VRAM_JSON")
    if raw is None:
        return None
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("AIDN_RESOURCE_GPU_VRAM_JSON must be a JSON object")
    return {str(device): int(amount) for device, amount in payload.items()}


def _probe_nvidia_vram() -> tuple[dict[str, int], dict[str, int], str | None]:
    query = [
        "nvidia-smi",
        "--query-gpu=index,memory.total,memory.used",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            query,
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
    except FileNotFoundError:
        return {}, {}, "nvidia-smi is not installed; NVIDIA VRAM is not reported"
    except (OSError, subprocess.TimeoutExpired):
        return {}, {}, "nvidia-smi did not complete; NVIDIA VRAM is not reported"

    if result.returncode != 0:
        return {}, {}, "nvidia-smi could not access a GPU; NVIDIA VRAM is not reported"

    devices: dict[str, int] = {}
    measured: dict[str, int] = {}
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) not in {2, 3}:
            continue
        try:
            index, amount = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if amount >= 0:
            device_id = f"gpu{index}"
            devices[device_id] = amount
            if len(parts) == 3:
                try:
                    used = int(parts[2])
                except ValueError:
                    used = -1
                if 0 <= used <= amount:
                    measured[device_id] = used
    limitation = None
    if devices and len(measured) != len(devices):
        limitation = "NVIDIA VRAM total was measured, but one or more usage readings were unavailable"
    return devices, measured, limitation


@dataclass(frozen=True)
class ResourceProbeReport:
    capacity: NodeCapacity
    source: str
    observed_at: str
    limitations: tuple[str, ...] = ()
    measured_vram_mb: dict[str, int] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": RESOURCE_PROBE_SCHEMA_VERSION,
            "source": self.source,
            "observed_at": self.observed_at,
            "capacity": self.capacity.model_dump(mode="json"),
            "measured_vram_mb": dict(self.measured_vram_mb),
            "limitations": list(self.limitations),
        }

    def metadata(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "observed_at": self.observed_at,
            "limitations": list(self.limitations),
            "gpu_reported": bool(self.capacity.gpu_devices),
            "measured_vram_mb": dict(self.measured_vram_mb),
        }


def probe_host_resources(*, source: str = "runtime-auto-probe") -> ResourceProbeReport:
    limitations: list[str] = []
    cpu_cores = _probe_cpu_cores()
    ram_mb = _probe_ram_mb()

    configured_vram = _configured_gpu_vram()
    measured_vram_mb: dict[str, int] = {}
    if configured_vram is None:
        vram_mb, measured_vram_mb, gpu_limitation = _probe_nvidia_vram()
        if gpu_limitation:
            limitations.append(gpu_limitation)
    else:
        vram_mb = configured_vram

    if cpu_cores <= 0:
        limitations.append("CPU capacity could not be measured")
    if ram_mb <= 0:
        limitations.append("RAM capacity could not be measured")

    capacity = NodeCapacity(
        cpu_cores=cpu_cores,
        ram_mb=ram_mb,
        gpu_devices=list(vram_mb),
        vram_mb=vram_mb,
    )
    return ResourceProbeReport(
        capacity=capacity,
        source=source,
        observed_at=datetime.now(UTC).isoformat(),
        limitations=tuple(limitations),
        measured_vram_mb=measured_vram_mb,
    )


def write_resource_probe_report(report: ResourceProbeReport, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(
        json.dumps(report.as_payload(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def read_resource_probe_report(path: str | Path) -> ResourceProbeReport:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != RESOURCE_PROBE_SCHEMA_VERSION:
        raise ValueError("unsupported resource probe schema version")
    raw_measured_vram = payload.get("measured_vram_mb") or {}
    # The field was added as an optional extension to schema v1.  Treat a
    # malformed/legacy value as absent rather than making the whole capacity
    # report unloadable; admission then remains conservative and can expose
    # the probe limitation in its normal metadata.
    if not isinstance(raw_measured_vram, Mapping):
        raw_measured_vram = {}
    return ResourceProbeReport(
        capacity=NodeCapacity.model_validate(payload["capacity"]),
        source=str(payload.get("source") or "capacity-file"),
        observed_at=str(payload.get("observed_at") or "unknown"),
        limitations=tuple(str(item) for item in payload.get("limitations", [])),
        measured_vram_mb={
            str(device): int(amount)
            for device, amount in raw_measured_vram.items()
            if _is_non_negative_int(amount)
        },
    )


def _is_non_negative_int(value: Any) -> bool:
    try:
        return int(value) >= 0
    except (TypeError, ValueError):
        return False


def load_resource_probe_from_environment(
    environ: Mapping[str, str] | None = None,
) -> ResourceProbeReport:
    values = os.environ if environ is None else environ
    mode = values.get("AIDN_RESOURCE_PROBE_MODE", "auto").strip().lower()
    if mode not in {"auto", "disabled"}:
        raise ValueError("AIDN_RESOURCE_PROBE_MODE must be auto or disabled")
    if mode == "disabled":
        return ResourceProbeReport(
            capacity=NodeCapacity(cpu_cores=0, ram_mb=0),
            source="disabled",
            observed_at=datetime.now(UTC).isoformat(),
            limitations=("automatic host capacity probing is disabled",),
        )

    capacity_path = values.get("AIDN_RESOURCE_CAPACITY_PATH")
    if capacity_path:
        try:
            return read_resource_probe_report(capacity_path)
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            fallback = probe_host_resources(source="runtime-auto-probe")
            return ResourceProbeReport(
                capacity=fallback.capacity,
                source=fallback.source,
                observed_at=fallback.observed_at,
                limitations=(
                    f"configured capacity file was unavailable or invalid: {type(error).__name__}",
                    *fallback.limitations,
                ),
            )
    return probe_host_resources(source="runtime-auto-probe")


def refresh_resource_probe_from_environment() -> ResourceProbeReport:
    mode = os.getenv("AIDN_RESOURCE_PROBE_MODE", "auto").strip().lower()
    if mode == "disabled":
        return load_resource_probe_from_environment()
    report = probe_host_resources(source="operator-refresh")
    capacity_path = os.getenv("AIDN_RESOURCE_CAPACITY_PATH")
    if capacity_path:
        write_resource_probe_report(report, capacity_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure AiDN host capacity")
    parser.add_argument("--output", required=True, help="capacity report JSON path")
    parser.add_argument("--source", default="operator-bootstrap")
    args = parser.parse_args(argv)
    report = probe_host_resources(source=args.source)
    write_resource_probe_report(report, args.output)
    print(json.dumps(report.as_payload(), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())
