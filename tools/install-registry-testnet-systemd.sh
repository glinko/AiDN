#!/usr/bin/env bash
# Install one operator-owned, systemd-managed replication-enabled Hypervisor.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  install-registry-testnet-systemd.sh \
    --root PATH --repo PATH [--run-as USER] [--service-name NAME] [--api-port PORT]

The root must contain registry-replication.json, secrets.json, master-key.b64,
and a prepared Python virtual environment at REPO/.venv. The master key is
read only by the generated local wrapper and is never written to the unit.
The command refuses to replace a running PID recorded in ROOT/replication-
hypervisor.pid; stop the disposable nohup process explicitly before migration.
EOF
}

root=''
repo=''
run_as="$(id -un)"
service_name='aidn-registry-testnet'
api_port='8767'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) root="$2"; shift 2 ;;
    --repo) repo="$2"; shift 2 ;;
    --run-as) run_as="$2"; shift 2 ;;
    --service-name) service_name="$2"; shift 2 ;;
    --api-port) api_port="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$root" && -n "$repo" ]] || {
  echo '--root and --repo are required' >&2
  exit 2
}
[[ "$root" == /* && "$repo" == /* ]] || {
  echo '--root and --repo must be absolute paths' >&2
  exit 2
}
[[ "$root$repo" != *[[:space:]]* ]] || {
  echo '--root and --repo must not contain whitespace' >&2
  exit 2
}
[[ "$service_name" =~ ^[A-Za-z0-9_.@-]+$ ]] || {
  echo '--service-name contains unsupported characters' >&2
  exit 2
}
[[ "$run_as" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || {
  echo '--run-as contains unsupported characters' >&2
  exit 2
}
[[ "$api_port" =~ ^[0-9]+$ ]] || {
  echo '--api-port must be numeric' >&2
  exit 2
}
(( api_port >= 1 && api_port <= 65535 )) || {
  echo '--api-port must be between 1 and 65535' >&2
  exit 2
}

[[ -d "$root" ]] || { echo "root directory does not exist: $root" >&2; exit 1; }
[[ -d "$repo/.git" ]] || { echo "repository is invalid: $repo" >&2; exit 1; }
for required in registry-replication.json secrets.json master-key.b64; do
  [[ -f "$root/$required" ]] || {
    echo "required replication file is missing: $root/$required" >&2
    exit 1
  }
done
python_bin="$repo/.venv/bin/python"
[[ -x "$python_bin" ]] || {
  echo "prepared venv is missing: $python_bin" >&2
  exit 1
}
id "$run_as" >/dev/null 2>&1 || { echo "run user does not exist: $run_as" >&2; exit 1; }

pid_file="$root/replication-hypervisor.pid"
if [[ -f "$pid_file" ]]; then
  pid="$(cat "$pid_file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    echo "refusing to replace running replication process $pid; stop it first" >&2
    exit 1
  fi
fi

group_name="$(id -gn "$run_as")"
wrapper="$root/run-hypervisor.sh"
unit_file="$(mktemp)"
cleanup() { rm -f "$unit_file"; }
trap cleanup EXIT

printf -v quoted_root '%q' "$root"
printf -v quoted_repo '%q' "$repo"
printf -v quoted_python '%q' "$python_bin"
cat > "$wrapper" <<EOF
#!/usr/bin/env bash
set -euo pipefail
root=$quoted_root
repo=$quoted_repo
python_bin=$quoted_python
export AIDN_REGISTRY_REPLICATION_CONFIG="\$root/registry-replication.json"
export AIDN_SECRET_MANAGER_PATH="\$root/secrets.json"
export AIDN_SECRET_MANAGER_MASTER_KEY="\$(tr -d '\\r\\n' < "\$root/master-key.b64")"
export AIDN_HYPERVISOR_STATE_PATH="\$root/hypervisor-state.json"
export AIDN_HYPERVISOR_BUNDLES_PATH="\$root/bundles.json"
export PYTHONUNBUFFERED=1
exec "\$python_bin" -m uvicorn aidn_hypervisor.main:build_app --factory --host 127.0.0.1 --port $api_port
EOF
chmod 700 "$wrapper"

cat > "$unit_file" <<EOF
[Unit]
Description=AiDN controlled Registry replication Hypervisor ($service_name)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$run_as
Group=$group_name
WorkingDirectory=$repo
ExecStart=$wrapper
Restart=on-failure
RestartSec=3
TimeoutStopSec=20
KillSignal=SIGTERM
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$root
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo install -o root -g root -m 0644 "$unit_file" "/etc/systemd/system/$service_name.service"
sudo systemctl daemon-reload
sudo systemctl enable --now "$service_name.service"

if [[ "$(sudo systemctl is-active "$service_name.service")" != 'active' ]]; then
  echo "systemd service did not become active: $service_name.service" >&2
  sudo systemctl --no-pager --full status "$service_name.service" >&2 || true
  exit 1
fi

printf '{"status":"ok","service":"%s","root":"%s","api_port":%s}\n' \
  "$service_name" "$root" "$api_port"
