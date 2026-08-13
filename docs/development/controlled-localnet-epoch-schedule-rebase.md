# Controlled Localnet Epoch Schedule Rebase

`EPOCH_SCHEDULE_REBASE` is a one-time recovery operation for this controlled
localnet. It exists because the initial schedule was committed after its
declared Epoch 0 start, making the first epoch already expired.

It is not a normal Epoch operation and is not a production shortcut.

## Safety boundary

The operation is accepted only when all of these are true:

- a canonical `EPOCH_SCHEDULE_COMMIT` already exists;
- no `EPOCH_RESULT_MANIFEST_COMMIT` for Epoch 0 exists;
- no `EPOCH_TRANSITION` exists;
- the effective start is after the original schedule start;
- the rebase hash binds the exact original `schedule_hash`;
- the active protocol authority policy verifies its threshold signatures.

Only the `controlled-localnet` recovery profile and the explicit
`CONTROLLED_LOCALNET_LATE_INITIAL_SCHEDULE` reason are supported. A second
rebase is rejected. No Wallet balance, pool budget, reward, or parameter is
changed by the operation.

After finality, the Epoch Engine uses
`effective_epoch_zero_start_time` as the canonical start of Epoch 0 while the
original schedule hash remains unchanged. A later Epoch 0 manifest must bind
that start, the derived scheduled end, and the finalized rebase operation ID,
record digest, and rebase hash as evidence references.

## Authority workflow

Do this only after the same validator build has been deployed and the public
authority policy query agrees on every validator. Keep all temporary artifacts
outside the repository and do not copy authority private keys to the submitter.

1. Query `epoch/schedule` on at least two validators and copy its
   `epoch_schedule.schedule_hash`.
2. Choose an RFC3339 UTC start slightly in the future. It is an explicit
   controlled-localnet recovery decision, not host-clock inference.
3. Create `/secure/aidn/epoch-0.rebase.json`:

```json
{
  "schema_version": "aidn.epoch-schedule-rebase.v1",
  "schedule_hash": "sha256:<canonical schedule hash>",
  "effective_epoch_zero_start_time": "2030-01-01T00:00:00Z",
  "reason_code": "CONTROLLED_LOCALNET_LATE_INITIAL_SCHEDULE",
  "recovery_profile": "controlled-localnet"
}
```

4. Prepare one unsigned artifact:

```text
uv run python tools/prepare-authorized-epoch-schedule-rebase.py \
  --policy /secure/aidn/protocol-authority.json \
  --rebase /secure/aidn/epoch-0.rebase.json \
  --created-at 2030-01-01T00:00:00Z \
  --output /secure/aidn/epoch-0.rebase.unsigned.json
```

5. Each authority signs the exact unsigned artifact independently:

```text
uv run python tools/sign-authorized-epoch-schedule-rebase.py \
  --unsigned-envelope /secure/aidn/epoch-0.rebase.unsigned.json \
  --policy /secure/aidn/protocol-authority.json \
  --authority-id authority-1 \
  --private-key /secure/keys/authority-1.seed \
  --output /secure/aidn/epoch-0.authority-1.sig.json
```

6. Combine at least the configured threshold with
`tools/combine-authorized-epoch-schedule-rebase.py`. Review the envelope and
submit it through the ordinary CometBFT transaction path. The repository does
not provide an auto-submit command for recovery operations deliberately.
7. Wait for multi-RPC finality, then verify `epoch/schedule-rebase` returns the
same operation, sequence, record digest, and rebase hash from every validator.

Only then collect the first Epoch 0 evidence and construct its manifest. The
manifest cannot use the former late start time.
