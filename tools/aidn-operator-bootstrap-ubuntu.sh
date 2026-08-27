#!/usr/bin/env bash
# Install one persistent AiDN operator on Ubuntu 24.04+.
#
# The default deployment is safe for a fresh host: the Hypervisor API and the
# Registry listener bind to loopback, no firewall rule is changed, and no
# private key or sudo password is printed or persisted in unit metadata.
set -euo pipefail

readonly REPOSITORY_URL="https://github.com/glinko/AiDN.git"
readonly SCRIPT_NAME="aidn-operator-bootstrap-ubuntu.sh"
readonly GENERATED_DASHBOARD_PATH="src/aidn_hypervisor/static/react-dashboard"

usage() {
  cat <<'EOF'
Usage:
  aidn-operator-bootstrap-ubuntu.sh [options]

Interactive wizard (default):
  curl --proto '=https' --tlsv1.2 -fsSL \
    https://raw.githubusercontent.com/glinko/AiDN/<reviewed-ref>/tools/aidn-operator-bootstrap-ubuntu.sh \
    | bash -s -- --ref <reviewed-ref>

Options:
  --operator-id ID          Operator/node identity (default: sanitized hostname)
  --peer-id ID              Registry peer ID (default: operator ID)
  --control-group-id ID     Declared control group (default: control-group-<operator>)
  --ref REF                 Git branch, tag, or reviewed commit (default: main)
  --install-dir DIR         Checkout path (default: $HOME/aidn/<operator>/AiDN)
  --data-dir DIR            Persistent state path (default: $HOME/.local/share/aidn/<operator>)
  --api-host HOST           Hypervisor bind address (default: 127.0.0.1)
  --api-port PORT           Hypervisor API port (default: 8766)
  --allow-public-api        Confirm an explicit non-loopback API bind
  --enable-registry         Enable the mTLS Registry listener
  --registry-listen-host H  Registry bind address (default: 0.0.0.0 when enabled)
  --registry-port PORT      Registry mTLS port (default: 9444)
  --advertise-host HOST     Address included in public-peer.json
  --network-id ID           Network ID (default: aidn)
  --chain-id ID             Chain ID (default: aidn-testnet-1)
  --network-revision REV    Network revision (default: 1.0)
  --consensus-mode MODE     validator, non_validator, or disabled (default: validator)
  --consensus-rpc URL       Verified private RPC for non_validator mode (required)
  --cometbft-version TAG   CometBFT release tag (default: v0.38.19)
  --no-consensus             Disable automatic local CometBFT installation
  --no-start                Install and write the user service, but do not start it
  --wallet-action ACTION    create, import, or skip (interactive default: create)
  --dashboard-pairing ACTION code, first_browser, or skip (interactive default: code)
  --agent-action ACTION     guide or skip existing MCP enrollment (default: guide)
  --setup-mode MODE         manual or ai_assisted (interactive default: manual)
  --setup-provider ID       skip, ollama, llama.cpp, or vllm for AI-assisted setup
  --setup-model ID           provider/model identifier for AI-assisted setup
  --setup-model-source SRC  HTTPS or hf:// model source (never a secret-bearing URL)
  --setup-endpoint ACTION   skip, draft, or start a private endpoint plan
  --setup-handoff TARGET    continue or dashboard after the AI-assisted plan
  --non-interactive         Use defaults and supplied flags; fail if a value is unsafe
  -h, --help                Show this help

The wizard reads prompts from /dev/tty, so it also works when downloaded via
curl | bash. It never asks for, stores, or sends a root password. Ubuntu sudo
prompts normally when package installation is required.

Interactive choices include a short consequence note. On success the installer
prints one structured handoff with URLs, identities, public artifacts, wallet
and pairing state, private-file locations, and next commands; secret contents
are never printed.

Finite-choice prompts are numbered: enter 1, 2, 3, and so on (or press Enter
for the marked default). AI-assisted setup includes a reviewed Qwen3 GGUF
model catalog with approximate download, VRAM, and RAM requirements. Built-in
artifacts use immutable Hugging Face revisions and pinned size/SHA-256 checks;
Custom model remains available for a public HTTPS or hf:// reference (optionally
with @40-hex-revision).

Rerunning the installer refreshes generated Dashboard assets left by an earlier
attempt. Any other local checkout changes are preserved in a timestamped
bootstrap-backup directory before a clean reviewed checkout is activated.

The first interactive question is the setup mode. Manual keeps the existing
step-by-step flow. AI-assisted still asks and validates every required node
parameter, then records an explicit, resumable plan for the CPU-first Resident
Steward. After an operator selects a concrete llama.cpp artifact, the installer
installs the reviewed CPU runtime, downloads and verifies the artifact before
the Hypervisor service starts, then prepares and starts the Resident Steward
automatically. Bundle creation, endpoint start, and publication remain bounded,
operator-approved actions that can be continued from the dashboard.

The installer creates a host-local encrypted Registry Secret Manager and an
Ed25519 operator identity. The private material stays below --data-dir with
mode 0600. Exchange only public-peer.json and operator-public-identity.json
after independent out-of-band approval.
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

