from __future__ import annotations

import hashlib
import zipfile

import pytest

from aidn_hypervisor.consensus.backup import (
    ValidatorBackupError,
    create_validator_backup,
    restore_validator_backup,
)
from aidn_hypervisor.main import build_app


def _create_validator_state(monkeypatch, root, *, finalize: bool = True):
    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(root / "hypervisor.json"))
    monkeypatch.setenv("AIDN_CONSENSUS_MODE", "validator")
    monkeypatch.setenv("AIDN_COMETBFT_ABCI_STATE_PATH", str(root / "abci"))
    monkeypatch.setenv("AIDN_COMETBFT_ABCI_PORT", "0")
    app = build_app()
    consensus = app.state.consensus_service
    assert consensus is not None and consensus.abci is not None
    if finalize:
        result, _ = consensus.abci.finalize_block_with_results(
            block_height=1,
            block_hash=hashlib.sha256(b"backup drill").digest(),
            txs=[],
        )
        assert result.code == "ok"
    return app


def test_backup_restore_drill_recovers_a_startable_validator(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _create_validator_state(monkeypatch, source)
    archive = tmp_path / "validator-backup.zip"
    manifest = create_validator_backup(
        hypervisor_state_path=source / "hypervisor.json",
        abci_state_path=source / "abci",
        archive_path=archive,
    )
    target = tmp_path / "restored"
    assert restore_validator_backup(archive_path=archive, target_root=target) == manifest

    restarted = _create_validator_state(monkeypatch, target, finalize=False).state.consensus_service
    assert restarted is not None and restarted.abci is not None
    assert restarted.abci.info().last_block_height == 1


def test_restore_rejects_tampered_archive(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _create_validator_state(monkeypatch, source)
    archive = tmp_path / "validator-backup.zip"
    create_validator_backup(
        hypervisor_state_path=source / "hypervisor.json",
        abci_state_path=source / "abci",
        archive_path=archive,
    )
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive) as input_archive, zipfile.ZipFile(tampered, "w") as output_archive:
        for member in input_archive.infolist():
            payload = input_archive.read(member.filename)
            if member.filename == "hypervisor.json":
                payload += b"\n"
            output_archive.writestr(member, payload)

    with pytest.raises(ValidatorBackupError, match="hashes"):
        restore_validator_backup(archive_path=tampered, target_root=tmp_path / "restored")
