#!/usr/bin/env bash
# Install one persistent AiDN operator on Ubuntu 24.04+.
#
# The default deployment is safe for a fresh host: the Hypervisor API and the
# Registry listener bind to loopback, no firewall rule is changed, and no
# private key or sudo password is printed or persisted in unit metadata.
set -euo pipefail

readonly REPOSITORY_URL="https://github.com/glinko/AiDN.git"
readonly SCRIPT_NAME="aidn-operator-bootstrap-ubuntu.sh"

usage() {
  cat <<'EOF'
Usage:
  aidn-operator-bootstrap-ubuntu.sh [options]

Interactive wizard (default):
  curl --proto '=https' --tlsv1.2 -fsSL \
    https://raw.githubusercontent.com/glinko/AiDN/<reviewed-ref>/tools/aidn-operator-bootstrap-ubuntu.sh \
    | bash -s -- --ref <reviewed-ref>

Options:
  --operator-id ID          Operator/node identity (default: sanitized hostname)
  --peer-id ID              Registry peer ID (default: operator ID)
  --control-group-id ID     Declared control group (default: control-group-<operator>)
  --ref REF                 Git branch, tag, or reviewed commit (default: main)
  --install-dir DIR         Checkout path (default: $HOME/aidn/<operator>/AiDN)
  --data-dir DIR            Persistent state path (default: $HOME/.local/share/aidn/<operator>)
  --api-host HOST           Hypervisor bind address (default: 127.0.0.1)
  --api-port PORT           Hypervisor API port (default: 8766)
  --allow-public-api        Confirm an explicit non-loopback API bind
  --enable-registry         Enable the mTLS Registry listener
  --registry-listen-host H  Registry bind address (default: 0.0.0.0 when enabled)
  --registry-port PORT      Registry mTLS port (default: 9444)
  --advertise-host HOST     Address included in public-peer.json
  --network-id ID           Network ID (default: aidn)
  --chain-id ID             Chain ID (default: aidn-testnet-1)
  --network-revision REV    Network revision (default: 1.0)
  --consensus-mode MODE     validator, non_validator, or disabled (default: validator)
  --consensus-rpc URL       Verified private RPC for non_validator mode (required)
  --cometbft-version TAG   CometBFT release tag (default: v0.38.19)
  --no-consensus             Disable automatic local CometBFT installation
  --no-start                Install and write the user service, but do not start it
  --wallet-action ACTION    create, import, or skip (interactive default: create)
  --dashboard-pairing ACTION create or skip (interactive default: create)
  --agent-action ACTION     guide or skip existing MCP enrollment (default: guide)
  --non-interactive         Use defaults and supplied flags; fail if a value is unsafe
  -h, --help                Show this help

The wizard reads prompts from /dev/tty, so it also works when downloaded via
curl | bash. It never asks for, stores, or sends a root password. Ubuntu sudo
prompts normally when package installation is required.

The installer creates a host-local encrypted Registry Secret Manager and an
Ed25519 operator identity. The private material stays below --data-dir with
mode 0600. Exchange only public-peer.json and operator-public-identity.json
after independent out-of-band approval.
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

require_value() {
  [[ $# -ge 2 ]] || die "$1 requires a value"
}

valid_identifier() {
  [[ "$1" =~ ^[A-Za-z0-9._-]+$ ]]
}

valid_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && (( 1 <= 10#$1 && 10#$1 <= 65535 ))
}

valid_path() {
  [[ "$1" =~ ^/[A-Za-z0-9._/-]+$ && "$1" != *".."* ]]
}

is_loopback_host() {
  [[ "$1" == "127.0.0.1" || "$1" == "::1" || "$1" == "localhost" ]]
}

valid_consensus_rpc() {
  [[ "$1" =~ ^https?://[^[:space:]/]+:[0-9]+/?$ ]]
}

sanitize_hostname() {
  local value
  value="$(hostname -s 2>/dev/null || printf 'aidn-operator')"
  value="$(printf '%s' "$value" | tr -c 'A-Za-z0-9._-' '-')"
  value="${value#-}"
  value="${value%-}"
  if [[ -z "$value" ]] || ! valid_identifier "$value"; then
    value='aidn-operator'
  fi
  printf '%s' "$value"
}

detect_advertise_host() {
  local value
  value="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [[ -z "$value" ]]; then
    value='127.0.0.1'
  fi
  printf '%s' "$value"
}

prompt_value() {
  local label="$1"
  local default_value="$2"
  local answer
  if [[ "$non_interactive" == 'true' ]]; then
    printf '%s' "$default_value"
    return
  fi
  if [[ -n "$default_value" ]]; then
    printf '%s [%s]: ' "$label" "$default_value" >&2
  else
    printf '%s: ' "$label" >&2
  fi
  IFS= read -r -u 3 answer || die 'interactive wizard requires a terminal'
  if [[ -z "$answer" ]]; then
    answer="$default_value"
  fi
  printf '%s' "$answer"
}

prompt_yes_no() {
  local label="$1"
  local default_value="$2"
  local answer
  if [[ "$non_interactive" == 'true' ]]; then
    [[ "$default_value" == 'yes' ]]
    return
  fi
  printf '%s [%s]: ' "$label" "$default_value" >&2
  IFS= read -r -u 3 answer || die 'interactive wizard requires a terminal'
  answer="${answer,,}"
  [[ -n "$answer" ]] || answer="$default_value"
  [[ "$answer" == 'y' || "$answer" == 'yes' ]]
}

shell_quote() {
  printf '%q' "$1"
}

operator_id=''
peer_id=''
control_group_id=''
ref='main'
install_dir=''
data_dir=''
api_host='127.0.0.1'
api_port='8766'
allow_public_api='false'
api_host_supplied='false'
enable_registry='false'
registry_listen_host=''
registry_listen_host_supplied='false'
registry_port='9444'
advertise_host=''
network_id='aidn'
chain_id='aidn-testnet-1'
network_revision='1.0'
consensus_mode='validator'
consensus_rpc=''
cometbft_version='v0.38.19'
no_start='false'
non_interactive='false'
wallet_action=''
dashboard_pairing_action=''
agent_action=''
operator_id_supplied='false'
enable_registry_supplied='false'
consensus_mode_supplied='false'
consensus_rpc_supplied='false'
wallet_action_supplied='false'
dashboard_pairing_supplied='false'
agent_action_supplied='false'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --operator-id|--node-name)
      require_value "$1" "$@"
      operator_id="$2"
      operator_id_supplied='true'
      shift 2
      ;;
    --peer-id)
      require_value "$1" "$@"
      peer_id="$2"
      shift 2
      ;;
    --control-group-id)
      require_value "$1" "$@"
      control_group_id="$2"
      shift 2
      ;;
    --ref)
      require_value "$1" "$@"
      ref="$2"
      shift 2
      ;;
    --install-dir)
      require_value "$1" "$@"
      install_dir="$2"
      shift 2
      ;;
    --data-dir)
      require_value "$1" "$@"
      data_dir="$2"
      shift 2
      ;;
    --api-host)
      require_value "$1" "$@"
      api_host="$2"
      api_host_supplied='true'
      shift 2
      ;;
    --api-port)
      require_value "$1" "$@"
      api_port="$2"
      shift 2
      ;;
    --allow-public-api)
      allow_public_api='true'
      shift
      ;;
    --enable-registry)
      enable_registry='true'
      enable_registry_supplied='true'
      shift
      ;;
    --registry-listen-host)
      require_value "$1" "$@"
      registry_listen_host="$2"
      registry_listen_host_supplied='true'
      shift 2
      ;;
    --registry-port)
      require_value "$1" "$@"
      registry_port="$2"
      shift 2
      ;;
    --advertise-host)
      require_value "$1" "$@"
      advertise_host="$2"
      shift 2
      ;;
    --network-id)
      require_value "$1" "$@"
      network_id="$2"
      shift 2
      ;;
    --chain-id)
      require_value "$1" "$@"
      chain_id="$2"
      shift 2
      ;;
    --network-revision)
      require_value "$1" "$@"
      network_revision="$2"
      shift 2
      ;;
    --consensus-mode)
      require_value "$1" "$@"
      consensus_mode="$2"
      consensus_mode_supplied='true'
      shift 2
      ;;
    --consensus-rpc)
      require_value "$1" "$@"
      consensus_rpc="$2"
      consensus_rpc_supplied='true'
      shift 2
      ;;
    --cometbft-version)
      require_value "$1" "$@"
      cometbft_version="$2"
      shift 2
      ;;
    --no-consensus)
      consensus_mode='disabled'
      consensus_mode_supplied='true'
      shift
      ;;
    --no-start)
      no_start='true'
      shift
      ;;
    --wallet-action)
      require_value "$1" "$@"
      wallet_action="$2"
      wallet_action_supplied='true'
      shift 2
      ;;
    --dashboard-pairing)
      require_value "$1" "$@"
      dashboard_pairing_action="$2"
      dashboard_pairing_supplied='true'
      shift 2
      ;;
    --agent-action)
      require_value "$1" "$@"
      agent_action="$2"
      agent_action_supplied='true'
      shift 2
      ;;
    --non-interactive)
      non_interactive='true'
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$non_interactive" != 'true' ]]; then
  [[ -r /dev/tty ]] || die 'interactive mode requires /dev/tty; use --non-interactive with explicit flags'
  exec 3</dev/tty