require_value() {
  [[ $# -ge 2 ]] || die "$1 requires a value"
}

valid_identifier() {
  [[ "$1" =~ ^[A-Za-z0-9._-]+$ ]]
}

valid_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && (( 1 <= 10#$1 && 10#$1 <= 65535 ))
}

valid_path() {
  [[ "$1" =~ ^/[A-Za-z0-9._/-]+$ && "$1" != *".."* ]]
}

checkout_is_clean() {
  local checkout="$1"
  [[ -z "$(git -C "$checkout" status --porcelain=v1 --untracked-files=all)" ]]
}

clean_generated_dashboard_assets() {
  local checkout="$1"
  local generated_status
  generated_status="$(git -C "$checkout" status --porcelain=v1 --untracked-files=all -- "$GENERATED_DASHBOARD_PATH")"
  [[ -n "$generated_status" ]] || return 0

  # The dashboard build replaces this directory atomically. It is a generated
  # deployment artifact, not operator configuration, so restore the tracked
  # baseline and remove stale generated files before the next build.
  printf '  [bootstrap] refreshing generated Dashboard assets in %s\n' "$checkout/$GENERATED_DASHBOARD_PATH" >&2
  git -C "$checkout" restore --source=HEAD --staged --worktree -- "$GENERATED_DASHBOARD_PATH"
  git -C "$checkout" clean -fd -- "$GENERATED_DASHBOARD_PATH"
}

next_checkout_path() {
  local base="$1"
  local suffix="$2"
  local stamp
  local candidate
  local counter=0
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  candidate="${base}.${suffix}-${stamp}"
  while [[ -e "$candidate" ]]; do
    counter=$((counter + 1))
    candidate="${base}.${suffix}-${stamp}-${counter}"
  done
  printf '%s' "$candidate"
}

clone_reviewed_checkout() {
  local target="$1"
  mkdir -p "$(dirname "$target")"
  git clone --depth 1 "$REPOSITORY_URL" "$target"
  git -C "$target" fetch --depth 1 origin "$ref"
  git -C "$target" checkout --detach FETCH_HEAD
}

replace_dirty_checkout() {
  local checkout="$1"
  local backup_path
  local staging_path

  backup_path="$(next_checkout_path "$checkout" 'bootstrap-backup')"
  staging_path="$(next_checkout_path "$checkout" 'bootstrap-new')"
  printf '  [bootstrap] local checkout changes detected; preparing a clean checkout\n' >&2
  clone_reviewed_checkout "$staging_path"

  if ! mv -- "$checkout" "$backup_path"; then
    die "could not preserve the existing checkout: $checkout"
  fi
  if ! mv -- "$staging_path" "$checkout"; then
    mv -- "$backup_path" "$checkout" || die "could not restore the existing checkout: $backup_path"
    die "could not activate the clean checkout: $checkout"
  fi
  checkout_backup_path="$backup_path"
  printf '  [bootstrap] preserved previous checkout at %s\n' "$checkout_backup_path" >&2
}

is_loopback_host() {
  [[ "$1" == "127.0.0.1" || "$1" == "::1" || "$1" == "localhost" ]]
}

valid_consensus_rpc() {
  [[ "$1" =~ ^https?://[^[:space:]/]+:[0-9]+/?$ ]]
}

sanitize_hostname() {
  local value
  value="$(hostname -s 2>/dev/null || printf 'aidn-operator')"
  value="$(printf '%s' "$value" | tr -c 'A-Za-z0-9._-' '-')"
  value="${value#-}"
  value="${value%-}"
  if [[ -z "$value" ]] || ! valid_identifier "$value"; then
    value='aidn-operator'
  fi
  printf '%s' "$value"
}

detect_advertise_host() {
  local value
  value="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [[ -z "$value" ]]; then
    value='127.0.0.1'
  fi
  printf '%s' "$value"
}

model_prefetch_progress() {
  # Render only between questions so a background writer never corrupts the
  # operator's current prompt line.
  local state_path="${model_prefetch_state_path:-}"
  local progress_python="${model_prefetch_python:-}"
  [[ -n "$state_path" && -f "$state_path" && -n "$progress_python" ]] || return 0
  local line
  line="$($progress_python - "$state_path" <<'PY' 2>/dev/null || true
import json
import sys

try:
    payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
except Exception:
    print("status unavailable")
    raise SystemExit(0)

status = str(payload.get("status") or "unknown")
downloaded = int(payload.get("downloaded_bytes") or 0)
total = payload.get("total_bytes")
if isinstance(total, int) and total > 0:
    percent = int(downloaded * 100 / total)
    width = 24
    filled = min(width, max(0, int(width * percent / 100)))
    bar = "#" * filled + "." * (width - filled)

    def human(value):
        value = float(value)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f} {unit}"
            value /= 1024

    print(f"{status} [{bar}] {percent:3d}% ({human(downloaded)} / {human(total)})")
else:
    print(f"{status} ({downloaded} bytes)")
PY
)"
  printf '  [model download] %s\n' "$line" >&2
}

model_source_to_download_url() {
  local source="$1"
  if [[ "$source" == hf://* ]]; then
    local reference="${source#hf://}"
    local owner="${reference%%/*}"
    local remainder="${reference#*/}"
    local repository_ref="${remainder%%/*}"
    local repository="$repository_ref"
    local revision='main'
    if [[ "$repository_ref" == *@* ]]; then
      repository="${repository_ref%@*}"
      revision="${repository_ref#*@}"
    fi
    local file_path="${remainder#*/}"
    [[ -n "$owner" && -n "$repository" && "$file_path" != "$remainder" ]] || return 1
    [[ "$revision" == 'main' || "$revision" =~ ^[0-9a-fA-F]{40}$ ]] || return 1
    printf 'https://huggingface.co/%s/%s/resolve/%s/%s' "$owner" "$repository" "$revision" "$file_path"
    return 0
  fi
  printf '%s' "$source"
}

available_disk_bytes() {
  local path="$1"
  local existing_path="$path"
  while [[ ! -e "$existing_path" && "$existing_path" != '/' ]]; do
    existing_path="${existing_path%/*}"
    [[ -n "$existing_path" ]] || existing_path='/'
  done
  local available_kib
  available_kib="$(df -Pk "$existing_path" 2>/dev/null | awk 'NR == 2 { print $4; exit }')"
  [[ "$available_kib" =~ ^[0-9]+$ ]] || return 1
  printf '%s' "$((available_kib * 1024))"
}

start_model_prefetch() {
  local provider="$1"
  local model_id="$2"
  local source="$3"
  [[ "$provider" == 'llama.cpp' && "$model_id" != 'skip' && -n "$source" ]] || return 0
  model_prefetch_status='preparing'

  local download_url
  download_url="$(model_source_to_download_url "$source")" || {
    model_prefetch_status='skipped_source'
    printf '  [model download] skipped: source could not be resolved\n' >&2
    return 0
  }
  local prefetch_python
  prefetch_python="$(command -v python3 || command -v python || true)"
  if [[ -z "$prefetch_python" ]]; then
    model_prefetch_status='skipped_python'
    printf '  [model download] skipped: Python 3 is not available for the background worker\n' >&2
    return 0
  fi

  local safe_model_id="${model_id//\//_}"
  local model_dir="$data_dir/models/$provider"
  local prefetch_target="$model_dir/$safe_model_id"
  local state_path="${prefetch_target}.aidn-prefetch.json"
  local temporary_path="${prefetch_target}.part.$$"
  local safe_log_name="${safe_model_id//[^A-Za-z0-9._-]/_}"
  local log_path="$data_dir/logs/model-prefetch-$safe_log_name.log"
  local max_bytes="${AIDN_PREFETCH_MAX_BYTES:-68719476736}"
  if [[ ! "$max_bytes" =~ ^[0-9]+$ || "$max_bytes" -le 0 ]]; then
    max_bytes=68719476736
  fi
  local expected_sha256=''
  local expected_bytes=''
  local catalog_source
  catalog_source="$(model_source_for_id "$model_id" || true)"
  if [[ -n "$catalog_source" && "$source" == "$catalog_source" ]]; then
    expected_sha256="$(model_expected_sha256_for_id "$model_id" || true)"
    expected_bytes="$(model_expected_size_bytes_for_id "$model_id" || true)"
  fi
  if ! mkdir -p "$model_dir" "$data_dir/logs"; then
    model_prefetch_status='skipped_unwritable'
    printf '  [model download] skipped: model cache directory is not writable\n' >&2
    return 0
  fi
  if ! chmod 700 "$data_dir" "$data_dir/models" "$model_dir" "$data_dir/logs"; then
    model_prefetch_status='skipped_permissions'
    printf '  [model download] skipped: could not secure model cache permissions\n' >&2
    return 0
  fi

  model_prefetch_state_path="$state_path"
  model_prefetch_target="$prefetch_target"
  model_prefetch_source="$source"
  model_prefetch_python="$prefetch_python"
  model_prefetch_expected_sha256="$expected_sha256"
  model_prefetch_expected_bytes="$expected_bytes"

  if [[ -n "$expected_bytes" ]]; then
    if (( expected_bytes > max_bytes )); then
      model_prefetch_status='skipped_limit'
      printf '  [model download] skipped: pinned artifact is larger than AIDN_PREFETCH_MAX_BYTES (%s bytes)\n' "$max_bytes" >&2
      return 0
    fi
    local existing_target_bytes=0
    if [[ -f "$prefetch_target" ]]; then
      existing_target_bytes="$(stat -c '%s' "$prefetch_target" 2>/dev/null || printf '0')"
      [[ "$existing_target_bytes" =~ ^[0-9]+$ ]] || existing_target_bytes=0
    fi
    local disk_safety_bytes=$((256 * 1024 * 1024))
    local required_disk_bytes=$((expected_bytes + existing_target_bytes + disk_safety_bytes))
    local free_disk_bytes
    free_disk_bytes="$(available_disk_bytes "$model_dir" || true)"
    if [[ ! "$free_disk_bytes" =~ ^[0-9]+$ ]]; then
      model_prefetch_status='skipped_disk_unknown'
      printf '  [model download] skipped: free disk space could not be measured\n' >&2
      return 0
    fi
    if (( free_disk_bytes < required_disk_bytes )); then
      model_prefetch_status='skipped_disk'
      printf '  [model download] skipped: need %s bytes free, only %s available\n' "$required_disk_bytes" "$free_disk_bytes" >&2
      return 0
    fi
  fi

  nohup "$prefetch_python" - "$download_url" "$source" "$provider" "$model_id" \
    "$temporary_path" "$prefetch_target" "$state_path" "$max_bytes" \
    "$expected_sha256" "$expected_bytes" \
    >"$log_path" 2>&1 <<'PY' &
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

(
    download_url,
    source_url,
    provider_type,
    model_id,
    temporary_path,
    target_path,
    state_path,
    max_bytes_raw,
    expected_sha256_raw,
    expected_bytes_raw,
) = sys.argv[1:]
max_bytes = int(max_bytes_raw)
expected_sha256 = expected_sha256_raw.lower() or None
if expected_sha256 is not None and (
    len(expected_sha256) != 64
    or any(character not in "0123456789abcdef" for character in expected_sha256)
):
    raise ValueError("invalid expected SHA-256 value")
expected_bytes = int(expected_bytes_raw) if expected_bytes_raw else None
if expected_bytes is not None and expected_bytes <= 0:
    raise ValueError("invalid expected artifact size")
state_file = Path(state_path)
target = Path(target_path)
temporary = Path(temporary_path)
safety_bytes = 256 * 1024 * 1024

def write_state(status, **fields):
    payload = {
        "schema_version": 1,
        "status": status,
        "pid": os.getpid(),
        "provider_type": provider_type,
        "model_id": model_id,
        "source_url": source_url,
        "resolved_source_url": download_url,
        "target_path": str(target),
        "expected_sha256": expected_sha256,
        "expected_bytes": expected_bytes,
        "integrity_mode": "pinned" if expected_sha256 and expected_bytes else "computed_only",
        "updated_at": time.time(),
        **fields,
    }
    state_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary_state = tempfile.mkstemp(
        prefix=f".{state_file.name}.", dir=state_file.parent
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temporary_state, state_file)
    except Exception:
        try:
            os.unlink(temporary_state)
        except OSError:
            pass
        raise

def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()

def ensure_disk_space(required_bytes):
    available = shutil.disk_usage(temporary.parent).free
    if available < required_bytes:
        raise ValueError(
            f"insufficient free disk space (need {required_bytes} bytes, have {available})"
        )

try:
    if target.is_file() and state_file.is_file():
        try:
            existing = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        existing_expected_sha256 = existing.get("expected_sha256")
        existing_expected_bytes = existing.get("expected_bytes")
        if (
            existing.get("status") == "completed"
            and existing.get("source_url") == source_url
            and existing.get("provider_type") == provider_type
            and existing.get("model_id") == model_id
            and (existing_expected_sha256 or None) == expected_sha256
            and (existing_expected_bytes or None) == expected_bytes
        ):
            target_size = target.stat().st_size
            existing_sha256 = sha256_file(target)
            if (
                (expected_bytes is None or target_size == expected_bytes)
                and (expected_sha256 is None or existing_sha256 == expected_sha256)
                and (
                    not existing.get("sha256")
                    or existing.get("sha256") == existing_sha256
                )
            ):
                write_state(
                    "completed",
                    downloaded_bytes=target_size,
                    total_bytes=target_size,
                    percent=100,
                    sha256=existing_sha256,
                    reused=True,
                )
                raise SystemExit(0)

    write_state("queued", downloaded_bytes=0, total_bytes=None, percent=None)
    request = Request(download_url, headers={"User-Agent": "AiDN-model-prefetch/1"})
    digest = hashlib.sha256()
    downloaded = 0
    next_update = 0.0
    with urlopen(request, timeout=45) as response, temporary.open("wb") as output:
        raw_total = response.headers.get("Content-Length")
        total = int(raw_total) if raw_total and raw_total.isdigit() else None
        if total is not None and total > max_bytes:
            raise ValueError(f"model artifact exceeds prefetch limit ({max_bytes} bytes)")
        if expected_bytes is not None and total is not None and total != expected_bytes:
            raise ValueError(
                f"pinned artifact size mismatch (expected {expected_bytes}, got {total})"
            )
        existing_target_bytes = target.stat().st_size if target.is_file() else 0
        ensure_disk_space((total or 0) + existing_target_bytes + safety_bytes)
        write_state("running", downloaded_bytes=0, total_bytes=total, percent=0)
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            downloaded += len(chunk)
            if downloaded > max_bytes:
                raise ValueError(f"model artifact exceeds prefetch limit ({max_bytes} bytes)")
            if expected_bytes is not None and downloaded > expected_bytes:
                raise ValueError(
                    f"pinned artifact size mismatch (expected {expected_bytes}, got more than that)"
                )
            output.write(chunk)
            digest.update(chunk)
            output.flush()
            remaining_bytes = max(
                0,
                (expected_bytes if expected_bytes is not None else total or 0)
                - downloaded,
            )
            ensure_disk_space(remaining_bytes + existing_target_bytes + safety_bytes)
            now = time.monotonic()
            if now >= next_update:
                percent = int(downloaded * 100 / total) if total else None
                write_state(
                    "running",
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    percent=percent,
                )
                next_update = now + 0.5
    if downloaded <= 0:
        raise ValueError("model artifact download returned no bytes")
    if expected_bytes is not None and downloaded != expected_bytes:
        raise ValueError(
            f"pinned artifact size mismatch (expected {expected_bytes}, got {downloaded})"
        )
    sha256 = digest.hexdigest()
    if expected_sha256 is not None and sha256 != expected_sha256:
        raise ValueError("pinned artifact SHA-256 mismatch")
    temporary.replace(target)
    os.chmod(target, 0o600)
    write_state(
        "completed",
        downloaded_bytes=downloaded,
        total_bytes=downloaded if total is None else total,
        percent=100,
        sha256=sha256,
    )
except Exception as error:
    try:
        temporary.unlink()
    except OSError:
        pass
    write_state(
        "failed",
        downloaded_bytes=locals().get("downloaded", 0),
        total_bytes=locals().get("total"),
        percent=None,
        error=str(error)[:512],
    )
    raise
PY
  model_prefetch_pid=$!
  model_prefetch_status='running'
  printf '  [model download] started in background for %s\n' "$model_id" >&2
  printf '  [model download] progress: %s\n' "$state_path" >&2
}

prompt_value() {
  local label="$1"
  local default_value="$2"
  local explanation="${3:-}"
  local answer
  if [[ "$non_interactive" == 'true' ]]; then
    printf '%s' "$default_value"
    return
  fi
  model_prefetch_progress
  if [[ -n "$explanation" ]]; then
    printf '\n  %s\n' "$explanation" >&2
  fi
  if [[ -n "$default_value" ]]; then
    printf '%s [%s]: ' "$label" "$default_value" >&2
  else
    printf '%s: ' "$label" >&2
  fi
  IFS= read -r -u 3 answer || die 'interactive wizard requires a terminal'
  if [[ -z "$answer" ]]; then
    answer="$default_value"
  fi
  model_prefetch_progress
  printf '%s' "$answer"
}

prompt_choice() {
  local label="$1"
  local default_value="$2"
  local explanation="${3:-}"
  shift 3
  local options=("$@")
  local answer entry key display detail
  local index=0 default_index=1 selected=''

  if [[ "$non_interactive" == 'true' ]]; then
    printf '%s' "$default_value"
    return
  fi

  model_prefetch_progress
  if [[ -n "$explanation" ]]; then
    printf '\n  %s\n' "$explanation" >&2
  fi
  printf '\n%s\n' "$label" >&2
  for entry in "${options[@]}"; do
    IFS='|' read -r key display detail <<< "$entry"
    index=$((index + 1))
    [[ "$key" == "$default_value" ]] && default_index="$index"
    if [[ "$key" == "$default_value" ]]; then
      printf '  %d) %s [по умолчанию]\n' "$index" "$display" >&2
    else
      printf '  %d) %s\n' "$index" "$display" >&2
    fi
    [[ -n "$detail" ]] && printf '     %s\n' "$detail" >&2
  done
  printf 'Введите номер [%d]: ' "$default_index" >&2
  IFS= read -r -u 3 answer || die 'interactive wizard requires a terminal'
  [[ -n "$answer" ]] || answer="$default_index"

  if [[ "$answer" =~ ^[0-9]+$ ]]; then
    if (( 10#$answer >= 1 && 10#$answer <= ${#options[@]} )); then
      entry="${options[$((10#$answer - 1))]}"
      IFS='|' read -r selected _ <<< "$entry"
    fi
  else
    # Keep accepting the old textual values for operators who have memorized
    # them, while making the numbered path the primary UX.
    local normalized_answer="${answer,,}"
    for entry in "${options[@]}"; do
      IFS='|' read -r key _ <<< "$entry"
      if [[ "${key,,}" == "$normalized_answer" ]]; then
        selected="$key"
        break
      fi
    done
  fi
  [[ -n "$selected" ]] || die "invalid selection for: $label (enter a number from 1 to ${#options[@]})"
  model_prefetch_progress
  printf '%s' "$selected"
}

prompt_yes_no() {
  local label="$1"
  local default_value="$2"
  local explanation="${3:-}"
  local yes_hint="${4:-Подтвердить действие}"
  local no_hint="${5:-Изменить выбор}"
  local answer
  answer="$(prompt_choice "$label" "$default_value" "$explanation" \
    "yes|Да|$yes_hint" \
    "no|Нет|$no_hint")"
  [[ "$answer" == 'yes' ]]
}

wait_for_model_prefetch() {
  if [[ -z "${model_prefetch_pid:-}" ]]; then
    [[ "${model_prefetch_status:-}" == 'completed' && -f "${model_prefetch_target:-}" ]] || return 1
    return 0
  fi
  printf '  [model download] waiting for the selected artifact before starting the Resident Steward\n' >&2
  local exit_status=0
  wait "$model_prefetch_pid" || exit_status=$?
  model_prefetch_pid=''
  if (( exit_status != 0 )); then
    model_prefetch_status='failed'
    printf '  [model download] failed; inspect logs under %s\n' "$data_dir/logs" >&2
    return "$exit_status"
  fi
  local status='unknown'
  if [[ -n "${model_prefetch_state_path:-}" && -f "$model_prefetch_state_path" ]]; then
    status="$($model_prefetch_python - "$model_prefetch_state_path" <<'PY'
import json
import sys

try:
    print(json.loads(open(sys.argv[1], encoding="utf-8").read()).get("status") or "unknown")
except Exception:
    print("unknown")
PY
    )"
  fi
  model_prefetch_status="$status"
  [[ "$status" == 'completed' ]] || {
    printf '  [model download] did not complete (status: %s)\n' "$status" >&2
    return 1
  }
  [[ -f "$model_prefetch_target" ]] || {
    printf '  [model download] completed without a readable target: %s\n' "$model_prefetch_target" >&2
    return 1
  }
}

ensure_assisted_provider_runtime() {
  # Run this only after the model prefetch has been accepted for automatic
  # Resident Steward startup.  The derived flag is deliberately used here
  # instead of re-reading CLI intent so reruns with an existing plan cannot
  # accidentally skip the runtime required by the generated wrapper.
  [[ "${steward_autostart:-false}" == 'true' ]] || return 0
  local runtime_root="$data_dir/providers/llama.cpp"
  if [[ -x "$runtime_root/bin/llama-server" ]]; then
    printf '  [provider runtime] reviewed llama.cpp runtime is already installed\n' >&2
    return 0
  fi
  printf '  [provider runtime] installing reviewed llama.cpp CPU runtime\n' >&2
  "$runtime_dispatcher" llama.cpp install \
    --ref b10433 --backend cpu --root "$runtime_root" \
    || die "the reviewed llama.cpp runtime could not be installed"
  [[ -x "$runtime_root/bin/llama-server" ]] \
    || die "the reviewed llama.cpp runtime install completed without llama-server"
}

model_source_for_id() {
  case "$1" in
    'Qwen/Qwen3-0.6B-GGUF:Q8_0')
      printf '%s' 'hf://Qwen/Qwen3-0.6B-GGUF@23749fefcc72300e3a2ad315e1317431b06b590a/Qwen3-0.6B-Q8_0.gguf' ;;
    'Qwen/Qwen3-1.7B-GGUF:Q4_K_M')
      printf '%s' 'hf://ggml-org/Qwen3-1.7B-GGUF@daeb8e2d528a760970442092f6bf1e55c3b659eb/Qwen3-1.7B-Q4_K_M.gguf' ;;
    'Qwen/Qwen3-4B-GGUF:Q4_K_M')
      printf '%s' 'hf://Qwen/Qwen3-4B-GGUF@bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf' ;;
    'Qwen/Qwen3-8B-GGUF:Q4_K_M')
      printf '%s' 'hf://Qwen/Qwen3-8B-GGUF@7c41481f57cb95916b40956ab2f0b139b296d974/Qwen3-8B-Q4_K_M.gguf' ;;
    'Qwen/Qwen3-14B-GGUF:Q4_K_M')
      printf '%s' 'hf://Qwen/Qwen3-14B-GGUF@530227a7d994db8eca5ab5ced2fb692b614357fd/Qwen3-14B-Q4_K_M.gguf' ;;
    *) return 1 ;;
  esac
}

