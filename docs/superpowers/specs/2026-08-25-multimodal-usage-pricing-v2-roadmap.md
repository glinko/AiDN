# Multimodal Usage Pricing V2 Roadmap

## Summary

AiDN currently exposes fixed `Q` per request in the operator Dashboard, while
the backend already has partial support for input tokens, output tokens,
fixed-request charges, audio input duration, Usage Reports, and integer
`q_atoms` Settlement terms.

Pricing V2 turns those partial paths into one versioned, immutable Rate Card
that can price text, speech, images, and video without creating a separate
billing implementation for each workload family.

## Core Decisions

1. `RateCardV2` is the public pricing contract for an Endpoint.
2. Money is represented only as integer `q_atoms` in new contracts.
3. Measured quantities use integer base units: tokens, characters, counts,
   pixels, and milliseconds.
4. An Endpoint may combine a base request charge with multiple metered
   components.
5. The accepted Rate Card version and hash are immutable for the lifetime of a
   Session.
6. Estimated Usage is diagnostic unless the accepted contract explicitly
   declares a fallback policy.
7. Provider retries do not create a second Consumer input charge.
8. LLM wall-clock latency is not a normal billable unit. Audio and video media
   duration may be billable because it describes the accepted input or output
   artifact rather than Provider slowness.
9. Pre-production migration is a clean cut: APIs, persisted Endpoint drafts,
   Dashboard writes, and tests accept only `RateCardV2`. Removed pricing fields
   are rejected rather than read through compatibility aliases or fallbacks.
10. A paid Endpoint publishes a positive minimum escrow deposit. That deposit is
    a refillable Consumer risk buffer, not a maximum request price: after each
    accepted invoice, another request is admitted only when the remaining
    escrow has been restored to the advertised minimum.
11. The Endpoint cannot debit the Consumer wallet. Charges are limited to the
    funds already authorized and locked in Session escrow; closing the Session
    settles the final invoice and refunds the remainder.
12. The default minimum escrow is a high-usage request estimate plus a 20%
    safety margin. The default recommended escrow is five times the minimum.
    Both values and all Usage assumptions are published; the recommendation is
    only a convenience balance for multiple requests.

## Canonical Billing Dimensions

### Text and LLM

- `request_count`
- `input_tokens`
- `cached_input_tokens`
- `output_tokens`
- `text_input_characters`

### Audio

- `audio_input_milliseconds`
- `audio_output_milliseconds`

### Images

- `image_input_count`
- `image_output_count`
- `image_input_pixels`
- `image_output_pixels`
- `image_input_tokens`
- `image_output_tokens`

Image prices may carry immutable qualifiers such as width, height, quality, or
provider pricing tier. The recommended local-runtime offer is a price per
generated image for an explicit size and quality tier. Opaque upstream proxies
may instead use authoritative image-token Usage.

### Video

- `video_input_milliseconds`
- `video_output_milliseconds`

Video prices carry immutable resolution, quality, frame-rate, and audio
qualifiers where those properties affect the advertised price.

### Session

- `idle_milliseconds`

## Delivery Slices

### Slice 1: Pricing V2 Foundation

Status: **implemented** on 2026-08-25.

- add typed `RateCardV2` and `RateComponent` models;
- use integer `q_atoms`, explicit divisors, scaling, and rounding;
- add canonical hashing and duplicate-component validation;
- bridge Rate Cards directly to integer Settlement terms;
- make `rate_card` the only Endpoint pricing field and reject removed fields.

### Slice 2: LLM Token Billing

Status: **implemented** on 2026-08-25. Exact input/output/cached-input token
declarations, integer Rate Card charging, component-level request breakdowns,
public preflight estimates, and atom-level escrow charging are in place.

- meter input, cached-input, and output tokens;
- update llama.cpp, Ollama, vLLM, and proxy Usage contracts;
- generate Usage evidence and request-level charge breakdowns;
- make settlement readiness depend on exact required dimensions;
- bind paid execution to the Endpoint's advertised minimum escrow deposit.

### Slice 3: Audio Billing

