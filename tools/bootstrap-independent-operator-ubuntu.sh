#!/usr/bin/env bash
# Install and start a loopback-only AiDN Hypervisor on a fresh Ubuntu host.
# It never creates or exchanges production identities, enables replication, or
# exposes an Internet-facing API. Complete peer approval separately.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bootstrap-independent-operator-ubuntu.sh --peer-id ID [options]

Options:
  --ref REF          Git ref to clone (default: main; prefer a reviewed tag or SHA)
  --install-dir DIR  Checkout location (default: $HOME/aidn/AiDN)
  --data-dir DIR     Local state and operator kit location (default: $HOME/.local/share/aidn)
  --port PORT        Loopback API port (default: 8766)
  --no-start         Install and prepare only; do not start the loopback API
  -h, --help         Show this help

The command requires sudo only to install Ubuntu packages. It never asks for,
stores, or sends Wallet keys, Registry signing keys, or TLS private keys.
EOF
}

peer_id=''
ref='main'
install_dir="${HOME}/aidn/AiDN"
data_dir="${HOME}/.local/share/aidn"
port='8766'
start_local='true'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --peer-id) peer_id="$2"; shift 2 ;;
    --ref) ref="$2"; shift 2 ;;
    --install-dir) install_dir="$2"; shift 2 ;;
    --data-dir) data_dir="$2"; shift 2 ;;
    --port) port="$2"; shift 2 ;;
    --no-start) start_local='false'; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$peer_id" ]] || { echo '--peer-id is required' >&2; exit 2; }
[[ "$peer_id" =~ ^[A-Za-z0-9._-]+$ ]] || { echo '--peer-id contains unsupported characters' >&2; exit 2; }
[[ "$port" =~ ^[0-9]+$ ]] && (( port >= 1 && port <= 65535 )) || {
  echo '--port must be between 1 and 65535' >&2; exit 2;
}

if [[ ! -r /etc/os-release ]]; then
  echo 'Ubuntu 24.04 or later is required' >&2; exit 1
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != 'ubuntu' ]]; then
  echo "this bootstrap supports Ubuntu only; detected ${ID:-unknown}" >&2; exit 1
fi

sudo apt-get update
sudo apt-get install -y --no-install-recommends ca-certificates curl git python3 python3-venv

if ! command -v uv >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh
fi
uv_bin="$(command -v uv || true)"
if [[ -z "$uv_bin" && -x "$HOME/.local/bin/uv" ]]; then uv_bin="$HOME/.local/bin/uv"; fi
[[ -n "$uv_bin" ]] || { echo 'uv installation did not produce an executable' >&2; exit 1; }

if [[ -e "$install_dir" && ! -d "$install_dir/.git" ]]; then
  echo "install directory exists but is not an AiDN checkout: $install_dir" >&2; exit 1
fi
if [[ ! -d "$install_dir/.git" ]]; then
  git clone --depth 1 https://github.com/glinko/AiDN.git "$install_dir"
  git -C "$install_dir" fetch --depth 1 origin "$ref"
  git -C "$install_dir" checkout --detach FETCH_HEAD
else
  git -C "$install_dir" fetch --depth 1 origin "$ref"
  git -C "$install_dir" checkout --detach FETCH_HEAD
fi

commit="$(git -C "$install_dir" rev-parse HEAD)"
"$uv_bin" --directory "$install_dir" sync --all-extras --frozen
"$uv_bin" --directory "$install_dir" run python tools/prepare-independent-operator-kit.py init \
  --output "$data_dir/operator-kit" --peer-id "$peer_id" --force

mkdir -p "$data_dir/logs"
cat > "$data_dir/bootstrap-state.json" <<EOF
{"peer_id":"$peer_id","commit":"$commit","api":"http://127.0.0.1:$port","replication":"disabled_until_mutual_peer_approval"}
EOF
chmod 600 "$data_dir/bootstrap-state.json"

if [[ "$start_local" == 'true' ]]; then
  if [[ -f "$data_dir/hypervisor.pid" ]] && kill -0 "$(cat "$data_dir/hypervisor.pid")" 2>/dev/null; then
    echo "AiDN Hypervisor is already running with PID $(cat "$data_dir/hypervisor.pid")" >&2
    exit 1
  fi
  nohup env \
    AIDN_HYPERVISOR_STATE_PATH="$data_dir/hypervisor-state.json" \
    AIDN_HYPERVISOR_BUNDLES_PATH="$data_dir/bundles.json" \
    "$uv_bin" --directory "$install_dir" run uvicorn aidn_hypervisor.main:build_app --factory \
      --host 127.0.0.1 --port "$port" \
      > "$data_dir/logs/hypervisor.log" 2>&1 &
  echo $! > "$data_dir/hypervisor.pid"
  for _ in $(seq 1 20); do
    if curl --fail --silent "http://127.0.0.1:$port/health" >/dev/null; then break; fi
    sleep 1
  done
  curl --fail --silent "http://127.0.0.1:$port/health" >/dev/null || {
    echo "Hypervisor did not become healthy; inspect $data_dir/logs/hypervisor.log" >&2; exit 1;
  }
fi

printf '{"status":"ok","commit":"%s","operator_workspace":"%s","api":"http://127.0.0.1:%s","replication":"disabled_until_mutual_peer_approval"}\n' \
  "$commit" "$data_dir/operator-kit" "$port"
