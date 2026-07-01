import json
from pathlib import Path

from aidn_hypervisor.state import HypervisorStateSnapshot


class FileStateStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> HypervisorStateSnapshot:
        if not self.path.exists():
            return HypervisorStateSnapshot()
        return HypervisorStateSnapshot.model_validate_json(
            self.path.read_text(encoding="utf-8")
        )

    def save(self, snapshot: HypervisorStateSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(snapshot.model_dump(mode="json"), indent=2)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(payload, encoding="utf-8")
        temporary_path.replace(self.path)
