from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import os
from threading import RLock
from typing import Any, Callable

from aidn_hypervisor.domain.models import NodeCapacity


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    cpu: float
    ram_mb: int
    vram_mb: int


@dataclass(frozen=True)
class ResourceLease:
    """Durable read model for one atomic local resource lease.

    ``Reservation`` remains the small backwards-compatible value returned by
    ``reserve``.  New admission paths use this richer object so a lease can be
    inspected across requested/granted/active/released transitions without
    leaking the orchestrator's mutable maps.
    """

    lease_id: str
    cpu: float
    ram_mb: int
    vram_mb: int
    status: str = "ACTIVE"
    owner_id: str | None = None
    created_at: str = ""
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "reservation_id": self.lease_id,
            "cpu": self.cpu,
            "ram_mb": self.ram_mb,
            "vram_mb": self.vram_mb,
            "status": self.status,
            "owner_id": self.owner_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ResourceSafetyPolicy:
    """Headroom kept outside normal local admission.

    Directly constructed orchestrators default to zero headroom for backwards
    compatibility with the test/in-memory service.  Production bootstrap uses
    ``from_environment`` which supplies conservative VRAM and RAM defaults.
    """

    vram_min_mb: int = 0
    vram_ratio: float = 0.0
    ram_min_mb: int = 0
    ram_ratio: float = 0.0
    cpu_min_cores: float = 0.0
    cpu_ratio: float = 0.0
    storage_min_mb: int = 0

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        production_defaults: bool = True,
    ) -> "ResourceSafetyPolicy":
        values = os.environ if environ is None else environ
        defaults = {
            "VRAM_SAFETY_MB": "1024" if production_defaults else "0",
            "VRAM_SAFETY_RATIO": "0.05" if production_defaults else "0",
            "RAM_SAFETY_MB": "4096" if production_defaults else "0",
            "RAM_SAFETY_RATIO": "0.10" if production_defaults else "0",
            "CPU_SAFETY_CORES": "0",
            "CPU_SAFETY_RATIO": "0",
            "STORAGE_SAFETY_MB": "0",
        }

        def integer(name: str) -> int:
            raw = values.get(f"AIDN_RESOURCE_{name.upper()}", defaults[name])
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                return int(defaults[name])

        def number(name: str) -> float:
            raw = values.get(f"AIDN_RESOURCE_{name.upper()}", defaults[name])
            try:
                return max(0.0, float(raw))
            except (TypeError, ValueError):
                return float(defaults[name])

        return cls(
            vram_min_mb=integer("VRAM_SAFETY_MB"),
            vram_ratio=number("VRAM_SAFETY_RATIO"),
            ram_min_mb=integer("RAM_SAFETY_MB"),
            ram_ratio=number("RAM_SAFETY_RATIO"),
            cpu_min_cores=number("CPU_SAFETY_CORES"),
            cpu_ratio=number("CPU_SAFETY_RATIO"),
            storage_min_mb=integer("STORAGE_SAFETY_MB"),
        )

    def headroom(self, *, cpu: float, ram_mb: int, vram_mb: int) -> dict[str, float | int]:
        return {
            "cpu": min(cpu, max(self.cpu_min_cores, cpu * self.cpu_ratio)),
            "ram_mb": min(ram_mb, max(self.ram_min_mb, int(ram_mb * self.ram_ratio))),
            "vram_mb": min(vram_mb, max(self.vram_min_mb, int(vram_mb * self.vram_ratio))),
            "storage_mb": max(0, self.storage_min_mb),
        }

    def as_payload(self, *, capacity: NodeCapacity) -> dict[str, float | int]:
        return self.headroom(
            cpu=capacity.cpu_cores,
            ram_mb=capacity.ram_mb,
            vram_mb=sum(capacity.vram_mb.values()),
        )


