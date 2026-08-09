# Agent Enrollment Operator Playbook

## Purpose

This file tells an AiDN-capable agent how to guide an operator through secure
MCP enrollment. It applies to a controlled LAN Hypervisor such as node 127.
It is not a way to obtain SSH access, an operator token, a Wallet key or an
existing MCP token.

The normal result is one dedicated Agent MCP credential encrypted to the
agent's ephemeral X25519 key. The operator approves a request in the Dashboard
but never sees the credential value.

## Agent Rules

The agent SHALL:

1. Generate a new X25519 key pair for each enrollment attempt.
2. Store the private key and retrieval secret only in its own secret runtime.
3. Submit the public key to the enrollment request endpoint.
4. Tell the operator the request label, public-key fingerprint, expiry and
   Dashboard URL.
5. Wait for approval or rejection without retrying the same request.
6. Decrypt an approved envelope locally, store the credential in its secret
   runtime and perform MCP `initialize`.
7. Report only status, fingerprint and stable error codes.

The agent SHALL NOT disclose, request or log any of these values:

* Agent private key;
* retrieval secret;
* pairing code;
* MCP credential value;
* operator credential;
* Wallet private key;
* SSH password or host Secret Manager key.

## Operator Prompt

After creating a request, the agent sends this message with substituted public
values only:

```text
AiDN agent access request is waiting for your approval.

Node Dashboard: <dashboard-url>
Open: Settings -> Agent enrollment requests
Request label: <label>
Key fingerprint: <sha256-fingerprint>
Expires: <UTC timestamp>

Please compare the label and fingerprint, then select Approve. Do not send me
any token, pairing code, password or private key. I will retrieve and decrypt
the credential locally after approval.
```

The agent must not make the operator copy a token into chat. Approval is the
only required operator action after Settings is unlocked.

## Unlocking Settings

If the operator says that Settings is locked, the agent gives this additional
instruction:

```text
On the Hypervisor host, run:

aidn-operator pair

Copy the short-lived code shown only by that command into the Dashboard Settings
pairing form. Do not send the code to the agent. Then return to Agent enrollment
requests and approve the request shown above.
```

`aidn-operator pair` creates a ten-minute, one-time browser pairing code. It
is a local owner-presence check, not an agent credential and not an MCP tool.

## Wire Sequence

The agent uses these endpoints in this order:

```text
POST /operators/dashboard/access/agent-enrollment/requests
GET  /operators/dashboard/access/agent-enrollment/requests/{request_id}
POST /mcp  (initialize after local envelope decryption)
```

The first response includes `request_id` and `retrieval_secret`. Polling must
send the retrieval secret in `X-AiDN-Enrollment-Secret`. The request remains
`pending` until a Dashboard operator approves or rejects it. An approved
response contains a sealed credential envelope, not a raw token.

The agent uses the envelope only once to populate its secret-backed MCP client
configuration. It then discards the ephemeral private key and retrieval secret.

## Operator Decision Rules

The operator approves only if all of the following match the expected agent:

* known agent label;
* displayed key fingerprint;
* expected node Dashboard;
* unexpired request.

The operator rejects unknown, stale, duplicate or unexpected requests. A
rejection does not affect existing agent credentials.

## Recovery Prompts

| Agent-observed condition | Required agent response |
| --- | --- |
| Enrollment is `pending` | Send the Operator Prompt once; wait until expiry or decision. |
| Enrollment is `rejected` | Report rejection without argument; generate a new request only after the operator confirms the reason. |
| Enrollment is `expired` | Generate a new key pair and request; never revive or reuse the old retrieval secret. |
| `MCP_ENROLLMENT_DISABLED` | Tell the operator that dashboard credential storage is not provisioned; request an approved Hypervisor rollout, not a manual token or configuration change. |
| `DASHBOARD_ACCESS_REQUIRED` | Tell the operator to unlock Settings with `aidn-operator pair`; do not ask for the code. |
| `MCP_ENROLLMENT_NOT_PENDING` | Refresh request status. Do not retry approve or create a replacement credential. |
| MCP `initialize` fails after decryption | Report the stable MCP error and credential fingerprint. Do not request the operator token or change host state. |

## Completion Report

After a successful enrollment, the agent reports:

```text
Agent enrollment: completed
Node: <node-id or URL>
Credential fingerprint: <fingerprint>
MCP initialize: successful
Authority: dedicated Agent MCP credential
Operator secrets received: none
Next safe action: read node health and current inventory
```

This report must not contain a token, a retrieval secret, a private key, a
pairing code or a full encrypted envelope.
