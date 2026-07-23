"""Transport abstraction for the dispatcher layer.

Defines the ``TransportGateway`` protocol that any network transport
implementation must satisfy, together with a ``MessageFramer`` that
handles length-prefixed JSON serialization of ``NetworkMessage`` objects.
"""

from __future__ import annotations

import enum
import json
import struct
from typing import Protocol, runtime_checkable

from aidn_hypervisor.dispatcher.models import NetworkMessage

# ---------------------------------------------------------------------------
# Transport status
# ---------------------------------------------------------------------------

class TransportStatus(enum.Enum):
    """Connection lifecycle states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


# ---------------------------------------------------------------------------
# TransportGateway protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class TransportGateway(Protocol):
    """Minimal interface every transport backend must implement.

    A transport is responsible for the low-level mechanics of getting
    ``NetworkMessage`` bytes across the wire — TCP sockets, Unix domain
    sockets, in-memory pipes, etc.  The dispatcher layer calls into this
    protocol without knowing *how* the bytes move.
    """

    # -- lifecycle ----------------------------------------------------------

    def connect(self) -> None:
        """Establish the underlying connection.

        Raises
        ------
        ConnectionError
            If the transport cannot reach the remote endpoint.
        """
        ...

    def disconnect(self) -> None:
        """Gracefully close the connection and release resources."""
        ...

    # -- messaging ----------------------------------------------------------

    def send(self, message: NetworkMessage) -> bytes:
        """Serialize and transmit a single message.

        Parameters
        ----------
        message:
            The ``NetworkMessage`` to send.

        Returns
        -------
        bytes
            The raw wire bytes that were actually transmitted.
        """
        ...

    def receive(self) -> NetworkMessage | None:
        """Read and deserialize the next available message.

        Returns
        -------
        NetworkMessage or None
            The deserialized message, or ``None`` if no data is available
            (e.g. non-blocking read with nothing pending).
        """
        ...

    # -- state --------------------------------------------------------------

    @property
    def status(self) -> TransportStatus:
        """Current connection status."""
        ...


# ---------------------------------------------------------------------------
# Message framing — length-prefixed JSON
# ---------------------------------------------------------------------------

_LENGTH_PREFIX_SIZE = 4
_LENGTH_FORMAT = "!I"  # 4-byte big-endian unsigned int


class MessageFramer:
    """Serialize and deserialize ``NetworkMessage`` with a length-prefix
    framing scheme.

    Wire format per message::

        | 4 bytes (big-endian uint32) | N bytes (JSON payload) |
        | length prefix              | message body           |

    This allows a stream of concatenated messages to be unambiguously
    delimited without requiring any application-level delimiter characters.
    """

    @staticmethod
    def encode(message: NetworkMessage) -> bytes:
        """Encode a single message into length-prefixed wire bytes."""
        body = message.model_dump_json().encode("utf-8")
        return struct.pack(_LENGTH_FORMAT, len(body)) + body

    @staticmethod
    def decode(data: bytes) -> NetworkMessage:
        """Decode a single length-prefixed message from *data*.

        Parameters
        ----------
        data:
            Must contain at least one complete framed message.

        Raises
        ------
        ValueError
            If the data is too short to contain a valid frame.
        """
        if len(data) < _LENGTH_PREFIX_SIZE:
            raise ValueError(
                f"insufficient data for length prefix "
                f"(have {len(data)}, need {_LENGTH_PREFIX_SIZE})"
            )

        length = struct.unpack(_LENGTH_FORMAT, data[:_LENGTH_PREFIX_SIZE])[0]
        end = _LENGTH_PREFIX_SIZE + length

        if len(data) < end:
            raise ValueError(
                f"incomplete message body "
                f"(have {len(data) - _LENGTH_PREFIX_SIZE}, need {length})"
            )

        body = data[_LENGTH_PREFIX_SIZE:end]
        return NetworkMessage.model_validate_json(body)

    @staticmethod
    def encode_batch(messages: list[NetworkMessage]) -> bytes:
        """Encode multiple messages into a single byte stream."""
        return b"".join(MessageFramer.encode(msg) for msg in messages)

    @staticmethod
    def decode_stream(data: bytes) -> list[NetworkMessage]:
        """Decode all complete messages from a byte stream.

        Any trailing bytes that do not form a complete frame are silently
        ignored (they will be delivered on the next call).

        Parameters
        ----------
        data:
            A potentially partial stream of framed messages.
        """
        messages: list[NetworkMessage] = []
        offset = 0

        while offset + _LENGTH_PREFIX_SIZE <= len(data):
            length = struct.unpack(
                _LENGTH_FORMAT, data[offset : offset + _LENGTH_PREFIX_SIZE]
            )[0]
            end = offset + _LENGTH_PREFIX_SIZE + length

            if end > len(data):
                # Incomplete frame — stop here; remainder is buffered
                break

            msg = MessageFramer.decode(data[offset:end])
            messages.append(msg)
            offset = end

        return messages
