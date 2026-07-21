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

It also runs an opt-in one-request fixed-price Session through the existing MVP
economic path: test escrow lock, provider execution, terminal Runtime evidence
and Settlement finalization. This path currently records RFC-0054-compatible
evidence after the legacy task executor returns; direct Session dispatch into
`LlamaCppOpenAIAdapter` remains a separate follow-up.

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
