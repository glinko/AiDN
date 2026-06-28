# TODO.md

# AiDN Hypervisor MVP TODO

This document tracks the implementation status of the Hypervisor.

Only implementation tasks belong here.

Architecture work belongs in RFC/IMP documents.

---

# Phase 1 — Foundation

## Repository

* [ ] Initialize repository structure
* [ ] Configure Go workspace
* [ ] Configure CI
* [ ] Configure linting
* [ ] Configure formatting
* [ ] Configure testing

---

## Bootstrap

* [ ] Bootstrap sequence
* [ ] Configuration loader
* [ ] Dependency Injection
* [ ] Lifecycle manager
* [ ] Graceful shutdown

---

## Persistence

* [ ] PostgreSQL schema
* [ ] Migration framework
* [ ] Repository layer
* [ ] Transaction helpers

---

## Event Bus

* [ ] Publish
* [ ] Subscribe
* [ ] Correlation IDs
* [ ] Event registry

---

# Phase 2 — Hypervisor Core

## Bundle Manager

* [ ] Bundle installation
* [ ] Bundle verification
* [ ] Bundle registry
* [ ] Artifact manager

---

## Endpoint Manager

* [ ] Endpoint CRUD
* [ ] Configuration Snapshots
* [ ] Publication policy
* [ ] Runtime configuration

---

## Provider SDK

* [ ] SDK interfaces
* [ ] SDK tests
* [ ] SDK examples

---

## Runtime Manager

* [ ] Provider lifecycle
* [ ] Bundle loading
* [ ] Bundle unloading
* [ ] Health monitoring

---

## Resource Manager

* [ ] CPU accounting
* [ ] RAM accounting
* [ ] GPU accounting
* [ ] VRAM accounting

---

## Scheduler

* [ ] Queue
* [ ] Admission control
* [ ] Resource reservation
* [ ] Dispatch
* [ ] Completion handling

---

# Phase 3 — API

## REST

* [ ] Endpoint API
* [ ] Bundle API
* [ ] Task API
* [ ] Metrics API

---

## Authentication

* [ ] Wallet authentication
* [ ] API tokens
* [ ] Authorization

---

# Phase 4 — First Provider

## llama.cpp

* [ ] Process manager
* [ ] Health
* [ ] Execute
* [ ] Usage reporting
* [ ] Streaming
* [ ] Warmup

---

# Phase 5 — Operator Dashboard

* [ ] Login
* [ ] Fleet
* [ ] Endpoints
* [ ] Bundles
* [ ] Tasks
* [ ] Metrics
* [ ] Logs

---

# Phase 6 — Wallet

* [ ] Usage ledger
* [ ] Billing Units
* [ ] Settlement
* [ ] Export

---

# Phase 7 — Registry

* [ ] Advertisement generation
* [ ] Signing
* [ ] Heartbeats
* [ ] Discovery

---

# Phase 8 — Validation

* [ ] Validator lifecycle
* [ ] Validation execution
* [ ] Attestation publication
* [ ] Validator certificates

---

# Phase 9 — Production Readiness

* [ ] Documentation
* [ ] Benchmarks
* [ ] Integration tests
* [ ] Load tests
* [ ] Release pipeline
* [ ] Installer
* [ ] Packaging
* [ ] Example configurations
* [ ] Example Providers

---

# Release Criteria

Hypervisor MVP is complete when:

* all mandatory RFC contracts are implemented;
* one production Provider (llama.cpp) passes all SDK tests;
* Endpoints can be published;
* tasks execute successfully;
* usage is recorded;
* advertisements are published;
* validators can verify supported Endpoints.
