from aidn_hypervisor.sessions.models import EndpointSession, LockedDeposit, ProxySessionBinding
from aidn_hypervisor.state import (
    EndpointSessionSnapshot,
    LockedDepositSnapshot,
    ProxySessionBindingSnapshot,
)


class SessionStore:
    def __init__(self, state_store=None) -> None:
        self._state_store = state_store
        self._sessions: dict[str, EndpointSession] = {}
        self._deposits: dict[str, LockedDeposit] = {}
        self._proxy_bindings: dict[str, ProxySessionBinding] = {}
        self.restore()

    def restore(self) -> None:
        if self._state_store is None:
            return
        root = self._state_store.load()
        self._sessions = {
            item.session_id: EndpointSession.model_validate(item.model_dump(mode="json"))
            for item in root.endpoint_sessions
        }
        self._deposits = {
            item.session_id: LockedDeposit.model_validate(item.model_dump(mode="json"))
            for item in root.locked_deposits
        }
        self._proxy_bindings = {
            item.local_session_id: ProxySessionBinding.model_validate(
                item.model_dump(mode="json")
            )
            for item in root.proxy_session_bindings
        }

    def list_sessions(self) -> list[EndpointSession]:
        return list(self._sessions.values())

    def get_session(self, session_id: str) -> EndpointSession:
        return self._sessions[session_id]

    def save_session(self, session: EndpointSession) -> None:
        self._sessions[session.session_id] = session
        self._flush()

    def save_deposit(self, deposit: LockedDeposit) -> None:
        self._deposits[deposit.session_id] = deposit
        self._flush()

    def get_deposit_for_session(self, session_id: str) -> LockedDeposit:
        return self._deposits[session_id]

    def get_proxy_session_binding(self, local_session_id: str) -> ProxySessionBinding:
        return self._proxy_bindings[local_session_id]

    def try_get_proxy_session_binding(
        self, local_session_id: str
    ) -> ProxySessionBinding | None:
        return self._proxy_bindings.get(local_session_id)

    def save_proxy_session_binding(self, binding: ProxySessionBinding) -> None:
        self._proxy_bindings[binding.local_session_id] = binding
        self._flush()

    def _flush(self) -> None:
        if self._state_store is None:
            return
        root = self._state_store.load()
        updated = root.model_copy(
            update={
                "endpoint_sessions": [
                    EndpointSessionSnapshot.model_validate(item.model_dump(mode="json"))
                    for item in self._sessions.values()
                ],
                "locked_deposits": [
                    LockedDepositSnapshot.model_validate(item.model_dump(mode="json"))
                    for item in self._deposits.values()
                ],
                "proxy_session_bindings": [
                    ProxySessionBindingSnapshot.model_validate(
                        item.model_dump(mode="json")
                    )
                    for item in self._proxy_bindings.values()
                ],
            }
        )
        self._state_store.save(updated)
