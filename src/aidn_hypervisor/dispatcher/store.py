from typing import TYPE_CHECKING

from aidn_hypervisor.dispatcher.models import (
    DeadLetterRecord,
    DeliveryRecord,
    DispatcherReplayRecord,
    DispatcherRoute,
    NetworkMessage,
)

if TYPE_CHECKING:
    from aidn_hypervisor.state import HypervisorStateSnapshot


class DispatcherStore:
    """Persists durable Dispatcher state without serializing local handlers."""

    def __init__(self, state_store=None) -> None:
        self._state_store = state_store
        self.routes: dict[tuple[str, str], DispatcherRoute] = {}
        self.queued_messages: dict[str, NetworkMessage] = {}
        self.delivery_records: dict[str, DeliveryRecord] = {}
        self.replays: dict[str, DispatcherReplayRecord] = {}
        self.dead_letters: list[DeadLetterRecord] = []
        self.restore()

    def restore(self, snapshot: "HypervisorStateSnapshot | None" = None) -> None:
        if snapshot is None:
            if self._state_store is None:
                return
            snapshot = self._state_store.load()
        self.routes = {
            (item.destination_type, item.destination_id): item
            for item in snapshot.dispatcher_routes
        }
        self.queued_messages = {
            item.message_id: item for item in snapshot.dispatcher_queued_messages
        }
        self.delivery_records = {
            item.message_id: item for item in snapshot.dispatcher_delivery_records
        }
        self.replays = {
            item.message_id: item for item in snapshot.dispatcher_replay_records
        }
        self.dead_letters = list(snapshot.dispatcher_dead_letters)

    def flush(self) -> None:
        if self._state_store is None:
            return
        snapshot = self._state_store.load().model_copy(
            update={
                "dispatcher_routes": list(self.routes.values()),
                "dispatcher_queued_messages": list(self.queued_messages.values()),
                "dispatcher_delivery_records": list(self.delivery_records.values()),
                "dispatcher_replay_records": list(self.replays.values()),
                "dispatcher_dead_letters": list(self.dead_letters),
            }
        )
        self._state_store.save(snapshot)
