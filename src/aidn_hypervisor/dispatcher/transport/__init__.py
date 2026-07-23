"""Transport abstraction layer for the dispatcher.

Re-exports the public symbols so callers can import from the package root.
"""

from aidn_hypervisor.dispatcher.transport.abc import (
    MessageFramer,
    TransportGateway,
    TransportStatus,
)
from aidn_hypervisor.dispatcher.transport.tcp import (
    TcpListener,
    TcpTransport,
)
from aidn_hypervisor.dispatcher.transport.tls import (
    TlsListener,
    TlsTransport,
)
from aidn_hypervisor.dispatcher.transport.unix_socket import (
    UnixSocketListener,
    UnixSocketTransport,
)

__all__ = [
    "MessageFramer",
    "TransportGateway",
    "TransportStatus",
    "TcpTransport",
    "TcpListener",
    "TlsTransport",
    "TlsListener",
    "UnixSocketTransport",
    "UnixSocketListener",
]
