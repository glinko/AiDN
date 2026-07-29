"""Operator configuration for signed remote snapshot trust anchors."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from .sync_mode import SyncModeConfig
from .trust_anchor import (
    CheckpointValidator,
    PersistentTrustAnchorStore,
    RemoteTrustAnchorClient,
    SignedTrustAnchor,
    TrustedAnchorSyncAdvisor,
)


class RemoteTrustAnchorDeploymentConfig(BaseModel, frozen=True):
    source_url: str
    storage_path: Path
    trusted_signers: dict[str, str]
    expected_network_id: str = Field(min_length=1)
    expected_chain_id: str = Field(min_length=1)
    expected_network_revision: int = Field(ge=0)
    max_checkpoint_age_blocks: int = Field(default=10_000, gt=0)
    max_checkpoint_age_seconds: int = Field(default=2_592_000, gt=0)

    @field_validator("source_url")
    @classmethod
    def _source_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("remote trust anchor source must use HTTPS")
        return value

    @field_validator("trusted_signers")
    @classmethod
    def _trusted_signers(cls, value: dict[str, str]) -> dict[str, str]:
        if not value or any(not signer_id or not key for signer_id, key in value.items()):
            raise ValueError("remote trust anchor trusted signers are required")
        return dict(value)


class RemoteTrustAnchorRuntime:
    """Explicit refresh boundary from remote signed evidence to state-sync config."""

    def __init__(
        self,
        *,
        config: RemoteTrustAnchorDeploymentConfig,
        client: RemoteTrustAnchorClient | None = None,
    ) -> None:
        self._config = config
        self._store = PersistentTrustAnchorStore(
            path=config.storage_path, trusted_signers=config.trusted_signers
        )
        self._client = client or RemoteTrustAnchorClient()
        self._advisor = TrustedAnchorSyncAdvisor(
            store=self._store,
            validator=CheckpointValidator(
                max_checkpoint_age_blocks=config.max_checkpoint_age_blocks,
                max_checkpoint_age_seconds=config.max_checkpoint_age_seconds,
            ),
            expected_network_id=config.expected_network_id,
            expected_chain_id=config.expected_chain_id,
            expected_network_revision=config.expected_network_revision,
        )

    def refresh(self) -> SignedTrustAnchor:
        envelope = self._client.fetch(self._config.source_url)
        self._store.add(envelope)
        return envelope

    def apply_to_sync_mode_config(
        self,
        config: SyncModeConfig,
        *,
        current_height: int,
        current_time: str,
    ) -> SyncModeConfig:
        return self._advisor.apply_to_sync_mode_config(
            config, current_height=current_height, current_time=current_time
        )

    def latest(self) -> SignedTrustAnchor | None:
        return self._store.latest()


def load_remote_trust_anchor_deployment_config(
    path: Path,
) -> RemoteTrustAnchorDeploymentConfig:
    try:
        return RemoteTrustAnchorDeploymentConfig.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("remote trust anchor configuration cannot be loaded") from error
