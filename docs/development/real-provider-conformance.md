# Real Provider Conformance

Real-provider checks are opt-in pytest integration tests. They complement the
deterministic fake-upstream suite; they are never required for ordinary local
development or CI.

## llama.cpp OpenAI-compatible profile

The target server must expose:

- `GET /health` returning `{"status":"ok"}`;
- `GET /v1/models` with the configured model ID;
- `POST /v1/completions` with provider Usage, timings and OpenAI SSE streaming.

Run from PowerShell:

```powershell
$env:AIDN_LLAMACPP_LIVE = "1"
$env:AIDN_LLAMACPP_ENDPOINT = "http://provider-host:9000"
$env:AIDN_LLAMACPP_MODEL = "provider-model-id"
python -m pytest -q tests/integration/test_llamacpp_live.py
```

The profile sends short completions. It verifies Health, model discovery,
completion response shape, provider-reported token Usage and timings, ordered
SSE stream chunks with a final content root, final Result redelivery, and a
Recovery State/Plan/Result cycle without another adapter execution. It does not
start, stop or reconfigure the provider.

The same opt-in profile also verifies the operator attach path: it attaches the
server without lifecycle authority, discovers the configured model through
`/v1/models`, creates a `llamacpp-openai.v1` Runtime Binding, evaluates
Endpoint admission, creates an Endpoint draft and records its signed
publication commitment.

It also verifies direct approved-Binding execution: a Session is bound to the
signed Endpoint Runtime Binding, the Hypervisor performs the RFC-0054
handshake, and `LlamaCppOpenAIAdapter` produces the terminal Result and Usage
evidence. The queue selects this direct path for an Endpoint bound to
`llamacpp-openai`; it does not invoke the legacy task-plugin RPC or synthesize
compatibility evidence afterwards.

The same opt-in profile runs a one-request fixed-price Session through that
approved-Binding path: escrow lock, queue dispatch, provider execution, terminal
Runtime evidence and Settlement finalization. The Session therefore has no
post-execution compatibility-evidence bridge.

Streaming endpoints normally do not disclose final Provider token usage. The
adapter therefore reports only locally observed delivered output bytes for a
stream and does not emit Provider token dimensions. The adapter also declares
best-effort cancellation only: a cancel result remains
`CANCELLATION_PENDING` with an unknown Provider execution state until a
Provider-specific operation handle or recovery observation can confirm the
outcome; it never claims a confirmed Provider stop for ordinary
`/v1/completions` traffic.

Unset `AIDN_LLAMACPP_LIVE` to skip the test. Do not put credentials in these
environment variables; authenticated upstream support belongs to the scoped
Secret Manager boundary.
