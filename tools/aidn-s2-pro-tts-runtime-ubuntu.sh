#!/usr/bin/env bash
# Install and manage the reviewed s2.cpp runtime for Fish Audio S2 Pro TTS.
set -euo pipefail

readonly DEFAULT_REF="2c33261938da1a41d713768b1b391b4d368d7d2c"
readonly DEFAULT_PORT="3030"
readonly DEFAULT_ROOT="${HOME}/.local/share/aidn/providers/s2-pro-tts"
readonly REPOSITORY_URL="https://github.com/rodrigomatta/s2.cpp.git"
readonly MODEL_URL="https://huggingface.co/rodrigomt/s2-pro-gguf/resolve/main/s2-pro-q8_0.gguf?download=true"
readonly MODEL_SHA256="e2043182234786e7b975547d3bbcb23ff02e4ff684b82f7fa851287e4cb4f267"
readonly MODEL_SIZE="5630037088"
readonly MODEL_DOWNLOAD_JOBS="8"
readonly MODEL_DOWNLOAD_CHUNK_SIZE="268435456"
readonly SERVICE_NAME="aidn-s2-pro-tts.service"

usage() {
  cat <<'EOF'
Usage: aidn-s2-pro-tts-runtime-ubuntu.sh <install|start|status|stop|remove> [options]

Options:
  --ref REF         Reviewed s2.cpp commit (default: pinned commit)
  --root PATH       Operator-owned runtime root
  --model PATH      Absolute q8_0 GGUF path; required only for start
  --port PORT       Loopback HTTP port (default: 3030)

The Fish Audio Research License permits research/non-commercial use; obtain a
separate commercial license before using this model commercially.
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
    # s2.cpp exposes POST /generate, so its root GET normally returns 404
    # even when the listener and model are ready. Any HTTP response proves
    # that the loopback socket accepted the request.
    local code
    code="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 3 "http://127.0.0.1:$port/")"
    if [[ "$code" != "000" ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

download_model() {
  local temporary_model="$1"
  local parts_dir="${temporary_model}.parts"
  local download_url
  local part_count
  local index
  local start
  local end
  local part_path
  local running=0
  local failed=0
  local -a pids=()

  # A signed HF redirect is reused for all ranges.  The CDN advertises byte
  # ranges, which lets a stock Ubuntu install download the large GGUF without
  # requiring an additional package such as aria2.
  download_url="$(curl --proto '=https' --tlsv1.2 --fail --silent --show-error \
    --location --head --output /dev/null --write-out '%{url_effective}' "$MODEL_URL")"
  [[ -n "$download_url" ]] || die "could not resolve Hugging Face model URL"
  rm -rf -- "$parts_dir"
  mkdir -p "$parts_dir"
  part_count=$(( (MODEL_SIZE + MODEL_DOWNLOAD_CHUNK_SIZE - 1) / MODEL_DOWNLOAD_CHUNK_SIZE ))

  for ((index = 0; index < part_count; index += 1)); do
    start=$((index * MODEL_DOWNLOAD_CHUNK_SIZE))
    end=$((start + MODEL_DOWNLOAD_CHUNK_SIZE - 1))
    (( end >= MODEL_SIZE )) && end=$((MODEL_SIZE - 1))
    part_path="$parts_dir/part-$(printf '%05d' "$index")"
    (
      curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
        --retry 3 --range "$start-$end" "$download_url" -o "$part_path"
      [[ "$(stat -c '%s' "$part_path")" == "$((end - start + 1))" ]]
    ) &
    pids+=("$!")
    running=$((running + 1))
    if (( running >= MODEL_DOWNLOAD_JOBS )); then
      if ! wait "${pids[0]}"; then failed=1; fi
      pids=("${pids[@]:1}")
      running=$((running - 1))
    fi
  done
  for index in "${!pids[@]}"; do
    if ! wait "${pids[index]}"; then failed=1; fi
  done
  (( failed == 0 )) || die "one or more q8_0 model download ranges failed"

  : > "$temporary_model"
  for ((index = 0; index < part_count; index += 1)); do
    part_path="$parts_dir/part-$(printf '%05d' "$index")"
    cat "$part_path" >> "$temporary_model"
  done
  rm -rf -- "$parts_dir"
}

[[ $# -gt 0 ]] || { usage >&2; exit 2; }
if [[ "$1" == "-h" || "$1" == "--help" ]]; then usage; exit 0; fi
action="$1"
shift
ref="$DEFAULT_REF"
root_path="$DEFAULT_ROOT"
model_path=""
port="$DEFAULT_PORT"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref) [[ $# -ge 2 ]] || die "--ref requires a value"; ref="$2"; shift 2 ;;
    --root) [[ $# -ge 2 ]] || die "--root requires a value"; root_path="$2"; shift 2 ;;
    --model) [[ $# -ge 2 ]] || die "--model requires a value"; model_path="$2"; shift 2 ;;
    --port) [[ $# -ge 2 ]] || die "--port requires a value"; port="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ "$ref" == "$DEFAULT_REF" ]] || die "only reviewed s2.cpp ref $DEFAULT_REF is supported"
valid_absolute_path "$root_path" || die "--root must be an absolute path without whitespace or traversal"
[[ "$root_path" != "/" ]] || die "--root cannot be filesystem root"
valid_port "$port" || die "--port must be between 1 and 65535"
if [[ -n "$model_path" ]]; then
  valid_absolute_path "$model_path" || die "--model must be an absolute path without whitespace or traversal"
fi

source_dir="$root_path/source"
build_dir="$root_path/build-cuda"
binary_path="$root_path/bin/s2"
model_dir="$root_path/models"
default_model_path="$model_dir/s2-pro-q8_0.gguf"
tokenizer_path="$root_path/tokenizer.json"
unit_path="$HOME/.config/systemd/user/$SERVICE_NAME"

case "$action" in
  install)
    require_ubuntu
    command -v curl >/dev/null 2>&1 || die "curl is required"
    command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"
    command -v git >/dev/null 2>&1 || die "git is required"
    command -v cmake >/dev/null 2>&1 || die "cmake is required"
    find_nvcc >/dev/null || die "CUDA Toolkit with nvcc is required"
    mkdir -p "$root_path" "$root_path/bin" "$model_dir"

    if [[ -d "$source_dir/.git" ]]; then
      # The pinned s2.cpp build applies two reviewed ggml CUDA patches in the
      # submodule, so the parent checkout is expected to report a dirty
      # submodule after the first build.  Only reject changes in the pinned
      # repository itself; never overwrite an operator-edited source tree.
      git -C "$source_dir" diff --quiet --ignore-submodules || die "existing s2.cpp source checkout has local changes"
      git -C "$source_dir" diff --cached --quiet --ignore-submodules || die "existing s2.cpp source checkout has staged changes"
    else
      [[ ! -e "$source_dir" ]] || die "source path exists but is not a git checkout: $source_dir"
      git clone --recurse-submodules "$REPOSITORY_URL" "$source_dir"
    fi
    git -C "$source_dir" fetch --depth 1 origin "$ref"
    git -C "$source_dir" checkout --detach FETCH_HEAD
    git -C "$source_dir" submodule update --init --recursive

    export PATH="$(dirname "$(find_nvcc)"):$PATH"
    cmake -S "$source_dir" -B "$build_dir" -DCMAKE_BUILD_TYPE=Release -DS2_CUDA=ON
    cmake --build "$build_dir" --config Release --target s2 -j "$(nproc)"
    install -m 0755 "$build_dir/s2" "$binary_path"
    install -m 0644 "$source_dir/tokenizer.json" "$tokenizer_path"

    if [[ -f "$default_model_path" ]]; then
      actual_sha256="$(sha256sum "$default_model_path" | awk '{print $1}')"
      [[ "$actual_sha256" == "$MODEL_SHA256" ]] || die "existing q8_0 model checksum mismatch"
    else
      temporary_model="$default_model_path.tmp.$$"
      trap 'rm -f -- "$temporary_model" "$temporary_model.parts"' EXIT
      download_model "$temporary_model"
      actual_size="$(stat -c '%s' "$temporary_model")"
      [[ "$actual_size" == "$MODEL_SIZE" ]] || die "q8_0 model size mismatch: $actual_size"
      actual_sha256="$(sha256sum "$temporary_model" | awk '{print $1}')"
      [[ "$actual_sha256" == "$MODEL_SHA256" ]] || die "q8_0 model checksum mismatch"
      mv -- "$temporary_model" "$default_model_path"
      trap - EXIT
    fi
    chmod 600 "$default_model_path"
    printf '%s %s %s %s\n' "$ref" "$(git -C "$source_dir" rev-parse HEAD)" "$MODEL_SHA256" "$MODEL_SIZE" > "$root_path/runtime-version"
    chmod 600 "$root_path/runtime-version"
    printf '{"status":"installed","provider":"s2-pro-tts","ref":"%s","model":"%s","model_sha256":"%s","binary":"%s"}\n' \
      "$ref" "$default_model_path" "$MODEL_SHA256" "$binary_path"
    ;;
  start)
    [[ -x "$binary_path" ]] || die "s2.cpp runtime is not installed"
    [[ -n "$model_path" ]] || model_path="$default_model_path"
    [[ -r "$model_path" && -f "$model_path" ]] || die "q8_0 model is not a readable file: $model_path"
    [[ -r "$tokenizer_path" && -f "$tokenizer_path" ]] || die "tokenizer.json is not installed"
    mkdir -p "$(dirname "$unit_path")" "$root_path/state"
    cat > "$unit_path" <<EOF
[Unit]
Description=AiDN Fish Audio S2 Pro TTS Provider runtime
After=network-online.target

[Service]
Type=simple
Environment=PATH=/usr/local/cuda/bin:/usr/bin:/bin
Environment=LD_LIBRARY_PATH=/usr/local/cuda/lib64
ExecStart=$binary_path --model $model_path --tokenizer $tokenizer_path --server --host 127.0.0.1 --port $port --cuda 0 --gpu-layers -1 --codec-cpu --log-level warn
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadOnlyPaths=$model_path $tokenizer_path $root_path
ReadWritePaths=$root_path/state

[Install]
WantedBy=default.target
EOF
    user_systemctl daemon-reload
    user_systemctl enable --now "$SERVICE_NAME"
    wait_ready || {
      user_systemctl --no-pager --full status "$SERVICE_NAME" >&2 || true
      die "s2.cpp did not become ready on loopback"
    }
    printf '{"status":"ready","provider":"s2-pro-tts","model":"%s","endpoint":"http://127.0.0.1:%s"}\n' \
      "$model_path" "$port"
    ;;
  status)
    if [[ ! -x "$binary_path" ]]; then
      echo '{"provider":"s2-pro-tts","state":"absent"}'
      exit 3
    fi
    if [[ ! -f "$unit_path" ]]; then
      echo '{"provider":"s2-pro-tts","state":"installed_unconfigured"}'
      exit 0
    fi
    if ! user_systemctl is-active --quiet "$SERVICE_NAME"; then
      echo '{"provider":"s2-pro-tts","state":"installed_stopped"}'
      exit 3
    fi
    code="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 3 "http://127.0.0.1:$port/")"
    if [[ "$code" != "000" ]]; then
      printf '{"provider":"s2-pro-tts","state":"ready","endpoint":"http://127.0.0.1:%s"}\n' "$port"
    else
      echo '{"provider":"s2-pro-tts","state":"starting_or_unavailable"}'
      exit 3
    fi
    ;;
  stop)
    user_systemctl stop "$SERVICE_NAME"
    echo '{"provider":"s2-pro-tts","status":"stopped"}'
    ;;
  remove)
    user_systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
    rm -f -- "$unit_path"
    user_systemctl daemon-reload
    rm -rf -- "$source_dir" "$build_dir" "$binary_path" "$tokenizer_path" "$root_path/runtime-version"
    printf '{"status":"removed","provider":"s2-pro-tts","runtime_root":"%s","model_files":"preserved"}\n' \
      "$root_path"
    ;;
  *) usage >&2; exit 2 ;;
esac