fi

if [[ -z "$operator_id" ]]; then
  operator_id="$(prompt_value 'Operator/node name' "$(sanitize_hostname)")"
fi
valid_identifier "$operator_id" || die 'operator ID contains unsupported characters'
[[ -n "$peer_id" ]] || peer_id="$operator_id"
valid_identifier "$peer_id" || die 'peer ID contains unsupported characters'
[[ -n "$control_group_id" ]] || control_group_id="control-group-$operator_id"
valid_identifier "$control_group_id" || die 'control group ID contains unsupported characters'
case "$consensus_mode" in
  validator|non_validator|disabled) ;;
  *) die 'consensus mode must be validator, non_validator, or disabled' ;;
esac

[[ "$cometbft_version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die 'CometBFT version must look like v0.38.19'

default_install_dir="$HOME/aidn/$operator_id/AiDN"
default_data_dir="$HOME/.local/share/aidn/$operator_id"
if [[ -z "$install_dir" ]]; then
  install_dir="$(prompt_value 'AiDN checkout path' "$default_install_dir")"
fi
if [[ -z "$data_dir" ]]; then
  data_dir="$(prompt_value 'Persistent data path' "$default_data_dir")"
fi
valid_path "$install_dir" || die 'install directory must be an absolute path'
valid_path "$data_dir" || die 'data directory must be an absolute path'

if [[ "$non_interactive" != 'true' && "$consensus_mode_supplied" != 'true' ]]; then
  consensus_mode="$(prompt_value 'Consensus mode (validator/non_validator/disabled)' "$consensus_mode")"
fi
case "$consensus_mode" in
  validator|non_validator|disabled) ;;
  *) die 'consensus mode must be validator, non_validator, or disabled' ;;
