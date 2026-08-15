#!/usr/bin/env bash
# Build and manage one loopback-only llama.cpp server for AiDN.
set -euo pipefail

readonly DEFAULT_REF="b10433"
readonly DEFAULT_PORT="8080"
readonly REPOSITORY_URL="https://github.com/ggml-org/llama.cpp.git"
readonly SERVICE_NAME="aidn-llamacpp.service"
readonly CUDA_TOOLKIT_PACKAGE="cuda-toolkit-13-3"

usage() {
  cat <<'EOF'
Usage: aidn-llamacpp-runtime-ubuntu.sh <install|start|status|stop|remove> [options]

Options:
  --ref REF         Pinned llama.cpp release/tag (default: b10433)
  --backend MODE    cpu or cuda (default: cpu; cuda provisions CUDA Toolkit 13.3)
  --root PATH       Operator-owned install root
  --model PATH      Absolute GGUF path; required only for start

Installation builds llama-server but does not download a model. Start writes a
user-systemd unit bound to 127.0.0.1:8080.
EOF
}

die() { echo "error: $*" >&2; exit 1; }

require_ubuntu() {
  [[ -r /etc/os-release ]] || die "Ubuntu 22.04 or later is required"
  # shellcheck disable=SC1091
  source /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || die "this installer supports Ubuntu only; detected ${ID:-unknown}"
}

find_nvcc() {
  if command -v nvcc >/dev/null 2>&1; then
    command -v nvcc
    return 0
  fi
  local candidate
  for candidate in /usr/local/cuda/bin/nvcc /usr/local/cuda-*/bin/nvcc; do
    [[ -x "$candidate" ]] || continue
    printf '%s\n' "$candidate"
    return 0
  done
  return 1
}

ensure_cuda_toolkit() {
  local nvcc_path=""
  nvcc_path="$(find_nvcc || true)"
  if [[ -z "$nvcc_path" ]]; then
    [[ "$(dpkg --print-architecture)" == "amd64" ]] \
      || die "CUDA backend is supported only on amd64 Ubuntu hosts"
    local temporary_dir
    temporary_dir="$(mktemp -d)"
    local distro="${ID}${VERSION_ID//./}"
    local keyring="$temporary_dir/cuda-keyring.deb"
    curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
      "https://developer.download.nvidia.com/compute/cuda/repos/$distro/x86_64/cuda-keyring_1.1-1_all.deb" \
      -o "$keyring"
    sudo dpkg -i "$keyring"
    rm -rf -- "$temporary_dir"
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends "$CUDA_TOOLKIT_PACKAGE"
    nvcc_path="$(find_nvcc || true)"
  fi
  [[ -n "$nvcc_path" ]] || die "CUDA toolkit installation did not provide nvcc"
  export PATH="$(dirname "$nvcc_path"):$PATH"
}

valid_absolute_path() {
  [[ "$1" =~ ^/[A-Za-z0-9._/-]+$ && "$1" != *".."* ]]
}

