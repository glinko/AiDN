---
version: 1
slug: "src-aidn-hypervisor-static-operator-dashboard-html"
primary_target: "src/aidn_hypervisor/static/operator_dashboard.html"
related_targets: []
---

# Operator Overview

## Scope

`src/aidn_hypervisor/static/operator_dashboard.html` renders the primary
Hypervisor Overview in **Operate** mode.

## Operator Job

An operator needs to identify the active Hypervisor, inspect live Bundle
deployments, see resource and Validation state, and navigate to the canonical
Bundle, Endpoint, Request, or infrastructure workflow without a separate
onboarding dashboard.

## Direction

The supplied UI-0001 reference is binding: top-level Hypervisor tabs, a
compact left navigation rail, a dense Bundle table in the central workspace,
a fixed right-side resource and Validation column, and a persistent resource
footer. Cyan marks the active route; health, pending, and failed states remain
explicitly named.

## Constraints

Bundle remains the primary local deployment object. Endpoint offers,
Validation, Sessions, Provider configuration, and Wallet operations remain
separate canonical screens. The Overview only reports API-provided facts;
missing telemetry is shown as `Not reported`, not inferred. Mobile retains
Hypervisor switching, navigation, and every metric without hiding state.
