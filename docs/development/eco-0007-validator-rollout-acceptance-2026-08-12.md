# ECO-0007 Validator Rollout Acceptance

Status: PASS

Date: 2026-08-12

This report records the controlled sequential rollout of the ABCI image that
implements the ECO-0007 production preflight and guarded batch execution
surfaces. It does not claim a production reward payout or public-network
readiness.

## Scope

- Source commit: `6d18cce9d30cdf53acbdbcfcc14b850b895733bc`
- Image tag: `aidn-hypervisor-lan-testnet-strict:6d18cce`
- Container replaced on each host: `aidn-g5-abci`
- State mount preserved on every host: `/home/user/aidn-g5-clean/state:/state`
- Rollout order: `192.168.88.128`, then `192.168.88.129`, then `192.168.88.130`
- Previous containers were retained for rollback; no ledger or CometBFT state
  reset was performed.

## Per-validator result

| Validator | Image ID | Health | Rollback container |
| --- | --- | --- | --- |
| `192.168.88.128` | `sha256:708b4e94bd4ba37cc1e9ce7cbccfa5d5a710dde4787becf53845944366b64f1d` | `{"status":"ok"}` | `aidn-g5-abci-prev-6d18cce-r1-128` |
| `192.168.88.129` | `sha256:012ea00b6bd48c82e0a9c8a20bdfcab07759d376279efda3892c27af24889bc4` | `{"status":"ok"}` | `aidn-g5-abci-prev-6d18cce-r1-129` |
| `192.168.88.130` | `sha256:66c69792a67ab91a312b4b7c70a1e8bc8b2ff2852358b2348569ecb10469940f` | `{"status":"ok"}` | `aidn-g5-abci-prev-6d18cce-r1-130` |

The image IDs differ because each host performed a local Docker build. The
source commit and Dockerfile are identical; the rollout verified the exact
expected image ID on each host before accepting it.

## Consensus verification

After the sequential rollout, all three CometBFT RPC endpoints reported:

- chain: `chain-Anm7Jk`;
- height: `51533` at the final check;
- AppHash: `1E541C0A9C3A92DD7F497DE2947A6DD0645C785B90358310B42D44BFC772D491`;
- `catching_up: false`.

The validators agreed on chain identity and AppHash while the network
continued producing blocks. The CometBFT containers were not replaced.

## ECO-0007 preflight result

The quorum query was run against all three validator RPCs after rollout. It
returned a consistent `3/3` observation with:

- `status: BLOCKED`;
- `reason_code: DEVELOPMENT_REWARD_EPOCH_TRANSITION_UNAVAILABLE`;
- `preflight_hash: sha256:63bad672ba3fc3ce4bda380a3ce7e1c640bc653860148e99fe3c3abcf45dbdfd`.

This is the expected fail-closed result for the current chain: no finalized
`EPOCH_TRANSITION` exposes a `GENERAL_DEVELOPMENT` pool budget yet. The new
query is therefore live and quorum-consistent, but a reward batch must not be
built or submitted until a canonical epoch transition and pool budget exist.

## Reproduction

```text
uv run python tools/query-development-reward-preflight.py \
  --rpc-url http://192.168.88.128:26657 \
  --rpc-url http://192.168.88.129:26657 \
  --rpc-url http://192.168.88.130:26657
```

Exit code `2` is correct for the current state. It must change to `0` only
after the canonical consensus path finalizes an eligible epoch transition.

## Limitations

- This is a controlled local network, not a public-network or independent
  operator acceptance.
- No production reward batch was submitted.
- No Q was minted or credited by this rollout.
- The next required evidence is a finalized `EPOCH_TRANSITION`, followed by a
  signed ECO-0007 activation/profile and a real, quorum-finalized contribution
  payout batch.
