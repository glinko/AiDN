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

The final G4 gate remains incomplete until the report also references reviewed
out-of-band operator/control-group evidence. Matching HTTPS responses alone do
not establish independent operators. The report must include true checks for
`lan_acceptance`, `public_p2p_acceptance`, `bootstrap_diversity`,
`public_rpc_observable` and `tls_validated`.

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
report must use this
shape for every drill:

```json
{
  "status": "PASS",
  "drills": {
    "graceful_restart": {"status": "PASS", "evidence_reference": "..."},
    "abrupt_process_termination": {"status": "PASS", "evidence_reference": "..."},
    "host_reboot": {"status": "PASS", "evidence_reference": "..."},
    "stale_predecessor_rejected": {"status": "PASS", "evidence_reference": "..."}
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
  --g6-evidence-dir evidence/operator-b
```

The gate requires distinct public keys, operator IDs and declared control
groups, and all bundles must refer to the same network, release version and
implementation profile. The declarations still require human/out-of-band
review; the protocol does not infer organizational independence from IP
addresses.

## G7 bundle creation

Build a bundle from explicitly selected files. The private key is read only for
signing and is never copied into the output:

```bash
uv run python tools/build-public-evidence-bundle.py \
  --output evidence/release-candidate \
  --network-id aidn-controlled-lan \
  --release-version 0.1.0-rc1 \
  --profile-id aidn-mainnet-candidate-1 \
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
`gates/release-gate-result.json` are control files. The latter may be written
after the artifact root is fixed and is therefore excluded from that root.
The final control file must declare `status: PASS` and passing G0 through G6
entries. Always run the final gate command with explicit `--require-evidence`
paths; a bundle without the embedded gate result is not G7-complete.
