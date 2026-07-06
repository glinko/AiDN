# Endpoint Guided Proxy Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing proxy handoff inside `Endpoints` into a visible hybrid guided flow that leads the operator through proxy attach, configuration publication, and optional validation without leaving the endpoint control plane.

**Architecture:** Keep the state machine client-side in `operator_dashboard.html` for this slice, but isolate it behind explicit guided-flow helpers instead of scattered inline conditions. Extend the existing shell tests in `tests/test_api.py` first, then implement a dedicated guided-flow panel, step rail, CTA mapping, and explicit finish/reset behavior while preserving the current endpoint editors and proxy controls.

**Tech Stack:** FastAPI shell HTML response tests, Python `pytest`, single-file dashboard UI in `src/aidn_hypervisor/static/operator_dashboard.html`, existing endpoint/proxy client actions.

---

## File Structure

### Files to modify

- `src/aidn_hypervisor/static/operator_dashboard.html`
  - Existing operator shell implementation.
  - Add guided-flow helper functions, guided panel rendering, phase-aware CTA mapping, and explicit finish/reset behavior.
- `tests/test_api.py`
  - Existing shell-route source assertions.
  - Add failing tests first for guided rail copy, finish CTA wiring, and phase transition strings.

### Files not to modify in this slice

- `src/aidn_hypervisor/dashboard.py`
- `src/aidn_hypervisor/operator_views.py`
- backend endpoint or publication APIs

Reason:
- This slice is intentionally UI-orchestration only.
- Existing APIs already expose enough state for attach, publish, and validation actions.

---

### Task 1: Lock the guided-flow UX contract with shell tests

**Files:**
- Modify: `tests/test_api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests for the guided rail and finish action**

Add tests near the existing proxy shell coverage:

```python
def test_operator_dashboard_shell_route_exposes_guided_proxy_step_rail() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Guided Route Flow" in response.text
    assert "Request Validation (Optional)" in response.text
    assert "Create Endpoint" in response.text
    assert "Attach Proxy Route" in response.text
    assert "Publish Configuration" in response.text


def test_operator_dashboard_shell_route_exposes_guided_proxy_finish_action() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Finish Guided Flow" in response.text
    assert 'data-endpoint-action="finish-guided-flow"' in response.text
    assert 'case "finish-guided-flow":' in response.text
```

- [ ] **Step 2: Run the new tests to verify they fail for the expected reason**

Run:

```bash
python -m pytest tests/test_api.py -k "guided_proxy_step_rail or guided_proxy_finish_action" -v
```

Expected:
- `FAIL`
- Missing strings such as `"Guided Route Flow"` or `'data-endpoint-action="finish-guided-flow"'`

- [ ] **Step 3: Expand tests for phase transitions and bootstrap persistence**

Add one more shell test that pins the state-machine strings:

```python
def test_operator_dashboard_shell_route_exposes_guided_proxy_phase_transitions() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'phase: "attach"' in response.text
    assert 'phase: "publish"' in response.text
    assert 'phase: "validate_optional"' in response.text
    assert "clearGuidedProxyFlow" in response.text
```

- [ ] **Step 4: Run the transition test to verify it also fails**

Run:

```bash
python -m pytest tests/test_api.py -k "guided_proxy_phase_transitions" -v
```

Expected:
- `FAIL`
- Missing `validate_optional` phase or missing `clearGuidedProxyFlow`

- [ ] **Step 5: Commit the red test contract**

```bash
git add tests/test_api.py
git commit -m "test: cover guided proxy flow shell states"
```

If implementation and tests are being committed together later, keep this task logically separate even if the actual commit happens after green.

---

### Task 2: Implement the guided-flow rail and phase-aware helpers

**Files:**
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
- Test: `tests/test_api.py`

- [ ] **Step 1: Add explicit guided-flow helper functions**

Insert focused helpers near the existing proxy helpers:

```javascript
    function clearGuidedProxyFlow() {
      state.proxyGuidedFlow = {
        endpointId: null,
        remoteEndpointId: "",
        phase: null,
      };
    }

    function guidedProxyPhase(flow, selected) {
      if (!flow?.remoteEndpointId) {
        return null;
      }
      if (!selected?.endpoint_id) {
        return "bootstrap";
      }
      return flow.phase || "attach";
    }

    function guidedProxySteps(phase) {
      return [
        {
          key: "attach",
          title: "Attach Proxy Route",
          detail:
            phase === "bootstrap"
              ? "Create a local endpoint first, then bind the staged remote route as its proxy target."
              : "Bind the staged remote route to this endpoint before publishing the new configuration.",
        },
        {
          key: "publish",
          title: "Publish Configuration",
          detail:
            "Publish the endpoint after proxy binding so the new execution route becomes the signed snapshot.",
        },
        {
          key: "validate_optional",
          title: "Request Validation (Optional)",
          detail:
            "Validation stays explicit and optional after the proxy-backed configuration is published.",
        },
      ];
    }