esac

if [[ "$consensus_mode" == 'non_validator' ]]; then
  if [[ -z "$consensus_rpc" && "$non_interactive" != 'true' ]]; then
    consensus_rpc="$(prompt_value 'Source CometBFT RPC (private HTTP URL)' '')"
  fi
  [[ -n "$consensus_rpc" ]] || die 'non_validator mode requires --consensus-rpc or an interactive source RPC'
  valid_consensus_rpc "$consensus_rpc" || die 'source CometBFT RPC must be an HTTP(S) host:port URL'
fi

if [[ "$wallet_action_supplied" != 'true' ]]; then
  if [[ "$non_interactive" == 'true' ]]; then
    wallet_action='skip'
  else
    wallet_action="$(prompt_value 'Owner wallet action (create/import/skip)' 'create')"
  fi
fi
case "$wallet_action" in
  create|import|skip) ;;
  *) die 'wallet action must be create, import, or skip' ;;
esac

if [[ "$dashboard_pairing_supplied" != 'true' ]]; then
  if [[ "$non_interactive" == 'true' ]]; then
    dashboard_pairing_action='skip'
  else
    dashboard_pairing_action="$(prompt_value 'Dashboard pairing (create/skip)' 'create')"
  fi
fi
case "$dashboard_pairing_action" in
  create|skip) ;;
  *) die 'dashboard pairing action must be create or skip' ;;
esac

if [[ "$agent_action_supplied" != 'true' ]]; then
  if [[ "$non_interactive" == 'true' ]]; then
    agent_action='skip'
  else
    agent_action='guide'
  fi
fi
case "$agent_action" in
  guide|skip) ;;
  *) die 'agent action must be guide or skip' ;;
esac

if [[ "$non_interactive" != 'true' ]]; then
  if [[ "$api_host_supplied" == 'true' ]]; then
    api_host="$(prompt_value 'Hypervisor API bind address' "$api_host")"
  elif prompt_yes_no 'Expose Dashboard/API to the LAN on 0.0.0.0?' 'no'; then
    api_host='0.0.0.0'
    allow_public_api='true'
  else
    api_host='127.0.0.1'
  fi
  api_port="$(prompt_value 'Hypervisor API port' "$api_port")"
fi
valid_port "$api_port" || die 'API port must be between 1 and 65535'
[[ -n "$api_host" && "$api_host" != *[[:space:]]* ]] || die 'API bind address is invalid'
if ! is_loopback_host "$api_host" && [[ "$allow_public_api" != 'true' ]]; then
  if [[ "$non_interactive" == 'true' ]]; then
    die 'non-loopback API requires --allow-public-api because the MVP API has no public auth boundary'
  fi
  prompt_yes_no 'The API is unauthenticated; allow a non-loopback bind?' 'no' || die 'public API bind was not approved'
  allow_public_api='true'
fi

if [[ "$enable_registry_supplied" != 'true' ]]; then
  if [[ "$non_interactive" != 'true' ]]; then
    if prompt_yes_no 'Enable the mTLS Registry listener for peer onboarding?' 'no'; then
      enable_registry='true'
    fi
  fi
fi
if [[ "$enable_registry" == 'true' ]]; then
  [[ -n "$registry_listen_host" ]] || registry_listen_host='0.0.0.0'
  if [[ "$non_interactive" != 'true' && "$registry_listen_host_supplied" != 'true' ]]; then
    registry_listen_host="$(prompt_value 'Registry listener bind address' "$registry_listen_host")"
    registry_port="$(prompt_value 'Registry mTLS port' "$registry_port")"
  fi
else
  registry_listen_host='127.0.0.1'
fi
valid_port "$registry_port" || die 'Registry port must be between 1 and 65535'
if [[ "$enable_registry" == 'true' && "$registry_port" == "$api_port" ]]; then
  die 'API and Registry ports must differ when both services run on one host'
fi
if [[ -z "$advertise_host" ]]; then
  advertise_host="$(detect_advertise_host)"
fi
[[ -n "$registry_listen_host" && "$registry_listen_host" != *[[:space:]]* ]] || die 'Registry bind address is invalid'
[[ -n "$advertise_host" && "$advertise_host" != *[[:space:]]* ]] || die 'advertise host is invalid'

if [[ "$EUID" -eq 0 ]]; then
  sudo_cmd=()
else
  sudo_cmd=(sudo)
  "${sudo_cmd[@]}" -v
fi

echo "Installing AiDN operator '$operator_id' from ref '$ref'" >&2
"${sudo_cmd[@]}" apt-get update
"${sudo_cmd[@]}" apt-get install -y --no-install-recommends ca-certificates curl git python3 python3-venv xz-utils

