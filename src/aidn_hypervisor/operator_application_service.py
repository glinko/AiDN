from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4


class OperatorApplicationService:
    """Operator-facing wallet, onboarding, and dashboard orchestration."""

    def __init__(self, host) -> None:
        self._host = host

    def owner_wallet_state(self) -> dict:
        if self._host._owner_wallet is None:
            return {
                "configured": False,
                "wallet_id": None,
                "public_key": None,
                "label": None,
                "created_at": None,
                "imported": False,
            }
        return {
            "configured": True,
            "wallet_id": self._host._owner_wallet["wallet_id"],
            "public_key": self._host._owner_wallet["public_key"],
            "label": self._host._owner_wallet.get("label"),
            "created_at": self._host._owner_wallet["created_at"],
            "imported": bool(self._host._owner_wallet.get("imported", False)),
        }

    def owner_wallet_private_key(self) -> str:
        if self._host._owner_wallet is None:
            raise ValueError("Owner wallet is not configured")
        return self._host._owner_wallet["private_key"]

    def node_identity(self) -> dict:
        owner = self.owner_wallet_state()
        return {
            "node_id": self._host.node_id,
            "operator_id": self._host.operator_id,
            "base_url": self._host.base_url,
            "owner_wallet_id": owner["wallet_id"],
            "ownership_configured": owner["configured"],
            "can_host_custom_model": self._host.can_host_custom_model,
        }

    def registry_enabled(self) -> bool:
        return False

    def validation_enabled(self) -> bool:
        return False

    def canonical_overlay_inventory(self) -> dict:
        return self._host._network_projection_service.canonical_overlay_inventory()

    def configure_owner_wallet(
        self,
        *,
        mode: str,
        label: str | None = None,
        private_key: str | None = None,
    ) -> dict:
        if mode not in {"create", "import"}:
            raise ValueError(f"Unsupported wallet bootstrap mode: {mode}")
        if mode == "import" and not private_key:
            raise ValueError("Private key is required for wallet import")

        resolved_private_key = private_key or f"sk-{uuid4().hex}{uuid4().hex}"
        digest = hashlib.sha256(resolved_private_key.encode("utf-8")).hexdigest()
        created_at = datetime.now(UTC).isoformat()
        self._host._owner_wallet = {
            "wallet_id": f"wallet-{digest[:12]}",
            "public_key": f"pk-{digest[:24]}",
            "private_key": resolved_private_key,
            "label": label,
            "created_at": created_at,
            "imported": mode == "import",
        }
        self._host._operator_onboarding = None
        self.sync_operator_onboarding_state(endpoint_items=[])
        return {
            "wallet": self.owner_wallet_state(),
            "private_key": resolved_private_key if mode == "create" else None,
        }

    def operator_onboarding_state(self) -> dict:
        if self._host._operator_onboarding is None:
            return {
                "completed": False,
                "completed_at": None,
                "completed_via": None,
                "current_step": "configure_wallet",
                "last_workspace": "home",
                "transition_history": [],
                "steps": [],
            }
        return deepcopy(self._host._operator_onboarding)

    def sync_operator_onboarding_state(
        self,
        *,
        endpoint_items: list[dict],
        last_workspace: str | None = None,
    ) -> dict:
        onboarding = self.operator_onboarding_state()
        already_completed = bool(onboarding.get("completed"))
        if last_workspace is not None:
            onboarding["last_workspace"] = last_workspace
        if already_completed or any(
            item.get("publication_status") == "published" for item in endpoint_items
        ):
            onboarding["completed"] = True
            onboarding["completed_via"] = (
                onboarding.get("completed_via") or "first_local_endpoint_published"
            )
            if onboarding["completed_at"] is None:
                onboarding["completed_at"] = datetime.now(UTC).isoformat()
            onboarding["current_step"] = "operate"
        elif endpoint_items:
            onboarding["completed"] = False
            onboarding["completed_via"] = None
            onboarding["completed_at"] = None
            onboarding["current_step"] = "publish_endpoint"
        elif self.owner_wallet_state()["configured"]:
            onboarding["completed"] = False
            onboarding["completed_via"] = None
            onboarding["completed_at"] = None
            onboarding["current_step"] = "attach_provider"
        else:
            onboarding["completed"] = False
            onboarding["completed_via"] = None
            onboarding["completed_at"] = None
            onboarding["current_step"] = "configure_wallet"
        self._host._operator_onboarding = onboarding
        self._host._persist_state()
        return deepcopy(onboarding)

    def operator_dashboard_home(self) -> dict:
        return self._host.operator_read_models.home()

    def operator_dashboard_fleet(self) -> dict:
        return self._host.operator_read_models.fleet()

    def operator_dashboard_endpoints(self) -> dict:
        return self._host.operator_read_models.endpoints()

    def operator_requests_policy(self) -> dict[str, bool | str]:
        return dict(self._host._operator_requests_policy)

    def update_operator_requests_policy(
        self,
        *,
        allow_spillover: bool,
        dispatch_strategy: str,
        ready_endpoint_only: bool,
    ) -> dict[str, bool | str]:
        if dispatch_strategy not in {"local_first", "balanced", "market_first"}:
            raise ValueError(f"Unsupported dispatch strategy: {dispatch_strategy}")
        self._host._operator_requests_policy = {
            "allow_spillover": bool(allow_spillover),
            "dispatch_strategy": dispatch_strategy,
            "ready_endpoint_only": bool(ready_endpoint_only),
        }
        self._host._persist_state()
        return self.operator_requests_policy()

    def operator_dashboard_requests(
        self,
        *,
        market_candidates: list[dict] | None = None,
    ) -> dict:
        return self._host.operator_read_models.requests(
            market_candidates=market_candidates,
        )
