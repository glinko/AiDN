"""Protocol Negotiation + Registry Status (RFC-0061 §§18-19)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProtocolVersion(BaseModel, frozen=True):
    """Protocol version representation."""

    major: int = 1
    minor: int = 0
    patch: int = 0

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


class RegistryStatus(BaseModel):
    """RFC-0061 §19 — Registry status exchange payload."""

    peer_id: str
    protocol_version: str = "1.0.0"
    registry_class: str = "full"
    finalized_height: int = 0
    current_epoch: int = 0
    profile_version: int = 1
    object_count: int = 0
    earliest_epoch: int = 0
    latest_epoch: int = 0
    supported_compression: list[str] = Field(default_factory=list)
    supported_formats: list[str] = Field(default_factory=list)
    max_object_size: int = 10 * 1024 * 1024
    max_chunk_size: int = 1024 * 1024
    inventory_summary: dict[str, Any] = Field(default_factory=dict)


class NegotiationResult(BaseModel):
    """Result of protocol negotiation."""

    peer_id: str
    compatible: bool
    agreed_compression: list[str]
    agreed_formats: list[str]
    max_object_size: int
    max_chunk_size: int


class ProtocolNegotiator:
    """
    RFC-0061 §18 — Protocol negotiation between peers.
    """

    def __init__(
        self,
        *,
        local_version: ProtocolVersion | None = None,
        local_status: RegistryStatus | None = None,
        supported_compression: list[str] | None = None,
        supported_formats: list[str] | None = None,
    ) -> None:
        self.local_version = local_version or ProtocolVersion()
        self.local_status = local_status
        self.supported_compression = supported_compression or ["gzip", "none"]
        self.supported_formats = supported_formats or ["json", "protobuf"]
        self._negotiated: dict[str, NegotiationResult] = {}

    def negotiate(
        self,
        *,
        peer_id: str,
        remote_status: RegistryStatus,
    ) -> NegotiationResult:
        """
        Negotiate protocol compatibility with a peer.
        Returns NegotiationResult with compatibility status.
        """
        # Version compatibility: major must match
        local_parts = self.local_version.__str__().split(".")
        remote_parts = remote_status.protocol_version.split(".")

        major_compat = (
            local_parts[0] == remote_parts[0]
            if remote_parts
            else False
        )

        # Find common compression
        common_compression = [
            c
            for c in self.supported_compression
            if c in remote_status.supported_compression
            or not remote_status.supported_compression
        ]
        if not common_compression:
            common_compression = ["none"]

        # Find common formats
        common_formats = [
            f
            for f in self.supported_formats
            if f in remote_status.supported_formats
            or not remote_status.supported_formats
        ]
        if not common_formats:
            common_formats = ["json"]

        # Determine limits (use minimum of both)
        local_max_obj = (
            self.local_status.max_object_size
            if self.local_status
            else 10 * 1024 * 1024
        )
        local_max_chunk = (
            self.local_status.max_chunk_size
            if self.local_status
            else 1024 * 1024
        )
        max_object = min(local_max_obj, remote_status.max_object_size)
        max_chunk = min(local_max_chunk, remote_status.max_chunk_size)

        result = NegotiationResult(
            peer_id=peer_id,
            compatible=major_compat,
            agreed_compression=common_compression,
            agreed_formats=common_formats,
            max_object_size=max_object,
            max_chunk_size=max_chunk,
        )
        self._negotiated[peer_id] = result
        return result

    def get_negotiated(self, peer_id: str) -> NegotiationResult | None:
        return self._negotiated.get(peer_id)

    def is_compatible(self, peer_id: str) -> bool:
        result = self._negotiated.get(peer_id)
        return result is not None and result.compatible
