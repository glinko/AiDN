---
name: AiDN Pearl Study
description: Route-local Pearl workspace with agent-published snapshots and native document controls above a milk-white reflective floor.
colors:
  milk-space: "#f4f6fb"
  milk-floor: "#f0f3fa"
  cyan-light: "#b9e1ff"
  lilac-light: "#c6b5f8"
  peach-light: "#ffe1cf"
  agent-yellow: "#efc75b"
  agent-coral: "#eb9d91"
  agent-mint: "#8ed5bd"
  agent-lilac: "#b6a7ec"
  agent-cyan: "#83c9e8"
  coral-pulse: "#f26f68"
  control-ink: "#4f6078"
  hint-ink: "#626f82"
  control-surface: "rgba(252,253,255,.72)"
  frame-ink: "#34475f"
  frame-muted: "#536780"
  frame-action: "#42658d"
  frame-error: "#8c373f"
  frame-surface: "rgba(249, 251, 255, .96)"
typography:
  title:
    fontFamily: "Segoe UI, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "Segoe UI, system-ui, sans-serif"
    fontSize: "14px"
    lineHeight: 1.55
  conversation:
    fontFamily: "Segoe UI, system-ui, sans-serif"
    fontSize: "16px"
    lineHeight: "24px"
  label:
    fontFamily: "Segoe UI, system-ui, sans-serif"
    fontSize: "12px"
rounded:
  control: "50%"
  frame: "16px"
  action: "10px"
  field: "9px"
components:
  scene-control:
    backgroundColor: "{colors.control-surface}"
    textColor: "{colors.control-ink}"
    rounded: "{rounded.control}"
    width: "44px"
    height: "44px"
  document-frame:
    backgroundColor: "{colors.frame-surface}"
    textColor: "{colors.frame-ink}"
    rounded: "{rounded.frame}"
    typography: "{typography.body}"
  button-primary:
    backgroundColor: "{colors.frame-action}"
    textColor: "#fff"
    rounded: "{rounded.action}"
    padding: "10px 14px"
---

# Design System: AiDN Pearl Study

## Overview

**Creative North Star: "Pearl, light, and reflected glass"**

This brief applies only to `/spatial-calibration.html`. The user-selected Pearl world retains its elevated orb, colored subagent orbs, solar endpoint nodes, and glass artifacts above milk-white space. The agent-mediated document extension inherits seed `aidn-pearl-calibration-v2`; it does not replace the dark operational dashboard direction in the root `PRODUCT.md` or establish a new global design system.

The scene presents a snapshot published by the Primary Agent after MCP reads. Before publication, only the Primary Agent is shown; published data determines the visible graph instead of the original fixed demo counts. Text or voice requests open a focused document in a milky foreground frame. The graph is an agent-published view, not direct live dashboard polling. Its materials approximate the supplied visual direction; reference fidelity is not exact or established by the source code alone.

## Colors

Cyan, lilac, and peach light shape the otherwise pale neutral scene. These colors express optical character, never health or readiness. Shader RGB values in `materials.ts` are authored optical calculations; the light colors above are the implemented studio palette, not a claim that every visible pixel matches these tokens.

The document overlay adds dark blue ink, muted supporting text, and a stronger blue action color on an almost opaque milk surface. Error and verified-result text belong to native document feedback; they do not reinterpret the scene's optical hues as status colors.

Workspace conversation cubes use a denser cyan/lilac/mint/peach/gold palette than the surrounding light so small artifacts remain visible against the milk floor. Their blue attenuation accent and reduced transmission strengthen the colored volume without changing the Pearl lighting. The Interaction Seed trace uses the frame action ink; focused trace ink and a outlined, muted disabled-send surface keep both state and silhouette visible.

## Typography

Segoe UI with system fallbacks keeps native documents readable over the scene. The frame uses the title and body roles above, with 16px semibold field-group legends and 12px supporting text. At widths of 600px or less, titles reduce to 18px and editable text/select inputs and the composer use 16px text. A small Russian drag hint accompanies two icon controls; the hint reduces to 11px on mobile. Loading and failure messages use 14px text. The scene title is available to assistive technology without adding visible page furniture.

## Layout

An empty-space click/tap creates a 72px Interaction Seed at the chosen point; Ctrl/Cmd+I provides keyboard access. Typing expands the same section and native textarea into a conversation surface, preserving DOM identity, focus, and draft text. Its width grows with measured text to a desktop cap of 720px or 60% of the viewport; on mobile it stays within 16px margins. Height grows afterward, and history scrolls inside the surface. `visualViewport` resize/scroll tracking keeps the surface within the keyboard-visible area. The title uses one-line ellipsis instead of wrapping into the toolbar. Expanded conversation hides the scene controls; closing it restores the scene surface.

