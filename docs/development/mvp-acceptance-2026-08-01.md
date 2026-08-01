# AiDN Functional MVP Acceptance Report

Status: Accepted for controlled testnet

Date: 2026-08-01

Profile: [MVP-0001](../product/MVP-0001-economic-execution-profile.md)

## Scope

This report closes the functional controlled-testnet gate for the fixed-price
execution profile: one accepted Request per prepaid Session, real Provider
execution, final Usage reporting, cooperative Settlement, and deterministic
restart/recovery behavior.

The acceptance policy explicitly accepts `hv-node10` (`192.168.88.126`) as an
independent operator by project declaration. This is an administrative MVP
assumption, not cryptographic proof of separate ownership. Protocol reports
continue to expose `ownership_evidence: NOT_PROVEN_BY_PROTOCOL`.

## Acceptance Results

| Gate | Result | Evidence |
| --- | --- | --- |
| Authoritative wallet identity sync | PASS | Signed peer envelope imported from `node4`, pinned by node/operator/owner wallet IDs; reconciliation showed one consistent identity, zero conflicts/divergence/errors/pending peers; state remained consistent after `hv-node10` systemd restart. |
| llama.cpp execution | PASS | `tests/integration/test_llamacpp_live.py`: 5 passed against `qwen3.6` at `192.168.88.20:9000`. |
| vLLM execution | PASS | `tests/integration/test_vllm_live.py`: 2 passed against `Qwen/Qwen2.5-0.5B-Instruct` at `192.168.88.20:8000`. vLLM was tested during an exclusive GPU window and llama.cpp was restored afterwards. |
| Ollama execution | PASS | `tests/integration/test_ollama_live.py`: 2 passed against `qwen2.5:0.5b` at `192.168.88.20:11434`. |
| Restart/recovery/idempotency | PASS | Each live Provider profile collected its provider-specific `...after_restart` test. The tests assert recovery without a second Provider execution or duplicate payment. |
| MVP release readiness | PASS | All required controlled-testnet gates above are satisfied. |

The live Provider evidence was collected against source commit `a7cd284`.
The acceptance runner added with this report rechecks the required Provider
restart test by JUnit test name and fails closed when wallet reconciliation is
unavailable, unpinned, stale, conflicting, or divergent.

## Reproducible Checks

Run the local acceptance unit tests without the repository coverage add-on
when another pytest process is holding `.coverage` on Windows:

```powershell
uv run pytest --override-ini addopts= -p no:cov tests/test_mvp_acceptance.py -q
```

Run live Provider checks with the existing profile-specific environment
variables:

```powershell
uv run python tools/run_mvp_acceptance.py `
  --provider llamacpp `
  --provider vllm `
  --provider ollama `
  --llamacpp-endpoint http://192.168.88.20:9000 `
  --llamacpp-model qwen3.6 `
  --vllm-endpoint http://192.168.88.20:8000 `
  --vllm-model Qwen/Qwen2.5-0.5B-Instruct `
  --ollama-endpoint http://192.168.88.20:11434 `
  --ollama-model qwen2.5:0.5b `
  --wallet-api-url http://127.0.0.1:8767 `
  --wallet-peer-base-url http://192.168.88.127:8000 `
  --evidence-dir .artifacts/mvp-acceptance
```

The all-provider command requires the target wallet reconciliation API to be
reachable from the machine running the command. It must be run only when the
vLLM and llama.cpp services have an exclusive GPU window; both cannot claim
the RTX 3090 concurrently under the tested configuration.

## Explicit Non-Claims

This acceptance does not claim:

- public Registry directory authority;
- cryptographic proof of organizationally independent operators;
- public multi-validator consensus finality;
- production economic deployment;
- subjective quality of a Provider result.

Those are separate post-MVP evidence and Governance gates. The controlled
MVP is accepted because its technical execution and accounting boundary is
explicit, bounded, replay-safe, and covered by live evidence.
