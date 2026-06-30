# Operator Dashboard Terminal Redesign Design

## Summary

This spec defines the visual redesign of the first AiDN operator dashboard slice.

The current dashboard already establishes the right product structure:
- `Home`
- `Fleet`
- `Market`
- real hypervisor and registry-backed data

What it lacks is the intended visual weight.

The new direction is a `market terminal control room`:
- dark navy control surface;
- amber action accents;
- dense metrics strip;
- left-side command rail;
- center workspace for market or fleet tables;
- right-side inspector panel for the selected node or offer;
- bottom operational cards for queue, health, wallet, and policies.

The redesign should borrow the composition and atmosphere of the user-provided reference screenshot without copying that product's branding, geography-first worldview, or exact information model.

## Design Decision

### Selected Direction

Restyle the current AiDN dashboard into a `terminal-style operator control room`.

This is not a change in IA or product scope.

It is a visual and interaction redesign that preserves:
- the AiDN operator workflows;
- the `Home / Fleet / Market` shell;
- the existing read models;
- the multi-node hypervisor context.

### Why

The current first slice is functionally correct but visually too light for the product role.

AiDN needs to look like:
- a serious operator console;
- a live compute market;
- a policy-aware hypervisor layer.

The approved reference achieves that through:
- visual density;
- explicit hierarchy;
- clear market table composition;
- strong control surfaces;
- a premium, infrastructural feel.

## Non-Goals

This redesign does not:
- rename the product around the reference branding;
- clone the reference one-to-one;
- make geography the center of the UX;
- replace AiDN terms with foreign terminology;
- change the current backend contracts before the UI needs them.

## Visual Reference Interpretation

We are copying the design language, not the product identity.

The transferable ideas from the reference are:
- a persistent left-side command rail;
- a high-density top metrics strip;
- a large, central execution or market table;
- a tall right-side detail inspector;
- a lower band of operational cards;
- strong use of status color;
- premium dark infrastructure styling.

The non-transferable parts are:
- `NEXUS` branding;
- exact iconography;
- country/city geography as the primary meaning carrier;
- market labels that do not match AiDN concepts.

## Layout Model

The target dashboard layout should have five structural zones.

### 1. Command Rail

A fixed left navigation column.

Purpose:
- make the dashboard feel like a control system, not a generic web app;
- keep the main operator modes visible at all times;
- host identity, status, and secondary system navigation.

Required contents:
- AiDN identity block;
- active operator or node group badge;
- primary navigation:
  - `Home`
  - `Fleet`
  - `Market`
- secondary operator modules that can be disabled or stubbed for now:
  - `Requests`
  - `Models`
  - `Policies`
  - `Settings`
- one live inline secondary module:
  - `Wallet` as a drawer-based settlement console opened from the rail or lower operations card
- bottom status cards or network health chips.

### 2. Metrics Strip

A full-width top row above the main workspace.

Purpose:
- instantly communicate market and network state;
- create the "live terminal" feeling;
- summarize what changed without opening deeper panels.

Recommended metric tiles:
- market depth or candidate count;
- median clearing price in `q`;
- local or operator spend over a rolling window;
- allocatable supply;
- network time or heartbeat freshness.

Visual behavior:
- small sparkline or micro-chart treatment where possible;
- green/red delta indicators;
- thin dividers and compact spacing.

### 3. Main Workspace

The largest center panel.

Purpose:
- show the current dominant table or comparison surface.

By mode:
- `Home`: hybrid overview with prioritized publish, market, and fleet blocks;
- `Fleet`: bundles, installs, resource health, and queue pressure;
- `Market`: candidate table with compare-friendly columns and filters.

For `Market`, the composition should resemble a professional execution table:
- row selection state;
- strong current-row highlight;
- compact sortable columns;
- direct action button per row;
- filters anchored above the table.

### 4. Inspector Panel

A fixed or sticky right-side detail panel.

Purpose:
- keep selected node or offer context visible while browsing rows;
- reduce navigation churn;
- make selection feel deliberate and consequential.

Required behavior:
- selecting a row updates the inspector;
- the inspector shows pricing, rating, policy, readiness, and attach/publish actions;
- the inspector can switch between local offer and external offer states.

### 5. Operational Cards

A bottom band of dense secondary panels.

Purpose:
- expose queue, provider health, wallet snapshot, and policy controls without leaving the main surface.

Recommended cards:
- local request queue;
- local provider health;
- wallet snapshot plus an entry point into the inline wallet console;
- policy controls.

These are secondary to the main workspace, but they should feel alive and actionable.

## Style System

### Color

Primary palette:
- deep navy background;
- near-black blue panels;
- amber for action, selected state, and premium emphasis;
- green for healthy or favorable state;
- red for cost increase or blocked state;
- muted steel-blue for inactive chrome.

Do not revert to light neutral backgrounds in this redesign.

### Surface Treatment

Panels should use:
- subtle inner glow or gradient depth;
- thin borders;
- slightly rounded corners;
- layered shadows that stay restrained.

The UI should feel engineered, not glossy or playful.

### Typography

Typography should feel technical and premium.

Recommended mix:
- strong uppercase micro-labels for sections and columns;
- compact sans-serif body text;
- large numeric display values for metrics and pricing;
- tighter tracking and denser spacing than the current dashboard.

### Data Emphasis

The redesign should prioritize:
- numbers;
- deltas;
- row state;
- status chips;
- selected-card focus;
- compareable columns.

It should deprioritize:
- explanatory paragraphs;
- oversized empty space;
- broad marketing-style card layouts.

## Product Mapping From Reference To AiDN

The reference composition should map to AiDN like this:

- `Execution Market` -> `Market` candidate table
- `Selected Node` -> AiDN selected node or selected offer inspector
- `Request Queue` -> local queued workloads
- `Local Provider Health` -> runtime and capacity health
- `Wallet` -> current operator wallet snapshot
- `Policy Controls` -> queue spillover, strict accounting, custom model hosting, limits

This mapping preserves the spirit of the reference while keeping the AiDN model intact.

## Interactivity Requirements

This redesign remains a `full interactivity` build.

At minimum:
- left rail navigation must work;
- row selection must update the inspector;
- `Home`, `Fleet`, and `Market` views must render distinct layouts;
- filters and selected state must be visually obvious;
- the wallet drawer must open from both the left rail and the lower wallet card;
- the wallet drawer must support real quote, settlement reopen, dispute open, and dispute resolve actions against current operator APIs;
- policy controls must feel like real operator controls, even if some remain read-only in the first visual pass.

## Implementation Boundary

The first redesign pass should stay inside the existing first-slice dashboard boundary:
- keep the current dashboard routes;
- keep the current read models;
- improve shell layout, styling, and client-side rendering;
- add front-end state for row selection and richer mode-specific layouts.

Do not expand scope into new backend features unless the redesign is blocked without them.

## QA Standard

The redesign is only acceptable if it:
- clearly reads as a market terminal rather than a generic admin page;
- preserves AiDN workflows and terminology;
- looks coherent on desktop and degrades cleanly on narrower screens;
- visibly improves hierarchy, density, and perceived product maturity.

## Related Documents

- Base dashboard architecture: [2026-06-20-operator-fleet-market-dashboard-design.md](./2026-06-20-operator-fleet-market-dashboard-design.md)
- First implementation slice plan: [../plans/2026-06-20-operator-dashboard-first-slice.md](../plans/2026-06-20-operator-dashboard-first-slice.md)
