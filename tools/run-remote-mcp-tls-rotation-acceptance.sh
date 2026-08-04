#!/usr/bin/env bash
# Run the real MCP TLS rotation acceptance harness on an Ubuntu operator host.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run-remote-mcp-tls-rotation-acceptance.sh \
    --remote-ssh USER@HOST [--remote-repo PATH|auto] [--timeout-seconds N] [--keep]

The remote host must already have the AiDN checkout and its .venv prepared.
SSH key or interactive password authentication is handled by ssh itself. The
script creates only disposable acceptance state on the remote host and never
uses the operator's production Secret Manager or TLS handles.
EOF
}

remote_ssh=''
remote_repo='auto'
timeout_seconds='30'
keep='false'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote-ssh) remote_ssh="$2"; shift 2 ;;
    --remote-repo) remote_repo="$2"; shift 2 ;;
    --timeout-seconds) timeout_seconds="$2"; shift 2 ;;
    --keep) keep='true'; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$remote_ssh" ]] || { echo '--remote-ssh is required' >&2; exit 2; }
[[ "$timeout_seconds" =~ ^[0-9]+([.][0-9]+)?$ ]] || {
  echo '--timeout-seconds must be positive' >&2; exit 2;
}

if [[ "$remote_repo" == 'auto' ]]; then
  remote_repo="$(ssh "$remote_ssh" 'for candidate in "$HOME/aidn/AiDN" "$HOME/aidn-registry-acceptance" "$HOME/AiDN"; do if [[ -f "$candidate/.git/HEAD" || -f "$candidate/.git" ]]; then printf "%s" "$candidate"; exit 0; fi; done; exit 1')" || {
    echo 'could not resolve a remote AiDN repository; pass --remote-repo explicitly' >&2
    exit 1
  }
fi

ssh "$remote_ssh" bash -s -- "$remote_repo" "$timeout_seconds" "$keep" <<'REMOTE'
set -euo pipefail
repo="$1"
timeout_seconds="$2"
keep="$3"
[[ -f "$repo/.git/HEAD" || -f "$repo/.git" ]] || {
  echo "remote repository is invalid: $repo" >&2
  exit 1
}
python_bin="$repo/.venv/bin/python"
[[ -x "$python_bin" ]] || {
  echo "remote virtualenv is missing: $python_bin" >&2
  exit 1
}
args=("$repo/tools/run_mcp_tls_rotation_acceptance.py" --repo "$repo" --timeout-seconds "$timeout_seconds")
if [[ "$keep" == 'true' ]]; then args+=(--keep); fi
exec "$python_bin" "${args[@]}"
REMOTE
