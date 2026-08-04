#!/usr/bin/env bash
# Prepare and run an isolated validator replacement without touching old state.
# The script never resets, deletes, or edits the source CometBFT home.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: provision-validator-replacement.sh {prepare|start|stop|abrupt|status}

Environment:
  AIDN_REPROVISION_ROOT       replacement root (default: $HOME/aidn-g5-reprovision)
  AIDN_REPROVISION_REPO       AiDN checkout (default: $HOME/aidn/AiDN)
  AIDN_SOURCE_COMET_HOME      old CometBFT home (default: $HOME/aidn-g5-clean/node)
  AIDN_COMET_BIN               CometBFT binary (default: $HOME/aidn-g5-clean/cometbft)
  AIDN_REPROVISION_REF         source ref recorded in the manifest (default: current)
  AIDN_TRUST_HEIGHT             trusted block height for State Sync
  AIDN_TRUST_HASH               trusted block hash for State Sync
  AIDN_RPC_SERVERS              comma-separated trusted RPC URLs
  AIDN_PERSISTENT_PEERS         replacement peer list without the replacement itself
  AIDN_ABCI_PORT                replacement ABCI port (default: 27658)
  AIDN_RPC_PORT                 replacement RPC port (default: 27657)
  AIDN_P2P_PORT                 replacement P2P port (default: 27656)
EOF
}

action="${1:-}"
case "$action" in
  prepare|start|stop|abrupt|status) ;;
  *) usage >&2; exit 2 ;;
esac

root="${AIDN_REPROVISION_ROOT:-$HOME/aidn-g5-reprovision}"
repo="${AIDN_REPROVISION_REPO:-$HOME/aidn/AiDN}"
source_home="${AIDN_SOURCE_COMET_HOME:-$HOME/aidn-g5-clean/node}"
comet_bin="${AIDN_COMET_BIN:-$HOME/aidn-g5-clean/cometbft}"
ref="${AIDN_REPROVISION_REF:-current}"
abci_port="${AIDN_ABCI_PORT:-27658}"
rpc_port="${AIDN_RPC_PORT:-27657}"
p2p_port="${AIDN_P2P_PORT:-27656}"
trust_height="${AIDN_TRUST_HEIGHT:-}"
trust_hash="${AIDN_TRUST_HASH:-}"
rpc_servers="${AIDN_RPC_SERVERS:-}"
persistent_peers="${AIDN_PERSISTENT_PEERS:-}"

die() {
  echo "validator replacement: $*" >&2
  exit 1
}

