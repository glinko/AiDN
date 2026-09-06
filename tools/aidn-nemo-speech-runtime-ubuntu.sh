#!/usr/bin/env bash
# Install and manage the pinned NVIDIA NeMo-Speech.cpp HTTP runtime.
#
# The runtime is a self-contained release archive.  This script never accepts
# an arbitrary URL or command: only the reviewed v0.1.0 x86_64 CPU/CUDA
# artifacts and the loopback-only user service are reachable through the
# provider broker.
set -euo pipefail

readonly DEFAULT_VERSION="0.1.0"
readonly DEFAULT_PORT="8090"
readonly DEFAULT_ROOT="${HOME}/.local/share/aidn/providers/nemo-speech"
readonly CUDA_SHA256="e68628f396489c98fb353e070efaea5bc4977409ae7734fce56c251a79e29147"
readonly CPU_SHA256="0f74131d631ad2c694cf0ec53490866bb6461147959589a69fb6fc231944065b"
readonly RELEASE_BASE="https://github.com/NVIDIA/NeMo-Speech.cpp/releases/download/v0.1.0"
readonly SERVICE_NAME="aidn-nemo-speech.service"

usage() {
  cat <<'EOF'
Usage: aidn-nemo-speech-runtime-ubuntu.sh <install|start|status|stop|remove> [options]

Options:
  --version VERSION  Reviewed runtime version (default: 0.1.0)
  --backend MODE      cpu or cuda (default: cuda)
  --root PATH         Operator-owned runtime root
  --model PATH        Absolute Parakeet GGUF path; required for start
  --port PORT         Loopback HTTP port (default: 8090)

Install downloads and verifies only the pinned NeMo-Speech.cpp archive.  The
model is configured separately; start serves one loaded ASR model on loopback.
EOF
}

die() { echo "error: $*" >&2; exit 1; }

require_ubuntu() {
  [[ -r /etc/os-release ]] || die "Ubuntu 22.04 or later is required"
  # shellcheck disable=SC1091
  source /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || die "this installer supports Ubuntu only; detected ${ID:-unknown}"
}

valid_absolute_path() {
  [[ "$1" =~ ^/[A-Za-z0-9._/-]+$ && "$1" != *".."* ]]
}

