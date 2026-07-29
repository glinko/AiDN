#!/usr/bin/env bash
set -euo pipefail

# Requires Docker and a checkout with .venv or a Python image able to install AiDN.
ROOT="${1:?usage: $0 <state-root>}"
IMAGE="${AIDN_COMETBFT_IMAGE:-cometbft/cometbft:v0.38.19}"
NETWORK="aidn-cometbft-devnet"
APP_IMAGE="aidn-hypervisor-devnet"
COUNT="${AIDN_VALIDATOR_COUNT:-4}"

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
docker build -t "$APP_IMAGE" -f "$ROOT/Dockerfile" "$(pwd)" >/dev/null
rm "$ROOT/Dockerfile"

docker run --rm --user 0 --entrypoint /bin/sh -v "$ROOT:/work" "$IMAGE" -c 'rm -rf /work/testnet /work/state; mkdir -p /work/testnet /work/state; chmod 777 /work/testnet /work/state' >/dev/null
chmod 777 "$ROOT/testnet" "$ROOT/state"
docker run --rm -v "$ROOT/testnet:/work" "$IMAGE" testnet --v 4 --o /work \
  --hostname comet-0 --hostname comet-1 --hostname comet-2 --hostname comet-3 >/dev/null
docker run --rm --user 0 --entrypoint /bin/sh -v "$ROOT/testnet:/work" "$IMAGE" -c 'chmod -R a+rwX /work' >/dev/null

for i in 0 1 2 3; do
  mkdir -p "$ROOT/state/node-$i"
  sed -i "s#^proxy_app = .*#proxy_app = \"tcp://aidn-abci-$i:26658\"#" "$ROOT/testnet/node$i/config/config.toml"
  docker rm -f "aidn-abci-$i" "aidn-comet-$i" >/dev/null 2>&1 || true
  docker run -d --name "aidn-abci-$i" --network "$NETWORK" \
    -e AIDN_HYPERVISOR_STATE_PATH=/state/hypervisor.json \
    -e AIDN_CONSENSUS_MODE=validator \
    -e AIDN_COMETBFT_ABCI_STATE_PATH=/state/abci \
    -e AIDN_COMETBFT_ABCI_HOST=0.0.0.0 \
    -e AIDN_COMETBFT_ABCI_PORT=26658 \
    -v "$ROOT/state/node-$i:/state" "$APP_IMAGE" >/dev/null
  ports=()
  [[ "$i" == "0" ]] && ports=(-p 127.0.0.1:26657:26657)
  docker run -d --name "aidn-comet-$i" --network "$NETWORK" --network-alias "comet-$i" "${ports[@]}" \
    -v "$ROOT/testnet/node$i:/cometbft" "$IMAGE" start >/dev/null
done

echo "waiting for validator network..."
for _ in $(seq 1 40); do
  height=$(curl -fsS http://127.0.0.1:26657/status 2>/dev/null | python3 -c 'import json, sys; print(json.load(sys.stdin)["result"]["sync_info"]["latest_block_height"])' 2>/dev/null || true)
  if [[ -n "$height" && "$height" -ge 3 ]]; then
    echo "multi-validator devnet ready at height $height"
    exit 0
  fi
  sleep 1
done
docker logs aidn-comet-0 --tail 80 >&2 || true
docker logs aidn-abci-0 --tail 80 >&2 || true
exit 1
