#!/usr/bin/env bash
# Install and manage the reviewed loopback-only Ollama runtime for AiDN.
set -euo pipefail

readonly DEFAULT_VERSION="0.32.12"
readonly DEFAULT_PORT="11434"
readonly SERVICE_NAME="ollama.service"
readonly INSTALLER_URL="https://ollama.com/install.sh"

usage() {
  cat <<'EOF'
Usage: aidn-ollama-runtime-ubuntu.sh <install|start|status|stop> [options]

Options:
  --version VERSION  Pinned Ollama version (default: 0.32.12)
  --model MODEL      Optional model to pull after start

The service is forced to 127.0.0.1:11434. Model download is optional and is
kept separate from runtime installation.
EOF
}

die() { echo "error: $*" >&2; exit 1; }

require_ubuntu() {
  [[ -r /etc/os-release ]] || die "Ubuntu 22.04 or later is required"
  # shellcheck disable=SC1091
  source /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || die "this installer supports Ubuntu only; detected ${ID:-unknown}"
}

wait_ready() {
  for _ in $(seq 1 60); do
    if curl --fail --silent --max-time 3 "http://127.0.0.1:$DEFAULT_PORT/api/tags" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

[[ $# -gt 0 ]] || { usage >&2; exit 2; }
if [[ "$1" == "-h" || "$1" == "--help" ]]; then usage; exit 0; fi
action="$1"
shift
version="$DEFAULT_VERSION"
model=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) [[ $# -ge 2 ]] || die "--version requires a value"; version="$2"; shift 2 ;;
    --model) [[ $# -ge 2 ]] || die "--model requires a value"; model="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || die "invalid Ollama version"
[[ "$version" == "$DEFAULT_VERSION" ]] || die "only reviewed Ollama version $DEFAULT_VERSION is supported"
[[ -z "$model" || "$model" =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]*$ ]] || die "invalid Ollama model identifier"
[[ "$model" != *".."* ]] || die "invalid Ollama model identifier"

case "$action" in
  install)
    require_ubuntu
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends ca-certificates curl
    temporary_dir="$(mktemp -d)"
    trap 'rm -rf -- "$temporary_dir"' EXIT
    curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
      "$INSTALLER_URL" -o "$temporary_dir/install-ollama.sh"
    OLLAMA_VERSION="$version" sh "$temporary_dir/install-ollama.sh"
    command -v ollama >/dev/null 2>&1 || die "Ollama installer did not produce an executable"
    sudo install -d -m 0755 /etc/systemd/system/ollama.service.d
    printf '[Service]\nEnvironment="OLLAMA_HOST=127.0.0.1:%s"\n' "$DEFAULT_PORT" \
      | sudo tee /etc/systemd/system/ollama.service.d/aidn-loopback.conf >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable --now "$SERVICE_NAME"
    wait_ready || {
      sudo systemctl --no-pager --full status "$SERVICE_NAME" >&2 || true
      die "Ollama did not become ready on loopback"
    }
    printf '{"status":"ready","provider":"ollama","version":"%s","endpoint":"http://127.0.0.1:%s"}\n' \
      "$version" "$DEFAULT_PORT"
    ;;
  start)
    command -v ollama >/dev/null 2>&1 || die "Ollama is not installed"
    sudo systemctl enable --now "$SERVICE_NAME"
    wait_ready || die "Ollama did not become ready on loopback"
    if [[ -n "$model" ]]; then
      ollama pull "$model"
    fi
    printf '{"status":"ready","provider":"ollama","model":"%s","endpoint":"http://127.0.0.1:%s"}\n' \
      "$model" "$DEFAULT_PORT"
    ;;
  status)
    if ! command -v ollama >/dev/null 2>&1; then
      echo '{"provider":"ollama","state":"absent"}'
      exit 3
    fi
    if ! sudo systemctl is-active --quiet "$SERVICE_NAME"; then
      echo '{"provider":"ollama","state":"installed_stopped"}'
      exit 3
    fi
    if curl --fail --silent --max-time 3 "http://127.0.0.1:$DEFAULT_PORT/api/tags" >/dev/null; then
      printf '{"provider":"ollama","state":"ready","endpoint":"http://127.0.0.1:%s"}\n' "$DEFAULT_PORT"
    else
      echo '{"provider":"ollama","state":"starting_or_unavailable"}'
      exit 3
    fi
    ;;
  stop)
    sudo systemctl stop "$SERVICE_NAME"
    echo '{"provider":"ollama","status":"stopped"}'
    ;;
  *) usage >&2; exit 2 ;;
esac
