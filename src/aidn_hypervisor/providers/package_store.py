"""Content-addressed storage for verified Provider Plugin package bytes."""

import hashlib


class PluginPackageStore:
    """Keep immutable package payloads keyed by their verified SHA-256 digest."""

    def __init__(self) -> None:
        self._packages: dict[str, bytes] = {}

    def stage(self, *, package_bytes: bytes, expected_digest: str) -> str:
        if not package_bytes:
            raise ValueError("plugin package must not be empty")
        actual_digest = f"sha256:{hashlib.sha256(package_bytes).hexdigest()}"
        if actual_digest != expected_digest:
            raise ValueError("plugin package digest does not match declared release digest")
        existing = self._packages.get(actual_digest)
        if existing is not None and existing != package_bytes:
            raise ValueError("plugin package digest conflicts with stored package content")
        self._packages[actual_digest] = bytes(package_bytes)
        return actual_digest

    def has(self, package_digest: str) -> bool:
        return package_digest in self._packages

    def read(self, package_digest: str) -> bytes:
        return self._packages[package_digest]
