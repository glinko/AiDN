# RFC Cross-Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the reconstructed AiDN RFC set so Marketplace, Session, Settlement, Registry, Runtime, Proxy, Certification, and Upgrade semantics use compatible fields, references, and lifecycle operations.

**Architecture:** This plan applies a semantic sync pass across the RFC markdown sources in `docs/product`. Changes are grouped by dependency order: first accepted commercial identity, then lifecycle tasks and operations, then accounting/runtime/proxy boundaries, then certification/recovery visibility, and finally summary/profile/storage wording. Verification is done with repository-local text checks that prove each dependent RFC now contains the required fields or operation names.

**Tech Stack:** Markdown RFC sources, PowerShell, `rg`, git

---

### Task 1: Bind Session and Settlement to Accepted Advertisement and Offer Identity

**Files:**
- Modify: `docs/product/RFC-0044-aidn-session-protocol.md:273-335`
- Modify: `docs/product/RFC-0044-aidn-session-protocol.md:2536-2578`
- Modify: `docs/product/RFC-0037-settlement-engine.md:78-119`
- Modify: `docs/product/RFC-0037-settlement-engine.md:241-261`
- Test: `docs/product/RFC-0044-aidn-session-protocol.md`
- Test: `docs/product/RFC-0037-settlement-engine.md`

- [ ] **Step 1: Write the failing consistency check**

```powershell
rg -n "advertisement_id|offer_id" docs/product/RFC-0044-aidn-session-protocol.md docs/product/RFC-0037-settlement-engine.md
```

- [ ] **Step 2: Run the check and verify it fails**

Run:

```powershell
rg -n "advertisement_id|offer_id" docs/product/RFC-0044-aidn-session-protocol.md docs/product/RFC-0037-settlement-engine.md
```

Expected: no matches, proving the accepted commercial identity is not yet carried through Session and Settlement.

- [ ] **Step 3: Patch `RFC-0044` Session Contract and invariants**

Insert the accepted Marketplace identity into the Session contract object and invariant language near `## 11. Session Contract` and the invariant sections:

```md
  advertisement_id:
  offer_id:
```

and add invariant wording such as:

```md
* Every accepted Session binds to one exact Advertisement or Offer scope.
* Settlement does not reinterpret a Session under a later Advertisement version.
```

- [ ] **Step 4: Patch `RFC-0037` Settlement inputs and auditability wording**

Add accepted commercial identity to the Session invoice and Settlement text near `## 6. Invoice`, `## 7. Settlement`, and `## 17. Failure Recovery`:

```md
Settlement input SHALL include the accepted Session commercial identity:

* advertisement_id;
* offer_id where present;
* accepted Pricing Policy and Accounting Contract references;
* the Session Contract hash.
```

and add audit language such as:

```md
Settlement SHALL use the Advertisement and Offer accepted when the Session opened.
Later Marketplace updates SHALL NOT retroactively alter the computed outcome.
```

- [ ] **Step 5: Run the verification search**

Run:

```powershell
rg -n "advertisement_id|offer_id|accepted Session commercial identity|Later Marketplace updates SHALL NOT retroactively alter" docs/product/RFC-0044-aidn-session-protocol.md docs/product/RFC-0037-settlement-engine.md
```

Expected: matches in both RFCs showing the accepted offer identity is now part of Session and Settlement semantics.

- [ ] **Step 6: Commit**

```bash
git add docs/product/RFC-0044-aidn-session-protocol.md docs/product/RFC-0037-settlement-engine.md
git commit -m "docs: bind sessions and settlement to accepted advertisements"
```

### Task 2: Add Marketplace Lifecycle Tasks and Canonical Operations

**Files:**
- Modify: `docs/product/RFC-0048-epoch-engine.md:1207-1224`
- Modify: `docs/product/RFC-0048-epoch-engine.md:1809-1860`
- Modify: `docs/product/RFC-0059-ledger-operation-catalog.md:717-807`
- Modify: `docs/product/RFC-0059-ledger-operation-catalog.md:1904-1998`
- Test: `docs/product/RFC-0048-epoch-engine.md`
- Test: `docs/product/RFC-0059-ledger-operation-catalog.md`

- [ ] **Step 1: Write the failing lifecycle check**

```powershell
rg -n "Expire Endpoint Advertisements|Activate Scheduled Advertisements|Apply Advertisement Withdrawals|ENDPOINT_ADVERTISEMENT_PUBLISH|ENDPOINT_OFFER_PUBLISH" docs/product/RFC-0048-epoch-engine.md docs/product/RFC-0059-ledger-operation-catalog.md
```

- [ ] **Step 2: Run the check and verify it fails**

Run:

