#!/usr/bin/env bash
# Install and manage the fixed CometBFT process used by an AiDN Hypervisor.
# Existing genesis state is validated, never silently replaced.
set -euo pipefail

readonly DEFAULT_VERSION='v0.38.19'

usage() {
  cat <<'EOF'
Usage:
  install-cometbft-ubuntu.sh [options]

Options:
  --version VERSION       CometBFT release tag (default: v0.38.19)
  --home DIR              CometBFT home (required)
  --binary-path PATH      Installed binary path (required)
  --service-name NAME     user-systemd unit name (required)
  --chain-id ID            Chain ID for a new local genesis (required)
  --moniker NAME          CometBFT moniker (required)
  --rpc-host HOST         RPC listen host (default: 127.0.0.1)
  --rpc-port PORT         RPC listen port (default: 26657)
  --p2p-host HOST         P2P listen host (default: 127.0.0.1)
  --p2p-port PORT         P2P listen port (default: 26656)
  --abci-host HOST        AiDN ABCI host (default: 127.0.0.1)
  --abci-port PORT        AiDN ABCI port (default: 26658)
  --no-abci               Do not configure a local AiDN ABCI proxy
  --no-start              Install and configure, but do not start the unit
  -h, --help              Show this help

The installer targets Ubuntu 24.04+ and user-systemd operation. It builds the
pinned CometBFT release through Go modules.
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
  [[ "$1" == /* && "$1" != *[[:space:]]* ]]
}

version="$DEFAULT_VERSION"
home=''
binary_path=''
service_name=''
chain_id=''
moniker=''
rpc_host='127.0.0.1'
rpc_port='26657'
p2p_host='127.0.0.1'
p2p_port='26656'
abci_host='127.0.0.1'
abci_port='26658'
no_start='false'
use_abci='true'
started='false'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) require_value "$1" "$@"; version="$2"; shift 2 ;;
    --home) require_value "$1" "$@"; home="$2"; shift 2 ;;
    --binary-path) require_value "$1" "$@"; binary_path="$2"; shift 2 ;;
    --service-name) require_value "$1" "$@"; service_name="$2"; shift 2 ;;
    --chain-id) require_value "$1" "$@"; chain_id="$2"; shift 2 ;;
    --moniker) require_value "$1" "$@"; moniker="$2"; shift 2 ;;
    --rpc-host) require_value "$1" "$@"; rpc_host="$2"; shift 2 ;;
    --rpc-port) require_value "$1" "$@"; rpc_port="$2"; shift 2 ;;
    --p2p-host) require_value "$1" "$@"; p2p_host="$2"; shift 2 ;;
    --p2p-port) require_value "$1" "$@"; p2p_port="$2"; shift 2 ;;
    --abci-host) require_value "$1" "$@"; abci_host="$2"; shift 2 ;;
    --abci-port) require_value "$1" "$@"; abci_port="$2"; shift 2 ;;
    --no-abci) use_abci='false'; shift ;;
    --no-start) no_start='true'; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -r /etc/os-release ]] || die 'Ubuntu 24.04 or later is required'
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == 'ubuntu' ]] || die "this installer supports Ubuntu only; detected ${ID:-unknown}"
[[ -n "$home" ]] && valid_path "$home" || die '--home must be an absolute path without spaces'
[[ -n "$binary_path" ]] && valid_path "$binary_path" || die '--binary-path must be an absolute path without spaces'
[[ -n "$service_name" ]] && valid_identifier "${service_name%.service}" || die '--service-name contains unsupported characters'
[[ -n "$chain_id" ]] && valid_identifier "$chain_id" || die '--chain-id contains unsupported characters'
[[ -n "$moniker" ]] && valid_identifier "$moniker" || die '--moniker contains unsupported characters'
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die '--version must look like v0.38.19'
for port in "$rpc_port" "$p2p_port" "$abci_port"; do
  valid_port "$port" || die "invalid port: $port"
done
[[ -n "$rpc_host" && "$rpc_host" != *[[:space:]]* ]] || die 'RPC host is invalid'
[[ -n "$p2p_host" && "$p2p_host" != *[[:space:]]* ]] || die 'P2P host is invalid'
[[ -n "$abci_host" && "$abci_host" != *[[:space:]]* ]] || die 'ABCI host is invalid'

if [[ "$EUID" -eq 0 ]]; then
  sudo_cmd=()
else
  sudo_cmd=(sudo)
  "${sudo_cmd[@]}" -v
fi

"${sudo_cmd[@]}" apt-get update
"${sudo_cmd[@]}" apt-get install -y --no-install-recommends ca-certificates curl golang-go python3

gopath="$(go env GOPATH)"
gobin="$(go env GOBIN)"
if [[ -z "$gobin" ]]; then
  gobin="$gopath/bin"
fi
mkdir -p "$gobin" "$(dirname "$binary_path")"
version_marker="$binary_path.version"
if [[ ! -x "$binary_path" || ! -f "$version_marker" || "$(cat "$version_marker" 2>/dev/null || true)" != "$version" ]]; then
  echo "Building CometBFT $version" >&2
  GOBIN="$gobin" go install "github.com/cometbft/cometbft/cmd/cometbft@$version"
  [[ -x "$gobin/cometbft" ]] || die "Go install did not produce $gobin/cometbft"
  install -m 0755 "$gobin/cometbft" "$binary_path"
  printf '%s\n' "$version" > "$version_marker"
  chmod 600 "$version_marker"
fi
[[ -x "$binary_path" ]] || die "CometBFT binary is missing: $binary_path"

mkdir -p "$home"
chmod 700 "$home"
genesis_path="$home/config/genesis.json"
if [[ ! -f "$genesis_path" ]]; then
  "$binary_path" init --home "$home" >/dev/null
  python3 - "$genesis_path" "$chain_id" <<'PY'
import json
import os
import sys

path, chain_id = sys.argv[1:]
with open(path, encoding="utf-8") as stream:
    payload = json.load(stream)
payload["chain_id"] = chain_id
payload.setdefault("app_state", {})
with open(path, "w", encoding="utf-8") as stream:
    json.dump(payload, stream, indent=2, sort_keys=True)
    stream.write("\n")
os.chmod(path, 0o600)
PY
else
  python3 - "$genesis_path" "$chain_id" <<'PY'
import json
import sys

path, expected_chain_id = sys.argv[1:]
with open(path, encoding="utf-8") as stream:
    payload = json.load(stream)
actual_chain_id = payload.get("chain_id")
if actual_chain_id != expected_chain_id:
    raise SystemExit(
        f"existing CometBFT genesis uses chain_id {actual_chain_id!r}, "
        f"not {expected_chain_id!r}; refusing to rewrite it"
    )
PY
fi

config_path="$home/config/config.toml"
[[ -f "$config_path" ]] || die "CometBFT config is missing: $config_path"
python3 - "$config_path" "$rpc_host" "$rpc_port" "$p2p_host" "$p2p_port" "$abci_host" "$abci_port" "$use_abci" "$moniker" <<'PY'
import sys

path, rpc_host, rpc_port, p2p_host, p2p_port, abci_host, abci_port, use_abci, moniker = sys.argv[1:]
rpc_laddr = f"tcp://{rpc_host}:{rpc_port}"
p2p_laddr = f"tcp://{p2p_host}:{p2p_port}"
proxy_app = f"tcp://{abci_host}:{abci_port}" if use_abci == "true" else "nil"
with open(path, encoding="utf-8") as stream:
    lines = stream.readlines()
section = ""
seen = {"proxy_app": False, "rpc_laddr": False, "p2p_laddr": False, "moniker": False}
result = []
for line in lines:
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        section = stripped[1:-1]
    if section == "" and stripped.startswith("proxy_app ="):
        line = f'proxy_app = "{proxy_app}"\n'
        seen["proxy_app"] = True
    elif section == "" and stripped.startswith("moniker ="):
        line = f'moniker = "{moniker}"\n'
        seen["moniker"] = True
    elif section == "rpc" and stripped.startswith("laddr ="):
        line = f'laddr = "{rpc_laddr}"\n'
        seen["rpc_laddr"] = True
    elif section == "p2p" and stripped.startswith("laddr ="):
        line = f'laddr = "{p2p_laddr}"\n'
        seen["p2p_laddr"] = True
    result.append(line)
if not all(seen.values()):
    missing = ", ".join(key for key, value in seen.items() if not value)
    raise SystemExit(f"CometBFT config did not contain expected settings: {missing}")
with open(path, "w", encoding="utf-8") as stream:
    stream.writelines(result)
PY
chmod 600 "$config_path"

uid="$(id -u)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$uid}"
systemd_dir="$HOME/.config/systemd/user"
mkdir -p "$systemd_dir"
unit_path="$systemd_dir/$service_name"
cat > "$unit_path" <<EOF
[Unit]
Description=CometBFT consensus for AiDN operator $moniker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$binary_path start --home $home
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$home
WorkingDirectory=$home

[Install]
WantedBy=default.target
EOF
chmod 600 "$unit_path"

if [[ "$no_start" != 'true' ]]; then
  systemctl --user daemon-reload
  systemctl --user enable --now "$service_name"
  for _ in $(seq 1 30); do
    if curl --fail --silent "http://$rpc_host:$rpc_port/status" >/dev/null; then
      break
    fi
    sleep 1
  done
  curl --fail --silent "http://$rpc_host:$rpc_port/status" >/dev/null || {
    systemctl --user --no-pager --full status "$service_name" >&2 || true
    die "CometBFT RPC did not become healthy; inspect journalctl --user -u $service_name"
  }
  started='true'
fi

python3 - "$version" "$home" "$binary_path" "$service_name" "$chain_id" "$rpc_host" "$rpc_port" "$p2p_host" "$p2p_port" "$abci_host" "$abci_port" "$use_abci" "$started" <<'PY'
import json
import sys

(
    version,
    home,
    binary_path,
    service_name,
    chain_id,
    rpc_host,
    rpc_port,
    p2p_host,
    p2p_port,
    abci_host,
    abci_port,
    use_abci,
    started,
) = sys.argv[1:]
print(json.dumps({
    "status": "ok",
    "version": version,
    "home": home,
    "binary": binary_path,
    "service": service_name,
    "chain_id": chain_id,
    "rpc": f"http://{rpc_host}:{rpc_port}",
    "p2p": f"tcp://{p2p_host}:{p2p_port}",
    "abci": f"tcp://{abci_host}:{abci_port}" if use_abci == "true" else None,
    "started": started == "true",
}, sort_keys=True))
PY
