"""SessionFailurePoller — periodic timeout enforcement for RFC-0060.

Polls registered sessions for expired recovery windows and other
timeout conditions, then triggers state transitions via the handler.
"""

from __future__ import annotations

from aidn_hypervisor.session_failure.service import SessionFailureHandler


class SessionFailurePoller:
    """Polls for expired recovery windows and timeout conditions.

    Designed to be called periodically (e.g. every 10-30 seconds) by
    a scheduler or the main event loop.
    """

    def __init__(self, handler: SessionFailureHandler) -> None:
        self.handler = handler

    def sweep_expired_recoveries(self) -> list[str]:
        """Check all recovering sessions for expired recovery windows.

        Returns:
            List of session IDs that were transitioned to force_closing.
        """
        expired: list[str] = []

        # Get all tracked session IDs
        session_ids = list(self.handler._session_states.keys())

        for session_id in session_ids:
            if self.handler.is_recovery_expired(session_id):
                event = self.handler.expire_recovery(session_id)
                if event is not None:
                    expired.append(session_id)

        return expired

    def sweep_all(self) -> dict[str, list[str]]:
        """Run all sweep passes.

        Returns:
            Dict mapping sweep type to list of affected session IDs.
        """
        return {
            "expired_recoveries": self.sweep_expired_recoveries(),
        }
