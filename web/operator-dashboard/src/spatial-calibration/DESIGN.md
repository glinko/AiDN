---
name: AiDN Pearl Study
description: Route-local study of a pearl orb and glass cube above a milk-white reflective floor.
colors:
  milk-space: "#f4f6fb"
  milk-floor: "#f0f3fa"
  cyan-light: "#b9e1ff"
  lilac-light: "#c6b5f8"
  peach-light: "#ffe1cf"
  coral-pulse: "#f26f68"
  control-ink: "#4f6078"
  hint-ink: "#626f82"
  control-surface: "rgba(252,253,255,.72)"
typography:
  label:
    fontFamily: "Segoe UI, system-ui, sans-serif"
    fontSize: "12px"
rounded:
  control: "50%"
components:
  scene-control:
    backgroundColor: "{colors.control-surface}"
    textColor: "{colors.control-ink}"
    rounded: "{rounded.control}"
    width: "44px"
    height: "44px"
---

# Design System: AiDN Pearl Study

## Overview

**Creative North Star: "Pearl, light, and reflected glass"**

This brief applies only to `/spatial-calibration.html`. The user-selected direction is a minimal material study: an elevated pearl orb, a smaller glass cube, and their soft reflections in milk-white space. It does not replace the dark operational dashboard direction in the root `PRODUCT.md` or establish a new global design system.

The scene is a local visual prototype with no Node binding, operational status, sidebar, or live data. Its materials approximate the supplied visual direction; reference fidelity is not exact or established by the source code alone. The orb represents the Primary Agent; the glass cube represents a dialogue artifact. A smaller white solar endpoint sits above the cube: a soft animated corona surrounds its core and exactly three cyan, lilac, and peach electric meteors orbit with tapered trails. These are visual roles, not live runtime objects.

## Colors

Cyan, lilac, and peach light shape the otherwise pale neutral scene. These colors express optical character, never health or readiness. Shader RGB values in `materials.ts` are authored optical calculations; the light colors above are the implemented studio palette, not a claim that every visible pixel matches these tokens.

## Typography

System typography stays subordinate to the objects. A small Russian drag hint accompanies two icon controls; the hint reduces to 11px at widths of 600px or less. Loading and failure messages use 14px text. The scene title is available to assistive technology without adding visible page furniture.

## Layout

The canvas fills the viewport without scrolling. The orb sits left of center and above the cube on the lower right. Both retain their relative scale on narrow screens: below 680px the camera moves farther away. Controls remain centered near the bottom safe area, with 44px circular targets and a smaller spacing gap on mobile. Tapping or clicking the orb, cube, or endpoint selects it, draws a restrained ring marker, and flies the camera toward its center; selecting the same object again returns to the shared home view.

## Elevation & Depth

Depth combines native Three.js physical transmission and planar reflection with deliberately authored shader layers. The orb uses `MeshPhysicalMaterial` under a slightly expanded transparent pearl shell. That shell draws fixed world-direction color lobes, a view-dependent bright rim, a softbox highlight, and a slowly changing local cloud pattern. A billboard ring adds a separate halo. This is not a physically accurate pearl volume or ray-traced light transport.

The rounded glass cube uses full physical transmission and attenuation, plus a distinct two-sided glass finish: clear face centers, tinted grazing angles, luminous edge regions, and subdued rear edges. It no longer contains the opaque pearl face layer or inner pearl sphere. Its finish samples a fixed world-space softbox direction, not an animated light. The milk floor uses a Three.js `Reflector` and a normalized 25-tap blur, composed in linear light rather than re-lit as diffuse material. Reflection opacity fades toward the viewer and horizon; analytic radial penumbras supplement it. Neutral tone mapping and a restrained bloom pass finish the image.

The environment is captured once from fixed rectangular lightformers, with fixed ambient and directional lights. Lights do not travel around the objects. Changing highlights come from object/camera movement and the time-driven shader pattern. The orb's `OrbEntity` owns a restrained 6% scale pulse, and its shell adds a warm coral chroma breath on that same six-second scene clock; neither effect changes the authored light direction. Current limitations include approximate internal scattering and caustics, synthetic halo/edge treatments, finite reflection and transmission buffers, and angle-dependent differences from the reference.

## Shapes

The solar endpoint is an independent `EndpointEntity`. `DEFAULT_ENDPOINT` owns position, radius, core/corona colors, three meteor colors, orbit radius/speed, and trail angle. The orbit and trail positions are deterministic functions of the shared scene clock; pause and reduced motion stop both the corona and meteors. Its 120 trail instances share one geometry/material draw rather than spawning objects every frame. The corona is an authored billboard shader, not simulated solar plasma; its muted periwinkle edge keeps the white core from disappearing into the background. Two `ConnectionEntity` objects link the agent to the artifact and endpoint with cubic control points; each connection is a nearly one-pixel core line carrying one endpoint-style satellite: a pastel head followed by a short, tapered 40-sample tail travelling along the curve. The orb drift and optical layers remain unchanged; the cube now rotates slowly and continuously around X, Y, and Z while keeping its fixed light direction and deeper blue volume.

One smooth sphere and one nearly sharp rounded cube carry the entire composition. The sphere's pulse is bounded by `pulseAmplitude: 0.06` and `pulseFrequency: 1.04719755` in `DEFAULT_CALIBRATION`, a six-second cycle that reads as an intentional breathing material rather than a hard scale jump. Its `OrbEntity.colorPulse` owns a coral accent and blend amount so the chroma breath can move from the current cool pearl toward a warm red tint without changing the fixed light direction. The cube's rounded shell has a radius of 0.016 scene units; its explicit edge outline follows a box. Keep the fine luminous silhouette and generous empty space when tuning the materials.

## Components

The scene uses demand rendering, DPR 1, and a timer that requests frames at approximately 30Hz while motion is active. This is an invalidation cadence, not a guaranteed measured frame rate or an absolute cap during interaction. Reflection buffers use 768px normally and 384px below the compact breakpoint. Native physical transmission replaces the per-object Drei capture buffers so mirrored views are rendered with the reflection camera.

Pause freezes the animation clock while preserving camera inspection. Reduced-motion preference stops automatic motion, removes control transitions and camera damping, and disables the pause toggle; object focus then snaps to its destination without a camera flight. Hidden documents stop rendering and timer invalidation. Drag inspection is bounded, with pan and zoom disabled; reset restores the initial camera view and clears selection. Loading, WebGL fallback, and retry states communicate scene availability without exposing operational status.

To run locally from `web/operator-dashboard`, use `pnpm dev --host 127.0.0.1 --port 5173` and open `http://127.0.0.1:5173/operators/dashboard/react/spatial-calibration.html`. If Vite reports another port, use that reported port. Check behavior with `pnpm test -- tests/unit/spatial-calibration-model.test.ts tests/unit/spatial-calibration-optics.test.ts` and TypeScript with `pnpm typecheck`. These commands are verification instructions, not a claim of passing results. Visually inspect desktop and portrait framing, drag/reset, pause, reduced motion, and loading/failure behavior in a WebGL 2 browser; unit tests cannot establish material fidelity.

## Do's and Don'ts

- Do preserve the sparse orb/cube/floor composition and restrained cyan, lilac, and peach accents.
- Do distinguish authored optical effects from physical material behavior in future descriptions.
- Do keep this route's visual brief separate from the operational product's global direction.
- Don't add Node binding, sidebar controls, or status semantics as incidental visual polish.
- Don't describe the result as an exact reference match or the lights as animated.
