# Controlled Localnet Epoch 1 ECO-0007 Wallet 127 Payout Acceptance

Date: `2026-08-14`

This record captures a repeated controlled-localnet RFC-0068 to ECO-0007
reward batch using the verified contributor Wallet profile for node 127. It
is live consensus evidence for the controlled testnet only. It is not a claim
of public-network readiness, external organizational independence or public
governance authority.

## Network And Authority

- Network: `aidn-localnet-1`
- Chain: `chain-Anm7Jk`
- Validators: `192.168.88.128`, `192.168.88.129`, `192.168.88.130`
- Finality quorum: `3/3` RPC observations, configured minimum `2/3`
- Protocol authority policy hash:
  `sha256:40c7c0371dca2160043bcd05e37ceb3d8cc8ab33d67bc21b451c95b3e45625a4`
- Protocol authority threshold: `2-of-3`
- ECO-0007 activation approval hash:
  `sha256:763013829e936f51eb33eab072edba980366db5ed315389f0f9ee25492db9545`
- ECO-0007 activation ID:
  `sha256:4bcd9bebe1d6fc375d823b4fad07367d3d79423dbff9ae01211b333adbb55b71`
- Production profile hash:
  `sha256:e8952c81b17dc0a274eeb2504ef79d9ef6c64a70853260ba398c8745600ae6ad`
- Finality deployment: controlled multi-RPC profile with trusted checkpoint
  height `64146`

Authority keys and the contributor Wallet private key remained external to the
repository. The Wallet profile is explicitly `CONTROLLED_LOCALNET_ONLY`.

## RFC-0068 Contribution

The acceptance runner created a clean repository workspace, produced a real
protected-branch merge and completed the normal RFC-0068 attribution path.

- Repository: `controlled-localnet-aidn`
- Base commit: `ada519632c7463103453cb3926045dc61668111b`
- Source commit: `82189cc479636f0ff58af2447714f30f6fe05d26`
- Merge commit: `811178403ab97e7b0963a2ae337cf41f3a4df33b`
- Contribution ID:
  `sha256:1015312f29207f4b10df9125451e3d390e7cbd7ba7d4f5937b8c34e10d718026`
- Attestation hash:
  `sha256:9d37bab4ddc298d189cb851d9bdb467f1bd660990fe3775a1482ffe3d6d3e04f`
- Contribution units: `3178 milli-CU`
- Wallet: `wallet-5320047bb01d`
- Wallet public key:
  `ed25519:c17c775a8a0402e695733ed4458dab309dbef2829bf19763ad02ae66bb165e03`
- Wallet binding hash:
  `sha256:d3985dcb4040cc870a12d1ce37c7e7409edd6964c361b6f3a1edbe914b6760d5`
- Wallet claim hash:
  `sha256:6c9e348beef9d15588bc92fb9f4b89d7aec41942e8cb0e6776c2fa03a232210a`
- Authority signatures: `controlled-localnet-authority-a` and
  `controlled-localnet-authority-b`, state `VERIFIED`
- Challenge boundary: epoch `2`
- Contribution finalization: epoch `3`, state `FINALIZED`

The controlled operator Wallet is used as a test contributor identity. It must
not be counted as an independent external contributor for network-governance
or independence claims.

## ECO-0007 Batch

The batch was built from the finalized attestation and one unchanged `READY`
quorum preflight:

- Pool: `GENERAL_DEVELOPMENT`
- Epoch: `1`
- Pool budget: `250000000 q_atoms = 250 Q`
- Preflight hash:
  `sha256:e9be982a3c40028919ba9db93878a804c09da13d99e5eb358785c46ef421314f`
- Source transition operation:
  `7af516b4a59d04439bcfc93e761172896df413d709d1923d0bbd3d905bad035f`
- Batch ID:
  `sha256:5ad06ba27b567a3f4cabd560e2847add4a42b40420b4a39e5471e8002034d599`
- Batch hash:
  `sha256:538e58d5076bd016175a7f81edd729f9de74fa1bec1979b5f812f5e6e1fd7523`
- Gross scheduled reward: `3178000 q_atoms = 3.178 Q`
- Immediate payout: `1271200 q_atoms = 1.2712 Q`
- Maturity reserve: `1906800 q_atoms = 1.9068 Q`
  (`953400 q_atoms` at stage one and `953400 q_atoms` at stage two)
- Denomination: `1 Q = 1000000 q_atoms`

The calculation commitment remains non-emitting and `simulation_only`. Q moved
only through the separately authorized ordered consensus operations below.

## Consensus Finality

Each operation has one operation ID and one transaction identity. Every tx was
observed with `tx_result.code=0` and an inclusion proof on all three configured
RPCs. The canonical `operation/finalized` projection returned the same
operation type, sequence and record digest on the validator quorum.

