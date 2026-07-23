"""Transport abstraction layer for the dispatcher.

Re-exports the public symbols so callers can import from the package root.
"""

from aidn_hypervisor.dispatcher.transport.abc import (
    MessageFramer,
    TransportGateway,
    TransportStatus,
)

__all__ = [
    "MessageFramer",
    "TransportGateway",
    "TransportStatus",
]
