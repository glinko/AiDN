# Operator MCP Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add locally paired encrypted MCP agent credential management to the Hypervisor dashboard.

**Architecture:** An encrypted store owns agent credentials and pairing-code digests. A short-lived browser session is issued after pairing. The MCP gateway resolves agent credentials through the store and closes associated transport sessions when a credential changes. A dedicated API and React Settings workspace expose redacted management operations.

**Tech Stack:** Python, FastAPI, `FileSecretManager`, pytest, React, TypeScript, Zod, Tailwind, pnpm.

---

### Task 1: Add `McpCredentialStore`

**Files:**
- Create: `src/aidn_hypervisor/mcp/credentials.py`
- Create: `tests/test_mcp_credentials.py`

- [ ] **Step 1: Write failing credential lifecycle tests.** The initial test creates `McpCredentialStore(secret_manager=_manager(tmp_path))`, issues a credential, asserts that `resolve(issued.token)` returns its ID, and asserts that `list_credentials()[0].token is None`.
- [ ] **Step 2: Run `uv run pytest tests/test_mcp_credentials.py -q`.** Expected: RED because `McpCredentialStore` is absent.
- [ ] **Step 3: Implement the smallest encrypted state model.** Use `secret://mcp/access-state`, random `secrets.token_urlsafe(32)` values, metadata digest/fingerprint only, and methods `create_credential`, `list_credentials`, `resolve`, `rotate_credential`, `revoke_credential`, and `record_use`.
- [ ] **Step 4: Run the lifecycle tests again.** Expected: GREEN.
- [ ] **Step 5: Add pairing test before implementation.** Create a 600-second code and assert first `consume_pairing_code(code)` is true while second is false. Run the focused test and observe RED.
- [ ] **Step 6: Persist digest, creation time, and expiry only; compare with `hmac.compare_digest` under the store lock.** Re-run `uv run pytest tests/test_mcp_credentials.py -q`. Expected: GREEN.
- [ ] **Step 7: Commit.** Stage only `src/aidn_hypervisor/mcp/credentials.py` and `tests/test_mcp_credentials.py`; commit message: `feat: add encrypted MCP credential store`.

### Task 2: Add Pairing Sessions and Local CLI

**Files:**
- Create: `src/aidn_hypervisor/operator_access.py`
- Create: `src/aidn_hypervisor/operator_cli.py`
- Modify: `pyproject.toml`
- Modify: `tools/aidn-operator-bootstrap-ubuntu.sh`
- Modify: `tests/test_mcp_credentials.py`

- [ ] **Step 1: Write failing access-session test.** It exchanges one pairing code, asserts one valid session, asserts second exchange fails, advances a clock beyond 15 minutes, then asserts authorization fails.
- [ ] **Step 2: Run the focused test.** Expected: RED because `DashboardAccessService` is absent.
- [ ] **Step 3: Implement bounded opaque in-memory sessions.** Sessions expire after 15 minutes and never persist across restart; code remains in encrypted store.
- [ ] **Step 4: Register `aidn-operator = "aidn_hypervisor.operator_cli:main"` and extend bootstrap.** Bootstrap writes a mode-0700 `aidn-operator` wrapper below the operator data directory and links it into `~/.local/bin`; the wrapper supplies only the local secret-manager path and master-key file to the CLI. The `pair` subcommand prints dashboard URL, UTC expiry, and raw 10-minute code only to local stdout, and exits nonzero if configuration is absent.
- [ ] **Step 5: Run `uv run pytest tests/test_mcp_credentials.py -q`.** Expected: GREEN.
- [ ] **Step 6: Commit.** Stage the two new source files, `pyproject.toml`, and test; commit message: `feat: add operator dashboard pairing`.

### Task 3: Resolve MCP Credentials and Invalidate Sessions

**Files:**
- Modify: `src/aidn_hypervisor/mcp/remote.py`
- Modify: `tests/test_mcp_remote.py`

- [ ] **Step 1: Write failing gateway test.** Create a store-issued credential, initialize an MCP transport session with it, call `gateway.invalidate_credential_sessions(credential_id)`, then assert session calls return 404 and revoked-token requests return 401.
- [ ] **Step 2: Run `uv run pytest tests/test_mcp_remote.py::test_revocation_rejects_credential_and_closes_transport_sessions -q`.** Expected: RED because resolver/invalidation is absent.
- [ ] **Step 3: Add optional `McpAgentCredentialResolver` to `McpRemoteGateway`.** Preserve the current single-token constant-time behavior. Store `(credential_id, McpJsonRpcServer)` per transport session, call `record_use` after authorization, and add `invalidate_credential_sessions`.
- [ ] **Step 4: Run `uv run pytest tests/test_mcp_remote.py tests/test_mcp_credentials.py -q`.** Expected: GREEN, including legacy token tests.
- [ ] **Step 5: Commit.** Stage remote gateway and its tests; commit message: `feat: resolve MCP agents from credential store`.

