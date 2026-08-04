# Release Gate Operational Evidence

This document defines how the repository turns operational observations into
GATE-0001 inputs. A report is evidence only when the corresponding drill was
actually run; a JSON field with `PASS` is not a substitute for the observation.

## G3 controlled multi-validator drill

Run the transaction/Merkle drill against all four validator RPC endpoints:

```bash
uv run python tools/verify-cometbft-multivalidator-devnet.py \
  --rpc-url http://validator-1:26657 \
  --validator-rpc-url http://validator-2:26657 \
  --validator-rpc-url http://validator-3:26657 \
  --validator-rpc-url http://validator-4:26657 \
  --restart-ssh-target user@validator-3 \
  --restart-command 'docker restart aidn-comet-3' \
  --output evidence/drills/g3-multivalidator.json
```

The run must not use `--skip-restart` for a complete G3 result. The report
must additionally contain `offline_status: PASS`, produced by the controlled
one-validator-offline drill. The tool records node IDs, chain IDs, peer counts,
transaction hashes, committed heights and Merkle-proof checks. The report
keeps `scope: CONTROLLED_LAN_TESTNET`; it does not prove operator
independence or public-network ownership.

## G4 public networking

The public verifier is read-only and requires at least two credential-free
HTTPS RPC endpoints plus a trusted CometBFT checkpoint:

```bash
uv run python tools/verify-cometbft-external-testnet.py \
  --config /etc/aidn/cometbft-external-acceptance.json \
  > evidence/network/external-finality.json
```

Collect the deployment observations separately. The collector performs
read-only `/status` and `/net_info` requests, relies on normal HTTPS
certificate validation, and emits hash-bound checks for peer reachability,
bootstrap diversity and TLS:

```bash
uv run python tools/verify-public-network-deployment.py \
  --rpc-url https://rpc-a.example \
  --rpc-url https://rpc-b.example \
  --minimum-peers 1 \
  --minimum-bootstrap-peers 2 \
  --minimum-bootstrap-hosts 2 \
  --output evidence/network/public-deployment.json
```

The collector does not prove that the endpoints belong to independent
operators; that remains an out-of-band G6 concern.

The final G4 gate remains incomplete until the report also references reviewed
out-of-band operator/control-group evidence. Matching HTTPS responses alone do
not establish independent operators. Every check for `lan_acceptance`,
`public_p2p_acceptance`, `bootstrap_diversity`, `public_rpc_observable` and
`tls_validated` must be an object with `status: PASS` and a non-empty
`evidence_reference`; bare boolean `true` is rejected.
When ownership is marked `OUT_OF_BAND_VERIFIED`, the ownership object must
also include a non-empty `ownership_evidence_root` for the reviewed
out-of-band record.

Combine the three source reports before passing G4 to the release gate:

```bash
uv run python tools/build-public-network-acceptance-report.py \
  --lan-report evidence/network/lan.json \
  --external-report evidence/network/external-finality.json \
  --deployment-report evidence/network/public-deployment.json \
  --output evidence/network/g4-public-network.json
```

The combined report uses `status: ok` for a structurally valid report and a
separate `gate_status` field. `gate_status: INCOMPLETE` is expected until the
public operator/control-group ownership review is complete; it is not a
substitute for that review.

## G5 fault recovery

First produce the controlled local snapshot report:

```bash
uv run python tools/run-consensus-snapshot-acceptance.py \
  --report evidence/drills/g2-snapshot.json
```

Then collect the live restart, abrupt termination, host reboot and stale
predecessor observations on the operator host. Host reboot MUST stop the ABCI
application and CometBFT before reboot, then explicitly start the ABCI
application before CometBFT after the host returns. Pass that post-reboot
operator command through `--host-reboot-recovery-command`; a host that merely
returns SSH while its service remains stopped is not recovered. The live
report must use `schema_version: 1`, `scope: CONTROLLED_LAN_TESTNET`, four or
more unique validator URLs, a target URL from that set, and a canonical
`report_hash`. Each restart/termination/reboot record must include the command
result, outage observation, converged before/after snapshots for all
validators, and checks for target identity and chain preservation. The host
reboot record additionally requires the explicit successful recovery command.
The stale-predecessor record must include the target URL, complete identity
snapshots, source and rejection transaction hashes, a non-zero rejection code
and the three rejection checks. The compact shape below shows the required
drill names; it is not sufficient evidence by itself:

```json
{
  "schema_version": 1,
  "status": "PASS",
  "report_hash": "sha256:<64 lowercase hex>",
  "drills": {
    "graceful_restart": {"status": "PASS", "evidence_reference": "sha256:<64 lowercase hex>"},
    "abrupt_process_termination": {"status": "PASS", "evidence_reference": "sha256:<64 lowercase hex>"},
    "host_reboot": {"status": "PASS", "evidence_reference": "sha256:<64 lowercase hex>"},
    "stale_predecessor_rejected": {"status": "PASS", "evidence_reference": "sha256:<64 lowercase hex>"}
  }
}
```

