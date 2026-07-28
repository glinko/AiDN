"""Content-addressed storage for verified Provider Plugin package bytes."""

import hashlib
import os
import shutil
import stat
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
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

    def __init__(
        self,
        root: Path | str,
        *,
        maximum_archive_entries: int = 1024,
        maximum_expanded_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        if maximum_archive_entries <= 0 or maximum_expanded_bytes <= 0:
            raise ValueError("plugin package archive limits must be positive")
        self.root = Path(root)
        self.maximum_archive_entries = maximum_archive_entries
        self.maximum_expanded_bytes = maximum_expanded_bytes

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

    def materialize_python_host(self, *, package_digest: str, entrypoint_path: str) -> Path:
        """Extract one verified ZIP package into a verified, content-addressed runtime tree."""
        entrypoint = _validated_python_entrypoint(entrypoint_path)
        package_bytes = self.read(package_digest)
        members = self._archive_members(package_bytes)
        if entrypoint not in members:
            raise ValueError("Plugin Host entrypoint is not present in the verified package")

        digest = _validated_package_digest(package_digest)
        runtime_root = self.root / "runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        destination = runtime_root / digest
        if destination.exists():
            self._verify_materialized_tree(destination=destination, members=members)
            return destination.joinpath(*PurePosixPath(entrypoint).parts)

        temporary = Path(tempfile.mkdtemp(prefix=f".{digest}.", dir=runtime_root))
        try:
            for relative_path, content in members.items():
                target = temporary.joinpath(*PurePosixPath(relative_path).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            self._verify_materialized_tree(destination=temporary, members=members)
            try:
                temporary.rename(destination)
            except FileExistsError:
                self._verify_materialized_tree(destination=destination, members=members)
            return destination.joinpath(*PurePosixPath(entrypoint).parts)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def _archive_members(self, package_bytes: bytes) -> dict[str, bytes]:
        try:
            archive = zipfile.ZipFile(BytesIO(package_bytes))
        except zipfile.BadZipFile as exc:
            raise ValueError("Plugin Host package must be a ZIP archive") from exc
        with archive:
            infos = archive.infolist()
            if len(infos) > self.maximum_archive_entries:
                raise ValueError("Plugin Host package exceeds the archive entry limit")
            members: dict[str, bytes] = {}
            total_size = 0
            for info in infos:
                relative_path = _validated_archive_path(info.filename)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError("Plugin Host packages must not contain symbolic links")
                if info.is_dir():
                    continue
                if relative_path in members:
                    raise ValueError("Plugin Host package contains duplicate archive paths")
                total_size += info.file_size
                if total_size > self.maximum_expanded_bytes:
                    raise ValueError("Plugin Host package exceeds the expanded size limit")
                members[relative_path] = archive.read(info)
        if not members:
            raise ValueError("Plugin Host package must contain files")
        return members

    @staticmethod
    def _verify_materialized_tree(*, destination: Path, members: dict[str, bytes]) -> None:
        if not destination.is_dir() or destination.is_symlink():
            raise ValueError("Plugin Host runtime tree is invalid")
        actual_paths: set[str] = set()
        for root, directories, files in os.walk(destination, followlinks=False):
            root_path = Path(root)
            for directory in directories:
                if (root_path / directory).is_symlink():
                    raise ValueError("Plugin Host runtime tree contains symbolic links")
            for filename in files:
                candidate = root_path / filename
                if candidate.is_symlink():
                    raise ValueError("Plugin Host runtime tree contains symbolic links")
                relative_path = candidate.relative_to(destination).as_posix()
                actual_paths.add(relative_path)
                expected_content = members.get(relative_path)
                if expected_content is None or candidate.read_bytes() != expected_content:
                    raise ValueError("Plugin Host runtime tree does not match the verified package")
        if actual_paths != set(members):
            raise ValueError("Plugin Host runtime tree does not match the verified package")


def _validated_archive_path(value: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise ValueError("Plugin Host package contains an unsafe archive path")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Plugin Host package contains an unsafe archive path")
    return path.as_posix()


def _validated_python_entrypoint(value: str) -> str:
    path = _validated_archive_path(value)
    if not path.endswith(".py"):
        raise ValueError("Plugin Host entrypoint must reference a Python file")
    return path


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