```

- [ ] **Step 2: Add status and CTA mapping helpers**

Add helpers that keep rendering logic out of the main template:

```javascript
    function guidedProxyStepState(phase, stepKey) {
      const order = ["bootstrap", "attach", "publish", "validate_optional", "done"];
      const stepOrder = ["attach", "publish", "validate_optional"];
      if (phase === "bootstrap" && stepKey === "attach") {
        return "Current";
      }
      if (phase === "done") {
        return stepKey === "validate_optional" ? "Done" : "Done";
      }
      const currentIndex = stepOrder.indexOf(phase);
      const stepIndex = stepOrder.indexOf(stepKey);
      if (stepKey === "validate_optional") {
        if (phase === "validate_optional") {
          return "Optional";
        }
      }
      if (currentIndex === -1) {
        return "Waiting";
      }
      if (stepIndex < currentIndex) {
        return "Done";
      }
      if (stepIndex === currentIndex) {
        return "Current";
      }
      return "Waiting";
    }

    function guidedProxyPrimaryAction(phase) {
      switch (phase) {
        case "bootstrap":
          return { action: "create-endpoint", label: "Create Endpoint" };
        case "attach":
          return { action: "attach-proxy-target", label: "Attach Proxy Route" };
        case "publish":
          return { action: "complete-guided-proxy-publish", label: "Publish Configuration" };
        case "validate_optional":
          return { action: "request-validation", label: "Request Validation" };
        default:
          return null;
      }
    }
```

- [ ] **Step 3: Render the guided panel inside the endpoint action column**

Replace the current one-off guided notice with a dedicated panel block:

```javascript
                      ${
                        proxyGuidedFlow
                          ? `
                            <div class="panel-heading" style="margin-top: 16px;">Guided Route Flow</div>
                            <div class="list" style="margin-top: 12px;">
                              ${guidedProxySteps(guidedProxyPhase(proxyGuidedFlow, selected))
                                .map(
                                  (step) => `
                                    <div class="list-row">
                                      <div>
                                        <strong>${step.title}</strong>
                                        <span>${step.detail}</span>
                                      </div>
                                      <span class="chip">${guidedProxyStepState(guidedProxyPhase(proxyGuidedFlow, selected), step.key)}</span>
                                    </div>
                                  `
                                )
                                .join("")}
                            </div>
                          `
                          : ""
                      }
```

- [ ] **Step 4: Run the shell tests and verify the guided rail is now green**

Run:

```bash
python -m pytest tests/test_api.py -k "guided_proxy_step_rail or guided_proxy_phase_transitions" -v
```

Expected:
- `PASS`

- [ ] **Step 5: Commit the helper and rail rendering**

```bash
git add src/aidn_hypervisor/static/operator_dashboard.html tests/test_api.py
git commit -m "feat: add guided proxy step rail"
```

---

### Task 3: Wire guided actions through attach, publish, validation, and finish

**Files:**
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
- Test: `tests/test_api.py`

- [ ] **Step 1: Make attach transition the flow to `publish`**

In the existing attach-proxy success path, set:

```javascript
        state.proxyGuidedFlow = {
          endpointId: draft.endpoint_id,
          remoteEndpointId: proxyGuidedFlow.remoteEndpointId,
          phase: "publish",
        };
```

Keep the existing success message, but make it publish-oriented:

```javascript
        state.bootstrapMessage = {
          kind: "good",
          text: `Proxy route attached to ${draft.endpoint_id}. Publish configuration next so the new execution path becomes the signed snapshot.`,
        };