```powershell
rg -n "Expire Endpoint Advertisements|Activate Scheduled Advertisements|Apply Advertisement Withdrawals|ENDPOINT_ADVERTISEMENT_PUBLISH|ENDPOINT_OFFER_PUBLISH" docs/product/RFC-0048-epoch-engine.md docs/product/RFC-0059-ledger-operation-catalog.md
```

Expected: at least some terms missing, proving Marketplace lifecycle machinery is incomplete.

- [ ] **Step 3: Patch `RFC-0048` extended protocol tasks and MVP wording**

Add Marketplace task bullets near `## 77. Extended Protocol Tasks` and mirror them in the MVP requirements section:

```md
Marketplace tasks MAY include:

* Expire Endpoint Advertisements;
* Activate Scheduled Advertisements;
* Apply Advertisement Withdrawals;
* Apply Endpoint Suspensions;
* Detect Configuration Mismatches;
* Update Marketplace Freshness Roots;
* Publish Capability Supply Metrics;
* Publish Pricing Distribution Metrics;
* Publish Operator Diversity Metrics.
```

- [ ] **Step 4: Patch `RFC-0059` endpoint operation catalog**

Extend the endpoint operation sections and MVP mandatory operations with Marketplace operations:

```md
* ENDPOINT_ADVERTISEMENT_PUBLISH;
* ENDPOINT_ADVERTISEMENT_WITHDRAW;
* ENDPOINT_OFFER_PUBLISH;
* ENDPOINT_OFFER_WITHDRAW;
```

and add one-line operation descriptions such as:

```md
`ENDPOINT_ADVERTISEMENT_PUBLISH`
Creates the canonical reference to one immutable Advertisement Object.
```

- [ ] **Step 5: Run the verification search**

Run:

```powershell
rg -n "Expire Endpoint Advertisements|Activate Scheduled Advertisements|Apply Advertisement Withdrawals|Publish Pricing Distribution Metrics|ENDPOINT_ADVERTISEMENT_PUBLISH|ENDPOINT_ADVERTISEMENT_WITHDRAW|ENDPOINT_OFFER_PUBLISH|ENDPOINT_OFFER_WITHDRAW" docs/product/RFC-0048-epoch-engine.md docs/product/RFC-0059-ledger-operation-catalog.md
```

Expected: all lifecycle task names and Marketplace operations appear in the owning RFCs.

- [ ] **Step 6: Commit**

```bash
git add docs/product/RFC-0048-epoch-engine.md docs/product/RFC-0059-ledger-operation-catalog.md
git commit -m "docs: add marketplace lifecycle tasks and operations"
```

### Task 3: Align Accounting, Runtime, and Proxy Boundaries

**Files:**
- Modify: `docs/product/RFC-0051-usage-reporting-and-verification-protocol.md:329-381`
- Modify: `docs/product/RFC-0051-usage-reporting-and-verification-protocol.md:1330-1459`
- Modify: `docs/product/RFC-0053-capability-runtime-specification.md:153-181`
- Modify: `docs/product/RFC-0053-capability-runtime-specification.md:425-463`
- Modify: `docs/product/RFC-0063-proxy-endpoint-protocol.md:225-386`
- Modify: `docs/product/RFC-0063-proxy-endpoint-protocol.md:1501-1555`
- Test: `docs/product/RFC-0051-usage-reporting-and-verification-protocol.md`
- Test: `docs/product/RFC-0053-capability-runtime-specification.md`
- Test: `docs/product/RFC-0063-proxy-endpoint-protocol.md`

- [ ] **Step 1: Write the failing boundary check**

```powershell
rg -n "Registry Object|published in the Endpoint Advertisement|Runtime .* does not publish price|Proxy Declaration|Failover Policy" docs/product/RFC-0051-usage-reporting-and-verification-protocol.md docs/product/RFC-0053-capability-runtime-specification.md docs/product/RFC-0063-proxy-endpoint-protocol.md
```

- [ ] **Step 2: Run the check and verify the missing surfaces**

Run:

```powershell
rg -n "Registry Object|Runtime .* does not publish price|Proxy Declaration|Failover Policy" docs/product/RFC-0051-usage-reporting-and-verification-protocol.md docs/product/RFC-0053-capability-runtime-specification.md docs/product/RFC-0063-proxy-endpoint-protocol.md
```

Expected: missing or insufficiently explicit matches for the new Marketplace-facing boundaries.

- [ ] **Step 3: Patch `RFC-0051` Accounting Contract ownership**

Add wording near `## 13. Accounting Contract` and `## 70. Marketplace Transparency` such as:

```md
The Accounting Contract SHALL be published as a versioned Registry Object and referenced by the Endpoint Advertisement.
Marketplace display of Accounting Mode and transparency SHALL derive from that accepted object rather than informal pricing text.
```

- [ ] **Step 4: Patch `RFC-0053` Runtime boundary**

