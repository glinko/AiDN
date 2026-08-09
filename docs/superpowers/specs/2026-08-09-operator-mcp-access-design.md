# Operator MCP Access Design

## Goal

Allow an operator to manage the credentials that an external agent uses to
control one Hypervisor, without exposing existing secrets in the dashboard or
turning the dashboard into an unauthenticated control channel.

## Scope

This slice adds a local pairing flow, short-lived dashboard access sessions,
multi-credential agent authentication, and the Settings UI for their lifecycle.
It does not make the dashboard a replacement for mTLS, implement remote-node
enrollment, or expose an operator credential to a browser.

## Security Model

### Trust boundaries

The following identities are intentionally different:

| Identity | Purpose | May be revealed after creation |
| --- | --- | --- |
| Operator authority | Approves privileged control-plane actions | No |
| Dashboard access session | Short-lived authority to manage local MCP credentials | No |
| MCP agent credential | Server-to-server credential for one agent integration | Once, at creation or rotation |
| Remote Hypervisor credential | Credential issued by the target Hypervisor | Once, by that target node |

An operator credential must never be reused as an MCP agent credential. A
remote Hypervisor connection uses an agent credential created by the remote
Hypervisor, plus its separately trusted transport identity; this first slice
only explains that boundary in Settings.

### Storage and transport

Credential material, pairing-code digests, and access metadata live in a
single encrypted `FileSecretManager` record. The dashboard API returns only
credential ID, display label, scope set, fingerprint, state, timestamps, and
the source type. It never returns an existing credential value.

The default production profile requires HTTPS and mTLS for dashboard access
management. A controlled LAN test profile may opt in explicitly to HTTP with
`AIDN_DASHBOARD_ACCESS_ALLOW_INSECURE_LAN=true`; the UI prominently labels this
as an insecure test profile. The access cookie is always `HttpOnly`,
`SameSite=Strict`, and path-scoped to the dashboard access API. It is `Secure`
whenever TLS is in use.

### Pairing

`aidn-operator pair` is a local-host command. It creates a random one-time
pairing code with a ten-minute TTL and writes only its digest and expiry to the
encrypted record. The command prints the node URL, expiry and raw code to its
own terminal; it does not write the code to normal logs or state JSON.

The Settings UI exchanges the code once for a fifteen-minute dashboard access
session. Successful consumption atomically removes the pairing record. A
failed exchange returns a generic error and does not disclose whether the code
was wrong, expired, or already consumed. Restarting the Hypervisor invalidates
all dashboard sessions, while an unexpired unused pairing code remains
available because it is encrypted at rest.

## Components

### `McpCredentialStore`

`McpCredentialStore` is a focused service backed by `FileSecretManager`. It
owns:

* named MCP agent credentials and their stable IDs;
* SHA-256 fingerprints and authorization digests;
* scopes, lifecycle state, created and last-used timestamps;
* a one-time pairing-code digest and expiry; and
* atomic creation, revocation and rotation.

It does not own MCP transport sessions, Wallet secrets, or the operator
authority. Revocation and rotation return a changed credential generation so
the gateway can invalidate all transport sessions authenticated under the
affected credential.

The initial migration supports deployments with `AIDN_MCP_REMOTE_TOKEN`:

* without a configured credential store, the existing environment token remains
  supported and Settings reports that management is unavailable;
* with a configured store, bootstrap imports the environment token exactly once
  as a `legacy-imported` agent credential, then authorization uses the encrypted
  store rather than the environment value;
* the imported credential may be rotated or revoked after migration.

This avoids a state in which a revoked credential remains usable because the
old environment variable is still present in a container.

### `DashboardAccessService`

This service consumes pairing codes and maintains a bounded, in-memory session
map. Sessions have random opaque IDs, a fifteen-minute idle-independent expiry,
and no user-controlled role or scope. Every protected request checks the
session before reaching `McpCredentialStore`. Session IDs never appear in API
JSON and are only sent in an HTTP-only cookie.

