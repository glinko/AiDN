#!/usr/bin/env bash
# Test-only mTLS/Ed25519 Registry replication acceptance across two SSH hosts.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run-cross-host-registry-smoke.sh --remote-ssh USER@HOST --remote-repo PATH [options]

Options:
  --remote-port PORT  Disposable remote loopback port (default: 29443)
  --local-port PORT   Local SSH-forwarded port (default: 29443)
  --timeout SECONDS   Client acceptance timeout (default: 20)
  -h, --help          Show this help

This is a controlled test harness. It creates disposable keys and an object on
the remote host, transfers only test client material via SCP, and never uses
production Registry, Wallet, TLS, or Hypervisor state.
EOF
}

remote_ssh=''
remote_repo=''
remote_port='29443'
local_port='29443'
timeout='20'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote-ssh) remote_ssh="$2"; shift 2 ;;
    --remote-repo) remote_repo="$2"; shift 2 ;;
    --remote-port) remote_port="$2"; shift 2 ;;
    --local-port) local_port="$2"; shift 2 ;;
    --timeout) timeout="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$remote_ssh" && -n "$remote_repo" ]] || {
  echo '--remote-ssh and --remote-repo are required' >&2; exit 2;
}
for value in remote_port local_port timeout; do
  [[ "${!value}" =~ ^[0-9]+$ ]] || { echo "--${value//_/-} must be numeric" >&2; exit 2; }
done
(( remote_port >= 1 && remote_port <= 65535 && local_port >= 1 && local_port <= 65535 )) || {
  echo 'ports must be between 1 and 65535' >&2; exit 2;
}

local_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
local_uv="$(command -v uv || true)"
if [[ -z "$local_uv" && -x "$HOME/.local/bin/uv" ]]; then local_uv="$HOME/.local/bin/uv"; fi
[[ -n "$local_uv" ]] || { echo 'uv is required locally' >&2; exit 1; }

run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
remote_state="/tmp/aidn-registry-smoke-${run_id}"
local_state="${TMPDIR:-/tmp}/aidn-registry-smoke-${run_id}"
local_bundle="$local_state/client-bootstrap.json"
remote_pid=''
tunnel_pid=''

cleanup() {
  [[ -n "$tunnel_pid" ]] && kill "$tunnel_pid" 2>/dev/null || true
  if [[ -n "$remote_pid" ]]; then
    ssh "$remote_ssh" "kill '$remote_pid' 2>/dev/null || true" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

remote_pid="$(ssh "$remote_ssh" 'bash -s' -- "$remote_repo" "$remote_state" "$remote_port" <<'REMOTE'
set -euo pipefail
repo="$1"
state_dir="$2"
port="$3"
uv_bin="$(command -v uv || true)"
if [[ -z "$uv_bin" && -x "$HOME/.local/bin/uv" ]]; then uv_bin="$HOME/.local/bin/uv"; fi
[[ -n "$uv_bin" ]] || { echo 'uv is required on the remote host' >&2; exit 1; }
[[ -d "$repo/.git" ]] || { echo "remote repository is invalid: $repo" >&2; exit 1; }
mkdir -p "$state_dir"
nohup "$uv_bin" --directory "$repo" run python tools/registry_replication_peer_acceptance.py \
  server --state-dir "$state_dir" --host 127.0.0.1 --port "$port" \
  > "$state_dir/server.log" 2>&1 < /dev/null &
echo $!
REMOTE
)"

mkdir -p "$local_state"
for _ in $(seq 1 30); do
  if scp -q "$remote_ssh:$remote_state/client-bootstrap.json" "$local_bundle" 2>/dev/null; then break; fi
  sleep 1
done
[[ -f "$local_bundle" ]] || {
  echo 'remote test peer did not produce a bootstrap bundle; inspect remote server.log' >&2; exit 1;
}

ssh -o ExitOnForwardFailure=yes -N \
  -L "127.0.0.1:${local_port}:127.0.0.1:${remote_port}" "$remote_ssh" &
tunnel_pid=$!
sleep 1
kill -0 "$tunnel_pid" 2>/dev/null || { echo 'SSH tunnel did not start' >&2; exit 1; }

"$local_uv" --directory "$local_repo" run python tools/registry_replication_peer_acceptance.py \
  client --state-dir "$local_state/client" --bundle "$local_bundle" \
  --host 127.0.0.1 --port "$local_port" --timeout "$timeout"

printf '{"status":"ok","remote_ssh":"%s","remote_test_state":"%s","warning":"test-only disposable identities; no independent ownership claim"}\n' \
  "$remote_ssh" "$remote_state"
