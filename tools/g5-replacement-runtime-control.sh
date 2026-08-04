#!/usr/bin/env bash
# Proxy explicit controls to an isolated validator replacement over SSH.
# The replacement helper owns PID validation and never receives credentials.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: g5-replacement-runtime-control.sh {status|stop|start|abrupt}

Environment:
  AIDN_G5_REPLACEMENT_TARGET_SSH  SSH target (default: user@192.168.88.127)
  AIDN_G5_REPLACEMENT_SSH_KEY     private key path on this control host
  AIDN_G5_REPLACEMENT_ROOT        replacement root on the target host
  AIDN_G5_REPLACEMENT_REPO        replacement checkout on the target host
  AIDN_G5_REPLACEMENT_SOURCE_HOME source CometBFT home on the target host
  AIDN_G5_REPLACEMENT_COMET_BIN   replacement CometBFT binary on the target host
  AIDN_G5_REPLACEMENT_REF         recorded replacement source ref
  AIDN_G5_REPLACEMENT_ABCI_PORT   replacement ABCI port
  AIDN_G5_REPLACEMENT_RPC_PORT    replacement RPC port
  AIDN_G5_REPLACEMENT_P2P_PORT    replacement P2P port
EOF
}

action="${1:-}"
case "$action" in
  status|stop|start|abrupt) ;;
  *) usage >&2; exit 2 ;;
esac

target="${AIDN_G5_REPLACEMENT_TARGET_SSH:-user@192.168.88.127}"
key="${AIDN_G5_REPLACEMENT_SSH_KEY:-$HOME/.ssh/aidn-g5-operator_ed25519}"
root="${AIDN_G5_REPLACEMENT_ROOT:-$HOME/aidn-g5-reprovision}"
repo="${AIDN_G5_REPLACEMENT_REPO:-$HOME/aidn/AiDN}"
source_home="${AIDN_G5_REPLACEMENT_SOURCE_HOME:-$HOME/aidn-g5-clean/node}"
comet_bin="${AIDN_G5_REPLACEMENT_COMET_BIN:-$HOME/aidn-g5-clean/cometbft}"
ref="${AIDN_G5_REPLACEMENT_REF:-current}"
abci_port="${AIDN_G5_REPLACEMENT_ABCI_PORT:-27658}"
rpc_port="${AIDN_G5_REPLACEMENT_RPC_PORT:-27657}"
p2p_port="${AIDN_G5_REPLACEMENT_P2P_PORT:-27656}"

[[ -r "$key" ]] || { echo "SSH key is not readable: $key" >&2; exit 2; }
[[ "$root" = /* && "$repo" = /* && "$source_home" = /* && "$comet_bin" = /* ]] || {
  echo "replacement paths must be absolute" >&2
  exit 2
}
for port in "$abci_port" "$rpc_port" "$p2p_port"; do
  [[ "$port" =~ ^[0-9]+$ ]] && ((1 <= 10#$port && 10#$port <= 65535)) || {
    echo "invalid replacement port: $port" >&2
    exit 2
  }
done

ssh \
  -i "$key" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=5 \
  "$target" bash -s -- \
  "$action" "$root" "$repo" "$source_home" "$comet_bin" "$ref" \
  "$abci_port" "$rpc_port" "$p2p_port" <<'REMOTE'
set -euo pipefail
action="$1"
root="$2"
repo="$3"
source_home="$4"
comet_bin="$5"
ref="$6"
abci_port="$7"
rpc_port="$8"
p2p_port="$9"

export AIDN_REPROVISION_ROOT="$root"
export AIDN_REPROVISION_REPO="$repo"
export AIDN_SOURCE_COMET_HOME="$source_home"
export AIDN_COMET_BIN="$comet_bin"
export AIDN_REPROVISION_REF="$ref"
export AIDN_ABCI_PORT="$abci_port"
export AIDN_RPC_PORT="$rpc_port"
export AIDN_P2P_PORT="$p2p_port"

[[ -x "$repo/tools/provision-validator-replacement.sh" ]] || {
  echo "replacement helper is missing: $repo/tools/provision-validator-replacement.sh" >&2
  exit 1
}
exec "$repo/tools/provision-validator-replacement.sh" "$action"
REMOTE