export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh
fi
uv_bin="$(command -v uv || true)"
[[ -n "$uv_bin" ]] || die 'uv installation did not produce an executable'

if [[ -e "$install_dir" && ! -d "$install_dir/.git" ]]; then
  die "install directory exists but is not an AiDN checkout: $install_dir"
fi
if [[ -d "$install_dir/.git" ]]; then
  git -C "$install_dir" diff --quiet || die "refusing to overwrite local changes in $install_dir"
  git -C "$install_dir" diff --cached --quiet || die "refusing to overwrite staged changes in $install_dir"
  git -C "$install_dir" fetch --depth 1 origin "$ref"
else
  mkdir -p "$(dirname "$install_dir")"
  git clone --depth 1 "$REPOSITORY_URL" "$install_dir"
  git -C "$install_dir" fetch --depth 1 origin "$ref"
fi
git -C "$install_dir" checkout --detach FETCH_HEAD
commit="$(git -C "$install_dir" rev-parse HEAD)"
"$uv_bin" --directory "$install_dir" sync --all-extras --frozen

# Install the reviewed Provider runtime dispatcher and its root-owned broker.
# The Hypervisor talks to the broker over a UID-restricted Unix socket; it
# never receives sudo, shell, or generic subprocess capability itself.
runtime_broker_root='/usr/libexec/aidn-provider-runtime'
runtime_dispatcher="$runtime_broker_root/aidn-provider-runtime-ubuntu.sh"
runtime_broker_script="$runtime_broker_root/aidn-provider-runtime-broker.py"
runtime_broker_service='aidn-provider-runtime-broker.service'
operator_uid="$(id -u "$USER")"
operator_gid="$(id -g "$USER")"
runtime_broker_socket="@aidn-provider-runtime-$operator_uid"
"${sudo_cmd[@]}" install -d -o root -g root -m 0755 "$runtime_broker_root"
for runtime_file in \
  aidn-provider-runtime-ubuntu.sh \
  aidn-whisper-runtime-ubuntu.sh \
  aidn-ollama-runtime-ubuntu.sh \
  aidn-llamacpp-runtime-ubuntu.sh \
  aidn-vllm-runtime-ubuntu.sh \
  aidn-consensus-runtime-ubuntu.sh \
  install-cometbft-ubuntu.sh \
  aidn-provider-runtime-broker.py; do
  [[ -f "$install_dir/tools/$runtime_file" ]] || die "runtime broker file is missing: $install_dir/tools/$runtime_file"
  "${sudo_cmd[@]}" install -o root -g root -m 0755 \
    "$install_dir/tools/$runtime_file" "$runtime_broker_root/$runtime_file"
done
runtime_unit_tmp="$(mktemp)"
cat > "$runtime_unit_tmp" <<EOF
[Unit]
Description=AiDN root-owned Provider runtime broker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 $runtime_broker_script --socket $runtime_broker_socket --dispatcher $runtime_dispatcher --allowed-uid $operator_uid --allowed-gid $operator_gid --operator-home $HOME --operator-name $USER
Restart=always
RestartSec=2
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF
"${sudo_cmd[@]}" install -o root -g root -m 0644 "$runtime_unit_tmp" "/etc/systemd/system/$runtime_broker_service"
rm -f "$runtime_unit_tmp"
if [[ "$no_start" != 'true' ]]; then
  "${sudo_cmd[@]}" systemctl daemon-reload
  "${sudo_cmd[@]}" systemctl enable --now "$runtime_broker_service"
fi

node_root="$(bash "$install_dir/tools/install-node-runtime-ubuntu.sh" \
  --output-dir "$data_dir/tooling/node")"
bash "$install_dir/tools/build-operator-dashboard.sh" \
  --project-root "$install_dir" --node-root "$node_root" \
  --tooling-dir "$data_dir/tooling" >/dev/null

mkdir -p "$data_dir"
chmod 700 "$data_dir"
operator_kit="$data_dir/operator-kit"
if [[ ! -f "$operator_kit/README.md" ]]; then
  "$uv_bin" --directory "$install_dir" run python tools/prepare-independent-operator-kit.py init \
    --output "$operator_kit" --peer-id "$peer_id" \
    --network-id "$network_id" --chain-id "$chain_id" \
    --network-revision "$network_revision"
fi

identity_root="$data_dir/operator-identity"
identity_result="$("$uv_bin" --directory "$install_dir" run python tools/prepare-operator-identity.py init \
  --root "$identity_root" --operator-id "$operator_id" --peer-id "$peer_id" \
  --control-group-id "$control_group_id" --host "$advertise_host" \
  --network-id "$network_id" --chain-id "$chain_id" \
  --network-revision "$network_revision")"
python_bin="$install_dir/.venv/bin/python"
[[ -x "$python_bin" ]] || die "prepared venv is missing: $python_bin"
resource_capacity_path="$data_dir/resource-capacity.json"
"$python_bin" -m aidn_hypervisor.resource_probe \
  --output "$resource_capacity_path" \
  --source operator-bootstrap >/dev/null
chmod 600 "$resource_capacity_path"

