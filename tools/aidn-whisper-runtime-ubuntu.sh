#!/usr/bin/env bash
# Start one bounded, operator-owned Whisper ASR container for an AiDN node.
set -euo pipefail

readonly SERVICE_NAME="aidn-whisper"
readonly DEFAULT_IMAGE="onerahmet/openai-whisper-asr-webservice:v1.9.1"
readonly DEFAULT_MODEL="base"
readonly DEFAULT_PORT="9000"
readonly DEFAULT_DATA_DIR="/var/lib/aidn/whisper"

action="status"
image="$DEFAULT_IMAGE"
model="$DEFAULT_MODEL"
port="$DEFAULT_PORT"
data_dir="$DEFAULT_DATA_DIR"

usage() {
  cat <<'EOF'
Usage: aidn-whisper-runtime-ubuntu.sh <install|start|status|stop> [options]

Installs or starts a reviewed Whisper ASR container bound only to 127.0.0.1.
It never exposes port 9000 on the LAN. Docker must already be installed and
running; Docker installation is a separate node-administration decision.

Options:
  --model MODEL       tiny, base, small, medium, or large-v3 (default: base)
  --port PORT         localhost port; only 9000 is supported in MVP
  --data-dir PATH     persistent model cache (default: /var/lib/aidn/whisper)
  --image IMAGE       exact approved image tag (default: v1.9.1)
EOF
}

die() { echo "error: $*" >&2; exit 1; }

[[ $# -gt 0 ]] || { usage >&2; exit 2; }
if [[ "$1" == "-h" || "$1" == "--help" ]]; then usage; exit 0; fi
action="$1"
shift
case "$action" in install|start|status|stop) ;; *) usage >&2; exit 2 ;; esac

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) model="${2:?missing model}"; shift 2 ;;
    --port) port="${2:?missing port}"; shift 2 ;;
    --data-dir) data_dir="${2:?missing data directory}"; shift 2 ;;
    --image) image="${2:?missing image}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

case "$model" in tiny|base|small|medium|large-v3) ;; *) die "unsupported Whisper model: $model" ;; esac
[[ "$port" == "9000" ]] || die "only localhost port 9000 is supported in MVP"
[[ "$image" == "$DEFAULT_IMAGE" ]] || die "only the reviewed image $DEFAULT_IMAGE is supported in MVP"
[[ "$data_dir" =~ ^/var/lib/aidn/[A-Za-z0-9._/-]+$ && "$data_dir" != *".."* ]] \
  || die "data directory must stay under /var/lib/aidn and use safe path characters"

command -v docker >/dev/null 2>&1 || die "Docker is required; install Docker before enabling managed Whisper"
docker info >/dev/null 2>&1 || die "Docker daemon is unavailable"

case "$action" in
  install)
    docker pull "$image" >/dev/null
    image_digest="$(docker image inspect "$image" --format '{{index .RepoDigests 0}}')"
    [[ -n "$image_digest" && "$image_digest" != '<no value>' ]] || die "could not resolve pulled image digest"
    printf '{"status":"installed","provider":"whisper","image":"%s","model_download":"deferred"}\n' \
      "$image_digest"
    ;;
  status)
    docker inspect "$SERVICE_NAME" --format '{"name":"{{.Name}}","state":"{{.State.Status}}","image":"{{.Config.Image}}"}' 2>/dev/null || {
      echo '{"state":"absent"}'
      exit 3
    }
    curl --fail --silent --max-time 3 "http://127.0.0.1:$port/openapi.json" >/dev/null \
      && echo '{"health":"ready"}' || echo '{"health":"starting_or_unavailable"}'
    ;;
  stop)
    docker stop --time 30 "$SERVICE_NAME" >/dev/null 2>&1 || true
    echo '{"status":"stopped"}'
    ;;
  start)
    install -d -m 0750 "$data_dir/cache"
    docker pull "$image" >/dev/null
    image_digest="$(docker image inspect "$image" --format '{{index .RepoDigests 0}}')"
    [[ -n "$image_digest" && "$image_digest" != '<no value>' ]] || die "could not resolve pulled image digest"
    docker rm --force "$SERVICE_NAME" >/dev/null 2>&1 || true
    docker run --detach --name "$SERVICE_NAME" --restart unless-stopped \
      --publish "127.0.0.1:$port:9000" \
      --volume "$data_dir/cache:/root/.cache:rw" \
      --env "ASR_ENGINE=openai_whisper" \
      --env "ASR_MODEL=$model" \
      --cpus 3 --memory 8g --pids-limit 256 \
      --security-opt no-new-privileges:true --cap-drop ALL \
      "$image" >/dev/null
    for _ in $(seq 1 90); do
      if curl --fail --silent --max-time 3 "http://127.0.0.1:$port/openapi.json" >/dev/null; then
        printf '{"status":"ready","service":"%s","model":"%s","image":"%s","endpoint":"http://127.0.0.1:%s"}\n' \
          "$SERVICE_NAME" "$model" "$image_digest" "$port"
        exit 0
      fi
      sleep 2
    done
    docker logs --tail 80 "$SERVICE_NAME" >&2 || true
    die "Whisper did not become ready within 180 seconds"
    ;;
esac