The canvas fills the viewport without scrolling. The primary orb is centered slightly above mid-frame; published subagents, endpoints, and artifacts inhabit the inherited constellation and floor-field grammar. Nodes render at a shared 86% visual scale while their authored world positions stay fixed, preserving breathing room across the field. Below 680px the camera keeps the same vertical framing as desktop, so the portrait viewport behaves like a keyhole and naturally crops lateral content instead of shrinking the composition again. Controls remain centered near the bottom safe area, with 44px circular targets and a smaller spacing gap on mobile. Tapping or clicking any node selects it, draws a restrained ring marker, and flies the camera toward its center; selecting the same node again returns to the shared home view. Selecting the Primary Agent also opens the document/dialogue frame and focuses the composer; other object selection remains camera inspection.

The frame and composer share a centered maximum width of 660px, with 24px viewport margins on desktop and 12px on mobile. Only the frame body scrolls; the header, document navigation, and status remain available. Document navigation scrolls horizontally when necessary. At 600px and below, text/select fields stack label and input at full width; numeric and boolean fields retain two-column rows. Short viewports (550px high or less) compress vertical offsets and hide the drag hint. Safe-area offsets and mobile dynamic viewport height preserve access to controls.

## Elevation & Depth

The document frame uses a diffuse blue shadow and 20px backdrop blur; the composer uses a lighter shadow and 16px blur. Their almost opaque surface protects text legibility while maintaining the scene's milky material character. These DOM surfaces do not change the 3D lighting or camera authority.

Depth combines native Three.js physical transmission and planar reflection with deliberately authored shader layers. The orb uses `MeshPhysicalMaterial` under a slightly expanded transparent pearl shell. That shell draws fixed world-direction color lobes, a view-dependent bright rim, a softbox highlight, and a slowly changing local cloud pattern. A billboard ring adds a separate halo. This is not a physically accurate pearl volume or ray-traced light transport.

The rounded glass cube uses full physical transmission and attenuation, plus a distinct two-sided glass finish: clear face centers, tinted grazing angles, luminous edge regions, and subdued rear edges. It no longer contains the opaque pearl face layer or inner pearl sphere. Its finish samples a fixed world-space softbox direction, not an animated light. The milk floor uses a Three.js `Reflector` and a normalized 25-tap blur, composed in linear light rather than re-lit as diffuse material. Reflection opacity fades toward the viewer and horizon; analytic radial penumbras supplement it. Neutral tone mapping and a restrained bloom pass finish the image.

The environment is captured once from fixed rectangular lightformers, with fixed ambient and directional lights. Lights do not travel around the objects. Changing highlights come from object/camera movement and the time-driven shader pattern. The orb's `OrbEntity` owns a restrained 6% scale pulse, and its shell adds a warm coral chroma breath on that same six-second scene clock; neither effect changes the authored light direction. Current limitations include approximate internal scattering and caustics, synthetic halo/edge treatments, finite reflection and transmission buffers, and angle-dependent differences from the reference.

## Shapes

The almost closed circular seed trace becomes a small Inti Trace at the conversation's upper left while Dictate, Send, and Collapse move beside it. Circle-to-rounded-frame geometry and the trace move together over 320ms; this is one evolving interaction surface. Existing document-frame geometry remains independent.

The solar endpoint is an independent `EndpointEntity` with distinct corona and meteor palettes. Each orbit and trail is a deterministic function of the shared scene clock; pause and reduced motion stop both the corona and meteors. Its 120 trail instances share one geometry/material draw rather than spawning objects every frame. The corona is an authored billboard shader, not simulated solar plasma. `OrbEntity` owns the primary and subagent nodes, while `CubeEntity` owns the featured cube and supporting artifacts when published. Each cube rotates slowly and independently around X, Y, and Z while keeping the fixed top-left-front light direction. `ConnectionEntity` resolves source and target IDs through a live position map: published graph links retain the fine curved line, endpoint-style pastel satellite, and short tapered tail vocabulary.

The primary sphere keeps its six-percent, six-second pulse and coral chroma breath. Subagents use the same pearl vocabulary with stronger per-node color pulses so hue encodes role without status semantics. Artifacts use sharp box geometry and per-node attenuation colors; their differing sizes, depths, and triaxial speeds make the three clusters legible without labels. Keep the fine luminous silhouettes, hairline connections, and generous empty space when tuning the materials.

## Components

Interaction Seed uses native textarea semantics: Enter inserts a newline, Ctrl/Cmd+Enter or Send submits, and Escape collapses. Closing an unsubmitted seed cancels its local draft; failed submission retains text. Dictation fills text for review and explicit Send, with no automatic speech output. Buttons have 44px targets, accessible names, visible focus, and disabled states. The conversation log is keyboard focusable with polite announcements and follows new replies only while already near the bottom. Drag movement above the tap threshold, pinch, secondary clicks, and cancelled pointers do not create seeds.

Conversation transport remains agent-only: the browser sends intents and receives publications through the agent channel; the Primary Agent accepts, reads, and replies through MCP. A Workspace Session is a persistent semantic conversation, distinct from an economic/protocol AiDN Session; chatting creates no execution contract, reservation, payment, or escrow. First accepted conversation creates one persistent artifact; further turns update that conversation, and opening its cube retrieves the same history through the agent. The browser's artifact cache is visual projection, not transcript authority.

