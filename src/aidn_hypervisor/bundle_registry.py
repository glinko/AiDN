import json
from pathlib import Path

from aidn_hypervisor.domain.models import BundleConfig


class FileBundleRegistry:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self, plugins) -> list[BundleConfig]:
        if not self.path.exists():
            return []

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        bundles = [BundleConfig.model_validate(item) for item in payload]
        for bundle in bundles:
            plugin = plugins.get(bundle.plugin_id)
            plugin.validate_bundle(bundle)
        return bundles

    def save(self, bundles: list[BundleConfig]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [bundle.model_dump(mode="json") for bundle in bundles],
            indent=2,
        )
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(payload, encoding="utf-8")
        temporary_path.replace(self.path)
