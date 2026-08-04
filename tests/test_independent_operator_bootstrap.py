from pathlib import Path


def test_ubuntu_bootstrap_is_loopback_only_and_requires_explicit_peer_identity() -> None:
    script = Path("tools/bootstrap-independent-operator-ubuntu.sh").read_text(encoding="utf-8")

    assert "--peer-id is required" in script
    assert "--host 127.0.0.1" in script
    assert "replication\":\"disabled_until_mutual_peer_approval" in script
    assert "AIDN_REGISTRY_REPLICATION_CONFIG" not in script


def test_cross_host_registry_smoke_is_explicitly_test_only() -> None:
    script = Path("tools/run-cross-host-registry-smoke.sh").read_text(encoding="utf-8")

    assert "--remote-ssh is required" in script
    assert "registry_replication_peer_acceptance.py" in script
    assert "remote checkout auto-discovery expected one candidate" in script
    assert "--host 127.0.0.1" in script
    assert "test-only disposable identities" in script
    assert ".venv/bin/python" in script


def test_systemd_replication_installer_keeps_master_key_out_of_unit() -> None:
    script = Path("tools/install-registry-testnet-systemd.sh").read_text(encoding="utf-8")

    assert "--root and --repo are required" in script
    assert "master-key.b64" in script
    assert "AIDN_SECRET_MANAGER_MASTER_KEY" in script
    assert "ReadWritePaths=$root" in script
    assert "ProtectHome=read-only" in script
    assert "sudo install -o root -g root -m 0644" in script
    assert "refusing to replace running replication process" in script
    assert '< "\\$root/master-key.b64")' in script
    assert '\\"$root/master-key.b64\\"' not in script
    assert "EnvironmentFile" not in script


def test_release_operator_bootstrap_uses_safe_defaults_and_user_systemd() -> None:
    script = Path("tools/aidn-operator-bootstrap-ubuntu.sh").read_text(encoding="utf-8")

    assert "exec 3</dev/tty" in script
    assert "--non-interactive" in script
    assert "--allow-public-api" in script
    assert "--enable-registry" in script
    assert "systemctl --user enable --now" in script
    assert "loginctl enable-linger" in script
    assert "master-key.b64" in script
    assert "AIDN_SECRET_MANAGER_MASTER_KEY" in script
    assert "operator-attestation-key.raw" in script
    assert "raw.githubusercontent.com/glinko/AiDN/<reviewed-ref>" in script
    assert "sudo password was used only by sudo" in script
