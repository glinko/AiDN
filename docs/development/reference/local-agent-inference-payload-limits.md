# Local-agent inference payload limits

The Hypervisor `/v1/chat/completions` route accepts agent requests that may
contain MCP tool schemas and tool results in addition to ordinary chat text.
The gateway therefore enforces a byte budget on the complete validated JSON
request body, rather than counting only message characters.

## Configuration

`AIDN_INFERENCE_MAX_REQUEST_BYTES` controls the application-level request
budget. It is a positive integer number of bytes and defaults to `4194304`
(4 MiB), which leaves room for a 128K-token local context plus MCP metadata
without removing the bounded request guard.

`AIDN_INFERENCE_MAX_MESSAGES` controls the number of validated chat messages
and defaults to `512`. The old fixed limit of 128 rejected MCP conversations
before the byte budget or Hermes compaction could run. The message limit is a
second bounded guard, not a replacement for context-length or byte-budget
checks.

The limit is independent of the model's `context_length`. A request can fit
the byte budget and still be rejected later by the provider if its token
context or runtime policy is too small. Conversely, a request can fit the
model context but exceed the byte budget when MCP schemas or tool output are
large.

## Client behavior

The gateway returns HTTP 413 with error code `request_too_large` when the
serialized request is over the budget. The message includes the observed and
configured byte counts so an agent can compact tool output or start a fresh
session instead of retrying the identical body.

For long MCP tasks, prefer reading files in focused ranges or asking the MCP
server for a summary. Do not append multiple full repository files to one
conversation when a small set of relevant excerpts is sufficient.
