# RFC-0056

Provider Plugin Runtime Interface

Status: Draft

Version: 0.2

Supersedes:

* RFC-0056 Version 0.1

Depends on:

* RFC-0039 Hypervisor Service Model
* RFC-0045 AiDN Capability Architecture
* RFC-0051 Usage Reporting and Verification Protocol
* RFC-0053 Capability Runtime Specification
* RFC-0054 Capability Runtime Protocol
* RFC-0055 Provider Plugin System and Directory

---

## 1. Purpose

This document defines the Provider Plugin Runtime Interface used inside one
Hypervisor.

It specifies how a Provider Plugin:

* validates Provider Instance configuration;
* attaches or installs a Provider Instance;
* separates installation-plan generation from approved plan application;
* discovers or installs Model Deployments;
* creates Runtime Bindings;
* reports health and usage capability;
* adapts execution into the Hypervisor Runtime surface;
* supports streaming, cancellation and recovery where available;
* exposes stable diagnostics and errors.

---

## 2. Core Principle

The Provider Plugin Runtime Interface is a Hypervisor-local normalization
boundary.

It translates provider-specific behavior into:

* Hypervisor control-plane operations;
* Runtime Binding metadata;
* normalized execution semantics.

It is not the public Hypervisor-to-Runtime network protocol of RFC-0054.

---

## 3. Interface Layers

The interface has two logical layers.

### 3.1 Control Plane

Used for:

* manifest inspection;
* compatibility checks;
* Provider Instance validation;
* installation-plan generation;
* attach-existing flow;
* model discovery and install;
* Runtime Binding creation;
* diagnostics.

### 3.2 Execution Adapter Plane

Used for:

* request execution;
* streaming;
* cancellation;
* usage-report retrieval;
* recovery hooks;
* health observation.

---

## 4. Hypervisor Boundary

The Hypervisor owns:

* plugin installation authorization;
* permission prompts;
* secret management;
* endpoint drafting;
* Advertisement publication;
* Wallet and Ledger interaction;
* Service Verification orchestration.

The plugin owns provider-specific behavior behind the normalized interface.

---

## 5. Required Metadata

A plugin runtime interface SHALL be able to expose:

* plugin identifier and version;
* provider-family identifier;
* supported Provider versions or profiles;
* supported AiDN Capabilities;
* supported installation modes;
* supported capability flags;
* execution and usage-reporting features.

---

## 6. Provider Instance Methods

The control plane SHOULD support methods equivalent to:

* `ValidateProviderConfiguration`
* `BuildInstallationPlan`
* `InstallProvider`
* `ApplyInstallationPlan`
* `AttachExistingProvider`
* `UpdateProvider`
* `StartProvider`
* `StopProvider`
* `RestartProvider`
* `RemoveProvider`
* `TestProviderConnection`
* `GetProviderHealth`

Not every plugin is required to implement every method.

`BuildInstallationPlan` SHALL be side-effect bounded. It may validate inputs
and construct an auditable plan, but it SHALL NOT perform host-mutating
installation work.

`ApplyInstallationPlan` SHALL be called only by the Hypervisor after an
operator approval has been recorded and bound to the exact plan and
configuration hashes.

An MVP implementation MAY expose only a recorded apply executor. In that mode,
the apply result records intended declarative actions and creates local Provider
Instance inventory state without running shell commands, container engines,
downloads, package managers or plugin installer code.

Host-mutating apply implementations SHALL report executor identity, requested
permissions, consumed secret references, step results, failure class and
rollback status through stable result objects.

---

## 7. Model Deployment Methods

The control plane SHOULD support methods equivalent to:

* `DiscoverModels`
* `ListModels`
* `ValidateModelConfiguration`
* `InstallModel`
* `ImportModel`
* `StartModel`
* `StopModel`
* `RemoveModel`
* `GetModelHealth`
* `GetModelCapabilities`

---

## 8. Runtime Binding Methods

The interface SHOULD support methods equivalent to:

* `CreateRuntimeBinding`
* `DescribeCapabilities`
* `DescribeUsageReportingCapabilities`
* `DescribeRuntimeLimits`
* `BuildRuntimeProjection`

`BuildRuntimeProjection` MAY be used during MVP to map a Runtime Binding into a
compatibility execution layer.

---

## 9. Execution Methods

The execution adapter plane SHOULD support methods equivalent to:

* `ExecuteRequest`
* `CancelRequest`
* `StreamEvents`
* `GetUsageReport`
* `RecoverRequest`

If a provider cannot support one of these behaviors, the plugin SHALL report
that explicitly instead of silently pretending support.

---

## 10. Usage Reporting Capability

The interface SHALL distinguish usage availability and authority.

Example shape:

```yaml
usage_reporting_capabilities:
  input_tokens:
    availability:
    authority:
  output_tokens:
    availability:
    authority:
  execution_time:
    availability:
    authority:
  upstream_cost:
    availability:
    authority:
```

Initial authorities include:

* AUTHORITATIVE_PROVIDER
* DETERMINISTIC_LOCAL
* OBSERVABLE_LOCAL
* ESTIMATED
* UNAVAILABLE

---

## 11. Model Metadata Sources

The interface SHOULD preserve metadata provenance for model-related claims.

Initial provenance classes include:

* PLUGIN_DISCOVERED
* OPERATOR_DECLARED
* MANIFEST_VERIFIED
* PROVIDER_REPORTED
* LOCALLY_MEASURED

---

## 12. Health

The interface SHOULD separate:

* plugin health;
* Provider Instance health;
* Model Deployment health;
* Runtime Binding readiness;
* execution-path health.

The Hypervisor SHALL not infer endpoint availability from a plugin merely being
installed.

---

## 13. Errors

The interface SHOULD expose stable error classes for:

* invalid configuration;
* unsupported install mode;
* provider connection failure;
* installation approval mismatch;
* installation executor unavailable;
* installation rollback failure;
* model discovery failure;
* model install failure;
* runtime-binding failure;
* execution failure;
* cancellation unsupported;
* usage-report unavailable;
* recovery unsupported.

Provider-native diagnostic details MAY be attached, but normalized error
classes remain authoritative.

---

## 14. Diagnostics

The interface SHOULD support methods equivalent to:

* `GetLogs`
* `RunDiagnostics`
* `RunConformanceChecks`
* `ExportSupportBundle`

Diagnostics remain Hypervisor-local operational tools.

They do not by themselves create Service Verification or Endpoint
Certification.

---

## 15. Security Invariants

* The plugin runtime interface does not grant Wallet or Ledger authority.
* Provider secrets remain mediated by Hypervisor secret management.
* Unsupported behavior is declared explicitly.
* Provider-native semantics are normalized before endpoint publication.
* Execution adaptation and plugin installation are separate concerns.
* Installation-plan generation is separate from approved plan application.
* A recorded apply executor is valid MVP behavior only when it is clearly
  reported as non-host-mutating.

---

## 16. Design Invariants

* The interface is plugin-family specific internally and AiDN-normalized
  externally.
* Control-plane operations and execution-plane behavior are distinct.
* Runtime Binding is the bridge from Model Deployment into AiDN runtime and
  endpoint lifecycle.
* RFC-0054 remains the Hypervisor-to-Runtime protocol boundary even when a
  plugin internally hosts or adapts the runtime.
