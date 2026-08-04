#!/usr/bin/env bash
set -euo pipefail

# Requires Docker and a checkout with .venv or a Python image able to install AiDN.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
ROOT="${1:?usage: $0 <state-root>}"
IMAGE="${AIDN_COMETBFT_IMAGE:-cometbft/cometbft:v0.38.19}"
NETWORK="aidn-cometbft-devnet"
APP_IMAGE="aidn-hypervisor-devnet"
COUNT="${AIDN_VALIDATOR_COUNT:-4}"

for required_command in docker curl python3; do
  command -v "$required_command" >/dev/null 2>&1 || {
    echo "required command is missing: $required_command" >&2
    exit 2
  }
done
docker info >/dev/null 2>&1 || {
  echo "Docker daemon is unavailable" >&2
  exit 2
}
[[ "$COUNT" == "4" ]] || { echo "this drill requires exactly four validators" >&2; exit 2; }
mkdir -p "$ROOT"
chmod 777 "$ROOT"
docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null

cat >"$ROOT/Dockerfile" <<'EOF'
FROM python:3.14-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .
CMD ["python", "-m", "uvicorn", "aidn_hypervisor.main:build_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
EOF
docker build -t "$APP_IMAGE" -f "$ROOT/Dockerfile" "$REPO_ROOT" >/dev/null
rm "$ROOT/Dockerfile"

docker run --rm --user 0 --entrypoint /bin/sh -v "$ROOT:/work" "$IMAGE" -c 'rm -rf /work/testnet /work/state; mkdir -p /work/testnet /work/state; chmod 777 /work/testnet /work/state' >/dev/null
chmod 777 "$ROOT/testnet" "$ROOT/state"
docker run --rm -v "$ROOT/testnet:/work" "$IMAGE" testnet --v 4 --o /work \
  --hostname comet-0 --hostname comet-1 --hostname comet-2 --hostname comet-3 >/dev/null
docker run --rm --user 0 --entrypoint /bin/sh -v "$ROOT/testnet:/work" "$IMAGE" -c 'chmod -R a+rwX /work' >/dev/null

for i in 0 1 2 3; do
  mkdir -p "$ROOT/state/node-$i"
  sed -i "s#^proxy_app = .*#proxy_app = \"tcp://aidn-abci-$i:26658\"#" "$ROOT/testnet/node$i/config/config.toml"
  sed -i 's#^laddr = "tcp://127.0.0.1:26657"#laddr = "tcp://0.0.0.0:26657"#' "$ROOT/testnet/node$i/config/config.toml"
  docker rm -f "aidn-abci-$i" "aidn-comet-$i" >/dev/null 2>&1 || true
  docker run -d --name "aidn-abci-$i" --restart unless-stopped --network "$NETWORK" \
    -e AIDN_HYPERVISOR_STATE_PATH=/state/hypervisor.json \
    -e AIDN_CONSENSUS_MODE=validator \
    -e AIDN_CONSENSUS_STRICT_OPERATION_COVERAGE=true \
    -e AIDN_CONSENSUS_GENESIS_ACCOUNTS_JSON='{"wallet:acceptance-consumer":2000}' \
    -e AIDN_COMETBFT_ABCI_STATE_PATH=/state/abci \
    -e AIDN_COMETBFT_ABCI_HOST=0.0.0.0 \
    -e AIDN_COMETBFT_ABCI_PORT=26658 \
    -v "$ROOT/state/node-$i:/state" "$APP_IMAGE" >/dev/null
  # Expose every validator RPC on a deterministic loopback port so the
  # acceptance verifier can prove convergence instead of observing node 0
  # only.  The CometBFT peers still communicate over the private Docker net.
  ports=(-p "127.0.0.1:$((26657 + i)):26657")
  docker run -d --name "aidn-comet-$i" --restart unless-stopped --network "$NETWORK" --network-alias "comet-$i" "${ports[@]}" \
    -v "$ROOT/testnet/node$i:/cometbft" "$IMAGE" start >/dev/null
done

echo "waiting for validator network..."
for _ in $(seq 1 40); do
  all_running=true
  for i in 0 1 2 3; do
    [[ "$(docker inspect -f '{{.State.Running}}' "aidn-comet-$i" 2>/dev/null || true)" == "true" ]] || all_running=false
    [[ "$(docker inspect -f '{{.State.Running}}' "aidn-abci-$i" 2>/dev/null || true)" == "true" ]] || all_running=false
  done
  height=$(curl -fsS http://127.0.0.1:26657/status 2>/dev/null | python3 -c 'import json, sys; print(json.load(sys.stdin)["result"]["sync_info"]["latest_block_height"])' 2>/dev/null || true)
  if [[ "$all_running" == true && -n "$height" && "$height" -ge 3 ]]; then
    echo "multi-validator devnet ready at height $height"
    exit 0
  fi
  sleep 1
done
docker logs aidn-comet-0 --tail 80 >&2 || true
docker logs aidn-abci-0 --tail 80 >&2 || true
exit 1
