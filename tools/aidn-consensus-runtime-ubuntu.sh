#!/usr/bin/env bash
# Reviewed CometBFT runtime dispatcher used by the root-owned local broker.
# It accepts only the installer flags exposed by the broker and never accepts
# a caller-supplied command, binary, home, or unit outside that allowlist.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  aidn-consensus-runtime-ubuntu.sh <install|start|status|stop|restart|remove> [options]

Install options are forwarded to install-cometbft-ubuntu.sh. Lifecycle actions
accept --service-name NAME and operate only on that user-systemd unit.
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

valid_service_name() {
  [[ "$1" =~ ^[A-Za-z0-9_.@-]+\.service$ ]]
}

user_systemctl() {
  if [[ "$EUID" -eq 0 && "${AIDN_PROVIDER_RUNTIME_OPERATOR_UID:-}" =~ ^[0-9]+$ && -n "${AIDN_PROVIDER_RUNTIME_OPERATOR_NAME:-}" ]]; then
    local runtime_dir="/run/user/$AIDN_PROVIDER_RUNTIME_OPERATOR_UID"
    runuser -u "$AIDN_PROVIDER_RUNTIME_OPERATOR_NAME" -- env \
      HOME="${AIDN_PROVIDER_RUNTIME_OPERATOR_HOME:-/home/$AIDN_PROVIDER_RUNTIME_OPERATOR_NAME}" \
      USER="$AIDN_PROVIDER_RUNTIME_OPERATOR_NAME" \
      LOGNAME="$AIDN_PROVIDER_RUNTIME_OPERATOR_NAME" \
      XDG_RUNTIME_DIR="$runtime_dir" \
      DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime_dir/bus" \
      /usr/bin/systemctl --user "$@"
  else
    systemctl --user "$@"
  fi
}

[[ $# -ge 1 ]] || { usage >&2; exit 2; }
action="$1"
shift
case "$action" in
  install)
    script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    [[ -f "$script_dir/install-cometbft-ubuntu.sh" ]] || die "CometBFT installer is missing"
    exec bash "$script_dir/install-cometbft-ubuntu.sh" "$@" --no-start
    ;;
  start|status|stop|restart|remove)
    service_name=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --service-name)
          [[ $# -ge 2 ]] || die "--service-name requires a value"
          service_name="$2"
          shift 2
          ;;
        -h|--help) usage; exit 0 ;;
        *) die "unsupported lifecycle option: $1" ;;
      esac
    done
    [[ -n "$service_name" ]] && valid_service_name "$service_name" || die "--service-name must be a valid .service unit"
    if [[ "$action" == "remove" ]]; then
      user_systemctl disable --now "$service_name" >/dev/null 2>&1 || true
      user_systemctl daemon-reload
      unit_path="${AIDN_PROVIDER_RUNTIME_OPERATOR_HOME:-$HOME}/.config/systemd/user/$service_name"
      [[ "$unit_path" == /* && "$unit_path" != *' '* ]] || die "unit path is invalid"
      rm -f -- "$unit_path"
      echo '{"status":"ok","action":"remove"}'
    elif [[ "$action" == "status" ]]; then
      active="inactive"
      if user_systemctl is-active "$service_name" >/dev/null 2>&1; then active="active"; fi
      printf '{"status":"ok","action":"status","service":"%s","active":"%s"}\n' "$service_name" "$active"
    else
      user_systemctl "$action" "$service_name"
      printf '{"status":"ok","action":"%s","service":"%s"}\n' "$action" "$service_name"
    fi
    ;;
  -h|--help) usage; exit 0 ;;
  *) die "unsupported CometBFT runtime action: $action" ;;
esac
