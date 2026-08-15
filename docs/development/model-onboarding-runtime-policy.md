# Model onboarding and runtime policy

The operator dashboard's **Models** workspace now provides one bounded flow for
an LLM artifact or repository:

1. Select an installed `ollama`, `llama.cpp`, or `vllm` Provider and enter the
   model ID plus a source URL.
2. Paste a Hugging Face `blob`/`resolve` file URL for GGUF artifacts. A
   Hugging Face repository URL (or a bare `org/model` reference) is accepted
   for vLLM; the repository is cached by vLLM on first start. Ollama library
   URLs and model references are pulled through its local API.
3. Set the operator defaults in **Runtime policy**. Each checkbox controls
   whether a consumer may override that parameter. The server, not the
   browser, enforces the decision for both the local plugin path and the
   approved Runtime Adapter path.
4. Queue and materialize the job, then register a Bundle. A llama.cpp Bundle
   starts `llama-server` with locked allocation flags such as `--ctx-size` and
   `--n-gpu-layers`; Ollama and vLLM receive the canonical request defaults
   through their native APIs.

Canonical parameters currently include `temperature`, `top_p`, `max_tokens`,
`context_length`, and the provider-specific GPU allocation setting. Unknown
parameters are rejected when a Bundle policy is created. Editable numeric
values are range-checked on every request; locked values cannot be changed by
the consumer.

The model materializer remains a node-side operation. It never executes a
browser-supplied command or target path; target paths are reserved by the
Hypervisor's model store.
