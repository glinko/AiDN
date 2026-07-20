# Real Provider Conformance

Real-provider checks are opt-in pytest integration tests. They complement the
deterministic fake-upstream suite; they are never required for ordinary local
development or CI.

## llama.cpp OpenAI-compatible profile

The target server must expose:

- `GET /health` returning `{"status":"ok"}`;
- `GET /v1/models` with the configured model ID;
- `POST /v1/completions` with provider Usage and timings.

Run from PowerShell:

```powershell
$env:AIDN_LLAMACPP_LIVE = "1"
$env:AIDN_LLAMACPP_ENDPOINT = "http://provider-host:9000"
$env:AIDN_LLAMACPP_MODEL = "provider-model-id"
python -m pytest -q tests/integration/test_llamacpp_live.py
```

The profile sends one short completion. It verifies Health, model discovery,
completion response shape, provider-reported token Usage and timings. It does
not start, stop or reconfigure the provider.

Unset `AIDN_LLAMACPP_LIVE` to skip the test. Do not put credentials in these
environment variables; authenticated upstream support belongs to the scoped
Secret Manager boundary.