consensus_service_name=''
consensus_home=''
consensus_binary_path=''
consensus_rpc_host='127.0.0.1'
consensus_rpc_port='26657'
consensus_rpc_endpoint=''
consensus_transport='disabled'
consensus_abci_host='127.0.0.1'
consensus_abci_port='26658'
if [[ "$consensus_mode" == 'validator' ]]; then
  consensus_transport='local'
  consensus_service_name="aidn-cometbft-$operator_id.service"
  consensus_home="$data_dir/consensus/cometbft"
  consensus_binary_path="$data_dir/consensus/bin/cometbft"
  [[ -x "$install_dir/tools/install-cometbft-ubuntu.sh" || -f "$install_dir/tools/install-cometbft-ubuntu.sh" ]] || {
    die "CometBFT installer is missing from checkout: $install_dir/tools/install-cometbft-ubuntu.sh"
  }
  consensus_abci_args=()
  if [[ "$consensus_mode" == 'non_validator' ]]; then
    consensus_abci_args=(--no-abci)
  fi
  bash "$install_dir/tools/install-cometbft-ubuntu.sh" \
    --version "$cometbft_version" \
    --home "$consensus_home" \
    --binary-path "$consensus_binary_path" \
    --service-name "$consensus_service_name" \
    --chain-id "$chain_id" \
    --moniker "$operator_id" \
    --rpc-host "$consensus_rpc_host" \
    --rpc-port "$consensus_rpc_port" \
    --p2p-host '127.0.0.1' \
    --p2p-port '26656' \
    --abci-host "$consensus_abci_host" \
    --abci-port "$consensus_abci_port" \
    "${consensus_abci_args[@]}" \
    --no-start >/dev/null
elif [[ "$consensus_mode" == 'non_validator' ]]; then
  consensus_transport='external_rpc'
  consensus_rpc_endpoint="$consensus_rpc"
fi
operator_public_key="$($python_bin - "$identity_root/operator-identity.json" <<'PY'
import json
import sys

print(json.loads(open(sys.argv[1], encoding="utf-8").read())["operator_public_key"])
PY
)"

registry_root="$data_dir/registry-replication"
registry_config="$registry_root/registry-replication.json"
if [[ ! -f "$registry_config" ]]; then
  "$uv_bin" --directory "$install_dir" run python tools/prepare-registry-replication-identity.py init \
    --root "$registry_root" --peer-id "$peer_id" --host "$advertise_host" \
    --listen-host "$registry_listen_host" --port "$registry_port" \
    --network-id "$network_id" --chain-id "$chain_id" \
    --network-revision "$network_revision"
else
  existing_peer="$($python_bin - "$registry_config" <<'PY'
import json
import sys

print(json.loads(open(sys.argv[1], encoding="utf-8").read())["local_peer_id"])
PY
)"
  [[ "$existing_peer" == "$peer_id" ]] || die "existing Registry identity belongs to peer '$existing_peer', not '$peer_id'"
  "$uv_bin" --directory "$install_dir" run python tools/prepare-registry-replication-identity.py update-listener \
    --root "$registry_root" --listen-host "$registry_listen_host" --port "$registry_port"
fi

mkdir -p "$data_dir/logs" "$HOME/.config/systemd/user"
chmod 700 "$data_dir/logs" "$HOME/.config/systemd" "$HOME/.config/systemd/user"
bind_host_path="$data_dir/hypervisor-bind-host"
printf '%s\n' "$api_host" > "$bind_host_path"
chmod 600 "$bind_host_path"
wrapper="$data_dir/run-hypervisor.sh"
repo_q="$(shell_quote "$install_dir")"
data_q="$(shell_quote "$data_dir")"
registry_q="$(shell_quote "$registry_config")"
python_q="$(shell_quote "$python_bin")"
bind_host_q="$(shell_quote "$bind_host_path")"
api_host_q="$(shell_quote "$api_host")"
api_port_q="$(shell_quote "$api_port")"
cat > "$wrapper" <<EOF
#!/usr/bin/env bash
set -euo pipefail
repo=$repo_q
data=$data_q
registry_config=$registry_q
python_bin=$python_q
bind_host_path=$bind_host_q
api_host=$api_host_q
if [[ -f "\$bind_host_path" ]]; then
  configured_host="\$(tr -d '\r\n' < "\$bind_host_path")"
  case "\$configured_host" in
    127.0.0.1|0.0.0.0) api_host="\$configured_host" ;;
  esac
fi
export AIDN_HYPERVISOR_STATE_PATH="\$data/hypervisor-state.json"
export AIDN_HYPERVISOR_BUNDLES_PATH="\$data/bundles.json"
export AIDN_HYPERVISOR_MODEL_STORE_PATH="\$data/models"
export AIDN_HYPERVISOR_API_HOST="\$api_host"
export AIDN_HYPERVISOR_API_PORT=$api_port_q
export AIDN_HYPERVISOR_BIND_HOST_PATH="\$bind_host_path"
export AIDN_HYPERVISOR_RESTART_ON_BIND_CHANGE=true
# The supported bootstrap uses browser pairing over the selected local or
# trusted-LAN HTTP boundary. Provider runtimes remain loopback-only.
export AIDN_DASHBOARD_ACCESS_ALLOW_INSECURE_LAN=true
export AIDN_NODE_ID=$(shell_quote "$operator_id")
export AIDN_OPERATOR_ID=$(shell_quote "$operator_id")
export AIDN_RESOURCE_PROBE_MODE=auto
export AIDN_RESOURCE_CAPACITY_PATH="\$data/resource-capacity.json"
export AIDN_SECRET_MANAGER_PATH="\$data/registry-replication/secrets.json"
export AIDN_SECRET_MANAGER_MASTER_KEY="\$(tr -d '\r\n' < "\$data/registry-replication/master-key.b64")"
export AIDN_MCP_REMOTE_ENABLED=true
export AIDN_ENABLE_PROVIDER_RUNTIME_INSTALL=true
export AIDN_PROVIDER_RUNTIME_DISPATCHER=/usr/libexec/aidn-provider-runtime/aidn-provider-runtime-ubuntu.sh
export AIDN_PROVIDER_RUNTIME_BROKER_SOCKET=$runtime_broker_socket
export PYTHONUNBUFFERED=1
EOF
if [[ "$consensus_mode" == 'validator' ]]; then
  cat >> "$wrapper" <<EOF
