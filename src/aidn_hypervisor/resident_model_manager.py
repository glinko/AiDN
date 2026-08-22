"""Explicit artifact preparation for the Resident Steward model.

The Steward may use a local model, but downloading a model is an operator
action rather than an implicit side effect of starting a resident process.
This module provides the small, auditable boundary for that action:
bounded sources, atomic writes, byte limits, and optional SHA-256
verification.  It deliberately does not know anything about providers or
resource leases.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, url2pathname, urlopen


class ResidentModelError(ValueError):
    """Stable error returned by the model artifact boundary."""

    code = "INFERENCE_MODEL_PREPARATION_FAILED"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


_DEFAULT_ALLOWED_HOSTS = {"huggingface.co", "www.huggingface.co"}
_CHUNK_SIZE = 1024 * 1024
_DEFAULT_MAX_BYTES = 64 * 1024 * 1024 * 1024


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


class ResidentModelManager:
    """Prepare and verify one local model artifact without starting it."""

    def __init__(
        self,
        *,
        allowed_hosts: set[str] | None = None,
        max_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        if isinstance(max_bytes, bool) or int(max_bytes) < 1:
            raise ValueError("max_bytes must be positive")
        self.allowed_hosts = {
            str(host).strip().lower().rstrip(".")
            for host in (allowed_hosts or _DEFAULT_ALLOWED_HOSTS)
            if str(host).strip()
        }
        self.max_bytes = int(max_bytes)

    def inspect(self, model_path: str) -> dict:
        path = self._path(model_path)
        if not path.is_file():
            raise ResidentModelError(
                "the resident model artifact does not exist",
                details={"code": "INFERENCE_MODEL_NOT_FOUND", "model_path": str(path)},
            )
        digest, size = _sha256(path)
        return {"model_path": str(path), "size_bytes": size, "sha256": f"sha256:{digest}"}

    def verify(self, model_path: str, *, expected_sha256: str | None = None) -> dict:
        result = self.inspect(model_path)
        expected = self._normalise_digest(expected_sha256)
        if expected is not None and result["sha256"] != expected:
            raise ResidentModelError(
                "resident model checksum does not match the expected digest",
                details={
                    "code": "INFERENCE_MODEL_CHECKSUM_MISMATCH",
                    "model_path": result["model_path"],
                    "expected_sha256": expected,
                    "actual_sha256": result["sha256"],
                },
            )
        result["verified"] = expected is not None
        return result

    def download(
        self,
        source_url: str,
        target_path: str,
        *,
        expected_sha256: str | None = None,
        max_bytes: int | None = None,
        allow_insecure_http: bool = False,
    ) -> dict:
        source = str(source_url or "").strip()
        target = self._path(target_path)
        if not source:
            raise ResidentModelError("model source URL is required", details={"code": "INFERENCE_MODEL_SOURCE_REQUIRED"})
        limit = self.max_bytes if max_bytes is None else int(max_bytes)
        if limit < 1 or limit > self.max_bytes:
            raise ResidentModelError("model download byte limit is invalid", details={"code": "INFERENCE_MODEL_SIZE_LIMIT_INVALID"})
        parsed = urlparse(source)
        if parsed.scheme in {"", "file"}:
            if parsed.scheme == "":
                source_path = Path(source)
            else:
                # `urlparse(file:///C:/...)` keeps the drive slash in the
                # path on Windows.  Normalise it before handing the path to
                # pathlib so local-file preparation works cross-platform.
                local_path = url2pathname(parsed.path)
                if os.name == "nt" and len(local_path) >= 3 and local_path[0] in {"/", "\\"} and local_path[2] == ":":
                    local_path = local_path[1:]
                source_path = Path(local_path)
            if not source_path.is_file():
                raise ResidentModelError("local model source does not exist", details={"code": "INFERENCE_MODEL_SOURCE_NOT_FOUND", "source": str(source_path)})
            try:
                size = source_path.stat().st_size
            except OSError as error:
                raise ResidentModelError("unable to inspect local model source", details={"code": "INFERENCE_MODEL_SOURCE_UNREADABLE"}) from error
            if size > limit:
                raise ResidentModelError("model source exceeds the configured byte limit", details={"code": "INFERENCE_MODEL_TOO_LARGE", "size_bytes": size, "max_bytes": limit})
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._temporary_path(target)
            try:
                shutil.copyfile(source_path, temporary)
                return self._finalize(temporary, target, expected_sha256=expected_sha256, source=source)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        if parsed.scheme != "https" and not (parsed.scheme == "http" and allow_insecure_http):
            raise ResidentModelError("model source must use HTTPS or a local file", details={"code": "INFERENCE_MODEL_SOURCE_SCHEME_INVALID"})
        host = (parsed.hostname or "").lower().rstrip(".")
        if host not in self.allowed_hosts:
            raise ResidentModelError("model source host is not allow-listed", details={"code": "INFERENCE_MODEL_SOURCE_HOST_DENIED", "host": host})
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._temporary_path(target)
        size = 0
        digest = hashlib.sha256()
        try:
            with urlopen(Request(source, headers={"User-Agent": "AiDN-Resident-Steward/1"}), timeout=30) as response, temporary.open("wb") as handle:
                while True:
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        raise ResidentModelError("model download exceeds the configured byte limit", details={"code": "INFERENCE_MODEL_TOO_LARGE", "max_bytes": limit})
                    digest.update(chunk)
                    handle.write(chunk)
            return self._finalize(temporary, target, expected_sha256=expected_sha256, source=source, digest=digest.hexdigest(), size=size)
        except ResidentModelError:
            temporary.unlink(missing_ok=True)
            raise
        except Exception as error:
            temporary.unlink(missing_ok=True)
            raise ResidentModelError("model download failed", details={"code": "INFERENCE_MODEL_DOWNLOAD_FAILED", "message": str(error)[:256]}) from error

    def _finalize(self, temporary: Path, target: Path, *, expected_sha256: str | None, source: str, digest: str | None = None, size: int | None = None) -> dict:
        actual_digest, actual_size = (digest, size) if digest is not None and size is not None else _sha256(temporary)
        actual = f"sha256:{actual_digest}"
        expected = self._normalise_digest(expected_sha256)
        if expected is not None and actual != expected:
            temporary.unlink(missing_ok=True)
            raise ResidentModelError("downloaded model checksum does not match the expected digest", details={"code": "INFERENCE_MODEL_CHECKSUM_MISMATCH", "expected_sha256": expected, "actual_sha256": actual, "source": source})
        os.replace(temporary, target)
        return {"model_path": str(target.resolve()), "source": source, "size_bytes": int(actual_size), "sha256": actual, "verified": expected is not None}

    @staticmethod
    def _temporary_path(target: Path) -> Path:
        fd, raw = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=str(target.parent))
        os.close(fd)
        return Path(raw)

    @staticmethod
    def _path(value: str) -> Path:
        raw = str(value or "").strip()
        if not raw or len(raw) > 4096:
            raise ResidentModelError("model path is required", details={"code": "INFERENCE_MODEL_PATH_INVALID"})
        return Path(os.path.expanduser(raw)).resolve()

    @staticmethod
    def _normalise_digest(value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        raw = str(value).strip().lower()
        if raw.startswith("sha256:"):
            raw = raw[7:]
        if len(raw) != 64 or any(char not in "0123456789abcdef" for char in raw):
            raise ResidentModelError("expected SHA-256 digest", details={"code": "INFERENCE_MODEL_CHECKSUM_INVALID"})
        return f"sha256:{raw}"