valid_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && (( 1 <= 10#$1 && 10#$1 <= 65535 ))
}

user_systemctl() {
  if [[ "$EUID" -eq 0 \
    && -n "${AIDN_PROVIDER_RUNTIME_OPERATOR_NAME:-}" \
    && "${AIDN_PROVIDER_RUNTIME_OPERATOR_UID:-}" =~ ^[0-9]+$ ]]; then
    runuser -u "$AIDN_PROVIDER_RUNTIME_OPERATOR_NAME" -- env \
      XDG_RUNTIME_DIR="/run/user/${AIDN_PROVIDER_RUNTIME_OPERATOR_UID}" \
      DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${AIDN_PROVIDER_RUNTIME_OPERATOR_UID}/bus" \
      /usr/bin/systemctl --user "$@"
  else
    systemctl --user "$@"
  fi
}

wait_ready() {
  for _ in $(seq 1 120); do
    if curl --fail --silent --max-time 3 "http://127.0.0.1:$port/ready" | grep -q '"ready"[[:space:]]*:[[:space:]]*true'; then
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
backend="cuda"
root_path="$DEFAULT_ROOT"
model_path=""
port="$DEFAULT_PORT"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) [[ $# -ge 2 ]] || die "--version requires a value"; version="$2"; shift 2 ;;
    --backend) [[ $# -ge 2 ]] || die "--backend requires a value"; backend="$2"; shift 2 ;;
    --root) [[ $# -ge 2 ]] || die "--root requires a value"; root_path="$2"; shift 2 ;;
    --model) [[ $# -ge 2 ]] || die "--model requires a value"; model_path="$2"; shift 2 ;;
    --port) [[ $# -ge 2 ]] || die "--port requires a value"; port="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ "$version" == "$DEFAULT_VERSION" ]] || die "only reviewed NeMo-Speech version $DEFAULT_VERSION is supported"
[[ "$backend" == "cpu" || "$backend" == "cuda" ]] || die "--backend must be cpu or cuda"
valid_absolute_path "$root_path" || die "--root must be an absolute path without whitespace or traversal"
[[ "$root_path" != "/" ]] || die "--root cannot be filesystem root"
valid_port "$port" || die "--port must be between 1 and 65535"
if [[ -n "$model_path" ]]; then
  valid_absolute_path "$model_path" || die "--model must be an absolute path without whitespace or traversal"
fi

archive_name="nemo-speech-${version}-linux-x86_64-${backend}.tar.gz"
archive_url="$RELEASE_BASE/$archive_name"
expected_sha256="$CPU_SHA256"
[[ "$backend" == "cuda" ]] && expected_sha256="$CUDA_SHA256"
archive_path="$root_path/$archive_name"
runtime_dir="$root_path/runtime"
extract_dir="$root_path/$archive_name.extracted"
binary_path="$runtime_dir/bin/nemo-speech"
unit_path="$HOME/.config/systemd/user/$SERVICE_NAME"

case "$action" in
  install)
    require_ubuntu
    command -v curl >/dev/null 2>&1 || die "curl is required"
    command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"
    command -v tar >/dev/null 2>&1 || die "tar is required"
    mkdir -p "$root_path" "$root_path/bin"
    temporary_archive="$archive_path.tmp.$$"
    trap 'rm -f -- "$temporary_archive"' EXIT
    curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
      "$archive_url" -o "$temporary_archive"
    actual_sha256="$(sha256sum "$temporary_archive" | awk '{print $1}')"
    [[ "$actual_sha256" == "$expected_sha256" ]] \
      || die "NeMo-Speech archive checksum mismatch"
    rm -rf -- "$extract_dir" "$runtime_dir"
    mkdir -p "$extract_dir"
    tar -xzf "$temporary_archive" -C "$extract_dir" --strip-components=1
    [[ -x "$extract_dir/bin/nemo-speech" ]] || die "verified archive has no nemo-speech binary"
    mv -- "$extract_dir" "$runtime_dir"
    chmod -R u=rwX,go-rwx "$runtime_dir"
    printf '%s %s %s\n' "$version" "$actual_sha256" "$backend" > "$root_path/runtime-version"
    chmod 600 "$root_path/runtime-version"
    rm -f -- "$temporary_archive"
    trap - EXIT
    printf '{"status":"installed","provider":"nemo-speech","version":"%s","backend":"%s","binary":"%s"}\n' \
      "$version" "$backend" "$binary_path"
    ;;
  start)
    [[ -x "$binary_path" ]] || die "NeMo-Speech runtime is not installed"
    [[ -n "$model_path" ]] || die "--model is required for start"
    [[ -r "$model_path" && -f "$model_path" ]] || die "Parakeet model is not a readable file: $model_path"
    mkdir -p "$(dirname "$unit_path")" "$root_path/state"
    library_path="$runtime_dir/lib"
    cat > "$unit_path" <<EOF
[Unit]
Description=AiDN NeMo-Speech.cpp Provider runtime
After=network-online.target

[Service]
Type=simple
Environment=LD_LIBRARY_PATH=$library_path
ExecStart=$binary_path serve --backend $backend --asr-model $model_path --host 127.0.0.1 --port $port --no-ui
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadOnlyPaths=$model_path $root_path
ReadWritePaths=$root_path/state

[Install]
WantedBy=default.target
EOF
    user_systemctl daemon-reload
    user_systemctl enable --now "$SERVICE_NAME"
    wait_ready || {
      user_systemctl --no-pager --full status "$SERVICE_NAME" >&2 || true
      die "NeMo-Speech did not become ready on loopback"
    }
    printf '{"status":"ready","provider":"nemo-speech","model":"%s","endpoint":"http://127.0.0.1:%s"}\n' \
      "$model_path" "$port"
    ;;
  status)
    if [[ ! -x "$binary_path" ]]; then
      echo '{"provider":"nemo-speech","state":"absent"}'
      exit 3
    fi
    if [[ ! -f "$unit_path" ]]; then
      echo '{"provider":"nemo-speech","state":"installed_unconfigured"}'
      exit 0
    fi
    if ! user_systemctl is-active --quiet "$SERVICE_NAME"; then
      echo '{"provider":"nemo-speech","state":"installed_stopped"}'
      exit 3
    fi
    if curl --fail --silent --max-time 3 "http://127.0.0.1:$port/ready" | grep -q '"ready"[[:space:]]*:[[:space:]]*true'; then
      printf '{"provider":"nemo-speech","state":"ready","endpoint":"http://127.0.0.1:%s"}\n' "$port"
    else
      echo '{"provider":"nemo-speech","state":"starting_or_unavailable"}'
      exit 3
    fi
    ;;
  stop)
    user_systemctl stop "$SERVICE_NAME"
    echo '{"provider":"nemo-speech","status":"stopped"}'
    ;;
  remove)
    user_systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
    rm -f -- "$unit_path"
    user_systemctl daemon-reload
    rm -rf -- "$runtime_dir" "$root_path/runtime-version" "$root_path"/*.tar.gz "$root_path"/*.extracted
    printf '{"status":"removed","provider":"nemo-speech","runtime_root":"%s","model_files":"preserved"}\n' "$root_path"
    ;;
  *) usage >&2; exit 2 ;;
esac
