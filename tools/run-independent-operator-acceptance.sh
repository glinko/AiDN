#!/usr/bin/env bash
# Run read-only technical acceptance and preserve tamper-evident local evidence.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run-independent-operator-acceptance.sh \
    --registry-config PATH --registry-snapshot PATH --peer-id ID \
    --external-finality-config PATH --evidence-dir PATH \
    [--required-object-id ID] [--timeout SECONDS]

The caller must set AIDN_SECRET_MANAGER_PATH and AIDN_SECRET_MANAGER_MASTER_KEY.
This script never makes directory-trust or independent-ownership claims.
EOF
}

registry_config=''
registry_snapshot=''
peer_id=''
finality_config=''
evidence_dir=''
required_object_id=''
timeout='30'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --registry-config) registry_config="$2"; shift 2 ;;
    --registry-snapshot) registry_snapshot="$2"; shift 2 ;;
    --peer-id) peer_id="$2"; shift 2 ;;
    --external-finality-config) finality_config="$2"; shift 2 ;;
    --evidence-dir) evidence_dir="$2"; shift 2 ;;
    --required-object-id) required_object_id="$2"; shift 2 ;;
    --timeout) timeout="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for name in registry_config registry_snapshot peer_id finality_config evidence_dir; do
  [[ -n "${!name}" ]] || { echo "missing --${name//_/-}" >&2; exit 2; }
done
[[ -n "${AIDN_SECRET_MANAGER_PATH:-}" && -n "${AIDN_SECRET_MANAGER_MASTER_KEY:-}" ]] || {
  echo 'AIDN_SECRET_MANAGER_PATH and AIDN_SECRET_MANAGER_MASTER_KEY are required' >&2
  exit 2
}

umask 077
mkdir -p "$evidence_dir"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
registry_report="$evidence_dir/registry-replication-${timestamp}.json"
finality_report="$evidence_dir/external-finality-${timestamp}.json"
validation_report="$evidence_dir/evidence-validation-${timestamp}.json"
checksum_manifest="$evidence_dir/SHA256SUMS-${timestamp}"

registry_args=(--config "$registry_config" --registry-snapshot "$registry_snapshot" --peer-id "$peer_id" --timeout "$timeout")
if [[ -n "$required_object_id" ]]; then registry_args+=(--required-object-id "$required_object_id"); fi

PYTHONPATH=src python tools/verify_registry_replication_deployment.py "${registry_args[@]}" > "$registry_report"
PYTHONPATH=src python tools/verify-cometbft-external-testnet.py --config "$finality_config" > "$finality_report"
(cd "$evidence_dir" && sha256sum "$(basename "$registry_report")" "$(basename "$finality_report")") > "$checksum_manifest"
PYTHONPATH=src python tools/validate_acceptance_evidence.py \
  --evidence-dir "$evidence_dir" \
  --checksum-file "$checksum_manifest" > "$validation_report"

printf '{"status":"ok","registry_report":"%s","finality_report":"%s","checksum_manifest":"%s","validation_report":"%s","ownership_evidence":"NOT_PROVEN_BY_PROTOCOL"}\n' \
  "$registry_report" "$finality_report" "$checksum_manifest" "$validation_report"