The live collector is intentionally explicit about all state-changing commands:

```bash
uv run python tools/run-live-fault-recovery-drills.py \\
  --rpc-url http://validator-1:26657 \\
  --rpc-url http://validator-2:26657 \\
  --rpc-url http://validator-3:26657 \\
  --rpc-url http://validator-4:26657 \\
  --target-rpc-url http://validator-1:26657 \\
  --ssh-target operator-jump \\
  --graceful-command /path/to/graceful-restart \\
  --abrupt-command /path/to/abrupt-termination \\
  --host-reboot-command /path/to/clean-host-reboot \\
  --host-reboot-recovery-command /path/to/start-abci-then-comet \\
  --stale-predecessor-command \\
    "uv run python tools/run-cometbft-stale-predecessor-drill.py ..." \\
  --timeout-seconds 900 \\
  --output evidence/drills/live-faults.json
```

Combine and validate the reports:

```bash
uv run python tools/verify-fault-recovery-evidence.py \
  --g2-report evidence/drills/g2-snapshot.json \
  --live-report evidence/drills/live-faults.json \
  --output evidence/drills/g5-fault-recovery.json
```

Without the live report the command deliberately emits `INCOMPLETE` and a
non-zero exit code.

## G6 operator quorum

Each operator creates and signs a separate EVD-0001 bundle. The attestation
contains `operator_id`, `control_group_id`, the Evidence Root and an Ed25519
signature. Verify the quorum with repeated inputs:

```bash
uv run python tools/verify-release-gates.py \
  --g6-evidence-dir evidence/operator-a \
  --g6-evidence-dir evidence/operator-b \
  --g6-review-key release-reviewer=ed25519:<64-hex-public-key>
```

The gate requires distinct public keys, operator IDs and declared control
groups, a signed `attestations/independence-review.json` for every bundle, and
all bundles must refer to the same network, release version and implementation
profile. Create each review only after the operator evidence has been checked:

```bash
uv run python tools/sign-independence-review.py \
  --evidence-dir evidence/operator-a \
  --reviewer-id release-reviewer \
  --operator-id operator-a \
  --control-group-id control-group-a \
  --review-basis "out-of-band identity and deployment review" \
  --private-key /secure/release-reviewer-ed25519.key
```

The protocol still does not infer organizational independence from IP
addresses; the trusted reviewer key represents the external review authority.

## G7 bundle creation

Use the release orchestrator instead of assembling the final bundle manually.
It first verifies G0-G6, refuses to build when any gate is `INCOMPLETE` or
`FAIL`, writes the G7 control file outside the Evidence Root, and runs the
strict verifier again after signing. The private key is read only for signing
and is never copied into the output:

```bash
uv run python tools/build-release-evidence-bundle.py \
  --output evidence/release-candidate \
  --network-id aidn-controlled-lan \
  --release-version 0.1.0-rc1 \
  --profile profiles/aidn-mainnet-candidate-1.json \
  --fixture-manifest fixtures/manifest.json \
  --g0-report evidence/gates/g0-release-integrity.json \
  --g1-report evidence/gates/g1-protocol-conformance.json \
  --g2-report evidence/drills/g2-snapshot.json \
  --g3-report evidence/drills/g3-multivalidator.json \
  --g4-report evidence/network/g4-public-network.json \
  --g5-report evidence/drills/g5-fault-recovery.json \
  --g6-evidence-dir evidence/operator-a \
  --g6-evidence-dir evidence/operator-b \
  --g6-review-key release-reviewer=ed25519:<64-hex-public-key> \
  --operator-id operator-a \
  --control-group-id control-group-a \
  --independence-status OUT_OF_BAND_DECLARED \
  --private-key /secure/operator-ed25519.key \
  --artifact profiles/aidn-mainnet-candidate-1.json=release/profile.json \
  --artifact fixtures/manifest.json=release/fixture-manifest.json \
  --artifact evidence/drills/g3-multivalidator.json=drills/g3-multivalidator.json \
  --artifact evidence/drills/g5-fault-recovery.json=drills/g5-fault-recovery.json
```

`manifest.json`, the operator attestation and
`gates/release-gate-result.json` are control files. The latter is written after
the artifact root is fixed and is therefore excluded from that root. The
orchestrator requires at least two G6 bundles and emits a final control file
with passing G0 through G7 entries. A bundle without the embedded gate result
is not G7-complete.

`tools/build-public-evidence-bundle.py` remains available as a low-level
development primitive, but it does not evaluate release gates and MUST NOT be
used as the final release path.
