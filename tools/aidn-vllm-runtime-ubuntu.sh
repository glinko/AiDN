#!/usr/bin/env bash
# Install and manage one loopback-only NVIDIA vLLM server for AiDN.
set -euo pipefail

readonly DEFAULT_VERSION="0.27.1"
readonly DEFAULT_PYTHON="3.12"
readonly DEFAULT_PORT="8000"
readonly SERVICE_NAME="aidn-vllm.service"

usage() {
  cat <<'EOF'
Usage: aidn-vllm-runtime-ubuntu.sh <install|start|status|stop> [options]

Options:
  --version VERSION       Pinned vLLM version (default: 0.27.1)
  --python VERSION        Managed Python version (default: 3.12)
  --root PATH             Operator-owned install root
  --model MODEL           Hugging Face model ID; required only for start
  --served-model-name ID  Optional API-visible model ID

This first managed profile targets NVIDIA CUDA on Linux. Installation creates
an isolated uv environment; model download remains a start/configuration step.
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

valid_model_id() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ && "$1" != *".."* && "$1" != /* ]]
}

resolve_uv() {
  if command -v uv >/dev/null 2>&1; then command -v uv; return; fi
  if [[ -x "$HOME/.local/bin/uv" ]]; then printf '%s\n' "$HOME/.local/bin/uv"; return; fi
  return 1
}

wait_ready() {
  for _ in $(seq 1 180); do
    if curl --fail --silent --max-time 3 "http://127.0.0.1:$DEFAULT_PORT/v1/models" >/dev/null; then
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
python_version="$DEFAULT_PYTHON"
root_path="${HOME}/.local/share/aidn/providers/vllm"
model_id=""
served_model_name=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) [[ $# -ge 2 ]] || die "--version requires a value"; version="$2"; shift 2 ;;
    --python) [[ $# -ge 2 ]] || die "--python requires a value"; python_version="$2"; shift 2 ;;
    --root) [[ $# -ge 2 ]] || die "--root requires a value"; root_path="$2"; shift 2 ;;
    --model) [[ $# -ge 2 ]] || die "--model requires a value"; model_id="$2"; shift 2 ;;
    --served-model-name) [[ $# -ge 2 ]] || die "--served-model-name requires a value"; served_model_name="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || die "invalid vLLM version"
[[ "$version" == "$DEFAULT_VERSION" ]] || die "only reviewed vLLM version $DEFAULT_VERSION is supported"
[[ "$python_version" =~ ^3\.(10|11|12|13)$ ]] || die "vLLM Python must be 3.10 through 3.13"
[[ "$python_version" == "$DEFAULT_PYTHON" ]] || die "only reviewed Python $DEFAULT_PYTHON is supported"
valid_absolute_path "$root_path" || die "--root must be an absolute path without whitespace"
if [[ -n "$model_id" ]]; then valid_model_id "$model_id" || die "invalid Hugging Face model ID"; fi
if [[ -n "$served_model_name" ]]; then valid_model_id "$served_model_name" || die "invalid served model name"; fi

venv_path="$root_path/venv"
binary_path="$venv_path/bin/vllm"
unit_path="$HOME/.config/systemd/user/$SERVICE_NAME"

case "$action" in
  install)
    require_ubuntu
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends ca-certificates curl
    if ! uv_bin="$(resolve_uv)"; then
      temporary_dir="$(mktemp -d)"
      trap 'rm -rf -- "$temporary_dir"' EXIT
      curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
        https://astral.sh/uv/install.sh -o "$temporary_dir/install-uv.sh"
      sh "$temporary_dir/install-uv.sh"
      uv_bin="$(resolve_uv)" || die "uv installation did not produce an executable"
    fi
    mkdir -p "$root_path" "$root_path/cache/huggingface" "$root_path/cache/vllm"
    "$uv_bin" venv --python "$python_version" --seed "$venv_path"
    "$uv_bin" pip install --python "$venv_path/bin/python" "vllm==$version" --torch-backend=auto
    [[ -x "$binary_path" ]] || die "vLLM installation did not produce an executable"
    printf '%s\n' "$version python-$python_version cuda-auto" > "$root_path/runtime-version"
    chmod 600 "$root_path/runtime-version"
    printf '{"status":"installed","provider":"vllm","version":"%s","python":"%s","binary":"%s"}\n' \
      "$version" "$python_version" "$binary_path"
    ;;
  start)
    [[ -x "$binary_path" ]] || die "vLLM runtime is not installed"
    [[ -n "$model_id" ]] || die "--model is required for start"
    command -v nvidia-smi >/dev/null 2>&1 || die "the managed vLLM profile requires an NVIDIA driver"
    nvidia-smi >/dev/null || die "the NVIDIA driver is unavailable"
    mkdir -p "$(dirname "$unit_path")" "$root_path/cache/huggingface" "$root_path/cache/vllm"
    served_args=""
    if [[ -n "$served_model_name" ]]; then served_args=" --served-model-name $served_model_name"; fi
    cat > "$unit_path" <<EOF
[Unit]
Description=AiDN vLLM Provider runtime
After=network-online.target

[Service]
Type=simple
Environment=HF_HOME=$root_path/cache/huggingface
Environment=VLLM_CACHE_ROOT=$root_path/cache/vllm
ExecStart=$binary_path serve $model_id --host 127.0.0.1 --port $DEFAULT_PORT$served_args
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$root_path

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now "$SERVICE_NAME"
    wait_ready || {
      systemctl --user --no-pager --full status "$SERVICE_NAME" >&2 || true
      die "vLLM did not become ready on loopback"
    }
    printf '{"status":"ready","provider":"vllm","model":"%s","endpoint":"http://127.0.0.1:%s"}\n' \
      "$model_id" "$DEFAULT_PORT"
    ;;
  status)
    if [[ ! -x "$binary_path" ]]; then
      echo '{"provider":"vllm","state":"absent"}'
      exit 3
    fi
    if [[ ! -f "$unit_path" ]]; then
      echo '{"provider":"vllm","state":"installed_unconfigured"}'
      exit 0
    fi
    if ! systemctl --user is-active --quiet "$SERVICE_NAME"; then
      echo '{"provider":"vllm","state":"installed_stopped"}'
      exit 3
    fi
    if curl --fail --silent --max-time 3 "http://127.0.0.1:$DEFAULT_PORT/v1/models" >/dev/null; then
      printf '{"provider":"vllm","state":"ready","endpoint":"http://127.0.0.1:%s"}\n' "$DEFAULT_PORT"
    else
      echo '{"provider":"vllm","state":"starting_or_unavailable"}'
      exit 3
    fi
    ;;
  stop)
    systemctl --user stop "$SERVICE_NAME"
    echo '{"provider":"vllm","status":"stopped"}'
    ;;
  *) usage >&2; exit 2 ;;
esac
