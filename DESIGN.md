---
name: AiDN Hypervisor Dashboard
description: Bundle-centered control plane for operating distributed AI execution.
colors:
  surface-deep: "#040a12"
  surface: "#07111d"
  panel: "#0b1725"
  panel-strong: "#0e1d2e"
  ink: "#f2f7fc"
  muted: "#8da0b8"
  rule: "#22354a"
  route-cyan: "#2bd7c5"
  healthy-green: "#5ad28f"
  attention-red: "#ff7e8b"
  data-blue: "#6aa8ff"
typography:
  display:
    fontFamily: "Manrope, IBM Plex Sans, sans-serif"
    fontSize: "clamp(24px, 2vw, 32px)"
    fontWeight: 760
    lineHeight: 1.1
    letterSpacing: "-0.045em"
  body:
    fontFamily: "Manrope, IBM Plex Sans, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.5
  label:
    fontFamily: "Manrope, IBM Plex Sans, sans-serif"
    fontSize: "10px"
    fontWeight: 750
    letterSpacing: "0.11em"
rounded:
  compact: "6px"
  control: "8px"
  surface: "10px"
  panel: "14px"
spacing:
  compact: "8px"
  control: "12px"
  panel: "16px"
  workspace: "20px"
components:
  button-primary:
    backgroundColor: "{colors.route-cyan}"
    textColor: "{colors.surface-deep}"
    rounded: "{rounded.control}"
    padding: "0 14px"
  button-secondary:
    backgroundColor: "{colors.panel-strong}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 14px"
  panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "16px"
  chip:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.muted}"
    rounded: "{rounded.compact}"
    padding: "5px 8px"
---

# Design System: AiDN Hypervisor Dashboard

## Overview

**Creative North Star: "The Bundle Control Plane"**

AiDN is a dense, calm operational surface rather than an AI chat product or a decorative monitoring screen. The active Hypervisor, stable navigation, Bundle execution chain, and real resource state remain legible before any secondary workflow. The visual world follows the supplied professional virtualization-control-plane reference: deep navy surfaces, thin technical rules, quiet cyan route state, and semantic color that never replaces a label.

The design treats Bundle as the operator's main deployment object. Provider plugins, models, Runtimes, Endpoint offers, Validation and Sessions are visible as distinct architectural objects with clear hand-offs, not as one blended configuration page.

**Key Characteristics:**
- Persistent Hypervisor identity and resource truth.
- Dense but bounded panels; no fake charts or decorative telemetry.
- Cyan signals selected route and active local context; green and red only describe explicit state.
- Mobile preserves access to Hypervisor selection and Advanced Mode through horizontal controls.

## Colors

The palette is a restrained navy field with one operational route accent and explicit semantic state colors.

### Primary
- **Route Cyan:** Used for active tabs, selected Bundle chain nodes, primary actions, and focus borders. It remains sparse so the current operational path is obvious.

### Secondary
- **Data Blue:** Used for supporting data and informational copy without competing with route state.

### Tertiary
- **Healthy Green:** Used only for confirmed healthy, validated, or ready states.
- **Attention Red:** Used only for explicit failure, blocked, or attention-required states.

### Neutral
- **Deep Surface:** The application field behind every workspace.
- **Panel Surface:** Tonal container for stable information groups.
- **Technical Rule:** Low-contrast border that separates dense operational regions without card clutter.
- **Muted Ink:** Secondary explanation, never a replacement for a state label.

**The One Route Rule.** Cyan marks the current operational path, not general decoration. A panel may have many facts but only one primary route state.

## Typography

**Display Font:** Manrope with IBM Plex Sans fallback.
**Body Font:** Manrope with IBM Plex Sans fallback.
**Label/Mono Font:** IBM Plex Mono for exact runtime, hash, and chain identifiers only.

**Character:** Manrope provides compact, deliberate operational hierarchy; IBM Plex Mono is reserved for machine identity so normal interface copy never reads like a terminal.

### Hierarchy
- **Display:** Used for workspace titles and selected-object names.
- **Body:** Used for readable operational consequences and guidance.
- **Label:** Uppercase, tracked labels identify metrics and panel roles.
- **Mono:** Used for route chain nodes and exact technical values only.

**The Data-Not-Decor Rule.** Monospace clarifies an identifier or protocol value; it is never used as an aesthetic substitute for hierarchy.

## Layout

Desktop uses four stable regions: Hypervisor tabs in the header, a fixed navigation rail, the main workspace with contextual inspector, and a persistent resource footer. The header always identifies which Hypervisor the operator is managing. The workspace may change, but its surrounding context does not.

At 1200px the inspector moves below the workspace. At 860px the rail becomes horizontally scrollable, Hypervisor tabs remain available in a compact second header row, and Advanced Mode remains reachable through the mobile navigation. Resource telemetry may scroll horizontally rather than becoming invented or omitted.

## Elevation & Depth

The system is flat by default. Tonal navy layering, thin rules, and sticky positional context express depth; shadows are intentionally absent. Backdrop blur is limited to the top Hypervisor header, where it preserves context during long operator workflows.

**The Evidence-First Depth Rule.** A panel gains visual weight from a real operational role or persistent location, never from a colored glow.

## Shapes

Forms are gently squared and technical: 6px for compact chips, 8px for controls, 10px for local surfaces, and 14px for major panels. Borders are low-contrast and continuous. Buttons, chips, table rows, and panels share this restrained geometry so density remains calm instead of fragmented.

## Components

### Buttons
- **Shape:** Compact rounded technical controls (8px radius).
- **Primary:** Route Cyan is reserved for the next explicit operator action.
- **Secondary:** Panel-toned, bordered controls for inspection and reversible navigation.
- **Hover / Focus:** Border and text contrast change; no colored glow.

### Chips
- **Style:** Compact uppercase labels with a visible border and semantic text color.
- **State:** Chips always name their state, even where color conveys the same meaning.

### Cards / Containers
- **Corner Style:** Major panels use 14px; local groups use 10px.
- **Background:** Layered navy surfaces, never white cards on a dark canvas.
- **Border:** A single technical rule; no shadow stack.
- **Internal Padding:** 16px for operational groups, 20px for workspace framing.

### Navigation
- **Style:** Stable text-first rail with an active cyan route marker and a separate Hypervisor tab row.
- **Mobile:** Horizontally scrollable controls preserve every essential object path instead of hiding it.

### Resource Footer
- **Style:** Persistent horizontal row of API-derived CPU, GPU, memory, storage, network, session, and queue facts.
- **Truth Rule:** Missing telemetry displays as not reported, never as zero or an artificial chart.

## Do's and Don'ts

### Do:
- **Do** keep Bundle as the central deployment workspace and show its exact execution chain.
- **Do** keep Endpoint offers, Validation, and Sessions as distinct canonical workflows.
- **Do** expose missing observability as `Not reported` or equivalent explicit uncertainty.
- **Do** preserve mobile access to Hypervisor switching and Basic/Advanced mode.

### Don't:
- **Don't** use a market offer as the default representation of local Hypervisor health.
- **Don't** hide topology or accounting consequences behind a generic success state.
- **Don't** use sparklines, progress rings, or colored glow as stand-ins for operational evidence.
- **Don't** edit deployed Bundles in place; route changes through a new immutable revision.
