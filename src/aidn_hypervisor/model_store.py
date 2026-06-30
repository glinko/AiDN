from pathlib import Path
import shutil
from urllib import parse, request


class FileModelStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def reserve_target_path(self, provider_type: str, model_id: str) -> Path:
        safe_name = model_id.replace("/", "_")
        target = self.root / provider_type / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def materialize_artifact(self, source_url: str, target_path: Path | str) -> Path:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        source_path = self._local_source_path(source_url)

        if source_path is not None:
            if not source_path.exists():
                raise FileNotFoundError(source_path)
            if source_path.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source_path, target)
                return target
            shutil.copy2(source_path, target)
            return target

        with request.urlopen(source_url, timeout=30) as response, target.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        return target

    def _local_source_path(self, source_url: str) -> Path | None:
        if "://" not in source_url:
            return Path(source_url)
        parsed = parse.urlparse(source_url)
        if parsed.scheme != "file":
            return None
        return Path(request.url2pathname(parsed.path))
