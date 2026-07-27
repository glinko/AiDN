"""M11-S3: Known Control Group Manager — anti-Sybil detection."""

from __future__ import annotations

import hashlib

from aidn_hypervisor.eligibility.models import (
    KnownControlGroup,
)


class KCGManager:
    """Detects and manages Known Control Groups (KCGs).

    KCGs are groups of services controlled by the same entity,
    detected via shared reward beneficiary wallets. Used to enforce
    concentration caps and diversity factors.
    """

    def __init__(self) -> None:
        # group_id → KnownControlGroup
        self._groups: dict[str, KnownControlGroup] = {}
        # service_id → group_id
        self._service_groups: dict[str, str] = {}
        # wallet → group_id (for quick lookup)
        self._wallet_groups: dict[str, str] = {}

    def register_service(
        self,
        service_id: str,
        reward_beneficiary: str,
        stake: int,
        epoch: int,
    ) -> str | None:
        """Register a service and detect its KCG.

        Returns:
            group_id if the service belongs to a KCG, None otherwise.
        """
        group_id = self._wallet_groups.get(reward_beneficiary)

        if group_id is not None:
            # Existing group — add member
            self._add_to_existing_group(group_id, service_id, stake, epoch)
        else:
            # New potential group
            self._create_group(reward_beneficiary, service_id, stake, epoch)
            group_id = self._wallet_groups[reward_beneficiary]

        self._service_groups[service_id] = group_id
        return group_id

    def get_group(self, group_id: str) -> KnownControlGroup | None:
        """Get a KCG by ID."""
        return self._groups.get(group_id)

    def get_group_for_service(
        self, service_id: str
    ) -> KnownControlGroup | None:
        """Get the KCG for a service."""
        group_id = self._service_groups.get(service_id)
        if group_id is None:
            return None
        return self._groups.get(group_id)

    def get_group_for_wallet(
        self, wallet: str
    ) -> KnownControlGroup | None:
        """Get the KCG for a reward beneficiary wallet."""
        group_id = self._wallet_groups.get(wallet)
        if group_id is None:
            return None
        return self._groups.get(group_id)

    def get_all_groups(self) -> list[KnownControlGroup]:
        """Get all KCGs."""
        return list(self._groups.values())

    def get_service_group_id(
        self, service_id: str
    ) -> str | None:
        """Get the group ID for a service."""
        return self._service_groups.get(service_id)

    def remove_service(
        self, service_id: str, epoch: int
    ) -> None:
        """Remove a service from its KCG."""
        group_id = self._service_groups.pop(service_id, None)
        if group_id is None:
            return

        group = self._groups.get(group_id)
        if group is None:
            return

        new_members = [
            s for s in group.member_service_ids if s != service_id
        ]
        new_group = group.model_copy(
            update={
                "member_service_ids": new_members,
                "last_updated_epoch": epoch,
            }
        )

        # If group becomes empty, remove it
        if not new_members:
            del self._groups[group_id]
            # Also clean up wallet mapping
            for w, gid in list(self._wallet_groups.items()):
                if gid == group_id:
                    del self._wallet_groups[w]
        else:
            self._groups[group_id] = new_group

    def update_concentration(
        self, group_id: str, total_network_stake: int
    ) -> None:
        """Update concentration percentage for a group."""
        group = self._groups.get(group_id)
        if group is None:
            return

        if total_network_stake == 0:
            pct = 0.0
        else:
            pct = (group.total_stake / total_network_stake) * 100.0

        self._groups[group_id] = group.model_copy(
            update={
                "concentration_percentage": round(pct, 4),
            }
        )

    def update_aggregate_weight(
        self, group_id: str, weight: float
    ) -> None:
        """Update aggregate weight for a group."""
        group = self._groups.get(group_id)
        if group is None:
            return

        self._groups[group_id] = group.model_copy(
            update={"aggregate_weight": round(weight, 6)}
        )

    # ── Internal ───────────────────────────────────────────────

    def _create_group(
        self,
        reward_beneficiary: str,
        service_id: str,
        stake: int,
        epoch: int,
    ) -> None:
        """Create a new KCG."""
        group_id = self._generate_group_id(reward_beneficiary)
        group = KnownControlGroup(
            group_id=group_id,
            reward_beneficiary=reward_beneficiary,
            member_service_ids=[service_id],
            total_stake=stake,
            detected_at_epoch=epoch,
            last_updated_epoch=epoch,
        )
        self._groups[group_id] = group
        self._wallet_groups[reward_beneficiary] = group_id

    def _add_to_existing_group(
        self, group_id: str, service_id: str, stake: int, epoch: int
    ) -> None:
        """Add a service to an existing KCG."""
        group = self._groups.get(group_id)
        if group is None:
            return

        if service_id in group.member_service_ids:
            return

        self._groups[group_id] = group.model_copy(
            update={
                "member_service_ids": [*group.member_service_ids, service_id],
                "total_stake": group.total_stake + stake,
                "last_updated_epoch": epoch,
            }
        )

    @staticmethod
    def _generate_group_id(reward_beneficiary: str) -> str:
        """Generate a deterministic group ID from the beneficiary."""
        raw = f"kcg:{reward_beneficiary}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @property
    def group_count(self) -> int:
        """Number of KCGs."""
        return len(self._groups)