export AIDN_CONSENSUS_MODE=$(shell_quote "$consensus_mode")
export AIDN_CONSENSUS_NODE_ID=$(shell_quote "$operator_id")
export AIDN_COMETBFT_ENDPOINT=$(shell_quote "tcp://$consensus_rpc_host:$consensus_rpc_port")
export AIDN_COMETBFT_CHAIN_ID=$(shell_quote "$chain_id")
export AIDN_COMETBFT_SERVICE=$(shell_quote "$consensus_service_name")
export AIDN_COMETBFT_ABCI_STATE_PATH="\$data/consensus/abci-state"
export AIDN_COMETBFT_ABCI_HOST=$(shell_quote "$consensus_abci_host")
export AIDN_COMETBFT_ABCI_PORT=$(shell_quote "$consensus_abci_port")
EOF
elif [[ "$consensus_mode" == 'non_validator' ]]; then
  cat >> "$wrapper" <<EOF
export AIDN_CONSENSUS_MODE=non_validator
export AIDN_CONSENSUS_NODE_ID=$(shell_quote "$operator_id")
export AIDN_COMETBFT_ENDPOINT=$(shell_quote "$consensus_rpc_endpoint")
export AIDN_COMETBFT_CHAIN_ID=$(shell_quote "$chain_id")
export AIDN_COMETBFT_SERVICE=''
export AIDN_COMETBFT_ABCI_STATE_PATH=''
EOF
else
  cat >> "$wrapper" <<'EOF'
export AIDN_CONSENSUS_MODE=disabled
EOF
fi
if [[ "$enable_registry" == 'true' ]]; then
  cat >> "$wrapper" <<'EOF'
export AIDN_REGISTRY_REPLICATION_CONFIG="$registry_config"
EOF
fi
cat >> "$wrapper" <<EOF
exec "\$python_bin" -m uvicorn aidn_hypervisor.main:build_app --factory --host "\$api_host" --port $api_port_q
EOF
chmod 700 "$wrapper"

operator_cli_wrapper="$data_dir/aidn-operator-wrapper.sh"
dashboard_url="http://$advertise_host:$api_port/operators/dashboard/react#settings"
operator_api_host="$api_host"
if [[ "$operator_api_host" == '0.0.0.0' || "$operator_api_host" == '::' ]]; then
  operator_api_host='127.0.0.1'
fi
operator_api_url_host="$operator_api_host"
if [[ "$operator_api_url_host" == *:* && "$operator_api_url_host" != \[*\] ]]; then
  operator_api_url_host="[$operator_api_url_host]"
fi
operator_api_url="http://$operator_api_url_host:$api_port"
cat > "$operator_cli_wrapper" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export AIDN_HYPERVISOR_STATE_PATH=$(shell_quote "$data_dir/hypervisor-state.json")
export AIDN_HYPERVISOR_BUNDLES_PATH=$(shell_quote "$data_dir/bundles.json")
export AIDN_NODE_ID=$(shell_quote "$operator_id")
export AIDN_OPERATOR_ID=$(shell_quote "$operator_id")
export AIDN_MCP_REMOTE_ENABLED=true
if [[ -z "\${AIDN_SECRET_MANAGER_MASTER_KEY:-}" ]]; then
  export AIDN_SECRET_MANAGER_MASTER_KEY="\$(tr -d '\r\n' < $(shell_quote "$registry_root/master-key.b64"))"
fi
common_args=(
  --secret-manager-path $(shell_quote "$registry_root/secrets.json")
  --master-key-file $(shell_quote "$registry_root/master-key.b64")
  --state-path $(shell_quote "$data_dir/hypervisor-state.json")
  --bundles-path $(shell_quote "$data_dir/bundles.json")
  --api-url $(shell_quote "$operator_api_url")
)
if [[ "\${1:-}" == 'pair' ]]; then
  exec "$python_bin" -m aidn_hypervisor.operator_cli "\$@" "\${common_args[@]}" \\
    --dashboard-url $(shell_quote "$dashboard_url")
fi
exec "$python_bin" -m aidn_hypervisor.operator_cli "\$@" "\${common_args[@]}"
EOF
chmod 700 "$operator_cli_wrapper"
mkdir -p "$HOME/.local/bin"
ln -sfn "$operator_cli_wrapper" "$HOME/.local/bin/aidn-operator"