Status: **implemented** on 2026-08-25. Whisper STT measures inline WAV duration
at the Hypervisor ingress boundary, normalizes it to integer milliseconds, and
binds the measurement to the input artifact SHA-256, MIME type, and byte size.
Provider-reported duration remains non-billable estimated evidence. The built-in
OpenAI-compatible TTS path requests WAV output, meters input characters and
locally verified output duration, and binds both to the generated artifact. TTS
streaming emits ordered hash-bound audio chunks, records cumulative delivered
bytes, and closes with terminal Usage evidence for both completion and
cancellation. Partial WAV duration is calculated only from complete PCM frames
that crossed the delivery boundary, never from the full size declared in the
WAV header.

- meter STT input duration at the trusted ingress boundary;
- meter TTS input characters or tokens and generated-audio duration;
- normalize duration to integer milliseconds;
- attach media metadata and artifact hashes to Usage evidence;
- add cancellation and partial-stream checkpoints.

### Slice 4: Image and Video Billing

- add image count, pixels, and provider-token measurements;
- add video input/output duration measurements;
- bind resolution and quality tiers into Rate Card hashes;
- validate generated artifact metadata before settlement;
- support fixed-per-artifact and metered hybrid offers.

### Slice 5: Quote, Escrow, and Streaming

Status: **partially implemented**. Request estimates, minimum-escrow Session
admission, explicit `SESSION_DEPOSIT_EXTEND`, and exact atom-level Session Usage
charges are available. LLM deposit recommendations derive from context/output
limits, Rate Card prices, a configurable safety margin, and a configurable
working-balance multiplier. Session read models now expose deterministic
admission state, the exact minimum top-up, and the top-up required to restore
the recommended working balance. Consumer signing/submission orchestration and streaming
checkpoints remain for this slice.

- return deterministic estimates for supplied Usage before execution;
- publish and lock the minimum Session escrow deposit;
- publish the recommended multi-request working balance and the assumptions
  behind both deposit values;
- after every invoice, require an explicit Consumer top-up back to the
  advertised minimum before admitting another request;
- never pull funds directly from the Consumer wallet during execution;
- checkpoint long-running or streaming Usage;
- settle accepted Usage only from escrow and refund the unused remainder;
- expose a component-level settlement breakdown.

### Slice 6: Dashboard and Market

- add Fixed, Usage-based, and Hybrid pricing editors;
- adapt fields to the selected workload family;
- display operator-friendly units while storing canonical base units;
- show scenario-based price estimates in Market comparisons;
- show settlement-readiness reasons when a Provider cannot prove a priced
  dimension.

### Slice 7: Hardening and Rollout

- define failure, retry, timeout, and cancellation charging rules;
- reject missing or conflicting authoritative Usage;
- fuzz canonical hashes and arithmetic boundaries;
- reject obsolete Endpoint drafts and publications with an actionable schema
  error; before production there is no dual-read window;
- remove superseded internal accounting snapshots once Session admission is
  bound directly to immutable Rate Cards;
- remove the node-level floating-point telemetry quote after all non-Endpoint
  wallet callers use the canonical Settlement calculation.

## Required Test Matrix

- exact `q_atom` arithmetic and rounding boundaries;
- stable Rate Card hash and qualifier ordering;
- rejection of every removed Endpoint pricing field;
- LLM input/output/cached token charging;
- STT and TTS duration/character charging;
- image tier and resolution matching;
- video duration and resolution matching;
- streaming cancellation and partial output;
- Provider retries and duplicate Usage reports;
- missing, estimated, or conflicting Usage evidence;
- immutable Session pricing;
- paid Endpoint publication without a minimum escrow deposit;
- request rejection below the minimum escrow and admission after an explicit
  top-up;
- invoice rejection when it exceeds the remaining locked escrow;
- quote to escrow to Usage to Settlement to refund end-to-end flow.

## Exit Criteria

Pricing V2 is complete when every paid request has an immutable Rate Card, a
verifiable Usage record for every variable component, integer-only Settlement
math, a human-readable charge breakdown, and a deterministic refund or dispute
outcome.
