#!/usr/bin/env bash
# Dispatch one reviewed AiDN Provider runtime action on Ubuntu.
#
# This is intentionally an allowlist, not a generic command runner. Future
# dashboard execution may call this entrypoint only after the Hypervisor has
# validated an approved installation plan and exact arguments.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  aidn-provider-runtime-ubuntu.sh <whisper|ollama|llama.cpp|vllm> \
    <install|start|status|stop|remove> [provider options]

The dispatcher never accepts a script path or arbitrary shell command.
Provider-specific help:
  aidn-provider-runtime-ubuntu.sh <provider> --help
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

[[ $# -ge 1 ]] || { usage >&2; exit 2; }

provider="$1"
shift
# The production broker runs this immutable dispatcher as root but keeps the
# operator's HOME and user-systemd runtime context for provider-local state.
# These values are injected by the root-owned broker, never accepted from the
# dashboard request.
if [[ "$EUID" -eq 0 && -n "${AIDN_PROVIDER_RUNTIME_OPERATOR_HOME:-}" ]]; then
  export HOME="$AIDN_PROVIDER_RUNTIME_OPERATOR_HOME"
  export USER="${AIDN_PROVIDER_RUNTIME_OPERATOR_NAME:-${USER:-root}}"
  export LOGNAME="$USER"
  if [[ "${AIDN_PROVIDER_RUNTIME_OPERATOR_UID:-}" =~ ^[0-9]+$ ]]; then
    export XDG_RUNTIME_DIR="/run/user/$AIDN_PROVIDER_RUNTIME_OPERATOR_UID"
    export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
  fi
  export PATH="$HOME/.local/bin:/usr/local/cuda/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
fi
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

case "$provider" in
  whisper) provider_script="$script_dir/aidn-whisper-runtime-ubuntu.sh" ;;
  ollama) provider_script="$script_dir/aidn-ollama-runtime-ubuntu.sh" ;;
  llama.cpp|llamacpp) provider_script="$script_dir/aidn-llamacpp-runtime-ubuntu.sh" ;;
  vllm) provider_script="$script_dir/aidn-vllm-runtime-ubuntu.sh" ;;
  -h|--help) usage; exit 0 ;;
  *) die "unsupported Provider runtime: $provider" ;;
esac

[[ -f "$provider_script" ]] || die "reviewed Provider runtime script is missing: $provider_script"
exec bash "$provider_script" "$@"
