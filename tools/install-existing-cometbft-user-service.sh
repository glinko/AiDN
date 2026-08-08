#!/usr/bin/env bash
# Supervise an already provisioned CometBFT home without rewriting its state.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install-existing-cometbft-user-service.sh \
  --binary /absolute/path/cometbft \
  --home /absolute/path/comet-home \
  --service-name NAME [--rpc-url URL] [--no-start]

The command never edits CometBFT configuration or chain data. It installs a
user-systemd service with restart supervision around an existing runtime.
EOF
}

die() {
  echo "CometBFT supervisor: $*" >&2
  exit 1
}

binary=''
home=''
service_name=''
rpc_url='http://127.0.0.1:26657/status'
no_start='false'

while (($#)); do
  case "$1" in
    --binary) binary="${2:-}"; shift 2 ;;
    --home) home="${2:-}"; shift 2 ;;
    --service-name) service_name="${2:-}"; shift 2 ;;
    --rpc-url) rpc_url="${2:-}"; shift 2 ;;
    --no-start) no_start='true'; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ "$binary" = /* && -x "$binary" ]] || die "binary is not executable: $binary"
[[ "$home" = /* && -d "$home/config" ]] || die "CometBFT home is invalid: $home"
[[ "$binary" != *[[:space:]]* && "$home" != *[[:space:]]* ]] || {
  die "binary and home paths must not contain whitespace"
}
[[ "$service_name" =~ ^[A-Za-z0-9_.@-]+\.service$ ]] || {
  die "service name must end in .service and contain only systemd-safe characters"
}
[[ "$rpc_url" =~ ^https?://[^[:space:]]+$ ]] || die "RPC URL is invalid"

uid="$(id -u)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$uid}"
systemd_dir="$HOME/.config/systemd/user"
unit_path="$systemd_dir/$service_name"
mkdir -p "$systemd_dir"
chmod 700 "$HOME/.config/systemd" "$systemd_dir"

cat >"$unit_path" <<EOF
[Unit]
Description=Supervised CometBFT runtime at $home
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$binary start --home $home
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
systemctl --user daemon-reload
systemctl --user enable "$service_name" >/dev/null

if [[ "$no_start" != 'true' ]]; then
  systemctl --user restart "$service_name"
  for _ in $(seq 1 45); do
    curl -fsS --max-time 2 "$rpc_url" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -fsS --max-time 2 "$rpc_url" >/dev/null || {
    systemctl --user --no-pager --full status "$service_name" >&2 || true
    die "RPC did not become healthy: $rpc_url"
  }
fi

printf '{"status":"ok","service":"%s","home":"%s","rpc":"%s","started":%s}\n' \
  "$service_name" "$home" "$rpc_url" "$([[ "$no_start" == 'true' ]] && echo false || echo true)"