Add wording near `## 8. Endpoint Management`, `## 23. Session Contract Binding`, and `## 25. Proxy Runtime Support`:

```md
The Runtime SHALL NOT publish Marketplace price identity directly.
Commercial terms belong to the accepted Advertisement or Offer selected by the Endpoint operator.
The Runtime executes work under the accepted Session Contract and referenced Accounting Contract.
```

- [ ] **Step 5: Patch `RFC-0063` Proxy disclosure and failover objects**

Add or tighten wording near `## 13. Proxy Declaration`, `## 24. Commercial-Only Upstream Change`, `## 114. Marketplace Disclosure`, and `## 116. Proxy Advertisement`:

```md
Proxy Declaration and Failover Policy SHALL be published through Marketplace-facing objects or object references bound to the Endpoint Advertisement.
A commercial-only upstream change MAY preserve Proxy mechanics, but changes to disclosed offer terms require Advertisement update.
```

- [ ] **Step 6: Run the verification search**

Run:

```powershell
rg -n "versioned Registry Object|referenced by the Endpoint Advertisement|Runtime SHALL NOT publish Marketplace price identity directly|Commercial terms belong to the accepted Advertisement or Offer|Proxy Declaration and Failover Policy SHALL be published" docs/product/RFC-0051-usage-reporting-and-verification-protocol.md docs/product/RFC-0053-capability-runtime-specification.md docs/product/RFC-0063-proxy-endpoint-protocol.md
```

Expected: all three RFCs now express the same accounting/runtime/proxy ownership boundaries.

- [ ] **Step 7: Commit**

```bash
git add docs/product/RFC-0051-usage-reporting-and-verification-protocol.md docs/product/RFC-0053-capability-runtime-specification.md docs/product/RFC-0063-proxy-endpoint-protocol.md
git commit -m "docs: align marketplace accounting runtime and proxy boundaries"
```

### Task 4: Align Certification and Recovery with Marketplace Visibility

**Files:**
- Modify: `docs/product/RFC-0065-endpoint-certification-derivation-and-lifecycle-protocol.md:1143-1248`
- Modify: `docs/product/RFC-0065-endpoint-certification-derivation-and-lifecycle-protocol.md:1427-1494`
- Modify: `docs/product/RFC-0066-protocol-upgrade-and-emergency-recovery.md:337-360`
- Modify: `docs/product/RFC-0066-protocol-upgrade-and-emergency-recovery.md:1372-1422`
- Test: `docs/product/RFC-0065-endpoint-certification-derivation-and-lifecycle-protocol.md`
- Test: `docs/product/RFC-0066-protocol-upgrade-and-emergency-recovery.md`

- [ ] **Step 1: Write the failing visibility check**

```powershell
rg -n "Marketplace views|does not rewrite Advertisement history|republish active Advertisements|new Network Revision" docs/product/RFC-0065-endpoint-certification-derivation-and-lifecycle-protocol.md docs/product/RFC-0066-protocol-upgrade-and-emergency-recovery.md
```

- [ ] **Step 2: Run the check and verify the gap**

Run:

```powershell
rg -n "Marketplace views|does not rewrite Advertisement history|republish active Advertisements|new Network Revision" docs/product/RFC-0065-endpoint-certification-derivation-and-lifecycle-protocol.md docs/product/RFC-0066-protocol-upgrade-and-emergency-recovery.md
```

Expected: missing or incomplete wording for Marketplace-visible certification and recovery behavior.

- [ ] **Step 3: Patch `RFC-0065` certification state update and Marketplace presentation**

Add wording near `## 73. Certification State Update` and `## 79. Marketplace Presentation`:

```md
Certification State Updates SHALL update Marketplace-visible certification status for the matching Configuration Hash.
They SHALL NOT rewrite or replace immutable historical Advertisement Objects.
```

- [ ] **Step 4: Patch `RFC-0066` Network Revision Recovery semantics**

Add wording near `## 20. Network Revision Recovery`:

```md
After Network Revision Recovery, active Marketplace offers SHALL be republished or explicitly reactivated under the new Network Revision before they may open new Sessions.
Old-revision Advertisements remain historical objects and do not automatically regain active status.
```

- [ ] **Step 5: Run the verification search**

Run:

```powershell
rg -n "Certification State Updates SHALL update Marketplace-visible certification status|They SHALL NOT rewrite or replace immutable historical Advertisement Objects|active Marketplace offers SHALL be republished|Old-revision Advertisements remain historical objects" docs/product/RFC-0065-endpoint-certification-derivation-and-lifecycle-protocol.md docs/product/RFC-0066-protocol-upgrade-and-emergency-recovery.md
```

Expected: both RFCs now reflect Marketplace visibility updates without mutating Advertisement history.

- [ ] **Step 6: Commit**