| Sequence | Operation | Operation ID | Transaction | Finality block | Record digest | RPC quorum |
| ---: | --- | --- | --- | ---: | --- | ---: |
| 33 | `DEVELOPMENT_REWARD_CALCULATE` | `368e7dbf7589f49601715a9043ee1df847e444595ca138946e613c25e273796f` | `D2C399286138A4FA17949E3B06620B2DA8AA957232BD3D44532D9ECD3C8C33A0` | 69433 | `273dda250ece3ac392a6cdeb1e6d33422c78027f162cdd1bc1109018150c55a5` | 3/3 |
| 34 | `DEVELOPMENT_POOL_ALLOCATE` | `2399b47ba0504396dc4e44b3b69778a79b7a9970a517f8288354ee04135163a4` | `576FCD152B43648EDE8B267B9824E562BD5E814A9EA957F68DD680CBBD58048B` | 69436 | `3344ec2cf1cfd5a38329cc8ad2fb637896d81cd741129afbf194cfe7810b90bc` | 3/3 |
| 35 | `DEVELOPMENT_REWARD_RESERVE` | `0fc0fc5f7e5b4f4eca68c4b6148d6a1b28f1445a6f36a6f0c9ff58ea2758eb90` | `D146B27C791EEC933F954DFD8FC20A62D6F58EAD90CD4332F309937EFE47C382` | 69440 | `4a96e617c098366340fc2594172191ba13ecbb15f9fd976b800fdf2589302f6f` | 3/3 |
| 36 | `DEVELOPMENT_REWARD_PAY_IMMEDIATE` | `ba44ac1ebac5ec7df78bc72ee40330822f7e64b34e3d1147aab225c74676a8e3` | `14654F6CB5E2592DF26C61A240CEF143F017D049DF4C2F9518C094217D43ED10` | 69610 | `784750c7d560db79ef5c084fe14004db98fe6a8bf1a8c9fc630a81817dd3101d` | 3/3 |

The validator status snapshots captured after finality agreed on height
`69690`, chain `chain-Anm7Jk`, `catching_up=false`, the same Block ID and the
same AppHash:

```text
Block ID: 9234580654BFCCEC8DC38FD81CCF587019CBAE80FFCDE8CA0E5DEBE1A1BFD408
AppHash: 927950F9450C8AEC7071CDA85967B612F09D373012F6B94D962ADF460699518E
```

## Wallet And Replay Checks

The canonical Wallet balance was read independently from each validator:

```text
192.168.88.128: 140251200 q_atoms
192.168.88.129: 140251200 q_atoms
192.168.88.130: 140251200 q_atoms
```

The pre-payout quorum read was `138980000 q_atoms`; the delta is exactly
`1271200 q_atoms`. No local balance projection was used as payment authority.

The first long-running attempt exposed a polling bug: after operations 33-35
were verified, the stateful light client was asked to verify operation 33 again
while waiting for operation 36. It correctly rejected verification of the older
height, and the executor reported `AWAITING_VERIFIED_FINALITY` even though no
duplicate operation had been created. The fix makes finality reconciliation
idempotent for an in-memory `FINALIZED` record and adds a non-secret submission
journal containing tx hashes and observed lifecycle state.

After the fix:

- the same batch completed with execution hash
  `sha256:eb27d1a7e1cdd4316c69db7f180000c6c3ab67650eeccc4b98eef72861f2a925`;
- a clean replay returned `FINALIZED` for all four operation IDs;
- the replay produced no new operation ID or transaction identity;
- the primary submission journal retained all four final tx hashes and heights;
- the pending envelope file was cleared after finality.

This proves controlled restart/reconciliation and replay safety for the batch.
The original batch still does not by itself prove maturity-stage payment,
public authority, external validator operation or independent organizational
identity. The additional live gate below records the separately finalized
scope extension and stage-one payment.

## Activation Scope Extension And Maturity Payment

The original activation approval intentionally remains immutable. A separate
future-effective scope extension was finalized before the reserved maturity
payment was submitted:

- Scope extension operation:
  `761c3312c6cf6d1093c38d3ce7bd8c7b1665020a13d4496cb89e3a3763f0a36d`
- Scope extension ID:
  `sha256:61157891a302fff09e9f72440aa5e5014f5558d905024afa9cb0cb22fb4e0ff3`
- Scope extension hash:
  `sha256:63f26d5fd784a16c11ba1fcfc36ba3e0f1fea72892943f2dd8301057eb277f78`
- Scope extension transaction:
  `6D94453A12EE81B85E559B6411490737387308C1D50D1786FEC20BEEDF060AB4`
- Scope extension finality block: `72115`

The exact stage-one payment then referenced the finalized extension operation,
the reserved payment hash and the finalized epoch boundary:

