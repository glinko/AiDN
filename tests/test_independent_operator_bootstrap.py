from pathlib import Path


def test_ubuntu_bootstrap_is_loopback_only_and_requires_explicit_peer_identity() -> None:
    script = Path("tools/bootstrap-independent-operator-ubuntu.sh").read_text(encoding="utf-8")

    assert "--peer-id is required" in script
    assert "--host 127.0.0.1" in script
    assert "install-cometbft-ubuntu.sh" in script
    assert "--consensus-mode MODE" in script
    assert "AIDN_COMETBFT_ENDPOINT" in script
    assert "systemctl --user enable --now \"$consensus_service_name\"" in script
    assert "replication\":\"disabled_until_mutual_peer_approval" in script
    assert "AIDN_REGISTRY_REPLICATION_CONFIG" not in script
    assert "install-node-runtime-ubuntu.sh" in script
    assert "build-operator-dashboard.sh" in script


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
    assert "--consensus-mode MODE" in script
    assert "install-cometbft-ubuntu.sh" in script
    assert "AIDN_COMETBFT_SERVICE" in script
    assert "systemctl --user enable --now \"$consensus_service_name\"" in script
    assert "aidn_hypervisor.resource_probe" in script
    assert "AIDN_RESOURCE_CAPACITY_PATH" in script
    assert "resource-capacity.json" in script
    assert "Restart=always" in script
    assert "raw.githubusercontent.com/glinko/AiDN/<reviewed-ref>" in script
    assert "sudo password was used only by sudo" in script
    assert "install-node-runtime-ubuntu.sh" in script
    assert "build-operator-dashboard.sh" in script
    assert "aidn-operator-wrapper.sh" in script
    assert "master-key-file" in script
    assert "ln -sfn" in script


def test_dashboard_build_tools_pin_and_verify_the_frontend_toolchain() -> None:
    node_installer = Path("tools/install-node-runtime-ubuntu.sh").read_text(
        encoding="utf-8"
    )
    dashboard_builder = Path("tools/build-operator-dashboard.sh").read_text(
        encoding="utf-8"
    )

    assert "DEFAULT_NODE_VERSION='v24.19.0'" in node_installer
    assert "SHASUMS256.txt" in node_installer
    assert "sha256sum" in node_installer
    assert "linux-${node_arch}" in node_installer
    assert "PNPM_VERSION='11.16.0'" in dashboard_builder
    assert 'install --frozen-lockfile' in dashboard_builder
    assert "react-dashboard" in dashboard_builder
    assert "old directory remains intact" in dashboard_builder


def test_dashboard_rollout_accepts_the_canonical_image_command() -> None:
    rollout = Path("tools/rollout-operator-dashboard-ubuntu.sh").read_text(
        encoding="utf-8"
    )
    dockerfile = Path("tools/lan-testnet.Dockerfile").read_text(encoding="utf-8")
    canonical_command = (
        '["python","-m","uvicorn","aidn_hypervisor.main:build_app",'
        '"--factory","--host","0.0.0.0","--port","8000"]'
    )

    assert 'CMD ["python", "-m", "uvicorn", "aidn_hypervisor.main:build_app"' in dockerfile
    assert f"expected_command='{canonical_command}'" in rollout


def test_cometbft_installer_is_pinned_idempotent_and_preserves_genesis() -> None:
    script = Path("tools/install-cometbft-ubuntu.sh").read_text(encoding="utf-8")

    assert "DEFAULT_VERSION='v0.38.19'" in script
    assert "go install \"github.com/cometbft/cometbft/cmd/cometbft@$version\"" in script
    assert "refusing to rewrite it" in script
    assert "systemctl --user enable --now \"$service_name\"" in script
    assert "ProtectSystem=strict" in script
    assert "ReadWritePaths=$home" in script
    assert "--no-start" in script
    assert "--no-abci" in script
    assert "Restart=always" in script


def test_existing_cometbft_runtime_can_be_supervised_without_state_rewrite() -> None:
    script = Path("tools/install-existing-cometbft-user-service.sh").read_text(
        encoding="utf-8"
    )

    assert "Restart=always" in script
    assert "systemctl --user enable" in script
    assert "systemctl --user restart" in script
    assert "ReadWritePaths=$home" in script
    assert "config.toml" not in script
