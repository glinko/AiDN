from aidn_hypervisor.dispatcher.handshake import (
    ClientHello,
    ConnectionIdentity,
    ConnectionState,
    HandshakeError,
    HandshakeProtocol,
    PROTOCOL_VERSION,
    ServerHello,
    SUPPORTED_VERSIONS,
    TransportProfile,
)
from aidn_hypervisor.dispatcher.transport import (
    QUICTransport,
    TCPTLSTransport,
    TransportProfileBase,
    create_transport,
)
from aidn_hypervisor.dispatcher.channels import (
    ChannelAuthorization,
    ChannelIdentity,
    ChannelManager,
    ChannelQueue,
    ChannelState,
)
from aidn_hypervisor.dispatcher.discovery import (
    DiscoveryManager,
    PeerAddress,
    PeerRecord,
)
from aidn_hypervisor.dispatcher.relay import (
    RelayEnvelope,
    RelayRouter,
    RelayStats,
)
from aidn_hypervisor.dispatcher.gateway import (
    GatewayConfig,
    NetworkGateway,
)
from aidn_hypervisor.dispatcher.models import (
    DeadLetterRecord,
    DeliveryRecord,
    DispatcherReplayRecord,
    DispatcherRoute,
    NetworkMessage,
    canonical_payload_hash,
)
from aidn_hypervisor.dispatcher.service import DispatcherError, NetworkDispatcher
from aidn_hypervisor.dispatcher.store import DispatcherStore
from aidn_hypervisor.dispatcher.lifecycle import DispatcherRouteLifecycle
from aidn_hypervisor.dispatcher.routes import (
    bind_plugin_control_route,
    bind_runtime_ingress_route,
    bind_runtime_route,
    bind_remote_runtime_route,
    bind_session_route,
    plugin_control_route,
    runtime_ingress_route,
    runtime_route,
    remote_runtime_route,
    session_route,
)

__all__ = [
    # Models
    "DeadLetterRecord",
    "DeliveryRecord",
    "DispatcherError",
    "DispatcherReplayRecord",
    "DispatcherRoute",
    "NetworkDispatcher",
    "NetworkMessage",
    "DispatcherStore",
    "DispatcherRouteLifecycle",
    "canonical_payload_hash",
    # Routes
    "bind_plugin_control_route",
    "bind_runtime_ingress_route",
    "bind_runtime_route",
    "bind_remote_runtime_route",
    "bind_session_route",
    "plugin_control_route",
    "runtime_ingress_route",
    "runtime_route",
    "remote_runtime_route",
    "session_route",
    # Handshake (RFC-0042 §20-24)
    "ClientHello",
    "ServerHello",
    "HandshakeProtocol",
    "HandshakeError",
    "ConnectionIdentity",
    "ConnectionState",
    "TransportProfile",
    "PROTOCOL_VERSION",
    "SUPPORTED_VERSIONS",
    # Transport (RFC-0042 §6-9)
    "QUICTransport",
    "TCPTLSTransport",
    "TransportProfileBase",
    "create_transport",
    # Channels (RFC-0042 §44-47)
    "ChannelManager",
    "ChannelQueue",
    "ChannelState",
    "ChannelAuthorization",
    "ChannelIdentity",
    # Discovery (RFC-0042 §27-32)
    "DiscoveryManager",
    "PeerRecord",
    "PeerAddress",
    # Relay (RFC-0042 §37-43)
    "RelayEnvelope",
    "RelayRouter",
    "RelayStats",
    # Gateway
    "NetworkGateway",
    "GatewayConfig",
]
