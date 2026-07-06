Canonical stack:

Agent
  ->
Hypervisor
  ->
Protocol Services
  ->
Capability Runtimes
  ->
Endpoints
  ->
Advertisements / Marketplace / Registry

Compatibility layer during migration:

Hypervisor
  ->
Compute Service
  ->
Legacy Provider Plugins / Bundles
  ->
Canonical Capability Runtime Overlay

Notes:
- `Providers` and `Bundles` remain local execution internals during the current migration slice.
- Public protocol-facing discovery should converge on services, capabilities, runtimes, endpoints, advertisements, and ledger-backed trust state.
