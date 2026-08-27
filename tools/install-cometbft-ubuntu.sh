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
  --genesis-file PATH      Verified Genesis JSON to install for an existing network
  --moniker NAME          CometBFT moniker (required)
  --rpc-host HOST         RPC listen host (default: 127.0.0.1)
  --rpc-port PORT         RPC listen port (default: 26657)
  --p2p-host HOST         P2P listen host (default: 127.0.0.1)
  --p2p-port PORT         P2P listen port (default: 26656)
  --external-address ADDR Advertised P2P host:port (optional)
  --seeds LIST             Comma-separated seed peers (optional)
  --persistent-peers LIST  Comma-separated persistent peers (optional)
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
genesis_file=''
moniker=''
rpc_host='127.0.0.1'
rpc_port='26657'
p2p_host='127.0.0.1'
p2p_port='26656'
external_address=''
seeds=''
persistent_peers=''
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
    --genesis-file) require_value "$1" "$@"; genesis_file="$2"; shift 2 ;;
    --moniker) require_value "$1" "$@"; moniker="$2"; shift 2 ;;
    --rpc-host) require_value "$1" "$@"; rpc_host="$2"; shift 2 ;;
    --rpc-port) require_value "$1" "$@"; rpc_port="$2"; shift 2 ;;
    --p2p-host) require_value "$1" "$@"; p2p_host="$2"; shift 2 ;;
    --p2p-port) require_value "$1" "$@"; p2p_port="$2"; shift 2 ;;
    --external-address) require_value "$1" "$@"; external_address="$2"; shift 2 ;;
    --seeds) require_value "$1" "$@"; seeds="$2"; shift 2 ;;
    --persistent-peers) require_value "$1" "$@"; persistent_peers="$2"; shift 2 ;;
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
if [[ -n "$genesis_file" ]]; then
  [[ "$genesis_file" == /* && -f "$genesis_file" && ! -L "$genesis_file" ]] || die '--genesis-file must be a readable regular absolute file'
fi
[[ -n "$moniker" ]] && valid_identifier "$moniker" || die '--moniker contains unsupported characters'
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die '--version must look like v0.38.19'
for port in "$rpc_port" "$p2p_port" "$abci_port"; do
  valid_port "$port" || die "invalid port: $port"
done
[[ -n "$rpc_host" && "$rpc_host" != *[[:space:]]* ]] || die 'RPC host is invalid'
[[ -n "$p2p_host" && "$p2p_host" != *[[:space:]]* ]] || die 'P2P host is invalid'
[[ -n "$abci_host" && "$abci_host" != *[[:space:]]* ]] || die 'ABCI host is invalid'

python3 - "$external_address" "$seeds" "$persistent_peers" <<'PY'
import re
import sys

external_address, seeds, persistent_peers = sys.argv[1:]
host = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")
ipv6 = re.compile(r"^[0-9A-Fa-f:]{2,45}$")
identifier = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


def endpoint(value: str, label: str) -> None:
    if not value:
        return
    if any(character.isspace() for character in value):
        raise SystemExit(f"{label} must be a host:port endpoint")
    if value.startswith("["):
        closing = value.find("]")
        if closing < 2 or closing + 1 >= len(value) or value[closing + 1] != ":":
            raise SystemExit(f"{label} must be a host:port endpoint")
        target, port_text = value[1:closing], value[closing + 2 :]
        valid_host = bool(ipv6.fullmatch(target))
    else:
        target, separator, port_text = value.rpartition(":")
        valid_host = bool(separator and host.fullmatch(target))
    if not valid_host or not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
        raise SystemExit(f"{label} must be a host:port endpoint")


def peer_list(value: str, label: str) -> None:
    entries = [item.strip() for item in re.split(r"[,\n\r]+", value) if item.strip()]
    if len(entries) > 32:
        raise SystemExit(f"{label} may contain at most 32 peers")
    for entry in entries:
        peer_endpoint = entry.rsplit("@", 1)[-1]
        if "@" in entry and not identifier.fullmatch(entry.rsplit("@", 1)[0]):
            raise SystemExit(f"{label} contains an invalid peer ID")
        endpoint(peer_endpoint, label)


endpoint(external_address, "external address")
peer_list(seeds, "seeds")
peer_list(persistent_peers, "persistent peers")
PY

if [[ "$EUID" -eq 0 ]]; then
  sudo_cmd=()
else
  sudo_cmd=(sudo)
  "${sudo_cmd[@]}" -v
fi

# The root-owned runtime broker preserves the operator identity in these
# variables. Package installation remains privileged, while user-systemd
# commands and unit files are always addressed to that operator's session.
operator_uid="${AIDN_PROVIDER_RUNTIME_OPERATOR_UID:-$(id -u)}"
operator_gid="${AIDN_PROVIDER_RUNTIME_OPERATOR_GID:-$(id -g)}"
operator_name="${AIDN_PROVIDER_RUNTIME_OPERATOR_NAME:-${USER:-$(id -un)}}"
operator_home="${AIDN_PROVIDER_RUNTIME_OPERATOR_HOME:-$HOME}"

user_systemctl() {
  if [[ "$EUID" -eq 0 && "$operator_uid" =~ ^[0-9]+$ && "$operator_uid" != '0' ]]; then
    runtime_dir="/run/user/$operator_uid"
    runuser -u "$operator_name" -- env \
      HOME="$operator_home" USER="$operator_name" LOGNAME="$operator_name" \
      XDG_RUNTIME_DIR="$runtime_dir" \
      DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime_dir/bus" \
      /usr/bin/systemctl --user "$@"
  else
    systemctl --user "$@"
  fi
}

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
consensus_root="$(dirname "$home")"
genesis_path="$home/config/genesis.json"
if [[ ! -f "$genesis_path" ]]; then
  "$binary_path" init --home "$home" >/dev/null
  if [[ -n "$genesis_file" ]]; then
    install -m 0600 "$genesis_file" "$genesis_path"
  else
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
  fi
else
  if [[ -n "$genesis_file" ]] && ! cmp --silent "$genesis_file" "$genesis_path"; then
    die 'existing CometBFT genesis differs from --genesis-file; refusing to replace it'
  fi
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

# CometBFT reads this file before it opens the RPC or P2P listeners.  A
# reconnect can intentionally keep the validated genesis/config while replacing
# the whole data directory, so do not rely on `cometbft init` having created it.
# Recreate the canonical empty state only for the non-ABCI (non-validator)
# profile.  For an ABCI validator, fail closed instead of silently replacing
# signing history and risking a double-sign.
state_path="$home/data/priv_validator_state.json"
if [[ ! -f "$state_path" ]]; then
  if [[ "$use_abci" != 'false' ]]; then
    die "validator CometBFT data is missing $state_path; refusing to recreate signing state"
  fi
  mkdir -p "$home/data"
  printf '%s\n' '{"height":"0","round":-1,"step":0}' >"$state_path"
  chmod 600 "$state_path"
fi

config_path="$home/config/config.toml"
[[ -f "$config_path" ]] || die "CometBFT config is missing: $config_path"
python3 - "$config_path" "$rpc_host" "$rpc_port" "$p2p_host" "$p2p_port" "$external_address" "$seeds" "$persistent_peers" "$abci_host" "$abci_port" "$use_abci" "$moniker" <<'PY'
import sys

(
    path,
    rpc_host,
    rpc_port,
    p2p_host,
    p2p_port,
    external_address,
    seeds,
    persistent_peers,
    abci_host,
    abci_port,
    use_abci,
    moniker,
) = sys.argv[1:]
rpc_laddr = f"tcp://{rpc_host}:{rpc_port}"
p2p_laddr = f"tcp://{p2p_host}:{p2p_port}"
proxy_app = f"tcp://{abci_host}:{abci_port}" if use_abci == "true" else "noop"
with open(path, encoding="utf-8") as stream:
    lines = stream.readlines()
section = ""
seen = {
    "proxy_app": False,
    "rpc_laddr": False,
    "p2p_laddr": False,
    "external_address": False,
    "seeds": False,
    "persistent_peers": False,
    "pex": False,
    "moniker": False,
}
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
    elif section == "p2p" and stripped.startswith("external_address ="):
        line = f'external_address = "{external_address}"\n'
        seen["external_address"] = True
    elif section == "p2p" and stripped.startswith("seeds ="):
        line = f'seeds = "{seeds}"\n'
        seen["seeds"] = True
    elif section == "p2p" and stripped.startswith("persistent_peers ="):
        line = f'persistent_peers = "{persistent_peers}"\n'
        seen["persistent_peers"] = True
    elif section == "p2p" and stripped.startswith("pex ="):
        line = "pex = true\n"
        seen["pex"] = True
    result.append(line)
if not all(seen.values()):
    missing = ", ".join(key for key, value in seen.items() if not value)
    raise SystemExit(f"CometBFT config did not contain expected settings: {missing}")
with open(path, "w", encoding="utf-8") as stream:
    stream.writelines(result)
PY
chmod 600 "$config_path"
if [[ "$EUID" -eq 0 && "$operator_uid" != '0' ]]; then
  # The broker ran the installer as root, but the user-systemd unit must be
  # be able to read/write its CometBFT home without a privileged helper. The
  # Hypervisor's ABCI state store lives next to that home, so the parent must
  # be operator-owned as well; otherwise the first committed block fails with
  # PermissionError while creating consensus/abci-state.
  chown "$operator_uid:$operator_gid" "$consensus_root"
  chown -R "$operator_uid:$operator_gid" "$home"
fi

uid="$operator_uid"
export HOME="$operator_home"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$uid}"
if [[ "$EUID" -eq 0 && "$uid" != '0' ]]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
fi
systemd_dir="$operator_home/.config/systemd/user"
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
# CometBFT can exit cleanly when its ABCI peer restarts. A clean exit is not
# an operator request to leave consensus offline.
Restart=always
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
if [[ "$EUID" -eq 0 && "$operator_uid" != '0' ]]; then
  chown "$operator_uid:$operator_gid" "$unit_path"
fi

user_systemctl daemon-reload
if [[ "$no_start" != 'true' ]]; then
  user_systemctl enable --now "$service_name"
  for _ in $(seq 1 30); do
    if curl --fail --silent "http://$rpc_host:$rpc_port/status" >/dev/null; then
      break
    fi
    sleep 1
  done
  curl --fail --silent "http://$rpc_host:$rpc_port/status" >/dev/null || {
    user_systemctl --no-pager --full status "$service_name" >&2 || true
    die "CometBFT RPC did not become healthy; inspect journalctl --user -u $service_name"
  }
  started='true'
fi

python3 - "$version" "$home" "$binary_path" "$service_name" "$chain_id" "$rpc_host" "$rpc_port" "$p2p_host" "$p2p_port" "$external_address" "$seeds" "$persistent_peers" "$abci_host" "$abci_port" "$use_abci" "$started" <<'PY'
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
    external_address,
    seeds,
    persistent_peers,
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
    "external_address": external_address,
    "seeds": seeds,
    "persistent_peers": persistent_peers,
    "abci": f"tcp://{abci_host}:{abci_port}" if use_abci == "true" else None,
    "started": started == "true",
}, sort_keys=True))
PY
