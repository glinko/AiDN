# Codex OAuth agent bridge

`aidn-codex-agent` runs outside the Hypervisor and connects a ChatGPT-authenticated
Codex instance to the generic operator-agent channel.

The boundary is deliberate:

- Codex owns ChatGPT OAuth and its refresh token in the dedicated `CODEX_HOME`;
- AiDN owns a separate, revocable MCP bearer credential and never receives the
  ChatGPT token;
- the bridge reads the MCP agent inbox, asks Codex, posts the resulting text to
  `aidn.operator.chat.reply`, then acknowledges the event.

The bridge must run on a trusted machine with the `codex` CLI installed. Do not
run it as `root`; give its service account a dedicated, mode-`0700` home.

## One-time setup

1. In **Settings → MCP agent credentials**, issue an agent token named
   `codex-operator-<node>`, with at least `AUDIT:READ` and `CHAT:WRITE`.
2. Bind the Dashboard operator channel to its identity:
   `mcp-credential:<credential_id>`. The credential id is visible in Settings;
   it is not the token or its fingerprint.
3. Place the newly revealed bearer token in a local environment file readable
   only by the bridge service account, for example:

   ```ini
   AIDN_MCP_TOKEN=<newly-issued-token>
   ```

4. On the bridge machine, authenticate Codex through the device flow:

   ```bash
   install -d -m 700 /var/lib/aidn-codex
   aidn-codex-agent --codex-home /var/lib/aidn-codex login
   ```

   The command displays an OpenAI device URL and a short-lived code. Open that
   URL in the operator's browser and complete the ChatGPT sign-in. Do not paste
   a ChatGPT access or refresh token into AiDN.

5. Start the relay:

   ```bash
   set -a
   . /etc/aidn/codex-agent.env
   set +a
   aidn-codex-agent \
     --codex-home /var/lib/aidn-codex \
     relay \
     --mcp-url http://127.0.0.1:8766/mcp
   ```

   For an always-on node, install the included
   [`deploy/aidn-codex-agent.service`](../../../deploy/aidn-codex-agent.service)
   after creating an unprivileged `aidn-codex` account and mode-`0600`
   `/etc/aidn/codex-agent.env`. The unit assumes the installed console command
   is `/usr/local/bin/aidn-codex-agent`; adjust it if the Hypervisor virtual
   environment uses another path.

`--once` processes the current inbox once, which is useful for a smoke test.

## Operational properties

- Operator messages remain canonical AiDN events until the bridge has posted a
  reply and acknowledged them. Restarting the bridge therefore does not lose a
  message.
- The persistent Codex thread id is stored next to `CODEX_HOME`; it contains no
  MCP bearer token and must still be protected because it identifies a Codex
  conversation.
- The initial bridge intentionally gives Codex no local-shell or node-control
  authority. AiDN changes require explicit MCP scopes and are added only after
  their tool contracts are reviewed.
- Images, voice and files remain out of this first bridge because the operator
  channel has no content-addressed attachment store yet. Text is the only
  supported payload.