model_expected_sha256_for_id() {
  case "$1" in
    'Qwen/Qwen3-0.6B-GGUF:Q8_0')
      printf '%s' '9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031' ;;
    'Qwen/Qwen3-1.7B-GGUF:Q4_K_M')
      printf '%s' 'd2387ca2dbfee2ffabce7120d3770dadca0b293052bc2f0e138fdc940d9bc7b5' ;;
    'Qwen/Qwen3-4B-GGUF:Q4_K_M')
      printf '%s' '7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5' ;;
    'Qwen/Qwen3-8B-GGUF:Q4_K_M')
      printf '%s' 'd98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785' ;;
    'Qwen/Qwen3-14B-GGUF:Q4_K_M')
      printf '%s' '500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0' ;;
    *) return 1 ;;
  esac
}

model_expected_size_bytes_for_id() {
  case "$1" in
    'Qwen/Qwen3-0.6B-GGUF:Q8_0') printf '%s' '639446688' ;;
    'Qwen/Qwen3-1.7B-GGUF:Q4_K_M') printf '%s' '1282439264' ;;
    'Qwen/Qwen3-4B-GGUF:Q4_K_M') printf '%s' '2497280256' ;;
    'Qwen/Qwen3-8B-GGUF:Q4_K_M') printf '%s' '5027783488' ;;
    'Qwen/Qwen3-14B-GGUF:Q4_K_M') printf '%s' '9001752960' ;;
    *) return 1 ;;
  esac
}

detect_assisted_model_id() {
  local ram_mb=0
  local vram_mb=0
  if [[ -r /proc/meminfo ]]; then
    ram_mb="$(awk '/^MemTotal:/ { print int($2 / 1024); exit }' /proc/meminfo 2>/dev/null || printf '0')"
  fi
  if command -v nvidia-smi >/dev/null 2>&1; then
    vram_mb="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | sort -nr | head -n 1 | tr -dc '0-9' || true)"
  fi
  [[ "$ram_mb" =~ ^[0-9]+$ ]] || ram_mb=0
  [[ "$vram_mb" =~ ^[0-9]+$ ]] || vram_mb=0

  if (( vram_mb >= 12000 && ram_mb >= 20000 )); then
    printf '%s' 'Qwen/Qwen3-14B-GGUF:Q4_K_M'
  elif (( vram_mb >= 7000 && ram_mb >= 12000 )); then
    printf '%s' 'Qwen/Qwen3-8B-GGUF:Q4_K_M'
  elif (( (vram_mb >= 4000 && ram_mb >= 8000) || ram_mb >= 14000 )); then
    printf '%s' 'Qwen/Qwen3-4B-GGUF:Q4_K_M'
  elif (( ram_mb >= 6000 )); then
    printf '%s' 'Qwen/Qwen3-1.7B-GGUF:Q4_K_M'
  else
    printf '%s' 'Qwen/Qwen3-0.6B-GGUF:Q8_0'
  fi
}

valid_model_id() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}$ && "$1" != *".."* ]]
}

valid_model_source() {
  local source="$1"
  [[ -n "$source" && ${#source} -le 2048 ]] || return 1
  [[ "$source" != *"?"* && "$source" != *"#"* ]] || return 1
  if [[ "$source" == hf://* ]]; then
    [[ "$source" =~ ^hf://[^/@[:space:]]+/[^/@[:space:]]+(@[0-9a-fA-F]{40})?(/[^[:space:]]+)?$ ]]
    return
  fi
  [[ "$source" != *"@"* ]] || return 1
  [[ "$source" =~ ^https://[^[:space:]/]+(/[^[:space:]]*)?$ ]]
}

shell_quote() {
  printf '%q' "$1"
}

operator_id=''
peer_id=''
control_group_id=''
ref='main'
install_dir=''
data_dir=''
api_host='127.0.0.1'
api_port='8766'
allow_public_api='false'
api_host_supplied='false'
enable_registry='false'
registry_listen_host=''
registry_listen_host_supplied='false'
registry_port='9444'
advertise_host=''
network_id='aidn'
chain_id='aidn-testnet-1'
network_revision='1.0'
consensus_mode='validator'
consensus_rpc=''
cometbft_version='v0.38.19'
no_start='false'
non_interactive='false'
wallet_action=''
dashboard_pairing_action=''
agent_action=''
setup_mode='manual'
setup_provider='skip'
setup_model_id='skip'
setup_model_source=''
setup_endpoint_action='skip'
setup_handoff='dashboard'
model_prefetch_pid=''
model_prefetch_state_path=''
model_prefetch_target=''
model_prefetch_source=''
model_prefetch_python=''
model_prefetch_status='not_started'
model_prefetch_expected_sha256=''
model_prefetch_expected_bytes=''
steward_autostart='false'
steward_model_path=''
steward_model_sha256=''
checkout_backup_path=''
operator_id_supplied='false'
enable_registry_supplied='false'
consensus_mode_supplied='false'
consensus_rpc_supplied='false'
wallet_action_supplied='false'
dashboard_pairing_supplied='false'
agent_action_supplied='false'
setup_mode_supplied='false'
setup_provider_supplied='false'
setup_model_id_supplied='false'
setup_model_source_supplied='false'
setup_endpoint_supplied='false'
setup_handoff_supplied='false'
recommended_defaults='false'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --operator-id|--node-name)
      require_value "$1" "$@"
      operator_id="$2"
      operator_id_supplied='true'
      shift 2
      ;;
    --peer-id)
      require_value "$1" "$@"
      peer_id="$2"
      shift 2
      ;;
    --control-group-id)
      require_value "$1" "$@"
      control_group_id="$2"
      shift 2
      ;;
    --ref)
      require_value "$1" "$@"
      ref="$2"
      shift 2
      ;;
    --install-dir)
      require_value "$1" "$@"
      install_dir="$2"
      shift 2
      ;;
    --data-dir)
      require_value "$1" "$@"
      data_dir="$2"
      shift 2
      ;;
    --api-host)
      require_value "$1" "$@"
      api_host="$2"
      api_host_supplied='true'
      shift 2
      ;;
    --api-port)
      require_value "$1" "$@"
      api_port="$2"
      shift 2
      ;;
    --allow-public-api)
      allow_public_api='true'
      shift
      ;;
    --enable-registry)
      enable_registry='true'
      enable_registry_supplied='true'
      shift
      ;;
    --registry-listen-host)
      require_value "$1" "$@"
      registry_listen_host="$2"
      registry_listen_host_supplied='true'
      shift 2
      ;;
    --registry-port)
      require_value "$1" "$@"
      registry_port="$2"
      shift 2
      ;;
    --advertise-host)
      require_value "$1" "$@"
      advertise_host="$2"
      shift 2
      ;;
    --network-id)
      require_value "$1" "$@"
      network_id="$2"
      shift 2
      ;;
    --chain-id)
      require_value "$1" "$@"
      chain_id="$2"
      shift 2
      ;;
    --network-revision)
      require_value "$1" "$@"
      network_revision="$2"
      shift 2
      ;;
    --consensus-mode)
      require_value "$1" "$@"
      consensus_mode="$2"
      consensus_mode_supplied='true'
      shift 2
      ;;
    --consensus-rpc)
      require_value "$1" "$@"
      consensus_rpc="$2"
      consensus_rpc_supplied='true'
      shift 2
      ;;
    --cometbft-version)
      require_value "$1" "$@"
      cometbft_version="$2"
      shift 2
      ;;
    --no-consensus)
      consensus_mode='disabled'
      consensus_mode_supplied='true'
      shift
      ;;
    --no-start)
      no_start='true'
      shift
      ;;
    --wallet-action)
      require_value "$1" "$@"
      wallet_action="$2"
      wallet_action_supplied='true'
      shift 2
      ;;
    --dashboard-pairing)
      require_value "$1" "$@"
      dashboard_pairing_action="$2"
      dashboard_pairing_supplied='true'
      shift 2
      ;;
    --agent-action)
      require_value "$1" "$@"
      agent_action="$2"
      agent_action_supplied='true'
      shift 2
      ;;
    --setup-mode)
      require_value "$1" "$@"
      setup_mode="$2"
      setup_mode_supplied='true'
      shift 2
      ;;
    --setup-provider)
      require_value "$1" "$@"
      setup_provider="$2"
      setup_provider_supplied='true'
      shift 2
      ;;
    --setup-model)
      require_value "$1" "$@"
      setup_model_id="$2"
      setup_model_id_supplied='true'
      shift 2
      ;;
    --setup-model-source)
      require_value "$1" "$@"
      setup_model_source="$2"
      setup_model_source_supplied='true'
      shift 2
      ;;
    --setup-endpoint)
      require_value "$1" "$@"
      setup_endpoint_action="$2"
      setup_endpoint_supplied='true'
      shift 2
      ;;
    --setup-handoff)
      require_value "$1" "$@"
      setup_handoff="$2"
      setup_handoff_supplied='true'
      shift 2
      ;;
    --non-interactive)
      non_interactive='true'
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$non_interactive" != 'true' ]]; then
  [[ -r /dev/tty ]] || die 'interactive mode requires /dev/tty; use --non-interactive with explicit flags'
  exec 3</dev/tty
