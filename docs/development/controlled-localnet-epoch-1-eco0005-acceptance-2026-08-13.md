# Controlled Localnet Epoch 1 ECO-0005/ECO-0007 Acceptance

Date: `2026-08-13`

This record captures the first non-zero controlled-localnet Development Pool
allocation derived from the fixed ECO-0005 launch profile. It proves that the
epoch manifest, transition and read-only ECO-0007 preflight agree across the
three configured validators. It does **not** prove that a contributor earned Q
or that a reward was paid.

## Network and Authority

- Network: `aidn-localnet-1`
- Chain: `chain-Anm7Jk`
- Validators: `192.168.88.128`, `192.168.88.129`, `192.168.88.130`
- Authority mode: `THRESHOLD_AUTHORIZED`
- Authority threshold: `2-of-3`
- Protocol authority policy hash:
  `sha256:40c7c0371dca2160043bcd05e37ceb3d8cc8ab33d67bc21b451c95b3e45625a4`
- Epoch schedule hash:
  `sha256:8addacbb10ab523a38993b017716ab64ea29b4c2b7e73bf15536dfda2c63f6c0`

Private authority seed files remain outside the repository. This record
contains no private key material.

## Controlled ECO-0005 Profile

The profile is generated from the checked-in ECO-0005 document and the public
authority policy. It fixes the launch parameters instead of accepting a pool
amount from the command line:

- ECO-0005 source version: `0.3`
- ECO-0005 source hash:
  `sha256:0fac3ccfaaf477f350e61f64b8209b3981b71191045eb08c9cb9eb7e18a9e4c2`
- Base emission: `5000 Q` per epoch
- Development share: `5%`
- Derived `GENERAL_DEVELOPMENT` pool: `250 Q`
- Carryover, grants, returned rewards, maturity reserve and bounty reserve:
  `0 Q`
- Profile hash:
  `sha256:3b6da464c99b18700bdf129d4c5cfee8d4ee78aa72aea5009aff044131a0c9ed`

The profile is a controlled-localnet calibration artifact. A production or
public network must use its own approved emission schedule and policy; this
profile is not a general authorization to create Q.

## Epoch Result Manifest

Epoch `1` closes into opening Epoch `2`.

- Closing height: `66607`
- Manifest hash:
  `sha256:fda4c050abe11d79bb40a7e3c98a8bc3b432ef01c736193013c14616e8e143fe`
- Manifest operation ID:
  `03960002f03db919599b5206649ec8a1eacebfed541f0552f21afa9bbe92dddc`
- Manifest sequence: `27`
- Manifest record digest:
  `sha256:51c47bdc1accfbf2a4f2e60e39cba3e24263e919e2c97d627e7ee604eaf4067b`
- Manifest finality block: `66619`
- Manifest finality block ID:
  `D37397A9DAA7176615DF072431BF4BC1D9E3F8369EC78C5AE22DCE1799D1295E`
- Manifest finality AppHash:
  `4AD5E6AE81D029086480E53CEC7E04F13963BDF15287FE6C8E60F426362141E6`
- Manifest finality quorum: `3/3`

`EPOCH_RESULT_MANIFEST_COMMIT` records the evidence and budget commitment. It
does not by itself credit a contributor Wallet.

## Epoch Transition

The transition was built only from a `READY` quorum report whose three
observations contained the exact finalized manifest reference.

- Operation ID:
  `7af516b4a59d04439bcfc93e761172896df413d709d1923d0bbd3d905bad035f`
- Transaction hash:
  `C932B9463255438AA0FED7B7D5A11493C3F8CDBFB17BBC8889661DB7B3F42F59`
- Quorum report hash:
  `sha256:e2bb6bc89d4b849b5df2e94c6dce2e2af61a2618bea667c3d13dd3ff72195fff`
- Input report hash:
  `sha256:ad874dc576715e418fe936953506b0b4a1adbe8b841407052b535bdd41d295f7`
- Transition sequence: `28`
- Transition record digest:
  `sha256:857dff4d538597c8600f1cb23403fb657238fd4e37d3d9c02d55ed0e3a33ee4d`
- Transition finality block: `66686`
- Transition finality block ID:
  `CBA0B4F9D56C4568477732FBAADBB5361913EDF28D73D74E1D2E5C489575BC4A`
- Transition finality AppHash:
  `AF096DBC74D0724352F41E2FCA33E98DE9E3F2CBF1A01DD2D2D50DA529A98204`
- Transition finality quorum: `3/3`

The transition exposes the following canonical budget:

```text
GENERAL_DEVELOPMENT = 250000000 q_atoms = 250 Q
budget reference = sha256:d263cc8e77567163028a8c910f0d9823cafe8b09233da50899575969c14e6cca
```

This is an available bounded pool budget. It is not a contributor payment and
must not be treated as an automatically earned balance.

## ECO-0007 Activation Preparation

A separate localnet-only activation approval and production profile were
prepared and verified offline:

- Development policy hash:
  `sha256:7a1c02aae505adc4e6a38f7761203721d3dfd2d05deb274ffc867e2ef274ad32`
- Activation ID:
  `sha256:4bcd9bebe1d6fc375d823b4fad07367d3d79423dbff9ae01211b333adbb55b71`
- Activation approval hash:
  `sha256:763013829e936f51eb33eab072edba980366db5ed315389f0f9ee25492db9545`
- Economic scope: `DEVELOPMENT_PAYMENTS`
- Activation authority signatures: `2-of-3`
- Rollout maximum: `250 Q` per epoch, `8` contributions, `50 Q` per contributor
- Production profile ID:
  `sha256:d54891c45ae88928156d52918db780d32c28d33afe29de91aef251ca9eae9ed0`
- Production profile hash:
  `sha256:e8952c81b17dc0a274eeb2504ef79d9ef6c64a70853260ba398c8745600ae6ad`

These are signed planning/authorization artifacts for the controlled
deployment. No separate activation transaction was broadcast by this step.

## ECO-0007 Preflight

The read-only preflight was collected after transition finality and matched on
all three validators:

- Status: `READY`
- Pool: `GENERAL_DEVELOPMENT`
- Budget: `250000000 q_atoms`
- Preflight hash:
  `sha256:e9be982a3c40028919ba9db93878a804c09da13d99e5eb358785c46ef421314f`
- Source transition: `7af516b4a59d04439bcfc93e761172896df413d709d1923d0bbd3d905bad035f`
- Preflight quorum hash:
  `sha256:f49cdffe88cffdb02544de05ee88ce880f875b757623f634e9e4e0e46a6b13a3`
- Agreement: `3/3`

## Remaining Payout Gate

No production reward batch was built or submitted. The following evidence is
still required:

1. A real finalized RFC-0068 Contribution Attestation from an eligible
   repository and protected-branch merge.
2. A verified RFC-0068 Wallet binding or a valid merged-commit Wallet claim.
3. Independent reproduction of the reward calculation and ordered batch.
4. Finality evidence for every calculation, allocation, reserve and payment
   operation.
5. Restart/reconciliation evidence proving that no payment stage can replay.

Creating a synthetic contribution, reusing an operator Wallet as a contributor
claim, or crediting the `250 Q` pool directly would invalidate this acceptance.

## Artifact Location

The live artifacts remain outside the repository under:

```text
%USERPROFILE%\.aidn\controlled-localnet-20260813\epoch-1-eco0005-evidence\
```

The archive contains the quorum report, manifest evidence, signed manifest,
transition envelope, transition finality, ECO-0007 preflight, activation
approval and production profile. Authority seeds are not copied there as
public evidence and are never committed.