service_name="aidn-hypervisor-$operator_id.service"
unit_path="$HOME/.config/systemd/user/$service_name"
wrapper_q="$(shell_quote "$wrapper")"
consensus_unit_dependency=''
if [[ "$consensus_mode" == 'validator' ]]; then
  consensus_unit_dependency="Wants=$consensus_service_name"
fi
cat > "$unit_path" <<EOF
[Unit]
Description=AiDN Hypervisor operator $operator_id
After=network-online.target
Wants=network-online.target
$consensus_unit_dependency

[Service]
Type=simple
ExecStart=$wrapper_q
Restart=always
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$data_q
WorkingDirectory=$repo_q

[Install]
WantedBy=default.target
EOF
chmod 600 "$unit_path"
if [[ "$consensus_mode" == 'validator' ]]; then
  consensus_dropin_dir="$HOME/.config/systemd/user/$consensus_service_name.d"
  mkdir -p "$consensus_dropin_dir"
  cat > "$consensus_dropin_dir/10-aidn-hypervisor.conf" <<EOF
[Unit]
After=$service_name
Wants=$service_name
EOF
  chmod 600 "$consensus_dropin_dir/10-aidn-hypervisor.conf"
fi

if command -v loginctl >/dev/null 2>&1 && [[ "$EUID" -ne 0 ]]; then
  "${sudo_cmd[@]}" loginctl enable-linger "$USER"
fi

if [[ "$no_start" != 'true' ]]; then
  uid="$(id -u)"
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$uid}"
  systemctl --user daemon-reload
  systemctl --user enable --now "$service_name"
  health_host="$api_host"
  if [[ "$health_host" == '0.0.0.0' || "$health_host" == '::' ]]; then
    health_host='127.0.0.1'
  fi
  for _ in $(seq 1 30); do
    if curl --fail --silent "http://$health_host:$api_port/health" >/dev/null; then
      break
    fi
    sleep 1
  done
  curl --fail --silent "http://$health_host:$api_port/health" >/dev/null || {
    systemctl --user --no-pager --full status "$service_name" >&2 || true
    die "Hypervisor did not become healthy; inspect journalctl --user -u $service_name"
  }
  if [[ "$consensus_mode" == 'validator' ]]; then
    systemctl --user enable --now "$consensus_service_name"
    for _ in $(seq 1 30); do
      if curl --fail --silent "http://$consensus_rpc_host:$consensus_rpc_port/status" >/dev/null; then
        break
      fi
      sleep 1
    done
    curl --fail --silent "http://$consensus_rpc_host:$consensus_rpc_port/status" >/dev/null || {
      systemctl --user --no-pager --full status "$consensus_service_name" >&2 || true
      die "CometBFT RPC did not become healthy; inspect journalctl --user -u $consensus_service_name"
    }
  fi
fi

wallet_bootstrap_status='deferred_no_start'
wallet_bootstrap_id=''
wallet_bootstrap_public_key=''
dashboard_pairing_status='skipped'
agent_onboarding_status='skipped'
if [[ "$no_start" == 'true' ]]; then
  echo 'Onboarding is deferred because --no-start was supplied.' >&2
  echo "  After starting $service_name, run: aidn-operator wallet create|import" >&2
  echo '  Then run: aidn-operator pair' >&2
else
  case "$wallet_action" in
    create)
      "$HOME/.local/bin/aidn-operator" wallet create --label 'Owner Wallet'
      ;;
    import)
      "$HOME/.local/bin/aidn-operator" wallet import --label 'Owner Wallet'
      ;;
    skip)
      echo 'Owner wallet bootstrap skipped by operator choice.' >&2
      ;;
  esac
  wallet_status_json=''
  if wallet_status_json="$("$HOME/.local/bin/aidn-operator" wallet status)"; then
    wallet_bootstrap_status="$($python_bin - "$wallet_status_json" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
print("configured" if payload.get("configured") else "not_configured")
PY
)"
    wallet_bootstrap_id="$($python_bin - "$wallet_status_json" <<'PY'
import json
import sys

print(json.loads(sys.argv[1]).get("wallet_id") or "")
PY
)"
    wallet_bootstrap_public_key="$($python_bin - "$wallet_status_json" <<'PY'
import json
import sys

print(json.loads(sys.argv[1]).get("public_key") or "")
PY
)"
  else
    wallet_bootstrap_status='status_unavailable'
  fi

  if [[ "$dashboard_pairing_action" == 'create' ]]; then
    "$HOME/.local/bin/aidn-operator" pair
    dashboard_pairing_status='created_once'
  else
    dashboard_pairing_status='skipped_by_operator'
  fi

  if [[ "$agent_action" == 'guide' ]]; then
    agent_onboarding_status='guided_existing_enrollment_boundary'
    echo >&2
    echo 'Agent onboarding remains an explicit enrollment/approval decision:' >&2
    echo "  MCP endpoint: $operator_api_url/mcp" >&2
    echo '  1. Start the agent with its own X25519 key and submit an enrollment request.' >&2
    echo '  2. Review its label and key fingerprint in Dashboard -> Settings -> Agent enrollment requests.' >&2
    echo '  3. Approve only the expected request; the agent retrieves its sealed credential once.' >&2
    echo '  Terminal helpers: aidn-operator enrollment list | aidn-operator enrollment approve --request-id <id>' >&2
  else
    agent_onboarding_status='skipped_by_operator'
  fi