fi

if [[ "$setup_mode_supplied" != 'true' && "$non_interactive" != 'true' ]]; then
  setup_mode="$(prompt_choice 'Installation mode (manual/ai_assisted)' 'manual' 'Manual reviews every setting. AI-assisted detects a conservative llama.cpp model, shows one complete recommended profile, and stages a bounded plan for the local Resident Steward.' \
    'manual|Ручной режим|После базовой установки дальнейшие действия остаются у оператора' \
    'ai_assisted|AI-assisted|Показать один безопасный профиль, автоматически выбрать локальную модель и продолжить в Dashboard')"
fi
case "${setup_mode,,}" in
  manual) setup_mode='manual' ;;
  ai|ai_assisted) setup_mode='ai_assisted' ;;
  *) die 'setup mode must be manual or ai_assisted' ;;
esac
if [[ "$setup_mode" == 'manual' && ( "$setup_provider_supplied" == 'true' || "$setup_model_id_supplied" == 'true' || "$setup_model_source_supplied" == 'true' || "$setup_endpoint_supplied" == 'true' || "$setup_handoff_supplied" == 'true' ) ]]; then
  die 'AI-assisted setup flags require --setup-mode ai_assisted'
fi

if [[ "$setup_mode" == 'ai_assisted' ]]; then
  if [[ "$setup_provider_supplied" != 'true' ]]; then
    setup_provider='llama.cpp'
  fi
  if [[ "$setup_model_id_supplied" != 'true' ]]; then
    setup_model_id="$(detect_assisted_model_id)"
  fi
  if [[ "$setup_model_source_supplied" != 'true' && -z "$setup_model_source" ]]; then
    setup_model_source="$(model_source_for_id "$setup_model_id" || true)"
  fi
  if [[ "$setup_endpoint_supplied" != 'true' ]]; then
    setup_endpoint_action='draft'
  fi
  if [[ "$setup_handoff_supplied" != 'true' ]]; then
    setup_handoff='dashboard'
  fi
fi

if [[ "$setup_mode" == 'ai_assisted' && "$non_interactive" != 'true' ]]; then
  recommended_operator_id="${operator_id:-$(sanitize_hostname)}"
  recommended_install_dir="${install_dir:-$HOME/aidn/$recommended_operator_id/AiDN}"
  recommended_data_dir="${data_dir:-$HOME/.local/share/aidn/$recommended_operator_id}"
  recommended_wallet_action="${wallet_action:-create}"
  recommended_pairing_action="${dashboard_pairing_action:-code}"
  printf '\nRecommended assisted setup\n' >&2
  printf '  Node name       : %s\n' "$recommended_operator_id" >&2
  printf '  Install path    : %s\n' "$recommended_install_dir" >&2
  printf '  Data path       : %s\n' "$recommended_data_dir" >&2
  printf '  Consensus       : %s\n' "$consensus_mode" >&2
  printf '  Wallet          : %s in protected local storage\n' "$recommended_wallet_action" >&2
  printf '  Dashboard       : %s one-time pairing code; bind %s:%s\n' "$recommended_pairing_action" "$api_host" "$api_port" >&2
  printf '  Registry        : %s\n' "$enable_registry" >&2
  printf '  Resident AI     : %s · %s\n' "$setup_provider" "$setup_model_id" >&2
  printf '  Handoff         : Dashboard with Resident Steward\n\n' >&2
  if prompt_yes_no 'Install with these recommended settings?' 'yes' 'Yes applies the complete safe local profile shown above. Choose no to review every node, path, consensus, wallet, port, and network setting individually.' \
    'Установить профиль' 'Перейти к ручной настройке'; then
    recommended_defaults='true'
    operator_id="$recommended_operator_id"
    install_dir="$recommended_install_dir"
    data_dir="$recommended_data_dir"
    [[ "$consensus_mode_supplied" == 'true' ]] || consensus_mode='validator'
    consensus_mode_supplied='true'
    [[ "$wallet_action_supplied" == 'true' ]] || wallet_action='create'
    wallet_action_supplied='true'
    [[ "$dashboard_pairing_supplied" == 'true' ]] || dashboard_pairing_action='code'
    dashboard_pairing_supplied='true'
    [[ "$agent_action_supplied" == 'true' ]] || agent_action='guide'
    agent_action_supplied='true'
    [[ "$api_host_supplied" == 'true' ]] || api_host='127.0.0.1'
    [[ "$enable_registry_supplied" == 'true' ]] || enable_registry='false'
    enable_registry_supplied='true'
  fi
fi

if [[ -z "$operator_id" ]]; then
  operator_id="$(prompt_value 'Operator/node name' "$(sanitize_hostname)" 'This becomes the stable identity of the node and its local service. Changing it later can require re-registration and can separate the node from persisted network state.')"
fi
valid_identifier "$operator_id" || die 'operator ID contains unsupported characters'
[[ -n "$peer_id" ]] || peer_id="$operator_id"
valid_identifier "$peer_id" || die 'peer ID contains unsupported characters'
[[ -n "$control_group_id" ]] || control_group_id="control-group-$operator_id"
valid_identifier "$control_group_id" || die 'control group ID contains unsupported characters'
case "$consensus_mode" in
  validator|non_validator|disabled) ;;
  *) die 'consensus mode must be validator, non_validator, or disabled' ;;
esac

[[ "$cometbft_version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die 'CometBFT version must look like v0.38.19'

default_install_dir="$HOME/aidn/$operator_id/AiDN"
default_data_dir="$HOME/.local/share/aidn/$operator_id"
if [[ -z "$install_dir" ]]; then
  install_dir="$(prompt_value 'AiDN checkout path' "$default_install_dir" 'This is where the reviewed AiDN source and virtual environment will be installed. Choosing another path uses a different checkout, while the persistent state remains in the data directory below.')"
fi
if [[ -z "$data_dir" ]]; then
  data_dir="$(prompt_value 'Persistent data path' "$default_data_dir" 'This directory stores node state, bundles, wallet metadata, and encrypted secrets. Keep it on durable storage with restricted permissions and include it in your backup plan; do not use a temporary directory.')"
fi
valid_path "$install_dir" || die 'install directory must be an absolute path'
valid_path "$data_dir" || die 'data directory must be an absolute path'

if [[ "$non_interactive" != 'true' && "$consensus_mode_supplied" != 'true' ]]; then
  consensus_mode="$(prompt_choice 'Consensus mode (validator/non_validator/disabled)' "$consensus_mode" 'This controls whether the node participates in CometBFT consensus. Validator uses local ports and storage; non-validator follows a trusted private RPC; disabled skips local consensus integration.' \
    'validator|Validator|Запустить локальный CometBFT и участвовать в консенсусе' \
    'non_validator|Non-validator|Подключиться к существующему приватному RPC без локального валидатора' \
    'disabled|Disabled|Не устанавливать локальную consensus-службу')"
fi
case "$consensus_mode" in
  validator|non_validator|disabled) ;;
  *) die 'consensus mode must be validator, non_validator, or disabled' ;;
esac

if [[ "$consensus_mode" == 'non_validator' ]]; then
  if [[ -z "$consensus_rpc" && "$non_interactive" != 'true' ]]; then
    consensus_rpc="$(prompt_value 'Source CometBFT RPC (private HTTP URL)' '' 'This is the CometBFT RPC that a non-validator follows for network state. It must be reachable from this host and kept on a trusted network; this mode does not run a local validator.')"
  fi
  [[ -n "$consensus_rpc" ]] || die 'non_validator mode requires --consensus-rpc or an interactive source RPC'
  valid_consensus_rpc "$consensus_rpc" || die 'source CometBFT RPC must be an HTTP(S) host:port URL'
fi

if [[ "$wallet_action_supplied" != 'true' ]]; then
  if [[ "$non_interactive" == 'true' ]]; then
    wallet_action='skip'
  else
    wallet_action="$(prompt_choice 'Owner wallet action (create/import/skip)' 'create' 'The wallet signs ownership and publication actions. Create makes a new encrypted local wallet; import uses an existing key; skip leaves ownership-dependent actions unavailable.' \
      'create|Создать кошелёк|Сгенерировать новый локальный кошелёк в зашифрованном хранилище' \
      'import|Импортировать|Использовать уже существующий приватный ключ' \
      'skip|Пропустить|Оставить публикацию и операции владельца недоступными')"
  fi
fi
case "$wallet_action" in
  create|import|skip) ;;
  *) die 'wallet action must be create, import, or skip' ;;
esac

if [[ "$dashboard_pairing_supplied" != 'true' ]]; then
  if [[ "$non_interactive" == 'true' ]]; then
    dashboard_pairing_action='skip'
  else
    dashboard_pairing_action="$(prompt_choice 'Dashboard browser binding (code/first_browser/skip)' 'code' 'Choose how the owner browser is bound after installation. A code is safest; the one-hour first-browser window is only for a trusted LAN and still requires an explicit confirmation in the Dashboard.' \
      'code|Код из CLI|Показать одноразовый URL и код после установки' \
      'first_browser|Первый доверенный браузер|Открыть окно на один час: в Dashboard нужно явно нажать привязку этого браузера' \
      'skip|Позже|Оставить Dashboard непарным до ручного запуска aidn-operator pair')"
  fi
fi
case "$dashboard_pairing_action" in
  code|first_browser|skip) ;;
  *) die 'dashboard pairing action must be code, first_browser, or skip' ;;
esac

if [[ "$agent_action_supplied" != 'true' ]]; then
  if [[ "$non_interactive" == 'true' ]]; then
    agent_action='skip'
  else
    agent_action='guide'
  fi
fi
case "$agent_action" in
  guide|skip) ;;
  *) die 'agent action must be guide or skip' ;;
esac

if [[ "$non_interactive" != 'true' && "$recommended_defaults" != 'true' ]]; then
  if [[ "$api_host_supplied" == 'true' ]]; then
    api_host="$(prompt_value 'Hypervisor API bind address' "$api_host" 'Loopback limits the dashboard and API to this machine; a LAN address makes them reachable by other devices. A non-loopback bind needs a trusted network, firewall rules, and an explicit unauthenticated-API risk decision.')"
  elif prompt_yes_no 'Expose Dashboard/API to the LAN on 0.0.0.0?' 'no' 'No keeps the service on loopback and blocks remote browsers; yes binds all interfaces so LAN devices can connect. The current bootstrap API has no public authentication boundary, so never expose this directly to the Internet.' \
    'Открыть доступ в LAN' 'Оставить loopback'; then
    api_host='0.0.0.0'
    allow_public_api='true'
  else
    api_host='127.0.0.1'
  fi
  api_port="$(prompt_value 'Hypervisor API port' "$api_port" 'This port is used by the Hypervisor API and dashboard URL. It must be free on this host and allowed by the local firewall if the API is reachable from the LAN; changing it also changes agent and browser connection URLs.')"
fi
valid_port "$api_port" || die 'API port must be between 1 and 65535'
[[ -n "$api_host" && "$api_host" != *[[:space:]]* ]] || die 'API bind address is invalid'
if ! is_loopback_host "$api_host" && [[ "$allow_public_api" != 'true' ]]; then
  if [[ "$non_interactive" == 'true' ]]; then
    die 'non-loopback API requires --allow-public-api because the MVP API has no public auth boundary'
  fi
  prompt_yes_no 'The API is unauthenticated; allow a non-loopback bind?' 'no' 'Approving this permits unauthenticated HTTP access from the selected network. Rejecting it keeps the service loopback-only; if you approve, restrict the network and firewall immediately.' \
    'Разрешить bind' 'Отменить доступ' || die 'public API bind was not approved'
  allow_public_api='true'
fi

