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
.\tools\run-live-provider-conformance.ps1 -Provider llamacpp
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
post-execution compatibility-evidence bridge. The smoke restarts the local
Hypervisor after the terminal Result and Final Usage are durable, restores the
Endpoint, Session and escrow state from the file store, then signs and
finalizes the same Settlement. It must not re-dispatch the Request to the
provider or create a second payment.

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

## vLLM attached-service profile

vLLM runs as a separate Provider service. The Hypervisor attaches it through
the `vllm` plugin and owns the Provider Instance, Model Deployment, Runtime
Binding and Endpoint records; it does not manage the vLLM process lifecycle.

Discovery and Health use short probes. Runtime execution defaults to a 90-second
request timeout, configurable through Runtime metadata as `timeout_seconds`, so
model warm-up is not mistaken for an unavailable attached service.

Run the opt-in provider and paid-session smoke:

```powershell
$env:AIDN_VLLM_ENDPOINT = "http://provider-host:8000"
$env:AIDN_VLLM_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
.\tools\run-live-provider-conformance.ps1 -Provider vllm
```

Attach a reachable server to a running Hypervisor:

```powershell
$body = @{
  plugin_id = "vllm"
  display_name = "RTX 3090 vLLM"
  configuration = @{ endpoint = "http://provider-host:8000" }
} | ConvertTo-Json -Depth 4

Invoke-RestMethod -Method Post `
  -Uri "http://hypervisor-host:8080/operators/provider-instances/attach" `
  -ContentType "application/json" -Body $body
```

Then discover the returned Provider Instance models, create a Runtime Binding
for the chosen deployment, and bind an Endpoint to that Runtime Binding. vLLM
Usage is provider-authoritative per token dimension. The attach configuration
must contain only the endpoint and scoped Secret Handle references; do not put
tokens or credentials in the URL.

## Ollama attached-service profile

Ollama remains an attached service: the Hypervisor discovers models and
executes the native `/api/generate` contract but does not manage the daemon.

```powershell
$env:AIDN_OLLAMA_ENDPOINT = "http://provider-host:11434"
$env:AIDN_OLLAMA_MODEL = "qwen2.5:0.5b"
.\tools\run-live-provider-conformance.ps1 -Provider ollama
```

The opt-in smoke verifies attach, model discovery, Health, native execution
and provider-reported prompt/evaluation token Usage. It also runs the public
fixed-price Session path through the approved `ollama-generate` Runtime
Binding: signed Endpoint publication, Consumer authorization, escrow lock,
Runtime execution, durable restart and signed cooperative Settlement. The
restored Hypervisor must finalize the existing execution evidence without a
second Provider request or Endpoint payment.

## Shared launcher

`tools/run-live-provider-conformance.ps1` validates the selected profile's
required environment variables and runs exactly one live test file using the
repository's standard pytest import configuration but without coverage. It
accepts `llamacpp`, `vllm` or `ollama`.
It never starts, stops or reconfigures a Provider and does not accept
credentials as command-line arguments.

The GitHub Actions integration job remains opt-in and intentionally has no
Provider endpoint configured. Run live conformance from an operator-controlled
host, or configure a separate self-hosted runner with the required endpoint and
model environment variables.