wait_ready() {
  for _ in $(seq 1 120); do
    if curl --fail --silent --max-time 3 "http://127.0.0.1:$DEFAULT_PORT/health" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

# The production broker executes this script as root on behalf of the
# operator.  A plain `systemctl --user` from root cannot connect to another
# user's user manager; target that manager explicitly while keeping direct
# operator invocations unchanged.
user_systemctl() {
  if [[ "$EUID" -eq 0 && -n "${AIDN_PROVIDER_RUNTIME_OPERATOR_NAME:-}" ]]; then
    systemctl --machine="${AIDN_PROVIDER_RUNTIME_OPERATOR_NAME}@.host" --user "$@"
  else
    systemctl --user "$@"
  fi
}

[[ $# -gt 0 ]] || { usage >&2; exit 2; }
if [[ "$1" == "-h" || "$1" == "--help" ]]; then usage; exit 0; fi
action="$1"
shift
ref="$DEFAULT_REF"
backend="cpu"
root_path="${HOME}/.local/share/aidn/providers/llama.cpp"
model_path=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref) [[ $# -ge 2 ]] || die "--ref requires a value"; ref="$2"; shift 2 ;;
    --backend) [[ $# -ge 2 ]] || die "--backend requires a value"; backend="$2"; shift 2 ;;
    --root) [[ $# -ge 2 ]] || die "--root requires a value"; root_path="$2"; shift 2 ;;
    --model) [[ $# -ge 2 ]] || die "--model requires a value"; model_path="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ "$ref" =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid llama.cpp ref"
[[ "$ref" == "$DEFAULT_REF" ]] || die "only reviewed llama.cpp ref $DEFAULT_REF is supported"
[[ "$backend" == "cpu" || "$backend" == "cuda" ]] || die "--backend must be cpu or cuda"
valid_absolute_path "$root_path" || die "--root must be an absolute path without whitespace"
if [[ -n "$model_path" ]]; then
  valid_absolute_path "$model_path" || die "--model must be an absolute path without whitespace"
fi

source_dir="$root_path/source"
build_dir="$root_path/build-$backend"
binary_path="$root_path/bin/llama-server"
unit_path="$HOME/.config/systemd/user/$SERVICE_NAME"

case "$action" in
  install)
    require_ubuntu
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends build-essential ca-certificates cmake curl git libcurl4-openssl-dev
    if [[ "$backend" == "cuda" ]]; then
      ensure_cuda_toolkit
    fi
    mkdir -p "$root_path" "$root_path/bin"
    if [[ -d "$source_dir/.git" ]]; then
      git -C "$source_dir" diff --quiet || die "existing llama.cpp source checkout has local changes"
      git -C "$source_dir" diff --cached --quiet || die "existing llama.cpp source checkout has staged changes"
    else
      [[ ! -e "$source_dir" ]] || die "source path exists but is not a git checkout: $source_dir"
      git clone --filter=blob:none --no-checkout "$REPOSITORY_URL" "$source_dir"
    fi
    git -C "$source_dir" fetch --depth 1 origin "refs/tags/$ref"
    git -C "$source_dir" checkout --detach FETCH_HEAD
    cmake_args=(-S "$source_dir" -B "$build_dir" -DCMAKE_BUILD_TYPE=Release)
    if [[ "$backend" == "cuda" ]]; then cmake_args+=(-DGGML_CUDA=ON); fi
    cmake "${cmake_args[@]}"
    cmake --build "$build_dir" --config Release --target llama-server -j "$(nproc)"
    install -m 0755 "$build_dir/bin/llama-server" "$binary_path"
    commit="$(git -C "$source_dir" rev-parse HEAD)"
    printf '%s\n' "$ref $commit $backend" > "$root_path/runtime-version"
    chmod 600 "$root_path/runtime-version"
    printf '{"status":"installed","provider":"llama.cpp","ref":"%s","commit":"%s","backend":"%s","binary":"%s"}\n' \
      "$ref" "$commit" "$backend" "$binary_path"
    ;;
  start)
    [[ -x "$binary_path" ]] || die "llama.cpp runtime is not installed"
    [[ -n "$model_path" ]] || die "--model is required for start"
    [[ -r "$model_path" && -f "$model_path" ]] || die "GGUF model is not a readable file: $model_path"
    mkdir -p "$(dirname "$unit_path")" "$root_path/state"
    cat > "$unit_path" <<EOF
[Unit]
Description=AiDN llama.cpp Provider runtime
After=network-online.target

[Service]
Type=simple
ExecStart=$binary_path --model $model_path --host 127.0.0.1 --port $DEFAULT_PORT
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadOnlyPaths=$model_path
ReadWritePaths=$root_path/state

[Install]
WantedBy=default.target
EOF
    user_systemctl daemon-reload
    user_systemctl enable --now "$SERVICE_NAME"
    wait_ready || {
      user_systemctl --no-pager --full status "$SERVICE_NAME" >&2 || true
      die "llama.cpp did not become ready on loopback"
    }
    printf '{"status":"ready","provider":"llama.cpp","model":"%s","endpoint":"http://127.0.0.1:%s"}\n' \
      "$model_path" "$DEFAULT_PORT"
    ;;
  status)
    if [[ ! -x "$binary_path" ]]; then
      echo '{"provider":"llama.cpp","state":"absent"}'
      exit 3
    fi
    if [[ ! -f "$unit_path" ]]; then
      echo '{"provider":"llama.cpp","state":"installed_unconfigured"}'
      exit 0
    fi
    if ! user_systemctl is-active --quiet "$SERVICE_NAME"; then
      echo '{"provider":"llama.cpp","state":"installed_stopped"}'
      exit 3
    fi
    if curl --fail --silent --max-time 3 "http://127.0.0.1:$DEFAULT_PORT/health" >/dev/null; then
      printf '{"provider":"llama.cpp","state":"ready","endpoint":"http://127.0.0.1:%s"}\n' "$DEFAULT_PORT"
    else
      echo '{"provider":"llama.cpp","state":"starting_or_unavailable"}'
      exit 3
    fi
    ;;
  stop)
    user_systemctl stop "$SERVICE_NAME"
    echo '{"provider":"llama.cpp","status":"stopped"}'
    ;;
  remove)
    user_systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
    rm -f -- "$unit_path"
    user_systemctl daemon-reload
    rm -rf -- "$source_dir" "$root_path"/build-* "$binary_path" "$root_path/runtime-version"
    printf '{"status":"removed","provider":"llama.cpp","runtime_root":"%s","model_files":"preserved"}\n' \
      "$root_path"
    ;;
  *) usage >&2; exit 2 ;;
esac