if [[ "$enable_registry_supplied" != 'true' ]]; then
  if [[ "$non_interactive" != 'true' ]]; then
    if prompt_yes_no 'Enable the mTLS Registry listener for peer onboarding?' 'no' 'Enable this only when the node must exchange signed peer bundles with other operators. It opens a separate listener and still requires mutual peer approval; disabling it keeps this node local and avoids an additional network surface.' \
      'Включить listener' 'Оставить listener выключенным'; then
      enable_registry='true'
    fi
  fi
fi
if [[ "$enable_registry" == 'true' ]]; then
  [[ -n "$registry_listen_host" ]] || registry_listen_host='0.0.0.0'
  if [[ "$non_interactive" != 'true' && "$registry_listen_host_supplied" != 'true' ]]; then
    registry_listen_host="$(prompt_value 'Registry listener bind address' "$registry_listen_host" 'This controls which interfaces accept mTLS peer onboarding traffic. Binding all interfaces increases reachability and firewall responsibility; loopback is suitable only for local testing.')"
    registry_port="$(prompt_value 'Registry mTLS port' "$registry_port" 'This separate port is used for peer discovery and signed bundle exchange. It must not conflict with the Hypervisor API and must be allowed only on the intended peer network.')"
  fi
else
  registry_listen_host='127.0.0.1'
fi
valid_port "$registry_port" || die 'Registry port must be between 1 and 65535'
if [[ "$enable_registry" == 'true' && "$registry_port" == "$api_port" ]]; then
  die 'API and Registry ports must differ when both services run on one host'
fi
if [[ -z "$advertise_host" ]]; then
  advertise_host="$(detect_advertise_host)"
fi
[[ -n "$registry_listen_host" && "$registry_listen_host" != *[[:space:]]* ]] || die 'Registry bind address is invalid'
[[ -n "$advertise_host" && "$advertise_host" != *[[:space:]]* ]] || die 'advertise host is invalid'

if [[ "$setup_mode" == 'ai_assisted' ]]; then
  setup_provider="${setup_provider,,}"
  case "$setup_provider" in
    skip|ollama|llama.cpp|vllm) ;;
    *) die 'setup provider must be skip, ollama, llama.cpp, or vllm' ;;
  esac
  if [[ "$setup_provider" == 'skip' && ( "$setup_model_id_supplied" == 'true' || "$setup_model_source_supplied" == 'true' || "$setup_endpoint_supplied" == 'true' ) ]]; then
    die 'setup model and endpoint flags require a selected setup provider'
  fi

  if [[ "$setup_provider" != 'skip' ]]; then
    if [[ -z "$setup_model_id" ]]; then
      setup_model_id='skip'
    fi
    if [[ "$setup_model_id" != 'skip' ]]; then
      valid_model_id "$setup_model_id" || die 'setup model ID contains unsupported characters'
      valid_model_source "$setup_model_source" || die 'setup model source must be an HTTPS URL or hf://owner/repository[@40-hex-revision] reference without credentials or query data'
      # Selecting a concrete llama.cpp artifact is the explicit operator
      # approval for the reviewed runtime and model preparation. Bundle and
      # Endpoint lifecycle remains separate and still requires review.
      start_model_prefetch "$setup_provider" "$setup_model_id" "$setup_model_source"
    else
      setup_model_source=''
      setup_endpoint_action='skip'
    fi
  else
    setup_model_id='skip'
    setup_model_source=''
    setup_endpoint_action='skip'
  fi

  if [[ "$setup_model_id" != 'skip' ]]; then
    setup_endpoint_action="${setup_endpoint_action,,}"
    case "$setup_endpoint_action" in
      skip|draft|start) ;;
      *) die 'setup endpoint action must be skip, draft, or start' ;;
    esac
  fi

  setup_handoff="${setup_handoff,,}"
  case "$setup_handoff" in
    continue|dashboard) ;;
    *) die 'setup handoff must be continue or dashboard' ;;
  esac
else
  setup_provider='skip'
  setup_model_id='skip'
  setup_model_source=''
  setup_endpoint_action='skip'
  setup_handoff='dashboard'
fi

if [[ "$EUID" -eq 0 ]]; then
  sudo_cmd=()
else
  sudo_cmd=(sudo)
  "${sudo_cmd[@]}" -v
fi

echo "Installing AiDN operator '$operator_id' from ref '$ref'" >&2
"${sudo_cmd[@]}" apt-get update
"${sudo_cmd[@]}" apt-get install -y --no-install-recommends ca-certificates curl git python3 python3-venv xz-utils

export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh
fi
uv_bin="$(command -v uv || true)"
[[ -n "$uv_bin" ]] || die 'uv installation did not produce an executable'

if [[ -e "$install_dir" && ! -d "$install_dir/.git" ]]; then
  die "install directory exists but is not an AiDN checkout: $install_dir"
fi
checkout_replaced='false'
if [[ -d "$install_dir/.git" ]]; then
  clean_generated_dashboard_assets "$install_dir"
  if ! checkout_is_clean "$install_dir"; then
    replace_dirty_checkout "$install_dir"
    checkout_replaced='true'
  fi
fi
if [[ "$checkout_replaced" == 'true' ]]; then
  :
elif [[ -d "$install_dir/.git" ]]; then
  git -C "$install_dir" fetch --depth 1 origin "$ref"
  git -C "$install_dir" checkout --detach FETCH_HEAD
else
  clone_reviewed_checkout "$install_dir"
fi
commit="$(git -C "$install_dir" rev-parse HEAD)"
"$uv_bin" --directory "$install_dir" sync --all-extras --frozen

# Install the reviewed Provider runtime dispatcher and its root-owned broker.
# The Hypervisor talks to the broker over a UID-restricted Unix socket; it
# never receives sudo, shell, or generic subprocess capability itself.
runtime_broker_root='/usr/libexec/aidn-provider-runtime'
runtime_dispatcher="$runtime_broker_root/aidn-provider-runtime-ubuntu.sh"
runtime_broker_script="$runtime_broker_root/aidn-provider-runtime-broker.py"
runtime_broker_service='aidn-provider-runtime-broker.service'
operator_uid="$(id -u "$USER")"
operator_gid="$(id -g "$USER")"
runtime_broker_socket="@aidn-provider-runtime-$operator_uid"
"${sudo_cmd[@]}" install -d -o root -g root -m 0755 "$runtime_broker_root"
for runtime_file in \
  aidn-provider-runtime-ubuntu.sh \
  aidn-whisper-runtime-ubuntu.sh \
  aidn-ollama-runtime-ubuntu.sh \
  aidn-llamacpp-runtime-ubuntu.sh \
  aidn-vllm-runtime-ubuntu.sh \
  aidn-consensus-runtime-ubuntu.sh \
  install-cometbft-ubuntu.sh \
  aidn-provider-runtime-broker.py; do
  [[ -f "$install_dir/tools/$runtime_file" ]] || die "runtime broker file is missing: $install_dir/tools/$runtime_file"
  "${sudo_cmd[@]}" install -o root -g root -m 0755 \
    "$install_dir/tools/$runtime_file" "$runtime_broker_root/$runtime_file"
done
runtime_unit_tmp="$(mktemp)"
cat > "$runtime_unit_tmp" <<EOF
[Unit]
Description=AiDN root-owned Provider runtime broker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 $runtime_broker_script --socket $runtime_broker_socket --dispatcher $runtime_dispatcher --allowed-uid $operator_uid --allowed-gid $operator_gid --operator-home $HOME --operator-name $USER
Restart=always
RestartSec=2
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF
"${sudo_cmd[@]}" install -o root -g root -m 0644 "$runtime_unit_tmp" "/etc/systemd/system/$runtime_broker_service"
rm -f "$runtime_unit_tmp"
if [[ "$no_start" != 'true' ]]; then
  "${sudo_cmd[@]}" systemctl daemon-reload
  "${sudo_cmd[@]}" systemctl enable --now "$runtime_broker_service"
fi

node_root="$(bash "$install_dir/tools/install-node-runtime-ubuntu.sh" \
  --output-dir "$data_dir/tooling/node")"
bash "$install_dir/tools/build-operator-dashboard.sh" \
  --project-root "$install_dir" --node-root "$node_root" \
  --tooling-dir "$data_dir/tooling" >/dev/null

mkdir -p "$data_dir"
chmod 700 "$data_dir"
operator_kit="$data_dir/operator-kit"
if [[ ! -f "$operator_kit/README.md" ]]; then
  "$uv_bin" --directory "$install_dir" run python tools/prepare-independent-operator-kit.py init \
    --output "$operator_kit" --peer-id "$peer_id" \
    --network-id "$network_id" --chain-id "$chain_id" \
    --network-revision "$network_revision"
fi

identity_root="$data_dir/operator-identity"
identity_result="$("$uv_bin" --directory "$install_dir" run python tools/prepare-operator-identity.py init \
  --root "$identity_root" --operator-id "$operator_id" --peer-id "$peer_id" \
  --control-group-id "$control_group_id" --host "$advertise_host" \
  --network-id "$network_id" --chain-id "$chain_id" \
  --network-revision "$network_revision")"
python_bin="$install_dir/.venv/bin/python"
[[ -x "$python_bin" ]] || die "prepared venv is missing: $python_bin"
resource_capacity_path="$data_dir/resource-capacity.json"
"$python_bin" -m aidn_hypervisor.resource_probe \
  --output "$resource_capacity_path" \
  --source operator-bootstrap >/dev/null
chmod 600 "$resource_capacity_path"

consensus_service_name=''
consensus_home=''
consensus_binary_path=''
consensus_rpc_host='127.0.0.1'
consensus_rpc_port='26657'
consensus_rpc_endpoint=''
consensus_transport='disabled'
consensus_abci_host='127.0.0.1'
consensus_abci_port='26658'
if [[ "$consensus_mode" == 'validator' ]]; then
  consensus_transport='local'
  consensus_service_name="aidn-cometbft-$operator_id.service"
  consensus_home="$data_dir/consensus/cometbft"
  consensus_binary_path="$data_dir/consensus/bin/cometbft"
  [[ -x "$install_dir/tools/install-cometbft-ubuntu.sh" || -f "$install_dir/tools/install-cometbft-ubuntu.sh" ]] || {
    die "CometBFT installer is missing from checkout: $install_dir/tools/install-cometbft-ubuntu.sh"
  }
  consensus_abci_args=()
  if [[ "$consensus_mode" == 'non_validator' ]]; then
    consensus_abci_args=(--no-abci)
  fi
  bash "$install_dir/tools/install-cometbft-ubuntu.sh" \
    --version "$cometbft_version" \
    --home "$consensus_home" \
    --binary-path "$consensus_binary_path" \
    --service-name "$consensus_service_name" \
    --chain-id "$chain_id" \
    --moniker "$operator_id" \
    --rpc-host "$consensus_rpc_host" \
    --rpc-port "$consensus_rpc_port" \
    --p2p-host '127.0.0.1' \
    --p2p-port '26656' \
    --abci-host "$consensus_abci_host" \
    --abci-port "$consensus_abci_port" \
    "${consensus_abci_args[@]}" \
    --no-start >/dev/null
elif [[ "$consensus_mode" == 'non_validator' ]]; then
  consensus_transport='external_rpc'
  consensus_rpc_endpoint="$consensus_rpc"
fi
operator_public_key="$($python_bin - "$identity_root/operator-identity.json" <<'PY'
import json
import sys

print(json.loads(open(sys.argv[1], encoding="utf-8").read())["operator_public_key"])
PY
)"

registry_root="$data_dir/registry-replication"
registry_config="$registry_root/registry-replication.json"
if [[ ! -f "$registry_config" ]]; then
  "$uv_bin" --directory "$install_dir" run python tools/prepare-registry-replication-identity.py init \
    --root "$registry_root" --peer-id "$peer_id" --host "$advertise_host" \
    --listen-host "$registry_listen_host" --port "$registry_port" \
    --network-id "$network_id" --chain-id "$chain_id" \
    --network-revision "$network_revision"
else
  existing_peer="$($python_bin - "$registry_config" <<'PY'
import json
import sys

print(json.loads(open(sys.argv[1], encoding="utf-8").read())["local_peer_id"])
PY
)"
  [[ "$existing_peer" == "$peer_id" ]] || die "existing Registry identity belongs to peer '$existing_peer', not '$peer_id'"
  "$uv_bin" --directory "$install_dir" run python tools/prepare-registry-replication-identity.py update-listener \
    --root "$registry_root" --listen-host "$registry_listen_host" --port "$registry_port"
