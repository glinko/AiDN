# Controlled Localnet Epoch 0 Manifest and Transition Acceptance

Date: `2026-08-13`

This record captures the first live RFC-0048 manifest and epoch transition on
the controlled AiDN localnet. It is an acceptance artifact for the
no-application-work calibration profile. It is not evidence that a production
development reward has been earned or paid.

## Network and Authority

- Network: `aidn-localnet-1`
- Chain: `chain-Anm7Jk`
- Validators: `192.168.88.128`, `192.168.88.129`, `192.168.88.130`
- Authority mode: `THRESHOLD_AUTHORIZED`
- Authority threshold: `2-of-3`
- Policy hash:
  `sha256:40c7c0371dca2160043bcd05e37ceb3d8cc8ab33d67bc21b451c95b3e45625a4`
- Schedule operation: `7a1729690f1f3dcf3d4b7cf35f784d06beac182d7b7e0fffd6591c5099ce4b82`
- Schedule sequence: `23`
- Schedule record digest:
  `c72fbdcf19f997a6e74180b6208001a3a065706abe940b8d1702aca4a2e3e24b`
- Rebase operation:
  `b634f5023e4d5d16a2287966dca2a9fb3be799b635a9dfeaf9298bf76dc5662c`
- Rebase hash:
  `sha256:76bed841805ec722dff9fb95af1c583be24b70a6a62c4c9cfc21ba4cf36405f8`

Private authority seed files remain outside the repository under the local
operator state directory. This document contains no private key material.

## Epoch Result Manifest

The controlled-localnet no-work evidence builder derived the manifest from the
finalized validator quorum and the finalized schedule/rebase anchors. The
profile is restricted to zero pool budgets and cannot be used to create
production reward evidence.

- Epoch: `0` -> opening epoch `1`
- Closing height: `65813`
- Manifest hash:
  `sha256:0da74acb5b1c32c75e882a277f39dda73d4d636a2accdc127303c03c72862987`
- Evidence bundle hash:
  `sha256:bb7926344c13a60994312278b9041f5d2cc7b684f4c1f6e4adb66ca7fa8e7a9d`
- Operation ID:
  `27e13e40fb91d9c8bfdbb81ccb8b0f932325485f1b8467a52b164ef7e1d04755`
- Finalized sequence: `25`
- Finalized record digest:
  `35ce54830a7f51a8dcf0689121a290f3c1173205eccd5ac3ba6bbe6c39886998`
- Finality block: `65833`
- Finality block ID:
  `72B73B3B2E0AB1F07A66CB303EDE6A03C311550C9229C70DC08858495627B6C7`
- Finality AppHash:
  `A27FCB3F7530F27DB1384C37B9D52CD7DD31E3AA34904E8BE515DD9F0661AE4A`
- Finality quorum: `3/3`

The `GENERAL_DEVELOPMENT` pool budget in this manifest is exactly `0
q_atoms`. No Q transfer or emission side effect is attached to a manifest
commit.

## Epoch Transition

The transition was built only from the `READY` quorum report and included the
finalized manifest and schedule references in both the payload and evidence
references.

- Operation ID:
  `d7d5745290fc92dde5a6b4b2455387b64fbb5dbcf08353a40de25fda7ac722ed`
- Transaction hash:
  `DFF1CC25831AEE6A742C7258B6274888C11DF5068F0212BDF2EA55AB252A9DCE`
- Quorum hash:
  `sha256:8c7be4dcdbaf0f315e9f2b62dacd489d85c93f15c470bf0daf020a9bc088d2a2`
- Input report hash:
  `sha256:64d1b864bcb9f0824edfa51bc86b113d7a958c7832ce6daa89c6c01219dcd54e`
- Finalized sequence: `26`
- Finalized record digest:
  `965ab343d6f44658d56bb515d7e0e149ec27e4a1afd6c4169b336a2f481ee908`
- Finality block: `65932`
- Finality block ID:
  `A0F92B40B1818EB6B368FFAABDC91D1176E6B92EF30485CBECC7605EEA6DECD2`
- Finality AppHash:
  `3A432A49BCD527F86B2FCF5D218260E765F0C69EBE31F001F730D169894C047B`
- Finality quorum: `3/3`

All three validators returned CheckTx code `0` for the same transaction
bytes. The finality observer verified the operation identity, chain ID,
block, AppHash and commit evidence.

## ECO-0007 Gate

The post-transition read-only production preflight agreed across all three
validators:

- Status: `NO_BUDGET`
- Pool: `GENERAL_DEVELOPMENT`
- Budget: `0 q_atoms`
- Pool budget reference:
  `sha256:8398491e729f4cc130a0a138375b0b7c36a7d06af9c1b256423d5f548a0df21d`
- Preflight hash:
  `sha256:6dc4457efa89cc4bd2bf18d5e826302f0f66c51b988a7968a242db91345fedfe`
- Source transition: `d7d5745290fc92dde5a6b4b2455387b64fbb5dbcf08353a40de25fda7ac722ed`
- Source transition sequence: `26`

`NO_BUDGET` is the expected fail-closed result. The production reward batch
builder correctly refuses to create a payout plan when the canonical pool
budget is zero. No contributor, wallet or Q payment was fabricated.

## Local Artifact Archive

The operator archive used for this acceptance is outside the repository:

```text
%USERPROFILE%\.aidn\controlled-localnet-20260813\epoch-0-evidence-20260813\
```

It contains the evidence bundle, manifest, signed manifest envelope, quorum
reports, signed transition envelope and finality outputs. Reproduction uses
the read-only `tools/build-live-epoch-result-manifest.py`, the quorum-bound
transition builder and the two finality-aware submitters. Authority seed files
are never copied into the repository.

## Next Gate

To execute the first real ECO-0007 reward batch, the network must first have:

1. a future-effective, authority-approved non-zero Development Pool allocation;
2. finalized RFC-0068 contribution attestations and verified Wallet bindings;
3. an independently reproduced production profile and reward batch;
4. multi-validator finality evidence for every ordered reward operation; and
5. restart/reconciliation evidence proving that no payment stage can replay.

