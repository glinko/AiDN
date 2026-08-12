#!/usr/bin/env bash
set -euo pipefail

# Refresh the external Faucet and core packages without allowing a stale
# non-editable package directory to shadow the reviewed checkout.

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
faucet_project="$repo_root/services/aidn-faucet"
faucet_python="$faucet_project/.venv/bin/python"

if [[ ! -x "$faucet_python" ]]; then
  printf 'Faucet virtualenv is missing: %s\n' "$faucet_python" >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' 'uv is required to refresh the Faucet runtime' >&2
  exit 1
fi

site_packages="$($faucet_python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
case "$site_packages" in
  "$faucet_project/.venv/"*) ;;
  *)
    printf 'Refusing to clean an unexpected site-packages path: %s\n' "$site_packages" >&2
    exit 1
    ;;
esac

rm -rf "$site_packages/aidn_faucet" "$site_packages/aidn_hypervisor"
uv pip install \
  --python "$faucet_python" \
  --reinstall \
  --no-cache \
  --editable "$faucet_project"

 AIDN_FAUCET_SOURCE="$faucet_project/src" "$faucet_python" - <<'PY'
import os
from pathlib import Path

import aidn_faucet.cometbft_submitter as submitter
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope

expected = Path(os.environ["AIDN_FAUCET_SOURCE"]).resolve()
loaded = Path(submitter.__file__).resolve()
if expected not in loaded.parents:
    raise SystemExit(f"Faucet imported outside reviewed checkout: {loaded}")
if "consensus_bytes" not in submitter.serialize_faucet_envelope.__code__.co_names:
    raise SystemExit("Faucet serializer is stale: consensus_bytes is not in use")
if not hasattr(LedgerOperationEnvelope, "consensus_bytes"):
    raise SystemExit("AiDN core package is stale: consensus_bytes is missing")
print(f"Faucet runtime verified: {loaded}")
PY