fi

state_path="$data_dir/bootstrap-state.json"
registry_state='disabled_until_mutual_peer_approval'
if [[ "$enable_registry" == 'true' ]]; then
  registry_state='listener_enabled_waiting_for_mutual_peer_approval'
fi
"$python_bin" - "$state_path" "$operator_id" "$peer_id" "$control_group_id" "$commit" \
  "$api_host" "$api_port" "$registry_state" "$service_name" "$identity_root" \
  "$registry_root" "$operator_public_key" "$ref" "$consensus_mode" \
  "$consensus_service_name" "$consensus_home" "$consensus_binary_path" \
  "$consensus_rpc_host" "$consensus_rpc_port" "$consensus_rpc_endpoint" "$consensus_transport" "$resource_capacity_path" \
  "$wallet_action" "$wallet_bootstrap_status" "$wallet_bootstrap_id" \
  "$wallet_bootstrap_public_key" "$dashboard_pairing_status" "$agent_onboarding_status" <<'PY'
import json
import os
import sys

(
    path,
    operator_id,
    peer_id,
    control_group_id,
    commit,
    api_host,
    api_port,
    registry_state,
    service_name,
    identity_root,
    registry_root,
    operator_public_key,
    ref,
    consensus_mode,
    consensus_service_name,
    consensus_home,
    consensus_binary_path,
    consensus_rpc_host,
    consensus_rpc_port,
    consensus_rpc_endpoint,
    consensus_transport,
    resource_capacity_path,
    wallet_action,
    wallet_bootstrap_status,
    wallet_bootstrap_id,
    wallet_bootstrap_public_key,
    dashboard_pairing_status,
    agent_onboarding_status,
) = sys.argv[1:]
payload = {
    "status": "ok",
    "operator_id": operator_id,
    "peer_id": peer_id,
    "control_group_id": control_group_id,
    "commit": commit,
    "ref": ref,
    "api": f"http://{api_host}:{api_port}",
    "service": service_name,
    "operator_identity": os.path.join(identity_root, "operator-identity.json"),
    "operator_public_identity": os.path.join(identity_root, "operator-public-identity.json"),
    "operator_public_key": operator_public_key,
    "registry_root": registry_root,
    "registry_public_bundle": os.path.join(registry_root, "public-peer.json"),
    "replication": registry_state,
    "consensus": {
        "mode": consensus_mode,
        "transport": consensus_transport,
        "service": consensus_service_name or None,
        "home": consensus_home or None,
        "binary": consensus_binary_path or None,
        "rpc": consensus_rpc_endpoint or (f"http://{consensus_rpc_host}:{consensus_rpc_port}" if consensus_service_name else None),
        "automatic_install": consensus_mode == "validator",
    },
    "resource_probe": {
        "mode": "auto",
        "capacity_report": resource_capacity_path,
        "automatic_install": True,
    },
    "onboarding": {
        "wallet_action": wallet_action,
        "wallet_status": wallet_bootstrap_status,
        "wallet_id": wallet_bootstrap_id or None,
        "wallet_public_key": wallet_bootstrap_public_key or None,
        "dashboard_pairing": dashboard_pairing_status,
        "agent": agent_onboarding_status,
        "private_material": "not_in_state_file",
    },
}
os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
with open(path, "w", encoding="utf-8") as stream:
    json.dump(payload, stream, indent=2, sort_keys=True)
    stream.write("\n")
os.chmod(path, 0o600)
print(json.dumps(payload, sort_keys=True))
PY

echo >&2
echo "AiDN operator installed: $operator_id" >&2
echo "  checkout: $install_dir" >&2
echo "  state:    $data_dir" >&2
echo "  service:  $service_name" >&2
echo "  API:      http://$api_host:$api_port" >&2
if is_loopback_host "$api_host"; then
  echo '  Dashboard network: loopback only' >&2
else
  echo "  Dashboard network: LAN bind ($api_host)" >&2
fi
echo "  Capacity: $resource_capacity_path (automatic host probe)" >&2
echo "  Registry: $registry_state" >&2
if [[ "$consensus_mode" == 'validator' ]]; then
  echo "  CometBFT: local validator $consensus_service_name ($consensus_rpc_host:$consensus_rpc_port)" >&2
elif [[ "$consensus_mode" == 'non_validator' ]]; then
  echo "  CometBFT: external RPC observer ($consensus_rpc_endpoint)" >&2
else
  echo '  CometBFT: disabled (--no-consensus)' >&2
fi
echo "  public peer bundle: $registry_root/public-peer.json" >&2
echo "  public operator identity: $identity_root/operator-public-identity.json" >&2
echo "  wallet onboarding: $wallet_bootstrap_status${wallet_bootstrap_id:+ ($wallet_bootstrap_id)}" >&2
echo "  dashboard pairing: $dashboard_pairing_status" >&2
echo "  agent onboarding: $agent_onboarding_status" >&2
echo "  operator CLI: $HOME/.local/bin/aidn-operator" >&2
echo >&2
echo 'The sudo password was used only by sudo and was not captured by this script.' >&2
echo 'Do not copy master-key.b64, secrets.json, or operator-attestation-key.raw.' >&2