numeric_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && ((1 <= 10#$1 && 10#$1 <= 65535))
}

[[ "$root" != "$source_home" ]] || die "replacement root must differ from source CometBFT home"
[[ -d "$repo" && -f "$repo/pyproject.toml" ]] || die "AiDN checkout is missing: $repo"
[[ -x "$comet_bin" ]] || die "CometBFT binary is not executable: $comet_bin"
for port in "$abci_port" "$rpc_port" "$p2p_port"; do
  numeric_port "$port" || die "invalid port: $port"
done

node_home="$root/node"
config_path="$node_home/config/config.toml"
state_root="$root/state"
abci_pid_file="$root/abci.pid"
comet_pid_file="$root/comet.pid"

pid_matches() {
  local pid="$1"
  local marker="$2"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  [[ -r "/proc/$pid/cmdline" ]] || return 1
  tr '\0' ' ' <"/proc/$pid/cmdline" | grep -F -- "$marker" >/dev/null
}

read_pid() {
  local path="$1"
  [[ -r "$path" ]] || return 1
  tr -d '[:space:]' <"$path"
}

assert_empty_data_dir() {
  [[ ! -e "$node_home/data/blockstore.db" ]] || die "replacement data already contains blockstore: $node_home/data"
  [[ ! -e "$node_home/data/state.db" ]] || die "replacement data already contains state DB: $node_home/data"
  [[ ! -e "$node_home/data/priv_validator_state.json" ]] || die "replacement validator state already exists; use a new root"
}

prepare() {
  [[ -n "$trust_height" && "$trust_height" =~ ^[1-9][0-9]*$ ]] || die "AIDN_TRUST_HEIGHT is required for prepare"
  [[ "$trust_hash" =~ ^[A-Fa-f0-9]{64}$ ]] || die "AIDN_TRUST_HASH must be a 64-hex block hash"
  [[ -n "$rpc_servers" ]] || die "AIDN_RPC_SERVERS is required for prepare"
  [[ -n "$persistent_peers" ]] || die "AIDN_PERSISTENT_PEERS is required for prepare"
  [[ ! -e "$root" ]] || die "replacement root already exists; choose a new root to avoid reusing state"

  local source_config="$source_home/config/config.toml"
  for path in \
    "$source_home/config/genesis.json" \
    "$source_home/config/node_key.json" \
    "$source_home/config/priv_validator_key.json" \
    "$source_config"; do
    [[ -f "$path" ]] || die "required source identity/config file is missing: $path"
  done

  mkdir -p "$node_home/config" "$node_home/data" "$state_root"
  cp -p "$source_home/config/genesis.json" "$node_home/config/genesis.json"
  cp -p "$source_home/config/node_key.json" "$node_home/config/node_key.json"
  cp -p "$source_home/config/priv_validator_key.json" "$node_home/config/priv_validator_key.json"
  cp -p "$source_config" "$config_path"
  assert_empty_data_dir

  CONFIG_PATH="$config_path" \
  AIDN_ABCI_PORT="$abci_port" \
  AIDN_RPC_PORT="$rpc_port" \
  AIDN_P2P_PORT="$p2p_port" \
  AIDN_TRUST_HEIGHT="$trust_height" \
  AIDN_TRUST_HASH="$trust_hash" \
  AIDN_RPC_SERVERS="$rpc_servers" \
  AIDN_PERSISTENT_PEERS="$persistent_peers" \
  python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["CONFIG_PATH"])
lines = path.read_text(encoding="utf-8").splitlines()

def set_key(section: str, key: str, value: str) -> None:
    current = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1]
        if current == section and stripped.startswith(key + " ="):
            lines[index] = f"{key} = {value}"
            return
    raise SystemExit(f"missing expected config key: [{section}] {key}")

set_key("", "proxy_app", f'"tcp://127.0.0.1:{os.environ["AIDN_ABCI_PORT"]}"')
set_key("", "moniker", '"aidn-reprovision"')
set_key("rpc", "laddr", f'"tcp://0.0.0.0:{os.environ["AIDN_RPC_PORT"]}"')
set_key("p2p", "laddr", f'"tcp://0.0.0.0:{os.environ["AIDN_P2P_PORT"]}"')
set_key("p2p", "persistent_peers", f'"{os.environ["AIDN_PERSISTENT_PEERS"]}"')
set_key("statesync", "enable", "true")
set_key("statesync", "rpc_servers", f'"{os.environ["AIDN_RPC_SERVERS"]}"')
set_key("statesync", "trust_height", os.environ["AIDN_TRUST_HEIGHT"])
set_key("statesync", "trust_hash", f'"{os.environ["AIDN_TRUST_HASH"].upper()}"')
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

  # A new validator starts with no signing history. Never copy the old height,
  # signature or signbytes from a failed predecessor.
  printf '%s\n' '{"height":"0","round":-1,"step":0}' >"$node_home/data/priv_validator_state.json"
  chmod 600 "$node_home/data/priv_validator_state.json"

  REPROVISION_ROOT="$root" \
  REPROVISION_REPO="$repo" \
  REPROVISION_REF="$ref" \
  SOURCE_HOME="$source_home" \
  python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["REPROVISION_ROOT"])
node = root / "node"

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

