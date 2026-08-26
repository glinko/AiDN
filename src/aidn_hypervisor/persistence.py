import json
from pathlib import Path

from aidn_hypervisor.pricing.migration import migrate_snapshot_pricing
from aidn_hypervisor.state import HypervisorStateSnapshot


class FileStateStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> HypervisorStateSnapshot:
        if not self.path.exists():
            return HypervisorStateSnapshot()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Hypervisor state snapshot must contain a JSON object")
        # EndpointPricing is intentionally strict for all new API writes.  The
        # read-time shim keeps nodes bootstrapped before Pricing V2 recoverable
        # without reopening legacy fields in the public model.
        migrate_snapshot_pricing(payload)
        return HypervisorStateSnapshot.model_validate(payload)

    def save(self, snapshot: HypervisorStateSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(snapshot.model_dump(mode="json"), indent=2)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(payload, encoding="utf-8")
        # Hypervisor snapshots contain locally-held wallet material. Keep the
        # atomic replacement while ensuring both the temporary and final file
        # are owner-readable only on POSIX hosts.
        try:
            temporary_path.chmod(0o600)
        except OSError:
            pass
        temporary_path.replace(self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
