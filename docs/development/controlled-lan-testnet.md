# Controlled LAN Testnet

This runbook is for a private, operator-controlled CometBFT lab. It is useful
for integration and failure testing, but it is not evidence of independent
validator ownership or production finality.

## Topology

The current four-host lab uses one CometBFT validator and one AiDN ABCI
container per host:

| Host | Role | RPC |
| --- | --- | --- |
| `192.168.88.127` | validator 4 | `http://192.168.88.127:26657` |
| `192.168.88.128` | validator 3 | `http://192.168.88.128:26657` |
| `192.168.88.129` | validator 2 | `http://192.168.88.129:26657` |
| `192.168.88.130` | validator 1 | `http://192.168.88.130:26657` |

Each node must expose three P2P peers, be caught up, and report the same chain
state before an integration drill begins. Do not expose the HTTP RPC ports
beyond the private LAN. Production and independent-testnet acceptance requires
authenticated HTTPS RPC endpoints and the external verifier.

The ABCI and CometBFT containers SHALL both use Docker restart policy
`unless-stopped`. CometBFT terminates when its ABCI socket is closed; without
the policy, restarting an ABCI process leaves the validator down and makes a
subsequent recovery result ambiguous. After any container replacement, verify
that both containers are running and that the four RPC views reconverge before
submitting transactions.

## Readiness Gate

Run from a checkout with the package installed, or prepend `PYTHONPATH=src`:

```bash
PYTHONPATH=src python tools/verify-cometbft-lan-testnet.py \
  --rpc-url http://192.168.88.127:26657 \
  --rpc-url http://192.168.88.128:26657 \
  --rpc-url http://192.168.88.129:26657 \
  --rpc-url http://192.168.88.130:26657
```

The verifier only accepts insecure HTTP after explicitly constraining it to
private IP addresses. Its successful report deliberately includes
`ownership_evidence: NOT_PROVEN_BY_PROTOCOL`.

On 2026-08-01 the four-host LAN gate passed against the live validators at
height `84959`: all four RPC views reported the same chain ID and application
hash, four unique validator IDs, and three P2P peers per node. This confirms
controlled topology readiness for multi-RPC integration drills only; it does
not establish independent ownership or public network finality.

The stricter live acceptance run on 2026-08-02 also passed the complete
external transaction/Merkle drill. It finalized the failure, Session lifecycle
and Reputation evidence chains, then recovered one remotely restarted CometBFT
validator without an AppHash change. See the [acceptance evidence record](./cometbft-lan-acceptance-2026-08-02.md).

The complete drill is disposable-state based. Start it from a fresh state for
each run; do not reuse a state that already contains the lifecycle lock from a
previous drill. The verifier does not replenish balances or mint test funds.

## Operating Rule

Use this environment for reproducible multi-host checks such as registry
replication, Runtime routing, snapshot restore, consensus restart and failure
recovery. Preserve the command output with the test run. Do not use the lab to
claim a public network, independent registry peer, or independent validator
acceptance.