manifest = {
    "schema_version": 1,
    "replacement_root": str(root),
    "repository": os.environ["REPROVISION_REPO"],
    "source_ref": os.environ["REPROVISION_REF"],
    "source_comet_home": os.environ["SOURCE_HOME"],
    "preserved_files": {
        name: sha256(node / "config" / name)
        for name in ("genesis.json", "node_key.json", "priv_validator_key.json")
    },
    "fresh_files": {
        "priv_validator_state.json": sha256(node / "data" / "priv_validator_state.json")
    },
    "state_policy": "new-data-only-no-blockstore-copy",
}
(root / "reprovision-manifest.json").write_text(
    json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
)
PY
  echo "prepared replacement home: $node_home"
  echo "manifest: $root/reprovision-manifest.json"
}

start_process() {
  local pid_file="$1"
  local marker="$2"
  local log_name="$3"
  shift 3
  if [[ -r "$pid_file" ]]; then
    local existing
    existing="$(read_pid "$pid_file" || true)"
    if pid_matches "$existing" "$marker"; then
      echo "already running $log_name pid=$existing"
      return 0
    fi
  fi
  nohup "$@" </dev/null >"$root/$log_name.log" 2>&1 &
  echo "$!" >"$pid_file"
}

wait_for_rpc() {
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 2 "http://127.0.0.1:${rpc_port}/status" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

start() {
  [[ -f "$config_path" ]] || die "replacement is not prepared: run prepare first"
  [[ -x "$repo/.venv/bin/python" ]] || die "checkout venv is missing: $repo/.venv/bin/python"
  start_process "$abci_pid_file" "$repo/.venv/bin/python" "abci" env \
    AIDN_HYPERVISOR_STATE_PATH="$state_root/hypervisor.json" \
    AIDN_CONSENSUS_MODE=validator \
    AIDN_CONSENSUS_STRICT_OPERATION_COVERAGE=true \
    AIDN_COMETBFT_ABCI_STATE_PATH="$state_root/abci" \
    AIDN_COMETBFT_ABCI_HOST=127.0.0.1 \
    AIDN_COMETBFT_ABCI_PORT="$abci_port" \
    "$repo/.venv/bin/python" -m uvicorn aidn_hypervisor.main:build_app --factory --host 127.0.0.1 --port 8768
  start_process "$comet_pid_file" "$comet_bin" "comet" "$comet_bin" start --home "$node_home"
  wait_for_rpc || die "replacement RPC did not start; inspect $root/comet.log"
  echo "replacement started: http://127.0.0.1:${rpc_port}"
}

stop_pid() {
  local pid_file="$1"
  local marker="$2"
  local pid
  pid="$(read_pid "$pid_file" || true)"
  if pid_matches "$pid" "$marker"; then
    kill -TERM "$pid"
    for _ in $(seq 1 30); do
      pid_matches "$pid" "$marker" || return 0
      sleep 1
    done
    die "process did not stop cleanly: $marker pid=$pid"
  fi
}

abrupt_stop_pid() {
  local pid_file="$1"
  local marker="$2"
  local pid
  pid="$(read_pid "$pid_file" || true)"
  if pid_matches "$pid" "$marker"; then
    kill -KILL "$pid"
    for _ in $(seq 1 10); do
      pid_matches "$pid" "$marker" || return 0
      sleep 1
    done
    die "process did not terminate after SIGKILL: $marker pid=$pid"
  fi
}

abrupt() {
  # Kill only the two processes owned by this replacement root. The caller
  # explicitly starts them again to make the outage and recovery observable.
  abrupt_stop_pid "$comet_pid_file" "$comet_bin"
  abrupt_stop_pid "$abci_pid_file" "$repo/.venv/bin/python"
}

status() {
  printf 'root=%s\n' "$root"
  printf 'abci='; pid_matches "$(read_pid "$abci_pid_file" || true)" "$repo/.venv/bin/python" && echo running || echo stopped
  printf 'comet='; pid_matches "$(read_pid "$comet_pid_file" || true)" "$comet_bin" && echo running || echo stopped
  curl -fsS --max-time 3 "http://127.0.0.1:${rpc_port}/status" || true
}

case "$action" in
  prepare) prepare ;;
  start) start ;;
  stop) stop_pid "$comet_pid_file" "$comet_bin"; stop_pid "$abci_pid_file" "$repo/.venv/bin/python" ;;
  abrupt) abrupt ;;
  status) status ;;
esac