fi

if [[ "$setup_mode" == 'ai_assisted' && "$setup_provider" == 'llama.cpp' && "$setup_model_id" != 'skip' ]]; then
  wait_for_model_prefetch || die "the selected Resident Steward model was not downloaded successfully"
  [[ "$model_prefetch_status" == 'completed' && -f "$model_prefetch_target" ]] || die "the selected Resident Steward model is not ready at $model_prefetch_target"
  steward_autostart='true'
  steward_model_path="$model_prefetch_target"
  steward_model_sha256="$model_prefetch_expected_sha256"
fi

# The model artifact and its integrity are now confirmed.  Install the exact
# reviewed runtime before writing the wrapper so a fresh service restart can
# autostart the Resident Steward immediately after the CLI exits.
ensure_assisted_provider_runtime

mkdir -p "$data_dir/logs" "$HOME/.config/systemd/user"
chmod 700 "$data_dir/logs" "$HOME/.config/systemd" "$HOME/.config/systemd/user"
bind_host_path="$data_dir/hypervisor-bind-host"
printf '%s\n' "$api_host" > "$bind_host_path"
chmod 600 "$bind_host_path"
wrapper="$data_dir/run-hypervisor.sh"
repo_q="$(shell_quote "$install_dir")"
data_q="$(shell_quote "$data_dir")"
registry_q="$(shell_quote "$registry_config")"
python_q="$(shell_quote "$python_bin")"
uv_q="$(shell_quote "$uv_bin")"
bind_host_q="$(shell_quote "$bind_host_path")"
api_host_q="$(shell_quote "$api_host")"
api_port_q="$(shell_quote "$api_port")"
setup_mode_q="$(shell_quote "$setup_mode")"
setup_plan_path="$data_dir/installation-plan.json"
setup_plan_q="$(shell_quote "$setup_plan_path")"
operator_config_path="$data_dir/operator-config.toml"
operator_config_q="$(shell_quote "$operator_config_path")"
steward_model_path_q="$(shell_quote "$steward_model_path")"
steward_model_sha256_q="$(shell_quote "$steward_model_sha256")"
node_root_q="$(shell_quote "$node_root")"
cat > "$wrapper" <<EOF
#!/usr/bin/env bash
set -euo pipefail
repo=$repo_q
data=$data_q
registry_config=$registry_q
python_bin=$python_q
bind_host_path=$bind_host_q
config_path=${operator_config_q:-$data_q/operator-config.toml}
api_host=$api_host_q
if [[ -f "\$bind_host_path" ]]; then
  configured_host="\$(tr -d '\r\n' < "\$bind_host_path")"
  case "\$configured_host" in
    127.0.0.1|0.0.0.0) api_host="\$configured_host" ;;
  esac
fi
export AIDN_HYPERVISOR_STATE_PATH="\$data/hypervisor-state.json"
export AIDN_HYPERVISOR_BUNDLES_PATH="\$data/bundles.json"
export AIDN_HYPERVISOR_MODEL_STORE_PATH="\$data/models"
export AIDN_HYPERVISOR_API_HOST="\$api_host"
export AIDN_HYPERVISOR_API_PORT=$api_port_q
export AIDN_HYPERVISOR_BIND_HOST_PATH="\$bind_host_path"
export AIDN_HYPERVISOR_RESTART_ON_BIND_CHANGE=true
export AIDN_HYPERVISOR_RESTART_ON_CONFIG_CHANGE=true
export AIDN_CONFIG_FILE="\$config_path"
export AIDN_UPDATE_REPOSITORY_URL='https://github.com/glinko/AiDN.git'
export AIDN_UPDATE_REF=$(shell_quote "${ref:-main}")
export AIDN_UPDATE_NODE_ROOT=$node_root_q
export AIDN_UPDATE_TOOLING_DIR="\$data/tooling"
export AIDN_UV_BIN=$(shell_quote "${uv_bin:-uv}")
export AIDN_INSTALLATION_SETUP_MODE=${setup_mode_q:-manual}
export AIDN_INSTALLATION_PLAN_PATH=${setup_plan_q:-}
# The supported bootstrap uses browser pairing over the selected local or
# trusted-LAN HTTP boundary. Provider runtimes remain loopback-only.
export AIDN_DASHBOARD_ACCESS_ALLOW_INSECURE_LAN=true
export AIDN_NODE_ID=$(shell_quote "${operator_id:-main}")
export AIDN_OPERATOR_ID=$(shell_quote "${operator_id:-main}")
export AIDN_RESOURCE_PROBE_MODE=auto
export AIDN_RESOURCE_CAPACITY_PATH="\$data/resource-capacity.json"
export AIDN_SECRET_MANAGER_PATH="\$data/registry-replication/secrets.json"
export AIDN_SECRET_MANAGER_MASTER_KEY="\$(tr -d '\r\n' < "\$data/registry-replication/master-key.b64")"
export AIDN_MCP_REMOTE_ENABLED=true
if [[ "\$AIDN_INSTALLATION_SETUP_MODE" == 'ai_assisted' ]]; then
  # The assisted bootstrap supplies a verified local artifact and opts the
  # Resident Steward into automatic prepare/start. Tool execution and Endpoint
  # publication remain separate, operator-approved lifecycle actions.
  export AIDN_STEWARD_ENABLED=true
  export AIDN_STEWARD_EXECUTION_PROFILE=CPU_RESIDENT
  export AIDN_STEWARD_MODEL_REPO='Qwen/Qwen2.5-0.5B-Instruct-GGUF'
  export AIDN_STEWARD_MODEL_QUANT=Q4_K_M
  export AIDN_STEWARD_RAM_BUDGET_MB=1024
  export AIDN_STEWARD_PROVIDER_TYPE=$(shell_quote "${setup_provider:-llama.cpp}")
  export AIDN_STEWARD_PLUGIN_ID=$(shell_quote "${setup_provider:-llama.cpp}")
  export AIDN_STEWARD_AUTOSTART=$(shell_quote "${steward_autostart:-false}")
  export AIDN_LLAMA_CPP_RUNTIME_ROOT="\$data/providers/llama.cpp"
  if [[ "${steward_autostart:-false}" == 'true' ]]; then
    export AIDN_STEWARD_MODEL_PATH=${steward_model_path_q:-}
    if [[ -n "${steward_model_sha256:-}" ]]; then
      export AIDN_STEWARD_MODEL_SHA256=${steward_model_sha256_q:-}
    fi
  fi
else
  export AIDN_STEWARD_ENABLED=false
  export AIDN_STEWARD_AUTOSTART=false
fi
export AIDN_ENABLE_PROVIDER_RUNTIME_INSTALL=true
export AIDN_PROVIDER_RUNTIME_DISPATCHER=/usr/libexec/aidn-provider-runtime/aidn-provider-runtime-ubuntu.sh
export AIDN_PROVIDER_RUNTIME_BROKER_SOCKET=${runtime_broker_socket:-}
export PYTHONUNBUFFERED=1
EOF
if [[ "$consensus_mode" == 'validator' ]]; then
  cat >> "$wrapper" <<EOF
export AIDN_CONSENSUS_MODE=$(shell_quote "$consensus_mode")
export AIDN_CONSENSUS_NODE_ID=$(shell_quote "$operator_id")
export AIDN_COMETBFT_ENDPOINT=$(shell_quote "tcp://$consensus_rpc_host:$consensus_rpc_port")
export AIDN_COMETBFT_CHAIN_ID=$(shell_quote "$chain_id")
export AIDN_COMETBFT_SERVICE=$(shell_quote "$consensus_service_name")
export AIDN_COMETBFT_ABCI_STATE_PATH="\$data/consensus/abci-state"
export AIDN_COMETBFT_ABCI_HOST=$(shell_quote "$consensus_abci_host")
export AIDN_COMETBFT_ABCI_PORT=$(shell_quote "$consensus_abci_port")
EOF
elif [[ "$consensus_mode" == 'non_validator' ]]; then
  cat >> "$wrapper" <<EOF
export AIDN_CONSENSUS_MODE=non_validator
export AIDN_CONSENSUS_NODE_ID=$(shell_quote "$operator_id")
export AIDN_COMETBFT_ENDPOINT=$(shell_quote "$consensus_rpc_endpoint")
export AIDN_COMETBFT_CHAIN_ID=$(shell_quote "$chain_id")
export AIDN_COMETBFT_SERVICE=''
export AIDN_COMETBFT_ABCI_STATE_PATH=''
EOF
else
  cat >> "$wrapper" <<'EOF'
export AIDN_CONSENSUS_MODE=disabled
EOF
fi
if [[ "$enable_registry" == 'true' ]]; then
  cat >> "$wrapper" <<'EOF'
export AIDN_REGISTRY_REPLICATION_CONFIG="$registry_config"
EOF
fi
cat >> "$wrapper" <<'EOF'
# Materialize the first profile from bootstrap defaults. Later restarts load
# this operator-owned file after the fixed identity/secrets exports above, so
# a Dashboard change is effective without giving the browser shell access.
if [[ ! -f "$AIDN_CONFIG_FILE" ]]; then
  "$python_bin" - "$AIDN_CONFIG_FILE" <<'PY'
import os
import sys
from aidn_hypervisor.config import write_operator_config_from_environment

write_operator_config_from_environment(sys.argv[1], os.environ)
PY
fi
if [[ "${BOOTSTRAP_CONFIG_INIT_ONLY:-false}" == 'true' ]]; then
  exit 0
fi
while IFS=$'\t' read -r -d '' key value; do
  [[ -n "$key" ]] || continue
  export "$key=$value"
done < <("$python_bin" - "$AIDN_CONFIG_FILE" <<'PY'
import sys
from aidn_hypervisor.config import read_operator_config_values

for key, value in sorted(read_operator_config_values(sys.argv[1]).items()):
    print(f"{key}\t{value}", end="\0")
PY
)
api_host="${AIDN_HYPERVISOR_API_HOST:-$api_host}"
api_port="${AIDN_HYPERVISOR_API_PORT:-8766}"
case "$api_host" in
  127.0.0.1|0.0.0.0) ;;
  *) echo "Invalid AIDN_HYPERVISOR_API_HOST in $AIDN_CONFIG_FILE" >&2; exit 64 ;;
esac
if [[ ! "$api_port" =~ ^[0-9]+$ ]] || (( api_port < 1 || api_port > 65535 )); then
  echo "Invalid AIDN_HYPERVISOR_API_PORT in $AIDN_CONFIG_FILE" >&2
  exit 64
fi
export AIDN_HYPERVISOR_API_HOST="$api_host"
export AIDN_HYPERVISOR_API_PORT="$api_port"
printf '%s\n' "$api_host" > "$bind_host_path"
chmod 600 "$bind_host_path"
exec "$python_bin" -m uvicorn aidn_hypervisor.main:build_app --factory --host "$api_host" --port "$api_port"
EOF
chmod 700 "$wrapper"
# Materialize the operator profile before starting (or reusing) a service.
# Reruns may find an already-active unit, in which case systemd would not
# execute the wrapper's normal startup path before the bootstrap invokes the
# local operator CLI.
BOOTSTRAP_CONFIG_INIT_ONLY=true "$wrapper"

operator_cli_wrapper="$data_dir/aidn-operator-wrapper.sh"
dashboard_url_host="$advertise_host"
if is_loopback_host "$api_host"; then
  dashboard_url_host='127.0.0.1'
fi
if [[ "$dashboard_url_host" == *:* && "$dashboard_url_host" != \[*\] ]]; then
  dashboard_url_host="[$dashboard_url_host]"
fi
dashboard_url="http://$dashboard_url_host:$api_port/operators/dashboard/react#settings"
operator_api_host="$api_host"
if [[ "$operator_api_host" == '0.0.0.0' || "$operator_api_host" == '::' ]]; then
  operator_api_host='127.0.0.1'
fi
operator_api_url_host="$operator_api_host"
if [[ "$operator_api_url_host" == *:* && "$operator_api_url_host" != \[*\] ]]; then
  operator_api_url_host="[$operator_api_url_host]"
