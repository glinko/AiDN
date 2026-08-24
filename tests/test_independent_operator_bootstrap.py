import shutil
import subprocess
from pathlib import Path

import pytest


def test_ubuntu_bootstrap_is_loopback_only_and_requires_explicit_peer_identity() -> None:
    script = Path("tools/bootstrap-independent-operator-ubuntu.sh").read_text(encoding="utf-8")

    assert "--peer-id is required" in script
    assert "--host 127.0.0.1" in script
    assert "install-cometbft-ubuntu.sh" in script
    assert "--consensus-mode MODE" in script
    assert "--consensus-rpc URL" in script
    assert "AIDN_COMETBFT_ENDPOINT" in script
    assert "consensus_transport='external_rpc'" in script
    assert "if [[ \"$consensus_mode\" == 'validator' ]]; then" in script
    assert "automatic_install\":false" in script
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
    assert "Expose Dashboard/API to the LAN on 0.0.0.0?" in script
    assert "Loopback limits the dashboard and API to this machine" in script
    assert "AiDN NODE INSTALLATION COMPLETE" in script
    assert "[PUBLIC ARTIFACTS — SAFE TO SHARE]" in script
    assert "[PRIVATE MATERIAL — NEVER COPY OR SHARE]" in script
    assert "dashboard_pairing_code" in script
    assert "dashboard_pairing_expires" in script
    assert "print(json.dumps(payload, sort_keys=True))" not in script
    assert "hypervisor-bind-host" in script
    assert "AIDN_HYPERVISOR_RESTART_ON_BIND_CHANGE=true" in script
    assert "AIDN_DASHBOARD_ACCESS_ALLOW_INSECURE_LAN=true" in script
    assert "127.0.0.1|0.0.0.0" in script
    assert "--enable-registry" in script
    assert "systemctl --user enable --now" in script
    assert "loginctl enable-linger" in script
    assert "master-key.b64" in script
    assert "AIDN_SECRET_MANAGER_MASTER_KEY" in script
    assert "operator-attestation-key.raw" in script
    assert "--consensus-mode MODE" in script
    assert "--setup-mode MODE" in script
    assert "--setup-provider ID" in script
    assert "--setup-model ID" in script
    assert "--setup-model-source SRC" in script
    assert "--setup-endpoint ACTION" in script
    assert "--setup-handoff TARGET" in script
    assert "Installation mode (manual/ai_assisted)" in script
    assert "AI-assisted provider (skip/ollama/llama.cpp/vllm)" in script
    assert "AI-assisted endpoint step (skip/draft/start)" in script
    assert "prompt_choice()" in script
    assert "prompt_model_choice()" in script
    assert "Qwen/Qwen3-0.6B-GGUF:Q8_0" in script
    assert "Qwen/Qwen3-4B-GGUF:Q4_K_M" in script
    assert "Qwen/Qwen3-14B-GGUF:Q4_K_M" in script
    assert "VRAM ~7–10 GB" in script
    assert "Введите номер" in script
    assert "start_model_prefetch" in script
    assert "model_prefetch_progress" in script
    assert "AIDN_PREFETCH_MAX_BYTES" in script
    assert ".aidn-prefetch.json" in script
    assert "[MODEL CACHE PREFETCH]" in script
    assert "installation-plan.json" in script
    assert "AIDN_INSTALLATION_SETUP_MODE" in script
    assert "AIDN_INSTALLATION_PLAN_PATH" in script
    assert "AIDN_STEWARD_ENABLED=true" in script
    assert "no provider, model, or public Endpoint is changed implicitly" in script
    assert script.index("Installation mode (manual/ai_assisted)") < script.index(
        "Operator/node name"
    )
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


def test_release_operator_bootstrap_generates_assisted_wrapper_with_nounset(
    tmp_path: Path,
) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to execute the Ubuntu wrapper-generation fragment")

    script = Path("tools/aidn-operator-bootstrap-ubuntu.sh").read_text(encoding="utf-8")
    marker = 'cat > "$wrapper" <<EOF\n'
    start = script.index(marker)
    end = script.index("\nEOF\n", start) + len("\nEOF")
    fragment = script[start:end]
    harness = f"""\
set -euo pipefail
shell_quote() {{ printf '%q' "$1"; }}
wrapper=generated-wrapper.sh
repo_q=/tmp/aidn
data_q=/tmp/aidn-data
registry_q=/tmp/registry.json
python_q=/tmp/aidn/.venv/bin/python
bind_host_q=/tmp/aidn-data/hypervisor-bind-host
api_host_q=127.0.0.1
api_port_q=8000
setup_mode_q=ai_assisted
setup_plan_q=/tmp/aidn-data/installation-plan.json
operator_id=main
runtime_broker_socket=/run/user/1000/aidn-provider-runtime.sock
{fragment}
test -s "$wrapper"
"""
    subprocess.run(
        [bash, "-c", harness],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    wrapper = (tmp_path / "generated-wrapper.sh").read_text(encoding="utf-8")
    assert 'if [[ "$AIDN_INSTALLATION_SETUP_MODE" == \'ai_assisted\' ]]; then' in wrapper


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
    assert f"expected_command_python='{canonical_command}'" in rollout
    assert "expected_command_python3=" in rollout
    assert '"$actual_command" == "$expected_command_python3"' in rollout
    assert "--enable-dashboard-access" in rollout
    assert "mcp-dashboard-access-master-key.b64" in rollout
    assert "AIDN_SECRET_MANAGER_PATH=/state/mcp-dashboard-access-secrets.json" in rollout
    assert "operator_cli_wrapper" in rollout
    assert "operator_pairing_command" in rollout
    assert "aidn_hypervisor.operator_cli" in rollout


def test_agent_enrollment_playbook_keeps_secrets_out_of_operator_prompts() -> None:
    playbook = Path("docs/development/agent-enrollment-operator-playbook.md").read_text(
        encoding="utf-8"
    )

    assert "Settings -> Agent enrollment requests" in playbook
    assert "Key fingerprint" in playbook
    assert "Do not send me" in playbook
    assert "any token, pairing code" in playbook
    assert "MCP_ENROLLMENT_DISABLED" in playbook
    assert "aidn-operator pair" in playbook


def test_cometbft_installer_is_pinned_idempotent_and_preserves_genesis() -> None:
    script = Path("tools/install-cometbft-ubuntu.sh").read_text(encoding="utf-8")

    assert "DEFAULT_VERSION='v0.38.19'" in script
    assert "go install \"github.com/cometbft/cometbft/cmd/cometbft@$version\"" in script
    assert "refusing to rewrite it" in script
    assert "user_systemctl enable --now \"$service_name\"" in script
    assert "ProtectSystem=strict" in script
    assert "ReadWritePaths=$home" in script
    assert "--no-start" in script
    assert "--no-abci" in script
    assert 'else "noop"' in script
    assert "priv_validator_state.json" in script
    assert "refusing to recreate signing state" in script
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