### `McpRemoteGateway`

The gateway accepts a credential resolver instead of only one token hash. Each
successful agent request resolves its credential, records `last_used_at`, and
binds a transport session to that credential ID. Revocation or rotation removes
all bound transport sessions immediately. Existing single-token construction
continues to work for deployments that have not enabled encrypted credential
management.

Operator approval keeps its distinct authority path. This slice shows only
operator-token availability and fingerprint in Settings; it cannot reveal,
export, or silently replace that token.

### Dashboard API

New endpoints remain separate from `/mcp` and are rejected for browser origins
unless the dashboard access policy allows the request:

* `GET /operators/dashboard/access/status` returns non-secret status and
  credential metadata;
* `POST /operators/dashboard/access/pair` exchanges a pairing code for the
  short-lived cookie session;
* `POST /operators/dashboard/access/logout` invalidates the current session;
* `POST /operators/dashboard/access/credentials` creates a labeled agent
  credential and returns the raw token only in that response;
* `POST /operators/dashboard/access/credentials/{credential_id}/rotate`
  revokes the predecessor, creates a replacement, invalidates its transport
  sessions, and returns the replacement only once;
* `POST /operators/dashboard/access/credentials/{credential_id}/revoke`
  revokes a credential and invalidates its transport sessions.

Protected endpoints return `401 DASHBOARD_ACCESS_REQUIRED` with no secret or
credential-specific detail. Invalid pairing exchanges return
`403 DASHBOARD_PAIRING_INVALID`. Credentials cannot be deleted if it would
remove the last active agent credential unless the operator explicitly confirms
the lockout in a separate field; the default UI creates a replacement before
revoking a predecessor.

## Settings UX

Settings gains an **Access** section, not a raw-token page.

1. The locked state explains that the operator must run `aidn-operator pair`
   locally and enter the resulting one-time code.
2. The unlocked state displays expiry and a `Lock now` action.
3. **Agent credentials** lists label, fingerprint, scopes, created time,
   last-used time and state. Actions are `Create`, `Rotate`, and `Revoke`.
4. After `Create` or `Rotate`, a modal shows the new token exactly once with a
   copy action and an acknowledgement before close. The UI never re-fetches it.
5. **Operator authority** displays only configured/unconfigured state and a
   fingerprint. Copy and reveal actions do not exist.
6. **Remote Hypervisors** explains that the operator must issue a dedicated
   target-node agent credential and never paste the local operator token.

All destructive actions have a confirmation dialog naming the credential label
and fingerprint. Errors are rendered inline and keep form data, while the
dashboard's read-only views remain available when access management is locked.

## Failure Handling

* Missing `FileSecretManager` disables pairing and mutation APIs; status gives
  the exact configuration keys required, but never secret values.
* A corrupted encrypted record fails closed: agent authorization is denied and
  access management reports a recoverable operator configuration error.
* Expired, used, or invalid pairing codes fail identically.
* Restart clears dashboard sessions and MCP transport sessions but preserves
  credential metadata and unused pairing code.
* A failed rotation leaves the existing credential active; revocation happens
  only after the replacement record is durably persisted.
* Audit events record identity IDs, fingerprints and result codes only.

## Tests

Backend tests cover code single-use and expiry, session expiry, unauthorized
requests, metadata redaction, create/rotate/revoke, last-credential guard,
legacy import, transport-session invalidation, and fail-closed secret-store
errors. React tests cover locked status, pairing submission, one-time reveal,
and destructive-action confirmation. Existing MCP remote tests continue to
cover the legacy one-token constructor.

## Explicit Non-Goals

* Reading or exporting the current operator token.
* Browser use of `/mcp` or the operator approval endpoints.
* Password-derived secret-manager keys.
* Credential synchronization across Hypervisors.
* Persisting dashboard sessions across restart.
