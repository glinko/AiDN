"""Peer discovery (RFC-0042 §27-32).

Discovery provides possible peer addresses but does NOT establish trust.
Every discovered peer SHALL complete authentication before communication.
"""

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── Discovery sources (RFC-0042 §27) ──────────────────────────────────────

DiscoverySource = Literal[
    "STATIC_CONFIGURATION",
    "GENESIS_SEEDS",
    "DNS_SEEDS",
    "REGISTRY_DISCOVERY",
    "PEER_EXCHANGE",
    "LOCAL_DISCOVERY",
    "OPERATOR_INPUT",
]


# ── Address classification (RFC-0042 §33) ────────────────────────────────

AddressClass = Literal[
    "PUBLIC_DIRECT",
    "PRIVATE_DIRECT",
    "RELAY_REQUIRED",
    "LOCAL_ONLY",
]

TrustState = Literal[
    "UNVERIFIED",
    "DISCOVERED",
    "HANDSHAKE_PENDING",
    "AUTHENTICATED",
    "ESTABLISHED",
    "QUARANTINED",
    "REVOKED",
]


# ── Peer models ──────────────────────────────────────────────────────────

class PeerAddress(BaseModel):
    """A single reachable address for a peer."""

    host: str
    port: int
    address_class: AddressClass = "PUBLIC_DIRECT"
    transport_profile: str = "QUIC_TLS"
    is_reachable: bool = True
    last_verified: str | None = None


class PeerRecord(BaseModel):
    """Persistent peer record (RFC-0042 §28)."""

    peer_id: str
    hypervisor_id: str
    addresses: list[PeerAddress] = Field(default_factory=list)
    discovery_source: DiscoverySource = "STATIC_CONFIGURATION"
    trust_state: TrustState = "UNVERIFIED"
    first_seen: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_seen: str | None = None
    last_heartbeat: str | None = None
    connection_success_count: int = 0
    connection_failure_count: int = 0
    metadata: dict = Field(default_factory=dict)
    recommended_by: str | None = None  # peer_id of recommender

    @property
    def success_rate(self) -> float:
        """Connection success rate (0.0 - 1.0)."""
        total = self.connection_success_count + self.connection_failure_count
        if total == 0:
            return 0.0
        return self.connection_success_count / total

    @property
    def is_trusted(self) -> bool:
        """Whether this peer has completed authentication."""
        return self.trust_state in ("AUTHENTICATED", "ESTABLISHED")

    @property
    def is_blocked(self) -> bool:
        """Whether this peer is quarantined or revoked."""
        return self.trust_state in ("QUARANTINED", "REVOKED")


# ── Discovery manager ────────────────────────────────────────────────────