fi
operator_api_url="http://$operator_api_url_host:$api_port"
cat > "$operator_cli_wrapper" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export AIDN_HYPERVISOR_STATE_PATH=$(shell_quote "$data_dir/hypervisor-state.json")
export AIDN_HYPERVISOR_BUNDLES_PATH=$(shell_quote "$data_dir/bundles.json")
export AIDN_CONFIG_FILE=$(shell_quote "$operator_config_path")
export AIDN_NODE_ID=$(shell_quote "$operator_id")
export AIDN_OPERATOR_ID=$(shell_quote "$operator_id")
export AIDN_MCP_REMOTE_ENABLED=true
if [[ -z "\${AIDN_SECRET_MANAGER_MASTER_KEY:-}" ]]; then
  export AIDN_SECRET_MANAGER_MASTER_KEY="\$(tr -d '\r\n' < $(shell_quote "$registry_root/master-key.b64"))"
fi
if [[ -f "\$AIDN_CONFIG_FILE" ]]; then
  while IFS=\$'\\t' read -r -d '' key value; do
    [[ -n "\$key" ]] || continue
    export "\$key=\$value"
  done < <("$python_bin" - "\$AIDN_CONFIG_FILE" <<'PY'
import sys
from aidn_hypervisor.config import read_operator_config_values

for key, value in sorted(read_operator_config_values(sys.argv[1]).items()):
    print(f"{key}\\t{value}", end="\\0")
PY
  )
fi
common_args=(
  --secret-manager-path $(shell_quote "$registry_root/secrets.json")
  --master-key-file $(shell_quote "$registry_root/master-key.b64")
  --state-path $(shell_quote "$data_dir/hypervisor-state.json")
  --bundles-path $(shell_quote "$data_dir/bundles.json")
  --api-url $(shell_quote "$operator_api_url")
)
if [[ "\${1:-}" == 'pair' ]]; then
  exec "$python_bin" -m aidn_hypervisor.operator_cli "\$@" "\${common_args[@]}" \\
    --dashboard-url $(shell_quote "$dashboard_url")
fi
exec "$python_bin" -m aidn_hypervisor.operator_cli "\$@" "\${common_args[@]}"
EOF
chmod 700 "$operator_cli_wrapper"
mkdir -p "$HOME/.local/bin"
ln -sfn "$operator_cli_wrapper" "$HOME/.local/bin/aidn-operator"

service_name="aidn-hypervisor-$operator_id.service"
unit_path="$HOME/.config/systemd/user/$service_name"
wrapper_q="$(shell_quote "$wrapper")"
consensus_unit_dependency=''
if [[ "$consensus_mode" == 'validator' ]]; then
  consensus_unit_dependency="Wants=$consensus_service_name"
fi
cat > "$unit_path" <<EOF
[Unit]
Description=AiDN Hypervisor operator $operator_id
After=network-online.target
Wants=network-online.target
$consensus_unit_dependency

[Service]
Type=simple
ExecStart=$wrapper_q
Restart=always
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=tmpfs
BindPaths=$repo_q $data_q
BindReadOnlyPaths=$uv_q
ReadWritePaths=$data_q
WorkingDirectory=$repo_q

[Install]
WantedBy=default.target
EOF
chmod 600 "$unit_path"
if [[ "$consensus_mode" == 'validator' ]]; then
  consensus_dropin_dir="$HOME/.config/systemd/user/$consensus_service_name.d"
  mkdir -p "$consensus_dropin_dir"
  cat > "$consensus_dropin_dir/10-aidn-hypervisor.conf" <<EOF
[Unit]
After=$service_name
Wants=$service_name
EOF
  chmod 600 "$consensus_dropin_dir/10-aidn-hypervisor.conf"
fi

if command -v loginctl >/dev/null 2>&1 && [[ "$EUID" -ne 0 ]]; then
  "${sudo_cmd[@]}" loginctl enable-linger "$USER"
fi

if [[ "$no_start" != 'true' ]]; then
  uid="$(id -u)"
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$uid}"
  systemctl --user daemon-reload
  systemctl --user enable "$service_name"
  if systemctl --user is-active --quiet "$service_name"; then
    systemctl --user restart "$service_name"
  else
    systemctl --user start "$service_name"
  fi
  health_host="$api_host"
  if [[ "$health_host" == '0.0.0.0' || "$health_host" == '::' ]]; then
    health_host='127.0.0.1'
  fi
  for _ in $(seq 1 30); do
    if curl --fail --silent "http://$health_host:$api_port/health" >/dev/null; then
      break
    fi
    sleep 1
  done
  curl --fail --silent "http://$health_host:$api_port/health" >/dev/null || {
    systemctl --user --no-pager --full status "$service_name" >&2 || true
    die "Hypervisor did not become healthy; inspect journalctl --user -u $service_name"
  }
  if [[ "$steward_autostart" == 'true' ]]; then
    inference_status_json=''
    inference_state=''
    # The provider may need to map the model before its first health probe.
    # Poll the canonical Dashboard status instead of treating STARTING as a
    # hard failure at the first read after systemd restart.
    for _ in $(seq 1 180); do
      if inference_status_json="$(curl --fail --silent "http://$health_host:$api_port/operators/dashboard/steward/inference" 2>/dev/null)"; then
        inference_state="$($python_bin - "$inference_status_json" <<'PY'
import json
import sys

try:
    print(str(json.loads(sys.argv[1]).get("state") or "").upper())
except Exception:
    print("")
PY
        )"
        [[ "$inference_state" == 'RUNNING' ]] && break
        if [[ "$inference_state" == 'FAILED' || "$inference_state" == 'RESOURCE_WAIT' ]]; then
          break
        fi
      fi
      sleep 1
    done
    [[ -n "$inference_status_json" ]] || {
      systemctl --user --no-pager --full status "$service_name" >&2 || true
      die "Resident Steward status could not be read after service start"
    }
    if ! "$python_bin" - "$inference_status_json" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
state = str(payload.get("state") or "").upper()
if state != "RUNNING":
    print(
        "Resident Steward did not start automatically "
        f"(state={state or 'UNKNOWN'}, error={payload.get('last_error') or 'none'})",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
    then
      systemctl --user --no-pager --full status "$service_name" >&2 || true
      die "Resident Steward model did not reach RUNNING state"
    fi
  fi
  if [[ "$consensus_mode" == 'validator' ]]; then
    systemctl --user enable --now "$consensus_service_name"
    for _ in $(seq 1 30); do
      if curl --fail --silent "http://$consensus_rpc_host:$consensus_rpc_port/status" >/dev/null; then
        break
      fi
      sleep 1
    done
    curl --fail --silent "http://$consensus_rpc_host:$consensus_rpc_port/status" >/dev/null || {
      systemctl --user --no-pager --full status "$consensus_service_name" >&2 || true
      die "CometBFT RPC did not become healthy; inspect journalctl --user -u $consensus_service_name"
    }
  fi
fi

wallet_bootstrap_status='deferred_no_start'
wallet_bootstrap_id=''
wallet_bootstrap_public_key=''
dashboard_pairing_status='skipped'
dashboard_pairing_url="$dashboard_url"
dashboard_pairing_expires=''
dashboard_pairing_code=''
agent_onboarding_status='skipped'
if [[ "$no_start" == 'true' ]]; then
  dashboard_pairing_status='deferred_no_start'
  agent_onboarding_status='deferred_no_start'
else
  case "$wallet_action" in
    create)
      "$HOME/.local/bin/aidn-operator" wallet create --label 'Owner Wallet' >/dev/null
      ;;
    import)
      "$HOME/.local/bin/aidn-operator" wallet import --label 'Owner Wallet' >/dev/null
      ;;
    skip) ;;
  esac
  wallet_status_json=''
  if wallet_status_json="$("$HOME/.local/bin/aidn-operator" wallet status)"; then
    wallet_bootstrap_status="$($python_bin - "$wallet_status_json" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
print("configured" if payload.get("configured") else "not_configured")
PY
)"
    wallet_bootstrap_id="$($python_bin - "$wallet_status_json" <<'PY'
import json
import sys

print(json.loads(sys.argv[1]).get("wallet_id") or "")
PY
)"
    wallet_bootstrap_public_key="$($python_bin - "$wallet_status_json" <<'PY'
import json
import sys

print(json.loads(sys.argv[1]).get("public_key") or "")
PY
)"
  else
    wallet_bootstrap_status='status_unavailable'
  fi

  if [[ "$dashboard_pairing_action" == 'code' || "$dashboard_pairing_action" == 'first_browser' ]]; then
    pairing_mode='code'
    pairing_ttl_seconds='600'
    if [[ "$dashboard_pairing_action" == 'first_browser' ]]; then
      pairing_mode='first-browser'
      pairing_ttl_seconds='3600'
    fi
    pairing_output="$("$HOME/.local/bin/aidn-operator" pair --mode "$pairing_mode" --ttl-seconds "$pairing_ttl_seconds")"
    dashboard_pairing_url="$(printf '%s\n' "$pairing_output" | sed -n 's/^Open: //p')"
    dashboard_pairing_expires="$(printf '%s\n' "$pairing_output" | sed -n 's/^Expires: //p')"
    dashboard_pairing_code="$(printf '%s\n' "$pairing_output" | sed -n 's/^Code: //p')"
    [[ -n "$dashboard_pairing_url" ]] || dashboard_pairing_url="$dashboard_url"
    if [[ "$dashboard_pairing_action" == 'code' ]]; then
      dashboard_pairing_status='code_created_once'
    else
      dashboard_pairing_status='first_browser_window_open'
    fi
  else
    dashboard_pairing_status='skipped_by_operator'
  fi

  if [[ "$agent_action" == 'guide' ]]; then
    agent_onboarding_status='guided_existing_enrollment_boundary'
  else
    agent_onboarding_status='skipped_by_operator'
  fi
fi

state_path="$data_dir/bootstrap-state.json"
registry_state='disabled_until_mutual_peer_approval'
if [[ "$enable_registry" == 'true' ]]; then
  registry_state='listener_enabled_waiting_for_mutual_peer_approval'
fi
setup_model_expected_sha256=''
setup_model_expected_bytes=''
if [[ "$setup_mode" == 'ai_assisted' && "$setup_model_id" != 'skip' && -n "$setup_model_source" ]]; then
  expected_catalog_source="$(model_source_for_id "$setup_model_id" || true)"
  if [[ -n "$expected_catalog_source" && "$setup_model_source" == "$expected_catalog_source" ]]; then
    setup_model_expected_sha256="$(model_expected_sha256_for_id "$setup_model_id")"
    setup_model_expected_bytes="$(model_expected_size_bytes_for_id "$setup_model_id")"
  fi
fi
"$python_bin" - "$state_path" "$operator_id" "$peer_id" "$control_group_id" "$commit" \
  "$api_host" "$api_port" "$registry_state" "$service_name" "$identity_root" \
  "$registry_root" "$operator_public_key" "$ref" "$consensus_mode" \
  "$consensus_service_name" "$consensus_home" "$consensus_binary_path" \
  "$consensus_rpc_host" "$consensus_rpc_port" "$consensus_rpc_endpoint" "$consensus_transport" "$resource_capacity_path" \
  "$install_dir" "$data_dir" "$dashboard_url" "$operator_api_url" \
  "$dashboard_pairing_url" "$dashboard_pairing_expires" \
  "$wallet_action" "$wallet_bootstrap_status" "$wallet_bootstrap_id" \
  "$wallet_bootstrap_public_key" "$dashboard_pairing_status" "$agent_onboarding_status" \
  "$setup_mode" "$setup_provider" "$setup_model_id" "$setup_model_source" \
  "$setup_model_expected_sha256" "$setup_model_expected_bytes" \
  "$setup_endpoint_action" "$setup_handoff" "$setup_plan_path" \
  "$checkout_backup_path" <<'PY'
import json
import os
import sys