```

- [ ] **Step 2: Make publish transition the flow to `validate_optional`**

In the guided publish success path, set:

```javascript
        state.proxyGuidedFlow = {
          endpointId: draft.endpoint_id,
          remoteEndpointId: proxyGuidedFlow.remoteEndpointId,
          phase: "validate_optional",
        };
```

Use a message that keeps validation optional:

```javascript
        state.bootstrapMessage = {
          kind: "good",
          text: `Configuration published for ${draft.endpoint_id}. Validation is optional; request it now or finish the guided flow.`,
        };
```

- [ ] **Step 3: Add request-validation and finish-guided-flow UI actions**

Extend the endpoint action handler switch:

```javascript
          case "request-validation":
            state.bootstrapMessage = {
              kind: "good",
              text: `Validation remains optional for ${draft.endpoint_id}. Open the validation controls when you are ready to request it.`,
            };
            clearGuidedProxyFlow();
            render();
            bindInteractiveElements();
            return;
          case "finish-guided-flow":
            clearGuidedProxyFlow();
            state.bootstrapMessage = {
              kind: "good",
              text: `Guided proxy flow completed for ${draft.endpoint_id}. Endpoint controls remain available for further edits.`,
            };
            render();
            bindInteractiveElements();
            return;
```

If there is already an endpoint action switch, add these cases directly there instead of creating a second switch.

- [ ] **Step 4: Render primary and secondary guided CTAs**

In the guided panel, render the mapped action and the finish button for `validate_optional`:

```javascript
                            <div class="wallet-inline-actions" style="margin-top: 12px;">
                              <button class="primary-button action-focus" type="button" data-endpoint-action="${guidedProxyPrimaryAction(guidedProxyPhase(proxyGuidedFlow, selected)).action}">
                                ${guidedProxyPrimaryAction(guidedProxyPhase(proxyGuidedFlow, selected)).label}
                              </button>
                              ${
                                guidedProxyPhase(proxyGuidedFlow, selected) === "validate_optional"
                                  ? `<button class="secondary-button" type="button" data-endpoint-action="finish-guided-flow">Finish Guided Flow</button>`
                                  : ""
                              }
                            </div>
```

- [ ] **Step 5: Make endpoint creation resume the guided flow at `attach`**

Keep the existing persistence logic, but ensure the created endpoint binds the flow explicitly:

```javascript
        if (state.endpointProxyDraft.remoteEndpointId) {
          state.proxyGuidedFlow = {
            endpointId: created.endpoint.endpoint_id,
            remoteEndpointId: state.endpointProxyDraft.remoteEndpointId,
            phase: "attach",
          };
        }
```

If this code already exists, verify the message and current-step rendering both match the `attach` state after creation.

- [ ] **Step 6: Run focused tests for guided flow transitions**

Run:

```bash
python -m pytest tests/test_api.py -k "guided_proxy or proxy_handoff or one_click_guided_proxy_publish" -v
```

Expected:
- `PASS`

- [ ] **Step 7: Run the full suite**

Run:

```bash
python -m pytest -q
```

Expected:
- `PASS`
- zero test failures

- [ ] **Step 8: Commit the finished guided flow**

```bash
git add src/aidn_hypervisor/static/operator_dashboard.html tests/test_api.py
git commit -m "feat: add guided endpoint proxy flow"
```

---

## Self-Review

### Spec coverage

- Guided hybrid panel in `Endpoints`: Task 2
- Explicit phases `bootstrap/attach/publish/validate_optional/done`: Tasks 2 and 3
- Preserve staged route through endpoint creation: Task 3
- Optional validation and explicit finish: Task 3
- No new backend wizard API: respected by file scope

### Placeholder scan

- No `TODO`, `TBD`, or deferred “implement later” language remains in task steps.
- Every code-changing step includes concrete code snippets.
- Every verification step includes an exact command.

### Type and naming consistency

- Guided phases consistently use `bootstrap`, `attach`, `publish`, `validate_optional`, `done`
- Helper names consistently use:
  - `clearGuidedProxyFlow`
  - `guidedProxyPhase`
  - `guidedProxySteps`
  - `guidedProxyStepState`
  - `guidedProxyPrimaryAction`

---

Plan complete and saved to `docs/superpowers/plans/2026-07-06-endpoint-guided-proxy-flow.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
