"""Content-addressed storage for verified Provider Plugin package bytes."""

import hashlib
import os
import tempfile
from pathlib import Path
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


def _validated_package_digest(package_digest: str) -> str:
    prefix = "sha256:"
    digest = package_digest.removeprefix(prefix)
    if not package_digest.startswith(prefix) or len(digest) != 64:
        raise ValueError("plugin package digest must be a SHA-256 digest")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise ValueError("plugin package digest must be a SHA-256 digest") from exc
    return digest.lower()


def _verified_digest(package_bytes: bytes, expected_digest: str) -> str:
    if not package_bytes:
        raise ValueError("plugin package must not be empty")
    expected_hex = _validated_package_digest(expected_digest)
    actual_digest = hashlib.sha256(package_bytes).hexdigest()
    if actual_digest != expected_hex:
        raise ValueError("plugin package digest does not match declared release digest")
    return f"sha256:{actual_digest}"


class PluginPackageStore:
    """Keep immutable package payloads keyed by their verified SHA-256 digest."""

    def __init__(self) -> None:
        self._packages: dict[str, bytes] = {}

    def stage(self, *, package_bytes: bytes, expected_digest: str) -> str:
        actual_digest = _verified_digest(package_bytes, expected_digest)
        existing = self._packages.get(actual_digest)
        if existing is not None and existing != package_bytes:
            raise ValueError("plugin package digest conflicts with stored package content")
        self._packages[actual_digest] = bytes(package_bytes)
        return actual_digest

    def has(self, package_digest: str) -> bool:
        return package_digest in self._packages

    def read(self, package_digest: str) -> bytes:
        return self._packages[package_digest]


class FilesystemPluginPackageStore:
    """Durable content-addressed package bytes under one operator-controlled root."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _path_for(self, package_digest: str) -> Path:
        digest = _validated_package_digest(package_digest)
        return self.root / digest[:2] / f"{digest}.package"

    def stage(self, *, package_bytes: bytes, expected_digest: str) -> str:
        actual_digest = _verified_digest(package_bytes, expected_digest)
        package_path = self._path_for(actual_digest)
        package_path.parent.mkdir(parents=True, exist_ok=True)
        if package_path.exists():
            if self.read(actual_digest) != package_bytes:
                raise ValueError("plugin package digest conflicts with stored package content")
            return actual_digest
        file_descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{package_path.name}.",
            dir=package_path.parent,
        )
        try:
            with os.fdopen(file_descriptor, "wb") as package_file:
                package_file.write(package_bytes)
                package_file.flush()
                os.fsync(package_file.fileno())
            os.replace(temporary_path, package_path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)
        return actual_digest

    def has(self, package_digest: str) -> bool:
        try:
            self.read(package_digest)
        except (FileNotFoundError, ValueError):
            return False
        return True

    def read(self, package_digest: str) -> bytes:
        package_path = self._path_for(package_digest)
        package_bytes = package_path.read_bytes()
        _verified_digest(package_bytes, package_digest)
        return package_bytes


class _RejectRedirect(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise ValueError("plugin package download redirects are not permitted")


class HttpsPluginPackageAcquirer:
    """Download one bounded package over HTTPS before content-addressed staging."""

    def __init__(self, *, timeout_seconds: float = 30, maximum_package_bytes: int = 64 * 1024 * 1024) -> None:
        if timeout_seconds <= 0:
            raise ValueError("plugin package download timeout must be positive")
        if maximum_package_bytes <= 0:
            raise ValueError("plugin package maximum size must be positive")
        self.timeout_seconds = timeout_seconds
        self.maximum_package_bytes = maximum_package_bytes
        self._opener = urllib_request.build_opener(_RejectRedirect())

    def acquire_and_stage(self, *, package_store, source_reference: str, expected_digest: str) -> str:
        package_bytes = self.acquire(source_reference)
        return package_store.stage(package_bytes=package_bytes, expected_digest=expected_digest)

    def acquire(self, source_reference: str) -> bytes:
        source_url = self._validated_source_url(source_reference)
        request = urllib_request.Request(source_url, method="GET", headers={"Accept": "application/octet-stream"})
        try:
            with self._open(request) as response:
                content_length = response.headers.get("Content-Length")
                if content_length is not None and int(content_length) > self.maximum_package_bytes:
                    raise ValueError("plugin package exceeds the configured maximum size")
                chunks: list[bytes] = []
                total_size = 0
                while True:
                    chunk = response.read(min(64 * 1024, self.maximum_package_bytes - total_size + 1))
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > self.maximum_package_bytes:
                        raise ValueError("plugin package exceeds the configured maximum size")
                    chunks.append(chunk)
        except ValueError:
            raise
        except (OSError, urllib_error.URLError, urllib_error.HTTPError) as exc:
            raise RuntimeError("plugin package download failed") from exc
        return b"".join(chunks)

    def _open(self, request):
        return self._opener.open(request, timeout=self.timeout_seconds)

    @staticmethod
    def _validated_source_url(source_reference: str) -> str:
        parsed = urllib_parse.urlparse(source_reference)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("plugin package source must be a credential-free HTTPS URL")
        return source_reference
