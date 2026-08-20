from collections.abc import Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Any

from aidn_hypervisor.domain.models import NodeCapacity


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    cpu: float
    ram_mb: int
    vram_mb: int


class ResourceAdmissionError(ValueError):
    """A runtime/request cannot be admitted with current measured capacity."""

    code = "RESOURCE_ADMISSION_DENIED"

    def __init__(self, message: str = "insufficient resources", *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


class ResourceOrchestrator:
    def __init__(
        self,
        capacity: NodeCapacity,
        *,
        probe: Mapping[str, Any] | None = None,
    ) -> None:
        self.capacity = capacity
        self.probe = dict(probe or {})
        self._measured_vram_mb = self._read_measured_vram(self.probe)
        self._reservations: dict[str, Reservation] = {}
        self._lock = RLock()

    def replace_capacity(
        self,
        capacity: NodeCapacity,
        *,
        probe: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            reserved_cpu = sum(item.cpu for item in self._reservations.values())
            reserved_ram = sum(item.ram_mb for item in self._reservations.values())
            reserved_vram = sum(item.vram_mb for item in self._reservations.values())
            if (
                reserved_cpu > capacity.cpu_cores
                or reserved_ram > capacity.ram_mb
                or reserved_vram > sum(capacity.vram_mb.values())
            ):
                raise ValueError("probed capacity is below active reservations")
            self.capacity = capacity
            self.probe = dict(probe or {})
            self._measured_vram_mb = self._read_measured_vram(self.probe)

    def _validate_request(self, cpu: float, ram_mb: int, vram_mb: int) -> None:
        if cpu < 0 or ram_mb < 0 or vram_mb < 0:
            raise ValueError("resource request values must be non-negative")

    def can_fit(self, cpu: float, ram_mb: int, vram_mb: int) -> bool:
        return bool(self.fit_report(cpu, ram_mb, vram_mb)["fits"])

    def fit_report(self, cpu: float, ram_mb: int, vram_mb: int) -> dict[str, float | int | bool]:
        with self._lock:
            return self._fit_report(cpu, ram_mb, vram_mb)

    def _fit_report(self, cpu: float, ram_mb: int, vram_mb: int) -> dict[str, float | int | bool]:
        if cpu < 0 or ram_mb < 0 or vram_mb < 0:
            return {
                "fits": False,
                "cpu_shortfall": max(0.0, -cpu),
                "ram_mb_shortfall": max(0, -ram_mb),
                "vram_mb_shortfall": max(0, -vram_mb),
            }

        used_cpu = sum(item.cpu for item in self._reservations.values())
        used_ram = sum(item.ram_mb for item in self._reservations.values())
        total_vram = sum(self.capacity.vram_mb.values())
        reserved_vram = sum(item.vram_mb for item in self._reservations.values())
        measured_vram = min(sum(self._measured_vram_mb.values()), total_vram)
        # Measured device usage already includes AiDN processes.  Use the
        # larger of lease accounting and measurement so a known runtime is not
        # double-counted while an unprofiled/external process still reduces
        # allocatable capacity.
        used_vram = max(reserved_vram, measured_vram)
        return {
            "fits": (
                used_cpu + cpu <= self.capacity.cpu_cores
                and used_ram + ram_mb <= self.capacity.ram_mb
                and used_vram + vram_mb <= total_vram
            ),
            "cpu_shortfall": max(0.0, used_cpu + cpu - self.capacity.cpu_cores),
            "ram_mb_shortfall": max(0, used_ram + ram_mb - self.capacity.ram_mb),
            "vram_mb_shortfall": max(0, used_vram + vram_mb - total_vram),
        }

    def admission_report(self, *, cpu: float, ram_mb: int, vram_mb: int) -> dict[str, object]:
        """Return an actionable admission decision for a resource lease."""

        with self._lock:
            fit = self._fit_report(cpu=cpu, ram_mb=ram_mb, vram_mb=vram_mb)
            snapshot = self._summary()
            return {
                "allowed": bool(fit["fits"]),
                "reason": "admitted" if fit["fits"] else "resource_wait",
                "required": {"cpu": cpu, "ram_mb": ram_mb, "vram_mb": vram_mb},
                "free": snapshot["free"],
                "shortfall": {
                    "cpu": fit["cpu_shortfall"],
                    "ram_mb": fit["ram_mb_shortfall"],
                    "vram_mb": fit["vram_mb_shortfall"],
                },
            }

    def lease_snapshot(self) -> list[dict[str, float | int | str]]:
        """Return the active Resource Broker leases in a stable read shape.

        The scheduler and MCP projections deliberately expose leases as a
        read model instead of leaking the internal ``Reservation`` objects.
        Sorting by id makes the response deterministic for agents and tests.
        """

        with self._lock:
            return [
                {
                    "reservation_id": reservation.reservation_id,
                    "cpu": reservation.cpu,
                    "ram_mb": reservation.ram_mb,
                    "vram_mb": reservation.vram_mb,
                }
                for reservation in sorted(
                    self._reservations.values(), key=lambda item: item.reservation_id
                )
            ]

    def leases(self) -> list[dict[str, float | int | str]]:
        """Compatibility alias for callers that use the RFC's ``leases`` term."""

        return self.lease_snapshot()

    def forecast(self, *, cpu: float, ram_mb: int, vram_mb: int) -> dict[str, object]:
        """Explain whether a new lease can be admitted right now.

        This is intentionally side-effect free.  A forecast never reserves
        capacity and is therefore safe for dashboards, MCP agents, and
        schedulers to call repeatedly while a request is waiting.
        """

        self._validate_request(cpu=cpu, ram_mb=ram_mb, vram_mb=vram_mb)
        report = self.admission_report(cpu=cpu, ram_mb=ram_mb, vram_mb=vram_mb)
        return {
            "decision": "ADMIT" if report["allowed"] else "RESOURCE_WAIT",
            "retryable": not bool(report["allowed"]),
            "required": report["required"],
            "free": report["free"],
            "shortfall": report["shortfall"],
            "leases": self.lease_snapshot(),
            "measured_vram_mb": dict(self._measured_vram_mb),
            "capacity": {
                "cpu": self.capacity.cpu_cores,
                "ram_mb": self.capacity.ram_mb,
                "vram_mb": dict(self.capacity.vram_mb),
            },
        }

    def reserve(self, reservation_id: str, cpu: float, ram_mb: int, vram_mb: int) -> Reservation:
        with self._lock:
            self._validate_request(cpu=cpu, ram_mb=ram_mb, vram_mb=vram_mb)

            if reservation_id in self._reservations:
                raise ValueError("reservation_id already exists")

            report = self.admission_report(cpu=cpu, ram_mb=ram_mb, vram_mb=vram_mb)
            if not report["allowed"]:
                raise ResourceAdmissionError(details=report)

            reservation = Reservation(
                reservation_id=reservation_id,
                cpu=cpu,
                ram_mb=ram_mb,
                vram_mb=vram_mb,
            )
            self._reservations[reservation_id] = reservation
            return reservation

    def release(self, reservation_id: str) -> None:
        with self._lock:
            self._reservations.pop(reservation_id, None)

    def summary(self) -> dict[str, object]:
        with self._lock:
            return self._summary()

    def _summary(self) -> dict[str, object]:
        reserved_cpu = sum(item.cpu for item in self._reservations.values())
        reserved_ram = sum(item.ram_mb for item in self._reservations.values())
        reserved_vram = sum(item.vram_mb for item in self._reservations.values())
        total_vram = sum(self.capacity.vram_mb.values())
        measured_vram = min(sum(self._measured_vram_mb.values()), total_vram)
        used_vram = max(reserved_vram, measured_vram)

        summary: dict[str, object] = {
            "total": {
                "cpu": self.capacity.cpu_cores,
                "ram_mb": self.capacity.ram_mb,
                "vram_mb": total_vram,
            },
            "reserved": {
                "cpu": reserved_cpu,
                "ram_mb": reserved_ram,
                "vram_mb": reserved_vram,
            },
            "free": {
                "cpu": self.capacity.cpu_cores - reserved_cpu,
                "ram_mb": self.capacity.ram_mb - reserved_ram,
                "vram_mb": total_vram - used_vram,
            },
        }
        if self.probe:
            summary["probe"] = dict(self.probe)
        return summary

    @staticmethod
    def _read_measured_vram(probe: Mapping[str, Any]) -> dict[str, int]:
        raw = probe.get("measured_vram_mb", probe.get("external_vram_mb", {}))
        if not isinstance(raw, Mapping):
            return {}
        result: dict[str, int] = {}
        for device, amount in raw.items():
            try:
                value = int(amount)
            except (TypeError, ValueError):
                continue
            if value >= 0:
                result[str(device)] = value
        return result