Persistent artifact identity and order determine the floor field. The newest cube has depthRank zero; older ranks recede by 0.62 world units per rank with smooth depth interpolation and a gentle scale reduction bounded at 76%. A new artifact receives one continuous discharge from the Primary Agent, an additive duplicate strand sharing the same geometry for a soft halo, and a growing cube. Reloaded history does not replay births. Pause freezes progression; reduced motion settles depth/birth immediately and omits the discharge, trace animation, and morph transitions. The material review retained denser pigments, blue attenuation, and depth-rank scale for legibility while preserving fixed lighting and camera framing.

The compact “Диалоги” archive opens saved conversations by name and order, including cubes beyond the mobile keyhole crop or renderer range and when WebGL is unavailable. Rendering keeps the newest 32 cubes plus a selected older cube; this is not archive deletion. Portrait screenshots preserve the lateral crop and show the archive as the accessible route to offscreen history. One foreground conversation is supported; attachments, branching, relevance-based aging, archive deletion, and token-streaming replies remain outside this slice.

The scene uses demand rendering, DPR 1, and a timer that requests frames at approximately 30Hz while motion is active. This is an invalidation cadence, not a guaranteed measured frame rate or an absolute cap during interaction. Reflection buffers use 768px normally and 384px below the compact breakpoint. Native physical transmission replaces the per-object Drei capture buffers so mirrored views are rendered with the reflection camera. Published graph objects share the existing bounded scene renderer; each link keeps one instanced 40-sample photon tail. The memoized viewport separates transport polling and form typing from scene invalidation.

The document frame renders registered text and fields blocks using native labeled text/number inputs, selects, and checkboxes; read-only metadata renders as text. Text or voice input goes to the Primary Agent, which reads through MCP and publishes the document. Apply sends document/source revisions plus exact old and proposed values back to the agent; pending feedback persists until agent apply and readback produce verified values in the same frame. Drafts remain visible during pending or failed operations, and conflicting refreshed values require an explicit draft reset. The current slice permits supported endpoint settings and read-only provider/bundle metadata, not every template or setting.

The frame uses rounded container corners, smaller rounded action and field corners, and 44px minimum text-control/button heights. Native checkbox controls retain their platform behavior. Visible focus outlines, disabled fields, field descriptions, previous-value hints, and explicit status/alert text make state readable without relying on color. The composer provides text submission and opt-in microphone input; answers remain text. The dialogue stays available when WebGL fails.

Pause freezes the animation clock while preserving camera inspection. Reduced-motion preference stops automatic motion, removes control transitions and camera damping, and disables the pause toggle; object focus then snaps to its destination without a camera flight. Hidden documents stop rendering and timer invalidation. Drag inspection is bounded with a wider azimuth/polar range, while perspective zoom is enabled for mouse wheel and two-finger pinch with bounded distances; reset restores the initial camera view and clears selection. Loading, WebGL fallback, and retry states communicate scene availability without exposing operational status.

To run locally from `web/operator-dashboard`, use `pnpm dev --host 127.0.0.1 --port 5173` and open `http://127.0.0.1:5173/operators/dashboard/react/spatial-calibration.html`. If Vite reports another port, use that reported port. Check behavior with `pnpm test -- tests/unit/spatial-calibration-model.test.ts tests/unit/spatial-calibration-optics.test.ts` and TypeScript with `pnpm typecheck`. These commands are verification instructions, not a claim of passing results. Visually inspect desktop and portrait framing, drag/reset, pause, reduced motion, and loading/failure behavior in a WebGL 2 browser; unit tests cannot establish material fidelity.

Interaction Seed verification for this local implementation: repository command `.venv/Scripts/python.exe -m pytest -q -o addopts='' tests/test_workspace_conversations.py tests/test_agent_interface.py tests/test_codex_agent_bridge.py` passed 33 tests. From `web/operator-dashboard`, the full `pnpm exec vitest run` passed 37 files / 200 tests; `pnpm build` passed; `pnpm exec playwright test tests/e2e/spatial-seed-chat.spec.ts --project=chromium` passed both desktop/mobile tests. The six supplied seed, conversation, and artifact-field screenshots were inspected. Browser data is synthetic; these results do not establish deployment, a public route, or live inference.

## Do's and Don'ts

- Do preserve the seed's DOM identity through its morph and keep conversation history accessible through the archive despite visual crop or depth.
- Don't equate a Workspace conversation with an economic AiDN Session or treat visual aging as deletion.

- Do preserve the sparse orb/cube/floor composition and restrained cyan, lilac, and peach accents.
- Do distinguish authored optical effects from physical material behavior in future descriptions.
- Do keep this route's visual brief separate from the operational product's global direction.
- Do retain native labels, inputs, selects, checkboxes, keyboard focus, and explicit pending/error/verified feedback in agent documents.
- Don't add a sidebar, automatic speech output, arbitrary HTML documents, or direct browser configuration writes to this route.
- Don't describe the result as an exact reference match or the lights as animated.