(
    path,
    operator_id,
    peer_id,
    control_group_id,
    commit,
    api_host,
    api_port,
    registry_state,
    service_name,
    identity_root,
    registry_root,
    operator_public_key,
    ref,
    consensus_mode,
    consensus_service_name,
    consensus_home,
    consensus_binary_path,
    consensus_rpc_host,
    consensus_rpc_port,
    consensus_rpc_endpoint,
    consensus_transport,
    resource_capacity_path,
    install_dir,
    data_dir,
    dashboard_url,
    operator_api_url,
    dashboard_pairing_url,
    dashboard_pairing_expires,
    wallet_action,
    wallet_bootstrap_status,
    wallet_bootstrap_id,
    wallet_bootstrap_public_key,
    dashboard_pairing_status,
    agent_onboarding_status,
    setup_mode,
    setup_provider,
    setup_model_id,
    setup_model_source,
    setup_model_expected_sha256,
    setup_model_expected_bytes,
    setup_endpoint_action,
    setup_handoff,
    setup_plan_path,
    checkout_backup_path,
) = sys.argv[1:]
from aidn_hypervisor.installation_onboarding import (
    InstallationOnboardingPlan,
    write_installation_plan,
)
installation_plan = InstallationOnboardingPlan(
    setup_mode=setup_mode,
    provider=setup_provider,
    model_id=setup_model_id,
    model_source=setup_model_source or None,
    model_expected_sha256=setup_model_expected_sha256 or None,
    model_expected_bytes=int(setup_model_expected_bytes) if setup_model_expected_bytes else None,
    endpoint_action=setup_endpoint_action,
    handoff=setup_handoff,
)
installation_plan_payload = write_installation_plan(setup_plan_path, installation_plan)
payload = {
    "status": "ok",
    "operator_id": operator_id,
    "peer_id": peer_id,
    "control_group_id": control_group_id,
    "commit": commit,
    "ref": ref,
    "api": f"http://{api_host}:{api_port}",
    "operator_api": operator_api_url,
    "dashboard": dashboard_url,
    "checkout": install_dir,
    "checkout_backup": checkout_backup_path or None,
    "data": data_dir,
    "service": service_name,
    "operator_identity": os.path.join(identity_root, "operator-identity.json"),
    "operator_public_identity": os.path.join(identity_root, "operator-public-identity.json"),
    "operator_public_key": operator_public_key,
    "registry_root": registry_root,
    "registry_public_bundle": os.path.join(registry_root, "public-peer.json"),
    "replication": registry_state,
    "consensus": {
        "mode": consensus_mode,
        "transport": consensus_transport,
        "service": consensus_service_name or None,
        "home": consensus_home or None,
        "binary": consensus_binary_path or None,
        "rpc": consensus_rpc_endpoint or (f"http://{consensus_rpc_host}:{consensus_rpc_port}" if consensus_service_name else None),
        "automatic_install": consensus_mode == "validator",
    },
    "resource_probe": {
        "mode": "auto",
        "capacity_report": resource_capacity_path,
        "automatic_install": True,
    },
    "onboarding": {
        "wallet_action": wallet_action,
        "wallet_status": wallet_bootstrap_status,
        "wallet_id": wallet_bootstrap_id or None,
        "wallet_public_key": wallet_bootstrap_public_key or None,
        "dashboard_pairing": dashboard_pairing_status,
        "dashboard_url": dashboard_pairing_url,
        "dashboard_expires_at": dashboard_pairing_expires or None,
        "agent": agent_onboarding_status,
        "private_material": "not_in_state_file",
    },
    "installation": {
        "mode": setup_mode,
        "ai_assisted": setup_mode == "ai_assisted",
        "plan_path": setup_plan_path,
        "plan": installation_plan_payload,
    },
}
os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
with open(path, "w", encoding="utf-8") as stream:
    json.dump(payload, stream, indent=2, sort_keys=True)
    stream.write("\n")
os.chmod(path, 0o600)
PY

setup_plan_hash="$($python_bin - "$setup_plan_path" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    plan = json.load(stream)
print(plan.get("plan_hash", "not available"))
PY
)"

display_wallet_id="$wallet_bootstrap_id"
[[ -n "$display_wallet_id" ]] || display_wallet_id='not available'
display_wallet_public_key="$wallet_bootstrap_public_key"
[[ -n "$display_wallet_public_key" ]] || display_wallet_public_key='not available'
display_pairing_expires="$dashboard_pairing_expires"
[[ -n "$display_pairing_expires" ]] || display_pairing_expires='unknown'
display_pairing_code="$dashboard_pairing_code"
[[ -n "$display_pairing_code" ]] || display_pairing_code='not returned'

printf '\n============================================================\n' >&2
printf 'AiDN NODE INSTALLATION COMPLETE\n' >&2
printf '============================================================\n' >&2
printf '\n[NODE IDENTITY]\n' >&2
printf '  operator ID       : %s\n' "$operator_id" >&2
printf '  peer ID           : %s\n' "$peer_id" >&2
printf '  control group     : %s\n' "$control_group_id" >&2
printf '  source ref/commit : %s / %s\n' "$ref" "$commit" >&2
printf '\n[SERVICE AND LINKS]\n' >&2
printf '  service           : %s\n' "$service_name" >&2
printf '  API (operator)    : %s\n' "$operator_api_url" >&2
printf '  dashboard         : %s\n' "$dashboard_url" >&2
printf '  listener          : %s:%s\n' "$api_host" "$api_port" >&2
if is_loopback_host "$api_host"; then
  printf '  access boundary   : loopback only\n' >&2
else
  printf '  access boundary   : LAN/non-loopback (firewall and trusted-network policy required)\n' >&2
fi
printf '  checkout          : %s\n' "$install_dir" >&2
if [[ -n "$checkout_backup_path" ]]; then
  printf '  previous checkout : %s (preserved local changes)\n' "$checkout_backup_path" >&2
fi
printf '  persistent data   : %s\n' "$data_dir" >&2
printf '  bootstrap state   : %s\n' "$state_path" >&2
printf '  capacity report   : %s\n' "$resource_capacity_path" >&2
printf '\n[NETWORK AND CONSENSUS]\n' >&2
printf '  consensus         : %s\n' "$consensus_mode" >&2
if [[ "$consensus_mode" == 'validator' ]]; then
  printf '  CometBFT RPC      : http://%s:%s\n' "$consensus_rpc_host" "$consensus_rpc_port" >&2
  printf '  CometBFT service  : %s\n' "$consensus_service_name" >&2
elif [[ "$consensus_mode" == 'non_validator' ]]; then
  printf '  source RPC        : %s\n' "$consensus_rpc_endpoint" >&2
else
  printf '  CometBFT          : disabled\n' >&2
fi
printf '  registry          : %s\n' "$registry_state" >&2
printf '\n[INSTALLATION MODE]\n' >&2
printf '  mode              : %s\n' "$setup_mode" >&2
printf '  plan              : %s\n' "$setup_plan_path" >&2
printf '  plan hash         : %s\n' "$setup_plan_hash" >&2
if [[ "$setup_mode" == 'ai_assisted' ]]; then
  printf '  provider intent   : %s\n' "$setup_provider" >&2
  printf '  model intent      : %s\n' "$setup_model_id" >&2
  [[ -n "$setup_model_source" ]] && printf '  model source      : %s\n' "$setup_model_source" >&2
  if [[ -n "$setup_model_source" ]]; then
    expected_catalog_source="$(model_source_for_id "$setup_model_id" || true)"
    if [[ -n "$expected_catalog_source" && "$setup_model_source" == "$expected_catalog_source" ]]; then
      printf '  artifact size     : %s bytes (pinned)\n' "$(model_expected_size_bytes_for_id "$setup_model_id")" >&2
      printf '  artifact SHA-256  : %s\n' "$(model_expected_sha256_for_id "$setup_model_id")" >&2
    else
      printf '  artifact integrity: SHA-256 computed after download (custom source)\n' >&2
    fi
  fi
  printf '  endpoint intent   : %s\n' "$setup_endpoint_action" >&2
  printf '  handoff           : %s\n' "$setup_handoff" >&2
  if [[ "$steward_autostart" == 'true' ]]; then
    printf '  steward           : CPU-first, bounded, prepared and started\n' >&2
  else
    printf '  steward           : CPU-first, bounded, dashboard start available\n' >&2
  fi
  # Assisted setup does not implicitly change a provider, model, or public
  # Endpoint; each later lifecycle change remains an explicit reviewed action.
  printf '  note              : no provider, model, or public Endpoint is changed implicitly\n' >&2
  printf '  note              : Bundle and public Endpoint changes remain operator-approved\n' >&2
else
  printf '  next step         : continue configuration from the Dashboard or CLI\n' >&2
fi
if [[ -n "$model_prefetch_state_path" ]]; then
  printf '\n[MODEL CACHE PREFETCH]\n' >&2
  model_prefetch_progress
  printf '  target            : %s\n' "$model_prefetch_target" >&2
  printf '  state             : %s\n' "$model_prefetch_state_path" >&2
  printf '  status            : %s\n' "$model_prefetch_status" >&2
  printf '  expected size     : %s\n' "${model_prefetch_expected_bytes:-unknown}" >&2
  printf '  expected SHA-256  : %s\n' "${model_prefetch_expected_sha256:-computed after download}" >&2
  printf '  background PID    : %s\n' "${model_prefetch_pid:-finished}" >&2
  if [[ "$steward_autostart" == 'true' ]]; then
    printf '  note              : verified before service start; Resident Steward is running\n' >&2
  else
    printf '  note              : model runtime activation remains available from the Dashboard\n' >&2
  fi
fi
printf '\n[PUBLIC ARTIFACTS — SAFE TO SHARE]\n' >&2
printf '  public peer bundle: %s\n' "$registry_root/public-peer.json" >&2
printf '  public identity   : %s\n' "$identity_root/operator-public-identity.json" >&2
printf '  public key        : %s\n' "$operator_public_key" >&2
printf '\n[WALLET AND DASHBOARD ACCESS]\n' >&2
printf '  wallet status     : %s\n' "$wallet_bootstrap_status" >&2
printf '  wallet ID         : %s\n' "$display_wallet_id" >&2
printf '  wallet public key : %s\n' "$display_wallet_public_key" >&2
printf '  dashboard pairing : %s\n' "$dashboard_pairing_status" >&2
if [[ "$dashboard_pairing_status" == 'code_created_once' ]]; then
  printf '  pairing URL       : %s\n' "$dashboard_pairing_url" >&2
  printf '  pairing expires   : %s\n' "$display_pairing_expires" >&2
  printf '  one-time code     : %s\n' "$display_pairing_code" >&2
elif [[ "$dashboard_pairing_status" == 'first_browser_window_open' ]]; then
  printf '  dashboard URL     : %s\n' "$dashboard_pairing_url" >&2
  printf '  claim expires     : %s\n' "$display_pairing_expires" >&2
  printf '  next step         : open Dashboard on the trusted browser and select Claim this browser\n' >&2
elif [[ "$dashboard_pairing_status" == 'deferred_no_start' ]]; then
  printf '  pairing next step : run aidn-operator pair after starting the service\n' >&2
else
  printf '  pairing next step : run aidn-operator pair when you are ready\n' >&2
fi
printf '\n[PRIVATE MATERIAL — NEVER COPY OR SHARE]\n' >&2
printf '  encrypted secrets : %s\n' "$registry_root/secrets.json" >&2
printf '  master key file   : %s\n' "$registry_root/master-key.b64" >&2
printf '  private identity  : %s\n' "$identity_root/operator-identity.json" >&2
printf '  attestation key   : %s\n' "$identity_root/operator-attestation-key.raw" >&2
printf '  The sudo password was used only by sudo and was not captured by this script.\n' >&2
printf '\n[AGENT ONBOARDING]\n' >&2
printf '  status            : %s\n' "$agent_onboarding_status" >&2
if [[ "$agent_onboarding_status" == 'guided_existing_enrollment_boundary' ]]; then
  printf '  MCP endpoint      : %s/mcp\n' "$operator_api_url" >&2
  printf '  1. Start the agent with its own X25519 key and submit an enrollment request.\n' >&2
  printf '  2. Review the label and key fingerprint in Dashboard -> Settings -> Agent enrollment requests.\n' >&2
  printf '  3. Approve only the expected request; the agent retrieves its sealed credential once.\n' >&2
  printf '  CLI helpers       : aidn-operator enrollment list\n' >&2
  printf '                      aidn-operator enrollment approve --request-id <id>\n' >&2
fi
printf '\n[NEXT COMMANDS]\n' >&2
printf '  systemctl --user status %s\n' "$service_name" >&2
printf '  journalctl --user -u %s -f\n' "$service_name" >&2
printf '  aidn-operator wallet status\n' >&2
printf '  aidn-operator pair\n' >&2
printf '============================================================\n' >&2