class DiscoveryManager:
    """Manages peer discovery from multiple sources (RFC-0042 §27-32).

    Discovery provides possible addresses but does NOT establish trust.
    Use several discovery sources for diversity.
    """

    def __init__(self) -> None:
        self._peers: dict[str, PeerRecord] = {}
        self._discovery_sources: set[DiscoverySource] = set()
        self._dns_seed_hosts: list[str] = []
        self._static_peers: list[PeerAddress] = []

    @property
    def peer_count(self) -> int:
        return len(self._peers)

    @property
    def discovery_diversity(self) -> int:
        """Number of active discovery sources."""
        return len(self._discovery_sources)

    # ── Static configuration (RFC-0042 §27) ─────────────────────────

    def add_static_peers(self, addresses: list[PeerAddress]) -> None:
        """Add statically configured peer addresses."""
        for addr in addresses:
            peer_id = f"static:{addr.host}:{addr.port}"
            if peer_id not in self._peers:
                record = PeerRecord(
                    peer_id=peer_id,
                    hypervisor_id="",  # unknown until handshake
                    addresses=[addr],
                    discovery_source="STATIC_CONFIGURATION",
                    trust_state="DISCOVERED",
                )
                self._peers[peer_id] = record
                logger.info("Static peer added: %s", peer_id)
        self._discovery_sources.add("STATIC_CONFIGURATION")

    def add_static_seed(self, host: str, port: int, *, address_class: AddressClass = "PUBLIC_DIRECT") -> None:
        """Add a single static seed peer."""
        addr = PeerAddress(host=host, port=port, address_class=address_class)
        self.add_static_peers([addr])

    # ── DNS seeds (RFC-0042 §29) ────────────────────────────────────

    def add_dns_seeds(self, hosts: list[str]) -> None:
        """Register DNS seed hosts for peer resolution."""
        self._dns_seed_hosts.extend(hosts)
        self._discovery_sources.add("DNS_SEEDS")

    async def resolve_dns_seeds(self) -> list[PeerRecord]:
        """Resolve DNS seed hosts to peer addresses.

        TODO: actual DNS TXT/SRV record resolution.
        """
        records: list[PeerRecord] = []
        for host in self._dns_seed_hosts:
            # Stub — would resolve DNS TXT records with peer addresses
            logger.info("Resolving DNS seed: %s", host)
            # For now, treat the seed host itself as a reachable peer
            peer_id = f"dns:{host}"
            if peer_id not in self._peers:
                record = PeerRecord(
                    peer_id=peer_id,
                    hypervisor_id="",
                    addresses=[PeerAddress(host=host, port=443)],
                    discovery_source="DNS_SEEDS",
                    trust_state="DISCOVERED",
                )
                self._peers[peer_id] = record
                records.append(record)
        return records

    # ── Registry discovery (RFC-0042 §30) ──────────────────────────

    async def registry_discovery(self, registry_url: str) -> list[PeerRecord]:
        """Discover peers via the distributed registry.

        TODO: actual registry API call.
        """
        logger.info("Registry discovery from %s", registry_url)
        self._discovery_sources.add("REGISTRY_DISCOVERY")
        # Stub — would query registry for active, authenticated peers
        return []

    # ── Peer exchange (RFC-0042 §31) ────────────────────────────────

    def peer_exchange(
        self,
        peer_addresses: list[PeerAddress],
        *,
        recommended_by: str,
    ) -> list[PeerRecord]:
        """Add peers recommended by an authenticated peer (RFC-0042 §31).

        Recommendations are attributed but non-authoritative.
        """
        records: list[PeerRecord] = []
        for addr in peer_addresses:
            peer_id = f"pex:{addr.host}:{addr.port}:{recommended_by}"
            if peer_id not in self._peers:
                record = PeerRecord(
                    peer_id=peer_id,
                    hypervisor_id="",
                    addresses=[addr],
                    discovery_source="PEER_EXCHANGE",
                    trust_state="DISCOVERED",
                    recommended_by=recommended_by,
                )
                self._peers[peer_id] = record
                records.append(record)
                logger.info(
                    "Peer exchange: %s recommended by %s", peer_id, recommended_by
                )
        self._discovery_sources.add("PEER_EXCHANGE")
        return records

    # ── Operator input (RFC-0042 §32) ──────────────────────────────

    def operator_add_peer(
        self,
        peer_id: str,
        addresses: list[PeerAddress],
        *,
        hypervisor_id: str = "",
    ) -> PeerRecord:
        """Add a peer from explicit operator input."""
        record = PeerRecord(
            peer_id=peer_id,
            hypervisor_id=hypervisor_id,
            addresses=addresses,
            discovery_source="OPERATOR_INPUT",
            trust_state="DISCOVERED",
        )
        self._peers[peer_id] = record
        self._discovery_sources.add("OPERATOR_INPUT")
        return record

    # ── Peer lookup ────────────────────────────────────────────────

    def get_peer(self, peer_id: str) -> PeerRecord | None:
        """Look up a peer by ID."""
        return self._peers.get(peer_id)

    def list_peers(
        self,
        trust_state: TrustState | None = None,
        discovery_source: DiscoverySource | None = None,
    ) -> list[PeerRecord]:
        """List peers with optional filters."""
        peers = self._peers.values()
        if trust_state is not None:
            peers = (p for p in peers if p.trust_state == trust_state)
        if discovery_source is not None:
            peers = (p for p in peers if p.discovery_source == discovery_source)
        return list(peers)

    def list_trusted_peers(self) -> list[PeerRecord]:
        """List authenticated/established peers."""
        return [p for p in self._peers.values() if p.is_trusted]

    def list_untrusted_peers(self) -> list[PeerRecord]:
        """List unverified/discovered peers needing authentication."""
        return [
            p for p in self._peers.values()
            if p.trust_state in ("UNVERIFIED", "DISCOVERED", "HANDSHAKE_PENDING")
        ]

    # ── Peer state management ──────────────────────────────────────

    def update_trust_state(self, peer_id: str, new_state: TrustState) -> None:
        """Update peer trust state."""
        record = self._peers.get(peer_id)
        if record:
            record.trust_state = new_state
            record.last_seen = datetime.now(timezone.utc).isoformat()

    def record_connection_success(self, peer_id: str) -> None:
        """Record a successful connection attempt."""
        record = self._peers.get(peer_id)
        if record:
            record.connection_success_count += 1
            record.last_heartbeat = datetime.now(timezone.utc).isoformat()

    def record_connection_failure(self, peer_id: str) -> None:
        """Record a failed connection attempt."""
        record = self._peers.get(peer_id)
        if record:
            record.connection_failure_count += 1

    def quarantine_peer(self, peer_id: str) -> None:
        """Quarantine a misbehaving peer."""
        self.update_trust_state(peer_id, "QUARANTINED")
        logger.warning("Peer quarantined: %s", peer_id)

    def revoke_peer(self, peer_id: str) -> None:
        """Revoke a peer (permanent ban)."""
        self.update_trust_state(peer_id, "REVOKED")
        logger.warning("Peer revoked: %s", peer_id)
