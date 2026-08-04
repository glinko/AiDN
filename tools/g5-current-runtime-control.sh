#!/usr/bin/env bash
# Control the current controlled-testnet deployment without embedded credentials.
# The operator must provision key-based SSH and narrowly scoped sudoers rules.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: g5-current-runtime-control.sh {status|graceful|abrupt|reboot|recover}

Environment:
  AIDN_G5_TARGET_SSH       SSH target for the validator host
  AIDN_G5_SSH_KEY          operator SSH private key path
  AIDN_G5_ABCI_CONTAINER   ABCI container name (default: aidn-g5-abci)
  AIDN_G5_COMET_BIN        CometBFT binary path on the target host
  AIDN_G5_COMET_HOME       CometBFT home path on the target host
EOF
}

action="${1:-}"
case "$action" in
  status|graceful|abrupt|reboot|recover) ;;
  *) usage >&2; exit 2 ;;
esac

target="${AIDN_G5_TARGET_SSH:-user@192.168.88.127}"
key="${AIDN_G5_SSH_KEY:-$HOME/.ssh/aidn-g5-operator_ed25519}"
container="${AIDN_G5_ABCI_CONTAINER:-aidn-g5-abci}"
comet_bin="${AIDN_G5_COMET_BIN:-/home/user/aidn-g5-clean/cometbft}"
comet_home="${AIDN_G5_COMET_HOME:-/home/user/aidn-g5-clean/node}"

[[ -r "$key" ]] || { echo "SSH key is not readable: $key" >&2; exit 2; }
[[ "$container" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "invalid ABCI container name" >&2; exit 2; }
[[ "$comet_bin" =~ ^/[A-Za-z0-9_./-]+$ ]] || { echo "invalid CometBFT binary path" >&2; exit 2; }
[[ "$comet_home" =~ ^/[A-Za-z0-9_./-]+$ ]] || { echo "invalid CometBFT home path" >&2; exit 2; }

ssh_options=(
  -i "$key"
  -o BatchMode=yes
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o ConnectTimeout=5
)

remote() {
  ssh "${ssh_options[@]}" "$target" "$@"
}

remote_script() {
  # Send a fixed script over stdin so remote paths are never re-parsed as shell code.
  ssh "${ssh_options[@]}" "$target" bash -s -- "$@"
}

wait_for_ssh() {
  local attempt
  for attempt in $(seq 1 120); do
    if remote true >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

stop_comet() {
  remote_script "$comet_bin" "$comet_home" <<'REMOTE'
set -euo pipefail
comet_bin="$1"
comet_home="$2"
if pgrep -x cometbft >/dev/null 2>&1; then
  pkill -TERM -x cometbft
  for _ in $(seq 1 30); do
    pgrep -x cometbft >/dev/null 2>&1 || exit 0
    sleep 1
  done
  echo "CometBFT did not stop cleanly: $comet_bin --home $comet_home" >&2
  exit 1
fi
REMOTE
}

start_comet_if_needed() {
  remote_script "$comet_bin" "$comet_home" <<'REMOTE'
set -euo pipefail
comet_bin="$1"
comet_home="$2"
[[ -x "$comet_bin" ]] || { echo "CometBFT binary is not executable: $comet_bin" >&2; exit 1; }
[[ -d "$comet_home" ]] || { echo "CometBFT home is missing: $comet_home" >&2; exit 1; }
if ! pgrep -x cometbft >/dev/null 2>&1; then
  nohup "$comet_bin" start --home "$comet_home" >/tmp/aidn-g5-comet.log 2>&1 </dev/null &
fi
for _ in $(seq 1 30); do
  pgrep -x cometbft >/dev/null 2>&1 && exit 0
  sleep 1
done
echo "CometBFT did not start; inspect /tmp/aidn-g5-comet.log" >&2
exit 1
REMOTE
}

stop_abruptly() {
  remote_script "$container" <<'REMOTE'
set -euo pipefail
container="$1"
pkill -KILL -x cometbft >/dev/null 2>&1 || true
sudo -n /usr/bin/docker kill "$container" >/dev/null
sleep 5
REMOTE
}

start_container() {
  remote_script "$container" <<'REMOTE'
set -euo pipefail
container="$1"
# An already-running container is acceptable; a missing container is not.
if ! sudo -n /usr/bin/docker start "$container" >/dev/null 2>&1; then
  sudo -n /usr/bin/docker inspect "$container" >/dev/null 2>&1 || {
    echo "ABCI container is missing: $container" >&2
    exit 1
  }
fi
REMOTE
}

case "$action" in
  status)
    remote_script "$container" <<'REMOTE'
set -euo pipefail
container="$1"
sudo -n /usr/bin/docker inspect "$container" >/dev/null
pgrep -x cometbft >/dev/null
curl -fsS --max-time 3 http://127.0.0.1:26657/status >/dev/null
printf '%s\n' 'current-runtime-ready'
REMOTE
    ;;
  graceful)
    stop_comet
    remote sudo -n /usr/bin/docker restart "$container"
    start_comet_if_needed
    ;;
  abrupt)
    stop_abruptly
    start_container
    start_comet_if_needed
    ;;
  reboot)
    remote_script "$container" <<'REMOTE'
set -euo pipefail
container="$1"
pkill -TERM -x cometbft >/dev/null 2>&1 || true
sudo -n /usr/bin/docker stop "$container" >/dev/null 2>&1 || true
exec sudo -n /usr/sbin/reboot
REMOTE
    ;;
  recover)
    wait_for_ssh || { echo 'validator host did not return over SSH' >&2; exit 1; }
    start_container
    start_comet_if_needed
    for attempt in $(seq 1 90); do
      if remote curl -fsS --max-time 3 http://127.0.0.1:26657/status >/dev/null; then
        printf '%s\n' 'current-runtime-recovered'
        exit 0
      fi
      sleep 2
    done
    echo 'validator RPC did not recover' >&2
    exit 1
    ;;
esac
