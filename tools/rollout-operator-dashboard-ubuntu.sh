#!/usr/bin/env bash
# Rebuild and replace the operator dashboard container without changing its state mount.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  sudo bash tools/rollout-operator-dashboard-ubuntu.sh --repo PATH --commit REF [options]

Options:
  --repo PATH          AiDN checkout used as the Docker build context (required)
  --commit REF         Reviewed Git commit or ref to deploy (required)
  --container NAME     Existing dashboard container (default: aidn-g5-abci)
  --image REPOSITORY   Image repository (default: aidn-hypervisor-lan-testnet-strict)
  --help               Show this help

The script requires root because it recreates a Docker container. It preserves
the existing /state mount and AiDN runtime environment, retains the previous
container as a stopped rollback target, and restores it if any smoke check fails.
EOF
}

repo=''
requested_commit=''
container='aidn-g5-abci'
image_repository='aidn-hypervisor-lan-testnet-strict'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      repo="${2:-}"
      shift 2
      ;;
    --commit)
      requested_commit="${2:-}"
      shift 2
      ;;
    --container)
      container="${2:-}"
      shift 2
      ;;
    --image)
      image_repository="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ "${EUID}" -eq 0 ]] || { echo 'run this script through sudo' >&2; exit 2; }
[[ -n "$repo" && -n "$requested_commit" ]] || { usage >&2; exit 2; }
[[ "$repo" == /* && -d "$repo/.git" ]] || { echo "invalid AiDN checkout: $repo" >&2; exit 2; }
[[ "$container" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "invalid container name: $container" >&2; exit 2; }
[[ "$image_repository" =~ ^[A-Za-z0-9_.:/-]+$ ]] || { echo "invalid image repository: $image_repository" >&2; exit 2; }

operator_user=$(stat --format='%U' "$repo")
id "$operator_user" >/dev/null 2>&1 || { echo "checkout owner does not exist: $operator_user" >&2; exit 2; }

run_as_operator() {
  runuser -u "$operator_user" -- env HOME="$(getent passwd "$operator_user" | cut -d: -f6)" "$@"
}

env_file=$(mktemp /tmp/aidn-dashboard-rollout-env.XXXXXX)
rollback_name=''
swapped=false

cleanup() {
  rm -f "$env_file"
}

rollback() {
  local status=$?
  if [[ "$swapped" == true ]]; then
    docker rm -f "$container" >/dev/null 2>&1 || true
    if [[ -n "$rollback_name" ]] && docker inspect "$rollback_name" >/dev/null 2>&1; then
      docker rename "$rollback_name" "$container" >/dev/null 2>&1 || true
      docker start "$container" >/dev/null 2>&1 || true
    fi
  fi
  exit "$status"
}

trap rollback ERR
trap cleanup EXIT

tracked_changes=$(run_as_operator git -C "$repo" status --porcelain | awk '$1 != "??" {print}')
[[ -z "$tracked_changes" ]] || { echo 'checkout has tracked local changes; refusing rollout' >&2; exit 1; }

run_as_operator git -C "$repo" fetch origin main
resolved_commit=$(run_as_operator git -C "$repo" rev-parse --verify "${requested_commit}^{commit}")
run_as_operator git -C "$repo" checkout --detach "$resolved_commit"
commit_short=$(run_as_operator git -C "$repo" rev-parse --short=12 HEAD)
image="${image_repository}:${commit_short}"

docker inspect "$container" >/dev/null
[[ "$(docker inspect --format '{{.State.Running}}' "$container")" == true ]] || {
  echo "dashboard container is not running: $container" >&2
  exit 1
}
[[ "$(docker inspect --format '{{.HostConfig.NetworkMode}}' "$container")" == host ]] || {
  echo 'refusing to replace a non-host-network dashboard container' >&2
  exit 1
}
[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$container")" == unless-stopped ]] || {
  echo 'refusing to replace a container with an unexpected restart policy' >&2
  exit 1
}

expected_command='["python3","-m","uvicorn","aidn_hypervisor.main:build_app","--factory","--host","0.0.0.0","--port","8000"]'
actual_command=$(docker inspect --format '{{json .Config.Cmd}}' "$container")
[[ "$actual_command" == "$expected_command" ]] || {
  echo 'refusing to replace a container with a custom command' >&2
  exit 1
}

mapfile -t mount_lines < <(
  docker inspect --format '{{range .Mounts}}{{.Destination}}|{{.Source}}|{{.RW}}{{"\n"}}{{end}}' "$container" \
    | sed '/^$/d'
)
[[ "${#mount_lines[@]}" -eq 1 ]] || { echo 'refusing to replace a container with unexpected mounts' >&2; exit 1; }
IFS='|' read -r mount_destination state_source mount_rw <<< "${mount_lines[0]}"
[[ "$mount_destination" == /state && "$mount_rw" == true && -d "$state_source" ]] || {
  echo 'refusing to replace a container without a writable /state mount' >&2
  exit 1
}

docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container" \
  | while IFS= read -r value; do
      case "$value" in
        AIDN_*=*|PYTHONDONTWRITEBYTECODE=*|PYTHONUNBUFFERED=*|LANG=*) printf '%s\n' "$value" ;;
      esac
    done > "$env_file"
chmod 600 "$env_file"

consensus_endpoint=$(sed -n 's/^AIDN_COMETBFT_ENDPOINT=//p' "$env_file" | head -n 1)
if [[ -z "$consensus_endpoint" ]]; then
  consensus_status_url='http://127.0.0.1:26657/status'
elif [[ "$consensus_endpoint" == tcp://* ]]; then
  consensus_status_url="http://${consensus_endpoint#tcp://}/status"
elif [[ "$consensus_endpoint" == http://* || "$consensus_endpoint" == https://* ]]; then
  consensus_status_url="${consensus_endpoint%/}/status"
else
  echo "unsupported AIDN_COMETBFT_ENDPOINT: $consensus_endpoint" >&2
  exit 1
fi

echo "building source_commit=${commit_short} image=${image}"
docker build --pull --file "$repo/tools/lan-testnet.Dockerfile" --tag "$image" "$repo"

rollback_name="${container}-rollback-${commit_short}-$(date -u +%Y%m%dT%H%M%SZ)"
docker stop --time 25 "$container" >/dev/null
docker rename "$container" "$rollback_name"
swapped=true
docker run --detach --name "$container" --network host --restart unless-stopped \
  --env-file "$env_file" --volume "$state_source:/state:rw" "$image" >/dev/null

for _ in $(seq 1 30); do
  if curl --fail --silent --max-time 3 http://127.0.0.1:8000/health >/tmp/aidn-dashboard-health.json 2>/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent --max-time 3 http://127.0.0.1:8000/health >/tmp/aidn-dashboard-health.json
curl --fail --silent --max-time 3 "$consensus_status_url" >/dev/null
curl --fail --silent --max-time 3 http://127.0.0.1:8000/operators/dashboard/react >/tmp/aidn-dashboard-react.html
grep -q 'id="root"' /tmp/aidn-dashboard-react.html
asset_path=$(grep -oE '/operators/dashboard/react/assets/[^" ]+\.js' /tmp/aidn-dashboard-react.html | head -n 1)
[[ -n "$asset_path" ]] || { echo 'React index did not include a JavaScript asset' >&2; exit 1; }
curl --fail --silent --max-time 3 "http://127.0.0.1:8000${asset_path}" >/dev/null

printf 'rollout_status=ok\n'
printf 'source_commit=%s\n' "$commit_short"
printf 'image=%s\n' "$image"
printf 'rollback_container=%s\n' "$rollback_name"
printf 'react_asset=%s\n' "$asset_path"
printf 'consensus_rpc=reachable\n'
