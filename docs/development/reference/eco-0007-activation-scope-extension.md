# ECO-0007 Activation Scope Extension

This runbook defines the controlled procedure for adding a missing economic
operation to an already finalized ECO-0007 activation approval. It exists for
the case where an old reward batch reserved maturity funds but its approval
did not include `DEVELOPMENT_REWARD_PAY_MATURITY`.

## Why this is a separate operation

The original approval is immutable evidence. Editing it would change the
meaning of an already finalized calculation and could make historical
operations unverifiable. The extension therefore:

- references the exact base activation ID, approval hash and policy hash;
- keeps the original authority set, quorum and economic effect profile;
- adds only explicitly named `DEVELOPMENT_*` operation types;
- becomes effective at a declared future epoch;
- has no direct Wallet or Q effect;
- requires the same authority quorum as the base approval.

The extension does not make a maturity payment by itself. A later payment must
reference the finalized extension operation, exact extension record and the
source epoch boundary for the maturity stage.

## Offline build

Extract the public approval from the existing batch into a protected working
directory. Do not copy private authority seeds into the repository or print
them in logs.

```powershell
$batch = Get-Content $env:AIDN_ECO0007_BATCH -Raw | ConvertFrom-Json
$approval = $batch.plan.envelopes[0].payload.activation_approval
$approval | ConvertTo-Json -Depth 40 | Set-Content $env:AIDN_ECO0007_BASE_APPROVAL -Encoding utf8
```

Build the extension with two authority seed files. The command verifies that
each seed matches the public key in the base approval and never emits private
material:

```powershell
uv run python tools/build-development-reward-activation-scope-extension.py `
  --base-approval $env:AIDN_ECO0007_BASE_APPROVAL `
  --signer controlled-localnet-authority-a=$env:AIDN_AUTHORITY_A_SEED `
  --signer controlled-localnet-authority-b=$env:AIDN_AUTHORITY_B_SEED `
  --effective-epoch 5 `
  --base-calculation-operation-id $env:AIDN_ECO0007_CALCULATION_OPERATION_ID `
  --created-at (Get-Date).ToUniversalTime().ToString('o') `
  --output $env:AIDN_ECO0007_SCOPE_EXTENSION_ENVELOPE `
  --extension-output $env:AIDN_ECO0007_SCOPE_EXTENSION
```

Review the printed IDs and hashes, then submit the exact envelope through the
canonical consensus path. The builder is offline-only and deliberately does
not broadcast.

The included executor persists the exact envelope before sending it and waits
for operation-bound finality from the configured RPC quorum:

```powershell
uv run python tools/execute-development-reward-activation-scope-extension.py `
  --envelope $env:AIDN_ECO0007_SCOPE_EXTENSION_ENVELOPE `
  --finality-config $env:AIDN_COMETBFT_FINALITY_CONFIG `
  --execution-output $env:AIDN_ECO0007_SCOPE_EXTENSION_RESULT
```

Once the extension operation is finalized, build the stage-one or stage-two
payment from the original batch. The source transition ID must be the exact
finalized epoch boundary reaching the selected maturity stage:

```powershell
uv run python tools/build-development-reward-maturity-payment.py `
  --batch $env:AIDN_ECO0007_BATCH `
  --extension $env:AIDN_ECO0007_SCOPE_EXTENSION `
  --extension-operation-id $env:AIDN_ECO0007_SCOPE_EXTENSION_OPERATION_ID `
  --stage MATURITY_STAGE_ONE `
  --source-epoch-transition-operation-id $env:AIDN_ECO0007_STAGE_ONE_EPOCH_OPERATION_ID `
  --created-at (Get-Date).ToUniversalTime().ToString('o') `
  --output $env:AIDN_ECO0007_MATURITY_PAYMENT_ENVELOPE
```

The maturity payment envelope is also offline-only. Submit it with the
existing hash-bound reward batch executor or an equivalent canonical
consensus submitter; do not credit the Wallet from the builder or from a
local projection.

## Consensus acceptance

Validators must run a compatible implementation before submission. The
operation is accepted only when:

1. the base calculation is finalized;
2. the extension envelope is valid and future-effective;
3. the extension signatures meet the base quorum;
4. the extension is not a replay or conflicting record;
5. all validators derive the same operation and state root.

After finality, use the returned extension operation ID in the maturity
payment envelope. A payment that omits it, references a non-finalized ID, or
uses a different extension is rejected before any Wallet credit.

## Controlled-localnet gate

The existing Wallet 127 batch was finalized under an older approval that did
not include maturity payment. Its immediate payment and maturity reserve are
valid and unchanged. The stage-one payout remains pending until:

- the new operation is deployed to validators `128`, `129` and `130`;
- the signed scope extension is finalized on all three RPCs;
- the stage-one source epoch boundary is finalized;
- the exact maturity envelope is submitted and reaches quorum finality.

No local balance adjustment, database edit or approval mutation is a valid
substitute for these steps.
