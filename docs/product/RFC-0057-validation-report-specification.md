# RFC-0057 Validation Report Specification

Status: `Draft`

Version: `0.1`

Depends on:

- `RFC-0035 Validation Escrow System`
- `ECO-0003 Validation Economics`

## 1. Purpose

Validation Reports are the canonical trust artifacts of AiDN validation.

They record observable endpoint behavior, protocol compliance, accounting-related protocol observations relevant to settlement compatibility, detected issues, and certification recommendation.

Certification Status is derived at the protocol level from published Validation Reports and their history for the relevant Endpoint configuration snapshot.

## 2. Design Invariants

- Reports are immutable.
- Reports describe evidence, not model identity.
- Certification is derived from reports.
- Marketplace and reputation consume report history.