```bash
git add docs/product/RFC-0065-endpoint-certification-derivation-and-lifecycle-protocol.md docs/product/RFC-0066-protocol-upgrade-and-emergency-recovery.md
git commit -m "docs: align certification and recovery with marketplace visibility"
```

### Task 5: Finish Summary, Profile, and Registry Storage Alignment

**Files:**
- Modify: `docs/product/RFC-0041-reputation-profile-engine.md:1536-1651`
- Modify: `docs/product/RFC-0045-aidn-capability-architecture.md:1379-1499`
- Modify: `docs/product/RFC-0045-aidn-capability-architecture.md:2296-2325`
- Modify: `docs/product/RFC-0046-aidn-registry-architecture.md:492-520`
- Modify: `docs/product/RFC-0046-aidn-registry-architecture.md:2297-2527`
- Test: `docs/product/RFC-0041-reputation-profile-engine.md`
- Test: `docs/product/RFC-0045-aidn-capability-architecture.md`
- Test: `docs/product/RFC-0046-aidn-registry-architecture.md`
- Test: `docs/product`

- [ ] **Step 1: Write the failing final-alignment check**

```powershell
rg -n "Marketplace Summary|Feature Profile|Limit Profile|Accounting Contract|Proxy Declaration|Failover Policy|active Advertisements" docs/product/RFC-0041-reputation-profile-engine.md docs/product/RFC-0045-aidn-capability-architecture.md docs/product/RFC-0046-aidn-registry-architecture.md
```

- [ ] **Step 2: Run the check and verify remaining omissions**

Run:

```powershell
rg -n "Marketplace Summary|Feature Profile|Limit Profile|Proxy Declaration|Failover Policy|active Advertisements" docs/product/RFC-0041-reputation-profile-engine.md docs/product/RFC-0045-aidn-capability-architecture.md docs/product/RFC-0046-aidn-registry-architecture.md
```

Expected: incomplete summary/profile/storage alignment before the final pass.

- [ ] **Step 3: Patch `RFC-0041`, `RFC-0045`, and `RFC-0046`**

Apply the following targeted wording:

```md
RFC-0041:
Marketplace Summary MAY expose a bounded non-canonical presentation layer derived from canonical Reputation state without replacing the underlying Profile.

RFC-0045:
Marketplace Feature Profile and Limit Profile references SHALL match the Capability-side definitions and Endpoint Implementation Profile.

RFC-0046:
Full Registry retention SHALL include active Advertisements, current withdrawals, and referenced current Marketplace policy objects such as Pricing Policy, Accounting Contract, Proxy Declaration, and Failover Policy.
```

- [ ] **Step 4: Run the repo-wide verification checks**

Run:

```powershell
rg -n "advertisement_id|offer_id|ENDPOINT_ADVERTISEMENT_PUBLISH|ENDPOINT_OFFER_PUBLISH|Proxy Declaration|Failover Policy|Marketplace Summary|republished or explicitly reactivated" docs/product
```

Run:

```powershell
$files = Get-ChildItem 'docs/product' -Filter '*.md'
$present = @{}
foreach ($f in $files) { if ($f.BaseName -match '^(RFC|ECO)-\d{4}') { $present[$matches[0]] = $true } }
$refs = [System.Collections.Generic.HashSet[string]]::new()
foreach ($f in $files) {
  $content = Get-Content $f.FullName -Raw
  [regex]::Matches($content,'\b(?:RFC|ECO)-\d{4}\b') | ForEach-Object { [void]$refs.Add($_.Value) }
}
$missing = $refs | Where-Object { -not $present.ContainsKey($_) } | Sort-Object
if ($missing) { $missing } else { 'ALL_REFERENCES_RESOLVED' }
```

Expected: the term search hits the aligned RFCs and the reference scan prints `ALL_REFERENCES_RESOLVED`.

- [ ] **Step 5: Commit**

```bash
git add docs/product/RFC-0041-reputation-profile-engine.md docs/product/RFC-0045-aidn-capability-architecture.md docs/product/RFC-0046-aidn-registry-architecture.md
git commit -m "docs: complete marketplace cross-rfc alignment"
```

## Self-Review

Spec coverage:

* Task 1 covers accepted commercial identity in Session and Settlement.
* Task 2 covers lifecycle scheduling and canonical operations.
* Task 3 covers accounting/runtime/proxy ownership boundaries.
* Task 4 covers certification and upgrade/recovery visibility.
* Task 5 covers summary/profile/storage cleanup and the final reference scan.

Placeholder scan:

* No `TBD`, `TODO`, or deferred “fill this in later” plan text remains.

Type consistency:

* The plan consistently uses `advertisement_id`, `offer_id`, `Pricing Policy`, `Accounting Contract`, `Proxy Declaration`, and `Failover Policy` in the same roles across all tasks.