### Task 4: Build Protected Dashboard API and Wire Application

**Files:**
- Create: `src/aidn_hypervisor/operator_access_api.py`
- Create: `tests/test_operator_access_api.py`
- Modify: `src/aidn_hypervisor/main.py`
- Modify: `src/aidn_hypervisor/mcp/__init__.py`

- [ ] **Step 1: Write failing API test.** Assert unpaired credential creation returns 401; issue pairing code; exchange it on `/operators/dashboard/access/pair`; then assert creation returns 201 with a token while subsequent status contains no token.
- [ ] **Step 2: Run `uv run pytest tests/test_operator_access_api.py -q`.** Expected: RED because routes are absent.
- [ ] **Step 3: Implement dedicated API endpoints.** Include status, pair, logout, create, rotate, and revoke. Pairing failure is generic. Mutations require session cookie. Set HTTP-only, SameSite-Strict cookie scoped to access routes; require TLS unless `AIDN_DASHBOARD_ACCESS_ALLOW_INSECURE_LAN=true`.
- [ ] **Step 4: Wire `FileSecretManager`, `McpCredentialStore`, `DashboardAccessService`, and gateway resolver in `build_app`.** Import environment agent token once as `legacy-imported`, then authorize from encrypted store. Without a secret manager, preserve legacy MCP and expose only redacted disabled status. Extend `_is_validator_consensus_write_path` with the exact dashboard access mutation paths only; this local secret boundary cannot use a wildcard exemption.
- [ ] **Step 5: Run `uv run pytest tests/test_operator_access_api.py tests/test_mcp_remote.py tests/test_mcp_credentials.py -q`.** Expected: GREEN.
- [ ] **Step 6: Commit.** Stage API/router wiring and tests; commit message: `feat: add protected dashboard credential API`.

### Task 5: Implement React Settings Access Workspace

**Files:**
- Modify: `web/operator-dashboard/src/lib/types.ts`
- Modify: `web/operator-dashboard/src/lib/api.ts`
- Modify: `web/operator-dashboard/src/hooks/use-dashboard.ts`
- Modify: `web/operator-dashboard/src/App.tsx`
- Modify: `tests/test_react_dashboard_assets.py`

- [ ] **Step 1: Write failing UI contract test.** Assert the app source contains `Pair this browser`, `Agent credentials`, `Operator authority`, `Remote Hypervisors`, and `Reveal once`.
- [ ] **Step 2: Run the focused dashboard asset test.** Expected: RED because Settings is generic.
- [ ] **Step 3: Add redacted Zod schemas and requests.** Only create/rotate response types may contain a `token`; status/list types cannot.
- [ ] **Step 4: Replace generic Settings with the Access workspace.** Include pairing form, session status/logout, credential list, destructive confirmation, one-time reveal modal, operator-authority fingerprint, remote-node credential guidance, and controlled-LAN warning. Clear raw token state on modal close/unmount.
- [ ] **Step 5: Run dashboard asset test, `pnpm --dir web/operator-dashboard typecheck`, `pnpm --dir web/operator-dashboard lint`, and `pnpm --dir web/operator-dashboard build`.** Expected: GREEN; only previously known Fast Refresh warnings may remain.
- [ ] **Step 6: Commit.** Stage React files/tests only; commit message: `feat: manage MCP agent access from settings`.

### Task 6: Document and Verify the Operator Flow

**Files:**
- Modify: `docs/operations/local-agent-node127-mcp-runbook.md`
- Modify: `docs/operations/independent-operator-onboarding-and-acceptance.md`
- Modify: `tests/test_independent_operator_bootstrap.py`

- [ ] **Step 1: Add failing documentation assertions.** Require `aidn-operator pair`, `one-time`, and the prohibition on giving the operator token to an agent.
- [ ] **Step 2: Run `uv run pytest tests/test_independent_operator_bootstrap.py -q`.** Expected: RED.
- [ ] **Step 3: Document secret-manager prerequisites, pairing/session expiry, one-time reveal, rotate/revoke, remote-node credential boundary, and controlled-LAN exception.** Re-run the test. Expected: GREEN.
- [ ] **Step 4: Run final targeted pytest suite, dashboard typecheck/lint/build, and `git diff --check`.** Expected: all commands green and no whitespace errors.
- [ ] **Step 5: Commit documentation.** Commit message: `docs: describe paired MCP credential management`.

## Final Checks

- [ ] Existing agent and operator tokens are never returned by any endpoint.
- [ ] An unpaired browser cannot mutate credentials.
- [ ] Revocation closes active MCP transport sessions.
- [ ] Legacy single-token MCP tests stay green.
- [ ] `bundles.json` is not staged or modified.
