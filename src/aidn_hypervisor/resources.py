from dataclasses import dataclass

from aidn_hypervisor.domain.models import NodeCapacity


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    cpu: float
    ram_mb: int
    vram_mb: int


class ResourceOrchestrator:
    def __init__(self, capacity: NodeCapacity) -> None:
        self.capacity = capacity
        self._reservations: dict[str, Reservation] = {}

    def _validate_request(self, cpu: float, ram_mb: int, vram_mb: int) -> None:
        if cpu < 0 or ram_mb < 0 or vram_mb < 0:
            raise ValueError("resource request values must be non-negative")

    def can_fit(self, cpu: float, ram_mb: int, vram_mb: int) -> bool:
        return bool(self.fit_report(cpu, ram_mb, vram_mb)["fits"])

    def fit_report(self, cpu: float, ram_mb: int, vram_mb: int) -> dict[str, float | int | bool]:
        if cpu < 0 or ram_mb < 0 or vram_mb < 0:
            return {
                "fits": False,
                "cpu_shortfall": max(0.0, -cpu),
                "ram_mb_shortfall": max(0, -ram_mb),
                "vram_mb_shortfall": max(0, -vram_mb),
            }

        used_cpu = sum(item.cpu for item in self._reservations.values())
        used_ram = sum(item.ram_mb for item in self._reservations.values())
        used_vram = sum(item.vram_mb for item in self._reservations.values())
        total_vram = sum(self.capacity.vram_mb.values())
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

    def reserve(self, reservation_id: str, cpu: float, ram_mb: int, vram_mb: int) -> Reservation:
        self._validate_request(cpu=cpu, ram_mb=ram_mb, vram_mb=vram_mb)

        if reservation_id in self._reservations:
            raise ValueError("reservation_id already exists")

        if not self.can_fit(cpu=cpu, ram_mb=ram_mb, vram_mb=vram_mb):
            raise ValueError("insufficient resources")

        reservation = Reservation(
            reservation_id=reservation_id,
            cpu=cpu,
            ram_mb=ram_mb,
            vram_mb=vram_mb,
        )
        self._reservations[reservation_id] = reservation
        return reservation

    def release(self, reservation_id: str) -> None:
        self._reservations.pop(reservation_id, None)

    def summary(self) -> dict[str, dict[str, float | int]]:
        reserved_cpu = sum(item.cpu for item in self._reservations.values())
        reserved_ram = sum(item.ram_mb for item in self._reservations.values())
        reserved_vram = sum(item.vram_mb for item in self._reservations.values())
        total_vram = sum(self.capacity.vram_mb.values())

        return {
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
                "vram_mb": total_vram - reserved_vram,
            },
        }
