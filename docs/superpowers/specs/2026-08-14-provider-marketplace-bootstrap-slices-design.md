# Provider Deployment, Marketplace Authoring, And Ubuntu Onboarding Design

Date: 2026-08-14

Status: Approved working design; implementation started

## Goal

Deliver three simple operator journeys without weakening the existing trust
and execution boundaries:

1. choose a reviewed Provider runtime and install it on an Ubuntu node with one
   primary dashboard action;
2. author and publish an Endpoint Marketplace listing with a rich HTML
   description;
3. install the Hypervisor from one terminal command and complete first-run
   setup in an interactive wizard.

The product surface should make the common path short. Permission review,
diagnostics, logs, model selection, and advanced configuration remain available
but do not compete with the primary action.

## Roadmap Alignment And Existing Baseline

The repository already contains most of the local Provider control-plane:
Plugin manifests, install recipes, plan preview, approval, diagnostics, durable
jobs, rollback records, a controlled-filesystem executor, Provider inventory,
model discovery, Runtime Binding, and Endpoint draft handoff. The generic
executor deliberately rejects broad host mutation. Shell, container, download,
and package-manager execution remain explicitly deferred in the roadmap.

Endpoint publication and structured profiles already exist. The profile has
summary, strengths, limitations, recommended tasks, languages, formats, and
examples, but no authored HTML field or sanitizer contract.

The Ubuntu bootstrap already supports a one-line `curl | bash` interactive
installation, operator identity, service installation, dashboard, and optional
CometBFT. It still needs post-install wallet and agent onboarding.

## Slice A: One-click Provider Deployment

### Initial reviewed catalog

| Provider | Reviewed runtime | Ubuntu strategy | Service endpoint | Model step |
| --- | --- | --- | --- | --- |
| Whisper | ASR webservice image `v1.9.1` | Pull/start hardened Docker container | `127.0.0.1:9000` | Choose Whisper model after runtime install |
| Ollama | `0.32.12` | Official Linux installer plus systemd override | `127.0.0.1:11434` | Pull selected model after runtime is ready |
| llama.cpp | `b10433` | Build pinned source with CMake, user systemd service | `127.0.0.1:8080` | Attach an absolute GGUF artifact before start |
| vLLM | `0.27.1` | Isolated `uv` environment, first profile is NVIDIA CUDA | `127.0.0.1:8000` | Select a Hugging Face model before start |

Whisper itself does not define an official HTTP server. The first managed
profile therefore uses an explicitly identified third-party ASR wrapper; the
UI and manifest must not describe that wrapper as an official OpenAI runtime.

Upstream installation references:

- [Ollama Linux installation](https://docs.ollama.com/linux)
- [llama.cpp build guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)
- [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [vLLM quickstart](https://docs.vllm.ai/en/latest/getting_started/quickstart/)
- [vLLM OpenAI-compatible server](https://docs.vllm.ai/en/stable/serving/openai_compatible_server/)
- [OpenAI Whisper requirements](https://github.com/openai/whisper/blob/main/README.md)

### Runtime installer contract

The Hypervisor exposes catalog metadata, not a free-form command:

```yaml
installer_id: aidn-provider-runtime-ubuntu.v1
provider: whisper | ollama | llama.cpp | vllm
platform: ubuntu
script: tools/aidn-provider-runtime-ubuntu.sh
pinned_version: reviewed immutable release reference
actions: [install, start, status, stop]
model_configuration_separate: true
```

The dispatcher maps exactly one Provider ID to one repository-owned script.
It never accepts a script path, executable, shell fragment, environment map, or
working directory from the browser or Plugin manifest.

### Execution architecture

The next backend increment adds an
`AllowlistedProviderRuntimeInstallationExecutor` beside the existing generic
executor. Its request is a typed `RuntimeInstallerInvocation` containing only:

- approved installation ID and plan hash;
- exact installer ID and Provider ID;
- one lifecycle action;
- typed, Provider-specific arguments;
- expected runtime version;
- requesting operator identity.

The executor resolves the script from a compiled/repository-owned map, validates
arguments again, and delegates privileged operations to a narrow local broker.
The broker should run as a root-owned system service or root-owned Unix socket,
authenticate the caller with local OS credentials, accept only the typed
allowlist, and append an audit record before execution. It must not expose
`command`, `argv`, `script_path`, `shell`, or arbitrary environment fields.

Jobs are asynchronous and durable. States are:

`queued -> preflight -> downloading -> installing -> configuring -> verifying -> ready`

Terminal alternatives are `failed`, `cancelled`, and `rollback_required`.
The installer emits newline-delimited bounded JSON events; stdout/stderr are
redacted, size-bounded, timestamped, and attached to the job. Replaying the
same approved invocation must be idempotent.

### Dashboard journey

The default Providers workspace shows reviewed catalog cards and node fit:

1. select one Provider;
2. inspect the short preflight result and requested permissions;
3. press one primary `Install` button;
4. follow progress until `Runtime ready`;
5. optionally choose/import a model;
6. continue to Runtime Binding and Endpoint publication.

`Attach existing Provider` moves under an advanced path. The primary button is
disabled for unsupported OS/GPU/prerequisite states and explains the blocking
condition. It is not shown as enabled while the backend is `RECORDED_ONLY`.

## Slice B: Marketplace Endpoint Authoring

### Data contract

Add a Marketplace description object to the versioned Endpoint configuration:

```yaml
marketplace_description:
  source_html: operator-authored bounded HTML
  sanitized_html: server-produced safe HTML
  sanitizer_version: aidn-marketplace-html.v1
  content_hash: sha256 of sanitizer version plus sanitized HTML
```

Only `source_html` is accepted from the client. The server sanitizes it and
stores/publishes the sanitized result and hash. Publication binds the exact
description hash to the Endpoint configuration/advertisement version so an
edit always creates a new draft or versioned publication transition.

### Sanitization policy

The v1 allowlist is intentionally small: paragraphs, headings, lists, emphasis,
code/preformatted text, blockquotes, horizontal rules, and links. Strip script,
style, form, iframe, SVG, media, event-handler attributes, inline styles, IDs,
classes, and unknown attributes. Permit only `https`, `mailto`, and approved
internal schemes on links; add safe `rel` values to external links. Enforce a
bounded source size, bounded nesting depth, and bounded rendered output.

Sanitization is server-side and covered by XSS fixtures. The dashboard renders
only `sanitized_html`; it never renders source HTML or relies on client-only
sanitization.

### Authoring journey

The Endpoint editor provides a source editor and live preview, plus the existing
structured profile fields. The primary action is `Publish Endpoint`; preview,
validation, and policy blockers appear inline. The confirmation shows the exact
Endpoint version, visibility, pricing, and description hash being published.

## Slice C: One-line Ubuntu Hypervisor Setup

The existing bootstrap remains the public entrypoint. Production documentation
uses a reviewed immutable tag or commit rather than `main`:

```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/glinko/AiDN/<reviewed-ref>/tools/aidn-operator-bootstrap-ubuntu.sh \
  | bash -s -- --ref <reviewed-ref>
```

Interactive steps:

1. verify Ubuntu version, architecture, disk, ports, sudo, and network;
2. select node identity, paths, API exposure, Registry, and consensus mode;
3. show a concise execution summary and obtain confirmation;
4. install pinned application and system dependencies;
5. generate operator identity and encrypted local secret storage;
6. write/start the user service and verify health;
7. create a new wallet, import an existing wallet, or explicitly skip;
8. create a one-time dashboard pairing code;
9. connect an agent through the existing enrollment/approval boundary;
10. print a completion summary with local URLs, public identity paths, service
    commands, backup requirements, and exact recovery instructions.

Secrets are read from `/dev/tty`, never command-line flags. Private keys are
written atomically with mode `0600`, never logged, and displayed only when an
explicit one-time recovery-secret flow requires it. Rerunning the installer
detects existing identity/wallet state and defaults to reuse, never overwrite.

## Delivery Order

1. provider scripts and typed catalog contract;
2. privileged broker and specialized executor;
3. one-click Provider dashboard flow;
4. sanitized Marketplace description backend;
5. Marketplace editor/preview/publish UI;
6. wallet and agent onboarding commands;
7. bootstrap wizard integration and fresh-Ubuntu acceptance.

This order closes the highest-value operator path first while reusing the
existing approval, job, Endpoint, wallet, and MCP enrollment boundaries.

## Acceptance Gates

- A fresh supported Ubuntu VM can install each compatible runtime from the
  dashboard without copying commands into a shell.
- Every host mutation is tied to an approved immutable plan and audit record;
  tampered Provider/action/argument values fail closed.
- Runtime installation does not silently download a default model.
- All managed Provider HTTP endpoints are loopback-only unless a separate,
  explicit networking feature is approved.
- Known Marketplace XSS payloads are removed server-side and cannot execute in
  the dashboard or public listing.
- A fresh Ubuntu VM completes Hypervisor installation, wallet choice, dashboard
  pairing, and agent enrollment from the one-line bootstrap journey.
- Interrupted installs can be safely rerun and never overwrite existing private
  identity material.

## Non-goals For The First Increment

- arbitrary community installer execution;
- arbitrary shell, Docker arguments, package sources, or environment variables;
- automatic model selection or large model download during runtime install;
- public exposure of Provider HTTP ports;
- WYSIWYG page-builder semantics or arbitrary CSS/JavaScript in listings;
- silent wallet creation or automatic network publication.