class ResourceAdmissionError(ValueError):
    """A runtime/request cannot be admitted with current measured capacity."""

    code = "RESOURCE_ADMISSION_DENIED"

    def __init__(self, message: str = "insufficient resources", *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


class ResourceReconciliationRequiredError(ResourceAdmissionError):
    """The broker is not confident enough to admit a new cold workload."""

    code = "RESOURCE_RECONCILIATION_REQUIRED"


class ResourceOrchestrator:
    _ACTIVE_LEASE_STATUSES = {"REQUESTED", "GRANTED", "ACTIVE"}
    _TERMINAL_LEASE_STATUSES = {"RELEASED", "EXPIRED", "REVOKED"}

    def __init__(
        self,
        capacity: NodeCapacity,
        *,
        probe: Mapping[str, Any] | None = None,
        safety: ResourceSafetyPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.capacity = capacity
        self.probe = dict(probe or {})
        self.safety = safety or ResourceSafetyPolicy()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._measured_vram_mb = self._read_measured_vram(self.probe)
        self._measured_cpu = self._read_non_negative_float(self.probe.get("measured_cpu_cores"))
        self._measured_ram_mb = self._read_non_negative_int(self.probe.get("measured_ram_mb"))
        self._reservations: dict[str, Reservation] = {}
        self._leases: dict[str, ResourceLease] = {}
        self._reconciliation_state = "TRUSTED"
        self._reconciliation_reason: str | None = None
        self._last_reconciled_at: str | None = self.probe.get("observed_at")
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
            self._measured_cpu = self._read_non_negative_float(self.probe.get("measured_cpu_cores"))
            self._measured_ram_mb = self._read_non_negative_int(self.probe.get("measured_ram_mb"))
            self._reconciliation_state = "TRUSTED"
            self._reconciliation_reason = None
            self._last_reconciled_at = self.probe.get("observed_at") or self._now_iso()

    def reconcile_hardware(
        self,
        capacity: NodeCapacity,
        *,
        probe: Mapping[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        """Refresh physical truth and fail closed if reservations no longer fit.

        Unlike ``replace_capacity`` (kept as a strict compatibility API), a
        reconciliation never throws merely because a machine lost capacity.
        It records an uncertain state and denies new leases until a trusted
        measurement proves the active reservations fit again.
        """

        with self._lock:
            self.capacity = capacity
            self.probe = dict(probe or {})
            self._measured_vram_mb = self._read_measured_vram(self.probe)
            self._measured_cpu = self._read_non_negative_float(self.probe.get("measured_cpu_cores"))
            self._measured_ram_mb = self._read_non_negative_int(self.probe.get("measured_ram_mb"))
            self._last_reconciled_at = observed_at or self.probe.get("observed_at") or self._now_iso()
            reserved = {
                "cpu": sum(item.cpu for item in self._reservations.values()),
                "ram_mb": sum(item.ram_mb for item in self._reservations.values()),
                "vram_mb": sum(item.vram_mb for item in self._reservations.values()),
            }
            fit = self._fit_report(0, 0, 0)
            if (
                reserved["cpu"] > fit["allocatable_cpu"]
                or reserved["ram_mb"] > fit["allocatable_ram_mb"]
                or reserved["vram_mb"] > fit["allocatable_vram_mb"]
            ):
                self._reconciliation_state = "UNCERTAIN"
                self._reconciliation_reason = "active leases exceed trusted allocatable capacity"
            else:
                self._reconciliation_state = "TRUSTED"
                self._reconciliation_reason = None
            return self.hardware_status()

    def reconciliation_status(self) -> dict[str, str | None]:
        with self._lock:
            return {
                "state": self._reconciliation_state,
                "reason": self._reconciliation_reason,
                "last_reconciled_at": self._last_reconciled_at,
            }

    def _validate_request(self, cpu: float, ram_mb: int, vram_mb: int) -> None:
        if cpu < 0 or ram_mb < 0 or vram_mb < 0:
            raise ValueError("resource request values must be non-negative")

    def can_fit(self, cpu: float, ram_mb: int, vram_mb: int) -> bool:
        return bool(self.fit_report(cpu, ram_mb, vram_mb)["fits"])

    def fit_report(self, cpu: float, ram_mb: int, vram_mb: int) -> dict[str, float | int | bool]:
        with self._lock:
            self._expire_leases_unlocked()
            return self._fit_report(cpu, ram_mb, vram_mb)

    def _fit_report(self, cpu: float, ram_mb: int, vram_mb: int) -> dict[str, float | int | bool]:
        if cpu < 0 or ram_mb < 0 or vram_mb < 0:
            return {
                "fits": False,
                "cpu_shortfall": max(0.0, -cpu),
                "ram_mb_shortfall": max(0, -ram_mb),
                "vram_mb_shortfall": max(0, -vram_mb),
            }

        reserved_cpu = sum(item.cpu for item in self._reservations.values())
        reserved_ram = sum(item.ram_mb for item in self._reservations.values())
        total_vram = sum(self.capacity.vram_mb.values())
        reserved_vram = sum(item.vram_mb for item in self._reservations.values())
        measured_vram = min(sum(self._measured_vram_mb.values()), total_vram)
        # Measured device usage already includes AiDN processes.  Use the
        # larger of lease accounting and measurement so a known runtime is not
        # double-counted while an unprofiled/external process still reduces
        # allocatable capacity.
        used_cpu = max(reserved_cpu, self._measured_cpu)
        used_ram = max(reserved_ram, self._measured_ram_mb)
        used_vram = max(reserved_vram, measured_vram)
        headroom = self.safety.headroom(
            cpu=self.capacity.cpu_cores,
            ram_mb=self.capacity.ram_mb,
            vram_mb=total_vram,
        )
        allocatable_cpu = self.capacity.cpu_cores - float(headroom["cpu"])
        allocatable_ram = self.capacity.ram_mb - int(headroom["ram_mb"])
        allocatable_vram = total_vram - int(headroom["vram_mb"])
        return {
            "fits": (
                self._reconciliation_state == "TRUSTED"
                and used_cpu + cpu <= allocatable_cpu
                and used_ram + ram_mb <= allocatable_ram
                and used_vram + vram_mb <= allocatable_vram
            ),
            "cpu_shortfall": max(0.0, used_cpu + cpu - allocatable_cpu),
            "ram_mb_shortfall": max(0, used_ram + ram_mb - allocatable_ram),
            "vram_mb_shortfall": max(0, used_vram + vram_mb - allocatable_vram),
            "allocatable_cpu": allocatable_cpu,
            "allocatable_ram_mb": allocatable_ram,
            "allocatable_vram_mb": allocatable_vram,
            "reconciliation_state": self._reconciliation_state,
        }

    def admission_report(self, *, cpu: float, ram_mb: int, vram_mb: int) -> dict[str, object]:
        """Return an actionable admission decision for a resource lease."""

        with self._lock:
            self._expire_leases_unlocked()
            fit = self._fit_report(cpu=cpu, ram_mb=ram_mb, vram_mb=vram_mb)
            snapshot = self._summary()
            allowed = bool(fit["fits"])
            if self._reconciliation_state != "TRUSTED":
                reason = "reconciliation_required"
            else:
                reason = "admitted" if allowed else "resource_wait"
            return {
                "allowed": allowed,
                "reason": reason,
                "required": {"cpu": cpu, "ram_mb": ram_mb, "vram_mb": vram_mb},
                "free": snapshot["free"],
                "shortfall": {
                    "cpu": fit["cpu_shortfall"],
                    "ram_mb": fit["ram_mb_shortfall"],
                    "vram_mb": fit["vram_mb_shortfall"],
                },
                "reconciliation": self.reconciliation_status(),
            }

    def lease_snapshot(self) -> list[dict[str, float | int | str]]:
        """Return the active Resource Broker leases in a stable read shape.

        The scheduler and MCP projections deliberately expose leases as a
        read model instead of leaking the internal ``Reservation`` objects.
        Sorting by id makes the response deterministic for agents and tests.
        """

        with self._lock:
            self._expire_leases_unlocked()
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

    def lease_details(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        """Return lifecycle-aware lease records for operators and agents."""

        with self._lock:
            self._expire_leases_unlocked()
            records = self._leases.values()
            if not include_inactive:
                records = [item for item in records if item.status in {"REQUESTED", "GRANTED", "ACTIVE"}]
            return [
                item.as_payload()
                for item in sorted(records, key=lambda lease: lease.lease_id)
            ]

    def has_active_lease(self, lease_id: str) -> bool:
        with self._lock:
            return lease_id in self._reservations

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
        lease = self.acquire_lease(
            reservation_id,
            cpu=cpu,
            ram_mb=ram_mb,
            vram_mb=vram_mb,
        )
        return Reservation(
            reservation_id=lease.lease_id,
            cpu=lease.cpu,
            ram_mb=lease.ram_mb,
            vram_mb=lease.vram_mb,
        )

    def acquire_lease(
        self,
        lease_id: str,
        *,
        cpu: float,
        ram_mb: int,
        vram_mb: int,
        owner_id: str | None = None,
        lease_seconds: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        status: str = "ACTIVE",
    ) -> ResourceLease:
        """Atomically admit and create a lifecycle-aware local lease."""

        with self._lock:
            self._validate_request(cpu=cpu, ram_mb=ram_mb, vram_mb=vram_mb)
            if not isinstance(lease_id, str) or not lease_id.strip():
                raise ValueError("lease_id must be a non-empty string")
            if lease_seconds is not None and (isinstance(lease_seconds, bool) or lease_seconds <= 0):
                raise ValueError("lease_seconds must be a positive integer")
            existing = self._leases.get(lease_id)
            if lease_id in self._reservations or (
                existing is not None
                and existing.status in {"REQUESTED", "GRANTED", "ACTIVE"}
            ):
                raise ValueError("reservation_id already exists")
            if existing is not None and existing.status in {"RELEASED", "EXPIRED", "REVOKED"}:
                self._leases.pop(lease_id, None)
            report = self.admission_report(cpu=cpu, ram_mb=ram_mb, vram_mb=vram_mb)
            if self._reconciliation_state != "TRUSTED":
                raise ResourceReconciliationRequiredError(
                    "resource reconciliation required before new lease admission",
                    details=report,
                )
            if not report["allowed"]:
                raise ResourceAdmissionError(details=report)
            now = self._clock()
            created_at = now.isoformat()
            expires_at = (
                (now + timedelta(seconds=lease_seconds)).isoformat()
                if lease_seconds is not None
                else None
            )
            lease = ResourceLease(
                lease_id=lease_id,
                cpu=cpu,
                ram_mb=ram_mb,
                vram_mb=vram_mb,
                status=status,
                owner_id=owner_id,
                created_at=created_at,
                expires_at=expires_at,
                metadata=dict(metadata or {}),
            )
            reservation = Reservation(
                reservation_id=lease_id,
                cpu=cpu,
                ram_mb=ram_mb,
                vram_mb=vram_mb,
            )
            self._leases[lease_id] = lease
            self._reservations[lease_id] = reservation
            return lease

    def request_lease(
        self,
        lease_id: str,
        *,
        cpu: float,
        ram_mb: int,
        vram_mb: int,
        owner_id: str | None = None,
        lease_seconds: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ResourceLease:
        """Reserve capacity in the provisional/requested lifecycle state."""

        return self.acquire_lease(
            lease_id,
            cpu=cpu,
            ram_mb=ram_mb,
            vram_mb=vram_mb,
            owner_id=owner_id,
            lease_seconds=lease_seconds,
            metadata=metadata,
            status="REQUESTED",
        )

    def activate_lease(self, lease_id: str) -> ResourceLease:
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None:
                raise KeyError(lease_id)
            if lease.status not in {"REQUESTED", "GRANTED", "ACTIVE"}:
                raise ValueError(f"lease {lease_id} is not activatable")
            if lease.status == "ACTIVE":
                return lease
            updated = ResourceLease(
                lease_id=lease.lease_id,
                cpu=lease.cpu,
                ram_mb=lease.ram_mb,
                vram_mb=lease.vram_mb,
                status="ACTIVE",
                owner_id=lease.owner_id,
                created_at=lease.created_at,
                expires_at=lease.expires_at,
                metadata=dict(lease.metadata),
            )
            self._leases[lease_id] = updated
            return updated

    def release_lease(self, lease_id: str, *, status: str = "RELEASED") -> ResourceLease | None:
        with self._lock:
            if status not in self._TERMINAL_LEASE_STATUSES:
                raise ValueError(f"invalid terminal lease status: {status}")
            lease = self._leases.get(lease_id)
            if lease is None:
                self._reservations.pop(lease_id, None)
                return None
            if lease.status not in {"RELEASED", "EXPIRED", "REVOKED"}:
                self._reservations.pop(lease_id, None)
                self._leases[lease_id] = ResourceLease(
                    lease_id=lease.lease_id,
                    cpu=lease.cpu,
                    ram_mb=lease.ram_mb,
                    vram_mb=lease.vram_mb,
                    status=status,
                    owner_id=lease.owner_id,
                    created_at=lease.created_at,
                    expires_at=lease.expires_at,
                    metadata=dict(lease.metadata),
                )
            return self._leases[lease_id]

    def revoke_lease(self, lease_id: str) -> ResourceLease | None:
        return self.release_lease(lease_id, status="REVOKED")

    def expire_leases(self, *, now: datetime | None = None) -> list[str]:
        current = now or self._clock()
        expired: list[str] = []
        with self._lock:
            expired = self._expire_leases_unlocked(now=current)
        return expired

    def _expire_leases_unlocked(self, *, now: datetime | None = None) -> list[str]:
        current = now or self._clock()
        expired: list[str] = []
        for lease in list(self._leases.values()):
            if lease.status not in self._ACTIVE_LEASE_STATUSES or not lease.expires_at:
                continue
            try:
                expiry = datetime.fromisoformat(lease.expires_at)
            except ValueError:
                continue
            if expiry <= current:
                self.release_lease(lease.lease_id, status="EXPIRED")
                expired.append(lease.lease_id)
        return expired

    def restore_leases(
        self,
        records: list[Mapping[str, Any]],
        *,
        replace: bool = False,
        exclude_prefixes: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Restore active leases after restart without optimistic admission."""

        with self._lock:
            if replace:
                self._reservations.clear()
                self._leases.clear()
            restored: list[str] = []
            rejected: list[str] = []
            expired: list[str] = []
            now = self._clock()
            for raw in records:
                lease_id = str(raw.get("lease_id") or raw.get("reservation_id") or "").strip()
                if not lease_id or lease_id.startswith(exclude_prefixes):
                    continue
                status = str(raw.get("status") or "ACTIVE")
                if status not in {"REQUESTED", "GRANTED", "ACTIVE"}:
                    continue
                expires_at = raw.get("expires_at")
                if expires_at:
                    try:
                        if datetime.fromisoformat(str(expires_at)) <= now:
                            expired.append(lease_id)
                            continue
                    except ValueError:
                        rejected.append(lease_id)
                        continue
                try:
                    lease = ResourceLease(
                        lease_id=lease_id,
                        cpu=float(raw.get("cpu", 0)),
                        ram_mb=int(raw.get("ram_mb", 0)),
                        vram_mb=int(raw.get("vram_mb", 0)),
                        status=status,
                        owner_id=raw.get("owner_id"),
                        created_at=str(raw.get("created_at") or self._now_iso()),
                        expires_at=expires_at,
                        metadata=dict(raw.get("metadata") or {}),
                    )
                    self._validate_request(lease.cpu, lease.ram_mb, lease.vram_mb)
                except (TypeError, ValueError):
                    rejected.append(lease_id)
                    continue
                if lease_id in self._reservations:
                    rejected.append(lease_id)
                    continue
                self._leases[lease_id] = lease
                self._reservations[lease_id] = Reservation(
                    reservation_id=lease_id,
                    cpu=lease.cpu,
                    ram_mb=lease.ram_mb,
                    vram_mb=lease.vram_mb,
                )
                restored.append(lease_id)
            allocatable = self.safety.headroom(
                cpu=self.capacity.cpu_cores,
                ram_mb=self.capacity.ram_mb,
                vram_mb=sum(self.capacity.vram_mb.values()),
            )
            reserved = {
                "cpu": sum(item.cpu for item in self._reservations.values()),
                "ram_mb": sum(item.ram_mb for item in self._reservations.values()),
                "vram_mb": sum(item.vram_mb for item in self._reservations.values()),
            }
            if (
                rejected
                or reserved["cpu"] > self.capacity.cpu_cores - float(allocatable["cpu"])
                or reserved["ram_mb"] > self.capacity.ram_mb - int(allocatable["ram_mb"])
                or reserved["vram_mb"] > sum(self.capacity.vram_mb.values()) - int(allocatable["vram_mb"])
            ):
                self._reconciliation_state = "UNCERTAIN"
                self._reconciliation_reason = "persisted leases require hardware reconciliation"
            return {
                "restored": restored,
                "rejected": rejected,
                "expired": expired,
                "reconciliation": self.reconciliation_status(),
            }

    def release(self, reservation_id: str) -> None:
        self.release_lease(reservation_id)

    def summary(self) -> dict[str, object]:
        with self._lock:
            self._expire_leases_unlocked()
            return self._summary()

    def _summary(self) -> dict[str, object]:
        reserved_cpu = sum(item.cpu for item in self._reservations.values())
        reserved_ram = sum(item.ram_mb for item in self._reservations.values())
        reserved_vram = sum(item.vram_mb for item in self._reservations.values())
        total_vram = sum(self.capacity.vram_mb.values())
        measured_vram = min(sum(self._measured_vram_mb.values()), total_vram)
        used_vram = max(reserved_vram, measured_vram)
        headroom = self.safety.headroom(
            cpu=self.capacity.cpu_cores,
            ram_mb=self.capacity.ram_mb,
            vram_mb=total_vram,
        )

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
                "cpu": max(0.0, self.capacity.cpu_cores - max(reserved_cpu, self._measured_cpu) - float(headroom["cpu"])),
                "ram_mb": max(0, self.capacity.ram_mb - max(reserved_ram, self._measured_ram_mb) - int(headroom["ram_mb"])),
                "vram_mb": max(0, total_vram - used_vram - int(headroom["vram_mb"])),
            },
        }
        if self.probe:
            summary["probe"] = dict(self.probe)
        if self.safety != ResourceSafetyPolicy():
            summary["safety_headroom"] = self.safety.as_payload(capacity=self.capacity)
        if self._reconciliation_state != "TRUSTED":
            summary["reconciliation"] = self.reconciliation_status()
        return summary

    def hardware_status(self) -> dict[str, Any]:
        """Return a bounded Hardware Monitor/read-model projection."""

        with self._lock:
            total_vram = sum(self.capacity.vram_mb.values())
            total_headroom = self.safety.headroom(
                cpu=self.capacity.cpu_cores,
                ram_mb=self.capacity.ram_mb,
                vram_mb=total_vram,
            )
            measured = dict(self._measured_vram_mb)
            reserved_vram = sum(item.vram_mb for item in self._reservations.values())
            gpu_items = []
            for device in self.capacity.gpu_devices:
                total = int(self.capacity.vram_mb.get(device, 0))
                used = int(measured.get(device, 0))
                device_headroom = self.safety.headroom(cpu=0, ram_mb=0, vram_mb=total)["vram_mb"]
                gpu_items.append(
                    {
                        "device_id": device,
                        "vram_total_mb": total,
                        "vram_measured_used_mb": min(used, total),
                        "vram_free_physical_mb": max(0, total - used),
                        "vram_allocatable_mb": max(0, total - int(device_headroom)),
                    }
                )
            status = {
                "schema_version": 1,
                "source": self.probe.get("source", "unknown"),
                "observed_at": self.probe.get("observed_at"),
                "reconciliation": self.reconciliation_status(),
                "safety_headroom": dict(total_headroom),
                "cpu": {
                    "physical_cores": self.capacity.cpu_cores,
                    "measured_used_cores": self._measured_cpu,
                    "reserved_cores": sum(item.cpu for item in self._reservations.values()),
                    "free_allocatable_cores": max(0.0, self.capacity.cpu_cores - max(self._measured_cpu, sum(item.cpu for item in self._reservations.values())) - float(total_headroom["cpu"])),
                },
                "ram": {
                    "physical_total_mb": self.capacity.ram_mb,
                    "measured_used_mb": self._measured_ram_mb,
                    "reserved_mb": sum(item.ram_mb for item in self._reservations.values()),
                    "free_allocatable_mb": max(0, self.capacity.ram_mb - max(self._measured_ram_mb, sum(item.ram_mb for item in self._reservations.values())) - int(total_headroom["ram_mb"])),
                },
                "gpus": gpu_items,
                "storage": self.probe.get("storage"),
                "external_processes": list(self.probe.get("external_processes") or []),
                "limitations": list(self.probe.get("limitations") or []),
                "leases": len(self._reservations),
                "reserved_vram_mb": reserved_vram,
            }
            return status

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

    @staticmethod
    def _read_non_negative_int(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, parsed)

    @staticmethod
    def _read_non_negative_float(value: Any) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, parsed)

    def _now_iso(self) -> str:
        return self._clock().isoformat()
