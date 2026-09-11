# Interaction Seed → Workspace conversation → artifact

Status: implemented locally for the Pearl calibration route; deployment is a separate operation.

This extends [agent-mediated documents](AGENT-DOCUMENTS-V1.md): the text path of §§5–8 of the [implementation plan](AiDN-Spatial-Agent-Interface-Implementation-Plan.md), [Workspace Sessions](ADR-006-workspace-sessions-context-graph.md), and a first projection of [memory aging](ADR-007-spatial-memory-aging-clustering.md). It does not mark the full milestones or ADR-007 complete.

## Operator interaction

- Click/tap empty canvas or press Ctrl/Cmd+I to place an Interaction Seed. Drags, pinches, cancelled pointers and secondary clicks do not create one.
- An almost closed ring surrounds a native blinking caret. Its working controls are Dictate, Send and Collapse. File/Image/Context/Action/More are deferred, not non-functional buttons.
- Typing expands the same surface and textarea; the ring becomes an Inti Trace and controls move to the upper left in 320 ms. Width follows text until capped, followed by height growth and internal scrolling. Mobile layout follows `visualViewport` for the keyboard.
- Enter inserts a newline; Ctrl/Cmd+Enter or Send submits; Escape collapses. Unsubmitted text is a local draft, not an artifact. Closing an unsent seed currently cancels that draft.
- Dictation fills the textarea for review and explicit submission. Automatic speech output stays disabled.
- Replies and follow-up messages appear in the same surface. The cube opens its saved conversation through the agent. The compact “Диалоги” navigator is an accessible fallback for cubes outside the portrait crop, the rendered depth range, or unavailable WebGL.

## Authority and persistence

The browser posts intents and polls publications on the existing agent channel; it never creates canonical sessions or calls configuration APIs.

1. `POST /operators/dashboard/agent-channel/messages` carries text, `request_id`, `surface_id`, and `chat: {conversation_id, action: message|open}`. The client ID is correlation, not authority. HTTP submission leaves the Workspace archive unchanged.
2. The bound Primary Agent calls `aidn.ui.conversation` with the exact request ID. The tool reads the canonical operator event; the model cannot substitute a session ID or transcript. First acceptance creates the semantic session, first turn and one artifact. Subsequent messages append; `open` only publishes history.
3. `aidn.operator.chat.reply` saves the correlated agent turn. Direct use of that MCP tool also accepts the intent, allowing alternative agents to save conversations without early birth. Replays do not add turns or cubes.
4. The node saves the archive inside `snapshot.resident_agent.agent_conversation.workspace`, using existing persistence. No second database or browser-local transcript authority is introduced.
5. `aidn.ui.read(kind=scene)` publishes the Workspace catalog after authorized scene reads. Views are ephemeral per surface and re-authorized after node restart. The archive survives agent rebinding, but the new identity cannot use the old agent's request IDs.

Frontend validators reuse `spatial.workspace-session.v1`, `spatial.conversation-turn.v1` and `spatial.artifact.v1`. Provenance retains intent, binding and event references. These are **not economic/protocol AiDN Sessions**: chatting does not create execution contracts, reservations, payments or escrow.

The transport display journal remains approximately 200 messages. Accepted Workspace turns and deduplication live independently of it; pending unaccepted chat intents are retained. Limits: 128 conversations, 2,000 turns per conversation, 8 Mi characters of transcript, with reserved capacity for pending replies. A full archive rejects new writes rather than deleting history. Export and paginated storage are later work.

## Model context

The Codex bridge accepts/opens Workspace intents through MCP before inference. It keeps a separate durable model-thread mapping per conversation; the general operator thread stays separate. Opening an artifact or replaying an answered event does not invoke the model. A marked, potentially truncated recent-history excerpt accompanies turns; the agent can retrieve full canonical history through the same MCP tool when needed. The excerpt is conversation data, not system instructions or a replacement for storage.

## Visual projection

`WorkspaceArtifactEntity` extends `CubeEntity`; material, color, independent X/Y/Z rotation, drift, depth target and birth progress belong to the object. A newly accepted session produces one soft continuous discharge from the primary agent to the creation point, then the cube grows into place. Reloaded history does not replay births.

New cubes occupy the near horizontal floor field at approximately `y=0.62`. Each new session moves older target Z by `−0.62`. Exponential interpolation prevents teleporting; the main scene and camera are not reset. Existing published artifacts also recede by a bounded shared offset. Reduced motion settles birth/depth immediately without a discharge; pause freezes animation.

The 32 newest cube renderers plus a selected older cube are retained. This is rendering virtualization only: all catalog entries and transcript records remain accessible. It is not semantic deletion, clustering, or relevance-based aging.

## Verification

From the repository:

```powershell
.venv/Scripts/python.exe -m pytest -q -o addopts='' tests/test_workspace_conversations.py tests/test_agent_interface.py tests/test_codex_agent_bridge.py
```

From `web/operator-dashboard`:

```powershell
pnpm exec vitest run tests/unit/spatial-seed-chat.test.tsx tests/unit/spatial-agent-document.test.tsx
pnpm exec playwright test tests/e2e/spatial-seed-chat.spec.ts --project=chromium
pnpm build
```

Backend tests cover real MCP acceptance/reply, persistence beyond the transport window, binding boundaries, quotas and separate model threads. UI tests cover DOM identity, explicit submission, failed-draft retention, canonical schemas, pointer intent, keyboard viewport clamping, birth identity and depth interpolation. Browser fixtures are explicitly synthetic, not evidence of deployment or live inference on node 122.

## Current boundaries

One foreground chat at a time. Attachments, branching, automatic session segmentation, pin/relevance policy, export and archive deletion are not implemented. Replies use the existing completed-reply/polling transport, not token streaming. Settings requests may open the existing typed document frame; form-change events are not yet merged into the Workspace transcript. Deployment must include backend, MCP registration, bridge and rebuilt frontend together: frontend-only deployment cannot provide persistence.