- Payment operation:
  `2727f2ee4206d5066b13603c4178720db16e8df3f58bd96af89da4eee1ee0d89`
- Payment transaction:
  `2199175CFFD6BE0ADCF43DEFD8345BBB4C94A3F6AA6D74A10DB4FFB4342D1602`
- Payment finality block: `72172`
- Payment stage: `MATURITY_STAGE_ONE`
- Amount: `953400 q_atoms = 0.9534 Q`
- Recipient: `wallet-5320047bb01d`
- Source epoch transition operation:
  `892cc574d4b926f8e723a0eed8bd6e33b2e676f7e6d9533881e2b453ba819a95`

Both transactions returned `tx_result.code=0` and were independently found
on all three validator RPCs. The configured finality threshold is `2-of-3`;
the post-finality observations reached `3/3` agreement. At the verification
height `72177`, all validators reported the same block ID, AppHash and
`catching_up=false`.

The canonical Wallet balance after stage-one payment was:

```text
192.168.88.128: 141204600 q_atoms
192.168.88.129: 141204600 q_atoms
192.168.88.130: 141204600 q_atoms
```

The balance delta from the post-immediate-payout value `140251200 q_atoms`
was exactly `953400 q_atoms`. A restart-style replay check restored both
exact envelopes without broadcasting and verified their existing finality at
blocks `72115` and `72172`; no new operation ID or transaction identity was
created. Both pending execution files were removed only after finality.

Stage one was independently finalized and verified. The remaining reserved
stage-two payment was intentionally held until the canonical Epoch Engine
reached its exact maturity boundary; the completion evidence is recorded below.

## Canonical Epoch Advancement And Stage Two

The current chain had reached closing epoch `5`, but no result manifest existed
for that boundary. The operator did not invent roots or pool budgets. Instead,
the controlled-localnet no-work builder derived a manifest from the finalized
epoch-4 anchor, and the same procedure was repeated for epochs `6` through
`12`. Every manifest and transition was signed by the configured 2-of-3
authority policy and finalized through the three validator RPCs.

The final transition was:

- Closing epoch: `12`
- Opening epoch: `13`
- Transition operation:
  `a41b7d26d9e7b4b49ef595eab7e90c03041a5f77da932b50dcd36d102e7c6232`
- Transition finality block: `74953`
- Manifest operation:
  `c739d857c4ea1fcf7e0bbe65e72a48edbcc79797f89a854147437816035dfb64`
- Manifest hash:
  `sha256:522dd3f7b8726ccebfb2c911c6e59fb18928520c3443a8706db19f00ddc49cc2`
- Manifest finality block: `74950`

The complete epoch-5 through epoch-12 artifact chain is retained in the
external evidence archive under `%USERPROFILE%\.aidn\controlled-localnet-20260813\epoch-*`.

The reserved stage-two payment then used the exact finalized opening-epoch-13
transition above:

- Payment operation:
  `83055581cbab0018e3546eae99dd3ad9755263e67a760d3ad53d7f1d5695a7bf`
- Payment transaction:
  `81F29E245B2ED3F5209B8609000E1BEBFBF8A344D33413CE4762823675F3878E`
- Payment finality block: `74988`
- Payment stage: `MATURITY_STAGE_TWO`
- Amount: `953400 q_atoms = 0.9534 Q`
- Recipient: `wallet-5320047bb01d`
- Reward ID:
  `sha256:2613d6a623b1f7f10eb7192dc57037fa592e31c19599ece82a6f2712a62a1624`
- Source epoch transition operation:
  `a41b7d26d9e7b4b49ef595eab7e90c03041a5f77da932b50dcd36d102e7c6232`

The transaction returned `tx_result.code=0` and was found at block `74988` on
all three validator RPCs. The post-stage-two canonical Wallet balance was:

```text
192.168.88.128: 142158000 q_atoms
192.168.88.129: 142158000 q_atoms
192.168.88.130: 142158000 q_atoms
```

The delta from the post-stage-one balance was exactly `953400 q_atoms`. A
restart-style replay through the reusable maturity executor returned
`FINALIZED` with the same operation ID, transaction hash and block height; no
second payment was created and the pending envelope was not replaced.

This completes the controlled-localnet ECO-0007 maturity gate for the Wallet
127 test profile. It remains a controlled testnet result and does not establish
public authority, permissionless validator diversity or external organizational
independence.

## External Evidence

The full disposable evidence archive remains outside the repository at:

```text
%USERPROFILE%\.aidn\controlled-localnet-20260813\contribution-wallet127-epoch1\
```

The archive includes the attestation, batch, preflight, execution result,
submission journal and validator-derived evidence. Private keys are not part of
the archive committed to this repository.
